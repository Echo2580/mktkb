"""P2-T203：产品端到端运行器（隔离应用 + Mock 证据）的定向单元测试。

覆盖任务书 T203 的编排语义（产品路径本身在 ``test_p2_product_e2e.py`` 里断言）：
- dry-run 在没有 ``production_ready`` 时也能完整跑完，且真实请求恒为 0；
- 授权/计划/门之间的 fail-closed：过期、未绑定、请求上限、Mock 配真门；
- 门序（begin -> confirm_before_send -> settle）与"发送前拒绝"不产生任何产品发送；
- 取消 / 超时 / 产品 service_error / 计划缺项 一律停，向后不重试；
- 空跑与成功明确区分；holdout 只写聚合、临时 trace 被删除、产物里没有题干。

零真实调用：全模块 ``t09_network_guard``（复用既有外层网络闸门）把任何**外部**出站
变成测试失败；本文件只跑隔离目录里的 SQLite 与 ASGI 应用。
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门，不复制实现
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation import cli
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_authorization import P2SendRefused, preflight_p2
from mktkb.evaluation.p2_contracts import (
    CHAT_HOST,
    CHAT_MODEL,
    CHAT_PRICING_SOURCE,
    CHAT_PROVIDER,
    CHAT_REGION,
    COST_CENTERS,
    P2LedgerSnapshot,
    P2PriceProfile,
    P2RequestItem,
    P2RunPlan,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
)
from mktkb.evaluation.p2_runner import (
    build_dry_run_authorization,
    run_p2,
)
from mktkb.evaluation.product_adapter import (
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
    ProductPaths,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")


def asyncio_test(func):
    """仓库没有 pytest-asyncio：用同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
NONCE = "0f" * 16

RAG_QUESTION = "把城东店和城西店的宣传海报记录都列出来"
LEGACY_QUESTION = "活动策划需要哪些步骤？"
UNKNOWN_QUESTION = "火星店的宣传海报在哪里？"
FOLLOWUP_QUESTION = "那城北店呢？"


# --------------------------------------------------------------------------- #
# 计划 / 快照 / 授权 / 数据集
# --------------------------------------------------------------------------- #


def chat_profile() -> P2PriceProfile:
    return P2PriceProfile(
        kind="chat",
        model=CHAT_MODEL,
        provider=CHAT_PROVIDER,
        host=CHAT_HOST,
        region=CHAT_REGION,
        pricing_source=CHAT_PRICING_SOURCE,
        input_price_per_million_cny=2.0,
        output_price_per_million_cny=8.0,
        prompt_tokens_cap=6144,
        completion_tokens_cap=800,
    )


def make_case(
    case_id: str,
    question: str,
    *,
    stratum: str = "paraphrase",
    turns: tuple[Mapping[str, Any], ...] = (),
) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite="p2-holdout",
        split="holdout",
        stratum=stratum,
        business_date="2026-11-10",
        question=question,
        turns=turns,
        label_version="synthetic-v1",
    )


def turn_questions(case: CaseSpec) -> tuple[str, ...]:
    if len(case.turns) < 2:
        return (case.question,)
    return tuple(str(turn.get("question") or turn.get("text")) for turn in case.turns)


def make_plan(cases: tuple[CaseSpec, ...], *, plan_id: str = "p2-t203-unit") -> P2RunPlan:
    items = []
    for case in cases:
        for turn in range(1, len(turn_questions(case)) + 1):
            items.append(
                P2RequestItem(
                    item_id=f"{case.case_id}:turn{turn}:answer",
                    operation="answer",
                    cost_center="answer_retrieval",
                    case_id=case.case_id,
                    turn=turn,
                    page=0,
                    requests=1,
                    price_profile=chat_profile(),
                    expected_success_cny=0.001,
                )
            )
    return P2RunPlan(
        schema_version="p2-run-plan/v0.1",
        plan_id=plan_id,
        plan_version="v1",
        mode="end_to_end",
        stage="P2-LIVE",
        created_utc="2026-11-10T00:00:00+00:00",
        project_total_limit_cny=40.0,
        stage_limit_cny=20.0,
        max_requests=1000,
        cost_centers_cny={
            "answer_retrieval": 12.0,
            "ocr": 3.0,
            "judge": 3.0,
            "independent": 2.0,
        },
        items=tuple(items),
    )


