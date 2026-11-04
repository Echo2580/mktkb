"""T05 检索层单元检查：分词/规范化、FTS 安全构造、字段角色映射、输入边界与反硬编码。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mktkb.retrieval.index import HEADER_ROLES, analyze_fields, resolve_requested_role
from mktkb.retrieval.tokenize import (
    TOKENIZER_VERSION,
    bigrams,
    cut,
    index_body,
    match_expression,
    normalize,
    normalize_value,
    term_expression,
)
from mktkb.retrieval.types import (
    FILTER_KEYS,
    QueryIntent,
    QueryRejected,
    normalize_intent,
    validate_limit,
)

ROOT = Path(__file__).resolve().parents[3]
RETRIEVAL_SRC = ROOT / "backend" / "src" / "mktkb" / "retrieval"


def test_normalize_is_nfkc_casefolded_and_keeps_original_values_separate():
    assert normalize("  城东店　的宣传海报  ") == "城东店 的宣传海报"
    assert normalize("ＡＢＣ－１２３") == "abc-123"
    assert normalize_value("010-00000001") == "010-00000001"
    assert normalize_value(None) == ""


def test_cut_and_bigrams_cover_domain_aliases():
    tokens = cut("城东店的宣传海报")
    assert "宣传海报" in tokens
    grams = bigrams("价签纸")
    assert grams == ("价签", "签纸")
    body = index_body("价签卡纸")
    assert "价签卡纸" in body.split()
    assert "价签" in body.split()
    assert TOKENIZER_VERSION.startswith("jieba-0.42.1")


def test_fts_expression_quotes_user_operators():
    expression = term_expression('宣传" OR "海报*')
    assert expression is not None
    assert " OR " in expression  # 只可能是我们构造的 OR，不在引号外暴露用户文本
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
        connection.execute("INSERT INTO t(body) VALUES (?)", (index_body("城东店的宣传海报"),))
        connection.execute("INSERT INTO t(body) VALUES (?)", (index_body("海报展示架"),))
        connection.execute("INSERT INTO t(body) VALUES (?)", (index_body("无关段落"),))
        # 若用户文本被直接拼接，`宣传" OR "海报*` 会同时命中“海报展示架”；
        # 安全构造只能命中同时包含“宣传”与“海报”的那一条。
        rows = connection.execute(
            "SELECT rowid FROM t WHERE t MATCH ? ORDER BY rowid", (expression,)
        ).fetchall()
        assert rows == [(1,)], rows
        literal = term_expression("宣传海报")
        rows = connection.execute("SELECT rowid FROM t WHERE t MATCH ?", (literal,)).fetchall()
        assert rows == [(1,)]
    finally:
        connection.close()


def test_match_expression_joins_terms_with_or_and_ignores_empty():
    assert match_expression(()) is None
    assert match_expression(("",)) is None
    expression = match_expression(("海报", "展架"))
    assert expression is not None and expression.count(" OR ") >= 1


def test_field_roles_do_not_unify_position_and_store_identifiers():
    position = {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "别名": "海报", "位置": "B区1号货架第二层"}
    _roles, _values, kind, key, label, filters = analyze_fields(position, document_id="doc-1", unit_id="unit-1")
    assert kind == "item"
    assert key == "item|id:p01"
    assert label == "城东店的宣传海报"
    assert filters == {"store": "城东店", "item": "宣传海报", "item_id": "P01"}

    store = {"标识": "S01", "店家": "城东店", "联系人": "陈宁", "电话": "010-00000001", "合作状态": "合作中"}
    _roles, _values, kind, key, label, filters = analyze_fields(store, document_id="doc-2", unit_id="unit-2")
    assert kind == "store"
    assert key == "store|id:s01"
    assert label == "城东店"
    assert filters["store_id"] == "S01"

    unknown = {"备注": "临时说明"}
    roles, _values, kind, key, label, filters = analyze_fields(unknown, document_id="d", unit_id="u")
    assert kind is None and key is None and filters is None
    assert roles == {"备注": None}


def test_records_without_identifier_are_not_merged():
    row = {"门店": "同名店", "物品": "海报", "位置": "A区"}
    _r, _v, kind, key_a, _l, _f = analyze_fields(row, document_id="doc-a", unit_id="unit-a")
    _r, _v, kind_b, key_b, _l, _f = analyze_fields(row, document_id="doc-b", unit_id="unit-b")
    assert kind == kind_b == "item"
    assert key_a != key_b, "没有明确标识时不得跨资料合并为同一实体"


def test_requested_field_labels_map_to_roles_not_sql_columns():
    assert resolve_requested_role("位置") == "location"
    assert resolve_requested_role("电话") == "phone"
    assert resolve_requested_role("合作状态") == "status"
    assert resolve_requested_role("store") == "store"
    assert resolve_requested_role("营业时间") is None
    assert set(HEADER_ROLES) >= {"store", "item", "location", "contact", "phone", "address", "status"}


def test_intent_validation_rejects_unknown_filters_and_bad_limits():
    with pytest.raises(QueryRejected):
        normalize_intent(QueryIntent(mode="sql"))  # type: ignore[arg-type]
    with pytest.raises(QueryRejected):
        normalize_intent(QueryIntent(mode="record", entity_filters={"sql": "1"}))
    with pytest.raises(QueryRejected):
        normalize_intent(QueryIntent(mode="record", terms=(123,)))  # type: ignore[arg-type]
    with pytest.raises(QueryRejected):
        normalize_intent(QueryIntent(mode="record", terms=("词" * 65,)))
    with pytest.raises(QueryRejected):
        normalize_intent(QueryIntent(mode="record", requested_fields=("字段" * 20,)))
    assert validate_limit(1) == 1 and validate_limit(100) == 100
    for bad in (0, 101, True, "5", 1.0):
        with pytest.raises(QueryRejected):
            validate_limit(bad)
    intent = normalize_intent(
        QueryIntent(mode="record", terms=("  海报 ", "海报", ""), entity_filters={"store": " 城东店 "})
    )
    assert intent.terms == ("海报",) and intent.entity_filters == {"store": "城东店"}
    assert set(FILTER_KEYS) == {"store", "item", "store_id", "item_id"}


def test_production_retrieval_code_has_no_frozen_answers_or_fixture_paths():
    forbidden = ("P01", "S01", "城东店", "城西店", "questions.json", "manifest.json", "fixtures/acceptance")
    for path in sorted(RETRIEVAL_SRC.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.name} 含预设答案/路径片段：{token}"
