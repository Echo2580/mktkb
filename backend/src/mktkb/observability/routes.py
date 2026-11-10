"""T113：只读监控 API（设计 §6）。

四个端点全部是 ``GET``，全部要求管理员角色，全部只返回**哈希 / 计数 / 长度 / 时长 /
成本 / 状态**类字段：

- ``GET /observability/traces/{trace_id}``：单条 trace 摘要 + span 摘要；
- ``GET /observability/requests/{request_id}/traces``：同一产品请求的全部尝试摘要
  （``attempt`` / ``replayed`` / ``previous_trace_id`` 关系）；
- ``GET /observability/metrics?window=24h``：按 ``path`` / ``outcome`` 聚合的条数、
  P50/P95 延迟、token、成本与 degraded 次数；
- ``GET /observability/runs/{run_id}``：评测 run 的 manifest / summary / gate 聚合。

隐私与降级口径：

- 不返回问题原文、答案原文、上下文正文、``*_json`` 原文、SQL / 库路径或凭据；span
  只返回属性键名与属性个数。响应模型是显式白名单，不是 ``asdict`` 透传；
- Trace 关闭（``app.state.trace_repo is None``）时 trace 相关端点返回 200 空聚合 +
  ``degraded_reason="trace_disabled"``；仓储读失败返回 ``trace_unavailable``，都不抛 500；
- 评测 run 只读 ``settings.data_dir/eval/runs/<run_id>`` 下的三份 JSON；``run_id`` 严格
  校验并做目录逃逸检查。holdout run（``suite=holdout`` 或 ``holdout_details=true``）
  只返回聚合，不读取 / 不返回逐题 ``cases.jsonl``、题干或答案；``details_withheld``
  显式说明逐题详情已被扣留。

本模块只依赖标准库、FastAPI/Pydantic 与 ``auth`` / ``errors`` / 本包 ``contracts`` /
``store``；导入时不建目录、不打开数据库、不读 ``.env``。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ..auth.routes import require_role
from ..auth.service import UserContext
from ..errors import ApiError, NotFound
from .contracts import SpanRecord, TraceRecord
from .store import TraceRepository, TraceWriteError

router = APIRouter(prefix="/observability", tags=["observability"])

#: 管理员依赖；四个端点共用（沿用 ``auth/routes.py`` 的 ``require_role``）。
admin_required = Depends(require_role("admin"))

#: trace_id / request_id / run_id 的公共安全字符集：不允许路径分隔符、空白、控制字符。
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
#: 指标窗口只接受 ``Nh`` / ``Nm``（正整数；``24h`` 为默认）。
_WINDOW = re.compile(r"^([1-9][0-9]{0,5})([hm])$")

#: 响应里的错误码；不把内部异常 / 路径 / SQL 暴露给调用方。
_INVALID_WINDOW = "INVALID_WINDOW"
_INVALID_RUN_ID = "INVALID_RUN_ID"
_INVALID_TRACE_ID = "INVALID_TRACE_ID"
_INVALID_REQUEST_ID = "INVALID_REQUEST_ID"
_TRACE_NOT_FOUND = "TRACE_NOT_FOUND"
_RUN_NOT_FOUND = "RUN_NOT_FOUND"

class _InvalidParameter(ApiError):
    """请求参数不合法（422）；沿用全局错误信封，不回显提交值。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 422)


class _TraceNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__(_TRACE_NOT_FOUND, "Trace 不存在")


class _RunNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__(_RUN_NOT_FOUND, "评测 run 不存在")


# --------------------------------------------------------------------------- #
# 响应模型（显式白名单：只允许哈希 / 计数 / 长度 / 时长 / 成本 / 状态）
# --------------------------------------------------------------------------- #


class SpanSummary(BaseModel):
    """单个 Span 的只读摘要；``attributes_json`` 原文不返回。"""

    span_id: str | None = None
    parent_span_id: str | None = None
    name: str | None = None
    started_at: str | None = None
    duration_ms: int | None = None
    status: str | None = None
    error_code: str | None = None
    attribute_count: int = 0
    attribute_keys: list[str] = Field(default_factory=list)


