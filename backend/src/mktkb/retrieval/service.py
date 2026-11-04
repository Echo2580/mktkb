"""T05 检索服务：当前有效记录的精确字段检索与中文正文检索。

安全与一致性：
- 每条渠道（字段、FTS、短词子串、候选计数、来源 ID 直取）最终都经
  ``visible_source_units_stmt()`` 读取单元，旧版本/取消/删除内容不可见；
- 所有值均通过 SQLAlchemy 绑定参数或 FTS 安全字面量传入，筛选键/请求字段不拼 SQL；
- 索引未就绪抛 IndexNotReady，revision 过时抛 KnowledgeRevisionChanged，均不映射为 none。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from ..documents.lifecycle import visible_source_units_stmt
from ..documents.models import DocumentVersion, KnowledgeState, SourceUnit
from .index import HEADER_ROLES, resolve_requested_role
from .models import RetrievalFieldIndex, RetrievalUnitIndex
from .tokenize import is_short_term, match_expression, normalize_value
from .verify_cache import verify_version_index_cached
from .types import (
    Candidate,
    EvidenceSet,
    IndexNotReady,
    KnowledgeRevisionChanged,
    QueryIntent,
    QueryRejected,
    normalize_intent,
    validate_limit,
)


def _visible_version_ids(db: Session) -> set:
    return set(
        db.scalars(visible_source_units_stmt().with_only_columns(SourceUnit.version_id).distinct()).all()
    )


def _read_revision(db: Session) -> int:
    """只读 revision；不对缺失行做写入/提交，保证读快照不被内部写破坏。"""
    value = db.scalar(select(KnowledgeState.revision).where(KnowledgeState.id == 1))
    return 0 if value is None else int(value)


@contextmanager
def _read_snapshot(db: Session) -> Iterator[Session]:
    """在独立连接上建立一个数据库级短读快照。

    - 显式 BEGIN 后的第一次 SELECT 固定快照；revision、就绪判断、召回、候选/冲突计数与
      最终来源读取都在同一读事务内，WAL 下写入者可并发提交而不会混入本次结果；
    - 不提交/回滚调用方 Session，也不复用其 ORM 身份映射，避免旧的 KnowledgeState 或旧
      单元对象污染结果；
    - 结果单元在离开会话前 expunge，仍保留已加载列值，供调用方继续读取字段/定位/ID。
    """
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)
    snapshot = Session(bind=engine, expire_on_commit=False)
    try:
        snapshot.execute(text("BEGIN"))
        yield snapshot
    finally:
        try:
            snapshot.expunge_all()
        finally:
            snapshot.rollback()
            snapshot.close()


def _ensure_indexes_ready(db: Session) -> None:
    """任何可见有效版本缺少真实完整索引时，整体报 IndexNotReady。"""
    try:
        _ensure_indexes_ready_inner(db)
    except OperationalError:
        raise IndexNotReady("检索索引结构不可用，请完成迁移与索引回填") from None


def _ensure_indexes_ready_inner(db: Session) -> None:
    version_ids = _visible_version_ids(db)
    if not version_ids:
        return
    # T10-PRE：同 revision 下复用“已完整核验通过”的真实行状态；索引行一旦被删除/改写/
    # 新增，状态指纹随之变化并触发完整核验，因此不会用缓存吞掉损坏检测（见 verify_cache）。
    revision = _read_revision(db)
    for version_id in version_ids:
        version = db.get(DocumentVersion, version_id, populate_existing=True)
        if version is None or not verify_version_index_cached(db, version, revision=revision):
            raise IndexNotReady("当前有效资料的检索索引不完整，请先完成索引回填或显式重建")


def _fts_unit_ids(db: Session, expression: str | None) -> set:
    if not expression:
        return set()
    try:
        rowids = db.execute(
            text("SELECT rowid FROM source_unit_fts WHERE source_unit_fts MATCH :expr"), {"expr": expression}
        ).scalars().all()
    except OperationalError:
        raise IndexNotReady("检索索引结构不可用，请完成迁移与索引回填") from None
    if not rowids:
        return set()
    return set(
        db.scalars(
            select(RetrievalUnitIndex.unit_id)
            .join(SourceUnit, SourceUnit.id == RetrievalUnitIndex.unit_id)
            .where(
                RetrievalUnitIndex.fts_rowid.in_(rowids),
                RetrievalUnitIndex.version_id == SourceUnit.version_id,
                RetrievalUnitIndex.document_id == SourceUnit.document_id,
            )
        ).all()
    )


def _filter_ids(db: Session, entity_filters: dict[str, str]) -> set | None:
    ids: set | None = None
    for key, value in entity_filters.items():
        role = key  # store/item/store_id/item_id 与字段角色同名
        norm = normalize_value(value)
        matched = set(
            db.scalars(
                select(RetrievalFieldIndex.unit_id)
                .join(SourceUnit, SourceUnit.id == RetrievalFieldIndex.unit_id)
                .where(
                    RetrievalFieldIndex.field_role == role,
                    RetrievalFieldIndex.norm_value == norm,
                    RetrievalFieldIndex.version_id == SourceUnit.version_id,
                    RetrievalFieldIndex.document_id == SourceUnit.document_id,
                )
            ).all()
        )
        ids = matched if ids is None else ids & matched
    return ids


def _visible_units(db: Session, unit_ids: set) -> list[SourceUnit]:
    if not unit_ids:
        return []
    return list(
        db.scalars(
            visible_source_units_stmt()
            .options(joinedload(SourceUnit.version).joinedload(DocumentVersion.document))
            .where(SourceUnit.id.in_(unit_ids))
            .order_by(SourceUnit.document_id, SourceUnit.ordinal)
        ).unique().all()
    )


def _term_ids(db: Session, term: str) -> set:
    """单个检索词的字段/短词/FTS 召回并集；字段原值不受分词改写。"""
    normalized = normalize_value(term)
    ids: set = set()
    if not normalized:
        return ids
    ids.update(
        db.scalars(
            select(RetrievalFieldIndex.unit_id)
            .join(SourceUnit, SourceUnit.id == RetrievalFieldIndex.unit_id)
            .where(
                RetrievalFieldIndex.norm_value == normalized,
                RetrievalFieldIndex.version_id == SourceUnit.version_id,
                RetrievalFieldIndex.document_id == SourceUnit.document_id,
            )
        ).all()
    )
    if is_short_term(term):
        ids.update(
            db.scalars(
                select(RetrievalFieldIndex.unit_id)
                .join(SourceUnit, SourceUnit.id == RetrievalFieldIndex.unit_id)
                .where(
                    func.instr(RetrievalFieldIndex.norm_value, normalized) > 0,
                    RetrievalFieldIndex.version_id == SourceUnit.version_id,
                    RetrievalFieldIndex.document_id == SourceUnit.document_id,
                )
            ).all()
        )
    ids.update(_fts_unit_ids(db, match_expression((term,))))
    return ids


def _conflict_roles(db: Session, unit_ids: list, requested_fields: tuple[str, ...]) -> tuple[dict, set]:
    """同一实体同一字段的不同有效值；返回 (角色 -> {规范化值: {原值}}, 涉及单元 ID)。"""
    roles = []
    for label in requested_fields:
        role = resolve_requested_role(label)
        if role in HEADER_ROLES:
            roles.append(role)
    if not roles or not unit_ids:
        return {}, set()
    rows = db.scalars(
        select(RetrievalFieldIndex)
        .join(SourceUnit, SourceUnit.id == RetrievalFieldIndex.unit_id)
        .where(
            RetrievalFieldIndex.unit_id.in_(unit_ids),
            RetrievalFieldIndex.field_role.in_(roles),
            RetrievalFieldIndex.version_id == SourceUnit.version_id,
            RetrievalFieldIndex.document_id == SourceUnit.document_id,
        )
    ).all()
    grouped: dict[str, dict[str, set]] = {}
    for row in rows:
        if not row.norm_value:
            continue
        grouped.setdefault(row.field_role, {}).setdefault(row.norm_value, set()).add(row.value_text)
    conflicts = {role: values for role, values in grouped.items() if len(values) > 1}
    conflict_ids = {row.unit_id for row in rows if row.field_role in conflicts}
    return conflicts, conflict_ids


def _record_name_key(mapping) -> tuple | None:
    """记录的业务名称键：物品记录用 (门店, 物品)，店家记录用 (门店)。"""
    filters = dict(getattr(mapping, "entity_filters", None) or {})
    store = filters.get("store")
    item = filters.get("item")
    if getattr(mapping, "entity_type", None) == "item" and item:
        return ("item", str(store or ""), str(item))
    if getattr(mapping, "entity_type", None) == "store" and store:
        return ("store", str(store))
    return None


def _has_identifier(mapping) -> bool:
    """该记录是否带明确标识（标识列决定 entity_key 为 ``type|id:...``）。"""
    key = str(getattr(mapping, "entity_key", "") or "")
    return "|id:" in key


def _merge_text_fact_groups(groups: dict) -> dict:
    """把「无标识来源」与同名称的「有标识记录」合并为一个实体组。

    T09-D2：正文通知没有"标识"列，按既有规则会得到独立实体键，同一实体因此被拆成
    "歧义"而不是"冲突"，正文通知也就无法参与冲突比较。这里只在**同一名称下同时存在
    有标识组与无标识组**时合并：
    - 两份表格记录即使显示名相同、标识不同（如 T01/T02），仍保持"歧义"，不合并、不按上传顺序选真；
    - 两份都没有标识的来源也保持原行为（各自独立候选）；
    - 正文通知（无标识）与表格记录（有标识）指向同一实体时，才能比较同一字段的不同有效值。
    """
    if len(groups) < 2:
        return groups
    buckets: dict[tuple, list[str]] = {}
    for key, members in groups.items():
        name_key = _record_name_key(members[0][1])
        if name_key is None:
            continue
        buckets.setdefault(name_key, []).append(key)
    merged = dict(groups)
    for _name_key, keys in buckets.items():
        if len(keys) < 2:
            continue
        identified = [key for key in keys if _has_identifier(groups[key][0][1])]
        unidentified = [key for key in keys if not _has_identifier(groups[key][0][1])]
        if not identified or not unidentified:
            continue
        host = identified[0]
        combined = [member for key in keys for member in groups[key]]
        merged[host] = combined
        for key in keys:
            if key != host:
                merged.pop(key, None)
    return merged


def _units_with_roles(db: Session, unit_ids: list, roles: set) -> set:
    """返回"至少含一个本次请求字段角色"的单元 ID 集合。

    T09-D2：记录型检索按实体合并后，同实体下可能还有与本次提问字段无关的记录行
    （例如盘点通知行只有"盘点时间/地点"，而提问问的是"位置"）。这些行既不能回答本问，
    也会污染模型看到的证据，因此不作为本次记录候选；若整组都被排除，该实体也就不参与。
    """
    if not unit_ids or not roles:
        return set()
    rows = db.execute(
        select(RetrievalFieldIndex.unit_id, RetrievalFieldIndex.field_role).where(
            RetrievalFieldIndex.unit_id.in_(unit_ids),
            RetrievalFieldIndex.field_role.in_(sorted(roles)),
        )
    ).all()
    return {unit_id for unit_id, _role in rows}


def _retrieve_records(
    db: Session,
    intent: QueryIntent,
    revision: int,
    limit: int,
    candidate_ids: set[str] | None = None,
) -> EvidenceSet:
    if not intent.terms and not intent.entity_filters:
        raise QueryRejected("record 模式需要检索词或实体条件")

    ids: set | None = None
    filter_ids = _filter_ids(db, dict(intent.entity_filters)) if intent.entity_filters else None
    if filter_ids is not None:
        ids = filter_ids
    term_ids: set | None = None
    for term in intent.terms:
        term_ids = _term_ids(db, term) if term_ids is None else term_ids | _term_ids(db, term)
    if term_ids is not None:
        ids = term_ids if ids is None else ids & term_ids
    if candidate_ids is not None:
        # S2：rag 内核本轮召回的来源单元是记录型证据的上界；空集就是明确的无候选，
        # 不回退到未受限检索（否则等于绕过 rag 索引）。候选是字符串 ID，这里转成
        # SourceUnit 主键类型（UUID）再求交，避免类型不同导致空集误判。
        allowed: set = set()
        for item in candidate_ids:
            try:
                allowed.add(uuid.UUID(str(item)))
            except (TypeError, ValueError):
                continue
        ids = allowed if ids is None else ids & allowed

    units = _visible_units(db, ids or set())
    if not units:
        return EvidenceSet([], "none", 0, revision, [])

    unit_ids = [unit.id for unit in units]
    mappings = {
        row.unit_id: row
        for row in db.scalars(
            select(RetrievalUnitIndex)
            .join(SourceUnit, SourceUnit.id == RetrievalUnitIndex.unit_id)
            .where(
                RetrievalUnitIndex.unit_id.in_(unit_ids),
                RetrievalUnitIndex.version_id == SourceUnit.version_id,
                RetrievalUnitIndex.document_id == SourceUnit.document_id,
            )
        ).all()
    }
    groups: dict[str, list[tuple[SourceUnit, RetrievalUnitIndex]]] = {}
    for unit in units:
        mapping = mappings.get(unit.id)
        if mapping is None or not mapping.entity_key:
            continue
        if mapping.version_id != unit.version_id or mapping.document_id != unit.document_id:
            continue
        groups.setdefault(mapping.entity_key, []).append((unit, mapping))
    if not groups:
        return EvidenceSet([], "none", 0, revision, [])

    groups = _merge_text_fact_groups(groups)

    # T09-D2：同一实体下可能带着与本次提问字段无关的记录行（例如盘点通知行只有
    # "盘点时间/地点"，而提问问的是"位置"），它们不能回答本问，也会污染模型证据。
    # 先按"含本次请求字段角色"裁剪；只有当**所有**实体都被裁空时，才回退到原候选，
    # 让上层仍能按"实体存在但该字段未记录"给出缺失说明，而不是误报 not_found。
    if intent.requested_fields:
        requested_roles = {resolve_requested_role(label) for label in intent.requested_fields}
        requested_roles = {role for role in requested_roles if role in HEADER_ROLES}
        if requested_roles:
            allowed_ids = _units_with_roles(db, [unit.id for unit in units], requested_roles)
            filtered = {
                key: [member for member in members if member[0].id in allowed_ids]
                for key, members in groups.items()
            }
            filtered = {key: members for key, members in filtered.items() if members}
            if filtered:
                groups = filtered


    # 只有门店条件、没有物品条件时，门店条件指店家记录本身：若存在店家实体，
    # 就不把该门店下的物品/位置记录一起当成候选（避免“联系人”误配物品行）。
    if ("store" in intent.entity_filters or "store_id" in intent.entity_filters) and not (
        "item" in intent.entity_filters or "item_id" in intent.entity_filters
    ):
        store_keys = [key for key in groups if groups[key][0][1].entity_type == "store"]
        if store_keys:
            groups = {key: groups[key] for key in store_keys}

    total = len(groups)
    ordered_keys = sorted(groups, key=lambda key: (groups[key][0][1].label or "", key))
    selected_keys = ordered_keys[:limit]
    candidates = []
    for key in selected_keys:
        rows = sorted(groups[key], key=lambda item: (item[0].document_id, item[0].ordinal))
        candidates.append(
            Candidate(
                label=rows[0][1].label or key,
                entity_filters=dict(rows[0][1].entity_filters or {}),
                source_ids=tuple(str(unit.id) for unit, _mapping in rows),
                matched_terms=intent.terms,
            )
        )

    kind = "ambiguous" if total > 1 else "matches"
    selected_units = [unit for key in selected_keys for unit, _mapping in groups[key]]
    if total == 1:
        conflicts, conflict_ids = _conflict_roles(db, [unit.id for unit, _ in groups[selected_keys[0]]], intent.requested_fields)
        if conflicts:
            kind = "conflict"
            selected_units = [
                unit for unit, _mapping in groups[selected_keys[0]] if unit.id in conflict_ids
            ] or selected_units

    selected_units.sort(key=lambda unit: (unit.document_id, unit.ordinal))
    truncated = total > limit or len(selected_units) > limit
    return EvidenceSet(selected_units[:limit], kind, total, revision, candidates, truncated)


def _retrieve_documents(db: Session, intent: QueryIntent, revision: int, limit: int) -> EvidenceSet:
    if not intent.terms:
        raise QueryRejected("document 模式需要至少一个检索词")
    expression = match_expression(intent.terms)
    ids = _fts_unit_ids(db, expression)
    for term in intent.terms:
        if is_short_term(term):
            normalized = normalize_value(term)
            if normalized:
                ids.update(
                    db.scalars(
                        visible_source_units_stmt()
                        .with_only_columns(SourceUnit.id)
                        .where(func.instr(func.lower(SourceUnit.text), normalized) > 0)
                    ).all()
                )
    if intent.entity_filters:
        filter_ids = _filter_ids(db, dict(intent.entity_filters)) or set()
        ids &= filter_ids

    units = _visible_units(db, ids)
    if not units:
        return EvidenceSet([], "none", 0, revision, [])
    total = len(units)
    truncated = total > limit
    return EvidenceSet(units[:limit], "matches", total, revision, [], truncated)


def retrieve(
    db: Session,
    intent: QueryIntent,
    *,
    revision: int,
    limit: int = 20,
    candidate_ids: set[str] | None = None,
) -> EvidenceSet:
    """按当前 revision 在一致短读快照内检索有效资料。

    结果只能是请求 revision 下的完整旧快照，或明确的 KnowledgeRevisionChanged；
    不会把查询中途的发布/删除混合成“旧 revision + 新事实/假 none”。
    """
    intent = normalize_intent(intent)
    limit = validate_limit(limit)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise QueryRejected("revision 必须是非负整数")
    with _read_snapshot(db) as snapshot:
        current = _read_revision(snapshot)
        if int(revision) != current:
            raise KnowledgeRevisionChanged("知识库版本已变化，请重新查询")
        _ensure_indexes_ready(snapshot)
        if intent.mode == "record":
            return _retrieve_records(snapshot, intent, current, limit, candidate_ids)
        return _retrieve_documents(snapshot, intent, current, limit)
