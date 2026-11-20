from mktkb.conversations.intent import EntityLexicon, parse_question
from mktkb.rag.query import Lexicon, parse_query


def test_explicit_topic_change_does_not_silently_guess_store():
    rag_lexicon = Lexicon(stores=("北园店", "南园店"), items=("展板", "横幅"), field_labels=("位置",))
    first = parse_query("北园店展板放在哪里？", previous=None, lexicon=rag_lexicon)
    second = parse_query("换个话题，采购流程有哪些步骤？", previous=first.state, lexicon=rag_lexicon)
    assert second.state.store is None
    lexicon = EntityLexicon(store_labels=("北园店", "南园店"), item_labels=("展板", "横幅"), identifier_labels=())
    third = parse_question("横幅呢？", lexicon=lexicon,
                           context_questions=("换个话题，采购流程有哪些步骤？",), context_entities={})
    assert third.clarification
    assert third.intent is None


def test_explicit_document_request_is_not_confused_with_bare_followup():
    lexicon = EntityLexicon(store_labels=("北园店", "南园店"), item_labels=("横幅",), identifier_labels=())
    plan = parse_question("横幅的制作流程有哪些规定？", lexicon=lexicon,
                          context_questions=("换个话题，采购流程有哪些步骤？",), context_entities={})
    assert plan.security_refusal is None
    assert not plan.clarification


def test_document_source_from_switched_topic_is_not_inherited_as_store():
    lexicon = EntityLexicon(store_labels=("北园店", "南园店"), item_labels=("横幅",), identifier_labels=())
    plan = parse_question("横幅呢？", lexicon=lexicon,
                          context_questions=("换个话题，采购流程有哪些步骤？",),
                          context_entities={"store": "南园店"})
    assert plan.clarification
    assert plan.intent is None
