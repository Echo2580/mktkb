"""T03 导入任务模型：任务状态、进度、重试与租约字段。

契约中的 JobStatus 使用 completed_pages/total_pages 字段名；本步中“页”是统一处理单元
（Excel 记录行或 Word 段落/表格行），不改变对外契约字段。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..documents.models import utcnow

JOB_STATES = ("queued", "running", "succeeded", "failed", "blocked", "cancelled")


class ImportJob(Base):
    """一个版本对应一个持久任务；重试复用同一任务，不产生重复任务/版本。"""

    __tablename__ = "import_jobs"
    __table_args__ = (
        Index("ux_import_jobs_version", "version_id", unique=True),
        Index("ix_import_jobs_state", "state"),
        Index("ix_import_jobs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", name="fk_import_jobs_version", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OCRCallRecord(Base):
    """T07 OCR 调用/成功检查点：仅用于本任务去重与排错，不代表账号余额或计费保证。

    成功行以 (version, page, mode, bbox_key, image_sha256) 部分唯一；同一页/模式/块
    重试时优先复用成功结果，不重复请求。失败/丢弃行保留尝试次数与稳定错误码。
    """

    __tablename__ = "ocr_call_records"
    __table_args__ = (
        Index("ix_ocr_call_records_version_page", "version_id", "page", "mode"),
        Index(
            "uq_ocr_call_records_success",
            "version_id",
            "page",
            "mode",
            "bbox_key",
            "image_sha256",
            unique=True,
            sqlite_where=text("state = 'succeeded'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", name="fk_ocr_call_document", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", name="fk_ocr_call_version", ondelete="CASCADE"), nullable=False
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    bbox_key: Mapped[str] = mapped_column(String(128), nullable=False)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
