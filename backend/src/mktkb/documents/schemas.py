"""T03 文档接口响应模型：字段名与《接口与数据契约》一致。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..ingestion.schemas import JobStatus
from .models import as_utc

VersionState = Literal[
    "queued",
    "processing",
    "review_required",
    "failed",
    "published",
    "superseded",
    "cancelled",
    "deleted",
]
FileType = Literal["xlsx", "docx", "pdf", "png", "jpg", "jpeg"]


def _aware(value: datetime | None) -> datetime | None:
    return as_utc(value) if isinstance(value, datetime) else value


class VersionSummary(BaseModel):
    id: uuid.UUID
    number: int
    state: VersionState
    sha256: str
    uploaded_at: datetime
    published_at: datetime | None = None
    processing_report: dict | None = None

    @field_validator("uploaded_at", "published_at", mode="before")
    @classmethod
    def _ensure_timezone(cls, value):
        return _aware(value)


class DocumentSummary(BaseModel):
    id: uuid.UUID
    name: str
    file_type: FileType
    active_version: VersionSummary | None = None
    latest_version: VersionSummary | None = None
    deleted: bool
    created_at: datetime
    last_published_at: datetime | None = None

    @field_validator("created_at", "last_published_at", mode="before")
    @classmethod
    def _ensure_timezone(cls, value):
        return _aware(value)


class DocumentDetail(BaseModel):
    document: DocumentSummary
    versions: list[VersionSummary]
    jobs: list[JobStatus] = Field(default_factory=list)
    revision: int = 0


class PublishRequest(BaseModel):
    """发布前置条件：两个键均必填；revision 严格非负整数，bool/浮点/负值不接受。"""

    expected_active_version_id: uuid.UUID | None
    expected_revision: int = Field(strict=True, ge=0)


class Publication(BaseModel):
    document_id: uuid.UUID
    active_version_id: uuid.UUID
    revision: int
    published_at: datetime

    @field_validator("published_at", mode="before")
    @classmethod
    def _ensure_timezone(cls, value):
        return _aware(value)


class Deletion(BaseModel):
    document_id: uuid.UUID
    deleted: bool = True
    revision: int


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    total: int
    offset: int
    limit: int


class SourceUnitPublic(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    kind: str
    locator: dict
    text: str
    fields: dict
    warnings: list[str] = []


class PreviewResponse(BaseModel):
    items: list[SourceUnitPublic]
    total: int
    offset: int
    limit: int
    report: dict


class UploadResponse(BaseModel):
    document: DocumentSummary
    version: VersionSummary
    job: JobStatus
