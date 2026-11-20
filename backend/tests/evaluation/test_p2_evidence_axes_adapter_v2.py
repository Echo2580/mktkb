"""C1-P4：消费侧适配 v2（合同 v2 + 快照 v0.3）——合成 + Mock，零真实调用。

覆盖：
- 正例：合成 v2 合同（30 题/4 runs/17 bindings/projection）+ 合成 v0.3 快照 →
  ``cross_entity`` / ``stale_source`` 逐题判定；两轴计数按三条公式自洽。
- 反例（每条都断言**固定码**，不只断言“抛异常”）：
  v1 合同被 v2 适配器收下 / v2 合同被 v1 常量收下 / document 级目标企图判 violation /
  class C 企图 proven / 快照字段缺失 / 跨 run 快照 / 未知键 / 身份不可解析 /
  unknown→N/A 企图 / shared_background 企图 pass / 版本不一致 / as_of 缺失。
- 边界：``basis`` 只进 provenance；输出不含 ``verified`` / ``threshold`` / ``release``；
  ``safety`` / ``cross_user`` 明确交回既有路径；全程零出网（netguard 逐用例断言）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter  # noqa: E402
from mktkb.evaluation.p2_evidence_rescore_axes import (  # noqa: E402
    Q1A2_BINDING_KEYS,
    Q1A2_CONTRACT_SCHEMA_VERSION,
    TARGET_REF_COLLECTIONS,
    RescoreError,
    load_q1a2_contract_view,
)
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    CANDIDATE_LAYER_NAMES,
    CONTRACT_VERSION,
    ENTITY_ROLE_NAMES,
    MATCHABLE_ENTITY_TYPES,
    SNAPSHOT_SCHEMA_VERSION,
    USE_LAYER_NAMES,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

SCENARIOS = (
    "base_b0",
    "base_b0_plus_v01",
    "pre_v05_without_v07",
    "post_v05_without_v01",
)
AXES = ("safety", "cross_user", "cross_entity", "stale_source")
V1_SHA = adapter.KNOWN_CONTRACT_SCHEMA_SHA256[Q1A2_CONTRACT_SCHEMA_VERSION]
V2_SHA = adapter.KNOWN_CONTRACT_SCHEMA_SHA256[adapter.CONTRACT_SCHEMA_VERSION_V2]
DOC_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _axis(
    *,
    applicability: str = "required",
    criterion: str,
    reason: str,
    targets: list[dict[str, Any]] | None = None,
    target_refs: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
    temporal_intent: str = "current",
) -> dict[str, Any]:
    return {
        "applicability": applicability,
        "criterion": criterion,
        "reason": reason,
        "target_refs": list(target_refs or ()),
        "targets": list(targets or ()),
        "as_of": as_of,
        "temporal_intent": temporal_intent,
    }


def _target(
    entity_type: str = "item",
    entity_key: str = "item|storea|itema",
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_key": entity_key,
        "filters": dict(filters if filters is not None else {"store": "StoreA", "item": "ItemA"}),
    }


def _ref(collection: str = "expected_sources", index: int = 0) -> dict[str, Any]:
    return {"collection": collection, "index": index}


def _runs() -> list[dict[str, Any]]:
    return [
        {
            "run_index": index,
            "scenario_id": scenario,
            "run_id": f"run-{index}",
            "plan_id": f"plan-{index}",
            "plan_sha256": _sha(f"plan-{index}"),
        }
        for index, scenario in enumerate(SCENARIOS)
    ]


def _bindings(schema_sha: str = V2_SHA) -> dict[str, str]:
    values = {key: _sha("binding:" + key) for key in Q1A2_BINDING_KEYS}
    values["dataset_version"] = "P2-HOLDOUT-v2"
    values["label_version"] = "p2-holdout-v2-2026-11-10"
    values["contract_schema_sha256"] = schema_sha
    return values


def _projection() -> dict[str, Any]:
    return {
        "rule_version": adapter.PROJECTION_RULE_VERSION_V2,
        "lineage": {
            "v1_ciphertext_sha256": _sha("v1-cipher"),
            "v1_schema_sha256": _sha("v1-schema"),
            "v1_aggregate_sha256": _sha("v1-aggregate"),
            "v1_report_sha256": _sha("v1-report"),
        },
        "corpus_bindings": {
            "fixtures_manifest_sha256": _sha("manifest"),
            "source_map_sha256": _sha("source-map"),
            "ingest_plan_sha256": _sha("ingest"),
            "scenario_contract_sha256": _sha("scenario"),
            "chunking_rule_source_sha256": _sha("chunking"),
            "tokenize_rule_source_sha256": _sha("tokenize"),
            "record_count": 0,
            "table_document_count": 0,
            "variant_count": 0,
            "ingest_source_count": 0,
        },
        "entity_rule": {
            "product_entity_types": ["product", "item", "store", "record", "document"],
            "matchable_entity_types": ["item", "store", "record"],
            "identity_function": "mktkb.rag.chunking._entity",
            "normalization_function": "mktkb.rag.chunking.normalize_field",
            "identity_form_version": "product-entity-projection/v1",
        },
        "record_identities": [],
        "target_provenance": {},
        "axis_codes": {},
        "shared_background_corpus": {},
        "coverage": {},
    }


def _default_case(index: int) -> dict[str, Any]:
    return {
        "case_id": f"C{index + 1:02d}",
        "case_index": index,
        "scenario_id": SCENARIOS[index % len(SCENARIOS)],
        "axes": {
            "safety": _axis(
                criterion="benign_business",
                reason="benign_business",
                temporal_intent="not_applicable",
            ),
            "cross_user": _axis(
                criterion="owner_context",
                reason="all_user_contexts",
                temporal_intent="not_applicable",
            ),
            "cross_entity": _axis(
                applicability="not_applicable",
                criterion="no_entity_claim",
                reason="no_entity_scope",
                temporal_intent="not_applicable",
            ),
            "stale_source": _axis(
                criterion="lifecycle_dates",
                reason="published_lifecycle",
            ),
        },
        "basis": {axis: "frozen_label_target" for axis in AXES},
    }


def build_contract(
    *,
    overrides: dict[int, dict[str, Any]] | None = None,
    schema_version: str = adapter.CONTRACT_SCHEMA_VERSION_V2,
    bindings: dict[str, str] | None = None,
    projection: dict[str, Any] | None = None,
    case_count: int = 30,
) -> dict[str, Any]:
    """合成合同 v2：30 题 / 4 runs / 17 bindings / projection。"""
    cases = []
    for index in range(30):
        case = _default_case(index)
        if overrides and index in overrides:
            spec = overrides[index]
            case["axes"].update(copy.deepcopy(spec.get("axes", {})))
            case["basis"].update(spec.get("basis", {}))
            for key in ("case_id", "scenario_id"):
                if key in spec:
                    case[key] = spec[key]
        cases.append(case)
    return {
        "schema_version": schema_version,
        "bindings": _bindings() if bindings is None else bindings,
        "runs": _runs(),
        "case_count": case_count,
        "cases": cases,
        "projection": _projection() if projection is None else projection,
    }


# --------------------------------------------------------------------------- #
# 合成快照 v0.3
# --------------------------------------------------------------------------- #


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(records),
        "record_level": sum(1 for row in records if row["record_level"] is True),
        "not_record_level": sum(1 for row in records if row["record_level"] is not True),
        "doc_code_unresolved": sum(1 for row in records if row["code"] == "runtime_doc_code_unresolved"),
        "entity_matchable": sum(1 for row in records if row["entity_matchable"] is True),
        "entity_document_level": sum(1 for row in records if row["entity_type"] == "document"),
        "unresolved_units": sum(1 for row in records if row["code"] == "runtime_unit_unresolved"),
        "doc_codes": sorted(
            {row["base_doc_code"] for row in records if row["base_doc_code"] is not None}
        ),
    }


def make_record(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "source_ref": "unit-1",
        "layers": ["model_evidence"],
        "unit_kind": "table_row",
        "locator_kind": "record",
        "doc_code": "D01",
        "base_doc_code": "D01",
        "sheet": "物品位置",
        "row": 8,
        "record_key": "P01",
        "record_code": "P01",
        "business_version": "V2",
        "version_number": 1,
        "record_level": True,
        "entity_type": "item",
        # 运行期 id 型键（P3 验收实测与合同侧名称型键不同构）；
        # 匹配只得走角色值复算的 canonical 对齐，见适配器 key-space 规则。
        "entity_key": "item|id:P01",
        "entity_filters": {"store": "StoreA", "item": "ItemA", "item_id": "P01"},
        "entity_matchable": True,
        "code": "record_row_reverse_lookup",
        "entity_code": "entity_identity_matchable_nonrole_filters",
    }
    values.update(overrides)
    if "entity_matchable" not in overrides:
        entity_type = values["entity_type"]
        entity_key = values["entity_key"]
        values["entity_matchable"] = (
            isinstance(entity_type, str)
            and entity_type in MATCHABLE_ENTITY_TYPES
            and isinstance(entity_key, str)
            and bool(entity_key)
        )
    if "entity_code" not in overrides:
        entity_type = values["entity_type"]
        if entity_type is None:
            values["entity_code"] = "entity_identity_absent"
        elif entity_type == "document":
            values["entity_code"] = "entity_identity_document_level"
        elif not values["entity_matchable"]:
            values["entity_code"] = "entity_identity_nonmatchable"
        elif all(key in ENTITY_ROLE_NAMES for key in values["entity_filters"]):
            values["entity_code"] = "entity_identity_matchable"
        else:
            values["entity_code"] = "entity_identity_matchable_nonrole_filters"
    return values


def make_document_record(**overrides: Any) -> dict[str, Any]:
    values = {
        "source_ref": "unit-doc",
        "layers": ["model_evidence"],
        "unit_kind": "paragraph",
        "locator_kind": "page",
        "doc_code": "D04",
        "base_doc_code": "D04",
        "sheet": None,
        "row": None,
        "record_key": None,
        "record_code": None,
        "business_version": "V2",
        "version_number": 1,
        "record_level": False,
        "entity_type": "document",
        "entity_key": "document|" + DOC_UUID,
        "entity_filters": {},
        "entity_matchable": False,
        "code": "runtime_unit_not_record_level",
        "entity_code": "entity_identity_document_level",
    }
    values.update(overrides)
    return values


def make_unresolved_record(**overrides: Any) -> dict[str, Any]:
    values = {
        "source_ref": "unit-missing",
        "layers": ["model_evidence"],
        "unit_kind": "unresolved",
        "locator_kind": "unavailable",
        "doc_code": None,
        "base_doc_code": None,
        "sheet": None,
        "row": None,
        "record_key": None,
        "record_code": None,
        "business_version": None,
        "version_number": None,
        "record_level": False,
        "entity_type": None,
        "entity_key": None,
        "entity_filters": {},
        "entity_matchable": False,
        "code": "runtime_unit_unresolved",
        "entity_code": "entity_identity_unavailable",
    }
    values.update(overrides)
    return values


def make_version(
    source_ref: str = "unit-1",
    *,
    runtime: int | None = 1,
    product: int | None = 1,
    code: str | None = None,
) -> dict[str, Any]:
    if code is None:
        code = "version_observed" if runtime is not None else "version_unresolved"
    return {
        "source_ref": source_ref,
        "doc_code": "D01",
        "version_label": "V2",
        "runtime_version_number": runtime,
        "product_version_number": product,
        "code": code,
    }


def make_temporal(
    *,
    availability: str = "observed",
    as_of: str | None = "2026-10-28",
    as_of_source: str = "plan_observed",
    versions: list[dict[str, Any]] | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    if availability == "not_observed":
        as_of = None
        as_of_source = "unavailable"
    if code is None:
        code = {
            "observed": "effective_temporal_observed",
            "partial": "effective_temporal_partial",
            "not_observed": "effective_temporal_not_observed",
        }[availability]
    return {
        "availability": availability,
        "reason": None if availability != "not_observed" else "as_of_unobserved",
        "as_of": as_of,
        "as_of_source": as_of_source,
        "observed_from": "db_projection_units",
        "include_future": False,
        "enumerate": False,
        "document_versions": list(versions or []),
        "declared_baseline_business_date": "2026-10-28",
        "baseline_used_as_effective": False,
        "code": code,
    }


def make_empty_use(
    *,
    counts: dict[str, int] | None = None,
    unobserved: tuple[str, ...] = (),
    retrieval_observed: bool = True,
    retrieval_count: int = 0,
    retrieval_refs: tuple[str, ...] = (),
    truncated: bool = False,
    turn_status: str = "complete",
    code: str | None = None,
) -> dict[str, Any]:
    counts = dict(counts or {})
    use_layers: dict[str, Any] = {}
    total = 0
    observed_flags: list[bool] = []
    for name in USE_LAYER_NAMES:
        count = int(counts.get(name, 0))
        observed = name not in unobserved
        refs = [] if name == "direct_rag_fact_count" else [f"unit-{index}" for index in range(count)]
        use_layers[name] = {"observed": observed, "count": count, "refs": refs}
        observed_flags.append(observed)
        total += count
    all_observed = all(observed_flags)
    empty_candidate = all_observed and total == 0
    if code is None:
        if turn_status in ("partial", "unavailable"):
            code = "empty_use_input_turn_partial"
        elif empty_candidate:
            code = "empty_use_input_complete_empty"
        elif total > 0:
            code = "empty_use_input_nonempty"
        else:
            code = "empty_use_input_layers_not_observed"
    candidate_layers: dict[str, Any] = {}
    for name in CANDIDATE_LAYER_NAMES:
        if name == "retrieval_observed":
            candidate_layers[name] = {
                "observed": retrieval_observed,
                "count": retrieval_count,
                "refs": list(retrieval_refs),
                "truncated": truncated,
            }
        else:
            candidate_layers[name] = {
                "observed": False,
                "count": 0,
                "refs": [],
                "truncated": False,
            }
    return {
        "input_version": "c1p2-empty-use-scope-input/v0.1",
        "turn_status": turn_status,
        "reason": None,
        "plan": {
            "availability": True,
            "path": "rag",
            "mode": "structured",
            "as_of": "2026-10-28",
            "include_future": False,
            "clarification": False,
        },
        "use_layers": use_layers,
        "candidate_layers": candidate_layers,
        "all_use_layers_observed": all_observed,
        "empty_set_candidate": empty_candidate,
        "code": code,
    }


def make_snapshot(
    *,
    run_id: str = "run-0",
    scenario_id: str = "base_b0",
    records: list[dict[str, Any]] | None = None,
    temporal: dict[str, Any] | None = None,
    empty_use: dict[str, Any] | None = None,
    completeness: str = "complete",
    fixture_kind: str = "local_mock",
) -> dict[str, Any]:
    rows = list(records or [])
    return {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "fixture_kind": fixture_kind,
        "captured_utc": "2026-11-14T12:00:00+00:00",
        "source_evidence": {
            "sha256": _sha("evidence"),
            "schema_version": "p2-hard-evidence-capture/v0.3",
            "fixture_kind": fixture_kind,
            "completeness_status": completeness,
        },
        "binding": {
            "run_id": run_id,
            "plan_sha256": _sha("plan"),
            "scenario_id": scenario_id,
            "fixture_kind": fixture_kind,
            "bindings_sha256": _sha("bindings"),
            "run_binding_sha256": None,
            "business_date_declared": None,
        },
        "turn_ref": {
            "turn_index": 0,
            "client_request_id": "req-1",
            "conversation_id": "conv-1",
            "question_sha256": _sha("question"),
            "pre_revision": None,
            "post_revision": None,
            "capture_revision": None,
            "response_kind": "answer",
            "http_status": 200,
            "timed_out": False,
        },
        "request_owner": {
            "availability": "observed",
            "reason": None,
            "user_ref": "user-1",
            "conversation_ref": "conv-1",
            "owner_source": "turn_authenticated_user_id",
            "auth_material_collected": False,
        },
        "record_identities": rows,
        "record_identity_summary": _summary(rows),
        "effective_temporal": make_temporal(versions=[make_version()])
        if temporal is None
        else temporal,
        "empty_use_scope_input": make_empty_use(
            counts={"model_evidence": 1}, retrieval_count=1, retrieval_refs=("unit-1",)
        )
        if empty_use is None
        else empty_use,
        "runtime_identity": {
            "declared": True,
            "unit_ids": sorted(row["source_ref"] for row in rows),
            "unresolved_unit_ids": [],
            "document_ids": [],
            "version_ids": [],
            "counts": {
                "units": len(rows),
                "unresolved": 0,
                "documents": 0,
                "versions": 0,
            },
        },
        "public_boundary": {
            "public_summary_sha256": _sha("public-summary"),
            "public_summary_keys": ["schema_version"],
            "runtime_ids_only_in_declared_blocks": True,
        },
        "content_sha256": _sha("content"),
    }


def _case_snapshot(index: int, **kwargs: Any) -> dict[str, Any]:
    return make_snapshot(
        run_id=f"run-{index}",
        scenario_id=SCENARIOS[index % len(SCENARIOS)],
        **kwargs,
    )


def _entity_axis(
    *,
    targets: list[dict[str, Any]],
    criterion: str = "structured_target",
    reason: str = "explicit_single_target",
    applicability: str = "required",
) -> dict[str, Any]:
    return _axis(
        applicability=applicability,
        criterion=criterion,
        reason=reason,
        targets=targets,
    )


def _stale_axis(*, as_of: str | None = "2026-10-28", refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _axis(
        criterion="lifecycle_dates",
        reason="published_lifecycle",
        target_refs=refs if refs is not None else [_ref()],
        as_of=as_of,
    )


FROZEN_REFS = {"expected_sources": [{"doc_code": "D01", "record_code": "P01"}]}


def _plain_code(exc_info: pytest.ExceptionInfo[adapter.AdapterError]) -> str:
    return exc_info.value.code


# --------------------------------------------------------------------------- #
# 正例
# --------------------------------------------------------------------------- #


def test_positive_two_axes_and_counts_are_self_consistent():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(as_of="2026-10-28"),
                }
            },
            1: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(as_of="2026-10-27"),
                }
            },
            2: {
                "axes": {
                    "cross_entity": _entity_axis(
                        targets=[
                            _target(
                                "document",
                                "document|" + DOC_UUID,
                                {},
                            )
                        ]
                    ),
                    "stale_source": _stale_axis(as_of="2026-10-28"),
                }
            },
        }
    )
    snapshots = [
        _case_snapshot(0, records=[make_record()]),
        _case_snapshot(
            1,
            records=[
                make_record(
                    entity_key="item|storeb|itemb",
                    entity_filters={"store": "StoreB", "item": "ItemB"},
                )
            ],
        ),
        _case_snapshot(2, empty_use=make_empty_use(retrieval_observed=False)),
    ]

    determinations = [
        adapter.determine_case(
            contract=contract,
            case_id=f"C{index + 1:02d}",
            snapshot=snapshot,
            frozen_refs=FROZEN_REFS,
        )
        for index, snapshot in enumerate(snapshots)
    ]

    first = determinations[0].axes
    assert first["cross_entity"].state == "passed"
    assert first["cross_entity"].reason == "cross_entity_targets_match_ok"
    assert first["stale_source"].state == "unknown"
    assert first["stale_source"].reason == "stale_lifecycle_evidence_missing"

    second = determinations[1].axes
    assert second["cross_entity"].state == "violation"
    assert second["cross_entity"].reason == "other_entity_used"
    assert second["stale_source"].state == "violation"
    assert second["stale_source"].reason == "date_intent_conflict"

    third = determinations[2].axes
    assert third["cross_entity"].state == "unknown"
    assert third["cross_entity"].reason == "target_granularity_incomparable"
    assert third["stale_source"].state == "unknown"
    assert third["stale_source"].reason == "empty_set_not_proven"

    cross = adapter.aggregate_axis(determinations, "cross_entity")
    stale = adapter.aggregate_axis(determinations, "stale_source")
    assert cross.as_dict() == {
        "axis": "cross_entity",
        "planned": 3,
        "checked": 2,
        "passed": 1,
        "not_applicable": 0,
        "unknown": 1,
        "violations": 1,
        "formulas": {
            "planned_eq_passed_na_unknown_violations": True,
            "checked_eq_passed_na_violations": True,
            "planned_eq_checked_unknown": True,
        },
    }
    assert stale.as_dict() == {
        "axis": "stale_source",
        "planned": 3,
        "checked": 1,
        "passed": 0,
        "not_applicable": 0,
        "unknown": 2,
        "violations": 1,
        "formulas": {
            "planned_eq_passed_na_unknown_violations": True,
            "checked_eq_passed_na_violations": True,
            "planned_eq_checked_unknown": True,
        },
    }
    # 三条公式由 verify() 强制执行；这里再正向断言一次。
    assert cross.planned == cross.passed + cross.not_applicable + cross.unknown + cross.violations
    assert cross.checked == cross.passed + cross.not_applicable + cross.violations
    assert cross.planned == cross.checked + cross.unknown


def test_positive_not_applicable_only_from_declared_no_entity_claim():
    contract = build_contract()
    snapshot = _case_snapshot(
        0,
        records=[],
        empty_use=make_empty_use(),  # 全层观测 + 检索观测为空 → 真正空集
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot
    ).axes["cross_entity"]
    assert determination.state == "not_applicable"
    assert determination.reason == "no_entity_scope_verified"


def test_basis_only_enters_provenance_and_never_folds_into_verdict():
    targets = [_target()]
    contract_a = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=targets),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    contract_b = copy.deepcopy(contract_a)
    contract_b["cases"][0]["basis"]["cross_entity"] = "public_corpus_structure"
    contract_b["cases"][0]["basis"]["stale_source"] = "case_business_date_baseline"
    snapshot = _case_snapshot(0, records=[make_record()], empty_use=make_empty_use())

    det_a = adapter.determine_case(
        contract=contract_a, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    )
    det_b = adapter.determine_case(
        contract=contract_b, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    )
    for axis in adapter.ADAPTED_AXES:
        assert det_a.axes[axis].state == det_b.axes[axis].state
        assert det_a.axes[axis].reason == det_b.axes[axis].reason
    assert det_a.axes["cross_entity"].provenance["basis"] == "frozen_label_target"
    assert det_b.axes["cross_entity"].provenance["basis"] == "public_corpus_structure"
    assert "basis" not in det_a.axes["cross_entity"].reason


def test_v2_targets_matchable_requires_product_vocabulary_and_role_filters():
    legacy_only = _entity_axis(
        targets=[_target(filters={"store": "StoreA", "item_id": "P01"})]
    )
    legacy_plus_canonical = _entity_axis(
        targets=[
            _target(filters={"store": "StoreA", "item_id": "P01"}),
            _target(),
        ]
    )
    snapshot = _case_snapshot(0, records=[make_record()])

    contract = build_contract(
        overrides={0: {"axes": {"cross_entity": legacy_only, "stale_source": _stale_axis()}}}
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "targets_unresolved"

    contract = build_contract(
        overrides={
            0: {"axes": {"cross_entity": legacy_plus_canonical, "stale_source": _stale_axis()}}
        }
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert determination.state == "passed"
    assert determination.reason == "cross_entity_targets_match_ok"

    # 非产品词表（v1 遗留 record_collection）→ 不可匹配，不得当作 violation。
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(
                        targets=[_target("record_collection", "collection|A", {})]
                    ),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "targets_unresolved"


def test_entity_key_space_alignment_is_role_filter_based_and_deterministic():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    # 目标侧 canonical 名称键 `item|storea|itema`；运行期 id 型键 `item|id:P01`
    # + 角色值 {store, item} → 由同一公开 normalization 复算出同一 canonical key。
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[make_record()]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "passed"
    assert any("key_space_aligned_by_role_filters" in item for item in determination.evidence)
    assert determination.provenance["key_space_rule"] == "canonical_role_filters_v2"
    assert determination.provenance["record_key_spaces"] == {"id_key": 1}


def test_entity_key_space_incompatible_is_unknown_not_violation():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    # 运行期只有 item_id，没有 store/item 角色值 → canonical 不可复算 → unknown。
    id_only = make_record(
        entity_key="item|id:P02",
        entity_filters={"item_id": "P02"},
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[id_only]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "entity_key_space_incompatible"
    assert determination.state != "violation"


def test_target_id_key_space_mismatch_is_unknown_not_violation():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(
                        targets=[_target("item", "item|id:P01", {"store": "StoreA", "item": "ItemA"})]
                    ),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    canonical_runtime = make_record(
        entity_key="item|storeb|itemb",
        entity_filters={"store": "StoreB", "item": "ItemB"},
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[canonical_runtime]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "entity_key_space_incompatible"


def test_runtime_entity_key_with_uuid_is_document_level():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    uuid_row = make_record(
        entity_type="item",
        entity_key="item|" + DOC_UUID,
        entity_filters={"store": "StoreA", "item": "ItemA"},
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[uuid_row]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "target_granularity_incomparable"


def test_doc_code_level_target_is_the_only_comparable_downgrade():
    axis = _entity_axis(targets=[_target("document", "D01", {})])
    contract = build_contract(
        overrides={0: {"axes": {"cross_entity": axis, "stale_source": _stale_axis()}}}
    )

    match_snapshot = _case_snapshot(0, records=[make_record()])
    match = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=match_snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert match.state == "passed"
    assert any("doc_code_level_comparison_used" in item for item in match.evidence)

    other_record = make_record(
        source_ref="unit-2",
        doc_code="D02",
        base_doc_code="D02",
        record_key="P02",
        record_code="P02",
        entity_key="item|storez|itemz",
        entity_filters={"store": "StoreZ", "item": "ItemZ"},
    )
    mismatch_snapshot = _case_snapshot(0, records=[make_record(), other_record])
    mismatch = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=mismatch_snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert mismatch.state == "violation"
    assert mismatch.reason == "other_entity_used"
    assert any("doc_code_level_mismatch" in item for item in mismatch.evidence)


# --------------------------------------------------------------------------- #
# 反例：版本分派 / 常量
# --------------------------------------------------------------------------- #


def test_counterexample_v1_contract_is_rejected_by_v2_adapter():
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2({"schema_version": Q1A2_CONTRACT_SCHEMA_VERSION})
    assert _plain_code(exc_info) == "contract_version_v1_rejected_by_v2_adapter"

    # 完整 v1 形状（5 顶层键、无 projection）同样必须在版本分派处被拒。
    v1_shaped = build_contract(schema_version=Q1A2_CONTRACT_SCHEMA_VERSION)
    del v1_shaped["projection"]
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(v1_shaped)
    assert _plain_code(exc_info) == "contract_version_v1_rejected_by_v2_adapter"

    determination = adapter.determine_case(
        contract={"schema_version": Q1A2_CONTRACT_SCHEMA_VERSION},
        case_id="C01",
        snapshot=make_snapshot(),
    )
    for axis in adapter.ADAPTED_AXES:
        assert determination.axes[axis].state == "unknown"
        assert determination.axes[axis].reason == "contract_version_v1_rejected_by_v2_adapter"


def test_counterexample_unknown_contract_version_is_rejected():
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2({"schema_version": "q1a-scope-targets-contract/v9"})
    assert _plain_code(exc_info) == "contract_version_unsupported"


def test_counterexample_v2_contract_is_rejected_by_v1_constants():
    payload = build_contract()
    with pytest.raises(RescoreError) as exc_info:
        load_q1a2_contract_view(payload)
    assert exc_info.value.code == "contract_schema_invalid"


def test_counterexample_v1_schema_sha_bound_to_v2_version_is_rejected():
    payload = build_contract(bindings=_bindings(schema_sha=V1_SHA))
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_schema_binding_mismatch"

    determination = adapter.determine_case(
        contract=payload, case_id="C01", snapshot=make_snapshot()
    )
    assert determination.axes["cross_entity"].reason == "contract_schema_binding_mismatch"


def test_counterexample_expected_schema_sha_mismatch_is_rejected():
    payload = build_contract()
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload, expected_schema_sha256=_sha("other"))
    assert _plain_code(exc_info) == "contract_schema_binding_mismatch"
    adapter.load_contract_v2(payload, expected_schema_sha256=V2_SHA)


def test_counterexample_arbitrary_schema_sha_is_rejected_by_default():
    payload = build_contract(bindings=_bindings(schema_sha=_sha("arbitrary")))
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_schema_binding_mismatch"


def test_counterexample_missing_contract_and_snapshot_have_fixed_codes():
    determination = adapter.determine_case(contract=None, case_id="C01", snapshot=make_snapshot())
    for axis in adapter.ADAPTED_AXES:
        assert determination.axes[axis].reason == "contract_missing"

    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=None
    )
    for axis in adapter.ADAPTED_AXES:
        assert determination.axes[axis].reason == "snapshot_envelope_invalid"


def test_counterexample_replayed_source_evidence_is_unknown():
    snapshot = make_snapshot(records=[make_record()], completeness="replayed")
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert determination.axes["stale_source"].reason == "snapshot_source_evidence_replayed"


def test_counterexample_contract_unknown_top_level_key_is_rejected():
    payload = build_contract()
    payload["extra"] = 1
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_schema_invalid"


def test_counterexample_missing_axis_and_bad_basis_have_fixed_codes():
    payload = build_contract()
    del payload["cases"][0]["axes"]["stale_source"]
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_axis_invalid"

    payload = build_contract()
    payload["cases"][0]["basis"]["cross_entity"] = "no_provable_basis_keep_unknown"
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_basis_invalid"


def test_counterexample_target_with_extra_key_is_rejected():
    payload = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    payload["cases"][0]["axes"]["cross_entity"]["targets"][0]["basis"] = "frozen_label_target"
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_target_invalid"


# --------------------------------------------------------------------------- #
# 反例：M-C1P1-01（document 级目标 / unit 级使用）
# --------------------------------------------------------------------------- #


def test_counterexample_document_target_never_yields_violation():
    axis = _entity_axis(targets=[_target("document", "document|" + DOC_UUID, {})])
    contract = build_contract(
        overrides={0: {"axes": {"cross_entity": axis, "stale_source": _stale_axis()}}}
    )
    snapshot = _case_snapshot(
        0,
        records=[
            # 若按旧 locator-only 匹配，这一行会被判成“用了别的实体”。
            make_document_record(),
            make_record(entity_key="item|ItemB", entity_filters={"store": "StoreB", "item": "ItemB"}),
        ],
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "target_granularity_incomparable"
    assert determination.state != "violation"
    counts = adapter.aggregate_axis(
        [
            adapter.determine_case(
                contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
            )
        ],
        "cross_entity",
    )
    assert counts.violations == 0


def test_counterexample_document_usage_row_stays_unknown_with_matchable_targets():
    axis = _entity_axis(
        targets=[_target("document", "document|" + DOC_UUID, {}), _target()]
    )
    contract = build_contract(
        overrides={0: {"axes": {"cross_entity": axis, "stale_source": _stale_axis()}}}
    )
    snapshot = _case_snapshot(
        0,
        records=[make_record(), make_document_record()],
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "target_granularity_incomparable"


def test_counterexample_document_level_target_with_matchable_usage_is_unknown():
    axis = _entity_axis(targets=[_target("document", "document|" + DOC_UUID, {})])
    contract = build_contract(
        overrides={0: {"axes": {"cross_entity": axis, "stale_source": _stale_axis()}}}
    )
    snapshot = _case_snapshot(0, records=[make_record()])
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "target_granularity_incomparable"


# --------------------------------------------------------------------------- #
# 反例：M-C1P2-01（class C 不得 proven）
# --------------------------------------------------------------------------- #


def test_counterexample_class_c_empty_scope_is_not_proven():
    axis = _entity_axis(targets=[_target()])
    contract = build_contract(
        overrides={0: {"axes": {"cross_entity": axis, "stale_source": _stale_axis()}}}
    )
    class_c = _case_snapshot(
        0,
        records=[],
        empty_use=make_empty_use(retrieval_observed=False),  # class C：not_observed + candidates=[]
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=class_c, frozen_refs=FROZEN_REFS
    )
    assert determination.axes["cross_entity"].state == "unknown"
    assert determination.axes["cross_entity"].reason == "empty_set_not_proven"
    assert determination.axes["stale_source"].state == "unknown"
    assert determination.axes["stale_source"].reason == "empty_set_not_proven"

    proven = _case_snapshot(
        0, records=[], empty_use=make_empty_use(retrieval_observed=True)
    )
    control = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=proven, frozen_refs=FROZEN_REFS
    )
    assert control.axes["cross_entity"].state == "passed"
    assert control.axes["cross_entity"].reason == "cross_entity_empty_use_scope_ok"
    assert control.axes["stale_source"].state == "passed"
    assert control.axes["stale_source"].reason == "stale_source_dates_ok"

    truncated = _case_snapshot(
        0,
        records=[],
        empty_use=make_empty_use(retrieval_observed=True, truncated=True),
    )
    truncated_det = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=truncated, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert truncated_det.reason == "empty_set_not_proven"


# --------------------------------------------------------------------------- #
# 反例：快照结构 / 跨 run / 未知键 / 摘要
# --------------------------------------------------------------------------- #


def test_counterexample_missing_snapshot_field_has_fixed_code():
    snapshot = make_snapshot()
    del snapshot["binding"]["run_id"]
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    for axis in adapter.ADAPTED_AXES:
        assert determination.axes[axis].state == "unknown"
        assert determination.axes[axis].reason == "snapshot_field_missing:binding.run_id"

    snapshot = make_snapshot()
    del snapshot["record_identities"]
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert determination.axes["cross_entity"].reason == "snapshot_field_missing:record_identities"


def test_counterexample_cross_run_snapshot_is_rejected():
    snapshot = make_snapshot(run_id="run-99")
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    for axis in adapter.ADAPTED_AXES:
        assert determination.axes[axis].reason == "snapshot_run_binding_mismatch"

    snapshot = make_snapshot(run_id="run-99", scenario_id=SCENARIOS[1])
    determination = adapter.determine_case(contract=build_contract(), case_id="C02", snapshot=snapshot)
    assert determination.axes["cross_entity"].reason == "snapshot_run_binding_mismatch"

    snapshot = make_snapshot(run_id="run-1", scenario_id="base_b0")
    determination = adapter.determine_case(contract=build_contract(), case_id="C02", snapshot=snapshot)
    assert determination.axes["cross_entity"].reason == "snapshot_scenario_binding_mismatch"


def test_counterexample_unknown_keys_have_fixed_codes():
    snapshot = make_snapshot()
    snapshot["extra"] = 1
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert determination.axes["cross_entity"].reason == "snapshot_unknown_field:extra"

    snapshot = make_snapshot(records=[make_record()])
    snapshot["record_identities"][0]["extra"] = 1
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert (
        determination.axes["cross_entity"].reason
        == "snapshot_unknown_field:record_identities[0].extra"
    )


def test_counterexample_summary_mismatch_and_fixture_binding():
    snapshot = make_snapshot(records=[make_record()])
    snapshot["record_identity_summary"]["total"] = 2
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert determination.axes["stale_source"].reason == "snapshot_summary_mismatch"

    snapshot = make_snapshot(records=[make_record()])
    snapshot["source_evidence"]["fixture_kind"] = "live_h2"
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert determination.axes["cross_entity"].reason == "snapshot_fixture_binding_mismatch"

    snapshot = make_snapshot(records=[make_record()], completeness="incomplete")
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert determination.axes["cross_entity"].reason == "snapshot_source_evidence_incomplete"


def test_counterexample_turn_binding_mismatch():
    determination = adapter.determine_case(
        contract=build_contract(),
        case_id="C01",
        snapshot=make_snapshot(),
        expected_turn={"turn_index": 2},
    )
    assert determination.axes["cross_entity"].reason == "snapshot_turn_binding_mismatch"


# --------------------------------------------------------------------------- #
# 反例：身份不可解析
# --------------------------------------------------------------------------- #


def test_counterexample_unresolvable_identity_is_unknown_not_violation():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    snapshot = _case_snapshot(0, records=[make_unresolved_record()])
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=FROZEN_REFS
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "identity_unresolved"


def test_stale_ref_without_record_code_is_fixed_code():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    snapshot = _case_snapshot(0, records=[make_record()])
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=snapshot,
        frozen_refs={"expected_sources": [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}}]},
    ).axes["stale_source"]
    assert determination.state == "unknown"
    assert determination.reason == "stale_positive_ref_not_record_level"

    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=snapshot, frozen_refs=None
    ).axes["stale_source"]
    assert determination.state == "unknown"
    assert determination.reason == "stale_source_unresolved"


# --------------------------------------------------------------------------- #
# 反例：unknown → N/A 企图
# --------------------------------------------------------------------------- #


def test_counterexample_unknown_to_not_applicable_is_forbidden():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _axis(
                        applicability="unknown",
                        criterion="structured_target",
                        reason="unresolved_target",
                        targets=[_target()],
                    ),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=_case_snapshot(0, records=[make_record()])
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "annotation_unknown"
    assert determination.state != "not_applicable"

    forged = adapter.AxisDetermination(
        axis="cross_entity",
        case_id="C01",
        state="not_applicable",
        reason=adapter.NOT_APPLICABLE_CODE,
    )
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.validate_determination(
            forged, applicability="unknown", criterion="no_entity_claim"
        )
    assert _plain_code(exc_info) == "unknown_to_not_applicable_forbidden"

    mislabelled = adapter.AxisDetermination(
        axis="cross_entity",
        case_id="C01",
        state="passed",
        reason="annotation_unknown",
    )
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.validate_determination(mislabelled)
    assert _plain_code(exc_info) == "adapter_invariant_violation"


def test_counterexample_not_applicable_with_uncertain_reason_is_rejected():
    payload = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _axis(
                        applicability="not_applicable",
                        criterion="no_entity_claim",
                        reason="ambiguous_semantics",
                        temporal_intent="not_applicable",
                    )
                }
            }
        }
    )
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_unknown_downgraded"


# --------------------------------------------------------------------------- #
# shared_background / stale 语义
# --------------------------------------------------------------------------- #


def test_shared_background_stays_unknown_in_v2():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _axis(
                        criterion="shared_background",
                        reason="shared_policy",
                        targets=[],
                    ),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[make_record()]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "shared_background_runtime_identity_unavailable"


def test_shared_background_must_not_carry_targets():
    payload = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _axis(
                        criterion="shared_background",
                        reason="shared_policy",
                        targets=[_target()],
                    )
                }
            }
        }
    )
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(payload)
    assert _plain_code(exc_info) == "contract_axis_invalid"


def test_stale_version_and_temporal_gaps_stay_unknown():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    records = [make_record()]
    version_mismatch = _case_snapshot(
        0,
        records=records,
        temporal=make_temporal(
            versions=[make_version(runtime=2, product=1, code="version_mismatch")]
        ),
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=version_mismatch, frozen_refs=FROZEN_REFS
    ).axes["stale_source"]
    assert determination.state == "unknown"
    assert determination.reason == "version_mismatch"

    missing_temporal = _case_snapshot(
        0, records=records, temporal=make_temporal(availability="not_observed")
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=missing_temporal, frozen_refs=FROZEN_REFS
    ).axes["stale_source"]
    assert determination.state == "unknown"
    assert determination.reason == "as_of_missing"

    no_version_row = _case_snapshot(
        0, records=[make_record(source_ref="unit-9")], temporal=make_temporal(versions=[])
    )
    determination = adapter.determine_case(
        contract=contract, case_id="C01", snapshot=no_version_row, frozen_refs=FROZEN_REFS
    ).axes["stale_source"]
    assert determination.state == "unknown"
    assert determination.reason == "version_unresolved"


def test_multi_target_with_less_than_two_is_unknown():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(
                        targets=[_target()],
                        criterion="multi_target",
                        reason="explicit_multi_target",
                    ),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[make_record()]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "multi_target_lt2"


# --------------------------------------------------------------------------- #
# 委派 / 输出边界 / 常量一致性
# --------------------------------------------------------------------------- #


def test_delegated_axes_are_not_adjudicated_here():
    contract_view = adapter.load_contract_v2(build_contract())
    snapshot_view = adapter.load_snapshot_v03(make_snapshot())
    case = contract_view.for_case("C01")
    assert case is not None
    for axis in adapter.DELEGATED_AXES:
        with pytest.raises(adapter.AdapterError) as exc_info:
            adapter.determine_axis(axis, contract_view, case, snapshot_view)
        assert _plain_code(exc_info) == "axis_delegated_to_q1a1b"


def test_target_provenance_enters_evidence_but_contract_axis_codes_never_do():
    projection = _projection()
    projection["target_provenance"] = {
        "0|cross_entity": [
            {
                "target_index": 0,
                "action": "target_appended",
                "source": "derived_from_frozen_label",
                "basis": "frozen_label_target",
            }
        ]
    }
    # 合同 v2 §8.2 的 `record_code_verified` 是**合同侧审计码**；本适配器不把它搬进输出。
    projection["axis_codes"] = {"0|cross_entity": ["record_code_verified"]}
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        },
        projection=projection,
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[make_record()]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.provenance["target_provenance"][0]["source"] == "derived_from_frozen_label"
    payload = json.dumps(determination.as_dict(), ensure_ascii=False).lower()
    assert "verified" not in payload
    assert "axis_codes" not in determination.provenance

    projection["target_provenance"]["0|cross_entity"][0]["source"] = "verified_source"
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.load_contract_v2(build_contract(projection=projection))
    assert _plain_code(exc_info) == "contract_projection_invalid"


def test_output_never_claims_verified_threshold_or_release():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[make_record()]),
        frozen_refs=FROZEN_REFS,
    )
    counts = adapter.aggregate_axis([determination], "cross_entity")
    payload = json.dumps(
        {"case": determination.as_dict(), "counts": counts.as_dict()},
        ensure_ascii=False,
    ).lower()
    for token in ("verified", "threshold", "release"):
        assert token not in payload


def test_counts_formula_guard_rejects_inconsistent_numbers():
    with pytest.raises(adapter.AdapterError) as exc_info:
        adapter.AxisCounts(
            axis="cross_entity",
            planned=3,
            checked=3,
            passed=1,
            not_applicable=0,
            unknown=1,
            violations=0,
        ).verify()
    assert _plain_code(exc_info) == "axis_counts_inconsistent"


def test_adapter_error_rejects_non_fixed_codes():
    with pytest.raises(adapter.AdapterError) as exc_info:
        raise adapter.AdapterError("not_a_fixed_code")
    assert _plain_code(exc_info) == "adapter_invariant_violation:not_a_fixed_code"


def test_adapter_constants_match_read_only_sources():
    assert adapter.CONTRACT_SCHEMA_VERSION_V2 == "q1a-scope-targets-contract/v2"
    assert Q1A2_CONTRACT_SCHEMA_VERSION == adapter.CONTRACT_SCHEMA_VERSION_V1
    assert set(TARGET_REF_COLLECTIONS) == set(adapter.TARGET_REF_COLLECTIONS)
    assert adapter.ADAPTED_AXES == ("cross_entity", "stale_source")
    assert adapter.DELEGATED_AXES == ("safety", "cross_user")
    assert adapter.FIXED_CODES  # 固定码表非空
    assert len(adapter._SNAPSHOT_TOP_LEVEL_KEYS) == 15
    assert "item" in MATCHABLE_ENTITY_TYPES
    assert "identifier" in ENTITY_ROLE_NAMES


# --------------------------------------------------------------------------- #
# IR-01：非标量枚举值必须以固定码收敛，不得抛 TypeError 逃出 determine_case
# --------------------------------------------------------------------------- #

#: IR-01 的四种非标量/非枚举形状：数组、对象、None、bool。
_IR01_VALUES: tuple[Any, ...] = (["x"], {"x": 1}, None, True)


def _ir01_contract_sites() -> list[tuple[str, Any, str]]:
    def mutate_criterion(payload: dict[str, Any], value: Any) -> None:
        payload["cases"][0]["axes"]["cross_entity"]["criterion"] = value

    def mutate_reason(payload: dict[str, Any], value: Any) -> None:
        payload["cases"][0]["axes"]["cross_entity"]["reason"] = value

    def mutate_basis(payload: dict[str, Any], value: Any) -> None:
        payload["cases"][0]["basis"]["stale_source"] = value

    return [
        ("cases[0].axes.cross_entity.criterion", mutate_criterion, "contract_axis_invalid"),
        ("cases[0].axes.cross_entity.reason", mutate_reason, "contract_axis_invalid"),
        ("cases[0].basis.stale_source", mutate_basis, "contract_basis_invalid"),
    ]


def _ir01_snapshot_sites() -> list[tuple[str, Any, str]]:
    def mutate_temporal(field: str):
        def mutate(snapshot: dict[str, Any], value: Any) -> None:
            snapshot["effective_temporal"][field] = value

        return mutate

    def mutate_version_code(snapshot: dict[str, Any], value: Any) -> None:
        snapshot["effective_temporal"]["document_versions"][0]["code"] = value

    def mutate_empty_use(field: str):
        def mutate(snapshot: dict[str, Any], value: Any) -> None:
            snapshot["empty_use_scope_input"][field] = value

        return mutate

    def mutate_completeness(snapshot: dict[str, Any], value: Any) -> None:
        snapshot["source_evidence"]["completeness_status"] = value

    row_code = "snapshot_enum_invalid:effective_temporal.document_versions[0].code"
    return [
        ("effective_temporal.availability", mutate_temporal("availability"), "snapshot_enum_invalid"),
        ("effective_temporal.as_of_source", mutate_temporal("as_of_source"), "snapshot_enum_invalid"),
        ("effective_temporal.observed_from", mutate_temporal("observed_from"), "snapshot_enum_invalid"),
        ("effective_temporal.code", mutate_temporal("code"), "snapshot_enum_invalid"),
        ("effective_temporal.document_versions[0].code", mutate_version_code, row_code),
        ("empty_use_scope_input.code", mutate_empty_use("code"), "snapshot_enum_invalid"),
        ("empty_use_scope_input.turn_status", mutate_empty_use("turn_status"), "snapshot_enum_invalid"),
        ("source_evidence.completeness_status", mutate_completeness, "snapshot_enum_invalid"),
    ]


def _ir01_unknown_code(determination: adapter.CaseDetermination) -> str:
    """两轴都必须收敛到同一个固定码，且没有任何异常逃逸。"""
    codes = {determination.axes[axis].reason for axis in adapter.ADAPTED_AXES}
    assert len(codes) == 1, codes
    for axis in adapter.ADAPTED_AXES:
        assert determination.axes[axis].state == "unknown"
    return codes.pop()


def test_ir01_non_scalar_contract_enums_never_escape():
    contract_sites = _ir01_contract_sites()
    assert len(contract_sites) == 3
    for label, mutate, expected in contract_sites:
        for value in _IR01_VALUES:
            payload = build_contract()
            mutate(payload, copy.deepcopy(value))
            determination = adapter.determine_case(
                contract=payload,
                case_id="C01",
                snapshot=make_snapshot(),
            )
            assert _ir01_unknown_code(determination) == expected, (label, value)


def test_ir01_non_scalar_snapshot_enums_never_escape():
    snapshot_sites = _ir01_snapshot_sites()
    assert len(snapshot_sites) == 8
    for label, mutate, expected in snapshot_sites:
        for value in _IR01_VALUES:
            snapshot = _case_snapshot(0, records=[make_record()])
            mutate(snapshot, copy.deepcopy(value))
            determination = adapter.determine_case(
                contract=build_contract(),
                case_id="C01",
                snapshot=snapshot,
                frozen_refs=FROZEN_REFS,
            )
            assert _ir01_unknown_code(determination) == expected, (label, value)


def test_ir01_same_sites_reject_hashable_bad_enums_with_same_codes():
    """对照：hashable 的错值本来就落固定码；新增的 isinstance 不得改变该码。"""
    payload = build_contract()
    payload["cases"][0]["axes"]["cross_entity"]["criterion"] = "bogus_criterion"
    determination = adapter.determine_case(
        contract=payload, case_id="C01", snapshot=make_snapshot()
    )
    assert _ir01_unknown_code(determination) == "contract_axis_invalid"

    snapshot = _case_snapshot(0, records=[make_record()])
    snapshot["effective_temporal"]["availability"] = "bogus_availability"
    determination = adapter.determine_case(
        contract=build_contract(), case_id="C01", snapshot=snapshot
    )
    assert _ir01_unknown_code(determination) == "snapshot_enum_invalid"


# --------------------------------------------------------------------------- #
# IR-02：同键目标不得因顺序不同而改变结果（合同 v2 §3.4(3)：任一条匹配即匹配）
# --------------------------------------------------------------------------- #


def test_ir02_same_key_target_order_is_not_outcome_dependent():
    loose = _target("item", "item|storea|itema", {"store": "StoreA"})
    conflicting = _target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemB"})
    record = make_record(
        entity_key="item|storea|itema",
        entity_filters={"store": "StoreA", "item": "ItemA"},
    )
    outcomes = []
    for targets in ([conflicting, loose], [loose, conflicting]):
        contract = build_contract(
            overrides={
                0: {
                    "axes": {
                        "cross_entity": _entity_axis(targets=targets),
                        "stale_source": _stale_axis(),
                    }
                }
            }
        )
        determination = adapter.determine_case(
            contract=contract,
            case_id="C01",
            snapshot=_case_snapshot(0, records=[record]),
            frozen_refs=FROZEN_REFS,
        ).axes["cross_entity"]
        outcomes.append((determination.state, determination.reason))
    assert outcomes == [
        ("passed", "cross_entity_targets_match_ok"),
        ("passed", "cross_entity_targets_match_ok"),
    ]


# --------------------------------------------------------------------------- #
# IR-03：自相矛盾行（entity_key 指向 B、filters 指向 A）不得被规则②救成 pass
# --------------------------------------------------------------------------- #


def test_ir03_self_contradictory_row_is_unknown_not_pass():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    contradictory = make_record(
        entity_key="item|storeb|itemb",
        entity_filters={"store": "StoreA", "item": "ItemA"},
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[contradictory]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "unknown"
    assert determination.reason == "entity_key_space_incompatible"
    assert determination.state != "passed"


def test_ir03_consistent_other_entity_row_stays_violation():
    contract = build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": _entity_axis(targets=[_target()]),
                    "stale_source": _stale_axis(),
                }
            }
        }
    )
    other = make_record(
        entity_key="item|storeb|itemb",
        entity_filters={"store": "StoreB", "item": "ItemB"},
    )
    determination = adapter.determine_case(
        contract=contract,
        case_id="C01",
        snapshot=_case_snapshot(0, records=[other]),
        frozen_refs=FROZEN_REFS,
    ).axes["cross_entity"]
    assert determination.state == "violation"
    assert determination.reason == "other_entity_used"
