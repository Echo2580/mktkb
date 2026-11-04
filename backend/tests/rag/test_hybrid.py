"""混合召回：>100 候选先打分、硬过滤优先、同义查询走向量、引用可追溯。"""

from __future__ import annotations

from mktkb.rag import QueryPlan, QueryState
from mktkb.rag.query import build_lexicon, parse_query


def test_more_than_100_candidates_scored_before_truncation(rag_index, add_records):
    rows = [
        {"标识": f"I{index:03d}", "门店": "滨江店", "物品": f"物品{index:03d}", "位置": f"位置{index:03d}"}
        for index in range(150)
    ]
    add_records(rows)
    lexicon = build_lexicon(rag_index.lexicon_data())
    plan = parse_query(
        "滨江店的物品位置",
        previous=QueryState(user_id="u", conversation_id="c"),
        lexicon=lexicon,
        business_date="2026-10-28",
    )
    result = rag_index.search(plan)
    assert result.recall_counts["exact"] == 150
    assert result.diagnostics["vector_scored"] == 150
    assert len(result.evidence) == 5
    assert result.total == 150


def test_hard_filter_not_overridden_by_vector(rag_index, add_records):
    add_records(
        [
            {"标识": "B01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧"},
            {"标识": "L01", "门店": "鹿鸣路店", "物品": "宣传海报", "位置": "入口堆头旁"},
        ]
    )
    answer = rag_index.ask("滨江店的宣传海报位置", user_id="u", conversation_id="c")
    assert answer.kind == "answer"
    assert "店内外侧" in answer.text
    assert "入口堆头旁" not in answer.text
    assert all("滨江店" in fact.entity_label for fact in answer.facts)


def test_semantic_synonym_query_reaches_text_evidence(rag_index, add_records):
    add_records(
        [],
        text_units=[
            {
                "text": "宣传海报应放在入口堆头旁，并由门店负责人确认。",
                "locator": {"paragraph": 1, "page": 1},
            }
        ],
    )
    plan = QueryPlan(
        question="海报搁哪儿",
        mode="document",
        query_text="海报搁哪儿",
        field_role=None,
        field_label=None,
        filters={},
        terms=("海报", "搁哪儿"),
        state=QueryState(user_id="u", conversation_id="c"),
        page=1,
        page_size=10,
    )
    result = rag_index.search(plan)
    assert result.vector
    assert any("入口堆头旁" in item.text for item in result.evidence)


def test_evidence_citations_have_source_and_revision(rag_index, add_records):
    add_records([{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧"}])
    answer = rag_index.ask("滨江店的宣传海报位置", user_id="u", conversation_id="c")
    assert answer.citations
    citation = answer.citations[0]
    assert citation.source_path
    assert citation.version_id
    assert citation.revision == rag_index.revision()
    assert citation.locator["row"] == 7
