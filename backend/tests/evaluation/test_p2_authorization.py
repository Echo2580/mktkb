"""P2-T201 定向回归：请求计划 / 资金预检 / 授权门 / 每次发送前拒绝链。

本文件锁定 T201 的验收口径（任务书 §8 T201）：
1. 计划 schema 严格：空/缺字段/多字段、bool 当 int、NaN/Inf/负数、0 价、缺单价或 token
   上界、cap 写小、错 stage、未注册操作、cost_center 不一致、中心合计不等于阶段额度、
   累计请求超硬顶、重复 item_id 一律在构造期拒绝；
2. 预检只读：阶段额度、项目总额、成本中心、累计请求四类余量不足都返回稳定原因码；
   历史 505 次请求不被新增预算重置；
3. 授权：旧 P1 GO（S2-LIVE-GO）默认拒绝、错 stage/未授权操作/未授权中心/过期/换计划
   复用 nonce/账本前缀变化/缺身份 -> 全部拒绝；
4. 门控：合法 Mock 请求走完 校验 -> 预留 -> 假发送 -> 假结算；串行、自动重试 0；
   预留后发送前失效（GO 过期/计划被改/操作被撤/账本前缀变化）安全停止并保守留账
   （status=failed，全额占用，保留 reservation_id/request_id/plan_id/cost_center）；
5. 所有拒绝路径：假发送计数不变（HTTP=0）、账本不新增 reserved 行、不释放已有预留。

零真实调用：账本/预算/GO 全是 tmp_path 隔离副本（monkeypatch 固定路径常量），
provider 用假发送记录器；不读 .env、不读 H2/Holdout、不碰 var/ 与原账本。
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mktkb import live_authorization
from mktkb.evaluation import p2_authorization as p2a
from mktkb.evaluation import p2_contracts as c
from mktkb.evaluation.p2_contracts import (
    COST_CENTERS,
    P2Authorization,
    P2ContractError,
    P2LedgerSnapshot,
    P2RequestItem,
    P2RunPlan,
)
from mktkb.rag.budget import BudgetLedger, RequestLimitExceeded
from mktkb.rag.errors import BudgetLedgerInvalid
from mktkb.rag.settlement_policy import UsageEvidence

P2_STAGE = "P2-LIVE"
HISTORY_CNY = 0.03
TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
CENTERS = {"answer_retrieval": 12.0, "ocr": 3.0, "judge": 3.0, "independent": 2.0}
CHAT_BOUND_CNY = 0.018688
EMB_BOUND_CNY = 0.002048
RERANK_BOUND_CNY = 0.0048
OCR_TEXT_PRICE_CNY = 0.5
OCR_TABLE_PRICE_CNY = 0.15
# 候选计划规模（与 docs/reports/OBS-EVAL/P2/T201/candidates 一致，不是 T206 的最终清单）。
PLANNED_REQUESTS = 30
PLANNED_WORST_CASE_CNY = 0.887504
PLANNED_RESERVE_PEAK_CNY = 0.5
NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)

CANDIDATES = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "reports"
    / "OBS-EVAL"
    / "P2"
    / "T201"
    / "candidates"
)
REAL_LEDGER = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "evidence"
    / "LOCAL-R1-20261101"
    / "budget"
    / "live-ledger.jsonl"
)


# --------------------------------------------------------------------------- #
# 计划/GO/预算夹具（全部内存或 tmp_path，不碰仓库共享文件）
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _profiles() -> dict[str, dict]:
    chat = {
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
    }
    embedding = {
        "kind": "embedding",
        "model": "text-embedding-v4",
        "provider": "bailian",
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": "official-list-price/bailian-text-embedding-v4-v1",
        "unit_price_per_million_cny": 0.5,
        "total_tokens_cap": 4096,
    }
    rerank = {
        "kind": "rerank",
        "model": "gte-rerank-v2",
        "provider": "bailian",
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": "official-list-price/bailian-gte-rerank-v2-v1",
        "unit_price_per_million_cny": 0.8,
        "total_tokens_cap": 6000,
    }
    ocr_text = {
        "kind": "ocr",
        "model": "GeneralAccurateOCR",
        "provider": "tencent",
        "host": "ocr.tencentcloudapi.com",
        "region": "ap-guangzhou",
        "pricing_source": "official-list-price/tencent-ocr-postpaid-highest-v1",
        "price_cny_per_page": 0.5,
        "pages_per_request": 1,
    }
    ocr_table = {**ocr_text, "model": "RecognizeTableAccurateOCR", "price_cny_per_page": 0.15}
    return {"chat": chat, "embedding": embedding, "rerank": rerank, "ocr_text": ocr_text, "ocr_table": ocr_table}


def _item(
    item_id: str,
    operation: str,
    case_id: str,
    *,
    requests: int = 1,
    turn: int = 1,
    page: int = 0,
    expected: float = 0.004,
    profile: dict | None = None,
    cost_center: str | None = None,
) -> dict:
    profiles = _profiles()
    kind = c.OPERATION_KIND[operation]
    if profile is None:
        if kind == "chat":
            profile = profiles["chat"]
        elif kind == "embedding":
            profile = profiles["embedding"]
            expected = min(expected, EMB_BOUND_CNY)
        elif kind == "rerank":
            profile = profiles["rerank"]
            expected = min(expected, RERANK_BOUND_CNY)
        else:
            profile = profiles["ocr_text"]
            expected = profile["price_cny_per_page"]
    return {
        "item_id": item_id,
        "operation": operation,
        "cost_center": cost_center or c.OPERATION_COST_CENTER[operation],
        "case_id": case_id,
        "turn": turn,
        "page": page,
        "requests": requests,
        "price_profile": copy.deepcopy(profile),
        "expected_success_cny": expected,
    }


def _plan_items() -> list[dict]:
    """候选计划：6 个 case、30 次底层调用（1 题 != 1 请求）。"""
    profiles = _profiles()
    items = [_item("ingest-index", "index_embedding", "INGEST", requests=8, expected=0.0003)]
    for case, turn in (("B0-Q01", 1), ("B0-Q03", 1), ("N01", 1), ("U01", 2), ("D07", 1)):
        items.append(_item(f"embed-{case}-t{turn}", "query_embedding", case, turn=turn, expected=0.0003))
        items.append(_item(f"rerank-{case}-t{turn}", "rerank", case, turn=turn, expected=0.001))
        items.append(_item(f"answer-{case}-t{turn}", "answer", case, turn=turn, expected=0.004))
    items.append(_item("expand-U01-t2", "query_expansion", "U01", turn=2, expected=0.004))
    items.append(_item("expand-B0-Q03", "query_expansion", "B0-Q03", expected=0.004))
    items.append(_item("ocr-D07-p1", "ocr", "D07", page=1, expected=OCR_TEXT_PRICE_CNY, profile=profiles["ocr_text"]))
    items.append(_item("ocr-D07-p2", "ocr", "D07", page=2, expected=OCR_TABLE_PRICE_CNY, profile=profiles["ocr_table"]))
    items.append(_item("judge-B0-Q01", "judge", "B0-Q01", expected=0.004))
    items.append(_item("judge-N01", "judge", "N01", expected=0.004))
    items.append(_item("independent-B0-Q01", "independent", "B0-Q01", expected=0.004))
    return items


_ITEM_INDEX = {item["item_id"]: index for index, item in enumerate(_plan_items())}
OCR_TEXT_INDEX = _ITEM_INDEX["ocr-D07-p1"]
INDEPENDENT_INDEX = _ITEM_INDEX["independent-B0-Q01"]


def _plan_dict(**overrides) -> dict:
    plan = {
        "schema_version": c.P2_RUN_PLAN_SCHEMA_VERSION,
        "plan_id": "P2-CAND-20261110",
        "plan_version": "v0.1",
        "mode": "end_to_end",
        "stage": P2_STAGE,
        "created_utc": "2026-11-10T18:00:00+08:00",
        "project_total_limit_cny": TOTAL_LIMIT_CNY,
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "max_requests": 1000,
        "cost_centers_cny": dict(CENTERS),
        "items": _plan_items(),
    }
    plan.update(overrides)
    return plan


def _plan(**overrides) -> P2RunPlan:
    return P2RunPlan.from_dict(_plan_dict(**overrides))


def _write_ledger(path: Path, *, history: float = HISTORY_CNY, seeded: int = 0) -> None:
    lines = [
        json.dumps(
            {
                "event": "historical_import",
                "accounted_cny": history,
                "estimated_success_list_price_cny": 0.0000352,
                "source": "unit-test",
            },
            ensure_ascii=False,
        )
    ]
    for index in range(seeded):
        # 历史预留：跨 kind 混排（chat/embedding/ocr），证明累计计数不分 kind。
        kind = ("chat", "embedding", "ocr")[index % 3]
        provider, model = {
            "chat": ("deepseek", "deepseek-flash"),
            "embedding": ("bailian", "text-embedding-v4"),
            "ocr": ("tencent", "GeneralAccurateOCR"),
        }[kind]
        lines.append(
            json.dumps(
                {
                    "event": "reserved",
                    "reservation_id": f"seed{index:04d}",
                    "stage": "S2-DEV",
                    "kind": kind,
                    "provider": provider,
                    "model": model,
                    "reserve_cny": 0.00000001,
                    "request_sha256": "e" * 64,
                    "time_utc": "2026-11-05T00:00:00+00:00",
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_budget(
    path: Path,
    *,
    limit: float = TOTAL_LIMIT_CNY,
    stage_limit: float = STAGE_LIMIT_CNY,
    stages: dict | None = None,
    history: float = HISTORY_CNY,
) -> None:
    payload = {
        "limit_cny": limit,
        "historical_conservative_accounted_cny": history,
        "stages": stages if stages is not None else {P2_STAGE: stage_limit, "S2-DEV": 15.4},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _go_dict(ledger_prefix: str, plan: P2RunPlan, *, ledger_path: Path, **overrides) -> dict:
    payload = {
        "document": "P2-LIVE-GO",
        "schema_version": "p2-live-go/v0.1",
        "stage": P2_STAGE,
        "authorization": "UNIT-TEST-MOCK-GO（零真实调用）",
        "issued_by": "pytest",
        "nonce": "unit-test-p2-nonce-0123456789",
        "issued_utc": "2026-11-19T00:00:00+00:00",
        "expires_utc": "2026-11-20T00:00:00+00:00",
        "budget_ledger_path": str(ledger_path),
        "budget_ledger_sha256": ledger_prefix,
        "budget_total_limit_cny": TOTAL_LIMIT_CNY,
        "scope": {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "operations": list(plan.operations),
            "cost_centers_cny": dict(CENTERS),
            "stage_limits_cny": {P2_STAGE: STAGE_LIMIT_CNY},
            "max_requests": 1000,
            "max_request_cny": 0.5,
        },
    }
    for key, value in overrides.items():
        if key == "scope":
            payload["scope"] = {**payload["scope"], **value}
        else:
            payload[key] = value
    return payload


def _write_go(
    path: Path, *, ledger_prefix: str, plan: P2RunPlan, ledger_path: Path, **overrides
) -> None:
    path.write_text(
        json.dumps(
            _go_dict(ledger_prefix, plan, ledger_path=ledger_path, **overrides),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _prefix_sha(path: Path) -> str:
    return live_authorization.historical_prefix_sha256(path)


@pytest.fixture
def p2_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """固定路径全部指向 tmp 副本：不读仓库共享账本/预算，也不写它们。"""
    ledger = tmp_path / "live-ledger.jsonl"
    budget = tmp_path / "budget.json"
    go = tmp_path / "P2-LIVE-GO.json"
    _write_ledger(ledger)
    _write_budget(budget)
    plan = _plan()
    _write_go(go, ledger_prefix=_prefix_sha(ledger), plan=plan, ledger_path=ledger)
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", ledger)
    monkeypatch.setattr(p2a, "P2_BUDGET_PATH", budget)
    monkeypatch.setattr(p2a, "P2_GO_PATH", go)
    monkeypatch.setenv(live_authorization.TOTAL_LIMIT_ENV, str(TOTAL_LIMIT_CNY))
    return SimpleNamespace(ledger=ledger, budget=budget, go=go, plan=plan, root=tmp_path)


def _snapshot(**kwargs) -> P2LedgerSnapshot:
    return p2a.read_ledger_snapshot(**kwargs)


def _open_gate(env: SimpleNamespace, **kwargs):
    return p2a.P2Gate.open(
        env.plan,
        go_payload=kwargs.pop("go_payload", env.go),
        budget_payload=kwargs.pop("budget_payload", env.budget),
        now=kwargs.pop("now", NOW),
        run_id=kwargs.pop("run_id", "p2run-unit"),
        **kwargs,
    )


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _reserved_count(path: Path) -> int:
    return sum(1 for event in _events(path) if event.get("event") == "reserved")


def _result_events(path: Path) -> list[dict]:
    return [event for event in _events(path) if event.get("event") == "result"]


class FakeTransport:
    """假发送：只计数，不发网络；拒绝路径必须保持 0 次。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, ticket) -> dict:
        self.calls.append(ticket.as_dict())
        return {"http_status": 200, "request_id": ticket.request_id}

    def __len__(self) -> int:
        return len(self.calls)


