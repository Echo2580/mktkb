#!/usr/bin/env python
"""探针 11：三轴语义自建反例（独立验收自建；不复用开发者用例）。

期望值按契约 v0.2 §5 / §6 逐条手写，先写期望再看实现结果；不一致即记录为差异。
输出：11-axis-semantics.out.json
"""

from __future__ import annotations

import json
from typing import Any

from _common import (
    HERE,
    OTHER_BINDINGS,
    RUN_BINDINGS,
    annotation,
    audit_codes,
    case,
    cross_entity_contract,
    cross_entity_view,
    cross_user_view,
    dump,
    lifecycle,
    old_card,
    rescore,
    axes,
    ref,
    scope_target,
    shared_entry,
    stale_source_contract,
    stale_source_view,
    unit,
    version_binding,
)

RESULTS: list[dict[str, Any]] = []


def check(
    label: str,
    view: axes.AxesCaseView,
    axis: str,
    want_state: str,
    want_reason: str | None = None,
    *,
    want_audit: tuple[str, ...] = (),
    forbid_audit: tuple[str, ...] = (),
    allow_synthetic: bool = True,
) -> None:
    result = axes.rescore_axes_case(view, allow_synthetic_fixture=allow_synthetic)
    row = result.new_axes[axis]
    codes = {item.code for item in result.axis_audit[axis]}
    ok_state = row["state"] == want_state
    ok_reason = want_reason is None or row["reason"] == want_reason
    ok_audit = set(want_audit) <= codes
    ok_forbid = not (set(forbid_audit) & codes)
    RESULTS.append(
        {
            "label": label,
            "axis": axis,
            "expected": {"state": want_state, "reason": want_reason, "audit": list(want_audit)},
            "actual": {"state": row["state"], "reason": row["reason"], "audit": sorted(codes)},
            "ok": ok_state and ok_reason and ok_audit and ok_forbid,
        }
    )


def anns(**kwargs: axes.AxisAnnotation) -> dict[str, axes.AxisAnnotation]:
    return dict(kwargs)


def plain_case(**kwargs: Any) -> axes.AxesCaseView:
    return case(**kwargs)


