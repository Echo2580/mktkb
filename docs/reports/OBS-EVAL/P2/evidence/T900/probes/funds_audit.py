"""T900 phase-1 independent funds/permission audit (read-only).

Recomputes shared-ledger facts from the fixed files without writing them.
No network, no product code, no ledger mutation.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation.p2_authorization import read_ledger_snapshot  # noqa: E402
from mktkb.evaluation.p2_contracts import payload_sha256  # noqa: E402
from mktkb.live_authorization import historical_prefix_sha256, ledger_binding_ok  # noqa: E402

LEDGER = ROOT / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = ROOT / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
GO = ROOT / "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json"
RUN = ROOT / "var/eval/runs/p2-t209-b0-20261120-02/p2-run"
SEALED_GO = (
    ROOT
    / "var/eval/t209-prep/b0-live-20261120-attempt3/go"
    / "P2-LIVE-GO.t209-b0-p2-t209-b0-20261120-02.attempt3.sealed.json"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    snap = read_ledger_snapshot(ledger_path=LEDGER, budget_path=BUDGET)
    rows = [json.loads(line) for line in LEDGER.read_text("utf-8").splitlines() if line.strip()]
    reserved = [r for r in rows if r.get("event") == "reserved"]
    results = [r for r in rows if r.get("event") == "result"]
    reservations = {r["reservation_id"] for r in reserved}
    result_ids = {r["reservation_id"] for r in results}
    counts = Counter(r.get("event") for r in rows)

    b0_reserved = [r for r in reserved if r.get("run_id") == "p2-t209-b0-20261120-02"]
    b0_results = [r for r in results if r.get("run_id") == "p2-t209-b0-20261120-02"]
    b0_reserve_sum = round(sum(float(r["reserve_cny"]) for r in b0_reserved), 10)
    b0_charge_sum = round(sum(float(r.get("conservative_charge_cny") or 0) for r in b0_results), 10)
    b0_centers = Counter()
    for r in b0_reserved:
        b0_centers[r.get("cost_center") or "<none>"] += 1

    # duplicate request identity inside one run (same sha256 twice = paid retry/duplicate)
    dup = Counter()
    for r in reserved:
        if r.get("run_id") and r.get("request_sha256"):
            dup[(r["run_id"], r["request_sha256"])] += 1
    dup_groups = {f"{k[0]}:{k[1][:12]}": v for k, v in dup.items() if v > 1}
    item_dup = Counter()
    for r in reserved:
        meta = r.get("metadata") or {}
        if r.get("run_id") and meta.get("item_id"):
            item_dup[(r["run_id"], meta["item_id"])] += 1
    item_dup_groups = {f"{k[0]}:{k[1]}": v for k, v in item_dup.items() if v > 1}

    run_agg = defaultdict(lambda: {"reserved": 0, "results": 0, "reserve_cny": 0.0, "charge_cny": 0.0})
    for r in reserved:
        a = run_agg[r.get("run_id") or "<none>"]
        a["reserved"] += 1
        a["reserve_cny"] += float(r.get("reserve_cny") or 0)
    for r in results:
        a = run_agg[r.get("run_id") or "<none>"]
        a["results"] += 1
        a["charge_cny"] += float(r.get("conservative_charge_cny") or 0)
    for a in run_agg.values():
        a["reserve_cny"] = round(a["reserve_cny"], 10)
        a["charge_cny"] = round(a["charge_cny"], 10)

    times = [r.get("time_utc") for r in rows if r.get("time_utc")]
    latest = max(times)
    finish = datetime.fromisoformat("2026-11-20T11:31:46.629519+00:00")
    after_b0 = [t for t in times if datetime.fromisoformat(t) > finish]
    provider_billed = sum(1 for r in results if r.get("provider_billed_cny") is not None)

    budget = json.loads(BUDGET.read_text("utf-8"))
    current_go = json.loads(GO.read_text("utf-8"))
    sealed_go = json.loads(SEALED_GO.read_text("utf-8"))
    gate = json.loads((RUN / "gate.json").read_text("utf-8"))
    summary = json.loads((RUN / "summary.json").read_text("utf-8"))
    auth = gate["authorization"]

    b0_chat = [r for r in b0_results if r.get("kind") == "chat"]
    b0_chat_prompt = sum(int((r.get("usage") or {}).get("prompt_tokens") or 0) for r in b0_chat)
    b0_chat_completion = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in b0_chat)

    report = {
        "checked_at_utc": datetime.now().astimezone().isoformat(),
        "files": {
            "ledger": {"path": str(LEDGER.relative_to(ROOT)), "sha256": sha(LEDGER)},
            "budget": {"path": str(BUDGET.relative_to(ROOT)), "sha256": sha(BUDGET)},
            "current_go": {"path": str(GO.relative_to(ROOT)), "sha256": sha(GO)},
            "sealed_b0_go": {"path": str(SEALED_GO.relative_to(ROOT)), "sha256": sha(SEALED_GO)},
        },
        "ledger_snapshot": snap.as_dict(),
        "ledger_events": dict(counts),
        "reservation_result_pairing": {
            "reserved": len(reserved),
            "results": len(results),
            "pending": len(reservations - result_ids),
            "orphan_results": len(result_ids - reservations),
            "duplicate_reservation_ids": len(reserved) - len(reservations),
        },
        "b0_run": {
            "run_id": "p2-t209-b0-20261120-02",
            "reserved_rows": len(b0_reserved),
            "result_rows": len(b0_results),
            "reserve_sum_cny": b0_reserve_sum,
            "conservative_charge_sum_cny": b0_charge_sum,
            "by_center": dict(b0_centers),
            "chat_prompt_tokens": b0_chat_prompt,
            "chat_completion_tokens": b0_chat_completion,
            "summary_expected": {
                "gate_reserved": summary["attempts"]["gate_reserved"],
                "center_total_with_answers_cny": summary["attempts"]["center_total_with_answers_cny"],
                "provider_billed_cny": summary["requests"]["provider_billed_cny"],
                "outbound_attempts": summary["network"]["outbound_attempts"],
            },
        },
        "duplicate_paid_request_groups": dup_groups,
        "duplicate_plan_item_groups": item_dup_groups,
        "runs": {str(k): v for k, v in run_agg.items()},
        "latest_ledger_time_utc": latest,
        "rows_after_b0_finish": len(after_b0),
        "vendor_billed_nonnull_rows": provider_billed,
        "budget": {
            "limit_cny": budget["limit_cny"],
            "stages": budget["stages"],
            "stage_sum": round(sum(budget["stages"].values()) + budget["historical_conservative_accounted_cny"], 10),
            "stage_revision_no": budget["stage_revision"]["revision"],
        },
        "go_bindings": {
            "current_go_payload_sha256": payload_sha256(current_go),
            "sealed_b0_go_payload_sha256": payload_sha256(sealed_go),
            "gate_authorization_go_sha256": auth["go_sha256"],
            "gate_authorization_ledger_sha256": auth["ledger_sha256"],
            "gate_authorization_budget_sha256": auth["budget_sha256"],
            "current_budget_payload_sha256": payload_sha256(budget),
            "current_ledger_historical_prefix_sha256": historical_prefix_sha256(LEDGER),
            "ledger_binding_ok": ledger_binding_ok(auth["ledger_sha256"], LEDGER),
            "current_go_scope_plan_id": current_go["scope"]["plan_id"],
            "current_go_expires_utc": current_go["expires_utc"],
            "sealed_go_scope_plan_id": sealed_go["scope"]["plan_id"],
            "sealed_go_expires_utc": sealed_go["expires_utc"],
            "gate_requests_used": auth["requests_used"],
            "gate_max_requests": auth["max_requests"],
            "gate_stage_limit_cny": auth["stage_limit_cny"],
            "gate_center_limits_cny": auth["cost_center_limits_cny"],
        },
        "rules_checks": {
            "b0_112_reservations": len(b0_reserved) == 112,
            "b0_112_results": len(b0_results) == 112,
            "b0_charge_matches_summary": abs(b0_charge_sum - summary["requests"]["provider_billed_cny"]) < 1e-9,
            "b0_chat_tokens_match_report": b0_chat_prompt == 22047 and b0_chat_completion == 2319,
            "b0_reserve_under_go_ceiling": b0_reserve_sum <= 6.586448 + 1e-9,
            "all_ledger_rows_settled": not (reservations - result_ids),
            "zero_rows_after_b0_finish": not after_b0,
            "budget_40_stage_24": budget["limit_cny"] == 40 and budget["stages"]["P2-LIVE"] == 24.0,
            "budget_stage_arithmetic_40": abs(
                sum(budget["stages"].values()) + budget["historical_conservative_accounted_cny"] - 40
            ) < 1e-9,
            "go_hash_matches_sealed_b0": payload_sha256(sealed_go) == auth["go_sha256"],
            "budget_hash_matches_current": payload_sha256(budget) == auth["budget_sha256"],
            "ledger_prefix_matches_current": historical_prefix_sha256(LEDGER) == auth["ledger_sha256"],
            "current_go_equals_b0_go": payload_sha256(current_go) == auth["go_sha256"],
            "cumulative_reservations_exceed_owner_2000_cap": snap.reservation_count > 2000,
            "gate_snapshot_requests_used_2567": auth["requests_used"] == 2567,
        },
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out is not None:
        out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
