"""T-R1-102b：三回合序列里的唯一门店范围（M3）。

合成序列（全部为假数据：门店 甲店/乙店，物品 立牌，位置 甲区/乙区）：
1. t1 点名甲店的立牌位置 → ``filters={store:甲店, item:立牌}``，只答甲区；
2. t2 换话题（政策/流程类，无实体无记录字段）→ 本轮不得把上一轮门店写成检索条件；
3. t3 只问物品位置（不再重复门店）→ ``filters`` 仍含 ``store=甲店``，答案/事实只出现甲区。

机制出处：``mktkb/rag/query.py`` 的 ``parse_query``/``_new_state``——话题切换重置把
``state.store``/``state.stores`` 一并清空后，下一轮的裸追问没有门店可继承，跨店列出记录。

边界（同一文件内的合法反例）：
- 显式“甲店和乙店”问法仍按多店枚举，不因保留的作用域被收窄；
- 多轮里显式换了另一家店时，按**最新显式门店**作答，不在两家店之间猜。
"""

from __future__ import annotations

from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState

ROWS = [
    {"门店": "甲店", "物品": "立牌", "位置": "甲区"},
    {"门店": "乙店", "物品": "立牌", "位置": "乙区"},
]
TURN_SCOPE = "甲店的立牌位置在哪？"
TURN_TOPIC = "调拨需要谁同意？"
TURN_BARE = "立牌现在放在哪个货架？"


def test_explicit_field_scopes_survive_paging() -> None:
    lexicon = Lexicon(stores=("甲店", "乙店"), items=("立牌",))
    first = parse_query(
        "甲店的立牌在哪个位置？乙店合作状态如何，电话也告诉我。",
        previous=QueryState(user_id="u", conversation_id="c"),
        lexicon=lexicon,
        page_size=1,
    )
    second = parse_query("第2页", previous=first.state, lexicon=lexicon, page_size=1)
    assert first.record_field_stores == second.record_field_stores == {
        "location": "甲店",
        "status": "乙店",
    }


def test_explicit_field_scopes_render_only_matching_records(rag_index, add_records, make_doc) -> None:
    add_records(ROWS, doc=make_doc(title="物品位置表"))
    add_records([
        {"店家": "甲店", "合作状态": "合作中"},
        {"店家": "乙店", "合作状态": "暂停合作", "电话": "020-00000011"},
    ], doc=make_doc(title="合作状态表"))
    answer = rag_index.ask(
        "甲店的立牌在哪个位置？乙店合作状态如何，电话也告诉我。",
        user_id="u", conversation_id="scoped-fields",
    )
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert {(fact.field_role, fact.value) for fact in answer.facts} == {
        ("location", "甲区"), ("status", "暂停合作"),
    }
    assert len(answer.citations) == 2
    assert all(value not in answer.text for value in ("乙区", "合作中", "020-00000011"))


def test_explicit_field_scopes_reject_ambiguous_store_rows(rag_index, add_records, make_doc) -> None:
    add_records(ROWS, doc=make_doc(title="物品位置表"))
    add_records([
        {"店家": "乙店", "合作状态": "合作中"},
        {"店家": "乙店", "合作状态": "暂停合作"},
    ], doc=make_doc(title="合作状态表"))
    answer = rag_index.ask(
        "甲店的立牌在哪个位置？乙店合作状态如何？",
        user_id="u", conversation_id="scoped-duplicate",
    )
    assert answer.reason == "MULTIPLE_ENTITIES", (answer.kind, answer.reason, answer.text)
    assert answer.facts == []
    assert answer.citations == []


def _seed(add_records, make_doc) -> None:
    add_records(ROWS, doc=make_doc(title="终端物料位置表"))


def _filters(answer) -> dict:
    return dict(answer.diagnostics["plan"]["filters"])


def test_topic_turn_does_not_filter_by_previous_store(rag_index, add_records, make_doc) -> None:
    """对照：换话题轮本身不继承上一轮门店（既有 T102 口径保持不变）。"""

    _seed(add_records, make_doc)
    first = rag_index.ask(TURN_SCOPE, user_id="u", conversation_id="c-topic")
    assert first.kind == "answer", (first.kind, first.reason, first.text)
    assert _filters(first) == {"store": "甲店", "item": "立牌"}

    topic = rag_index.ask(TURN_TOPIC, user_id="u", conversation_id="c-topic")
    assert _filters(topic) == {}, (topic.kind, topic.reason, topic.text)
    assert topic.state["store"] is None


