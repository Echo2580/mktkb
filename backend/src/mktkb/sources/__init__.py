"""T06 来源模块：消息引用绑定、实时有效性、失效元信息与受保护文件读取。"""

from __future__ import annotations

from .service import (
    get_message_source,
    load_message,
    media_type_for,
    message_sources,
    resolve_source_file,
    status_of,
    summary_for,
)

__all__ = [
    "get_message_source",
    "load_message",
    "media_type_for",
    "message_sources",
    "resolve_source_file",
    "status_of",
    "summary_for",
]
