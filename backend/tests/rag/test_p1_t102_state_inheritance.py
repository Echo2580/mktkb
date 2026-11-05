"""T102：组 A 状态继承（ERR-01/ERR-02）的查询规划单元用例。

不建索引、不调用模型：直接验证 ``parse_query`` 在“上一轮有实体”的前提下如何重置状态。
"""

from __future__ import annotations

import pytest

from mktkb.rag.query import Lexicon, _unknown_region_tokens, is_policy_question, parse_query
from mktkb.rag.types import QueryState


def _lexicon() -> Lexicon:
    return Lexicon(
        stores=("城东店", "城西店", "卓刀河店", "滨江店"),
        items=("宣传海报", "马克杯", "展架"),
        identifiers=("QF01", "QF21"),
    )


def _previous(store: str = "城东店", item: str | None = "宣传海报", field_role: str = "location") -> QueryState:
    return QueryState(
        user_id="u",
        conversation_id="c",
        store=store,
        stores=(store,),
        item=item,
        field_role=field_role,
        turn=1,
        last_kind="answer",
    )


def test_unknown_region_clears_inherited_store_and_clarifies() -> None:
    plan = parse_query("城西区的宣传海报在哪？", previous=_previous(), lexicon=_lexicon())

    assert plan.reason == "UNKNOWN_REGION"
    assert plan.clarification is not None
    assert "城西区" in plan.clarification
    assert "城东店" not in plan.clarification
    assert plan.state.store is None
    assert plan.state.stores == ()
    # 本轮明确说的物品仍保留，只清掉上一轮门店。
    assert plan.state.item == "宣传海报"
    assert plan.candidates == ()


@pytest.mark.parametrize(
    "question",
    [
        "黄金陈列位的高度区间是多少？",
        "华东大区现在叫什么名字？",
        "B区1号货架第二层在哪？",
        "经销商跨区串货第二次会怎么处理？",
        "城东店物料区的海报在哪？",
        "城市片区怎么划分？",
    ],
)
def test_region_like_words_are_not_misread(question: str) -> None:
    assert _unknown_region_tokens(question, _lexicon()) == ()


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("城西区的宣传海报在哪？", ("城西区",)),
        ("城南片区的宣传海报在哪？", ("城南片区",)),
        ("苏城市城西区的宣传海报在哪？", ("城西区",)),
        ("请问城西区有海报吗？", ("城西区",)),
    ],
)
def test_region_like_words_are_detected(question: str, expected: tuple[str, ...]) -> None:
    assert _unknown_region_tokens(question, _lexicon()) == expected


def test_policy_question_does_not_inherit_previous_entities() -> None:
    question = "档期物料要提前多少天提报需求？给出所有内容"
    assert is_policy_question(question)

    plan = parse_query(question, previous=_previous(store="卓刀河店", item="马克杯"), lexicon=_lexicon())

    assert plan.reason is None
    assert plan.clarification is None
    assert plan.mode == "document"
    assert plan.state.store is None
    assert plan.state.item is None
    assert plan.state.identifier is None
    assert plan.filters == {}
    # “给出所有内容”不应把政策事实题变成按标签排序的记录枚举页。
    assert plan.enumerate is False


def test_policy_list_request_keeps_enumeration() -> None:
    plan = parse_query("把所有制度列出来", previous=QueryState(), lexicon=_lexicon())

    assert plan.state.store is None
    assert plan.enumerate is True


def test_policy_question_with_field_like_word_still_resets() -> None:
    question = "档期物料提前多少天提报，时间怎么算？"

    plan = parse_query(question, previous=_previous(store="卓刀河店", item="马克杯"), lexicon=_lexicon())

    assert plan.state.store is None and plan.state.item is None
    # 政策题没有实体时不按记录字段规划，也就不会变成“请补充门店”的澄清。
    assert plan.field_role is None
    assert plan.mode == "document"


def test_topic_switch_without_entity_or_field_resets() -> None:
    plan = parse_query("公司今年营收是多少", previous=_previous(), lexicon=_lexicon())

    assert plan.state.store is None and plan.state.item is None
    assert plan.mode == "document"


def test_field_followup_still_inherits_previous_store_and_item() -> None:
    plan = parse_query("数量呢？", previous=_previous(), lexicon=_lexicon())

    assert plan.state.store == "城东店"
    assert plan.state.item == "宣传海报"
    assert plan.field_role == "quantity"


def test_anaphora_followup_still_inherits_previous_entities() -> None:
    plan = parse_query("它的电话呢？", previous=_previous(field_role="contact"), lexicon=_lexicon())

    assert plan.state.store == "城东店"
    assert plan.state.item == "宣传海报"
    assert plan.field_role == "phone"


def test_page_request_keeps_enumeration_state() -> None:
    previous = _previous(field_role="location")
    previous.enumerate = True
    previous.page = 1

    plan = parse_query("下一页", previous=previous, lexicon=_lexicon())

    assert plan.state.store == "城东店"
    assert plan.state.enumerate is True
    assert plan.page == 2
