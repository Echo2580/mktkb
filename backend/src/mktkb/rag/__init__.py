"""LOCAL-R1/S1 隔离 RAG 包。

对外主要入口：`RagIndex`、`RagConfig`、`BudgetLedger`、`parse_query`、`build_chunks`。
本包不写产品 HTTP 契约、不打开 var 正式数据库；S2 由适配层接入。
"""

from .budget import BudgetLedger, BudgetSummary, Reservation
from .chunking import adapt_parsed_unit, build_chunks, field_role, role_values
from .config import RagConfig, safe_config_summary
from .errors import (
    BudgetExceeded,
    BudgetPricingUnknown,
    FactRejected,
    KnowledgeChanged,
    RagError,
    RagNotReady,
)
from .index import RagIndex
from .query import Lexicon, build_lexicon, parse_query
from .types import (
    AtomicUnit,
    Citation,
    DocumentSpec,
    EvidenceItem,
    Fact,
    IndexedChunk,
    QueryPlan,
    QueryState,
    RagAnswer,
    RetrievalResult,
)

__all__ = [
    "AtomicUnit",
    "BudgetExceeded",
    "BudgetLedger",
    "BudgetPricingUnknown",
    "BudgetSummary",
    "Citation",
    "DocumentSpec",
    "EvidenceItem",
    "Fact",
    "FactRejected",
    "IndexedChunk",
    "KnowledgeChanged",
    "Lexicon",
    "QueryPlan",
    "QueryState",
    "RagAnswer",
    "RagConfig",
    "RagError",
    "RagIndex",
    "RagNotReady",
    "Reservation",
    "RetrievalResult",
    "adapt_parsed_unit",
    "build_chunks",
    "build_lexicon",
    "field_role",
    "parse_query",
    "role_values",
    "safe_config_summary",
]