# --------------------------------------------------------------------------- #
# A. 注解门（三轴共享，缺字段/坏枚举/不可信来源 → unknown，不 raise）
# --------------------------------------------------------------------------- #
def annotation_gate_cases() -> None:
    base_user = cross_user_view()
    for axis, unknown_reason in (
        ("cross_user", "evidence_incomplete"),
        ("cross_entity", "annotation_unknown"),
        ("stale_source", "annotation_unknown"),
    ):
        check(
            f"{axis}: annotation object missing -> unknown",
            plain_case(cross_user=base_user, cross_entity=cross_entity_view(), stale_source=stale_source_view()),
            axis,
            "unknown",
            unknown_reason,
            want_audit=("annotation_object_missing",),
        )

    # 缺 7 字段之一
    partial = {
        "applicability": "required",
        "criterion": "owner_context",
        "reason": "all_user_contexts",
        # target_refs 缺失
        "targets": [],
        "as_of": None,
        "temporal_intent": "current",
        "basis": "synthetic_fixture",
        "source": "synthetic_fixture",
    }
    bad = axes.AxisAnnotation.from_mapping("cross_user", partial)
    check(
        "cross_user: 7-field missing -> unknown annotation_field_missing",
        plain_case(anns=anns(cross_user=bad), cross_user=base_user),
        "cross_user",
        "unknown",
        "evidence_incomplete",
        want_audit=("annotation_field_missing",),
    )

    # 多字段
    extra = dict(partial)
    extra["target_refs"] = []
    extra["extra_key"] = 1
    bad_extra = axes.AxisAnnotation.from_mapping("cross_user", extra)
    check(
        "cross_user: extra key -> unknown annotation_field_invalid",
        plain_case(anns=anns(cross_user=bad_extra), cross_user=base_user),
        "cross_user",
        "unknown",
        "evidence_incomplete",
        want_audit=("annotation_field_invalid",),
    )

    # 坏 applicability 枚举
    bad_enum = dict(partial, target_refs=[], applicability="maybe")
    check(
        "cross_user: bad applicability -> unknown",
        plain_case(anns=anns(cross_user=axes.AxisAnnotation.from_mapping("cross_user", bad_enum)), cross_user=base_user),
        "cross_user",
        "unknown",
        "evidence_incomplete",
        want_audit=("annotation_field_invalid",),
    )

    # basis / source 缺失
    no_basis = {k: v for k, v in dict(partial, target_refs=[]).items() if k not in ("basis", "source")}
    parsed = axes.AxisAnnotation.from_mapping("cross_user", no_basis)
    check(
        "cross_user: basis+source missing -> unknown with basis_missing/source_marker_missing",
        plain_case(anns=anns(cross_user=parsed), cross_user=base_user),
        "cross_user",
        "unknown",
        "evidence_incomplete",
        want_audit=("basis_missing", "source_marker_missing"),
    )

    # synthetic source 在 allow_synthetic_fixture=False 下不可信
    synthetic_ok = annotation("cross_user")
    check(
        "cross_user: synthetic source rejected when allow_synthetic_fixture=False",
        plain_case(anns=anns(cross_user=synthetic_ok), cross_user=base_user),
        "cross_user",
        "unknown",
        "evidence_incomplete",
        want_audit=("source_marker_untrusted",),
        allow_synthetic=False,
    )
    check(
        "cross_user: synthetic source accepted when allow_synthetic_fixture=True",
        plain_case(anns=anns(cross_user=synthetic_ok), cross_user=base_user),
        "cross_user",
        "passed",
        "all_user_contexts_ok",
        allow_synthetic=True,
    )

    # unresolved source 永远不可信
    check(
        "cross_user: source=unresolved always untrusted",
        plain_case(
            anns=anns(cross_user=annotation("cross_user", source="unresolved")),
            cross_user=base_user,
        ),
        "cross_user",
        "unknown",
        "evidence_incomplete",
        want_audit=("source_marker_untrusted",),
    )

    # applicability=unknown / criterion=unknown
    check(
        "cross_entity: applicability=unknown -> unknown annotation_unknown_scope",
        plain_case(
            anns=anns(cross_entity=annotation("cross_entity", applicability="unknown")),
            cross_entity=cross_entity_view(),
            cross_entity_contract=cross_entity_contract(mode="no_entity_scope"),
        ),
        "cross_entity",
        "unknown",
        "annotation_unknown",
        want_audit=("annotation_unknown_scope",),
    )
    check(
        "stale_source: criterion=unknown -> unknown",
        plain_case(
            anns=anns(stale_source=annotation("stale_source", criterion="unknown")),
            stale_source=stale_source_view(),
            stale_source_contract=stale_source_contract(),
        ),
        "stale_source",
        "unknown",
        "annotation_unknown",
        want_audit=("annotation_unknown_scope",),
    )

    # 不确定 reason 必须直接 unknown，不能靠证据猜
    check(
        "cross_entity: reason=ambiguous_semantics -> unknown (no guessing)",
        plain_case(
            anns=anns(cross_entity=annotation("cross_entity", reason="ambiguous_semantics")),
            cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K1")}),
            cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
        ),
        "cross_entity",
        "unknown",
        "annotation_unknown",
        want_audit=("annotation_reason_uncertain",),
    )


