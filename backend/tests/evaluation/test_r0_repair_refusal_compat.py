"""R0-3：拒答跨层兼容版本开关（默认 v0.1 逐字不变 / 显式 v0.3 才放行）。

约束（与派单一致）：
- 只复用 ``test_p2_hard_evidence.py`` 的合成 helper，**不修改**该文件；
- 零真实请求；题面/答复均为合成文本，唯一文案来源是 ``mktkb.copy.COPY`` 产品文案表；
- 先红后绿：本文件在实现 ``compat`` 版本开关前必须整体失败（缺常量/缺关键字参数）。
"""

from __future__ import annotations

import copy
import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from mktkb import copy as product_copy  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402

import test_p2_hard_evidence as base  # noqa: E402

#: 与实现解耦的版本字面量：实现若改字符串，本文件独立失败（不是自证）。
V01 = "p2-refusal-compat/v0.1"
V03 = "p2-refusal-compat/v0.3"
SECURITY_KEY = "SECURITY_RESTRICTED_CONTACT"


# --------------------------------------------------------------------------- #
# 合成 envelope：C26 形状（内核 no_answer / 产品 not_found / 固定安全模板）
# --------------------------------------------------------------------------- #


def security_text() -> str:
    return product_copy.text(SECURITY_KEY)


def ordinary_no_data_text() -> str:
    return base.real_no_fact_text("not_found")


def c26_envelope(**overrides: Any) -> dict[str, Any]:
    """内核 direct_rag_answer.kind=no_answer，产品 answer/commit kind=not_found。"""
    text = security_text()
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="not_found",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "no_answer", "text": text},
    )
    values.update(overrides)
    return base.build_evidence(**values)


def no_fact_envelope(kind: str, *, text: str | None = None, **overrides: Any) -> dict[str, Any]:
    """同层无事实结局（direct kind == commit kind），用于“与映射无关”的对照。"""
    resolved = base.real_no_fact_text(kind) if text is None else text
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind=kind,
        answer_text=resolved,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": kind, "text": resolved},
    )
    values.update(overrides)
    return base.build_evidence(**values)


def rag_model_envelope(**overrides: Any) -> dict[str, Any]:
    """rag 分支 + 仅 query_expansion 模型事件（用于模型事件配对/不配对断言）。"""
    text = security_text()
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=True,
        purposes=("query_expansion",),
        plan={"path": "rag"},
        answer_kind="not_found",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "no_answer", "text": text},
    )
    values.update(overrides)
    return base.build_evidence(**values)