class TraceSummary(BaseModel):
    """一条 trace 的只读摘要；不含问题/答案/上下文原文与 ``*_json``。"""

    trace_id: str | None = None
    request_id: str | None = None
    http_request_id: str | None = None
    attempt: int = 1
    replayed: bool = False
    previous_trace_id: str | None = None
    mode: str | None = None
    scope: str | None = None
    path: str | None = None
    content_mode: str = "hash"
    query_kind: str | None = None
    outcome_kind: str | None = None
    reason: str | None = None
    answer_source: str | None = None
    status: str | None = None
    error_code: str | None = None
    latency_ms: int | None = None
    created_at: str | None = None
    question_hash: str | None = None
    question_chars: int | None = None
    hash_algo: str | None = None
    hmac_key_id: str | None = None
    user_id_hash: str | None = None
    conversation_id_hash: str | None = None
    go_decision: str | None = None
    index_revision: str | None = None
    manifest_sha256: str | None = None
    pipeline_version: str | None = None
    config_hash: str | None = None
    span_count: int | None = None


class TraceDetailResponse(BaseModel):
    trace: TraceSummary | None = None
    spans: list[SpanSummary] = Field(default_factory=list)
    degraded_reason: str | None = None


class RequestTracesResponse(BaseModel):
    request_id: str
    traces: list[TraceSummary] = Field(default_factory=list)
    degraded_reason: str | None = None


class MetricGroup(BaseModel):
    path: str
    outcome: str
    count: int
    latency_samples: int
    latency_ms_p50: int | None = None
    latency_ms_p95: int | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0
    cost_cny: float = 0.0
    degraded_count: int = 0
    error_count: int = 0


class MetricsResponse(BaseModel):
    window: str
    since: str
    until: str
    total_traces: int
    invalid_created_at_count: int = 0
    invalid_payload_count: int = 0
    groups: list[MetricGroup] = Field(default_factory=list)
    degraded_reason: str | None = None


class RunManifestSummary(BaseModel):
    """``run_manifest.json`` 的聚合白名单；不返回 dataset_path / corpus_dir 等路径。"""

    run_id: str | None = None
    mode: str | None = None
    scope: str | None = None
    suite: str | None = None
    dataset_version: str | None = None
    dataset_sha256: str | None = None
    corpus_manifest_sha256: str | None = None
    business_date: str | None = None
    index_revision: int | None = None
    pipeline_version: str | None = None
    gate_version: str | None = None
    label_version: str | None = None
    created_at: str | None = None
    case_count: int | None = None
    config_hash: str | None = None
    holdout_details: bool = False
    holdout_labels_sha256: str | None = None
    multi_turn_case_count: int = 0
    multi_turn_turns_executed: int = 0


class HoldoutSummary(BaseModel):
    """holdout 只保留聚合与哈希；不返回逐题 / 题干 / 答案 / 审计正文。"""

    aggregate_only: bool | None = None
    details_written: bool | None = None
    label_version: str | None = None
    questions_sha256: str | None = None
    labels_sha256: str | None = None
    strata: dict[str, int] = Field(default_factory=dict)
    metadata_mismatch_count: int | None = None
    traces_persisted: bool | None = None


class RunSummaryBlock(BaseModel):
    """``summary.json`` 的聚合白名单；不返回 metrics_scope / declarations 等明细。"""

    run_id: str | None = None
    mode: str | None = None
    suite: str | None = None
    scope: str | None = None
    dataset_version: str | None = None
    dataset_sha256: str | None = None
    corpus_manifest_sha256: str | None = None
    business_date: str | None = None
    index_revision: int | None = None
    pipeline_version: str | None = None
    gate_version: str | None = None
    case_count: int | None = None
    scored_count: int | None = None
    skipped_ocr_count: int | None = None
    error_count: int | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, int | float] = Field(default_factory=dict)
    retrieval_only: bool = False
    holdout: HoldoutSummary | None = None


class GateSummary(BaseModel):
    """``gate.json`` 的聚合白名单；不返回 failures / unknowns 的 evidence 明细。"""

    exit_code: int | None = None
    run_id: str | None = None
    suite: str | None = None
    mode: str | None = None
    gate_version: str | None = None
    scored_count: int | None = None
    min_sample: int | None = None
    hard_failures: list[str] = Field(default_factory=list)
    gate_status: dict[str, str] = Field(default_factory=dict)
    failure_count: int = 0
    unknown_count: int = 0
    not_applicable_count: int = 0
    warnings_count: int = 0
    quality_status: str | None = None


