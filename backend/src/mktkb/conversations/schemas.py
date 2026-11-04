"""T06 HTTP 请求/响应模型：字段名与《接口与数据契约》第 4 节一致。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ResultKind = Literal["answer", "clarification", "not_found", "conflict", "service_error", "knowledge_changed"]
SourceStatus = Literal["active", "superseded", "deleted"]
QUESTION_MIN = 1
QUESTION_MAX = 2000
TITLE_MAX = 200


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=TITLE_MAX)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    offset: int
    limit: int


class AskRequest(BaseModel):
    client_request_id: uuid.UUID
    question: str = Field(max_length=QUESTION_MAX)

    @field_validator("question")
    @classmethod
    def _clean_question(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < QUESTION_MIN:
            raise ValueError("question 去除首尾空白后不能为空")
        if len(cleaned) > QUESTION_MAX:
            raise ValueError(f"question 超出上限 {QUESTION_MAX}")
        return cleaned


class SourceSummary(BaseModel):
    source_id: uuid.UUID
    document_name: str
    version_number: int
    status: SourceStatus
    locator: dict
    published_at: datetime | None = None


class CandidateView(BaseModel):
    label: str
    followup_question: str


class PaginationView(BaseModel):
    """S2：枚举分页（向后兼容扩展；旧客户端忽略该字段）。"""

    page: int
    page_size: int
    total: int
    returned: int
    has_more: bool
    next_page: int | None = None


class ConflictEntry(BaseModel):
    value: str
    source_id: uuid.UUID


class ConflictView(BaseModel):
    field: str
    entries: list[ConflictEntry]


class MessageView(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    text: str
    kind: ResultKind | None = None
    revision: int | None = None
    error_code: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    created_at: datetime
    sources: list[SourceSummary] = Field(default_factory=list)
    candidates: list[CandidateView] = Field(default_factory=list)
    conflicts: list[ConflictView] = Field(default_factory=list)
    pagination: PaginationView | None = None


class MessageList(BaseModel):
    items: list[MessageView]
    total: int
    offset: int
    limit: int


class AskResult(BaseModel):
    request_id: uuid.UUID
    message_id: uuid.UUID
    kind: ResultKind
    text: str
    revision: int
    sources: list[SourceSummary] = Field(default_factory=list)
    candidates: list[CandidateView] = Field(default_factory=list)
    conflicts: list[ConflictView] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    pagination: PaginationView | None = None
    error_code: str | None = None
    retryable: bool = False


class SourceView(BaseModel):
    source_id: uuid.UUID
    status: SourceStatus
    document_name: str
    version_number: int
    locator: dict
    published_at: datetime | None = None
    text: str | None = None
    fields: dict | None = None
    warnings: list[str] = Field(default_factory=list)
    file_url: str | None = None
