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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门，不复制实现
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation import cli
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_authorization import P2Gate, P2SendRefused, preflight_p2
from mktkb.evaluation.p2_contracts import (
    CHAT_HOST,
    CHAT_MODEL,
    CHAT_PRICING_SOURCE,
    CHAT_PROVIDER,
    CHAT_REGION,
    COST_CENTERS,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
    P2_RUN_RESULT_SCHEMA_VERSION,
    P2ContractError,
    P2LedgerSnapshot,
    P2PriceProfile,
    P2RequestItem,
    P2RunPlan,
    P2RunResult,
)
from mktkb.evaluation.p2_runner import (
    P2RunError,
    P2RunLedger,
    _money_split,
    build_dry_run_authorization,
    is_real_p2_gate,
    run_p2,
)
from mktkb.evaluation.p2_scoring import (
    build_gate_rows,
    build_gate_run,
    citation_evidence_status,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    score_public_case as score_p2_public_case,
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
from mktkb.rag import providers as rag_providers

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
        # 替身也必须交出**实测**字段（runner 不认常量兜底）：这里确实一次都没调过 provider。
        # A1：network.detail 必须是顶层出站的分解（chat + RAG POST），而不是第二份真值。
        return {
            "chat": {"calls": 0, "outbound_network": 0},
            "embedding": {"calls": 0, "outbound_network": 0},
            "rerank": {"calls": 0, "outbound_network": 0},
            "outbound_network": 0,
            "network": {
                "outbound_attempts": 0,
                "chat_outbound_attempts": 0,
                "rag_provider_posts": 0,
                "mock_intercepted": 0,
            },
        }

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
    # F1：出站数是**实测**的（Mock 链上被传输层接住，计到拦截而不是出站）。
    assert manifest["providers"]["outbound_network"] == 0
    assert manifest["providers"]["network"]["mock_intercepted"] > 0
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

    # F4：P04（火星店）这一轮是产品 not_found 且 **0 次 chat**——从逐轮实测计数断言，
    # 不靠"总结里写一句"。
    p04 = next(row for row in case_rows if row["case_id"] == "P04")
    assert p04["turns"][0]["kind"] == "not_found"
    p04_request = next(row for row in request_rows if row["case_id"] == "P04")
    assert p04_request["product"]["kind"] == "not_found"
    assert p04_request["provider_calls"]["chat"] == 0
    # 同一份产物里，RAG/legacy 轮确实调过 chat（否则上面那条断言没有证伪力）。
    assert any(row["provider_calls"]["chat"] > 0 for row in request_rows)

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
    # 发送前有两处不通过：没有 production_ready，且这个门不是真实 P2Gate（F2）。
    failed = {check["name"] for check in gate_payload["checks"] if not check["ok"]}
    assert failed == {"production_ready", "live_gate"}
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
    # 桩门结算的金额进入门回执（success 路径不再记 0 元），但没有任何真实出站；
    # 因此 summary 的实测口径仍然是 real_requests=0 / billed_cny=0（见下）。
    assert result.settled_cny == 0.018688
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
    assert summary["holdout"]["aggregate_only"] is True
    assert summary["holdout"]["trace_retention"] == "purged-at-close"
    # A4(F3-a)：这是策略标签，不是"已删"的测量结论；测量证据是 close() 的 seal_receipt。
    assert summary["holdout"]["question_store"] == "policy:delete-at-close"
    assert summary["holdout"]["question_store_measurement"].startswith("close() 返回 seal_receipt")
    # F6：业务库（会话/消息/请求里的题干明文）在 close 时删除，不是"留着等 T206"。
    assert adapter.seal_receipt == {
        "question_store": "deleted",
        "removed": [str(adapter.paths.business_db)],
    }
    assert not adapter.paths.business_db.exists()
    # 临时 trace 已删除，且任何产物里都找不到题干/H2 case id。
    assert not adapter.paths.trace_db.exists()
    for path in run_dir.iterdir():
        raw = path.read_text(encoding="utf-8")
        for secret in (RAG_QUESTION, LEGACY_QUESTION, "H01", "H02"):
            assert secret not in raw, f"{path.name} 泄漏受限内容: {secret}"


# --------------------------------------------------------------------------- #
# 7. R1 加固：F1 实测计数 / F2 live 真门 / F3 holdout fail-closed / F5 / F6
# --------------------------------------------------------------------------- #

#: 哨兵题干：只要它还出现在 out_dir 里，就说明 holdout 的题干明文没被封存（F6）。
HOLDOUT_SENTINEL = "H2哨兵题干9F4A：火星店的宣传海报到底在哪里？"
#: 第二轮仍会真的调用 chat 的问题（用于"多轮中间失败"保留现场，F5）。
SECOND_CHAT_QUESTION = "活动策划流程有哪些环节？"


def files_containing(root: Path, text: str) -> list[str]:
    """在目录里按字节找明文（含 sqlite 等二进制文件），返回命中的相对路径。"""
    needle = text.encode("utf-8")
    hits: list[str] = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:  # pragma: no cover - 临时目录里正常都读得到
            continue
        if needle in raw:
            hits.append(str(path.relative_to(root)))
    return hits


class MeteredMockAdapter(ProductEvalAdapter):
    """真实 Mock 适配器 + 可注入的"出站"计数（证明 summary 用测量值，不是常量）。

    只在**测试**里模拟"这一轮真的出去了 N 次"；其余部分（产品 HTTP、Mock provider、隔离库）
    完全走真实实现，所以验证的是 runner 的统计口径，而不是替换被测逻辑。

    A1(F1-a)：注入点是**计量器本身**（真实的测量源），顶层 outbound 与 network.detail
    都从同一个计数器派生，不会出现"顶层 4 次、分解 0 次"这种自相矛盾的证据。
    """

    def __init__(self, *args: Any, outbound_per_turn: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.outbound_per_turn = int(outbound_per_turn)

    async def ask_turn(self, question: str, **kwargs: Any):  # noqa: ANN201 - 透传父类
        turn = await super().ask_turn(question, **kwargs)
        self._meter.outbound_attempts += self.outbound_per_turn
        return turn


class _TopLevelOnlyAdapter(MeteredMockAdapter):
    """只抬高**顶层** outbound_network、detail 不动：模拟"证据自相矛盾"。"""

    def provider_calls(self) -> dict[str, Any]:
        payload = dict(super().provider_calls())
        payload["outbound_network"] = int(payload["outbound_network"]) + 3
        return payload


class _BrokenDetailAdapter(MeteredMockAdapter):
    """detail 自身对不上（分解之和 ≠ network.outbound_attempts）。"""

    def provider_calls(self) -> dict[str, Any]:
        payload = dict(super().provider_calls())
        detail = dict(payload["network"])
        detail["rag_provider_posts"] = int(detail["rag_provider_posts"]) + 2
        payload["network"] = detail
        return payload


class RagPostMockAdapter(ProductEvalAdapter):
    """每轮真的记一次 RAG 供应商 POST（`rag.providers` 的机器计数，不联网）。

    A2(F1-b)：RAG 增量必须一路反映到 summary 的顶层/detail/real_requests/billed_cny，
    而不是只在 chat 计分器上成立。
    """

    def __init__(self, *args: Any, posts_per_turn: int = 1, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.posts_per_turn = int(posts_per_turn)

    async def ask_turn(self, question: str, **kwargs: Any):  # noqa: ANN201 - 透传父类
        turn = await super().ask_turn(question, **kwargs)
        for _ in range(self.posts_per_turn):
            rag_providers._record_post_attempt("embedding")
        return turn


@asyncio_test
async def test_metered_transport_counts_real_outbound_without_network() -> None:
    """F1：同一个计数器在 MockTransport 上记"拦截"、在真实传输上记"出站"（本例不出网）。"""
    from mktkb.evaluation.product_adapter import NetworkMeter, _MeteredTransport

    request = httpx.Request("POST", "http://provider.invalid/chat")
    meter = NetworkMeter()
    mocked = _MeteredTransport(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={})), meter
    )
    await mocked.handle_async_request(request)
    assert (meter.outbound_attempts, meter.mock_intercepted) == (0, 1)

    class _LocalDummyTransport(httpx.AsyncBaseTransport):
        """不联网的"真实"传输替身：只用来证明计量分支，不产生任何出站。"""

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

    realish = _MeteredTransport(_LocalDummyTransport(), meter)
    await realish.handle_async_request(request)
    assert (meter.outbound_attempts, meter.mock_intercepted) == (1, 1)
    assert meter.as_dict() == {"outbound_attempts": 1, "mock_intercepted": 1}


@asyncio_test
async def test_summary_reports_measured_network_and_billing_counts(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    adapter = MeteredMockAdapter(
        tmp_path / "metered",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
        outbound_per_turn=2,
    )
    gate = StubGate(is_mock_gate=True)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
        )
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    summary = read_json(adapter.paths.run_dir / "summary.json")
    request_rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
    # 每轮注入 2 次出站：真实请求数/出站数/计费都必须跟着实测走（不是常量 0）。
    assert [row["provider_calls"]["outbound"] for row in request_rows] == [2, 2]
    assert summary["requests"]["real_requests"] == 2
    assert summary["network"]["outbound_attempts"] == 4
    assert summary["requests"]["billed_cny"] == round(2 * 0.018688, 8)
    assert summary["providers"]["outbound_network"] == 4
    # A1：detail 是顶层的分解（chat 出站 + RAG POST），不是第二份真值。
    detail = summary["network"]["detail"]
    assert detail["chat_outbound_attempts"] == 4 and detail["rag_provider_posts"] == 0
    assert detail["outbound_attempts"] == summary["providers"]["outbound_network"] == 4
    # A3：provider 级 outbound_network 已恢复，且与 detail 的同一来源对齐（旧 probe 依赖此键）。
    assert summary["providers"]["chat"]["outbound_network"] == 4
    assert summary["providers"]["embedding"]["outbound_network"] == 0
    # 门的回执（reserved/sent/settled）与实测口径互相印证：成功结算不再表现为 0 元。
    assert result.requests_reserved == 2 and result.requests_sent == 2
    assert result.settled_cny == summary["requests"]["billed_cny"]


@asyncio_test
async def test_inconsistent_network_detail_is_a_stable_error(tmp_path: Path) -> None:
    """A1(F1-a)：顶层与 detail 不一致（或 detail 自身对不上）必须失败，不静默拼接。"""
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    for name, adapter_cls in (
        ("top-level-only", _TopLevelOnlyAdapter),
        ("broken-detail", _BrokenDetailAdapter),
    ):
        adapter = adapter_cls(
            tmp_path / f"inconsistent-{name}",
            chat=MockChatBackend(),
            dataset=make_dataset(cases),
            ingest_plan=make_ingest_plan(),
        )
        try:
            with pytest.raises(ValueError, match="provider_network_detail_mismatch"):
                await run_p2(
                    plan,
                    adapter=adapter,
                    authorization=authorization,
                    gate=StubGate(is_mock_gate=True),
                    now=NOW,
                )
        finally:
            await adapter.close()


@asyncio_test
async def test_missing_network_detail_is_refused(tmp_path: Path) -> None:
    """A1：连 detail 都不给，runner 直接报错（缺测量字段不按 0 兜底）。"""
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)

    class _NoDetailAdapter(MeteredMockAdapter):
        def provider_calls(self) -> dict[str, Any]:
            payload = dict(super().provider_calls())
            payload.pop("network", None)
            return payload

    adapter = _NoDetailAdapter(
        tmp_path / "no-detail",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    try:
        with pytest.raises(ValueError, match="provider_network_detail_mismatch"):
            await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
    finally:
        await adapter.close()


@asyncio_test
async def test_rag_post_increment_flows_into_summary_and_billing(tmp_path: Path) -> None:
    """A2(F1-b)：每轮一次 RAG 供应商 POST → 顶层/detail/real_requests/billed 都跟着动。"""
    rag_providers.reset_post_counters()
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    adapter = RagPostMockAdapter(
        tmp_path / "rag-post",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=authorization,
            gate=StubGate(is_mock_gate=True),
            now=NOW,
        )
    finally:
        await adapter.close()
        rag_providers.reset_post_counters()

    assert result.status == "succeeded", result.as_dict()
    summary = read_json(adapter.paths.run_dir / "summary.json")
    request_rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
    # 每轮实测增量：chat 0 次、RAG POST 1 次 → 该轮确实"出网"1 次。
    assert [row["provider_calls"]["outbound"] for row in request_rows] == [1, 1]
    assert summary["requests"]["real_requests"] == 2
    assert summary["requests"]["billed_cny"] == round(2 * 0.018688, 8)
    assert summary["providers"]["outbound_network"] == 2
    detail = summary["network"]["detail"]
    assert (detail["chat_outbound_attempts"], detail["rag_provider_posts"]) == (0, 2)
    assert detail["outbound_attempts"] == 2
    # A3：provider 级字段与 detail 同源（chat 为 0，RAG 只体现在 network.detail）。
    assert summary["providers"]["chat"]["outbound_network"] == 0
    assert result.settled_cny == summary["requests"]["billed_cny"]


@asyncio_test
async def test_live_requires_real_gate_refuses_stub_gate_before_send(tmp_path: Path) -> None:
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = replace(dry_run_authorization(plan), production_ready=True)
    adapter = RealishAdapter(tmp_path / "live-stub", make_dataset(cases))
    gate = StubGate(is_mock_gate=True)  # 桩门：没有真实 P2Gate 的账本/GO 事实

    result = await run_p2(
        plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
    )

    assert result.status == "blocked"
    assert result.stop_code == "live_requires_real_gate"
    # 发送前就拒：适配器一行没答、门一步没走。
    assert adapter.asks == []
    assert gate.calls == []
    gate_payload = read_json(adapter.paths.run_dir / "gate.json")
    assert gate_payload["execution"] == "live"
    assert gate_payload["real_sends_allowed"] is False
    failed = {check["name"] for check in gate_payload["checks"] if not check["ok"]}
    assert failed == {"live_gate"}
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["failure"]["stage"] == "authorization"
    assert summary["requests"]["real_requests"] == 0


@asyncio_test
async def test_live_refuses_duck_gate_that_is_not_p2gate(tmp_path: Path) -> None:
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = replace(dry_run_authorization(plan), production_ready=True)
    adapter = RealishAdapter(tmp_path / "live-duck", make_dataset(cases))
    gate = StubGate(is_mock_gate=False)  # 看起来"不是桩"，但不是 P2Gate 本身

    result = await run_p2(
        plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
    )

    assert result.status == "blocked"
    assert result.stop_code == "live_requires_real_gate"
    assert adapter.asks == [] and gate.calls == []


def test_live_gate_policy_accepts_only_concrete_p2gate() -> None:
    assert is_real_p2_gate(None) is False
    assert is_real_p2_gate(object()) is False
    assert is_real_p2_gate(StubGate(is_mock_gate=True)) is False
    assert is_real_p2_gate(StubGate(is_mock_gate=False)) is False
    # 真实 P2Gate 类型（这里只判类型，不构造账本/GO）才是 live 唯一接受的"门"。
    assert is_real_p2_gate(P2Gate.__new__(P2Gate)) is True


@asyncio_test
async def test_holdout_without_purge_is_refused_before_any_work(tmp_path: Path) -> None:
    cases = (make_case("H01", RAG_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    dataset = make_dataset(cases, visibility="holdout", manifest_sha256="e" * 64)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "holdout-nopurge", chat=chat, dataset=dataset, ingest_plan=make_ingest_plan()
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
        calls = adapter.provider_calls()
    finally:
        await adapter.close()

    assert result.status == "blocked"
    assert result.stop_code == "holdout_requires_purge"
    # fail closed：没灌库、没建会话、没调 provider、也没建 trace 库。
    assert adapter.ingest_receipts == []
    assert chat.call_count == 0 and calls["embedding"]["calls"] == 0
    assert not adapter.paths.trace_db.exists()
    summary = read_json(adapter.paths.run_dir / "summary.json")
    assert summary["failure"]["stage"] == "holdout_policy"
    assert summary["holdout"]["trace_retention"] == "refused-before-start"
    gate_payload = read_json(adapter.paths.run_dir / "gate.json")
    failed = {check["name"] for check in gate_payload["checks"] if not check["ok"]}
    assert failed == {"holdout_purge"}
    assert gate_payload["real_sends_allowed"] is False


@asyncio_test
async def test_real_adapter_without_gate_is_refused_as_adapter_must_be_mock(
    tmp_path: Path,
) -> None:
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    adapter = RealishAdapter(tmp_path / "realish-no-gate", make_dataset(cases))

    result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)

    assert result.status == "blocked"
    assert result.stop_code == "adapter_must_be_mock"
    assert adapter.asks == []
    gate_payload = read_json(adapter.paths.run_dir / "gate.json")
    failed = {check["name"] for check in gate_payload["checks"] if not check["ok"]}
    assert failed == {"adapter_mock"}
    assert gate_payload["execution"] == "dry_run"
    assert read_json(adapter.paths.run_dir / "summary.json")["requests"]["real_requests"] == 0


@asyncio_test
async def test_multiturn_midway_failure_keeps_stage_case_turn_item_and_ticket(
    tmp_path: Path,
) -> None:
    case = make_case(
        "P02",
        LEGACY_QUESTION,
        turns=(
            {"role": "user", "question": LEGACY_QUESTION},
            {"role": "user", "question": SECOND_CHAT_QUESTION},
        ),
        stratum="multi_turn",
    )
    cases = (case,)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    # 第一轮正常，第二轮 Mock 供应商 503：失败必须停在第二轮并保留全部现场。
    chat = MockChatBackend(
        behaviors=(ChatBehavior(), ChatBehavior(kind="http_error", status_code=503))
    )
    adapter = ProductEvalAdapter(
        tmp_path / "midturn-fail",
        chat=chat,
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
    finally:
        await adapter.close()

    assert result.status == "aborted"
    assert result.stop_code == "product_service_error"
    failure = read_json(adapter.paths.run_dir / "summary.json")["failure"]
    assert failure["stage"] == "product_answer"
    assert failure["case_id"] == "P02"
    assert failure["turn"] == 2
    assert failure["item_id"] == "P02:turn2:answer"
    assert failure["error_code"] == "MODEL_UNAVAILABLE"
    assert failure["ticket"]["item_id"] == "P02:turn2:answer"
    assert failure["ticket"]["request_id"]
    case_rows = read_jsonl(adapter.paths.run_dir / "cases.jsonl")
    assert case_rows[0]["turns_executed"] == 2
    assert [turn["status"] for turn in case_rows[0]["turns"]] == ["ok", "error"]


@asyncio_test
async def test_holdout_close_removes_question_plaintext_from_out_dir(tmp_path: Path) -> None:
    cases = (make_case("H91", HOLDOUT_SENTINEL),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    dataset = make_dataset(cases, visibility="holdout", manifest_sha256="f" * 64)
    adapter = ProductEvalAdapter(
        tmp_path / "holdout-sealed",
        chat=MockChatBackend(),
        dataset=dataset,
        ingest_plan=make_ingest_plan(),
        purge_traces_on_close=True,
    )
    out_dir = adapter.paths.root
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
        # 前置：运行期业务库里确实存着题干明文——否则这个测试没有证伪力。
        assert adapter.paths.business_db.is_file()
        assert files_containing(out_dir, HOLDOUT_SENTINEL), "close 前应能在 out_dir 里找到题干"
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    # close 之后：题干明文在 out_dir 里一次都不出现（业务库/trace 都已删除）。
    assert files_containing(out_dir, HOLDOUT_SENTINEL) == []
    assert not adapter.paths.business_db.exists()
    assert adapter.seal_receipt == {
        "question_store": "deleted",
        "removed": [str(adapter.paths.business_db)],
    }
    # 聚合产物仍在，且依旧没有逐题行/题干。
    assert (adapter.paths.run_dir / "holdout_aggregate.json").is_file()
    assert not (adapter.paths.run_dir / "cases.jsonl").exists()
    assert not (adapter.paths.run_dir / "requests.jsonl").exists()



# --------------------------------------------------------------------------- #
# 8. T206-PRE：真实准入前的绑定（trace 身份 / 证据 id / config_hash / 失败产物 / run_id）
# --------------------------------------------------------------------------- #

DOCUMENT_CODES = {
    D01.name: "D01",
    D04.name: "D04",
}


def read_trace(adapter: Any, trace_id: str) -> Any:
    repo = adapter.app.state.trace_repo
    found = repo.get(trace_id)
    assert found is not None, trace_id
    return found


@pytest.mark.parametrize("index_event", ["stable", "not_ready", "before_second", "during_final"])
@asyncio_test
async def test_formal_b0_binds_ready_index_and_stops_on_drift(tmp_path, monkeypatch, index_event):
    from mktkb.evaluation import p2_runner
    from mktkb.evaluation.p2_b0 import build_b0_plan_binding, load_approved_b0_config

    config = load_approved_b0_config(ROOT / "docs/evaluation/gate_v0_3_approved.json")
    run_id = "synthetic-b0-index"
    cases = (
        make_case("P01", RAG_QUESTION),
        make_case("P02", LEGACY_QUESTION),
        make_case("P03", "城东店的宣传海报在哪里？"),
    )
    plan = replace(make_plan(cases), b0_binding=build_b0_plan_binding(run_id))
    gate = StubGate()
    # Reach the formal B0 runner with product routes and a test-only gate.
    monkeypatch.setattr(p2_runner, "is_real_p2_gate", lambda candidate: candidate is gate)
    ingest = P2IngestPlan(
        sources=(
            IngestSource(path=FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx", name=D01.name),
            IngestSource(path=D01, document_ref=D01.name),
            IngestSource(path=D04),
        ),
        label="synthetic-b0-replaced-source",
    )
    dataset = make_dataset(cases)
    chat = MockChatBackend(behaviors=(ChatBehavior(), ChatBehavior(answer="位置：B区1号货架第二层")))
    adapter = ProductEvalAdapter(
        tmp_path / "b0", chat=chat, dataset=dataset, ingest_plan=ingest,
    )
    actual_status = adapter.index_status
    open_conversation = adapter.open_conversation
    ask_turn = adapter.ask_turn
    observed = []
    opened = 0

    def change_index():
        index = adapter.app.state.qa.index()
        index.remove_document(index.list_documents()[0]["doc_id"])

    async def open_with_drift(**kwargs):
        nonlocal opened
        opened += 1
        if opened == 2:
            change_index()
        return await open_conversation(**kwargs)

    async def ask_and_record(question, **kwargs):
        product = await ask_turn(question, **kwargs)
        trace, _ = read_trace(adapter, product.trace_id)
        observed.append((trace.path, trace.index_revision))
        if index_event == "during_final" and question == cases[-1].question:
            change_index()
        return product

    if index_event == "not_ready":
        monkeypatch.setattr(adapter, "index_status", lambda: {**actual_status(), "ready": False})
    if index_event == "before_second":
        monkeypatch.setattr(adapter, "open_conversation", open_with_drift)
    monkeypatch.setattr(adapter, "ask_turn", ask_and_record)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=dry_run_authorization(plan),
            gate=gate, gate_config=config, b0_corpus=(), run_id=run_id, now=NOW,
        )
        out = adapter.paths.run_dir
        manifest = read_json(out / "run_manifest.json")
        summary = read_json(out / "summary.json")
        assert adapter.product_revision() == 3
        assert adapter.provider_calls()["outbound_network"] == 0
        if index_event == "not_ready":
            assert (result.status, result.stop_code) == ("blocked", "b0_index_not_ready")
            assert not gate.calls and not observed
            assert manifest["index_revision"] is None and not manifest["binding"]["complete"]
            assert read_jsonl(out / "requests.jsonl") == []
            return

        count = 1 if index_event == "before_second" else 3
        assert manifest["index_revision"] == manifest["binding"]["index_revision"] == 4
        assert summary["binding"] == manifest["binding"] == read_json(out / "gate.json")["binding"]
        assert observed == [
            ("rag", "4"), ("legacy", "4"), ("legacy_with_rag_candidates", "4"),
        ][:count]
        assert gate.calls == ["begin", "confirm_before_send", "settle_success"] * count
        assert len(read_jsonl(out / "requests.jsonl")) == count
        if index_event != "stable":
            assert (result.status, result.stop_code) == ("aborted", "b0_index_changed")
            expected_case = "P02" if index_event == "before_second" else "P03"
            assert summary["failure"]["case_id"] == expected_case
            assert summary["failure"]["stage"] == (
                "index_before_turn" if index_event == "before_second" else "index_after_turn"
            )
            return

        assert (result.status, result.stop_code) == ("succeeded", None)
        scored = [
            score_p2_public_case(case, row, document_codes=DOCUMENT_CODES,
                                 allowed_doc_codes=set(DOCUMENT_CODES.values()))
            for case, row in zip(cases, read_jsonl(out / "cases.jsonl"), strict=True)
        ]
        rows = build_gate_rows(cases, scored)
        # Match p2-admit's projection: trace manifest_sha256 binds the frozen cases.
        bridge = dict(manifest, corpus_manifest_sha256=manifest["binding"]["manifest_sha256"])
        gate_run = build_gate_run(run_dir=out, manifest=bridge, cases=cases, rows=rows, summary=summary)
        hard = evaluate_p2_hard_gates(gate_run, config=config, require_trace=True)
        assert hard.gate_status["trace_integrity"] == "pass", json.dumps(hard.to_dict(), ensure_ascii=False)
    finally:
        await adapter.close()


@asyncio_test
async def test_mock_dry_run_binds_identity_and_passes_trace_integrity(tmp_path: Path) -> None:
    """Mock dry-run：身份绑进 trace、证据 id 可判定 True、8 硬门禁里的 trace_integrity 真 PASS。"""
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    dataset = make_dataset(cases)
    config = load_p2_gate_config()
    adapter = ProductEvalAdapter(
        tmp_path / "bound", chat=MockChatBackend(), dataset=dataset, ingest_plan=make_ingest_plan()
    )
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=authorization,
            now=NOW,
            gate_config=config,
        )
        assert result.status == "succeeded", result.as_dict()
        run_dir = adapter.paths.run_dir
        manifest = read_json(run_dir / "run_manifest.json")
        summary = read_json(run_dir / "summary.json")
        gate_payload = read_json(run_dir / "gate.json")
        case_rows = read_jsonl(run_dir / "cases.jsonl")

        # 1) config_hash 绑定：确定、64 位、写入 manifest/summary/gate，且 gate 身份齐全
        binding = manifest["binding"]
        assert binding["complete"] is True, binding["missing"]
        assert len(binding["config_hash"]) == 64
        assert manifest["config_hash"] == binding["config_hash"] == summary["binding"]["config_hash"]
        assert gate_payload["binding"]["config_hash"] == binding["config_hash"]
        assert manifest["gate_version"] == config.gate_version
        assert manifest["gate_config_hash"] == config.config_hash
        assert manifest["index_revision"] == adapter.product_revision()
        assert manifest["dataset_sha256"] == binding["dataset_sha256"]
        assert binding["trace_identity_bound"] is True

        # 2) trace 身份：每条 trace 与 manifest 同源（不是评测器自己写一个"看起来对"的值）
        expected = {
            "dataset_version": manifest["dataset_version"],
            "run_id": manifest["run_id"],
            "index_revision": str(manifest["index_revision"]),
            "manifest_sha256": manifest["corpus_manifest_sha256"],
            "pipeline_version": manifest["pipeline_version"],
            "config_hash": manifest["config_hash"],
        }
        for case_row in case_rows:
            for turn in case_row["turns"]:
                trace, _spans = read_trace(adapter, turn["trace_id"])
                for name, value in expected.items():
                    assert str(getattr(trace, name)) == str(value), (case_row["case_id"], name)

        # 3) 引用证据 id：产品来源解析出稳定 unit_id/locator/版本，判定 True（不是伪造）
        status = citation_evidence_status(case_rows)
        assert status["complete"] is True, status
        assert status["answered_turns"] >= 1 and status["verified_citations"] == status["citations"]
        assert summary["citation_evidence"]["complete"] is True
        first_evidence = case_rows[0]["turns"][0]["product"]["evidence"][0]
        assert first_evidence["unit_id"] and first_evidence["locator"] and first_evidence["version_number"] >= 1
        assert first_evidence["active"] is True and first_evidence["in_run"] is True

        # 4) 把 run 产物接进 gate：trace_integrity 必须真 PASS（不是合成 trace）
        scored = []
        for case, case_row in zip(cases, case_rows):
            scored.append(
                score_p2_public_case(
                    case,
                    case_row,
                    document_codes=DOCUMENT_CODES,
                    allowed_doc_codes=set(DOCUMENT_CODES.values()),
                )
            )
        rows = build_gate_rows(cases, scored)
        gate_run = build_gate_run(
            run_dir=run_dir, manifest=manifest, cases=cases, rows=rows, summary=summary
        )
        hard = evaluate_p2_hard_gates(gate_run, config=config, require_trace=True)
        assert hard.gate_status["trace_integrity"] == "pass", hard.to_dict()
        assert not [
            item for item in hard.hard_failures if item == "trace_integrity"
        ], hard.to_dict()

        # 5) R1：gate 行的 retrieved 是产品本轮**真实检索候选**（不是引用），citation_required 真 PASS
        assert hard.gate_status["citation_required"] == "pass", hard.to_dict()
        for case_row, row in zip(case_rows, rows):
            outcome = row["outcome"] or {}
            cited = {unit for item in outcome.get("citations") or () for unit in item.get("unit_ids") or ()}
            candidates = {unit for item in outcome.get("retrieved") or () for unit in item.get("unit_ids") or ()}
            if outcome.get("kind") == "answer":
                assert candidates, (case_row["case_id"], outcome)
                assert cited <= candidates, (case_row["case_id"], cited - candidates)
        products = [case_row["turns"][0]["product"] for case_row in case_rows]
        assert all(product["retrieved"] for product in products)
        # 候选多于引用：证明不是把引用抄进 retrieved
        assert any(len(product["retrieved"]) > len(product["sources"]) for product in products)
    finally:
        await adapter.close()


FOREIGN_UNIT = "99999999-9999-4999-8999-999999999999"


def _tampered_rows(rows, *, mode: str) -> tuple[dict[str, Any], ...]:
    """反例：把作答行的检索候选删掉（drop）或换成无关单元（foreign）。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        outcome = copy.get("outcome")
        if isinstance(outcome, Mapping) and outcome.get("kind") == "answer":
            outcome = dict(outcome)
            if mode == "drop":
                outcome["retrieved"] = []
            else:
                outcome["retrieved"] = [
                    {
                        "doc_code": "D01",
                        "unit_ids": [FOREIGN_UNIT],
                        "unit_key": "sheet:无关:row:99",
                        "locator": {"sheet": "无关", "row": 99},
                        "chunk_id": None,
                        "hard_filter_violation": None,
                    }
                ]
            copy["outcome"] = outcome
        out.append(copy)
    return tuple(out)


@asyncio_test
async def test_gate_rows_use_real_retrieval_candidates_and_fail_closed(tmp_path: Path) -> None:
    """R1：gate 行的 retrieved = 产品本轮真实检索候选；缺候选/引用不在候选内 → fail（不放宽）。"""
    cases = (
        make_case("P01", RAG_QUESTION),
        make_case("P03", LEGACY_QUESTION),
        make_case("P04", UNKNOWN_QUESTION, stratum="negative"),
    )
    plan = make_plan(cases)
    adapter = ProductEvalAdapter(
        tmp_path / "candidates",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    config = load_p2_gate_config()
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=dry_run_authorization(plan),
            now=NOW,
            gate_config=config,
        )
        assert result.status == "succeeded", result.as_dict()
        run_dir = adapter.paths.run_dir
        manifest = read_json(run_dir / "run_manifest.json")
        summary = read_json(run_dir / "summary.json")
        case_rows = read_jsonl(run_dir / "cases.jsonl")
        by_id = {row["case_id"]: row for row in case_rows}

        # 1) 产品逐轮记的是检索候选：包含被引用的单元、带稳定身份，且不只是引用的副本
        for case_id in ("P01", "P03"):
            product = by_id[case_id]["turns"][0]["product"]
            cited = {str(item["source_id"]) for item in product["sources"]}
            candidates = {unit for item in product["retrieved"] for unit in item["unit_ids"]}
            assert cited and cited <= candidates, case_id
            for item in product["retrieved"]:
                assert item["unit_key"] and item["locator"], item
        assert any(
            len(by_id[case_id]["turns"][0]["product"]["retrieved"])
            > len(by_id[case_id]["turns"][0]["product"]["sources"])
            for case_id in ("P01", "P03")
        )
        # 2) 非作答轮不造候选（gate 也不要求引用）
        assert by_id["P04"]["turns"][0]["product"]["kind"] == "not_found"
        assert by_id["P04"]["turns"][0]["product"]["retrieved"] == []

        scored = [
            score_p2_public_case(
                case,
                by_id[case.case_id],
                document_codes=DOCUMENT_CODES,
                allowed_doc_codes=set(DOCUMENT_CODES.values()),
            )
            for case in cases
        ]
        rows = build_gate_rows(cases, scored)
        gate_run = build_gate_run(
            run_dir=run_dir, manifest=manifest, cases=cases, rows=rows, summary=summary
        )
        positive = evaluate_p2_hard_gates(gate_run, config=config, require_trace=True)
        assert positive.gate_status["citation_required"] == "pass", positive.to_dict()
        assert "citation_required" not in positive.hard_failures

        # 3) 反例：候选缺失 / 引用不在候选内 → fail（不是 unknown、不是 pass）
        for mode in ("drop", "foreign"):
            tampered = build_gate_run(
                run_dir=run_dir,
                manifest=manifest,
                cases=cases,
                rows=_tampered_rows(rows, mode=mode),
                summary=summary,
            )
            hard = evaluate_p2_hard_gates(tampered, config=config, require_trace=True)
            assert hard.gate_status["citation_required"] == "fail", (mode, hard.to_dict())
            assert "citation_required" in hard.hard_failures, mode
            assert any(item.check_id == "citation_not_in_evidence" for item in hard.failures), mode
    finally:
        await adapter.close()


@asyncio_test
async def test_dry_run_without_gate_config_keeps_identity_unbound(tmp_path: Path) -> None:
    """没给 gate 配置 → 绑定不完整、trace 不绑身份（缺一项整体不绑，不写半套）。"""
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    adapter = ProductEvalAdapter(
        tmp_path / "unbound", chat=MockChatBackend(), dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
        assert result.status == "succeeded", result.as_dict()
        run_dir = adapter.paths.run_dir
        manifest = read_json(run_dir / "run_manifest.json")
        binding = manifest["binding"]
        assert binding["complete"] is False
        assert binding["config_hash"] is None
        assert {"gate_version", "gate_config_hash", "trace_identity"} <= set(binding["missing"])
        assert binding["trace_identity_bound"] is False
        case_row = read_jsonl(run_dir / "cases.jsonl")[0]
        trace, _ = read_trace(adapter, case_row["turns"][0]["trace_id"])
        for name in ("run_id", "dataset_version", "pipeline_version", "index_revision",
                     "manifest_sha256", "config_hash"):
            assert getattr(trace, name) is None, name
    finally:
        await adapter.close()


@asyncio_test
async def test_artifact_validation_failure_still_writes_all_products(tmp_path: Path) -> None:
    """R2-F-R2-1：校验失败也要落 run_result/summary/gate（带失败阶段与稳定码）。"""
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    adapter = _TopLevelOnlyAdapter(
        tmp_path / "artifact-fail",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    try:
        with pytest.raises(P2RunError) as excinfo:
            await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
        code = excinfo.value.code
        run_dir = adapter.paths.run_dir
        result = read_json(run_dir / "run_result.json")
        summary = read_json(run_dir / "summary.json")
        gate_payload = read_json(run_dir / "gate.json")
        assert read_json(run_dir / "run_manifest.json")["run_id"] == result["run_id"]
    finally:
        await adapter.close()

    assert code == "provider_network_detail_mismatch"
    assert result["status"] == "aborted" and result["stop_code"] == code
    assert summary["status"] == "aborted" and summary["stop_code"] == code
    assert summary["failure"]["stage"] == "artifact_validation"
    assert summary["failure"]["error_code"] == code
    # 未通过交叉校验的计数**不得**写成实测事实
    assert summary["network"]["available"] is False and summary["network"]["code"] == code
    assert summary["providers"] is None
    assert gate_payload["artifact_validation"]["ok"] is False
    assert gate_payload["artifact_validation"]["code"] == code
    assert gate_payload["failure"]["stop_code"] == code
    assert gate_payload["real_sends_allowed"] is False


@asyncio_test
async def test_missing_run_id_is_refused_before_any_send(tmp_path: Path) -> None:
    """R2-F-R2-3：run_id 必填；空/非字符串在发送前用稳定码拒绝，不悄悄换一个身份。"""
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    for bad in ("", "   ", 123):
        adapter = ProductEvalAdapter(
            tmp_path / f"run-id-{type(bad).__name__}-{len(str(bad))}",
            chat=MockChatBackend(),
            dataset=make_dataset(cases),
            ingest_plan=make_ingest_plan(),
        )
        try:
            with pytest.raises(P2RunError) as excinfo:
                await run_p2(
                    plan,
                    adapter=adapter,
                    authorization=authorization,
                    now=NOW,
                    run_id=bad,  # type: ignore[arg-type]
                )
        finally:
            await adapter.close()
        assert excinfo.value.code == "run_id_missing"
        assert not adapter.paths.run_dir.exists(), "拒绝必须在建 run 目录/发送之前"


# --------------------------------------------------------------------------- #
# T207-FIX-B：run_result 的 additive 尝试口径 + summary 三段金额（零真实调用）
# --------------------------------------------------------------------------- #


def _legacy_run_result_payload() -> dict[str, Any]:
    """pilot 的 run_result.json 形状（answer 单侧，没有 attempts_* 键）。"""
    return {
        "schema_version": P2_RUN_RESULT_SCHEMA_VERSION,
        "run_id": "p2-t206-pilot-20261111-01",
        "plan_id": "P2-T206-PILOT-20261111",
        "plan_sha256": "02725aa7309fe2ca3a5bb05cf4d450cc276f361c80b11c3ac22df54ac6375d80",
        "status": "succeeded",
        "stop_code": None,
        "requests_planned": 61,
        "requests_reserved": 6,
        "requests_sent": 3,
        "reserved_cny": 0.11212799999999999,
        "settled_cny": 0.061806,
        "by_operation": {"answer": 6},
        "by_center_cny": {
            "answer_retrieval": 0.061806,
            "independent": 0.0,
            "judge": 0.0,
            "ocr": 0.0,
        },
        "production_ready": True,
    }


def test_run_result_attempts_keys_are_additive_and_old_artifacts_still_load() -> None:
    """旧产物缺 attempts_* 仍可读（=unavailable/0）；新键补上后往返一致；未知键仍拒。"""
    legacy = _legacy_run_result_payload()
    loaded = P2RunResult.from_dict(legacy)
    assert loaded.attempts_scope == "unavailable"
    assert loaded.attempts_reserved == 0
    assert dict(loaded.attempts_by_operation) == {}
    assert dict(loaded.attempts_by_center_cny) == {}
    # answer 单侧旧键语义逐字不变。
    assert loaded.requests_reserved == 6 and loaded.settled_cny == pytest.approx(0.061806)
    assert loaded.as_dict()["attempts_scope"] == "unavailable"

    full = P2RunResult(
        **legacy,
        attempts_scope="all_attempts",
        attempts_reserved=42,
        attempts_by_operation={"answer": 6, "index_embedding": 31, "ocr": 1, "query_embedding": 2, "rerank": 2},
        attempts_by_center_cny={
            "answer_retrieval": 0.0713583,
            "ocr": 0.5,
            "judge": 0.0,
            "independent": 0.0,
        },
    )
    assert P2RunResult.from_dict(full.as_dict()).as_dict() == full.as_dict()

    # unavailable 不得带计数（不用 answer 口径冒充全量）；未知键仍拒绝。
    with pytest.raises(P2ContractError) as excinfo:
        P2RunResult(**legacy, attempts_scope="unavailable", attempts_reserved=42)
    assert excinfo.value.reason == "result_inconsistent"
    with pytest.raises(P2ContractError) as excinfo:
        P2RunResult.from_dict({**legacy, "attempts_typo": 1})
    assert excinfo.value.reason == "field_unknown"


def test_summary_money_split_replays_pilot_totals() -> None:
    """回放 pilot 实测：保守 0.5713583 / 供应商证据 0.5152943 / 零付费轮 3（差 0.056064）。"""
    ledger = P2RunLedger(
        run_id="p2-t206-pilot-20261111-01",
        plan_id="P2-T206-PILOT-20261111",
        plan_sha256="02725aa7309fe2ca3a5bb05cf4d450cc276f361c80b11c3ac22df54ac6375d80",
        execution="live",
        production_ready=True,
    )
    # 3 笔按 usage 结算的 answer 轮（合计 0.005742）+ 3 笔零付费轮（各按上界 0.018688）。
    ledger.settled_cny = 0.061806
    ledger.unused = 3  # runner 的唯一零付费轮计数器（不另算第二份）
    ledger.requests.extend(
        [
            {"status": "ok", "charged_cny": 0.001914},
            {"status": "ok", "charged_cny": 0.001838},
            {"status": "ok", "charged_cny": 0.001990},
            {"status": "not_found", "paid_attempt": False, "charged_cny": 0.018688},
            {"status": "conflict", "paid_attempt": False, "charged_cny": 0.018688},
            {"status": "answer", "paid_attempt": False, "charged_cny": 0.018688},
        ]
    )
    audit = {
        "available": True,
        "receipts": [
            {"phase": "reserve", "status": "reserved", "charged_cny": 0.0},
            {"phase": "settle", "status": "succeeded", "charged_cny": 0.004},
            {"phase": "settle", "status": "succeeded", "charged_cny": 0.004},
            {"phase": "settle", "status": "succeeded", "charged_cny": 0.0015523},
            {"phase": "settle", "status": "succeeded", "charged_cny": 0.5},
        ],
    }
    split = _money_split(ledger, audit)
    assert split["conservative_held_cny"] == pytest.approx(0.5713583)
    assert split["provider_billed_cny"] == pytest.approx(0.5152943)
    assert split["unpaid_rounds"] == 3
    # 差额 = 3 笔零付费轮的整笔上界（不是供应商花费）。
    assert split["conservative_held_cny"] - split["provider_billed_cny"] == pytest.approx(0.056064)
    # mock_gate / dry_run 没有供应商：即使有"结算金额"也不能声称已计费。
    assert _money_split(replace(ledger, execution="mock_gate"), audit)["provider_billed_cny"] == 0.0

# --------------------------------------------------------------------------- #
# T207-FIX-B-R1：J1 拒绝轮的保守占用记账（C1，零真实调用）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_j1_rejected_settle_books_bound_without_counting_success_or_failure(
    tmp_path: Path,
) -> None:
    """answer 轮 J1 结算被拒时，按账本 result 的保守占用入账（C1）。

    门的 J1 拒绝口径是「账本已写 status=unknown + 保守上界，再抛错」（真实 P2Gate 的
    端到端用例见 test_p2_live_wiring.py）。runner 必须把这一笔按同一上界计入
    summary.conservative_held_cny，并用互斥的 rejected_rounds 计数：既不算成功结算，
    也不算真实失败结算（settled_failure/failed_rounds）。
    """
    from mktkb.evaluation.p2_authorization import P2GateError

    cases = (make_case("P03", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)

    class _RejectingGate(StubGate):
        """模拟 J1 拒绝：settle_success 抛错（账本侧已按上界写保守 result）。"""

        def settle_success(self, ticket: "_StubTicket", **kwargs: Any) -> float:
            self.calls.append("settle_success")
            raise P2GateError("usage_total_mismatch", "SettlementNotReleasable")

    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "rejected",
        chat=chat,
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    gate = _RejectingGate(is_mock_gate=True)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
        )
    finally:
        await adapter.close()

    assert result.status == "aborted"
    assert result.stop_code == "gate_error"
    # 门没有把这笔计成 sent/settled：不是「成功」，也不是「真实失败结算」。
    assert result.requests_sent == 0
    assert result.by_operation == {}
    # 保守占用 = 该笔预留上界（= 账本 result 的保守额），不是 0。
    assert result.settled_cny == pytest.approx(0.018688)
    assert result.by_center_cny["answer_retrieval"] == pytest.approx(0.018688)

    summary = read_json(adapter.paths.run_dir / "summary.json")
    requests = summary["requests"]
    assert requests["rejected_rounds"] == 1
    assert requests["settled_success"] == 0
    assert requests["settled_failure"] == requests["failed_rounds"] == 0
    assert requests["unpaid_rounds"] == 0
    assert requests["conservative_held_cny"] == pytest.approx(0.018688)
    assert requests["provider_billed_cny"] == 0.0
    assert requests["billed_cny"] == 0.0, "Mock 链零出站：不冒充真实出网计费"

    request_row = read_jsonl(adapter.paths.run_dir / "requests.jsonl")[0]
    assert request_row["status"] == "error" and request_row["billed"] is False
    assert request_row["error_code"] == "gate_error"
    assert request_row["charged_cny"] == pytest.approx(0.018688)
    assert summary["failure"]["stage"] == "gate_settle"


@asyncio_test
async def test_normal_settle_does_not_count_a_rejected_round(tmp_path: Path) -> None:
    """正常成功结算的轮次不得误计成 J1 拒绝轮（互斥计数、不重复记账）。"""
    cases = (make_case("P03", LEGACY_QUESTION),)
    plan = make_plan(cases)
    authorization = dry_run_authorization(plan)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "normal",
        chat=chat,
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    gate = StubGate(is_mock_gate=True)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW
        )
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    assert result.settled_cny == pytest.approx(0.018688)
    summary = read_json(adapter.paths.run_dir / "summary.json")
    requests = summary["requests"]
    assert requests["rejected_rounds"] == 0, "正常结算不能被算成 J1 拒绝轮"
    assert requests["settled_success"] == 1
    assert requests["settled_failure"] == 0
    assert requests["conservative_held_cny"] == pytest.approx(0.018688)
