"""v3-fix-2/B：首轮“显式门店 + 物品”的有据请求不再被判“未记录该字段”（not_found）。

复现面（合成、离线）：首轮（``state.turn == 1``），题面显式点名词表内门店与物品，字段
措辞不在字段词表里，且句中出现一个回指词（“那个”）。
改前：``parse_query`` 把它当“带新内容的指代追问”→ ``reason=ANAPHORA_NEW_CONTENT``、
``enumerate=True`` → 答案层在**任何检索之前**返回 ``no_answer``（产品结局 ``not_found``）。
这与 v3 首轮封存证据里 C02/C05 的 ``direct_rag_answer`` 逐字段相同
（``kind=no_answer`` / ``reason=ANAPHORA_NEW_CONTENT`` / ``fact_count=0`` /
``cited_unit_ids=[]``，而 ``plan.filters`` 同时含门店与物品）。

改后：首轮没有可回指的先行语，按“显式实体的记录枚举”作答（真实引用 + 事实准入）；
追问仍走原有 ``ANAPHORA_NEW_CONTENT`` 收口（T105 R1/B2 口径不变）。

反例（真无覆盖仍 not_found）：门店与物品都在词表里、但该门店没有该物品记录 → 仍
``not_found``，零引用、不编造取值。纯指代首轮仍澄清。

全部离线：临时 SQLite + 确定性 offline provider；不建产品库、不调模型/embedding/rerank、
不开端口、不发请求。
"""

from __future__ import annotations

import pytest

from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState

LEXICON = Lexicon(
    stores=("城东店", "城西店"),
    items=("宣传海报", "展架", "价签卡纸"),
    field_labels=("位置",),
)

RECORDS = [
    {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "位置": "A区1号货架"},
    {"标识": "P03", "门店": "城东店", "物品": "展架", "位置": "C区门口"},
    {"标识": "P05", "门店": "城东店", "物品": "价签卡纸", "位置": "E区3号端架"},
    {"标识": "P04", "门店": "城西店", "物品": "展架", "位置": "D区立柱"},
    {"标识": "P02", "门店": "城西店", "物品": "宣传海报", "位置": "B区2号货架"},
]


def _plan(question: str, previous: QueryState | None = None):
    return parse_query(question, previous=previous, lexicon=LEXICON, business_date="2026-10-15")


def _seed(add_records, make_doc) -> None:
    add_records(RECORDS, doc=make_doc(title="D01_物品位置表.xlsx"))


# --------------------------------------------------------------- B 正例（规划层）


@pytest.mark.parametrize(
    "question",
    [
        "城东店的展架那个陈列规矩是怎么定的",
        "城东店的宣传海报那个上架节奏如何安排",
    ],
)
def test_first_turn_explicit_entity_is_not_collapsed_to_not_recorded(question: str):
    plan = _plan(question)
    assert plan.reason != "ANAPHORA_NEW_CONTENT", plan.reason
    assert plan.clarification is None
    assert plan.mode == "record"
    assert plan.enumerate is True
    assert plan.filters.get("store") == "城东店"
    assert _rag_owns_turn(QueryState(), plan) is True


# --------------------------------------------------------------- B 正例（内核 e2e）


def test_first_turn_explicit_entity_answers_from_record(rag_index, add_records, make_doc):
    _seed(add_records, make_doc)
    answer = rag_index.ask(
        "城东店的展架那个陈列规矩是怎么定的", user_id="u", conversation_id="c-fix2-b1"
    )
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert answer.reason is None
    assert len(answer.citations) >= 1
    assert "C区门口" in answer.text
    # 不得把别的门店的记录带进来。
    assert "D区立柱" not in answer.text


# --------------------------------------------------------------- B 反例（真无覆盖）


def test_known_store_without_record_still_not_found(rag_index, add_records, make_doc):
    """门店与物品都在词表里，但城西店没有“价签卡纸”记录 → 仍判找不到，且不编造取值。"""
    _seed(add_records, make_doc)
    answer = rag_index.ask(
        "城西店的价签卡纸那个陈列规矩是怎么定的", user_id="u", conversation_id="c-fix2-b2"
    )
    assert answer.kind == "no_answer", (answer.kind, answer.reason, answer.text)
    assert answer.reason in ("NO_RECORD_FOR_ENTITY", "NO_EVIDENCE")
    assert answer.citations == []
    for value in ("A区1号货架", "B区2号货架", "C区门口", "D区立柱", "E区3号端架"):
        assert value not in answer.text


# ------------------------------------------------------- B 反例（追问口径不回退）


def test_followup_new_content_still_collapses_to_not_recorded(rag_index, add_records, make_doc):
    """T105 R1/B2 口径不回退：有上文的“带新内容”追问仍按“不属于台账字段”收口。"""
    _seed(add_records, make_doc)
    first = rag_index.ask("城东店的展架在哪里？", user_id="u", conversation_id="c-fix2-b3")
    assert first.kind == "answer", (first.kind, first.reason, first.text)

    followup = rag_index.ask(
        "城东店的展架那个打印材质呢", user_id="u", conversation_id="c-fix2-b3"
    )
    assert followup.kind == "no_answer", (followup.kind, followup.reason, followup.text)
    assert followup.reason == "ANAPHORA_NEW_CONTENT"
    assert followup.citations == []
    for value in ("A区1号货架", "C区门口", "E区3号端架"):
        assert value not in followup.text


def test_first_turn_bare_anaphora_still_clarifies(rag_index, add_records, make_doc):
    """首轮纯指代（没有点名目标）仍澄清，不因本轮修复被放行。"""
    _seed(add_records, make_doc)
    plan = _plan("这两个分别放在哪里")
    assert plan.clarification is not None
    assert _rag_owns_turn(QueryState(), plan) is False

    answer = rag_index.ask("这两个分别放在哪里", user_id="u", conversation_id="c-fix2-b4")
    assert answer.kind == "clarification", (answer.kind, answer.reason, answer.text)
