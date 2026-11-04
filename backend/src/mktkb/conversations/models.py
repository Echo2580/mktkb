"""T06 个人会话、消息、来源引用与问答请求的持久模型。

设计要点（与任务单第 5.3/5.4 节、契约第 4/5 节一致）：
- 会话、消息、请求都绑定 ``user_id``；跨用户访问由服务层拒绝，不依赖页面隐藏；
- 会话内 ``client_request_id`` 唯一；``status='running'`` 上建部分唯一索引，
  保证"每会话最多一个有效处理中请求"由数据库而不是进程字典保证；
- 请求保存规范化问题摘要、attempt/fencing token、持久截止时间与结果 JSON；
- 消息来源用复合外键绑定 ``source_units`` 的真实归属（id/version_id/document_id），
  不能只存一个可伪造的 UUID。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

MESSAGE_ROLES = ("user", "assistant")
REQUEST_STATUSES = ("running", "succeeded", "failed", "cancelled", "expired")
# 已产生最终结果、可直接幂等重放的状态
SETTLED_STATUSES = ("succeeded",)
# 可以显式重试（复用同一请求、新增 attempt）的状态
RETRYABLE_STATUSES = ("failed", "expired", "cancelled")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Conversation(Base):
    """本人会话；删除是逻辑删除，不触碰知识库资料。"""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_created", "user_id", "created_at"),
        Index("ix_conversations_user_deleted", "user_id", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_conversations_user", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.seq"
    )


class ConversationMessage(Base):
    """会话消息：用户问题或助手结果；助手消息保存当次 revision 与结果类型。"""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_conversation_messages_seq"),
        Index("ix_conversation_messages_conversation", "conversation_id", "seq"),
        Index("ix_conversation_messages_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", name="fk_conversation_messages_conversation", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_conversation_messages_user", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    missing_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    sources: Mapped[list["MessageSource"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageSource.created_at"
    )


class MessageSource(Base):
    """助手消息引用的真实来源单元：只允许本次有效 EvidenceSet 中存在的单元。"""

    __tablename__ = "conversation_message_sources"
    __table_args__ = (
        UniqueConstraint("message_id", "source_id", name="uq_conversation_message_sources_pair"),
        ForeignKeyConstraint(
            ["source_id", "version_id", "document_id"],
            [
                "source_units.id",
                "source_units.version_id",
                "source_units.document_id",
            ],
            name="fk_conversation_message_sources_unit",
        ),
        Index("ix_conversation_message_sources_message", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversation_messages.id", name="fk_conversation_message_sources_message", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    message: Mapped[ConversationMessage] = relationship(back_populates="sources")


class ConversationRequest(Base):
    """一次问答请求的持久状态；幂等、恢复、fencing 与结果重放都以本表为准。"""

    __tablename__ = "conversation_requests"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_request_id", name="uq_conversation_requests_client_id"),
        Index(
            "uq_conversation_requests_running",
            "conversation_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
        Index("ix_conversation_requests_conversation", "conversation_id", "created_at"),
        Index("ix_conversation_requests_status_deadline", "status", "deadline_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", name="fk_conversation_requests_conversation", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_conversation_requests_user", ondelete="CASCADE"), nullable=False
    )
    client_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    user_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("conversation_messages.id", name="fk_conversation_requests_user_message"),
        nullable=True,
    )
    result_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("conversation_messages.id", name="fk_conversation_requests_result_message"),
        nullable=True,
    )
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