def _chat_evidence(ticket, *, prompt: int = 1200, completion: int = 200) -> UsageEvidence:
    return UsageEvidence(
        kind="chat",
        provider="deepseek",
        model="deepseek-flash",
        host="api.deepseek.com",
        region="global",
        pricing_source="official-list-price/deepseek-chat-cache-miss-v1",
        request_sha256=ticket.reservation.request_sha256,
        http_status=200,
        streamed=False,
        finish_reason="stop",
        content_complete=True,
        content_parse_ok=True,
        usage={
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": prompt,
        },
    )


def _append_event(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _append_reserved(
    path: Path,
    *,
    rid: str,
    stage: str,
    kind: str = "chat",
    reserve: float = 0.018688,
    cost_center: str | None = "answer_retrieval",
) -> None:
    event = {
        "event": "reserved",
        "reservation_id": rid,
        "stage": stage,
        "kind": kind,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "reserve_cny": reserve,
        "request_sha256": "a" * 64,
        "time_utc": "2026-11-19T00:00:00+00:00",
    }
    if cost_center is not None:
        event["cost_center"] = cost_center
    _append_event(path, event)


def _set(plan: dict, path: tuple, value) -> None:
    target = plan
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _drop(plan: dict, path: tuple) -> None:
    target = plan
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]


# --------------------------------------------------------------------------- #
# 1. 冻结来源与固定路径
# --------------------------------------------------------------------------- #


