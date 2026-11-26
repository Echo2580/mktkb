"""必测 3：M-C1P2-01 —— class C（not_observed + candidates=[]）必须 empty_set_not_proven。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from harness import Checks, code_of
import synth

from mktkb.evaluation.p2_evidence_axes_adapter_v2 import (
    determine_case,
    load_contract_v2,
    load_snapshot_v03,
)

FROZEN_REFS = {"expected_sources": [{"record_code": "W01"}]}
CROSS_AXIS = synth.axis(
    "required", "structured_target", "explicit_single_target",
    targets=[synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})],
)
STALE_AXIS = synth.axis(
    "required", "lifecycle_dates", "published_lifecycle",
    target_refs=[synth.ref("expected_sources", 0)],
)


def run(records: Sequence[Mapping[str, Any]], *, empty: Mapping[str, Any], with_stale: bool = True):
    axes = synth.case_axes(cross_entity=CROSS_AXIS, stale_source=STALE_AXIS if with_stale else None)
    payload = synth.contract({0: axes})
    snap = synth.snapshot(records, empty=empty)
    return determine_case(contract=payload, case_id="C00", snapshot=snap, frozen_refs=FROZEN_REFS)


def summarize(det) -> dict[str, Any]:
    return {
        axis: {
            "state": det.axes[axis].state,
            "reason": det.axes[axis].reason,
            "evidence": list(det.axes[axis].evidence),
        }
        for axis in ("cross_entity", "stale_source")
    }


def main() -> dict:
    checks = Checks("03-class-c")
    report: dict[str, Any] = {}

    # 1) 标准 class C：9 层 observed + 计数 0（P3 结构上接受），retrieval 未观测 -------- #
    class_c = synth.empty_use(retrieval=(False, 0, (), False))
    det = run([], empty=class_c)
    report["class_c_standard"] = summarize(det)
    checks.eq("class_c_cross_state", det.axes["cross_entity"].state, "unknown")
    checks.eq("class_c_cross_reason", det.axes["cross_entity"].reason, "empty_set_not_proven")
    checks.eq("class_c_stale_state", det.axes["stale_source"].state, "unknown")
    checks.eq("class_c_stale_reason", det.axes["stale_source"].reason, "empty_set_not_proven")
    checks.eq(
        "class_c_proof_audit_marker",
        any("class_c_retrieval_not_observed" in item for item in det.axes["cross_entity"].evidence),
        True,
    )
    checks.record(
        "class_c_p3_flag_is_true_but_not_proven",
        class_c["empty_set_candidate"] is True and det.axes["cross_entity"].state != "passed",
        {"empty_set_candidate": class_c["empty_set_candidate"]},
    )

    # 2) class C 且 query_state/projection 候选均为空观测 -> 仍然不 proven -------------- #
    class_c2 = synth.empty_use(
        retrieval=(False, 0, (), False),
        query_state=(True, 0, (), False),
    )
    det2 = run([], empty=class_c2)
    report["class_c_query_state_observed"] = summarize(det2)
    checks.eq("class_c2_cross_reason", det2.axes["cross_entity"].reason, "empty_set_not_proven")

    # 3) 候选被截断（truncated=True）-> 不 proven ----------------------------------- #
    truncated = synth.empty_use(retrieval=(True, 0, (), True))
    det3 = run([], empty=truncated)
    report["retrieval_truncated"] = summarize(det3)
    checks.eq("truncated_cross_reason", det3.axes["cross_entity"].reason, "empty_set_not_proven")
    checks.eq(
        "truncated_marker",
        any("retrieval_candidates_truncated" in item for item in det3.axes["cross_entity"].evidence),
        True,
    )

    # 4) 检索观测到非空候选 -> 不 proven -------------------------------------------- #
    nonempty = synth.empty_use(retrieval=(True, 1, ("unit-1",), False))
    det4 = run([], empty=nonempty)
    report["retrieval_nonempty"] = summarize(det4)
    checks.eq("nonempty_cross_reason", det4.axes["cross_entity"].reason, "empty_set_not_proven")

    # 5) 使用层未观测 -> 不 proven -------------------------------------------------- #
    observed = {name: True for name in synth.USE_LAYER_NAMES}
    observed["entity_inheritance"] = False
    unobserved = synth.empty_use(observed=observed)
    det5 = run([], empty=unobserved)
    report["use_layer_unobserved"] = summarize(det5)
    checks.eq("unobserved_cross_reason", det5.axes["cross_entity"].reason, "empty_set_not_proven")

    # 6) 回合未完成 -> 不 proven ---------------------------------------------------- #
    partial = synth.empty_use(turn_status="partial")
    det6 = run([], empty=partial)
    report["turn_partial"] = summarize(det6)
    checks.eq("partial_cross_reason", det6.axes["cross_entity"].reason, "empty_set_not_proven")

    # 7) 真正的空集（9 层观测 + 检索观测且空候选、未截断）-> 才允许 pass -------------- #
    genuine = synth.empty_use(retrieval=(True, 0, (), False))
    det7 = run([], empty=genuine)
    report["genuine_empty"] = summarize(det7)
    checks.eq("genuine_cross_state", det7.axes["cross_entity"].state, "passed")
    checks.eq("genuine_cross_reason", det7.axes["cross_entity"].reason, "cross_entity_empty_use_scope_ok")
    checks.eq("genuine_stale_state", det7.axes["stale_source"].state, "passed")
    checks.eq("genuine_stale_reason", det7.axes["stale_source"].reason, "stale_source_dates_ok")

    # 8) P3 布尔自相矛盾（candidate=true 但 all_observed=false）-> 结构拒绝 ----------- #
    contradictory = synth.empty_use(
        observed={**{name: True for name in synth.USE_LAYER_NAMES}, "model_evidence": False},
        empty_set_candidate=True,
        all_observed=False,
    )
    checks.eq(
        "contradictory_empty_set_candidate_rejected",
        code_of(lambda: load_snapshot_v03(synth.snapshot([], empty=contradictory))),
        "snapshot_field_invalid:empty_use_scope_input.empty_set_candidate",
    )

    # 9) 有记录 + no_entity_claim -> N/A 不依赖空集证明（也不是 class C） ------------- #
    axes_na = synth.case_axes(
        cross_entity=synth.axis("not_applicable", "no_entity_claim", "no_entity_scope"),
        stale_source=STALE_AXIS,
    )
    na_payload = synth.contract({0: axes_na})
    na_det = determine_case(
        contract=na_payload,
        case_id="C00",
        snapshot=synth.snapshot([synth.text_record()], empty=class_c),
        frozen_refs=FROZEN_REFS,
    )
    report["no_entity_claim_with_records"] = summarize(na_det)
    checks.eq("na_state", na_det.axes["cross_entity"].state, "not_applicable")
    checks.eq("na_reason", na_det.axes["cross_entity"].reason, "no_entity_scope_verified")
    checks.eq("na_stale_still_unknown", na_det.axes["stale_source"].reason, "stale_source_unresolved")

    # 10) class C 在“有记录但身份不可解析”时也不得因空集标记翻 pass ------------------ #
    unresolved = synth.record(
        record_level=False, locator_kind="none", code="runtime_unit_unresolved",
        record_key=None, record_code=None, sheet=None, row=None,
        entity_type=None, entity_key=None, entity_filters={}, entity_matchable=False,
        entity_code="entity_identity_unavailable",
    )
    det10 = run([unresolved], empty=class_c)
    report["records_unresolved_with_class_c"] = summarize(det10)
    checks.eq("unresolved_records_cross_state", det10.axes["cross_entity"].state, "unknown")
    checks.eq("unresolved_records_cross_reason", det10.axes["cross_entity"].reason, "identity_unresolved")

    # 11) 扫描：class C 的 6 种形状里没有任何一个轴落 passed/not_applicable ---------- #
    shapes = {
        "class_c_standard": det,
        "class_c_query_state": det2,
        "truncated": det3,
        "nonempty": det4,
        "unobserved": det5,
        "partial": det6,
    }
    offending = {
        name: summarize(value)
        for name, value in shapes.items()
        if value.axes["cross_entity"].state in {"passed", "not_applicable"}
        or value.axes["stale_source"].state in {"passed", "not_applicable"}
    }
    checks.eq("no_class_c_shape_becomes_proven_or_na", offending, {})

    return checks.write({"shapes": report, "checked_shape_count": len(shapes)})


if __name__ == "__main__":
    main()
