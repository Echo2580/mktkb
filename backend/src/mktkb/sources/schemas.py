"""T06 来源响应模型：SourceView 定义在会话 schemas 中，这里保持模块边界的显式出口。"""

from __future__ import annotations

from ..conversations.schemas import SourceSummary, SourceView

__all__ = ["SourceSummary", "SourceView"]