def make_snapshot(plan: P2RunPlan) -> P2LedgerSnapshot:
    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        ledger_path="in-memory:unit",
        ledger_sha256="0" * 64,
        historical_prefix_sha256="1" * 64,
        budget_sha256="2" * 64,
        total_limit_cny=float(plan.project_total_limit_cny),
        historical_accounted_cny=15.0709445,
        accounted_cny=15.0709445,
        reservation_count=505,
        result_count=505,
        stage_allocations_cny={"S2-DEV": 3.0, "P1-RETRIEVAL": 2.0, "P2-LIVE": 20.0},
        p2_stage_accounted_cny=0.0,
        p2_center_accounted_cny={center: 0.0 for center in COST_CENTERS},
        source="in-memory",
    )


def dry_run_authorization(plan: P2RunPlan, *, now: datetime = NOW):
    preflight = preflight_p2(plan, make_snapshot(plan))
    assert preflight.ok, preflight.reasons
    assert preflight.production_ready is False, "内存快照永远不是 production_ready"
    return build_dry_run_authorization(plan, preflight, now=now, nonce=NONCE)


def make_dataset(
    cases: tuple[CaseSpec, ...],
    *,
    visibility: str = "public",
    manifest_sha256: str = "b" * 64,
) -> P2RunDataset:
    strata: dict[str, int] = {}
    for case in cases:
        strata[case.stratum] = strata.get(case.stratum, 0) + 1
    return P2RunDataset(
        visibility=visibility,
        cases=cases,
        identity={
            "dataset_version": "p2-synthetic-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": manifest_sha256,
            "case_count": len(cases),
            "strata": strata,
        },
    )


def make_ingest_plan() -> P2IngestPlan:
    return P2IngestPlan(
        sources=(
            IngestSource(path=D01),
            IngestSource(path=D04),
        ),
        label="t203-unit",
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------- #
# 测试替身：桩门 / 非 Mock 适配器（只用于"发送前就应该被拒绝"的路径）
# --------------------------------------------------------------------------- #


@dataclass
class StubGate:
    """记录 begin/confirm/settle 调用；``is_mock_gate=True`` 表示**不是**真实 P2Gate。"""

    is_mock_gate: bool = True
    fail_confirm: str | None = None
    calls: list[str] = field(default_factory=list)
    began: list[str] = field(default_factory=list)
    settled: list[dict[str, Any]] = field(default_factory=list)

    def begin(self, item_id: str, **_kwargs: Any) -> "_StubTicket":
        self.calls.append("begin")
        self.began.append(item_id)
        return _StubTicket(item_id=item_id)

    def confirm_before_send(self, ticket: "_StubTicket", **_kwargs: Any) -> "_StubTicket":
        self.calls.append("confirm_before_send")
        if self.fail_confirm is not None:
            raise P2SendRefused(self.fail_confirm, ticket=_RefusedTicket(ticket.item_id))
        return ticket

    def settle_success(self, ticket: "_StubTicket", **kwargs: Any) -> float:
        self.calls.append("settle_success")
        self.settled.append({"item_id": ticket.item_id, "status": "succeeded", **kwargs})
        return 0.018688

    def settle_failure(self, ticket: "_StubTicket", **kwargs: Any) -> None:
        self.calls.append("settle_failure")
        self.settled.append({"item_id": ticket.item_id, "status": "failed", **kwargs})


@dataclass
class _StubTicket:
    item_id: str
    bound_cny: float = 0.018688

    def as_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": "resv-stub",
            "request_id": "p2req-stub",
            "item_id": self.item_id,
            "cost_center": "answer_retrieval",
            "operation": "answer",
            "bound_cny": self.bound_cny,
        }


@dataclass
class _RefusedTicket:
    """与 P2RequestTicket 同形的拒绝回执（P2SendRefused 会读三个属性）。"""

    item_id: str
    reservation_id: str = "resv-refused"
    request_id: str = "p2req-refused"
    cost_center: str = "answer_retrieval"

    def as_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": "resv-refused",
            "request_id": "p2req-refused",
            "item_id": self.item_id,
            "cost_center": "answer_retrieval",
            "operation": "answer",
            "bound_cny": 0.018688,
        }


