"""R0 entity_key 统一：同一记录在两条链上必须派生出逐字相同的实体键。

两条链：
- 来源/单位侧 ``mktkb.retrieval.index.analyze_fields``（写 ``retrieval_unit_index.entity_key``，
  评测 ``db_projection.units`` 读它）；
- 产品事实侧 ``mktkb.rag.chunking._entity``（写 ``rag_chunks.entity_key``，
  ``direct_rag_answer.facts[].entity_key`` 读它）。

判据只有一条：同一 unit 的同一份 ``fields`` 走两条链得到同一字符串；不同记录的键仍不相等
（防止归一化过度把两个实体并成一个）。键形态由 ``mktkb.entity_identity`` 单点定义。
"""

from __future__ import annotations

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, build_chunks
from mktkb.retrieval.index import analyze_fields

DOC_ID = "9f1c0d6e-2b1a-4a52-8a4f-3b2d5c7e1a09"
UNIT_ID = "b0d6a83c-51ef-4c37-9a0e-7f2c1d4b6e88"


def _doc(doc_id: str = DOC_ID) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        source_path="corpus/物品位置表.xlsx",
        title="物品位置表",
        file_kind="xlsx",
        version_id="v-1",
        version_label="当前V1",
        sha256="a" * 64,
    )


def _unit(fields: dict, *, doc_id: str = DOC_ID, unit_id: str = UNIT_ID) -> AtomicUnit:
    return AtomicUnit(
        unit_id=unit_id,
        doc_id=doc_id,
        version_id="v-1",
        kind="table_row",
        ordinal=0,
        unit_key="sheet:台账:row:4",
        text="",
        fields=fields,
        sheet="台账",
        locator={"sheet": "台账", "row": 4, "header_row": 3},
        header_row=3,
        row_number=4,
        title="物品位置表",
    )


def _source_key(fields: dict, *, doc_id: str = DOC_ID, unit_id: str = UNIT_ID) -> str:
    """来源/单位侧键（retrieval 索引）。"""
    entity_type, entity_key = analyze_fields(fields, document_id=doc_id, unit_id=unit_id)[2:4]
    assert entity_type is not None and entity_key is not None
    return entity_key


def _fact_key(fields: dict, *, doc_id: str = DOC_ID, unit_id: str = UNIT_ID) -> str:
    """产品事实侧键（rag 记录块；fact.entity_key 直接取 chunk.entity_key）。"""
    chunks = build_chunks(_doc(doc_id), [_unit(fields, doc_id=doc_id, unit_id=unit_id)], RagConfig())
    assert len(chunks) == 1
    assert chunks[0].entity_key is not None
    return chunks[0].entity_key


ITEM_WITH_ID = {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "位置": "A区1号货架"}
ITEM_NO_ID = {"门店": "北门店", "物品": "立牌", "位置": "一层入口"}
STORE_WITH_ID = {"标识": "S01", "店家": "城东店", "联系人": "陈宁", "电话": "010-00000001"}
STORE_NO_ID = {"店家": "南门店", "联系人": "王平", "合作状态": "合作中"}


def test_identified_item_record_has_the_same_key_on_both_chains() -> None:
    assert _source_key(ITEM_WITH_ID) == "item|id:p01"
    assert _fact_key(ITEM_WITH_ID) == "item|id:p01"


def test_unidentified_item_record_has_the_same_key_on_both_chains() -> None:
    assert _source_key(ITEM_NO_ID) == _fact_key(ITEM_NO_ID)
    # 无标识时不得跨行/跨资料合并：键必须带资料与单元身份。
    assert DOC_ID in _fact_key(ITEM_NO_ID) and UNIT_ID in _fact_key(ITEM_NO_ID)


def test_store_record_has_the_same_key_on_both_chains() -> None:
    assert _source_key(STORE_WITH_ID) == _fact_key(STORE_WITH_ID) == "store|id:s01"
    assert _source_key(STORE_NO_ID) == _fact_key(STORE_NO_ID)


def test_identifier_normalization_is_shared() -> None:
    """同一套归一化（NFKC + 空白折叠 + casefold）：写法不同、标识相同 => 同一个键。"""
    for variant in ({"标识": " p01 ", "门店": "城东店", "物品": "宣传海报"}, {"标识": "Ｐ０１", "门店": "城东店", "物品": "宣传海报"}):
        assert _source_key(variant) == _fact_key(variant) == "item|id:p01"


def test_different_identifiers_stay_distinct_on_both_chains() -> None:
    other = {**ITEM_WITH_ID, "标识": "P02", "门店": "城西店"}
    assert _source_key(ITEM_WITH_ID) != _source_key(other)
    assert _fact_key(ITEM_WITH_ID) != _fact_key(other)


def test_unidentified_rows_in_different_units_stay_distinct() -> None:
    """同名不同单元（无标识）不得被归一化并成一个实体。"""
    second = "11111111-2222-4333-8444-555555555555"
    assert _source_key(ITEM_NO_ID, unit_id=second) != _source_key(ITEM_NO_ID)
    assert _fact_key(ITEM_NO_ID, unit_id=second) != _fact_key(ITEM_NO_ID)


def test_same_unit_derives_identical_key_twice() -> None:
    """纯函数性质：同一输入重复派生必须逐字相同（无随机/无顺序依赖）。"""
    assert _source_key(ITEM_NO_ID) == _source_key(ITEM_NO_ID)
    assert _fact_key(ITEM_NO_ID) == _fact_key(ITEM_NO_ID)
