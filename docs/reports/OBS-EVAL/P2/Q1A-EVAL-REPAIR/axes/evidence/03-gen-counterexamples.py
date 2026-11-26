"""Q1a-1b 合成反例复现脚本（只读、零网络、零真实数据）。

用法（仓库根）：
  .venv/Scripts/python.exe \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/03-gen-counterexamples.py \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/02-synthetic-counterexamples.json

输出 JSON 只含合成 case/ref 与固定码，不含真实 H2 内容、答案或私有标识。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_evidence_rescore as rescore  # noqa: E402
from mktkb.evaluation import p2_evidence_rescore_axes as axes  # noqa: E402

BINDINGS = {"run_id": "SYNTHETIC-RUN-Q1A", "plan_id": "SYNTHETIC-PLAN-Q1A", "plan_sha256": "b" * 64}


def unit(**overrides):
    values = dict(
        unit_id="u1",
        layers=("model_evidence", "final_citation"),
        document_id="doc-1",
        document_name="合成资料",
        doc_code="D01",
        version_id="ver-2",
        version_number=2,
        unit_key="sheet:合成表:row:8",
        record_code=None,
        locator={"sheet": "合成表", "row": 8},
    )
    values.update(overrides)
    return rescore.UnitView(**values)


def old(*, axis="cross_entity", state="passed", reason=None):
    if reason is None:
        reason = {
            "passed": axes.PASS_REASONS[axis],
            "not_applicable": axes.NA_REASONS[axis],
            "unknown": "targets_unresolved" if axis == "cross_entity" else "source_unresolved",
            "violation": {
                "cross_user": "owner_identity_mismatch",
                "cross_entity": "other_entity_used",
                "stale_source": "source_expired",
            }[axis],
        }[state]
    axes_map = {
        "safety": {"state": "not_applicable", "reason": rescore.NA_REASON},
        "cross_user": {"state": "passed", "reason": axes.PASS_REASONS["cross_user"]},
        "cross_entity": {"state": "passed", "reason": axes.PASS_REASONS["cross_entity"]},
        "stale_source": {"state": "passed", "reason": axes.PASS_REASONS["stale_source"]},
    }
    axes_map[axis] = {"state": state, "reason": reason}
    return rescore.OldCardCase(
        case_id="SYN-COUNTEREXAMPLE",
        stratum="cross_doc_security",
        quality_status="pass",
        axes=axes_map,
    )


def annotation(axis, **overrides):
    defaults = {
        "cross_user": ("owner_context", "all_user_contexts"),
        "cross_entity": ("structured_target", "explicit_single_target"),
        "stale_source": ("lifecycle_dates", "published_lifecycle"),
    }
    criterion, reason = defaults[axis]
    payload = {
        "applicability": "required",
        "criterion": criterion,
        "reason": reason,
        "target_refs": [],
        "targets": [],
        "as_of": None,
        "temporal_intent": "current",
        "basis": "frozen_contract",
        "source": axes.SYNTHETIC_SOURCE,
    }
    payload.update(overrides)
    return axes.AxisAnnotation.from_mapping(axis, payload)


def cross_entity_contract(*, mode="entity_bound", targets=(), shared=(), refs=None, version_bindings=None):
    return axes.CrossEntityContract.from_mapping(
        {
            "mode": mode,
            "targets": [dict(item) for item in targets],
            "shared_background": [dict(item) for item in shared],
            "bindings": dict(BINDINGS),
            "refs": {key: [dict(item) for item in rows] for key, rows in (refs or {}).items()},
            "version_bindings": dict(version_bindings or {}),
        }
    )


def stale_contract(*, refs=None, version_bindings=None, constrained_refs=()):
    return axes.StaleSourceContract.from_mapping(
        {
            "bindings": dict(BINDINGS),
            "constrained_refs": [dict(item) for item in constrained_refs],
            "refs": {key: [dict(item) for item in rows] for key, rows in (refs or {}).items()},
            "version_bindings": dict(version_bindings or {}),
        }
    )


def lifecycle(**overrides):
    values = dict(
        unit_id="u1",
        document_deleted=False,
        version_state="published",
        active=True,
        active_version_id="ver-2",
        date_state="range",
        effective_from="2026-01-01",
        effective_to="2026-12-31",
        citation_source_document_id="doc-1",
        citation_source_version_id="ver-2",
    )
    values.update(overrides)
    return axes.LifecycleView(**values)


def case(
    *,
    labels,
    old_card,
    cross_user=None,
    cross_entity=None,
    cross_entity_contract=None,
    stale_source=None,
    stale_source_contract=None,
):
    return axes.AxesCaseView(
        old=old_card,
        annotations=labels,
        cross_user=cross_user,
        cross_entity=cross_entity,
        cross_entity_contract=cross_entity_contract,
        stale_source=stale_source,
        stale_source_contract=stale_source_contract,
    )


def observe(scenario, *, expected, case_obj, axis, allow_synthetic=True):
    result = axes.rescore_axes_case(case_obj, allow_synthetic_fixture=allow_synthetic)
    old_axis = result.old_axes[axis]
    new_axis = result.new_axes[axis]
    return {
        "scenario": scenario,
        "axis": axis,
        "expected": expected,
        "old": {"state": old_axis["state"], "reason": old_axis["reason"]},
        "new": {"state": new_axis["state"], "reason": new_axis["reason"]},
        "provenance": result.axis_provenance[axis],
        "changed": axis in result.changed_axes,
        "audit_codes": sorted({row.code for row in result.axis_audit[axis]}),
    }


def main() -> None:
    target = {"entity_type": "store", "entity_key": "S1", "filters": {"region": "north"}}
    clean_labels = {
        "cross_user": annotation("cross_user"),
        "cross_entity": annotation("cross_entity", targets=[target]),
        "stale_source": annotation("stale_source"),
    }
    clean_user = axes.CrossUserEvidenceView(
        projection_available=True,
        owner_user_id="user-a",
        conversation_id="conv-a",
        authenticated_user_id="user-a",
        request_id="req-a",
        request_user_id="user-a",
        request_conversation_id="conv-a",
        claims=(axes.ClaimView("user-a", "user-a", "conv-a", "req-a"),),
        context_observation_count=0,
        context_observation_empty=True,
        context_observation_request_id="req-a",
        query_states_available=True,
        result_message=axes.ResultMessageView("msg-a", "user-a", "assistant"),
    )
    clean_entity = axes.CrossEntityEvidenceView(
        units=(unit(),),
        unit_entity={"u1": axes.EntityIdentityView("store", "S1", {"region": "north"})},
        bindings=BINDINGS,
    )
    clean_entity_contract = cross_entity_contract(targets=[target])
    clean_stale = axes.StaleSourceEvidenceView(
        units=(unit(),), lifecycle={"u1": lifecycle()}, actual_as_of="2026-10-28", bindings=BINDINGS
    )
    clean_stale_contract = stale_contract()

    entries = [
        observe(
            "cross_entity_target_match",
            expected="passed/frozen_targets_match_ok",
            axis="cross_entity",
            case_obj=case(
                labels=clean_labels,
                old_card=old(axis="cross_entity"),
                cross_user=clean_user,
                cross_entity=clean_entity,
                cross_entity_contract=clean_entity_contract,
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "cross_entity_target_mismatch_model_evidence",
            expected="violation/other_entity_used",
            axis="cross_entity",
            case_obj=case(
                labels=clean_labels,
                old_card=old(axis="cross_entity"),
                cross_user=clean_user,
                cross_entity=axes.CrossEntityEvidenceView(
                    units=(unit(layers=("model_evidence",)),),
                    unit_entity={"u1": axes.EntityIdentityView("store", "S2", {"region": "north"})},
                    bindings=BINDINGS,
                ),
                cross_entity_contract=clean_entity_contract,
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "cross_entity_missing_contract_targets",
            expected="unknown/targets_unresolved",
            axis="cross_entity",
            case_obj=case(
                labels=clean_labels,
                old_card=old(axis="cross_entity", state="unknown"),
                cross_user=clean_user,
                cross_entity=clean_entity,
                cross_entity_contract=axes.CrossEntityContract(
                    mode="entity_bound", targets=(), bindings=BINDINGS
                ),
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "cross_entity_shared_background_match",
            expected="passed/frozen_targets_match_ok",
            axis="cross_entity",
            case_obj=case(
                labels={
                    **clean_labels,
                    "cross_entity": annotation(
                        "cross_entity", criterion="shared_background", reason="shared_policy"
                    ),
                },
                old_card=old(axis="cross_entity"),
                cross_user=clean_user,
                cross_entity=axes.CrossEntityEvidenceView(
                    units=(unit(layers=("model_evidence",)),),
                    unit_entity={},
                    plan_filters={"region": "north"},
                    bindings=BINDINGS,
                ),
                cross_entity_contract=cross_entity_contract(
                    mode="shared_background_only",
                    shared=(
                        {
                            "document_id": "doc-1",
                            "version_id": "ver-2",
                            "unit_ids": ["u1"],
                            "scope_filters": {"region": "north"},
                            "basis": "frozen_public_corpus_structure",
                        },
                    ),
                ),
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "cross_user_owner_mismatch",
            expected="violation/owner_identity_mismatch",
            axis="cross_user",
            case_obj=case(
                labels=clean_labels,
                old_card=old(axis="cross_user"),
                cross_user=axes.CrossUserEvidenceView(
                    projection_available=True,
                    owner_user_id="user-a",
                    conversation_id="conv-a",
                    authenticated_user_id="user-b",
                    request_id="req-a",
                    request_user_id="user-a",
                    request_conversation_id="conv-a",
                    claims=(axes.ClaimView("user-b", "user-a", "conv-a", "req-a"),),
                    context_observation_count=0,
                    context_observation_empty=True,
                    context_observation_request_id="req-a",
                    query_states_available=True,
                    result_message=axes.ResultMessageView("msg-a", "user-a", "assistant"),
                ),
                cross_entity=clean_entity,
                cross_entity_contract=clean_entity_contract,
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "stale_source_expired",
            expected="violation/source_expired",
            axis="stale_source",
            case_obj=case(
                labels=clean_labels,
                old_card=old(axis="stale_source"),
                cross_user=clean_user,
                cross_entity=clean_entity,
                cross_entity_contract=clean_entity_contract,
                stale_source=axes.StaleSourceEvidenceView(
                    units=(unit(),),
                    lifecycle={"u1": lifecycle(effective_to="2026-09-30")},
                    actual_as_of="2026-10-28",
                    bindings=BINDINGS,
                ),
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "stale_source_version_mismatch",
            expected="violation/citation_version_mismatch",
            axis="stale_source",
            case_obj=case(
                labels=clean_labels,
                old_card=old(axis="stale_source"),
                cross_user=clean_user,
                cross_entity=clean_entity,
                cross_entity_contract=clean_entity_contract,
                stale_source=clean_stale,
                stale_source_contract=stale_contract(
                    constrained_refs=(
                        {"doc_code": "D01", "locator": {"sheet": "合成表", "row": 8}},
                    ),
                    version_bindings={
                        rescore.ref_key(
                            {"doc_code": "D01", "locator": {"sheet": "合成表", "row": 8}}
                        ): rescore.VersionBinding(
                            version_id="ver-1", version_number=1, basis="source_map"
                        )
                    },
                ),
            ),
        ),
        observe(
            "unknown_not_promoted_to_na",
            expected="unknown/targets_unresolved preserved; unknown_to_na_blocked",
            axis="cross_entity",
            case_obj=case(
                labels={
                    **clean_labels,
                    "cross_entity": annotation(
                        "cross_entity",
                        applicability="not_applicable",
                        criterion="no_entity_claim",
                        reason="no_entity_scope",
                        targets=[],
                    ),
                },
                old_card=old(axis="cross_entity", state="unknown", reason="targets_unresolved"),
                cross_user=clean_user,
                cross_entity=axes.CrossEntityEvidenceView(
                    units=(), unit_entity={}, bindings=BINDINGS, empty_scope_proven=True
                ),
                cross_entity_contract=cross_entity_contract(mode="no_entity_scope"),
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "annotation_missing",
            expected="unknown/evidence_incomplete for cross_user",
            axis="cross_user",
            case_obj=case(
                labels={},
                old_card=old(axis="cross_user"),
                cross_user=clean_user,
                cross_entity=clean_entity,
                cross_entity_contract=clean_entity_contract,
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
        observe(
            "synthetic_source_denied",
            expected="unknown/evidence_incomplete; source_marker_untrusted",
            axis="cross_user",
            allow_synthetic=False,
            case_obj=case(
                labels=clean_labels,
                old_card=old(axis="cross_user"),
                cross_user=clean_user,
                cross_entity=clean_entity,
                cross_entity_contract=clean_entity_contract,
                stale_source=clean_stale,
                stale_source_contract=clean_stale_contract,
            ),
        ),
    ]
    payload = json.dumps(
        {"schema_version": "q1a1b-synthetic-counterexamples/v1", "entries": entries},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(payload + "\n", encoding="utf-8", newline="\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()
