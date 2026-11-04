"""T06 来源详情与原件：先鉴权消息归属，再核对来源引用与当前有效性。

安全边界（任务单 5.5）：
- 知道 source UUID 不足以授权：必须先证明当前用户拥有 message 所属未删除会话，
  且该 source_id 确实是这条 message 的引用；
- 再核对 SourceUnit/version/document 的完整归属与当前有效性；
- active 返回真实文件名/版本/定位/片段；superseded/deleted 只返回必要失效元信息（410）；
- 原件路径只来自数据库记录并由 Store 解析，拒绝路径穿越，响应 no-store/nosniff。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..conversations.models import Conversation, ConversationMessage, ConversationRequest, MessageSource
from ..conversations.schemas import SourceSummary, SourceView
from ..documents.models import Document, DocumentVersion, SourceUnit
from ..documents.service import Store, media_type_for as _document_media_type
from ..errors import AccessDenied, MessageNotFound, SourceNotFound, SourceUnavailable

ACTIVE = "active"
SUPERSEDED = "superseded"
DELETED = "deleted"


def load_message(db: Session, user, message_id: uuid.UUID) -> ConversationMessage:
    """读取本人未删除会话中的消息；他人消息 403，未知/已删除 404。"""
    message = db.get(ConversationMessage, message_id)
    if message is None:
        raise MessageNotFound()
    conversation = db.get(Conversation, message.conversation_id)
    if conversation is None or conversation.deleted_at is not None:
        raise MessageNotFound()
    if conversation.user_id != user.id or message.user_id != user.id:
        raise AccessDenied()
    return message


def _legacy_conflict_reference(db: Session, message: ConversationMessage, source_id: uuid.UUID):
    """R1A 兼容：修复前的冲突消息只在 result_json 记录了 source_id，没有 MessageSource 行。

    仅当该 source_id 确实出现在这条消息持久化的 result_json.conflicts 中时才解析真实单元；
    不新建行、不改变权限或有效性规则。找不到/不匹配一律 SOURCE_NOT_FOUND。
    """
    request_row = db.scalar(
        select(ConversationRequest).where(ConversationRequest.result_message_id == message.id)
    )
    payload = request_row.result_json if request_row is not None else None
    if not payload or payload.get("kind") != "conflict":
        raise SourceNotFound()
    allowed = {
        str(entry.get("source_id", "")).lower()
        for conflict in payload.get("conflicts") or []
        for entry in conflict.get("entries") or []
    }
    if str(source_id).lower() not in allowed:
        raise SourceNotFound()
    unit = db.get(SourceUnit, source_id)
    if unit is None:
        raise SourceNotFound()
    return SimpleNamespace(source_id=unit.id, version_id=unit.version_id, document_id=unit.document_id)


def load_reference(
    db: Session, message: ConversationMessage, source_id: uuid.UUID
) -> MessageSource | SimpleNamespace:
    reference = db.scalar(
        select(MessageSource).where(
            MessageSource.message_id == message.id,
            MessageSource.source_id == source_id,
        )
    )
    if reference is None:
        return _legacy_conflict_reference(db, message, source_id)
    return reference


def load_unit(db: Session, reference: MessageSource) -> tuple[SourceUnit, DocumentVersion, Document]:
    """按引用快照读取单元/版本/资料，并核对三者归属完全一致。"""
    unit = db.get(SourceUnit, reference.source_id)
    if unit is None:
        raise SourceNotFound()
    if unit.version_id != reference.version_id or unit.document_id != reference.document_id:
        raise SourceNotFound()
    version = db.get(DocumentVersion, unit.version_id)
    document = db.get(Document, unit.document_id)
    if version is None or document is None:
        raise SourceNotFound()
    if version.document_id != document.id:
        raise SourceNotFound()
    return unit, version, document


def status_of(document: Document, version: DocumentVersion) -> str:
    """当前有效性：active 只能同时满足未删除、已发布且仍是资料当前有效版本。"""
    if document.deleted or version.state == "deleted":
        return DELETED
    if version.state == "published" and document.active_version_id == version.id:
        return ACTIVE
    return SUPERSEDED


def summary_for(db: Session, unit_id: uuid.UUID) -> SourceSummary | None:
    """消息列表用：按当前状态给出摘要；引用行缺失时返回 None。"""
    unit = db.get(SourceUnit, unit_id)
    if unit is None:
        return None
    version = db.get(DocumentVersion, unit.version_id)
    document = db.get(Document, unit.document_id)
    if version is None or document is None or version.document_id != document.id:
        return None
    status = status_of(document, version)
    return SourceSummary(
        source_id=unit.id,
        document_name=document.name,
        version_number=version.number,
        status=status,
        locator=unit.locator or {},
        published_at=version.published_at,
    )


def message_sources(db: Session, message: ConversationMessage) -> list[SourceSummary]:
    references = db.scalars(
        select(MessageSource).where(MessageSource.message_id == message.id).order_by(MessageSource.created_at)
    ).all()
    summaries: list[SourceSummary] = []
    for reference in references:
        summary = summary_for(db, reference.source_id)
        if summary is not None:
            summaries.append(summary)
    return summaries


def _ensure_consistency(db: Session, reference: MessageSource, unit: SourceUnit, version: DocumentVersion, document: Document) -> None:
    if unit.version_id != reference.version_id or unit.document_id != reference.document_id:
        raise SourceNotFound()
    if version.document_id != document.id:
        raise SourceNotFound()


def get_message_source(db: Session, user, message_id: uuid.UUID, source_id: uuid.UUID) -> SourceView:
    """来源详情：active 200；superseded/deleted 抛 410（仅必要失效元信息）。"""
    message = load_message(db, user, message_id)
    reference = load_reference(db, message, source_id)
    unit, version, document = load_unit(db, reference)
    _ensure_consistency(db, reference, unit, version, document)
    status = status_of(document, version)
    if status != ACTIVE:
        raise SourceUnavailable(status=status, document_name=document.name, version_number=version.number)
    return SourceView(
        source_id=unit.id,
        status=ACTIVE,
        document_name=document.name,
        version_number=version.number,
        locator=unit.locator or {},
        published_at=version.published_at,
        text=unit.text,
        fields=unit.fields or {},
        warnings=[str(item) for item in (unit.warnings or [])],
        file_url=f"/api/v1/messages/{message.id}/sources/{unit.id}/file",
    )


def resolve_source_file(
    db: Session, store: Store, user, message_id: uuid.UUID, source_id: uuid.UUID
) -> tuple[ConversationMessage, SourceUnit, DocumentVersion, Document, Path]:
    """受保护原件：先鉴权与当前有效性，再由 Store 解析受控路径。"""
    message = load_message(db, user, message_id)
    reference = load_reference(db, message, source_id)
    unit, version, document = load_unit(db, reference)
    _ensure_consistency(db, reference, unit, version, document)
    status = status_of(document, version)
    if status != ACTIVE:
        raise SourceUnavailable(status=status, document_name=document.name, version_number=version.number)
    path = store.path_for(version.stored_path)
    if not path.is_file():
        raise SourceUnavailable(status=DELETED, document_name=document.name, version_number=version.number)
    return message, unit, version, document, path


def media_type_for(document: Document) -> str:
    return _document_media_type(document.file_type)
