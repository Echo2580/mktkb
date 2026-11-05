"""T003a：请求级 Trace 内核（设计 §6.1 / §6.3 / §6.4 / §6.5 / §6.6）。

本模块只做**观测内核**，不接业务代码：

- ``start_trace`` 用 ``contextvars`` 建立请求级 ``TraceContext``，退出时自动 ``finish``；
- ``current_trace()`` 返回当前上下文中的 Trace，没有正在执行的 Trace 时返回 ``None``；
- ``TraceContext.span(name, **attrs)`` 用 ``contextvars`` 维护 Span 栈，自动填
  ``parent_span_id`` / ``started_at`` / ``duration_ms`` / ``status`` / ``attributes_json``；
- ``finish`` 把 ``TraceRecord`` + ``SpanRecord`` 交给 ``TraceRepository.write_best_effort``
  （设计 §6.6：写入失败不抛、不中断调用方）；没有 repo 时不写、不创建任何 DB 文件；
- 内容模式实现 ``off`` 与默认 ``hash``（无 key 走 sha256，有 key 走 hmac-sha256）；
  ``redacted`` / ``full`` 在 P0 未实现，``start_trace`` 显式 fail closed（``ValueError``）；
- 路径感知完整性校验 ``validate_required_spans`` 由 T001 的 ``contracts`` 末尾追加。

本模块顶层只 import 标准库 + ``.contracts`` / ``.versioning``（``.store`` 只在
``TYPE_CHECKING`` 下做类型引用），不 import ``qa`` / ``rag`` / ``conversations`` / ``main`` /
``config`` 等业务包；测试只写 ``tmp_path``，零真实模型 / OCR / embedding / rerank 调用，
不读环境变量文件、不访问外网、不打印凭据。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from .contracts import (
    _CONDITIONAL_SPANS,
    OutcomeKind,
    SpanRecord,
    TraceMode,
    TracePath,
    TraceRecord,
)
from .versioning import hash_question, key_fingerprint

if TYPE_CHECKING:  # pragma: no cover - 只为类型标注，运行期不 import 存储层
    from .store import TraceRepository

LOGGER = logging.getLogger(__name__)

#: 当前请求上下文中的 Trace（contextvar：线程 / asyncio task 各自独立）。
_CURRENT_TRACE: ContextVar["TraceContext | None"] = ContextVar(
    "mktkb.trace.current", default=None
)
#: 当前 Trace 内的 Span 栈（只存 span_id；只在线程内部生效，不跨线程共享可变对象）。
_SPAN_STACK: ContextVar[tuple[str, ...]] = ContextVar(
    "mktkb.trace.span_stack", default=()
)

# 内容模式（设计 §6.5）：P0 只实现最保守的两种。
CONTENT_MODE_HASH = "hash"
CONTENT_MODE_OFF = "off"
_SUPPORTED_CONTENT_MODES = frozenset({CONTENT_MODE_OFF, CONTENT_MODE_HASH})
#: 设计允许、但 P0 未实现 → 显式 fail closed，防止真实数据被当默认值落盘。
_UNIMPLEMENTED_CONTENT_MODES = frozenset({"redacted", "full"})

HASH_ALGO_SHA256 = "sha256"
HASH_ALGO_HMAC_SHA256 = "hmac-sha256"

# Trace 状态（设计 §6.3 status：ok / replayed / error 等）。
TRACE_STATUS_OK = "ok"
TRACE_STATUS_ERROR = "error"
TRACE_STATUS_INCOMPLETE = "incomplete"
TRACE_STATUS_REPLAYED = "replayed"

SPAN_STATUS_OK = "ok"
SPAN_STATUS_ERROR = "error"

#: 这两个业务结局代表执行失败，Trace.status 同步记为 error（其余结局记 ok）。
_ERROR_OUTCOMES = frozenset({OutcomeKind.ERROR, OutcomeKind.SERVICE_ERROR})

_TRACE_FIELD_NAMES = frozenset(field.name for field in fields(TraceRecord))
_JSON_FIELD_NAMES = frozenset(
    name for name in _TRACE_FIELD_NAMES if name.endswith("_json")
)
_FLAGS_FIELD = "filter_decisions_json"
#: 条件必需 Span 的四个执行属性键（与 T001 contracts 的规则单一来源）。
_RETRIEVAL_FLAGS = tuple(flag for flag, _span in _CONDITIONAL_SPANS)

#: 这些 Trace 字段由内核计算 / 标识，禁止 annotate 覆盖（伪造 status 会破坏完整性语义）。
_RESERVED_TRACE_FIELDS = frozenset(
    {
        "trace_id",
        "trace_schema_version",
        "created_at",
        "latency_ms",
        "status",
        "question_hash",
        "question_chars",
        "hash_algo",
        "hmac_key_id",
    }
)
#: Span 的标识 / 计时字段禁止通过 annotate 覆盖；status / error_code 走字段级覆盖。
_RESERVED_SPAN_FIELDS = frozenset(
    {
        "span_id",
        "trace_id",
        "parent_span_id",
        "name",
        "started_at",
        "duration_ms",
        "attributes_json",
    }
)


# ---- 通用工具 ----


def _utc_now_iso() -> str:
    """UTC ISO-8601 文本（设计 §6.3 created_at / started_at 口径）。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _elapsed_ms(started_monotonic: float) -> int:
    """单调时钟耗时（毫秒，非负整数）；单调时钟不受系统时间跳变影响。"""
    return max(0, int(round((time.perf_counter() - started_monotonic) * 1000.0)))


