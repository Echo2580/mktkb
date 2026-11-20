"""R1/T-R1-106b（C22）：多门店同现时的“主目标门店”。

合成（离线）：甲店宣传海报一行（位置 甲区一层）、乙店同物品一行（位置 乙区二层，
生效日期在未来）。问句同时提到两家门店，但只有甲店是被问目标——乙店那句
“有一条尚未生效的登记，现在能作为取用依据吗”只是旁证状态问题。

改前（红）：规划把两家门店都当目标（``MULTI_TARGET_ENUMERATE``），``state.store`` 还落在
排序靠后的乙店；答案按枚举渲染**乙店**那一行（位置 乙区二层、生效日期 2026-12-01），
并写“未在资料中找到：甲店”。这正是 C22 的跨实体违规：数值与引用来自异店。

改后（绿）：``PRIMARY_STORE_TARGET``——取值与引用只来自甲店；乙店只出现名字与
“尚未生效／不能作为依据”的状态说明（日期以外不渲染其行值、不作为引用）。

反例（不得误收窄）：显式“都列出来／分别”仍枚举两家；两家各问同一字段仍按多目标执行；
单店问法不变。

全部离线：临时 SQLite + 确定性 offline provider（conftest 的 ``rag_index``），
不建产品库、不调模型/embedding/rerank、不开端口、不发请求。
"""

from __future__ import annotations

from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState

#: C22 冻结问句：两家门店同现，但只有甲店是被问目标。
QUESTION = "甲店的宣传海报放在哪？乙店有一条尚未生效的登记，现在能作为取用依据吗？"
#: 目标门店的值：必须命中。
EXPECTED_VALUES = ("甲区一层",)
#: 异店那一行的值：不得渲染。
OTHER_STORE_VALUES = ("乙区二层",)
#: 异店状态说明允许出现的内容（名称 + 状态；日期允许，位置不允许）。
OTHER_STORE_NAME = "乙店"
OTHER_STORE_STATUS = "尚未生效"

ROWS = [
    {"标识": "P01", "门店": "甲店", "物品": "宣传海报", "位置": "甲区一层"},
    {
        "标识": "P02",
        "门店": "乙店",
        "物品": "宣传海报",
        "位置": "乙区二层",
        "生效日期": "2026-12-01",
    },
    # 相邻反例用：两店各一行**当前有效**的易拉宝记录（显式“都列出来”仍要两家）。
    {"标识": "P03", "门店": "甲店", "物品": "易拉宝", "位置": "甲区三层"},
    {"标识": "P04", "门店": "乙店", "物品": "易拉宝", "位置": "乙区四层"},
]

LEXICON = Lexicon(stores=("甲店", "乙店"), items=("宣传海报", "易拉宝"))


def _plan(question: str, previous: QueryState | None = None):
    return parse_query(
        question, previous=previous, lexicon=LEXICON, business_date="2026-10-28"
    )


def _seed(add_records, make_doc) -> None:
    add_records(ROWS, doc=make_doc(doc_id="D-r1106b", title="终端物料位置表"))


def _ask(rag_index, question: str, conversation_id: str):
    return rag_index.ask(question, user_id="u", conversation_id=conversation_id)


# --------------------------------------------------------------------- 规划层


def test_planner_targets_the_asked_store_only() -> None:
    """红：改前 reason=MULTI_TARGET_ENUMERATE、store=乙店、field_role=effective_from。"""
    plan = _plan(QUESTION)

    assert plan.reason == "PRIMARY_STORE_TARGET", (plan.reason, dict(plan.filters))
    assert plan.clarification is None
    # 被问目标是先问的那家店，不是排序靠后的异店。
    assert plan.state.store == "甲店", plan.state.store
    # 问的是位置；“乙店…尚未生效”里的“生效”不是本轮的字段请求。
    assert plan.field_role == "location", (plan.field_role, plan.field_roles)
    assert plan.field_roles == ("location",), plan.field_roles
    # 产品层仍要把本轮交给 rag 内核（由 ``enumerate`` 这个既有入口识别）。
    assert plan.enumerate is True
    assert _rag_owns_turn(QueryState(), plan) is True
    # 异店仍被登记为本轮被提到的门店（状态说明需要），但不作为取值目标。
    assert set(plan.state.stores) == {"甲店", "乙店"}
    assert "store" not in plan.filters, dict(plan.filters)


def test_two_stores_asked_the_same_field_is_not_narrowed() -> None:
    """反例：两家各问同一字段 = 两条并列请求，不能只收窄成一家。"""
    plan = _plan("甲店的宣传海报放在哪？乙店的宣传海报放在哪？")

    assert plan.reason != "PRIMARY_STORE_TARGET", plan.reason
    assert plan.reason == "MULTI_TARGET_ENUMERATE", plan.reason


