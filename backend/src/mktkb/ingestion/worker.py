"""T03 单次 worker：领取租约、解析、检查点、恢复与失败重试。

- 单并发：凭数据库租约领取，默认 120 秒、运行中每 30 秒续期；旧租约不能提交结果。
- 解析在写事务之外；领取、单元检查点与最终状态提交均为短事务。
- 检查点按 version + 稳定单元键保存，重试/恢复复用已保存单元，不重复写。
- 只把处理成功的版本置为 review_required；本步从不发布、不切换有效版本、不递增 revision。
- 入口可单次执行（`python -m mktkb.ingestion.worker`），不启动常驻后台服务。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..db import Database
from ..documents.models import Document, DocumentVersion, SourceUnit, as_utc, utcnow
from ..documents.service import Store, UploadLimits
from ..errors import (
    ContentUnavailable,
    DuplicateContent,
    JobNotFound,
    JobStateConflict,
)
from ..providers.types import (
    OCRError,
    OCRInput,
    OCRMode,
    OCRPageResult,
    OCRQuotaUnavailable,
    OCRUnavailable,
    make_ocr_source_scope,
)
from .models import ImportJob, OCRCallRecord
from .parsers import parse_document, parse_docx, parse_image, parse_pdf, parse_xlsx
from .parsers.types import (
    ParseAborted,
    ParseError,
    ParseLimitError,
    ParsedUnit,
    ParseQuotaExceeded,
    ParseServices,
)

logger = logging.getLogger("mktkb.worker")

LOCAL_LEASE_SECONDS = 120
LOCAL_RENEW_SECONDS = 30
# 每批单元提交一次检查点：兼顾恢复成本与短事务；测试可配合 max_units 观察中间状态
CHECKPOINT_BATCH_UNITS = 50
CLAIM_MAX_ATTEMPTS = 5
DEFAULT_PARSERS: Mapping[str, Callable] = {
    "xlsx": parse_xlsx,
    "docx": parse_docx,
    "pdf": parse_pdf,
    "png": parse_image,
    "jpg": parse_image,
    "jpeg": parse_image,
}

PROCESSABLE_VERSION_STATES = ("queued", "processing")


@dataclass
class JobLease:
    job_id: uuid.UUID
    version_id: uuid.UUID
    token: str
    claimed_at: datetime
    expires_at: datetime
    owner: str | None = None


@dataclass
class JobRunResult:
    job_id: uuid.UUID | None
    state: str
    units_written: int = 0
    units_reused: int = 0
    error_code: str | None = None
    message: str | None = None
    total_pages: int = 0


class _LeaseLost(Exception):
    """租约在提交前失效：调用方必须丢弃本次结果，不写最终状态。"""


class OcrRateLimiter:
    """单 worker 的有界调用频率：默认不超过 2 次/秒；时钟/睡眠可注入测试。"""

    def __init__(
        self,
        *,
        max_per_second: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        self._interval = 1.0 / min(float(max_per_second), 2.0)
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self.calls = 0
        self.total_wait_seconds = 0.0

    def acquire(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self._interval - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
                self.total_wait_seconds += wait
        self._last = now
        self.calls += 1


def _bbox_key(bbox: tuple[float, float, float, float] | None) -> str:
    if bbox is None:
        return "-"
    return ",".join(f"{float(value):.3f}" for value in bbox)


def _result_to_json(result: OCRPageResult) -> dict:
    return {
        "text": result.text,
        "table_rows": [list(row) for row in result.table_rows],
        "regions": [dict(region) for region in result.regions],
        "provider_request_id": result.provider_request_id,
        "confidence": result.confidence,
    }


def _result_from_json(data: dict | None) -> OCRPageResult | None:
    if not isinstance(data, dict):
        return None
    try:
        rows = data.get("table_rows") or []
        regions = data.get("regions") or []
        return OCRPageResult(
            text=str(data.get("text") or ""),
            table_rows=tuple(tuple(row) for row in rows),
            regions=tuple(dict(region) for region in regions),
            provider_request_id=data.get("provider_request_id"),
            confidence=data.get("confidence"),
        )
    except (TypeError, ValueError):
        return None


class OcrExecutor:
    """包装 OCR 网关：成功检查点复用、单 worker 限流、429 有界退避与尝试记录。

    成功结果按 (version, page, mode, bbox, image_sha256) 持久化；重试同一页/模式/块
    时直接复用，不重复请求。调用前后都执行 ensure_live（任务/资料/版本/租约），
    限流等待结束与尝试记录写入后、实际请求发出前也重新核对。
    发送成功但本地落盘前崩溃的窗口无法完全消除，报告按“可能重复调用”陈述。

    S2-K-R1A：每次实际 OCR 请求都用本 worker 实际持有的 document/version 生成可信来源锚
    （覆盖调用方 OCRInput 里可能伪造的 source_scope），使网关按 (来源锚, 真实页号) 而不是
    全项目页号计 tile；检查点键仍为 version+page+mode+bbox+image_sha，含义不变。
    """

    def __init__(
        self,
        db: Session,
        *,
        version_id: uuid.UUID,
        document_id: uuid.UUID,
        gateway,
        ensure_live: Callable[[], None],
        limiter: OcrRateLimiter | None = None,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
        retry_max_single_seconds: float = 1.0,
        retry_total_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._db = db
        self._version_id = version_id
        self._document_id = document_id
        # 可信来源锚：只由服务端数据库持有的 document/version 生成；解析器/上传文件名无权决定。
        self._source_scope = make_ocr_source_scope(document_id, version_id)
        self._gateway = gateway
        self._ensure_live = ensure_live
        self._limiter = limiter or OcrRateLimiter()
        self._max_attempts = max(1, int(max_attempts))
        self._retry_base = max(0.0, float(retry_base_seconds))
        self._retry_max_single = max(0.0, float(retry_max_single_seconds))
        self._retry_total = max(0.0, float(retry_total_seconds))
        self._sleep = sleep

    def recognize(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult:
        self._ensure_live()
        if isinstance(page, OCRInput):
            # 无条件覆盖调用方提供的来源锚：本 worker 的 document/version 才是可信身份。
            # 检查点查询仍按 version/page/mode/bbox/image_sha，不因来源锚改变复用语义。
            page = replace(page, source_scope=self._source_scope)
        image_sha = hashlib.sha256(page.content).hexdigest()
        bbox_key = _bbox_key(page.bbox)
        cached = self._load_success(page, mode, bbox_key, image_sha)
        if cached is not None:
            return cached

        attempts = 0
        waited = 0.0
        while True:
            attempts += 1
            self._ensure_live()
            self._limiter.acquire()
            # 限流等待结束后、写入尝试记录与实际请求发出前必须重新核对：
            # 等待期间可能发生取消、删除或租约到期，此时不得再发下一页/重试请求。
            self._ensure_live()
            record_id = self._insert_attempt(
                page,
                mode=mode,
                bbox_key=bbox_key,
                image_sha=image_sha,
                attempt=attempts,
            )
            try:
                # 尝试记录写入（含提交）也可能阻塞；实际发送前再核对一次有效性，
                # 已创建的审计行在此情形明确终结为 discarded，不留下无终态记录。
                self._ensure_live()
            except ParseAborted:
                self._finish(record_id, state="discarded", error_code="REQUEST_CANCELLED")
                raise
            try:
                result = self._gateway.recognize(page, mode=mode)
            except ParseAborted:
                self._finish(record_id, state="discarded", error_code="REQUEST_CANCELLED")
                raise
            except OCRError as exc:
                self._finish(
                    record_id,
                    state="failed",
                    error_code=exc.code,
                    provider_request_id=exc.provider_request_id,
                )
                if (
                    exc.code != "OCR_RATE_LIMITED"
                    or not exc.retryable
                    or attempts >= self._max_attempts
                ):
                    raise
                wait = min(self._retry_base * (2 ** (attempts - 1)), self._retry_max_single)
                if waited + wait > self._retry_total:
                    raise
                self._sleep(wait)
                waited += wait
                continue
            except Exception as exc:
                self._finish(record_id, state="failed", error_code="OCR_INTERNAL")
                raise OCRUnavailable(type(exc).__name__) from exc

            try:
                self._ensure_live()
            except ParseAborted:
                self._finish(record_id, state="discarded", error_code="REQUEST_CANCELLED")
                raise
            saved = self._finish_success(record_id, result)
            return saved if saved is not None else result

    # ---------------------------------------------------------------- 持久化

    def _audit_session(self) -> Session:
        return Session(bind=self._db.get_bind(), expire_on_commit=False, future=True)

    def _load_success(
        self, page: OCRInput, mode: OCRMode, bbox_key: str, image_sha: str
    ) -> OCRPageResult | None:
        with self._audit_session() as audit:
            record = audit.scalar(
                select(OCRCallRecord)
                .where(
                    OCRCallRecord.version_id == self._version_id,
                    OCRCallRecord.document_id == self._document_id,
                    OCRCallRecord.page == page.page,
                    OCRCallRecord.mode == mode,
                    OCRCallRecord.bbox_key == bbox_key,
                    OCRCallRecord.image_sha256 == image_sha,
                    OCRCallRecord.state == "succeeded",
                )
                .order_by(OCRCallRecord.finished_at.desc())
                .limit(1)
            )
            return _result_from_json(record.result) if record is not None else None

    def _insert_attempt(
        self,
        page: OCRInput,
        *,
        mode: OCRMode,
        bbox_key: str,
        image_sha: str,
        attempt: int,
    ) -> uuid.UUID:
        record = OCRCallRecord(
            document_id=self._document_id,
            version_id=self._version_id,
            page=page.page,
            mode=mode,
            bbox_key=bbox_key,
            bbox=list(page.bbox) if page.bbox is not None else None,
            image_sha256=image_sha,
            image_bytes=len(page.content),
            mime_type=page.mime_type,
            state="pending",
            attempt=attempt,
        )
        with self._audit_session() as audit:
            audit.add(record)
            audit.commit()
            return record.id

    def _finish(
        self,
        record_id: uuid.UUID,
        *,
        state: str,
        error_code: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        with self._audit_session() as audit:
            record = audit.get(OCRCallRecord, record_id)
            if record is None:
                return
            record.state = state
            record.error_code = error_code
            record.provider_request_id = provider_request_id
            record.finished_at = utcnow()
            audit.commit()

    def _finish_success(self, record_id: uuid.UUID, result: OCRPageResult) -> OCRPageResult | None:
        """保存成功检查点；若另一个成功行已存在，返回已持久化结果而不是覆盖。"""
        with self._audit_session() as audit:
            record = audit.get(OCRCallRecord, record_id)
            if record is None:
                return None
            page, mode, bbox_key, image_sha = (
                record.page,
                record.mode,
                record.bbox_key,
                record.image_sha256,
            )
            record.state = "succeeded"
            record.provider_request_id = result.provider_request_id
            record.confidence = result.confidence
            record.result = _result_to_json(result)
            record.finished_at = utcnow()
            try:
                audit.commit()
                return None
            except IntegrityError:
                audit.rollback()
                existing = audit.scalar(
                    select(OCRCallRecord)
                    .where(
                        OCRCallRecord.version_id == self._version_id,
                        OCRCallRecord.document_id == self._document_id,
                        OCRCallRecord.page == page,
                        OCRCallRecord.mode == mode,
                        OCRCallRecord.bbox_key == bbox_key,
                        OCRCallRecord.image_sha256 == image_sha,
                        OCRCallRecord.state == "succeeded",
                    )
                    .order_by(OCRCallRecord.finished_at.desc())
                    .limit(1)
                )
                return _result_from_json(existing.result) if existing is not None else None


def _aware(value: datetime) -> datetime:
    return as_utc(value)


def _naive_utc(value: datetime) -> datetime:
    """SQLite 以无时区的 UTC 墙钟字符串保存时间；比较参数用同样形式。"""
    return _aware(value).astimezone(timezone.utc).replace(tzinfo=None)


def _resolve_clock(now: datetime | None, now_fn: Callable[[], datetime] | None) -> Callable[[], datetime]:
    if now_fn is not None:
        return now_fn
    if now is not None:
        return lambda: now
    return lambda: datetime.now(timezone.utc)


# ---------------------------------------------------------------- 有效性条件（T04）


def _live_version_ids():
    """可继续处理的版本：状态 queued/processing 且资料未删除（同一事务内重检用）。"""
    return (
        select(DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.state.in_(PROCESSABLE_VERSION_STATES), Document.deleted.is_(False))
    )


def _lease_conditions(lease: JobLease, moment: datetime) -> tuple:
    """提交类 UPDATE 的公共条件：任务归属、租约仍有效、版本可处理、资料未删除。"""
    return (
        ImportJob.id == lease.job_id,
        ImportJob.lease_token == lease.token,
        ImportJob.lease_expires_at > _naive_utc(moment),
        ImportJob.state == "running",
        ImportJob.version_id.in_(_live_version_ids()),
    )


def _job_live_state(db: Session, lease: JobLease, moment: datetime) -> str:
    """解析前的只读核对：返回 ok / cancelled / already_finished / lease_lost。

    使用 no_autoflush 避免把本批未提交单元提前 flush 成写事务（否则会长时间持锁）。
    """
    with db.no_autoflush:
        row = db.execute(
            select(
                ImportJob.state,
                ImportJob.lease_token,
                ImportJob.lease_expires_at,
                DocumentVersion.state,
                Document.deleted,
            )
            .select_from(ImportJob)
            .join(DocumentVersion, DocumentVersion.id == ImportJob.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(ImportJob.id == lease.job_id)
        ).first()
    if row is None:
        return "lease_lost"
    job_state, token, expires_at, version_state, deleted = row
    if job_state == "cancelled" or deleted or version_state in {"cancelled", "deleted"}:
        return "cancelled"
    if version_state not in PROCESSABLE_VERSION_STATES:
        return "already_finished"
    if job_state != "running" or token != lease.token or expires_at is None:
        return "lease_lost"
    if _aware(expires_at) <= moment:
        return "lease_lost"
    return "ok"


def _invalid_result(db: Session, lease: JobLease) -> JobRunResult:
    """提交条件失败后的稳定结果：已取消/已删除 → cancelled，其余按租约失效处理。"""
    db.rollback()
    try:
        row = db.execute(
            select(ImportJob.state, DocumentVersion.state, Document.deleted)
            .select_from(ImportJob)
            .join(DocumentVersion, DocumentVersion.id == ImportJob.version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(ImportJob.id == lease.job_id)
        ).first()
    except Exception:  # 只读诊断失败也不得把未提交内容写回
        db.rollback()
        row = None
    if row is not None and (
        row[0] == "cancelled" or row[2] or row[1] in {"cancelled", "deleted"}
    ):
        return JobRunResult(job_id=lease.job_id, state="cancelled")
    return JobRunResult(job_id=lease.job_id, state="lease_lost")


# ---------------------------------------------------------------- 领取租约


def claim_job(
    db: Session,
    *,
    now: datetime | None = None,
    now_fn: Callable[[], datetime] | None = None,
    lease_seconds: int = LOCAL_LEASE_SECONDS,
    owner: str | None = None,
) -> JobLease | None:
    """领取最早的可处理任务；queued 或租约已过期的 running 可领取。"""
    clock = _resolve_clock(now, now_fn)
    moment = _aware(clock())
    naive = _naive_utc(moment)
    expires_at = moment + timedelta(seconds=lease_seconds)

    for _attempt in range(CLAIM_MAX_ATTEMPTS):
        candidate = db.scalar(
            select(ImportJob)
            .where(
                or_(
                    ImportJob.state == "queued",
                    and_(
                        ImportJob.state == "running",
                        or_(ImportJob.lease_expires_at.is_(None), ImportJob.lease_expires_at <= naive),
                    ),
                ),
                ImportJob.version_id.in_(_live_version_ids()),
            )
            .order_by(ImportJob.created_at, ImportJob.id)
            .limit(1)
        )
        if candidate is None:
            return None
        conditions = [ImportJob.id == candidate.id, ImportJob.version_id.in_(_live_version_ids())]
        if candidate.state == "queued":
            conditions.append(ImportJob.state == "queued")
        else:
            conditions.append(ImportJob.state == "running")
            conditions.append(ImportJob.lease_token == candidate.lease_token)
            # 关键：不能只凭 SELECT 结果回收。同一条件 UPDATE 内重新核对“当前仍已过期”，
            # 否则原持有者在 SELECT 与 UPDATE 之间成功续期后，新领取者仍会抢走有效租约。
            conditions.append(
                or_(ImportJob.lease_expires_at.is_(None), ImportJob.lease_expires_at <= naive)
            )
        token = uuid.uuid4().hex
        result = db.execute(
            update(ImportJob).execution_options(synchronize_session=False)
            .where(*conditions)
            .values(
                state="running",
                stage="claimed",
                lease_token=token,
                lease_owner=owner,
                lease_expires_at=expires_at,
                attempts=ImportJob.attempts + 1,
                updated_at=moment,
                error_code=None,
                message=None,
                finished_at=None,
            )
        )
        if result.rowcount == 1:
            db.execute(
                update(DocumentVersion).execution_options(synchronize_session=False)
                .where(DocumentVersion.id == candidate.version_id, DocumentVersion.state == "queued")
                .values(state="processing")
            )
            db.commit()
            # 领取用 SQL 直接更新；清空本会话缓存，避免后续读到旧租约字段
            db.expire_all()
            return JobLease(
                job_id=candidate.id,
                version_id=candidate.version_id,
                token=token,
                claimed_at=moment,
                expires_at=expires_at,
                owner=owner,
            )
        db.rollback()
    return None


# ---------------------------------------------------------------- 单次运行


def _live_or_abort(db: Session, lease: JobLease, clock: Callable[[], datetime]) -> None:
    state = _job_live_state(db, lease, _aware(clock()))
    if state != "ok":
        raise ParseAborted(state)


def run_one_job(
    db: Session,
    store: Store,
    *,
    parsers: Mapping[str, Callable] | None = None,
    now: datetime | None = None,
    now_fn: Callable[[], datetime] | None = None,
    ocr=None,  # T07：OCRGateway；None 时扫描页/图片以 OCR_NOT_CONFIGURED 失败
    ocr_limiter: OcrRateLimiter | None = None,
    ocr_options: Mapping[str, object] | None = None,
    lease: JobLease | None = None,
    lease_seconds: int = LOCAL_LEASE_SECONDS,
    renew_seconds: int = LOCAL_RENEW_SECONDS,
    max_units: int | None = None,
    owner: str | None = None,
) -> JobRunResult:
    """领取（或使用给定租约）并处理一个任务；返回值区分成功/失败/暂停/空闲/租约失效。"""
    clock = _resolve_clock(now, now_fn)
    if lease is None:
        lease = claim_job(db, now=clock(), lease_seconds=lease_seconds, owner=owner)
        if lease is None:
            return JobRunResult(job_id=None, state="idle")

    job = db.get(ImportJob, lease.job_id)
    if job is None:
        return JobRunResult(job_id=None, state="idle")
    version = db.get(DocumentVersion, job.version_id)
    if version is None:
        return JobRunResult(job_id=job.id, state="lease_lost")
    document = db.get(Document, version.document_id)
    if document is None:
        return JobRunResult(job_id=job.id, state="lease_lost")

    # T04：任务/版本已被取消或删除时直接结束，不写任何状态或单元
    if job.state == "cancelled" or version.state in {"cancelled", "deleted"}:
        db.rollback()
        return JobRunResult(job_id=job.id, state="cancelled", total_pages=job.total_pages)

    moment = _aware(clock())
    if (
        job.state != "running"
        or job.lease_token != lease.token
        or job.lease_expires_at is None
        or _aware(job.lease_expires_at) <= moment
    ):
        return JobRunResult(job_id=job.id, state="lease_lost", total_pages=job.total_pages)

    services = ParseServices(limits=store.limits.to_parse_limits())
    if ocr is not None:
        options = dict(ocr_options or {})
        services.ocr = OcrExecutor(
            db,
            version_id=version.id,
            document_id=version.document_id,
            gateway=ocr,
            ensure_live=lambda: _live_or_abort(db, lease, clock),
            limiter=ocr_limiter,
            max_attempts=int(options.get("max_attempts", 3)),
            retry_base_seconds=float(options.get("retry_base_seconds", 0.25)),
            retry_max_single_seconds=float(options.get("retry_max_single_seconds", 1.0)),
            retry_total_seconds=float(options.get("retry_total_seconds", 2.0)),
            sleep=options.get("sleep", time.sleep),
        )
    services.ensure_live = lambda: _live_or_abort(db, lease, clock)
    existing_keys = set(db.scalars(select(SourceUnit.unit_key).where(SourceUnit.version_id == version.id)).all())
    existing_ordinals = set(
        db.scalars(select(SourceUnit.ordinal).where(SourceUnit.version_id == version.id)).all()
    )
    persisted = len(existing_keys)
    written = reused = 0
    parser_map = parsers if parsers is not None else DEFAULT_PARSERS
    parser = parser_map.get(document.file_type) if parser_map else None
    if parser is None:
        parser = _parser_for(document.file_type)

    try:
        if document.deleted:
            return _finalize_blocked(
                db, job, version, lease, clock, services.report, persisted, "CONTENT_DELETED", "资料已删除，停止处理"
            )
        path = store.path_for(version.stored_path)
        if not path.is_file():
            return _finalize_failure(
                db,
                job,
                version,
                lease,
                clock,
                services.report,
                persisted,
                "FILE_MISSING",
                "原始文件缺失，无法继续处理；请重新上传",
                retryable=False,
            )
        if version.state not in PROCESSABLE_VERSION_STATES:
            return JobRunResult(
                job_id=job.id, state="already_finished", total_pages=job.total_pages
            )

        iterator = parser(path, document.file_type, services)
        ordinal = 0
        while True:
            # 每推进一个单元前重新核对：任务/租约/版本/资料仍有效，否则丢弃本批未提交内容
            live = _job_live_state(db, lease, _aware(clock()))
            if live != "ok":
                db.rollback()
                return JobRunResult(job_id=job.id, state=live, total_pages=_progress_total(services, job))
            if max_units is not None and written >= max_units:
                _checkpoint(db, job, lease, services, persisted, clock, lease_seconds, renew_seconds)
                return JobRunResult(
                    job_id=job.id,
                    state="paused",
                    units_written=written,
                    units_reused=reused,
                    total_pages=_progress_total(services, job),
                )
            try:
                unit = next(iterator)
            except StopIteration:
                break
            current_ordinal = ordinal
            ordinal += 1
            if unit.unit_key in existing_keys:
                reused += 1
                continue
            if current_ordinal in existing_ordinals:
                # 重试时失败页补写：把其后已保存单元的 ordinal 后移一位，保持页码/预览顺序。
                # 两段式负偏移避免 SQLite 立即唯一约束在多行前移时互相冲突。
                db.execute(
                    update(SourceUnit)
                    .where(SourceUnit.version_id == version.id, SourceUnit.ordinal >= current_ordinal)
                    .values(ordinal=-(SourceUnit.ordinal + 1))
                )
                db.execute(
                    update(SourceUnit)
                    .where(SourceUnit.version_id == version.id, SourceUnit.ordinal < 0)
                    .values(ordinal=-SourceUnit.ordinal)
                )
                existing_ordinals = {
                    (value + 1 if value >= current_ordinal else value) for value in existing_ordinals
                }
            db.add(
                SourceUnit(
                    document_id=version.document_id,
                    version_id=version.id,
                    kind=unit.kind,
                    ordinal=current_ordinal,
                    unit_key=unit.unit_key,
                    sheet=unit.sheet,
                    locator=unit.locator,
                    text=unit.text,
                    fields=unit.fields,
                    warnings=list(unit.warnings or []),
                )
            )
            existing_keys.add(unit.unit_key)
            existing_ordinals.add(current_ordinal)
            written += 1
            persisted = len(existing_keys)
            if written % CHECKPOINT_BATCH_UNITS == 0:
                _checkpoint(db, job, lease, services, persisted, clock, lease_seconds, renew_seconds)

        _checkpoint(db, job, lease, services, persisted, clock, lease_seconds, renew_seconds)
        return _finalize_success(db, job, version, document, lease, clock, services, persisted, written, reused)
    except ParseAborted as exc:
        db.rollback()
        return JobRunResult(job_id=job.id, state=exc.state, total_pages=_progress_total(services, job))
    except ParseQuotaExceeded:
        return _finalize_blocked(
            db,
            job,
            version,
            lease,
            clock,
            services.report,
            persisted,
            "OCR_QUOTA_UNAVAILABLE",
            "OCR 额度不足，任务已暂停；恢复额度后可显式重试",
            retryable=True,
        )
    except ParseLimitError as exc:
        return _finalize_failure(
            db, job, version, lease, clock, services.report, persisted, exc.code, exc.message, retryable=False
        )
    except ParseError as exc:
        return _finalize_failure(
            db, job, version, lease, clock, services.report, persisted, exc.code, exc.message, retryable=exc.retryable
        )
    except _LeaseLost:
        return JobRunResult(job_id=job.id, state="lease_lost", total_pages=_progress_total(services, job))
    except IntegrityError:
        # 另一持有有效租约的 worker 已写入同一检查点；旧持有者不得覆盖
        db.rollback()
        return JobRunResult(job_id=job.id, state="lease_lost", total_pages=_progress_total(services, job))
    except OperationalError as exc:
        db.rollback()
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            # 取消/删除与检查点竞争导致快照写冲突：不得把本批内容写回
            return _invalid_result(db, lease)
        logger.error("worker_db_error type=%s job_id=%s", type(exc).__name__, job.id)
        return _finalize_failure(
            db,
            job,
            version,
            lease,
            clock,
            services.report,
            persisted,
            "PARSE_INTERNAL",
            "处理过程出现未预期错误，可重试；资料未被发布",
            retryable=True,
        )
    except Exception as exc:  # 未预期错误：只记录类型，不把异常消息/路径写入任务与日志
        logger.error("worker_unhandled type=%s job_id=%s", type(exc).__name__, job.id)
        db.rollback()
        return _finalize_failure(
            db,
            job,
            version,
            lease,
            clock,
            services.report,
            persisted,
            "PARSE_INTERNAL",
            "处理过程出现未预期错误，可重试；资料未被发布",
            retryable=True,
        )


def _parser_for(kind: str) -> Callable:
    return DEFAULT_PARSERS.get(kind, parse_document)


def _progress_total(services: ParseServices, job: ImportJob) -> int:
    if services.page_total is not None:
        return int(services.page_total)
    return int(services.planned_units if services.planned_units is not None else job.total_pages)


def _checkpoint(
    db: Session,
    job: ImportJob,
    lease: JobLease,
    services: ParseServices,
    persisted: int,
    clock: Callable[[], datetime],
    lease_seconds: int,
    renew_seconds: int,
) -> None:
    moment = _aware(clock())
    completed_pages = services.pages_done if services.page_total is not None else persisted
    total_pages = (
        services.page_total
        if services.page_total is not None
        else (services.planned_units if services.planned_units is not None else job.total_pages)
    )
    values: dict = {
        "completed_pages": completed_pages,
        "total_pages": total_pages,
        "updated_at": moment,
        "stage": "parsing",
    }
    if (moment - _aware(lease.claimed_at)).total_seconds() >= renew_seconds:
        values["lease_expires_at"] = moment + timedelta(seconds=lease_seconds)
    result = db.execute(
        update(ImportJob).execution_options(synchronize_session=False)
        .where(*_lease_conditions(lease, moment))
        .values(**values)
    )
    if result.rowcount != 1:
        db.rollback()
        raise _LeaseLost()
    db.commit()


def _finalize_success(
    db: Session,
    job: ImportJob,
    version: DocumentVersion,
    document: Document,
    lease: JobLease,
    clock: Callable[[], datetime],
    services: ParseServices,
    persisted: int,
    written: int,
    reused: int,
) -> JobRunResult:
    moment = _aware(clock())
    page_total = services.page_total if services.page_total is not None else persisted
    document_now = db.get(Document, version.document_id, populate_existing=True)
    if document_now is None or document_now.deleted:
        return _invalid_result(db, lease)
    result = db.execute(
        update(ImportJob).execution_options(synchronize_session=False)
        .where(*_lease_conditions(lease, moment))
        .values(
            state="succeeded",
            stage="finished",
            completed_pages=page_total,
            total_pages=page_total,
            updated_at=moment,
            finished_at=moment,
            lease_token=None,
            lease_owner=None,
            lease_expires_at=None,
            error_code=None,
            message=None,
            retryable=False,
        )
    )
    if result.rowcount != 1:
        return _invalid_result(db, lease)
    version_result = db.execute(
        update(DocumentVersion).execution_options(synchronize_session=False)
        .where(
            DocumentVersion.id == version.id,
            DocumentVersion.id.in_(_live_version_ids()),
        )
        .values(state="review_required", processing_report=services.report)
    )
    if version_result.rowcount != 1:
        return _invalid_result(db, lease)
    db.commit()
    return JobRunResult(
        job_id=job.id,
        state="succeeded",
        units_written=written,
        units_reused=reused,
        total_pages=page_total,
    )


def _finalize_failure(
    db: Session,
    job: ImportJob,
    version: DocumentVersion,
    lease: JobLease,
    clock: Callable[[], datetime],
    report: dict,
    persisted: int,
    error_code: str,
    message: str,
    *,
    retryable: bool,
) -> JobRunResult:
    moment = _aware(clock())
    is_paged = report.get("kind") in {"pdf", "png", "jpg", "jpeg"} and isinstance(
        report.get("total_pages"), int
    )
    if is_paged:
        completed = len(report.get("pages") or [])
        total = int(report.get("total_pages") or 0)
    else:
        completed = persisted
        total = max(persisted, int(report.get("total_data_rows") or 0), int(report.get("units") or 0))
    result = db.execute(
        update(ImportJob).execution_options(synchronize_session=False)
        .where(*_lease_conditions(lease, moment))
        .values(
            state="failed",
            stage="failed",
            completed_pages=completed,
            total_pages=total,
            updated_at=moment,
            finished_at=moment,
            lease_token=None,
            lease_owner=None,
            lease_expires_at=None,
            error_code=error_code,
            message=message,
            retryable=retryable,
        )
    )
    if result.rowcount != 1:
        return _invalid_result(db, lease)
    version_result = db.execute(
        update(DocumentVersion).execution_options(synchronize_session=False)
        .where(DocumentVersion.id == version.id, DocumentVersion.id.in_(_live_version_ids()))
        .values(state="failed", processing_report=report)
    )
    if version_result.rowcount != 1:
        return _invalid_result(db, lease)
    db.commit()
    return JobRunResult(
        job_id=job.id,
        state="failed",
        error_code=error_code,
        message=message,
        total_pages=total,
    )


def _finalize_blocked(
    db: Session,
    job: ImportJob,
    version: DocumentVersion,
    lease: JobLease,
    clock: Callable[[], datetime],
    report: dict,
    persisted: int,
    error_code: str,
    message: str,
    *,
    retryable: bool = False,
) -> JobRunResult:
    moment = _aware(clock())
    is_paged = report.get("kind") in {"pdf", "png", "jpg", "jpeg"} and isinstance(
        report.get("total_pages"), int
    )
    if is_paged:
        completed = len(report.get("pages") or [])
        total = int(report.get("total_pages") or 0)
    else:
        completed = persisted
        total = max(persisted, int(report.get("units") or 0))
    result = db.execute(
        update(ImportJob).execution_options(synchronize_session=False)
        .where(
            ImportJob.id == job.id,
            ImportJob.lease_token == lease.token,
            ImportJob.lease_expires_at > _naive_utc(moment),
            ImportJob.state == "running",
        )
        .values(
            state="blocked",
            stage="blocked",
            completed_pages=completed,
            total_pages=total,
            updated_at=moment,
            finished_at=moment,
            lease_token=None,
            lease_owner=None,
            lease_expires_at=None,
            error_code=error_code,
            message=message,
            retryable=retryable,
        )
    )
    if result.rowcount != 1:
        return _invalid_result(db, lease)
    version_result = db.execute(
        update(DocumentVersion).execution_options(synchronize_session=False)
        .where(DocumentVersion.id == version.id, DocumentVersion.state.in_(PROCESSABLE_VERSION_STATES))
        .values(state="failed", processing_report=report)
    )
    if version_result.rowcount != 1:
        return _invalid_result(db, lease)
    db.commit()
    return JobRunResult(
        job_id=job.id,
        state="blocked",
        error_code=error_code,
        message=message,
        total_pages=total,
    )


# ---------------------------------------------------------------- 查询与重试


def get_job(db: Session, job_id: uuid.UUID) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise JobNotFound()
    return job


def _document_live_ids():
    """未删除资料的 id 子查询（重试等按版本状态单独校验时使用）。"""
    return select(Document.id).where(Document.deleted.is_(False))


def _begin_write(db: Session) -> None:
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def retry_job(
    db: Session,
    job_id: uuid.UUID,
    *,
    now: datetime | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> ImportJob:
    """把合法失败任务重新排队；复用同字节文件与已保存检查点，不产生重复任务/版本。

    T04：在同一 BEGIN IMMEDIATE 短事务内重检任务/版本/资料状态后再排队，
    删除或取消后的任务不能被重试“复活”。
    """
    clock = _resolve_clock(now, now_fn)
    job = get_job(db, job_id)
    moment = _aware(clock())

    def operation() -> ImportJob:
        job_now = db.get(ImportJob, job.id, populate_existing=True)
        if job_now is None:
            raise JobNotFound()
        version_now = db.get(DocumentVersion, job_now.version_id, populate_existing=True)
        if version_now is None:
            raise JobStateConflict("JOB_NOT_RETRYABLE", "版本状态不可重试")
        document_now = db.get(Document, version_now.document_id, populate_existing=True)
        if document_now is None or document_now.deleted:
            raise ContentUnavailable("资料已删除，不能重试")
        if job_now.state == "running":
            raise JobStateConflict("JOB_ALREADY_RUNNING", "任务正在处理中，不能重复重试")
        if job_now.state == "queued":
            raise JobStateConflict("JOB_ALREADY_QUEUED", "任务已在等待处理")
        if job_now.state not in {"failed", "blocked"} or not job_now.retryable:
            raise JobStateConflict("JOB_NOT_RETRYABLE", "任务当前状态或失败原因不可直接重试，请重新上传文件")
        if version_now.state != "failed":
            raise JobStateConflict("JOB_NOT_RETRYABLE", "版本状态不可重试")

        requeued_job = db.execute(
            update(ImportJob)
            .where(
                ImportJob.id == job_now.id,
                ImportJob.state.in_(("failed", "blocked")),
                ImportJob.retryable.is_(True),
            )
            .values(
                state="queued",
                stage="queued",
                error_code=None,
                message=None,
                retryable=True,
                lease_token=None,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=moment,
                finished_at=None,
            )
        )
        if requeued_job.rowcount != 1:
            raise JobStateConflict("JOB_RETRY_CONFLICT", "任务状态正在变化，请稍后重试")
        requeued_version = db.execute(
            update(DocumentVersion)
            .where(
                DocumentVersion.id == version_now.id,
                DocumentVersion.state == "failed",
                DocumentVersion.document_id.in_(_document_live_ids()),
            )
            .values(state="queued")
        )
        if requeued_version.rowcount != 1:
            raise JobStateConflict("JOB_RETRY_CONFLICT", "版本状态正在变化，请稍后重试")
        try:
            db.commit()
        except IntegrityError:
            # 同字节内容已被其他资料占用（例如失败后被重新导入）：不能覆盖
            db.rollback()
            raise DuplicateContent() from None
        return db.get(ImportJob, job_now.id, populate_existing=True)

    for attempt in range(3):
        try:
            _begin_write(db)
            return operation()
        except OperationalError as exc:
            db.rollback()
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            if attempt == 2:
                raise JobStateConflict("JOB_RETRY_CONFLICT", "任务正在被其他操作修改，请稍后重试") from None
            time.sleep(0.05 * (attempt + 1))
        except BaseException:
            db.rollback()
            raise
    raise JobStateConflict("JOB_RETRY_CONFLICT", "任务正在被其他操作修改，请稍后重试")


# ---------------------------------------------------------------- 单次入口


def _ocr_from_env():
    """单次 worker 从环境变量构造 OCR 网关；缺任一项则返回 None（扫描页稳定失败）。

    S2-H：``MKTKB_OCR_DISABLED=1`` 时无条件返回 None，即使进程环境里仍有 OCR 凭据。
    这与 ``providers.build_ocr_gateway`` 的 ``Settings.ocr_disabled`` 保持同一语义，
    避免 smoke 模式在未显式清除凭据时无意构造可用 OCR 客户端。
    """
    if (os.environ.get("MKTKB_OCR_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on"):
        return None
    secret_id = (os.environ.get("MKTKB_OCR_SECRET_ID") or "").strip()
    secret_key = (os.environ.get("MKTKB_OCR_SECRET_KEY") or "").strip()
    if not secret_id or not secret_key:
        return None
    from ..providers.tencent_ocr import TencentOCRClient

    return TencentOCRClient(
        secret_id=secret_id,
        secret_key=secret_key,
        region=(os.environ.get("MKTKB_OCR_REGION") or "ap-guangzhou").strip(),
        endpoint=(os.environ.get("MKTKB_OCR_ENDPOINT") or "https://ocr.tencentcloudapi.com").strip(),
        timeout_seconds=float(os.environ.get("MKTKB_OCR_REQUEST_TIMEOUT_SECONDS") or 30.0),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="单次运行文件处理 worker（不常驻、不调度 HTTP）")
    parser.add_argument("--database-url", required=True, help="SQLite URL，例如 sqlite:////var/lib/mktkb/mktkb.sqlite3")
    parser.add_argument("--storage-dir", required=True, help="项目专属存储根目录（originals/staging 在其下）")
    parser.add_argument("--max-jobs", type=int, default=1, help="本次最多处理的任务数，默认 1")
    parser.add_argument("--max-units", type=int, default=None, help="有界测试用：处理 N 个来源单元后保存检查点并退出")
    parser.add_argument("--lease-seconds", type=int, default=LOCAL_LEASE_SECONDS, help="领取租约秒数，默认 120")
    parser.add_argument("--renew-seconds", type=int, default=LOCAL_RENEW_SECONDS, help="续期周期秒数，默认 30")
    parser.add_argument("--owner", default=None, help="可选的 worker 标识，仅用于排错")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    database = Database(args.database_url)
    store = Store(Path(args.storage_dir), UploadLimits())
    db = database.session()
    ocr = _ocr_from_env()
    ocr_limiter = OcrRateLimiter(
        max_per_second=float(os.environ.get("MKTKB_OCR_MAX_REQUESTS_PER_SECOND") or 2.0)
    )
    ocr_options = {
        "max_attempts": int(os.environ.get("MKTKB_OCR_MAX_ATTEMPTS") or 3),
        "retry_base_seconds": float(os.environ.get("MKTKB_OCR_RETRY_BASE_SECONDS") or 0.25),
        "retry_max_single_seconds": float(os.environ.get("MKTKB_OCR_RETRY_MAX_SINGLE_SECONDS") or 1.0),
        "retry_total_seconds": float(os.environ.get("MKTKB_OCR_RETRY_TOTAL_SECONDS") or 2.0),
    }
    exit_code = 0
    try:
        for _ in range(max(1, args.max_jobs)):
            result = run_one_job(
                db,
                store,
                ocr=ocr,
                ocr_limiter=ocr_limiter,
                ocr_options=ocr_options,
                lease_seconds=args.lease_seconds,
                renew_seconds=args.renew_seconds,
                max_units=args.max_units,
                owner=args.owner,
            )
            print(
                json.dumps(
                    {
                        "job_id": str(result.job_id) if result.job_id else None,
                        "state": result.state,
                        "units_written": result.units_written,
                        "units_reused": result.units_reused,
                        "total_pages": result.total_pages,
                        "error_code": result.error_code,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if result.state in {"failed", "blocked", "lease_lost"}:
                exit_code = 1
            if result.state in {"idle", "paused", "failed", "blocked", "lease_lost"}:
                break
    finally:
        ocr_closer = getattr(ocr, "close", None)
        if ocr_closer is not None:
            ocr_closer()
        db.close()
        database.dispose()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
