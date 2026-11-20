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
from datetime import date
from typing import Iterable, Iterator

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

#: 店家记录行自身能承载的字段角色。store-only 检索命中店家记录时，只有请求字段
#: 全部落在这些角色内，才把候选收敛到店家行；否则同门店的记录行可能是唯一来源。
_STORE_RECORD_ROLES = frozenset({"store", "contact", "phone", "address", "status", "alias"})

#: 只登记在店家信息行上的字段角色（物品位置行没有这些列）。R0/C12：一次提问同时要
#: "物品字段 + 这些字段"时，物品行的 ``entity_filters["item"]`` 等值过滤天然命不中
#: 店家行，证据面会缺掉唯一承载这些值的来源；因此按同一门店把店家行一并纳入。
_STORE_LEVEL_FIELD_ROLES = frozenset({"contact", "phone", "address", "status"})

#: 只登记在物品位置行上的字段角色。跨表纳入要求本问**同时**问到一个物品行字段：
#: 只问店家级字段（或"负责人"这类按产品口径未记录的字段标签）时保持既有口径，
#: 不能因为同门店存在店家行就把物品目标改写成店家行。
_ITEM_LEVEL_FIELD_ROLES = frozenset({"location"})


def _visible_version_ids(db: Session) -> set:
    return set(
        db.scalars(visible_source_units_stmt().with_only_columns(SourceUnit.version_id).distinct()).all()
    )


