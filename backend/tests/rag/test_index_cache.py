"""向量缓存复用、版本删除/切换后可见性与内容哈希缓存不误用。"""

from __future__ import annotations

from mktkb.rag.index import _cache_key


ROWS = [
    {"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧", "数量": 40, "单位": "张"},
    {"标识": "QF02", "门店": "鹿鸣路店", "物品": "宣传海报", "位置": "入口堆头旁", "数量": 24, "单位": "张"},
]


def test_cache_reused_across_documents_and_delete_does_not_delete_cache(rag_index, add_records, make_doc):
    first = add_records(ROWS)
    stats = rag_index.stats()
    assert stats["embedding_stats"]["provider_calls"] == 1
    cache_count = stats["embedding_cache"]

    second = add_records(ROWS, doc=make_doc(doc_id="E11-copy", title="测试资料"))
    stats = rag_index.stats()
    assert stats["embedding_stats"]["provider_calls"] == 1
    assert stats["embedding_cache"] == cache_count
    assert stats["chunk_embeddings"] == 4

    rag_index.remove_document(first.doc_id)
    answer = rag_index.ask("滨江店的宣传海报在哪里？", user_id="u", conversation_id="c")
    assert answer.kind == "answer"
    assert "店内外侧" in answer.text
    assert rag_index.stats()["embedding_cache"] == cache_count

    rag_index.remove_document(second.doc_id)
    answer = rag_index.ask("滨江店的宣传海报在哪里？", user_id="u2", conversation_id="c2")
    assert answer.kind in ("no_answer", "clarification")
    assert rag_index.stats()["embedding_cache"] == cache_count


def test_version_supersede_and_activate(rag_index, add_records, make_doc):
    v1 = add_records(ROWS, doc=make_doc(doc_id="E11-v1", logical_id="E11"))
    v2 = add_records(
        [{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "D区暂存柜", "数量": 40, "单位": "张"}],
        doc=make_doc(doc_id="E11-v2", logical_id="E11", is_current=False, version_label="新版"),
    )
    first = rag_index.ask("滨江店的宣传海报在哪里？", user_id="u", conversation_id="c")
    assert "店内外侧" in first.text

    rag_index.set_active_version("E11", v2.version_id)
    second = rag_index.ask("滨江店的宣传海报在哪里？", user_id="u2", conversation_id="c2")
    assert "D区暂存柜" in second.text
    assert second.citations and "新版" in second.citations[0].version_label

    rag_index.remove_version(v1.version_id)
    third = rag_index.ask("滨江店的宣传海报在哪里？", user_id="u3", conversation_id="c3")
    assert "D区暂存柜" in third.text


def test_cache_key_distinguishes_model_dimensions_and_provider() -> None:
    content = "a" * 64
    base = _cache_key(content, "text-embedding-v4", 1024, "bailian")
    assert base != _cache_key(content, "text-embedding-v4", 512, "bailian")
    assert base != _cache_key(content, "other-model", 1024, "bailian")
    assert base != _cache_key(content, "text-embedding-v4", 1024, "mock")
    assert base == _cache_key(content, "text-embedding-v4", 1024, "bailian")
