"""v3-fix-1/A 合成回归：单轮多目标走多目标执行，真歧义仍澄清。

全部为离线合成数据：临时 SQLite + 确定性 offline provider（conftest 的 ``rag_index``），
不建产品库、不调模型/embedding/rerank、不开端口、不发请求。
"""

from __future__ import annotations

import pytest

from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState

LEXICON = Lexicon(
    stores=("城东店", "城西店"),
    items=("宣传海报", "易拉宝"),
    field_labels=("位置", "电话"),
)


def _plan(question: str, previous: QueryState | None = None):
    return parse_query(
        question, previous=previous, lexicon=LEXICON, business_date="2026-10-15"
    )


# --------------------------------------------------------------------- 正例（规划器）


@pytest.mark.parametrize(
    "question",
    [
        "城东店和城西店的宣传海报在哪里？",  # 两个门店、一个物品
        "城东店的宣传海报和易拉宝在哪里？",  # 一个门店、两个物品
        "城东店和城西店的电话是多少？",  # 两个门店、门店级字段（无单值实体过滤）
    ],
)
def test_multi_target_is_executed_not_clarified(question: str):
    plan = _plan(question)
    assert plan.clarification is None, plan.clarification
    assert plan.mode == "record"
    assert plan.enumerate is True
    assert plan.reason == "MULTI_TARGET_ENUMERATE"
    # 产品层必须把这类轮次交给 rag 内核（否则会退回 legacy 的“多个实体→澄清”）。
    assert _rag_owns_turn(QueryState(), plan) is True


def test_multi_target_state_keeps_all_named_targets():
    stores_plan = _plan("城东店和城西店的宣传海报在哪里？")
    assert stores_plan.state.stores == ("城东店", "城西店")
    assert stores_plan.state.pending_slot is None

    items_plan = _plan("城东店的宣传海报和易拉宝在哪里？")
    assert items_plan.state.items == ("宣传海报", "易拉宝")
    assert items_plan.state.store == "城东店"


# --------------------------------------------------------------- 正例（端到端离线内核）


def _seed_multi_target(add_records, make_doc):
    doc = make_doc(title="物品位置表")
    add_records(
        [
            {"门店": "城东店", "物品": "宣传海报", "位置": "A区1号货架"},
            {"门店": "城西店", "物品": "宣传海报", "位置": "B区2号货架"},
            {"门店": "城东店", "物品": "易拉宝", "位置": "C区门口"},
            {"门店": "城西店", "物品": "易拉宝", "位置": "D区立柱"},
        ],
        doc=doc,
    )
    return doc


def test_two_stores_one_item_answers_both_targets(rag_index, add_records, make_doc):
    _seed_multi_target(add_records, make_doc)
    answer = rag_index.ask(
        "城东店和城西店的宣传海报在哪里？", user_id="u", conversation_id="c-multi-stores"
    )
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "A区1号货架" in answer.text and "B区2号货架" in answer.text
    # 只取被点名的两个目标，不多带同门店的其它物品。
    assert answer.diagnostics["returned"] == 2
    assert "C区门口" not in answer.text and "D区立柱" not in answer.text


def test_one_store_two_items_answers_both_targets(rag_index, add_records, make_doc):
    _seed_multi_target(add_records, make_doc)
    answer = rag_index.ask(
        "城东店的宣传海报和易拉宝在哪里？", user_id="u", conversation_id="c-multi-items"
    )
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "A区1号货架" in answer.text and "C区门口" in answer.text
    # 只取被点名的两个物品：城西店与其它物品的行不进作答证据面。
    assert answer.diagnostics["returned"] == 2
    assert "B区2号货架" not in answer.text and "D区立柱" not in answer.text


def test_two_stores_store_level_field_answers_both(rag_index, add_records, make_doc):
    """门店级字段（无物品维度）：多门店目标同样逐条作答。"""
    doc = make_doc(title="合作店家信息")
    add_records(
        [
            {"门店": "城东店", "联系人": "张", "电话": "010-00000001"},
            {"门店": "城西店", "联系人": "李", "电话": "010-00000002"},
        ],
        doc=doc,
    )
    answer = rag_index.ask(
        "城东店和城西店的电话是多少？", user_id="u", conversation_id="c-multi-phone"
    )
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "010-00000001" in answer.text and "010-00000002" in answer.text
    assert answer.diagnostics["returned"] == 2


# --------------------------------------------------------------------- 反例（真歧义）


def test_two_stores_two_items_still_clarify(rag_index, add_records, make_doc):
    """两维同时点名多个目标 = 交叉配对不明，仍按澄清处理（不得一概放行）。"""
    _seed_multi_target(add_records, make_doc)
    plan = _plan("城东店和城西店的宣传海报和易拉宝在哪里？")
    assert plan.clarification is not None
    assert plan.reason == "ITEM_AMBIGUOUS"
    assert plan.enumerate is False

    answer = rag_index.ask(
        "城东店和城西店的宣传海报和易拉宝在哪里？",
        user_id="u",
        conversation_id="c-multi-cross",
    )
    assert answer.kind == "clarification"


def test_unknown_store_is_not_treated_as_multi_target(rag_index, add_records, make_doc):
    """词表外门店不能被“多目标”吞掉：不进入多目标执行，且未知名进 missing_stores。

    注：未知名与已知名同时出现时“只答已知名、不披露未知名”是既有行为，本包不改它的
    披露口径（登记为本包残余），这里只锁定“不因多目标把未知名当成目标执行”。
    """
    _seed_multi_target(add_records, make_doc)
    plan = _plan("城东店和城南店的宣传海报在哪里？")
    assert plan.reason != "MULTI_TARGET_ENUMERATE"
    assert "城南店" in plan.missing_stores

    answer = rag_index.ask(
        "城东店和城南店的宣传海报在哪里？", user_id="u", conversation_id="c-unknown"
    )
    assert "城南店" not in answer.text
    assert answer.kind in {"answer", "clarification"}, answer.kind


def test_unnamed_targets_still_clarify(rag_index, add_records, make_doc):
    """反例：目标没有点名（纯指代）时仍走既有澄清，不因“可能多个”放行。"""
    _seed_multi_target(add_records, make_doc)
    plan = _plan("这两个分别放在哪里？")
    assert plan.reason != "MULTI_TARGET_ENUMERATE"
    assert plan.clarification is not None

    answer = rag_index.ask("这两个分别放在哪里？", user_id="u", conversation_id="c-anaphora")
    assert answer.kind == "clarification"


def test_multi_target_without_answerable_field_is_not_released(rag_index, add_records, make_doc):
    """没有可回答的字段角色时不进入多目标执行（保持既有正文/澄清路径）。"""
    _seed_multi_target(add_records, make_doc)
    plan = _plan("城东店和城西店的宣传海报和易拉宝")
    assert plan.reason != "MULTI_TARGET_ENUMERATE"
    assert _rag_owns_turn(QueryState(), plan) is False
