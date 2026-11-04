"""T04 生命周期服务：原子发布、取消、逻辑删除、revision 与有效来源基础过滤。

事务边界：
- 写操作先在短事务内用 ``BEGIN IMMEDIATE`` 取得 SQLite 写锁，再做校验与写入；
  竞争写者只能在提交后重新读取，因此“读取 revision 再覆盖”的竞态不会发生；
- revision 另有条件 UPDATE（CAS）作第二道证明，行数不为 1 即冲突；
- 失败/异常一律 rollback，不留下半套 revision、状态、计数或幂等凭据；
- 不执行文件读取、解析或外部调用；原件与旧 SourceUnit 由状态过滤撤销访问，不做不可逆清理。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..errors import (
    ApiError,
    ContentUnavailable,
    DeleteConflict,
    DocumentNotFound,
    JobStateConflict,
    PublishConflict,
    VersionNotCancellable,
    VersionNotPublishable,
    VersionNotFound,
)
from ..ingestion.models import ImportJob
from ..retrieval.index import (
    build_index_plan,
    index_rows_present,
    prepare_version_index,
    read_status,
    verify_version_index,
)
from .models import (
    DeletionReceipt,
    Document,
    DocumentVersion,
    KnowledgeState,
    PublicationReceipt,
    SourceUnit,
    utcnow,
)
from .schemas import Deletion, Publication

PROCESSABLE_VERSION_STATES = ("queued", "processing")
CANCELLABLE_VERSION_STATES = ("queued", "processing", "review_required", "failed")
WRITE_RETRIES = 5
WRITE_RETRY_SLEEP = 0.05


# ---------------------------------------------------------------- revision 与有效过滤基础


def get_revision(db: Session) -> int:
    """读取持久化的全库 revision；单例行缺失时按迁移约定初始化为 0 并持久保存。"""
    state = db.get(KnowledgeState, 1)
    if state is not None:
        return int(state.revision)
    state = KnowledgeState(
        id=1, revision=0, active_document_count=0, active_excel_row_count=0, updated_at=utcnow()
    )
    db.add(state)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return int(db.get(KnowledgeState, 1).revision)


def visible_source_units_stmt():
    """当前可用的来源单元查询（不执行/不提交）：同时校验文档与版本双重归属。

    条件：资料未删除、版本属于该资料、版本就是当前有效版本且状态为 published。
    调用方只能在该 Select 上继续追加条件；旧版本/已取消/已删除资料内的单元不会出现。
    """
    return (
        select(SourceUnit)
        .join(DocumentVersion, SourceUnit.version_id == DocumentVersion.id)
        .join(Document, SourceUnit.document_id == Document.id)
        .where(
            DocumentVersion.document_id == Document.id,
            Document.deleted.is_(False),
            Document.active_version_id == DocumentVersion.id,
            DocumentVersion.state == "published",
        )
    )


# ---------------------------------------------------------------- 写事务基础设施


def _begin_write(db: Session) -> None:
    """结束鉴权读留下的逻辑事务，再以 IMMEDIATE 取得写锁（SQLite 写入串行化）。"""
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def _is_lock_error(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _run_write(db: Session, operation, *, conflict):
    """在 BEGIN IMMEDIATE 短事务中执行 operation；锁竞争有界重试后转稳定冲突错误。"""
    for attempt in range(WRITE_RETRIES):
        try:
            _begin_write(db)
            return operation()
        except OperationalError as exc:
            db.rollback()
            if not _is_lock_error(exc):
                raise
            if attempt == WRITE_RETRIES - 1:
                break
            time.sleep(WRITE_RETRY_SLEEP * (attempt + 1))
        except BaseException:
            db.rollback()
            raise
    raise conflict()


def _knowledge_state(db: Session) -> KnowledgeState:
    state = db.get(KnowledgeState, 1, populate_existing=True)
    if state is None:
        state = KnowledgeState(
            id=1, revision=0, active_document_count=0, active_excel_row_count=0, updated_at=utcnow()
        )
        db.add(state)
        db.flush()
    return state


def _load_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id, populate_existing=True)
    if document is None:
        raise DocumentNotFound()
    return document


def _load_version(db: Session, document: Document, version_id: uuid.UUID) -> DocumentVersion:
    version = db.get(DocumentVersion, version_id, populate_existing=True)
    if version is None or version.document_id != document.id:
        raise VersionNotFound()
    return version


def _excel_row_count(db: Session, version: DocumentVersion | None, file_type: str) -> int:
    """Excel 有效记录行：只统计 xlsx 版本的 table_row；Word 表格与历史版本不计。"""
    if version is None or file_type != "xlsx":
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(SourceUnit)
            .where(SourceUnit.version_id == version.id, SourceUnit.kind == "table_row")
        )
        or 0
    )


def _unit_count(db: Session, version_id: uuid.UUID) -> int:
    return int(
        db.scalar(select(func.count()).select_from(SourceUnit).where(SourceUnit.version_id == version_id)) or 0
    )


def _conflict(code: str, message: str) -> ApiError:
    return JobStateConflict(code, message)


# ---------------------------------------------------------------- 发布


def publish_version(
    db: Session,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    expected_active_version_id: uuid.UUID | None,
    expected_revision: int,
) -> Publication:
    """管理员显式发布：校验处理完整性与前置条件，短事务内切换有效版本并 revision+1。"""
    document = _load_document(db, document_id)
    version = _load_version(db, document, version_id)
    if document.deleted:
        raise ContentUnavailable("资料已删除，不能发布")
    # T05：索引在不可查询的待发布阶段准备；分词/遍历在短写事务之外完成。
    # - 尚无索引状态：准备一次，失败则不进入发布事务；
    # - 已有状态：用真实映射/FTS/字段行核对，不静默补全、不损坏旧有效版。
    index_plan = None
    if version.state == "review_required":
        status = read_status(db, version.id)
        if status is None:
            # marker 丢失但实际索引行仍在：这是损坏，不是正常首次准备；拒绝并等待显式重建。
            if index_rows_present(db, version.id):
                raise VersionNotPublishable()
            prepared = prepare_version_index(db, version.id)
            if not prepared.ready:
                raise VersionNotPublishable()
            # prepare 内部会结束当前事务并重建索引；重新加载发布对象。
            document = _load_document(db, document_id)
            version = _load_version(db, document, version_id)
        index_plan = build_index_plan(db, version)
        if index_plan is None or not verify_version_index(db, version, plan=index_plan):
            raise VersionNotPublishable()
    return _run_write(
        db,
        lambda: _publish_operation(
            db,
            document_id,
            version_id,
            expected_active_version_id,
            expected_revision,
            index_plan=index_plan,
        ),
        conflict=PublishConflict,
    )


def _publish_operation(
    db: Session,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    expected_active_version_id: uuid.UUID | None,
    expected_revision: int,
    *,
    index_plan=None,
) -> Publication:
    state = _knowledge_state(db)
    revision_now = int(state.revision)
    document = _load_document(db, document_id)
    version = _load_version(db, document, version_id)
    if document.deleted:
        raise ContentUnavailable("资料已删除，不能发布")

    if version.state == "published":
        if document.active_version_id == version.id:
            receipt = db.scalar(select(PublicationReceipt).where(PublicationReceipt.version_id == version.id))
            if (
                receipt is not None
                and receipt.expected_active_version_id == expected_active_version_id
                and int(receipt.expected_revision) == expected_revision
                and revision_now == int(receipt.revision)
            ):
                db.commit()
                return Publication(
                    document_id=document.id,
                    active_version_id=version.id,
                    revision=int(receipt.revision),
                    published_at=receipt.published_at,
                )
        raise PublishConflict()
    if version.state == "superseded":
        raise PublishConflict()
    if version.state != "review_required":
        raise VersionNotPublishable()
    if revision_now != expected_revision:
        raise PublishConflict()
    if document.active_version_id != expected_active_version_id:
        raise PublishConflict()

    _ensure_publishable(db, version)
    # T05-R1：发布原子事务内核对真实索引（marker + 映射 + FTS 正文 + 字段行逐项对应）。
    # 计划在写事务外构建；事务内只重读并核对，不在写事务内临时补索引。
    # 不通过则整体回滚，旧有效版、revision、计数与发布凭据保持不变。
    if index_plan is None or not verify_version_index(db, version, plan=index_plan):
        raise VersionNotPublishable()

    old_version: DocumentVersion | None = None
    if document.active_version_id is not None:
        old_version = db.get(DocumentVersion, document.active_version_id, populate_existing=True)
        if (
            old_version is None
            or old_version.document_id != document.id
            or old_version.state != "published"
            or old_version.id == version.id
        ):
            raise PublishConflict()

    moment = utcnow()
    cas = db.execute(
        update(KnowledgeState)
        .where(KnowledgeState.id == 1, KnowledgeState.revision == expected_revision)
        .values(revision=expected_revision + 1, updated_at=moment)
    )
    if cas.rowcount != 1:
        raise PublishConflict()
    if old_version is not None:
        moved = db.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == old_version.id, DocumentVersion.state == "published")
            .values(state="superseded")
        )
        if moved.rowcount != 1:
            raise PublishConflict()
    published = db.execute(
        update(DocumentVersion)
        .where(DocumentVersion.id == version.id, DocumentVersion.state == "review_required")
        .values(state="published", published_at=moment)
    )
    if published.rowcount != 1:
        raise PublishConflict()
    active_condition = (
        Document.active_version_id.is_(None)
        if expected_active_version_id is None
        else Document.active_version_id == expected_active_version_id
    )
    switched = db.execute(
        update(Document)
        .where(Document.id == document.id, Document.deleted.is_(False), active_condition)
        .values(active_version_id=version.id, last_published_at=moment)
    )
    if switched.rowcount != 1:
        raise PublishConflict()

    old_rows = _excel_row_count(db, old_version, document.file_type)
    new_rows = _excel_row_count(db, version, document.file_type)
    state = _knowledge_state(db)
    new_document_count = int(state.active_document_count) + (0 if old_version is not None else 1)
    new_excel_rows = int(state.active_excel_row_count) - old_rows + new_rows
    if new_document_count < 0 or new_excel_rows < 0:
        raise PublishConflict()
    db.execute(
        update(KnowledgeState)
        .where(KnowledgeState.id == 1)
        .values(active_document_count=new_document_count, active_excel_row_count=new_excel_rows)
    )
    db.add(
        PublicationReceipt(
            document_id=document.id,
            version_id=version.id,
            expected_active_version_id=expected_active_version_id,
            expected_revision=expected_revision,
            revision=expected_revision + 1,
            published_at=moment,
            created_at=moment,
        )
    )
    db.commit()
    return Publication(
        document_id=document.id,
        active_version_id=version.id,
        revision=expected_revision + 1,
        published_at=moment,
    )


def _ensure_publishable(db: Session, version: DocumentVersion) -> None:
    """不信任 version.state 或客户端：任务成功、完整性报告、单元与检查点必须相互一致。"""
    job = db.scalar(select(ImportJob).where(ImportJob.version_id == version.id))
    if job is None or job.state != "succeeded":
        raise VersionNotPublishable()
    report = version.processing_report
    if not isinstance(report, dict):
        raise VersionNotPublishable()
    quality = report.get("quality")
    if not isinstance(quality, dict) or quality.get("complete") is not True:
        raise VersionNotPublishable()
    units = _unit_count(db, version.id)
    try:
        reported_units = int(report.get("units", -1))
    except (TypeError, ValueError):
        raise VersionNotPublishable() from None
    if units <= 0 or reported_units != units:
        raise VersionNotPublishable()
    kind = report.get("kind")
    if kind in {"pdf", "png", "jpg", "jpeg"}:
        # T07：按页完整性发布；单元数可以多于页数（正文行/表格行/识别块），
        # 但每一页必须有成功/空白结果，失败页存在时整份不可发布。
        pages = report.get("pages")
        if not isinstance(pages, list) or not pages:
            raise VersionNotPublishable()
        try:
            total_pages = int(report.get("total_pages", -1))
        except (TypeError, ValueError):
            raise VersionNotPublishable() from None
        if total_pages != len(pages) or int(job.total_pages) != total_pages:
            raise VersionNotPublishable()
        if int(job.completed_pages) != total_pages:
            raise VersionNotPublishable()
        if report.get("failed_pages"):
            raise VersionNotPublishable()
        if any(entry.get("status") not in {"success", "blank"} for entry in pages):
            raise VersionNotPublishable()
        return
    if int(job.completed_pages) != units or int(job.total_pages) != units:
        raise VersionNotPublishable()


# ---------------------------------------------------------------- 取消


def cancel_version(db: Session, document_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """取消未生效版本及其尚可继续的任务；不影响旧有效版本、revision 和有效总量。"""
    document = _load_document(db, document_id)
    _load_version(db, document, version_id)
    if document.deleted:
        raise ContentUnavailable("资料已删除，不能取消版本")
    _run_write(
        db,
        lambda: _cancel_operation(db, document_id, version_id),
        conflict=lambda: JobStateConflict("VERSION_STATE_CONFLICT", "版本状态正在变化，请刷新后重试"),
    )


def _cancel_operation(db: Session, document_id: uuid.UUID, version_id: uuid.UUID) -> None:
    document = _load_document(db, document_id)
    version = _load_version(db, document, version_id)
    if document.deleted:
        raise ContentUnavailable("资料已删除，不能取消版本")
    if version.state == "cancelled":
        db.commit()
        return
    if version.state in {"published", "superseded"}:
        raise VersionNotCancellable()
    if version.state not in CANCELLABLE_VERSION_STATES:
        raise VersionNotCancellable()

    moment = utcnow()
    result = db.execute(
        update(DocumentVersion)
        .where(DocumentVersion.id == version.id, DocumentVersion.state.in_(CANCELLABLE_VERSION_STATES))
        .values(state="cancelled")
    )
    if result.rowcount != 1:
        raise _conflict("VERSION_STATE_CONFLICT", "版本状态已变化，请刷新后重试")
    job = db.scalar(select(ImportJob).where(ImportJob.version_id == version.id))
    if job is not None:
        db.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id, ImportJob.state.in_(("queued", "running")))
            .values(
                state="cancelled",
                stage="cancelled",
                retryable=False,
                lease_token=None,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=moment,
                finished_at=moment,
                error_code="VERSION_CANCELLED",
                message="版本已取消，任务已撤销",
            )
        )
        db.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id, ImportJob.state.in_(("failed", "blocked")))
            .values(retryable=False)
        )
    db.commit()


# ---------------------------------------------------------------- 删除


def delete_document(db: Session, document_id: uuid.UUID, *, expected_revision: int) -> Deletion:
    """首次逻辑删除：revision+1、撤销有效版本与访问、取消未完成任务；重复删除返回原结果。"""
    document = db.get(Document, document_id)
    if document is None:
        raise DocumentNotFound()
    if document.deleted:
        return _existing_deletion(db, document_id)
    return _run_write(
        db,
        lambda: _delete_operation(db, document_id, expected_revision),
        conflict=DeleteConflict,
    )


def _existing_deletion(db: Session, document_id: uuid.UUID) -> Deletion:
    receipt = db.get(DeletionReceipt, document_id)
    if receipt is not None:
        return Deletion(document_id=document_id, deleted=True, revision=int(receipt.revision))
    # 缺少凭据的已删除资料（历史异常数据）：保守返回当前 revision，不再递增
    return Deletion(document_id=document_id, deleted=True, revision=get_revision(db))


def _delete_operation(db: Session, document_id: uuid.UUID, expected_revision: int) -> Deletion:
    state = _knowledge_state(db)
    document = _load_document(db, document_id)
    if document.deleted:
        db.rollback()
        return _existing_deletion(db, document_id)
    if int(state.revision) != expected_revision:
        raise DeleteConflict()

    old_version: DocumentVersion | None = None
    if document.active_version_id is not None:
        old_version = db.get(DocumentVersion, document.active_version_id, populate_existing=True)
    old_rows = _excel_row_count(db, old_version, document.file_type)
    had_active = old_version is not None and old_version.state == "published"

    moment = utcnow()
    version_ids = select(DocumentVersion.id).where(DocumentVersion.document_id == document.id)
    db.execute(
        update(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .values(state="deleted")
    )
    db.execute(
        update(ImportJob)
        .where(ImportJob.version_id.in_(version_ids), ImportJob.state.in_(("queued", "running")))
        .values(
            state="cancelled",
            stage="cancelled",
            retryable=False,
            lease_token=None,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=moment,
            finished_at=moment,
            error_code="CONTENT_DELETED",
            message="资料已删除，任务已取消",
        )
    )
    db.execute(
        update(ImportJob)
        .where(ImportJob.version_id.in_(version_ids), ImportJob.state.in_(("failed", "blocked")))
        .values(retryable=False)
    )
    deleted = db.execute(
        update(Document)
        .where(Document.id == document.id, Document.deleted.is_(False))
        .values(deleted=True, active_version_id=None, name_key=None)
    )
    if deleted.rowcount != 1:
        raise DeleteConflict()
    cas = db.execute(
        update(KnowledgeState)
        .where(KnowledgeState.id == 1, KnowledgeState.revision == expected_revision)
        .values(revision=expected_revision + 1, updated_at=moment)
    )
    if cas.rowcount != 1:
        raise DeleteConflict()

    state = _knowledge_state(db)
    new_document_count = int(state.active_document_count) - (1 if had_active else 0)
    new_excel_rows = int(state.active_excel_row_count) - old_rows
    if new_document_count < 0 or new_excel_rows < 0:
        raise DeleteConflict()
    db.execute(
        update(KnowledgeState)
        .where(KnowledgeState.id == 1)
        .values(active_document_count=new_document_count, active_excel_row_count=new_excel_rows)
    )
    db.add(
        DeletionReceipt(
            document_id=document.id,
            expected_revision=expected_revision,
            revision=expected_revision + 1,
            deleted_at=moment,
        )
    )
    db.commit()
    return Deletion(document_id=document.id, deleted=True, revision=expected_revision + 1)
