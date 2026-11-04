"""MKTKB Observability 内核（P0）。

T001 只落地**纯数据契约与版本绑定**：Schema 版本常量、枚举、路径感知必需 Span 规则、
冻结 ``TraceRecord`` / ``SpanRecord``，以及 ``pipeline_version`` / ``config_hash`` /
问题哈希工具。本包不写 SQLite、不接业务执行路径；store / tracer 由后续任务在同一
包内新增。
"""

from __future__ import annotations

from .contracts import (
    CASE_SCHEMA_VERSION,
    GATE_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    OutcomeKind,
    SpanRecord,
    TraceMode,
    TracePath,
    TraceRecord,
    conditional_required_spans,
    required_spans,
    validate_required_spans,
)
from .tracer import SpanHandle, TraceContext, current_trace, start_trace
from .versioning import (
    CONFIG_HASH_FIELDS,
    config_hash,
    hash_question,
    key_fingerprint,
    pipeline_version,
)

__all__ = [
    "CASE_SCHEMA_VERSION",
    "CONFIG_HASH_FIELDS",
    "GATE_SCHEMA_VERSION",
    "TRACE_SCHEMA_VERSION",
    "OutcomeKind",
    "SpanHandle",
    "SpanRecord",
    "TraceContext",
    "TraceMode",
    "TracePath",
    "TraceRecord",
    "conditional_required_spans",
    "config_hash",
    "current_trace",
    "hash_question",
    "key_fingerprint",
    "pipeline_version",
    "required_spans",
    "start_trace",
    "validate_required_spans",
]
