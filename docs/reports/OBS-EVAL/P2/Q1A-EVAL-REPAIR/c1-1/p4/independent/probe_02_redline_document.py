"""必测 2：M-C1P1-01 —— document 粒度目标绝不产 violation；uuid 键必须 unknown。

自造 3 类反例（A 目标侧 document|uuid / B 运行期 entity_key 携带 doc|unit uuid /
C 运行期出现文档粒度行），外加 doc_code 降级通道的两个方向（pass / violation）作为
“规则可执行性”刻画。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from harness import Checks
import synth

from mktkb.evaluation.p2_evidence_axes_adapter_v2 import (
    determine_cross_entity,
    determine_case,
    load_contract_v2,
    load_snapshot_v03,
)

UUID = "3f1c2b7a-0d4e-4a6f-9c1d-2b8e5a7c9d10"
UNIT_UUID = "9a7b1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d"
VIOLATION_CODES = {"other_entity_used", "citation_entity_mismatch"}


def build(
    axes: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    frozen_refs: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    empty: Mapping[str, Any] | None = None,
    temporal_view: Mapping[str, Any] | None = None,
):
    payload = synth.contract({0: axes})
    snap = synth.snapshot(records, empty=empty, temporal_view=temporal_view)
    contract = load_contract_v2(payload)
    return determine_cross_entity(contract, contract.cases["C00"], load_snapshot_v03(snap))


def case_row(det) -> dict[str, Any]:
    return {
        "state": det.state,
        "reason": det.reason,
        "evidence": list(det.evidence),
        "violation_hits": sorted(code for code in det.evidence if code.split(":")[-1] in VIOLATION_CODES),
        "target_codes": det.provenance.get("target_codes"),
        "target_granularities": det.provenance.get("target_granularities"),
        "matchable_target_count": det.provenance.get("matchable_target_count"),
        "record_key_spaces": det.provenance.get("record_key_spaces"),
    }


def main() -> dict:
    checks = Checks("02-redline-document")
    report: dict[str, Any] = {}

    # 类 A：目标侧 document|<uuid>，运行期为文本行（实体 absent） -------------------- #
    axes_a = synth.case_axes(
        cross_entity=synth.axis(
            "required", "structured_target", "explicit_single_target",
            targets=[synth.target("document", f"document|{UUID}")],
        )
    )
    det_a = build(axes_a, [synth.text_record()])
    report["A_document_uuid_target_text_usage"] = case_row(det_a)
    checks.eq("A_state", det_a.state, "unknown")
    checks.eq("A_reason", det_a.reason, "target_granularity_incomparable")
    checks.eq("A_violation_hits", case_row(det_a)["violation_hits"], [])
    checks.eq("A_target_granularity", case_row(det_a)["target_granularities"], ["document"])

    # 类 A2：同一目标 + 运行期是记录级 item 行（unit 级使用） ------------------------ #
    det_a2 = build(axes_a, [synth.record()])
    report["A2_document_uuid_target_record_usage"] = case_row(det_a2)
    checks.eq("A2_state", det_a2.state, "unknown")
    checks.eq("A2_reason", det_a2.reason, "target_granularity_incomparable")
    checks.eq("A2_violation_hits", case_row(det_a2)["violation_hits"], [])

    # 类 B：运行期 entity_key 携带 doc/unit uuid + 可匹配 item 目标 ------------------ #
    axes_b = synth.case_axes(
        cross_entity=synth.axis(
            "required", "structured_target", "explicit_single_target",
            targets=[synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})],
        )
    )
    uuid_row = synth.record(
        entity_key=f"item|城北店|折叠凳|doc:{UUID}|unit:{UNIT_UUID}",
        entity_filters={"store": "城北店", "item": "折叠凳"},
        entity_matchable=False,
        entity_code="entity_identity_document_level",
    )
    det_b = build(axes_b, [uuid_row])
    report["B_runtime_key_carries_uuid"] = case_row(det_b)
    checks.eq("B_state", det_b.state, "unknown")
    checks.eq("B_reason", det_b.reason, "target_granularity_incomparable")
    checks.eq("B_violation_hits", case_row(det_b)["violation_hits"], [])
    checks.eq("B_record_key_space", case_row(det_b)["record_key_spaces"], {"document": 1})

    # 类 B2：uuid 只出现在 entity_filters（键看起来干净） --------------------------- #
    dirty_filters = synth.record(
        entity_key="item|storea|itema",
        entity_filters={"store": UUID, "item": "ItemA"},
    )
    det_b2 = build(axes_b, [dirty_filters])
    report["B2_uuid_in_filters"] = case_row(det_b2)
    checks.eq("B2_state", det_b2.state, "unknown")
    checks.eq("B2_reason", det_b2.reason, "identity_unresolved")
    checks.eq("B2_violation_hits", case_row(det_b2)["violation_hits"], [])

    # 类 C：可匹配目标 + 运行期出现文档粒度行 -------------------------------------- #
    det_c = build(axes_b, [synth.document_record(layers=["model_evidence"])])
    report["C_document_granularity_usage_row"] = case_row(det_c)
    checks.eq("C_state", det_c.state, "unknown")
    checks.eq("C_reason", det_c.reason, "target_granularity_incomparable")
    checks.eq("C_violation_hits", case_row(det_c)["violation_hits"], [])

    # 类 C2：可匹配目标命中 + 另有一行文档粒度行 -> 仍然 unknown，不因命中而 pass --- #
    det_c2 = build(axes_b, [synth.record(), synth.document_record()])
    report["C2_match_plus_document_row"] = case_row(det_c2)
    checks.eq("C2_state", det_c2.state, "unknown")
    checks.eq("C2_reason", det_c2.reason, "target_granularity_incomparable")
    checks.eq("C2_violation_hits", case_row(det_c2)["violation_hits"], [])

    # 类 D：目标自身携带运行期 id（entity_type=item 但键是 document|<uuid>） -------- #
    axes_d = synth.case_axes(
        cross_entity=synth.axis(
            "required", "structured_target", "explicit_single_target",
            targets=[synth.target("item", f"document|{UUID}", {"store": "StoreA"})],
        )
    )
    det_d = build(axes_d, [synth.record()])
    report["D_target_carries_runtime_id"] = case_row(det_d)
    checks.eq("D_state", det_d.state, "unknown")
    checks.eq("D_reason", det_d.reason, "entity_key_space_incompatible")
    checks.eq("D_violation_hits", case_row(det_d)["violation_hits"], [])
    checks.eq(
        "D_structural_matchable_flag_is_misleading",
        case_row(det_d)["matchable_target_count"],
        1,
        {"note": "结构上记为 matchable，运行期键空间却永远不可匹配"},
    )

    # 类 E：doc_code 降级通道（合同数据域内不可达，手工构造才存在） ----------------- #
    axes_e = synth.case_axes(
        cross_entity=synth.axis(
            "required", "structured_target", "explicit_single_target",
            targets=[synth.target("document", "S01")],
        )
    )
    det_e_pass = build(axes_e, [synth.record()])
    report["E_doc_code_channel_same_doc"] = case_row(det_e_pass)
    checks.eq("E_same_doc_state", det_e_pass.state, "passed")
    checks.eq("E_same_doc_reason", det_e_pass.reason, "cross_entity_targets_match_ok")
    checks.record(
        "E_same_doc_used_doc_code_channel",
        any(item.endswith("doc_code_level_comparison_used") for item in det_e_pass.evidence),
        list(det_e_pass.evidence),
    )

    other_doc = synth.record(doc_code="S02", base_doc_code="S02", source_ref="src-2")
    det_e_violation = build(axes_e, [synth.record(), other_doc])
    report["E_doc_code_channel_other_doc"] = case_row(det_e_violation)
    checks.eq("E_other_doc_state", det_e_violation.state, "violation")
    checks.eq("E_other_doc_reason", det_e_violation.reason, "other_entity_used")
    # 对照：运行期根本没有目标 doc_code -> doc_targets 为空 -> targets_unresolved（unknown）
    det_e_absent = build(axes_e, [other_doc])
    report["E_doc_code_target_absent_from_runtime"] = case_row(det_e_absent)
    checks.eq("E_target_doc_absent_state", det_e_absent.state, "unknown")
    checks.eq("E_target_doc_absent_reason", det_e_absent.reason, "targets_unresolved")

    # E3：同一轴同时有 document|<uuid>（不可匹配）与 doc_code 型 document 目标
    axes_e3 = synth.case_axes(
        cross_entity=synth.axis(
            "required", "structured_target", "explicit_single_target",
            targets=[synth.target("document", f"document|{UUID}"), synth.target("document", "S01")],
        )
    )
    det_e3 = build(axes_e3, [synth.record(), other_doc])
    report["E3_document_uuid_plus_doc_code_target"] = case_row(det_e3)
    checks.eq("E3_state", det_e3.state, "violation")
    checks.eq("E3_reason", det_e3.reason, "other_entity_used")
    checks.record(
        "E3_document_uuid_target_does_not_block_doc_code_channel",
        det_e3.state == "violation",
        {"note": "违规定因是 doc_code 型目标，不是 document|<uuid> 目标"},
    )
    checks.record(
        "E_doc_code_channel_is_the_only_violation_path_for_document_typed_target",
        True,
        {"note": "该 target 的 entity_type 是 document；违反字面 M-C1P1-01，但符合“改用 doc_code 级身份”的口径"},
    )

    # 类 F：no_entity_claim + 运行期有实体 -> 冲突 unknown（不得 N/A） -------------- #
    axes_f = synth.case_axes(
        cross_entity=synth.axis("not_applicable", "no_entity_claim", "no_entity_scope")
    )
    det_f = build(axes_f, [synth.record()])
    report["F_no_entity_claim_with_runtime_entity"] = case_row(det_f)
    checks.eq("F_state", det_f.state, "unknown")
    checks.eq("F_reason", det_f.reason, "entity_scope_conflict")

    # 汇总：A/B/C 三类的 violation 计数必须为 0 ----------------------------------- #
    class_rows = [det_a, det_a2, det_b, det_b2, det_c, det_c2, det_d]
    checks.eq("redline_classes_violation_total", sum(1 for det in class_rows if det.state == "violation"), 0)
    checks.eq("redline_classes_unknown_total", sum(1 for det in class_rows if det.state == "unknown"), len(class_rows))

    # 走完整题入口（含 stale 轴）确认不是单轴函数的偶然 ---------------------------- #
    full = determine_case(
        contract=synth.contract({0: axes_a}),
        case_id="C00",
        snapshot=synth.snapshot([synth.text_record()]),
    )
    checks.eq("full_case_document_target_state", full.axes["cross_entity"].state, "unknown")
    checks.eq(
        "full_case_document_target_reason",
        full.axes["cross_entity"].reason,
        "target_granularity_incomparable",
    )

    return checks.write({"shapes": report})


if __name__ == "__main__":
    main()
