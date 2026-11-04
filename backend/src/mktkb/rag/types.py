"""LOCAL-R1/S1 隔离 RAG 的可序列化类型。

这些类型不依赖产品 HTTP 契约；S2 迁入时再由适配层映射到现有 AskResult/来源视图。
所有时间统一使用 ISO 日期字符串（YYYY-MM-DD），便于 SQLite 与测试稳定比较。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

AnswerKind = Literal["answer", "clarification", "no_answer", "ambiguous", "conflict", "error"]
QueryMode = Literal["record", "document"]
ChunkKind = Literal["record", "text"]


@dataclass(frozen=True)
class DocumentSpec:
    """一份隔离资料的版本身份；不写产品 documents 表。"""

    doc_id: str
    source_path: str
    title: str
    file_kind: str
    version_id: str
    version_label: str
    sha256: str
    logical_id: str = ""
    state: str = "active"  # active / superseded / deleted
    is_current: bool = True
    effective_from: str | None = None
    effective_to: str | None = None
    business_date: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.logical_id:
            object.__setattr__(self, "logical_id", self.doc_id)


@dataclass(frozen=True)
class AtomicUnit:
    """来自现有 ParsedUnit/SourceUnit 的保真单元（表格行或正文段落）。"""

    unit_id: str
    doc_id: str
    version_id: str
    kind: str
    ordinal: int
    unit_key: str
    text: str
    fields: Mapping[str, Any]
    sheet: str | None = None
    locator: Mapping[str, Any] = field(default_factory=dict)
    header_row: int | None = None
    row_number: int | None = None
    title: str = ""
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(frozen=True)
class IndexedChunk:
    """可检索块；record 块保留完整结构化字段，text 块保留相邻语境。"""

    chunk_id: str
    doc_id: str
    version_id: str
    revision: int
    kind: ChunkKind
    ordinal: int
    text: str
    title: str
    content_sha256: str
    token_count: int
    sheet: str | None = None
    locator: Mapping[str, Any] = field(default_factory=dict)
    fields: Mapping[str, Any] = field(default_factory=dict)
    role_values: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    filters: Mapping[str, str] = field(default_factory=dict)
    filters_norm: Mapping[str, Any] = field(default_factory=dict)
    entity_type: str | None = None
    entity_key: str | None = None
    label: str | None = None
    record_unit_id: str | None = None
    unit_ids: tuple[str, ...] = ()
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: tuple[tuple[float, ...], ...]
    model: str
    dimensions: int
    provider: str
    usage: Mapping[str, int] = field(default_factory=dict)
    request_id: str | None = None
    estimated_list_price_cny: float = 0.0


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


@dataclass(frozen=True)
class RerankResponse:
    results: tuple[RerankResult, ...]
    model: str
    provider: str
    usage: Mapping[str, int] = field(default_factory=dict)
    request_id: str | None = None
    estimated_list_price_cny: float = 0.0


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str
    provider: str
    usage: Mapping[str, int] = field(default_factory=dict)
    request_id: str | None = None
    estimated_list_price_cny: float = 0.0


@dataclass
class QueryState:
    """跨轮查询状态；只保存检索条件，不保存助手答案作为业务事实。"""

    user_id: str = ""
    conversation_id: str = ""
    store: str | None = None
    stores: tuple[str, ...] = ()
    item: str | None = None
    product: str | None = None
    channel: str | None = None
    price_type: str | None = None
    identifier: str | None = None
    doc_id: str | None = None
    doc_title: str | None = None
    field_role: str | None = None
    field_roles: tuple[str, ...] = ()
    as_of: str | None = None
    enumerate: bool = False
    page: int = 1
    page_size: int = 10
    pending_slot: str | None = None
    candidates: tuple[str, ...] = ()
    last_question: str | None = None
    last_kind: str | None = None
    turn: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "store": self.store,
            "stores": list(self.stores),
            "item": self.item,
            "product": self.product,
            "channel": self.channel,
            "price_type": self.price_type,
            "identifier": self.identifier,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "field_role": self.field_role,
            "field_roles": list(self.field_roles),
            "as_of": self.as_of,
            "enumerate": self.enumerate,
            "page": self.page,
            "page_size": self.page_size,
            "pending_slot": self.pending_slot,
            "candidates": list(self.candidates),
            "last_question": self.last_question,
            "last_kind": self.last_kind,
            "turn": self.turn,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "QueryState":
        data = dict(data or {})
        return cls(
            user_id=str(data.get("user_id") or ""),
            conversation_id=str(data.get("conversation_id") or ""),
            store=_opt_str(data.get("store")),
            stores=tuple(str(x) for x in (data.get("stores") or ()) if x),
            item=_opt_str(data.get("item")),
            product=_opt_str(data.get("product")),
            channel=_opt_str(data.get("channel")),
            price_type=_opt_str(data.get("price_type")),
            identifier=_opt_str(data.get("identifier")),
            doc_id=_opt_str(data.get("doc_id")),
            doc_title=_opt_str(data.get("doc_title")),
            field_role=_opt_str(data.get("field_role")),
            field_roles=tuple(str(x) for x in (data.get("field_roles") or ()) if x),
            as_of=_opt_str(data.get("as_of")),
            enumerate=bool(data.get("enumerate")),
            page=max(1, int(data.get("page") or 1)),
            page_size=max(1, min(50, int(data.get("page_size") or 10))),
            pending_slot=_opt_str(data.get("pending_slot")),
            candidates=tuple(str(x) for x in (data.get("candidates") or ())),
            last_question=_opt_str(data.get("last_question")),
            last_kind=_opt_str(data.get("last_kind")),
            turn=max(0, int(data.get("turn") or 0)),
        )


@dataclass(frozen=True)
class QueryPlan:
    question: str
    mode: QueryMode
    query_text: str
    field_role: str | None
    field_label: str | None
    filters: Mapping[str, str]
    terms: tuple[str, ...]
    state: QueryState
    enumerate: bool = False
    page: int = 1
    page_size: int = 10
    clarification: str | None = None
    candidates: tuple[str, ...] = ()
    unknown_store: str | None = None
    include_future: bool = False
    reason: str | None = None
    field_roles: tuple[str, ...] = ()
    missing_stores: tuple[str, ...] = ()
    unknown_stores: tuple[str, ...] = ()

    @property
    def as_of(self) -> str | None:
        return self.state.as_of


@dataclass(frozen=True)
class Citation:
    source_id: str
    doc_id: str
    source_path: str
    title: str
    version_id: str
    version_label: str
    revision: int
    locator: Mapping[str, Any]
    text: str
    kind: str

    def display(self) -> str:
        where = _locator_text(self.locator)
        return f"{self.title}（{where}，版本 {self.version_label}，修订 {self.revision}）"


@dataclass(frozen=True)
class EvidenceItem:
    chunk_id: str
    doc_id: str
    source_path: str
    title: str
    version_id: str
    version_label: str
    revision: int
    kind: str
    text: str
    sheet: str | None
    locator: Mapping[str, Any]
    fields: Mapping[str, Any]
    citation: Citation
    scores: Mapping[str, float] = field(default_factory=dict)
    matched_channels: tuple[str, ...] = ()
    effective_status: str = "current"


@dataclass(frozen=True)
class Fact:
    entity_key: str
    entity_label: str
    field_role: str
    field_label: str
    value: str
    source_chunk_id: str
    source_unit_id: str
    doc_id: str
    version_id: str
    revision: int


@dataclass
class RetrievalResult:
    plan: QueryPlan
    revision: int
    exact: list[IndexedChunk] = field(default_factory=list)
    lexical: list[IndexedChunk] = field(default_factory=list)
    vector: list[IndexedChunk] = field(default_factory=list)
    fused: list[tuple[IndexedChunk, float]] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    total: int = 0
    returned: int = 0
    has_more: bool = False
    next_page: int | None = None
    recall_counts: Mapping[str, int] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    degraded: tuple[str, ...] = ()
    effective_hints: list[tuple[IndexedChunk, str]] = field(default_factory=list)


@dataclass
class RagAnswer:
    kind: AnswerKind
    question: str
    text: str
    state: Mapping[str, Any]
    citations: list[Citation] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    reason: str | None = None
    answer_source: str = "structured"
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "question": self.question,
            "text": self.text,
            "state": dict(self.state),
            "citations": [
                {
                    "source_id": c.source_id,
                    "doc_id": c.doc_id,
                    "source_path": c.source_path,
                    "title": c.title,
                    "version_id": c.version_id,
                    "version_label": c.version_label,
                    "revision": c.revision,
                    "locator": dict(c.locator),
                    "display": c.display(),
                }
                for c in self.citations
            ],
            "facts": [
                {
                    "entity_key": f.entity_key,
                    "entity_label": f.entity_label,
                    "field_role": f.field_role,
                    "field_label": f.field_label,
                    "value": f.value,
                    "source_chunk_id": f.source_chunk_id,
                    "source_unit_id": f.source_unit_id,
                    "doc_id": f.doc_id,
                    "version_id": f.version_id,
                    "revision": f.revision,
                }
                for f in self.facts
            ],
            "reason": self.reason,
            "answer_source": self.answer_source,
            "diagnostics": dict(self.diagnostics),
        }


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _locator_text(locator: Mapping[str, Any]) -> str:
    sheet = locator.get("sheet")
    row = locator.get("row")
    if sheet and row:
        return f"工作表 {sheet} 第 {row} 行"
    if row:
        return f"第 {row} 行"
    paragraph = locator.get("paragraph")
    if paragraph:
        return f"第 {paragraph} 段"
    page = locator.get("page")
    if page:
        return f"第 {page} 页"
    page_start = locator.get("page_start")
    page_end = locator.get("page_end")
    if page_start and page_end and page_start != page_end:
        return f"第 {page_start}-{page_end} 页"
    if page_start:
        return f"第 {page_start} 页"
    return "来源定位"
