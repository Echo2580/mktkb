"""必测 6：计数自洽（三公式）、basis 不进 verdict、输出无 verified/threshold/release。"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from harness import Checks
import synth

from mktkb.evaluation.p2_evidence_axes_adapter_v2 import (
    aggregate_axis,
    determine_case,
    reason_histogram,
)

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
FORBIDDEN = ("verified", "threshold", "release")


def walk_keys(value: Any, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            keys.append(f"{prefix}.{key}" if prefix else str(key))
            keys.extend(walk_keys(child, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            keys.extend(walk_keys(child, f"{prefix}[{index}]"))
    return keys


def walk_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            found.append(str(key))
            found.extend(walk_strings(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(walk_strings(child))
    elif isinstance(value, str):
        found.append(value)
    return found


def main() -> dict:
    checks = Checks("06-counts-and-output")
    name_target = synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})
    other_target = synth.target("item", "item|storeb|itemb", {"store": "StoreB", "item": "ItemB"})

    cases = {
        0: synth.case_axes(cross_entity=synth.axis("required", "structured_target", "explicit_single_target", targets=[name_target])),
        1: synth.case_axes(cross_entity=synth.axis("required", "structured_target", "explicit_single_target", targets=[name_target])),
        2: synth.case_axes(cross_entity=synth.axis("required", "structured_target", "explicit_single_target")),
        3: synth.case_axes(cross_entity=synth.axis("not_applicable", "no_entity_claim", "no_entity_scope")),
    }
    other_row = synth.record(entity_key="item|storeb|itemb", entity_filters={"store": "StoreB", "item": "ItemB"})
    payload = synth.contract(cases)
    snapshots = {
        index: synth.snapshot([row], scenario_id=synth.SCENARIOS[index % len(synth.SCENARIOS)])
        for index, row in {
            0: synth.record(),
            1: other_row,
            2: synth.record(),
            3: synth.text_record(),
        }.items()
    }
    determinations = [
        determine_case(contract=payload, case_id=f"C0{index}", snapshot=snapshots[index])
        for index in range(4)
    ]
    states = {index: determinations[index].axes["cross_entity"].state for index in range(4)}
    checks.eq("case0_state", states[0], "passed")
    checks.eq("case1_state", states[1], "violation")
    checks.eq("case2_state", states[2], "unknown")
    checks.eq("case3_state", states[3], "not_applicable")

    counts = aggregate_axis(determinations, "cross_entity")
    counts_dict = counts.as_dict()
    checks.eq("counts_planned", counts.planned, 4)
    checks.eq("counts_checked", counts.checked, 3)
    checks.eq("counts_passed", counts.passed, 1)
    checks.eq("counts_not_applicable", counts.not_applicable, 1)
    checks.eq("counts_unknown", counts.unknown, 1)
    checks.eq("counts_violations", counts.violations, 1)
    checks.record(
        "formula_planned_eq_parts",
        counts.planned == counts.passed + counts.not_applicable + counts.unknown + counts.violations,
    )
    checks.record(
        "formula_checked_eq_checked_parts",
        counts.checked == counts.passed + counts.not_applicable + counts.violations,
    )
    checks.record("formula_planned_eq_checked_plus_unknown", counts.planned == counts.checked + counts.unknown)
    checks.eq("counts_as_dict_formulas_all_true", all(counts_dict["formulas"].values()), True)

    stale_counts = aggregate_axis(determinations, "stale_source")
    checks.eq("stale_planned", stale_counts.planned, 4)
    checks.eq("stale_checked", stale_counts.checked, 0)
    checks.eq("stale_unknown", stale_counts.unknown, 4)

    histogram = reason_histogram(determinations, "cross_entity")
    checks.eq("histogram_total", sum(histogram.values()), 4)

    # ---- basis 不进 verdict ------------------------------------------------ #
    baseline = determinations[0]
    basis_variants = {}
    for basis in ("frozen_label_target", "public_corpus_structure", "frozen_question_scope", "case_business_date_baseline"):
        variant = synth.contract({
            0: synth.case_axes(cross_entity=synth.axis("required", "structured_target", "explicit_single_target", targets=[name_target], basis=basis))
        })
        determination = determine_case(contract=variant, case_id="C00", snapshot=snapshots[0])
        basis_variants[basis] = {
            "state": determination.axes["cross_entity"].state,
            "reason": determination.axes["cross_entity"].reason,
            "provenance_basis": determination.axes["cross_entity"].provenance.get("basis"),
        }
    checks.record(
        "basis_does_not_change_state_or_reason",
        len({(row["state"], row["reason"]) for row in basis_variants.values()}) == 1,
        basis_variants,
    )
    checks.eq(
        "basis_is_carried_into_provenance",
        [row["provenance_basis"] for row in basis_variants.values()],
        ["frozen_label_target", "public_corpus_structure", "frozen_question_scope", "case_business_date_baseline"],
    )

    # ---- 输出边界：无 verified/threshold/release --------------------------- #
    from mktkb.evaluation.p2_evidence_axes_adapter_v2 import FIXED_CODES

    outputs = [determination.as_dict() for determination in determinations]
    keys = [key for output in outputs for key in walk_keys(output)]
    strings = [value for output in outputs for value in walk_strings(output)]
    bad_keys = [key for key in keys if any(token in key.lower() for token in FORBIDDEN)]

    def is_fixed_code(value: str) -> bool:
        return value.split(":", 1)[0] in FIXED_CODES

    bad_values = [
        value
        for value in strings
        if any(token in value.lower() for token in FORBIDDEN) and not is_fixed_code(value)
    ]
    fixed_code_hits = sorted({value for value in strings if any(token in value.lower() for token in FORBIDDEN) and is_fixed_code(value)})
    checks.eq("no_forbidden_output_keys", bad_keys, [])
    checks.eq("no_forbidden_output_claim_values", bad_values, [])
    checks.record(
        "forbidden_token_only_in_fixed_code_vocabulary",
        fixed_code_hits == ["no_entity_scope_verified"],
        {"hits": fixed_code_hits, "note": "该串是 v1 固定码词汇，不是结论字段"},
    )
    serialized = json.dumps(outputs, ensure_ascii=False)
    checks.eq(
        "serialized_output_has_no_release_claim",
        [token for token in FORBIDDEN if token in serialized.lower().replace("no_entity_scope_verified", "")],
        [],
    )

    # ---- 合同 projection.axis_codes 不进输出 ------------------------------- #
    projection_payload = synth.default_projection()
    projection_payload["axis_codes"] = {"0|cross_entity": ["record_code_verified", "v1_target_empty_key_completed"]}
    projection_payload["target_provenance"] = {
        "0|cross_entity": [
            {"target_index": 0, "action": "derived_from_corpus_structure", "source": "derived_from_frozen_label", "basis": "public_corpus_structure"}
        ]
    }
    with_projection = synth.contract({0: cases[0]}, projection=projection_payload)
    det_projection = determine_case(contract=with_projection, case_id="C00", snapshot=snapshots[0])
    projection_output = json.dumps(det_projection.as_dict(), ensure_ascii=False)
    checks.eq("contract_axis_codes_never_in_output", "record_code_verified" in projection_output, False)
    checks.eq("target_provenance_enters_output", "derived_from_corpus_structure" in projection_output, True)

    # ---- provenance 不含运行期 id / 记录键 / 日期值 ------------------------ #
    provenance_dump = json.dumps([output["axes"]["cross_entity"]["provenance"] for output in outputs], ensure_ascii=False)
    checks.eq("provenance_has_no_uuid", UUID_RE.search(provenance_dump) is None, True)
    checks.eq("provenance_has_no_record_key_value", "W01" in provenance_dump, False)
    checks.eq("provenance_has_no_date_value", "2026-10-28" in provenance_dump, False)
    checks.eq("provenance_has_no_question_text", "question" in provenance_dump.lower(), False)

    # ---- 输出形状固定 ------------------------------------------------------ #
    checks.eq(
        "case_output_keys",
        sorted(determinations[0].as_dict().keys()),
        sorted(["case_id", "scenario_id", "delegated_axes", "contract_schema_version", "snapshot_schema_version", "axes"]),
    )
    checks.eq("axis_output_keys", sorted(determinations[0].axes["cross_entity"].as_dict().keys()),
              sorted(["axis", "case_id", "state", "reason", "provenance", "evidence", "missing"]))
    checks.eq("delegated_axes_declared", determinations[0].as_dict()["delegated_axes"], ["safety", "cross_user"])

    return checks.write(
        {
            "states": states,
            "counts": counts_dict,
            "stale_counts": stale_counts.as_dict(),
            "histogram": histogram,
            "basis_variants": basis_variants,
            "output_keys": sorted({key.split(".")[-1] for key in keys}),
        }
    )


if __name__ == "__main__":
    main()