def test_frozen_price_sources_match_j1_and_s2_j2() -> None:
    """P2 价格画像只能引用已核来源：caps/费率下限/OCR 固定价逐值对齐，防漂移。"""
    from mktkb.providers import ocr_budgeted
    from mktkb.rag import settlement_policy as sp

    assert c.CHAT_PROMPT_TOKENS_CAP == sp.CHAT_PROMPT_TOKENS_CAP
    assert c.CHAT_COMPLETION_TOKENS_CAP == sp.CHAT_COMPLETION_TOKENS_CAP
    assert c.EMBEDDING_TOTAL_TOKENS_CAP == sp.EMBEDDING_TOTAL_TOKENS_CAP
    assert c.RERANK_TOTAL_TOKENS_CAP == sp.RERANK_TOTAL_TOKENS_CAP
    assert c.CHAT_INPUT_PRICE_FLOOR == sp.CHAT_INPUT_PRICE_FLOOR
    assert c.CHAT_OUTPUT_PRICE_FLOOR == sp.CHAT_OUTPUT_PRICE_FLOOR
    assert c.EMBEDDING_UNIT_PRICE_FLOOR == sp.EMBEDDING_UNIT_PRICE_FLOOR
    assert c.RERANK_UNIT_PRICE_FLOOR == sp.RERANK_UNIT_PRICE_FLOOR
    assert c.OCR_TEXT_PRICE_CNY == float(ocr_budgeted.OCR_TEXT_PRICE_CNY)
    assert c.OCR_TABLE_PRICE_CNY == float(ocr_budgeted.OCR_TABLE_PRICE_CNY)
    assert c.OCR_TEXT_MODEL == ocr_budgeted.OCR_MODEL_TEXT
    assert c.OCR_TABLE_MODEL == ocr_budgeted.OCR_MODEL_TABLE
    assert c.OCR_PRICING_SOURCE.endswith("tencent-ocr-postpaid-highest-v1")


def test_p2_fixed_paths_are_the_shared_ledger_and_budget() -> None:
    """P2 不新开账本：固定路径必须指向 P1 的同一只共享账本与同一份预算。"""
    assert p2a.P2_LEDGER_PATH == live_authorization.SHARED_LEDGER_PATH
    assert p2a.P2_BUDGET_PATH == live_authorization.SHARED_BUDGET_PATH
    assert p2a.P2_GO_PATH.name == "P2-LIVE-GO.json"
    assert c.HARD_MAX_REQUESTS == live_authorization.MAX_GO_REQUESTS


# --------------------------------------------------------------------------- #
# 2. 计划 schema 负例（全部在构造期拒绝，未预留未发送）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "mutation", "reason"),
    [
        ("bool_requests", (("items", 0, "requests"), True), "integer_invalid"),
        ("bool_turn", (("items", 0, "turn"), True), "integer_invalid"),
        ("nan_price", (("items", 0, "price_profile", "total_tokens_cap"), float("nan")), "integer_invalid"),
        (
            "inf_price",
            (("items", 0, "price_profile", "unit_price_per_million_cny"), float("inf")),
            "number_invalid",
        ),
        (
            "negative_price",
            (("items", 0, "price_profile", "unit_price_per_million_cny"), -0.5),
            "number_invalid",
        ),
        (
            "zero_price",
            (("items", 0, "price_profile", "unit_price_per_million_cny"), 0.0),
            "number_invalid",
        ),
        (
            "low_token_cap",
            (("items", 0, "price_profile", "total_tokens_cap"), 256),
            "cap_not_frozen",
        ),
        ("legacy_stage", (("stage",), "S2-DEV"), "stage_invalid"),
        ("p1_stage", (("stage",), "P1-RETRIEVAL"), "stage_invalid"),
        ("bad_mode", (("mode",), "retrieval_only"), "mode_invalid"),
        ("empty_items", (("items",), []), "items_required"),
        ("unknown_operation", (("items", 0, "operation"), "tts"), "operation_unregistered"),
        ("cost_center_mismatch", (("items", 0, "cost_center"), "judge"), "cost_center_mismatch"),
        ("page_on_answer", (("items", 0, "page"), 1), "page_forbidden"),
        ("ocr_page_zero", (("items", OCR_TEXT_INDEX, "page"), 0), "page_required"),
        ("center_sum_mismatch", (("cost_centers_cny",), {"answer_retrieval": 11.0, **{k: v for k, v in CENTERS.items() if k != "answer_retrieval"}}), "cost_center_total_mismatch"),
        ("center_missing", (("cost_centers_cny",), {"answer_retrieval": 15.0, "ocr": 5.0}), "cost_center_set_invalid"),
        ("independent_overrun", (("items", INDEPENDENT_INDEX, "requests"), 110), "center_budget_exceeded"),
        ("request_cap_over_hard", (("max_requests",), 2001), "request_cap_over_hard_limit"),
        ("plan_requests_over_cap", (("max_requests",), 10), "plan_requests_over_cap"),
        (
            "estimate_over_bound",
            (("items", -1, "expected_success_cny"), 1.0),
            "success_estimate_over_bound",
        ),
    ],
)
def test_plan_rejects_invalid_schema(label: str, mutation: tuple, reason: str) -> None:
    plan = _plan_dict()
    path, value = mutation
    _set(plan, path, value)
    with pytest.raises(P2ContractError) as excinfo:
        P2RunPlan.from_dict(plan)
    assert excinfo.value.reason == reason, (label, excinfo.value.reason)
    # 拒绝发生在任何资金动作之前：只构造计划，没有账本/GO 参与。
    assert not hasattr(excinfo.value, "reservation_id")


def test_plan_rejects_missing_price_and_missing_cap() -> None:
    plan = _plan_dict()
    _drop(plan, ("items", 0, "price_profile", "unit_price_per_million_cny"))
    with pytest.raises(P2ContractError) as excinfo:
        P2RunPlan.from_dict(plan)
    assert excinfo.value.reason == "field_missing"

    plan = _plan_dict()
    _drop(plan, ("items", 0, "price_profile", "total_tokens_cap"))
    with pytest.raises(P2ContractError) as excinfo:
        P2RunPlan.from_dict(plan)
    assert excinfo.value.reason == "field_missing"

    plan = _plan_dict()
    _set(plan, ("items", 0, "price_profile"), {**_profiles()["embedding"], "model": "text-embedding-v3"})
    with pytest.raises(P2ContractError) as excinfo:
        P2RunPlan.from_dict(plan)
    assert excinfo.value.reason in ("price_model_invalid", "price_below_floor")


def test_plan_rejects_unknown_and_duplicate_fields() -> None:
    plan = _plan_dict()
    plan["note"] = "extra"
    with pytest.raises(P2ContractError) as excinfo:
        P2RunPlan.from_dict(plan)
    assert excinfo.value.reason == "field_unknown"

    plan = _plan_dict()
    plan["items"][1]["item_id"] = plan["items"][0]["item_id"]
    with pytest.raises(P2ContractError) as excinfo:
        P2RunPlan.from_dict(plan)
    assert excinfo.value.reason == "item_id_duplicate"


