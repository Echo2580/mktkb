"""T05 检索层类型与稳定错误。

QueryIntent / EvidenceSet 与《接口与数据契约》4.2 节保持一致；候选与截断事实是该节要求的
补充结构，供 T06 映射最终 AskResult，不新增任何对外 HTTP 响应。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Mapping

Mode = Literal["record", "document"]
Kind = Literal["matches", "ambiguous", "conflict", "none"]

# 只允许这四类实体筛选键；它们映射到已验证的字段角色，不能当任意 SQL 列。
FILTER_KEYS: tuple[str, ...] = ("store", "item", "store_id", "item_id")
MAX_TERMS = 12
MAX_TERM_CHARS = 64
MAX_REQUESTED_FIELDS = 12
MAX_FIELD_CHARS = 32
MAX_LIMIT = 100


class RetrievalError(Exception):
    """检索层稳定错误基类；code 供 T06 映射，不携带原文、路径或 SQL。"""

    code = "RETRIEVAL_ERROR"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class QueryRejected(RetrievalError, ValueError):
    """查询参数不合法（模式、筛选键、limit、类型或超长）。"""

    code = "INVALID_QUERY"


class IndexNotReady(RetrievalError):
    """索引未就绪或规则版本不匹配；必须与 none 区分。"""

    code = "INDEX_NOT_READY"


class KnowledgeRevisionChanged(RetrievalError):
    """请求 revision 与持久 KnowledgeState 不一致。"""

    code = "KNOWLEDGE_CHANGED"


@dataclass(frozen=True)
class QueryIntent:
    mode: Mode
    terms: tuple[str, ...] = ()
    entity_filters: Mapping[str, str] = field(default_factory=dict)
    requested_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    """一个逻辑实体候选：可读标签、可直接用于下一次 QueryIntent 的实体条件、真实来源单元 ID。"""

    label: str
    entity_filters: dict[str, str]
    source_ids: tuple[str, ...]
    matched_terms: tuple[str, ...] = ()


@dataclass
class EvidenceSet:
    units: list  # list[SourceUnit]；类型在此避免与 documents.models 循环导入
    kind: Kind
    total_candidates: int
    revision: int
    candidates: list[Candidate]
    truncated: bool = False


@dataclass(frozen=True)
class IndexStatus:
    version_id: uuid.UUID
    ready: bool
    unit_count: int = 0
    input_digest: str | None = None
    tokenizer_version: str = ""
    prepared_at: datetime | None = None
    reason: str | None = None


def normalize_intent(intent: QueryIntent) -> QueryIntent:
    """校验并规范化查询意图；非法输入在服务边界拒绝，不做静默降级。"""
    if not isinstance(intent, QueryIntent):
        raise QueryRejected("intent 必须是 QueryIntent")
    if intent.mode not in ("record", "document"):
        raise QueryRejected("mode 只允许 record/document")

    if not isinstance(intent.terms, (tuple, list)):
        raise QueryRejected("terms 必须是字符串列表")
    terms: list[str] = []
    for term in intent.terms:
        if not isinstance(term, str):
            raise QueryRejected("terms 只允许字符串")
        cleaned = term.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_TERM_CHARS:
            raise QueryRejected("单项检索词过长")
        if cleaned not in terms:
            terms.append(cleaned)
    if len(terms) > MAX_TERMS:
        raise QueryRejected("检索词数量超出上限")

    if not isinstance(intent.entity_filters, Mapping):
        raise QueryRejected("entity_filters 必须是映射")
    filters: dict[str, str] = {}
    for key, value in intent.entity_filters.items():
        if not isinstance(key, str) or key not in FILTER_KEYS:
            raise QueryRejected("不允许的实体筛选键")
        if not isinstance(value, str):
            raise QueryRejected("实体筛选值必须是字符串")
        cleaned = value.strip()
        if not cleaned or len(cleaned) > MAX_TERM_CHARS:
            raise QueryRejected("实体筛选值不合法")
        filters[key] = cleaned

    if not isinstance(intent.requested_fields, (tuple, list)):
        raise QueryRejected("requested_fields 必须是字符串列表")
    requested: list[str] = []
    for name in intent.requested_fields:
        if not isinstance(name, str):
            raise QueryRejected("requested_fields 只允许字符串")
        cleaned = name.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_FIELD_CHARS:
            raise QueryRejected("请求字段名过长")
        if cleaned not in requested:
            requested.append(cleaned)
    if len(requested) > MAX_REQUESTED_FIELDS:
        raise QueryRejected("请求字段数量超出上限")

    return QueryIntent(
        mode=intent.mode,
        terms=tuple(terms),
        entity_filters=filters,
        requested_fields=tuple(requested),
    )


def validate_limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise QueryRejected("limit 必须是整数")
    if not 1 <= limit <= MAX_LIMIT:
        raise QueryRejected(f"limit 只允许 1～{MAX_LIMIT}")
    return limit