class RunResponse(BaseModel):
    run_id: str
    holdout_detected: bool = False
    details_withheld: bool = False
    manifest: RunManifestSummary | None = None
    summary: RunSummaryBlock | None = None
    gate: GateSummary | None = None
    degraded_reason: str | None = None


# --------------------------------------------------------------------------- #
# 参数校验与通用转换
# --------------------------------------------------------------------------- #


def _validate_id(value: str, *, code: str, label: str) -> str:
    """校验 trace_id / request_id / run_id：只允许安全字符集，拒绝 ``..`` 与结尾点。"""
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or ".." in value
        or value.endswith(".")
    ):
        raise _InvalidParameter(code, f"{label} 不合法")
    return value


def _parse_window(window: str) -> timedelta:
    """解析 ``Nh`` / ``Nm`` 窗口；非法值抛 422，不回显提交值。"""
    match = _WINDOW.fullmatch(window or "")
    if match is None:
        raise _InvalidParameter(_INVALID_WINDOW, "window 只接受 Nh 或 Nm（N 为正整数）")
    amount = int(match.group(1))
    return timedelta(hours=amount) if match.group(2) == "h" else timedelta(minutes=amount)


def _utc_iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _as_optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _attribute_summary(attributes_json: str | None) -> tuple[int, list[str]]:
    """span 只返回属性个数与键名（排序）；JSON 原文或键值一律不返回。"""
    if not isinstance(attributes_json, str) or not attributes_json:
        return 0, []
    try:
        payload = json.loads(attributes_json)
    except (TypeError, ValueError):
        return 0, []
    if not isinstance(payload, Mapping):
        return 0, []
    keys = sorted(str(key) for key in payload)
    return len(keys), keys


def _trace_summary(record: TraceRecord, *, span_count: int | None = None) -> TraceSummary:
    """把冻结的 ``TraceRecord`` 裁剪成响应白名单（不读 ``*_json`` 原文）。"""
    return TraceSummary(
        trace_id=record.trace_id,
        request_id=record.request_id,
        http_request_id=record.http_request_id,
        attempt=record.attempt,
        replayed=record.replayed,
        previous_trace_id=record.previous_trace_id,
        mode=record.mode,
        scope=record.scope,
        path=record.path,
        content_mode=record.content_mode,
        query_kind=record.query_kind,
        outcome_kind=record.outcome_kind,
        reason=record.reason,
        answer_source=record.answer_source,
        status=record.status,
        error_code=record.error_code,
        latency_ms=record.latency_ms,
        created_at=record.created_at,
        question_hash=record.question_hash,
        question_chars=record.question_chars,
        hash_algo=record.hash_algo,
        hmac_key_id=record.hmac_key_id,
        user_id_hash=record.user_id_hash,
        conversation_id_hash=record.conversation_id_hash,
        go_decision=record.go_decision,
        index_revision=record.index_revision,
        manifest_sha256=record.manifest_sha256,
        pipeline_version=record.pipeline_version,
        config_hash=record.config_hash,
        span_count=span_count,
    )


def _span_summary(span: SpanRecord) -> SpanSummary:
    count, keys = _attribute_summary(span.attributes_json)
    return SpanSummary(
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        name=span.name,
        started_at=span.started_at,
        duration_ms=span.duration_ms,
        status=span.status,
        error_code=span.error_code,
        attribute_count=count,
        attribute_keys=keys,
    )


# --------------------------------------------------------------------------- #
# 指标聚合
# --------------------------------------------------------------------------- #


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _json_object(text: str | None) -> tuple[dict[str, Any] | None, bool]:
    """返回 ``(object, parse_error)``；空值/合法空对象不是解析失败。"""
    if text is None or not isinstance(text, str) or not text.strip():
        return None, False
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None, True
    return (payload, False) if isinstance(payload, dict) else (None, True)