def test_bare_followup_after_topic_turn_keeps_unique_store_scope(rag_index, add_records, make_doc) -> None:
    """红（修复前）：t3 的 filters 只剩 item，答案跨店列出甲区与乙区。"""

    _seed(add_records, make_doc)
    rag_index.ask(TURN_SCOPE, user_id="u", conversation_id="c-bare")
    rag_index.ask(TURN_TOPIC, user_id="u", conversation_id="c-bare")

    third = rag_index.ask(TURN_BARE, user_id="u", conversation_id="c-bare")
    filters = _filters(third)
    assert filters.get("store") == "甲店", (filters, third.kind, third.reason, third.text)
    assert "乙区" not in third.text, (third.kind, third.reason, third.text)
    assert "甲区" in third.text, (third.kind, third.reason, third.text)
    assert {fact.value for fact in third.facts} <= {"甲区"}, [
        (fact.field_role, fact.value) for fact in third.facts
    ]
    # 来源也只引用甲店那一条记录（不把乙店的记录当依据带出来）。
    assert third.citations, (third.kind, third.text)
    assert all("甲店" in citation.text for citation in third.citations), [
        citation.text for citation in third.citations
    ]
    assert all("乙店" not in citation.text for citation in third.citations), [
        citation.text for citation in third.citations
    ]


def test_explicit_multi_store_question_still_enumerates(rag_index, add_records, make_doc) -> None:
    """合法反例：显式点名两家店时仍枚举多店，不被保留的作用域收窄。"""

    _seed(add_records, make_doc)
    rag_index.ask(TURN_SCOPE, user_id="u", conversation_id="c-multi")
    rag_index.ask(TURN_TOPIC, user_id="u", conversation_id="c-multi")

    third = rag_index.ask(
        "甲店和乙店的立牌位置分别列一下？", user_id="u", conversation_id="c-multi"
    )
    filters = _filters(third)
    assert "store" not in filters, (filters, third.kind, third.reason, third.text)
    assert third.kind == "answer", (third.kind, third.reason, third.text)
    assert "甲区" in third.text and "乙区" in third.text, (third.kind, third.text)


def test_topic_turn_retains_scope_without_making_it_a_filter(rag_index, add_records, make_doc) -> None:
    """机制：话题轮把唯一门店留在 ``stores``（不是 ``store``），本轮 filters 仍为空。"""

    _seed(add_records, make_doc)
    rag_index.ask(TURN_SCOPE, user_id="u", conversation_id="c-retain")
    rag_index.ask(TURN_TOPIC, user_id="u", conversation_id="c-retain")

    state = rag_index.load_state("u", "c-retain")
    assert state.store is None
    assert state.stores == ("甲店",)


def test_retained_scope_turn_is_owned_by_rag_kernel() -> None:
    """产品层分流：收回保留作用域的记录追问必须由内核结构化作答，不交给只读题面的 legacy。"""

    lexicon = Lexicon(stores=("甲店", "乙店"), items=("立牌",))
    previous = QueryState(user_id="u", conversation_id="c", stores=("甲店",), turn=2)
    plan = parse_query(TURN_BARE, previous=previous, lexicon=lexicon)

    assert plan.filters == {"store": "甲店", "item": "立牌"}
    assert _rag_owns_turn(previous, plan) is True


def test_later_explicit_store_replaces_scope_without_guessing(rag_index, add_records, make_doc) -> None:
    """冲突反例：多轮出现两家店时按最新显式门店作答，不混店、不猜。"""

    _seed(add_records, make_doc)
    rag_index.ask(TURN_SCOPE, user_id="u", conversation_id="c-switch")

    second = rag_index.ask("乙店的立牌位置在哪？", user_id="u", conversation_id="c-switch")
    assert _filters(second).get("store") == "乙店", (second.kind, second.reason, second.text)
    assert "乙区" in second.text and "甲区" not in second.text, (second.kind, second.text)

    third = rag_index.ask(TURN_BARE, user_id="u", conversation_id="c-switch")
    assert _filters(third).get("store") == "乙店", (third.kind, third.reason, third.text)
    assert "甲区" not in third.text, (third.kind, third.reason, third.text)
    assert {fact.value for fact in third.facts} <= {"乙区"}, [
        (fact.field_role, fact.value) for fact in third.facts
    ]
