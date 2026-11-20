"""v3-safety-fix 合成单测：安全拒答判据 + 实体型裸追问的继承收敛。

离线纯函数：只调用产品 ``parse_question`` / ``parse_query`` 与文案表，不建库、不检索、
不调模型、不出网。用例只按“本轮显式物品目标 + 显式个人联系字段”判定，不含题号/固定整句。
"""

from __future__ import annotations

import pytest

from mktkb import copy as copy_module
from mktkb.conversations import intent as intent_module
from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState

LEXICON = Lexicon(
    stores=("城东店", "城西店"),
    items=("宣传海报", "展架"),
    field_labels=("位置", "联系人", "电话", "地址", "合作状态"),
)

ENTITY_LEXICON = intent_module.EntityLexicon(
    store_labels=("城东店", "城西店"),
    item_labels=("宣传海报", "展架"),
    identifier_labels=("P01",),
)


def _intent(question: str, *, context_entities: dict[str, str] | None = None, context_questions=()):
    return intent_module.parse_question(
        question,
        lexicon=ENTITY_LEXICON,
        context_entities=context_entities,
        context_questions=tuple(context_questions),
    )


def _plan(question: str, previous: QueryState | None = None):
    return parse_query(question, previous=previous, lexicon=LEXICON, business_date="2026-10-15")


# ---------------------------------------------------------------- 安全拒答：正例


@pytest.mark.parametrize(
    "question",
    [
        "城东店宣传海报的位置和门店联系电话是多少？",
        "城东店展架的联系人是谁？",
        "城西店宣传海报放在哪，顺便把店家地址也给我",
        "城东店的宣传海报和展架的联系人电话是多少？",
        "城东店标识 P01 的联系电话是多少？",
    ],
)
def test_item_plus_contact_field_is_security_refusal(question: str):
    plan = _intent(question)
    assert plan.security_refusal == "SECURITY_RESTRICTED_CONTACT", plan
    assert plan.intent is not None


@pytest.mark.parametrize(
    "question",
    [
        "城东店宣传海报的位置和门店联系电话是多少？",
        # R0/C12（2026-11-16 安全边界收窄）：冻结契约要求 item + 只请求 contact
        # （联系人/对接人/负责人）放行（C12 t7：should_refuse=False，期望位置+对接人+合作状态），
        # 因此规划层安全覆盖改用同族的 phone/address 形态；contact-only 的放行与
        # phone/address 的继续拒答见 backend/tests/rag/test_r0_c12b_boundary_synthetic.py。
        # legacy 意图层（conversations/intent.py）未改，item + 联系人 在服务层仍整体拒答。
        "城东店展架的地址是多少？",
        "城东店的宣传海报和展架的联系人电话是多少？",
        "先看物品位置表。城东店宣传海报放哪？再从合作店家信息表给出城西店电话。",
        "城东店的宣传海报放哪？城西店的地址也请提供。",
    ],
)
def test_rag_planner_marks_item_plus_phone_or_address_as_security_refusal(question: str):
    plan = _plan(question)
    assert plan.reason == "SECURITY_RESTRICTED_CONTACT", plan.reason


def test_security_refusal_copy_is_fixed_skeleton_without_values():
    text = copy_module.text("SECURITY_RESTRICTED_CONTACT")
    for leaked in ("010-", "示例路", "陈宁", "王平", "S01", "S02"):
        assert leaked not in text
    assert "个人信息" in text
    assert "不是资料中没有答案" in text
    entry = copy_module.COPY["SECURITY_RESTRICTED_CONTACT"]
    assert entry.retryable is True
    assert entry.material_related is False
    assert entry.requires_user_input is True


# ---------------------------------------------------------------- 安全拒答：反例（不得假拒答）


@pytest.mark.parametrize(
    "question",
    [
        "城东店的展架在哪里？",  # 纯物品字段
        "城西店的宣传海报在哪里？",  # 纯物品字段
        "城东店的电话是多少？",  # 纯店家级联系信息（既有路径，不作答者外拒）
        "城东店和城西店的电话是多少？",  # fix-1/A 正例：多门店电话仍逐条作答
        "城东店的合作状态是什么？",  # 店家级非联系字段
    ],
)
def test_benign_record_question_is_not_security_refused(question: str):
    plan = _intent(question)
    assert plan.security_refusal is None, plan.security_refusal
    rag_plan = _plan(question)
    assert rag_plan.reason != "SECURITY_RESTRICTED_CONTACT"


def test_policy_question_with_contact_word_is_not_security_refused():
    question = "宣传海报的物料领用规定里要求登记联系人吗？"
    plan = _intent(question)
    assert plan.security_refusal is None, plan.security_refusal
    assert _plan(question).reason != "SECURITY_RESTRICTED_CONTACT"


def test_item_only_question_without_contact_field_keeps_features():
    plan = _plan("城东店的展架在哪里？")
    assert plan.mode == "record"
    assert plan.reason is None or plan.reason == "MULTI_TARGET_ENUMERATE"
    assert _rag_owns_turn(QueryState(), plan) is False


# ---------------------------------------------------------------- 实体型裸追问：正例


def test_bare_item_followup_inherits_store_and_location_field():
    plan = _intent(
        "宣传海报呢？",
        context_entities={"store": "城东店", "item": "展架"},
        context_questions=("城东店的展架在哪里？",),
    )
    assert plan.security_refusal is None
    assert plan.intent is not None
    assert plan.intent.mode == "record"
    assert plan.intent.entity_filters == {"store": "城东店", "item": "宣传海报"}
    assert plan.requested_fields == ("位置",)


def test_bare_item_followup_with_store_level_previous_field_does_not_inherit_item_field():
    """反例：上一轮问的是店家级联系信息时，物品型裸追问不按物品行字段收敛。"""
    plan = _intent(
        "宣传海报呢？",
        context_entities={"store": "城东店"},
        context_questions=("城东店的电话是多少？",),
    )
    assert plan.intent is None or plan.intent.mode != "record" or not plan.requested_fields


def test_bare_item_followup_without_context_stays_unscoped():
    """反例：没有上文门店/字段时不臆造实体条件（保持既有正文/澄清路径）。"""
    plan = _intent("宣传海报呢？")
    assert plan.intent is None or plan.intent.entity_filters in ({}, {"item": "宣传海报"})
    assert "store" not in (plan.intent.entity_filters if plan.intent else {})