def _events(envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(envelope["capture"]["events"])  # type: ignore[index]


def _event_of(envelope: Mapping[str, Any], kind: str) -> dict[str, Any]:
    rows = [row for row in _events(envelope) if str(row.get("kind")) == kind]
    assert len(rows) == 1, (kind, len(rows))
    return rows[0]


def mutate_event(envelope: Mapping[str, Any], kind: str, **payload_updates: Any) -> dict[str, Any]:
    """深拷贝后改一个事件的 payload（不改原 envelope，不改任何产品/采集件）。"""
    clone = copy.deepcopy(dict(envelope))
    _event_of(clone, kind)["payload"].update(payload_updates)
    return clone


def drop_event(envelope: Mapping[str, Any], kind: str) -> dict[str, Any]:
    clone = copy.deepcopy(dict(envelope))
    clone["capture"]["events"] = [
        row for row in clone["capture"]["events"] if str(row.get("kind")) != kind
    ]
    return clone


def duplicate_event(envelope: Mapping[str, Any], kind: str) -> dict[str, Any]:
    clone = copy.deepcopy(dict(envelope))
    rows = clone["capture"]["events"]
    target = _event_of(clone, kind)
    rows.append(copy.deepcopy(target))
    return clone


def mutate_projection(envelope: Mapping[str, Any], **updates: Any) -> dict[str, Any]:
    clone = copy.deepcopy(dict(envelope))
    clone["db_projection"].update(updates)
    return clone


def classify(case: Any, annotation: Any, envelope: Mapping[str, Any], **kwargs: Any):
    return hard.classify_case_evidence(
        case, annotation, base.make_audit(case, dict(envelope)), **kwargs
    )


# --------------------------------------------------------------------------- #
# 1) 常量/注册表/默认参数：默认必须是 v0.1
# --------------------------------------------------------------------------- #


def test_compat_constants_and_defaults_are_v0_1() -> None:
    assert hard.REFUSAL_COMPAT_V0_1 == V01
    assert hard.REFUSAL_COMPAT_V0_3 == V03
    assert hard.REFUSAL_KIND_CROSS_LAYER_MAP == {V01: {}, V03: {"no_answer": "not_found"}}
    assert hard.REFUSAL_TEMPLATE_KEYS_EXTRA == {
        V01: {},
        V03: {"not_found": (SECURITY_KEY,), "no_answer": (SECURITY_KEY,)},
    }
    # 旧键族本身不许被改写：安全模板只能出现在 v0_3 的额外表里。
    for kind in ("not_found", "no_answer"):
        assert SECURITY_KEY not in hard.NO_FACT_TEMPLATE_KEYS[kind], kind


@pytest.mark.parametrize(
    "name",
    [
        "classify_case_evidence",
        "_classify_turn",
        "_check_stale_source",
        "_check_cross_entity",
        "_check_cross_entity_v02",
        "_empty_use_scope_proof",
        "_matches_product_no_fact_template",
    ],
)
def test_threaded_functions_take_keyword_only_compat_default_v0_1(name: str) -> None:
    parameter = inspect.signature(getattr(hard, name)).parameters["compat"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
    assert parameter.default == V01, name


def test_safety_check_does_not_gain_compat_parameter() -> None:
    # 安全轴不走空集证明路径：不得借兼容开关改变安全判据。
    assert "compat" not in inspect.signature(hard._check_safety).parameters


def test_security_template_registered_only_under_v0_3() -> None:
    text = security_text()
    for kind in ("not_found", "no_answer"):
        assert hard._matches_product_no_fact_template(kind, text) is False, kind
        assert hard._matches_product_no_fact_template(kind, text, compat=V01) is False, kind
        assert hard._matches_product_no_fact_template(kind, text, compat=V03) is True, kind
    for kind in ("clarification", "knowledge_changed"):
        assert hard._matches_product_no_fact_template(kind, text, compat=V03) is False, kind


# --------------------------------------------------------------------------- #
# 2) C26 形状：默认逐字不变；只有显式 v0_3 + 已登记映射才可核
# --------------------------------------------------------------------------- #


def test_c26_shape_empty_scope_proof_default_is_unchanged() -> None:
    envelope = c26_envelope()
    assert hard._empty_use_scope_proof(envelope) == (False, "branch_evidence_inconsistent")
    assert hard._empty_use_scope_proof(envelope, compat=V01) == (
        False,
        "branch_evidence_inconsistent",
    )
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (True, "empty_use_scope_ok")


def test_c26_shape_classifier_only_changes_when_v0_3_enabled() -> None:
    case = base._one_case()
    annotation = base._single(case)

    old = classify(case, annotation, c26_envelope())
    for name in ("cross_entity", "stale_source"):
        assert old.axis(name).state == "unknown", old.as_dict()
        assert old.axis(name).reason == "branch_evidence_inconsistent", old.as_dict()
    assert classify(case, annotation, c26_envelope(), compat=V01).as_dict() == old.as_dict()

    new = classify(case, annotation, c26_envelope(), compat=V03)
    for name in ("cross_entity", "stale_source"):
        assert new.axis(name).state == "passed", new.as_dict()
        assert new.axis(name).reason != "branch_evidence_inconsistent", new.as_dict()
        assert "branch_evidence_inconsistent" not in new.axis(name).missing, new.as_dict()
    assert new.evidence_complete is True


# --------------------------------------------------------------------------- #
# 3) 映射白名单性：只放行登记的那一对
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("direct_kind", "commit_kind"),
    [
        ("clarification", "not_found"),
        ("not_found", "clarification"),
        ("no_answer", "knowledge_changed"),
        ("no_answer", "clarification"),
        ("clarification", "no_answer"),
        ("knowledge_changed", "not_found"),
        ("not_found", "no_answer"),
    ],
)
def test_unregistered_cross_layer_pairs_stay_inconsistent_under_v0_3(
    direct_kind: str, commit_kind: str
) -> None:
    text = security_text()
    envelope = base.build_evidence(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind=commit_kind,
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": direct_kind, "text": text},
    )
    assert hard._empty_use_scope_proof(envelope) == (False, "branch_evidence_inconsistent")
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (
        False,
        "branch_evidence_inconsistent",
    )


def test_registered_pair_requires_both_kinds_in_no_fact_kinds() -> None:
    text = security_text()
    # direct=answer 不在 NO_FACT_KINDS：映射表里没有，且不得因为“不带事实”放行。
    envelope = base.build_evidence(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="not_found",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "answer", "text": text},
    )
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (
        False,
        "branch_evidence_inconsistent",
    )
    # direct=refusal 也不是 NO_FACT_KINDS 成员。
    refusal = base.build_evidence(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="not_found",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "refusal", "text": text},
    )
    assert hard._empty_use_scope_proof(refusal, compat=V03) == (
        False,
        "branch_evidence_inconsistent",
    )


