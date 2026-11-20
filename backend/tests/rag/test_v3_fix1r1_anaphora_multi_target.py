"""v3-fix-1/R1：纯指代（“这两个/这几个”）不得被当成本轮显式多目标放行。

回归面（独立验收 N2/N2b）：``城东店和城西店的这两个分别放在哪里？`` 在 fix-1/A 之后被
``MULTI_TARGET_ENUMERATE`` 放行、由内核按“两店全部物品”作答；改前 legacy 是澄清。
本文件锁定：

- 纯指代 + 已点名门店 → 仍澄清（planner ``MULTIPLE_ENTITIES``，不归内核）；
- 纯指代 + 未点名 → 仍澄清（既有 ``MISSING_SLOT``）；
- 混合（显式目标 + 指代）→ 不冒充多目标（物品维回到 ``ITEM_AMBIGUOUS``）；
- 跨轮指代 → 不重新枚举整表（只延续上一轮已点名的目标）；
- 指代 + 词表外门店 → 澄清（不静默只答已知门店）；
- 复指限定语（“海报和易拉宝这两个物品”）→ 仍按显式多目标作答（不过度拦截）；
- fix-1/A 正例（两店一物品 / 一店两物品 / 两店电话）保持 ``MULTI_TARGET_ENUMERATE``。

全部为离线合成：临时 SQLite + 确定性 offline provider；不建产品库、不调模型/embedding/
rerank、不开端口、不发请求。
"""

from __future__ import annotations

import pytest

from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, _bare_quantified_anaphora, parse_query
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


def _seed(add_records, make_doc) -> None:
    doc = make_doc(title="物品位置表")
    add_records(
        [
            {"门店": "城东店", "物品": "宣传海报", "位置": "A区1号货架", "电话": "010-00000001"},
            {"门店": "城西店", "物品": "宣传海报", "位置": "B区2号货架", "电话": "010-00000002"},
            {"门店": "城东店", "物品": "易拉宝", "位置": "C区门口", "电话": "010-00000001"},
            {"门店": "城西店", "物品": "易拉宝", "位置": "D区立柱", "电话": "010-00000002"},
        ],
        doc=doc,
    )


# ------------------------------------------------------------- 纯指代（回归面）


@pytest.mark.parametrize(
    "question",
    [
        "城东店和城西店的这两个分别放在哪里？",
        "城东店和城西店的这几个分别放在哪里？",
    ],
)
def test_pure_anaphora_with_named_stores_clarifies(question: str):
    plan = _plan(question)
    assert plan.reason != "MULTI_TARGET_ENUMERATE"
    assert plan.reason == "MULTIPLE_ENTITIES"
    assert plan.clarification is not None
    # 产品层不得把该轮交给 rag 内核（否则会按整表/多目标作答）。
    assert _rag_owns_turn(QueryState(), plan) is False


def test_pure_anaphora_with_named_stores_clarifies_in_kernel(rag_index, add_records, make_doc):
    _seed(add_records, make_doc)
    answer = rag_index.ask(
        "城东店和城西店的这两个分别放在哪里？", user_id="u", conversation_id="c-r1-anaphora"
    )
    assert answer.kind == "clarification", (answer.kind, answer.reason, answer.text)
    # 不得以两店全部物品作答（改前回归是 4 行整表）。
    assert "A区1号货架" not in answer.text
    assert "C区门口" not in answer.text


def test_bare_anaphora_without_targets_still_clarifies(rag_index, add_records, make_doc):
    _seed(add_records, make_doc)
    plan = _plan("这两个分别放在哪里？")
    assert plan.reason != "MULTI_TARGET_ENUMERATE"
    assert plan.clarification is not None
    assert _rag_owns_turn(QueryState(), plan) is False

    answer = rag_index.ask("这两个分别放在哪里？", user_id="u", conversation_id="c-r1-bare")
    assert answer.kind == "clarification"


def test_existing_anaphor_word_they_still_not_multi_target():
    """“它们”在 fix-1/A 之前就不进多目标；本包不改它的既有澄清口径。"""
    plan = _plan("城东店和城西店的它们分别放在哪里？")
    assert plan.reason != "MULTI_TARGET_ENUMERATE"
    assert _rag_owns_turn(QueryState(), plan) is False


# ----------------------------------------------------------------- 混合（显式 + 指代）


def test_mixed_explicit_items_plus_anaphora_clarifies(rag_index, add_records, make_doc):
    """两个显式物品 + “这两个”：不能把这一轮当显式多目标（改前会按 2 行作答）。"""
    _seed(add_records, make_doc)
    plan = _plan("城东店的宣传海报、易拉宝和这两个分别放在哪里？")
    assert plan.reason == "ITEM_AMBIGUOUS"
    assert plan.clarification is not None
    assert _rag_owns_turn(QueryState(), plan) is False

    answer = rag_index.ask(
        "城东店的宣传海报、易拉宝和这两个分别放在哪里？",
        user_id="u",
        conversation_id="c-r1-mixed-items",
    )
    assert answer.kind == "clarification", (answer.kind, answer.reason, answer.text)


