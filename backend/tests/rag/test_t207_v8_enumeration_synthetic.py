def test_item_all_fields_does_not_disclose_restricted_contact(rag_index, add_records, make_doc):
    add_records([{"门店": "北园店", "物品": "展板", "位置": "甲柜", "电话": "010-55551234"}],
                doc=make_doc(title="合成设备资料"))
    answer = rag_index.ask("列出北园店展板的全部信息", user_id="u", conversation_id="c")
    assert answer.kind == "no_answer"
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT"
    assert not answer.citations
    assert "010-55551234" not in answer.text


def test_store_contact_without_item_remains_available(rag_index, add_records, make_doc):
    add_records([{"门店": "北园店", "电话": "010-55551234"}], doc=make_doc(title="合成门店资料"))
    answer = rag_index.ask("北园店的电话是多少？", user_id="u", conversation_id="c")
    assert answer.kind == "answer"
    assert "010-55551234" in answer.text


def test_item_all_fields_without_contact_remains_available(rag_index, add_records, make_doc):
    add_records([{"门店": "北园店", "物品": "展板", "位置": "甲柜"}],
                doc=make_doc(title="合成设备资料"))
    answer = rag_index.ask("列出北园店展板的全部信息", user_id="u", conversation_id="c")
    assert answer.kind == "answer"
    assert "甲柜" in answer.text
