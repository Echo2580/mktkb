
"""P2-T206-LIVE 定向回归：真实 live 入口的接线与 fail-closed（零真实调用）。

覆盖（对应本包 G1–G6 的可验证部分）：
1. 环境缺项/OCR 关闭/模型非白名单 -> **发送前**拒绝；
2. 计划项解析与尝试配额：未知项/配额用尽都不发送；
3. 真实门缺 GO / 缺预算修订时，CLI --mode live 在构造适配器之前拒绝，出站 0；
4. fake transport + 真实 provider + 真实 P2Gate（tmp 固定路径副本）：每次底层尝试都有
   reservation、成本中心正确、账本计数与回执一致、产物网络分解一致；
5. 缺 chat usage -> usage_evidence_missing（不伪造花费、保守留账）；
6. OCR 走真实 TencentOCRClient（MockTransport）并按页固定价结算；
7. 零付费轮次（合法拒答）走 close_unused：保守留账但**不**停止后续；
8. R1-F1：query_expansion 走自己的 expand-* 计划项（独立 reservation/usage/成本中心）；
9. R1-F2：计划项配额按**真实 HTTP 批**计（embed batch 拆分 → 逐批 take，用尽即发送前停）；
10. R1-F6：live 的 retrieved 来自产品 answer 请求实际交给模型的证据集合（零额外调用），
    citation 落在候选内才 pass，候选缺失仍 fail-closed。

零真实调用：所有出站都被 httpx.MockTransport 接住，外层 socket 闸门断言外部尝试 = 0。
账本/预算/GO 全是 tmp_path 副本（monkeypatch 固定路径常量），不碰仓库共享文件。
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb import live_authorization
from mktkb.evaluation import p2_authorization as p2a
from mktkb.evaluation import p2_contracts as c
from mktkb.evaluation import p2_live
from mktkb.evaluation.dataset import CaseSpec, validate_case
from mktkb.evaluation.p2_contracts import P2RunPlan
from mktkb.evaluation.product_adapter import (
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
)
from mktkb.providers.types import CompletionOutput, OCRInput

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D09 = FIXTURES / "normal" / "D09_物料领用通知.png"
B0 = ROOT / "fixtures" / "evaluation" / "b0.jsonl"

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
CENTERS = {"answer_retrieval": 9.0, "ocr": 6.0, "judge": 3.0, "independent": 2.0}
LIVE_ENV_OVERRIDES = {
    "chat_api_key": "unit-test-chat-key-not-a-secret",
    "chat_base_url": "https://api.deepseek.com",
    "chat_model": "deepseek-flash",
    "dashscope_api_key": "unit-test-dashscope-key-not-a-secret",
    "dashscope_base_url": "https://dashscope.aliyuncs.com",
    "ocr_secret_id": "unit-test-ocr-id-not-a-secret",
    "ocr_secret_key": "unit-test-ocr-key-not-a-secret",
    "ocr_region": "ap-guangzhou",
}


# --------------------------------------------------------------------------- #
# 计划 / GO / 预算（全部 tmp 副本，等价 T201 口径）
# --------------------------------------------------------------------------- #


def _profiles() -> dict[str, dict]:
    return {
        "embedding": {
            "kind": "embedding",
            "model": "text-embedding-v4",
            "provider": "bailian",
            "host": "dashscope.aliyuncs.com",
            "region": "cn-beijing",
            "pricing_source": "official-list-price/bailian-text-embedding-v4-v1",
            "unit_price_per_million_cny": 0.5,
            "total_tokens_cap": 4096,
        },
        "rerank": {
            "kind": "rerank",
            "model": "gte-rerank-v2",
            "provider": "bailian",
            "host": "dashscope.aliyuncs.com",
            "region": "cn-beijing",
            "pricing_source": "official-list-price/bailian-gte-rerank-v2-v1",
            "unit_price_per_million_cny": 0.8,
            "total_tokens_cap": 6000,
        },
        "chat": {
            "kind": "chat",
            "model": "deepseek-flash",
            "provider": "deepseek",
            "host": "api.deepseek.com",
            "region": "global",
            "pricing_source": "official-list-price/deepseek-chat-cache-miss-v1",
            "input_price_per_million_cny": 2.0,
            "output_price_per_million_cny": 8.0,
            "prompt_tokens_cap": 6144,
            "completion_tokens_cap": 800,
        },
        "ocr": {
            "kind": "ocr",
            "model": "GeneralAccurateOCR",
            "provider": "tencent",
            "host": "ocr.tencentcloudapi.com",
            "region": "ap-guangzhou",
            "pricing_source": "official-list-price/tencent-ocr-postpaid-highest-v1",
            "price_cny_per_page": 0.5,
            "pages_per_request": 1,
        },
    }


def _item(item_id: str, operation: str, case_id: str, *, requests: int = 1, page: int = 0) -> dict:
    profiles = _profiles()
    kind = c.OPERATION_KIND[operation]
    profile = profiles[kind]
    expected = {"chat": 0.004, "embedding": 0.0003, "rerank": 0.001, "ocr": 0.5}[kind]
    return {
        "item_id": item_id,
        "operation": operation,
        "cost_center": c.OPERATION_COST_CENTER[operation],
        "case_id": case_id,
        "turn": 1,
        "page": page,
        "requests": requests,
        "price_profile": copy.deepcopy(profile),
        "expected_success_cny": expected,
    }


def _plan_dict() -> dict:
    return {
        "schema_version": c.P2_RUN_PLAN_SCHEMA_VERSION,
        "plan_id": "P2-LIVE-UNIT-20261111",
        "plan_version": "v0.1",
        "mode": "end_to_end",
        "stage": "P2-LIVE",
        "created_utc": "2026-11-11T00:00:00+08:00",
        "project_total_limit_cny": TOTAL_LIMIT_CNY,
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "max_requests": 1000,
        "cost_centers_cny": dict(CENTERS),
        "items": [
            _item("ingest-index", "index_embedding", "INGEST", requests=8),
            _item("embed-Q01-t1", "query_embedding", "Q01"),
            _item("rerank-Q01-t1", "rerank", "Q01"),
            _item("expand-Q01-t1", "query_expansion", "Q01"),
            _item("answer-Q01-t1", "answer", "Q01"),
            _item("embed-Q25-t1", "query_embedding", "Q25"),
            _item("rerank-Q25-t1", "rerank", "Q25"),
            _item("expand-Q25-t1", "query_expansion", "Q25"),
            _item("answer-Q25-t1", "answer", "Q25"),
            _item("ocr-Q01-p1", "ocr", "Q01", page=1),
        ],
    }


def _plan() -> P2RunPlan:
    return P2RunPlan.from_dict(_plan_dict())


def _write_ledger(path: Path) -> None:
    path.write_text(
        json.dumps(
            {"event": "historical_import", "accounted_cny": 2.0, "source": "unit-test"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_budget(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "limit_cny": TOTAL_LIMIT_CNY,
                "historical_conservative_accounted_cny": 2.0,
                "stages": {"S2-DEV": 18.0, "P2-LIVE": STAGE_LIMIT_CNY},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_go(path: Path, *, ledger: Path, plan: P2RunPlan) -> None:
    path.write_text(
        json.dumps(
            {
                "document": "P2-LIVE-GO",
                "schema_version": "p2-live-go/v0.1",
                "stage": "P2-LIVE",
                "authorization": "UNIT-TEST-MOCK-GO（零真实调用）",
                "issued_by": "pytest",
                "nonce": "unit-test-live-nonce-0123456789",
                "issued_utc": "2026-11-19T00:00:00+00:00",
                "expires_utc": "2026-11-20T00:00:00+00:00",
                "budget_ledger_path": str(ledger),
                "budget_ledger_sha256": live_authorization.historical_prefix_sha256(ledger),
                "budget_total_limit_cny": TOTAL_LIMIT_CNY,
                "scope": {
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.plan_sha256,
                    "operations": list(plan.operations),
                    "cost_centers_cny": dict(CENTERS),
                    "stage_limits_cny": {"P2-LIVE": STAGE_LIMIT_CNY},
                    "max_requests": 1000,
                    "max_request_cny": 0.5,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def live_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    ledger = tmp_path / "live-ledger.jsonl"
    budget = tmp_path / "budget.json"
    go = tmp_path / "P2-LIVE-GO.json"
    plan = _plan()
    _write_ledger(ledger)
    _write_budget(budget)
    _write_go(go, ledger=ledger, plan=plan)
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", ledger)
    monkeypatch.setattr(p2a, "P2_BUDGET_PATH", budget)
    monkeypatch.setattr(p2a, "P2_GO_PATH", go)
    monkeypatch.setenv(live_authorization.TOTAL_LIMIT_ENV, str(TOTAL_LIMIT_CNY))
    return SimpleNamespace(ledger=ledger, budget=budget, go=go, plan=plan, root=tmp_path)


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _reservations(path: Path) -> list[dict]:
    return [row for row in _events(path) if row.get("event") == "reserved"]


def _results(path: Path) -> list[dict]:
    return [row for row in _events(path) if row.get("event") == "result"]


# --------------------------------------------------------------------------- #
# fake transports（真实 provider 编解码，不出网）
# --------------------------------------------------------------------------- #


class _UsageChatBackend(MockChatBackend):
    """MockChatBackend + 官方 chat usage 的 cache 拆分字段（J1 结算要求）。"""

    def _completion(self, request: httpx.Request, content: str, *, call: int) -> httpx.Response:
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        payload["usage"] = {
            "prompt_tokens": 64,
            "completion_tokens": 32,
            "total_tokens": 96,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 64,
        }
        return httpx.Response(200, json=payload, request=request)


class _NoUsageChatBackend(MockChatBackend):
    """故意不返回 usage：必须 fail closed（不得伪造花费）。"""

    def _completion(self, request: httpx.Request, content: str, *, call: int) -> httpx.Response:
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        payload.pop("usage", None)
        return httpx.Response(200, json=payload, request=request)


def _embedding_transport(calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        texts = list(body.get("input") or ())
        dims = int(body.get("dimensions") or 1024)
        calls.append({"texts": len(texts), "dimensions": dims})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": index, "embedding": [0.01] * dims}
                    for index in range(len(texts))
                ],
                "usage": {"total_tokens": 40},
                "id": "emb-" + str(len(calls)),
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _rerank_transport(calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        docs = list((body.get("input") or {}).get("documents") or ())
        calls.append({"documents": len(docs)})
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": index, "relevance_score": 0.9 - index * 0.01}
                        for index in range(len(docs))
                    ]
                },
                "usage": {"total_tokens": 80},
                "request_id": "rerank-" + str(len(calls)),
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _ocr_transport(calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"action": request.headers.get("X-TC-Action")})
        return httpx.Response(
            200,
            json={
                "Response": {
                    "TextDetections": [
                        {
                            "DetectedText": "领取活动物料需先填写物料领用单",
                            "Confidence": 99,
                            "Polygon": [
                                {"X": 10, "Y": 10},
                                {"X": 200, "Y": 10},
                                {"X": 200, "Y": 40},
                                {"X": 10, "Y": 40},
                            ],
                        }
                    ],
                    "RequestId": "ocr-unit-1",
                }
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _dataset(case_id: str = "Q01") -> P2RunDataset:
    rows = [json.loads(line) for line in B0.read_text(encoding="utf-8").splitlines() if line.strip()]
    case = CaseSpec.from_dict(next(row for row in rows if row["case_id"] == case_id))
    validate_case(case)
    return P2RunDataset(
        visibility="public",
        cases=(case,),
        identity={
            "dataset_version": "p2-live-unit-v1",
            "label_version": "b0-2026-11-04",
            "suite": "b0",
            "manifest_sha256": "a" * 64,
            "case_count": 1,
        },
    )


def _transports(chat: MockChatBackend) -> dict[str, Any]:
    return {
        "chat": chat.transport,
        "embedding": _embedding_transport([]),
        "rerank": _rerank_transport([]),
        "ocr": _ocr_transport([]),
    }


def _run(
    env: SimpleNamespace,
    tmp_path: Path,
    *,
    chat: MockChatBackend | None = None,
    ingest=D01,
    case_id: str = "Q01",
    gate_config: Any = None,
):
    plan = env.plan
    gate = p2_live.open_live_gate(plan, run_id="p2-live-unit", now=NOW)
    ingest_plan = (
        None
        if ingest is None
        else P2IngestPlan(sources=(IngestSource(path=ingest),), label="t206-live")
    )

    async def go():
        return await p2_live.run_live_p2(
            plan,
            run_id="p2-live-unit",
            out_dir=tmp_path / "run",
            dataset=_dataset(case_id),
            ingest_plan=ingest_plan,
            gate=gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=LIVE_ENV_OVERRIDES,
            transports=_transports(chat or _UsageChatBackend()),
            now=NOW,
            gate_config=gate_config,
        )

    result, build = asyncio.run(go())
    return result, build, gate


# --------------------------------------------------------------------------- #
# 1. 环境 fail closed
# --------------------------------------------------------------------------- #


def _valid_env() -> dict[str, str]:
    return {
        "MKTKB_MODEL_API_KEY": "placeholder-not-a-secret",
        "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com",
        "MKTKB_MODEL_NAME": "deepseek-flash",
        "DASHSCOPE_API_KEY": "placeholder-not-a-secret",
        "MKTKB_OCR_SECRET_ID": "placeholder-not-a-secret",
        "MKTKB_OCR_SECRET_KEY": "placeholder-not-a-secret",
        "MKTKB_OCR_DISABLED": "0",
    }


def test_live_env_requires_every_named_variable() -> None:
    for name in p2_live.REQUIRED_ENV_VARS:
        env = _valid_env()
        env.pop(name)
        with pytest.raises(p2_live.P2LiveConfigError) as excinfo:
            p2_live.load_live_env(env)
        assert excinfo.value.code == "live_env_missing"
        assert name in excinfo.value.detail
    full = p2_live.load_live_env(_valid_env())
    assert full.chat_model == "deepseek-flash"
    assert "placeholder" not in repr(full)


def test_live_env_refuses_ocr_disabled_and_foreign_model() -> None:
    env = _valid_env()
    with pytest.raises(p2_live.P2LiveConfigError) as excinfo:
        p2_live.load_live_env({**env, "MKTKB_OCR_DISABLED": "1"})
    assert excinfo.value.code == "live_ocr_disabled"
    with pytest.raises(p2_live.P2LiveConfigError) as excinfo:
        p2_live.load_live_env({**env, "MKTKB_MODEL_NAME": "gpt-4o"})
    assert excinfo.value.code == "live_chat_model_not_authorized"


def test_plan_index_and_attempt_budget_fail_closed(live_env: SimpleNamespace) -> None:
    plan = live_env.plan
    index = p2_live.PlanIndex(plan)
    budget = p2_live.AttemptBudget(plan)
    assert index.index_embedding_item().item_id == "ingest-index"
    assert index.turn_item("query_embedding", "Q01", 1).item_id == "embed-Q01-t1"
    assert index.next_ocr_item(0).item_id == "ocr-Q01-p1"
    assert index.ocr_count == 1
    with pytest.raises(p2_live.P2LiveRefused) as excinfo:
        index.next_ocr_item(1)
    assert excinfo.value.code == "attempt_item_exhausted"

    for _ in range(8):
        budget.take("ingest-index")
    with pytest.raises(p2_live.P2LiveRefused) as excinfo:
        budget.take("ingest-index")
    assert excinfo.value.code == "attempt_quota_exhausted"
    with pytest.raises(p2_live.P2LiveRefused) as excinfo:
        budget.take("judge-Q01")
    assert excinfo.value.code == "attempt_item_unknown"


# --------------------------------------------------------------------------- #
# 2. 真实门 / CLI --mode live：缺 GO 时发送前拒绝
# --------------------------------------------------------------------------- #


def test_cli_live_refuses_without_go_before_building_adapter(
    live_env: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F3：**先真正写计划**，才会走到 live/GO 分支；拒绝码必须是稳定码而不是异常类名。"""
    from mktkb.evaluation import cli

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan_dict_for_file(live_env.plan)), encoding="utf-8")
    # 环境齐备（值不是凭据）→ 拒绝必须发生在**门**上：固定路径 GO 不存在 ⇒ path_missing。
    for name, value in _valid_env().items():
        monkeypatch.setenv(name, value)
    absent = tmp_path / "no-go.json"
    monkeypatch.setattr(p2a, "P2_GO_PATH", absent)
    out_dir = tmp_path / "cli-out"
    exit_code = cli.main(
        [
            "p2-run",
            "--plan",
            str(plan_path),
            "--out",
            str(out_dir),
            "--mode",
            "live",
            "--run-id",
            "p2-live-cli-unit",
            "--ingest",
            str(D01),
        ]
    )
    assert exit_code == cli.EXIT_DATA
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["error_code"] == "path_missing", payload
    assert payload["requests_sent"] == 0
    assert not (out_dir / "data").exists(), "拒绝必须发生在构造隔离应用之前"
    assert not (out_dir / "p2-run").exists()

    # 反例：计划文件不存在时是稳定码 plan_unreadable（不再用 FileNotFoundError 混过 exit 3）。
    assert (
        cli.main(
            [
                "p2-run",
                "--plan",
                str(tmp_path / "absent-plan.json"),
                "--out",
                str(out_dir),
                "--mode",
                "live",
                "--run-id",
                "p2-live-cli-unit",
                "--ingest",
                str(D01),
            ]
        )
        == cli.EXIT_DATA
    )
    assert "plan_unreadable" in capsys.readouterr().err
    assert not (out_dir / "data").exists()


