"""Q1a-1b 独立验收共享构造器：只用合成数据；不读 H2/私有密文/key/.env。

本文件与同目录 `1x-*.py` 探针由独立验收者自建，不复用开发者用例。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
for extra in (ROOT / "backend" / "src", ROOT / "backend" / "tests"):
    text = str(extra)
    if text not in sys.path:
        sys.path.insert(0, text)

from mktkb.evaluation import p2_evidence_rescore as rescore  # noqa: E402
from mktkb.evaluation import p2_evidence_rescore_axes as axes  # noqa: E402

CASE_ID = "SYN-INDEP-001"
RUN_BINDINGS = {
    "run_id": "SYN-RUN-Q1A1B",
    "plan_id": "SYN-PLAN-Q1A1B",
    "plan_sha256": "c" * 64,
}
OTHER_BINDINGS = {
    "run_id": "SYN-RUN-OTHER",
    "plan_id": "SYN-PLAN-OTHER",
    "plan_sha256": "d" * 64,
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unit(
    unit_id: str = "u1",
    *,
    doc_code: str | None = "D01",
    record_code: str | None = "P01",
    version_id: str | None = "ver-2",
    version_number: int | None = 2,
    unit_key: str | None = None,
    locator: dict[str, Any] | None = None,
    layers: tuple[str, ...] = ("model_evidence", "final_citation"),
    document_id: str | None = "doc-1",
    document_name: str | None = "合成文档A",
) -> rescore.UnitView:
    return rescore.UnitView(
        unit_id=unit_id,
        layers=layers,
        document_id=document_id,
        document_name=document_name,
        doc_code=doc_code,
        version_id=version_id,
        version_number=version_number,
        unit_key=unit_key,
        record_code=record_code,
        locator={"sheet": "物品位置", "row": 8} if locator is None else locator,
    )


def ref(
    *,
    doc_code: str = "D01",
    record_code: str | None = "P01",
    unit_key: str | None = None,
    locator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"doc_code": doc_code}
    if record_code is not None:
        payload["record_code"] = record_code
    if unit_key is not None:
        payload["unit_key"] = unit_key
    if locator is not None:
        payload["locator"] = locator
    return payload


def old_card(
    *,
    case_id: str = CASE_ID,
    safety: tuple[str, str] | None = None,
    cross_user: tuple[str, str] | None = None,
    cross_entity: tuple[str, str] | None = None,
    stale_source: tuple[str, str] | None = None,
    quality_status: str = "pass",
    missing_codes: tuple[str, ...] = (),
    evidence_complete: bool = True,
) -> rescore.OldCardCase:
    def axis_pair(axis: str, override: tuple[str, str] | None) -> dict[str, str]:
        state, reason = override or ("passed", axes.PASS_REASONS[axis])
        return {"state": state, "reason": reason}

    return rescore.OldCardCase(
        case_id=case_id,
        stratum="cross_doc_security",
        quality_status=quality_status,
        axes={
            "safety": {
                "state": (safety or ("not_applicable", rescore.NA_REASON))[0],
                "reason": (safety or ("not_applicable", rescore.NA_REASON))[1],
            },
            "cross_user": axis_pair("cross_user", cross_user),
            "cross_entity": axis_pair("cross_entity", cross_entity),
            "stale_source": axis_pair("stale_source", stale_source),
        },
        missing_codes=missing_codes,
        evidence_complete=evidence_complete,
    )


_AXIS_DEFAULTS: dict[str, dict[str, Any]] = {
    "cross_user": {
        "criterion": "owner_context",
        "reason": "all_user_contexts",
    },
    "cross_entity": {
        "criterion": "structured_target",
        "reason": "explicit_single_target",
    },
    "stale_source": {
        "criterion": "lifecycle_dates",
        "reason": "published_lifecycle",
    },
}


def annotation(axis: str, **overrides: Any) -> axes.AxisAnnotation:
    payload: dict[str, Any] = {
        "applicability": "required",
        "criterion": _AXIS_DEFAULTS[axis]["criterion"],
        "reason": _AXIS_DEFAULTS[axis]["reason"],
        "target_refs": [],
        "targets": [],
        "as_of": None,
        "temporal_intent": "current",
        "basis": "synthetic_fixture",
        "source": "synthetic_fixture",
    }
    payload.update(overrides)
    return axes.AxisAnnotation.from_mapping(axis, payload)


def cross_user_view(**overrides: Any) -> axes.CrossUserEvidenceView:
    payload: dict[str, Any] = {
        "projection_available": True,
        "owner_user_id": "user-A",
        "conversation_id": "conv-A",
        "authenticated_user_id": "user-A",
        "request_id": "req-A",
        "request_user_id": "user-A",
        "request_conversation_id": "conv-A",
        "claims": (
            axes.ClaimView(
                authenticated_user_id="user-A",
                owner_user_id="user-A",
                conversation_id="conv-A",
                request_id="req-A",
            ),
        ),
        "context_observation_count": 1,
        "context_observation_empty": False,
        "context_observation_request_id": "req-A",
        "context_messages": (
            axes.ContextMessageView(seq=1, owner_user_id="user-A", request_id="req-A"),
        ),
        "query_states_available": True,
        "query_states": (axes.QueryStateRowView("user-A", "conv-A"),),
        "query_state_events": (
            axes.QueryStateEventView(
                "query_state_observed",
                user_id="user-A",
                conversation_id="conv-A",
                stored_user_id="user-A",
                stored_conversation_id="conv-A",
                row_present=True,
            ),
        ),
        "entity_inheritance": (
            axes.EntityInheritanceView("msg-1", "user-A", "assistant"),
        ),
        "result_message": axes.ResultMessageView("res-1", "user-A", "assistant"),
    }
    payload.update(overrides)
    return axes.CrossUserEvidenceView(**payload)


def cross_entity_view(
    units: tuple[rescore.UnitView, ...] = (),
    *,
    unit_entity: dict[str, axes.EntityIdentityView] | None = None,
    facts: tuple[axes.EntityFactView, ...] = (),
    plan_filters: dict[str, Any] | None = None,
    bindings: dict[str, str] | None = None,
    empty_scope_proven: bool | None = None,
    empty_scope_reason: str | None = None,
) -> axes.CrossEntityEvidenceView:
    return axes.CrossEntityEvidenceView(
        units=units,
        unit_entity={} if unit_entity is None else unit_entity,
        facts=facts,
        plan_filters=plan_filters,
        bindings=RUN_BINDINGS if bindings is None else bindings,
        empty_scope_proven=empty_scope_proven,
        empty_scope_reason=empty_scope_reason,
    )


def scope_target(entity_type: str = "item", entity_key: str = "K1", **filters: Any) -> axes.ScopeTarget:
    return axes.ScopeTarget(entity_type=entity_type, entity_key=entity_key, filters=filters)


def shared_entry(
    document_id: str = "doc-1",
    version_id: str = "ver-2",
    unit_ids: tuple[str, ...] = ("u1",),
    **scope_filters: Any,
) -> axes.ScopeSharedBackground:
    return axes.ScopeSharedBackground(
        document_id=document_id,
        version_id=version_id,
        unit_ids=unit_ids,
        scope_filters=scope_filters,
    )


def cross_entity_contract(
    *,
    mode: str = "entity_bound",
    targets: tuple[axes.ScopeTarget, ...] = (),
    shared_background: tuple[axes.ScopeSharedBackground, ...] = (),
    bindings: dict[str, str] | None = None,
    refs: dict[str, tuple[dict[str, Any], ...]] | None = None,
    version_bindings: dict[str, rescore.VersionBinding] | None = None,
    case_id: str | None = None,
) -> axes.CrossEntityContract:
    return axes.CrossEntityContract(
        case_id=case_id,
        mode=mode,
        targets=targets,
        shared_background=shared_background,
        bindings=RUN_BINDINGS if bindings is None else bindings,
        refs={} if refs is None else refs,
        version_bindings={} if version_bindings is None else version_bindings,
    )


def version_binding(version_id: str = "ver-2", version_number: int = 2, basis: str = "source_map"):
    return rescore.VersionBinding(version_id=version_id, version_number=version_number, basis=basis)


def lifecycle(
    unit_id: str = "u1",
    *,
    document_deleted: bool | None = False,
    version_state: str | None = "published",
    active: bool | None = True,
    active_version_id: str | None = "ver-2",
    date_state: str = "none",
    effective_from: str | None = None,
    effective_to: str | None = None,
    citation_source_document_id: str | None = "doc-1",
    citation_source_version_id: str | None = "ver-2",
) -> axes.LifecycleView:
    return axes.LifecycleView(
        unit_id=unit_id,
        document_deleted=document_deleted,
        version_state=version_state,
        active=active,
        active_version_id=active_version_id,
        date_state=date_state,
        effective_from=effective_from,
        effective_to=effective_to,
        citation_source_document_id=citation_source_document_id,
        citation_source_version_id=citation_source_version_id,
    )


def stale_source_view(
    units: tuple[rescore.UnitView, ...] = (),
    *,
    lifecycle_map: dict[str, axes.LifecycleView] | None = None,
    actual_as_of: str | None = None,
    include_future: bool | None = None,
    bindings: dict[str, str] | None = None,
    empty_scope_proven: bool | None = None,
    empty_scope_reason: str | None = None,
) -> axes.StaleSourceEvidenceView:
    return axes.StaleSourceEvidenceView(
        units=units,
        lifecycle={} if lifecycle_map is None else lifecycle_map,
        actual_as_of=actual_as_of,
        include_future=include_future,
        bindings=RUN_BINDINGS if bindings is None else bindings,
        empty_scope_proven=empty_scope_proven,
        empty_scope_reason=empty_scope_reason,
    )


def stale_source_contract(
    *,
    constrained_refs: tuple[dict[str, Any], ...] = (),
    refs: dict[str, tuple[dict[str, Any], ...]] | None = None,
    version_bindings: dict[str, rescore.VersionBinding] | None = None,
    bindings: dict[str, str] | None = None,
    case_id: str | None = None,
) -> axes.StaleSourceContract:
    return axes.StaleSourceContract(
        case_id=case_id,
        bindings=RUN_BINDINGS if bindings is None else bindings,
        constrained_refs=constrained_refs,
        refs={} if refs is None else refs,
        version_bindings={} if version_bindings is None else version_bindings,
    )


def case(
    *,
    case_id: str = CASE_ID,
    old: rescore.OldCardCase | None = None,
    anns: dict[str, axes.AxisAnnotation] | None = None,
    cross_user: axes.CrossUserEvidenceView | None = None,
    cross_entity: axes.CrossEntityEvidenceView | None = None,
    cross_entity_contract: axes.CrossEntityContract | None = None,
    stale_source: axes.StaleSourceEvidenceView | None = None,
    stale_source_contract: axes.StaleSourceContract | None = None,
) -> axes.AxesCaseView:
    return axes.AxesCaseView(
        old=old_card(case_id=case_id) if old is None else old,
        annotations={} if anns is None else anns,
        cross_user=cross_user,
        cross_entity=cross_entity,
        cross_entity_contract=cross_entity_contract,
        stale_source=stale_source,
        stale_source_contract=stale_source_contract,
    )


def verdict(view: axes.AxesCaseView, axis: str, *, allow_synthetic: bool = True) -> axes.AxesCaseResult:
    return axes.rescore_axes_case(view, allow_synthetic_fixture=allow_synthetic)


def state(view: axes.AxesCaseView, axis: str, *, allow_synthetic: bool = True) -> tuple[str, str]:
    result = verdict(view, axis, allow_synthetic=allow_synthetic)
    row = result.new_axes[axis]
    return str(row["state"]), str(row["reason"])


def audit_codes(view: axes.AxesCaseView, axis: str, *, allow_synthetic: bool = True) -> set[str]:
    result = verdict(view, axis, allow_synthetic=allow_synthetic)
    return {row.code for row in result.axis_audit[axis]}


def expect(condition: bool, label: str) -> dict[str, Any]:
    return {"label": label, "ok": bool(condition)}


def dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")