class RealishAdapter:
    """``is_mock=False`` 的适配器替身：只用于验证"没有 production_ready 就不许发送"。"""

    def __init__(self, out_dir: Path, dataset: P2RunDataset) -> None:
        self.paths = ProductPaths.of(out_dir)
        self.dataset = dataset
        self.ingest_plan = None
        self.ingest_receipts: list[Any] = []
        self.turn_timeout_seconds = 60.0
        self.trace_enabled = False
        self.trace_content_mode = "off"
        self.purge_traces_on_close = False
        self.asks: list[str] = []

    @property
    def is_mock(self) -> bool:
        return False

    def provider_calls(self) -> dict[str, Any]:
        return {"chat": {"calls": 0}, "embedding": {"calls": 0}, "rerank": {"calls": 0}}

    def index_status(self) -> dict[str, Any]:
        return {}

    async def open_conversation(self, **_kwargs: Any) -> str:
        return "00000000-0000-4000-8000-000000000000"

    async def ask_turn(self, question: str, **_kwargs: Any):  # noqa: ANN201 - 替身
        self.asks.append(question)
        raise AssertionError("真实适配器替身不该被调用：发送门必须先在授权阶段拒绝")

    def purge_traces(self) -> list[str]:
        return []


# --------------------------------------------------------------------------- #
# 1. dry-run：没有 production_ready 也能跑完，真实请求 0
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_dry_run_completes_without_production_ready(tmp_path: Path) -> None:
    multi_turn = make_case(
        "P02",
        FOLLOWUP_QUESTION,
        turns=(
            {"role": "user", "question": RAG_QUESTION},
            {"role": "user", "question": FOLLOWUP_QUESTION},
        ),
        stratum="multi_turn",
    )
    cases = (
        make_case("P01", RAG_QUESTION),
        make_case("P03", LEGACY_QUESTION),
        make_case("P04", UNKNOWN_QUESTION, stratum="negative"),
        multi_turn,
    )
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    dataset = make_dataset(cases)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "run", chat=chat, dataset=dataset, ingest_plan=make_ingest_plan()
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
        calls = adapter.provider_calls()
    finally:
        await adapter.close()

    # 授权结果本身没有 production_ready，dry-run 仍必须完整跑完（不是"跑不了"）。
    assert authorization.production_ready is False
    assert result.status == "succeeded", result.as_dict()
    assert result.stop_code is None
    assert result.production_ready is False
    assert result.requests_reserved == 0 and result.requests_sent == 0
    assert result.reserved_cny == 0.0 and result.settled_cny == 0.0
    assert result.by_operation == {}

    run_dir = adapter.paths.run_dir
    manifest = read_json(run_dir / "run_manifest.json")
    summary = read_json(run_dir / "summary.json")
    gate = read_json(run_dir / "gate.json")
    receipts = read_json(run_dir / "run_result.json")
    case_rows = read_jsonl(run_dir / "cases.jsonl")
    request_rows = read_jsonl(run_dir / "requests.jsonl")

    # 身份绑定：dataset / manifest / plan / 授权 / provider / 代码。
    assert manifest["dataset"]["dataset_version"] == "p2-synthetic-v1"
    assert manifest["dataset"]["manifest_sha256"] == "b" * 64
    assert manifest["dataset"]["case_count"] == 4
    assert manifest["plan"]["plan_sha256"] == plan.plan_sha256
    assert manifest["authorization"]["go_document"] == "P2-DRY-RUN"
    assert manifest["authorization"]["production_ready"] is False
    assert manifest["authorization"]["go_nonce_len"] == len(NONCE)
    assert manifest["providers"]["chat"]["transport"] == "httpx.MockTransport"
    assert manifest["providers"]["chat"]["outbound_network"] == 0
    assert manifest["execution"] == "dry_run"
    for name, digest in manifest["pipeline"]["code_sha256"].items():
        assert len(str(digest)) == 64, name

    # 产物齐全（run_manifest / 公开 cases / summary / 请求回执 / gate）。
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "run_result.json").is_file()
    assert receipts["status"] == "succeeded"
    assert gate["quality_gate"] == "deferred-to-T205"
    assert gate["real_sends_allowed"] is False
    assert all(check["ok"] for check in gate["checks"])

    # 逐题行与请求回执：每轮都有产品结果、trace 与"未计费"标记。
    assert len(case_rows) == 4
    assert summary["cases"] == {
        "planned": 4,
        "executed": 4,
        "with_error": 0,
        "not_executed": 0,
    }
    assert summary["turns"]["planned"] == 5 and summary["turns"]["executed"] == 5
    assert len(request_rows) == 5
    for row in request_rows:
        assert row["billed"] is False
        assert row["ticket"]["dry_run"] is True
        assert row["product"]["trace_id"]
    # 多轮：同一会话、两轮各自一条 trace。
    multi = next(row for row in case_rows if row["case_id"] == "P02")
    assert multi["turns_executed"] == 2
    assert len({turn["trace_id"] for turn in multi["turns"]}) == 2

    # 两条分支都经过产品入口（trace.path 由产品自己写），且确实调用过 provider。
    branches = summary["branches"]
    assert branches.get("rag", 0) >= 1
    assert branches.get("legacy", 0) >= 1
    assert calls["chat"]["calls"] >= 1
    assert calls["embedding"]["calls"] > 0
    assert calls["rerank"]["calls"] > 0
    assert summary["network"]["outbound_attempts"] == 0
    assert summary["requests"]["real_requests"] == 0
    assert summary["requests"]["billed_cny"] == 0.0