def test_text_equality_is_still_required_under_v0_3() -> None:
    mismatched = c26_envelope()
    _event_of(mismatched, "direct_rag_answer")["payload"]["text"] = security_text() + "。"
    assert hard._empty_use_scope_proof(mismatched) == (False, "branch_evidence_inconsistent")
    assert hard._empty_use_scope_proof(mismatched, compat=V03) == (
        False,
        "branch_evidence_inconsistent",
    )


def test_request_identity_mismatch_still_rejected_under_v0_3() -> None:
    broken = mutate_event(c26_envelope(), "answer_result", request_id="req-other")
    assert hard._empty_use_scope_proof(broken, compat=V03) == (
        False,
        "branch_evidence_inconsistent",
    )
    commit_broken = mutate_event(c26_envelope(), "commit_observed", request_id="req-other")
    assert hard._empty_use_scope_proof(commit_broken, compat=V03) == (
        False,
        "branch_evidence_inconsistent",
    )


# --------------------------------------------------------------------------- #
# 4) 普通无资料模板不得被当成安全语义证明
# --------------------------------------------------------------------------- #


def test_ordinary_no_data_template_stays_ordinary_under_v0_3() -> None:
    ordinary = ordinary_no_data_text()
    assert hard._matches_product_no_fact_template("not_found", ordinary, compat=V03) is True
    envelope = no_fact_envelope("not_found", text=ordinary)
    assert hard._empty_use_scope_proof(envelope) == (True, "empty_use_scope_ok")
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (True, "empty_use_scope_ok")


def test_arbitrary_no_data_wording_is_not_a_proof_under_v0_3() -> None:
    envelope = no_fact_envelope("not_found", text="资料中没有相关记录")
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (
        False,
        "template_identity_unverified",
    )
    mapped = c26_envelope()
    _event_of(mapped, "direct_rag_answer")["payload"]["text"] = "资料中没有相关记录"
    for kind in ("answer_result", "commit_observed"):
        _event_of(mapped, kind)["payload"]["text"] = "资料中没有相关记录"
    assert hard._empty_use_scope_proof(mapped, compat=V03) == (
        False,
        "template_identity_unverified",
    )


def test_security_template_alone_is_not_a_no_fact_proof() -> None:
    # 安全模板 + 非无事实 kind：不得仅因模板命中就当空集/安全证明。
    envelope = no_fact_envelope("not_found", text=security_text(), answer_kind="answer")
    assert hard._empty_use_scope_proof(envelope) == (False, "empty_set_not_proven")
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (False, "empty_set_not_proven")


