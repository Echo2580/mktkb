"""Reviewer probe: which row actually blocks the synthetic release-gate fixtures?

Imports the SHIPPED fixture builder (`backend/tests/evaluation/test_p2_release_gate_fixtures.py`,
not a reviewer copy) and prints every non-pass row with its reasons/detail, so that
"blocked by the candidate.pipeline version gate" can be distinguished from any other cause
(for example the new FU-3 provenance row).

Usage: python gate_fixture_rows.py --root <CHECKOUT> --out <json>
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root / "backend" / "src"))
    sys.path.insert(0, str(root / "backend" / "tests"))

    from evaluation.test_p2_release_gate_fixtures import build_complete_inputs

    from mktkb.evaluation.p2_release_gate import evaluate_release_gate

    work = Path(tempfile.mkdtemp(prefix="gate-fixture-rows-"))
    cases = {
        "complete": {},
        "citation_gap": {"u_kwargs": {"citation_gap": True}},
        "with_binding": {"public_kwargs": {"with_binding": True}},
    }
    report: dict[str, Any] = {"probe": "reviewer-gate-fixture-rows", "root": str(root), "cases": {}}
    for name, kwargs in cases.items():
        target = work / name
        target.mkdir(parents=True, exist_ok=True)
        path, _payload = build_complete_inputs(target, **kwargs)
        result = evaluate_release_gate(path)
        rows = {row.row_id: row for row in result.rows}
        non_pass = [
            {
                "row_id": row.row_id,
                "decision": row.decision,
                "reasons": list(row.reasons),
                "cause": row.detail.get("cause"),
                "detail_keys": sorted(row.detail),
            }
            for row in result.rows
            if row.decision != "pass"
        ]
        report["cases"][name] = {
            "decision": result.decision,
            "row_count": len(rows),
            "non_pass_rows": non_pass,
            "has_provenance_row": "evidence_provenance" in rows,
            "candidate_pipeline": {
                "decision": rows["candidate.pipeline"].decision,
                "reasons": list(rows["candidate.pipeline"].reasons),
                "detail": dict(rows["candidate.pipeline"].detail),
            }
            if "candidate.pipeline" in rows
            else None,
        }
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, case in report["cases"].items():
        print(
            name,
            "->",
            case["decision"],
            "| non-pass:",
            [(r["row_id"], r["decision"], r["reasons"]) for r in case["non_pass_rows"]],
            "| provenance row:",
            case["has_provenance_row"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