# --------------------------------------------------------------------------- #
# 2. 发送门：没有 production_ready 一律不发送
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_real_adapter_without_production_ready_never_sends(tmp_path: Path) -> None:
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    dataset = make_dataset(cases)
    adapter = RealishAdapter(tmp_path / "realish", dataset)
    gate = StubGate(is_mock_gate=False)

    result = await run_p2(
        plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
    )

    assert result.status == "blocked"
    assert result.stop_code == "production_not_ready"
    assert adapter.asks == []
    assert gate.calls == []
    gate_payload = read_json(adapter.paths.run_dir / "gate.json")
    assert gate_payload["real_sends_allowed"] is False
    failed = {check["name"] for check in gate_payload["checks"] if not check["ok"]}
    assert failed == {"production_ready"}
    assert read_json(adapter.paths.run_dir / "summary.json")["failure"]["stage"] == "authorization"


@asyncio_test
async def test_mock_adapter_cannot_be_paired_with_real_gate(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(tmp_path / "run", chat=chat, dataset=make_dataset(cases))
    gate = StubGate(is_mock_gate=False)  # 没有 is_mock_gate 标记 = 按真实门对待
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
        )
        calls = adapter.provider_calls()
    finally:
        await adapter.close()

    assert result.status == "blocked"
    assert result.stop_code == "mock_gate_requires_stub_gate"
    assert gate.calls == []
    assert calls["chat"]["calls"] == 0
    assert calls["embedding"]["calls"] == 0


# --------------------------------------------------------------------------- #
# 3. 门序：begin -> confirm -> 发送 -> settle（桩门，不产生资金事实）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_mock_gate_runs_full_send_sequence_without_billing(tmp_path: Path) -> None:
    cases = (make_case("P03", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "run", chat=chat, dataset=make_dataset(cases), ingest_plan=make_ingest_plan()
    )
    gate = StubGate(is_mock_gate=True)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
        )
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    assert gate.calls == ["begin", "confirm_before_send", "settle_success"]
    assert gate.began == ["P03:turn1:answer"]
    assert result.requests_reserved == 1 and result.requests_sent == 1
    assert result.by_operation == {"answer": 1}
    assert result.production_ready is False
    gate_payload = read_json(adapter.paths.run_dir / "gate.json")
    assert gate_payload["execution"] == "mock_gate"
    # 桩门不是真实账本：产物里仍然如实写"真实请求 0、计费 0"。
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["execution"] == "mock_gate"
    assert summary["requests"]["real_requests"] == 0
    assert summary["requests"]["billed_cny"] == 0.0


@asyncio_test
async def test_pre_send_refusal_stops_before_any_product_send(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "run", chat=chat, dataset=make_dataset(cases), ingest_plan=make_ingest_plan()
    )
    gate = StubGate(is_mock_gate=True, fail_confirm="authorization_expired")
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
        )
        calls = adapter.provider_calls()
    finally:
        await adapter.close()

    assert result.status in {"aborted", "blocked"}
    assert result.stop_code == "pre_send_refused"
    assert gate.calls == ["begin", "confirm_before_send"]
    # 关键：产品问答一次都没被调用（reserve 后失效也停在 HTTP 之前）。
    # embedding/rerank 里只有灌库建索引的那部分；问答路径的 chat/rerank 都是 0。
    assert calls["chat"]["calls"] == 0
    assert calls["rerank"]["calls"] == 0
    request_rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
    assert [row["status"] for row in request_rows] == ["refused_before_send"]
    assert "product" not in request_rows[0]
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["failure"]["stage"] == "gate_confirm"
    assert summary["failure"]["ticket"]["request_id"] == "p2req-refused"
    assert summary["cases"]["not_executed"] == 1


