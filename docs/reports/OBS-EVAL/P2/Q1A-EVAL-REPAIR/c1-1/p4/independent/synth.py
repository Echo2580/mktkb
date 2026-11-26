"""C1-P4 独立验收：自建合成 v2 合同 + v0.3 快照构建器。

独立实现，不 import 开发测试模块、不复制其 fixture；只 import 被测模块与只读依赖的
**公开常量**，并把所用常量值写进证据，便于复核。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from mktkb.evaluation.p2_evidence_axes_adapter_v2 import (
    CONTRACT_SCHEMA_VERSION_V1,
    CONTRACT_SCHEMA_VERSION_V2,
    KNOWN_CONTRACT_SCHEMA_SHA256,
    PROJECTION_RULE_VERSION_V2,
)
from mktkb.evaluation.p2_evidence_rescore import AXES
from mktkb.evaluation.p2_evidence_rescore_axes import (
    Q1A2_BINDING_KEYS,
    Q1A2_SCENARIO_IDS,
)
from mktkb.evaluation.p2_evidence_snapshot_v03 import (
    CANDIDATE_LAYER_NAMES,
    CONTRACT_VERSION as SNAPSHOT_CONTRACT_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    USE_LAYER_NAMES,
)

SCHEMA_V2_SHA = KNOWN_CONTRACT_SCHEMA_SHA256[CONTRACT_SCHEMA_VERSION_V2]
SCHEMA_V1_SHA = KNOWN_CONTRACT_SCHEMA_SHA256[CONTRACT_SCHEMA_VERSION_V1]
SCENARIOS = Q1A2_SCENARIO_IDS
AS_OF = "2026-10-28"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 合同 v2
# --------------------------------------------------------------------------- #


def target(entity_type: str, entity_key: str, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"entity_type": entity_type, "entity_key": entity_key, "filters": dict(filters or {})}


def ref(collection: str, index: int) -> dict[str, Any]:
    return {"collection": collection, "index": index}


def axis(
    applicability: str,
    criterion: str,
    reason: str,
    *,
    targets: Sequence[Mapping[str, Any]] = (),
    target_refs: Sequence[Mapping[str, Any]] = (),
    as_of: str | None = AS_OF,
    temporal_intent: str = "current",
    basis: str = "frozen_label_target",
) -> dict[str, Any]:
    return {
        "applicability": applicability,
        "criterion": criterion,
        "reason": reason,
        "target_refs": [dict(row) for row in target_refs],
        "targets": [dict(row) for row in targets],
        "as_of": as_of,
        "temporal_intent": temporal_intent,
        "basis": basis,
    }


def default_axes() -> dict[str, dict[str, Any]]:
    """无关轴用最小合法形状；被聚焦的轴由调用方覆盖。"""
    return {
        "safety": axis(
            "unknown",
            "unknown",
            "insufficient_annotation",
            as_of=None,
            temporal_intent="unknown",
            basis="no_provable_basis_keep_unknown",
        ),
        "cross_user": axis("required", "unknown", "insufficient_annotation"),
        "cross_entity": axis("required", "structured_target", "explicit_single_target"),
        "stale_source": axis("required", "lifecycle_dates", "published_lifecycle"),
    }


def default_projection() -> dict[str, Any]:
    return {
        "rule_version": PROJECTION_RULE_VERSION_V2,
        "lineage": {f"v1_{name}": sha(f"lineage-{name}") for name in ("ciphertext", "schema", "aggregate", "report")},
        "corpus_bindings": {"record_count": 76, "table_document_count": 4, "variant_count": 7,
                            "ingest_source_count": 12, "fixtures_manifest_sha256": sha("manifest")},
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
        "coverage": {"has_matchable_target": 16, "only_unmatchable_targets": 3, "still_empty": 11},
    }


def bindings(*, schema_sha: str = SCHEMA_V2_SHA) -> dict[str, str]:
    values = {key: sha(f"binding::{key}") for key in Q1A2_BINDING_KEYS}
    values["dataset_version"] = "P2-HOLDOUT-v2"
    values["label_version"] = "p2-holdout-v2-2026-11-10"
    values["contract_schema_sha256"] = schema_sha
    return values


def contract(
    case_axes: Mapping[int, Mapping[str, Mapping[str, Any]]] | None = None,
    *,
    case_count: int = 30,
    schema_version: str = CONTRACT_SCHEMA_VERSION_V2,
    schema_sha: str = SCHEMA_V2_SHA,
    projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = dict(case_axes or {})
    cases: list[dict[str, Any]] = []
    for index in range(case_count):
        raw = overrides.get(index) or default_axes()
        axes: dict[str, Any] = {}
        basis: dict[str, str] = {}
        for name in AXES:
            payload = dict(raw[name])
            basis[name] = str(payload.pop("basis", "frozen_label_target"))
            axes[name] = payload
        cases.append(
            {
                "case_id": f"C{index:02d}",
                "case_index": index,
                "scenario_id": SCENARIOS[index % len(SCENARIOS)],
                "axes": axes,
                "basis": basis,
            }
        )
    runs = [
        {
            "run_index": index,
            "scenario_id": SCENARIOS[index],
            "run_id": f"run-{index}",
            "plan_id": f"plan-{index}",
            "plan_sha256": sha(f"plan-{index}"),
        }
        for index in range(len(SCENARIOS))
    ]
    return {
        "schema_version": schema_version,
        "bindings": bindings(schema_sha=schema_sha),
        "runs": runs,
        "case_count": case_count,
        "cases": cases,
        "projection": dict(projection or default_projection()),
    }


# --------------------------------------------------------------------------- #
# 快照 v0.3
# --------------------------------------------------------------------------- #


def record(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_ref": "src-1",
        "layers": ["model_evidence"],
        "unit_kind": "record",
        "locator_kind": "record",
        "doc_code": "S01",
        "base_doc_code": "S01",
        "sheet": "Sheet1",
        "row": 2,
        "record_key": "W01",
        "record_code": "W01",
        "business_version": "1",
        "version_number": 1,
        "record_level": True,
        "entity_type": "item",
        "entity_key": "item|storea|itema",
        "entity_filters": {"store": "StoreA", "item": "ItemA"},
        "entity_matchable": True,
        "code": "record_row_reverse_lookup",
        "entity_code": "entity_identity_matchable",
    }
    row.update(overrides)
    return row


def text_record(**overrides: Any) -> dict[str, Any]:
    """非记录级（文档段落/页）身份：无记录身份、无实体身份。"""
    row = record(
        unit_kind="chunk",
        locator_kind="other",
        sheet=None,
        row=None,
        record_key=None,
        record_code=None,
        record_level=False,
        entity_type=None,
        entity_key=None,
        entity_filters={},
        entity_matchable=False,
        code="runtime_unit_not_record_level",
        entity_code="entity_identity_absent",
    )
    row.update(overrides)
    return row


def document_record(**overrides: Any) -> dict[str, Any]:
    """文档粒度：entity_type=document + document|<uuid>。"""
    row = record(
        entity_type="document",
        entity_key="document|3f1c2b7a-0d4e-4a6f-9c1d-2b8e5a7c9d10",
        entity_filters={},
        entity_matchable=False,
        entity_code="entity_identity_document_level",
    )
    row.update(overrides)
    return row


def summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(records),
        "record_level": sum(1 for row in records if row["record_level"] is True),
        "not_record_level": sum(1 for row in records if row["record_level"] is not True),
        "doc_code_unresolved": sum(1 for row in records if row["code"] == "runtime_doc_code_unresolved"),
        "entity_matchable": sum(1 for row in records if row["entity_matchable"] is True),
        "entity_document_level": sum(1 for row in records if row["entity_type"] == "document"),
        "unresolved_units": sum(1 for row in records if row["code"] == "runtime_unit_unresolved"),
        "doc_codes": sorted({row["base_doc_code"] for row in records if row["base_doc_code"] is not None}),
    }


def temporal(
    *,
    as_of: str | None = AS_OF,
    availability: str = "observed",
    code: str | None = None,
    source_refs: Sequence[str] = ("src-1",),
    version_code: str = "version_observed",
    runtime_version: int | None = 2,
    product_version: int | None = 2,
    as_of_source: str = "plan_observed",
    baseline_used: bool = False,
) -> dict[str, Any]:
    if code is None:
        code = "effective_temporal_observed" if availability == "observed" else "effective_temporal_partial"
    if availability == "not_observed":
        as_of = None
        as_of_source = "unavailable"
    versions = [
        {
            "source_ref": source_ref,
            "doc_code": "S01",
            "version_label": "v1",
            "runtime_version_number": runtime_version,
            "product_version_number": product_version,
            "code": version_code,
        }
        for source_ref in source_refs
    ]
    return {
        "availability": availability,
        "reason": None,
        "as_of": as_of,
        "as_of_source": as_of_source,
        "observed_from": "db_projection_units" if availability == "observed" else "unavailable",
        "include_future": False,
        "enumerate": False,
        "document_versions": versions,
        "declared_baseline_business_date": AS_OF,
        "baseline_used_as_effective": baseline_used,
        "code": code,
    }


def empty_use(
    *,
    counts: Mapping[str, int] | None = None,
    observed: Mapping[str, bool] | None = None,
    retrieval: tuple[bool, int, Sequence[str], bool] = (True, 0, (), False),
    query_state: tuple[bool, int, Sequence[str], bool] = (True, 0, (), False),
    turn_status: str = "complete",
    code: str | None = None,
    empty_set_candidate: bool | None = None,
    all_observed: bool | None = None,
) -> dict[str, Any]:
    counts = dict(counts or {name: 0 for name in USE_LAYER_NAMES})
    observed = dict(observed or {name: True for name in USE_LAYER_NAMES})
    use_layers: dict[str, Any] = {}
    for name in USE_LAYER_NAMES:
        count = int(counts[name])
        refs = [] if name == "direct_rag_fact_count" else [f"{name}-u{i}" for i in range(count)]
        use_layers[name] = {"observed": bool(observed[name]), "count": count, "refs": refs}
    computed_all = all(bool(observed[name]) for name in USE_LAYER_NAMES)
    total = sum(int(counts[name]) for name in USE_LAYER_NAMES)
    if all_observed is None:
        all_observed = computed_all
    if empty_set_candidate is None:
        empty_set_candidate = computed_all and total == 0
    if code is None:
        if turn_status in {"partial", "unavailable"}:
            code = "empty_use_input_turn_partial"
        elif empty_set_candidate:
            code = "empty_use_input_complete_empty"
        elif total > 0:
            code = "empty_use_input_nonempty"
        else:
            code = "empty_use_input_layers_not_observed"

    def candidate(values: tuple[bool, int, Sequence[str], bool]) -> dict[str, Any]:
        flag, count, refs, truncated = values
        return {"observed": flag, "count": count, "refs": list(refs), "truncated": truncated}

    return {
        "input_version": "c1p2-empty-use-scope-input/v0.1",
        "turn_status": turn_status,
        "reason": None,
        "plan": {
            "availability": True,
            "path": "rag",
            "mode": "entity_bound",
            "as_of": AS_OF,
            "include_future": False,
            "clarification": False,
        },
        "use_layers": use_layers,
        "candidate_layers": {
            "retrieval_observed": candidate(retrieval),
            "query_state_candidates": candidate(query_state),
            "projection_query_state_candidates": candidate((True, 0, (), False)),
        },
        "all_use_layers_observed": bool(all_observed),
        "empty_set_candidate": bool(empty_set_candidate),
        "code": code,
    }


def snapshot(
    records: Sequence[Mapping[str, Any]] = (),
    *,
    scenario_id: str = SCENARIOS[0],
    run_id: str | None = None,
    source_refs: Sequence[str] = ("src-1",),
    completeness: str = "complete",
    empty: Mapping[str, Any] | None = None,
    temporal_view: Mapping[str, Any] | None = None,
    fixture_kind: str = "local_mock",
    turn_index: int = 0,
    client_request_id: str = "crid-0",
) -> dict[str, Any]:
    if run_id is None:
        run_id = f"run-{SCENARIOS.index(scenario_id)}"
    rows = [dict(row) for row in records]
    refs = sorted({row["source_ref"] for row in rows}) or list(source_refs)
    body: dict[str, Any] = {
        "contract_version": SNAPSHOT_CONTRACT_VERSION,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "fixture_kind": fixture_kind,
        "captured_utc": "2026-11-14T00:00:00Z",
        "source_evidence": {
            "sha256": sha("source-evidence"),
            "schema_version": "p2-hard-evidence/v0.3",
            "fixture_kind": fixture_kind,
            "completeness_status": completeness,
        },
        "binding": {
            "run_id": run_id,
            "plan_sha256": sha(f"plan-{SCENARIOS.index(scenario_id)}"),
            "scenario_id": scenario_id,
            "fixture_kind": fixture_kind,
            "bindings_sha256": sha("bindings"),
            "run_binding_sha256": sha("run-binding"),
            "business_date_declared": AS_OF,
        },
        "turn_ref": {
            "turn_index": turn_index,
            "client_request_id": client_request_id,
            "conversation_id": "conv-1",
            "question_sha256": sha("question"),
            "pre_revision": 0,
            "post_revision": 1,
            "capture_revision": 1,
            "response_kind": "answer",
            "http_status": 200,
            "timed_out": False,
        },
        "request_owner": {
            "availability": "observed",
            "reason": None,
            "user_ref": "user-ref",
            "conversation_ref": "conv-ref",
            "owner_source": "turn_authenticated_user_id",
            "auth_material_collected": False,
        },
        "record_identities": rows,
        "record_identity_summary": summary(rows),
        "effective_temporal": dict(temporal_view or temporal(source_refs=refs)),
        "empty_use_scope_input": dict(empty or empty_use()),
        "runtime_identity": {
            "declared": True,
            "unit_ids": ["unit-1"],
            "unresolved_unit_ids": [],
            "document_ids": [],
            "version_ids": [],
            "counts": {"units": 1, "unresolved": 0, "documents": 0, "versions": 0},
        },
        "public_boundary": {
            "public_summary_sha256": sha("public-summary"),
            "public_summary_keys": ["axes", "counts"],
            "runtime_ids_only_in_declared_blocks": True,
        },
    }
    body["content_sha256"] = sha(json.dumps(body, sort_keys=True, ensure_ascii=False))
    return body


def case_axes(
    *,
    cross_entity: Mapping[str, Any] | None = None,
    stale_source: Mapping[str, Any] | None = None,
) -> dict[str, Mapping[str, Any]]:
    axes = default_axes()
    if cross_entity is not None:
        axes["cross_entity"] = dict(cross_entity)
    if stale_source is not None:
        axes["stale_source"] = dict(stale_source)
    return axes


__all__ = [
    "AS_OF",
    "CANDIDATE_LAYER_NAMES",
    "CONTRACT_SCHEMA_VERSION_V1",
    "CONTRACT_SCHEMA_VERSION_V2",
    "SCENARIOS",
    "SCHEMA_V1_SHA",
    "SCHEMA_V2_SHA",
    "axis",
    "bindings",
    "case_axes",
    "contract",
    "default_axes",
    "default_projection",
    "document_record",
    "empty_use",
    "record",
    "ref",
    "sha",
    "snapshot",
    "summary",
    "target",
    "temporal",
    "text_record",
    "USE_LAYER_NAMES",
]
