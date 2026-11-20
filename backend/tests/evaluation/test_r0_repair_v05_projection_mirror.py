"""R0-3C / v0.5 空用集增补：投影 ``units`` 逐值镜像检索层。

背景（已确证的 v0.4 结构性不可达）
--------------------------------
生产不变式：``db_projection.units`` 由 ``_event_unit_ids(events)`` 派生
（``backend/src/mktkb/evaluation/p2_evidence_capture.py``）；空用集形状里检索层是
唯一来源时，投影 ``units`` 的 unit_id 集合就是 ``retrieval_observed[*].unit_ids`` 的并集。
因此"检索观察非空 + 投影 units 显式为空"是**生产上不可能出现**的夹具形状：
v0.4 虽放行了检索观察层非空，随后在 E 段"投影 units 必须显式为空"被拒，返回与
v0.3 完全相同的 ``(False, "empty_set_not_proven")``。

v0.5 只多放行这一种情况
----------------------
``compat == "p2-refusal-compat/v0.5"`` 时，**且**同时满足：

a. v0.4 的 ``_retrieval_observed_unused_relaxable`` 放行条件已成立
   （事实使用容器全显式空、无 ``direct_rag_answer``、固定无事实模板恒等）；
b. 投影 ``units`` 的 unit_id 集合**逐值等于**检索层 ``unit_ids`` 并集
   （只认检索层；``message_sources`` / facts / citation / ``entity_inheritance`` /
   ``_event_unit_ids`` 全层并集都不得为镜像作证，那些层继续 fail-closed）；
c. 其余空集前提（``message_sources``、``unresolved_unit_ids``、查询态候选、
   ``_used_unit_layers``、commit 单条/kind/模板恒等、A 段 schema 闭包、完整性、
   errors/truncations）全部照旧。

约束（与派单一致）
------------------
- 只复用 ``test_p2_hard_evidence.py`` 的合成 helper；文案唯一来源 ``mktkb.copy.COPY``；
- 零真实请求、零私有材料；题面/答复/候选均为合成值；
- 先红后绿：实现 v0.5 前 ``REFUSAL_COMPAT_V0_5``/镜像判据/审计码都不存在（见报告）。
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

from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402

import test_p2_hard_evidence as base  # noqa: E402
import test_r0_repair_c16_empty_scope as c16_prev  # noqa: E402
import test_r0_repair_refusal_compat as compat_prev  # noqa: E402

#: 与实现解耦的版本字面量：实现若改字符串，本文件独立失败（不是自证）。
V01 = "p2-refusal-compat/v0.1"
V03 = "p2-refusal-compat/v0.3"
V04 = "p2-refusal-compat/v0.4"
V05 = "p2-refusal-compat/v0.5"
OLD_VERSIONS = (V01, V03, V04)
AUDIT_MIRROR = "projection_mirrors_retrieval"
AUDIT_RETRIEVAL_UNUSED = "retrieval_observed_unused"
OK = (True, "empty_use_scope_ok")
REJECTED = (False, "empty_set_not_proven")


# --------------------------------------------------------------------------- #
# 合成 envelope：C16 真实形状（投影镜像检索 / legacy 无模型 / 事实使用全空 / 固定模板）
# --------------------------------------------------------------------------- #


def no_fact_text() -> str:
    """产品固定无事实模板（引用 ``mktkb.copy.COPY``，不另造文案）。"""
    return base.real_no_fact_text("not_found")


def _append_retrieval(
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


def mirror_envelope(
    *,
    text: str | None = None,
    unit_ids: tuple[str, ...] = ("unit-1",),
    extra_units: tuple[str, ...] = (),
    **overrides: Any,
) -> dict[str, Any]:
    """C16 真实形状：投影 ``units`` 的 unit_id 集合 == 检索层 unit_ids 并集。"""
    projected = tuple(unit_ids) + tuple(extra_units)
    values: dict[str, Any] = dict(
        units=[{"unit_id": str(item)} for item in projected],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        answer_kind="not_found",
        answer_text=no_fact_text() if text is None else text,
    )
    values.update(overrides)
    return _append_retrieval(base.build_evidence(**values), unit_ids=unit_ids)


def mirror_model_envelope(**overrides: Any) -> dict[str, Any]:
    """legacy + 仅 answer 模型事件对（使用层显式空）；投影仍镜像检索层。"""
    values: dict[str, Any] = dict(
        units=[{"unit_id": "unit-1"}],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=True,
        purposes=("answer",),
        answer_kind="not_found",
        answer_text=no_fact_text(),
    )
    values.update(overrides)
    return _append_retrieval(base.build_evidence(**values))


def mirror_rag_envelope() -> dict[str, Any]:
    """rag 直接回答分支 + 检索观察非空；``direct_rag_answer`` 在，v0.5 不得放行。"""
    text = no_fact_text()
    envelope = base.build_evidence(
        units=[{"unit_id": "unit-1"}],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="not_found",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "not_found", "text": text},
    )
    return _append_retrieval(envelope, scope="rag_candidate_upper_bound")


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


def drop_payload_key(envelope: Mapping[str, Any], kind: str, field: str) -> dict[str, Any]:
    clone = copy.deepcopy(dict(envelope))
    for row in clone["capture"]["events"]:
        if str(row.get("kind")) == kind:
            row["payload"].pop(field, None)
    return clone


def set_payload_key(
    envelope: Mapping[str, Any], kind: str, field: str, value: Any
) -> dict[str, Any]:
    """按事件种类设置 payload 字段（``kind`` 字段本身不能用 ``mutate_event``）。"""
    clone = copy.deepcopy(dict(envelope))
    for row in clone["capture"]["events"]:
        if str(row.get("kind")) == kind:
            row["payload"][field] = value
    return clone


def duplicate_event(envelope: Mapping[str, Any], kind: str) -> dict[str, Any]:
    clone = copy.deepcopy(dict(envelope))
    rows = [row for row in clone["capture"]["events"] if str(row.get("kind")) == kind]
    assert len(rows) == 1, (kind, len(rows))
    clone["capture"]["events"].append(copy.deepcopy(rows[0]))
    for index, row in enumerate(clone["capture"]["events"], 1):
        row["seq"] = index
    clone["capture"]["seq"] = len(clone["capture"]["events"])
    clone["capture"]["event_count"] = len(clone["capture"]["events"])
    return clone


def classify(case: Any, annotation: Any, envelope: Mapping[str, Any], **kwargs: Any):
    return hard.classify_case_evidence(
        case, annotation, base.make_audit(case, dict(envelope)), **kwargs
    )


def audit_refs(envelope: Mapping[str, Any], compat: str) -> set[str]:
    """空用集两轴的 audit 引用并集（固定码都以 ``.<code>`` 结尾）。"""
    case = base._one_case()
    annotation = base._single(case)
    result = classify(case, annotation, envelope, compat=compat)
    refs: set[str] = set()
    for name in ("cross_entity", "stale_source"):
        refs.update(result.axis(name).evidence)
    return refs


# --------------------------------------------------------------------------- #
# 1) 版本常量 / 继承链 / 默认参数：v0.5 只在显式启用时生效
# --------------------------------------------------------------------------- #


def test_v0_5_constant_and_inheritance_chain() -> None:
    assert hard.REFUSAL_COMPAT_V0_1 == V01
    assert hard.REFUSAL_COMPAT_V0_3 == V03
    assert hard.REFUSAL_COMPAT_V0_4 == V04
    assert hard.REFUSAL_COMPAT_V0_5 == V05
    # v0.5 继承 v0.4；v0.4 继承 v0.3 → 链式解析落到同一张登记表，逐条取值相同。
    assert hard.REFUSAL_COMPAT_INHERITS[V05] == V04
    assert hard.REFUSAL_COMPAT_INHERITS[V04] == V03
    assert hard._compat_lineage(V05) == (V05, V04, V03)
    assert hard._compat_table_version(V05) == hard._compat_table_version(V04) == V03
    # 旧两张表本体一个键都不增（旧版契约字面量不动）。
    assert set(hard.REFUSAL_KIND_CROSS_LAYER_MAP) == {V01, V03}
    assert set(hard.REFUSAL_TEMPLATE_KEYS_EXTRA) == {V01, V03}
    # 继承的可见行为：跨层映射（no_answer→not_found）与安全模板在 v0.5 下同 v0.3/v0.4。
    c26 = c16_prev.c26_envelope()
    assert hard._empty_use_scope_proof(c26, compat=V04) == hard._empty_use_scope_proof(
        c26, compat=V05
    ) == OK
    assert hard._matches_product_no_fact_template(
        "not_found", c16_prev.security_text(), compat=V05
    ) is True
    assert hard._relax_retrieval_enabled(V04) is True
    assert hard._relax_retrieval_enabled(V05) is True
    assert hard._relax_retrieval_enabled(V01) is False
    assert hard._relax_retrieval_enabled(V03) is False


def test_default_compat_stays_v0_1_keyword_only() -> None:
    for function in (
        hard._empty_use_scope_proof,
        hard._retrieval_observed_unused_relaxable,
        hard._projection_mirror_relaxable,
    ):
        parameter = inspect.signature(function).parameters["compat"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, function.__name__
        assert parameter.default == V01, function.__name__
    parameter = inspect.signature(hard.classify_case_evidence).parameters["compat"]
    assert parameter.default == V01


# --------------------------------------------------------------------------- #
# 2) 核心红→绿：同一 C16 真实形状在 v0.1/v0.3/v0.4 拒绝、v0.5 放行
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("compat", "expected"),
    [
        (V01, REJECTED),
        (V03, REJECTED),
        (V04, REJECTED),
        (V05, OK),
    ],
    ids=["v0_1", "v0_3", "v0_4", "v0_5"],
)
def test_c16_mirror_shape_flips_only_under_v0_5(
    compat: str, expected: tuple[bool, str]
) -> None:
    assert hard._empty_use_scope_proof(mirror_envelope(), compat=compat) == expected


def test_c16_mirror_shape_default_is_still_rejected() -> None:
    envelope = mirror_envelope()
    assert hard._empty_use_scope_proof(envelope) == REJECTED
    assert hard._empty_use_scope_proof(envelope) == hard._empty_use_scope_proof(
        envelope, compat=V01
    )
    assert hard._empty_use_scope_proof(envelope, compat=V05) == OK


def test_v0_5_accepts_union_of_two_retrieval_observations() -> None:
    """条件 b 说的是**并集**：两条检索观察各 1 个 unit，投影两行都算镜像。"""
    envelope = base.build_evidence(
        units=[{"unit_id": "unit-1"}, {"unit_id": "unit-2"}],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        answer_kind="not_found",
        answer_text=no_fact_text(),
    )
    envelope = _append_retrieval(envelope, unit_ids=("unit-1",))
    envelope = _append_retrieval(
        envelope, unit_ids=("unit-2",), scope="legacy_retrieve_after_model"
    )
    assert hard._retrieval_unit_id_union(hard._events(envelope)) == {"unit-1", "unit-2"}
    assert hard._projection_units_mirror_retrieval(envelope) is True
    assert hard._empty_use_scope_proof(envelope, compat=V04) == REJECTED
    assert hard._empty_use_scope_proof(envelope, compat=V05) == OK


def test_v0_5_axes_flip_unknown_to_passed_only_on_mirror_shape() -> None:
    case = base._one_case()
    annotation = base._single(case)
    envelope = mirror_envelope()

    old = classify(case, annotation, envelope)
    for name in ("cross_entity", "stale_source"):
        assert old.axis(name).state == "unknown", old.as_dict()
        assert old.axis(name).reason == "empty_set_not_proven", old.as_dict()
    for compat in OLD_VERSIONS:
        assert classify(case, annotation, envelope, compat=compat).as_dict() == old.as_dict()

    new = classify(case, annotation, envelope, compat=V05)
    for name in ("cross_entity", "stale_source"):
        assert new.axis(name).state == "passed", new.as_dict()
        assert "empty_set_not_proven" not in new.axis(name).missing, new.as_dict()
        refs = new.axis(name).evidence
        assert any(ref.endswith("." + AUDIT_MIRROR) for ref in refs), new.as_dict()
    # 放行只作用于空集证明：其余两轴与旧版逐值相同，采集完整性不变。
    for name in ("safety", "cross_user"):
        assert new.axis(name).as_dict() == old.axis(name).as_dict(), name
    assert new.evidence_complete is True


# --------------------------------------------------------------------------- #
# 3) 反例：v0.5 只跳过"投影 units 必须为空"这一项
# --------------------------------------------------------------------------- #


def _counterexamples() -> list[tuple[str, Callable[[], dict[str, Any]], str]]:
    template = no_fact_text()
    return [
        # 条件 b：镜像齐性——多一个 / 少一个 / 重复 / 检索层为空都不算镜像。
        (
            "projection_unit_not_in_retrieval",
            lambda: mirror_envelope(extra_units=("unit-9",)),
            "empty_set_not_proven",
        ),
        (
            "projection_missing_retrieval_unit",
            lambda: mutate_projection(
                mirror_envelope(unit_ids=("unit-1", "unit-2")), units=[base._unit_row(unit_id="unit-1")]
            ),
            "empty_set_not_proven",
        ),
        (
            "projection_duplicate_unit_row",
            lambda: mutate_projection(
                mirror_envelope(),
                units=[base._unit_row(unit_id="unit-1"), base._unit_row(unit_id="unit-1")],
            ),
            "empty_set_not_proven",
        ),
        (
            "projection_units_without_retrieval",
            lambda: _append_retrieval(
                base.build_evidence(
                    units=[{"unit_id": "unit-1"}],
                    used_unit_ids=[],
                    final_source_ids=[],
                    use_model=False,
                    answer_kind="not_found",
                    answer_text=template,
                ),
                unit_ids=(),
            ),
            "empty_set_not_proven",
        ),
        # 条件 c：其余使用层/候选层必须仍为空。
        (
            "projection_message_sources_non_empty",
            lambda: mutate_projection(
                mirror_envelope(),
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
            "unresolved_unit_ids_non_empty",
            lambda: mutate_projection(
                mirror_envelope(),
                unresolved_unit_ids=[{"unit_id": "unit-9", "reason": "unit_not_found"}],
            ),
            "empty_set_not_proven",
        ),
        (
            "query_state_candidates_non_empty",
            lambda: mirror_envelope(query_states=[{"state_json": {"candidates": ["unit-1"]}}]),
            "empty_set_not_proven",
        ),
        (
            "answer_sources_non_empty",
            lambda: mutate_event(mirror_envelope(), "answer_result", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "commit_sources_non_empty",
            lambda: mutate_event(mirror_envelope(), "commit_observed", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "model_output_sources_non_empty",
            lambda: mutate_event(mirror_model_envelope(), "model_output", source_ids=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "model_evidence_non_empty",
            lambda: mirror_model_envelope(model_evidence=["unit-1"]),
            "empty_set_not_proven",
        ),
        (
            "model_input_evidence_key_missing",
            lambda: _append_retrieval(
                base.build_evidence(
                    units=[{"unit_id": "unit-1"}],
                    used_unit_ids=[],
                    final_source_ids=[],
                    use_model=True,
                    purposes=("answer",),
                    answer_kind="not_found",
                    answer_text=template,
                    model_input_without_evidence_key=True,
                    skip_validate=True,
                )
            ),
            "branch_evidence_missing",
        ),
        (
            "direct_rag_answer_present",
            mirror_rag_envelope,
            "empty_set_not_proven",
        ),
        # commit 单条 / kind 类型 / 模板恒等。
        (
            "commit_missing",
            lambda: _append_retrieval(
                base.build_evidence(
                    units=[{"unit_id": "unit-1"}],
                    used_unit_ids=[],
                    final_source_ids=[],
                    use_model=False,
                    answer_kind="not_found",
                    answer_text=template,
                    missing_commit=True,
                )
            ),
            "empty_set_not_proven",
        ),
        (
            "commit_duplicated",
            lambda: duplicate_event(mirror_envelope(), "commit_observed"),
            "empty_set_not_proven",
        ),
        (
            "commit_kind_not_str",
            lambda: set_payload_key(mirror_envelope(), "commit_observed", "kind", 123),
            "empty_set_not_proven",
        ),
        (
            "free_text_answer",
            lambda: mirror_envelope(text="合成自由文本：资料里没有，但这不是固定模板"),
            "empty_set_not_proven",
        ),
        (
            "template_with_appended_fact",
            lambda: mirror_envelope(text=template + " 联系电话 13800000000"),
            "empty_set_not_proven",
        ),
        (
            "wrong_kind_template",
            lambda: mirror_envelope(text=base.real_no_fact_text("knowledge_changed")),
            "empty_set_not_proven",
        ),
        # 检索层本身不可核。
        (
            "retrieval_unit_ids_bad_type",
            lambda: mutate_event(mirror_envelope(), "retrieval_observed", unit_ids="unit-1"),
            "branch_evidence_missing",
        ),
        (
            "retrieval_unit_ids_key_missing",
            lambda: drop_payload_key(mirror_envelope(), "retrieval_observed", "unit_ids"),
            "branch_evidence_missing",
        ),
    ]


_COUNTEREXAMPLES = _counterexamples()


@pytest.mark.parametrize(
    ("name", "factory", "reason"),
    _COUNTEREXAMPLES,
    ids=[name for name, _factory, _reason in _COUNTEREXAMPLES],
)
def test_counterexamples_stay_rejected_under_v0_5(
    name: str, factory: Callable[[], dict[str, Any]], reason: str
) -> None:
    envelope = factory()
    baseline = hard._empty_use_scope_proof(envelope)
    assert baseline == (False, reason), (name, baseline)
    for compat in OLD_VERSIONS:
        assert hard._empty_use_scope_proof(envelope, compat=compat) == baseline, (name, compat)
    # v0.5 在这些形状上必须与 v0.1 逐值相同（镜像不成立 / 其它前提缺一即维持原判）。
    assert hard._empty_use_scope_proof(envelope, compat=V05) == baseline, name


def test_counterexamples_stay_unknown_at_axis_level_under_v0_5() -> None:
    case = base._one_case()
    annotation = base._single(case)
    for name, factory, _reason in _COUNTEREXAMPLES:
        envelope = factory()
        old = classify(case, annotation, envelope, compat=V04)
        new = classify(case, annotation, envelope, compat=V05)
        # 空集证明被拒后两轴不得**同时** passed；且各轴与 v0.4 逐值相同
        # （`model_evidence_non_empty` 的 stale_source 走真实使用层路径，见 C16 文件同款注释）。
        assert not (
            new.axis("cross_entity").state == "passed"
            and new.axis("stale_source").state == "passed"
        ), (name, new.as_dict())
        assert old.axis("cross_entity").as_dict() == new.axis("cross_entity").as_dict(), name
        assert old.axis("stale_source").as_dict() == new.axis("stale_source").as_dict(), name


# --------------------------------------------------------------------------- #
# 4) 审计码：放行样本出现 projection_mirrors_retrieval，被拒样本不出现
# --------------------------------------------------------------------------- #


def test_audit_code_present_on_accepted_sample_only() -> None:
    accepted = audit_refs(mirror_envelope(), V05)
    assert any(ref.endswith("." + AUDIT_MIRROR) for ref in accepted), accepted
    assert any(ref.endswith("." + AUDIT_RETRIEVAL_UNUSED) for ref in accepted), accepted
    assert any(ref.endswith(".empty_use_scope") for ref in accepted), accepted
    # 同一形状在旧版本被拒 → 审计码不得出现。
    for compat in OLD_VERSIONS:
        refs = audit_refs(mirror_envelope(), compat)
        assert all(not ref.endswith("." + AUDIT_MIRROR) for ref in refs), (compat, refs)


def test_audit_code_absent_when_projection_stays_empty() -> None:
    """投影为空时不需要镜像放行（v0.4 旧路径）→ v0.5 也不得记镜像码。

    这里的 envelope 是 v0.4 契约当初 pin 的“投影为空 + 检索非空”形状：生产上不可达，
    只用于核 v0.5 不得在**无需镜像**的路径上误记镜像审计码。
    """
    empty_projection = _append_retrieval(
        base.build_evidence(
            units=[],
            used_unit_ids=[],
            final_source_ids=[],
            use_model=False,
            answer_kind="not_found",
            answer_text=no_fact_text(),
        )
    )
    assert empty_projection["db_projection"]["units"] == []
    assert hard._empty_use_scope_proof(empty_projection, compat=V05) == OK
    refs = audit_refs(empty_projection, V05)
    assert any(ref.endswith("." + AUDIT_RETRIEVAL_UNUSED) for ref in refs), refs
    assert all(not ref.endswith("." + AUDIT_MIRROR) for ref in refs), refs


def test_audit_code_absent_on_every_rejected_sample() -> None:
    for name, factory, _reason in _COUNTEREXAMPLES:
        refs = audit_refs(factory(), V05)
        assert all(not ref.endswith("." + AUDIT_MIRROR) for ref in refs), (name, refs)


# --------------------------------------------------------------------------- #
# 5) 旧版不变自证：v0.1/v0.3/v0.4 在既有两套样本上逐值不变
# --------------------------------------------------------------------------- #


def _existing_samples() -> list[tuple[str, dict[str, Any]]]:
    """既有 62 passed（拒答兼容）与 28 passed（C16 v0.4）两套的全部样本。"""
    samples: list[tuple[str, dict[str, Any]]] = []
    for name, envelope in c16_prev._battery():
        samples.append(("c16_battery/" + name, envelope))
    for name, factory, _reason in c16_prev._counterexamples():
        samples.append(("c16_counterexample/" + name, factory()))
    for name, envelope in compat_prev._battery():
        samples.append(("refusal_battery/" + name, envelope))
    for name, factory, _reason in compat_prev._container_mutations():
        samples.append(("refusal_mutation/" + name, factory()))
    return samples


def test_old_versions_value_identical_on_all_existing_samples() -> None:
    flips_v03_v04: list[str] = []
    flips_v04_v05: list[str] = []
    for name, envelope in _existing_samples():
        assert hard._empty_use_scope_proof(envelope) == hard._empty_use_scope_proof(
            envelope, compat=V01
        ), name
        v03 = hard._empty_use_scope_proof(envelope, compat=V03)
        v04 = hard._empty_use_scope_proof(envelope, compat=V04)
        v05 = hard._empty_use_scope_proof(envelope, compat=V05)
        relax_v04 = hard._retrieval_observed_unused_relaxable(envelope, compat=V04)
        if not relax_v04:
            # v0.4 的唯一增量以该判据为前提；判据不成立 ⇒ 三个版本走同一代码路径。
            assert v04 == v03, (name, v03, v04)
            assert v05 == v04, (name, v04, v05)
            continue
        if v03 != v04:
            flips_v03_v04.append(name)
        if v04 != v05:
            flips_v04_v05.append(name)
    # v0.4 在**可达**样本上不翻转任何形状（它只放行投影为空的旧夹具形状）。
    assert flips_v03_v04 == [], flips_v03_v04
    # v0.5 只翻转 C16 真实（镜像）形状这一处。
    assert flips_v04_v05 == ["c16_battery/c16_shape"], flips_v04_v05


def test_v0_4_flips_nothing_on_the_reachable_mirror_battery() -> None:
    """夹具修正后：v0.4 与 v0.3 在 C16 真实形状上逐值相同（这正是 v0.5 的动机）。"""
    mirror = mirror_envelope()
    assert hard._retrieval_observed_unused_relaxable(mirror, compat=V04) is True
    assert hard._empty_use_scope_proof(mirror, compat=V03) == hard._empty_use_scope_proof(
        mirror, compat=V04
    ) == REJECTED
    assert hard._empty_use_scope_proof(mirror, compat=V05) == OK