def test_cli_live_requires_explicit_run_id(live_env: SimpleNamespace, tmp_path: Path) -> None:
    from mktkb.evaluation import cli

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan_dict_for_file(live_env.plan)), encoding="utf-8")
    with pytest.raises(cli.CliError):
        cli._cmd_p2_run(
            SimpleNamespace(
                plan=str(plan_path),
                snapshot=None,
                out=str(tmp_path / "out"),
                cases=None,
                visibility="public",
                holdout_manifest=None,
                ingest=[str(D01)],
                dataset_version="p2-live-unit-v1",
                label_version="b0-2026-11-04",
                mode="live",
                run_id=None,
            )
        )


def _plan_dict_for_file(plan: P2RunPlan) -> dict:  # noqa: ARG001 - 只用同一份计划字典
    # CLI 只从文件读计划；写回同一份 _plan_dict()（不依赖内部私有字段）。
    return _plan_dict()


# --------------------------------------------------------------------------- #
# 3. live 端到端（fake transport + 真实 gate）
# --------------------------------------------------------------------------- #


def test_live_run_records_every_attempt_with_centers_and_zero_outbound(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    # fake chat 返回冻结的期望值（产品提交回合需要"记录型答案"），接线才是本用例的被测对象。
    chat = _UsageChatBackend(
        behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),)
    )
    result, build, gate = _run(live_env, tmp_path, chat=chat)

    assert result.production_ready is True
    assert result.stop_code is None, result.stop_code
    assert result.status == "succeeded"
    assert chat.call_count == 1
    assert result.requests_sent == 1
    # answer 轮按真实 usage 结算（prompt 64 × 2/M + completion 32 × 8/M）。
    assert result.by_center_cny["answer_retrieval"] == pytest.approx(0.000384)

    # 逐次回执：只有真实发送才留 settle；成本中心逐项来自计划项。
    receipts = build.wiring.receipt_payload()
    settled = [row for row in receipts if row["phase"] == "settle"]
    operations = {row["operation"] for row in settled}
    assert "index_embedding" in operations
    assert "query_embedding" in operations
    assert all(row["cost_center"] == c.OPERATION_COST_CENTER[row["operation"]] for row in settled)
    assert all(row["reservation_id"] for row in settled)
    assert len({row["reservation_id"] for row in settled}) == len(settled)

    # 账本：每次预留都有 result；总计数 = answer 轮 + 从属尝试。
    reservations = _reservations(live_env.ledger)
    results = _results(live_env.ledger)
    assert len(reservations) == len(results)
    assert len(reservations) == len({row["reservation_id"] for row in reservations})
    assert all(row.get("cost_center") for row in reservations), "不得出现无归属预留"
    assert len(reservations) == result.requests_reserved + len(
        {row["reservation_id"] for row in settled if row["operation"] != "answer"}
    )

    # 出站 = 0（MockTransport 接住），但确实发生了 provider 调用。
    providers = build.adapter.provider_calls()
    assert providers["outbound_network"] == 0
    assert providers["network"]["mock_intercepted"] >= 5
    assert providers["chat"]["calls"] == 1
    assert providers["embedding"]["calls"] >= 1
    assert providers["live"]["attempts"]["receipts"] == len(receipts)

    summary = json.loads((build.adapter.paths.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["execution"] == "live"
    assert summary["attempts"]["available"] is True
    assert summary["attempts"]["gate_reserved"] == len(reservations)
    assert summary["attempts"]["expected_reservations"] == len(reservations)
    center_total = sum(summary["attempts"]["by_center_cny"].values())
    assert center_total == pytest.approx(summary["attempts"]["center_stage_total_cny"])
    combined = center_total + sum(summary["attempts"]["answer_by_center_cny"].values())
    assert combined == pytest.approx(summary["attempts"]["center_total_with_answers_cny"])
    assert summary["network"]["available"] is True
    assert summary["network"]["outbound_attempts"] == 0


def test_live_missing_usage_stops_without_fabricating_cost(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    result, build, _gate = _run(
        live_env,
        tmp_path,
        chat=_NoUsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),)),
    )

    assert result.status == "aborted"
    assert result.stop_code == "usage_evidence_missing"
    results = _results(live_env.ledger)
    answer_rows = [row for row in results if row.get("kind") == "chat"]
    assert answer_rows, "answer 预留必须留下结果回执（保守占用）"
    for row in answer_rows:
        assert row["status"] == "failed"
        assert row["error_code"] == "usage_evidence_missing"
        assert row["conservative_charge_cny"] == pytest.approx(0.018688)
    summary = json.loads((build.adapter.paths.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["requests"]["settled_failure"] == 1
    assert summary["failure"]["stage"] == "gate_settle"


# --------------------------------------------------------------------------- #
# 4. OCR 真实传输 + 逐页预留
# --------------------------------------------------------------------------- #


def test_gated_ocr_gateway_uses_real_client_and_reserves_fixed_price(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    from mktkb.providers.tencent_ocr import TencentOCRClient

    plan = live_env.plan
    gate = p2_live.open_live_gate(plan, run_id="p2-live-ocr", now=NOW)
    env = p2_live.load_live_env({}, overrides=LIVE_ENV_OVERRIDES)
    wiring = p2_live.LiveWiring(
        env=env,
        plan=plan,
        run_id="p2-live-ocr",
        gate=gate,
        ledger=p2_live.GateAttemptLedger(gate, plan, on_receipt=None),
        attempt_budget=p2_live.AttemptBudget(plan),
        plan_index=p2_live.PlanIndex(plan),
    )
    wiring.ledger._on_receipt = wiring.receipts.append  # noqa: SLF001 - 测试内接线
    calls: list[dict] = []
    client = TencentOCRClient(
        secret_id="unit-test-ocr-id",
        secret_key="unit-test-ocr-key",
        region="ap-guangzhou",
        transport=_ocr_transport(calls),
    )
    gateway = p2_live.GatedOcrGateway(client, wiring=wiring)
    page = OCRInput(content=D09.read_bytes(), mime_type="image/png", page=1)
    first = gateway.recognize(page, mode="text")
    assert first.text == "领取活动物料需先填写物料领用单"
    # 真实客户端会把供应商 RequestId 换成稳定摘要（不回显原文），只需证明拿到了身份。
    assert str(first.provider_request_id or "").startswith("sha256:")
    assert calls == [{"action": "GeneralAccurateOCR"}]

    # 第二页没有计划项：发送前拒绝，不再出站。
    with pytest.raises(p2_live.P2LiveRefused) as excinfo:
        gateway.recognize(page, mode="text")
    assert excinfo.value.code == "attempt_item_exhausted"
    assert len(calls) == 1

    reservations = [row for row in _reservations(live_env.ledger) if row.get("kind") == "ocr"]
    assert len(reservations) == 1
    assert reservations[0]["cost_center"] == "ocr"
    results = [row for row in _results(live_env.ledger) if row.get("kind") == "ocr"]
    assert results[0]["conservative_charge_cny"] == pytest.approx(0.5)
    assert [row["operation"] for row in wiring.receipt_payload()] == ["ocr", "ocr"]


# --------------------------------------------------------------------------- #
# 5. 零付费轮次：close_unused 不停止后续
# --------------------------------------------------------------------------- #


def test_close_unused_keeps_conservative_charge_and_does_not_stop(
    live_env: SimpleNamespace,
) -> None:
    plan = live_env.plan
    gate = p2_live.open_live_gate(plan, run_id="p2-live-unused", now=NOW)
    first = gate.begin("answer-Q01-t1")
    gate.confirm_before_send(first)
    gate.close_unused(first, reason="not_found")
    # 门没有被停止：下一笔仍然可以预留（合法拒答不补调用、不中断 run）。
    second = gate.begin_attempt("embed-Q01-t1")
    gate.confirm_before_send(second)
    gate.settle_success(second, evidence=_embedding_evidence(second))
    results = _results(live_env.ledger)
    unused = [row for row in results if str(row.get("error_code") or "").startswith("P2_NO_PAID_ATTEMPT")]
    assert len(unused) == 1
    assert unused[0]["status"] == "failed"
    assert unused[0]["conservative_charge_cny"] == pytest.approx(0.018688)
    assert gate.stopped_reason is None


def _embedding_evidence(ticket: Any) -> Any:
    from mktkb.rag.controlled_usage import build_total_evidence
    from mktkb.rag.settlement_policy import build_policy

    return build_total_evidence(
        build_policy("embedding", model="text-embedding-v4"),
        request_sha256=ticket.reservation.request_sha256,
        usage={"total_tokens": 40},
        http_status=200,
        output_valid=True,
    )


# --------------------------------------------------------------------------- #
# 6. R1-F1：query_expansion 记到 expand-*（计划项 = 资金身份，不再顶账 answer-*）
# --------------------------------------------------------------------------- #


def test_live_query_expansion_is_booked_to_expand_item(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    # 空库 + 正文型问题 = 产品**真的**会调模型的 query_expansion 路径（不是评测器自己造的）。
    chat = _UsageChatBackend()
    result, build, _gate = _run(live_env, tmp_path, chat=chat, case_id="Q25", ingest=None)

    assert chat.counts_by_purpose() == {"query_expansion": 1}
    assert result.status == "succeeded", result.stop_code
    assert result.stop_code is None

    receipts = build.wiring.receipt_payload()
    expansion = [row for row in receipts if row["operation"] == "query_expansion"]
    assert [row["phase"] for row in expansion] == ["reserve", "settle"], expansion
    reserve, settle = expansion
    assert reserve["item_id"] == settle["item_id"] == "expand-Q25-t1"
    assert reserve["cost_center"] == c.OPERATION_COST_CENTER["query_expansion"]
    assert reserve["reservation_id"] and reserve["reservation_id"] == settle["reservation_id"]
    assert settle["status"] == "succeeded"
    # 按真实 usage 结算（64 prompt × 2/M + 32 completion × 8/M），不是空占上界。
    assert settle["charged_cny"] == pytest.approx(0.000384)

    # 计划项 = 资金身份：expansion 只消耗 expand-*，answer-* 没有被顶账。
    assert build.wiring.attempt_budget.used("expand-Q25-t1") == 1
    assert build.wiring.attempt_budget.used("answer-Q25-t1") == 0
    assert build.wiring.as_dict()["calls"]["expansion"] == 1
    assert build.wiring.as_dict()["calls"]["chat"] == 0

    chat_reservations = [
        row for row in _reservations(live_env.ledger) if row.get("kind") == "chat"
    ]
    assert len(chat_reservations) == 2, "answer 轮 + expand 各一笔独立预留"
    assert settle["reservation_id"] in {row["reservation_id"] for row in chat_reservations}
    # 账本行（reserved）也带成本中心：金额归属可从账本独立重算，不靠回执自报。
    ledger_center = {
        row["reservation_id"]: row.get("cost_center") for row in chat_reservations
    }
    assert ledger_center[settle["reservation_id"]] == "answer_retrieval"
    results = _results(live_env.ledger)
    assert len(results) == 2
    unused = [
        row
        for row in results
        if str(row.get("error_code") or "").startswith("P2_NO_PAID_ATTEMPT")
    ]
    assert len(unused) == 1, "没有发生 answer chat 的那一轮走 close_unused（不是记成成功）"
    assert unused[0]["status"] == "failed"
    expansion_results = [
        row for row in results if row["reservation_id"] == settle["reservation_id"]
    ]
    assert len(expansion_results) == 1
    assert expansion_results[0]["status"] == "succeeded"


# --------------------------------------------------------------------------- #
# 7. R1-F2：计划项配额按真实 HTTP 批计（embed batch 拆分 → 逐批 take）
# --------------------------------------------------------------------------- #


def _plan_with_ingest_requests(requests: int) -> P2RunPlan:
    payload = _plan_dict()
    for item in payload["items"]:
        if item["operation"] == "index_embedding":
            item["requests"] = requests
    return P2RunPlan.from_dict(payload)


def _embedding_gated(
    env: SimpleNamespace,
    tmp_path: Path,
    plan: P2RunPlan,
    *,
    run_id: str,
) -> tuple[Any, Any, list[dict]]:
    from mktkb.rag import RagConfig
    from mktkb.rag.providers import BailianEmbeddingProvider
    from mktkb.rag.settlement_policy import build_policy

    config = RagConfig(
        provider_mode="live",
        data_dir=tmp_path / "data",
        business_date=None,
        top_k=8,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
        embedding_base_url="https://dashscope.aliyuncs.com",
        embedding_api_key="unit-test-dashscope-key-not-a-secret",
        embedding_batch_size=5,
        embedding_timeout_seconds=30.0,
        max_request_cny=0.5,
        max_retries=0,
        require_zero_retries=True,
    )
    gate = p2_live.open_live_gate(plan, run_id=run_id, now=NOW)
    budget = p2_live.AttemptBudget(plan)
    receipts: list = []
    ledger = p2_live.GateAttemptLedger(
        gate, plan, on_receipt=receipts.append, attempt_budget=budget
    )
    wiring = p2_live.LiveWiring(
        env=env,
        plan=plan,
        run_id=run_id,
        gate=gate,
        ledger=ledger,
        attempt_budget=budget,
        plan_index=p2_live.PlanIndex(plan),
        receipts=receipts,
    )
    calls: list[dict] = []
    inner = BailianEmbeddingProvider(
        config,
        budget=ledger,
        require_budget=True,
        settlement_policy=build_policy("embedding", model=config.embedding_model),
        transport=_embedding_transport(calls),
    )
    return p2_live.GatedEmbeddingProvider(inner, wiring=wiring), wiring, calls


def test_embedding_quota_counts_http_batches_not_embed_calls(
    live_env: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mktkb.rag.errors import BudgetLedgerInvalid

    env = p2_live.load_live_env({}, overrides=LIVE_ENV_OVERRIDES)
    texts = [f"第{index}条待索引文本" for index in range(12)]
    embed_reservations = [
        row for row in _reservations(live_env.ledger) if row.get("kind") == "embedding"
    ]

    gated, wiring, calls = _embedding_gated(
        env, tmp_path, live_env.plan, run_id="p2-live-batch-ok"
    )
    response = gated.embed(texts)
    assert len(response.vectors) == len(texts)
    # 12 条 / batch 5 = 3 次真实 POST：配额与账本 reservation 都是 3（不是 1 次 embed()）。
    assert len(calls) == 3
    assert wiring.attempt_budget.used("ingest-index") == 3
    assert wiring.ledger.attempts("index_embedding") == 3
    assert gated.as_dict()["calls"] == 3
    assert gated.as_dict()["embed_calls"] == 1
    after_ok = [
        row for row in _reservations(live_env.ledger) if row.get("kind") == "embedding"
    ]
    assert len(after_ok) - len(embed_reservations) == 3
    assert len([row for row in _results(live_env.ledger) if row.get("kind") == "embedding"]) == 3

    # 计划只给 2 次（item.requests=2）：第 3 批在**发送前**被配额拦住，不偷偷多发。
    tight = _plan_with_ingest_requests(2)
    _write_go(tmp_path / "go-tight.json", ledger=live_env.ledger, plan=tight)
    monkeypatch.setattr(p2a, "P2_GO_PATH", tmp_path / "go-tight.json")
    gated_tight, tight_wiring, tight_calls = _embedding_gated(
        env, tmp_path, tight, run_id="p2-live-batch-tight"
    )
    with pytest.raises(BudgetLedgerInvalid):
        gated_tight.embed(texts)
    assert len(tight_calls) == 2, "被配额拒绝的那一批没有发出请求"
    assert tight_wiring.attempt_budget.used("ingest-index") == 2
    assert tight_wiring.ledger.attempts("index_embedding") == 2
    assert gated_tight.as_dict()["calls"] == 2


# --------------------------------------------------------------------------- #
# 8. R1-F6：live 的 retrieved 来自产品实际交给模型的证据集合（零额外调用）
# --------------------------------------------------------------------------- #


def test_live_retrieved_from_product_evidence_and_gate_fails_closed(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    from mktkb.evaluation.p2_scoring import (
        EXECUTION_MODE_LIVE,
        build_gate_rows,
        build_gate_run,
        evaluate_p2_hard_gates,
        load_p2_gate_config,
        score_public_case,
    )

    config = load_p2_gate_config()
    chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, _gate = _run(live_env, tmp_path, chat=chat, gate_config=config)
    assert result.status == "succeeded", result.stop_code

    run_dir = build.adapter.paths.run_dir
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    case_rows = [
        json.loads(line)
        for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    product = case_rows[0]["turns"][0]["product"]
    assert product["kind"] == "answer"
    cited = {str(item["source_id"]) for item in product["sources"]}
    candidates = {unit for item in product["retrieved"] for unit in item["unit_ids"]}
    assert cited and cited <= candidates, (cited, candidates)
    # 候选**逐条等于**模型实际拿到的证据 id（不是引用的副本，也不是重放出来的另一套）。
    assert chat.calls[0]["purpose"] == "answer"
    assert len(product["retrieved"]) == chat.calls[0]["evidence"] >= 1
    assert candidates == {str(item) for item in chat.calls[0]["evidence_ids"]}
    for item in product["retrieved"]:
        assert item["unit_key"] and item["locator"], item
    assert build.wiring.as_dict()["calls"]["chat"] == 1

    cases = _dataset().cases
    scored = [
        score_public_case(
            case,
            row,
            document_codes={"D01_物品位置表.xlsx": "D01"},
            allowed_doc_codes={"D01"},
            execution_mode=EXECUTION_MODE_LIVE,
        )
        for case, row in zip(cases, case_rows)
    ]
    rows = build_gate_rows(cases, scored)
    hard = evaluate_p2_hard_gates(
        build_gate_run(run_dir=run_dir, manifest=manifest, cases=cases, rows=rows, summary=summary),
        config=config,
        require_trace=False,
    )
    assert hard.gate_status["citation_required"] == "pass", hard.to_dict()

    # 缺候选仍 fail-closed：只删掉 retrieved（不重跑产品）就必须 fail。
    tampered: list[dict] = []
    for row in rows:
        copied = dict(row)
        outcome = dict(row.get("outcome") or {})
        if outcome.get("kind") == "answer":
            outcome["retrieved"] = []
        copied["outcome"] = outcome
        tampered.append(copied)
    hard_missing = evaluate_p2_hard_gates(
        build_gate_run(
            run_dir=run_dir, manifest=manifest, cases=cases, rows=tampered, summary=summary
        ),
        config=config,
        require_trace=False,
    )
    assert hard_missing.gate_status["citation_required"] == "fail", hard_missing.to_dict()
    assert "citation_required" in hard_missing.hard_failures


# --------------------------------------------------------------------------- #
# 11. T207-FIX-B：output_valid 三判据、结算金额与两个口径（零真实调用）
# --------------------------------------------------------------------------- #


def test_chat_output_validity_requires_stop_nonempty_and_parsed_structure() -> None:
    """三判据缺一即无效（不猜、不补造）；全成立才 output_valid=True。"""
    good = CompletionOutput(text="位置：B区1号货架第二层", source_ids=("unit-1",))
    assert p2_live.chat_output_validity(good) == {
        "finish_reason": "stop",
        "content_present": True,
        "content_parsed": True,
        "output_valid": True,
    }
    # 空内容：不成立。
    empty = p2_live.chat_output_validity(CompletionOutput(text="   ", source_ids=("unit-1",)))
    assert empty["content_present"] is False
    assert empty["content_parsed"] is False
    assert empty["output_valid"] is False
    # 非 stop：输出对象自带该字段时按其值判定（不信"拿到了对象"）。
    truncated = p2_live.chat_output_validity(
        SimpleNamespace(finish_reason="length", text="位置", source_ids=("unit-1",))
    )
    assert truncated["finish_reason"] == "length"
    assert truncated["output_valid"] is False
    # JSON 未解析：没有 answer/terms 解析结构（例如把正文原样当文本返回的网关）。
    raw_text = p2_live.chat_output_validity(SimpleNamespace(text="{\"answer\": \"x\"}"))
    assert raw_text["content_present"] is True
    assert raw_text["content_parsed"] is False
    assert raw_text["output_valid"] is False
    # query_expansion 用自己的 schema（terms）判定。
    expansion = p2_live.chat_output_validity(
        CompletionOutput(text="{\"terms\": [\"价目\"]}", query_terms=("价目",)),
        purpose="query_expansion",
    )
    assert expansion["output_valid"] is True
    assert (
        p2_live.chat_output_validity(SimpleNamespace(text="正文"), purpose="query_expansion")[
            "output_valid"
        ]
        is False
    )


def test_chat_usage_evidence_settles_by_usage_only_for_valid_output() -> None:
    """合法输出 -> 按 usage 结算 0.000384（<< 上界 0.018688）；空内容/非 stop/缺判据 ->
    J1 拒绝并保守上界（修复前这三类被硬编码成"有效内容"，等于把无效输出按真账入账）。"""
    from mktkb.rag.settlement_policy import KIND_CHAT, build_policy, evaluate_settlement

    policy = build_policy(KIND_CHAT, model="deepseek-flash")
    usage = {
        "prompt_tokens": 64,
        "completion_tokens": 32,
        "total_tokens": 96,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 64,
    }
    reserved = {
        "kind": KIND_CHAT,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "request_sha256": "a" * 64,
    }

    def decide(**kwargs: Any):
        evidence = p2_live.chat_usage_evidence(
            request_sha256="a" * 64, usage=usage, **kwargs
        )
        assert evidence is not None
        return evidence, evaluate_settlement(
            policy, reserved=reserved, evidence=evidence, reserve_cny=0.018688
        )

    valid_evidence, valid = decide(
        finish_reason="stop", content_present=True, content_parsed=True
    )
    assert valid_evidence.output_valid is True
    assert valid.accepted is True
    assert float(valid.charge_cny) == pytest.approx(0.000384)
    assert float(valid.charge_cny) < 0.018688

    empty_evidence, empty = decide(
        finish_reason="stop", content_present=False, content_parsed=False
    )
    assert empty_evidence.output_valid is False
    assert empty.accepted is False and empty.reason == "content_incomplete"
    assert float(empty.charge_cny) == pytest.approx(0.018688)

    _not_stop_evidence, not_stop = decide(
        finish_reason="length", content_present=True, content_parsed=True
    )
    assert not_stop.accepted is False and not_stop.reason == "finish_reason_not_stop"
    assert float(not_stop.charge_cny) == pytest.approx(0.018688)

    unparsed_evidence, unparsed = decide(
        finish_reason="stop", content_present=True, content_parsed=False
    )
    assert unparsed_evidence.output_valid is False
    assert unparsed.accepted is False and unparsed.reason == "content_not_parsed"

    # 调用方不给判据（缺省）-> fail closed，绝不为了"结算成功"恒置 True。
    default_evidence, default = decide()
    assert default_evidence.output_valid is False
    assert default.accepted is False
    assert float(default.charge_cny) == pytest.approx(0.018688)

    # usage 缺字段：连证据都造不出来（None）-> runner 侧 usage_evidence_missing。
    assert (
        p2_live.chat_usage_evidence(
            request_sha256="a" * 64,
            usage={},
            finish_reason="stop",
            content_present=True,
            content_parsed=True,
        )
        is None
    )


def test_live_run_separates_answer_scope_from_all_attempts_and_marks_output_valid(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    """A/B/C 三件事的联合回归（零真实调用）。"""
    chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, _gate = _run(live_env, tmp_path, chat=chat)

    run_dir = build.adapter.paths.run_dir
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    reservations = _reservations(live_env.ledger)
    results = _results(live_env.ledger)

    # A 返工②：answer 单侧与全量尝试两个口径都写出来，且 attempts_reserved 就是门计数。
    assert summary["requests"]["scope"] == "answer_turns"
    assert summary["attempts"]["scope"] == "all_attempts"
    assert result.requests_reserved == summary["requests"]["reserved"] == 1
    assert result.attempts_scope == "all_attempts"
    assert result.attempts_reserved == len(reservations)
    assert result.attempts_reserved == summary["attempts"]["gate_reserved"]
    assert run_result["attempts_reserved"] == result.attempts_reserved
    assert result.attempts_reserved > result.requests_reserved
    assert sum(run_result["attempts_by_operation"].values()) == result.attempts_reserved
    assert run_result["attempts_by_operation"]["answer"] == result.requests_reserved
    assert sum(result.attempts_by_center_cny.values()) == pytest.approx(
        summary["attempts"]["center_total_with_answers_cny"]
    )

    # B 返工③：保守占用与账本逐笔一致；三段互不冒充。
    ledger_held = round(sum(float(row["conservative_charge_cny"]) for row in results), 8)
    assert summary["requests"]["conservative_held_cny"] == pytest.approx(ledger_held)
    assert summary["requests"]["unpaid_rounds"] == 0
    assert summary["requests"]["failed_rounds"] == summary["requests"]["settled_failure"] == 0
    assert summary["requests"]["provider_billed_cny"] == pytest.approx(
        summary["requests"]["conservative_held_cny"]
    )

    # C 返工⑤：合法 usage 的 chat 轮按 usage 结算，账本证据块 settlement.output_valid=true。
    chat_results = [row for row in results if row.get("kind") == "chat"]
    assert len(chat_results) == 1, chat_results
    chat_result = chat_results[0]
    assert chat_result["status"] == "succeeded"
    assert chat_result["settlement"]["output_valid"] is True
    assert chat_result["settlement"]["content_complete"] is True
    assert chat_result["settlement"]["content_parse_ok"] is True
    assert chat_result["conservative_charge_cny"] == pytest.approx(0.000384)
    assert chat_result["conservative_charge_cny"] < 0.018688


# --------------------------------------------------------------------------- #
# 12. T207-FIX-B-R1：J1 拒绝轮的保守占用必须进 summary（C1，真实 P2Gate）
# --------------------------------------------------------------------------- #


def test_live_j1_rejected_settle_keeps_conservative_held_cny(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    """端到端复现 C1：answer 轮 usage total 对不上 -> J1 拒绝结算（gate_error）。

    账本已经按该笔上界写了一条保守 result；summary.conservative_held_cny 必须等于
    本 run 账本 result 保守合计（含这一笔），且 rejected_rounds=1、不算成功/失败结算。
    """

    class _TotalMismatchChat(_UsageChatBackend):
        """官方 usage 自相矛盾（total_tokens=999 != prompt+completion）：J1 必须拒绝。"""

        def _completion(self, request: httpx.Request, content: str, *, call: int) -> httpx.Response:
            response = super()._completion(request, content, call=call)
            payload = json.loads(response.content.decode("utf-8"))
            payload["usage"]["total_tokens"] = 999
            return httpx.Response(200, json=payload, request=request)

    chat = _TotalMismatchChat(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, _gate = _run(live_env, tmp_path, chat=chat)

    assert result.status == "aborted"
    assert result.stop_code == "gate_error"
    assert result.requests_sent == 0
    # answer 单侧旧键含该笔上界（不是 0，也不是成功结算额）。
    assert result.settled_cny == pytest.approx(0.018688)
    assert result.by_center_cny["answer_retrieval"] == pytest.approx(0.018688)

    run_dir = build.adapter.paths.run_dir
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    requests = summary["requests"]
    results = _results(live_env.ledger)
    ledger_held = round(
        sum(float(row.get("conservative_charge_cny") or 0.0) for row in results), 8
    )
    answer_rows = [row for row in results if row.get("kind") == "chat"]
    assert len(answer_rows) == 1
    assert answer_rows[0]["status"] == "unknown"
    assert str(answer_rows[0]["error_code"]).startswith("SETTLEMENT_NOT_RELEASABLE:total_mismatch")
    assert answer_rows[0]["conservative_charge_cny"] == pytest.approx(0.018688)

    assert requests["rejected_rounds"] == 1
    assert requests["settled_success"] == requests["settled_failure"] == 0
    assert requests["failed_rounds"] == 0
    assert requests["unpaid_rounds"] == 0
    # C1：summary 的保守占用必须等于账本 result 保守合计（含被拒的这一笔）。
    assert requests["conservative_held_cny"] == pytest.approx(ledger_held)
    assert requests["conservative_held_cny"] == pytest.approx(0.018812)
    assert requests["provider_billed_cny"] == pytest.approx(ledger_held - 0.018688)
    assert requests["billed_cny"] == 0.0, "Mock 链零出站：不冒充真实出网计费"
    assert run_result["settled_cny"] == pytest.approx(0.018688)
    assert run_result["by_center_cny"]["answer_retrieval"] == pytest.approx(0.018688)
    assert sum(result.attempts_by_center_cny.values()) == pytest.approx(ledger_held)
    assert summary["failure"]["stage"] == "gate_settle"
    assert summary["network"]["outbound_attempts"] == 0


# --------------------------------------------------------------------------- #
# 11. T207-FIX-A §F7：每次 run 新开一扇门（同一计划/GO 可连续独立 run）
# --------------------------------------------------------------------------- #


def _dataset_empty() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-live-unit-empty",
            "label_version": "b0-2026-11-04",
            "suite": "b0",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )


def _run_once(env: SimpleNamespace, out_dir: Path, run_id: str, *, gate=None):
    """计划/GO/账本都不变，只换 run_id、输出目录与**新开的门**。"""
    plan = env.plan
    live_gate = gate or p2_live.open_live_gate(plan, run_id=run_id, now=NOW)
    chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))

    async def go():
        return await p2_live.run_live_p2(
            plan,
            run_id=run_id,
            out_dir=out_dir,
            dataset=_dataset("Q01"),
            ingest_plan=P2IngestPlan(sources=(IngestSource(path=D01),), label="t207-f7"),
            gate=live_gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=LIVE_ENV_OVERRIDES,
            transports=_transports(chat),
            now=NOW,
        )

    result, build = asyncio.run(go())
    return result, build, live_gate


def test_two_runs_with_fresh_gates_keep_per_run_accounting(live_env: SimpleNamespace, tmp_path: Path) -> None:
    first, build_first, gate_first = _run_once(live_env, tmp_path / "run-1", "p2-f7-r1")
    assert first.status == "succeeded", (first.status, first.stop_code)
    assert first.stop_code is None
    assert first.requests_sent == 1
    summary_first = json.loads((build_first.adapter.paths.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_first["attempts"]["gate_reserved"] == summary_first["attempts"]["expected_reservations"]
    used_after_first = int(gate_first.authorization.requests_used) + len(_reservations(live_env.ledger))
    reserved_first = len(_reservations(live_env.ledger))
    assert reserved_first > 0

    # 第二扇门：同一份计划、同一份 GO、同一只账本，但那扇门是**新开**的。
    second, build_second, gate_second = _run_once(live_env, tmp_path / "run-2", "p2-f7-r2")
    assert second.status == "succeeded", (second.status, second.stop_code)
    assert second.stop_code is None
    assert second.requests_sent == 1
    summary_second = json.loads((build_second.adapter.paths.run_dir / "summary.json").read_text(encoding="utf-8"))
    # 关键：第二 run 的 gate 累计计数只等于**本 run**的期望（不是两 run 之和）。
    assert summary_second["attempts"]["expected_reservations"] == summary_first["attempts"]["expected_reservations"]
    assert summary_second["attempts"]["gate_reserved"] == summary_second["attempts"]["expected_reservations"]
    assert gate_second.authorization.requests_used == reserved_first, "新门看到的是已有账本，但计数从本 run 起算"
    assert int(gate_second.authorization.requests_used) > int(gate_first.authorization.requests_used)
    reservations = _reservations(live_env.ledger)
    assert len(reservations) == reserved_first * 2
    assert all(row.get("cost_center") for row in reservations)
    assert all(row.get("run_id") in {"p2-f7-r1", "p2-f7-r2"} for row in reservations)
    assert {row.get("run_id") for row in reservations} == {"p2-f7-r1", "p2-f7-r2"}
    _ = used_after_first


def test_reusing_one_gate_for_a_second_run_is_refused_by_accounting(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    """反证：同一扇门跑第二次 → attempt_accounting_mismatch（口径不放宽，只能换门）。"""
    first, _build, gate_first = _run_once(live_env, tmp_path / "run-1", "p2-f7-reuse-r1")
    assert first.status == "succeeded", (first.status, first.stop_code)
    reserved_first = len(_reservations(live_env.ledger))

    # 同一扇门 + 空题集（不会发送任何请求）：计数口径立刻不自洽。
    async def go():
        return await p2_live.run_live_p2(
            live_env.plan,
            run_id="p2-f7-reuse-r2",
            out_dir=tmp_path / "run-2",
            dataset=_dataset_empty(),
            ingest_plan=None,
            gate=gate_first,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=LIVE_ENV_OVERRIDES,
            transports=_transports(_UsageChatBackend()),
            now=NOW,
        )

    second, _build2 = asyncio.run(go())
    assert second.status != "succeeded"
    assert second.stop_code == "attempt_accounting_mismatch", second.stop_code
    assert second.requests_sent == 0
    assert len(_reservations(live_env.ledger)) == reserved_first, "反证路径不得再写账本"


# --------------------------------------------------------------------------- #
# 12. T207-FIX-A：live 执行包装器（显式 --env-file，只报变量名、绝不回显值）
# --------------------------------------------------------------------------- #


def _wrapper():
    import importlib.util

    path = ROOT / "tools" / "p2_live_execute.py"
    spec = importlib.util.spec_from_file_location("p2_live_execute", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclass 解析字符串注解时要能按 __module__ 在 sys.modules 里找到本模块。
    sys.modules["p2_live_execute"] = module
    spec.loader.exec_module(module)
    return module


def _env_file(path: Path, *, secret: str = "S3CRET-VALUE-never-printed", extra: str = "") -> Path:
    lines = [
        f"MKTKB_MODEL_API_KEY={secret}",
        "MKTKB_MODEL_BASE_URL=https://api.deepseek.com",
        "MKTKB_MODEL_NAME=deepseek-flash",
        f"DASHSCOPE_API_KEY={secret}-dashscope",
        f"MKTKB_OCR_SECRET_ID={secret}-ocr-id",
        f"MKTKB_OCR_SECRET_KEY={secret}-ocr-key",
        "MKTKB_OCR_DISABLED=0",
        "MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0",
    ]
    if extra:
        lines.append(extra)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_wrapper_reads_explicit_env_file_and_never_prints_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wrapper = _wrapper()
    secret = "S3CRET-VALUE-never-printed"
    env_file = _env_file(tmp_path / "p2-live.env", secret=secret)
    code = wrapper.main(["--env-file", str(env_file), "--check-only"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True and payload["values_printed"] is False
    assert "MKTKB_MODEL_API_KEY" in payload["injected"]
    assert secret not in captured.out and secret not in captured.err
    assert env_file.name in captured.out

    # 显式要求才读：不传 --env-file 时 argparse 直接拒绝（默认不读 .env）。
    with pytest.raises(SystemExit) as excinfo:
        wrapper.main(["--check-only"])
    assert int(excinfo.value.code or 0) == 2

    # 名为 .env 的文件一律拒绝（避免"顺手从工作区 .env 取凭据"）。
    dotenv = _env_file(tmp_path / ".env", secret=secret)
    code = wrapper.main(["--env-file", str(dotenv), "--check-only"])
    captured = capsys.readouterr()
    assert code == 3
    assert json.loads(captured.out)["error_code"] == "env_file_forbidden"
    assert secret not in captured.out and secret not in captured.err


def test_wrapper_fails_closed_on_missing_or_foreign_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wrapper = _wrapper()
    secret = "S3CRET-VALUE-never-printed"
    missing = tmp_path / "missing.env"
    missing.write_text(
        f"MKTKB_MODEL_API_KEY={secret}\nMKTKB_MODEL_BASE_URL=https://api.deepseek.com\n",
        encoding="utf-8",
    )
    code = wrapper.main(["--env-file", str(missing), "--check-only"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 3 and payload["error_code"] == "env_required_missing"
    assert "MKTKB_OCR_SECRET_ID" in payload["detail"]
    assert secret not in captured.out and secret not in captured.err

    foreign = _env_file(tmp_path / "foreign.env", secret=secret, extra=f"AWS_SECRET_ACCESS_KEY={secret}")
    code = wrapper.main(["--env-file", str(foreign), "--check-only"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 3 and payload["error_code"] == "env_name_not_allowed"
    assert "AWS_SECRET_ACCESS_KEY" in payload["detail"]
    assert secret not in captured.out and secret not in captured.err


def test_wrapper_injects_into_child_process_env_only(tmp_path: Path) -> None:
    wrapper = _wrapper()
    secret = "S3CRET-VALUE-never-printed"
    env_file = _env_file(tmp_path / "p2-live.env", secret=secret)
    env = wrapper.build_child_env(env_file, base_env={})
    assert env["MKTKB_MODEL_API_KEY"] == secret
    assert "AWS_SECRET_ACCESS_KEY" not in env
    # 父进程环境不变（只影响子进程）。
    assert "MKTKB_MODEL_API_KEY" not in __import__("os").environ or __import__("os").environ["MKTKB_MODEL_API_KEY"] != secret
    probe = (
        "import os,sys;"
        "sys.exit(0 if os.environ.get('MKTKB_MODEL_API_KEY') == %r else 9)" % secret
    )
    completed = wrapper.run_command([sys.executable, "-c", probe], env=env)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert secret not in (completed.stdout or "") and secret not in (completed.stderr or "")

    # 走真实子进程路径（bogus plan）：子进程失败，但输出里只有它自己的错误，不含凭据值。
    code, stdout, stderr = wrapper.run_cli(
        env_file, ["p2-run", "--plan", str(tmp_path / "no-such-plan.json"), "--out", str(tmp_path / "out")]
    )
    assert code != 0
    assert "plan_unreadable" in stderr
    assert secret not in stdout and secret not in stderr


# --------------------------------------------------------------------------- #
# 13. T207-FIX-LIVEGATE：live 门的 OCR 要求随计划（无 OCR 项的计划不再被无条件挡下）
# --------------------------------------------------------------------------- #


def _plan_dict_without_ocr(*, plan_id: str = "P2-LIVEGATE-H2LIKE-20261111") -> dict:
    """H2 型计划：与公开型计划同一套 item 口径，但**没有** ocr 项（无 OCR 页）。"""
    document = _plan_dict()
    document["plan_id"] = plan_id
    document["items"] = [item for item in document["items"] if item["operation"] != "ocr"]
    return document


def _rewrite_scope_operations(go: Path, *, drop: str = "", add: str = "") -> None:
    """就地改 GO 的 scope.operations（只动这一个字段，其他绑定值保持原样）。"""
    document = json.loads(go.read_text(encoding="utf-8"))
    operations = {op for op in document["scope"]["operations"] if op != drop}
    if add:
        operations.add(add)
    document["scope"]["operations"] = sorted(operations)
    go.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_live_gate_still_requires_ocr_for_plan_with_ocr_items(
    live_env: SimpleNamespace,
) -> None:
    """回归：公开矩阵计划含 OCR 项 -> 证仍要求 ocr（GO 不覆盖就在发放前拒）。

    默认计划有 12 页 OCR 项，因此 ``required_live_operations`` 仍把 ocr 算进必需集；
    GO 少了 ocr 时由 ``authorize_p2`` 以 go_operation_unauthorized 拒绝（GO 必须先覆盖计划
    操作），门自己那道 live_operation_not_authorized 也不因"计划里有 OCR"而放松。
    """
    plan = live_env.plan
    assert "ocr" in plan.operations
    assert p2_live.required_live_operations(plan) == (
        "answer",
        "index_embedding",
        "ocr",
        "query_embedding",
        "rerank",
    )

    _rewrite_scope_operations(live_env.go, drop="ocr")
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        p2_live.open_live_gate(plan, run_id="p2-livegate-ocr-required", now=NOW)
    assert excinfo.value.reason == "go_operation_unauthorized"


def test_live_gate_opens_for_plan_without_ocr_items(
    live_env: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2 型计划（无 OCR 项、其余核心齐）在 GO 覆盖计划操作时开门。

    复现 T207 H2 的真实形态：GO 的 scope.operations 仍是六项**超集**（含 ocr），而
    ``authorization.operations`` 取自**计划**（p2_authorization.py:644）= 五项（无 ocr）。
    修正前这里会以 live_operation_not_authorized: [ocr] 拒绝本次 live 执行。
    """
    plan = P2RunPlan.from_dict(_plan_dict_without_ocr())
    assert "ocr" not in plan.operations
    assert p2_live.required_live_operations(plan) == (
        "answer",
        "index_embedding",
        "query_embedding",
        "rerank",
    )

    go = tmp_path / "P2-LIVE-GO-h2like.json"
    _write_go(go, ledger=live_env.ledger, plan=plan)
    # 真实 H2 GO 是照旧模板签的：scope 里仍写着 ocr（超集不是授权来源，只是上界声明）。
    _rewrite_scope_operations(go, add="ocr")
    monkeypatch.setattr(p2a, "P2_GO_PATH", go)

    gate = p2_live.open_live_gate(plan, run_id="p2-livegate-h2like", now=NOW)
    assert gate.authorization.production_ready is True
    assert gate.authorization.operations == (
        "answer",
        "index_embedding",
        "query_embedding",
        "query_expansion",
        "rerank",
    )
    assert "ocr" not in gate.authorization.operations


@pytest.mark.parametrize("operation", ["answer", "index_embedding", "query_embedding", "rerank"])
def test_live_gate_refuses_plan_missing_a_core_operation(
    live_env: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """四个核心操作恒需：计划缺任一（GO 照计划签发）-> live_operation_not_authorized。"""
    document = _plan_dict_without_ocr(plan_id="P2-LIVEGATE-NO-" + operation)
    document["items"] = [item for item in document["items"] if item["operation"] != operation]
    plan = P2RunPlan.from_dict(document)
    assert operation not in plan.operations

    go = tmp_path / ("P2-LIVE-GO-no-" + operation + ".json")
    _write_go(go, ledger=live_env.ledger, plan=plan)
    monkeypatch.setattr(p2a, "P2_GO_PATH", go)

    with pytest.raises(p2_live.P2LiveConfigError) as excinfo:
        p2_live.open_live_gate(plan, run_id="p2-livegate-core", now=NOW)
    assert excinfo.value.code == "live_operation_not_authorized"
    assert operation in excinfo.value.detail


def test_live_gate_change_is_not_a_bypass_for_go_plan_consistency(
    live_env: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不作任何放行：authorization.operations 与 plan.operations 的一致性仍由 authorize 保证。

    本包只把 ocr 从"无条件要求"改成"随计划要求"，没有放宽 GO 与计划的一致性：
    GO 少写计划里的任一操作 -> go_operation_unauthorized；GO 写未注册操作 ->
    go_operation_invalid。两者都在构造适配器之前拒绝。
    """
    plan = P2RunPlan.from_dict(_plan_dict_without_ocr(plan_id="P2-LIVEGATE-CONSISTENCY"))
    go = tmp_path / "P2-LIVE-GO-consistency.json"
    _write_go(go, ledger=live_env.ledger, plan=plan)
    monkeypatch.setattr(p2a, "P2_GO_PATH", go)

    _rewrite_scope_operations(go, drop="rerank")
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        p2_live.open_live_gate(plan, run_id="p2-livegate-consistency", now=NOW)
    assert excinfo.value.reason == "go_operation_unauthorized"

    _write_go(go, ledger=live_env.ledger, plan=plan)
    _rewrite_scope_operations(go, add="replay")
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        p2_live.open_live_gate(plan, run_id="p2-livegate-consistency-2", now=NOW)
    assert excinfo.value.reason == "go_operation_invalid"


# --------------------------------------------------------------------------- #
# 14. T207-FIX-H2PURGE：CLI live 必须把 holdout 的 purge 开关转发给 run_live_p2
# --------------------------------------------------------------------------- #


class _StopBuild(RuntimeError):
    """在装配处截停：只验证参数是否传到，不构造适配器、不发送。"""


def _p2_case() -> CaseSpec:
    rows = [json.loads(line) for line in B0.read_text(encoding="utf-8").splitlines() if line.strip()]
    case = CaseSpec.from_dict(next(row for row in rows if row["case_id"] == "Q01"))
    validate_case(case)
    return case


def _holdout_p2_dataset() -> SimpleNamespace:
    """与 T202 P2Dataset 同形的 holdout 视图（只供 CLI 身份装配，不读封存文件）。"""
    cases = (_p2_case(),)
    manifest = SimpleNamespace(
        dataset_version="p2-holdout-unit-v1",
        label_version="holdout-unit-v1",
        suite="h2",
        manifest_sha256="b" * 64,
        case_count=len(cases),
        strata={},
        turn_stats={"total_turns": len(cases), "max_turns_per_case": 1},
    )
    return SimpleNamespace(visibility="holdout", manifest=manifest, cases=cases)


def _cli_stub_result(out_dir: Path) -> tuple[SimpleNamespace, SimpleNamespace]:
    result = SimpleNamespace(
        status="succeeded",
        stop_code=None,
        requests_planned=0,
        requests_sent=0,
        production_ready=False,
        by_center_cny={},
    )
    build = SimpleNamespace(
        wiring=SimpleNamespace(receipts=[]),
        adapter=SimpleNamespace(paths=SimpleNamespace(run_dir=out_dir)),
    )
    return result, build


def _cli_args(tmp_path: Path, *, visibility: str) -> SimpleNamespace:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan_dict_for_file(_plan())), encoding="utf-8")
    return SimpleNamespace(
        plan=str(plan_path),
        snapshot=None,
        out=str(tmp_path / "cli-out"),
        cases=None,
        visibility=visibility,
        holdout_manifest=str(tmp_path / "holdout-manifest.json"),
        ingest=[str(D01)] if visibility == "holdout" else None,
        ingest_plan=None,
        dataset_version="p2-holdout-unit-v1",
        label_version="holdout-unit-v1",
        mode="live",
        run_id="p2-h2purge-cli",
    )


def _spy_cli_live(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    from mktkb.evaluation import p2_dataset

    captured: list[dict[str, Any]] = []

    async def fake_run(_plan, **kwargs):
        captured.append(kwargs)
        return _cli_stub_result(tmp_path / "stub-run")

    monkeypatch.setattr(p2_live, "run_live_p2", fake_run)
    monkeypatch.setattr(
        p2_dataset, "load_p2_dataset", lambda _path, *, visibility: _holdout_p2_dataset()
    )
    return captured


def test_cli_holdout_live_passes_purge_true_to_run_live_p2(
    live_env: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """H2 回归点：--visibility holdout --mode live 必须以 purge=True 装配。

    修复前这里到 run_live_p2 的 kwargs 里没有该开关，适配器默认 False，
    p2_runner 在首个发送之前以 holdout_requires_purge 拒绝（零发送，但也零产出）。
    """
    from mktkb.evaluation import cli

    captured = _spy_cli_live(monkeypatch, tmp_path)
    exit_code = cli._cmd_p2_run(_cli_args(tmp_path, visibility="holdout"))

    assert exit_code == 0
    assert len(captured) == 1
    kwargs = captured[0]
    assert kwargs["purge_traces_on_close"] is True
    assert kwargs["dataset"].visibility == "holdout"
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["mode"] == "live" and payload["execution"] == "live"


def test_cli_public_live_keeps_purge_false(
    live_env: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """public 行为不变：live 仍以 purge=False 构造（不该顺手把公开 run 也清了）。"""
    from mktkb.evaluation import cli

    captured = _spy_cli_live(monkeypatch, tmp_path)
    exit_code = cli._cmd_p2_run(_cli_args(tmp_path, visibility="public"))

    assert exit_code == 0
    assert len(captured) == 1
    kwargs = captured[0]
    assert kwargs["purge_traces_on_close"] is False
    assert kwargs["dataset"].visibility == "public"
    capsys.readouterr()


@pytest.mark.parametrize("flag", [True, False, None])
def test_run_live_p2_forwards_purge_flag_to_adapter_builder(
    live_env: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: bool | None,
) -> None:
    """run_live_p2 -> build_live_adapter 的形参对齐（True/False/缺省 False）。

    缺省仍是 False：runner 的 holdout_requires_purge 拒绝规则因此保持可达（负例见
    test_p2_runner.py 的 test_holdout_without_purge_is_refused_before_any_work）。
    """
    seen: dict[str, Any] = {}

    def fake_build(_plan, **kwargs):
        seen.update(kwargs)
        raise _StopBuild

    monkeypatch.setattr(p2_live, "build_live_adapter", fake_build)
    gate = p2_live.open_live_gate(live_env.plan, run_id="p2-h2purge-build", now=NOW)
    extra = {} if flag is None else {"purge_traces_on_close": flag}

    async def go():
        return await p2_live.run_live_p2(
            live_env.plan,
            run_id="p2-h2purge-build",
            out_dir=tmp_path / "run",
            dataset=_dataset(),
            gate=gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=LIVE_ENV_OVERRIDES,
            now=NOW,
            **extra,
        )

    with pytest.raises(_StopBuild):
        asyncio.run(go())
    assert seen["purge_traces_on_close"] is bool(flag)


# --------------------------------------------------------------------------- #
# 9. FU-1：live（隔离 Mock 传输）走同一通用入口时也绑定实际 RAG 索引版本
# --------------------------------------------------------------------------- #


def test_live_mode_binds_actual_rag_index_revision(
    live_env: SimpleNamespace, tmp_path: Path
) -> None:
    """FU-1：live 分支的 ``binding_components`` 取 RAG 索引版本，且与 manifest 一致。

    用隔离 Mock 传输（零真实外发、零费用）：先灌历史版、再发同一资料的**新版本**，
    让"产品资料发布版本"与"RAG 索引版本"分开；绑定必须跟 RAG 走（不是产品计数）。
    """
    from mktkb.evaluation.p2_scoring import load_p2_gate_config

    config = load_p2_gate_config()
    chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    plan = live_env.plan
    gate = p2_live.open_live_gate(plan, run_id="p2-live-unit", now=NOW)
    ingest = P2IngestPlan(
        sources=(
            IngestSource(
                path=FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx", name=D01.name
            ),
            IngestSource(path=D01, document_ref=D01.name),
        ),
        label="fu1-live-publish-version-change",
    )

    async def go():
        return await p2_live.run_live_p2(
            plan,
            run_id="p2-live-unit",
            out_dir=tmp_path / "run",
            dataset=_dataset("Q01"),
            ingest_plan=ingest,
            gate=gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=LIVE_ENV_OVERRIDES,
            transports=_transports(chat),
            now=NOW,
            gate_config=config,
        )

    result, build = asyncio.run(go())
    assert result.status == "succeeded", result.stop_code
    # 隔离传输：发生了 provider 调用，但出站 0（MockTransport 接住）。
    assert build.adapter.provider_calls()["outbound_network"] == 0

    # 两套计数器确实分开，否则这条用例没有证伪力。
    product_revision = build.adapter.product_revision()
    index_revision = build.adapter.index_status()["index_revision"]
    assert product_revision == 2, product_revision
    assert index_revision != product_revision, (product_revision, index_revision)

    manifest = json.loads(
        (build.adapter.paths.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["index_revision"] == manifest["binding"]["index_revision"] == index_revision
    assert manifest["binding"]["complete"] is True
    # 绑定同源：适配器组件与 manifest 值逐值相同（不是评测器另算一套）。
    assert build.adapter.binding_components()["index_revision"] == index_revision
