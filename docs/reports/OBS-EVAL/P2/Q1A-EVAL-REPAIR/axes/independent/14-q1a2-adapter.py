#!/usr/bin/env python
"""探针 14：Q1a-2 v1 公开 schema 适配层正例/反例（5/17/4/30/4/7 形状；fail-closed）。

只用合成 30 题 payload；不解密、不读密文/key/.env。
输出：14-q1a2-adapter.out.json
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable

from _common import (
    HERE,
    annotation,
    axes,
    case,
    cross_entity_view,
    cross_user_view,
    dump,
    lifecycle,
    old_card,
    ref,
    rescore,
    stale_source_view,
    unit,
    version_binding,
)

RESULTS: list[dict[str, Any]] = []

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64

BINDINGS: dict[str, str] = {
    "old_run_binding_sha256": HASH_A,
    "old_run_binding_file_sha256": HASH_B,
    "dataset_version": "P2-HOLDOUT-v2",
    "label_version": "p2-holdout-v2-2026-11-10",
    "manifest_sha256": HASH_C,
    "cases_sha256": HASH_D,
    "source_map_sha256": HASH_E,
    "ingest_plan_sha256": HASH_A,
    "scenario_contract_sha256": HASH_B,
    "annotation_v0_2_ciphertext_sha256": HASH_C,
    "annotation_review_v0_2_ciphertext_sha256": HASH_D,
    "annotation_v0_3_ciphertext_sha256": HASH_E,
    "annotation_schema_sha256": HASH_A,
    "annotation_manager_acceptance_v2_sha256": HASH_B,
    "annotation_review_aggregate_v2_sha256": HASH_C,
    "addendum_acceptance_v3_sha256": HASH_D,
    "contract_schema_sha256": HASH_E,
}

SCENARIOS = ["base_b0", "base_b0_plus_v01", "pre_v05_without_v07", "post_v05_without_v01"]
RUNS = [
    {
        "run_index": index,
        "scenario_id": scenario,
        "run_id": f"RUN-{index}",
        "plan_id": f"PLAN-{index}",
        "plan_sha256": (str(index) * 64)[:64],
    }
    for index, scenario in enumerate(SCENARIOS)
]


def axis_object(axis: str, index: int) -> dict[str, Any]:
    if axis == "safety":
        if index % 7 == 3:
            return {
                "applicability": "not_applicable",
                "criterion": "benign_business",
                "reason": "benign_business",
                "target_refs": [],
                "targets": [],
                "as_of": None,
                "temporal_intent": "not_applicable",
            }
        return {
            "applicability": "required",
            "criterion": "must_refuse_security",
            "reason": "explicit_security",
            "target_refs": [{"collection": "forbidden_sources", "index": 0}],
            "targets": [{"entity_type": "secret", "entity_key": f"S{index}", "filters": {}}],
            "as_of": None,
            "temporal_intent": "current",
        }
    if axis == "cross_user":
        return {
            "applicability": "required",
            "criterion": "owner_context",
            "reason": "all_user_contexts",
            "target_refs": [],
            "targets": [],
            "as_of": None,
            "temporal_intent": "current",
        }
    if axis == "cross_entity":
        mode = index % 3
        if mode == 0:
            return {
                "applicability": "required",
                "criterion": "structured_target",
                "reason": "explicit_single_target",
                "target_refs": [{"collection": "expected_sources", "index": 0}],
                "targets": [{"entity_type": "item", "entity_key": f"K{index}", "filters": {"region": "north"}}],
                "as_of": None,
                "temporal_intent": "current",
            }
        if mode == 1:
            return {
                "applicability": "required",
                "criterion": "shared_background",
                "reason": "shared_policy",
                "target_refs": [],
                "targets": [],
                "as_of": None,
                "temporal_intent": "not_applicable",
            }
        return {
            "applicability": "not_applicable",
            "criterion": "no_entity_claim",
            "reason": "no_entity_scope",
            "target_refs": [],
            "targets": [],
            "as_of": None,
            "temporal_intent": "not_applicable",
        }
    # stale_source
    return {
        "applicability": "required",
        "criterion": "lifecycle_dates",
        "reason": "published_lifecycle",
        "target_refs": [{"collection": "expected_sources", "index": 0}],
        "targets": [],
        "as_of": "2026-10-28" if index % 2 == 0 else None,
        "temporal_intent": "current",
    }


BASIS = {
    "safety": "frozen_label_target",
    "cross_user": "frozen_question_scope",
    "cross_entity": "frozen_label_target",
    "stale_source": "case_business_date_baseline",
}


def build_payload() -> dict[str, Any]:
    cases = []
    for index in range(30):
        cases.append(
            {
                "case_id": f"SYN-CASE-{index:02d}",
                "case_index": index,
                "scenario_id": SCENARIOS[index % 4],
                "axes": {axis: axis_object(axis, index) for axis in axes.AXES},
                "basis": {axis: BASIS[axis] for axis in axes.AXES},
            }
        )
    return {
        "schema_version": "q1a-scope-targets-contract/v1",
        "bindings": dict(BINDINGS),
        "runs": copy.deepcopy(RUNS),
        "case_count": 30,
        "cases": cases,
    }


def check(label: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"label": label, "ok": bool(ok), "detail": detail})


def expect_code(label: str, expected: str, payload: Any, **kwargs: Any) -> None:
    try:
        axes.load_q1a2_contract_view(payload, **kwargs)
    except axes.RescoreError as exc:
        check(label, str(exc) == expected, {"expected": expected, "actual": str(exc)})
    except Exception as exc:  # noqa: BLE001
        check(label, False, {"expected": expected, "raised": type(exc).__name__, "message": str(exc)})
    else:
        check(label, False, {"expected": expected, "raised": "accepted"})


def mutate(label: str, expected: str, fn: Callable[[dict[str, Any]], None]) -> None:
    payload = build_payload()
    fn(payload)
    expect_code(label, expected, payload)


def main() -> int:
    payload = build_payload()

    # ---------- 正例 ----------
    view = axes.load_q1a2_contract_view(payload)
    check("positive: 5/17/4/30 accepted", view.case_count == 30 and len(view.cases) == 30 and len(view.runs) == 4, {"cases": len(view.cases), "runs": len(view.runs), "bindings": len(view.bindings)})
    check("positive: schema_version", view.schema_version == "q1a-scope-targets-contract/v1")
    first = view.for_case("SYN-CASE-00")
    check("positive: case view resolved", first is not None and first.case_index == 0)
    check("positive: run_for_scenario", view.run_for_scenario("base_b0_plus_v01")["plan_id"] == "PLAN-1")
    check("positive: missing case returns None", view.for_case("NO-SUCH") is None)

    # 逐轴 7 字段保留
    check("positive: axis objects keep exactly 7 fields", all(set(first.axes[axis]) == axes.Q1A2_AXIS_KEYS for axis in axes.AXES))

    # expected_axes 一致 -> 通过
    expected = {case_id: {axis: copy.deepcopy(dict(case_view.axes[axis])) for axis in axes.AXES} for case_id, case_view in view.cases.items()}
    view2 = axes.load_q1a2_contract_view(payload, expected_axes=expected)
    check("positive: expected_axes deep-equal accepted", view2.case_count == 30)

    # expected_axes 反例：改任意一个 7 字段值
    bad = copy.deepcopy(expected)
    bad["SYN-CASE-03"]["cross_entity"]["targets"][0]["entity_key"] = "K-CHANGED"
    expect_code("expected_axes value changed -> contract_semantics_changed", "contract_semantics_changed", payload, expected_axes=bad)

    bad_missing = copy.deepcopy(expected)
    bad_missing["SYN-CASE-07"]["stale_source"].pop("as_of")
    expect_code("expected_axes missing field -> contract_semantics_changed", "contract_semantics_changed", payload, expected_axes=bad_missing)

    bad_extra = copy.deepcopy(expected)
    bad_extra["SYN-CASE-08"]["safety"]["extra"] = 1
    expect_code("expected_axes extra field -> contract_semantics_changed", "contract_semantics_changed", payload, expected_axes=bad_extra)

    bad_case = copy.deepcopy(expected)
    bad_case.pop("SYN-CASE-09")
    expect_code("expected_axes case set mismatch -> contract_coverage_invalid", "contract_coverage_invalid", payload, expected_axes=bad_case)

    bad_case_axis = copy.deepcopy(expected)
    bad_case_axis["SYN-CASE-10"].pop("safety")
    expect_code("expected_axes case missing axis -> contract_semantics_changed", "contract_semantics_changed", payload, expected_axes=bad_case_axis)

    expect_code("expected_axes not a mapping -> contract_semantics_changed", "contract_semantics_changed", payload, expected_axes=["not", "a", "mapping"])

    # 传 expected_axes 时，结构/绑定/轴/basis 错误仍按各自固定码拒绝（不被语义检查吞掉）
    p_schema = build_payload()
    p_schema["schema_version"] = "q1a-scope-targets-contract/v2"
    expect_code("with expected_axes: schema still rejected by own code", "contract_schema_invalid", p_schema, expected_axes=expected)
    p_basis = build_payload()
    p_basis["cases"][0]["basis"]["safety"] = "best_effort"
    expect_code("with expected_axes: basis still rejected by own code", "contract_basis_invalid", p_basis, expected_axes=expected)
    p_axis = build_payload()
    p_axis["cases"][0]["axes"]["cross_user"]["criterion"] = "structured_target"
    expect_code("with expected_axes: axis still rejected by own code", "contract_axis_invalid", p_axis, expected_axes=expected)
    p_down = build_payload()
    p_down["cases"][2]["axes"]["cross_entity"]["reason"] = "unresolved_target"
    expect_code("with expected_axes: unknown downgrade still rejected", "contract_unknown_downgraded", p_down, expected_axes=expected)

    # unknown -> N/A：无 expected_axes 时只有“N/A + 不确定 reason”签名被拒；改写为良性 reason 需 expected_axes 兜底
    unknown_payload = build_payload()
    unknown_payload["cases"][2]["axes"]["cross_entity"] = {
        "applicability": "unknown",
        "criterion": "unknown",
        "reason": "insufficient_annotation",
        "target_refs": [],
        "targets": [],
        "as_of": None,
        "temporal_intent": "unknown",
    }
    unknown_payload["cases"][2]["basis"]["cross_entity"] = "no_provable_basis_keep_unknown"
    unknown_view = axes.load_q1a2_contract_view(unknown_payload)
    unknown_expected = {
        case_id: {axis: copy.deepcopy(dict(case_view.axes[axis])) for axis in axes.AXES}
        for case_id, case_view in unknown_view.cases.items()
    }
    rewritten = copy.deepcopy(unknown_payload)
    rewritten["cases"][2]["axes"]["cross_entity"] = {
        "applicability": "not_applicable",
        "criterion": "no_entity_claim",
        "reason": "no_entity_scope",
        "target_refs": [],
        "targets": [],
        "as_of": None,
        "temporal_intent": "not_applicable",
    }
    rewritten["cases"][2]["basis"]["cross_entity"] = "frozen_question_scope"
    try:
        axes.load_q1a2_contract_view(rewritten)
    except axes.RescoreError as exc:
        check("unknown -> N/A benign rewrite observed behavior (no expected_axes)", False, str(exc))
    else:
        RESULTS.append(
            {
                "label": "unknown -> N/A benign rewrite is NOT caught without expected_axes (deferral; expected_axes catches it)",
                "ok": True,
                "detail": "accepted by design; schema §5 deep compare / expected_axes is the consumer's duty",
            }
        )
    expect_code(
        "unknown -> N/A benign rewrite caught by expected_axes",
        "contract_semantics_changed",
        rewritten,
        expected_axes=unknown_expected,
    )

    # N/A + insufficient_annotation 也属于 unknown 降级签名
    p_insufficient = build_payload()
    p_insufficient["cases"][2]["axes"]["cross_entity"]["reason"] = "insufficient_annotation"
    expect_code(
        "N/A + insufficient_annotation -> contract_unknown_downgraded",
        "contract_unknown_downgraded",
        p_insufficient,
    )

    # ---------- 反例：schema / binding / coverage / axis / basis ----------    mutate("schema_version wrong", "contract_schema_invalid", lambda p: p.__setitem__("schema_version", "q1a-scope-targets-contract/v2"))
    mutate("schema_version missing", "contract_schema_invalid", lambda p: p.pop("schema_version"))
    mutate("top-level extra key", "contract_schema_invalid", lambda p: p.__setitem__("private", {}))
    expect_code("top-level not mapping", "contract_schema_invalid", ["not", "a", "mapping"])

    mutate("bindings missing key", "contract_binding_mismatch", lambda p: p["bindings"].pop("contract_schema_sha256"))
    mutate("bindings extra key", "contract_binding_mismatch", lambda p: p["bindings"].__setitem__("extra", HASH_A))
    mutate("bindings hash not 64 hex", "contract_binding_mismatch", lambda p: p["bindings"].__setitem__("manifest_sha256", "z" * 64))
    mutate("bindings hash short", "contract_binding_mismatch", lambda p: p["bindings"].__setitem__("cases_sha256", "a" * 63))
    mutate("dataset_version wrong", "contract_binding_mismatch", lambda p: p["bindings"].__setitem__("dataset_version", "P2-HOLDOUT-v3"))
    mutate("label_version wrong", "contract_binding_mismatch", lambda p: p["bindings"].__setitem__("label_version", "p2-holdout-v2-2026-11-11"))
    mutate("bindings not mapping", "contract_binding_mismatch", lambda p: p.__setitem__("bindings", []))

    mutate("runs length 3", "contract_schema_invalid", lambda p: p["runs"].pop())
    mutate("runs length 5", "contract_schema_invalid", lambda p: p["runs"].append(copy.deepcopy(p["runs"][0])))
    mutate("runs order wrong", "contract_schema_invalid", lambda p: p["runs"][0].__setitem__("scenario_id", "base_b0_plus_v01"))
    mutate("run_index wrong", "contract_schema_invalid", lambda p: p["runs"][2].__setitem__("run_index", 3))
    mutate("run_id empty", "contract_schema_invalid", lambda p: p["runs"][1].__setitem__("run_id", ""))
    mutate("run plan_sha256 bad", "contract_schema_invalid", lambda p: p["runs"][1].__setitem__("plan_sha256", "x" * 64))
    mutate("run extra key", "contract_schema_invalid", lambda p: p["runs"][0].__setitem__("extra", 1))

    mutate("case_count 29", "contract_coverage_invalid", lambda p: p.__setitem__("case_count", 29))
    mutate("case_count bool", "contract_coverage_invalid", lambda p: p.__setitem__("case_count", True))
    mutate("cases length 29", "contract_coverage_invalid", lambda p: p["cases"].pop())
    mutate("cases not list", "contract_coverage_invalid", lambda p: p.__setitem__("cases", {}))
    mutate("case duplicate id", "contract_coverage_invalid", lambda p: p["cases"][1].__setitem__("case_id", p["cases"][0]["case_id"]))
    mutate("case_index wrong", "contract_schema_invalid", lambda p: p["cases"][4].__setitem__("case_index", 5))
    mutate("case extra key", "contract_schema_invalid", lambda p: p["cases"][0].__setitem__("extra", 1))
    mutate("case scenario_id unknown", "contract_schema_invalid", lambda p: p["cases"][0].__setitem__("scenario_id", "base_b9"))
    mutate("case_id empty", "contract_schema_invalid", lambda p: p["cases"][3].__setitem__("case_id", ""))
    mutate("case not mapping", "contract_schema_invalid", lambda p: p["cases"].__setitem__(6, "x"))

    mutate("axes missing axis", "contract_axis_invalid", lambda p: p["cases"][0]["axes"].pop("stale_source"))
    mutate("axes extra axis", "contract_axis_invalid", lambda p: p["cases"][0]["axes"].__setitem__("extra", {}))
    mutate("axes not mapping", "contract_axis_invalid", lambda p: p["cases"][0].__setitem__("axes", []))
    mutate("axis object missing field", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_user"].pop("as_of"))
    mutate("axis object extra field", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_user"].__setitem__("extra", 1))
    mutate("applicability invalid", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_user"].__setitem__("applicability", "maybe"))
    mutate("criterion invalid for axis", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_user"].__setitem__("criterion", "structured_target"))
    mutate("reason not in 18 codes", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_user"].__setitem__("reason", "made_up_reason"))
    mutate("temporal_intent invalid", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"].__setitem__("temporal_intent", "past"))
    mutate("target_refs not list", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_user"].__setitem__("target_refs", {}))
    mutate("target_refs negative index", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"]["target_refs"][0].__setitem__("index", -1))
    mutate("target_refs bool index", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"]["target_refs"][0].__setitem__("index", True))
    mutate("target_refs invalid collection", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"]["target_refs"][0].__setitem__("collection", "other"))
    mutate("target_refs extra key", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"]["target_refs"][0].__setitem__("extra", 1))
    mutate(
        "target_refs duplicate pair",
        "contract_axis_invalid",
        lambda p: p["cases"][0]["axes"]["stale_source"]["target_refs"].append({"collection": "expected_sources", "index": 0}),
    )
    mutate("targets not list", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_entity"].__setitem__("targets", "item"))
    mutate("targets entry missing key", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_entity"]["targets"][0].pop("filters"))
    mutate("targets entity_type empty", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_entity"]["targets"][0].__setitem__("entity_type", ""))
    mutate("targets filters not mapping", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_entity"]["targets"][0].__setitem__("filters", []))
    mutate("targets filters list value", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_entity"]["targets"][0]["filters"].__setitem__("k", ["v"]))
    mutate("as_of not ISO", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"].__setitem__("as_of", "2026/10/28"))
    mutate("as_of impossible date", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"].__setitem__("as_of", "2026-02-31"))
    mutate("cross_user not required", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["cross_user"].__setitem__("applicability", "not_applicable"))
    mutate("stale_source unknown applicability", "contract_axis_invalid", lambda p: p["cases"][0]["axes"]["stale_source"].__setitem__("applicability", "unknown"))
    mutate(
        "cross_entity N/A with wrong criterion",
        "contract_axis_invalid",
        lambda p: p["cases"][2]["axes"]["cross_entity"].__setitem__("criterion", "structured_target"),
    )
    mutate(
        "N/A + ambiguous_semantics -> unknown downgraded",
        "contract_unknown_downgraded",
        lambda p: p["cases"][2]["axes"]["cross_entity"].__setitem__("reason", "ambiguous_semantics"),
    )
    mutate(
        "N/A + unresolved_target -> unknown downgraded",
        "contract_unknown_downgraded",
        lambda p: p["cases"][2]["axes"]["cross_entity"].__setitem__("reason", "unresolved_target"),
    )
    mutate(
        "N/A + source_state_conflict -> unknown downgraded",
        "contract_unknown_downgraded",
        lambda p: p["cases"][2]["axes"]["cross_entity"].__setitem__("reason", "source_state_conflict"),
    )
    mutate(
        "N/A + third_state_required -> unknown downgraded",
        "contract_unknown_downgraded",
        lambda p: p["cases"][2]["axes"]["cross_entity"].__setitem__("reason", "third_state_required"),
    )

    mutate("basis missing axis", "contract_basis_invalid", lambda p: p["cases"][0]["basis"].pop("safety"))
    mutate("basis extra axis", "contract_basis_invalid", lambda p: p["cases"][0]["basis"].__setitem__("extra", "frozen_label_target"))
    mutate("basis value out of enum", "contract_basis_invalid", lambda p: p["cases"][0]["basis"].__setitem__("safety", "best_effort"))
    mutate(
        "no_provable_basis_keep_unknown with required",
        "contract_basis_invalid",
        lambda p: p["cases"][0]["basis"].__setitem__("cross_user", "no_provable_basis_keep_unknown"),
    )
    mutate("basis not mapping", "contract_basis_invalid", lambda p: p["cases"][0].__setitem__("basis", []))

    # ---------- 适配映射与评分 ----------
    payload_ok = build_payload()
    view_ok = axes.load_q1a2_contract_view(payload_ok)
    case_view = view_ok.for_case("SYN-CASE-00")
    entity_target = case_view.axes["cross_entity"]["targets"][0]
    frozen_ref = ref()
    evidence = cross_entity_view(
        units=(unit("u1"),),
        unit_entity={"u1": axes.EntityIdentityView(entity_target["entity_type"], entity_target["entity_key"], {"region": "north"})},
        bindings={"run_id": "RUN-0", "plan_id": "PLAN-0", "plan_sha256": "0" * 64},
    )
    axes_view = axes.axes_case_from_q1a2_view(
        view_ok,
        case_id="SYN-CASE-00",
        old_card=old_card(case_id="SYN-CASE-00"),
        cross_user=cross_user_view(),
        cross_entity=evidence,
        stale_source=stale_source_view(units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28", bindings={"run_id": "RUN-0", "plan_id": "PLAN-0", "plan_sha256": "0" * 64}),
        frozen_refs={"expected_sources": (frozen_ref,)},
        version_bindings={rescore.ref_key(frozen_ref): version_binding()},
    )
    check("adapter: run bindings injected from scenario", dict(axes_view.cross_entity_contract.bindings) == {"run_id": "RUN-0", "plan_id": "PLAN-0", "plan_sha256": "0" * 64}, dict(axes_view.cross_entity_contract.bindings))
    check("adapter: basis injected per axis", all(axes_view.annotations[axis].basis == case_view.basis[axis] for axis in axes.RESCORED_AXES))
    check("adapter: source marker default frozen_contract", all(axes_view.annotations[axis].source == "frozen_contract" for axis in axes.RESCORED_AXES))
    check("adapter: cross_entity mode entity_bound", axes_view.cross_entity_contract.mode == "entity_bound", axes_view.cross_entity_contract.mode)
    result = axes.rescore_axes_case(axes_view, allow_synthetic_fixture=False)
    check("adapter: real-marker contract scores cross_entity pass", result.new_axes["cross_entity"]["state"] == "passed", dict(result.new_axes["cross_entity"]))
    check("adapter: cross_user pass", result.new_axes["cross_user"]["state"] == "passed", dict(result.new_axes["cross_user"]))
    check("adapter: stale_source pass", result.new_axes["stale_source"]["state"] == "passed", dict(result.new_axes["stale_source"]))

    # basis 只进 provenance：换合法 basis 不改 verdict
    payload_basis = build_payload()
    payload_basis["cases"][0]["basis"]["cross_entity"] = "public_corpus_structure"
    view_basis = axes.load_q1a2_contract_view(payload_basis)
    axes_view_basis = axes.axes_case_from_q1a2_view(
        view_basis,
        case_id="SYN-CASE-00",
        old_card=old_card(case_id="SYN-CASE-00"),
        cross_user=cross_user_view(),
        cross_entity=evidence,
        stale_source=stale_source_view(units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28", bindings={"run_id": "RUN-0", "plan_id": "PLAN-0", "plan_sha256": "0" * 64}),
        frozen_refs={"expected_sources": (frozen_ref,)},
        version_bindings={rescore.ref_key(frozen_ref): version_binding()},
    )
    result_basis = axes.rescore_axes_case(axes_view_basis, allow_synthetic_fixture=False)
    check("basis only provenance: verdict unchanged", result_basis.new_axes["cross_entity"] == result.new_axes["cross_entity"])
    check("basis only provenance: axis_basis changed", result_basis.axis_basis["cross_entity"] == "public_corpus_structure" and result.axis_basis["cross_entity"] == "frozen_label_target")

    # synthetic marker：默认不可信
    synthetic_view = axes.axes_case_from_q1a2_view(
        view_ok,
        case_id="SYN-CASE-00",
        old_card=old_card(case_id="SYN-CASE-00"),
        cross_user=cross_user_view(),
        cross_entity=evidence,
        stale_source=stale_source_view(units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28", bindings={"run_id": "RUN-0", "plan_id": "PLAN-0", "plan_sha256": "0" * 64}),
        frozen_refs={"expected_sources": (frozen_ref,)},
        version_bindings={rescore.ref_key(frozen_ref): version_binding()},
        source_marker="synthetic_fixture",
    )
    denied = axes.rescore_axes_case(synthetic_view, allow_synthetic_fixture=False)
    check("adapter: synthetic marker denied by default", denied.new_axes["cross_entity"]["state"] == "unknown" and {row.code for row in denied.axis_audit["cross_entity"]} >= {"source_marker_untrusted"}, dict(denied.new_axes["cross_entity"]))

    # 合同缺失 case / 越界 ref：fail-closed（unknown，不 pass）
    try:
        axes.axes_case_from_q1a2_view(view_ok, case_id="NO-SUCH", old_card=old_card(case_id="NO-SUCH"))
    except axes.RescoreError as exc:
        check("adapter: unknown case -> contract_coverage_invalid", str(exc) == "contract_coverage_invalid", str(exc))
    else:
        check("adapter: unknown case -> contract_coverage_invalid", False, "accepted")

    out_of_range_view = axes.axes_case_from_q1a2_view(
        view_ok,
        case_id="SYN-CASE-00",
        old_card=old_card(case_id="SYN-CASE-00"),
        cross_user=cross_user_view(),
        cross_entity=cross_entity_view(
            units=(unit("u1"),),
            unit_entity={"u1": axes.EntityIdentityView(entity_target["entity_type"], entity_target["entity_key"], {"region": "north"})},
            bindings={"run_id": "RUN-0", "plan_id": "PLAN-0", "plan_sha256": "0" * 64},
        ),
        stale_source=stale_source_view(units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28", bindings={"run_id": "RUN-0", "plan_id": "PLAN-0", "plan_sha256": "0" * 64}),
        frozen_refs={"expected_sources": ()},
        version_bindings={},
    )
    out_result = axes.rescore_axes_case(out_of_range_view, allow_synthetic_fixture=False)
    check(
        "adapter: target_ref beyond frozen collection -> unknown (fail-closed, not pass)",
        out_result.new_axes["cross_entity"]["state"] == "unknown" and out_result.new_axes["cross_entity"]["reason"] == "targets_unresolved",
        dict(out_result.new_axes["cross_entity"]),
    )

    failures = [item for item in RESULTS if not item["ok"]]
    out = {
        "probe": "14-q1a2-adapter",
        "assertions_total": len(RESULTS),
        "assertions_failed": len(failures),
        "failures": failures,
        "results": RESULTS,
        "verdict": "PASS" if not failures else "FAIL",
    }
    dump(HERE / "14-q1a2-adapter.out.json", out)
    print(json.dumps({"assertions": len(RESULTS), "failed": len(failures), "verdict": out["verdict"]}, ensure_ascii=False))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())


