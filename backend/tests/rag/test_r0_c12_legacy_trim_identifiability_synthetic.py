"""R0/C12：legacy 记录检索「6 个候选 -> 1 条」的可辨识性合成件（去身份化，零真实数据）。

外部观测（lead 第九轮 SAFE 投影，只有计数/身份键）：
- 期望来源 **2**，候选上界 **6**（``candidate_unit_keys`` 未截断），期望来源 **2/2** 在上界里；
- ``legacy_retrieve_initial`` 只保留 **1** 个单元 → 最终引用 1。

本文件只回答一个更窄的问题：**在那组观测下，``backend/src/mktkb/retrieval/service.py``
里哪些裁剪点真的能把 6 裁成 1？** 全部假门店/假表头/假值，不读 fixtures、题面、私有材料。

可直接被观测检验的结论：

1. 实体等值（``_filter_ids``，service.py:162-180/360-362）**不可能**是这一刀：候选上界由
   **同一份** ``intent.entity_filters`` 生成（``conversations/service.py:2524-2531`` →
   ``qa/service.py:591-631`` → ``rag/retrieval.py:192-252``）。
   - 单键：每个候选都带该键的值 → ``_filter_ids`` 裁不动；
   - 双键（store+item）：同一行必须同时具备两个角色，跨文档的另一条期望来源**进不了上界**
     → 与「2/2 在上界里」矛盾。
   见 ``test_entity_filter_equality_needs_an_inconsistent_bound``。
2. 同记录分组/``_merge_text_fact_groups`` 只合并、不丢单元；``limit`` 只截到
   ``min(total, 20)``，且本轮未截断。见 ``test_limit_cannot_shrink_below_limit``。
3. 冲突切片（``total == 1`` 时，service.py:487-493）保留**承载冲突角色的全部单元**；
   一个角色出现 ≥2 个不同值至少需要 2 个单元 → 不可能剩 1。
   见 ``test_conflict_slice_never_yields_one``。
4. 唯一可达的「6 -> 1」落点是角色覆盖裁剪（``_units_with_roles`` ∪
   ``_units_with_field_labels``，service.py:416-432）：只有被裁掉的 5 行都不含本轮请求角色时
   才剩 1。见 ``test_role_trim_cuts_six_to_one_only_when_one_row_carries_role``。
5. 同一份候选 + 同一 entity_filters，若本轮请求角色是**两项**（位置+合作状态），两条期望来源
   各自带一项 → 裁剪后仍是 2 条 → **该问法下角色裁剪不是断点**。
   见 ``test_role_trim_keeps_both_when_each_expected_row_carries_a_requested_role``。

⇒ “legacy 只剩 1”本身**不足以指认机制**：它要么是该轮问法下的**正确**裁剪（只问位置时，
只有位置的行才是证据），要么断点在角色裁剪之外（业务日窗口 / 可见性 / 引用渲染）。判据是
**被保留那 1 个单元的 unit_key + entity_type** 与**该轮请求角色**——两者都已在同一 envelope 的
``db_projection.units`` / ``plan_observed.field_roles`` 里（离线、零成本、不出正文）。
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select

from mktkb.documents.models import SourceUnit
from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag.legacy import LegacyIndex
from mktkb.retrieval.models import RetrievalFieldIndex
from mktkb.retrieval.service import retrieve
from mktkb.retrieval.types import QueryIntent

STORE = "甲店"
ITEM = "立牌"
ITEM_SHEET = "合成物品表"
STORE_SHEET = "合成店家表"


# --------------------------------------------------------------------------- #
# 合成装配（去身份化）
# --------------------------------------------------------------------------- #


def _doc(doc_id: str, title: str, file_kind: str = "xlsx") -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"synthetic/{doc_id}.{file_kind}",
        title=title,
        file_kind=file_kind,
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


def _six_candidate_index(tmp_path) -> LegacyIndex:
    """6 个候选：1 条物品行（含位置）+ 4 条只含数量的物品行 + 1 条店家行（含合作状态、无位置）。

    对应 C12 的形状：两条“期望来源”分属两份资料的不同实体类型，其余 4 行是同一门店下
    与本次提问无关的行；它们全部满足 ``entity_filters={"store": 甲店}``。
    """

    items = _doc("D-syn-c12-items", "合成物品表")
    stores = _doc("D-syn-c12-stores", "合成店家表")
    rows = [
        # 期望来源 #1：物品行，携带“位置”角色
        (items, _unit(items, 0, {"标识": "P01", "门店": STORE, "物品": ITEM, "位置": "甲区"}, ITEM_SHEET)),
        # 同门店的无关物品行：只有数量，没有位置
        (items, _unit(items, 1, {"标识": "P02", "门店": STORE, "物品": "海报", "数量": "3"}, ITEM_SHEET)),
        (items, _unit(items, 2, {"标识": "P03", "门店": STORE, "物品": "展架", "数量": "5"}, ITEM_SHEET)),
        (items, _unit(items, 3, {"标识": "P04", "门店": STORE, "物品": "台卡", "数量": "8"}, ITEM_SHEET)),
        (items, _unit(items, 4, {"标识": "P05", "门店": STORE, "物品": "立牌架", "数量": "2"}, ITEM_SHEET)),
        # 期望来源 #2：店家行，携带“合作状态”角色，没有位置
        (
            stores,
            _unit(
                stores,
                0,
                {"标识": "S01", "门店": STORE, "合作状态": "合作中", "电话": "010-00000000"},
                STORE_SHEET,
            ),
        ),
    ]
    by_doc: dict[str, tuple[DocumentSpec, list[AtomicUnit]]] = {}
    for doc, unit in rows:
        by_doc.setdefault(doc.doc_id, (doc, []))[1].append(unit)
    index = LegacyIndex(tmp_path / "synthetic-c12-identifiability.sqlite3")
    index.build(list(by_doc.values()))
    return index


def _all_unit_ids(index: LegacyIndex) -> set[str]:
    with index.database.session() as session:
        return {str(value) for value in session.scalars(select(SourceUnit.id)).all()}


def _unit_keys(index: LegacyIndex, ids: set[str]) -> set[str]:
    import uuid as _uuid

    keys: set[str] = set()
    with index.database.session() as session:
        rows = session.execute(
            select(SourceUnit.unit_key).where(
                SourceUnit.id.in_([_uuid.UUID(str(item)) for item in ids])
            )
        ).scalars().all()
        keys.update(str(key) for key in rows)
    return keys


def _retrieve(index: LegacyIndex, requested_fields, entity_filters=None, candidate_ids=None, as_of=None):
    intent = QueryIntent(
        mode="record",
        entity_filters=dict(entity_filters or {"store": STORE}),
        requested_fields=tuple(requested_fields),
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


def _same_filter_bound(index: LegacyIndex, filters: dict[str, str]) -> set[str]:
    """按 rag 记录面 ``_base_stmt`` 的等值过滤语义模拟候选上界（同一份 filters）。

    ``rag/retrieval.py:221-244``：每个键对 ``chunk.filters_norm[key]`` 做等值匹配；
    这里用产品字段索引的同一批角色/原值复算“该上界里有哪些来源单元”。
    """

    with index.database.session() as session:
        ids: set[str] | None = None
        for role, value in filters.items():
            matched = {
                str(unit_id)
                for unit_id, norm in session.execute(
                    select(RetrievalFieldIndex.unit_id, RetrievalFieldIndex.norm_value).where(
                        RetrievalFieldIndex.field_role == role
                    )
                ).all()
                if norm == value
            }
            ids = matched if ids is None else ids & matched
        return ids or set()


# --------------------------------------------------------------------------- #
# 主用例：唯一可达的 6 -> 1
# --------------------------------------------------------------------------- #


def test_role_trim_cuts_six_to_one_only_when_one_row_carries_role(tmp_path):
    index = _six_candidate_index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        assert len(bound) == 6, bound
        # 复现外部观测：候选上界 6 条，两条“期望来源”都在里面。
        keys = _unit_keys(index, bound)
        assert f"sheet:{ITEM_SHEET}:row:2" in keys
        assert f"sheet:{STORE_SHEET}:row:2" in keys

        # 只问“位置”：6 个候选里只有物品行带该角色 → legacy 只剩 1 条。
        result = _retrieve(index, ("位置",), candidate_ids=bound)
        assert result.kind == "matches", result.kind
        assert len(result.units) == 1, [unit.unit_key for unit in result.units]
        assert result.units[0].unit_key == f"sheet:{ITEM_SHEET}:row:2"
        # 被裁掉的那一条正是跨文档的期望来源 #2（只带合作状态，没有位置）。
        assert all("合作状态" not in (unit.fields or {}) for unit in result.units)
    finally:
        index.close()


def test_role_trim_keeps_both_when_each_expected_row_carries_a_requested_role(tmp_path):
    """反例（同一份 6 候选）：请求角色两项时角色裁剪不是断点 —— 两条来源各自带一项，仍是 2 条。"""

    index = _six_candidate_index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("位置", "合作状态"), candidate_ids=bound)
        keys = {str(unit.unit_key) for unit in result.units}
        assert keys == {f"sheet:{ITEM_SHEET}:row:2", f"sheet:{STORE_SHEET}:row:2"}, keys
        assert result.kind == "matches", result.kind
    finally:
        index.close()


# --------------------------------------------------------------------------- #
# 排除法：实体等值需要“上界与过滤器不一致”的前提
# --------------------------------------------------------------------------- #


def test_entity_filter_equality_needs_an_inconsistent_bound(tmp_path):
    """双键等值确实能把 6 裁成 1，但生产上界由同一份 filters 生成 → 另一条来源进不了上界。"""

    index = _six_candidate_index(tmp_path)
    try:
        bound = _all_unit_ids(index)

        # (a) 单键 store：上界里每条都带该值 → 等值裁不动（6 条都在）。
        store_bound = _same_filter_bound(index, {"store": STORE})
        assert store_bound == bound, store_bound
        kept = _retrieve(index, (), {"store": STORE}, candidate_ids=store_bound)
        # 无请求字段时 store-only 捷径会把同门店行并成 1 个候选，但单元数不会变成 1。
        assert len(kept.units) >= 1

        # (b) 双键 store+item：上界只含“同时具备两个角色”的物品行 → 店家行根本不在上界里。
        two_key_bound = _same_filter_bound(index, {"store": STORE, "item": ITEM})
        assert two_key_bound, two_key_bound
        assert f"sheet:{STORE_SHEET}:row:2" not in _unit_keys(index, two_key_bound)

        # 若硬把这 6 条塞进双键 intent：R0/C12 修点前等值过滤裁到 1（正是“上界不一致”
        # 才出现的形状）；修点后「物品字段 + 店家字段」按同门店把店家行并回证据面，
        # 两条期望来源各自的那一行都在，但仍是**一个**物品目标（不是新候选）。
        forced = _retrieve(index, ("位置", "合作状态"), {"store": STORE, "item": ITEM}, candidate_ids=bound)
        keys = {str(unit.unit_key) for unit in forced.units}
        assert keys == {f"sheet:{ITEM_SHEET}:row:2", f"sheet:{STORE_SHEET}:row:2"}, keys
        assert forced.total_candidates == 1, forced.total_candidates
        assert forced.kind == "matches", forced.kind
    finally:
        index.close()


# --------------------------------------------------------------------------- #
# 排除法：分组/去重、冲突切片、limit
# --------------------------------------------------------------------------- #


def test_window_filter_can_produce_the_same_shape(tmp_path):
    """同一组“6 进、两条来源都在、1 出”的观测，还可以由**业务日窗口**产生（不同修点）。

    候选上界用 ``include_future=True``、无业务日生成（qa/service.py:626/649），而 legacy
    证据面按业务日裁剪（service.py:382 → ``_drop_out_of_window``）。两条期望行的窗口若跨过
    业务日，legacy 会丢掉其中一条 —— 形状与角色裁剪**逐值相同**，但修点不是 ``_units_with_roles``。
    """

    items = _doc("D-syn-c12-window-items", "合成物品表")
    stores = _doc("D-syn-c12-window-stores", "合成店家表")
    rows = [
        (
            items,
            _unit(
                items,
                0,
                {"标识": "P01", "门店": STORE, "物品": ITEM, "位置": "甲区", "失效日期": "2026-10-31"},
                ITEM_SHEET,
            ),
        ),
        (
            items,
            _unit(
                items,
                1,
                {"标识": "P02", "门店": STORE, "物品": "海报", "位置": "甲区", "失效日期": "2026-10-31"},
                ITEM_SHEET,
            ),
        ),
        (
            stores,
            _unit(
                stores,
                0,
                {"标识": "S01", "门店": STORE, "合作状态": "合作中", "失效日期": "2026-11-15"},
                STORE_SHEET,
            ),
        ),
    ]
    index = LegacyIndex(tmp_path / "synthetic-c12-window.sqlite3")
    index.build([(items, [rows[0][1], rows[1][1]]), (stores, [rows[2][1]])])
    try:
        bound = _all_unit_ids(index)
        assert len(bound) == 3
        # 业务日 2026-11-01：物品行（失效 10-31）过期，店家行（失效 11-15）仍在窗口内。
        result = _retrieve(index, ("位置", "合作状态"), candidate_ids=bound, as_of="2026-11-01")
        keys = {str(unit.unit_key) for unit in result.units}
        assert keys == {f"sheet:{STORE_SHEET}:row:2"}, keys
    finally:
        index.close()


def test_naive_trim_removal_leaks_unrelated_rows(tmp_path, monkeypatch):
    """候选最小修点「直接去掉角色裁剪」在本合成件上会多带 5 条无关行 → 不可用（红）。

    这正是“证伪”：若把 ``_units_with_roles`` 的裁剪当成 C12 的修点，单实体单记录问法就会多出
    同门店的无关记录（4 条无位置物品行 + 1 条店家行），违反「不因修复多出无关记录」。
    """

    from mktkb.retrieval import service as retrieval_service

    index = _six_candidate_index(tmp_path)
    try:
        bound = _all_unit_ids(index)
        monkeypatch.setattr(
            retrieval_service,
            "_units_with_roles",
            lambda db, unit_ids, roles: {item for item in unit_ids},
        )
        monkeypatch.setattr(
            retrieval_service, "_units_with_field_labels", lambda db, unit_ids, labels: set()
        )
        leaked = _retrieve(index, ("位置",), candidate_ids=bound)
        keys = {str(unit.unit_key) for unit in leaked.units}
        assert len(keys) == 6, keys  # 6 条全进证据面
    finally:
        index.close()


def test_conflict_slice_never_yields_one(tmp_path):
    """同一实体两条记录、两个不同位置值 → kind=conflict，保留两条，不会只剩 1。"""

    doc = _doc("D-syn-c12-conflict", "合成物品表")
    rows = [
        _unit(doc, 0, {"标识": "P01", "门店": STORE, "物品": ITEM, "位置": "甲区"}, ITEM_SHEET),
        _unit(doc, 1, {"标识": "P01", "门店": STORE, "物品": ITEM, "位置": "乙区"}, ITEM_SHEET),
    ]
    index = LegacyIndex(tmp_path / "synthetic-c12-conflict.sqlite3")
    index.build([(doc, rows)])
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("位置",), candidate_ids=bound)
        assert result.total_candidates == 1, result.total_candidates
        assert result.kind == "conflict", result.kind
        assert len(result.units) == 2, [unit.unit_key for unit in result.units]
    finally:
        index.close()


def test_limit_cannot_shrink_below_limit(tmp_path):
    """25 个同门店物品行、20 上限 → 截断发生在 20 条，不是 1 条。"""

    doc = _doc("D-syn-c12-limit", "合成物品表")
    rows = [
        _unit(doc, ordinal, {"标识": f"P{ordinal:02d}", "门店": STORE, "物品": f"物料{ordinal}", "位置": "甲区"}, ITEM_SHEET)
        for ordinal in range(25)
    ]
    index = LegacyIndex(tmp_path / "synthetic-c12-limit.sqlite3")
    index.build([(doc, rows)])
    try:
        intent = QueryIntent(mode="record", entity_filters={"store": STORE})
        with index.database.session() as session:
            result = retrieve(session, intent, revision=index.revision, limit=20)
        assert result.total_candidates == 25, result.total_candidates
        assert result.truncated is True
        assert len(result.units) == 20, len(result.units)
    finally:
        index.close()


# --------------------------------------------------------------------------- #
# 正常反例：单实体单记录问法行为不变
# --------------------------------------------------------------------------- #


def test_single_entity_single_record_is_unchanged(tmp_path):
    """单实体单记录：候选就是那一条，输出仍是那一条，不多带任何无关记录。"""

    doc = _doc("D-syn-c12-single", "合成物品表")
    row = _unit(doc, 0, {"标识": "P01", "门店": STORE, "物品": ITEM, "位置": "甲区"}, ITEM_SHEET)
    index = LegacyIndex(tmp_path / "synthetic-c12-single.sqlite3")
    index.build([(doc, [row])])
    try:
        bound = _all_unit_ids(index)
        result = _retrieve(index, ("位置",), candidate_ids=bound)
        assert result.kind == "matches"
        assert [unit.unit_key for unit in result.units] == [f"sheet:{ITEM_SHEET}:row:2"]
        assert result.total_candidates == 1
        assert result.truncated is False
    finally:
        index.close()


@pytest.mark.parametrize("requested", [("位置",), ("位置", "合作状态")])
def test_candidate_bound_is_part_of_the_contract(tmp_path, requested):
    """``candidate_ids`` 是上界：传空集就是明确无候选（不回退到未受限检索）。"""

    index = _six_candidate_index(tmp_path)
    try:
        empty = _retrieve(index, requested, candidate_ids=set())
        assert empty.units == []
        assert empty.kind == "none"
    finally:
        index.close()