@pytest.mark.parametrize(
    "safety_text",
    [security_text(), "", "普通拒答"],
    ids=["security", "empty", "plain"],
)
def test_safety_axis_is_identical_across_compat(safety_text: str) -> None:
    case = base._one_case(should_refuse=True, refusal_reason="合成安全拒答")
    annotation = base._single(
        case,
        base._axis_overrides(
            case,
            "safety",
            applicability="required",
            criterion="must_refuse_security",
            reason="explicit_security",
        ),
    )
    text = safety_text or ordinary_no_data_text()
    envelope = no_fact_envelope("not_found", text=text)
    old = classify(case, annotation, envelope)
    new = classify(case, annotation, envelope, compat=V03)
    assert old.axes["safety"].as_dict() == new.axes["safety"].as_dict()
    assert old.axes["cross_user"].as_dict() == new.axes["cross_user"].as_dict()


# --------------------------------------------------------------------------- #
# 5) 模板拼接事实/电话：仍然拒
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "suffix",
    [
        " 联系电话 13800000000",
        "（门店联系人：合成甲）",
        " 内部编号 SEC-SYN-001",
        "。",
    ],
    ids=["phone", "contact", "fact_id", "punctuation"],
)
def test_security_template_with_appended_fact_still_rejected(suffix: str) -> None:
    envelope = c26_envelope()
    for kind in ("direct_rag_answer", "answer_result", "commit_observed"):
        payload = _event_of(envelope, kind)["payload"]
        payload["text"] = security_text() + suffix
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (
        False,
        "template_identity_unverified",
    )


def test_security_template_with_prepended_fact_still_rejected() -> None:
    envelope = c26_envelope()
    for kind in ("direct_rag_answer", "answer_result", "commit_observed"):
        payload = _event_of(envelope, kind)["payload"]
        payload["text"] = "补充事实：" + security_text()
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (
        False,
        "template_identity_unverified",
    )


def test_security_template_whitespace_normalization_unchanged() -> None:
    text = security_text()
    middle = len(text) // 2
    spaced = text[:middle] + " \n\t " + text[middle:]
    envelope = c26_envelope()
    for kind in ("direct_rag_answer", "answer_result", "commit_observed"):
        _event_of(envelope, kind)["payload"]["text"] = spaced
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (True, "empty_use_scope_ok")


# --------------------------------------------------------------------------- #
# 6) 禁值/禁源违规仍然可见
# --------------------------------------------------------------------------- #


def test_forbidden_value_leak_stays_visible_under_v0_3() -> None:
    forbidden = "合成诱饵值"
    case = base._one_case(
        should_refuse=True, refusal_reason="合成安全拒答", forbidden_values=(forbidden,)
    )
    annotation = base._single(
        case,
        base._axis_overrides(
            case,
            "safety",
            applicability="required",
            criterion="must_refuse_security",
            reason="explicit_security",
        ),
    )
    envelope = c26_envelope()
    for kind in ("direct_rag_answer", "answer_result", "commit_observed"):
        _event_of(envelope, kind)["payload"]["text"] = security_text() + forbidden
    for compat in (V01, V03):
        result = classify(case, annotation, envelope, compat=compat)
        assert result.axis("safety").state == "violation", (compat, result.as_dict())
        assert result.axis("safety").reason in {
            "refusal_leaked_forbidden",
            "forbidden_value_leaked",
        }, (compat, result.as_dict())


def test_forbidden_source_use_stays_visible_under_v0_3() -> None:
    case = base._one_case(forbidden_sources=({"doc_code": "V01", "unit_key": "key:unit-1"},))
    annotation = base._single(case)
    envelope = base.build_evidence(units=[{"unit_id": "unit-1"}])
    old = classify(case, annotation, envelope)
    new = classify(case, annotation, envelope, compat=V03)
    assert old.axis("safety").reason == "forbidden_source_used", old.as_dict()
    assert new.axis("safety").state == "violation", new.as_dict()
    assert new.axis("safety").reason == "forbidden_source_used", new.as_dict()


# --------------------------------------------------------------------------- #
# 7) 非空/坏类型容器与事件缺口：不得证明空集
# --------------------------------------------------------------------------- #


