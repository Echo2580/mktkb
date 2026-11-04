"""T001：Trace / Evaluation / Gate 数据契约 v0.1。

本模块只包含枚举、Schema 版本常量、路径感知必需 Span 规则与冻结的
``TraceRecord`` / ``SpanRecord``；顶层只 import 标准库，不引入 ``qa`` / ``rag`` /
``conversations`` / ``main`` 等业务包（延迟导入由 ``versioning`` 负责），避免循环依赖。

设计来源：``docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md``
§6.3（Trace 字段）与 §6.4（Span 名称与路径感知完整性）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

# 三套独立版本常量：Trace / Evaluation Case / Release Gate。
TRACE_SCHEMA_VERSION = "mktkb.trace.v0.1"
CASE_SCHEMA_VERSION = "mktkb.eval.case.v0.1"
GATE_SCHEMA_VERSION = "mktkb.gate.v0.1"


class TraceMode(StrEnum):
    """一次执行的运行模式；P0 只允许 replay / local，live 禁止。"""

    REPLAY = "replay"
    LOCAL = "local"
    LIVE = "live"


class TracePath(StrEnum):
    """执行路径；``legacy_with_rag_candidates`` 表示 legacy 作答但带 RAG 候选。"""

    RAG = "rag"
    LEGACY = "legacy"
    LEGACY_WITH_RAG_CANDIDATES = "legacy_with_rag_candidates"


class OutcomeKind(StrEnum):
    """一次执行尝试的结局。"""

    ANSWER = "answer"
    CLARIFICATION = "clarification"
    NO_ANSWER = "no_answer"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    ERROR = "error"
    NOT_FOUND = "not_found"
    SERVICE_ERROR = "service_error"
    KNOWLEDGE_CHANGED = "knowledge_changed"


# 设计 §6.4「基础必需 Span」表。RAG 与 legacy 各自一张表；
# 表里没有定义的 path + outcome 组合视为契约缺口，调用方必须 fail closed（抛 ValueError）。
_RAG_REQUIRED_SPANS: dict[OutcomeKind, frozenset[str]] = {
    OutcomeKind.ANSWER: frozenset({"parse", "recall", "fuse", "answer", "commit"}),
    OutcomeKind.CONFLICT: frozenset({"parse", "recall", "fuse", "answer", "commit"}),
    OutcomeKind.CLARIFICATION: frozenset({"parse", "commit"}),
    OutcomeKind.NO_ANSWER: frozenset({"parse", "recall", "fuse", "commit"}),
    OutcomeKind.AMBIGUOUS: frozenset({"parse", "recall", "fuse", "commit"}),
    OutcomeKind.ERROR: frozenset({"parse", "commit"}),
    OutcomeKind.KNOWLEDGE_CHANGED: frozenset({"parse", "commit"}),
}

_LEGACY_REQUIRED_SPANS: dict[OutcomeKind, frozenset[str]] = {
    OutcomeKind.ANSWER: frozenset(
        {"intent_parse", "retrieve", "model_answer", "answer_validate", "commit"}
    ),
    OutcomeKind.NOT_FOUND: frozenset({"intent_parse", "retrieve", "commit"}),
    OutcomeKind.CLARIFICATION: frozenset({"intent_parse", "commit"}),
    OutcomeKind.SERVICE_ERROR: frozenset({"intent_parse", "commit"}),
}

# 设计 §6.4「条件必需 Span」：只认这四个属性键；值为真时才要求对应 Span。
_CONDITIONAL_SPANS: tuple[tuple[str, str], ...] = (
    ("vector_enabled", "vector_recall"),
    ("rerank_enabled", "rerank"),
    ("expansion_triggered", "query_expansion"),
    ("index_sync_performed", "index_sync"),
)

# 记录字段里的 mode / path / outcome_kind 使用枚举的字符串值；记录本身保持纯数据。
TraceModeLike = TraceMode | str
TracePathLike = TracePath | str
OutcomeKindLike = OutcomeKind | str


def required_spans(path: TracePathLike, outcome: OutcomeKindLike) -> frozenset[str]:
    """返回 ``path + outcome`` 的基础必需 Span 集合（设计 §6.4）。

    - 传入枚举或等值字符串均可；
    - ``legacy_with_rag_candidates`` 与 ``legacy`` 共用 legacy 规则；
    - 设计表未定义的组合抛 ``ValueError``（fail closed，不静默返回空集）。
    """
    resolved_path = TracePath(path)
    resolved_outcome = OutcomeKind(outcome)
    table = _RAG_REQUIRED_SPANS if resolved_path is TracePath.RAG else _LEGACY_REQUIRED_SPANS
    try:
        return table[resolved_outcome]
    except KeyError:
        raise ValueError(
            "设计 §6.4 未定义 path="
            f"{resolved_path.value!r} + outcome={resolved_outcome.value!r} 的必需 Span 契约"
        ) from None


def conditional_required_spans(attrs: Mapping[str, Any] | None) -> frozenset[str]:
    """按执行属性返回条件必需 Span；只认四个约定键，空/未知属性返回空集。

    属性值为假（``False`` / ``None`` / 缺省）时不要求；为真时要求对应 Span。
    未执行的通道由调用方不写属性即可，不要求也不伪造。
    """
    if not attrs:
        return frozenset()
    return frozenset(span for flag, span in _CONDITIONAL_SPANS if attrs.get(flag))


@dataclass(frozen=True)
class TraceRecord:
    """一条执行尝试的 Trace（设计 §6.3 traces 全字段）。

    字段均为可空默认值，方便 store / tracer 分层填充；必填语义由写入方与门禁保证：
    ``trace_id``、``request_id``、``mode``、``scope``、``path``、``content_mode``、
    ``status`` 在成功写入的记录上必须有值。JSON 字段以 TEXT 存储（canonical JSON）。
    """

    trace_id: str | None = None
    request_id: str | None = None
    http_request_id: str | None = None
    attempt: int = 1
    replayed: bool = False
    previous_trace_id: str | None = None
    trace_schema_version: str = TRACE_SCHEMA_VERSION
    mode: str | None = None
    scope: str | None = None
    path: str | None = None
    case_id: str | None = None
    dataset_version: str | None = None
    run_id: str | None = None
    index_revision: str | None = None
    manifest_sha256: str | None = None
    pipeline_version: str | None = None
    config_hash: str | None = None
    query_kind: str | None = None
    outcome_kind: str | None = None
    reason: str | None = None
    answer_source: str | None = None
    content_mode: str = "hash"
    question_hash: str | None = None
    question_chars: int | None = None
    hash_algo: str | None = None
    hmac_key_id: str | None = None
    user_id_hash: str | None = None
    conversation_id_hash: str | None = None
    retrieval_counts_json: str | None = None
    filter_decisions_json: str | None = None
    fact_gate_json: str | None = None
    citation_refs_json: str | None = None
    pagination_json: str | None = None
    token_usage_json: str | None = None
    cost_json: str | None = None
    go_decision: str | None = None
    degraded_json: str | None = None
    latency_ms: int | None = None
    status: str | None = None
    error_code: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class SpanRecord:
    """一个 Span（设计 §6.3 spans 全字段）；``attributes_json`` 为 canonical JSON 文本。"""

    span_id: str | None = None
    trace_id: str | None = None
    parent_span_id: str | None = None
    name: str | None = None
    started_at: str | None = None
    duration_ms: int | None = None
    status: str | None = None
    attributes_json: str | None = None
    error_code: str | None = None


__all__ = [
    "CASE_SCHEMA_VERSION",
    "GATE_SCHEMA_VERSION",
    "TRACE_SCHEMA_VERSION",
    "OutcomeKind",
    "SpanRecord",
    "TraceMode",
    "TracePath",
    "TraceRecord",
    "conditional_required_spans",
    "required_spans",
]


def validate_required_spans(record: TraceRecord, span_names: Any) -> list[str]:
    """按设计 §6.4 校验一条 Trace 的 Span 完整性，返回排序后的缺失 Span 名称列表。

    T003a 在文件末尾追加的纯函数（不改动本文件既有常量 / 类 / 函数）：

    - 基础必需 Span：``required_spans(record.path, record.outcome_kind)``；
    - 条件必需 Span：执行属性从记录的任意 ``*_json`` 字段载荷中读取，只取该 JSON
      object 的**顶层键**，认 ``vector_enabled`` / ``rerank_enabled`` /
      ``expansion_triggered`` / ``index_sync_performed`` 四个键（T003a 的 tracer 会把
      ``annotate(...)`` 的条件属性并入 ``filter_decisions_json``）；
    - 完整集合返回 ``[]``；缺任意必需 / 条件必需 Span 返回缺失清单；
      ``rag + clarification`` 不要求 ``answer``（规则来自 T001 冻结表）；
    - ``record.path`` 或 ``record.outcome_kind`` 缺失、或属于设计未定义的组合时
      抛 ``ValueError``（fail closed，不返回空集冒充完整）；
    - ``span_names`` 必须是 Span 名称的可迭代对象；单个字符串会抛 ``TypeError``。
    """
    if isinstance(span_names, str):
        raise TypeError(
            "span_names 必须是 Span 名称的可迭代对象（如 list[str]），不能是单个字符串"
        )
    path = record.path
    outcome = record.outcome_kind
    if path is None or outcome is None:
        raise ValueError(
            "TraceRecord 缺少 path 或 outcome_kind，无法判定必需 Span（fail closed）"
        )
    required = set(required_spans(path, outcome))

    from dataclasses import fields as _fields
    import json as _json

    attrs: dict[str, Any] = {}
    for field in _fields(TraceRecord):
        if not field.name.endswith("_json"):
            continue
        payload = getattr(record, field.name, None)
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except (TypeError, ValueError):
                continue  # 不可解析的 JSON 文本不能提供属性证据
        if isinstance(payload, Mapping):
            for flag, _span in _CONDITIONAL_SPANS:
                if flag in payload:
                    attrs[flag] = payload[flag]
    required |= set(conditional_required_spans(attrs))
    return sorted(required - set(span_names))

