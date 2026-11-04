"""精确值不同自然句式均通过；有效冲突显示双方来源；失效价格不冒充当前值。"""

from __future__ import annotations

from mktkb.rag import DocumentSpec


def _doc(code: str, title: str = "测试资料") -> DocumentSpec:
    return DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=f"{code}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=(code * 64)[:64],
    )


def test_multiple_natural_phrasings_return_same_exact_value(rag_index, add_records):
    add_records(
        [{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "别名": "海报", "位置": "店内外侧", "数量": 40}],
        doc=_doc("P1"),
    )
    questions = [
        "滨江店的宣传海报放在哪里？",
        "滨江店海报放哪？",
        "海报在滨江店的位置",
        "QF01 位置",
        "请问滨江店的宣传海报是放在哪里的？",
        "滨江店的宣传海报在哪",
    ]
    for index, question in enumerate(questions):
        answer = rag_index.ask(question, user_id="u", conversation_id=f"c{index}")
        assert answer.kind == "answer", (question, answer.text)
        assert "店内外侧" in answer.text
        assert answer.citations and answer.citations[0].locator["row"] == 7


def test_conflicting_active_sources_are_shown_not_upload_time_picked(rag_index, add_records):
    add_records(
        [{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧"}],
        doc=_doc("A"),
    )
    add_records(
        [{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "D区暂存柜"}],
        doc=_doc("B"),
    )
    answer = rag_index.ask("滨江店的宣传海报位置", user_id="u", conversation_id="c")
    assert answer.kind == "conflict"
    assert "店内外侧" in answer.text and "D区暂存柜" in answer.text
    assert len(answer.citations) >= 2
    assert answer.reason == "CONFLICTING_VALUES"


def test_expired_business_price_is_not_current_answer(rag_index, add_records):
    add_records(
        [
            {
                "价格单号": "PX-NEW",
                "品名规格": "启沣乌龙茶（900ml PET） 900ml×12瓶/箱",
                "适用渠道": "NKA卖场",
                "价格类型": "组合价",
                "价格(元)": 5,
                "计价单位": "2瓶",
                "生效日期": "2026-10-01",
                "失效日期": "2026-11-15",
            },
            {
                "价格单号": "PX-OLD",
                "品名规格": "启沣乌龙茶（900ml PET） 900ml×12瓶/箱",
                "适用渠道": "NKA卖场",
                "价格类型": "组合价",
                "价格(元)": 4.5,
                "计价单位": "2瓶",
                "生效日期": "2025-10-01",
                "失效日期": "2025-12-31",
            },
        ],
        doc=_doc("PRICE"),
    )
    answer = rag_index.ask(
        "启沣乌龙茶（900ml PET）在NKA卖场的组合价是多少？", user_id="u", conversation_id="c"
    )
    assert answer.kind == "answer"
    assert "5" in answer.text and "2瓶" in answer.text
    assert "4.5" not in answer.text
    assert answer.citations and answer.citations[0].locator["row"] == 7
