"""必测 5：fail-closed —— 缺合同/缺轴/缺快照字段/身份不可解析/未知键的固定码与 unknown。

含 3 组：结构化反例矩阵、逐码 unknown->N/A 门、确定性变异模糊测试（无裸异常逃逸）。
"""

from __future__ import annotations

import ast
import copy
import random
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from harness import Checks
import synth

from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter
from mktkb.evaluation.p2_evidence_axes_adapter_v2 import (
    ADAPTED_AXES,
    FIXED_CODES,
    UNKNOWN_CODES,
    AdapterError,
    AxisCounts,
    AxisDetermination,
    determine_axis,
    determine_case,
    load_contract_v2,
    load_snapshot_v03,
    validate_determination,
)

REPO = Path(__file__).resolve().parents[8]
ADAPTER_PATH = REPO / "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py"
FROZEN_REFS = {"expected_sources": [{"record_code": "W01"}]}


def call(fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001
        return {"raised": True, "type": type(exc).__name__, "code": getattr(exc, "code", None), "value": None}
    return {"raised": False, "type": None, "code": None, "value": value}


def contract_code(payload: Mapping[str, Any]) -> str | None:
    result = call(lambda: load_contract_v2(payload))
    return None if not result["raised"] else (result["code"] or f"EXC:{result['type']}")


def snapshot_code(payload: Mapping[str, Any]) -> str | None:
    result = call(lambda: load_snapshot_v03(payload))
    return None if not result["raised"] else (result["code"] or f"EXC:{result['type']}")


def cross_axis(targets: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    return synth.axis(
        "required", "structured_target", "explicit_single_target",
        targets=list(targets or [synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})]),
    )


