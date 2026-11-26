"""Independent reviewer probe for P2 FU-3 (N/C/U provenance checks run by DEFAULT at the
real release-gate entry).

Offline / read-only against the frozen evidence: builds the real gate inputs through
`wire_real_ncu.build_inputs` (same production wiring), then feeds the gate a TEMP COPY of the
real manifest with exactly one legal mutation each time. Nothing in the repo is written.

Usage:
    python fu3_probe.py --root <CHECKOUT> --out <json>
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def _load_wire(root: Path):
    script = root / "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py"
    spec = importlib.util.spec_from_file_location("review_wire_real_ncu", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _row_projection(result) -> dict[str, Any]:
    rows = {row.row_id: row for row in result.rows}
    prov = rows.get("evidence_provenance")
    out = {
        "decision": result.decision,
        "counts": {
            "pass": sum(1 for row in result.rows if row.decision == "pass"),
            "blocked": sum(1 for row in result.rows if row.decision == "blocked"),
            "pending": sum(1 for row in result.rows if row.decision == "pending"),
            "observed": sum(1 for row in result.rows if row.decision == "observed"),
        },
        "reason_codes": sorted({code for row in result.rows for code in row.reasons}),
        "row_ids": {row_id: row.decision for row_id, row in rows.items()},
        "provenance_row": None,
    }
    if prov is not None:
        detail = dict(prov.detail or {})
        nested = detail.get("evidence")
        evidence = nested if isinstance(nested, dict) else detail
        out["provenance_row"] = {
            "decision": prov.decision,
            "reasons": list(prov.reasons),
            "cause": detail.get("cause"),
            "cases_checked": (evidence or {}).get("cases_checked"),
            "files_checked": (evidence or {}).get("files_checked"),
            "files_verified": (evidence or {}).get("files_verified"),
            "traces_checked": (evidence or {}).get("traces_checked"),
            "u_real_cases": (evidence or {}).get("u_real_cases"),
            "u_local_cases": (evidence or {}).get("u_local_cases"),
            "problem_count": (evidence or {}).get("problem_count"),
            "source_unavailable": (evidence or {}).get("source_unavailable"),
            "problems": (evidence or {}).get("problems"),
        }
    blocked_rows = [row.row_id for row in result.rows if row.decision == "blocked"]
    out["blocked_rows"] = blocked_rows
    out["provenance_codes"] = sorted(
        {
            str(problem.get("code"))
            for problem in ((out["provenance_row"] or {}).get("problems") or [])
        }
    )
    return out


def main() -> int:
    args = _args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root / "backend" / "src"))
    module = _load_wire(root)
    from mktkb.evaluation.p2_release_gate import evaluate_release_gate

    work = Path(tempfile.mkdtemp(prefix="fu3-probe-"))
    inputs_path, payload = module.build_inputs(work)
    real_manifest_path = root / payload["evidence_manifest"]["manifest"]["path"]
    real_manifest = json.loads(real_manifest_path.read_text(encoding="utf-8"))
    base_selection = json.loads(Path(payload["public"]["selection"]["path"]).read_text("utf-8"))

    report: dict[str, Any] = {
        "probe": "reviewer-fu3",
        "checkout_root": str(root),
        "work_dir": str(work),
        "real_manifest": str(real_manifest_path),
        "cases": {},
    }

    def evaluate(name: str, manifest: dict[str, Any] | None) -> dict[str, Any]:
        case_work = work / name
        case_work.mkdir(parents=True, exist_ok=True)
        case_payload = copy.deepcopy(payload)
        case_selection = copy.deepcopy(base_selection)
        if manifest is None:
            # untouched inputs, built by the production script
            return _row_projection(evaluate_release_gate(inputs_path))
        manifest_copy = case_work / "manifest.copy.json"
        manifest_copy.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        digest = module.file_sha256(manifest_copy)
        case_payload["evidence_manifest"]["manifest"] = {
            "path": str(manifest_copy),
            "sha256": digest,
        }
        case_selection["authority"]["document"] = str(manifest_copy)
        case_selection["authority"]["sha256"] = digest
        selection_copy = case_work / "selection.copy.json"
        selection_copy.write_text(
            json.dumps(case_selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        case_payload["public"]["selection"] = {
            "path": str(selection_copy),
            "sha256": module.file_sha256(selection_copy),
        }
        case_inputs = case_work / "inputs.copy.json"
        case_inputs.write_text(
            json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return _row_projection(evaluate_release_gate(case_inputs))

    # 1. positive: the real manifest, untouched, through the real entry.
    positive = evaluate("positive", None)
    report["cases"]["positive"] = positive

    # 2. legal-hex but content-mismatched question digest (N01).
    mutated = copy.deepcopy(real_manifest)
    for case in mutated["cases"]:
        if case["case_id"] == "N01":
            case["question_sha256"] = "e" * 64
    report["cases"]["question_digest_mismatch"] = evaluate("question_digest", mutated)

    # 3. declared evidence path that does not exist (inside the approved root).
    mutated = copy.deepcopy(real_manifest)
    victim = next(c for c in mutated["cases"] if c.get("basis") == "R")
    victim["evidence_paths"] = dict(victim["evidence_paths"])
    victim["evidence_paths"]["run_cases"] = (
        "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/__review_missing__.jsonl"
    )
    report["cases"]["missing_evidence_path"] = {
        **evaluate("missing_path", mutated),
        "victim": victim["case_id"],
    }

    # 4. out-of-root absolute evidence path.
    mutated = copy.deepcopy(real_manifest)
    victim = next(c for c in mutated["cases"] if c.get("basis") == "R")
    victim["evidence_paths"] = dict(victim["evidence_paths"])
    victim["evidence_paths"]["run_cases"] = "C:\\Windows\\win.ini"
    report["cases"]["out_of_root_absolute_path"] = {
        **evaluate("out_of_root", mutated),
        "victim": victim["case_id"],
    }

    # 5. trace swap between two cases of the SAME run (same question hash not required).
    mutated = copy.deepcopy(real_manifest)
    by_run: dict[str, list[dict[str, Any]]] = {}
    for case in mutated["cases"]:
        if case.get("basis") == "R" and case.get("trace_id"):
            by_run.setdefault(str(case.get("run_id")), []).append(case)
    pair = None
    for run_id, cases in by_run.items():
        if len(cases) >= 2:
            pair = (run_id, cases[0], cases[1])
            break
    assert pair is not None, "no two R cases with traces in the same run"
    run_id, first, second = pair
    first["trace_id"], second["trace_id"] = second["trace_id"], first["trace_id"]
    report["cases"]["same_run_trace_swap"] = {
        **evaluate("trace_swap", mutated),
        "run_id": run_id,
        "swapped": [first["case_id"], second["case_id"]],
    }

    # 6. U R/L type mixing, both directions.
    mutated = copy.deepcopy(real_manifest)
    u_r = next(c for c in mutated["cases"] if c.get("group") == "U" and c.get("basis") == "R")
    u_r["test_file"] = "backend/tests/evaluation/test_p2_release_gate_positive.py"
    report["cases"]["u_real_case_with_local_field"] = {
        **evaluate("u_r_mixed", mutated),
        "victim": u_r["case_id"],
    }

    mutated = copy.deepcopy(real_manifest)
    u_l = next(
        c
        for c in mutated["cases"]
        if c.get("group") == "U" and c.get("basis") == "L" and c.get("test_file")
    )
    u_l["run_id"] = "p2-t207-r2-20261111-01"
    report["cases"]["u_local_case_with_run_field"] = {
        **evaluate("u_l_mixed", mutated),
        "victim": u_l["case_id"],
    }

    # baseline facts that must be preserved (tiers / tallies / mechanical failures / D-011)
    mechanical = [
        (c["case_id"], tuple((g["gate"], g["check"]) for g in c.get("mechanical_gate_failures") or ()))
        for c in real_manifest["cases"]
        if c.get("mechanical_gate_failures")
    ]
    report["manifest_facts"] = {
        "case_count": len(real_manifest["cases"]),
        "groups": {
            g: sum(1 for c in real_manifest["cases"] if c.get("group") == g)
            for g in ("N", "C", "U")
        },
        "mechanical_failure_cases": mechanical,
        "mechanical_failure_count": len(mechanical),
        "tallies": real_manifest.get("tallies"),
        "hard_gate_min_sample": real_manifest.get("hard_gate_min_sample"),
        "hard_gate_applicability": real_manifest.get("hard_gate_applicability"),
    }
    positive_rows = positive["row_ids"]
    report["positive_snapshot"] = {
        "rows_total": len(positive_rows),
        "decision_counts": positive["counts"],
        "mechanical_line_row": {
            row_id: decision
            for row_id, decision in positive_rows.items()
            if "mechanical" in row_id or "min_sample" in row_id or "d-011" in row_id.lower()
        },
        "evidence_manifest_row": positive_rows.get("evidence_manifest"),
        "hard_gate_min_sample_row": positive_rows.get("hard_gate_min_sample"),
    }
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "positive_decision": positive["decision"],
                "positive_counts": positive["counts"],
                "provenance": (positive["provenance_row"] or {}).get("decision"),
                "mutations": {
                    name: {
                        "decision": case["decision"],
                        "reason_codes": case["reason_codes"],
                        "provenance_decision": (case["provenance_row"] or {}).get("decision"),
                        "provenance_codes": case["provenance_codes"],
                    }
                    for name, case in report["cases"].items()
                    if name != "positive"
                },
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