# --------------------------------------------------------------------------- #
# B. cross_user
# --------------------------------------------------------------------------- #
def cross_user_cases() -> None:
    good = cross_user_view()

    check("cross_user: fully consistent -> passed", plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=good), "cross_user", "passed", "all_user_contexts_ok")

    # N/A 非法：必须 unknown，且不得 N/A
    view = plain_case(anns=anns(cross_user=annotation("cross_user", applicability="not_applicable")), cross_user=good)
    check(
        "cross_user: not_applicable illegal -> unknown never N-A",
        view,
        "cross_user",
        "unknown",
        None,
        want_audit=("scope_mode_mismatch",),
        forbid_audit=(),
    )
    result = axes.rescore_axes_case(view, allow_synthetic_fixture=True)
    RESULTS.append(
        {
            "label": "cross_user: N/A reason inside frozen cross_user unknown table",
            "ok": result.new_axes["cross_user"]["reason"] in axes.UNKNOWN_REASONS["cross_user"],
            "actual": result.new_axes["cross_user"]["reason"],
        }
    )

    check("cross_user: projection unavailable -> unknown projection_unavailable",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(projection_available=False)),
          "cross_user", "unknown", "projection_unavailable", want_audit=("projection_unavailable",))

    check("cross_user: missing request_id -> unknown projection_unavailable",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(request_id=None)),
          "cross_user", "unknown", "projection_unavailable")

    check("cross_user: zero claims -> unknown claim_missing",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(claims=())),
          "cross_user", "unknown", "claim_missing", want_audit=("claim_missing",))

    check("cross_user: two claims -> unknown claim_missing",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(claims=(
              axes.ClaimView("user-A", "user-A", "conv-A", "req-A"),
              axes.ClaimView("user-A", "user-A", "conv-A", "req-A"),
          ))),
          "cross_user", "unknown", "claim_missing")

    check("cross_user: authenticated identity missing -> unknown identity_projection_mismatch",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(authenticated_user_id=None)),
          "cross_user", "unknown", "identity_projection_mismatch", want_audit=("identity_missing",))

    check("cross_user: authenticated != owner -> violation owner_identity_mismatch",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(authenticated_user_id="user-B")),
          "cross_user", "violation", "owner_identity_mismatch", want_audit=("owner_identity_mismatch",))

    check("cross_user: claim owner != owner -> violation owner_identity_mismatch",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(claims=(
              axes.ClaimView("user-A", "user-B", "conv-A", "req-A"),
          ))),
          "cross_user", "violation", "owner_identity_mismatch")

    check("cross_user: claim request != request -> unknown identity_projection_mismatch",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(claims=(
              axes.ClaimView("user-A", "user-A", "conv-A", "req-X"),
          ))),
          "cross_user", "unknown", "identity_projection_mismatch")

    check("cross_user: request.user != owner -> violation request_owner_mismatch",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(request_user_id="user-B")),
          "cross_user", "violation", "request_owner_mismatch", want_audit=("request_owner_mismatch",))

    check("cross_user: context count mismatch -> unknown context_evidence_missing",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(context_observation_count=3)),
          "cross_user", "unknown", "context_evidence_missing")

    check("cross_user: context owner other -> violation other_user_context",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(context_messages=(
              axes.ContextMessageView(1, "user-B", "req-A"),
          ))),
          "cross_user", "violation", "other_user_context", want_audit=("context_owner_mismatch",))

    check("cross_user: query state stored other user -> violation other_user_query_state",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(query_states=(
              axes.QueryStateRowView("user-B", "conv-A"),
          ))),
          "cross_user", "violation", "other_user_query_state", want_audit=("query_state_owner_mismatch",))

    check("cross_user: query state projection unavailable -> unknown query_state_unavailable",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(query_states_available=None)),
          "cross_user", "unknown", "query_state_unavailable", want_audit=("query_state_unavailable",))

    check("cross_user: entity inheritance from other user -> violation other_user_entity_inheritance",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(entity_inheritance=(
              axes.EntityInheritanceView("msg-1", "user-B", "assistant"),
          ))),
          "cross_user", "violation", "other_user_entity_inheritance", want_audit=("entity_inheritance_owner_mismatch",))

    check("cross_user: result message missing -> unknown result_message_unavailable",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(result_message=None)),
          "cross_user", "unknown", "result_message_unavailable", want_audit=("result_message_unavailable",))

    check("cross_user: result owner mismatch -> violation result_message_owner_mismatch",
          plain_case(anns=anns(cross_user=annotation("cross_user")), cross_user=cross_user_view(result_message=axes.ResultMessageView("res-1", "user-B", "assistant"))),
          "cross_user", "violation", "result_message_owner_mismatch", want_audit=("result_message_owner_mismatch",))


# --------------------------------------------------------------------------- #
# C. cross_entity
# --------------------------------------------------------------------------- #
def entity_bound_view(*, entity: tuple[str | None, str | None] | None = ("item", "K1"), unit_obj=None, **kwargs: Any):
    u = unit("u1") if unit_obj is None else unit_obj
    unit_entity = {} if entity is None else {"u1": axes.EntityIdentityView(entity[0], entity[1])}
    return cross_entity_view(units=(u,), unit_entity=unit_entity, **kwargs)


