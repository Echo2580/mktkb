"""T105/ERR-06：指代追问的字段继承与“无字段澄清”单元用例。

不建产品、不调模型：用隔离 rag 索引验证多轮状态——继承了实体就必须判断“问什么”：
- 上文问过某个记录字段 → 只答该字段，不倾倒整条记录；
- 没有可继承字段 → 澄清要哪项信息；
- 指代无源 → 澄清对象；
- 用户显式要求“列出来”仍按枚举渲染（不被指代分支吞掉）。
"""

from __future__ import annotations

from mktkb.rag import DocumentSpec

ROWS = [
    {
        "标识": "QF02",
        "门店": "城西店",
        "物品": "宣传海报",
        "别名": "海报",
        "位置": "C区2号货架第一层",
        "数量": 20,
        "参考供价": 2.6,
        "规格型号": "A2 铜版纸 157g",
    },
    {
        "标识": "QF01",
        "门店": "滨江店",
        "物品": "宣传海报",
        "别名": "海报",
        "位置": "店内外侧",
        "数量": 40,
        "参考供价": 2.6,
        "规格型号": "A2 铜版纸 157g",
    },
]

UNASKED_VALUES = ("店内外侧", "C区2号货架第一层", "A2 铜版纸 157g", "2.6", "40")


def _seed(rag_index, add_records) -> None:
    add_records(
        ROWS,
        doc=DocumentSpec(
            doc_id="E11",
            source_path="e11.xlsx",
            title="终端物料位置表",
            file_kind="xlsx",
            version_id="E11-v1",
            version_label="当前",
            sha256="e" * 64,
            business_date="2026-10-28",
        ),
    )


def _ask(rag_index, conversation: str, question: str):
    return rag_index.ask(question, user_id="u", conversation_id=conversation)


def test_location_followup_answers_location_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-loc", "城西店的宣传海报在哪里？")
    assert first.kind == "answer", first.text
    assert "C区2号货架第一层" in first.text

    followup = _ask(rag_index, "c-loc", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "C区2号货架第一层" in followup.text
    assert "A2 铜版纸 157g" not in followup.text
    assert "2.6" not in followup.text
    assert "20" not in followup.text
    assert followup.state["field_role"] == "location"
    # “只答该字段”不是枚举页：状态里不得残留枚举标记。
    assert followup.state["enumerate"] is False


def test_quantity_followup_answers_quantity_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-qty", "城西店的宣传海报的数量是多少？")
    assert "20" in first.text

    followup = _ask(rag_index, "c-qty", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "20" in followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "A2 铜版纸 157g" not in followup.text
    assert "2.6" not in followup.text
    assert followup.state["field_role"] == "quantity"


def test_price_followup_answers_price_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-price", "城西店的宣传海报的参考供价是多少？")
    assert "2.6" in first.text

    followup = _ask(rag_index, "c-price", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "2.6" in followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "A2 铜版纸 157g" not in followup.text
    assert "20" not in followup.text
    assert followup.state["field_role"] == "price"


def test_spec_followup_answers_spec_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-spec", "城西店的宣传海报的规格型号是什么？")
    assert "A2 铜版纸 157g" in first.text

    followup = _ask(rag_index, "c-spec", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "A2 铜版纸 157g" in followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "2.6" not in followup.text
    assert "20" not in followup.text
    assert followup.state["field_role"] == "spec"


def test_anaphora_without_context_asks_which_field(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    answer = _ask(rag_index, "c-fresh", "那个海报呢")

    assert answer.kind == "clarification", answer.text
    assert answer.reason == "ANAPHORA_NO_FIELD"
    assert "哪项信息" in answer.text
    for value in UNASKED_VALUES:
        assert value not in answer.text, (value, answer.text)
    assert answer.state["item"] == "宣传海报"


def test_anaphora_without_entity_clarifies_referent(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    answer = _ask(rag_index, "c-bare", "那个呢")

    assert answer.kind == "clarification", answer.text
    assert answer.reason == "ANAPHORA_NO_ENTITY"
    assert "哪个物品" in answer.text


def test_anaphora_without_unique_entity_does_not_dump_fields(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-multi", "宣传海报在哪里？")
    assert first.kind == "ambiguous", first.text

    followup = _ask(rag_index, "c-multi", "那个海报呢")
    assert followup.kind == "ambiguous", followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "A2 铜版纸 157g" not in followup.text


def test_anaphora_after_multi_field_question_asks_which_field(rag_index, add_records) -> None:
    """上文问了两个字段时没有唯一的“问什么”可继承：应澄清，不得整条渲染。"""
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-many", "城西店的宣传海报的位置和数量是什么？")
    assert first.kind == "answer", first.text
    assert "C区2号货架第一层" in first.text
    assert "20" in first.text

    followup = _ask(rag_index, "c-many", "那个海报呢")
    assert followup.kind == "clarification", followup.text
    assert followup.reason == "ANAPHORA_NO_FIELD"
    assert "哪项信息" in followup.text
    for value in UNASKED_VALUES:
        assert value not in followup.text, (value, followup.text)


def test_explicit_enumeration_is_not_treated_as_field_followup(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    _ask(rag_index, "c-list", "城西店的宣传海报在哪里？")

    listed = _ask(rag_index, "c-list", "把那个海报的位置列出来")
    assert listed.kind == "answer", listed.text
    assert "共 " in listed.text
    assert listed.state["enumerate"] is True
