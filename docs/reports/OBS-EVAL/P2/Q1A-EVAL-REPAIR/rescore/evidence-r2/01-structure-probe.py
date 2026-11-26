"""Q1a-3-R2 结构探针：公开结构 -> active 版本表 / ref 绑定覆盖 / unit doc_code 覆盖。

只输出计数、固定 reason 分类与 hash；不输出文档名、doc_code、题号、题面、答案或目标值。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (HERE, REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r2 as C  # noqa: E402
from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402


def main() -> int:
    structure = C.load_public_structure()
    bundle = C.load_bundle()
    annotation = {row["case_id"]: row["scenario_id"] for row in bundle.annotation["cases"]}
    specs = {case.case_id: case for case in bundle.dataset.cases}

    aggregate = Counter()
    for case in bundle.dataset.cases:
        scenario = annotation[case.case_id]
        refs = {
            "expected_sources": tuple(dict(ref) for ref in specs[case.case_id].expected_sources),
            "forbidden_sources": tuple(dict(ref) for ref in specs[case.case_id].forbidden_sources),
            "relevant_units": tuple(dict(ref) for ref in specs[case.case_id].relevant_units),
        }
        _bindings, _normalized_refs, coverage = C.version_bindings_for_case(structure, scenario, refs)
        aggregate["refs"] += coverage["refs"]
        aggregate["bound"] += coverage["bound"]
        aggregate["unbound"] += coverage["unbound"]
        aggregate["alias_normalized"] += coverage["alias_normalized"]
        for reason, count in coverage["unbound_by_reason"].items():
            aggregate[f"unbound|{reason}"] += count
        for collection, bucket in coverage["by_collection"].items():
            aggregate[f"{collection}|refs"] += bucket["refs"]
            aggregate[f"{collection}|bound"] += bucket["bound"]
            aggregate[f"{collection}|unbound"] += bucket["unbound"]
        for basis, count in coverage["bound_by_basis"].items():
            aggregate[f"basis|{basis}"] += count

    unit_reasons = Counter()
    unit_units = Counter()
    unresolved_shapes = Counter()
    unit_shapes = Counter()
    for run_index in range(4):
        run_dir = C.OLD_RUN / "runs" / f"r{run_index}"
        plan = C.strict_json((run_dir / "out" / "controlled" / "case-plan.json").read_bytes())
        key = (run_dir / "ev.key").read_bytes()
        evidence_dir = next(p for p in (run_dir / "evidence").iterdir() if p.is_dir())
        for plan_case in plan["cases"]:
            for turn in plan_case["turns"]:
                if turn.get("status") != "executed":
                    continue
                envelope = read_encrypted_evidence(evidence_dir / turn["evidence_file"], key=key)
                projection = envelope["db_projection"]
                for unit in projection.get("units") or ():
                    name = unit.get("document_name")
                    version = unit.get("version_number") if type(unit.get("version_number")) is int else None
                    doc_code, reason = structure.doc_code_for_unit(name, version)
                    unit_reasons[reason] += 1
                    candidates = [row for row in structure.rows if row.product_name == name]
                    name_kind = (
                        "display_D"
                        if candidates and all(row.file_code.startswith("D") for row in candidates)
                        else "variant_basename"
                        if candidates
                        else "unmatched"
                    )
                    unit_shapes[
                        f"run=r{run_index}|namekind={name_kind}|candidate_versions="
                        f"{sorted({row.version_number for row in candidates})}|unit_version={version}|reason={reason}"
                    ] += 1
                    if doc_code is not None:
                        unit_units["resolved"] += 1
                    else:
                        unresolved_shapes[
                            "|".join(
                                [
                                    f"run=r{run_index}",
                                    f"name_matches={bool(candidates)}",
                                    f"candidate_versions={sorted({row.version_number for row in candidates})}",
                                    f"unit_version={version}",
                                    f"reason={reason}",
                                ]
                            )
                        ] += 1

    payload = {
        "public_structure": structure.summary(),
        "ref_binding_coverage": {
            "refs": aggregate["refs"],
            "bound": aggregate["bound"],
            "unbound": aggregate["unbound"],
            "alias_normalized": aggregate["alias_normalized"],
            "unbound_by_reason": {
                key.split("|", 1)[1]: value
                for key, value in sorted(aggregate.items())
                if key.startswith("unbound|")
            },
            "by_collection": {
                collection: {
                    "refs": aggregate[f"{collection}|refs"],
                    "bound": aggregate[f"{collection}|bound"],
                    "unbound": aggregate[f"{collection}|unbound"],
                }
                for collection in ("expected_sources", "forbidden_sources", "relevant_units")
            },
            "bound_by_basis": {
                key.split("|", 1)[1]: value
                for key, value in sorted(aggregate.items())
                if key.startswith("basis|")
            },
        },
        "unit_doc_code_coverage": {
            "units": sum(unit_reasons.values()),
            "resolved": unit_units["resolved"],
            "unresolved_by_reason": dict(sorted(unit_reasons.items())),
            "unit_shapes": dict(sorted(unit_shapes.items())),
            "unresolved_shapes": dict(sorted(unresolved_shapes.items())),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
