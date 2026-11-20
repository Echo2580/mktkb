"""R0/C12 跨表并集（物品行 + 同门店店家行）合成件：去身份化，零真实数据。

被验证的产品行为（只由 ``backend/src/mktkb/retrieval/service.py`` 的检索层决定）：
- 一次提问**同时**要物品行字段（位置）与只登记在店家信息行上的字段（合作状态/联系人等）时，
  物品条件 ``entity_filters["item"]`` 只能命中物品行，店家行按同一 ``store`` 条件补入；
  两条来源行仍是**一个**候选（物品目标），不新造候选、不改排序/limit 口径；
- 只问物品属性、只问店家属性、或候选上界里没有店家行时，行为不变（不多带店家行）；
- 并入的店家行同样受业务日窗口约束，字段值取该行真实单元格值。

全部假门店/假表头/假值；不读 fixtures、题面、私有材料。
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select

from mktkb.documents.models import SourceUnit
from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag.legacy import LegacyIndex
from mktkb.retrieval.service import retrieve
from mktkb.retrieval.types import QueryIntent

STORE = "甲店"
ITEM = "立牌"
ITEM_SHEET = "合成物品表"
STORE_SHEET = "合成店家表"


def _doc(doc_id: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"synthetic/{doc_id}.xlsx",
        title=doc_id,
        file_kind="xlsx",
        version_id=f"V-{doc_id}-1",
        version_label="1",
        sha256=hashlib.sha256(doc_id.encode("utf-8")).hexdigest(),
        business_date=None,
    )


def _unit(doc: DocumentSpec, ordinal: int, fields: dict, sheet: str) -> AtomicUnit:
    return AtomicUnit(
        unit_id=f"U-{doc.doc_id}-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"sheet:{sheet}:row:{ordinal + 2}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet=sheet,
        locator={"sheet": sheet, "row": ordinal + 2, "header_row": 1},
        header_row=1,
        row_number=ordinal + 2,
        title=doc.title,
    )


def _index(tmp_path, *, store_fields: dict | None = None, item_extra: list[dict] | None = None) -> LegacyIndex:
    items = _doc("D-syn-join-items")
    stores = _doc("D-syn-join-stores")
    item_rows = [
        _unit(items, 0, {"标识": "P01", "门店": STORE, "物品": ITEM, "位置": "甲区"}, ITEM_SHEET),
        # 同门店但无关的物品行：只含数量，没有任何本次请求字段。
        _unit(items, 1, {"标识": "P02", "门店": STORE, "物品": "海报", "数量": "3"}, ITEM_SHEET),
    ]
    item_rows.extend(
        _unit(items, 2 + offset, fields, ITEM_SHEET)
        for offset, fields in enumerate(item_extra or [])
    )
    store_values = store_fields or {
        "标识": "S01",
        "门店": STORE,
        "联系人": "阿甲经理",
        "地址": "甲路1号",
        "合作状态": "合作中",
    }
    rows = [(items, item_rows), (stores, [_unit(stores, 0, store_values, STORE_SHEET)])]
    index = LegacyIndex(tmp_path / "synthetic-c12-join.sqlite3")
    index.build(rows)
    return index


def _all_unit_ids(index: LegacyIndex) -> set[str]:
    with index.database.session() as session:
        return {str(value) for value in session.scalars(select(SourceUnit.id)).all()}


def _unit_keys(index: LegacyIndex, ids) -> set[str]:
    if not ids:
        return set()
    with index.database.session() as session:
        rows = session.execute(
            select(SourceUnit.unit_key).where(
                SourceUnit.id.in_([uuid.UUID(str(item)) for item in ids])
            )
        ).scalars().all()
        return {str(key) for key in rows}


def _retrieve(index: LegacyIndex, requested, filters=None, candidate_ids=None, as_of=None):
    intent = QueryIntent(
        mode="record",
        entity_filters=dict(filters or {"store": STORE, "item": ITEM}),
        requested_fields=tuple(requested),
    )
    with index.database.session() as session:
        return retrieve(
            session,
            intent,
            revision=index.revision,
            limit=20,
            candidate_ids=candidate_ids,
            as_of=as_of,
        )


ITEM_ROW = f"sheet:{ITEM_SHEET}:row:2"
UNRELATED_ITEM_ROW = f"sheet:{ITEM_SHEET}:row:3"
STORE_ROW = f"sheet:{STORE_SHEET}:row:2"


# --------------------------------------------------------------------------- #
# 绿：物品字段 + 店家字段 → 同门店店家行并入同一候选
# --------------------------------------------------------------------------- #


def test_item_plus_store_field_joins_same_store_row(tmp_path):
    index = _index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("位置", "合作状态"), candidate_ids=bound)
        assert result.kind == "matches", result.kind
        assert result.total_candidates == 1, result.total_candidates
        keys = _unit_keys(index, {str(unit.id) for unit in result.units})
        assert keys == {ITEM_ROW, STORE_ROW}, keys
        # 多带出的店家行值必须是该行真实单元格值（逐字取自 fields，不做拼装）。
        store_unit = next(unit for unit in result.units if unit.unit_key == STORE_ROW)
        assert store_unit.fields["合作状态"] == "合作中"
        assert store_unit.fields["联系人"] == "阿甲经理"
        # 候选仍是物品目标：标签/筛选条件来自物品行，不因并入店家行而改写。
        assert result.candidates[0].entity_filters == {"store": STORE, "item": ITEM, "item_id": "P01"}
        assert result.candidates[0].source_ids == tuple(
            str(unit.id) for unit in sorted(result.units, key=lambda item: (item.document_id, item.ordinal))
        )
    finally:
        index.close()


def test_joined_store_row_is_window_filtered(tmp_path):
    index = _index(tmp_path, store_fields={
        "标识": "S01",
        "门店": STORE,
        "合作状态": "合作中",
        "失效日期": "2026-10-31",
    })
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("位置", "合作状态"), candidate_ids=bound, as_of="2026-11-01")
        keys = _unit_keys(index, {str(unit.id) for unit in result.units})
        assert keys == {ITEM_ROW}, keys
        assert result.kind == "matches", result.kind
    finally:
        index.close()


# --------------------------------------------------------------------------- #
# 反例：只问物品属性 / 只问店家属性 / 候选里没有店家行 → 不多带
# --------------------------------------------------------------------------- #


def test_single_item_attribute_does_not_join_store_row(tmp_path):
    index = _index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("位置",), candidate_ids=bound)
        keys = _unit_keys(index, {str(unit.id) for unit in result.units})
        assert keys == {ITEM_ROW}, keys
        assert all("合作状态" not in (unit.fields or {}) for unit in result.units)
        assert all("联系人" not in (unit.fields or {}) for unit in result.units)
    finally:
        index.close()


def test_store_level_label_only_keeps_item_target(tmp_path):
    """只问店家级标签（“负责人”按产品口径属于未记录字段）时不得改写成店家行。"""

    index = _index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("负责人",), candidate_ids=bound)
        keys = _unit_keys(index, {str(unit.id) for unit in result.units})
        assert keys == {ITEM_ROW}, keys
        assert all("甲路1号" not in (unit.text or "") for unit in result.units)
        assert all("阿甲经理" not in (unit.text or "") for unit in result.units)
    finally:
        index.close()


def test_requested_contact_joins_only_when_the_item_target_exists(tmp_path):
    index = _index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("联系人",), candidate_ids=bound)
        assert result.kind == "matches"
        assert _unit_keys(index, {str(unit.id) for unit in result.units}) == {STORE_ROW}

        missing_item = _retrieve(
            index, ("联系人",), filters={"store": STORE, "item": "不存在的物品"}, candidate_ids=bound,
        )
        assert missing_item.kind == "none"
        assert not missing_item.units
    finally:
        index.close()


def test_store_row_outside_candidate_bound_is_not_joined(tmp_path):
    index = _index(tmp_path)
    try:
        with index.database.session() as session:
            item_id = str(
                session.scalar(
                    select(SourceUnit.id).where(SourceUnit.unit_key == ITEM_ROW)
                )
            )
        result = _retrieve(index, ("位置", "合作状态"), candidate_ids={item_id})
        keys = _unit_keys(index, {str(unit.id) for unit in result.units})
        assert keys == {ITEM_ROW}, keys
    finally:
        index.close()


def test_multiple_item_targets_do_not_join_store_row(tmp_path):
    """两个物品目标时不做挂载：既不能靠挂载顺序并成一个目标，也不能多带店家行。"""

    index = _index(tmp_path, item_extra=[{"标识": "P10", "门店": STORE, "物品": ITEM, "位置": "乙区"}])
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("位置", "合作状态"), candidate_ids=bound)
        keys = _unit_keys(index, {str(unit.id) for unit in result.units})
        assert STORE_ROW not in keys, keys
        assert keys == {ITEM_ROW, f"sheet:{ITEM_SHEET}:row:4"}, keys
        assert result.kind == "ambiguous", result.kind
        assert result.total_candidates == 2, result.total_candidates
    finally:
        index.close()


# --------------------------------------------------------------------------- #
# 红：把并集关掉 → 回到“只按 item 过滤、店家字段缺来源”的改前形态
# --------------------------------------------------------------------------- #


def test_join_is_the_switch_for_the_second_source(tmp_path, monkeypatch):
    from mktkb.retrieval import service as retrieval_service

    index = _index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        monkeypatch.setattr(retrieval_service, "_store_join_ids", lambda db, intent: set())
        result = _retrieve(index, ("位置", "合作状态"), candidate_ids=bound)
        keys = _unit_keys(index, {str(unit.id) for unit in result.units})
        assert keys == {ITEM_ROW}, keys
        assert all("合作状态" not in (unit.fields or {}) for unit in result.units)
    finally:
        index.close()
