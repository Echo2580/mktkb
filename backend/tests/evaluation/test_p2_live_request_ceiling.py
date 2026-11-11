
"""T207-FIX-LIVECAP 定向回归：live 单请求上限（provider 单次预留 vs 计划峰值 vs GO）。

R4PREP F-1 的判据（零真实调用；全部出站由 httpx.MockTransport 接住）：

1. 推导不写魔法数：embedding = 官方单请求 81,920 token × 费率、rerank = provider 请求
   token 上限 × 费率、chat = 冻结 token cap × 官方费率；
2. 无 OCR 计划（page_count=0，峰值只有 chat 的 0.018688）：effective 必须被抬到
   max(计划峰值, 各 provider 单次预留) 且 <= GO 授权上限 —— embedding POST 真的发出，
   索引不再降级为 degraded=embedding_error；
3. GO 单请求上限被人为压低到覆盖不了 provider 预留时：**装配期** fail closed
   （live_request_ceiling_insufficient），不发送、不预留、不降级；
4. 含 OCR 的公开计划（峰值 0.5 高于全部 provider 上界）：effective 逐字等于计划峰值，
   行为/计数与修正前一致。

零真实调用：账本/预算/GO 全是 tmp_path 副本（monkeypatch 固定路径常量），
外层 socket 闸门断言外部尝试 = 0。
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
from mktkb.rag import RagConfig
from mktkb.rag.providers import MAX_EMBEDDING_REQUEST_TOKENS

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
B0 = ROOT / "fixtures" / "evaluation" / "b0.jsonl"

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
CENTERS = {"answer_retrieval": 9.0, "ocr": 6.0, "judge": 3.0, "independent": 2.0}

#: provider 侧单次预留（与 rag/providers.py 同一组常量/公式，逐值钉住回归）。
EMBEDDING_RESERVE_CNY = MAX_EMBEDDING_REQUEST_TOKENS * 0.5 / 1_000_000  # 0.04096
RERANK_RESERVE_CNY = 30000 * 0.8 / 1_000_000  # 0.024（live RagConfig 的请求 token 上限）
CHAT_RESERVE_CNY = (6144 * 2.0 + 800 * 8.0) / 1_000_000  # 0.018688（冻结 token cap × 费率）

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
# 计划 / GO / 预算（全部 tmp 副本；与既有 live wiring 测试同口径）
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


def _plan_dict(*, with_ocr: bool) -> dict:
    items = [
        _item("ingest-index", "index_embedding", "INGEST", requests=8),
        _item("embed-Q01-t1", "query_embedding", "Q01"),
        _item("rerank-Q01-t1", "rerank", "Q01"),
        _item("expand-Q01-t1", "query_expansion", "Q01"),
        _item("answer-Q01-t1", "answer", "Q01"),
        _item("embed-Q25-t1", "query_embedding", "Q25"),
        _item("rerank-Q25-t1", "rerank", "Q25"),
        _item("expand-Q25-t1", "query_expansion", "Q25"),
        _item("answer-Q25-t1", "answer", "Q25"),
    ]
    if with_ocr:
        items.append(_item("ocr-Q01-p1", "ocr", "Q01", page=1))
    return {
        "schema_version": c.P2_RUN_PLAN_SCHEMA_VERSION,
        "plan_id": "P2-LIVE-CEILING-UNIT-20261111",
        "plan_version": "v0.1",
        "mode": "end_to_end",
        "stage": "P2-LIVE",
        "created_utc": "2026-11-11T00:00:00+08:00",
        "project_total_limit_cny": TOTAL_LIMIT_CNY,
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "max_requests": 1000,
        "cost_centers_cny": dict(CENTERS),
        "items": items,
    }


def _plan(*, with_ocr: bool) -> P2RunPlan:
    return P2RunPlan.from_dict(_plan_dict(with_ocr=with_ocr))


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


def _write_go(path: Path, *, ledger: Path, plan: P2RunPlan, max_request_cny: float) -> None:
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
                    "max_request_cny": float(max_request_cny),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_ocr: bool,
    max_request_cny: float = 0.5,
) -> SimpleNamespace:
    ledger = tmp_path / "live-ledger.jsonl"
    budget = tmp_path / "budget.json"
    go = tmp_path / "P2-LIVE-GO.json"
    plan = _plan(with_ocr=with_ocr)
    _write_ledger(ledger)
    _write_budget(budget)
    _write_go(go, ledger=ledger, plan=plan, max_request_cny=max_request_cny)
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", ledger)
    monkeypatch.setattr(p2a, "P2_BUDGET_PATH", budget)
    monkeypatch.setattr(p2a, "P2_GO_PATH", go)
    monkeypatch.setenv(live_authorization.TOTAL_LIMIT_ENV, str(TOTAL_LIMIT_CNY))
    return SimpleNamespace(ledger=ledger, budget=budget, go=go, plan=plan, root=tmp_path)


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# fake transports（真实 provider 编解码，零出网）
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


def _embedding_transport(calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        texts = list(body.get("input") or ())
        dims = int(body.get("dimensions") or 1024)
        calls.append({"texts": len(texts)})
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
                    "RequestId": "ocr-unit-ceiling",
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
            "dataset_version": "p2-live-ceiling-unit-v1",
            "label_version": "b0-2026-11-04",
            "suite": "b0",
            "manifest_sha256": "a" * 64,
            "case_count": 1,
        },
    )


def _live_rag_config(*, max_request_cny: float) -> RagConfig:
    """与 product_adapter._start_live 同形（只差凭据/路径，价格与 batch 必须一致）。"""
    return RagConfig(
        provider_mode="live",
        data_dir=Path("."),
        business_date=None,
        top_k=8,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
        embedding_batch_size=5,
        embedding_timeout_seconds=30.0,
        rerank_timeout_seconds=30.0,
        max_request_cny=max_request_cny,
        max_retries=0,
        require_zero_retries=True,
        chat_model="",
        chat_base_url="",
        chat_api_key="",
    )


def _run(
    env: SimpleNamespace,
    tmp_path: Path,
    *,
    embedding_calls: list[dict],
    rerank_calls: list[dict],
    ocr_calls: list[dict],
    chat: MockChatBackend,
):
    plan = env.plan
    gate = p2_live.open_live_gate(plan, run_id="p2-live-ceiling", now=NOW)
    ingest_plan = P2IngestPlan(sources=(IngestSource(path=D01),), label="t207-livecap")

    async def go():
        return await p2_live.run_live_p2(
            plan,
            run_id="p2-live-ceiling",
            out_dir=tmp_path / "run",
            dataset=_dataset("Q01"),
            ingest_plan=ingest_plan,
            gate=gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=LIVE_ENV_OVERRIDES,
            transports={
                "chat": chat.transport,
                "embedding": _embedding_transport(embedding_calls),
                "rerank": _rerank_transport(rerank_calls),
                "ocr": _ocr_transport(ocr_calls),
            },
            now=NOW,
        )

    result, build = asyncio.run(go())
    return result, build, gate


# --------------------------------------------------------------------------- #
# 1. 推导：从 provider 常量/公式来，不写魔法数
# --------------------------------------------------------------------------- #


def test_provider_bounds_follow_provider_formulas() -> None:
    bounds = p2_live.provider_single_request_bounds(_live_rag_config(max_request_cny=0.018688))
    assert bounds["embedding"] == pytest.approx(EMBEDDING_RESERVE_CNY)
    assert bounds["rerank"] == pytest.approx(RERANK_RESERVE_CNY)
    assert bounds["chat"] == pytest.approx(CHAT_RESERVE_CNY)


def test_effective_ceiling_covers_provider_reserve_and_respects_go_cap() -> None:
    cfg = _live_rag_config(max_request_cny=0.018688)
    ceiling = p2_live.resolve_request_ceiling(
        cfg, plan_peak_cny=0.018688, authorization_cny=0.5
    )
    # 无 OCR 计划：峰值 0.018688 抬到 embedding 的 0.04096，且不超过 GO 的 0.5。
    assert ceiling.effective_cny == pytest.approx(EMBEDDING_RESERVE_CNY)
    assert ceiling.effective_cny <= ceiling.authorization_cny
    assert ceiling.as_dict()["provider_single_request_cny"] == {
        "embedding": pytest.approx(EMBEDDING_RESERVE_CNY),
        "rerank": pytest.approx(RERANK_RESERVE_CNY),
        "chat": pytest.approx(CHAT_RESERVE_CNY),
    }

    # 含 OCR 的公开型计划：峰值 0.5 高于全部 provider 上界 ⇒ effective 逐字等于峰值。
    ocr_ceiling = p2_live.resolve_request_ceiling(
        _live_rag_config(max_request_cny=0.5), plan_peak_cny=0.5, authorization_cny=0.5
    )
    assert ocr_ceiling.effective_cny == 0.5
    assert all(value < 0.5 for value in ocr_ceiling.provider_bounds_cny.values())


def test_ceiling_below_provider_reserve_is_refused_with_stable_code() -> None:
    cfg = _live_rag_config(max_request_cny=0.018688)
    with pytest.raises(p2_live.P2LiveConfigError) as excinfo:
        p2_live.resolve_request_ceiling(
            cfg, plan_peak_cny=0.018688, authorization_cny=0.02
        )
    assert excinfo.value.code == "live_request_ceiling_insufficient"
    assert "embedding" in excinfo.value.detail


# --------------------------------------------------------------------------- #
# 2. 无 OCR 计划：embedding POST 必须真的发出（F-1 的修复面）
# --------------------------------------------------------------------------- #


def test_no_ocr_plan_emits_embedding_posts_without_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _prepare(tmp_path, monkeypatch, with_ocr=False)
    embedding_calls: list[dict] = []
    rerank_calls: list[dict] = []
    ocr_calls: list[dict] = []
    chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, gate = _run(
        env,
        tmp_path,
        embedding_calls=embedding_calls,
        rerank_calls=rerank_calls,
        ocr_calls=ocr_calls,
        chat=chat,
    )

    # 推导可见：effective 来自 provider 单次预留，不是计划的 0.018688。
    ceiling = build.wiring.request_ceiling
    assert ceiling is not None
    assert ceiling["plan_peak_cny"] == pytest.approx(0.018688)
    assert ceiling["effective_max_request_cny"] == pytest.approx(EMBEDDING_RESERVE_CNY)
    assert ceiling["effective_max_request_cny"] <= gate.authorization.max_request_cny

    # POST 真的发出：D01 灌库 9 单元按批 5 拆 2 次 + 查询 1 次。
    assert len(embedding_calls) == 3, embedding_calls
    assert build.wiring.ledger.attempts("index_embedding", "query_embedding") == 3
    # rerank 的 provider 预留 0.024 同样高于旧上限；修复后也必须发出。
    assert len(rerank_calls) == 1
    assert ocr_calls == []  # 计划无 OCR 项：一次都不调用

    # 不再降级：索引 ready 且没有 embedding_error。
    status = build.adapter.index_status()
    assert status["degraded"] == []
    assert status["ready"] is True
    assert status["error_code"] is None
    assert status["documents"] == 1 and status["chunks"] > 0

    assert result.status == "succeeded"
    assert chat.call_count == 1
    assert build.adapter.provider_calls()["outbound_network"] == 0


# --------------------------------------------------------------------------- #
# 3. GO 上限不足：装配期 fail closed（不发送、不预留、不降级）
# --------------------------------------------------------------------------- #


def test_live_refuses_at_start_when_go_cap_cannot_cover_provider_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 0.02 >= 0.018688（计划峰值）⇒ 旧的 GO 校验能过；但低于 embedding 的 0.04096。
    env = _prepare(tmp_path, monkeypatch, with_ocr=False, max_request_cny=0.02)
    embedding_calls: list[dict] = []
    rerank_calls: list[dict] = []
    ocr_calls: list[dict] = []
    chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))

    with pytest.raises(p2_live.P2LiveConfigError) as excinfo:
        _run(
            env,
            tmp_path,
            embedding_calls=embedding_calls,
            rerank_calls=rerank_calls,
            ocr_calls=ocr_calls,
            chat=chat,
        )
    assert excinfo.value.code == "live_request_ceiling_insufficient"

    # 发送前停住：没有 POST、没有预留、没有产物、没有降级记录。
    assert embedding_calls == []
    assert rerank_calls == []
    assert ocr_calls == []
    assert chat.call_count == 0
    assert [row for row in _events(env.ledger) if row.get("event") == "reserved"] == []
    assert not (tmp_path / "run" / "summary.json").exists()


# --------------------------------------------------------------------------- #
# 4. 含 OCR 的公开型计划：effective 等于计划峰值，计数不变
# --------------------------------------------------------------------------- #


def test_public_ocr_plan_ceiling_and_counts_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _prepare(tmp_path, monkeypatch, with_ocr=True)
    embedding_calls: list[dict] = []
    rerank_calls: list[dict] = []
    ocr_calls: list[dict] = []
    chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, gate = _run(
        env,
        tmp_path,
        embedding_calls=embedding_calls,
        rerank_calls=rerank_calls,
        ocr_calls=ocr_calls,
        chat=chat,
    )

    plan_peak = float(env.plan.reserve_peak_cny)
    assert plan_peak == pytest.approx(0.5)
    ceiling = build.wiring.request_ceiling
    assert ceiling is not None
    # 逐字不变：effective == 计划的串行峰值（旧行为），而不是被 provider 上界改小/改大。
    assert ceiling["effective_max_request_cny"] == plan_peak
    assert ceiling["effective_max_request_cny"] <= gate.authorization.max_request_cny
    # provider 上界全部低于峰值 ⇒ 这条计划在修正前后走的是同一个上限值。
    assert all(value <= plan_peak for value in ceiling["provider_single_request_cny"].values())

    # 计数与既有 live 用例一致：embedding 3 批、rerank 1 次、OCR 0 次（xlsx 不走 OCR）。
    assert len(embedding_calls) == 3
    assert len(rerank_calls) == 1
    assert ocr_calls == []
    assert result.status == "succeeded"
    assert build.adapter.index_status()["degraded"] == []
    assert build.adapter.provider_calls()["outbound_network"] == 0

