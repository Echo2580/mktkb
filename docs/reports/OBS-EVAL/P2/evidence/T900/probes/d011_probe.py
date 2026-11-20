"""T900 D-011 independent probe (read-only source; writes only to isolated tmp).

1) Reads the real min-sample coverage semantics from p2_standards.
2) Builds a complete synthetic input set with one run-level citation failure and
   verifies u.hard_gates + hard_gates are both blocked (D-011 must not mask it).
3) Shows a self-reported plan count is rejected by the input contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "backend/tests"))

from mktkb.evaluation.p2_b0 import load_approved_b0_config  # noqa: E402
from mktkb.evaluation.p2_release_gate import evaluate_release_gate  # noqa: E402
from mktkb.evaluation.p2_release_public import min_sample_coverage  # noqa: E402
from evaluation.test_p2_release_gate_fixtures import (  # noqa: E402
    build_complete_inputs,
    write_inputs,
)

APPROVED = ROOT / "docs/evaluation/gate_v0_3_approved.json"
TMP = ROOT / ".tmp-t900-isolated/phase2/d011"


def rows_of(result):
    return {row.row_id: row for row in result.rows}


def main() -> int:
    config = load_approved_b0_config(APPROVED)
    real = min_sample_coverage(
        standards=config.standards, gate_config=config,
        suite="update_delete", run_level_evaluated=1,
    )
    inflated = min_sample_coverage(
        standards=config.standards, gate_config=config,
        suite="update_delete", run_level_evaluated=99,
    )
    import dataclasses
    forged_standards = dataclasses.replace(config.standards, update_delete_total=9)
    forged = min_sample_coverage(
        standards=forged_standards, gate_config=config,
        suite="update_delete", run_level_evaluated=10,
    )

    control_dir = TMP / "control"
    control_path, _ = build_complete_inputs(
        control_dir, run_level_cases=("U01",), local_controls=True,
    )
    control = evaluate_release_gate(control_path)
    control_rows = rows_of(control)

    fail_dir = TMP / "failing-run-level"
    fail_path, _ = build_complete_inputs(
        fail_dir, run_level_cases=("U01",), local_controls=True,
        u_kwargs={"failing_citations": True},
    )
    failed = evaluate_release_gate(fail_path)
    failed_rows = rows_of(failed)

    forged_dir = TMP / "forged-planned"
    forged_path, forged_payload = build_complete_inputs(
        forged_dir, run_level_cases=("U01",), local_controls=True,
    )
    forged_payload["hard_gate_min_sample"] = {"suite_planned_cases": 10}
    rewritten = write_inputs(forged_dir / "inputs-forged.json", forged_payload)
    forged_result = evaluate_release_gate(rewritten)
    forged_codes = {code for row in forged_result.rows for code in row.reasons}

    report = {
        "real_coverage": real,
        "inflated_run_level_99": inflated,
        "forged_plan_total_9": forged,
        "control": {
            "decision": control.decision,
            "u.hard_gates": control_rows["u.hard_gates"].decision,
            "hard_gates": control_rows["hard_gates"].decision,
        },
        "injected_run_level_failure": {
            "decision": failed.decision,
            "u.hard_gates": failed_rows["u.hard_gates"].decision,
            "u.hard_gates_reasons": list(failed_rows["u.hard_gates"].reasons),
            "hard_gates": failed_rows["hard_gates"].decision,
            "hard_gates_reasons": list(failed_rows["hard_gates"].reasons),
            "u_gate_status": failed_rows["u.hard_gates"].detail.get("gate_status"),
            "u_unknowns": failed_rows["u.hard_gates"].detail.get("unknowns"),
        },
        "forged_self_report": {
            "decision": forged_result.decision,
            "reason_codes": sorted(forged_codes),
            "release_inputs_invalid": "release_inputs_invalid" in forged_codes,
        },
    }
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if out is not None:
        out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    ok = (
        real["suite_planned_cases"] == 10
        and real["required_min_sample"] == 10
        and real["run_level_evaluated"] == 1
        and real["covered"] is True
        and inflated["covered"] is True
        and forged["covered"] is False
        and control.decision == "pass"
        and failed.decision != "pass"
        and failed_rows["u.hard_gates"].decision == "blocked"
        and failed_rows["hard_gates"].decision == "blocked"
        and forged_result.decision == "blocked"
        and "release_inputs_invalid" in forged_codes
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
