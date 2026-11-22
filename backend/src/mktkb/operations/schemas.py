"""T302 运营接口响应模型（显式白名单，禁止 ``*_json`` / ``stored_path`` / 租约字段）。

字段命名以 ``T301-data-audit.md`` §6.7 约定为准；相对派单 §3 的扩展或实现决定登记在
``T302-evidence/T302-delivery.md`` 第 4 节。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..observability.routes import (
    GateSummary,
    RunManifestSummary,
    RunSummaryBlock,
    SpanSummary,
)


class WindowBlock(BaseModel):
    window: str
    since_utc: str
    until_utc: str
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"


# --------------------------------------------------------------------------- #
# 总览
# --------------------------------------------------------------------------- #


class OverviewMetrics(BaseModel):
    completed_requests: int = 0
    not_found: int = 0
    conflict: int = 0
    interrupted: int = 0
    review_required_versions: int = 0
    active_documents: int = 0
    basis: Literal["current"] = "current"


class TrendPoint(BaseModel):
    date: str
    completed: int = 0
    citations: int = 0


class TraceCoverage(BaseModel):
    covered: int | None = None
    total: int | None = None
    status: str = "not_recorded"
    note: str | None = None


class PendingItem(BaseModel):
    type: str
    request_id: str | None = None
    kind: str | None = None
    finished_at: str | None = None
    document_id: str | None = None
    version_id: str | None = None
    state: str | None = None
    error_code: str | None = None
    drilldown: dict[str, str | None] = Field(default_factory=dict)


class OverviewResponse(BaseModel):
    window: WindowBlock
    metrics: OverviewMetrics
    trend: list[TrendPoint] = Field(default_factory=list)
    result_distribution: dict[str, int] = Field(default_factory=dict)
    trace_coverage: TraceCoverage
    pending: list[PendingItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 问答列表 / 详情
# --------------------------------------------------------------------------- #


class RequestListItem(BaseModel):
    request_id: str
    conversation_id_hash: str
    kind: str | None = None
    status: str
    finished_at: str | None = None
    error_code: str | None = None
    revision: int | None = None
    trace_status: str
    citation_count: int = 0
    conflict_flag: bool = False


class RequestsPage(BaseModel):
    window: WindowBlock
    items: list[RequestListItem] = Field(default_factory=list)
    next_cursor: str | None = None
    page_size: int = 20


class ResultBlock(BaseModel):
    kind: str | None = None
    text: str = ""
    error_code: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    revision: int | None = None


class CitationItem(BaseModel):
    source_id: str
    document_id: str
    version_id: str
    version_number: int | None = None
    document_name: str | None = None
    status: str
    published_at: str | None = None
    locator: dict | None = None


class ConflictEntryItem(BaseModel):
    value: str = ""
    source_id: str
    document_id: str | None = None
    version_id: str | None = None
    document_name: str | None = None
    version_number: int | None = None
    status: str | None = None


class ConflictGroupItem(BaseModel):
    field: str = ""
    conflict_flag: Literal[True] = True
    entries: list[ConflictEntryItem] = Field(default_factory=list)


class TraceAttemptItem(BaseModel):
    trace_id: str | None = None
    attempt: int = 1
    replayed: bool = False
    previous_trace_id: str | None = None
    path: str | None = None
    outcome: str | None = None
    status: str | None = None
    error_code: str | None = None
    spans: list[SpanSummary] = Field(default_factory=list)


class TraceBlock(BaseModel):
    status: str = "not_recorded"
    attempts: list[TraceAttemptItem] = Field(default_factory=list)
    note: str | None = None


class RequestDetailResponse(BaseModel):
    request_id: str
    conversation_id_hash: str
    question: str
    result: ResultBlock
    citations: list[CitationItem] = Field(default_factory=list)
    citation_count: int = 0
    conflicts: list[ConflictGroupItem] = Field(default_factory=list)
    trace: TraceBlock


# --------------------------------------------------------------------------- #
# 资料列表 / 详情
# --------------------------------------------------------------------------- #


class DocumentVersionSummary(BaseModel):
    version_id: str
    number: int
    state: str
    published_at: str | None = None


class ImportSummary(BaseModel):
    state: str
    stage: str
    error_code: str | None = None
    attempts: int = 0
    retryable: bool | None = None
    finished_at: str | None = None


class DocumentListItem(BaseModel):
    document_id: str
    name: str
    file_type: str
    current_version: DocumentVersionSummary | None = None
    latest_import: ImportSummary | None = None
    final_citations: int = 0
    related_requests_count: int = 0


class DocumentsPage(BaseModel):
    window: WindowBlock
    items: list[DocumentListItem] = Field(default_factory=list)
    next_cursor: str | None = None
    page_size: int = 20


class DocumentBasic(BaseModel):
    document_id: str
    name: str
    file_type: str
    latest_version_number: int = 0
    active_version_id: str | None = None
    deleted: bool = False
    created_at: str | None = None
    last_published_at: str | None = None


class VersionDetail(BaseModel):
    version_id: str
    number: int
    state: str
    uploaded_at: str | None = None
    published_at: str | None = None
    error_code: str | None = None
    message: str | None = None


class ImportDetail(BaseModel):
    version_id: str
    state: str
    stage: str
    error_code: str | None = None
    message: str | None = None
    attempts: int = 0
    retryable: bool = True
    created_at: str | None = None
    finished_at: str | None = None


class RequestsDrilldown(BaseModel):
    requests_filter: dict[str, str] = Field(default_factory=dict)


class DocumentDetailResponse(BaseModel):
    document: DocumentBasic
    versions: list[VersionDetail] = Field(default_factory=list)
    imports: list[ImportDetail] = Field(default_factory=list)
    drilldown: RequestsDrilldown


# --------------------------------------------------------------------------- #
# 评测批次
# --------------------------------------------------------------------------- #


class EvaluationRunItem(BaseModel):
    run_id: str
    holdout_detected: bool = False
    details_withheld: bool = False
    manifest: RunManifestSummary | None = None
    summary: RunSummaryBlock | None = None
    gate: GateSummary | None = None
    degraded_reason: str | None = None


class EvaluationRunsResponse(BaseModel):
    runs: list[EvaluationRunItem] = Field(default_factory=list)
    skipped: int = 0
    status: Literal["ok", "empty"] = "empty"
    degraded_reason: str | None = None


__all__ = [
    "WindowBlock",
    "OverviewMetrics",
    "TrendPoint",
    "TraceCoverage",
    "PendingItem",
    "OverviewResponse",
    "RequestListItem",
    "RequestsPage",
    "ResultBlock",
    "CitationItem",
    "ConflictEntryItem",
    "ConflictGroupItem",
    "TraceAttemptItem",
    "TraceBlock",
    "RequestDetailResponse",
    "DocumentVersionSummary",
    "ImportSummary",
    "DocumentListItem",
    "DocumentsPage",
    "DocumentBasic",
    "VersionDetail",
    "ImportDetail",
    "RequestsDrilldown",
    "DocumentDetailResponse",
    "EvaluationRunItem",
    "EvaluationRunsResponse",
    "SpanSummary",
]
