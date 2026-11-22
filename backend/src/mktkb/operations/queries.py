"""T302 共享查询层：时间窗口转换、窗口内已完成请求、库存与 Trace 状态。

口径来源：``docs/reports/OBS-EVAL/P3/T301-data-audit.md`` §3、§4.7、§6.1-6.3
（已冻结）与 ``T301-D5-decision.md``（冲突消息查询侧排除）。

设计要点：

- 统计与下钻**共用** :func:`load_completed_requests`，禁止两处各写一套条件；
- 已完成问答量 = ``status='succeeded'`` + ``result_message_id`` 非空 + ``finished_at``
  落窗 + 排除 ``conversations.deleted_at``；同一产品请求行天然去重（幂等重放复用行）；
- 引用按「结果消息 + 文档」「结果消息 + 版本」两维去重；冲突消息不计最终引用；
- 冲突来源取自 ``result_json.conflicts``，按 source_id 回查单元归属用于文档/版本匹配；
- 只读：本层不发任何 INSERT/UPDATE/DELETE。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..conversations.models import (
    Conversation,
    ConversationMessage,
    ConversationRequest,
    MessageSource,
)
from ..documents.models import Document, DocumentVersion, SourceUnit
from ..errors import ApiError

TIMEZONE_NAME = "Asia/Shanghai"
try:  # 优先使用 IANA 时区（含历史规则）；Windows 缺 tzdata 时退回固定 UTC+8。
    from zoneinfo import ZoneInfo

    SHANGHAI = ZoneInfo(TIMEZONE_NAME)
except Exception:  # pragma: no cover - 仅运行时环境缺少时区库时触发
    SHANGHAI = timezone(timedelta(hours=8), TIMEZONE_NAME)
TIMEZONE_NAME = "Asia/Shanghai"
MAX_CUSTOM_DAYS = 90
PRESET_DAYS = {"today": 1, "7d": 7, "30d": 30}
DEFAULT_PRESET = "7d"

RESULT_KINDS = (
    "answer",
    "clarification",
    "not_found",
    "conflict",
    "service_error",
    "knowledge_changed",
)
INTERRUPTED_STATUSES = ("running", "failed", "cancelled", "expired")
REVIEW_REQUIRED = "review_required"


class InvalidWindow(ApiError):
    """时间窗口参数非法（422）；不回显提交值。"""

    def __init__(self, message: str = "时间窗口不合法") -> None:
        super().__init__("INVALID_WINDOW", message, 422)


class InvalidParameter(ApiError):
    """通用参数非法（422）；沿用全局错误信封。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 422)


