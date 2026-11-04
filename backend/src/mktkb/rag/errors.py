"""LOCAL-R1/S1 隔离 RAG 的稳定错误。

错误只携带稳定 code 与面向用户的短消息，不包含 API Key、认证头、完整 .env、
SQL、文件绝对路径或供应商响应正文。调用方按 code 决定追问、拒绝或降级。
"""

from __future__ import annotations


class RagError(Exception):
    code = "RAG_ERROR"

    def __init__(self, message: str = "", *, detail: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.detail = detail


class RagConfigError(RagError):
    code = "RAG_CONFIG_INVALID"


class RagNotReady(RagError):
    code = "RAG_NOT_READY"


class KnowledgeChanged(RagError):
    code = "KNOWLEDGE_CHANGED"


class QueryRejected(RagError, ValueError):
    code = "QUERY_REJECTED"


class EmbeddingError(RagError):
    code = "EMBEDDING_ERROR"


class EmbeddingDimensionError(EmbeddingError):
    code = "EMBEDDING_DIMENSION_INVALID"


class EmbeddingResponseError(EmbeddingError):
    code = "EMBEDDING_RESPONSE_INVALID"


class EmbeddingTimeout(EmbeddingError):
    code = "EMBEDDING_TIMEOUT"


class EmbeddingRateLimited(EmbeddingError):
    code = "EMBEDDING_RATE_LIMITED"


class EmbeddingUnavailable(EmbeddingError):
    code = "EMBEDDING_UNAVAILABLE"


class RerankError(RagError):
    code = "RERANK_ERROR"


class RerankUnavailable(RerankError):
    code = "RERANK_UNAVAILABLE"


class ChatError(RagError):
    code = "CHAT_ERROR"


class ChatUnavailable(ChatError):
    code = "CHAT_UNAVAILABLE"


class BudgetError(RagError):
    code = "BUDGET_ERROR"


class BudgetExceeded(BudgetError):
    code = "BUDGET_EXCEEDED"


class RequestLimitExceeded(BudgetError):
    code = "REQUEST_LIMIT_EXCEEDED"


class BudgetPricingUnknown(BudgetError):
    code = "BUDGET_PRICING_UNKNOWN"


class BudgetLedgerInvalid(BudgetError):
    code = "BUDGET_LEDGER_INVALID"


class FactRejected(RagError):
    code = "FACT_REJECTED"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StaleSource(FactRejected):
    def __init__(self, message: str = "引用来源已失效") -> None:
        super().__init__("STALE_SOURCE", message)


class ForgedValue(FactRejected):
    def __init__(self, message: str = "回答包含无依据的值") -> None:
        super().__init__("FORGED_VALUE", message)


class CrossEntity(FactRejected):
    def __init__(self, message: str = "回答混入了其它实体") -> None:
        super().__init__("CROSS_ENTITY", message)


class CrossField(FactRejected):
    def __init__(self, message: str = "回答混入了其它字段角色") -> None:
        super().__init__("CROSS_FIELD", message)


class UnsupportedClaim(FactRejected):
    def __init__(self, message: str = "回答含无法由引用证据支持的内容") -> None:
        super().__init__("UNSUPPORTED_CLAIM", message)
