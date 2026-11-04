"""T05 索引准备、字段角色映射与就绪核对。

职责边界：
- 本模块只做“把已有 SourceUnit 变成可检索索引”和“核对索引是否就绪”，不改变 SourceUnit、
  Document、revision 或有效总量；不读取文件、不调用模型/OCR。
- 分词与单元遍历在写事务之外完成；写事务用 BEGIN IMMEDIATE 保持短小，并在事务内重检
  版本仍可准备、输入摘要未变（取消/删除后的迟到索引不会落库，也不会恢复资料）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..documents.models import Document, DocumentVersion, SourceUnit
from .models import RetrievalFieldIndex, RetrievalUnitIndex, RetrievalVersionIndex
from .tokenize import TOKENIZER_VERSION, index_body, normalize, normalize_value
from .types import IndexStatus

# 受控表头映射：只按已识别表头关系判断，不按 P/S 前缀或取第一行猜业务事实。
HEADER_ROLES: dict[str, tuple[str, ...]] = {
    "store": ("门店", "店家", "店铺", "商户", "门店名称", "店家名称", "店铺名称", "商户名称"),
    "item": ("物品", "物品名称", "物料", "物料名称"),
    "alias": ("别名", "俗称", "别称", "别名/俗称"),
    "location": ("位置", "存放位置", "货架位置", "所在位置", "存放区域"),
    "contact": ("联系人", "联系人姓名", "负责人"),
    "phone": ("电话", "联系电话", "手机号", "手机号码", "联系方式"),
    "address": ("地址", "门店地址", "详细地址", "店家地址"),
    "status": ("合作状态", "状态"),
}
ID_HEADERS: tuple[str, ...] = ("标识", "编号", "id", "ID")

ROLE_LABELS: dict[str, str] = {
    "store": "门店",
    "item": "物品",
    "alias": "别名",
    "location": "位置",
    "contact": "联系人",
    "phone": "电话",
    "address": "地址",
    "status": "合作状态",
    "store_id": "标识",
    "item_id": "标识",
}

PREPARABLE_STATES = ("review_required", "published")


def _clean_name(name: object) -> str:
    return str(name).strip()


def _role_for_name(name: str) -> str | None:
    for role, synonyms in HEADER_ROLES.items():
        if name in synonyms:
            return role
    return None


def _is_id_header(name: str) -> bool:
    return name in ID_HEADERS or name.lower() in ("id", "编号")


def resolve_requested_role(label: str) -> str | None:
    """业务字段标签 -> 字段角色；未知标签返回 None（不当作 SQL 列）。"""
    cleaned = _clean_name(label)
    normalized = normalize(cleaned)
    for role, synonyms in HEADER_ROLES.items():
        if normalized == normalize(role) or cleaned in synonyms or normalized in {normalize(item) for item in synonyms}:
            return role
    if normalized in ("标识", "编号", "id"):
        return "identifier"
    return None


def analyze_fields(
    fields: dict | None, *, document_id=None, unit_id=None
) -> tuple[dict[str, str | None], dict[str, str], str | None, str | None, str | None, dict | None]:
    """分析一条记录的字段：返回 (表头->角色, 角色->原值, 实体类型, 实体键, 标签, 可用筛选条件)。

    实体类型按表头关系判定：同时存在门店与物品列 => 物品/位置记录（其“标识”是 item_id）；
    只有门店列（电话/联系人/地址/合作状态等）=> 店家记录（其“标识”是 store_id）。

    实体键：有明确标识时跨资料按标识合并（可判定同一实体，才允许冲突比较）；没有标识时
    不跨行/跨资料拼字段，键包含资料与单元身份，只会成为独立候选（歧义），不按上传顺序选真。
    """
    role_by_name: dict[str, str | None] = {}
    role_values: dict[str, str] = {}
    id_name: str | None = None
    id_value: str | None = None
    for name, value in (fields or {}).items():
        cleaned = _clean_name(name)
        role = _role_for_name(cleaned)
        role_by_name[cleaned] = role
        if _is_id_header(cleaned):
            id_name = cleaned if id_name is None else id_name
            if id_value is None and value not in (None, ""):
                id_value = str(value).strip()
        if role and value not in (None, ""):
            role_values.setdefault(role, str(value).strip())

    store = role_values.get("store")
    item = role_values.get("item")
    if item:
        entity_type = "item"
        name_key = f"item|{normalize_value(store)}|{normalize_value(item)}"
        label = f"{store}的{item}" if store else item
    elif store:
        entity_type = "store"
        name_key = f"store|{normalize_value(store)}"
        label = store
    else:
        return role_by_name, role_values, None, None, None, None

    if id_name is not None and id_value:
        entity_key = f"{entity_type}|id:{normalize_value(id_value)}"
    else:
        entity_key = f"{name_key}|doc:{document_id}|unit:{unit_id}"

    entity_filters: dict[str, str] = {}
    if store:
        entity_filters["store"] = store
    if item:
        entity_filters["item"] = item
    if id_name is not None and id_value:
        id_role = "item_id" if entity_type == "item" else "store_id"
        role_by_name[id_name] = id_role
        entity_filters[id_role] = id_value
    return role_by_name, role_values, entity_type, entity_key, label, entity_filters


def version_input_digest(version: DocumentVersion, units: list[SourceUnit]) -> str:
    """索引输入摘要：版本字节 SHA + 有序单元（ordinal/unit_key/kind/text/fields/sheet）。

    发布事务内用同一算法重算；不一致说明索引不是当前输入的产物，拒绝发布。
    """
    payload = {
        "sha256": version.sha256,
        "units": [
            [unit.ordinal, unit.unit_key, unit.kind, unit.text, unit.fields, unit.sheet] for unit in units
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_units(db: Session, version_id: uuid.UUID) -> list[SourceUnit]:
    return list(
        db.scalars(
            select(SourceUnit).where(SourceUnit.version_id == version_id).order_by(SourceUnit.ordinal)
        ).all()
    )


@dataclass(frozen=True)
class _FieldPlan:
    """一条应有字段索引行的完整期望值；用于和实际行做多重集比较。"""

    unit_id: uuid.UUID
    version_id: uuid.UUID
    document_id: uuid.UUID
    field_name: str
    field_role: str | None
    norm_value: str
    value_text: str


@dataclass(frozen=True)
class _UnitPlan:
    unit_id: uuid.UUID
    version_id: uuid.UUID
    document_id: uuid.UUID
    ordinal: int
    body: str
    entity_type: str | None
    entity_key: str | None
    label: str | None
    entity_filters: dict | None
    token_count: int
    fields: tuple[_FieldPlan, ...]


@dataclass(frozen=True)
class _IndexPlan:
    """在写事务之外算好的核验计划：真实来源、应有字段行、FTS 正文与输入摘要。"""

    version_id: uuid.UUID
    document_id: uuid.UUID
    input_digest: str
    units: tuple[_UnitPlan, ...]


def _build_plan(version: DocumentVersion, units: list[SourceUnit]) -> _IndexPlan:
    unit_plans: list[_UnitPlan] = []
    for unit in units:
        body = index_body(unit.text)
        role_by_name, _values, entity_type, entity_key, label, filters = analyze_fields(
            unit.fields, document_id=unit.document_id, unit_id=unit.id
        )
        field_plans: list[_FieldPlan] = []
        for name, value in (unit.fields or {}).items():
            if value in (None, ""):
                continue
            value_text = str(value)
            cleaned = _clean_name(name)
            field_plans.append(
                _FieldPlan(
                    unit_id=unit.id,
                    version_id=version.id,
                    document_id=version.document_id,
                    field_name=cleaned[:128],
                    field_role=role_by_name.get(cleaned),
                    norm_value=normalize_value(value_text)[:512],
                    value_text=value_text,
                )
            )
        unit_plans.append(
            _UnitPlan(
                unit_id=unit.id,
                version_id=version.id,
                document_id=version.document_id,
                ordinal=unit.ordinal,
                body=body,
                entity_type=entity_type,
                entity_key=entity_key,
                label=label,
                entity_filters=filters,
                token_count=len(body.split()) if body else 0,
                fields=tuple(field_plans),
            )
        )
    return _IndexPlan(
        version_id=version.id,
        document_id=version.document_id,
        input_digest=version_input_digest(version, units),
        units=tuple(unit_plans),
    )


def build_index_plan(db: Session, version: DocumentVersion | uuid.UUID) -> _IndexPlan | None:
    """构建核验计划；分词/遍历发生在调用方写事务之外。版本不存在时返回 None。"""
    if isinstance(version, uuid.UUID):
        version = db.get(DocumentVersion, version, populate_existing=True)
    else:
        version = db.get(DocumentVersion, version.id, populate_existing=True)
    if version is None:
        return None
    return _build_plan(version, _load_units(db, version.id))


def _verify_plan(db: Session, version: DocumentVersion, plan: _IndexPlan) -> bool:
    """核对 marker、真实来源、单元映射、FTS 正文与字段索引的一一对应。

    只使用当前事务内可见的行；缺行、额外行、错归属、同数量错内容都会返回 False。
    """
    if plan.version_id != version.id or plan.document_id != version.document_id:
        return False
    marker = db.execute(
        select(RetrievalVersionIndex)
        .where(RetrievalVersionIndex.version_id == version.id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if marker is None or not bool(marker.ready):
        return False
    if marker.document_id != version.document_id:
        return False
    if marker.tokenizer_version != TOKENIZER_VERSION:
        return False
    if int(marker.unit_count) != len(plan.units):
        return False
    if marker.input_digest != plan.input_digest:
        return False

    units = _load_units(db, version.id)
    if len(units) != len(plan.units):
        return False
    expected_ids = {plan_unit.unit_id for plan_unit in plan.units}
    actual_by_id = {unit.id: unit for unit in units}
    if set(actual_by_id) != expected_ids:
        return False
    if version_input_digest(version, units) != plan.input_digest:
        return False
    for plan_unit in plan.units:
        unit = actual_by_id[plan_unit.unit_id]
        if unit.version_id != version.id or unit.document_id != version.document_id:
            return False
        if unit.ordinal != plan_unit.ordinal:
            return False

    unit_ids = list(expected_ids)
    mappings = list(
        db.scalars(
            select(RetrievalUnitIndex).where(
                or_(
                    RetrievalUnitIndex.unit_id.in_(unit_ids),
                    RetrievalUnitIndex.version_id == version.id,
                )
            )
        ).all()
    )
    if len(mappings) != len(plan.units):
        return False
    mapping_by_unit: dict[uuid.UUID, RetrievalUnitIndex] = {}
    for row in mappings:
        if row.unit_id in mapping_by_unit:
            return False
        mapping_by_unit[row.unit_id] = row
    if set(mapping_by_unit) != expected_ids:
        return False

    for plan_unit in plan.units:
        row = mapping_by_unit[plan_unit.unit_id]
        if row.version_id != version.id or row.document_id != version.document_id:
            return False
        if row.entity_type != plan_unit.entity_type:
            return False
        if row.entity_key != plan_unit.entity_key:
            return False
        if row.label != plan_unit.label:
            return False
        if (row.entity_filters or None) != (plan_unit.entity_filters or None):
            return False
        if int(row.token_count) != plan_unit.token_count:
            return False

    rowids = [mapping_by_unit[plan_unit.unit_id].fts_rowid for plan_unit in plan.units]
    fts_rows = db.execute(
        text("SELECT rowid, body FROM source_unit_fts WHERE version_id = :version"),
        {"version": str(version.id)},
    ).all()
    if len(fts_rows) != len(rowids):
        return False
    bodies: dict[int, str] = {}
    for rowid, body in fts_rows:
        key = int(rowid)
        if key in bodies:
            return False
        bodies[key] = body
    if set(bodies) != set(rowids):
        return False
    for plan_unit in plan.units:
        row = mapping_by_unit[plan_unit.unit_id]
        if bodies[int(row.fts_rowid)] != plan_unit.body:
            return False

    field_rows = list(
        db.scalars(
            select(RetrievalFieldIndex).where(
                or_(
                    RetrievalFieldIndex.unit_id.in_(unit_ids),
                    RetrievalFieldIndex.version_id == version.id,
                )
            )
        ).all()
    )
    expected_fields = [
        (
            field.unit_id,
            field.version_id,
            field.document_id,
            field.field_name,
            field.field_role,
            field.norm_value,
            field.value_text,
        )
        for plan_unit in plan.units
        for field in plan_unit.fields
    ]
    actual_fields = [
        (
            row.unit_id,
            row.version_id,
            row.document_id,
            row.field_name,
            row.field_role,
            row.norm_value,
            row.value_text,
        )
        for row in field_rows
    ]
    return Counter(expected_fields) == Counter(actual_fields)


def verify_version_index(
    db: Session, version: DocumentVersion, *, plan: _IndexPlan | None = None
) -> bool:
    """真实索引完整性判定；FTS 结构缺失/故障按未就绪处理，不伪装 none。"""
    if plan is None:
        plan = build_index_plan(db, version)
    if plan is None:
        return False
    try:
        return _verify_plan(db, version, plan)
    except OperationalError:
        return False



def _clear_version_rows(db: Session, version_id: uuid.UUID) -> None:
    rowids = list(
        db.scalars(select(RetrievalUnitIndex.fts_rowid).where(RetrievalUnitIndex.version_id == version_id)).all()
    )
    if rowids:
        statement = text("DELETE FROM source_unit_fts WHERE rowid IN :rowids").bindparams(
            bindparam("rowids", expanding=True)
        )
        db.execute(statement, {"rowids": rowids})
    # 即使映射行已损坏/缺失，FTS 行上的 version_id 归属仍能定位并清理本版本残留。
    db.execute(
        text("DELETE FROM source_unit_fts WHERE version_id = :version"),
        {"version": str(version_id)},
    )
    db.execute(delete(RetrievalFieldIndex).where(RetrievalFieldIndex.version_id == version_id))
    db.execute(delete(RetrievalUnitIndex).where(RetrievalUnitIndex.version_id == version_id))
    db.execute(delete(RetrievalVersionIndex).where(RetrievalVersionIndex.version_id == version_id))


def prepare_version_index(db: Session, version_id: uuid.UUID) -> IndexStatus:
    """为单个版本准备索引；可重复执行，不重复单元或 FTS 行。

    完成判定不再只看 marker：写入后在同一事务内用 ``_verify_plan`` 核对真实来源、单元映射、
    FTS 正文与字段索引；任何缺行/额外行/错归属/内容不符都回滚并返回 ready=False。
    取消/删除后的迟到准备不会写入任何索引行。
    """
    version = db.get(DocumentVersion, version_id)
    if version is None:
        return IndexStatus(version_id, False, reason="version_not_found")
    document = db.get(Document, version.document_id)
    if document is None or document.deleted or version.state not in PREPARABLE_STATES:
        return IndexStatus(version_id, False, reason="version_not_preparable")

    snapshot_sha = version.sha256
    plan = _build_plan(version, _load_units(db, version_id))

    db.rollback()
    moment = datetime.now().astimezone()
    try:
        db.execute(text("BEGIN IMMEDIATE"))
        version = db.get(DocumentVersion, version_id, populate_existing=True)
        document = db.get(Document, version.document_id, populate_existing=True) if version is not None else None
        if (
            version is None
            or document is None
            or document.deleted
            or version.state not in PREPARABLE_STATES
            or version.sha256 != snapshot_sha
        ):
            db.rollback()
            return IndexStatus(version_id, False, reason="version_not_preparable")
        if version_input_digest(version, _load_units(db, version_id)) != plan.input_digest:
            db.rollback()
            return IndexStatus(version_id, False, reason="source_changed")

        _clear_version_rows(db, version_id)
        # 其他版本的 FTS-only 残留不能被全库扫描/清理；本版本重建时显式选择高于现有
        # FTS 与映射的最大 rowid，避免复用 rowid 与无关残留冲突。
        max_fts_rowid = int(db.scalar(text("SELECT COALESCE(MAX(rowid), 0) FROM source_unit_fts")) or 0)
        max_mapping_rowid = int(
            db.scalar(text("SELECT COALESCE(MAX(fts_rowid), 0) FROM retrieval_unit_index")) or 0
        )
        next_rowid = max(max_fts_rowid, max_mapping_rowid) + 1
        for unit_plan in plan.units:
            row = RetrievalUnitIndex(
                fts_rowid=next_rowid,
                unit_id=unit_plan.unit_id,
                version_id=version_id,
                document_id=version.document_id,
                entity_type=unit_plan.entity_type,
                entity_key=unit_plan.entity_key,
                label=unit_plan.label,
                entity_filters=unit_plan.entity_filters,
                token_count=unit_plan.token_count,
            )
            next_rowid += 1
            db.add(row)
            db.flush()
            db.execute(
                text("INSERT INTO source_unit_fts(rowid, body, version_id) VALUES (:rowid, :body, :version_id)"),
                {"rowid": row.fts_rowid, "body": unit_plan.body, "version_id": str(version_id)},
            )
            for field in unit_plan.fields:
                db.add(
                    RetrievalFieldIndex(
                        unit_id=field.unit_id,
                        version_id=field.version_id,
                        document_id=field.document_id,
                        field_name=field.field_name,
                        field_role=field.field_role,
                        norm_value=field.norm_value,
                        value_text=field.value_text,
                    )
                )
        db.add(
            RetrievalVersionIndex(
                version_id=version_id,
                document_id=version.document_id,
                unit_count=len(plan.units),
                input_digest=plan.input_digest,
                tokenizer_version=TOKENIZER_VERSION,
                ready=True,
                prepared_at=moment,
                updated_at=moment,
            )
        )
        db.flush()
        if not _verify_plan(db, version, plan):
            db.rollback()
            return IndexStatus(version_id, False, reason="index_incomplete")
        db.commit()
    except OperationalError:
        # 索引存储不可用（例如 FTS5 表缺失/损坏）时不得伪装就绪；由调用方按未就绪处理。
        db.rollback()
        return IndexStatus(version_id, False, reason="index_storage_error")
    except IntegrityError:
        # 复合归属约束拒绝不一致的 unit/version/document 组合；不静默修复。
        db.rollback()
        return IndexStatus(version_id, False, reason="ownership_conflict")
    except BaseException:
        db.rollback()
        raise
    return IndexStatus(
        version_id,
        True,
        unit_count=len(plan.units),
        input_digest=plan.input_digest,
        tokenizer_version=TOKENIZER_VERSION,
        prepared_at=moment,
    )


def backfill_published_indexes(db: Session) -> list[IndexStatus]:
    """为所有“资料未删除 + 当前有效版本 published”的版本准备索引；重复调用幂等。"""
    version_ids = list(
        db.scalars(
            select(DocumentVersion.id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                Document.deleted.is_(False),
                Document.active_version_id == DocumentVersion.id,
                DocumentVersion.state == "published",
            )
            .order_by(DocumentVersion.id)
        ).all()
    )
    return [prepare_version_index(db, version_id) for version_id in version_ids]


def read_status(db: Session, version_id: uuid.UUID) -> IndexStatus | None:
    row = db.get(RetrievalVersionIndex, version_id)
    if row is None:
        return None
    return IndexStatus(
        version_id=row.version_id,
        ready=bool(row.ready),
        unit_count=int(row.unit_count),
        input_digest=row.input_digest,
        tokenizer_version=row.tokenizer_version,
        prepared_at=row.prepared_at,
    )


def index_rows_present(db: Session, version_id: uuid.UUID) -> bool:
    """版本是否残留任何实际索引行（用于区分“正常首次准备”和“marker 丢失的损坏”）。"""
    mapping = db.scalar(
        select(RetrievalUnitIndex.fts_rowid).where(RetrievalUnitIndex.version_id == version_id).limit(1)
    )
    if mapping is not None:
        return True
    field = db.scalar(
        select(RetrievalFieldIndex.id).where(RetrievalFieldIndex.version_id == version_id).limit(1)
    )
    if field is not None:
        return True
    try:
        fts = db.scalar(
            text("SELECT rowid FROM source_unit_fts WHERE version_id = :version LIMIT 1"),
            {"version": str(version_id)},
        )
    except OperationalError:
        # FTS 结构缺失/故障不能被当成“空表”而进入首次准备；按已有残留/不可发布处理。
        return True
    return fts is not None


def version_index_ready(db: Session, version: DocumentVersion, *, verify_digest: bool = True) -> bool:
    """兼容入口：实际完整性永远核对，不只信 ready marker/单元计数/输入摘要。

    ``verify_digest`` 仅为保留既有调用签名；无论取值都执行同一真实行核对。
    """
    return verify_version_index(db, version)


def indexed_unit_count(db: Session, version_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(RetrievalUnitIndex).where(RetrievalUnitIndex.version_id == version_id)
        )
        or 0
    )
