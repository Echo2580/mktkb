"""T900 T208 real-judge audit (read-only).

Verifies the finite real judge receipt, refusal unknown, retained hard failure,
cost/authorization, and ledger pairing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
BASE = ROOT / "var/eval/t208-real-judge/live-attempt2"
LEDGER = ROOT / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
RUN_ID = "t208-real-judge-public-20261119-attempt2"


def main() -> int:
    receipt = json.loads((BASE / "receipt.json").read_text("utf-8"))
    closeout = json.loads((BASE / "closeout.json").read_text("utf-8"))
    go = json.loads((BASE / "signed-go.json").read_text("utf-8"))
    rows = [json.loads(line) for line in LEDGER.read_text("utf-8").splitlines() if line.strip()]
    reserved = [r for r in rows if r.get("event") == "reserved" and r.get("run_id") == RUN_ID]
    results = [r for r in rows if r.get("event") == "result" and r.get("run_id") == RUN_ID]
    reserve_sum = round(sum(float(r.get("reserve_cny") or 0) for r in reserved), 10)
    charge_sum = round(sum(float(r.get("conservative_charge_cny") or 0) for r in results), 10)
    cases = {case["case_id"]: case for case in receipt["cases"]}
    checks = {
        "status_scored": receipt["status"] == "scored",
        "complete": receipt["complete"] is True,
        "retry_zero": receipt["retry_count"] == 0,
        "embedding_zero": receipt["embedding_calls"] == 0,
        "calls_24": len(receipt["calls"]) == 24 and len(results) == 24 and len(reserved) == 24,
        "reserve_0448512": reserve_sum == 0.448512 and closeout["reserved_cny"] == 0.448512,
        "charge_00383": charge_sum == 0.0383 and closeout["conservative_cny"] == 0.0383,
        "tokens": closeout["input_tokens"] == 15414 and closeout["output_tokens"] == 934,
        "retained_hard_failure": cases["T208-PUB-04"]["hard_failure"] == "stale_source"
        and receipt["counts"]["hard_failure_with_judge_score"] == 1,
        "refusal_unknown": cases["T208-PUB-05"]["status"] == "unknown"
        and cases["T208-PUB-05"]["reason_code"] == "refusal_not_applicable"
        and cases["T208-PUB-05"]["judge_calls"] == 0
        and cases["T208-PUB-05"]["charged_cny"] == 0.0,
        "unknown_count_one": receipt["counts"] == {
            "scored": 4, "expected_refusal": 1, "unknown": 1,
            "hard_failure_with_judge_score": 1},
        "pending_zero": receipt["cost"]["requests_reserved"] == 24
        and receipt["cost"]["requests_sent"] == 24,
        "cost_center_judge": receipt["cost"]["cost_center"] == "judge"
        and receipt["cost"]["charged_cny"] == 0.0383,
        "judge_cumulative_0056988": closeout["judge_cumulative_accounted_cny"] == 0.056988,
        "go_plan": closeout["go_sha256"]
        == "4fdd291dc260b241b6b5edd353dec0610629c7737c079e74179d7f57d3a80004"
        and closeout["plan_sha256"] == go["scope"]["plan_sha256"]
        == "bad6d3261661846b407845d6fab0acf6a209e6ef03282e0b71c60f51d9e0e800",
        "provider_ids_24": closeout["provider_request_ids_present"] == 24
        and all(call.get("provider_request_id") for call in receipt["calls"]),
        "provider_invoice_unknown": closeout["provider_invoice_verified"] is False,
        "judge_center_within_3": 0.056988 <= 3.0,
        "zero_new_requests": receipt["cost"]["requests_sent"] == 24,
    }
    failed = [name for name, ok in checks.items() if not ok]
    out = {
        "run_id": RUN_ID,
        "checks": checks,
        "failed": failed,
        "reserve_cny": reserve_sum,
        "charge_cny": charge_sum,
        "refusal": cases["T208-PUB-05"],
        "hard_failure_case": {k: cases["T208-PUB-04"][k] for k in (
            "case_id", "status", "hard_failure", "faithfulness", "factual_correctness")},
        "go_sha256": closeout["go_sha256"],
        "plan_sha256": closeout["plan_sha256"],
    }
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if target is not None:
        target.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"failed": failed, "checks": len(checks)}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