def _token_usage(record: TraceRecord) -> tuple[int, int, int, bool, bool]:
    """返回 ``(input, output, total, has_usage, parse_error)``。"""
    payload, parse_error = _json_object(record.token_usage_json)
    if payload is None:
        return 0, 0, 0, False, parse_error
    tokens_in = None
    for key in ("input", "prompt_tokens", "input_tokens"):
        tokens_in = _non_negative_int(payload.get(key))
        if tokens_in is not None:
            break
    tokens_out = None
    for key in ("output", "completion_tokens", "output_tokens"):
        tokens_out = _non_negative_int(payload.get(key))
        if tokens_out is not None:
            break
    total = _non_negative_int(payload.get("total_tokens"))
    if tokens_in is None and tokens_out is None and total is None:
        return 0, 0, 0, False, False
    tokens_in = tokens_in or 0
    tokens_out = tokens_out or 0
    if total is None:
        total = tokens_in + tokens_out
    return tokens_in, tokens_out, total, True, False


def _cost_cny(record: TraceRecord) -> tuple[float, bool, bool]:
    """返回 ``(cost, has_cost, parse_error)``；只认 ``cny`` / ``cost_cny``。"""
    payload, parse_error = _json_object(record.cost_json)
    if payload is None:
        return 0.0, False, parse_error
    for key in ("cny", "cost_cny"):
        value = _non_negative_number(payload.get(key))
        if value is not None:
            return value, True, False
    return 0.0, False, False


def _degraded(record: TraceRecord) -> tuple[bool, bool]:
    """返回 ``(is_degraded, parse_error)``；不可解析按 degraded fail-safe 计。"""
    text = record.degraded_json
    if text is None or not isinstance(text, str) or not text.strip():
        return False, False
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return True, True
    if payload is None:
        return False, False
    if isinstance(payload, (list, dict, tuple, set, frozenset)):
        return bool(payload), False
    return True, False


def _is_error(record: TraceRecord) -> bool:
    return record.status == "error" or record.outcome_kind in {"error", "service_error"}


