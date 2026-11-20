from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState
from mktkb.conversations.intent import EntityLexicon, parse_question


def test_cross_product_contact_request_refuses_before_ambiguity():
    lexicon = Lexicon(stores=("北园店", "南园店"), items=("展板", "横幅"), field_labels=("位置", "电话"))
    plan = parse_query("北园店和南园店的展板和横幅的位置及联系电话是多少？", previous=None, lexicon=lexicon)
    assert plan.reason == "SECURITY_RESTRICTED_CONTACT"
    assert plan.clarification is None
    assert _rag_owns_turn(QueryState(), plan)


def test_cross_product_without_contact_still_clarifies():
    lexicon = Lexicon(stores=("北园店", "南园店"), items=("展板", "横幅"), field_labels=("位置", "电话"))
    plan = parse_query("北园店和南园店的展板和横幅的位置分别在哪里？", previous=None, lexicon=lexicon)
    assert plan.reason == "ITEM_AMBIGUOUS"


def test_cross_product_contact_refusal_has_no_citations(rag_index, add_records, make_doc):
    add_records([
        {"门店": "北园店", "物品": "展板", "位置": "甲柜"},
        {"门店": "南园店", "物品": "横幅", "位置": "乙柜"},
    ], doc=make_doc(title="设备表"))
    answer = rag_index.ask("北园店和南园店的展板和横幅的位置及联系电话是多少？",
                           user_id="synthetic", conversation_id="synthetic")
    assert answer.kind == "no_answer"
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT"
    assert not answer.citations
    assert "甲柜" not in answer.text and "乙柜" not in answer.text


def test_legacy_unknown_store_cannot_bypass_existing_contact_policy():
    lexicon = EntityLexicon(store_labels=("北园店",), item_labels=("展板",), identifier_labels=())
    plan = parse_question("南园店展板的位置和联系电话是多少？", lexicon=lexicon)
    assert plan.security_refusal == "SECURITY_RESTRICTED_CONTACT"


def test_legacy_unrelated_unknown_store_remains_unknown():
    lexicon = EntityLexicon(store_labels=("北园店",), item_labels=("展板",), identifier_labels=())
    plan = parse_question("南园店展板在哪里？", lexicon=lexicon)
    assert plan.security_refusal is None
    assert plan.unknown_store


def test_legacy_financial_topic_does_not_hide_contact_request():
    lexicon = EntityLexicon(store_labels=("北园店",), item_labels=("展板",), identifier_labels=())
    plan = parse_question("北园店展板的位置和联系电话，以及公司的营业收入是多少？", lexicon=lexicon)
    assert plan.security_refusal == "SECURITY_RESTRICTED_CONTACT"