def _as_of_bound(value: object) -> str | None:
    """业务日取值校验：只接受 YYYY-MM-DD 文本；非法值在服务边界拒绝，不静默降级。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise QueryRejected("as_of 必须是 YYYY-MM-DD 文本")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise QueryRejected("as_of 必须是 YYYY-MM-DD 文本") from None


def _in_effective_window(fields: object, as_of: str) -> bool:
    """记录行自带的生效/失效窗口是否覆盖业务日（v3-fix-1/B）。

    窗口口径与 rag 索引同源：``rag.chunking.effective_dates`` 从行字段解析
    生效日期/失效日期（v3 语料按 L1 生命周期表逐值写入单元格）。闭区间语义：
    ``effective_from <= as_of <= effective_to``；未声明的一侧不参与判定（与冻结
    分类器“null 只削弱可判性”的口径一致）。这里只做时间维度的过滤，不改变召回
    与排序。
    """
    from ..rag.chunking import effective_dates  # 局部导入：避免 rag 包与检索层的模块级循环

    start, end = effective_dates(dict(fields or {}))
    if start and start > as_of:
        return False
    if end and end < as_of:
        return False
    return True


def _drop_out_of_window(units: list, as_of: str | None) -> list:
    """按业务日裁剪证据单元；``as_of`` 为空时原样返回（既有行为）。"""
    if as_of is None:
        return units
    return [unit for unit in units if _in_effective_window(getattr(unit, "fields", None), as_of)]


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


def _requested_roles(requested_fields: Iterable[str]) -> set:
    """请求字段标签 -> 已登记字段角色集合（未登记标签不参与）。"""
    return {
        role
        for role in (resolve_requested_role(label) for label in requested_fields)
        if role is not None
    }


def _store_join_ids(db: Session, intent: QueryIntent) -> set:
    """「物品 + 店家级字段」跨表提问时，按门店条件取同门店的店家级行（R0/C12）。

    物品条件（``entity_filters["item"]`` 等值）只能命中带物品列的行，而联系人/合作状态
    等值只登记在店家信息行上；两边同时被问到时，店家行不会出现在物品条件的命中集里。
    这里只做**额外取数**：按同一 ``store`` 条件取店家记录行（``entity_type == "store"``），
    是否真的纳入仍由调用方按候选上界与分组唯一性决定；本函数不改变过滤/排序口径。

    触发条件全部来自本轮意图本身（无题号、无固定门店/物品）：
    - 实体过滤里同时有物品条件与门店条件；
    - 请求同时包含物品字段和店家字段，或明确只请求对接人。
      两种问法都需要唯一的同店物品组才能挂载店家行。
    """
    filters = dict(intent.entity_filters or {})
    if not ("item" in filters or "item_id" in filters):
        return set()
    store_value = filters.get("store")
    if not store_value:
        return set()
    requested_roles = _requested_roles(intent.requested_fields)
    if not requested_roles & _STORE_LEVEL_FIELD_ROLES:
        return set()
    if intent.requested_fields != ("联系人",) and not requested_roles & _ITEM_LEVEL_FIELD_ROLES:
        return set()
    store_ids = _filter_ids(db, {"store": store_value})
    if not store_ids:
        return set()
    return set(
        db.scalars(
            select(RetrievalUnitIndex.unit_id)
            .join(SourceUnit, SourceUnit.id == RetrievalUnitIndex.unit_id)
            .where(
                RetrievalUnitIndex.unit_id.in_(store_ids),
                RetrievalUnitIndex.entity_type == "store",
                RetrievalUnitIndex.version_id == SourceUnit.version_id,
                RetrievalUnitIndex.document_id == SourceUnit.document_id,
            )
        ).all()
    )


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


def _attach_store_rows(groups: dict, store_ids: set) -> dict:
    """把本次额外取到的店家级行挂到唯一的物品目标组上（R0/C12）。

    只有目标唯一（恰好一个物品实体组）、且店家行的门店值与目标门店一致时才挂载；
    否则丢弃本次并入的店家行、保持既有口径——多目标本来就按"歧义"收口，不能靠挂载
    顺序把不同目标并成一个。挂载只是给同一实体组**增加来源行**：不新建候选、不改
    候选标签/筛选条件、不改排序与 limit 口径。
    """
    store_keys = [
        key
        for key, members in groups.items()
        if members and all(unit.id in store_ids for unit, _mapping in members)
    ]
    if not store_keys:
        return groups
    kept = {key: members for key, members in groups.items() if key not in store_keys}
    item_keys = [key for key in kept if kept[key][0][1].entity_type == "item"]
    if len(item_keys) != 1:
        return kept
    host = item_keys[0]
    host_store = normalize_value((kept[host][0][1].entity_filters or {}).get("store") or "")
    store_values = {
        normalize_value((groups[key][0][1].entity_filters or {}).get("store") or "")
        for key in store_keys
    }
    if not host_store or store_values != {host_store}:
        return kept
    merged = {key: list(members) for key, members in kept.items()}
    for key in sorted(store_keys):
        merged[host].extend(groups[key])
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


def _units_with_field_labels(db: Session, unit_ids: list, labels: Iterable[str]) -> set:
    """返回"表头逐字命中本次请求字段名"的单元 ID 集合（不看角色是否登记）。

    ``HEADER_ROLES`` 只登记了门店/物品/位置/联系人等少数表头；"盘点时间""数量""价格"
    这类请求字段解析不到角色。角色裁剪若把它们当成"与本次提问无关"，只剩这类字段的
    记录行会被整行裁掉，承载期望值的来源既不进证据面也不被引用（R0/C12）。
    这里只做**并集补充**：请求字段名在表头里逐字出现的行保留，不改变原有裁剪口径。
    """
    wanted = {normalize_value(str(label)) for label in labels if str(label or "").strip()}
    if not unit_ids or not wanted:
        return set()
    rows = db.execute(
        select(RetrievalFieldIndex.unit_id, RetrievalFieldIndex.field_name).where(
            RetrievalFieldIndex.unit_id.in_(unit_ids)
        )
    ).all()
    return {unit_id for unit_id, name in rows if normalize_value(str(name)) in wanted}


def _group_host_mapping(rows: list, key: str):
    """候选身份取本组的"主记录行"（R0/C12）。

    跨表并集会把店家行并入物品目标组；候选的标签/筛选条件必须仍描述物品目标，
    不能因为店家行在文档/序号排序里靠前就改写成店家条件。其余分组形态（同实体多行、
    正文通知与表格记录合并）保持既有"取排序后第一行"的口径不变。
    """
    if len(rows) < 2:
        return rows[0][1]
    entity_types = {mapping.entity_type for _unit, mapping in rows}
    if "store" in entity_types and "item" in entity_types:
        return next(
            mapping for _unit, mapping in rows if mapping.entity_type == "item"
        )
    return rows[0][1]


def _retrieve_records(
    db: Session,
    intent: QueryIntent,
    revision: int,
    limit: int,
    candidate_ids: set[str] | None = None,
    as_of: str | None = None,
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
    allowed: set | None = None
    if candidate_ids is not None:
        # S2：rag 内核本轮召回的来源单元是记录型证据的上界；空集就是明确的无候选，
        # 不回退到未受限检索（否则等于绕过 rag 索引）。候选是字符串 ID，这里转成
        # SourceUnit 主键类型（UUID）再求交，避免类型不同导致空集误判。
        allowed = set()
        for item in candidate_ids:
            try:
                allowed.add(uuid.UUID(str(item)))
            except (TypeError, ValueError):
                continue
        ids = allowed if ids is None else ids & allowed

    # R0/C12：「物品 + 店家级字段」跨表提问时，同门店的店家记录行不会被 item 等值
    # 命中，但它是店家级字段的唯一来源。这里只把**同一份候选上界内**的店家行并入
    # 候选集合；分组阶段再挂到唯一的物品目标上（不唯一就整组丢弃，保持既有口径）。
    store_join_ids = _store_join_ids(db, intent)
    if allowed is not None:
        store_join_ids &= allowed
    if store_join_ids:
        ids = (ids or set()) | store_join_ids

    units = _visible_units(db, ids or set())
    # v3-fix-1/B：时间维度过滤（过期/未生效的记录行不进入证据面，召回与排序不变）。
    units = _drop_out_of_window(units, as_of)
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
    if store_join_ids:
        groups = _attach_store_rows(groups, store_join_ids)
        if not groups:
            return EvidenceSet([], "none", 0, revision, [])

    # T09-D2：同一实体下可能带着与本次提问字段无关的记录行（例如盘点通知行只有
    # "盘点时间/地点"，而提问问的是"位置"），它们不能回答本问，也会污染模型证据。
    # 先按"含本次请求字段角色"裁剪；只有当**所有**实体都被裁空时，才回退到原候选，
    # 让上层仍能按"实体存在但该字段未记录"给出缺失说明，而不是误报 not_found。
    if intent.requested_fields:
        requested_roles = {resolve_requested_role(label) for label in intent.requested_fields}
        requested_roles = {role for role in requested_roles if role in HEADER_ROLES}
        if requested_roles:
            allowed_ids = _units_with_roles(db, [unit.id for unit in units], requested_roles)
            # 请求字段名逐字出现在表头里、但角色表未登记的行同样承载本问字段（R0/C12）：
            # 只把这类行补回裁剪集合，不改变“全部请求字段都能解析角色”时的既有口径。
            allowed_ids |= _units_with_field_labels(
                db, [unit.id for unit in units], intent.requested_fields
            )
            filtered = {
                key: [member for member in members if member[0].id in allowed_ids]
                for key, members in groups.items()
            }
            filtered = {key: members for key, members in filtered.items() if members}
            if filtered:
                groups = filtered


    # 只有门店条件、没有物品条件时，门店条件通常指店家记录本身；但不能因为
    # 店家行存在，就把同门店的其它记录行整批丢掉（例如“联系人 + 位置”这类跨行
    # 请求）。仅在请求字段全部落在店家行角色内时收敛到店家行；否则把同门店的
    # 记录行并入店家组，保持“一个门店候选”而不另造歧义候选。
    if ("store" in intent.entity_filters or "store_id" in intent.entity_filters) and not (
        "item" in intent.entity_filters or "item_id" in intent.entity_filters
    ):
        store_keys = [key for key in groups if groups[key][0][1].entity_type == "store"]
        if store_keys:
            requested_roles = {
                resolve_requested_role(label) for label in intent.requested_fields
            }
            if not requested_roles - _STORE_RECORD_ROLES:
                # 旧口径：只问店家级字段时，不把物品/位置行当成候选。
                groups = {key: groups[key] for key in store_keys}
            else:
                by_store: dict[str, str] = {}
                for key in store_keys:
                    mapping = groups[key][0][1]
                    store_value = normalize_value((mapping.entity_filters or {}).get("store") or "")
                    if store_value:
                        by_store.setdefault(store_value, key)
                merged = {key: list(groups[key]) for key in store_keys}
                for key, members in groups.items():
                    if key in merged:
                        continue
                    mapping = members[0][1]
                    store_value = normalize_value((mapping.entity_filters or {}).get("store") or "")
                    host = by_store.get(store_value)
                    if host is None:
                        # 不属于已命中的门店：沿用旧口径收敛，避免越界候选。
                        continue
                    merged[host].extend(members)
                groups = merged

    total = len(groups)
    ordered_keys = sorted(groups, key=lambda key: (groups[key][0][1].label or "", key))
    selected_keys = ordered_keys[:limit]
    candidates = []
    for key in selected_keys:
        rows = sorted(groups[key], key=lambda item: (item[0].document_id, item[0].ordinal))
        host = _group_host_mapping(rows, key)
        candidates.append(
            Candidate(
                label=host.label or key,
                entity_filters=dict(host.entity_filters or {}),
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


def _retrieve_documents(
    db: Session,
    intent: QueryIntent,
    revision: int,
    limit: int,
    as_of: str | None = None,
) -> EvidenceSet:
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
    # v3-fix-1/B：正文证据同样只按时间维度过滤（没有日期列的正文单元不受影响）。
    units = _drop_out_of_window(units, as_of)
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
    as_of: str | None = None,
) -> EvidenceSet:
    """按当前 revision 在一致短读快照内检索有效资料。

    结果只能是请求 revision 下的完整旧快照，或明确的 KnowledgeRevisionChanged；
    不会把查询中途的发布/删除混合成“旧 revision + 新事实/假 none”。

    ``as_of`` 非空时只按时间维度裁剪证据单元（行自带的生效/失效窗口）；召回渠道、
    分组与排序不变。为空时与既有行为逐值相同。
    """
    intent = normalize_intent(intent)
    limit = validate_limit(limit)
    as_of = _as_of_bound(as_of)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise QueryRejected("revision 必须是非负整数")
    with _read_snapshot(db) as snapshot:
        current = _read_revision(snapshot)
        if int(revision) != current:
            raise KnowledgeRevisionChanged("知识库版本已变化，请重新查询")
        _ensure_indexes_ready(snapshot)
        if intent.mode == "record":
            return _retrieve_records(
                snapshot, intent, current, limit, candidate_ids, as_of=as_of
            )
        return _retrieve_documents(snapshot, intent, current, limit, as_of=as_of)
