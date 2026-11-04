"""进程内最小中断归因事件。

只记录“原始 BaseException 在被 anyio/TestClient portal 改写之前”能可靠拿到的事实：
类型、组件、阶段、reservation_id / request_id。不抄异常消息、请求头、请求体或密钥。
本模块只做诊断；不吞异常、不结算/释放预留、不改变异常传播。
"""

from __future__ import annotations

import contextvars
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

_LOCK = threading.Lock()
_EVENTS: deque[dict[str, Any]] = deque(maxlen=32)
_QUESTION_ID: contextvars.ContextVar[Any] = contextvars.ContextVar("mktkb_question_id", default=None)
_PHASE: contextvars.ContextVar[Any] = contextvars.ContextVar("mktkb_question_phase", default=None)


def reset() -> None:
    with _LOCK:
        _EVENTS.clear()


def set_question_context(*, question_id: Any, phase: Any) -> tuple[contextvars.Token, contextvars.Token]:
    """在发起题目前设置；portal 复制上下文后，产品侧事件可带上题号/阶段。"""
    return _QUESTION_ID.set(question_id), _PHASE.set(phase)


def set_phase(phase: Any) -> None:
    _PHASE.set(phase)


def clear_question_context(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    question_token, phase_token = tokens
    _QUESTION_ID.reset(question_token)
    _PHASE.reset(phase_token)


def record_base_exception(
    exc: BaseException,
    *,
    component: str,
    stage: Any | None = None,
    reservation_id: Any | None = None,
    request_id: Any | None = None,
) -> dict[str, Any]:
    event = {
        "type": type(exc).__name__,
        "component": str(component),
        "question_id": None if _QUESTION_ID.get() is None else str(_QUESTION_ID.get()),
        "phase": None if _PHASE.get() is None else str(_PHASE.get()),
        "stage": None if stage is None else str(stage),
        "reservation_id": None if reservation_id is None else str(reservation_id),
        "request_id": None if request_id is None else str(request_id),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with _LOCK:
        _EVENTS.append(event)
    return event


def events() -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(item) for item in _EVENTS]


def last_event() -> dict[str, Any] | None:
    with _LOCK:
        return dict(_EVENTS[-1]) if _EVENTS else None


__all__ = [
    "clear_question_context",
    "events",
    "last_event",
    "record_base_exception",
    "reset",
    "set_phase",
    "set_question_context",
]
