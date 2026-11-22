"""T302：只读运营接口（6 个 GET，仅 admin）。

- ``GET /operations/overview``：窗口指标、按日趋势、六类分布、Trace 覆盖率、待处理项；
- ``GET /operations/requests``：窗口内已完成问答列表（keyset 分页 + 文档/版本过滤）；
- ``GET /operations/requests/{request_id}``：问题、结果、引用、冲突、Trace attempts；
- ``GET /operations/documents``：资料列表（当前版本、导入状态、窗口最终引用）；
- ``GET /operations/documents/{document_id}``：版本、导入摘要与下钻条件；
- ``GET /operations/evaluation-runs``：白名单评测批次摘要（holdout 详情扣留）。

口径与权限以 ``T301-data-audit.md``（冻结）和 T302 派单 §3 为准；本模块只读，
不写业务库/Trace 库、不发起评测、不调用模型或 OCR。响应为显式白名单模型，
不含 ``*_json`` 原文、``stored_path``、``lease_*``、密钥或原始请求头。
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.routes import get_db, require_role
from ..auth.service import UserContext
from ..documents.models import Document, DocumentVersion, SourceUnit
from ..ingestion.models import ImportJob
from ..observability.routes import (
    SpanSummary,
    _as_bool,
    _as_optional_str,
    _gate_summary,
    _manifest_summary,
    _read_json_object,
    _span_summary,
    _summary_block,
)
from ..observability.store import TraceRepository, TraceWriteError
from ..errors import NotFound
from ..sources.service import ACTIVE, status_of
from . import queries
from .queries import (
    InvalidParameter,
    RESULT_KINDS,
    Window,
    iso_utc,
    load_completed_requests,
    resolve_window,
)
from .schemas import (
    CitationItem,
    ConflictEntryItem,
    ConflictGroupItem,
    DocumentBasic,
    DocumentDetailResponse,
    DocumentListItem,
    DocumentsPage,
    EvaluationRunItem,
    EvaluationRunsResponse,
    ImportDetail,
    ImportSummary,
    OverviewMetrics,
    OverviewResponse,
    PendingItem,
    RequestDetailResponse,
    RequestListItem,
    RequestsDrilldown,
    RequestsPage,
    ResultBlock,
    TraceAttemptItem,
    TraceBlock,
    TraceCoverage,
    TrendPoint,
    VersionDetail,
    DocumentVersionSummary,
    WindowBlock,
)

router = APIRouter(prefix="/operations", tags=["operations"])

#: 管理员依赖；6 个端点共用（沿用 ``auth/routes.py`` 的 ``require_role``）。
admin_required = Depends(require_role("admin"))

_VERSION_STATES = (
    "queued",
    "processing",
    "review_required",
    "failed",
    "published",
    "superseded",
    "cancelled",
    "deleted",
)
_JOB_STATES = ("queued", "running", "succeeded", "failed", "blocked", "cancelled")
_ABNORMAL_KINDS = ("service_error", "conflict", "not_found")
_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 20


class _RequestNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("REQUEST_NOT_FOUND", "问答请求不存在")


class _DocumentNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("DOCUMENT_NOT_FOUND", "资料不存在")


# --------------------------------------------------------------------------- #
# 通用辅助
# --------------------------------------------------------------------------- #


def _window(window: str | None, since: str | None, until: str | None) -> Window:
    return resolve_window(window, since, until)


def _window_block(window: Window) -> WindowBlock:
    return WindowBlock(**window.block())


def _trace_repo(request: Request) -> TraceRepository | None:
    return getattr(request.app.state, "trace_repo", None)


def _trace_status(records: list) -> str:
    if not records:
        return "not_recorded"
    return "recorded" if any(not record.replayed for record in records) else "not_recorded"


def _page_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidParameter("INVALID_PAGE_SIZE", "page_size 需为正整数")
    if value < 1:
        raise InvalidParameter("INVALID_PAGE_SIZE", "page_size 需为正整数")
    if value > _MAX_PAGE_SIZE:
        raise InvalidParameter("INVALID_PAGE_SIZE", f"page_size 不能超过 {_MAX_PAGE_SIZE}")
    return value


def _kind(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in RESULT_KINDS:
        raise InvalidParameter("INVALID_KIND", "kind 不在六类结果范围内")
    return value


def _uuid_param(value: str | None, *, code: str, label: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise InvalidParameter(code, f"{label} 不合法") from None


def _uuid_path(value: str, *, not_found: type[NotFound]) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        raise not_found() from None


def _encode_id_cursor(entity_id: str) -> str:
    raw = json.dumps({"id": entity_id}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_id_cursor(cursor: str | None) -> str | None:
    if not cursor:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error):
        raise InvalidParameter("INVALID_CURSOR", "游标不合法") from None
    entity_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(entity_id, str) or not entity_id:
        raise InvalidParameter("INVALID_CURSOR", "游标不合法")
    return entity_id


def _paginate_ids(items: list, *, cursor: str | None, page_size: int, key) -> tuple[list, str | None]:
    marker = _decode_id_cursor(cursor)
    start = 0
    if marker is not None:
        while start < len(items) and key(items[start]) <= marker:
            start += 1
    page = items[start : start + page_size]
    next_cursor = None
    if start + page_size < len(items) and page:
        next_cursor = _encode_id_cursor(key(page[-1]))
    return page, next_cursor


def _coverage(repo: TraceRepository | None, request_ids: list[str]) -> TraceCoverage:
    if repo is None:
        return TraceCoverage(
            covered=None, total=None, status="disabled", note="Trace 已关闭，不计算覆盖率"
        )
    if not request_ids:
        return TraceCoverage(
            covered=0,
            total=0,
            status="not_recorded",
            note="窗口内无已完成请求（空样本）",
        )
    covered = 0
    try:
        for request_id in request_ids:
            records = repo.list_by_request(request_id)
            if any(not record.replayed for record in records):
                covered += 1
    except TraceWriteError:
        return TraceCoverage(
            covered=None, total=None, status="unavailable", note="Trace 读取失败，不计算覆盖率"
        )
    total = len(request_ids)
    status = "recorded" if covered == total else ("partial" if covered else "not_recorded")
    return TraceCoverage(
        covered=covered,
        total=total,
        status=status,
        note=None if status == "recorded" else f"覆盖 {covered}/{total}",
    )


def _conversation_visible(db: Session, conversation_id: uuid.UUID) -> bool:
    from ..conversations.models import Conversation

    conversation = db.get(Conversation, conversation_id)
    return conversation is not None and conversation.deleted_at is None


# --------------------------------------------------------------------------- #
# 总览
# --------------------------------------------------------------------------- #


def _pending_requests(completed: list) -> list[PendingItem]:
    items: list[PendingItem] = []
    for entry in completed:
        if entry.kind not in _ABNORMAL_KINDS:
            continue
        day = queries.shanghai_day(entry.finished_at).isoformat()
        items.append(
            PendingItem(
                type="request",
                request_id=entry.request_id,
                kind=entry.kind,
                finished_at=iso_utc(entry.finished_at),
                error_code=entry.error_code,
                drilldown={"date": day, "kind": entry.kind},
            )
        )
    return items


def _pending_imports(db: Session) -> list[PendingItem]:
    rows = db.execute(
        select(ImportJob, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == ImportJob.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(ImportJob.state.in_(("failed", "blocked")), Document.deleted.is_(False))
        .order_by(ImportJob.created_at)
    ).all()
    items: list[PendingItem] = []
    for job, version in rows:
        items.append(
            PendingItem(
                type="import",
                document_id=str(version.document_id),
                version_id=str(version.id),
                state=job.state,
                error_code=job.error_code,
                finished_at=iso_utc(job.finished_at),
                drilldown={
                    "document_id": str(version.document_id),
                    "version_id": str(version.id),
                    "state": job.state,
                },
            )
        )
    return items


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="运营总览（窗口指标、趋势、六类分布、Trace 覆盖率、待处理项）",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_overview(
    request: Request,
    window: str | None = Query(default=None, description="today / 7d / 30d"),
    since: str | None = Query(default=None, description="自定义起始日 YYYY-MM-DD"),
    until: str | None = Query(default=None, description="自定义结束日 YYYY-MM-DD（含当天）"),
    db: Session = Depends(get_db),
    _user: UserContext = admin_required,
) -> OverviewResponse:
    scope = _window(window, since, until)
    completed = load_completed_requests(db, scope)

    distribution = {kind: 0 for kind in RESULT_KINDS}
    for entry in completed:
        if entry.kind in distribution:
            distribution[entry.kind] += 1

    trend: dict[str, TrendPoint] = {}
    for entry in completed:
        day = queries.shanghai_day(entry.finished_at).isoformat()
        point = trend.get(day)
        if point is None:
            point = trend[day] = TrendPoint(date=day)
        point.completed += 1
        point.citations += entry.final_document_count()

    coverage = _coverage(_trace_repo(request), [entry.request_id for entry in completed])

    pending = _pending_requests(completed) + _pending_imports(db)

    return OverviewResponse(
        window=_window_block(scope),
        metrics=OverviewMetrics(
            completed_requests=len(completed),
            not_found=distribution["not_found"],
            conflict=distribution["conflict"],
            interrupted=queries.interrupted_count(db, scope),
            review_required_versions=queries.review_required_count(db),
            active_documents=queries.active_document_count(db),
        ),
        trend=[trend[day] for day in sorted(trend)],
        result_distribution=distribution,
        trace_coverage=coverage,
        pending=pending,
    )


# --------------------------------------------------------------------------- #
# 问答列表 / 详情
# --------------------------------------------------------------------------- #


def _matches_document_filter(entry, document_id: str | None, version_id: str | None) -> bool:
    if document_id is None and version_id is None:
        return True

    def _hit(candidate_doc: str | None, candidate_version: str | None) -> bool:
        if document_id is not None and candidate_doc != document_id:
            return False
        if version_id is not None and candidate_version != version_id:
            return False
        return True

    if any(_hit(row.document_id, row.version_id) for row in entry.sources):
        return True
    return any(
        _hit(item.document_id, item.version_id) for item in entry.conflict_entries
    )


def _request_item(entry, repo: TraceRepository | None) -> RequestListItem:
    status = _trace_status(_safe_trace_records(repo, entry.request_id))
    return RequestListItem(
        request_id=entry.request_id,
        conversation_id_hash=entry.conversation_id_hash,
        kind=entry.kind,
        status="succeeded",
        finished_at=iso_utc(entry.finished_at),
        error_code=entry.error_code,
        revision=entry.revision,
        trace_status=status,
        citation_count=entry.final_document_count(),
        conflict_flag=entry.conflict_flag,
    )


def _safe_trace_records(repo: TraceRepository | None, request_id: str) -> list:
    if repo is None:
        return []
    try:
        return repo.list_by_request(request_id)
    except TraceWriteError:
        return []


@router.get(
    "/requests",
    response_model=RequestsPage,
    summary="窗口内已完成问答列表（keyset 分页，可按结果类型/文档/版本过滤）",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_requests(
    request: Request,
    window: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    version_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE),
    db: Session = Depends(get_db),
    _user: UserContext = admin_required,
) -> RequestsPage:
    scope = _window(window, since, until)
    kind_filter = _kind(kind)
    doc = _uuid_param(document_id, code="INVALID_DOCUMENT_ID", label="document_id")
    ver = _uuid_param(version_id, code="INVALID_VERSION_ID", label="version_id")
    size = _page_size(page_size)

    completed = load_completed_requests(db, scope)
    filtered = [
        entry
        for entry in completed
        if (kind_filter is None or entry.kind == kind_filter)
        and _matches_document_filter(entry, doc, ver)
    ]
    page, next_cursor = queries.paginate(
        filtered,
        cursor=cursor,
        page_size=size,
        key=lambda entry: (entry.finished_at, entry.request_id),
    )
    repo = _trace_repo(request)
    return RequestsPage(
        window=_window_block(scope),
        items=[_request_item(entry, repo) for entry in page],
        next_cursor=next_cursor,
        page_size=size,
    )


def _citation_items(db: Session, entry) -> list[CitationItem]:
    """非冲突持久引用摘要：按 (document_id, version_id) 去重，active 才带 locator。"""
    deduped = []
    seen: set[tuple[str, str]] = set()
    for row in entry.sources:
        key = (row.document_id, row.version_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    from ..documents.models import SourceUnit

    items: list[CitationItem] = []
    for row in deduped:
        unit = db.get(SourceUnit, uuid.UUID(row.source_id)) if _is_uuid(row.source_id) else None
        version = (
            db.get(DocumentVersion, uuid.UUID(row.version_id)) if _is_uuid(row.version_id) else None
        )
        document = db.get(Document, uuid.UUID(row.document_id)) if _is_uuid(row.document_id) else None
        status = status_of(document, version) if document is not None and version is not None else "deleted"
        locator = None
        if status == ACTIVE and unit is not None:
            locator = {
                key: value for key, value in (unit.locator or {}).items() if key != "cells"
            }
        items.append(
            CitationItem(
                source_id=row.source_id,
                document_id=row.document_id,
                version_id=row.version_id,
                version_number=version.number if version is not None else None,
                document_name=document.name if document is not None else None,
                status=status,
                published_at=iso_utc(version.published_at) if version is not None else None,
                locator=locator,
            )
        )
    return items


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (TypeError, ValueError):
        return False


def _conflict_groups(db: Session, entry) -> list[ConflictGroupItem]:
    """冲突两方来源取自 ``result_json.conflicts``，不计入 citation_count。"""
    groups: list[ConflictGroupItem] = []
    for group_field in (entry.result_json or {}).get("conflicts") or []:  # type: ignore[union-attr]
        if not isinstance(group_field, dict):
            continue
        entries: list[ConflictEntryItem] = []
        for raw in group_field.get("entries") or []:
            if not isinstance(raw, dict):
                continue
            source_id = str(raw.get("source_id") or "")
            document_id = version_id = document_name = status = None
            version_number = None
            if _is_uuid(source_id):
                unit = db.get(SourceUnit, uuid.UUID(source_id))
                if unit is not None:
                    document_id = str(unit.document_id)
                    version_id = str(unit.version_id)
                    version = db.get(DocumentVersion, unit.version_id)
                    document = db.get(Document, unit.document_id)
                    if version is not None and document is not None:
                        version_number = version.number
                        document_name = document.name
                        status = status_of(document, version)
            entries.append(
                ConflictEntryItem(
                    value=str(raw.get("value") or ""),
                    source_id=source_id,
                    document_id=document_id,
                    version_id=version_id,
                    document_name=document_name,
                    version_number=version_number,
                    status=status,
                )
            )
        groups.append(
            ConflictGroupItem(
                field=str(group_field.get("field") or ""),
                entries=entries,
            )
        )
    return groups


def _attempts(repo: TraceRepository, records: list) -> list[TraceAttemptItem]:
    attempts: list[TraceAttemptItem] = []
    for record in records:
        spans: list[SpanSummary] = []
        if record.trace_id:
            try:
                _record, raw_spans = repo.get(record.trace_id)
                spans = [_span_summary(span) for span in raw_spans]
            except (KeyError, TraceWriteError):
                spans = []
        attempts.append(
            TraceAttemptItem(
                trace_id=record.trace_id,
                attempt=record.attempt,
                replayed=record.replayed,
                previous_trace_id=record.previous_trace_id,
                path=record.path,
                outcome=record.outcome_kind,
                status=record.status,
                error_code=record.error_code,
                spans=spans,
            )
        )
    return attempts


@router.get(
    "/requests/{request_id}",
    response_model=RequestDetailResponse,
    summary="问答详情（问题、结果、可展示引用、冲突两方来源、Trace attempts）",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_request_detail(
    request_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _user: UserContext = admin_required,
) -> RequestDetailResponse:
    from ..conversations.models import Conversation, ConversationRequest, ConversationMessage

    parsed = _uuid_path(request_id, not_found=_RequestNotFound)
    row = db.get(ConversationRequest, parsed)
    if row is None or not _conversation_visible(db, row.conversation_id):
        raise _RequestNotFound()
    message = db.get(ConversationMessage, row.result_message_id) if row.result_message_id else None
    kind = (message.kind if message is not None else None) or (
        (row.result_json or {}).get("kind") if isinstance(row.result_json, dict) else None
    )
    missing = message.missing_fields if message is not None and isinstance(message.missing_fields, list) else []

    entry = queries.CompletedRequest(
        request_id=str(row.id),
        conversation_id=str(row.conversation_id),
        conversation_id_hash=queries._hash_conversation(row.conversation_id),
        finished_at=queries.utc(row.finished_at) or queries.utc(row.started_at),  # type: ignore[arg-type]
        kind=kind if isinstance(kind, str) else None,
        error_code=message.error_code if message is not None else row.error_code,
        revision=message.revision if message is not None else None,
        message_id=str(message.id) if message is not None else None,
        question=row.question or "",
        result_text=(message.text if message is not None else "") or "",
        missing_fields=[str(item) for item in missing],
        result_json=row.result_json if isinstance(row.result_json, dict) else None,
    )
    if entry.message_id:
        from ..conversations.models import MessageSource

        source_rows = db.scalars(
            select(MessageSource).where(MessageSource.message_id == message.id)
        ).all()
        entry.sources = [
            queries.SourceRow(
                source_id=str(item.source_id),
                document_id=str(item.document_id),
                version_id=str(item.version_id),
            )
            for item in source_rows
        ]

    # D5：冲突消息的持久引用行是冲突两方的原始记录，不计最终引用；
    # 冲突来源统一走 conflicts 块展示，citations 仅给非冲突回答。
    citations = [] if entry.kind == "conflict" else _citation_items(db, entry)
    conflicts = _conflict_groups(db, entry) if entry.kind == "conflict" else []

    repo = _trace_repo(request)
    if repo is None:
        trace = TraceBlock(status="disabled", attempts=[], note="Trace 已关闭，业务结果照常可读")
    else:
        try:
            records = repo.list_by_request(entry.request_id)
        except TraceWriteError:
            trace = TraceBlock(status="unavailable", attempts=[], note="Trace 读取失败")
        else:
            attempts = _attempts(repo, records)
            trace = TraceBlock(status=_trace_status(records), attempts=attempts)

    return RequestDetailResponse(
        request_id=entry.request_id,
        conversation_id_hash=entry.conversation_id_hash,
        question=entry.question,
        result=ResultBlock(
            kind=entry.kind,
            text=entry.result_text,
            error_code=entry.error_code,
            missing_fields=entry.missing_fields,
            revision=entry.revision,
        ),
        citations=citations,
        citation_count=entry.final_document_count(),
        conflicts=conflicts,
        trace=trace,
    )


# --------------------------------------------------------------------------- #
# 资料列表 / 详情
# --------------------------------------------------------------------------- #


def _document_maps(completed: list) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """返回 (文档 → 最终引用消息集合, 文档 → 相关问答请求集合)。"""
    finals: dict[str, set[str]] = {}
    related: dict[str, set[str]] = {}
    for entry in completed:
        for row in entry.sources:
            related.setdefault(row.document_id, set()).add(entry.request_id)
            if not entry.is_conflict and entry.message_id:
                finals.setdefault(row.document_id, set()).add(entry.message_id)
        for item in entry.conflict_entries:
            if item.document_id:
                related.setdefault(item.document_id, set()).add(entry.request_id)
    return finals, related


def _latest_version(db: Session, document: Document) -> DocumentVersion | None:
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.number == document.latest_version_number,
        )
    )
    return version


def _current_version(db: Session, document: Document) -> DocumentVersion | None:
    if document.active_version_id is not None:
        return db.get(DocumentVersion, document.active_version_id)
    return _latest_version(db, document)


def _import_summary(job: ImportJob | None) -> ImportSummary | None:
    if job is None:
        return None
    return ImportSummary(
        state=job.state,
        stage=job.stage,
        error_code=job.error_code,
        attempts=job.attempts,
        retryable=job.retryable,
        finished_at=iso_utc(job.finished_at),
    )


def _versions_for(db: Session, document_id: uuid.UUID) -> list[DocumentVersion]:
    return list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.number)
        ).all()
    )


@router.get(
    "/documents",
    response_model=DocumentsPage,
    summary="知识资产列表（当前版本、最近导入、窗口最终引用与相关问答）",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_documents(
    request: Request,
    window: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    version_state: str | None = Query(default=None),
    processing_state: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE),
    db: Session = Depends(get_db),
    _user: UserContext = admin_required,
) -> DocumentsPage:
    scope = _window(window, since, until)
    if version_state not in (None, "") and version_state not in _VERSION_STATES:
        raise InvalidParameter("INVALID_VERSION_STATE", "version_state 不在现有版本状态枚举内")
    if processing_state not in (None, "") and processing_state not in _JOB_STATES:
        raise InvalidParameter("INVALID_PROCESSING_STATE", "processing_state 不在现有任务状态枚举内")
    size = _page_size(page_size)

    finals, related = _document_maps(load_completed_requests(db, scope))

    documents = list(
        db.scalars(select(Document).where(Document.deleted.is_(False))).all()
    )
    documents.sort(key=lambda item: str(item.id))

    items: list[DocumentListItem] = []
    for document in documents:
        latest = _latest_version(db, document)
        current = _current_version(db, document)
        job = None
        if latest is not None:
            job = db.scalar(select(ImportJob).where(ImportJob.version_id == latest.id))
        if file_type and document.file_type != file_type:
            continue
        if version_state and (latest is None or latest.state != version_state):
            continue
        if processing_state and (job is None or job.state != processing_state):
            continue
        items.append(
            DocumentListItem(
                document_id=str(document.id),
                name=document.name,
                file_type=document.file_type,
                current_version=DocumentVersionSummary(
                    version_id=str(current.id),
                    number=current.number,
                    state=current.state,
                    published_at=iso_utc(current.published_at),
                )
                if current is not None
                else None,
                latest_import=_import_summary(job),
                final_citations=len(finals.get(str(document.id), set())),
                related_requests_count=len(related.get(str(document.id), set())),
            )
        )

    page, next_cursor = _paginate_ids(
        items, cursor=cursor, page_size=size, key=lambda item: item.document_id
    )
    return DocumentsPage(
        window=_window_block(scope),
        items=page,
        next_cursor=next_cursor,
        page_size=size,
    )


def _safe_message(message: str | None) -> str | None:
    """失败信息含内部路径/堆栈/库名时只回错误码，不回显原文。"""
    if not isinstance(message, str) or not message:
        return None
    lowered = message.lower()
    if (
        "\\" in message
        or "/" in message
        or "traceback" in lowered
        or "sqlite" in lowered
        or "storage" in lowered
    ):
        return None
    return message


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
    summary="资料详情（全部版本、导入摘要、失败原因与按文档/版本下钻条件）",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_document_detail(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _user: UserContext = admin_required,
) -> DocumentDetailResponse:
    parsed = _uuid_path(document_id, not_found=_DocumentNotFound)
    document = db.get(Document, parsed)
    if document is None or document.deleted:
        raise _DocumentNotFound()

    versions = _versions_for(db, document.id)
    jobs = {
        job.version_id: job
        for job in db.scalars(select(ImportJob).where(ImportJob.version_id.in_(
            [version.id for version in versions]
        ))).all()
    } if versions else {}

    version_items: list[VersionDetail] = []
    import_items: list[ImportDetail] = []
    for version in versions:
        job = jobs.get(version.id)
        version_items.append(
            VersionDetail(
                version_id=str(version.id),
                number=version.number,
                state=version.state,
                uploaded_at=iso_utc(version.uploaded_at),
                published_at=iso_utc(version.published_at),
                error_code=job.error_code if job is not None else None,
                message=_safe_message(job.message if job is not None else None),
            )
        )
        if job is not None:
            import_items.append(
                ImportDetail(
                    version_id=str(version.id),
                    state=job.state,
                    stage=job.stage,
                    error_code=job.error_code,
                    message=_safe_message(job.message),
                    attempts=job.attempts,
                    retryable=job.retryable,
                    created_at=iso_utc(job.created_at),
                    finished_at=iso_utc(job.finished_at),
                )
            )

    filter_conditions = {"document_id": str(document.id)}
    if document.active_version_id is not None:
        filter_conditions["version_id"] = str(document.active_version_id)

    return DocumentDetailResponse(
        document=DocumentBasic(
            document_id=str(document.id),
            name=document.name,
            file_type=document.file_type,
            latest_version_number=document.latest_version_number,
            active_version_id=str(document.active_version_id)
            if document.active_version_id is not None
            else None,
            deleted=bool(document.deleted),
            created_at=iso_utc(document.created_at),
            last_published_at=iso_utc(document.last_published_at),
        ),
        versions=version_items,
        imports=import_items,
        drilldown=RequestsDrilldown(requests_filter=filter_conditions),
    )


# --------------------------------------------------------------------------- #
# 评测批次
# --------------------------------------------------------------------------- #


def _run_root(settings) -> Path:
    return Path(settings.data_dir) / "eval" / "runs"


def _run_item(run_dir: Path) -> EvaluationRunItem | None:
    """读取单个 run 目录的白名单摘要；目录缺 manifest 返回 None（跳过）。"""
    manifest, manifest_status = _read_json_object(run_dir / "run_manifest.json")
    if manifest_status == "missing":
        return None
    summary, summary_status = _read_json_object(run_dir / "summary.json")
    gate, gate_status = _read_json_object(run_dir / "gate.json")

    reasons: list[str] = []
    if manifest_status == "invalid":
        reasons.append("manifest_invalid")
    if summary_status == "invalid":
        reasons.append("summary_invalid")
    if gate_status == "invalid":
        reasons.append("gate_invalid")

    manifest_suite = _as_optional_str(manifest.get("suite")) if manifest else None
    summary_suite = _as_optional_str(summary.get("suite")) if summary else None
    holdout_details = _as_bool(manifest.get("holdout_details")) if manifest else False
    cases_present = (run_dir / "cases.jsonl").is_file()
    holdout_detected = manifest_suite == "holdout" or summary_suite == "holdout" or holdout_details
    details_withheld = bool(holdout_detected and (holdout_details or cases_present))

    return EvaluationRunItem(
        run_id=run_dir.name,
        holdout_detected=holdout_detected,
        details_withheld=details_withheld,
        manifest=_manifest_summary(manifest) if manifest else None,
        summary=_summary_block(summary) if summary else None,
        gate=_gate_summary(gate) if gate else None,
        degraded_reason=reasons[0] if reasons else None,
    )


@router.get(
    "/evaluation-runs",
    response_model=EvaluationRunsResponse,
    summary="评测批次列表（白名单摘要；holdout 只回聚合，详情扣留）",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_evaluation_runs(
    request: Request,
    _user: UserContext = admin_required,
) -> EvaluationRunsResponse:
    settings = request.app.state.settings
    root = _run_root(settings)
    if not root.is_dir():
        return EvaluationRunsResponse(runs=[], skipped=0, status="empty")

    skipped = 0
    items: list[EvaluationRunItem] = []
    for run_dir in sorted(root.iterdir(), key=lambda item: item.name):
        if not run_dir.is_dir():
            continue
        item = _run_item(run_dir)
        if item is None:
            skipped += 1
            continue
        items.append(item)

    def _sort_key(item: EvaluationRunItem) -> tuple[str, str]:
        created = item.manifest.created_at if item.manifest is not None else None
        return (created or "", item.run_id)

    items.sort(key=_sort_key, reverse=True)
    return EvaluationRunsResponse(
        runs=items,
        skipped=skipped,
        status="ok" if items else "empty",
    )


__all__ = ["router"]
