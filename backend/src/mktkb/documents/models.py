"""T03 逻辑文件/版本/来源单元模型。

Document 表示逻辑资料，DocumentVersion 表示某次上传；active_version 与 latest_version 分开表达。
SourceUnit 保存可预览、可供后续任务消费的结构化内容与定位。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
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

# 版本内部状态（接口与契约一致）
VERSION_STATES = (
    "queued",
    "processing",
    "review_required",
    "failed",
    "published",
    "superseded",
    "cancelled",
    "deleted",
)
# 参与“同字节去重”的存活状态：有效版或待确认/待处理候选
LIVE_VERSION_STATES = ("queued", "processing", "review_required", "published")
# 允许通过受保护接口读取原件的状态
READABLE_VERSION_STATES = ("queued", "processing", "review_required", "published", "superseded")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite 返回的天真时间按 UTC 处理（与 auth 会话一致）。"""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Document(Base):
    """逻辑资料；名称不是主键，同名独立资料通过 allow_same_name 显式创建。"""

    __tablename__ = "documents"
    __table_args__ = (
        # 未显式允许同名时，名称键唯一，防止并发同名请求都创建成功；
        # 显式作为独立资料新增时 name_key 为 NULL（SQLite 允许多个 NULL）。
        Index("uq_documents_name_key", "name_key", unique=True),
        Index("ix_documents_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("document_versions.id", name="fk_documents_active_version"), nullable=True
    )
    latest_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.number",
        foreign_keys="DocumentVersion.document_id",
    )


class DocumentVersion(Base):
    """某次上传的版本；新版不会自动切换有效版本。"""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "number", name="uq_document_versions_number"),
        # 有效或待处理版本指纹唯一：防止并发重复创建；失效/已被替换/删除后自动退出唯一约束
        Index(
            "uq_document_versions_live_sha",
            "sha256",
            unique=True,
            sqlite_where=text("state IN ('queued','processing','review_required','published')"),
        ),
        Index("ix_document_versions_document_id", "document_id"),
        Index("ix_document_versions_sha256", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", name="fk_document_versions_document", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    document: Mapped[Document] = relationship(back_populates="versions", foreign_keys=[document_id])
    units: Mapped[list["SourceUnit"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="SourceUnit.ordinal"
    )


class SourceUnit(Base):
    """可预览/可检索的来源单元：Excel 记录行、Word 段落或表格行。"""

    __tablename__ = "source_units"
    __table_args__ = (
        UniqueConstraint("version_id", "unit_key", name="uq_source_units_key"),
        UniqueConstraint("version_id", "ordinal", name="uq_source_units_ordinal"),
        Index("ix_source_units_version_id", "version_id"),
        Index("ix_source_units_sheet", "sheet"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", name="fk_source_units_document", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", name="fk_source_units_version", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_key: Mapped[str] = mapped_column(String(200), nullable=False)
    sheet: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locator: Mapped[dict] = mapped_column(JSON, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    version: Mapped[DocumentVersion] = relationship(back_populates="units")


class KnowledgeState(Base):
    """单例知识库状态：全库 revision 与有效总量（发布/删除时同事务维护）。"""

    __tablename__ = "knowledge_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    active_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    active_excel_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PublicationReceipt(Base):
    """一次成功发布的最小幂等凭据；只有同时匹配请求条件与当前 revision 才可重放。"""

    __tablename__ = "publication_receipts"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_publication_receipts_version"),
        Index("ix_publication_receipts_document", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", name="fk_publication_receipts_document", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("document_versions.id", name="fk_publication_receipts_version", ondelete="CASCADE"),
        nullable=False,
    )
    expected_active_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DeletionReceipt(Base):
    """一次成功逻辑删除的持久结果；重复删除返回同一 revision，不随全库变化改写。"""

    __tablename__ = "deletion_receipts"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", name="fk_deletion_receipts_document", ondelete="CASCADE"), primary_key=True
    )
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
