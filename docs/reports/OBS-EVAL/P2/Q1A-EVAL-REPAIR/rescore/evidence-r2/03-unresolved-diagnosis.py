"""Q1a-3-R2 未解析诊断：逐个 ref 的绑定/匹配结果分类（只输出计数与固定码）。

用途：解释 R2 中仍为 `source_unresolved` / `targets_unresolved` 的结构原因。
不输出题号、题面、答案、目标值、文档名或 doc_code 字面值。
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
from mktkb.evaluation.p2_evidence_rescore import match_ref_to_unit, ref_key  # noqa: E402


def main() -> int:
    structure = C.load_public_structure()
    bundle = C.load_bundle()
    annotation = {row["case_id"]: row["scenario_id"] for row in bundle.annotation["cases"]}
    specs = {case.case_id: case for case in bundle.dataset.cases}

    # 先把每个 case 的 used units 投影出来（与正式脚本同一投影）。
    units_by_case: dict[str, list[object]] = {}
    for run_index in range(4):
        run_dir = C.OLD_RUN / "runs" / f"r{run_index}"
        plan = C.strict_json((run_dir / "out" / "controlled" / "case-plan.json").read_bytes())
        key = (run_dir / "ev.key").read_bytes()
        evidence_dir = next(p for p in (run_dir / "evidence").iterdir() if p.is_dir())
        for plan_case in plan["cases"]:
            case_id = plan_case["case_id"]
            collected: list[object] = []
            for local_index, turn in enumerate(plan_case["turns"]):
                if turn.get("status") != "executed":
                    continue
                envelope = read_encrypted_evidence(evidence_dir / turn["evidence_file"], key=key)
                projection = C.project_turn_v2(
                    envelope,
                    turn_index=local_index,
                    status="executed",
                    structure=structure,
                    evidence_turn_index=turn["turn_index"],
                )
                collected.extend(projection.units)
            units_by_case[case_id] = collected

    outcomes = Counter()
    shapes = Counter()
    for case in bundle.dataset.cases:
        scenario = annotation[case.case_id]
        spec = specs[case.case_id]
        refs = {
            "expected_sources": tuple(dict(ref) for ref in spec.expected_sources),
            "forbidden_sources": tuple(dict(ref) for ref in spec.forbidden_sources),
            "relevant_units": tuple(dict(ref) for ref in spec.relevant_units),
        }
        bindings, normalized_refs, coverage = C.version_bindings_for_case(structure, scenario, refs)
        for collection, rows in normalized_refs.items():
            for ref in rows:
                shape_key = "|".join(
                    [
                        f"record_code={'yes' if ref.get('record_code') is not None else 'no'}",
                        f"unit_key={'yes' if ref.get('unit_key') is not None else 'no'}",
                        f"locator={'yes' if ref.get('locator') else 'no'}",
                    ]
                )
                binding = bindings.get(ref_key(ref))
                if binding is None:
                    outcomes[f"{collection}|unbound"] += 1
                    shapes[f"{collection}|unbound|{shape_key}"] += 1
                    continue
                verdicts = [match_ref_to_unit(ref, unit, version_binding=binding) for unit in units_by_case[case.case_id]]
                if any(verdict.verdict == "match" for verdict in verdicts):
                    outcomes[f"{collection}|match"] += 1
                    continue
                unresolved_codes = sorted({verdict.code for verdict in verdicts if verdict.verdict == "unresolved"})
                no_match_codes = sorted({verdict.code for verdict in verdicts if verdict.verdict == "no_match"})
                if unresolved_codes:
                    outcomes[f"{collection}|unresolved|{','.join(unresolved_codes)}"] += 1
                elif no_match_codes:
                    outcomes[f"{collection}|no_match|{','.join(no_match_codes)}"] += 1
                else:
                    outcomes[f"{collection}|no_units"] += 1

    payload = {
        "ref_outcomes": dict(sorted(outcomes.items())),
        "ref_shapes": dict(sorted(shapes.items())),
        "note": "match/unresolved/no_match 使用 Q1a-1b matcher v2；unbound 表示合同绑定按规则为 unresolved",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
