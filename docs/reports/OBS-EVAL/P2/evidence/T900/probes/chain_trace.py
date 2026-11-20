"""T900 phase-1 evidence-chain trace (read-only).

Closes receipt -> digest -> artifact -> acceptance-record for the B0 baseline
and three real runs (T206 pilot, T208 judge attempt2, T209 B0 attempt3).
No network, no writes except the requested JSON output.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation.p2_contracts import payload_sha256  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def ledger_rows():
    path = ROOT / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def run_money(rows, run_id):
    reserved = [r for r in rows if r.get("event") == "reserved" and r.get("run_id") == run_id]
    results = [r for r in rows if r.get("event") == "result" and r.get("run_id") == run_id]
    return {
        "reserved_rows": len(reserved),
        "result_rows": len(results),
        "reserve_cny": round(sum(float(r.get("reserve_cny") or 0) for r in reserved), 10),
        "charge_cny": round(sum(float(r.get("conservative_charge_cny") or 0) for r in results), 10),
        "prompt_tokens": sum(int((r.get("usage") or {}).get("prompt_tokens") or 0) for r in results),
        "completion_tokens": sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in results),
    }


def main() -> int:
    rows = ledger_rows()
    evidence_dir = ROOT / "var/eval/baselines/7981d4afc2d1"
    archive = ROOT / "var/eval/t209-prep/b0-baseline-7981d4afc2d1/archive"
    baseline = load(evidence_dir / "baseline.json")
    approval = load(evidence_dir / "approval.json")
    receipt = load(ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP/b0-attempt3-baseline-approval.json")
    admission = load(evidence_dir / "b0-admission.json")
    manifest = load(archive / "archive_manifest.json")
    gate = load(ROOT / "var/eval/runs/p2-t209-b0-20261120-02/p2-run/gate.json")
    summary = load(ROOT / "var/eval/runs/p2-t209-b0-20261120-02/p2-run/summary.json")
    pilot = load(ROOT / "docs/reports/OBS-EVAL/P2/T206/PILOT/summary.json")

    admission_digest = payload_sha256(admission)
    b0_links = {
        "receipt.evidence_sha256": receipt["evidence_sha256"],
        "admission.payload_sha256": admission_digest,
        "baseline.gate_result_sha256": baseline["gate"]["gate_result_sha256"],
        "approval.gate_result_sha256": approval["gate_result_sha256"],
        "archive_manifest.approval.gate_result_sha256": manifest["approval"]["gate_result_sha256"],
        "run_gate.authorization.go_sha256": gate["authorization"]["go_sha256"],
    }
    b0_closed = len({value for key, value in b0_links.items() if key != "run_gate.authorization.go_sha256"}) == 1
    ids = {
        "receipt.baseline_id": receipt["baseline_id"],
        "baseline.baseline_id": baseline["baseline_id"],
        "approval.baseline_id": approval["baseline_id"],
        "archive_manifest.baseline_id": manifest["baseline_id"],
        "receipt.run_id": receipt["run_id"],
        "baseline.run_id": baseline["run_id"],
        "approval.run_id": approval["run_id"],
        "archive_manifest.run_id": manifest["run_id"],
        "gate.run_id": gate["authorization"].get("plan_id") and summary["run_id"],
    }
    archive_files = {entry["path"]: entry for entry in manifest["files"]}
    archived_ok = all(
        sha(archive / rel) == entry["sha256"] and (archive / rel).stat().st_size == entry["bytes"]
        for rel, entry in archive_files.items()
    )

    t206 = run_money(rows, "p2-t206-pilot-20261111-01")
    t208 = run_money(rows, "t208-real-judge-public-20261119-attempt2")
    t209 = run_money(rows, "p2-t209-b0-20261120-02")

    report = {
        "b0_chain": {
            "links": b0_links,
            "one_digest_across_receipt_baseline_approval_admission": b0_closed,
            "ids": ids,
            "ids_consistent": (
                len({v for k, v in ids.items() if k.endswith("baseline_id")}) == 1
                and len({v for k, v in ids.items() if k.endswith("run_id")}) == 1
            ),
            "archive_files": len(archive_files),
            "archive_files_match_manifest": archived_ok,
            "archive_manifest_sha256": sha(archive / "archive_manifest.json"),
            "expected_archive_manifest_sha256": "be511c7e2814374cc2a7e6897196ef6e216e41c1c44574839f700c0ccdc2f9b3",
            "b0_admission_b0": admission["b0"],
            "b0_summary_requests": summary["requests"],
        },
        "t206_pilot": {
            **t206,
            "pilot_summary_billed_cny": pilot["requests"].get("billed_cny"),
            "pilot_summary_center_total_with_answers_cny": pilot["attempts"].get("center_total_with_answers_cny"),
            "pilot_summary_outbound": pilot["network"]["outbound_attempts"],
            "pm_receipt_claims": {"reserved_cny": 0.6893120, "settled_cny": 0.5713583, "outbound": 39},
            "receipt_matches_ledger": abs(t206["charge_cny"] - 0.5713583) < 1e-9
            and t206["reserved_rows"] == 42
            and t206["result_rows"] == 42,
        },
        "t208_judge": {
            **t208,
            "receipt_claims": {"reserved_cny": 0.448512, "settled_cny": 0.038300, "calls": 24,
                               "prompt_tokens": 15414, "completion_tokens": 934},
            "receipt_matches_ledger": abs(t208["charge_cny"] - 0.0383) < 1e-9
            and t208["reserved_rows"] == 24
            and t208["result_rows"] == 24
            and t208["prompt_tokens"] == 15414
            and t208["completion_tokens"] == 934,
        },
        "t209_attempt3": {
            **t209,
            "report_claims": {"outbound": 112, "charge_cny": 5.7200466, "ocr_cny": 5.65},
            "summary_outbound": summary["network"]["outbound_attempts"],
            "summary_center_total_with_answers_cny": summary["attempts"]["center_total_with_answers_cny"],
            "matches_report": t209["reserved_rows"] == 112
            and t209["result_rows"] == 112
            and abs(t209["charge_cny"] - 5.7200466) < 1e-9
            and summary["network"]["outbound_attempts"] == 112,
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