def test_explicit_list_both_stores_is_not_narrowed() -> None:
    """反例：显式“都列出来”仍是两家枚举（不得因主目标判定误收窄）。"""
    plan = _plan("甲店和乙店的宣传海报位置都列出来。")

    assert plan.reason == "MULTI_TARGET_ENUMERATE", (plan.reason, dict(plan.filters))
    assert set(plan.state.stores) == {"甲店", "乙店"}, plan.state.stores
    assert "store" not in plan.filters, dict(plan.filters)


def test_single_store_question_is_unchanged() -> None:
    """反例：单店问法保持既有规划（门店 + 物品硬过滤，无新 reason）。"""
    plan = _plan("甲店的宣传海报放在哪？")

    assert plan.reason is None, plan.reason
    assert dict(plan.filters) == {"store": "甲店", "item": "宣传海报"}, dict(plan.filters)
    assert plan.state.store == "甲店" and plan.state.stores == ("甲店",)
    assert plan.field_role == "location"


# ----------------------------------------------------------------- 内核端到端


def test_primary_store_answer_uses_target_values_only(rag_index, add_records, make_doc) -> None:
    """红：改前答案渲染乙店行（乙区二层）并把甲店写成“未在资料中找到”。"""
    _seed(add_records, make_doc)

    answer = _ask(rag_index, QUESTION, "c-106b-main")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    for value in EXPECTED_VALUES:
        assert value in answer.text, answer.text
    for value in OTHER_STORE_VALUES:
        assert value not in answer.text, (value, answer.text)
    # 目标门店有记录，不得反过来说它“没有匹配记录”。
    assert "未在资料中找到" not in answer.text, answer.text
    # 引用只含目标门店那一行（异店行不作为依据）。
    assert answer.citations, answer.text
    assert all("甲店" in citation.text for citation in answer.citations), [
        citation.text for citation in answer.citations
    ]
    assert all(OTHER_STORE_NAME not in citation.text for citation in answer.citations), [
        citation.text for citation in answer.citations
    ]
    # 事实值只来自目标门店。
    assert {fact.value for fact in answer.facts} == set(EXPECTED_VALUES), [
        (fact.field_role, fact.value) for fact in answer.facts
    ]
    # 本轮“检索证据”同样只含目标门店那一条：评测按 diagnostics.evidence_ids 判其它实体。
    assert answer.diagnostics["returned"] == 1, answer.diagnostics["returned"]
    evidence_ids = list(answer.diagnostics.get("evidence_ids") or ())
    assert len(evidence_ids) == 1, evidence_ids
    assert {citation.source_id for citation in answer.citations} == set(evidence_ids), (
        [citation.source_id for citation in answer.citations],
        evidence_ids,
    )
    # 持久状态里的目标门店同样只有甲店，供后续追问继续收敛。
    assert answer.state["store"] == "甲店", answer.state.get("store")
    assert list(answer.state.get("stores") or ()) == ["甲店"], answer.state.get("stores")


def test_other_store_is_explained_as_status_only(rag_index, add_records, make_doc) -> None:
    """异店只作名称 + 状态说明：不渲染其行值、不作为引用。"""
    _seed(add_records, make_doc)

    answer = _ask(rag_index, QUESTION, "c-106b-status")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert OTHER_STORE_NAME in answer.text, answer.text
    assert OTHER_STORE_STATUS in answer.text, answer.text
    for value in OTHER_STORE_VALUES:
        assert value not in answer.text, (value, answer.text)
    assert all(OTHER_STORE_NAME not in citation.text for citation in answer.citations), [
        citation.text for citation in answer.citations
    ]


def test_explicit_list_both_stores_still_answers_both(rag_index, add_records, make_doc) -> None:
    """相邻反例：显式“都列出来”仍逐条作答两家（两行都是当前有效记录）。"""
    _seed(add_records, make_doc)

    answer = _ask(rag_index, "甲店和乙店的易拉宝位置都列出来。", "c-106b-both")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "甲区三层" in answer.text and "乙区四层" in answer.text, answer.text
    assert answer.diagnostics["returned"] == 2, answer.diagnostics["returned"]


def test_single_store_question_still_answers(rag_index, add_records, make_doc) -> None:
    """单店问法端到端不变。"""
    _seed(add_records, make_doc)

    answer = _ask(rag_index, "甲店的宣传海报放在哪？", "c-106b-single")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "甲区一层" in answer.text, answer.text
    assert "乙区二层" not in answer.text, answer.text
    assert answer.citations and all("甲店" in item.text for item in answer.citations)
