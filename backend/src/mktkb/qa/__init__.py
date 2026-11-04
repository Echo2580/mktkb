"""S2 产品问答适配层：产品数据库 → rag 索引、持久查询状态与索引同步。"""

from .service import (
    QA_ENGINE_VERSION,
    QaEngine,
    QaIndexStatus,
    QaNotReady,
    manifest_summary,
    resolve_rag_config,
)

__all__ = [
    "QA_ENGINE_VERSION",
    "QaEngine",
    "QaIndexStatus",
    "QaNotReady",
    "manifest_summary",
    "resolve_rag_config",
]