# --------------------------------------------------------------------------- #
# 4. 反例：超时 / 服务错误 / 取消 / 计划缺项 / 空跑
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_turn_timeout_stops_run_without_retry(tmp_path: Path) -> None:
    cases = (make_case("P03", LEGACY_QUESTION), make_case("P01", RAG_QUESTION))
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    chat = MockChatBackend(behaviors=(ChatBehavior(kind="delay", delay_seconds=1.0),))
    adapter = ProductEvalAdapter(
        tmp_path / "run",
        chat=chat,
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
        turn_timeout_seconds=0.2,
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
    finally:
        await adapter.close()

    assert result.status == "aborted"
    assert result.stop_code == "turn_timeout"
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["failure"]["stage"] == "product_wait"
    assert summary["failure"]["timeout_seconds"] == 0.2
    assert summary["cases"]["executed"] == 1
    assert summary["cases"]["not_executed"] == 1
    # 没有重试：只发生了一次 chat 调用。
    assert chat.call_count == 1


@asyncio_test
async def test_service_error_stops_and_does_not_pay_again(tmp_path: Path) -> None:
    cases = (make_case("P03", LEGACY_QUESTION), make_case("P01", RAG_QUESTION))
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    chat = MockChatBackend(behaviors=(ChatBehavior(kind="http_error", status_code=503),))
    adapter = ProductEvalAdapter(
        tmp_path / "run", chat=chat, dataset=make_dataset(cases), ingest_plan=make_ingest_plan()
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
    finally:
        await adapter.close()

    assert result.status == "aborted"
    assert result.stop_code == "product_service_error"
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["failure"]["stage"] == "product_answer"
    assert summary["failure"]["error_code"] == "MODEL_UNAVAILABLE"
    assert summary["cases"]["executed"] == 1 and summary["cases"]["not_executed"] == 1
    assert chat.call_count == 1  # 服务错误后不再有下一次付费尝试


@asyncio_test
async def test_cancel_between_cases_stops_without_extra_sends(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "run", chat=chat, dataset=make_dataset(cases), ingest_plan=make_ingest_plan()
    )
    seen: list[int] = []

    def cancel() -> bool:
        seen.append(1)
        return len(seen) > 1  # 第一个 case 之后取消

    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, cancel=cancel, now=NOW
        )
    finally:
        await adapter.close()

    assert result.status == "aborted"
    assert result.stop_code == "cancelled"
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["cases"]["executed"] == 1 and summary["cases"]["not_executed"] == 1
    assert summary["failure"]["stage"] == "cancel"


@asyncio_test
async def test_plan_item_missing_fails_closed(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    # 计划只覆盖第一题：第二题没有 answer 计划项，绝不能"顺手"发出去。
    partial = make_plan((cases[0],))
    authorization = dry_run_authorization(partial)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "run", chat=chat, dataset=make_dataset(cases), ingest_plan=make_ingest_plan()
    )
    try:
        result = await run_p2(
            partial, adapter=adapter, authorization=authorization, now=NOW
        )
    finally:
        await adapter.close()

    assert result.status == "aborted"
    assert result.stop_code == "plan_item_missing"
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["failure"]["stage"] == "plan"
    assert summary["cases"]["executed"] == 1 and summary["cases"]["not_executed"] == 1


@asyncio_test
async def test_empty_run_is_blocked_not_succeeded(tmp_path: Path) -> None:
    plan = make_plan((make_case("P01", RAG_QUESTION),))
    authorization = dry_run_authorization(plan)
    empty = make_dataset(())
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(tmp_path / "run", chat=chat, dataset=empty)
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
        calls = adapter.provider_calls()
    finally:
        await adapter.close()

    assert result.status == "blocked"
    assert result.stop_code == "no_case_executed"
    assert result.requests_sent == 0
    assert calls["chat"]["calls"] == 0
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["cases"]["executed"] == 0


# --------------------------------------------------------------------------- #
# 5. 授权失败必须早于灌库与发送
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_expired_authorization_blocks_before_ingest(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan, now=NOW - timedelta(hours=1))
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "run", chat=chat, dataset=make_dataset(cases), ingest_plan=make_ingest_plan()
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
        calls = adapter.provider_calls()
    finally:
        await adapter.close()

    assert result.status == "blocked"
    assert result.stop_code == "authorization_expired"
    assert adapter.ingest_receipts == []  # 没有灌库
    assert calls["embedding"]["calls"] == 0 and calls["chat"]["calls"] == 0


@asyncio_test
async def test_foreign_authorization_is_rejected(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION),)
    plan = make_plan(cases)
    foreign = dry_run_authorization(make_plan(cases, plan_id="another-plan"))
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(tmp_path / "run", chat=chat, dataset=make_dataset(cases))
    try:
        result = await run_p2(plan, adapter=adapter, authorization=foreign, now=NOW)
    finally:
        await adapter.close()

    assert result.status == "blocked"
    assert result.stop_code == "plan_authorization_mismatch"
    assert read_json(adapter.paths.run_dir / "gate.json")["checks"][0]["name"] == "plan_identity"


