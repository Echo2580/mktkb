from mktkb.rag.query import DocumentRef, Lexicon, _document_core, _match_document


def test_numbered_upload_title_matches_human_title():
    doc = DocumentRef(doc_id="synthetic-1", title="D99_设备巡检表.xlsx")
    lexicon = Lexicon(documents=(doc,))
    assert _document_core(doc.title) == "设备巡检表"
    assert _match_document("设备巡检表在哪里", lexicon) == (doc, ())


def test_other_underscore_titles_keep_existing_meaning():
    assert _document_core("设备巡检表_旧版.xlsx") == "设备巡检表"
    assert _document_core("D99_设备巡检表_旧版.xlsx") == "设备巡检表"