def _json_default(value: Any) -> Any:
    """canonical JSON 的稳定兜底编码（与 T001 versioning 口径一致）。"""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (set, frozenset)):
        return sorted(str(item) for item in value)
    raise TypeError(f"无法稳定序列化到 trace attributes 的类型：{type(value).__name__}")


def _canonical_json(payload: Any) -> str:
    """设计 §6.2 canonical JSON：ensure_ascii=False, sort_keys=True。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _current_span_id() -> str | None:
    stack = _SPAN_STACK.get()
    return stack[-1] if stack else None


def _coerce_mode(mode: TraceMode | str) -> TraceMode:
    try:
        return TraceMode(mode)
    except ValueError:
        raise ValueError(
            "mode 只允许 TraceMode.REPLAY / LOCAL / LIVE，收到 "
            f"{mode!r}（P0 调用方不得使用 live，见设计 §9）"
        ) from None


def _coerce_path(path: TracePath | str | None) -> TracePath | None:
    if path is None:
        return None
    try:
        return TracePath(path)
    except ValueError:
        raise ValueError(
            f"path 只允许 TracePath / 其字符串值 / None，收到 {path!r}"
        ) from None


def _coerce_outcome(outcome: OutcomeKind | str) -> OutcomeKind:
    try:
        return OutcomeKind(outcome)
    except ValueError:
        raise ValueError(f"outcome 不是合法的 OutcomeKind：{outcome!r}") from None


def _coerce_content_mode(content_mode: str) -> str:
    if not isinstance(content_mode, str):
        raise TypeError(f"content_mode 必须是 str，收到 {type(content_mode).__name__}")
    if content_mode in _UNIMPLEMENTED_CONTENT_MODES:
        raise ValueError(
            f"content_mode={content_mode!r} 在 P0 未实现，显式 fail closed："
            "真实数据只允许 off（默认最保守）或 hash（默认）；"
            "redacted / full 需在后续阶段实现后才能使用"
        )
    if content_mode not in _SUPPORTED_CONTENT_MODES:
        raise ValueError(
            f"content_mode 只允许 {sorted(_SUPPORTED_CONTENT_MODES)}，收到 {content_mode!r}"
        )
    return content_mode


def _coerce_hmac_key(hmac_key: bytes | None) -> bytes | None:
    if hmac_key is None:
        return None
    if not isinstance(hmac_key, (bytes, bytearray, memoryview)):
        raise TypeError("hmac_key 必须是 bytes（或 None）")
    key = bytes(hmac_key)
    return key or None  # 空 key 视为“无 key”→ sha256（设计 §6.5：合成语料可用 sha256）


def _validate_optional_str(name: str, value: str | None) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} 必须是 str 或 None，收到 {type(value).__name__}")


def _normalize_start_arguments(
    *,
    http_request_id: str,
    mode: TraceMode | str,
    scope: str,
    path: TracePath | str | None,
    question: str,
    case_id: str | None,
    attempt: int,
    replayed: bool,
    previous_trace_id: str | None,
    repo: "TraceRepository | None",
    content_mode: str,
    hmac_key: bytes | None,
) -> dict[str, Any]:
    """校验并归一 ``start_trace`` 参数；非法输入 fail closed（抛 TypeError / ValueError）。"""
    if not isinstance(http_request_id, str):
        raise TypeError("http_request_id 必须是 str")
    if not isinstance(scope, str) or not scope:
        raise ValueError("scope 必须是非空 str（retrieval_only / end_to_end）")
    if not isinstance(question, str):
        raise TypeError("question 必须是 str")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError(f"attempt 必须是 >=1 的 int，收到 {attempt!r}")
    _validate_optional_str("case_id", case_id)
    _validate_optional_str("previous_trace_id", previous_trace_id)
    if repo is not None and not callable(getattr(repo, "write_best_effort", None)):
        raise TypeError("repo 必须提供 write_best_effort(record, spans) 方法")
    return {
        "http_request_id": http_request_id,
        "mode": _coerce_mode(mode),
        "scope": scope,
        "path": _coerce_path(path),
        "question": question,
        "case_id": case_id,
        "attempt": attempt,
        "replayed": bool(replayed),
        "previous_trace_id": previous_trace_id,
        "repo": repo,
        "content_mode": _coerce_content_mode(content_mode),
        "hmac_key": _coerce_hmac_key(hmac_key),
    }


def _hash_question_fields(
    question: str | None, content_mode: str, hmac_key: bytes | None
) -> dict[str, Any]:
    """按内容模式生成 question_hash / question_chars / hash_algo / hmac_key_id。

    - 未设置问题：四项均为 None；
    - ``off``：不存摘要，只存字符数（设计 §6.5“只存计数与 ID”）；
    - ``hash``：无 key → sha256；有 key → hmac-sha256 + key 指纹（永不存 key 本身）。
    """
    if question is None:
        return {
            "question_hash": None,
            "question_chars": None,
            "hash_algo": None,
            "hmac_key_id": None,
        }
    if content_mode == CONTENT_MODE_OFF:
        return {
            "question_hash": None,
            "question_chars": len(question),
            "hash_algo": None,
            "hmac_key_id": None,
        }
    if hmac_key:
        return {
            "question_hash": hash_question(question, key=hmac_key, algo=HASH_ALGO_HMAC_SHA256),
            "question_chars": len(question),
            "hash_algo": HASH_ALGO_HMAC_SHA256,
            "hmac_key_id": key_fingerprint(hmac_key),
        }
    return {
        "question_hash": hash_question(question, algo=HASH_ALGO_SHA256),
        "question_chars": len(question),
        "hash_algo": HASH_ALGO_SHA256,
        "hmac_key_id": None,
    }


# ---- Span ----


class SpanHandle:
    """一个 Span 的句柄（``trace.span(name)`` 的上下文管理器产出物）。

    ``span_id`` 在进入时生成；``annotate(**attrs)`` 在 Span 结束前追加属性。
    ``status`` / ``error_code`` 是 Span 字段级覆盖（异常时由内核写 error +
    异常类型名）；其余键进入 ``attributes_json``（canonical JSON）。
    Span 结束后的 ``annotate`` 是 no-op，不会修改已写记录。
    """

    __slots__ = (
        "span_id",
        "name",
        "parent_span_id",
        "started_at",
        "_started_monotonic",
        "_attrs",
        "_status",
        "_error_code",
        "_duration_ms",
        "_finished",
        "_disabled",
    )

    def __init__(
        self, *, span_id: str, name: str, parent_span_id: str | None, started_at: str
    ) -> None:
        self.span_id = span_id
        self.name = name
        self.parent_span_id = parent_span_id
        self.started_at = started_at
        self._started_monotonic = time.perf_counter()
        self._attrs: dict[str, Any] = {}
        self._status = SPAN_STATUS_OK
        self._error_code: str | None = None
        self._duration_ms = 0
        self._finished = False
        self._disabled = False

    def annotate(self, **attrs: Any) -> None:
        """追加 Span 属性（``status`` / ``error_code`` 写字段，其余写 attributes_json）。"""
        if self._disabled or self._finished:
            return
        for key, value in attrs.items():
            if key in _RESERVED_SPAN_FIELDS:
                raise ValueError(f"Span 保留字段不能通过 annotate 覆盖：{key!r}")
            if key == "status":
                if not isinstance(value, str) or not value:
                    raise ValueError("Span status 必须是非空 str")
                self._status = value
            elif key == "error_code":
                if value is not None and not isinstance(value, str):
                    raise ValueError("Span error_code 必须是 str 或 None")
                self._error_code = value
            else:
                self._attrs[key] = value

    def _mark_error(self, exc: BaseException) -> None:
        self._status = SPAN_STATUS_ERROR
        self._error_code = type(exc).__name__

    def _close(self) -> None:
        self._duration_ms = _elapsed_ms(self._started_monotonic)
        self._finished = True

    def __repr__(self) -> str:  # pragma: no cover - 仅调试可读性
        return f"SpanHandle(name={self.name!r}, span_id={self.span_id!r})"


# ---- Trace ----


class TraceContext:
    """一次执行尝试的 Trace 上下文（用 ``start_trace(...)`` 创建，不直接实例化）。

    线程内通过 contextvar 串联；``finish()`` 幂等，重复 / 上下文退出只写一次。
    ``finish`` 之后所有 setter / annotate / span 都是 no-op（记录已定稿）。
    """

    def __init__(
        self,
        *,
        trace_id: str,
        http_request_id: str,
        mode: TraceMode,
        scope: str,
        path: TracePath | None,
        question: str,
        case_id: str | None,
        attempt: int,
        replayed: bool,
        previous_trace_id: str | None,
        repo: "TraceRepository | None",
        content_mode: str,
        hmac_key: bytes | None,
    ) -> None:
        self.trace_id = trace_id
        self._http_request_id = http_request_id
        self._mode = mode
        self._scope = scope
        self._path = path
        self._case_id = case_id
        self._attempt = attempt
        self._replayed = replayed
        self._previous_trace_id = previous_trace_id
        self._repo = repo
        self._content_mode = content_mode
        self._hmac_key = hmac_key

        self._request_id: str | None = None
        self._question: str | None = question or None
        self._outcome: OutcomeKind | None = None
        self._reason: str | None = None
        self._annotations: dict[str, Any] = {}
        self._retrieval_flags: dict[str, bool] = {}
        self._spans: list[SpanHandle] = []
        self._started_monotonic = time.perf_counter()
        self._error_code: str | None = None
        self._has_error = False
        self._finished = False
        self._lock = threading.Lock()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试可读性
        return f"TraceContext(trace_id={self.trace_id!r})"

    # ---- 请求级字段 ----

    def set_request_id(self, request_id: str) -> None:
        """设置产品请求 ID（``ConversationRequest.id``）；空/非 str fail closed。"""
        if self._finished:
            return
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id 必须是非空 str")
        self._request_id = request_id

    def set_question(self, question: str) -> None:
        """设置本次执行的问题原文；``finish`` 时按内容模式只落摘要/长度。"""
        if self._finished:
            return
        if not isinstance(question, str):
            raise TypeError("question 必须是 str")
        self._question = question

    def set_path(self, path: TracePath | str | None) -> None:
        """设置执行路径（rag / legacy / legacy_with_rag_candidates）；抛 ValueError 表示非法值。"""
        if self._finished:
            return
        self._path = _coerce_path(path)

    def set_outcome(
        self, outcome: OutcomeKind | str, reason: str | None = None, **attrs: Any
    ) -> None:
        """设置结局与原因，并可选追加 Trace 字段（等价于再调用一次 ``annotate``）。"""
        if self._finished:
            return
        if reason is not None and not isinstance(reason, str):
            raise TypeError("reason 必须是 str 或 None")
        self._outcome = _coerce_outcome(outcome)
        self._reason = reason
        if attrs:
            self.annotate(**attrs)

    def annotate(self, **attrs: Any) -> None:
        """写入 Trace 级字段（T003c/d 埋点用）。

        - 仅允许 ``TraceRecord`` 字段名，以及设计 §6.4 的四个条件 Span 属性
          （``vector_enabled`` / ``rerank_enabled`` / ``expansion_triggered`` /
          ``index_sync_performed``，会并入 ``filter_decisions_json``）；
        - ``*_json`` 字段接受 str（视为已序列化文本）或可 canonical 序列化的对象；
        - 保留字段（trace_id / status / latency_ms 等内核计算字段）→ ValueError。
        """
        if self._finished:
            return
        for key, value in attrs.items():
            if key in _RETRIEVAL_FLAGS:
                self._retrieval_flags[key] = bool(value)
                continue
            if key in _RESERVED_TRACE_FIELDS:
                raise ValueError(f"Trace 保留字段不能通过 annotate 覆盖：{key!r}")
            if key not in _TRACE_FIELD_NAMES:
                raise ValueError(
                    f"未知的 Trace 字段：{key!r}；只允许 TraceRecord 字段或条件 Span 属性 "
                    f"{list(_RETRIEVAL_FLAGS)}"
                )
            if key == _FLAGS_FIELD:
                value = _normalize_flags_payload(value)
            elif key in _JSON_FIELD_NAMES and value is not None and not isinstance(value, str):
                value = _canonical_json(value)
            self._annotations[key] = value

    # ---- Span ----

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[SpanHandle]:
        """开启一个 Span；退出时自动记录 duration/status/attributes_json。

        支持嵌套（``parent_span_id`` 取当前 Span 栈顶）；未进入的 Span 不产生记录；
        Trace 已 finish 时是 no-op（仍可安全 yield 一个不落库的句柄）。
        """
        if not isinstance(name, str) or not name:
            raise ValueError("span name 必须是非空 str")
        if self._finished:
            disabled = SpanHandle(
                span_id=uuid.uuid4().hex,
                name=name,
                parent_span_id=None,
                started_at=_utc_now_iso(),
            )
            disabled._disabled = True
            disabled._finished = True
            yield disabled
            return
        handle = SpanHandle(
            span_id=uuid.uuid4().hex,
            name=name,
            parent_span_id=_current_span_id(),
            started_at=_utc_now_iso(),
        )
        if attrs:
            handle.annotate(**attrs)  # 非法属性在进入 with 前 fail closed
        self._spans.append(handle)
        token = _SPAN_STACK.set((*_SPAN_STACK.get(), handle.span_id))
        try:
            yield handle
        except BaseException as exc:
            handle._mark_error(exc)
            raise
        finally:
            handle._close()
            _SPAN_STACK.reset(token)

    # ---- 结束与落库 ----

    def finish(self) -> None:
        """组装并 best-effort 写入；幂等、不向调用方抛异常（设计 §6.6）。"""
        with self._lock:
            if self._finished:
                return
            self._finished = True
            try:
                record, spans = self._build_record_and_spans()
            except Exception:  # noqa: BLE001 - 观测内核不得中断调用方
                LOGGER.warning(
                    "trace_assembly_error: trace_id=%r", self.trace_id, exc_info=True
                )
                return
        if self._repo is None:
            return
        try:
            self._repo.write_best_effort(record, spans)
        except Exception:  # noqa: BLE001 - 写入失败不抛、不中断调用方（设计 §6.6）
            LOGGER.warning(
                "trace_finish_error: trace_id=%r", self.trace_id, exc_info=True
            )

    def _capture_exception(self, exc: BaseException) -> None:
        self._has_error = True
        self._error_code = type(exc).__name__

    def _build_record_and_spans(self) -> tuple[TraceRecord, list[SpanRecord]]:
        annotations = dict(self._annotations)
        if self._retrieval_flags:
            merged = _merge_retrieval_flags(annotations.get(_FLAGS_FIELD))
            merged.update(self._retrieval_flags)
            annotations[_FLAGS_FIELD] = _canonical_json(merged)

        record_fields: dict[str, Any] = {
            "trace_id": self.trace_id,
            "request_id": self._request_id,
            "http_request_id": self._http_request_id,
            "attempt": self._attempt,
            "replayed": self._replayed,
            "previous_trace_id": self._previous_trace_id,
            "mode": self._mode.value,
            "scope": self._scope,
            "path": None if self._path is None else self._path.value,
            "case_id": self._case_id,
            "content_mode": self._content_mode,
            "outcome_kind": None if self._outcome is None else self._outcome.value,
            "reason": self._reason,
            "latency_ms": _elapsed_ms(self._started_monotonic),
            "created_at": _utc_now_iso(),
        }
        record_fields.update(
            _hash_question_fields(self._question, self._content_mode, self._hmac_key)
        )
        record_fields.update(annotations)
        if self._error_code is not None and "error_code" not in annotations:
            record_fields["error_code"] = self._error_code
        record_fields["status"] = self._trace_status(record_fields)

        record = TraceRecord(**record_fields)

        open_spans = [handle.name for handle in self._spans if not handle._finished]
        if open_spans:
            LOGGER.warning(
                "trace_finish_with_open_spans: trace_id=%r names=%r",
                self.trace_id,
                open_spans,
            )
        spans = [
            self._to_span_record(handle)
            for handle in self._spans
            if handle._finished
        ]
        return record, spans

    def _trace_status(self, record_fields: dict[str, Any]) -> str:
        if self._has_error:
            return TRACE_STATUS_ERROR
        if record_fields.get("replayed"):
            return TRACE_STATUS_REPLAYED
        outcome = record_fields.get("outcome_kind")
        path = record_fields.get("path")
        if outcome is None or path is None:
            return TRACE_STATUS_INCOMPLETE
        normalized = getattr(outcome, "value", outcome)
        if normalized in {kind.value for kind in _ERROR_OUTCOMES}:
            return TRACE_STATUS_ERROR
        return TRACE_STATUS_OK

    def _to_span_record(self, handle: SpanHandle) -> SpanRecord:
        attributes_json: str | None = "{}"
        if handle._attrs:
            try:
                attributes_json = _canonical_json(handle._attrs)
            except TypeError:
                # 观测内核不得因为一个不可序列化的属性值中断调用方
                LOGGER.warning(
                    "trace_span_attributes_error: span=%r", handle.name, exc_info=True
                )
                attributes_json = None
        return SpanRecord(
            span_id=handle.span_id,
            trace_id=self.trace_id,
            parent_span_id=handle.parent_span_id,
            name=handle.name,
            started_at=handle.started_at,
            duration_ms=handle._duration_ms,
            status=handle._status,
            attributes_json=attributes_json,
            error_code=handle._error_code,
        )


def _normalize_flags_payload(value: Any) -> str:
    """``filter_decisions_json`` 统一为 canonical JSON object 文本（条件属性要并入）。"""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            raise ValueError(
                "filter_decisions_json 必须是 JSON object 文本或 dict"
            ) from None
        if not isinstance(parsed, dict):
            raise ValueError("filter_decisions_json 必须是 JSON object 文本或 dict")
        return _canonical_json(parsed)
    if isinstance(value, dict):
        return _canonical_json(value)
    raise ValueError("filter_decisions_json 必须是 JSON object 文本或 dict")


def _merge_retrieval_flags(existing: Any) -> dict[str, Any]:
    """把条件 Span 属性并入已有 ``filter_decisions_json``（保留既有键）。"""
    if existing is None:
        return {}
    if isinstance(existing, str):
        parsed = json.loads(existing)  # annotate 时已校验为 object 文本
        if isinstance(parsed, dict):
            return dict(parsed)
    raise ValueError("filter_decisions_json 必须是 JSON object 文本")


# ---- 公共入口 ----


@contextmanager
def start_trace(
    *,
    http_request_id: str,
    mode: TraceMode | str,
    scope: str,
    path: TracePath | str | None = TracePath.RAG,
    question: str = "",
    case_id: str | None = None,
    attempt: int = 1,
    replayed: bool = False,
    previous_trace_id: str | None = None,
    repo: "TraceRepository | None" = None,
    content_mode: str = CONTENT_MODE_HASH,
    hmac_key: bytes | None = None,
) -> Iterator[TraceContext]:
    """开启一次执行尝试的 Trace；``with`` 退出时自动 ``finish``（幂等）。

    参数语义见设计 §6.1 / §6.3 / §6.5：

    - ``http_request_id``：HTTP 中间件生成的请求 ID；
    - ``mode`` / ``scope`` / ``path``：运行模式、范围、执行路径；
    - ``question``：问题原文，只在内存中使用，``finish`` 按 ``content_mode`` 转摘要/长度；
    - ``repo``：``TraceRepository``；``None`` 时所有写入 no-op（不创建 DB 文件）；
    - ``content_mode``：默认 ``hash``；``off`` 不存问题/答案，只存计数与 ID；
      ``redacted`` / ``full`` 在 P0 未实现，显式 ``ValueError``（fail closed）；
    - ``hmac_key``：真实业务问题的 HMAC key；``None`` / 空字节 → 退化为 sha256，
      永不写入记录（只写 ``key_fingerprint`` 得到的 ``hmac_key_id``）。

    T003c/d 接入时由 ``main.py`` 把 ``settings.trace_content_mode`` 与
    ``MKTKB_TRACE_HMAC_KEY`` 解码后的 key 传进来（本内核不读环境变量文件）。
    """
    trace = TraceContext(
        trace_id=uuid.uuid4().hex,
        **_normalize_start_arguments(
            http_request_id=http_request_id,
            mode=mode,
            scope=scope,
            path=path,
            question=question,
            case_id=case_id,
            attempt=attempt,
            replayed=replayed,
            previous_trace_id=previous_trace_id,
            repo=repo,
            content_mode=content_mode,
            hmac_key=hmac_key,
        ),
    )
    current_token = _CURRENT_TRACE.set(trace)
    span_token = _SPAN_STACK.set(())
    try:
        yield trace
    except BaseException as exc:
        trace._capture_exception(exc)
        raise
    finally:
        trace.finish()
        _SPAN_STACK.reset(span_token)
        _CURRENT_TRACE.reset(current_token)


def current_trace() -> TraceContext | None:
    """返回当前上下文的 ``TraceContext``；没有正在执行的 Trace 时返回 ``None``。"""
    return _CURRENT_TRACE.get()


__all__ = [
    "CONTENT_MODE_HASH",
    "CONTENT_MODE_OFF",
    "HASH_ALGO_HMAC_SHA256",
    "HASH_ALGO_SHA256",
    "SPAN_STATUS_ERROR",
    "SPAN_STATUS_OK",
    "TRACE_STATUS_ERROR",
    "TRACE_STATUS_INCOMPLETE",
    "TRACE_STATUS_OK",
    "TRACE_STATUS_REPLAYED",
    "SpanHandle",
    "TraceContext",
    "current_trace",
    "start_trace",
]
