"""探针：fact.entity_key 的尾段相对 backing unit 到底是什么。

只输出布尔/计数：尾段是否是 unit 的标签值 / 是否出现在 unit 文本 / 是否等于某个 raw_field 值；
以及 rescore 匹配器 AttributeError 的缺失属性名（属性名是代码标识，不是业务值）。
"""
from __future__ import annotations

import collections
import pathlib
import sys
from typing import Any, Mapping

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402
import r2_boundary_ext as ext  # noqa: E402

KEY = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings"
    r"\run2-pre_v05_without_v07.binding.json"
)
EVIDENCE_ROOT = pathlib.Path(
    r"D:\mktkb-p2-h2v3-fullverify-20261116\r2\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07"
)
CASE_PLAN = (
    base.REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"
)


def main() -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()
    key = KEY.read_bytes().strip()
    binding = base._read_json(BINDING)
    case_plan = base._read_json(CASE_PLAN)
    run_entry = binding["runs"][0]
    entry = base._load_module(
        "p2_h2_v3_controlled_execute_probetail",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    import mktkb.evaluation.p2_scoring as scoring
    import mktkb.evaluation.p2_runner as runner

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    document_codes = runner.holdout_document_codes(bundle.contract._ingest)
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    plan = entry.v2._validate_case_plan_document(
        dict(case_plan), cases=cases, static_bindings=static_bindings
    )
    rows, envelopes_by_case = base._build_rows(
        cases,
        plan["cases"],
        EVIDENCE_ROOT,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,
        collections.defaultdict(int),
    )
    # 先定位 rescore 缺失属性
    from mktkb.evaluation import p2_evidence_rescore as rescore

    for name in ("UnitView", "VersionBinding", "match_ref_to_unit", "LOCATOR_KEYS"):
        print("rescore has", name, hasattr(rescore, name))

    for case in cases:
        case_id = str(case.case_id)
        if case_id not in ("H2V3-C25", "H2V3-C29"):
            continue
        for envelope in envelopes_by_case.get(case_id) or ():
            units = {}
            for row in (envelope.get("db_projection") or {}).get("units") or ():
                if isinstance(row, Mapping):
                    units[str(row.get("unit_id"))] = row
            facts = [
                item
                for payload in ext._payloads(ext._events(envelope), "direct_rag_answer")
                for item in (payload.get("facts") or ())
                if isinstance(item, Mapping)
            ]
            for fact in facts:
                tail = ext._tail_value(fact.get("entity_key"))
                unit = units.get(str(fact.get("source_unit_id")))
                if not isinstance(unit, Mapping):
                    continue
                unit_tail = ext._tail_value(unit.get("entity_key"))
                label = unit.get("entity_label")
                raw_values = [
                    str(v)
                    for block in (unit.get("raw_fields"), unit.get("date_fields"))
                    if isinstance(block, Mapping)
                    for v in block.values()
                    if isinstance(v, (str, int, float))
                ]
                text = unit.get("text") if isinstance(unit.get("text"), str) else ""
                print(
                    f"{case_id} fact_tail_len={len(tail)} unit_tail_len={len(unit_tail)}"
                    f" tail_eq_unit_tail={tail == unit_tail}"
                    f" tail_eq_unit_entity_label={isinstance(label, str) and tail == label}"
                    f" tail_in_raw_values={tail in raw_values}"
                    f" tail_in_unit_text={tail in text}"
                    f" tail_equals_any_raw_field_key={tail in [str(k) for k in dict(unit.get('raw_fields') or {})]}"
                    f" fact_key_len={len(str(fact.get('entity_key')))}"
                    f" unit_key_len={len(str(unit.get('entity_key')))}"
                    f" fact_has_id_tag={':' in str(fact.get('entity_key')).partition('|')[2]}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