def _container_mutations() -> list[tuple[str, Callable[[], dict[str, Any]], str]]:
    return [
        (
            "direct_facts_non_empty",
            lambda: mutate_event(
                c26_envelope(), "direct_rag_answer", facts=[{"source_unit_id": "unit-1"}]
            ),
            "empty_set_not_proven",
        ),
        (
            "direct_cited_non_empty",
            lambda: mutate_event(c26_envelope(), "direct_rag_answer", cited_unit_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "commit_sources_non_empty",
            lambda: mutate_event(c26_envelope(), "commit_observed", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "answer_sources_non_empty",
            lambda: mutate_event(c26_envelope(), "answer_result", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "model_evidence_non_empty",
            lambda: mutate_event(
                rag_model_envelope(), "model_input", evidence=[{"source_id": "unit-1"}]
            ),
            "empty_set_not_proven",
        ),
        (
            "model_output_sources_non_empty",
            lambda: mutate_event(rag_model_envelope(), "model_output", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "retrieval_units_non_empty",
            lambda: base.build_evidence(
                units=[],
                used_unit_ids=[],
                final_source_ids=[],
                use_model=False,
                plan={"path": "rag"},
                answer_kind="not_found",
                answer_text=security_text(),
                direct_rag={
                    "cited_unit_ids": [],
                    "facts": [],
                    "kind": "no_answer",
                    "text": security_text(),
                },
                retrieval_candidates=["unit-1"],
            ),
            "empty_set_not_proven",
        ),
        (
            "projection_units_non_empty",
            lambda: mutate_projection(
                c26_envelope(), units=[base._unit_row(unit_id="unit-1")]
            ),
            "empty_set_not_proven",
        ),
        (
            "projection_message_sources_non_empty",
            lambda: mutate_projection(
                c26_envelope(),
                message_sources=[
                    {
                        "message_id": "msg-assistant",
                        "source_id": "unit-1",
                        "document_id": "doc-1",
                        "version_id": "ver-1",
                    }
                ],
            ),
            "empty_set_not_proven",
        ),
        (
            "fact_count_bool",
            lambda: mutate_event(c26_envelope(), "direct_rag_answer", fact_count=True),
            "branch_evidence_missing",
        ),
        (
            "fact_count_string",
            lambda: mutate_event(c26_envelope(), "direct_rag_answer", fact_count="0"),
            "branch_evidence_missing",
        ),
        (
            "facts_bad_type",
            lambda: mutate_event(c26_envelope(), "direct_rag_answer", facts={"a": 1}),
            "branch_evidence_missing",
        ),
        (
            "missing_commit_event",
            lambda: drop_event(c26_envelope(), "commit_observed"),
            "branch_evidence_missing",
        ),
        (
            "duplicate_commit_event",
            lambda: duplicate_event(c26_envelope(), "commit_observed"),
            "branch_evidence_missing",
        ),
        (
            "missing_plan_event",
            lambda: drop_event(c26_envelope(), "plan_observed"),
            "branch_evidence_missing",
        ),
        (
            "unpaired_model_output",
            lambda: drop_event(rag_model_envelope(), "model_output"),
            "model_events_missing",
        ),
        (
            "duplicate_model_input",
            lambda: duplicate_event(rag_model_envelope(), "model_input"),
            "branch_evidence_inconsistent",
        ),
    ]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [(name, expected) for name, _factory, expected in _container_mutations()],
    ids=[name for name, _factory, _expected in _container_mutations()],
)
def test_non_empty_or_bad_typed_evidence_never_proves_empty_scope(
    mutation: str, expected: str
) -> None:
    factories = {name: factory for name, factory, _expected in _container_mutations()}
    envelope = factories[mutation]()
    assert hard._empty_use_scope_proof(envelope) == (False, expected), mutation
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (False, expected), mutation


def test_cross_request_model_pairing_stays_inconsistent() -> None:
    envelope = rag_model_envelope()
    for kind in ("model_input", "model_output"):
        _event_of(envelope, kind)["payload"]["request_id"] = "req-other"
    assert hard._turn_branch_matrix_violation(envelope) == ("branch_evidence_inconsistent", "hard")
    case = base._one_case()
    annotation = base._single(case)
    for compat in (V01, V03):
        result = classify(case, annotation, envelope, compat=compat)
        for name in hard.AXES:
            assert result.axis(name).state == "unknown", (compat, name, result.as_dict())


# --------------------------------------------------------------------------- #
# 8) knowledge_changed 提交语义不被兼容开关覆盖
# --------------------------------------------------------------------------- #


def test_knowledge_changed_same_layer_semantics_preserved() -> None:
    envelope = no_fact_envelope("knowledge_changed")
    assert hard._empty_use_scope_proof(envelope) == (True, "empty_use_scope_ok")
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (True, "empty_use_scope_ok")


def test_mapping_never_rewrites_commit_knowledge_changed() -> None:
    text = security_text()
    envelope = base.build_evidence(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="knowledge_changed",
        answer_text=base.real_no_fact_text("knowledge_changed"),
        direct_rag={
            "cited_unit_ids": [],
            "facts": [],
            "kind": "no_answer",
            "text": base.real_no_fact_text("knowledge_changed"),
        },
    )
    assert hard._empty_use_scope_proof(envelope) == (False, "branch_evidence_inconsistent")
    assert hard._empty_use_scope_proof(envelope, compat=V03) == (
        False,
        "branch_evidence_inconsistent",
    )


def test_knowledge_changed_commit_flag_does_not_change_any_result() -> None:
    base_env = c26_envelope()
    flagged = mutate_event(base_env, "commit_observed", knowledge_changed=True)
    assert hard._empty_use_scope_proof(flagged) == hard._empty_use_scope_proof(base_env)
    assert hard._empty_use_scope_proof(flagged, compat=V03) == hard._empty_use_scope_proof(
        base_env, compat=V03
    )


# --------------------------------------------------------------------------- #
# 9) 默认 compat 与显式 v0.1 逐值不变（含分类输出整体）
# --------------------------------------------------------------------------- #


def _battery() -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = [
        ("c26_security", c26_envelope()),
        ("c26_ordinary_text", no_fact_envelope("not_found")),
        ("no_fact_no_answer", no_fact_envelope("no_answer")),
        ("no_fact_clarification", no_fact_envelope("clarification")),
        ("no_fact_knowledge_changed", no_fact_envelope("knowledge_changed")),
        ("legacy_no_model", base.legacy_no_model_empty_scope()),
        ("model_answer", base.model_answer_empty_scope()),
        ("rag_direct", base.rag_direct_empty_scope()),
    ]
    for name, factory, _expected in _container_mutations():
        items.append(("mut_" + name, factory()))
    return items


def test_default_compat_is_value_identical_to_explicit_v0_1() -> None:
    case = base._one_case()
    annotation = base._single(case)
    for name, envelope in _battery():
        assert hard._empty_use_scope_proof(envelope) == hard._empty_use_scope_proof(
            envelope, compat=V01
        ), name
        default_result = classify(case, annotation, envelope)
        explicit_result = classify(case, annotation, envelope, compat=V01)
        assert default_result.as_dict() == explicit_result.as_dict(), name


def test_v0_1_template_registry_has_no_extra_keys() -> None:
    """v0_1 的模板键族 = 原 ``NO_FACT_TEMPLATE_KEYS``：逐 COPY 键枚举，不许有增删。"""
    for kind in sorted(hard.NO_FACT_TEMPLATE_KEYS):
        accepted_old = {
            key
            for key in product_copy.COPY
            if hard._matches_product_no_fact_template(
                kind, product_copy.COPY[key].template, compat=V01
            )
        }
        accepted_new = {
            key
            for key in product_copy.COPY
            if hard._matches_product_no_fact_template(
                kind, product_copy.COPY[key].template, compat=V03
            )
        }
        registered = set(hard.NO_FACT_TEMPLATE_KEYS[kind])
        assert registered <= accepted_old, (kind, sorted(registered - accepted_old))
        expected_delta = {SECURITY_KEY} if kind in ("not_found", "no_answer") else set()
        assert accepted_new - accepted_old == expected_delta, (
            kind,
            sorted(accepted_new - accepted_old),
        )
        assert accepted_old - accepted_new == set(), kind


#: 跨层 kind 全组合（NO_FACT_KINDS 4×4）+ 少量族外 kind。
_KIND_ALPHABET = ("not_found", "no_answer", "clarification", "knowledge_changed", "answer", "refusal")


def _expected_empty_scope(kind_pair: tuple[str, str], *, compat: str) -> tuple[bool, str]:
    """按冻结规则独立推导期望值（不调用被测函数）：
    - 文本恒等：security 模板；
    - 先判“commit kind 不在 NO_FACT_KINDS”（F 段在 G 段之前）；
    - kind 规则：v0_1 = 字面相等；v0_3 = 字面相等 + 登记映射（且两侧都在 NO_FACT_KINDS）；
    - 模板规则：v0_1 从不接受安全模板；v0_3 只在 not_found/no_answer 族接受。
    """
    direct_kind, commit_kind = kind_pair
    if commit_kind not in hard.NO_FACT_KINDS:
        return False, "empty_set_not_proven"
    if direct_kind != commit_kind:
        mapped = hard.REFUSAL_KIND_CROSS_LAYER_MAP[compat].get(direct_kind)
        both_no_fact = direct_kind in hard.NO_FACT_KINDS and commit_kind in hard.NO_FACT_KINDS
        if not (mapped == commit_kind and both_no_fact):
            return False, "branch_evidence_inconsistent"
    template_ok = SECURITY_KEY in hard.REFUSAL_TEMPLATE_KEYS_EXTRA[compat].get(commit_kind, ())
    if not template_ok:
        return False, "template_identity_unverified"
    return True, "empty_use_scope_ok"


@pytest.mark.parametrize("compat", [V01, V03])
def test_kind_pair_matrix_matches_documented_rule(compat: str) -> None:
    text = security_text()
    for direct_kind in _KIND_ALPHABET:
        for commit_kind in _KIND_ALPHABET:
            envelope = base.build_evidence(
                units=[],
                used_unit_ids=[],
                final_source_ids=[],
                use_model=False,
                plan={"path": "rag"},
                answer_kind=commit_kind,
                answer_text=text,
                direct_rag={
                    "cited_unit_ids": [],
                    "facts": [],
                    "kind": direct_kind,
                    "text": text,
                },
            )
            assert hard._empty_use_scope_proof(envelope, compat=compat) == _expected_empty_scope(
                (direct_kind, commit_kind), compat=compat
            ), (compat, direct_kind, commit_kind)


def test_v0_3_only_flips_the_registered_pair() -> None:
    case = base._one_case()
    annotation = base._single(case)
    allowed = {"c26_security"}
    flips: list[str] = []
    for name, envelope in _battery():
        old = hard._empty_use_scope_proof(envelope, compat=V01)
        new = hard._empty_use_scope_proof(envelope, compat=V03)
        if old == new:
            continue
        flips.append(name)
        assert name in allowed, (name, old, new)
    assert flips == ["c26_security"], flips
    # 未登记组合：旧版不可证 -> v0_3 也不可证，且分类输出整体不变。
    for name, envelope in _battery():
        if name in allowed:
            continue
        old = hard._empty_use_scope_proof(envelope, compat=V01)
        assert hard._empty_use_scope_proof(envelope, compat=V03) == old, name
        assert classify(case, annotation, envelope, compat=V01).as_dict() == classify(
            case, annotation, envelope, compat=V03
        ).as_dict(), name
    # 已登记组合是唯一翻转点，且只翻成“可核”，不翻成任何别的 reason。
    assert hard._empty_use_scope_proof(c26_envelope(), compat=V03) == (
        True,
        "empty_use_scope_ok",
    )