def test_mixed_explicit_item_plus_anaphora_does_not_expand(rag_index, add_records, make_doc):
    """一个显式物品 + “这两个”：不冒充多目标，也不把指代扩成整表（只答显式物品）。"""
    _seed(add_records, make_doc)
    plan = _plan("城东店和城西店的宣传海报和这两个分别放在哪里？")
    assert plan.reason != "MULTI_TARGET_ENUMERATE"

    answer = rag_index.ask(
        "城东店和城西店的宣传海报和这两个分别放在哪里？",
        user_id="u",
        conversation_id="c-r1-mixed-store",
    )
    assert answer.diagnostics["returned"] == 2
    assert "A区1号货架" in answer.text and "B区2号货架" in answer.text
    # 指代没有被扩展成“两店全部物品”。
    assert "C区门口" not in answer.text and "D区立柱" not in answer.text


# --------------------------------------------------------------------- 跨轮指代


def test_cross_turn_anaphora_does_not_reenumerate_table(rag_index, add_records, make_doc):
    _seed(add_records, make_doc)
    first = rag_index.ask(
        "城东店和城西店的宣传海报在哪里？", user_id="u", conversation_id="c-r1-cross"
    )
    assert first.kind == "answer", (first.kind, first.reason, first.text)
    assert first.diagnostics["returned"] == 2

    plan = _plan(
        "这两个分别放在哪里？",
        previous=QueryState.from_dict(first.state),
    )
    assert plan.reason != "MULTI_TARGET_ENUMERATE"

    second = rag_index.ask(
        "这两个分别放在哪里？", user_id="u", conversation_id="c-r1-cross"
    )
    assert second.kind == "answer", (second.kind, second.reason, second.text)
    # 延续上一轮已点名的“宣传海报”两个目标，不重开整表（不含易拉宝行）。
    assert second.diagnostics["returned"] == 2
    assert "C区门口" not in second.text and "D区立柱" not in second.text


# ------------------------------------------------------------- 词表外门店 + 指代


def test_anaphora_with_unknown_store_clarifies(rag_index, add_records, make_doc):
    _seed(add_records, make_doc)
    plan = _plan("城东店和城南店的这两个分别放在哪里？")
    assert plan.reason != "MULTI_TARGET_ENUMERATE"
    assert plan.clarification is not None
    assert _rag_owns_turn(QueryState(), plan) is False

    answer = rag_index.ask(
        "城东店和城南店的这两个分别放在哪里？",
        user_id="u",
        conversation_id="c-r1-unknown",
    )
    assert answer.kind == "clarification", (answer.kind, answer.reason, answer.text)
    assert "城南店" not in answer.text


# --------------------------------------------------- 复指限定语（不过度拦截）与 A 正例


@pytest.mark.parametrize(
    "question",
    [
        "城东店的宣传海报和易拉宝这两个物品分别放在哪里？",  # 前置枚举 + 后置名词
        "城东店的宣传海报、易拉宝这两个分别放在哪里？",  # 前置枚举（标点）
        "城东店和城西店这两家的电话是多少？",  # 前置枚举（“这两家”）
    ],
)
def test_resumptive_quantifier_is_not_treated_as_bare_anaphora(question: str):
    assert _bare_quantified_anaphora(question, LEXICON) is False
    plan = _plan(question)
    assert plan.reason == "MULTI_TARGET_ENUMERATE"
    assert _rag_owns_turn(QueryState(), plan) is True


def test_store_resumptive_phrase_is_not_bare_anaphora():
    """“这两个店”形态由既有未知门店守卫处理（本包不改），但也不能被记成纯指代。"""
    question = "城东店和城西店这两个店的电话是多少？"
    assert _bare_quantified_anaphora(question, LEXICON) is False
    plan = _plan(question)
    assert plan.reason != "MULTI_TARGET_ENUMERATE"


@pytest.mark.parametrize(
    "question",
    [
        "城东店和城西店的宣传海报在哪里？",  # 两店一物品
        "城东店的宣传海报和易拉宝在哪里？",  # 一店两物品
        "城东店和城西店的电话是多少？",  # 两店门店级字段
    ],
)
def test_fix1_positive_cases_stay_released(question: str):
    plan = _plan(question)
    assert plan.reason == "MULTI_TARGET_ENUMERATE"
    assert plan.clarification is None
    assert _rag_owns_turn(QueryState(), plan) is True