def cross_entity_cases() -> None:
    ann = annotation("cross_entity", targets=[{"entity_type": "item", "entity_key": "K1", "filters": {}}])

    check("cross_entity: target match -> passed frozen_targets_match_ok",
          plain_case(anns=anns(cross_entity=ann), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "passed", "frozen_targets_match_ok", want_audit=("target_matched",))

    check("cross_entity: other entity in model_evidence -> violation other_entity_used",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(entity=("item", "K2")),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "violation", "other_entity_used", want_audit=("target_mismatch",))

    check("cross_entity: other entity citation-only -> violation citation_entity_mismatch",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")),
                     cross_entity=entity_bound_view(entity=("item", "K2"), unit_obj=unit("u1", layers=("final_citation",))),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "violation", "citation_entity_mismatch")

    check("cross_entity: contract missing -> unknown targets_unresolved",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view()),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("contract_missing",))

    check("cross_entity: entity_bound with zero targets -> unknown targets_unresolved",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(mode="entity_bound", targets=())),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("targets_missing",))

    check("cross_entity: entity_bound targets incomplete -> unknown",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(
                         mode="entity_bound",
                         targets=(axes.ScopeTarget("", "K1"),),
                     )),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("targets_incomplete",))

    check("cross_entity: contract bindings mismatch -> unknown",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),), bindings=OTHER_BINDINGS)),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("contract_binding_mismatch",))

    check("cross_entity: contract bindings missing -> unknown",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),), bindings={})),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("contract_binding_missing",))

    check("cross_entity: contract case mismatch -> unknown",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),), case_id="OTHER")),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("contract_case_mismatch",))

    check("cross_entity: annotation targets != contract targets -> unknown targets_unresolved",
          plain_case(anns=anns(cross_entity=annotation("cross_entity", targets=[{"entity_type": "item", "entity_key": "K9", "filters": {}}])),
                     cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("annotation_targets_mismatch",))

    check("cross_entity: multi_target with one contract target -> unknown targets_incomplete",
          plain_case(anns=anns(cross_entity=annotation("cross_entity", criterion="multi_target")), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "unknown", "targets_unresolved", want_audit=("targets_incomplete",))

    # N/A 合法路径
    na_ann = annotation("cross_entity", applicability="not_applicable", criterion="no_entity_claim", reason="no_entity_scope")
    check("cross_entity: verified no-entity scope -> not_applicable",
          plain_case(anns=anns(cross_entity=na_ann), cross_entity=cross_entity_view(units=(), empty_scope_proven=True),
                     cross_entity_contract=cross_entity_contract(mode="no_entity_scope")),
          "cross_entity", "not_applicable", "no_entity_scope_verified", want_audit=("empty_scope_proven",))

    check("cross_entity: N/A but contract entity_bound -> unknown entity_scope_conflict",
          plain_case(anns=anns(cross_entity=na_ann), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "unknown", "entity_scope_conflict", want_audit=("scope_mode_mismatch",))

    check("cross_entity: N/A with wrong criterion -> unknown annotation_unknown",
          plain_case(anns=anns(cross_entity=annotation("cross_entity", applicability="not_applicable", criterion="structured_target", reason="no_entity_scope")),
                     cross_entity=cross_entity_view(units=(), empty_scope_proven=True),
                     cross_entity_contract=cross_entity_contract(mode="no_entity_scope")),
          "cross_entity", "unknown", "annotation_unknown", want_audit=("scope_mode_mismatch",))

    check("cross_entity: required but contract no_entity_scope -> unknown entity_scope_conflict",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(mode="no_entity_scope")),
          "cross_entity", "unknown", "entity_scope_conflict")

    # shared_background_only
    shared_ann = annotation("cross_entity", criterion="shared_background", reason="shared_policy")
    check("cross_entity: shared background covered -> passed",
          plain_case(anns=anns(cross_entity=shared_ann),
                     cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={}, plan_filters={"topic": "policy"}),
                     cross_entity_contract=cross_entity_contract(mode="shared_background_only",
                                                                  shared_background=(shared_entry(topic="policy"),))),
          "cross_entity", "passed", "frozen_targets_match_ok", want_audit=("shared_background_matched",))

    check("cross_entity: shared background plan_filters missing -> unknown",
          plain_case(anns=anns(cross_entity=shared_ann),
                     cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={}),
                     cross_entity_contract=cross_entity_contract(mode="shared_background_only",
                                                                  shared_background=(shared_entry(),))),
          "cross_entity", "unknown", "free_text_attribution_unverifiable", want_audit=("plan_filters_missing",))

    check("cross_entity: shared background unproven unit -> unknown",
          plain_case(anns=anns(cross_entity=shared_ann),
                     cross_entity=cross_entity_view(units=(unit("u9"),), unit_entity={}, plan_filters={}),
                     cross_entity_contract=cross_entity_contract(mode="shared_background_only",
                                                                  shared_background=(shared_entry(unit_ids=("u1",)),))),
          "cross_entity", "unknown", "free_text_attribution_unverifiable", want_audit=("shared_background_unproven",))

    check("cross_entity: structured entity inside shared_background mode -> unknown entity_scope_conflict",
          plain_case(anns=anns(cross_entity=shared_ann), cross_entity=entity_bound_view(),
                     cross_entity_contract=cross_entity_contract(mode="shared_background_only", shared_background=(shared_entry(),))),
          "cross_entity", "unknown", "entity_scope_conflict")

    # entity_bound 自由文本归属
    check("cross_entity: entity_bound free-text unit unverifiable -> unknown",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")),
                     cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={}),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "unknown", "free_text_attribution_unverifiable", want_audit=("shared_background_unproven",))

    check("cross_entity: entity identity incomplete -> unknown entity_identity_unresolved",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=entity_bound_view(entity=("item", None)),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "unknown", "entity_identity_unresolved", want_audit=("entity_identity_missing",))

    # target_ref 与实体身份冲突
    ref_ok = ref()
    check("cross_entity: target_ref matched but entity conflicts -> unknown entity_scope_conflict",
          plain_case(anns=anns(cross_entity=annotation("cross_entity", target_refs=[{"collection": "expected_sources", "index": 0}])),
                     cross_entity=entity_bound_view(entity=("item", "K2")),
                     cross_entity_contract=cross_entity_contract(
                         targets=(scope_target("item", "K1"),),
                         refs={"expected_sources": (ref_ok,)},
                         version_bindings={rescore.ref_key(ref_ok): version_binding()},
                     )),
          "cross_entity", "unknown", "entity_scope_conflict", want_audit=("target_ref_conflict",))

    # facts
    check("cross_entity: direct fact matching target -> passed",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")),
                     cross_entity=cross_entity_view(
                         units=(unit("u1"),),
                         unit_entity={"u1": axes.EntityIdentityView("item", "K1")},
                         facts=(axes.EntityFactView("K1", "u1"),),
                     ),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "passed", "frozen_targets_match_ok")

    check("cross_entity: direct fact other entity -> violation other_entity_used",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")),
                     cross_entity=cross_entity_view(
                         units=(unit("u1"),),
                         unit_entity={"u1": axes.EntityIdentityView("item", "K2")},
                         facts=(axes.EntityFactView("K2", "u1"),),
                     ),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "violation", "other_entity_used")

    check("cross_entity: fact without backing unit -> unknown entity_identity_unresolved",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")),
                     cross_entity=cross_entity_view(facts=(axes.EntityFactView("K1", "u-missing"),)),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "unknown", "entity_identity_unresolved")

    # 空集
    check("cross_entity: empty scope proven -> passed",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=cross_entity_view(units=(), empty_scope_proven=True),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "passed", "frozen_targets_match_ok", want_audit=("empty_scope_proven",))

    check("cross_entity: empty scope not proven -> unknown empty_set_not_proven",
          plain_case(anns=anns(cross_entity=annotation("cross_entity")), cross_entity=cross_entity_view(units=()),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "unknown", "empty_set_not_proven", want_audit=("empty_scope_not_proven",))

    # 旧 unknown 不得降级 N/A
    view = plain_case(
        old=old_card(cross_entity=("unknown", "targets_unresolved")),
        anns=anns(cross_entity=na_ann),
        cross_entity=cross_entity_view(units=(), empty_scope_proven=True),
        cross_entity_contract=cross_entity_contract(mode="no_entity_scope"),
    )
    result = axes.rescore_axes_case(view, allow_synthetic_fixture=True)
    RESULTS.append(
        {
            "label": "cross_entity: old unknown stays unknown, N/A blocked",
            "expected": {"state": "unknown", "reason": "targets_unresolved", "provenance": "preserved_old_verdict"},
            "actual": {
                "state": result.new_axes["cross_entity"]["state"],
                "reason": result.new_axes["cross_entity"]["reason"],
                "provenance": result.axis_provenance["cross_entity"],
                "audit": sorted({row.code for row in result.axis_audit["cross_entity"]}),
            },
            "ok": result.new_axes["cross_entity"]["state"] == "unknown"
            and result.new_axes["cross_entity"]["reason"] == "targets_unresolved"
            and result.axis_provenance["cross_entity"] == "preserved_old_verdict"
            and {"unknown_to_na_blocked"} <= {row.code for row in result.axis_audit["cross_entity"]},
        }
    )

    # 旧 unknown 可被新证据重评为 pass（合同未禁止）
    check("cross_entity: old unknown can be rescored to pass",
          plain_case(old=old_card(cross_entity=("unknown", "targets_unresolved")),
                     anns=anns(cross_entity=annotation("cross_entity")),
                     cross_entity=cross_entity_view(units=(), empty_scope_proven=True),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "passed", "frozen_targets_match_ok")

    # 旧 violation 命中前置门 -> 保留
    preserved = plain_case(
        old=old_card(cross_entity=("violation", "other_entity_used"), missing_codes=("branch_evidence_missing",)),
        anns=anns(cross_entity=annotation("cross_entity")),
        cross_entity=entity_bound_view(),
        cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
    )
    result = axes.rescore_axes_case(preserved, allow_synthetic_fixture=True)
    RESULTS.append(
        {
            "label": "cross_entity: old violation preserved on gate code",
            "expected": {"state": "violation", "reason": "other_entity_used", "provenance": "preserved_old_verdict"},
            "actual": {
                "state": result.new_axes["cross_entity"]["state"],
                "reason": result.new_axes["cross_entity"]["reason"],
                "provenance": result.axis_provenance["cross_entity"],
                "audit": sorted({row.code for row in result.axis_audit["cross_entity"]}),
            },
            "ok": result.new_axes["cross_entity"]["state"] == "violation"
            and result.new_axes["cross_entity"]["reason"] == "other_entity_used"
            and result.axis_provenance["cross_entity"] == "preserved_old_verdict"
            and {"old_verdict_preserved", "preserved_gate"} <= {row.code for row in result.axis_audit["cross_entity"]},
        }
    )

    # 旧 violation 无 gate -> 正常重评，不得静默升级为 pass（新证据不支持则仍 violation/unknown）
    check("cross_entity: old violation without gate is rescored (not silently upgraded)",
          plain_case(old=old_card(cross_entity=("violation", "other_entity_used")),
                     anns=anns(cross_entity=annotation("cross_entity")),
                     cross_entity=entity_bound_view(entity=("item", "K2")),
                     cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),))),
          "cross_entity", "violation", "other_entity_used")


