"""R3 prototype: new `stale_source` determination on old evidence (aggregate-only).

Primary reading: record identity = observed runtime `unit_key` (record locator).
Strict reading: record identity absent -> source_unresolved.
No case ids, question text, answers or target values are printed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")
FOR = (REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2",
       REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1",
       REPO / "backend/src", REPO / "tools")
for path in FOR:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r2 as C  # noqa: E402
from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402
from mktkb.evaluation.p2_evidence_rescore import _used_layers  # noqa: E402
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    _extract_candidate_layers,
    _extract_use_layers,
)
from mktkb.evaluation.p2_stale_version_state import (  # noqa: E402
    CRITERION_VERSION,
    determine_stale_case,
    reason_histogram,
)


def main() -> int:
    scenario_contract = json.loads((REPO / "docs/evaluation/p2-h2-scenarios-v0_2.json").read_bytes())
    ingest = json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json").read_bytes())
    source_map = json.loads((REPO / "docs/evaluation/p2-holdout-v2.source-map.json").read_bytes())
    scenarios = {row["scenario_id"]: row for row in scenario_contract["scenarios"]}
    structure = C.load_public_structure()

    contract_v2 = json.loads(
        __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet(
            Path(r"D:\mktkb-p2-holdout\keys\v2.key").read_bytes()
        ).decrypt(Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet").read_bytes()).decode("utf-8")
    )
    contract_cases = {row["case_id"]: row for row in contract_v2["cases"]}

    cases: list[dict] = []
    for index in range(4):
        run = OLD_RUN / "runs" / f"r{index}"
        plan = json.loads((run / "out" / "controlled" / "case-plan.json").read_bytes())
        ev_key = (run / "ev.key").read_bytes()
        ev_dir = next(p for p in (run / "evidence").iterdir() if p.is_dir())
        for plan_case in plan["cases"]:
            case_id = plan_case["case_id"]
            contract_case = contract_cases[case_id]
            scenario_id = contract_case["scenario_id"]
            scenario = scenarios[scenario_id]
            stale_axis = contract_case["axes"]["stale_source"]
            annotation = {
                "applicability": stale_axis["applicability"],
                "criterion": stale_axis["criterion"],
                "reason": stale_axis["reason"],
                "as_of": stale_axis["as_of"],
                "temporal_intent": stale_axis["temporal_intent"],
            }
            grounding = {
                "mode": "version_state",
                "fixture_sha256": None,
                "scenario": {
                    "scenario_id": scenario_id,
                    "source_indices": scenario["source_indices"],
                    "ingest_batches": scenario.get("ingest_batches"),
                },
                "ingest_plan": ingest,
                "source_map": source_map,
                "windows": None,
            }
            turn_inputs = []
            code_resolved = 0
            code_unresolved = 0
            unit_total = 0
            for local_index, turn in enumerate(plan_case["turns"]):
                status = turn["status"]
                if status != "executed":
                    turn_inputs.append({
                        "turn_index": local_index,
                        "state_inputs": {
                            "usage": {
                                "observed": False,
                                "reason": "turn_error" if status == "error" else "turn_not_executed",
                            }
                        },
                    })
                    continue
                env = read_encrypted_evidence(ev_dir / turn["evidence_file"], key=ev_key)
                events = (env.get("capture") or {}).get("events") or []
                projection = env.get("db_projection") or {}
                rows = {str(u.get("unit_id")): u for u in projection.get("units") or [] if isinstance(u, dict)}
                units = []
                for uid in _used_layers(events):
                    unit = rows.get(uid)
                    if unit is None:
                        code_unresolved += 1
                        continue
                    doc_name = unit.get("document_name")
                    version = unit.get("version_number")
                    base, _base_reason = structure.doc_code_for_unit(doc_name, version)
                    candidates = [r for r in structure.rows if r.base_doc_code == base] if base else []
                    exact = [r for r in candidates if r.version_number == version]
                    if len(exact) == 1:
                        file_code = exact[0].file_code
                    elif len(candidates) == 1 and version is None:
                        file_code = candidates[0].file_code
                    else:
                        file_code = None
                    unit_total += 1
                    if file_code is None:
                        code_unresolved += 1
                        units.append({
                            "unit_id": uid,
                            "record_code": unit.get("unit_key"),
                        })
                        continue
                    code_resolved += 1
                    units.append({
                        "unit_id": uid,
                        "code": file_code,
                        "record_code": unit.get("unit_key"),
                        "document_id": unit.get("document_id"),
                        "version_id": unit.get("version_id"),
                    })
                use_layers, use_malformed = _extract_use_layers(events, projection)
                candidate_layers, candidate_malformed = _extract_candidate_layers(events, projection)
                completeness = (env.get("completeness") or {}).get("status")
                retrieval = candidate_layers["retrieval_observed"]
                usage = {
                    "observed": True,
                    "units": units,
                    "turn_status": "complete" if completeness == "complete" else "partial",
                    "use_layers": {
                        name: {
                            "observed": layer["observed"],
                            "count": layer["count"],
                            "refs": list(layer["refs"]),
                        }
                        for name, layer in use_layers.items()
                    },
                    "retrieval": {
                        "observed": retrieval["observed"],
                        "count": retrieval["count"],
                        "refs": list(retrieval["refs"]),
                        "truncated": retrieval["truncated"],
                    },
                }
                # runtime as_of
                as_of = None
                for event in events:
                    if isinstance(event, dict) and event.get("kind") == "plan_observed":
                        payload = event.get("payload") or {}
                        if isinstance(payload.get("as_of"), str):
                            as_of = payload["as_of"]
                        break
                turn_inputs.append({
                    "turn_index": local_index,
                    "state_inputs": {"usage": usage, "as_of": as_of},
                })
            evidence = {"case_id": case_id, "annotation": annotation, "turns": turn_inputs}
            determination = determine_stale_case(CRITERION_VERSION, grounding, evidence)
            cases.append({
                "run_index": index,
                "case_id": case_id,
                "state": determination.state,
                "reason": determination.reason,
                "per_turn": [t.as_dict() for t in determination.per_turn],
                "active_versions": dict(determination.provenance.get("active_versions") or {}),
                "audit": list(determination.provenance.get("audit") or []),
                "units": unit_total,
                "code_resolved": code_resolved,
                "code_unresolved": code_unresolved,
            })

    out = {
        "criterion_version": CRITERION_VERSION,
        "case_count": len(cases),
        "states": dict(Counter(case["state"] for case in cases)),
        "reasons": dict(sorted(Counter(case["reason"] for case in cases).items())),
        "by_run": {
            f"r{i}": {
                "cases": sum(1 for c in cases if c["run_index"] == i),
                "states": dict(Counter(c["state"] for c in cases if c["run_index"] == i)),
                "reasons": dict(sorted(Counter(c["reason"] for c in cases if c["run_index"] == i).items())),
            }
            for i in range(4)
        },
        "units": sum(c["units"] for c in cases),
        "code_resolved": sum(c["code_resolved"] for c in cases),
        "code_unresolved": sum(c["code_unresolved"] for c in cases),
        "active_version_table_case_count": sum(1 for c in cases if c["active_versions"]),
        "audit_counts": dict(sorted(Counter(code for c in cases for code in c["audit"]).items())),
        "ambiguous_count": sum(1 for c in cases if c["reason"] == "stale_active_version_ambiguous"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
