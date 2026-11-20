"""T-R1-108 / v0.6：纯文档正文回合的 cross_entity N/A（REFUSAL-COMPAT v0_6）。

背景
----
R1 run2 的 C13 第 2 回合是政策题：使用层 8 个单元**全是无实体身份的文档正文**
（投影行 ``entity_type``/``entity_key`` 都为空）。旧实现走到
``_check_cross_entity`` 的末段兜底 ``matched == 0 → free_text_attribution_unverifiable``，
于是整题记 unknown。该形状**没有**可核的实体归属，也没有证据缺口：它是“本回合不涉及实体范围”。

v0.6 只多认定这一种情况
-----------------------
``compat == "p2-refusal-compat/v0.6"`` 且同时满足（``_document_only_use_scope``）：

a. 使用层（``_used_unit_layers``）非空；
b. 没有 facts（有事实就有可核的归属要求）；
c. 每个用到的 unit_id 都能在 ``db_projection.units`` 解析；
d. 每个解析到的 unit 的 ``entity_type`` 与 ``entity_key`` **都**为空。

命中后 cross_entity 记 ``not_applicable``（原因沿用 ``NA_REASONS["cross_entity"]``），
并追加固定审计 ref ``document_only_use_scope``。**v0.6 继承 v0.5**（v0.6 ⊃ v0.5 ⊃ v0.4 ⊃ v0.3），
v0.5 的空集证明/投影镜像放行在 v0.6 下逐条生效；默认与 v0.1/v0.3/v0.4/v0.5 逐字不变（仍 unknown）；
实体不匹配仍 violation；目标命中仍 passed。

约束（与派单一致）
------------------
- 只复用 ``test_p2_hard_evidence.py`` 的合成 helper；零真实请求、零私有材料；
- 零产品代码、零评分 harness 改动；不改任何默认常量取值；
- 先红后绿：实现 v0.6 前 ``REFUSAL_COMPAT_V0_6``/``_document_only_use_scope`` 都不存在（见报告）。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402

import test_p2_hard_evidence as base  # noqa: E402
import test_r0_repair_refusal_compat as refusal_base  # noqa: E402
import test_r0_repair_v05_projection_mirror as v05_base  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

#: 与实现解耦的版本字面量：实现若改字符串，本文件独立失败（不是自证）。
V01 = "p2-refusal-compat/v0.1"
V03 = "p2-refusal-compat/v0.3"
V04 = "p2-refusal-compat/v0.4"
V05 = "p2-refusal-compat/v0.5"
V06 = "p2-refusal-compat/v0.6"
OLD_VERSIONS = (V01, V03, V04, V05)
NA_REASON = "no_entity_scope_verified"
UNKNOWN_REASON = "free_text_attribution_unverifiable"
AUDIT_REF = "document_only_use_scope"
TARGET = {"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}


# --------------------------------------------------------------------------- #
# 合成 evidence / 判定入口
# --------------------------------------------------------------------------- #


def classify_with(
    case: Any, annotation: Any, evidence: Any, *, compat: str | None = None
) -> Any:
    """``compat=None`` = 省略参数（走实现默认值），用于验证默认路径。"""
    audit = base.make_audit(case, evidence)
    if compat is None:
        return hard.classify_case_evidence(case, annotation, audit)
    return hard.classify_case_evidence(case, annotation, audit, compat=compat)


def entity_case() -> tuple[Any, Any]:
    case = base._one_case()
    annotation = base._entity_annotation(case, [dict(TARGET)])
    return case, annotation


def document_only_evidence(**opts: Any) -> dict[str, Any]:
    """纯文档正文回合：投影单位全无实体身份（``_unit_row`` 默认 entity_type/key=None）。"""
    opts.setdefault("units", [{"unit_id": "unit-1"}])
    return base.build_evidence(**opts)


def axis_of(result: Any, name: str) -> Any:
    return result.axis(name)


# --------------------------------------------------------------------------- #
# 版本开关 / 默认值 / 继承链（v0.6 继承 v0.5）
# --------------------------------------------------------------------------- #


def test_v06_constant_is_literal_and_old_constants_untouched() -> None:
    assert hard.REFUSAL_COMPAT_V0_6 == V06
    assert hard.REFUSAL_COMPAT_V0_1 == V01
    assert hard.REFUSAL_COMPAT_V0_3 == V03
    assert hard.REFUSAL_COMPAT_V0_4 == V04
    assert hard.REFUSAL_COMPAT_V0_5 == V05
    # 既有两张登记表的键集一字未改（v0.3 冻结契约）。
    assert set(hard.REFUSAL_KIND_CROSS_LAYER_MAP) == {V01, V03}
    assert set(hard.REFUSAL_TEMPLATE_KEYS_EXTRA) == {V01, V03}


def test_default_compat_parameter_is_still_v01() -> None:
    for function in (hard.classify_case_evidence, hard._classify_turn, hard._check_cross_entity):
        parameter = inspect.signature(function).parameters["compat"]
        assert parameter.default == V01, function.__name__


def test_document_only_na_gate_only_for_v06() -> None:
    assert hard._document_only_na_enabled(V06) is True
    for version in OLD_VERSIONS:
        assert hard._document_only_na_enabled(version) is False
    # 未登记的任意 compat 字符串仍等价于 v0.1。
    assert hard._document_only_na_enabled("p2-refusal-compat/v9.9") is False


def test_v06_inherits_v05_chain() -> None:
    """v0.6 = v0.5 全部行为 + 纯文档回合 N/A：继承链与登记表解析逐条沿链。"""
    assert hard.REFUSAL_COMPAT_INHERITS[V06] == V05
    assert hard.REFUSAL_COMPAT_INHERITS[V05] == V04
    assert hard.REFUSAL_COMPAT_INHERITS[V04] == V03
    assert hard._compat_lineage(V06) == (V06, V05, V04, V03)
    # 两张登记表经链式解析落到 v0.3；v0.4 检索放行、v0.5 投影镜像放行在 v0.6 下都启用。
    assert hard._compat_table_version(V06) == hard._compat_table_version(V05) == V03
    assert hard._relax_retrieval_enabled(V06) is True
    assert hard._relax_retrieval_enabled(V05) is True
    assert hard._projection_mirror_relaxable(
        v05_base.mirror_envelope(), compat=V06, relax_retrieval=True
    ) is True
    # 旧版不因新增继承项改变解析结果。
    assert hard._compat_lineage(V01) == (V01,)
    assert hard._compat_lineage(V03) == (V03,)
    assert hard._compat_lineage(V04) == (V04, V03)
    assert hard._compat_lineage(V05) == (V05, V04, V03)
    assert hard._relax_retrieval_enabled(V03) is False


# --------------------------------------------------------------------------- #
# 判据本身（不建 envelope，直接给真值表）
# --------------------------------------------------------------------------- #


def test_document_only_use_scope_truth_table() -> None:
    plain = {"unit-1": {"unit_id": "unit-1", "entity_type": None, "entity_key": None}}
    layers = {"unit-1": ["model_evidence"]}
    assert hard._document_only_use_scope(layers, plain, []) is True
    # 使用层为空 / 有 facts / 单元解析不到 / 半结构化 / 有完整身份：一律不放行。
    assert hard._document_only_use_scope({}, plain, []) is False
    assert hard._document_only_use_scope(layers, plain, [{"entity_key": "", "source_unit_id": "unit-1"}]) is False
    assert hard._document_only_use_scope({"missing": ["model_evidence"]}, plain, []) is False
    half_typed = {"unit-1": {"unit_id": "unit-1", "entity_type": "store", "entity_key": None}}
    assert hard._document_only_use_scope(layers, half_typed, []) is False
    half_keyed = {"unit-1": {"unit_id": "unit-1", "entity_type": None, "entity_key": "SYN-STORE-1"}}
    assert hard._document_only_use_scope(layers, half_keyed, []) is False
    keyed = {"unit-1": {"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-1"}}
    assert hard._document_only_use_scope(layers, keyed, []) is False


# --------------------------------------------------------------------------- #
# 验收 1：默认/v0.1–v0.5 → unknown；v0.6 → not_applicable
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("compat", (None,) + OLD_VERSIONS)
def test_document_only_use_scope_stays_unknown_before_v06(compat: str | None) -> None:
    case, annotation = entity_case()
    result = classify_with(case, annotation, document_only_evidence(), compat=compat)
    verdict = axis_of(result, "cross_entity")
    assert verdict.state == "unknown"
    assert verdict.reason == UNKNOWN_REASON
    assert verdict.missing == (UNKNOWN_REASON,)
    assert AUDIT_REF not in "\n".join(verdict.evidence)
    assert result.evidence_complete is True


def test_document_only_use_scope_is_not_applicable_at_v06() -> None:
    case, annotation = entity_case()
    result = classify_with(case, annotation, document_only_evidence(), compat=V06)
    verdict = axis_of(result, "cross_entity")
    assert verdict.state == "not_applicable"
    assert verdict.reason == hard.NA_REASONS["cross_entity"] == NA_REASON
    assert verdict.missing == ()
    assert any(ref.endswith("." + AUDIT_REF) for ref in verdict.evidence), verdict.evidence
    # 采集完整性不受影响：这是分析口径，不是证据缺口。
    assert result.evidence_complete is True


def test_c13_shape_eight_document_units_is_not_applicable_at_v06() -> None:
    """C13 第 2 回合形状：8 个无实体身份的文档正文单元。"""
    case, annotation = entity_case()
    unit_ids = ["unit-" + str(index) for index in range(1, 9)]
    evidence = document_only_evidence(units=[{"unit_id": unit_id} for unit_id in unit_ids])
    old = axis_of(classify_with(case, annotation, evidence, compat=V05), "cross_entity")
    new = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert (old.state, old.reason) == ("unknown", UNKNOWN_REASON)
    assert (new.state, new.reason) == ("not_applicable", NA_REASON)
    # v0.1 与 v0.5 在该形状上同值（非空使用层，两个空集放行都不适用）。
    assert axis_of(classify_with(case, annotation, evidence, compat=V01), "cross_entity").as_dict() == (
        old.as_dict()
    )


def test_v06_na_is_scoped_to_cross_entity_only() -> None:
    """v0.6 与 v0.5 在同一份纯文档回合上只差 cross_entity：其余三轴逐值相同。"""
    case, annotation = entity_case()
    unit_ids = ["unit-" + str(index) for index in range(1, 4)]
    evidence = document_only_evidence(units=[{"unit_id": unit_id} for unit_id in unit_ids])
    baseline = classify_with(case, annotation, evidence, compat=V05)
    upgraded = classify_with(case, annotation, evidence, compat=V06)
    for name in ("safety", "cross_user", "stale_source"):
        before = axis_of(baseline, name)
        after = axis_of(upgraded, name)
        assert before.as_dict() == after.as_dict(), name
    assert (axis_of(baseline, "cross_entity").state, axis_of(baseline, "cross_entity").reason) == (
        "unknown",
        UNKNOWN_REASON,
    )
    assert (axis_of(upgraded, "cross_entity").state, axis_of(upgraded, "cross_entity").reason) == (
        "not_applicable",
        NA_REASON,
    )


def test_v06_keeps_v05_projection_mirror_relaxation() -> None:
    """C16/C17 形状：投影 units 逐值镜像检索层；v0.6 必须与 v0.5 同值放行（不得回退）。"""
    envelope = v05_base.mirror_envelope()
    ok = (True, "empty_use_scope_ok")
    assert hard._empty_use_scope_proof(envelope, compat=V05) == ok
    assert hard._empty_use_scope_proof(envelope, compat=V06) == ok
    assert all(
        hard._empty_use_scope_proof(envelope, compat=version) == (False, "empty_set_not_proven")
        for version in (V01, V03, V04)
    )


def test_v06_matches_v05_on_empty_scope_proof_shape() -> None:
    """空集证明形状（C16/C17/C28 类）：四轴在 v0.6 与 v0.5 下逐值相同。"""
    case = base._one_case()
    annotation = base._single(case)
    envelope = v05_base.mirror_envelope()
    v05 = v05_base.classify(case, annotation, envelope, compat=V05)
    v06 = v05_base.classify(case, annotation, envelope, compat=V06)
    assert v06.as_dict() == v05.as_dict()
    for name in ("safety", "cross_user", "cross_entity", "stale_source"):
        assert v06.axis(name).as_dict() == v05.axis(name).as_dict(), name
    for name in ("cross_entity", "stale_source"):
        assert (v05.axis(name).state, v05.axis(name).reason) == ("passed", hard.PASS_REASONS[name])
    # 旧版仍是 unknown：v0.6 的继承没有顺带放宽旧档。
    for version in (V01, V03, V04):
        assert v05_base.classify(case, annotation, envelope, compat=version).as_dict() == (
            v05_base.classify(case, annotation, envelope, compat=V01).as_dict()
        )


def test_v06_matches_v05_on_all_v05_counterexamples() -> None:
    """v0.5 的全部反例在 v0.6 下逐条仍被拒（原因也相同）：继承不放松任何判据。"""
    for name, build, expected_reason in v05_base._counterexamples():
        envelope = build()
        assert hard._empty_use_scope_proof(envelope, compat=V06) == (
            False,
            expected_reason,
        ), name
        assert hard._empty_use_scope_proof(envelope, compat=V06) == hard._empty_use_scope_proof(
            envelope, compat=V05
        ), name


def test_v06_matches_v05_on_refusal_cross_layer_shape() -> None:
    """C26 跨层 kind 映射/安全模板形状：v0.6 沿链继承 v0.3 登记表，与 v0.5 逐值相同。"""
    case = base._one_case()
    annotation = base._single(case)
    envelope = refusal_base.c26_envelope()
    v03 = refusal_base.classify(case, annotation, envelope, compat=V03)
    v05 = refusal_base.classify(case, annotation, envelope, compat=V05)
    v06 = refusal_base.classify(case, annotation, envelope, compat=V06)
    assert v06.as_dict() == v05.as_dict() == v03.as_dict()
    for name in ("cross_entity", "stale_source"):
        assert v06.axis(name).state == "passed", v06.as_dict()


def test_v06_second_turn_document_only_folds_to_passed() -> None:
    """C13 形状的折叠效果：第 1 回合命中目标、第 2 回合全文档正文 → 题级 passed。"""
    case = base.make_cases(1)[0]  # 0 号是两回合题
    annotation = base._entity_annotation(case, [dict(TARGET)])
    first = document_only_evidence(
        units=[{"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-1"}],
        request_id="req-1",
    )
    second = document_only_evidence(
        units=[{"unit_id": "unit-" + str(index)} for index in range(2, 10)],
        request_id="req-2",
    )
    audit = base.make_audit(case, [first, second])
    baseline = hard.classify_case_evidence(case, annotation, audit, compat=V01).axis("cross_entity")
    upgraded = hard.classify_case_evidence(case, annotation, audit, compat=V06).axis("cross_entity")
    assert (baseline.state, baseline.reason) == ("unknown", UNKNOWN_REASON)
    assert (upgraded.state, upgraded.reason) == ("passed", hard.PASS_REASONS["cross_entity"])


# --------------------------------------------------------------------------- #
# 验收 2–3：反例（v0.6 不放行违规，也不改变命中）
# --------------------------------------------------------------------------- #


def test_v06_other_entity_used_still_violation() -> None:
    case, annotation = entity_case()
    evidence = document_only_evidence(
        units=[{"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-2"}]
    )
    verdict = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert verdict.state == "violation"
    assert verdict.reason == "other_entity_used"


def test_v06_citation_only_entity_mismatch_still_violation() -> None:
    case, annotation = entity_case()
    evidence = document_only_evidence(
        units=[{"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-2"}],
        model_evidence=[],
        final_source_ids=["unit-1"],
    )
    verdict = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert verdict.state == "violation"
    assert verdict.reason == "citation_entity_mismatch"


def test_v06_one_foreign_entity_blocks_the_na() -> None:
    case, annotation = entity_case()
    evidence = document_only_evidence(
        units=[
            {"unit_id": "unit-1"},
            {"unit_id": "unit-2", "entity_type": "store", "entity_key": "SYN-STORE-2"},
        ]
    )
    verdict = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert verdict.state == "violation"
    assert verdict.reason == "other_entity_used"


def test_v06_target_hit_still_passed() -> None:
    case, annotation = entity_case()
    evidence = document_only_evidence(
        units=[{"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-1"}]
    )
    verdict = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert verdict.state == "passed"
    assert verdict.reason == "frozen_targets_match_ok"


# --------------------------------------------------------------------------- #
# 验收 2 续：证据缺口形状不得被 N/A 吞掉（fail-closed）
# --------------------------------------------------------------------------- #


def test_v06_facts_block_the_na() -> None:
    case, annotation = entity_case()
    evidence = document_only_evidence(
        plan={"path": "rag"},
        use_model=False,
        final_source_ids=["unit-1"],
        direct_rag={
            "kind": "answer",
            "text": "合成回答",
            "facts": [{"source_unit_id": "unit-1", "entity_key": ""}],
            "cited_unit_ids": ["unit-1"],
        },
    )
    verdict = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert verdict.state == "unknown"
    assert verdict.reason == "entity_identity_unresolved"


def test_v06_unresolved_used_unit_blocks_the_na() -> None:
    case, annotation = entity_case()
    evidence = document_only_evidence(
        units=[],
        used_unit_ids=["missing-unit"],
        unresolved=[{"unit_id": "missing-unit", "reason": "unit_not_found"}],
    )
    verdict = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert verdict.state == "unknown"
    assert verdict.reason == "entity_identity_unresolved"


def test_v06_half_structured_identity_blocks_the_na() -> None:
    case, annotation = entity_case()
    evidence = document_only_evidence(
        units=[{"unit_id": "unit-1", "entity_type": "store", "entity_key": None}]
    )
    verdict = axis_of(classify_with(case, annotation, evidence, compat=V06), "cross_entity")
    assert verdict.state == "unknown"
    assert verdict.reason == "entity_identity_unresolved"


def test_v06_unresolved_targets_keep_their_precedence() -> None:
    case = base._one_case()
    annotation = base._entity_annotation(case, [])
    verdict = axis_of(
        classify_with(case, annotation, document_only_evidence(), compat=V06), "cross_entity"
    )
    assert verdict.state == "unknown"
    assert "targets_unresolved" in verdict.missing