def test_plan_derives_case_turn_page_and_request_counts_separately() -> None:
    """1 题 != 1 请求：同一题的多轮/每页 OCR 分别计。"""
    plan = _plan()
    assert plan.total_requests == PLANNED_REQUESTS
    assert plan.case_count == 6
    assert plan.turn_count == 6
    assert plan.page_count == 2
    assert plan.worst_case_cny == pytest.approx(PLANNED_WORST_CASE_CNY, abs=1e-9)
    assert plan.reserve_peak_cny == pytest.approx(PLANNED_RESERVE_PEAK_CNY, abs=1e-9)
    assert plan.requests_by_operation()["answer"] == 5
    assert plan.center_needs_cny()["ocr"] == pytest.approx(0.65, abs=1e-9)
    assert set(plan.cost_centers_cny) == set(COST_CENTERS)


# --------------------------------------------------------------------------- #
# 3. 预检：只读、稳定原因码、不重置历史计数
# --------------------------------------------------------------------------- #


def test_preflight_accepts_candidate_scale_plan(p2_env: SimpleNamespace) -> None:
    snapshot = _snapshot()
    assert snapshot.production_ready is True
    assert snapshot.reservation_count == 0
    assert snapshot.total_limit_cny == TOTAL_LIMIT_CNY
    result = p2a.preflight_p2(p2_env.plan, snapshot)
    assert result.ok is True, result.reasons
    assert result.reasons == ()
    assert result.stage_limit_cny == pytest.approx(STAGE_LIMIT_CNY)
    assert result.stage_remaining_cny == pytest.approx(STAGE_LIMIT_CNY)
    assert result.worst_case_cny == pytest.approx(PLANNED_WORST_CASE_CNY)
    assert result.reserve_peak_cny == pytest.approx(PLANNED_RESERVE_PEAK_CNY)
    assert result.estimated_success_cny == pytest.approx(0.6989, abs=1e-9)
    assert result.requests_planned == PLANNED_REQUESTS
    assert result.center_needs_cny["answer_retrieval"] == pytest.approx(0.18144, abs=1e-9)


def test_preflight_rejects_stage_allocation_missing(p2_env: SimpleNamespace) -> None:
    _write_budget(p2_env.budget, stages={"S2-DEV": 15.4})
    result = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert result.ok is False
    assert "stage_allocation_missing" in result.reasons


def test_preflight_rejects_stage_allocation_below_plan(p2_env: SimpleNamespace) -> None:
    _write_budget(p2_env.budget, stage_limit=5.0)
    result = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert result.ok is False
    assert "stage_allocation_below_plan" in result.reasons
    # 5 元仍够本次计划的 0.89 元上界，所以只有“低于计划阶段额度”这一条；余量类拒绝另有用例。
    assert result.stage_limit_cny == pytest.approx(5.0)


def test_preflight_rejects_budget_total_mismatch(p2_env: SimpleNamespace) -> None:
    _write_budget(p2_env.budget, limit=20.0)
    result = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert result.ok is False
    assert "budget_total_mismatch" in result.reasons


def test_preflight_rejects_consumed_stage_budget(p2_env: SimpleNamespace) -> None:
    _append_reserved(p2_env.ledger, rid="p2-spent", stage=P2_STAGE, reserve=19.5)
    result = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert result.ok is False
    assert "stage_budget_insufficient" in result.reasons
    assert result.stage_remaining_cny == pytest.approx(0.5, abs=1e-9)


def test_preflight_rejects_consumed_center_budget(p2_env: SimpleNamespace) -> None:
    _append_reserved(
        p2_env.ledger, rid="p2-ocr", stage=P2_STAGE, kind="ocr", reserve=2.9, cost_center="ocr"
    )
    result = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert result.ok is False
    assert "center_budget_insufficient:ocr" in result.reasons
    assert result.center_remaining_cny["ocr"] == pytest.approx(0.1, abs=1e-9)


def test_preflight_rejects_unattributed_stage_spend(p2_env: SimpleNamespace) -> None:
    """阶段里有不归属任何成本中心的预留：不能证明“换个中心就不超”，默认拒绝。"""
    _append_reserved(p2_env.ledger, rid="p2-nocenter", stage=P2_STAGE, reserve=0.1, cost_center=None)
    result = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert result.ok is False
    assert "center_accounting_inconsistent" in result.reasons


def test_preflight_keeps_505_history_requests(p2_env: SimpleNamespace) -> None:
    """新增 20 元不重置累计请求：505 次历史请求照旧计入。"""
    _write_ledger(p2_env.ledger, seeded=505)
    snapshot = _snapshot()
    assert snapshot.reservation_count == 505
    assert snapshot.result_count == 0
    result = p2a.preflight_p2(_plan(max_requests=525), snapshot)
    assert result.ok is False
    assert "request_budget_insufficient" in result.reasons
    assert result.requests_used == 505
    assert result.requests_remaining == 20
    ok_result = p2a.preflight_p2(p2_env.plan, snapshot)
    assert ok_result.ok is True, ok_result.reasons
    assert ok_result.requests_remaining == 495


# --------------------------------------------------------------------------- #
# 4. 授权负例（全部在首个预留/首个发送之前拒绝）
# --------------------------------------------------------------------------- #


def _authorize(env: SimpleNamespace, *, plan: P2RunPlan | None = None, **kwargs) -> P2Authorization:
    kwargs.setdefault("go_payload", env.go)
    kwargs.setdefault("budget_payload", env.budget)
    kwargs.setdefault("ledger_snapshot", _snapshot())
    kwargs.setdefault("now", NOW)
    return p2a.authorize_p2(plan or env.plan, **kwargs)


def _refuse(env: SimpleNamespace, reason: str, **kwargs) -> None:
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        _authorize(env, **kwargs)
    assert excinfo.value.reason == reason, excinfo.value.reason


def test_loaders_reject_non_fixed_paths(p2_env: SimpleNamespace, tmp_path: Path) -> None:
    """固定路径不能换：换成别处的账本/预算/GO 一律拒绝（不给“绕过账本”的口子）。"""
    foreign_ledger = tmp_path / "elsewhere-ledger.jsonl"
    foreign_budget = tmp_path / "elsewhere-budget.json"
    foreign_go = tmp_path / "elsewhere-go.json"
    _write_ledger(foreign_ledger)
    _write_budget(foreign_budget)
    _write_go(
        foreign_go,
        ledger_prefix=_prefix_sha(foreign_ledger),
        plan=p2_env.plan,
        ledger_path=foreign_ledger,
    )
    for loader, path, reason in (
        (p2a.load_go_payload, foreign_go, "path_not_fixed"),
        (p2a.load_budget_payload, foreign_budget, "path_not_fixed"),
    ):
        with pytest.raises(p2a.P2AuthorizationError) as excinfo:
            loader(path)
        assert excinfo.value.reason == reason
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        p2a.read_ledger_snapshot(ledger_path=foreign_ledger)
    assert excinfo.value.reason == "path_not_fixed"
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        p2a.read_ledger_snapshot(budget_path=foreign_budget)
    assert excinfo.value.reason == "path_not_fixed"


def test_authorize_accepts_fixed_paths_and_keeps_identity(p2_env: SimpleNamespace) -> None:
    auth = _authorize(p2_env)
    assert auth.production_ready is True
    assert auth.stage == P2_STAGE
    assert auth.stage_limit_cny == pytest.approx(STAGE_LIMIT_CNY)
    assert auth.stage_remaining_cny == pytest.approx(STAGE_LIMIT_CNY)
    assert auth.max_requests == 1000
    assert auth.max_request_cny == pytest.approx(0.5)
    assert auth.requests_used == 0
    assert auth.requests_remaining == 1000
    assert auth.operations == tuple(sorted(p2_env.plan.operations))
    assert auth.go_document == "P2-LIVE-GO"
    assert auth.ledger_sha256 == _prefix_sha(p2_env.ledger)
    assert auth.expires_utc > auth.issued_utc
    payload = auth.as_dict()
    assert payload["plan_sha256"] == p2_env.plan.plan_sha256
    assert payload["production_ready"] is True
    # 授权摘要不含任何凭据形态串；nonce 只给长度。
    assert "unit-test-p2-nonce" not in json.dumps(payload, ensure_ascii=False)
    assert payload["go_nonce_len"] == len("unit-test-p2-nonce-0123456789")


