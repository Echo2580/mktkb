"""T003c：RAG 埋点用的 no-op 安全助手（纯函数 / 轻量包装，不依赖业务模块）。

设计约束（handoff §7）：

- 只通过 ``current_trace()`` 取当前 Trace；没有 Trace 时**所有入口 no-op**，
  绝不创建隐式 Trace（这是“无 trace 时零行为变化”的结构性保证）；
- ``span(name, **attrs)`` 是 ``TraceContext.span`` 的薄包装：无 Trace 时产出
  一个空句柄，调用方照常 ``handle.annotate(...)`` 即可，不需要分支；
- ``annotate_trace(**attrs)`` 只写数据字段（T003d 负责 request_id/path/outcome 等
  启动字段，本包不越界）；
- ``canonical_json`` / ``hash_ref`` 供 trace attributes 共享：JSON 口径与内核
  ``ensure_ascii=False, sort_keys=True`` 一致；稳定引用只落短哈希，不落原始
  chunk/unit UUID（设计 §6.3“只存 chunk_id_hash 供调试”）。

本模块顶层只 import 标准库 + ``.tracer``，不 import ``qa`` / ``rag`` / ``conversations``
/ ``main`` / ``config``，避免循环依赖。
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from typing import Any, Iterator

from .tracer import SpanHandle, current_trace


class NullSpan:
    """无 Trace 时的空 Span 句柄：``annotate`` 永远 no-op。"""

    __slots__ = ()

    def annotate(self, **attrs: Any) -> None:  # noqa: ARG002 - 与 SpanHandle 同签名
        """空实现；保留与 ``SpanHandle.annotate`` 相同的调用形态。"""
        return None


_NULL_SPAN = NullSpan()


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[SpanHandle | NullSpan]:
    """开启一个 Span；当前没有 Trace 时产出空句柄（不落任何记录）。

    ``name`` 非法（空字符串）时仍与内核一致：有 Trace 时 fail closed；无 Trace 时
    不校验（no-op 路径不改变业务控制流）。
    """
    trace = current_trace()
    if trace is None:
        yield _NULL_SPAN
        return
    with trace.span(name, **attrs) as handle:
        yield handle


def annotate_trace(**attrs: Any) -> None:
    """向当前 Trace 写数据字段；无 Trace 时 no-op（禁止创建隐式 Trace）。"""
    trace = current_trace()
    if trace is not None:
        trace.annotate(**attrs)


def canonical_json(payload: Any) -> str:
    """设计 §6.2 canonical JSON 口径（``ensure_ascii=False, sort_keys=True``）。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_ref(value: str, *, length: int = 16) -> str:
    """稳定短引用：sha256 十六进制前缀；不落原始 chunk/unit UUID。"""
    if not isinstance(value, str) or not value:
        raise ValueError("hash_ref 需要非空字符串")
    if not isinstance(length, int) or isinstance(length, bool) or not 8 <= length <= 64:
        raise ValueError("hash_ref 长度必须是 8..64 的 int")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


__all__ = [
    "NullSpan",
    "annotate_trace",
    "canonical_json",
    "hash_ref",
    "span",
]
