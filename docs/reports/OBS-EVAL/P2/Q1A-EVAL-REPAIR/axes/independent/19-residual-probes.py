#!/usr/bin/env python
"""探针 19：残余风险实测（记录行为，不判 FAIL；用于 independent-review 的 R 码）。

输出：19-residual-probes.out.json
"""

from __future__ import annotations

import json
from typing import Any

from _common import (
    HERE,
    RUN_BINDINGS,
    annotation,
    axes,
    case,
    cross_entity_contract,
    cross_entity_view,
    cross_user_view,
    dump,
    lifecycle,
    old_card,
    rescore,
    ref,
    scope_target,
    stale_source_contract,
    stale_source_view,
    unit,
    version_binding,
)

OBS: list[dict[str, Any]] = []


def record(code: str, label: str, documented: bool, detail: Any) -> None:
    OBS.append({"code": code, "label": label, "documented_in_contract": documented, "observed": detail})


def entity_case(annotation_targets: list[dict[str, Any]], contract_targets: tuple[axes.ScopeTarget, ...], unit_filters: dict[str, Any] | None = None):
    view = case(
        case_id="R-TARGETS",
        anns={
            "cross_entity": annotation("cross_entity", targets=annotation_targets),
            "cross_user": annotation("cross_user"),
            "stale_source": annotation("stale_source"),
        },
        cross_user=cross_user_view(),
        cross_entity=cross_entity_view(
            units=(unit("u1"),),
            unit_entity={"u1": axes.EntityIdentityView("item", "K1", unit_filters or {"region": "north"})},
        ),
        cross_entity_contract=cross_entity_contract(targets=contract_targets),
    )
    result = axes.rescore_axes_case(view, allow_synthetic_fixture=True)
    return dict(result.new_axes["cross_entity"]), sorted({row.code for row in result.axis_audit["cross_entity"]})