def test_authorize_rejects_legacy_p1_go_document(p2_env: SimpleNamespace) -> None:
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        document="S2-LIVE-GO",
    )
    _refuse(p2_env, "legacy_go_document", go_payload=go)


def test_authorize_rejects_real_p1_go_file_if_present(p2_env: SimpleNamespace) -> None:
    """仓库里真实的 P1 GO（S2-LIVE-GO.json）不获得 P2 权限（只读，若不存在则跳过）。"""
    p1_go = REAL_LEDGER.parent.parent / "PM" / "S2-LIVE-GO.json"
    if not p1_go.is_file():
        pytest.skip("仓库内没有 S2-LIVE-GO.json")
    payload = json.loads(p1_go.read_text(encoding="utf-8"))
    _refuse(p2_env, "legacy_go_document", go_payload=payload)


def test_authorize_rejects_wrong_stage(p2_env: SimpleNamespace) -> None:
    _refuse(p2_env, "go_stage_mismatch", go_payload=_go_dict(
        _prefix_sha(p2_env.ledger), p2_env.plan, ledger_path=p2_env.ledger, stage="S2-DEV"
    ))


def test_authorize_rejects_expired_and_future_go(p2_env: SimpleNamespace) -> None:
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        issued_utc="2026-11-17T00:00:00+00:00",
        expires_utc="2026-11-18T00:00:00+00:00",
    )
    _refuse(p2_env, "go_expired", go_payload=go)
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        issued_utc="2026-11-20T00:00:00+00:00",
        expires_utc="2026-11-21T00:00:00+00:00",
    )
    _refuse(p2_env, "go_not_yet_valid", go_payload=go)


def test_authorize_rejects_unauthorized_operation(p2_env: SimpleNamespace) -> None:
    operations = [item for item in p2_env.plan.operations if item != "ocr"]
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"operations": operations},
    )
    _refuse(p2_env, "go_operation_unauthorized", go_payload=go)


def test_authorize_rejects_unauthorized_cost_center(p2_env: SimpleNamespace) -> None:
    centers = {key: value for key, value in CENTERS.items() if key != "independent"}
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"cost_centers_cny": centers},
    )
    _refuse(p2_env, "go_cost_center_unauthorized", go_payload=go)
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"cost_centers_cny": {**CENTERS, "answer_retrieval": 12.0, "independent": 1.0}},
    )
    _refuse(p2_env, "go_cost_center_below_plan", go_payload=go)


def test_authorize_rejects_stage_limit_shrunk(p2_env: SimpleNamespace) -> None:
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"stage_limits_cny": {P2_STAGE: 5.0}},
    )
    _refuse(p2_env, "go_stage_limit_below_plan", go_payload=go)
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"stage_limits_cny": {"S2-DEV": 20.0}},
    )
    _refuse(p2_env, "go_stage_limit_missing", go_payload=go)


def test_authorize_rejects_request_caps(p2_env: SimpleNamespace) -> None:
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"max_requests": 2000},
    )
    _refuse(p2_env, "go_max_requests_over_hard_cap", go_payload=go)
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"max_requests": 20},
    )
    _refuse(p2_env, "go_max_requests_below_plan", go_payload=go)
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"max_request_cny": 0.01},
    )
    _refuse(p2_env, "go_max_request_cny_below_plan", go_payload=go)


def test_authorize_rejects_plan_swap_with_same_nonce(p2_env: SimpleNamespace) -> None:
    go = _go_dict(_prefix_sha(p2_env.ledger), p2_env.plan, ledger_path=p2_env.ledger)
    other_plan = _plan(plan_id="P2-CAND-OTHER")
    _refuse(p2_env, "go_plan_id_mismatch", go_payload=go, plan=other_plan)
    # 同一 plan_id 改一个 item：摘要不同，同一 GO/nonce 不能复用。
    mutated = _plan_dict()
    mutated["items"][-1]["requests"] = 2
    mutated_plan = P2RunPlan.from_dict(mutated)
    assert mutated_plan.plan_sha256 != p2_env.plan.plan_sha256
    _refuse(p2_env, "go_plan_sha256_mismatch", go_payload=go, plan=mutated_plan)


def test_authorize_rejects_ledger_prefix_change(p2_env: SimpleNamespace) -> None:
    _authorize(p2_env)  # 改账本之前是可授权的
    lines = p2_env.ledger.read_text(encoding="utf-8").splitlines()
    history = json.loads(lines[0])
    history["accounted_cny"] = 0.0301
    p2_env.ledger.write_text(
        "\n".join([json.dumps(history, ensure_ascii=False)] + lines[1:]) + "\n", encoding="utf-8"
    )
    _refuse(p2_env, "go_ledger_binding_mismatch")


def test_authorize_rejects_missing_identity(p2_env: SimpleNamespace) -> None:
    go = _go_dict(_prefix_sha(p2_env.ledger), p2_env.plan, ledger_path=p2_env.ledger, nonce="short")
    _refuse(p2_env, "go_nonce_invalid", go_payload=go)
    go = _go_dict(_prefix_sha(p2_env.ledger), p2_env.plan, ledger_path=p2_env.ledger)
    del go["issued_by"]
    _refuse(p2_env, "field_missing", go_payload=go)
    go = _go_dict(_prefix_sha(p2_env.ledger), p2_env.plan, ledger_path=p2_env.ledger, issued_by="   ")
    _refuse(p2_env, "text_invalid", go_payload=go)
    go = _go_dict(_prefix_sha(p2_env.ledger), p2_env.plan, ledger_path=p2_env.ledger)
    del go["scope"]["plan_sha256"]
    _refuse(p2_env, "field_missing", go_payload=go)


def test_authorize_rejects_budget_mismatch_and_history_change(p2_env: SimpleNamespace) -> None:
    _refuse(
        p2_env,
        "budget_total_mismatch",
        budget_payload={"limit_cny": 20.0, "stages": {P2_STAGE: STAGE_LIMIT_CNY}},
    )
    _refuse(
        p2_env,
        "budget_stage_missing",
        budget_payload={"limit_cny": TOTAL_LIMIT_CNY, "stages": {"S2-DEV": 19.97}},
    )
    _refuse(
        p2_env,
        "budget_stage_below_plan",
        budget_payload={"limit_cny": TOTAL_LIMIT_CNY, "stages": {P2_STAGE: 1.0}},
    )
    _refuse(
        p2_env,
        "budget_history_mismatch",
        budget_payload={
            "limit_cny": TOTAL_LIMIT_CNY,
            "stages": {P2_STAGE: STAGE_LIMIT_CNY},
            "historical_conservative_accounted_cny": 0.05,
        },
    )


