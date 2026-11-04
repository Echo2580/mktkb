"""T05 检索索引模型：版本索引状态、单元索引映射与字段索引。

FTS5 虚拟表 `source_unit_fts` 由迁移用原生 SQL 建立（SQLAlchemy 不映射虚拟表）；
`retrieval_unit_index.fts_rowid` 是它唯一的物理 rowid 映射，客户端不能据此授权，
真实来源仍绑定 SourceUnit/版本/Document，并由有效版本过滤复核。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RetrievalVersionIndex(Base):
    """一个版本的索引准备状态；ready=0 时检索必须报 IndexNotReady，不能当 none。"""

    __tablename__ = "retrieval_version_index"
    __table_args__ = (Index("ix_retrieval_version_index_document", "document_id"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    tokenizer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RetrievalUnitIndex(Base):
    """SourceUnit -> FTS rowid 的唯一映射；同时缓存实体分组键与可读标签。"""

    __tablename__ = "retrieval_unit_index"
    __table_args__ = (
        UniqueConstraint("unit_id", name="uq_retrieval_unit_index_unit"),
        Index("ix_retrieval_unit_index_version", "version_id"),
        Index("ix_retrieval_unit_index_document", "document_id"),
        Index("ix_retrieval_unit_index_entity", "entity_key"),
    )

    fts_rowid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_units.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    entity_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    entity_filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RetrievalFieldIndex(Base):
    """规范化后的字段值索引：精确/子串匹配与冲突比较，不改变返回原值。"""

    __tablename__ = "retrieval_field_index"
    __table_args__ = (
        Index("ix_retrieval_field_index_unit", "unit_id"),
        Index("ix_retrieval_field_index_version", "version_id"),
        Index("ix_retrieval_field_index_role_value", "field_role", "norm_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_units.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    norm_value: Mapped[str] = mapped_column(String(512), nullable=False)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