def _percentile(values: list[int], percentile: int) -> int | None:
    """最近秩百分位（nearest-rank）：P50 取第 ``ceil(0.5*n)`` 个；无样本返回 None。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


class _GroupAccumulator:
    """单个 ``(path, outcome)`` 分组的聚合中间态。"""

    __slots__ = (
        "count",
        "latencies",
        "tokens_input",
        "tokens_output",
        "tokens_total",
        "cost_cny",
        "degraded_count",
        "error_count",
    )

    def __init__(self) -> None:
        self.count = 0
        self.latencies: list[int] = []
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_total = 0
        self.cost_cny = 0.0
        self.degraded_count = 0
        self.error_count = 0


def _aggregate(
    records: list[TraceRecord],
) -> tuple[list[MetricGroup], int]:
    """按 ``(path, outcome)`` 聚合；返回 ``(groups, invalid_payload_count)``。"""
    groups: dict[tuple[str, str], _GroupAccumulator] = {}
    invalid_payloads = 0
    for record in records:
        key = (record.path or "unknown", record.outcome_kind or "unknown")
        group = groups.get(key)
        if group is None:
            group = groups[key] = _GroupAccumulator()
        group.count += 1

        latency = _non_negative_int(record.latency_ms)
        if latency is not None:
            group.latencies.append(latency)

        tokens_in, tokens_out, tokens_total, _has_usage, usage_error = _token_usage(record)
        group.tokens_input += tokens_in
        group.tokens_output += tokens_out
        group.tokens_total += tokens_total
        cost, _has_cost, cost_error = _cost_cny(record)
        group.cost_cny += cost
        degraded, degraded_error = _degraded(record)
        if degraded:
            group.degraded_count += 1
        if _is_error(record):
            group.error_count += 1
        if usage_error or cost_error or degraded_error:
            invalid_payloads += 1

    result = [
        MetricGroup(
            path=path,
            outcome=outcome,
            count=group.count,
            latency_samples=len(group.latencies),
            latency_ms_p50=_percentile(group.latencies, 50),
            latency_ms_p95=_percentile(group.latencies, 95),
            tokens_input=group.tokens_input,
            tokens_output=group.tokens_output,
            tokens_total=group.tokens_total,
            cost_cny=round(group.cost_cny, 6),
            degraded_count=group.degraded_count,
            error_count=group.error_count,
        )
        for (path, outcome), group in sorted(groups.items())
    ]
    return result, invalid_payloads


# --------------------------------------------------------------------------- #
# 评测 run 读取
# --------------------------------------------------------------------------- #


def _read_json_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    """只读解析 JSON object；返回 ``(payload, status)``，status 为 ok/missing/invalid。"""
    try:
        if not path.is_file():
            return None, "missing"
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None, "invalid"
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None, "invalid"
    return (payload, "ok") if isinstance(payload, dict) else (None, "invalid")


def _run_directory(settings: Any, run_id: str) -> Path:
    """定位 run 目录并阻断路径穿越 / 符号链接逃逸；不存在抛 404。"""
    runs_root = Path(settings.data_dir) / "eval" / "runs"
    candidate = runs_root / run_id
    try:
        root = runs_root.resolve()
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        raise _RunNotFound() from None
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise _RunNotFound()
    return resolved


def _manifest_summary(payload: Mapping[str, Any]) -> RunManifestSummary:
    return RunManifestSummary(
        run_id=_as_optional_str(payload.get("run_id")),
        mode=_as_optional_str(payload.get("mode")),
        scope=_as_optional_str(payload.get("scope")),
        suite=_as_optional_str(payload.get("suite")),
        dataset_version=_as_optional_str(payload.get("dataset_version")),
        dataset_sha256=_as_optional_str(payload.get("dataset_sha256")),
        corpus_manifest_sha256=_as_optional_str(payload.get("corpus_manifest_sha256")),
        business_date=_as_optional_str(payload.get("business_date")),
        index_revision=_as_optional_int(payload.get("index_revision")),
        pipeline_version=_as_optional_str(payload.get("pipeline_version")),
        gate_version=_as_optional_str(payload.get("gate_version")),
        label_version=_as_optional_str(payload.get("label_version")),
        created_at=_as_optional_str(payload.get("created_at")),
        case_count=_as_optional_int(payload.get("case_count")),
        config_hash=_as_optional_str(payload.get("config_hash")),
        holdout_details=_as_bool(payload.get("holdout_details")),
        holdout_labels_sha256=_as_optional_str(payload.get("holdout_labels_sha256")),
        multi_turn_case_count=_as_optional_int(payload.get("multi_turn_case_count")) or 0,
        multi_turn_turns_executed=_as_optional_int(payload.get("multi_turn_turns_executed")) or 0,
    )


def _flatten_numeric(
    payload: Any, *, prefix: str = "", depth: int = 0, budget: list[int] | None = None
) -> dict[str, int | float]:
    """把嵌套指标压平为 ``a.b`` 数值键；只保留 int/float，最多 200 个键。"""
    if not isinstance(payload, Mapping) or depth > 2:
        return {}
    if budget is None:
        budget = [200]
    result: dict[str, int | float] = {}
    for key, value in payload.items():
        if budget[0] <= 0:
            break
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                continue
            result[name] = value
            budget[0] -= 1
        elif isinstance(value, Mapping):
            nested = _flatten_numeric(value, prefix=name, depth=depth + 1, budget=budget)
            result.update(nested)
    return result


def _holdout_summary(payload: Any) -> HoldoutSummary | None:
    if not isinstance(payload, Mapping):
        return None
    strata: dict[str, int] = {}
    raw_strata = payload.get("strata")
    if isinstance(raw_strata, Mapping):
        for key, value in raw_strata.items():
            count = _as_optional_int(value)
            if count is not None:
                strata[str(key)] = count
    return HoldoutSummary(
        aggregate_only=payload.get("aggregate_only") if isinstance(payload.get("aggregate_only"), bool) else None,
        details_written=payload.get("details_written") if isinstance(payload.get("details_written"), bool) else None,
        label_version=_as_optional_str(payload.get("label_version")),
        questions_sha256=_as_optional_str(payload.get("questions_sha256")),
        labels_sha256=_as_optional_str(payload.get("labels_sha256")),
        strata=strata,
        metadata_mismatch_count=_as_optional_int(payload.get("metadata_mismatch_count")),
        traces_persisted=payload.get("traces_persisted") if isinstance(payload.get("traces_persisted"), bool) else None,
    )


def _status_counts(payload: Any) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, value in payload.items():
        count = _as_optional_int(value)
        if count is not None:
            result[str(key)] = count
    return dict(sorted(result.items()))


def _summary_block(payload: Mapping[str, Any]) -> RunSummaryBlock:
    retrieval_only = payload.get("retrieval_only")
    return RunSummaryBlock(
        run_id=_as_optional_str(payload.get("run_id")),
        mode=_as_optional_str(payload.get("mode")),
        suite=_as_optional_str(payload.get("suite")),
        scope=_as_optional_str(payload.get("scope")),
        dataset_version=_as_optional_str(payload.get("dataset_version")),
        dataset_sha256=_as_optional_str(payload.get("dataset_sha256")),
        corpus_manifest_sha256=_as_optional_str(payload.get("corpus_manifest_sha256")),
        business_date=_as_optional_str(payload.get("business_date")),
        index_revision=_as_optional_int(payload.get("index_revision")),
        pipeline_version=_as_optional_str(payload.get("pipeline_version")),
        gate_version=_as_optional_str(payload.get("gate_version")),
        case_count=_as_optional_int(payload.get("case_count")),
        scored_count=_as_optional_int(payload.get("scored_count")),
        skipped_ocr_count=_as_optional_int(payload.get("skipped_ocr_count")),
        error_count=_as_optional_int(payload.get("error_count")),
        status_counts=_status_counts(payload.get("status_counts")),
        metrics=_flatten_numeric(payload.get("metrics")),
        retrieval_only=retrieval_only if isinstance(retrieval_only, bool) else False,
        holdout=_holdout_summary(payload.get("holdout")),
    )


def _gate_summary(payload: Mapping[str, Any]) -> GateSummary:
    hard_failures: list[str] = []
    raw_failures = payload.get("hard_failures")
    if isinstance(raw_failures, list):
        hard_failures = [str(item) for item in raw_failures if isinstance(item, str)]

    gate_status: dict[str, str] = {}
    raw_status = payload.get("gate_status")
    if isinstance(raw_status, Mapping):
        for key, value in raw_status.items():
            if isinstance(value, str):
                gate_status[str(key)] = value

    quality_status = None
    quality = payload.get("quality")
    if isinstance(quality, Mapping) and isinstance(quality.get("status"), str):
        quality_status = quality["status"]

    def _list_len(value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    return GateSummary(
        exit_code=_as_optional_int(payload.get("exit_code")),
        run_id=_as_optional_str(payload.get("run_id")),
        suite=_as_optional_str(payload.get("suite")),
        mode=_as_optional_str(payload.get("mode")),
        gate_version=_as_optional_str(payload.get("gate_version")),
        scored_count=_as_optional_int(payload.get("scored_count")),
        min_sample=_as_optional_int(payload.get("min_sample")),
        hard_failures=hard_failures,
        gate_status=gate_status,
        failure_count=_list_len(payload.get("failures")),
        unknown_count=_list_len(payload.get("unknowns")),
        not_applicable_count=_list_len(payload.get("not_applicable")),
        warnings_count=_list_len(payload.get("warnings")),
        quality_status=quality_status,
    )


def _trace_repo(request: Request) -> TraceRepository | None:
    return getattr(request.app.state, "trace_repo", None)


def _trace_disabled(request: Request) -> bool:
    return _trace_repo(request) is None


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #


@router.get(
    "/traces/{trace_id}",
    response_model=TraceDetailResponse,
    summary="查询单次执行 Trace（仅哈希/计数/时长/状态）",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_trace(
    trace_id: str,
    request: Request,
    _user: UserContext = admin_required,
) -> TraceDetailResponse:
    trace_id = _validate_id(trace_id, code=_INVALID_TRACE_ID, label="trace_id")
    repo = _trace_repo(request)
    if repo is None:
        return TraceDetailResponse(degraded_reason="trace_disabled")
    try:
        record, spans = repo.get(trace_id)
    except KeyError:
        raise _TraceNotFound() from None
    except TraceWriteError:
        return TraceDetailResponse(degraded_reason="trace_unavailable")
    return TraceDetailResponse(
        trace=_trace_summary(record, span_count=len(spans)),
        spans=[_span_summary(span) for span in spans],
    )


@router.get(
    "/requests/{request_id}/traces",
    response_model=RequestTracesResponse,
    summary="查询同一产品请求的全部 Trace 尝试",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_request_traces(
    request_id: str,
    request: Request,
    _user: UserContext = admin_required,
) -> RequestTracesResponse:
    request_id = _validate_id(request_id, code=_INVALID_REQUEST_ID, label="request_id")
    repo = _trace_repo(request)
    if repo is None:
        return RequestTracesResponse(request_id=request_id, degraded_reason="trace_disabled")
    try:
        records = repo.list_by_request(request_id)
    except TraceWriteError:
        return RequestTracesResponse(request_id=request_id, degraded_reason="trace_unavailable")
    return RequestTracesResponse(
        request_id=request_id,
        traces=[_trace_summary(record) for record in records],
    )


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="按 path/outcome 聚合 Trace 指标",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_metrics(
    request: Request,
    window: str = Query(default="24h", description="聚合窗口，如 24h / 30m"),
    _user: UserContext = admin_required,
) -> MetricsResponse:
    delta = _parse_window(window)
    until = datetime.now(timezone.utc)
    since = until - delta
    window_text = window
    repo = _trace_repo(request)
    if repo is None:
        return MetricsResponse(
            window=window_text,
            since=_utc_iso(since),
            until=_utc_iso(until),
            total_traces=0,
            degraded_reason="trace_disabled",
        )
    try:
        records, invalid_created_at = repo.list_window(since)
    except TraceWriteError:
        return MetricsResponse(
            window=window_text,
            since=_utc_iso(since),
            until=_utc_iso(until),
            total_traces=0,
            degraded_reason="trace_unavailable",
        )
    groups, invalid_payloads = _aggregate(records)
    degraded_reason = "partial_data" if (invalid_created_at or invalid_payloads) else None
    return MetricsResponse(
        window=window_text,
        since=_utc_iso(since),
        until=_utc_iso(until),
        total_traces=sum(group.count for group in groups),
        invalid_created_at_count=invalid_created_at,
        invalid_payload_count=invalid_payloads,
        groups=groups,
        degraded_reason=degraded_reason,
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    summary="查询评测 run 的 manifest/summary/gate 聚合",
    responses={401: {"description": "未登录"}, 403: {"description": "需要管理员权限"}},
)
def get_run(
    run_id: str,
    request: Request,
    _user: UserContext = admin_required,
) -> RunResponse:
    run_id = _validate_id(run_id, code=_INVALID_RUN_ID, label="run_id")
    settings = request.app.state.settings
    run_dir = _run_directory(settings, run_id)

    manifest, manifest_status = _read_json_object(run_dir / "run_manifest.json")
    if manifest_status == "missing":
        raise _RunNotFound()
    summary, summary_status = _read_json_object(run_dir / "summary.json")
    gate, gate_status = _read_json_object(run_dir / "gate.json")

    manifest_suite = _as_optional_str(manifest.get("suite")) if manifest else None
    summary_suite = _as_optional_str(summary.get("suite")) if summary else None
    holdout_details = _as_bool(manifest.get("holdout_details")) if manifest else False
    cases_present = (run_dir / "cases.jsonl").is_file()
    holdout_suite = manifest_suite == "holdout" or summary_suite == "holdout"
    # 只有 holdout run 的逐题文件才算“详情”；普通 suite 的 cases.jsonl 不是 holdout 明细。
    holdout_detected = holdout_suite or holdout_details
    details_withheld = bool(holdout_detected and (holdout_details or cases_present))

    reasons: list[str] = []
    if _trace_disabled(request):
        reasons.append("trace_disabled")
    if manifest_status == "invalid":
        reasons.append("manifest_invalid")
    if summary_status == "invalid":
        reasons.append("summary_invalid")
    if gate_status == "invalid":
        reasons.append("gate_invalid")

    return RunResponse(
        run_id=run_id,
        holdout_detected=holdout_detected,
        details_withheld=details_withheld,
        manifest=_manifest_summary(manifest) if manifest else None,
        summary=_summary_block(summary) if summary else None,
        gate=_gate_summary(gate) if gate else None,
        degraded_reason=reasons[0] if reasons else None,
    )


__all__ = ["router"]