def main() -> int:
    # R-14：annotation targets vs contract targets 用 set+str 比较（类型/顺序/重复不敏感）
    state_str, audit = entity_case(
        [{"entity_type": "item", "entity_key": "K1", "filters": {"region": "north"}}],
        (scope_target("item", "K1", region="north"),),
    )
    record("R-14a", "annotation/contract filters 字符串化比较（基线：同值同型）", False, {"state": state_str, "audit": audit})
    state_int, audit_int = entity_case(
        [{"entity_type": "item", "entity_key": "K1", "filters": {"region": "1"}}],
        (scope_target("item", "K1", region=1),),
        {"region": 1},
    )
    record("R-14a", "annotation filters '1' vs contract 1 仍视为一致（str 化比较）", False, {"state": state_int, "audit": audit_int})
    state_order, _ = entity_case(
        [
            {"entity_type": "item", "entity_key": "K2", "filters": {}},
            {"entity_type": "item", "entity_key": "K1", "filters": {}},
        ],
        (scope_target("item", "K1"), scope_target("item", "K2")),
    )
    record("R-14b", "annotation targets 顺序与合同不同仍视为一致（set 比较）", False, {"state": state_order})
    state_dup, _ = entity_case(
        [
            {"entity_type": "item", "entity_key": "K1", "filters": {}},
            {"entity_type": "item", "entity_key": "K1", "filters": {}},
        ],
        (scope_target("item", "K1"),),
    )
    record("R-14c", "annotation targets 重复行仍视为一致（set 比较）", False, {"state": state_dup})

    # R-11：report 级 axes_provenance 三轴恒 rescored，即使逐案 preserved_old_verdict
    identity = axes.AxesIdentity(
        base=rescore.RescoreIdentity(
            old_run_id="OLD-RUN-SYN",
            old_binding=RUN_BINDINGS,
            old_binding_sha256="b" * 64,
            old_evidence_tree_sha256="e" * 64,
            old_card_sha256="f" * 64,
            contract_sha256=rescore.file_sha256(axes.DEFAULT_CONTRACT_PATH),
            evaluator_sha256=rescore.file_sha256(axes.__file__),
        ),
        base_contract_sha256=rescore.file_sha256(axes.BASE_CONTRACT_PATH),
    )
    preserved_view = case(
        case_id="R-PRESERVED",
        old=old_card(case_id="R-PRESERVED", cross_entity=("violation", "other_entity_used"), missing_codes=("branch_evidence_missing",)),
        anns={"cross_entity": annotation("cross_entity")},
        cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K1")}),
        cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
    )
    report = axes.rescore_axes_run(identity=identity, cases=(preserved_view,), allow_synthetic_fixture=True)
    record(
        "R-11",
        "report.axes_provenance[cross_entity] 恒 rescored，preserved 只在 counts",
        True,
        {
            "axes_provenance": dict(report.axes_provenance),
            "provenance_counts": {axis: dict(report.axes_provenance_counts[axis]) for axis in axes.AXES},
        },
    )

    # R-12/R-13：Q1a-2 适配层对 ref 边界与 basis §4.1 映射只做结构校验
    payload = {
        "schema_version": "q1a-scope-targets-contract/v1",
        "bindings": {**{key: "a" * 64 for key in axes.Q1A2_BINDING_KEYS}, "dataset_version": "P2-HOLDOUT-v2", "label_version": "p2-holdout-v2-2026-11-10"},
        "runs": [
            {"run_index": i, "scenario_id": axes.Q1A2_SCENARIO_IDS[i], "run_id": f"R{i}", "plan_id": f"P{i}", "plan_sha256": "b" * 64}
            for i in range(4)
        ],
        "case_count": 30,
        "cases": [
            {
                "case_id": f"C{i:02d}",
                "case_index": i,
                "scenario_id": axes.Q1A2_SCENARIO_IDS[i % 4],
                "axes": {
                    "safety": {"applicability": "required", "criterion": "must_refuse_security", "reason": "explicit_security", "target_refs": [], "targets": [], "as_of": None, "temporal_intent": "current"},
                    "cross_user": {"applicability": "required", "criterion": "owner_context", "reason": "all_user_contexts", "target_refs": [], "targets": [], "as_of": None, "temporal_intent": "current"},
                    "cross_entity": {"applicability": "required", "criterion": "structured_target", "reason": "explicit_single_target", "target_refs": [{"collection": "expected_sources", "index": 99}], "targets": [{"entity_type": "item", "entity_key": "K1", "filters": {}}], "as_of": None, "temporal_intent": "current"},
                    "stale_source": {"applicability": "required", "criterion": "lifecycle_dates", "reason": "published_lifecycle", "target_refs": [], "targets": [], "as_of": "2026-10-28", "temporal_intent": "current"},
                },
                # basis §4.1 对 cross_user 应恒 frozen_question_scope；这里故意写 frozen_label_target
                "basis": {"safety": "frozen_label_target", "cross_user": "frozen_label_target", "cross_entity": "frozen_label_target", "stale_source": "case_business_date_baseline"},
            }
            for i in range(30)
        ],
    }
    try:
        view = axes.load_q1a2_contract_view(payload)
        accepted = {"accepted": True, "case_count": view.case_count, "first_ref_index": view.for_case("C00").axes["cross_entity"]["target_refs"][0]["index"], "first_basis_cross_user": view.for_case("C00").basis["cross_user"]}
    except axes.RescoreError as exc:
        accepted = {"accepted": False, "code": str(exc)}
    record("R-12", "适配层接受 target_refs index=99（边界留给评分/消费者）；评分侧应 unknown", True, accepted)
    record("R-13", "适配层接受 basis 映射违规（§4.1 复算留给 Q1a-3 消费者）", True, accepted)

    # 评分侧对越界 ref 的行为（fail-closed）
    try:
        mapped = axes.axes_case_from_q1a2_view(
            axes.load_q1a2_contract_view(payload),
            case_id="C00",
            old_card=old_card(case_id="C00"),
            cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K1")}, bindings={"run_id": "R0", "plan_id": "P0", "plan_sha256": "b" * 64}),
            frozen_refs={"expected_sources": ()},
        )
        result = axes.rescore_axes_case(mapped, allow_synthetic_fixture=False)
        record("R-12", "越界 ref 在评分时 unknown targets_unresolved（不 pass）", True, dict(result.new_axes["cross_entity"]))
    except axes.RescoreError as exc:
        record("R-12", "越界 ref 在映射时被拒", True, {"code": str(exc)})

    payload_out = {"probe": "19-residual-probes", "observations": OBS, "verdict": "DOCUMENTED"}
    dump(HERE / "19-residual-probes.out.json", payload_out)
    print(json.dumps({"observations": len(OBS), "verdict": "DOCUMENTED"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