def test_authorize_env_total_limit_guard(p2_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(live_authorization.TOTAL_LIMIT_ENV, "20.0")
    _refuse(p2_env, "env_total_limit_mismatch")
    monkeypatch.delenv(live_authorization.TOTAL_LIMIT_ENV)
    _refuse(p2_env, "env_total_limit_missing")


def test_authorize_memory_payloads_are_not_production(p2_env: SimpleNamespace) -> None:
    go = _go_dict(_prefix_sha(p2_env.ledger), p2_env.plan, ledger_path=p2_env.ledger)
    budget = {"limit_cny": TOTAL_LIMIT_CNY, "stages": {P2_STAGE: STAGE_LIMIT_CNY}}
    auth = _authorize(p2_env, go_payload=go, budget_payload=budget)
    assert auth.production_ready is False
    assert auth.budget_sha256 == c.payload_sha256(budget)


def test_authorize_rejects_snapshot_from_other_ledger(p2_env: SimpleNamespace, tmp_path: Path) -> None:
    other = tmp_path / "other-ledger.jsonl"
    _write_ledger(other)
    snapshot = _snapshot()
    forged = P2LedgerSnapshot.from_dict(
        {**snapshot.as_dict(), "ledger_path": str(other)}
    )
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        _authorize(p2_env, ledger_snapshot=forged)
    assert excinfo.value.reason == "snapshot_ledger_path_not_fixed"


# --------------------------------------------------------------------------- #
# 5. 门控：合法 Mock 路径 + 每次发送前拒绝 + 保守留账 + 零自动重试
# --------------------------------------------------------------------------- #


def test_gate_legal_mock_request_full_path(p2_env: SimpleNamespace) -> None:
    """合法路径必须真的能走通：校验 -> 预留 -> 假发送 -> 假结算（不是把请求全关掉）。"""
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    assert len(transport) == 0  # 发送前还没有任何 HTTP
    assert ticket.cost_center == "answer_retrieval"
    assert ticket.kind == "chat"
    assert ticket.bound_cny == pytest.approx(CHAT_BOUND_CNY)
    gate.confirm_before_send(ticket)
    transport.send(ticket)
    charge = gate.settle_success(ticket, evidence=_chat_evidence(ticket))
    assert charge == pytest.approx(0.004)
    assert len(transport) == 1

    events = _events(p2_env.ledger)
    assert [event["event"] for event in events] == ["historical_import", "reserved", "result"]
    reserved, result = events[1], events[2]
    assert reserved["stage"] == P2_STAGE
    assert reserved["cost_center"] == "answer_retrieval"
    assert reserved["reserve_cny"] == pytest.approx(CHAT_BOUND_CNY)
    assert reserved["settlement_policy"]["version"] == "usage-conservative-v1"
    assert result["status"] == "succeeded"
    assert result["request_id"] == ticket.request_id
    assert result["conservative_charge_cny"] == pytest.approx(0.004)

    summary = BudgetLedger(
        p2_env.ledger, p2_env.budget, stage=P2_STAGE, stage_limit_cny=STAGE_LIMIT_CNY, max_requests=1000
    ).summary()
    assert summary.accounted_cny == pytest.approx(HISTORY_CNY + 0.004, abs=1e-9)
    assert summary.center_accounted_cny["answer_retrieval"] == pytest.approx(0.004, abs=1e-9)
    assert summary.reservation_count == 1 and summary.result_count == 1

    receipt = gate.result()
    assert receipt.status == "succeeded"
    assert receipt.stop_code is None
    assert receipt.requests_planned == PLANNED_REQUESTS
    assert receipt.requests_reserved == 1 and receipt.requests_sent == 1
    assert receipt.reserved_cny == pytest.approx(CHAT_BOUND_CNY)
    assert receipt.settled_cny == pytest.approx(0.004)
    assert receipt.by_operation == {"answer": 1}
    assert receipt.production_ready is True


def test_gate_ocr_item_settles_at_fixed_price(p2_env: SimpleNamespace) -> None:
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    ticket = gate.begin("ocr-D07-p1")
    assert ticket.operation == "ocr" and ticket.cost_center == "ocr"
    assert ticket.bound_cny == pytest.approx(OCR_TEXT_PRICE_CNY)
    gate.confirm_before_send(ticket)
    transport.send(ticket)
    charge = gate.settle_success(ticket)
    assert charge == pytest.approx(OCR_TEXT_PRICE_CNY)
    result = _result_events(p2_env.ledger)[-1]
    assert result["status"] == "succeeded"
    assert result["conservative_charge_cny"] == pytest.approx(OCR_TEXT_PRICE_CNY)
    assert gate.result().by_center_cny["ocr"] == pytest.approx(OCR_TEXT_PRICE_CNY)


def test_gate_refuses_second_inflight_request(p2_env: SimpleNamespace) -> None:
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    gate.begin("answer-B0-Q01-t1")
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate.begin("answer-B0-Q03-t1")
    assert excinfo.value.reason == "request_inflight"
    assert _reserved_count(p2_env.ledger) == 1
    assert len(transport) == 0


def test_gate_refuses_unknown_item_and_foreign_ticket(p2_env: SimpleNamespace) -> None:
    gate = _open_gate(p2_env)
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate.begin("no-such-item")
    assert excinfo.value.reason == "item_unknown"
    assert _reserved_count(p2_env.ledger) == 0

    ticket = gate.begin("answer-B0-Q01-t1")
    other = _open_gate(p2_env)
    with pytest.raises(p2a.P2GateError) as excinfo:
        other.confirm_before_send(ticket)
    assert excinfo.value.reason == "ticket_not_inflight"
    gate.confirm_before_send(ticket)
    gate.settle_success(ticket, evidence=_chat_evidence(ticket))
    # 同一张票不能重复结算（不得重复记账）。
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate.settle_success(ticket, evidence=_chat_evidence(ticket))
    assert excinfo.value.reason == "ticket_not_inflight"


def test_gate_expired_before_send_is_conservative(p2_env: SimpleNamespace) -> None:
    """预留已发生、发送前 GO 过期：不发送、不回 0、不擅自释放，保留请求身份。"""
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    with pytest.raises(p2a.P2SendRefused) as excinfo:
        gate.confirm_before_send(ticket, now=NOW + timedelta(days=2))
    refusal = excinfo.value
    assert refusal.reason == "authorization_expired"
    assert refusal.reservation_id == ticket.reservation_id
    assert refusal.request_id == ticket.request_id
    assert refusal.cost_center == "answer_retrieval"
    assert len(transport) == 0
    assert _reserved_count(p2_env.ledger) == 1
    results = _result_events(p2_env.ledger)
    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert results[0]["reservation_id"] == ticket.reservation_id
    assert results[0]["request_id"] == ticket.request_id
    assert results[0]["error_code"] == "P2_PRE_SEND_REFUSED:authorization_expired"
    assert results[0]["conservative_charge_cny"] == pytest.approx(CHAT_BOUND_CNY)
    summary = BudgetLedger(
        p2_env.ledger, p2_env.budget, stage=P2_STAGE, stage_limit_cny=STAGE_LIMIT_CNY, max_requests=1000
    ).summary()
    assert summary.accounted_cny == pytest.approx(HISTORY_CNY + CHAT_BOUND_CNY, abs=1e-9)
    receipt = gate.result()
    assert receipt.status == "blocked"
    assert receipt.stop_code == "authorization_expired"
    assert receipt.requests_sent == 0
    assert receipt.settled_cny == pytest.approx(CHAT_BOUND_CNY)


def test_gate_plan_edit_before_send_refused(p2_env: SimpleNamespace) -> None:
    gate = _open_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    go = json.loads(p2_env.go.read_text(encoding="utf-8"))
    go["scope"]["plan_sha256"] = "0" * 64
    p2_env.go.write_text(json.dumps(go, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(p2a.P2SendRefused) as excinfo:
        gate.confirm_before_send(ticket)
    assert excinfo.value.reason == "plan_sha256_changed"
    assert _reserved_count(p2_env.ledger) == 1


def test_gate_operation_withdrawn_before_send_refused(p2_env: SimpleNamespace) -> None:
    gate = _open_gate(p2_env)
    ticket = gate.begin("ocr-D07-p1")
    go = json.loads(p2_env.go.read_text(encoding="utf-8"))
    go["scope"]["operations"] = [op for op in go["scope"]["operations"] if op != "ocr"]
    p2_env.go.write_text(json.dumps(go, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(p2a.P2SendRefused) as excinfo:
        gate.confirm_before_send(ticket)
    assert excinfo.value.reason == "operation_unauthorized"


def test_gate_ledger_prefix_change_before_send_refused(p2_env: SimpleNamespace) -> None:
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    lines = p2_env.ledger.read_text(encoding="utf-8").splitlines()
    history = json.loads(lines[0])
    history["accounted_cny"] = 0.0301
    p2_env.ledger.write_text(
        "\n".join([json.dumps(history, ensure_ascii=False)] + lines[1:]) + "\n", encoding="utf-8"
    )
    with pytest.raises(p2a.P2SendRefused) as excinfo:
        gate.confirm_before_send(ticket)
    assert excinfo.value.reason == "ledger_prefix_mismatch"
    assert len(transport) == 0


def test_gate_stops_after_failure_without_retry(p2_env: SimpleNamespace) -> None:
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    gate.confirm_before_send(ticket)
    transport.send(ticket)
    gate.settle_failure(ticket, error_code="CHAT_UNAVAILABLE", http_status=503)
    assert gate.stopped_reason == "CHAT_UNAVAILABLE"
    assert len(transport) == 1
    before = _reserved_count(p2_env.ledger)
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate.begin("answer-B0-Q03-t1")
    assert excinfo.value.reason == "gate_stopped"
    assert _reserved_count(p2_env.ledger) == before
    receipt = gate.result()
    assert receipt.status == "blocked"
    assert receipt.stop_code == "CHAT_UNAVAILABLE"
    assert receipt.requests_sent == 1
    assert receipt.settled_cny == pytest.approx(CHAT_BOUND_CNY)
    failed = _result_events(p2_env.ledger)[-1]
    assert failed["status"] == "failed" and failed["http_status"] == 503
    assert failed["conservative_charge_cny"] == pytest.approx(CHAT_BOUND_CNY)


def test_gate_runtime_request_cap_counts_across_kinds(p2_env: SimpleNamespace) -> None:
    """累计请求上限来自账本计数（跨 kind/跨进程），换 kind 或成本中心都不能绕过。"""
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    for index in range(999):
        _append_reserved(
            p2_env.ledger,
            rid=f"other{index:04d}",
            stage=P2_STAGE,
            kind=("chat", "embedding", "ocr")[index % 3],
            reserve=0.00000001,
            cost_center=("answer_retrieval", "ocr", "judge")[index % 3],
        )
    first = gate.begin("answer-B0-Q01-t1")
    gate.confirm_before_send(first)
    transport.send(first)
    gate.settle_success(first, evidence=_chat_evidence(first))
    assert _reserved_count(p2_env.ledger) == 1000
    before = _reserved_count(p2_env.ledger)
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate.begin("answer-B0-Q03-t1")
    assert excinfo.value.reason == "request_limit"
    assert _reserved_count(p2_env.ledger) == before
    assert len(transport) == 1


def test_gate_refuses_when_center_room_gone(p2_env: SimpleNamespace) -> None:
    """授权后别的进程吃掉 OCR 中心余量：本次预留前就被拒（HTTP=0，无新预留）。"""
    transport = FakeTransport()
    gate = _open_gate(p2_env)
    _append_reserved(p2_env.ledger, rid="other-ocr", stage=P2_STAGE, kind="ocr", reserve=2.6, cost_center="ocr")
    before = _reserved_count(p2_env.ledger)
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate.begin("ocr-D07-p1")
    assert excinfo.value.reason == "center_budget_exceeded"
    assert _reserved_count(p2_env.ledger) == before
    assert len(transport) == 0
    assert gate.stopped_reason is None


def test_gate_refuses_unattributed_stage_spend(p2_env: SimpleNamespace) -> None:
    gate = _open_gate(p2_env)
    _append_reserved(p2_env.ledger, rid="other-nocenter", stage=P2_STAGE, reserve=0.1, cost_center=None)
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate.begin("answer-B0-Q01-t1")
    assert excinfo.value.reason == "center_accounting_inconsistent"
    assert _reserved_count(p2_env.ledger) == 1


def test_gate_refuses_unregistered_center_label(p2_env: SimpleNamespace) -> None:
    """T203 小加固（T201 遗留 ②）：账本事实里的中心标签必须 ⊆ COST_CENTERS。

    未注册标签既不能领额度，也不能靠"合计相等"混过归属检查——否则拼错/伪造的中心可以
    绕开四个中心各自的硬顶。
    """
    gate = _open_gate(p2_env)
    with pytest.raises(p2a.P2GateError) as excinfo:
        gate._assert_center_accounting(
            {"center_accounted": {"rogue_center": 0.1}, "stage_accounted": 0.1}
        )
    assert excinfo.value.reason == "cost_center_unregistered"
    assert _reserved_count(p2_env.ledger) == 0


def test_gate_rejects_budget_file_that_differs_from_authorized_payload(p2_env: SimpleNamespace) -> None:
    """固定预算文件与授权用的预算对象必须是同一份，否则“授权额度”和“真账额度”会分叉。"""
    payload = {"limit_cny": TOTAL_LIMIT_CNY, "stages": {P2_STAGE: 19.0}}
    with pytest.raises(p2a.P2AuthorizationError) as excinfo:
        p2a.P2Gate.open(
            p2_env.plan,
            go_payload=p2_env.go,
            budget_payload=payload,
            now=NOW,
            run_id="p2run-mismatch",
        )
    assert excinfo.value.reason in ("budget_file_mismatch", "budget_stage_below_plan")


def test_ledger_cost_center_accounting_is_append_only(p2_env: SimpleNamespace) -> None:
    """账本层的中心归属：预留时原子落盘，结算后按重算额聚合，非法标签拒绝。"""
    book = BudgetLedger(
        p2_env.ledger, p2_env.budget, stage=P2_STAGE, stage_limit_cny=STAGE_LIMIT_CNY, max_requests=1000
    )
    reservation = book.reserve(
        kind="chat",
        provider="deepseek",
        model="deepseek-flash",
        max_cny=0.018688,
        request_sha256="b" * 64,
        cost_center="judge",
    )
    assert _events(p2_env.ledger)[-1]["cost_center"] == "judge"
    book.settle(reservation, status="failed", error_code="UNIT_TEST", request_id="unit")
    summary = book.summary()
    assert summary.center_accounted_cny["judge"] == pytest.approx(0.018688, abs=1e-9)
    assert summary.stage_accounted_cny == pytest.approx(0.018688, abs=1e-9)
    with pytest.raises(BudgetLedgerInvalid):
        book.reserve(
            kind="chat",
            provider="deepseek",
            model="deepseek-flash",
            max_cny=0.018688,
            request_sha256="c" * 64,
            cost_center="bad center",
        )


def test_p1_gate_rejects_p2_stage(p2_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """旧 P1 入口（rag/chat 授权）默认拒绝 P2 阶段：OCR/judge 不能借旧 GO 偷渡。"""
    monkeypatch.setattr(live_authorization, "SHARED_LEDGER_PATH", p2_env.ledger)
    monkeypatch.setattr(live_authorization, "SHARED_BUDGET_PATH", p2_env.budget)
    monkeypatch.setattr(live_authorization, "PRODUCT_GO_PATH", p2_env.go)
    with pytest.raises(live_authorization.LiveGateError):
        live_authorization.load_live_authorization(stage=P2_STAGE, service="rag", now=NOW)
    with pytest.raises(live_authorization.LiveGateError):
        live_authorization.resolve_live_gate(
            stage=P2_STAGE,
            service="chat",
            requested_stage_limit_cny=1.0,
            requested_max_requests=1,
            now=NOW,
        )


# --------------------------------------------------------------------------- #
# 6. 候选交付物：必须与代码同一套口径，且明确不是可用授权
# --------------------------------------------------------------------------- #


def _load_candidate(name: str) -> dict:
    path = CANDIDATES / name
    assert path.is_file(), f"缺少候选文件 {name}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_candidate_artifacts_are_coherent_and_not_an_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """候选计划/GO/预算/快照能一起过预检与授权，但 production_ready 必须为 False。"""
    if not REAL_LEDGER.is_file():
        pytest.skip("本机没有共享账本文件，无法核对候选绑定的真实前缀")
    plan = P2RunPlan.from_dict(_load_candidate("p2-run-plan-v0_1.CANDIDATE-DRAFT.json"))
    go = _load_candidate("p2-live-go.CANDIDATE-DRAFT.json")
    budget = _load_candidate("budget.CANDIDATE-DRAFT.json")
    snapshot = P2LedgerSnapshot.from_dict(
        _load_candidate("p2-ledger-snapshot.CANDIDATE-DRAFT.json")
    )
    assert plan.total_requests == PLANNED_REQUESTS
    assert plan.worst_case_cny == pytest.approx(PLANNED_WORST_CASE_CNY)
    assert snapshot.source == "in-memory"
    assert snapshot.production_ready is False
    assert go["document"] == "P2-LIVE-GO"
    assert "DRAFT" in go["issued_by"].upper()
    assert "DRAFT" in go["authorization"].upper()
    assert budget["limit_cny"] == TOTAL_LIMIT_CNY
    assert budget["stages"][P2_STAGE] == pytest.approx(STAGE_LIMIT_CNY)

    preflight = p2a.preflight_p2(plan, snapshot)
    assert preflight.ok is True, preflight.reasons

    # 只读核对候选绑定的是仓库真实共享账本（固定路径指向真实文件，不写入）。
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", REAL_LEDGER)
    monkeypatch.setenv(live_authorization.TOTAL_LIMIT_ENV, str(TOTAL_LIMIT_CNY))
    auth = p2a.authorize_p2(
        plan,
        # 候选以**内存对象**推演：候选目录不是固定共享路径，绝不当作生产 GO 读取。
        go_payload=go,
        budget_payload=budget,
        ledger_snapshot=snapshot,
        now=NOW,
    )
    # 快照不是从固定共享账本读出的：候选只是推演，不能当真实准入。
    assert auth.production_ready is False
    assert auth.stage_limit_cny == pytest.approx(STAGE_LIMIT_CNY)
    assert auth.max_request_cny == pytest.approx(PLANNED_RESERVE_PEAK_CNY)
    assert auth.expires_utc - auth.issued_utc <= timedelta(days=14)


def test_candidate_budget_keeps_owner_arithmetic() -> None:
    """候选总额 20->40 且 P2-LIVE=20：历史 0.03 与原阶段分配原样保留，不挪用旧余额。"""
    budget = _load_candidate("budget.CANDIDATE-DRAFT.json")
    stages = budget["stages"]
    assert stages[P2_STAGE] == pytest.approx(20.0)
    assert stages["S2-DEV"] == pytest.approx(15.4)
    assert stages["P1-RETRIEVAL"] == pytest.approx(3.0)
    assert stages["later_shared_reserve"] == pytest.approx(1.57)
    assert budget["historical_conservative_accounted_cny"] == pytest.approx(0.03)
    total_stages = sum(
        value for stage, value in stages.items() if stage != P2_STAGE and value
    )
    assert total_stages + stages[P2_STAGE] + 0.03 == pytest.approx(40.0)


def test_candidate_snapshot_binds_the_real_shared_ledger() -> None:
    """候选快照必须绑定仓库真实的共享账本历史前缀（若本机没有该文件则跳过）。"""
    if not REAL_LEDGER.is_file():
        pytest.skip("本机没有共享账本文件")
    snapshot = _load_candidate("p2-ledger-snapshot.CANDIDATE-DRAFT.json")
    raw = REAL_LEDGER.read_bytes()
    assert snapshot["ledger_sha256"] == hashlib.sha256(raw).hexdigest()
    assert snapshot["historical_prefix_sha256"] == live_authorization.historical_prefix_sha256(
        REAL_LEDGER
    )
    assert snapshot["ledger_path"].endswith("live-ledger.jsonl")
    assert snapshot["reservation_count"] >= 505


def test_hard_max_requests_is_the_manager_recorded_1600(p2_env: SimpleNamespace) -> None:
    """D1（2026-11-11 经理落盘）：两处常量同值 1600；1600 可用、1601 拒绝。"""
    # 纯常量一致性钉值：这两处必须永远相等（原不变式保留）。
    assert c.HARD_MAX_REQUESTS == 1600
    assert live_authorization.MAX_GO_REQUESTS == 1600
    assert c.HARD_MAX_REQUESTS == live_authorization.MAX_GO_REQUESTS

    # 计划层：恰好 1600 可建，多 1 次即拒（安全阈值不放宽）。
    accepted_plan = P2RunPlan.from_dict(_plan_dict(max_requests=1600))
    assert accepted_plan.max_requests == 1600
    with pytest.raises(P2ContractError) as excinfo:
        P2RunPlan.from_dict(_plan_dict(max_requests=c.HARD_MAX_REQUESTS + 1))
    assert excinfo.value.reason == "request_cap_over_hard_limit"

    # GO 层：1600 可授权；1601 被硬顶拒（go_max_requests_over_hard_cap）。
    # 授权上限取 min(plan.max_requests, GO scope.max_requests)，所以两端都声明 1600。
    plan_1600 = P2RunPlan.from_dict(_plan_dict(max_requests=1600, plan_id="P2-CAND-1600"))
    go = _go_dict(
        _prefix_sha(p2_env.ledger),
        plan_1600,
        ledger_path=p2_env.ledger,
        scope={"max_requests": 1600},
    )
    assert _authorize(p2_env, plan=plan_1600, go_payload=go).max_requests == 1600
    over = _go_dict(
        _prefix_sha(p2_env.ledger),
        p2_env.plan,
        ledger_path=p2_env.ledger,
        scope={"max_requests": 1601},
    )
    _refuse(p2_env, "go_max_requests_over_hard_cap", go_payload=over)