# --------------------------------------------------------------------------- #
# 5b. CLI：只加一个空跑子命令，预检不过就不跑
# --------------------------------------------------------------------------- #


def test_cli_p2_run_is_dry_run_and_refuses_unpreflighted_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = (make_case("P01", RAG_QUESTION),)
    plan = make_plan(cases)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False), encoding="utf-8"
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(make_snapshot(plan).as_dict(), ensure_ascii=False), encoding="utf-8"
    )
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        "\n".join(json.dumps(case.to_dict(), ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "cli-run"

    exit_code = cli.main(
        [
            "p2-run",
            "--plan",
            str(plan_path),
            "--snapshot",
            str(snapshot_path),
            "--out",
            str(out_dir),
            "--cases",
            str(cases_path),
            "--ingest",
            str(D01),
        ]
    )
    assert exit_code == 0, capsys.readouterr().out
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert printed["ok"] is True
    assert printed["status"] == "succeeded"
    assert printed["requests_sent"] == 0
    assert printed["execution"] == "dry_run"
    assert Path(printed["out_dir"]) == out_dir / "p2-run"
    assert (out_dir / "p2-run" / "run_manifest.json").is_file()

    # 预算里没有 P2-LIVE 阶段分配 -> 预检拒绝 -> 不跑、不写产物。
    bad_snapshot = make_snapshot(plan)
    bad_payload = bad_snapshot.as_dict()
    bad_payload["stage_allocations_cny"] = {"S2-DEV": 3.0}
    bad_path = tmp_path / "snapshot-bad.json"
    bad_path.write_text(json.dumps(bad_payload, ensure_ascii=False), encoding="utf-8")
    refused_dir = tmp_path / "cli-refused"
    refused = cli.main(
        [
            "p2-run",
            "--plan",
            str(plan_path),
            "--snapshot",
            str(bad_path),
            "--out",
            str(refused_dir),
            "--cases",
            str(cases_path),
            "--ingest",
            str(D01),
        ]
    )
    assert refused == 3
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert "stage_allocation_missing" in payload["reasons"]
    assert not refused_dir.exists()


# --------------------------------------------------------------------------- #
# 6. holdout：只产聚合 + 临时 trace 受保护
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_holdout_run_writes_aggregate_only_and_purges_traces(tmp_path: Path) -> None:
    cases = (
        make_case("H01", RAG_QUESTION),
        make_case("H02", LEGACY_QUESTION, stratum="multi_turn"),
    )
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    dataset = make_dataset(cases, visibility="holdout", manifest_sha256="c" * 64)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "holdout",
        chat=chat,
        dataset=dataset,
        ingest_plan=make_ingest_plan(),
        purge_traces_on_close=True,
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    run_dir = adapter.paths.run_dir
    assert (run_dir / "holdout_aggregate.json").is_file()
    assert not (run_dir / "cases.jsonl").exists()
    assert not (run_dir / "requests.jsonl").exists()
    aggregate = read_json(run_dir / "holdout_aggregate.json")
    assert aggregate["detail_export"] is False
    assert aggregate["dataset"]["manifest_sha256"] == "c" * 64
    assert aggregate["cases"]["executed"] == 2
    assert sum(aggregate["branches"].values()) == 2
    assert aggregate["turns"]["with_product_result"] == 2
    summary = read_json(run_dir / "summary.json")
    assert summary["holdout"] == {
        "aggregate_only": True,
        "trace_retention": "purged-at-close",
    }
    # 临时 trace 已删除，且任何产物里都找不到题干/H2 case id。
    assert not adapter.paths.trace_db.exists()
    for path in run_dir.iterdir():
        raw = path.read_text(encoding="utf-8")
        for secret in (RAG_QUESTION, LEGACY_QUESTION, "H01", "H02"):
            assert secret not in raw, f"{path.name} 泄漏受限内容: {secret}"
