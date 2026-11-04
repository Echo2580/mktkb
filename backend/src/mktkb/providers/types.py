"""T06 模型网关类型：只描述服务端内部的输入/输出，不暴露给客户端。

与《接口与数据契约》4.2 节一致：
- ``CompletionInput``：purpose=query_expansion/answer、question、DialogueContext、ModelEvidence；
- ``DialogueContext`` 只含最近最多 3 条用户问题与已明确实体条件，历史助手答案不是事实；
- ``ModelEvidence`` 只取本次有效 EvidenceSet 的 source_id/text/fields；
- ``CompletionOutput``：text/source_ids/query_terms/provider_request_id/usage；usage 缺失为 None。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

Purpose = Literal["query_expansion", "answer"]

MAX_CONTEXT_QUESTIONS = 3
MAX_MODEL_TERMS = 12
MAX_MODEL_TERM_CHARS = 64


@dataclass(frozen=True)
class DialogueContext:
    """本会话最近最多 3 条用户问题与已明确实体条件。"""

    questions: tuple[str, ...] = ()
    entities: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelEvidence:
    """一条本次有效候选来源；fields 为原值字段，不作为模型可改写的自由文本。"""

    source_id: str
    text: str
    fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionInput:
    purpose: Purpose
    question: str
    context: DialogueContext = field(default_factory=DialogueContext)
    evidence: tuple[ModelEvidence, ...] = ()


@dataclass(frozen=True)
class CompletionOutput:
    text: str
    source_ids: tuple[str, ...] = ()
    query_terms: tuple[str, ...] = ()
    provider_request_id: str | None = None
    usage: Mapping[str, int] | None = None
    # S2-J2：供应商实际 usage 原始映射（仅内存传递，用于受控结算证据；不直接落盘）。
    raw_usage: Mapping[str, Any] | None = None


@runtime_checkable
class ModelGateway(Protocol):
    """模型网关协议；调用方只传本类型，不允许客户端指定目的地址。"""

    async def complete(self, request: CompletionInput, *, timeout_seconds: float) -> CompletionOutput: ...


class ModelError(Exception):
    """模型层稳定错误基类；message 面向内部，code 映射 AskResult.error_code。"""

    code = "MODEL_ERROR"
    retryable = False

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class ModelNotConfigured(ModelError):
    code = "MODEL_NOT_CONFIGURED"


class ModelTimeout(ModelError):
    code = "MODEL_TIMEOUT"
    retryable = True


class ModelUnavailable(ModelError):
    code = "MODEL_UNAVAILABLE"
    retryable = True


class ModelBudgetRefused(ModelError):
    """预留/授权阶段拒绝：阶段额度、累计请求或账本不可用，本次**没有**发出任何请求。

    与 ``ModelUnavailable`` 分开的原因：供应商本身可能是可用的，真实原因是预算/授权不足；
    界面若显示“服务不可用”会把可修复的额度问题伪装成外部故障（真实 UI 已发生过）。
    重试不会自行恢复，必须由管理员补额度或重签 GO，因此 ``retryable=False``。
    """

    code = "MODEL_BUDGET_REFUSED"
    retryable = False


class ModelOutputInvalid(ModelError):
    code = "MODEL_OUTPUT_INVALID"


# ---------------------------------------------------------------- T07 OCR 协议
# 与《接口与数据契约》3.1/4.2/6 一致：
# - OCRInput 只含经边界检查的本地图片内容与来源定位，不含目标 URL；
# - OCRPageResult.confidence 只在服务真实提供时使用，否则为 None；
# - 模式 text/table 分别映射 GeneralAccurateOCR / RecognizeTableAccurateOCR。

OCRMode = Literal["text", "table"]

# S2-K-R1A：OCR 来源锚。受控 OCR 网关按 (来源锚, 真实页号) 统计 tile，而不是全项目共用一个
# 页号槽；锚是“服务端实际持有的 document+version”的不可逆哈希，不含文件名/请求体可伪造的
# namespace，也不会把原始 id 或任何秘密写进账本/日志。
OCR_SOURCE_SCOPE_VERSION = "ocr-source-v1"
OCR_SOURCE_SCOPE_HEX_LEN = 64
_OCR_SOURCE_SCOPE_PATTERN = re.compile(r"[0-9a-f]{%d}\Z" % OCR_SOURCE_SCOPE_HEX_LEN)


def make_ocr_source_scope(document_id: object, version_id: object) -> str:
    """由 worker 可信上下文生成来源锚；只在服务端内部使用，返回 64 位小写 hex。"""
    if document_id is None or version_id is None:
        raise ValueError("OCR 来源锚需要实际的 document_id 与 version_id")
    normalized = f"{OCR_SOURCE_SCOPE_VERSION}|{document_id}|{version_id}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_valid_ocr_source_scope(value: object) -> bool:
    """受控来源锚格式校验：只接受恰好 64 位小写 hex。"""
    return isinstance(value, str) and bool(_OCR_SOURCE_SCOPE_PATTERN.fullmatch(value))


@dataclass(frozen=True)
class OCRInput:
    """一页/一块待识别图片；bbox 为源页面坐标（PDF 点或图片像素），None 表示整页。

    ``source_scope`` 是 S2-K-R1A 增加的可选服务端来源锚：由实际处理该版本的
    ``ingestion.worker.OcrExecutor`` 用数据库持有的 document_id/version_id 覆盖写入，
    解析器与上传请求体都没有可信身份，不能自行决定它。历史/测试直调可省略（网关走固定
    legacy 兼容锚，仍受同一页 tile 上限与全局次数上限）。
    """

    content: bytes
    mime_type: str
    page: int
    bbox: tuple[float, float, float, float] | None = None
    source_scope: str | None = None


@dataclass(frozen=True)
class OCRPageResult:
    """一页/一块的识别结果；table_rows 保留供应商给出的行/列顺序与原值。"""

    text: str
    table_rows: tuple[tuple[str | None, ...], ...] = ()
    regions: tuple[Mapping[str, Any], ...] = ()
    provider_request_id: str | None = None
    confidence: float | None = None


@runtime_checkable
class OCRGateway(Protocol):
    """OCR 网关协议；目的地址只来自服务端配置，调用方不能传入 URL。"""

    def recognize(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult: ...


class OCRError(Exception):
    """OCR 层稳定错误基类；code 映射任务 error_code，message 不回显密钥/图片内容。"""

    code = "OCR_ERROR"
    retryable = False

    def __init__(self, message: str = "", *, provider_request_id: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.provider_request_id = provider_request_id


class OCRNotConfigured(OCRError):
    code = "OCR_NOT_CONFIGURED"


class OCRTimeout(OCRError):
    code = "OCR_TIMEOUT"
    retryable = True


class OCRUnavailable(OCRError):
    code = "OCR_UNAVAILABLE"
    retryable = True


class OCRRateLimited(OCRError):
    code = "OCR_RATE_LIMITED"
    retryable = True


class OCRQuotaUnavailable(OCRError):
    """额度不足：不自动重试；恢复额度后由管理员显式重试。"""

    code = "OCR_QUOTA_UNAVAILABLE"
    retryable = True


class OCRAuthFailed(OCRError):
    code = "OCR_AUTH_FAILED"


class OCRInvalidInput(OCRError):
    code = "OCR_INVALID_INPUT"


class OCRInvalidOutput(OCRError):
    code = "OCR_INVALID_OUTPUT"
