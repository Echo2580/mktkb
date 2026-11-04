"""查询补全、澄清恢复、跨用户隔离、话题切换与“全部”分页。"""

from __future__ import annotations

from mktkb.rag import DocumentSpec, QueryState


def test_clarification_then_follow_up_keeps_conditions(rag_index, add_records):
    add_records(
        [
            {"标识": "S01", "门店": "滨江店", "联系人": "陈宁", "电话": "010-00000001"},
            {"标识": "S02", "门店": "鹿鸣路店", "联系人": "王平", "电话": "010-00000002"},
        ],
        doc=DocumentSpec(
            doc_id="D02",
            source_path="d02.xlsx",
            title="合作店家信息",
            file_kind="xlsx",
            version_id="D02-v1",
            version_label="当前",
            sha256="c" * 64,
        ),
    )
    first = rag_index.ask("联系人是谁？", user_id="u1", conversation_id="c1")
    assert first.kind == "clarification"
    assert first.state["pending_slot"] == "store"
    assert "滨江店" in first.text

    second = rag_index.ask("滨江店", user_id="u1", conversation_id="c1")
    assert second.kind == "answer"
    assert "陈宁" in second.text
    assert second.state["store"] == "滨江店"
    assert second.state["pending_slot"] is None
    assert second.state["field_role"] == "contact"


def test_cross_user_state_isolation(rag_index, add_records):
    add_records(
        [{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧", "数量": 40}],
    )
    rag_index.ask("滨江店的宣传海报位置", user_id="alice", conversation_id="same")
    alice_state = rag_index.load_state("alice", "same")
    bob_state = rag_index.load_state("bob", "same")
    assert alice_state.store == "滨江店"
    assert bob_state.store is None

    bob_answer = rag_index.ask("那数量呢？", user_id="bob", conversation_id="same")
    assert bob_answer.kind in ("clarification", "no_answer")
    assert bob_answer.state["store"] is None


def test_topic_switch_clears_stale_entities(rag_index, add_records):
    add_records(
        [{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧", "数量": 40}],
    )
    add_records(
        [
            {
                "价格单号": "PX-1",
                "品名规格": "启沣乌龙茶（900ml PET） 900ml×12瓶/箱",
                "适用渠道": "NKA卖场",
                "价格类型": "组合价",
                "价格(元)": 5,
                "计价单位": "2瓶",
                "生效日期": "2026-10-01",
                "失效日期": "2026-11-15",
            }
        ],
        doc=DocumentSpec(
            doc_id="E03",
            source_path="e03.xlsx",
            title="渠道价目表",
            file_kind="xlsx",
            version_id="E03-v1",
            version_label="当前",
            sha256="d" * 64,
        ),
    )
    first = rag_index.ask("滨江店的宣传海报位置", user_id="u", conversation_id="c")
    assert first.kind == "answer"
    second = rag_index.ask("启沣乌龙茶 900ml 在 NKA卖场的组合价是多少？", user_id="u", conversation_id="c")
    assert second.kind == "answer"
    assert second.state["store"] is None
    assert second.state["item"] is None
    assert second.state["product"] == "启沣乌龙茶（900ml PET） 900ml×12瓶/箱"
    assert second.state["channel"] == "NKA卖场"
    assert second.state["price_type"] == "组合价"


def test_enumeration_larger_than_top_k_reports_total_and_more(rag_index, add_records):
    rows = [
        {"标识": f"I{index:03d}", "门店": "滨江店", "物品": f"测试物品{index:03d}", "位置": f"位置{index:03d}"}
        for index in range(25)
    ]
    add_records(rows)
    first = rag_index.ask("把滨江店的所有物品位置列出来", user_id="u", conversation_id="c")
    assert first.kind == "answer"
    assert first.diagnostics["total"] == 25
    assert first.diagnostics["returned"] == 10
    assert first.diagnostics["has_more"] is True
    assert "共 25 条" in first.text
    assert "还有更多" in first.text

    second = rag_index.ask("下一页", user_id="u", conversation_id="c")
    assert second.kind == "answer"
    assert second.diagnostics["page"] == 2
    assert second.diagnostics["returned"] == 10
    assert second.diagnostics["has_more"] is True

    third = rag_index.ask("下一页", user_id="u", conversation_id="c")
    assert third.kind == "answer"
    assert third.diagnostics["page"] == 3
    assert third.diagnostics["returned"] == 5
    assert third.diagnostics["has_more"] is False
    assert "已到最后一页" in third.text and "已显示全部" not in third.text


def test_state_roundtrip_keeps_candidates_and_pagination() -> None:
    state = QueryState(
        user_id="u",
        conversation_id="c",
        store="滨江店",
        item="宣传海报",
        field_role="location",
        enumerate=True,
        page=2,
        page_size=10,
        pending_slot="store",
        candidates=("滨江店", "鹿鸣路店"),
    )
    restored = QueryState.from_dict(state.to_dict())
    assert restored.store == "滨江店"
    assert restored.enumerate is True
    assert restored.page == 2
    assert restored.candidates == ("滨江店", "鹿鸣路店")
    assert restored.pending_slot == "store"
