"""T203 独立验收探针 2：单轮时限口径 + 超时/服务错误停止语义（不重试、后续 case 不执行）。

自写断言：
1. 产品单轮 60 秒总时限：conversations.service.BUDGET_SECONDS == 60 == 适配器默认值
   == runner 产物 pipeline.turn_timeout_seconds；
2. 短超时（客户端硬截止 0.2s）下：run 以 turn_timeout 停，失败现场写 stage=product_wait，
   第二个 case 未执行，chat 只发生 1 次（0 重试）；
3. 产品 503（service_error）：run 以 product_service_error 停，第二个 case 不执行，
   chat 仍只 1 次（不重复付费）。
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[8]
sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.conversations.service import BUDGET_SECONDS  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_authorization import preflight_p2  # noqa: E402
from mktkb.evaluation.p2_contracts import (  # noqa: E402
    CHAT_HOST,
    CHAT_MODEL,
    CHAT_PRICING_SOURCE,
    CHAT_PROVIDER,
    CHAT_REGION,
    COST_CENTERS,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
    P2LedgerSnapshot,
    P2PriceProfile,
    P2RequestItem,
    P2RunPlan,
)
from mktkb.evaluation.p2_runner import build_dry_run_authorization, run_p2  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    PRODUCT_TURN_TIMEOUT_SECONDS,
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
D04 = REPO / "fixtures" / "acceptance" / "normal" / "D04_活动策划流程.docx"
LEGACY_Q = "活动策划需要哪些步骤？"
RAG_Q = "把城东店和城西店的宣传海报记录都列出来"


def profile() -> P2PriceProfile:
    return P2PriceProfile(
        kind="chat", model=CHAT_MODEL, provider=CHAT_PROVIDER, host=CHAT_HOST,
        region=CHAT_REGION, pricing_source=CHAT_PRICING_SOURCE,
        input_price_per_million_cny=2.0, output_price_per_million_cny=8.0,
        prompt_tokens_cap=6144, completion_tokens_cap=800,
    )


def cases() -> tuple[CaseSpec, ...]:
    return (
        CaseSpec(case_id="V01", suite="probe", split="holdout", stratum="paraphrase",
                 business_date="2026-11-10", question=LEGACY_Q, turns=(), label_version="probe"),
        CaseSpec(case_id="V02", suite="probe", split="holdout", stratum="paraphrase",
                 business_date="2026-11-10", question=RAG_Q, turns=(), label_version="probe"),
    )


def plan(chosen: tuple[CaseSpec, ...]) -> P2RunPlan:
    items = tuple(
        P2RequestItem(
            item_id=f"{c.case_id}:turn{n}:answer", operation="answer", cost_center="answer_retrieval",
            case_id=c.case_id, turn=n, page=0, requests=1, price_profile=profile(),
            expected_success_cny=0.001,
        )
        for c in chosen
        for n in range(1, (len(c.turns) if len(c.turns) >= 2 else 1) + 1)
    )
    return P2RunPlan(
        schema_version="p2-run-plan/v0.1", plan_id="verify-probe2", plan_version="v1",
        mode="end_to_end", stage="P2-LIVE", created_utc="2026-11-10T00:00:00+00:00",
        project_total_limit_cny=40.0, stage_limit_cny=20.0, max_requests=1000,
        cost_centers_cny={"answer_retrieval": 12.0, "ocr": 3.0, "judge": 3.0, "independent": 2.0},
        items=items,
    )


def snapshot(p: P2RunPlan) -> P2LedgerSnapshot:
    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION, ledger_path="in-memory:verify",
        ledger_sha256="0" * 64, historical_prefix_sha256="1" * 64, budget_sha256="2" * 64,
        total_limit_cny=float(p.project_total_limit_cny), historical_accounted_cny=15.0709445,
        accounted_cny=15.0709445, reservation_count=505, result_count=505,
        stage_allocations_cny={"S2-DEV": 3.0, "P1-RETRIEVAL": 2.0, "P2-LIVE": 20.0},
        p2_stage_accounted_cny=0.0, p2_center_accounted_cny={c: 0.0 for c in COST_CENTERS},
        source="in-memory",
    )


def dataset(chosen: tuple[CaseSpec, ...]) -> P2RunDataset:
    return P2RunDataset(
        visibility="public", cases=chosen,
        identity={"dataset_version": "verify-probe2", "label_version": "probe",
                  "suite": "probe", "manifest_sha256": "e" * 64, "case_count": len(chosen)},
    )


from dataclasses import dataclass, field  # noqa: E402


@dataclass
class StubGate:
    is_mock_gate: bool = True
    calls: list = field(default_factory=list)

    def begin(self, item_id: str, **_kwargs):
        self.calls.append(("begin", item_id))
        return _StubTicket(item_id)

    def confirm_before_send(self, ticket, **_kwargs):
        self.calls.append(("confirm", ticket.item_id))
        return ticket

    def settle_success(self, ticket, **_kwargs):
        self.calls.append(("settle_success", ticket.item_id))
        return 0.0

    def settle_failure(self, ticket, **_kwargs):
        self.calls.append(("settle_failure", ticket.item_id))


@dataclass
class _StubTicket:
    item_id: str
    bound_cny: float = 0.018688

    def as_dict(self):
        return {"reservation_id": "stub", "request_id": "stub", "item_id": self.item_id,
                "cost_center": "answer_retrieval", "operation": "answer", "bound_cny": self.bound_cny}


class RealishAdapter:
    """is_mock=False 的替身：只用于验证"真实适配器 + 无门"必须拒绝。"""

    def __init__(self, out_dir: Path, ds: P2RunDataset) -> None:
        from mktkb.evaluation.product_adapter import ProductPaths
        self.paths = ProductPaths.of(out_dir)
        self.dataset = ds
        self.ingest_plan = None
        self.ingest_receipts: list = []
        self.turn_timeout_seconds = 60.0
        self.trace_enabled = False
        self.trace_content_mode = "off"
        self.purge_traces_on_close = False
        self.asks: list[str] = []

    @property
    def is_mock(self) -> bool:
        return False

    def provider_calls(self) -> dict:
        return {"chat": {"calls": 0}, "embedding": {"calls": 0}, "rerank": {"calls": 0}}

    def index_status(self) -> dict:
        return {}

    async def open_conversation(self, **_kwargs) -> str:
        return "00000000-0000-4000-8000-000000000000"

    async def ask_turn(self, question: str, **_kwargs):
        self.asks.append(question)
        raise AssertionError("真实适配器替身不该被调用：无门时必须在授权阶段拒绝")

    def purge_traces(self) -> list[str]:
        return []


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="p2t203-probe2-"))
    result: dict = {"probe": "stop_semantics", "ok": False, "checks": []}
    result["scratch_root"] = str(root)

    def check(name, ok, detail=None):
        result["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise AssertionError(f"{name}: {detail!r}")

    chosen = cases()
    p = plan(chosen)
    pre = preflight_p2(p, snapshot(p))
    check("preflight_ok", pre.ok and pre.production_ready is False, list(pre.reasons))
    auth = build_dry_run_authorization(p, pre, now=NOW, nonce="0f" * 16)
    ds = dataset(chosen)

    async def scenario() -> None:
        # 1) 时限口径
        check("budget_seconds_is_60", float(BUDGET_SECONDS) == 60.0, BUDGET_SECONDS)
        check("adapter_default_timeout_is_budget", PRODUCT_TURN_TIMEOUT_SECONDS == 60.0, PRODUCT_TURN_TIMEOUT_SECONDS)

        # 2) 超时
        chat = MockChatBackend(behaviors=(ChatBehavior(kind="delay", delay_seconds=1.0),))
        adapter = ProductEvalAdapter(
            root / "timeout", chat=chat, dataset=ds, turn_timeout_seconds=0.2,
            ingest_plan=P2IngestPlan(sources=(IngestSource(path=D04),), label="probe2"),
        )
        try:
            check("default_timeout_on_fresh_adapter",
                  ProductEvalAdapter(root / "instant", dataset=ds).turn_timeout_seconds == 60.0)
            res = await run_p2(p, adapter=adapter, authorization=auth, now=NOW)
            summary = read_json(adapter.paths.run_dir / "summary.json")
            manifest = read_json(adapter.paths.run_dir / "run_manifest.json")
            requests = (adapter.paths.run_dir / "requests.jsonl").read_text(encoding="utf-8").strip().splitlines()
        finally:
            await adapter.close()
        check("timeout_status_aborted", res.status == "aborted", res.as_dict())
        check("timeout_stop_code", res.stop_code == "turn_timeout", res.stop_code)
        check("timeout_zero_sent", res.requests_sent == 0 and res.requests_reserved == 0, res.as_dict())
        check("timeout_failure_stage", summary["failure"]["stage"] == "product_wait", summary.get("failure"))
        check("timeout_failure_seconds", summary["failure"]["timeout_seconds"] == 0.2, summary.get("failure"))
        check("timeout_manifest_matches", manifest["pipeline"]["turn_timeout_seconds"] == 0.2,
              manifest["pipeline"]["turn_timeout_seconds"])
        check("timeout_no_retry_one_chat", chat.call_count == 1, chat.call_count)
        check("timeout_second_case_not_executed",
              summary["cases"]["executed"] == 1 and summary["cases"]["not_executed"] == 1, summary["cases"])
        check("timeout_request_row_single", len(requests) == 1, len(requests))

        # 3) 服务错误
        chat2 = MockChatBackend(behaviors=(ChatBehavior(kind="http_error", status_code=503),))
        adapter2 = ProductEvalAdapter(
            root / "service", chat=chat2, dataset=ds,
            ingest_plan=P2IngestPlan(sources=(IngestSource(path=D04),), label="probe2b"),
        )
        try:
            res2 = await run_p2(p, adapter=adapter2, authorization=auth, now=NOW)
            summary2 = read_json(adapter2.paths.run_dir / "summary.json")
        finally:
            await adapter2.close()
        check("service_error_aborted", res2.status == "aborted" and res2.stop_code == "product_service_error",
              res2.as_dict())
        check("service_error_failure_stage", summary2["failure"]["stage"] == "product_answer", summary2.get("failure"))
        check("service_error_no_retry", chat2.call_count == 1, chat2.call_count)
        check("service_error_second_case_not_executed",
              summary2["cases"]["executed"] == 1 and summary2["cases"]["not_executed"] == 1, summary2["cases"])

    async def scenario2() -> None:
        # 4) 真实适配器 + 无门 -> 发送前拒绝（契约 §2 规则 1；开发用例未覆盖）
        realish = RealishAdapter(root / "realish", ds)
        res3 = await run_p2(p, adapter=realish, authorization=auth, now=NOW)
        check("real_adapter_without_gate_blocked", res3.status == "blocked"
              and res3.stop_code == "adapter_must_be_mock", res3.as_dict())
        check("real_adapter_without_gate_never_asked", realish.asks == [], realish.asks)

        # 5) 多轮中间失败：第 1 轮成功、第 2 轮 503 -> 保留 turn/item/ticket 且后续 case 不执行
        multi_case = CaseSpec(
            case_id="V03", suite="probe", split="holdout", stratum="multi_turn",
            business_date="2026-11-10", question=LEGACY_Q,
            turns=({"role": "user", "question": LEGACY_Q}, {"role": "user", "question": LEGACY_Q}),
            label_version="probe",
        )
        tail_case = CaseSpec(case_id="V04", suite="probe", split="holdout", stratum="paraphrase",
                             business_date="2026-11-10", question=RAG_Q, turns=(), label_version="probe")
        chosen2 = (multi_case, tail_case)
        p2_plan = plan(chosen2)
        pre2 = preflight_p2(p2_plan, snapshot(p2_plan))
        auth2 = build_dry_run_authorization(p2_plan, pre2, now=NOW, nonce="1e" * 16)
        chat3 = MockChatBackend(behaviors=(ChatBehavior(), ChatBehavior(kind="http_error", status_code=503)))
        adapter3 = ProductEvalAdapter(
            root / "multiturn", chat=chat3, dataset=dataset(chosen2),
            ingest_plan=P2IngestPlan(sources=(IngestSource(path=D04),), label="probe2c"),
        )
        try:
            res4 = await run_p2(p2_plan, adapter=adapter3, authorization=auth2, now=NOW)
            summary4 = read_json(adapter3.paths.run_dir / "summary.json")
            cases4 = [json.loads(line) for line in
                      (adapter3.paths.run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        finally:
            await adapter3.close()
        failure = summary4["failure"]
        check("midturn_failure_stops", res4.status == "aborted" and res4.stop_code == "product_service_error",
              res4.as_dict())
        check("midturn_failure_identity",
              failure["stage"] == "product_answer" and failure["case_id"] == "V03"
              and failure["turn"] == 2 and failure["item_id"] == "V03:turn2:answer",
              {k: failure.get(k) for k in ("stage", "case_id", "turn", "item_id")})
        check("midturn_failure_keeps_ticket", isinstance(failure.get("ticket"), dict)
              and failure["ticket"].get("dry_run") is True, failure.get("ticket"))
        check("midturn_turn1_recorded", cases4[0]["turns"][0]["status"] == "ok"
              and cases4[0]["turns"][1]["status"] == "error", [t["status"] for t in cases4[0]["turns"]])
        check("midturn_next_case_not_executed",
              summary4["cases"]["executed"] == 1 and summary4["cases"]["not_executed"] == 1,
              summary4["cases"])
        check("midturn_no_extra_chat", chat3.call_count == 2, chat3.call_count)

    async def scenario3() -> None:
        # 6) 契约偏差取证：live 分支没有断言"门必须非桩"——真实适配器 + 桩门 + production_ready=True
        #    会被判成 live（如果门也是桩，就不存在真实账本预留）。这里只取证，不发送。
        import dataclasses
        ready_auth = dataclasses.replace(auth, production_ready=True)
        probe = RealishAdapter(root / "live-stub", ds)
        stub_gate = StubGate(is_mock_gate=True)
        res5 = await run_p2(p, adapter=probe, authorization=ready_auth, gate=stub_gate, now=NOW)
        gate_payload = read_json(probe.paths.run_dir / "gate.json")
        result["live_with_stub_gate"] = {
            "execution": gate_payload["execution"],
            "real_sends_allowed": gate_payload["real_sends_allowed"],
            "stop_code": res5.stop_code,
            "stub_gate_calls": stub_gate.calls,
        }

    try:
        asyncio.run(scenario3())
        asyncio.run(scenario2())
        asyncio.run(scenario())
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-2000:]
    Path(__file__).resolve().with_name("probe2_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": result.get("ok"), "error": result.get("error"),
                      "failed": [c["name"] for c in result["checks"] if not c["ok"]],
                      "checks": len(result["checks"])}, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
