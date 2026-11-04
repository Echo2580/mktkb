"""隔离 RAG 的 SQLite 模型。

与产品 `documents`/`source_units` 表完全分离；S2 迁入时由适配层把现有 SourceUnit
映射成 `RagUnit`。向量按内容哈希/模型/维度缓存在独立表中，删除版本不删除缓存。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class RagBase(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RagDocument(RagBase):
    __tablename__ = "rag_documents"
    __table_args__ = (
        Index("ix_rag_documents_logical", "logical_id"),
        Index("ix_rag_documents_state", "state", "is_current"),
    )

    doc_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    logical_id: Mapped[str] = mapped_column(String(160), nullable=False)
    version_id: Mapped[str] = mapped_column(String(160), nullable=False)
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    business_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RagUnit(RagBase):
    __tablename__ = "rag_units"
    __table_args__ = (
        Index("ix_rag_units_doc", "doc_id"),
        Index("ix_rag_units_version", "version_id"),
        UniqueConstraint("version_id", "unit_key", name="uq_rag_units_version_key"),
    )

    unit_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("rag_documents.doc_id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_key: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    sheet: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locator: Mapped[dict] = mapped_column(JSON, nullable=False)
    header_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    effective_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)


class RagChunk(RagBase):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        Index("ix_rag_chunks_doc", "doc_id"),
        Index("ix_rag_chunks_version", "version_id"),
        Index("ix_rag_chunks_kind", "kind"),
        Index("ix_rag_chunks_entity", "entity_key"),
    )

    chunk_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("rag_documents.doc_id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sheet: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locator: Mapped[dict] = mapped_column(JSON, nullable=False)
    fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    role_values: Mapped[dict] = mapped_column(JSON, nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False)
    filters_norm: Mapped[dict] = mapped_column(JSON, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    entity_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    record_unit_id: Mapped[str | None] = mapped_column(
        String(160), ForeignKey("rag_units.unit_id", ondelete="SET NULL"), nullable=True
    )
    unit_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    effective_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RagEmbeddingCache(RagBase):
    """内容/模型/维度/供应商寻址的向量缓存；删除资料不删除缓存。"""

    __tablename__ = "rag_embedding_cache"
    __table_args__ = (
        UniqueConstraint(
            "content_sha256", "model", "dimensions", "provider", name="uq_rag_embedding_cache_key"
        ),
        Index("ix_rag_embedding_cache_lookup", "model", "dimensions", "provider"),
    )

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RagChunkEmbedding(RagBase):
    __tablename__ = "rag_chunk_embedding"
    __table_args__ = (
        Index("ix_rag_chunk_embedding_cache", "cache_key"),
        Index("ix_rag_chunk_embedding_model", "model", "dimensions", "provider"),
    )

    chunk_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("rag_chunks.chunk_id", ondelete="CASCADE"), primary_key=True
    )
    cache_key: Mapped[str] = mapped_column(
        String(128), ForeignKey("rag_embedding_cache.cache_key", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)


class RagQueryStateRow(RagBase):
    __tablename__ = "rag_query_state"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RagMeta(RagBase):
    __tablename__ = "rag_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
