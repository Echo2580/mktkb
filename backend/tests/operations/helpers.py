"""T302 测试数据构造：直接写隔离测试库（受控样本），不触碰 ``var/``。

所有时间显式用 UTC；``BASE`` 对应 2026-11-21 12:00 Asia/Shanghai。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from mktkb.auth.models import User
from mktkb.conversations.models import (
    Conversation,
    ConversationMessage,
    ConversationRequest,
    MessageSource,
)
from mktkb.documents.models import Document, DocumentVersion, SourceUnit
from mktkb.ingestion.models import ImportJob

UTC = timezone.utc
BASE = datetime(2026, 11, 21, 4, 0, tzinfo=UTC)  # 2026-11-21 12:00 +08:00


def user_id(db: Session, username: str = "admin") -> uuid.UUID:
    row = db.scalar(select(User).where(User.username == username))
    assert row is not None, f"预置账号 {username} 不存在"
    return row.id


def make_document(
    db: Session,
    *,
    name: str = "演示资料",
    file_type: str = "xlsx",
    states: tuple[str, ...] = ("published",),
    deleted: bool = False,
    active: bool = True,
    units: int = 1,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    """创建资料 + 版本 + 来源单元（满足 MessageSource 复合外键）。"""
    document = Document(
        name=name,
        name_key=None,
        file_type=file_type,
        latest_version_number=len(states),
        deleted=deleted,
        created_at=created_at or BASE,
    )
    db.add(document)
    db.flush()

    versions: list[DocumentVersion] = []
    units_by_version: dict[uuid.UUID, list[SourceUnit]] = {}
    for index, state in enumerate(states, start=1):
        version = DocumentVersion(
            document_id=document.id,
            number=index,
            state=state,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            size_bytes=1,
            stored_path=f"storage/{uuid.uuid4().hex}.{file_type}",
            uploaded_at=created_at or BASE,
            published_at=(created_at or BASE) if state == "published" else None,
        )
        db.add(version)
        db.flush()
        versions.append(version)
        created_units: list[SourceUnit] = []
        for ordinal in range(1, units + 1):
            unit = SourceUnit(
                document_id=document.id,
                version_id=version.id,
                kind="record",
                ordinal=ordinal,
                unit_key=f"row-{index}-{ordinal}",
                sheet="Sheet1",
                locator={"sheet": "Sheet1", "row": ordinal, "cells": ["不应出口"]},
                text=f"{name} 第 {index} 版第 {ordinal} 行",
                fields={"门店": "滨江店"},
            )
            db.add(unit)
            db.flush()
            created_units.append(unit)
        units_by_version[version.id] = created_units

    if active and versions:
        published = next((item for item in reversed(versions) if item.state == "published"), None)
        if published is not None:
            document.active_version_id = published.id
    db.flush()
    return SimpleNamespace(document=document, versions=versions, units=units_by_version)


def make_import(
    db: Session,
    version: DocumentVersion,
    *,
    state: str = "failed",
    stage: str = "parse",
    error_code: str | None = "PARSE_INCOMPLETE",
    message: str | None = "解析未完成：缺少缓存值",
    attempts: int = 1,
    retryable: bool = True,
    finished_at: datetime | None = None,
) -> ImportJob:
    """创建导入任务；租约字段故意写入哨兵值，用于验证响应不外泄 ``lease_*``。"""
    job = ImportJob(
        version_id=version.id,
        state=state,
        stage=stage,
        total_pages=1,
        completed_pages=1 if state == "succeeded" else 0,
        error_code=error_code,
        message=message,
        retryable=retryable,
        attempts=attempts,
        lease_token="LEAK-CANARY-LEASE-TOKEN",
        lease_owner="LEAK-CANARY-LEASE-OWNER",
        lease_expires_at=BASE,
        created_at=BASE,
        updated_at=BASE,
        finished_at=finished_at,
    )
    db.add(job)
    db.flush()
    return job


def make_request(
    db: Session,
    *,
    kind: str | None = "answer",
    finished_at: datetime = BASE,
    question: str = "演示问题",
    user: uuid.UUID | None = None,
    sources: tuple[tuple[str, str], ...] = (),
    conflicts: tuple[dict, ...] = (),
    status: str = "succeeded",
    deleted: bool = False,
    revision: int = 1,
    error_code: str | None = None,
    missing_fields: list[str] | None = None,
    client_request_id: uuid.UUID | None = None,
    result_text: str = "演示结果",
) -> SimpleNamespace:
    """构造一次问答；``sources`` 为 ``(document_id, version_id)``（实际单元取该版本首个）。"""
    owner = user or user_id(db)
    conversation = Conversation(
        user_id=owner,
        title="T302 测试会话",
        created_at=finished_at - timedelta(minutes=5),
        updated_at=finished_at,
        deleted_at=finished_at if deleted else None,
    )
    db.add(conversation)
    db.flush()
    user_message = ConversationMessage(
        conversation_id=conversation.id,
        user_id=owner,
        seq=1,
        role="user",
        text=question,
        created_at=finished_at - timedelta(minutes=1),
    )
    db.add(user_message)
    db.flush()

    result_message = None
    if status == "succeeded" and kind is not None:
        result_message = ConversationMessage(
            conversation_id=conversation.id,
            user_id=owner,
            seq=2,
            role="assistant",
            text=result_text,
            kind=kind,
            revision=revision,
            error_code=error_code,
            missing_fields=missing_fields,
            created_at=finished_at,
        )
        db.add(result_message)
        db.flush()

    result_json = {"kind": kind, "text": result_text, "sources": [], "conflicts": list(conflicts)}
    request_row = ConversationRequest(
        conversation_id=conversation.id,
        user_id=owner,
        client_request_id=client_request_id or uuid.uuid4(),
        payload_sha256=uuid.uuid4().hex,
        question=question,
        status=status,
        attempt=1,
        user_message_id=user_message.id,
        result_message_id=result_message.id if result_message is not None else None,
        result_json=result_json if status == "succeeded" else None,
        error_code=error_code,
        error_retryable=False,
        created_at=finished_at - timedelta(minutes=5),
        started_at=finished_at - timedelta(minutes=5),
        deadline_at=finished_at + timedelta(minutes=1),
        finished_at=finished_at if status != "running" else None,
    )
    db.add(request_row)
    db.flush()

    if result_message is not None:
        for spec in sources:
            document_id, version_id = spec[0], spec[1]
            unit_index = spec[2] if len(spec) > 2 else 0
            unit = db.scalar(
                select(SourceUnit)
                .where(
                    SourceUnit.document_id == uuid.UUID(str(document_id)),
                    SourceUnit.version_id == uuid.UUID(str(version_id)),
                )
                .order_by(SourceUnit.ordinal)
                .offset(unit_index)
            )
            assert unit is not None, "引用来源缺少来源单元"
            db.add(
                MessageSource(
                    message_id=result_message.id,
                    source_id=unit.id,
                    document_id=unit.document_id,
                    version_id=unit.version_id,
                    created_at=finished_at,
                )
            )
        db.flush()

    return SimpleNamespace(
        request=request_row,
        conversation=conversation,
        user_message=user_message,
        message=result_message,
    )
