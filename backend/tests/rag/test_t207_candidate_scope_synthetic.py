from types import SimpleNamespace

from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.retrieval import _passes_filters
from mktkb.rag.types import QueryState


def test_multi_store_hard_filter_rejects_unrequested_store():
    lexicon = Lexicon(stores=("北园店", "南园店", "西园店"), items=("展板",), field_labels=("位置",))
    plan = parse_query("北园店和南园店的展板在哪里？", previous=None, lexicon=lexicon)
    chunk = SimpleNamespace(doc_id="d", filters_norm={"store": "西园店", "item": "展板"},
                            effective_from=None, effective_to=None)
    assert not _passes_filters(chunk, plan)


def test_multi_item_hard_filter_rejects_unrequested_item():
    lexicon = Lexicon(stores=("北园店",), items=("展板", "横幅", "灯箱"), field_labels=("位置",))
    plan = parse_query("北园店的展板和横幅在哪里？", previous=None, lexicon=lexicon)
    chunk = SimpleNamespace(doc_id="d", filters_norm={"store": "北园店", "item": "灯箱"},
                            effective_from=None, effective_to=None)
    assert not _passes_filters(chunk, plan)


def test_multi_item_no_match_never_answers_another_item(rag_index, add_records, make_doc):
    add_records([
        {"门店": "北园店", "物品": "灯箱", "位置": "甲柜"},
        {"门店": "南园店", "物品": "展板", "位置": "乙柜"},
        {"门店": "南园店", "物品": "横幅", "位置": "丙柜"},
    ], doc=make_doc(title="设备位置表"))
    answer = rag_index.ask("北园店的展板和横幅在哪里？", user_id="u", conversation_id="c")
    assert answer.kind == "no_answer"
    assert not answer.citations
    assert all(value not in answer.text for value in ("甲柜", "乙柜", "丙柜"))


def test_previous_single_item_does_not_narrow_new_multiple_items():
    lexicon = Lexicon(stores=("北园店",), items=("展板", "横幅"), field_labels=("位置",))
    previous = QueryState(store="北园店", stores=("北园店",), item="展板", items=("展板",), turn=1)
    plan = parse_query("北园店的展板和横幅在哪里？", previous=previous, lexicon=lexicon)
    assert set(plan.state.items) == {"展板", "横幅"}
    assert "item" not in plan.filters


def test_vector_candidates_respect_multiple_items(rag_index, add_records, make_doc):
    add_records([
        {"门店": "北园店", "物品": "展板", "位置": "甲柜"},
        {"门店": "北园店", "物品": "横幅", "位置": "乙柜"},
        {"门店": "北园店", "物品": "灯箱", "位置": "丙柜"},
    ], doc=make_doc(title="设备位置表"))
    lexicon = Lexicon(stores=("北园店",), items=("展板", "横幅", "灯箱"), field_labels=("位置",))
    plan = parse_query("北园店的展板和横幅在哪里？", previous=None, lexicon=lexicon)
    result = rag_index.search(plan)
    assert result.vector
    assert {chunk.filters_norm["item"] for chunk in result.vector} <= {"展板", "横幅"}