def utc(value: datetime | None) -> datetime | None:
    """SQLite 返回的天真时间按 UTC 处理（与项目既有约定一致）。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return utc(value).isoformat(timespec="milliseconds")  # type: ignore[union-attr]


def shanghai_day(value: datetime) -> date:
    return utc(value).astimezone(SHANGHAI).date()  # type: ignore[union-attr]


@dataclass(frozen=True)
class Window:
    """左闭右开 UTC 窗口 ``[start_utc, end_utc)`` 与对外显示的窗口标识。"""

    label: str
    start_utc: datetime
    end_utc: datetime

    def block(self) -> dict[str, str]:
        return {
            "window": self.label,
            "since_utc": iso_utc(self.start_utc) or "",
            "until_utc": iso_utc(self.end_utc) or "",
            "timezone": TIMEZONE_NAME,
        }


def resolve_window(
    preset: str | None,
    since: str | None,
    until: str | None,
    *,
    now: datetime | None = None,
) -> Window:
    """预置（today/7d/30d）或自定义（since/until，含当天）→ 左闭右开 UTC 窗口。"""
    if since or until:
        if not since or not until:
            raise InvalidWindow("自定义窗口需同时提供 since 与 until")
        try:
            since_day = date.fromisoformat(since)
            until_day = date.fromisoformat(until)
        except ValueError:
            raise InvalidWindow("since/until 需为 YYYY-MM-DD") from None
        if since_day > until_day:
            raise InvalidWindow("since 不能晚于 until")
        span_days = (until_day - since_day).days + 1
        if span_days > MAX_CUSTOM_DAYS:
            raise InvalidWindow(f"自定义窗口不能超过 {MAX_CUSTOM_DAYS} 天")
        return Window(
            label="custom",
            start_utc=datetime.combine(since_day, time.min, tzinfo=SHANGHAI).astimezone(timezone.utc),
            end_utc=datetime.combine(
                until_day + timedelta(days=1), time.min, tzinfo=SHANGHAI
            ).astimezone(timezone.utc),
        )

    label = (preset or DEFAULT_PRESET).strip()
    if label not in PRESET_DAYS:
        raise InvalidWindow("window 只接受 today / 7d / 30d，或改用 since+until")
    days = PRESET_DAYS[label]
    today = (now or datetime.now(timezone.utc)).astimezone(SHANGHAI).date()
    first_day = today - timedelta(days=days - 1)
    return Window(
        label=label,
        start_utc=datetime.combine(first_day, time.min, tzinfo=SHANGHAI).astimezone(timezone.utc),
        end_utc=datetime.combine(
            today + timedelta(days=1), time.min, tzinfo=SHANGHAI
        ).astimezone(timezone.utc),
    )


# --------------------------------------------------------------------------- #
# 窗口内已完成请求（统计与下钻共用）
# --------------------------------------------------------------------------- #


@dataclass
class SourceRow:
    source_id: str
    document_id: str
    version_id: str


@dataclass
class ConflictEntryRow:
    field_name: str
    value: str
    source_id: str
    document_id: str | None
    version_id: str | None


@dataclass
class CompletedRequest:
    request_id: str
    conversation_id: str
    conversation_id_hash: str
    finished_at: datetime
    kind: str | None
    error_code: str | None
    revision: int | None
    message_id: str | None
    question: str
    result_text: str
    missing_fields: list[str]
    result_json: dict[str, Any] | None
    sources: list[SourceRow] = field(default_factory=list)
    conflict_entries: list[ConflictEntryRow] = field(default_factory=list)

    @property
    def is_conflict(self) -> bool:
        return self.kind == "conflict"

    @property
    def conflict_flag(self) -> bool:
        return self.is_conflict

    def document_ids(self) -> set[str]:
        """该回答持久引用到的文档（消息+文档去重后的集合）。"""
        return {row.document_id for row in self.sources}

    def version_pairs(self) -> set[tuple[str, str]]:
        """消息+版本去重后的 (document_id, version_id) 集合。"""
        return {(row.document_id, row.version_id) for row in self.sources}

    def final_document_count(self) -> int:
        """最终引用（文档维）：冲突消息不计。"""
        return 0 if self.is_conflict else len(self.document_ids())

    def final_version_count(self) -> int:
        """最终引用（版本维）：冲突消息不计。"""
        return 0 if self.is_conflict else len(self.version_pairs())


def _id(value: Any) -> str:
    return "" if value is None else str(value)


def _hash_conversation(conversation_id: Any) -> str:
    return hashlib.sha256(_id(conversation_id).encode("utf-8")).hexdigest()[:16]


def _kind_of(request: ConversationRequest, message: ConversationMessage | None) -> str | None:
    if message is not None and isinstance(message.kind, str) and message.kind:
        return message.kind
    payload = request.result_json
    if isinstance(payload, dict) and isinstance(payload.get("kind"), str):
        return payload["kind"]
    return None


def _missing_fields(message: ConversationMessage | None) -> list[str]:
    raw = message.missing_fields if message is not None else None
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _conflict_pairs(payload: Any) -> list[tuple[str, str, str]]:
    """从 ``result_json.conflicts`` 提取 ``(field, value, source_id)``。"""
    pairs: list[tuple[str, str, str]] = []
    if not isinstance(payload, dict):
        return pairs
    for conflict in payload.get("conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        field_name = str(conflict.get("field") or "")
        for entry in conflict.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            source_id = _id(entry.get("source_id"))
            if not source_id:
                continue
            pairs.append((field_name, str(entry.get("value") or ""), source_id))
    return pairs


def _as_uuid(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _load_source_identity(
    db: Session, source_ids: Iterable[str]
) -> dict[str, tuple[str | None, str | None]]:
    """批量回查 source_id → (document_id, version_id)；找不到给 None。"""
    wanted: set[uuid.UUID] = set()
    for raw in source_ids:
        parsed = _as_uuid(raw)
        if parsed is not None:
            wanted.add(parsed)
    if not wanted:
        return {}
    units = db.scalars(select(SourceUnit).where(SourceUnit.id.in_(sorted(wanted)))).all()
    result: dict[str, tuple[str | None, str | None]] = {}
    for unit in units:
        key = _id(unit.id)
        result[key] = (_id(unit.document_id), _id(unit.version_id))
        result[key.replace("-", "")] = result[key]
    return result


def load_completed_requests(db: Session, window: Window) -> list[CompletedRequest]:
    """加载窗口内已完成、未删除会话的问答请求（含引用与冲突来源）。"""
    rows = db.execute(
        select(ConversationRequest, ConversationMessage)
        .join(Conversation, Conversation.id == ConversationRequest.conversation_id)
        .outerjoin(
            ConversationMessage,
            ConversationMessage.id == ConversationRequest.result_message_id,
        )
        .where(
            ConversationRequest.status == "succeeded",
            ConversationRequest.result_message_id.is_not(None),
            ConversationRequest.finished_at.is_not(None),
            ConversationRequest.finished_at >= window.start_utc,
            ConversationRequest.finished_at < window.end_utc,
            Conversation.deleted_at.is_(None),
        )
    ).all()

    completed: list[CompletedRequest] = []
    message_ids: list[str] = []
    for request_row, message_row in rows:
        entry = CompletedRequest(
            request_id=_id(request_row.id),
            conversation_id=_id(request_row.conversation_id),
            conversation_id_hash=_hash_conversation(request_row.conversation_id),
            finished_at=utc(request_row.finished_at),  # type: ignore[arg-type]
            kind=_kind_of(request_row, message_row),
            error_code=message_row.error_code if message_row is not None else request_row.error_code,
            revision=message_row.revision if message_row is not None else None,
            message_id=_id(message_row.id) if message_row is not None else None,
            question=request_row.question or "",
            result_text=(message_row.text if message_row is not None else "") or "",
            missing_fields=_missing_fields(message_row),
            result_json=request_row.result_json if isinstance(request_row.result_json, dict) else None,
        )
        if entry.message_id:
            message_ids.append(entry.message_id)
        completed.append(entry)

    if message_ids:
        typed_ids = [parsed for parsed in (_as_uuid(item) for item in message_ids) if parsed]
        source_rows = db.scalars(
            select(MessageSource).where(MessageSource.message_id.in_(sorted(typed_ids)))
        ).all()
        by_message: dict[str, list[SourceRow]] = {}
        for row in source_rows:
            by_message.setdefault(_id(row.message_id), []).append(
                SourceRow(
                    source_id=_id(row.source_id),
                    document_id=_id(row.document_id),
                    version_id=_id(row.version_id),
                )
            )
        for entry in completed:
            if entry.message_id:
                entry.sources = by_message.get(entry.message_id, [])

    conflict_ids = [
        source_id
        for entry in completed
        if entry.is_conflict
        for _field, _value, source_id in _conflict_pairs(entry.result_json)
    ]
    identities = _load_source_identity(db, conflict_ids)
    for entry in completed:
        if not entry.is_conflict:
            continue
        for field_name, value, source_id in _conflict_pairs(entry.result_json):
            document_id, version_id = identities.get(source_id, (None, None))
            if document_id is None:
                document_id, version_id = identities.get(
                    source_id.replace("-", ""), (None, None)
                )
            entry.conflict_entries.append(
                ConflictEntryRow(
                    field_name=field_name,
                    value=value,
                    source_id=source_id,
                    document_id=document_id,
                    version_id=version_id,
                )
            )

    completed.sort(key=lambda item: (item.finished_at, item.request_id), reverse=True)
    return completed


def interrupted_count(db: Session, window: Window) -> int:
    """未提交中断（running/failed/cancelled/expired），单列，不入六类。"""
    stmt = (
        select(func.count())
        .select_from(ConversationRequest)
        .join(Conversation, Conversation.id == ConversationRequest.conversation_id)
        .where(
            ConversationRequest.status.in_(INTERRUPTED_STATUSES),
            ConversationRequest.started_at >= window.start_utc,
            ConversationRequest.started_at < window.end_utc,
            Conversation.deleted_at.is_(None),
        )
    )
    return int(db.scalar(stmt) or 0)


def review_required_count(db: Session) -> int:
    """当前库存：待审核版本（资料未删除）。"""
    stmt = (
        select(func.count())
        .select_from(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.state == REVIEW_REQUIRED, Document.deleted.is_(False))
    )
    return int(db.scalar(stmt) or 0)


def active_document_count(db: Session) -> int:
    """当前库存：生效资料（未删除且存在有效版本）。"""
    stmt = (
        select(func.count())
        .select_from(Document)
        .where(Document.deleted.is_(False), Document.active_version_id.is_not(None))
    )
    return int(db.scalar(stmt) or 0)


# --------------------------------------------------------------------------- #
# 游标（keyset）
# --------------------------------------------------------------------------- #


class InvalidCursor(ApiError):
    def __init__(self) -> None:
        super().__init__("INVALID_CURSOR", "游标不合法", 422)


def encode_cursor(finished_at: datetime, entity_id: str) -> str:
    payload = {"t": iso_utc(finished_at), "id": entity_id}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error):
        raise InvalidCursor() from None
    if not isinstance(payload, dict):
        raise InvalidCursor()
    timestamp, entity_id = payload.get("t"), payload.get("id")
    if not isinstance(timestamp, str) or not isinstance(entity_id, str) or not entity_id:
        raise InvalidCursor()
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        raise InvalidCursor() from None
    return utc(parsed), entity_id  # type: ignore[return-value]


def paginate(
    items: list[CompletedRequest] | list[Any],
    *,
    cursor: str | None,
    page_size: int,
    key: Any,
) -> tuple[list[Any], str | None]:
    """按 ``key(item) -> (datetime, str)`` 降序键集分页；返回页与下一页游标。"""
    marker = decode_cursor(cursor)
    start = 0
    if marker is not None:
        while start < len(items) and key(items[start]) >= marker:
            start += 1
    page = items[start : start + page_size]
    next_cursor = None
    if start + page_size < len(items) and page:
        marker_time, marker_id = key(page[-1])
        next_cursor = encode_cursor(marker_time, marker_id)
    return page, next_cursor


__all__ = [
    "SHANGHAI",
    "TIMEZONE_NAME",
    "MAX_CUSTOM_DAYS",
    "RESULT_KINDS",
    "INTERRUPTED_STATUSES",
    "Window",
    "CompletedRequest",
    "ConflictEntryRow",
    "SourceRow",
    "InvalidWindow",
    "InvalidParameter",
    "InvalidCursor",
    "resolve_window",
    "load_completed_requests",
    "interrupted_count",
    "review_required_count",
    "active_document_count",
    "iso_utc",
    "utc",
    "shanghai_day",
    "encode_cursor",
    "decode_cursor",
    "paginate",
]