# --------------------------------------------------------------------------- #
# D. stale_source
# --------------------------------------------------------------------------- #
def stale_case(*, ann_kwargs: dict[str, Any] | None = None, ev_kwargs: dict[str, Any] | None = None,
               contract_kwargs: dict[str, Any] | None = None, old: rescore.OldCardCase | None = None):
    ev = {
        "units": (unit("u1"),),
        "lifecycle_map": {"u1": lifecycle()},
        "actual_as_of": "2026-10-28",
    }
    ev.update(ev_kwargs or {})
    contract = {"constrained_refs": (ref(),), "version_bindings": {rescore.ref_key(ref()): version_binding()}}
    contract.update(contract_kwargs or {})
    return plain_case(
        old=old_card(stale_source=None) if old is None else old,
        anns=anns(stale_source=annotation("stale_source", **(ann_kwargs or {}))),
        stale_source=stale_source_view(**ev),
        stale_source_contract=stale_source_contract(**contract),
    )


def stale_source_cases() -> None:
    check("stale_source: consistent published/active -> passed", stale_case(), "stale_source", "passed", "lifecycle_dates_ok", want_audit=("lifecycle_checked", "version_match"))

    check("stale_source: deleted document -> violation source_deleted",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(document_deleted=True)}}),
          "stale_source", "violation", "source_deleted", want_audit=("source_deleted",))

    check("stale_source: not published -> violation source_not_published",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(version_state="not_published")}}),
          "stale_source", "violation", "source_not_published")

    check("stale_source: inactive -> violation source_not_active",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(active=False)}}),
          "stale_source", "violation", "source_not_active")

    check("stale_source: active but different active version -> violation source_not_active",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(active_version_id="ver-9")}}),
          "stale_source", "violation", "source_not_active")

    check("stale_source: lifecycle missing for used unit -> unknown lifecycle_unavailable",
          stale_case(ev_kwargs={"lifecycle_map": {}}),
          "stale_source", "unknown", "lifecycle_unavailable", want_audit=("lifecycle_unavailable",))

    check("stale_source: document_deleted None -> unknown lifecycle_unavailable",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(document_deleted=None)}}),
          "stale_source", "unknown", "lifecycle_unavailable")

    check("stale_source: date_state ambiguous -> unknown date_unresolved",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="ambiguous")}}),
          "stale_source", "unknown", "date_unresolved", want_audit=("date_unresolved",))

    check("stale_source: date_state unavailable -> unknown lifecycle_unavailable",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="unavailable")}}),
          "stale_source", "unknown", "lifecycle_unavailable")

    check("stale_source: range without boundaries -> unknown date_unresolved",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range")}}),
          "stale_source", "unknown", "date_unresolved")

    check("stale_source: future source as current -> violation future_source_as_current",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range", effective_from="2026-11-01")}}),
          "stale_source", "violation", "future_source_as_current", want_audit=("future_source_as_current",))

    check("stale_source: future_explicit + include_future=True -> passed",
          stale_case(ann_kwargs={"temporal_intent": "future_explicit", "as_of": "2026-10-28"},
                     ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range", effective_from="2026-11-01")}, "include_future": True}),
          "stale_source", "passed", "lifecycle_dates_ok")

    check("stale_source: future_explicit + include_future=False -> violation",
          stale_case(ann_kwargs={"temporal_intent": "future_explicit", "as_of": "2026-10-28"},
                     ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range", effective_from="2026-11-01")}, "include_future": False}),
          "stale_source", "violation", "future_source_as_current")

    check("stale_source: future_explicit + include_future=None -> unknown annotation_unknown",
          stale_case(ann_kwargs={"temporal_intent": "future_explicit", "as_of": "2026-10-28"},
                     ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range", effective_from="2026-11-01")}, "include_future": None}),
          "stale_source", "unknown", "annotation_unknown", want_audit=("include_future_missing",))

    check("stale_source: expired source -> violation source_expired",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range", effective_from="2026-01-01", effective_to="2026-10-01")}}),
          "stale_source", "violation", "source_expired", want_audit=("source_expired",))

    check("stale_source: dated source without actual as_of -> unknown as_of_missing",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range", effective_from="2026-01-01")}, "actual_as_of": None}),
          "stale_source", "unknown", "as_of_missing", want_audit=("as_of_missing",))

    check("stale_source: annotation as_of conflicts actual -> violation date_intent_conflict",
          stale_case(ann_kwargs={"as_of": "2026-10-01"},
                     ev_kwargs={"lifecycle_map": {"u1": lifecycle(date_state="range", effective_from="2026-01-01")}}),
          "stale_source", "violation", "date_intent_conflict", want_audit=("date_conflict",))

    check("stale_source: constrained ref version mismatch -> violation citation_version_mismatch",
          stale_case(contract_kwargs={"version_bindings": {rescore.ref_key(ref()): version_binding("ver-1", 1)}}),
          "stale_source", "violation", "citation_version_mismatch", want_audit=("version_mismatch",))

    check("stale_source: constrained ref binding missing -> unknown source_unresolved",
          stale_case(contract_kwargs={"version_bindings": {}}),
          "stale_source", "unknown", "source_unresolved", want_audit=("version_binding_missing",))

    check("stale_source: final citation source unresolvable -> unknown citation_source_unresolved",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(citation_source_document_id=None)}}),
          "stale_source", "unknown", "citation_source_unresolved", want_audit=("citation_source_unresolved",))

    check("stale_source: final citation document mismatch -> violation citation_version_mismatch",
          stale_case(ev_kwargs={"lifecycle_map": {"u1": lifecycle(citation_source_document_id="doc-9")}},
                     contract_kwargs={}),
          "stale_source", "violation", "citation_version_mismatch")

    check("stale_source: not_applicable illegal -> unknown annotation_unknown",
          stale_case(ann_kwargs={"applicability": "not_applicable"}),
          "stale_source", "unknown", "annotation_unknown", want_audit=("scope_mode_mismatch",))

    check("stale_source: no units + proven empty scope -> passed",
          stale_case(ev_kwargs={"units": (), "lifecycle_map": {}, "empty_scope_proven": True}),
          "stale_source", "passed", "lifecycle_dates_ok", want_audit=("empty_scope_proven",))

    check("stale_source: no units + unproven empty scope -> unknown empty_set_not_proven",
          stale_case(ev_kwargs={"units": (), "lifecycle_map": {}}),
          "stale_source", "unknown", "empty_set_not_proven")

    # 旧 unknown 不得降级 N/A：stale_source 的 N/A 在注解门就被拒，仍是 unknown
    view = plain_case(
        old=old_card(stale_source=("unknown", "source_unresolved")),
        anns=anns(stale_source=annotation("stale_source", applicability="not_applicable")),
        stale_source=stale_source_view(units=(), lifecycle_map={}, empty_scope_proven=True, bindings=RUN_BINDINGS),
        stale_source_contract=stale_source_contract(),
    )
    result = axes.rescore_axes_case(view, allow_synthetic_fixture=True)
    codes = {row.code for row in result.axis_audit["stale_source"]}
    RESULTS.append(
        {
            "label": "stale_source: old unknown never upgraded to N/A/pass",
            "expected": {"state": "unknown", "reason": "annotation_unknown", "audit": ["scope_mode_mismatch"]},
            "actual": {
                "state": result.new_axes["stale_source"]["state"],
                "reason": result.new_axes["stale_source"]["reason"],
                "audit": sorted(codes),
            },
            "ok": result.new_axes["stale_source"]["state"] == "unknown"
            and "scope_mode_mismatch" in codes,
        }
    )

    # quality_status=error 覆盖
    check("stale_source: old error quality -> unknown turn_error",
          plain_case(old=old_card(stale_source=("passed", "lifecycle_dates_ok"), quality_status="error"),
                     anns=anns(stale_source=annotation("stale_source")),
                     stale_source=stale_source_view(units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28"),
                     stale_source_contract=stale_source_contract(constrained_refs=(ref(),), version_bindings={rescore.ref_key(ref()): version_binding()})),
          "stale_source", "unknown", "turn_error", want_audit=("quality_error_override",))

    # evidence_complete=False 覆盖 pass
    check("cross_user: old evidence_complete=False blocks pass -> unknown evidence_incomplete",
          plain_case(old=old_card(evidence_complete=False),
                     anns=anns(cross_user=annotation("cross_user")),
                     cross_user=cross_user_view()),
          "cross_user", "unknown", "evidence_incomplete", want_audit=("evidence_incomplete_override",))


def main() -> int:
    annotation_gate_cases()
    cross_user_cases()
    cross_entity_cases()
    stale_source_cases()
    failures = [item for item in RESULTS if not item["ok"]]
    payload = {
        "probe": "11-axis-semantics",
        "assertions_total": len(RESULTS),
        "assertions_failed": len(failures),
        "failures": failures,
        "results": RESULTS,
        "verdict": "PASS" if not failures else "FAIL",
    }
    dump(HERE / "11-axis-semantics.out.json", payload)
    print(json.dumps({"assertions": len(RESULTS), "failed": len(failures), "verdict": payload["verdict"]}, ensure_ascii=False))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