def stale_axis(*, refs: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    return synth.axis(
        "required", "lifecycle_dates", "published_lifecycle",
        target_refs=list(refs if refs is not None else [synth.ref("expected_sources", 0)]),
    )


def main() -> dict:
    checks = Checks("05-failclosed")
    base_contract = synth.contract({0: synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis())})
    base_snapshot = synth.snapshot([synth.record()])
    matrix: dict[str, Any] = {}

    def contract_check(name: str, mutate: Callable[[dict], None], expected: str) -> None:
        payload = copy.deepcopy(base_contract)
        mutate(payload)
        actual = contract_code(payload)
        matrix[name] = actual
        checks.eq(name, actual, expected)

    def snapshot_check(name: str, mutate: Callable[[dict], None], expected: str) -> None:
        payload = copy.deepcopy(base_snapshot)
        mutate(payload)
        actual = snapshot_code(payload)
        matrix[name] = actual
        checks.eq(name, actual, expected)

    # ---- 合同结构 ---------------------------------------------------------- #
    def drop_axis(payload: dict) -> None:
        payload["cases"][0]["axes"].pop("safety")

    contract_check("missing_axis", drop_axis, "contract_axis_invalid")

    def add_axis(payload: dict) -> None:
        payload["cases"][0]["axes"]["extra"] = synth.default_axes()["safety"]

    contract_check("extra_axis", add_axis, "contract_axis_invalid")

    def drop_axis_field(payload: dict) -> None:
        payload["cases"][0]["axes"]["cross_entity"].pop("temporal_intent")

    contract_check("axis_missing_field", drop_axis_field, "contract_axis_invalid")

    def target_extra_key(payload: dict) -> None:
        payload["cases"][0]["axes"]["cross_entity"]["targets"][0]["basis"] = "x"

    contract_check("target_extra_key", target_extra_key, "contract_target_invalid")

    def bad_basis(payload: dict) -> None:
        payload["cases"][0]["basis"]["cross_entity"] = "not_a_basis"

    contract_check("bad_basis", bad_basis, "contract_basis_invalid")

    def no_provable_with_required(payload: dict) -> None:
        payload["cases"][0]["basis"]["cross_entity"] = "no_provable_basis_keep_unknown"

    contract_check("no_provable_basis_with_required", no_provable_with_required, "contract_basis_invalid")

    def na_with_uncertain(payload: dict) -> None:
        payload["cases"][0]["axes"]["cross_entity"].update(
            {"applicability": "not_applicable", "criterion": "no_entity_claim", "reason": "ambiguous_semantics"}
        )

    contract_check("not_applicable_with_uncertain_reason", na_with_uncertain, "contract_unknown_downgraded")

    def na_wrong_criterion(payload: dict) -> None:
        payload["cases"][0]["axes"]["cross_entity"].update(
            {"applicability": "not_applicable", "criterion": "structured_target", "reason": "no_entity_scope"}
        )

    contract_check("not_applicable_wrong_criterion", na_wrong_criterion, "contract_axis_invalid")

    def cross_user_not_required(payload: dict) -> None:
        payload["cases"][0]["axes"]["cross_user"]["applicability"] = "unknown"

    contract_check("cross_user_not_required", cross_user_not_required, "contract_axis_invalid")

    def shared_background_with_targets(payload: dict) -> None:
        payload["cases"][0]["axes"]["cross_entity"].update(
            {"criterion": "shared_background", "targets": [synth.target("item", "item|a|b")]}
        )

    contract_check("shared_background_with_targets", shared_background_with_targets, "contract_axis_invalid")

    def duplicate_ref(payload: dict) -> None:
        payload["cases"][0]["axes"]["stale_source"]["target_refs"] = [
            synth.ref("expected_sources", 0),
            synth.ref("expected_sources", 0),
        ]

    contract_check("duplicate_target_ref", duplicate_ref, "contract_axis_invalid")

    def bad_ref_collection(payload: dict) -> None:
        payload["cases"][0]["axes"]["stale_source"]["target_refs"] = [synth.ref("bogus", 0)]

    contract_check("bad_ref_collection", bad_ref_collection, "contract_axis_invalid")

    def projection_missing_key(payload: dict) -> None:
        payload["projection"].pop("coverage")

    contract_check("projection_missing_key", projection_missing_key, "contract_projection_invalid")

    def projection_rule_version(payload: dict) -> None:
        payload["projection"]["rule_version"] = "q1a-scope-targets-projection/v1"

    contract_check("projection_rule_version", projection_rule_version, "contract_projection_invalid")

    def projection_bad_provenance(payload: dict) -> None:
        payload["projection"]["target_provenance"]["0|cross_entity"] = [{"target_index": 0}]

    contract_check("projection_bad_provenance_row", projection_bad_provenance, "contract_projection_invalid")

    def projection_forbidden_token(payload: dict) -> None:
        payload["projection"]["target_provenance"]["0|cross_entity"] = [
            {"target_index": 0, "action": "record_code_verified", "source": "derived_from_frozen_label", "basis": "frozen_label_target"}
        ]

    contract_check("projection_forbidden_token", projection_forbidden_token, "contract_projection_invalid")

    def runs_wrong_scenario(payload: dict) -> None:
        payload["runs"][1]["scenario_id"] = synth.SCENARIOS[0]

    contract_check("runs_wrong_scenario", runs_wrong_scenario, "contract_schema_invalid")

    def case_count_wrong(payload: dict) -> None:
        payload["case_count"] = 29

    contract_check("case_count_wrong", case_count_wrong, "contract_schema_invalid")

    def duplicate_case_id(payload: dict) -> None:
        payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]

    contract_check("duplicate_case_id", duplicate_case_id, "contract_schema_invalid")

    def unknown_top_key(payload: dict) -> None:
        payload["extra"] = 1

    contract_check("unknown_top_level_key", unknown_top_key, "contract_schema_invalid")

    def binding_missing(payload: dict) -> None:
        payload["bindings"].pop("cases_sha256")

    contract_check("binding_missing", binding_missing, "contract_binding_mismatch")

    def binding_dataset(payload: dict) -> None:
        payload["bindings"]["dataset_version"] = "P2-HOLDOUT-v1"

    contract_check("binding_dataset_version", binding_dataset, "contract_binding_mismatch")

    def plan_sha_bad(payload: dict) -> None:
        payload["runs"][0]["plan_sha256"] = "not-a-sha"

    contract_check("run_plan_sha_invalid", plan_sha_bad, "contract_schema_invalid")

    # ---- 快照结构 ---------------------------------------------------------- #
    snapshot_check("missing_run_id", lambda p: p["binding"].pop("run_id"), "snapshot_field_missing:binding.run_id")

    def extra_binding_key(payload: dict) -> None:
        payload["binding"]["extra"] = 1

    snapshot_check("unknown_binding_key", extra_binding_key, "snapshot_unknown_field:binding.extra")

    def run_id_type(payload: dict) -> None:
        payload["binding"]["run_id"] = 7

    snapshot_check("run_id_type", run_id_type, "snapshot_field_invalid:binding.run_id")

    def run_mismatch(payload: dict) -> None:
        payload["binding"]["run_id"] = "run-9"

    snap_run = copy.deepcopy(base_snapshot)
    run_mismatch(snap_run)
    checks.eq("run_mismatch", snapshot_code(snap_run), None)
    det = determine_case(contract=base_contract, case_id="C00", snapshot=snap_run)
    matrices_run = det.axes["cross_entity"].reason
    matrix["run_mismatch"] = matrices_run
    checks.eq("run_mismatch", matrices_run, "snapshot_run_binding_mismatch")

    def scenario_mismatch(payload: dict) -> None:
        payload["binding"]["scenario_id"] = synth.SCENARIOS[1]

    snap_scenario = copy.deepcopy(base_snapshot)
    scenario_mismatch(snap_scenario)
    matrix["scenario_mismatch"] = determine_case(
        contract=base_contract, case_id="C00", snapshot=snap_scenario
    ).axes["cross_entity"].reason
    checks.eq("scenario_mismatch", matrix["scenario_mismatch"], "snapshot_scenario_binding_mismatch")

    def turn_mismatch(payload: dict) -> None:
        payload["turn_ref"]["turn_index"] = 5

    snap_turn = copy.deepcopy(base_snapshot)
    turn_mismatch(snap_turn)
    matrix["turn_mismatch"] = determine_case(
        contract=base_contract, case_id="C00", snapshot=snap_turn, expected_turn={"turn_index": 0}
    ).axes["cross_entity"].reason
    checks.eq("turn_mismatch", matrix["turn_mismatch"], "snapshot_turn_binding_mismatch")

    for name, mutate, expected in [
        ("source_evidence_incomplete", lambda p: p["source_evidence"].update({"completeness_status": "incomplete"}), "snapshot_source_evidence_incomplete"),
        ("source_evidence_replayed", lambda p: p["source_evidence"].update({"completeness_status": "replayed"}), "snapshot_source_evidence_replayed"),
        ("public_boundary_false", lambda p: p["public_boundary"].update({"runtime_ids_only_in_declared_blocks": False}), "snapshot_field_invalid:public_boundary.runtime_ids_only_in_declared_blocks"),
        ("content_sha_bad", lambda p: p.update({"content_sha256": "xyz"}), "snapshot_field_invalid:content_sha256"),
        ("contract_version_bad", lambda p: p.update({"contract_version": "p2-hard-evidence-capture-identity/v0.2"}), "snapshot_contract_version_invalid"),
        ("schema_version_bad", lambda p: p.update({"schema_version": "p2-runtime-identity-snapshot/v0.2"}), "snapshot_schema_version_invalid"),
        ("fixture_kind_bad", lambda p: p.update({"fixture_kind": "prod"}), "snapshot_fixture_kind_invalid"),
        ("fixture_binding_mismatch", lambda p: p["binding"].update({"fixture_kind": "live_h2"}), "snapshot_fixture_binding_mismatch"),
    ]:
        snap = copy.deepcopy(base_snapshot)
        mutate(snap)
        actual = determine_case(contract=base_contract, case_id="C00", snapshot=snap).axes["cross_entity"].reason
        matrix[name] = actual
        checks.eq(name, actual, expected)

    def nonrecord_with_record_code(payload: dict) -> None:
        payload["record_identities"][0].update(
            {"record_level": False, "locator_kind": "other", "code": "runtime_unit_not_record_level"}
        )

    snapshot_check("nonrecord_with_record_code", nonrecord_with_record_code, "snapshot_field_invalid:record_identities[0].record_code")

    def record_level_with_page_locator(payload: dict) -> None:
        payload["record_identities"][0].update({"locator_kind": "page"})

    snapshot_check("record_level_with_page_locator", record_level_with_page_locator, "snapshot_field_invalid:record_identities[0].record_level")

    def summary_mismatch(payload: dict) -> None:
        payload["record_identity_summary"]["record_level"] = 0

    snapshot_check("summary_mismatch", summary_mismatch, "snapshot_summary_mismatch")

    def summary_tampered_but_consistent(payload: dict) -> None:
        payload["record_identity_summary"]["total"] = 2

    snapshot_check("summary_total_mismatch", summary_tampered_but_consistent, "snapshot_summary_mismatch")

    def empty_missing_layer(payload: dict) -> None:
        payload["empty_use_scope_input"]["use_layers"].pop("model_evidence")

    snapshot_check("empty_use_missing_layer", empty_missing_layer, "snapshot_field_missing:empty_use_scope_input.use_layers.model_evidence")

    def empty_unknown_layer(payload: dict) -> None:
        payload["empty_use_scope_input"]["use_layers"]["extra"] = {"observed": True, "count": 0, "refs": []}

    snapshot_check("empty_use_unknown_layer", empty_unknown_layer, "snapshot_unknown_field:empty_use_scope_input.use_layers.extra")

    def empty_count_refs_mismatch(payload: dict) -> None:
        payload["empty_use_scope_input"]["use_layers"]["model_evidence"]["count"] = 1

    snapshot_check("empty_use_count_refs_mismatch", empty_count_refs_mismatch, "snapshot_field_invalid:empty_use_scope_input.use_layers.model_evidence.count")

    def empty_code_inconsistent(payload: dict) -> None:
        payload["empty_use_scope_input"]["code"] = "empty_use_input_nonempty"

    snapshot_check("empty_use_code_inconsistent", empty_code_inconsistent, "snapshot_field_invalid:empty_use_scope_input.code")

    def temporal_observed_without_as_of(payload: dict) -> None:
        payload["effective_temporal"]["as_of"] = None

    snapshot_check("temporal_observed_without_as_of", temporal_observed_without_as_of, "snapshot_field_invalid:effective_temporal.as_of")

    def baseline_as_effective(payload: dict) -> None:
        payload["effective_temporal"]["baseline_used_as_effective"] = True

    snapshot_check("baseline_used_as_effective", baseline_as_effective, "snapshot_field_invalid:effective_temporal.baseline_used_as_effective")

    def version_mismatch_equal(payload: dict) -> None:
        payload["effective_temporal"]["document_versions"][0].update({"code": "version_mismatch"})

    snapshot_check("version_mismatch_equal_numbers", version_mismatch_equal, "snapshot_field_invalid:effective_temporal.document_versions[0].code")

    def version_observed_without_runtime(payload: dict) -> None:
        payload["effective_temporal"]["document_versions"][0]["runtime_version_number"] = None

    snapshot_check("version_observed_without_runtime", version_observed_without_runtime, "snapshot_field_invalid:effective_temporal.document_versions[0].runtime_version_number")

    def candidate_count_mismatch(payload: dict) -> None:
        payload["empty_use_scope_input"]["candidate_layers"]["retrieval_observed"]["count"] = 2

    snapshot_check("candidate_count_refs_mismatch", candidate_count_mismatch, "snapshot_field_invalid:empty_use_scope_input.candidate_layers.retrieval_observed.count")

    def owner_not_mapping(payload: dict) -> None:
        payload["request_owner"] = "owner"

    snapshot_check("request_owner_not_mapping", owner_not_mapping, "snapshot_field_invalid:request_owner")

    # ---- 身份不可解析 / 语义 unknown -------------------------------------- #
    def semantic(name: str, axes: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
                 *, empty: Mapping[str, Any] | None = None, frozen: Mapping[str, Any] | None = FROZEN_REFS,
                 temporal_view: Mapping[str, Any] | None = None, expected_axis: str = "cross_entity") -> str:
        payload = synth.contract({0: axes})
        det = determine_case(
            contract=payload,
            case_id="C00",
            snapshot=synth.snapshot(records, empty=empty, temporal_view=temporal_view),
            frozen_refs=frozen,
        )
        reason = det.axes[expected_axis].reason
        state = det.axes[expected_axis].state
        matrix[name] = {"state": state, "reason": reason}
        return reason

    unresolved = synth.record(
        record_level=False, locator_kind="none", code="runtime_unit_unresolved",
        sheet=None, row=None, record_key=None, record_code=None,
        entity_type=None, entity_key=None, entity_filters={}, entity_matchable=False,
        entity_code="entity_identity_unavailable",
    )
    checks.eq("identity_unresolved_code", semantic("identity_unresolved", synth.case_axes(cross_entity=cross_axis()), [unresolved]), "identity_unresolved")

    entity_absent = synth.record(
        entity_type=None, entity_key=None, entity_filters={}, entity_matchable=False,
        entity_code="entity_identity_absent",
    )
    checks.eq("entity_absent_code", semantic("entity_absent", synth.case_axes(cross_entity=cross_axis()), [entity_absent]), "identity_unresolved")

    checks.eq("targets_missing_code", semantic("targets_missing", synth.case_axes(cross_entity=synth.axis("required", "structured_target", "explicit_single_target")), []), "targets_missing")

    checks.eq(
        "stale_no_positive_refs_code",
        semantic("stale_no_positive_refs", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis(refs=[])), [synth.record()], expected_axis="stale_source"),
        "stale_no_positive_refs",
    )
    checks.eq(
        "stale_without_frozen_refs_code",
        semantic("stale_without_frozen_refs", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis()), [synth.record()], frozen=None, expected_axis="stale_source"),
        "stale_source_unresolved",
    )
    checks.eq(
        "stale_ref_index_out_of_range",
        semantic("stale_ref_index_out_of_range", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis(refs=[synth.ref("expected_sources", 5)])), [synth.record()], expected_axis="stale_source"),
        "stale_source_unresolved",
    )
    checks.eq(
        "stale_ref_without_record_code",
        semantic("stale_ref_without_record_code", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis()), [synth.record()], frozen={"expected_sources": [{"sheet": "S", "row": 2}]}, expected_axis="stale_source"),
        "stale_positive_ref_not_record_level",
    )
    checks.eq(
        "stale_records_not_matching",
        semantic("stale_records_not_matching", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis()), [synth.record(record_code="W99", record_key="W99")], expected_axis="stale_source"),
        "stale_source_unresolved",
    )
    checks.eq(
        "stale_date_conflict_is_violation",
        semantic("stale_date_conflict", synth.case_axes(
            cross_entity=cross_axis(),
            stale_source=synth.axis("required", "lifecycle_dates", "published_lifecycle", target_refs=[synth.ref("expected_sources", 0)], as_of="2026-10-27"),
        ), [synth.record()], expected_axis="stale_source"),
        "date_intent_conflict",
    )
    checks.eq(
        "stale_version_mismatch_code",
        semantic("stale_version_mismatch", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis()), [synth.record()], temporal_view=synth.temporal(version_code="version_mismatch", runtime_version=2, product_version=3), expected_axis="stale_source"),
        "version_mismatch",
    )
    checks.eq(
        "stale_as_of_missing_code",
        semantic("stale_as_of_missing", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis()), [synth.record()], temporal_view=synth.temporal(availability="partial", as_of=None, code="effective_temporal_partial"), expected_axis="stale_source"),
        "as_of_missing",
    )
    checks.eq(
        "stale_lifecycle_gap_code",
        semantic("stale_lifecycle_gap", synth.case_axes(cross_entity=cross_axis(), stale_source=stale_axis()), [synth.record()], expected_axis="stale_source"),
        "stale_lifecycle_evidence_missing",
    )
    checks.eq(
        "multi_target_lt2_code",
        semantic("multi_target_lt2", synth.case_axes(cross_entity=synth.axis(
            "required", "multi_target", "explicit_multi_target",
            targets=[synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})],
        )), [synth.record()]),
        "multi_target_lt2",
    )
    checks.eq(
        "annotation_unknown_code",
        semantic("annotation_unknown", synth.case_axes(cross_entity=synth.axis("unknown", "unknown", "insufficient_annotation", as_of=None, temporal_intent="unknown", basis="no_provable_basis_keep_unknown")), [synth.record()]),
        "annotation_unknown",
    )

    # ---- unknown -> N/A 门 ------------------------------------------------- #
    unknown_to_na: list[str] = []
    for code in sorted(UNKNOWN_CODES):
        determination = AxisDetermination(axis="cross_entity", case_id="C00", state="not_applicable", reason=code)
        result = call(lambda: validate_determination(determination, applicability="not_applicable", criterion="no_entity_claim"))
        if result["raised"] and result["code"] == "unknown_to_not_applicable_forbidden":
            continue
        unknown_to_na.append(f"{code}->{result['code'] or 'ACCEPTED'}")
    checks.eq("unknown_to_not_applicable_forbidden_for_all_unknown_codes", unknown_to_na, [])

    checks.eq(
        "declared_na_is_allowed",
        call(lambda: validate_determination(
            AxisDetermination(axis="cross_entity", case_id="C00", state="not_applicable", reason="no_entity_scope_verified"),
            applicability="not_applicable", criterion="no_entity_claim",
        ))["raised"],
        False,
    )
    checks.eq(
        "na_without_no_entity_claim_is_forbidden",
        call(lambda: validate_determination(
            AxisDetermination(axis="cross_entity", case_id="C00", state="not_applicable", reason="no_entity_scope_verified"),
            applicability="required", criterion="structured_target",
        ))["code"],
        "unknown_to_not_applicable_forbidden",
    )
    checks.eq(
        "passed_with_unknown_reason_forbidden",
        call(lambda: validate_determination(AxisDetermination(axis="cross_entity", case_id="C00", state="passed", reason="identity_unresolved")))["code"],
        "adapter_invariant_violation",
    )
    checks.eq(
        "violation_with_unknown_reason_forbidden",
        call(lambda: validate_determination(AxisDetermination(axis="cross_entity", case_id="C00", state="violation", reason="identity_unresolved")))["code"],
        "adapter_invariant_violation",
    )
    checks.eq(
        "adapter_error_rejects_non_fixed_code",
        str(call(lambda: AdapterError("not_a_fixed_code"))["code"]).split(":", 1)[0],
        "adapter_invariant_violation",
    )
    checks.eq(
        "axis_counts_inconsistent",
        call(lambda: AxisCounts(axis="cross_entity", planned=3, checked=3, passed=1, not_applicable=0, unknown=1, violations=1).verify())["code"],
        "axis_counts_inconsistent",
    )
    checks.eq(
        "delegated_axis_code",
        call(lambda: determine_axis("safety", None, None, None))["code"],
        "axis_delegated_to_q1a1b",
    )
    checks.eq(
        "unknown_axis_code",
        call(lambda: determine_axis("bogus", None, None, None))["code"],
        "axis_not_adapted",
    )

    # ---- 非字符串 case_id（调用方误用） ----------------------------------- #
    bad_case = call(lambda: determine_case(contract=base_contract, case_id=None, snapshot=base_snapshot))
    matrix["non_str_case_id"] = bad_case
    checks.record(
        "non_str_case_id_fails_with_fixed_code_not_bare_exception",
        (bad_case["raised"] and bad_case["code"] == "adapter_invariant_violation") or (not bad_case["raised"]),
        bad_case,
    )
    checks.eq(
        "unknown_case_id_code",
        determine_case(contract=base_contract, case_id="C99", snapshot=base_snapshot).axes["cross_entity"].reason,
        "contract_case_missing",
    )

    # ---- 静态：getattr 默认值 / 裸 except / pass --------------------------- #
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    getattr_calls = [ast.get_source_segment(source, node) for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"getattr", "hasattr"}]
    bare_except = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.type is None]
    pass_nodes = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Pass)]
    dict_get_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if len(node.args) >= 2:
                dict_get_calls.append({"line": node.lineno, "text": ast.get_source_segment(source, node) or ""})
    checks.eq("no_getattr_or_hasattr", getattr_calls, [])
    checks.eq("no_bare_except", bare_except, [])
    checks.eq("no_pass_statements", pass_nodes, [])
    checks.record(
        "dict_get_with_default_sites_are_non_verdict",
        True,
        dict_get_calls,
    )

    # ---- 非标量枚举值：hashable 之外是否仍 fail-closed ------------------------- #
    def nest(obj: Any, dotted: str, value: Any) -> None:
        parts: list[Any] = []
        for token in dotted.split("."):
            parts.append(int(token) if token.isdigit() else token)
        cursor = obj
        for token in parts[:-1]:
            cursor = cursor[token] if isinstance(cursor, dict) else cursor[int(token)]
        cursor[parts[-1]] = value

    contract_sites = [
        ("cases.0.axes.cross_entity.criterion", []),
        ("cases.0.axes.cross_entity.reason", {}),
        ("cases.0.basis.cross_entity", []),
    ]
    snapshot_sites = [
        ("effective_temporal.availability", []),
        ("effective_temporal.as_of_source", {}),
        ("effective_temporal.observed_from", []),
        ("effective_temporal.code", {}),
        ("effective_temporal.document_versions.0.code", []),
        ("empty_use_scope_input.code", []),
        ("empty_use_scope_input.turn_status", {}),
        ("source_evidence.completeness_status", []),
    ]
    contract_crash: list[dict[str, Any]] = []
    for dotted, value in contract_sites:
        payload = copy.deepcopy(base_contract)
        nest(payload, dotted, value)
        result = call(lambda: determine_case(contract=payload, case_id="C00", snapshot=base_snapshot))
        contract_crash.append(
            {"path": dotted, "value_type": type(value).__name__, "raised": result["raised"],
             "type": result["type"], "code": result["code"]}
        )
    snapshot_crash: list[dict[str, Any]] = []
    for dotted, value in snapshot_sites:
        payload = copy.deepcopy(base_snapshot)
        nest(payload, dotted, value)
        result = call(lambda: determine_case(contract=base_contract, case_id="C00", snapshot=payload))
        snapshot_crash.append(
            {"path": dotted, "value_type": type(value).__name__, "raised": result["raised"],
             "type": result["type"], "code": result["code"]}
        )
    contract_unfixed = [row for row in contract_crash if row["raised"] and not row["code"]]
    snapshot_unfixed = [row for row in snapshot_crash if row["raised"] and not row["code"]]
    checks.eq("contract_non_scalar_enum_fail_closed", contract_unfixed, [])
    checks.eq("snapshot_non_scalar_enum_fail_closed", snapshot_unfixed, [])
    # 对照：hashable 的错误枚举值应给固定码
    control_contract = copy.deepcopy(base_contract)
    control_contract["cases"][0]["axes"]["cross_entity"]["criterion"] = "bogus"
    checks.eq("scalar_bad_criterion_is_fixed_code", contract_code(control_contract), "contract_axis_invalid")
    control_snapshot = copy.deepcopy(base_snapshot)
    control_snapshot["effective_temporal"]["availability"] = "bogus"
    checks.eq("scalar_bad_availability_is_fixed_code", snapshot_code(control_snapshot), "snapshot_enum_invalid")

    # ---- 确定性变异模糊测试：不得有裸异常逃逸 ----------------------------- #
    rng = random.Random(20261114)
    pool = [None, 0, 1, -1, "", "x", [], {}, True, False, 1.5, ["x"], {"a": 1}, "item|a|b"]

    def paths(obj: Any, prefix: tuple = ()) -> list[list[Any]]:
        found: list[list[Any]] = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                found.append(list(prefix) + [key])
                found.extend(paths(value, prefix + (key,)))
        elif isinstance(obj, list) and obj:
            found.append(list(prefix) + [0])
            found.extend(paths(obj[0], prefix + (0,)))
        return found

    def set_path(obj: Any, path: list[Any], value: Any) -> None:
        cursor = obj
        for key in path[:-1]:
            cursor = cursor[key] if isinstance(cursor, dict) else cursor[int(key)]
        last = path[-1]
        if isinstance(cursor, list):
            index = int(last)
            if index < len(cursor):
                cursor[index] = value
        else:
            cursor[last] = value

    def delete_path(obj: Any, path: list[Any]) -> None:
        cursor = obj
        for key in path[:-1]:
            cursor = cursor[key] if isinstance(cursor, dict) else cursor[int(key)]
        last = path[-1]
        if isinstance(cursor, dict):
            cursor.pop(last, None)
        elif isinstance(cursor, list) and int(last) < len(cursor):
            cursor.pop(int(last))

    fuzz = {"contract": {"runs": 0, "raised_unfixed": 0, "accepted": 0, "rejected": 0, "bad_reason": [], "na_violations": []},
            "snapshot": {"runs": 0, "raised_unfixed": 0, "accepted": 0, "rejected": 0, "bad_reason": [], "na_violations": []}}

    def reason_ok(reason: str) -> bool:
        return reason.split(":", 1)[0] in FIXED_CODES

    for label, base in (("contract", base_contract), ("snapshot", base_snapshot)):
        all_paths = paths(base)
        for _ in range(400):
            payload = copy.deepcopy(base)
            path = rng.choice(all_paths)
            decision = rng.random()
            if decision < 0.4:
                set_path(payload, path, rng.choice(pool))
            elif decision < 0.8:
                delete_path(payload, path)
            else:
                set_path(payload, path, copy.deepcopy(rng.choice(pool)))
            if label == "contract":
                result = call(lambda: determine_case(contract=payload, case_id="C00", snapshot=base_snapshot, frozen_refs=FROZEN_REFS))
            else:
                result = call(lambda: determine_case(contract=base_contract, case_id="C00", snapshot=payload, frozen_refs=FROZEN_REFS))
            fuzz[label]["runs"] += 1
            if result["raised"]:
                fuzz[label]["raised_unfixed"] += 1
                fuzz[label].setdefault("raised_examples", []).append({"path": path, "code": result["code"], "type": result["type"]})
                continue
            determination = result["value"]
            for axis in ADAPTED_AXES:
                row = determination.axes[axis]
                if not reason_ok(row.reason):
                    fuzz[label]["bad_reason"].append({"path": path, "axis": axis, "reason": row.reason})
                if row.state == "not_applicable" and not (
                    axis == "cross_entity"
                    and row.reason == "no_entity_scope_verified"
                    and determination.case_id == "C00"
                ):
                    fuzz[label]["na_violations"].append({"path": path, "axis": axis, "reason": row.reason})
            heads = {determination.axes[axis].reason.split(":", 1)[0] for axis in ADAPTED_AXES}
            counter = fuzz[label].setdefault("reason_heads", {})
            for head in heads:
                counter[head] = counter.get(head, 0) + 1
            intake = any(
                head.startswith("contract_")
                or head.startswith("snapshot_")
                or head in {
                    "identity_unresolved",
                    "targets_missing",
                    "targets_unresolved",
                    "multi_target_lt2",
                    "entity_scope_conflict",
                    "entity_key_space_incompatible",
                    "target_granularity_incomparable",
                    "empty_set_not_proven",
                    "annotation_unknown",
                }
                for head in heads
            )
            if intake:
                fuzz[label]["rejected"] += 1
            else:
                fuzz[label]["accepted"] += 1
                fuzz[label].setdefault("accepted_examples", []).append(
                    {"path": path, "states": {axis: determination.axes[axis].state for axis in ADAPTED_AXES}}
                )

    for label in ("contract", "snapshot"):
        checks.eq(f"fuzz_{label}_no_unfixed_exception", fuzz[label]["raised_unfixed"], 0, fuzz[label].get("raised_examples"))
        checks.eq(f"fuzz_{label}_all_reasons_are_fixed_codes", fuzz[label]["bad_reason"], [])
        checks.eq(f"fuzz_{label}_no_unknown_to_na", fuzz[label]["na_violations"], [])
        checks.record(
            f"fuzz_{label}_both_outcomes_exercised",
            fuzz[label]["accepted"] > 0 and fuzz[label]["rejected"] > 0,
            {"accepted": fuzz[label]["accepted"], "rejected": fuzz[label]["rejected"]},
        )

    return checks.write(
        {
            "matrix": matrix,
            "fuzz": fuzz,
            "dict_get_calls": dict_get_calls,
            "non_scalar_enum_sites": {"contract": contract_crash, "snapshot": snapshot_crash},
        }
    )


if __name__ == "__main__":
    main()
