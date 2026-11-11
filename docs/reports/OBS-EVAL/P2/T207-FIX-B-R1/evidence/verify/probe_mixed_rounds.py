"""P2-T207-FIX-B-R1 独立验收：混合轮次（先成功后 J1 拒绝）不双重计数。

复用 test_p2_runner.py 的离线脚手架（StubGate / MockChatBackend / tmp 目录），零真实出站。
输出 JSON：run_result、summary.requests、逐请求行，以及"成功额 + 拒绝额"的加总核对。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "src" / "mktkb" / "evaluation" / "p2_runner.py").exists()
)
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND / "tests"))
sys.path.insert(0, str(BACKEND / "src"))

_SPEC = importlib.util.spec_from_file_location(
    "probe_runner_helpers", BACKEND / "tests" / "evaluation" / "test_p2_runner.py"
)
r = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = r
assert _SPEC.loader is not None
_SPEC.loader.exec_module(r)

from mktkb.evaluation.p2_authorization import P2GateError  # noqa: E402


class MixedGate(r.StubGate):
    """第一轮按 0.000384 成功结算；第二轮模拟 J1 拒绝（不写账本，桩门无账本）。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._settle_calls = 0

    def settle_success(self, ticket, **kwargs):
        self._settle_calls += 1
        self.calls.append("settle_success")
        if self._settle_calls == 1:
            return 0.000384
        raise P2GateError("usage_total_mismatch", "SettlementNotReleasable")


async def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="p2-fixbr1-mixed-"))
    case = r.make_case(
        "P02",
        r.FOLLOWUP_QUESTION,
        turns=(
            {"role": "user", "question": r.RAG_QUESTION},
            {"role": "user", "question": r.FOLLOWUP_QUESTION},
        ),
        stratum="multi_turn",
    )
    cases = (case,)
    plan = r.make_plan(cases)
    authorization = r.dry_run_authorization(plan)
    adapter = r.ProductEvalAdapter(
        base / "mixed",
        chat=r.MockChatBackend(),
        dataset=r.make_dataset(cases),
        ingest_plan=r.make_ingest_plan(),
    )
    gate = MixedGate(is_mock_gate=True)
    try:
        result = await r.run_p2(
            plan, adapter=adapter, authorization=authorization, gate=gate, now=r.NOW
        )
    finally:
        await adapter.close()

    run_dir = adapter.paths.run_dir
    summary = r.read_json(run_dir / "summary.json")
    requests = summary["requests"]
    rows = r.read_jsonl(run_dir / "requests.jsonl")
    report = {
        "status": result.status,
        "stop_code": result.stop_code,
        "requests_sent": result.requests_sent,
        "settled_cny": result.settled_cny,
        "by_center_cny": dict(result.by_center_cny),
        "summary_requests": requests,
        "requests_jsonl": [
            {
                "turn": row.get("turn"),
                "status": row.get("status"),
                "billed": row.get("billed"),
                "error_code": row.get("error_code"),
                "charged_cny": row.get("charged_cny"),
            }
            for row in rows
        ],
        "invariants": {
            "rejected_rounds_key_present": "rejected_rounds" in requests,
            "rejected_rounds": requests.get("rejected_rounds"),
            "settled_success": requests["settled_success"],
            "settled_failure": requests["settled_failure"],
            "unpaid_rounds": requests["unpaid_rounds"],
            "count_sum": int(requests["settled_success"])
            + int(requests["settled_failure"])
            + int(requests["unpaid_rounds"])
            + int(requests.get("rejected_rounds") or 0),
            "requests_rows": len(rows),
            "charged_sum_rows": round(sum(float(row.get("charged_cny") or 0.0) for row in rows), 8),
            "summary_held_cny": requests["conservative_held_cny"],
            "held_equals_charged_sum_rows": requests["conservative_held_cny"]
            == round(sum(float(row.get("charged_cny") or 0.0) for row in rows), 8),
            "settled_equals_charged_sum_rows": round(float(result.settled_cny), 8)
            == round(sum(float(row.get("charged_cny") or 0.0) for row in rows), 8),
        },
    }
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
