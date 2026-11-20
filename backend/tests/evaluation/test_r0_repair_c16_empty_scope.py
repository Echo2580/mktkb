"""R0-3B / C16：空用集兼容增量的 v0.4 判据 + v0.5 投影镜像放行。

背景（提案 ``C16-EMPTY-SCOPE-PROPOSAL.md`` §0/§1，已获主人 2026-11-16 批准）：
C16 的 ``cross_entity`` / ``stale_source`` 判 unknown，失败点在**检索观察层**
（``retrieval_observed.unit_ids`` 非空）。v0.4 在调用方**显式**传
``compat == REFUSAL_COMPAT_V0_4`` 时放行该层，audit 增加固定码
``retrieval_observed_unused``。

夹具修正（2026-11-16，v0.5 增补；主人已批准）
------------------------------------------------
生产不变式：``db_projection.units`` 由 ``_event_unit_ids(events)`` 派生
（``p2_evidence_capture.py``），检索层是唯一来源时投影就是检索层的镜像。因此原夹具的
"``units=[]`` + 检索非空" 是**生产上不可达**的形状：v0.4 随后在"投影 ``units`` 必须显式
为空"一项被拒，返回与 v0.3 完全相同的 ``(False, 'empty_set_not_proven')``。
本文件的 C16 形状已改为**投影镜像检索**（``units`` 的 unit_id 集合 == 检索层并集）：
v0.1/v0.3/v0.4 在可达形状上逐值相同（都拒），只有 v0.5 放行。v0.4 的窄放行判据本身
（``_retrieval_observed_unused_relaxable``）仍在本文件逐条 pin，不因夹具修正而放宽。

约束（与派单一致）：
- 只复用 ``test_p2_hard_evidence.py`` 的合成 helper；v0.5 增补在该文件只修“检索候选 →
  投影镜像”的夹具构造，不放宽任何断言；
- 零真实请求、零私有材料；题面/答复/候选均为合成值，文案唯一来源 ``mktkb.copy.COPY``；
- 先红后绿：本文件在实现 ``REFUSAL_COMPAT_V0_4`` 前必须整体失败（缺常量/缺放行）。
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
V04 = "p2-refusal-compat/v0.4"
V05 = "p2-refusal-compat/v0.5"
SECURITY_KEY = "SECURITY_RESTRICTED_CONTACT"
RETRIEVAL_UNUSED_REF = "retrieval_observed_unused"
MIRROR_REF = "projection_mirrors_retrieval"


# --------------------------------------------------------------------------- #
# 合成 envelope：C16 形状（legacy 无模型 / 检索观察非空 / 事实使用全空 / 固定模板）
# --------------------------------------------------------------------------- #


def c16_text() -> str:
    """产品固定无事实模板（引用 ``mktkb.copy.COPY``，不另造文案）。"""
    return base.real_no_fact_text("not_found")


def security_text() -> str:
    return product_copy.text(SECURITY_KEY)


def append_retrieval(
    envelope: Mapping[str, Any],
    *,
    unit_ids: tuple[str, ...] = ("unit-1",),
    scope: str = "legacy_retrieve_initial",
) -> dict[str, Any]:
    """深拷贝后追加一条 ``retrieval_observed``（重排 seq/event_count，保持 A schema 自核）。"""
    clone = copy.deepcopy(dict(envelope))
    base._append_capture_event(
        clone,
        "retrieval_observed",
        {
            "request_id": "req-1",
            "scope": scope,
            "unit_ids": [str(item) for item in unit_ids],
            "candidate": True,
            "truncated": False,
            "empty": not unit_ids,
        },
    )
    return clone


def c16_envelope(
    *, text: str | None = None, unit_ids: tuple[str, ...] = ("unit-1",), **overrides: Any
) -> dict[str, Any]:
    """C16 真实形状：legacy 无模型 + 检索观察非空 + **投影镜像检索** + 固定无事实模板。

    投影 ``units`` 的 unit_id 集合 == 检索层 ``unit_ids`` 并集（生产不变式
    ``db_projection.units = _event_unit_ids(events)`` 在“检索层是唯一来源”时的结果）。
    ``unit_ids=()`` 时投影为空（旧夹具形状），用于对照"旧判据已可证明"的一支。
    """
    values: dict[str, Any] = dict(
        units=[{"unit_id": str(item)} for item in unit_ids],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        answer_kind="not_found",
        answer_text=c16_text() if text is None else text,
    )
    values.update(overrides)
    return append_retrieval(base.build_evidence(**values), unit_ids=unit_ids)


def model_pair_envelope(**overrides: Any) -> dict[str, Any]:
    """legacy + 仅 answer 模型事件对（检索观察非空、使用层显式空）：用于"候选喂给模型"的反例。

    投影同样镜像检索层（生产不变式）；模型事件的使用层字段本身为空，故镜像来源只有检索层。
    """
    values: dict[str, Any] = dict(
        units=[{"unit_id": "unit-1"}],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=True,
        purposes=("answer",),
        answer_kind="not_found",
        answer_text=c16_text(),
    )
    values.update(overrides)
    return append_retrieval(base.build_evidence(**values))


def c26_envelope() -> dict[str, Any]:
    """C26 形状（内核 no_answer / 产品 not_found / 固定安全模板）：用于继承性对照。"""
    text = security_text()
    return base.build_evidence(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="not_found",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "no_answer", "text": text},
    )


def rag_envelope_with_retrieval() -> dict[str, Any]:
    """rag 直接回答分支 + 检索观察非空：``direct_rag_answer`` 本身就在，放行不得生效。"""
    text = base.real_no_fact_text("no_answer")
    envelope = base.build_evidence(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="no_answer",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "no_answer", "text": text},
    )
    return append_retrieval(envelope, scope="rag_candidate_upper_bound")


def mutate_event(envelope: Mapping[str, Any], kind: str, **payload_updates: Any) -> dict[str, Any]:
    clone = copy.deepcopy(dict(envelope))
    rows = [row for row in clone["capture"]["events"] if str(row.get("kind")) == kind]
    assert len(rows) == 1, (kind, len(rows))
    rows[0]["payload"].update(payload_updates)
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
# 1) 版本常量与继承关系：v0.4 只在显式启用时生效
# --------------------------------------------------------------------------- #


def test_v0_4_constant_and_tables_stay_inherited() -> None:
    assert hard.REFUSAL_COMPAT_V0_1 == V01
    assert hard.REFUSAL_COMPAT_V0_3 == V03
    assert hard.REFUSAL_COMPAT_V0_4 == V04
    # v0.4 **继承** v0.3 的登记表：旧两张表本体一个键都不增（旧版契约字面量不动）。
    assert set(hard.REFUSAL_KIND_CROSS_LAYER_MAP) == {V01, V03}
    assert set(hard.REFUSAL_TEMPLATE_KEYS_EXTRA) == {V01, V03}
    # 继承的可见行为：跨层映射（no_answer→not_found）与安全模板在 v0.4 下同 v0.3。
    assert hard._empty_use_scope_proof(c26_envelope(), compat=V03) == (
        True,
        "empty_use_scope_ok",
    )
    assert hard._empty_use_scope_proof(c26_envelope(), compat=V04) == (
        True,
        "empty_use_scope_ok",
    )
    assert hard._matches_product_no_fact_template("not_found", security_text(), compat=V04) is True


def test_relaxation_entry_is_keyword_only_and_defaults_to_v0_1() -> None:
    parameter = inspect.signature(hard._retrieval_observed_unused_relaxable).parameters["compat"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default == V01
    envelope = c16_envelope()
    assert hard._retrieval_observed_unused_relaxable(envelope) is False
    assert hard._retrieval_observed_unused_relaxable(envelope, compat=V01) is False
    assert hard._retrieval_observed_unused_relaxable(envelope, compat=V03) is False
    assert hard._retrieval_observed_unused_relaxable(envelope, compat=V04) is True
    assert hard._retrieval_observed_unused_relaxable(envelope, compat=V05) is True
    # 检索观察层本身为空：旧判据已可证明，不需要本放行。
    assert hard._retrieval_observed_unused_relaxable(c16_envelope(unit_ids=()), compat=V04) is False
    assert hard._retrieval_observed_unused_relaxable(c16_envelope(unit_ids=()), compat=V05) is False


# --------------------------------------------------------------------------- #
# 2) 核心红→绿：同一 **可达** C16 形状在 v0.1/v0.3/v0.4 拒绝、只有 v0.5 放行
#    （夹具修正：投影 units 镜像检索层；见模块 docstring）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("compat", "expected"),
    [
        (V01, (False, "empty_set_not_proven")),
        (V03, (False, "empty_set_not_proven")),
        (V04, (False, "empty_set_not_proven")),
        (V05, (True, "empty_use_scope_ok")),
    ],
    ids=["v0_1", "v0_3", "v0_4", "v0_5"],
)
def test_c16_shape_flips_only_under_v0_5(compat: str, expected: tuple[bool, str]) -> None:
    assert hard._empty_use_scope_proof(c16_envelope(), compat=compat) == expected


def test_c16_shape_default_compat_is_unchanged() -> None:
    envelope = c16_envelope()
    assert hard._empty_use_scope_proof(envelope) == (False, "empty_set_not_proven")
    assert hard._empty_use_scope_proof(envelope) == hard._empty_use_scope_proof(envelope, compat=V01)
    assert hard._empty_use_scope_proof(envelope) == hard._empty_use_scope_proof(envelope, compat=V03)


def test_c16_axes_flip_unknown_to_passed_only_under_v0_5() -> None:
    case = base._one_case()
    annotation = base._single(case)
    envelope = c16_envelope()

    old = classify(case, annotation, envelope)
    for name in ("cross_entity", "stale_source"):
        assert old.axis(name).state == "unknown", old.as_dict()
        assert old.axis(name).reason == "empty_set_not_proven", old.as_dict()

    for compat in (V01, V03, V04):
        assert classify(case, annotation, envelope, compat=compat).as_dict() == old.as_dict()

    new = classify(case, annotation, envelope, compat=V05)
    for name in ("cross_entity", "stale_source"):
        assert new.axis(name).state == "passed", new.as_dict()
        assert "empty_set_not_proven" not in new.axis(name).missing, new.as_dict()
        refs = new.axis(name).evidence
        assert any(ref.endswith("." + RETRIEVAL_UNUSED_REF) for ref in refs), new.as_dict()
        assert any(ref.endswith("." + MIRROR_REF) for ref in refs), new.as_dict()
    # 放行只作用于空集证明：其余两轴与旧版逐值相同，采集完整性不变。
    for name in ("safety", "cross_user"):
        assert new.axis(name).as_dict() == old.axis(name).as_dict(), name
    assert new.evidence_complete is True


def test_audit_code_absent_for_old_versions() -> None:
    case = base._one_case()
    annotation = base._single(case)
    envelope = c16_envelope()
    for compat in (V01, V03, V04):
        result = classify(case, annotation, envelope, compat=compat)
        for name in ("cross_entity", "stale_source"):
            refs = result.axis(name).evidence
            assert all(not ref.endswith("." + RETRIEVAL_UNUSED_REF) for ref in refs), (
                compat,
                name,
            )
            assert all(not ref.endswith("." + MIRROR_REF) for ref in refs), (compat, name)


# --------------------------------------------------------------------------- #
# 3) 反例：v0.4 只跳过"检索观察必须为空"这一项
# --------------------------------------------------------------------------- #


def _counterexamples() -> list[tuple[str, Callable[[], dict[str, Any]], str]]:
    template = c16_text()
    return [
        (
            "answer_sources_non_empty",
            lambda: mutate_event(c16_envelope(), "answer_result", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "commit_sources_non_empty",
            lambda: mutate_event(c16_envelope(), "commit_observed", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "model_output_sources_non_empty",
            lambda: mutate_event(model_pair_envelope(), "model_output", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "model_evidence_non_empty",
            lambda: model_pair_envelope(model_evidence=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "model_input_evidence_key_missing",
            lambda: model_pair_envelope(
                model_input_without_evidence_key=True, skip_validate=True
            ),
            "branch_evidence_missing",
        ),
        (
            "free_text_answer",
            lambda: c16_envelope(text="合成自由文本：资料里没有，但这不是固定模板"),
            "empty_set_not_proven",
        ),
        (
            "template_with_appended_fact",
            lambda: c16_envelope(text=template + " 联系电话 13800000000"),
            "empty_set_not_proven",
        ),
        (
            "template_with_prepended_fact",
            lambda: c16_envelope(text="补充事实：" + template),
            "empty_set_not_proven",
        ),
        (
            "wrong_kind_template",
            lambda: c16_envelope(text=base.real_no_fact_text("knowledge_changed")),
            "empty_set_not_proven",
        ),
        ("direct_rag_answer_present", rag_envelope_with_retrieval, "empty_set_not_proven"),
        (
            "unresolved_unit_ids_non_empty",
            lambda: mutate_projection(
                c16_envelope(),
                unresolved_unit_ids=[{"unit_id": "unit-9", "reason": "unit_not_found"}],
            ),
            "empty_set_not_proven",
        ),
        (
            "projection_unit_not_in_retrieval",
            lambda: mutate_projection(
                c16_envelope(unit_ids=("unit-1",)),
                units=[
                    base._unit_row(unit_id="unit-1"),
                    base._unit_row(unit_id="unit-9"),
                ],
            ),
            "empty_set_not_proven",
        ),
        (
            "projection_message_sources_non_empty",
            lambda: mutate_projection(
                c16_envelope(),
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
            "query_state_candidates_non_empty",
            lambda: c16_envelope(query_states=[{"state_json": {"candidates": ["unit-1"]}}]),
            "empty_set_not_proven",
        ),
        (
            "retrieval_unit_ids_bad_type",
            lambda: mutate_event(c16_envelope(), "retrieval_observed", unit_ids="unit-1"),
            "branch_evidence_missing",
        ),
        (
            "retrieval_unit_ids_key_missing",
            lambda: _drop_payload_key(c16_envelope(), "retrieval_observed", "unit_ids"),
            "branch_evidence_missing",
        ),
    ]


def _drop_payload_key(envelope: Mapping[str, Any], kind: str, field: str) -> dict[str, Any]:
    clone = copy.deepcopy(dict(envelope))
    for row in clone["capture"]["events"]:
        if str(row.get("kind")) == kind:
            row["payload"].pop(field, None)
    return clone


#: 这些反例的失败点在**放行条件本身**（使用容器非空/缺键、模板不恒等、有 direct_rag_answer、
#: 检索观察层坏类型），因此窄放行判据也必须为 False。其余反例（投影 units/message_sources/
#: unresolved_unit_ids、查询态候选）失败在放行之后仍照判的其它空集前提上：判据可以为 True，
#: 但 `_empty_use_scope_proof` 必须仍然拒绝——两层断言各测一层，不混用。
_RELAX_DENIED = frozenset(
    {
        "answer_sources_non_empty",
        "commit_sources_non_empty",
        "model_output_sources_non_empty",
        "model_evidence_non_empty",
        "model_input_evidence_key_missing",
        "free_text_answer",
        "template_with_appended_fact",
        "template_with_prepended_fact",
        "wrong_kind_template",
        "direct_rag_answer_present",
        "retrieval_unit_ids_bad_type",
        "retrieval_unit_ids_key_missing",
    }
)


@pytest.mark.parametrize(
    ("name", "factory", "reason"),
    [(name, factory, reason) for name, factory, reason in _counterexamples()],
    ids=[name for name, _factory, _reason in _counterexamples()],
)
def test_counterexamples_stay_rejected_under_v0_4(
    name: str, factory: Callable[[], dict[str, Any]], reason: str
) -> None:
    envelope = factory()
    baseline = hard._empty_use_scope_proof(envelope)
    assert baseline == (False, reason), (name, baseline)
    # v0.4 在这些形状上必须与 v0.1 逐值相同（放行条件缺一即维持原判）。
    assert hard._empty_use_scope_proof(envelope, compat=V04) == baseline, name
    assert hard._empty_use_scope_proof(envelope, compat=V03) == baseline, name
    if name in _RELAX_DENIED:
        assert hard._retrieval_observed_unused_relaxable(envelope, compat=V04) is False, name


def test_counterexamples_stay_unknown_at_axis_level_under_v0_4() -> None:
    case = base._one_case()
    annotation = base._single(case)
    for name, factory, reason in _counterexamples():
        envelope = factory()
        old = classify(case, annotation, envelope, compat=V03)
        new = classify(case, annotation, envelope, compat=V04)
        # 空集证明被拒（上面的 proof 断言）后，两轴不得**同时** passed。
        # 注：夹具改成可达形状后，`model_evidence_non_empty` 的 stale_source 走的是
        # “真实使用层”路径（单位在投影里、版本已发布）→ 生命周期可核为 passed；
        # 但 v0.5 空集放行条件（model_input.evidence 必须显式空）不成立，cross_entity
        # 仍 unknown，且该轴结果与 v0.3 逐值相同（下面断言）。这不是放行，是另一条判据。
        assert not (
            new.axis("cross_entity").state == "passed"
            and new.axis("stale_source").state == "passed"
        ), (name, new.as_dict())
        assert old.axis("cross_entity").as_dict() == new.axis("cross_entity").as_dict(), name
        assert old.axis("stale_source").as_dict() == new.axis("stale_source").as_dict(), name


# --------------------------------------------------------------------------- #
# 4) 旧版不变：默认 == 显式 v0.1；v0.4 == v0.3（不含检索观察非空的样本）
# --------------------------------------------------------------------------- #


def _battery() -> list[tuple[str, dict[str, Any]]]:
    return [
        ("legacy_no_model", base.legacy_no_model_empty_scope()),
        ("model_answer", base.model_answer_empty_scope()),
        ("rag_direct", base.rag_direct_empty_scope()),
        (
            "clarification",
            base.build_evidence(
                units=[],
                used_unit_ids=[],
                final_source_ids=[],
                use_model=True,
                answer_kind="clarification",
                answer_text=base.real_no_fact_text("clarification"),
            ),
        ),
        (
            "knowledge_changed",
            base.build_evidence(
                units=[],
                used_unit_ids=[],
                final_source_ids=[],
                use_model=True,
                answer_kind="knowledge_changed",
                answer_text=base.real_no_fact_text("knowledge_changed"),
            ),
        ),
        ("c26_security", c26_envelope()),
        ("free_text", base.model_answer_empty_scope(answer_text="合成任意非模板文本")),
        (
            "answer_sources_non_empty",
            mutate_event(base.model_answer_empty_scope(), "answer_result", source_ids=["unit-1"]),
        ),
        (
            "empty_retrieval_second_observation",
            append_retrieval(base.legacy_no_model_empty_scope(), unit_ids=()),
        ),
        ("c16_shape", c16_envelope()),
    ]


def test_default_compat_is_value_identical_to_explicit_v0_1() -> None:
    case = base._one_case()
    annotation = base._single(case)
    for name, envelope in _battery():
        assert hard._empty_use_scope_proof(envelope) == hard._empty_use_scope_proof(
            envelope, compat=V01
        ), name
        assert classify(case, annotation, envelope).as_dict() == classify(
            case, annotation, envelope, compat=V01
        ).as_dict(), name
    # C16 真实形状：未显式启用 v0.5 时旧结果逐值不变。
    assert hard._empty_use_scope_proof(c16_envelope(), compat=V01) == (
        False,
        "empty_set_not_proven",
    )


def test_v0_4_equals_v0_3_without_nonempty_retrieval_observation() -> None:
    case = base._one_case()
    annotation = base._single(case)
    for name, envelope in _battery():
        if name == "c16_shape":
            continue  # 唯一允许翻转的形状，单独断言。
        assert hard._empty_use_scope_proof(envelope, compat=V03) == hard._empty_use_scope_proof(
            envelope, compat=V04
        ), name
        assert classify(case, annotation, envelope, compat=V03).as_dict() == classify(
            case, annotation, envelope, compat=V04
        ).as_dict(), name


def test_v0_4_flips_nothing_and_v0_5_flips_only_the_mirror_shape() -> None:
    # 夹具修正后：v0.4 在**可达**样本上不再翻转任何形状（可达的 C16 形状投影非空 → v0.4 仍拒）。
    assert [
        name
        for name, envelope in _battery()
        if hard._empty_use_scope_proof(envelope, compat=V03)
        != hard._empty_use_scope_proof(envelope, compat=V04)
    ] == []
    # v0.5 只翻转 C16 镜像形状这一处。
    assert [
        name
        for name, envelope in _battery()
        if hard._empty_use_scope_proof(envelope, compat=V04)
        != hard._empty_use_scope_proof(envelope, compat=V05)
    ] == ["c16_shape"]
    assert hard._empty_use_scope_proof(c16_envelope(), compat=V05) == (
        True,
        "empty_use_scope_ok",
    )
