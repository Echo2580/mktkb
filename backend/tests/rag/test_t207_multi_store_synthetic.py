from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState


def test_explicit_multiple_stores_clear_previous_single_record_id():
    lexicon = Lexicon(stores=("北园店", "南园店"), items=("展板",), identifiers=("P77",))
    previous = QueryState(store="北园店", stores=("北园店",), item="展板", identifier="P77", turn=1)
    plan = parse_query("北园店和南园店的展板放在哪里？", previous=previous, lexicon=lexicon)
    assert set(plan.state.stores) == {"北园店", "南园店"}
    assert plan.state.identifier is None
    assert "identifier" not in plan.filters


def test_explicit_record_id_is_preserved():
    lexicon = Lexicon(stores=("北园店",), items=("展板",), identifiers=("P77",))
    plan = parse_query("北园店的P77展板放在哪里？", previous=None, lexicon=lexicon)
    assert plan.state.identifier == "P77"


def test_two_stores_then_single_store_never_returns_other_store(rag_index, add_records, make_doc):
    add_records([
        {"门店": "北园店", "物品": "展板", "位置": "甲柜"},
        {"门店": "南园店", "物品": "展板", "位置": "乙柜"},
        {"门店": "西园店", "物品": "展板", "位置": "丙柜"},
    ], doc=make_doc(title="设备位置表"))
    first = rag_index.ask("北园店和南园店的展板分别在哪里？", user_id="u", conversation_id="c")
    assert first.kind == "answer"
    assert "甲柜" in first.text and "乙柜" in first.text and "丙柜" not in first.text
    second = rag_index.ask("西园店的展板在哪里？", user_id="u", conversation_id="c")
    assert second.kind == "answer"
    assert "丙柜" in second.text and "甲柜" not in second.text and "乙柜" not in second.text
