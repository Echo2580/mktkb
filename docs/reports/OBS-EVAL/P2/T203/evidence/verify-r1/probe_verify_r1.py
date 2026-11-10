"""P2-T203-R1 独立复验探针（verify-r1；不复用 R1 的探针结论）。

目的（证伪优先）：
- F1：产物里的 real_requests / billed_cny / network.outbound_attempts / provider_calls().outbound_network
  是否来自实测（传输层 + RAG post_counters 增量）；缺字段是否报错；network.detail 与顶层是否自洽。
- F2：live + 桩门/鸭子门是否在发送前被拒；真实 P2Gate 是唯一可通过的类型。
- F3：holdout + purge=False 是否 fail-closed（0 灌库/0 会话/0 provider/不建 trace）。
- F6：holdout close 后 out_dir 是否 0 条题干明文；公开路径是否不删业务库；删不干净是否报错。
- 顺带：settled_cny 成功结算修复；mock_gate 两套口径；RAG post 计数增量。

运行：.venv/Scripts/python.exe -B <本文件> [输出 JSON 路径]
零真实调用：本探针自带 socket 出站闸门（回环放行），并在结束时断言 external==0。
只写系统临时目录 + 调用方给的 JSON 路径；不改源码/测试/报告。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "backend" / "tests"))

from evaluation.test_p2_runner import (  # noqa: E402
    LEGACY_QUESTION,
    NOW,
    RAG_QUESTION,
    ChatBehavior,
    MockChatBackend,
    ProductEvalAdapter,
    dry_run_authorization,
    make_case,
    make_dataset,
    make_ingest_plan,
    make_plan,
    read_json,
    read_jsonl,
)
from mktkb.evaluation.p2_authorization import P2Gate  # noqa: E402
from mktkb.evaluation.p2_runner import is_real_p2_gate, run_p2  # noqa: E402
from mktkb.rag import providers as rag_providers  # noqa: E402

SENTINEL = "VERIFY-R1-9B2E 火星店的宣传海报到底在哪里？"
SENTINEL_PUBLIC = "VERIFY-R1-9B2E-PUBLIC 活动策划流程有哪些环节？"
CHECKS: list[dict[str, Any]] = []
OBSERVATIONS: dict[str, Any] = {}


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    return bool(ok)


def scratch(name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"t203-verify-r1-{name}-"))


# --------------------------------------------------------------------------- #
# 出站闸门（只拦外部；回环放行并记账）
# --------------------------------------------------------------------------- #
LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _is_loopback(address: Any) -> bool:
    if isinstance(address, str):
        return address.startswith("/") or address.startswith("\\\\.\\pipe\\") or "localhost" in address
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", "replace")
        if not isinstance(host, str):
            return False
        return host in LOOPBACK or host.startswith("127.")
    return False


@contextlib.contextmanager
def outbound_guard():
    attempts = {"external": [], "local": []}
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    def guard_connect(self, address, *args, **kwargs):  # noqa: ANN001
        if _is_loopback(address):
            attempts["local"].append(repr(address))
            return real_connect(self, address, *args, **kwargs)
        attempts["external"].append(f"connect {address!r}")
        raise RuntimeError(f"VERIFY-R1 外部出站被拒: {address!r}")

    def guard_connect_ex(self, address, *args, **kwargs):  # noqa: ANN001
        if _is_loopback(address):
            attempts["local"].append(repr(address))
            raise RuntimeError(f"VERIFY-R1 不发起本地 connect_ex: {address!r}")
        attempts["external"].append(f"connect_ex {address!r}")
        raise RuntimeError(f"VERIFY-R1 外部出站被拒: {address!r}")

    def guard_create_connection(address, *args, **kwargs):  # noqa: ANN001
        if _is_loopback(address):
            attempts["local"].append(repr(address))
            return real_create(address, *args, **kwargs)
        attempts["external"].append(f"create_connection {address!r}")
        raise RuntimeError(f"VERIFY-R1 外部出站被拒: {address!r}")

    socket.socket.connect = guard_connect
    socket.socket.connect_ex = guard_connect_ex
    socket.create_connection = guard_create_connection
    try:
        yield attempts
    finally:
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex
        socket.create_connection = real_create


# --------------------------------------------------------------------------- #
# 自写替身（不复用 R1 的 MeteredMockAdapter/RealishAdapter/StubGate）
# --------------------------------------------------------------------------- #
class MyTicket:
    def __init__(self, item_id: str, bound_cny: float = 0.018688) -> None:
        self.item_id = item_id
        self.bound_cny = bound_cny

    def as_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": "resv-verify-r1",
            "request_id": "p2req-verify-r1",
            "item_id": self.item_id,
            "cost_center": "answer_retrieval",
            "operation": "answer",
            "bound_cny": self.bound_cny,
        }


class MyStubGate:
    """桩门：is_mock_gate 默认 True；返回金额可按需改（bool 用于验证保守回退）。"""

    def __init__(self, *, is_mock_gate: bool = True, charge: Any = 0.018688) -> None:
        self.is_mock_gate = is_mock_gate
        self.charge = charge
        self.calls: list[str] = []
        self.settled: list[dict[str, Any]] = []

    def begin(self, item_id: str, **_kwargs: Any) -> MyTicket:
        self.calls.append("begin")
        return MyTicket(item_id)

    def confirm_before_send(self, ticket: MyTicket, **_kwargs: Any) -> MyTicket:
        self.calls.append("confirm_before_send")
        return ticket

    def settle_success(self, ticket: MyTicket, **kwargs: Any) -> Any:
        self.calls.append("settle_success")
        self.settled.append({"item_id": ticket.item_id, "status": "succeeded", **kwargs})
        return self.charge

    def settle_failure(self, ticket: MyTicket, **kwargs: Any) -> None:
        self.calls.append("settle_failure")
        self.settled.append({"item_id": ticket.item_id, "status": "failed", **kwargs})


class _StubBase:
    """runner 在发送前被拒时只会用到这些属性（不会 invoke）。"""

    def __init__(self, out_dir: Path, dataset: Any, *, is_mock: bool) -> None:
        from mktkb.evaluation.product_adapter import ProductPaths

        self.paths = ProductPaths.of(out_dir)
        self.dataset = dataset
        self.ingest_plan = None
        self.ingest_receipts: list[Any] = []
        self.turn_timeout_seconds = 60.0
        self.trace_enabled = False
        self.trace_content_mode = "off"
        self.purge_traces_on_close = False
        self.asks: list[str] = []
        self._is_mock = bool(is_mock)

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    def provider_calls(self) -> dict[str, Any]:
        return {
            "chat": {"calls": 0},
            "embedding": {"calls": 0},
            "rerank": {"calls": 0},
            "outbound_network": 0,
            "network": {"outbound_attempts": 0, "mock_intercepted": 0},
        }

    def index_status(self) -> dict[str, Any]:
        return {}

    async def open_conversation(self, **_kwargs: Any) -> str:
        return "00000000-0000-4000-8000-000000000000"

    async def ask_turn(self, question: str, **_kwargs: Any) -> Any:
        self.asks.append(question)
        raise AssertionError("live 被拒的路径不允许真正提问")


class MeteredProductAdapter(ProductEvalAdapter):
    """把"真实出站"注入生产计量器本身：network_stats/顶层/detail 都应跟着动。"""

    def __init__(self, *args: Any, outbound_per_turn: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.outbound_per_turn = int(outbound_per_turn)

    async def ask_turn(self, question: str, **kwargs: Any):  # noqa: ANN201
        turn = await super().ask_turn(question, **kwargs)
        self._meter.outbound_attempts += self.outbound_per_turn
        return turn


class TopOnlyOutboundAdapter(ProductEvalAdapter):
    """复现 R1 probe/digest 的注入方式：只改顶层 outbound_network，不改 network.detail。"""

    def __init__(self, *args: Any, outbound_per_turn: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.outbound_per_turn = int(outbound_per_turn)
        self._injected = 0

    async def ask_turn(self, question: str, **kwargs: Any):  # noqa: ANN201
        turn = await super().ask_turn(question, **kwargs)
        self._injected += self.outbound_per_turn
        return turn

    def provider_calls(self) -> dict[str, Any]:
        payload = super().provider_calls()
        payload["outbound_network"] = int(payload["outbound_network"]) + self._injected
        return payload


class NoOutboundAdapter(ProductEvalAdapter):
    def provider_calls(self) -> dict[str, Any]:
        payload = super().provider_calls()
        payload.pop("outbound_network", None)
        return payload


class NoChatCallsAdapter(ProductEvalAdapter):
    def provider_calls(self) -> dict[str, Any]:
        payload = super().provider_calls()
        payload.pop("chat", None)
        return payload


class RagPostAdapter(ProductEvalAdapter):
    """每轮真实发生一次 RAG 供应商 POST（计机器数，不联网）：验证产物含 RAG 增量。"""

    async def ask_turn(self, question: str, **kwargs: Any):  # noqa: ANN201
        turn = await super().ask_turn(question, **kwargs)
        rag_providers._record_post_attempt("embedding")
        return turn


def files_containing(root: Path, text: str) -> list[str]:
    needle = text.encode("utf-8")
    hits: list[str] = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:  # pragma: no cover
            continue
        if needle in raw:
            hits.append(str(path.relative_to(root)))
    return hits


def measured(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "requests": {
            "real_requests": summary["requests"]["real_requests"],
            "billed_cny": summary["requests"]["billed_cny"],
            "settled_success": summary["requests"]["settled_success"],
        },
        "network": {
            "outbound_attempts": summary["network"]["outbound_attempts"],
            "detail_outbound_attempts": (summary["network"].get("detail") or {}).get(
                "outbound_attempts"
            ),
            "detail": summary["network"].get("detail") or {},
        },
        "providers_outbound_network": summary["providers"]["outbound_network"],
        "holdout": summary.get("holdout"),
    }


# --------------------------------------------------------------------------- #
# F1
# --------------------------------------------------------------------------- #
async def f1_default_mock() -> dict[str, Any]:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    adapter = ProductEvalAdapter(
        scratch("f1-default") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        summary = read_json(adapter.paths.run_dir / "summary.json")
        rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
        payload = {"status": result.status, "stop_code": result.stop_code, "measured": measured(summary)}
        check("F1.mock.real_requests==0", payload["measured"]["requests"]["real_requests"] == 0)
        check("F1.mock.billed_cny==0", payload["measured"]["requests"]["billed_cny"] == 0.0)
        check("F1.mock.top_outbound==0", payload["measured"]["network"]["outbound_attempts"] == 0)
        check(
            "F1.mock.detail_outbound==top",
            payload["measured"]["network"]["detail_outbound_attempts"] == 0,
            str(payload["measured"]["network"]["detail_outbound_attempts"]),
        )
        check(
            "F1.mock.providers_outbound==0",
            payload["measured"]["providers_outbound_network"] == 0,
        )
        check(
            "F1.mock.rows_outbound_all_zero",
            all(int(row["provider_calls"]["outbound"]) == 0 for row in rows),
            str([row["provider_calls"] for row in rows]),
        )
        detail = payload["measured"]["network"]["detail"]
        check(
            "F1.mock.transport_saw_intercept",
            int(detail.get("mock_intercepted", 0)) >= 1,
            str(detail.get("mock_intercepted")),
        )
        check(
            "F1.mock.detail_decomposes",
            int(detail.get("chat_outbound_attempts", -1)) + int(detail.get("rag_provider_posts", -1))
            == payload["measured"]["network"]["outbound_attempts"],
            str(detail),
        )
        return payload
    finally:
        await adapter.close()


async def f1_measured_injection() -> dict[str, Any]:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    adapter = MeteredProductAdapter(
        scratch("f1-metered") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
        outbound_per_turn=2,
    )
    gate = MyStubGate()
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=dry_run_authorization(plan), gate=gate, now=NOW
        )
        summary = read_json(adapter.paths.run_dir / "summary.json")
        rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
        payload = {
            "status": result.status,
            "stop_code": result.stop_code,
            "measured": measured(summary),
            "row_outbound": [row["provider_calls"]["outbound"] for row in rows],
            "row_charged": [row["charged_cny"] for row in rows],
            "gate_settled_cny": result.settled_cny,
            "requests_sent": result.requests_sent,
        }
        m = payload["measured"]
        check("F1.metered.status", result.status == "succeeded", str(result.as_dict()))
        check("F1.metered.top_outbound==4", m["network"]["outbound_attempts"] == 4)
        check(
            "F1.metered.detail_outbound==top",
            m["network"]["detail_outbound_attempts"] == 4,
            str(m["network"]["detail_outbound_attempts"]),
        )
        check("F1.metered.providers==4", m["providers_outbound_network"] == 4)
        check("F1.metered.real_requests==2", m["requests"]["real_requests"] == 2)
        check("F1.metered.billed==2x", m["requests"]["billed_cny"] == 0.037376)
        check("F1.metered.rows_outbound==[2,2]", payload["row_outbound"] == [2, 2], str(payload["row_outbound"]))
        check(
            "F1.metered.rows_charged==0.018688",
            payload["row_charged"] == [0.018688, 0.018688],
            str(payload["row_charged"]),
        )
        check("F1.settled_success_accumulated", result.settled_cny == 0.037376, str(result.settled_cny))
        check("F1.requests_sent==2", result.requests_sent == 2, str(result.requests_sent))
        return payload
    finally:
        await adapter.close()


async def f1_rag_measured_in_artifacts() -> dict[str, Any]:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    adapter = RagPostAdapter(
        scratch("f1-ragrun") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=dry_run_authorization(plan), gate=MyStubGate(), now=NOW
        )
        summary = read_json(adapter.paths.run_dir / "summary.json")
        rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
        m = measured(summary)
        detail = m["network"]["detail"]
        payload = {
            "status": result.status,
            "measured": m,
            "row_outbound": [row["provider_calls"]["outbound"] for row in rows],
        }
        check("F1.ragrun.status", result.status == "succeeded", str(result.as_dict()))
        check("F1.ragrun.top_outbound==2", m["network"]["outbound_attempts"] == 2, str(m))
        check("F1.ragrun.top==detail", m["network"]["detail_outbound_attempts"] == 2, str(m))
        check("F1.ragrun.rag_posts==2", int(detail.get("rag_provider_posts", -1)) == 2, str(detail))
        check("F1.ragrun.real_requests==2", m["requests"]["real_requests"] == 2, str(m))
        check("F1.ragrun.billed==2x", m["requests"]["billed_cny"] == 0.037376, str(m))
        check("F1.ragrun.rows_outbound==[1,1]", payload["row_outbound"] == [1, 1], str(payload))
        check(
            "F1.ragrun.decomposes",
            int(detail.get("chat_outbound_attempts", -1)) + int(detail.get("rag_provider_posts", -1))
            == m["network"]["outbound_attempts"],
            str(detail),
        )
        return payload
    finally:
        await adapter.close()


async def f1_top_only_injection() -> dict[str, Any]:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    adapter = TopOnlyOutboundAdapter(
        scratch("f1-toponly") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
        outbound_per_turn=2,
    )
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=dry_run_authorization(plan), gate=MyStubGate(), now=NOW
        )
        summary = read_json(adapter.paths.run_dir / "summary.json")
        payload = {"status": result.status, "measured": measured(summary)}
        top = payload["measured"]["network"]["outbound_attempts"]
        detail = payload["measured"]["network"]["detail_outbound_attempts"]
        OBSERVATIONS["f1_top_only_contradiction"] = {"top": top, "detail": detail}
        check(
            "F1.top_only.artifacts_not_cross_checked",
            top == 4 and detail == 0 and result.status == "succeeded",
            f"top={top} detail={detail}（R1 digest 即此形态；runner 未报错）",
        )
        return payload
    finally:
        await adapter.close()


async def f1_missing_fields() -> dict[str, Any]:
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    auth = dry_run_authorization(plan)
    out: dict[str, Any] = {}
    for label, cls in (("outbound", NoOutboundAdapter), ("chat", NoChatCallsAdapter)):
        adapter = cls(
            scratch(f"f1-missing-{label}") / "run",
            chat=MockChatBackend(),
            dataset=make_dataset(cases),
            ingest_plan=make_ingest_plan(),
        )
        try:
            await run_p2(plan, adapter=adapter, authorization=auth, now=NOW)
            out[label] = {"raised": None}
        except Exception as exc:  # noqa: BLE001 - 期望失败
            out[label] = {"raised": type(exc).__name__, "message": str(exc)}
        finally:
            await adapter.close()
        check(
            f"F1.missing_{label}_raises",
            out[label]["raised"] is not None,
            json.dumps(out[label], ensure_ascii=False),
        )
    check(
        "F1.missing_outbound_message",
        "outbound_network" in str(out["outbound"].get("message", "")),
        str(out["outbound"]),
    )
    return out


def f1_rag_post_increment() -> dict[str, Any]:
    rag_providers.reset_post_counters()
    adapter = ProductEvalAdapter(scratch("f1-rag") / "run", dataset=None)
    try:
        base = adapter.network_stats()
        rag_providers._record_post_attempt("embedding")
        rag_providers._record_post_attempt("rerank")
        after = adapter.network_stats()
        payload = {
            "baseline": base,
            "after_increment": after,
            "outbound_from_provider_calls": adapter.provider_calls()["outbound_network"],
        }
        check("F1.rag.rag_posts==2", after["rag_provider_posts"] == 2, str(after))
        check("F1.rag.outbound==2", after["outbound_attempts"] == 2, str(after))
        check(
            "F1.rag.provider_calls_follows",
            payload["outbound_from_provider_calls"] == 2,
            str(payload),
        )
        return payload
    finally:
        rag_providers.reset_post_counters()


# --------------------------------------------------------------------------- #
# F2
# --------------------------------------------------------------------------- #
async def f2_live_gates() -> dict[str, Any]:
    cases = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cases)
    auth_live = replace(dry_run_authorization(plan), production_ready=True)
    out: dict[str, Any] = {}

    for label, gate in (
        ("stub", MyStubGate(is_mock_gate=True)),
        ("duck_false_flag", MyStubGate(is_mock_gate=False)),
    ):
        adapter = _StubBase(scratch(f"f2-{label}") / "run", make_dataset(cases), is_mock=False)
        result = await run_p2(plan, adapter=adapter, authorization=auth_live, gate=gate, now=NOW)
        gate_payload = read_json(adapter.paths.run_dir / "gate.json")
        summary = read_json(adapter.paths.run_dir / "summary.json")
        failed = sorted(name for name, ok in ((c["name"], c["ok"]) for c in gate_payload["checks"]) if not ok)
        out[label] = {
            "status": result.status,
            "stop_code": result.stop_code,
            "execution": gate_payload["execution"],
            "real_sends_allowed": gate_payload["real_sends_allowed"],
            "failed_checks": failed,
            "gate_calls": gate.calls,
            "adapter_asks": adapter.asks,
            "real_requests": summary["requests"]["real_requests"],
            "stage": summary["failure"]["stage"],
        }
        check(f"F2.{label}.blocked", out[label]["status"] == "blocked", str(out[label]))
        check(f"F2.{label}.stop", out[label]["stop_code"] == "live_requires_real_gate", str(out[label]))
        check(f"F2.{label}.execution_live", out[label]["execution"] == "live", str(out[label]))
        check(f"F2.{label}.real_sends_false", out[label]["real_sends_allowed"] is False, str(out[label]))
        check(f"F2.{label}.only_live_gate_failed", out[label]["failed_checks"] == ["live_gate"], str(out[label]))
        check(f"F2.{label}.gate_zero_steps", out[label]["gate_calls"] == [], str(out[label]))
        check(f"F2.{label}.adapter_zero_calls", out[label]["adapter_asks"] == [], str(out[label]))
        check(f"F2.{label}.real_requests_zero", out[label]["real_requests"] == 0, str(out[label]))

    # 真实 P2Gate 实例配 Mock 适配器：旧护栏不能放松（mock_gate_requires_stub_gate）。
    mock_adapter = _StubBase(scratch("f2-mock-real") / "run", make_dataset(cases), is_mock=True)
    real_gate_instance = P2Gate.__new__(P2Gate)  # 只判类型，不构造账本/GO；不会被调用
    result = await run_p2(
        plan, adapter=mock_adapter, authorization=dry_run_authorization(plan), gate=real_gate_instance, now=NOW
    )
    gate_payload = read_json(mock_adapter.paths.run_dir / "gate.json")
    failed = [c["name"] for c in gate_payload["checks"] if not c["ok"]]
    out["mock_with_real_gate"] = {
        "status": result.status,
        "stop_code": result.stop_code,
        "execution": gate_payload["execution"],
        "failed_checks": failed,
        "real_sends_allowed": gate_payload["real_sends_allowed"],
    }
    check(
        "F2.mock_with_real_gate_still_rejected",
        result.stop_code == "mock_gate_requires_stub_gate",
        str(out["mock_with_real_gate"]),
    )

    # 真实适配器 + 无门：adapter_must_be_mock 仍成立。
    real_adapter = _StubBase(scratch("f2-real-nogate") / "run", make_dataset(cases), is_mock=False)
    result = await run_p2(plan, adapter=real_adapter, authorization=dry_run_authorization(plan), now=NOW)
    out["real_no_gate"] = {"status": result.status, "stop_code": result.stop_code}
    check(
        "F2.real_no_gate_still_rejected",
        result.stop_code == "adapter_must_be_mock",
        str(out["real_no_gate"]),
    )

    # 类型判定：只有真实 P2Gate（且无 is_mock_gate）为 True。
    class _FakeMockP2Gate(P2Gate):
        is_mock_gate = True

    type_cases = {
        "none": is_real_p2_gate(None),
        "object": is_real_p2_gate(object()),
        "stub_true": is_real_p2_gate(MyStubGate(is_mock_gate=True)),
        "stub_false": is_real_p2_gate(MyStubGate(is_mock_gate=False)),
        "real_new": is_real_p2_gate(P2Gate.__new__(P2Gate)),
        "p2gate_subclass_mock_flag": is_real_p2_gate(_FakeMockP2Gate.__new__(_FakeMockP2Gate)),
    }
    out["type_checks"] = type_cases
    check(
        "F2.type_checks",
        type_cases == {
            "none": False,
            "object": False,
            "stub_true": False,
            "stub_false": False,
            "real_new": True,
            "p2gate_subclass_mock_flag": False,
        },
        str(type_cases),
    )
    return out


# --------------------------------------------------------------------------- #
# F3 / F6
# --------------------------------------------------------------------------- #
async def f3_holdout_without_purge() -> dict[str, Any]:
    cases = (make_case("H01", RAG_QUESTION),)
    plan = make_plan(cases)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        scratch("f3-nopurge") / "run",
        chat=chat,
        dataset=make_dataset(cases, visibility="holdout", manifest_sha256="e" * 64),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        summary = read_json(adapter.paths.run_dir / "summary.json")
        calls = adapter.provider_calls()
        files = sorted(path.name for path in adapter.paths.run_dir.iterdir() if path.is_file())
        plaintext = files_containing(adapter.paths.root, RAG_QUESTION)
        payload = {
            "status": result.status,
            "stop_code": result.stop_code,
            "execution": summary["execution"],
            "failure_stage": summary["failure"]["stage"],
            "holdout": summary["holdout"],
            "ingest_receipts": len(adapter.ingest_receipts),
            "chat_calls": chat.call_count,
            "embedding_calls": calls["embedding"]["calls"],
            "trace_db_exists": adapter.paths.trace_db.exists(),
            "business_db_exists": adapter.paths.business_db.exists(),
            "run_files": files,
            "question_plaintext_hits": plaintext,
        }
        check("F3.blocked", result.status == "blocked", str(payload))
        check("F3.stop", result.stop_code == "holdout_requires_purge", str(payload))
        check("F3.stage", payload["failure_stage"] == "holdout_policy", str(payload))
        check("F3.no_ingest", payload["ingest_receipts"] == 0, str(payload))
        check("F3.no_chat", payload["chat_calls"] == 0, str(payload))
        check("F3.no_embedding", payload["embedding_calls"] == 0, str(payload))
        check("F3.no_trace_db", payload["trace_db_exists"] is False, str(payload))
        check("F3.no_business_db_created", payload["business_db_exists"] is False, str(payload))
        check("F3.no_question_plaintext", payload["question_plaintext_hits"] == [], str(payload))
        check(
            "F3.aggregate_only_artifacts",
            "holdout_aggregate.json" in files
            and "cases.jsonl" not in files
            and "requests.jsonl" not in files,
            str(files),
        )
        check(
            "F3.trace_retention_refused",
            summary["holdout"]["trace_retention"] == "refused-before-start",
            str(summary["holdout"]),
        )
        OBSERVATIONS["f3_question_store_label"] = {
            "value": summary["holdout"]["question_store"],
            "business_db_exists": adapter.paths.business_db.exists(),
            "note": "业务库从未创建，但 summary 已写 deleted-at-close（标签非测量）",
        }
        return payload
    finally:
        await adapter.close()


async def f6_holdout_sealed() -> dict[str, Any]:
    cases = (make_case("H91", SENTINEL),)
    plan = make_plan(cases)
    adapter = ProductEvalAdapter(
        scratch("f6-sealed") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases, visibility="holdout", manifest_sha256="f" * 64),
        ingest_plan=make_ingest_plan(),
        purge_traces_on_close=True,
    )
    out_dir = adapter.paths.root
    before: list[str] = []
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        before = files_containing(out_dir, SENTINEL)
        summary = read_json(adapter.paths.run_dir / "summary.json")
        payload: dict[str, Any] = {
            "status": result.status,
            "stop_code": result.stop_code,
            "plaintext_hits_before_close": before,
            "holdout": summary["holdout"],
        }
        check("F6.holdout.status", result.status == "succeeded", str(result.as_dict()))
        check("F6.before_close_has_plaintext", bool(before), str(before))
    finally:
        await adapter.close()
    after = files_containing(out_dir, SENTINEL)
    payload.update(
        {
            "seal_receipt": adapter.seal_receipt,
            "plaintext_hits_after_close": after,
            "business_db_family": {
                suffix: adapter.paths.business_db.with_name(
                    adapter.paths.business_db.name + suffix
                ).exists()
                for suffix in ("", "-wal", "-shm", "-journal")
            },
            "trace_db_exists": adapter.paths.trace_db.exists(),
            "aggregate_exists": (adapter.paths.run_dir / "holdout_aggregate.json").is_file(),
            "cases_jsonl_exists": (adapter.paths.run_dir / "cases.jsonl").exists(),
            "requests_jsonl_exists": (adapter.paths.run_dir / "requests.jsonl").exists(),
            "detail_files": sorted(path.name for path in adapter.paths.run_dir.iterdir() if path.is_file()),
        }
    )
    check("F6.after_close_zero_plaintext", after == [], str(after))
    check(
        "F6.business_db_family_deleted",
        not any(payload["business_db_family"].values()),
        str(payload["business_db_family"]),
    )
    check("F6.trace_db_deleted", payload["trace_db_exists"] is False)
    check("F6.aggregate_kept", payload["aggregate_exists"] is True, str(payload["detail_files"]))
    check(
        "F6.no_per_case_artifacts",
        payload["cases_jsonl_exists"] is False and payload["requests_jsonl_exists"] is False,
    )
    check(
        "F6.seal_receipt",
        (payload["seal_receipt"] or {}).get("question_store") == "deleted",
        str(payload["seal_receipt"]),
    )
    check(
        "F6.summary_flags",
        payload["holdout"]["trace_retention"] == "purged-at-close"
        and payload["holdout"]["question_store"] == "deleted-at-close",
        str(payload["holdout"]),
    )
    return payload


async def f6_public_path_keeps_store() -> dict[str, Any]:
    cases = (make_case("P01", SENTINEL_PUBLIC),)
    plan = make_plan(cases)
    adapter = ProductEvalAdapter(
        scratch("f6-public") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    out_dir = adapter.paths.root
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        summary = read_json(adapter.paths.run_dir / "summary.json")
    finally:
        await adapter.close()
    payload = {
        "status": result.status,
        "business_db_exists": adapter.paths.business_db.exists(),
        "plaintext_hits_after_close": files_containing(out_dir, SENTINEL_PUBLIC),
        "question_store": summary["holdout"]["question_store"],
        "cases_jsonl_exists": (adapter.paths.run_dir / "cases.jsonl").is_file(),
        "requests_jsonl_exists": (adapter.paths.run_dir / "requests.jsonl").is_file(),
        "seal_receipt": adapter.seal_receipt,
    }
    check("F6.public.status", result.status == "succeeded", str(result.as_dict()))
    check("F6.public.business_db_kept", payload["business_db_exists"] is True, str(payload))
    check("F6.public.no_seal", payload["seal_receipt"] is None, str(payload))
    check("F6.public.question_store_label", payload["question_store"] == "kept-in-isolated-dir", str(payload))
    check(
        "F6.public.per_case_artifacts_kept",
        payload["cases_jsonl_exists"] and payload["requests_jsonl_exists"],
        str(payload),
    )
    return payload


async def f6_delete_failure_raises() -> dict[str, Any]:
    cases = (make_case("H92", SENTINEL),)
    plan = make_plan(cases)
    adapter = ProductEvalAdapter(
        scratch("f6-fail") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases, visibility="holdout", manifest_sha256="1" * 64),
        ingest_plan=make_ingest_plan(),
        purge_traces_on_close=True,
    )
    journal = adapter.paths.business_db.with_name(adapter.paths.business_db.name + "-journal")
    raised: dict[str, Any] = {}
    try:
        await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        if journal.exists():
            journal.unlink()
        journal.mkdir(parents=True, exist_ok=True)  # 让 unlink 必然失败（目录不可 unlink）
        try:
            await adapter.close()
            raised = {"raised": None}
        except Exception as exc:  # noqa: BLE001 - 期望失败
            raised = {"raised": type(exc).__name__, "message": str(exc)}
    finally:
        if adapter._closed is False:  # pragma: no cover
            await adapter.close()
        import shutil

        shutil.rmtree(adapter.paths.root.parent, ignore_errors=True)
    check("F6.delete_failure_raises", raised.get("raised") is not None, json.dumps(raised, ensure_ascii=False))
    return raised


# --------------------------------------------------------------------------- #
# 结算口径
# --------------------------------------------------------------------------- #
async def settle_semantics() -> dict[str, Any]:
    cases = (make_case("P03", LEGACY_QUESTION),)
    plan = make_plan(cases)
    out: dict[str, Any] = {}
    # 1) 纯 mock_gate：成功结算累计 0.018688，但无出站 -> billed=0（两套口径）。
    adapter = ProductEvalAdapter(
        scratch("settle-mockgate") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    gate = MyStubGate(is_mock_gate=True)
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), gate=gate, now=NOW)
        summary = read_json(adapter.paths.run_dir / "summary.json")
        rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
        out["mock_gate"] = {
            "settled_cny": result.settled_cny,
            "billed_cny": summary["requests"]["billed_cny"],
            "real_requests": summary["requests"]["real_requests"],
            "row_charged": [row["charged_cny"] for row in rows],
        }
        check("SETTLE.mock_gate.settled", result.settled_cny == 0.018688, str(out["mock_gate"]))
        check("SETTLE.mock_gate.billed_zero", summary["requests"]["billed_cny"] == 0.0, str(out["mock_gate"]))
        check("SETTLE.mock_gate.row_charged", out["mock_gate"]["row_charged"] == [0.018688], str(out["mock_gate"]))
    finally:
        await adapter.close()

    # 2) 门返回 bool（非金额）：保守回退到该笔预留上界，而不是记 0。
    adapter = ProductEvalAdapter(
        scratch("settle-bool") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cases),
        ingest_plan=make_ingest_plan(),
    )
    gate = MyStubGate(is_mock_gate=True, charge=True)
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), gate=gate, now=NOW)
        rows = read_jsonl(adapter.paths.run_dir / "requests.jsonl")
        out["bool_gate"] = {"settled_cny": result.settled_cny, "row_charged": [r["charged_cny"] for r in rows]}
        check("SETTLE.bool_gate.conservative_bound", result.settled_cny == 0.018688, str(out["bool_gate"]))
    finally:
        await adapter.close()
    return out


# --------------------------------------------------------------------------- #
async def main() -> dict[str, Any]:
    with outbound_guard() as attempts:
        scenarios = {
            "f1_default_mock": await f1_default_mock(),
            "f1_measured_injection": await f1_measured_injection(),
            "f1_rag_measured_in_artifacts": await f1_rag_measured_in_artifacts(),
            "f1_top_only_injection": await f1_top_only_injection(),
            "f1_missing_fields": await f1_missing_fields(),
            "f1_rag_post_increment": f1_rag_post_increment(),
            "f2_live_gates": await f2_live_gates(),
            "f3_holdout_without_purge": await f3_holdout_without_purge(),
            "f6_holdout_sealed": await f6_holdout_sealed(),
            "f6_public_path": await f6_public_path_keeps_store(),
            "f6_delete_failure": await f6_delete_failure_raises(),
            "settle_semantics": await settle_semantics(),
        }
        external = list(attempts["external"])
        local = list(attempts["local"])
    check("NET.external==0", external == [], str(external))
    check(
        "F1.post_counters_end_zero",
        all(total == 0 for total in (rag_providers.post_counters().get("attempts") or {}).values()),
        str(rag_providers.post_counters()),
    )
    failed = [c for c in CHECKS if not c["ok"]]
    return {
        "schema": "p2-t203-r1-verify-digest/v0.1",
        "ok": not failed,
        "counts": {"checks": len(CHECKS), "failed": len(failed)},
        "failed": failed,
        "network": {"external_attempts": external, "local_attempts": len(local)},
        "observations": OBSERVATIONS,
        "scenarios": scenarios,
        "checks": CHECKS,
    }


if __name__ == "__main__":
    digest = asyncio.run(main())
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(digest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": digest["ok"],
                "counts": digest["counts"],
                "failed": [c["name"] for c in digest["failed"]],
                "external": len(digest["network"]["external_attempts"]),
                "f1_injected": {
                    "top": digest["scenarios"]["f1_measured_injection"]["measured"]["network"]["outbound_attempts"],
                    "detail": digest["scenarios"]["f1_measured_injection"]["measured"]["network"]["detail_outbound_attempts"],
                    "real_requests": digest["scenarios"]["f1_measured_injection"]["measured"]["requests"]["real_requests"],
                    "billed": digest["scenarios"]["f1_measured_injection"]["measured"]["requests"]["billed_cny"],
                },
                "f2_stop": digest["scenarios"]["f2_live_gates"]["stub"]["stop_code"],
                "f3_stop": digest["scenarios"]["f3_holdout_without_purge"]["stop_code"],
                "f6_before": len(digest["scenarios"]["f6_holdout_sealed"]["plaintext_hits_before_close"]),
                "f6_after": len(digest["scenarios"]["f6_holdout_sealed"]["plaintext_hits_after_close"]),
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    raise SystemExit(0 if digest["ok"] else 1)
