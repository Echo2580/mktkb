"""S2-J2 受控字段白名单与 ``UsageEvidence`` 构造（纯函数，无 IO / 无网络 / 无环境）。

为什么需要（J1 已接收核心之外，J2 才接真实供应商字段）：
- ``settle_usage`` 的 ``UsageEvidence`` 由未来受控 adapter 从**实际 HTTP 响应**整理；
- J1-R2 独立复验 §7 已实证：版本化路径的 ``request_id`` 与 ``dimensions`` 会原样落盘，
  旧生产 ``settle()`` 也直传 ``http_status/request_id/error_code/dimensions``；
  OCR 的 ``provider_request_id`` 还会写进业务审计表。若把供应商原文直接塞进去，
  就可能绕过 usage/reason 白名单把凭据形态串或超长串写进账本/数据库/日志。

本模块只做**受控收敛**：
- ``request_id``：**任何外部原始字符串**（HTTP/JSON 解析产物，包括安全字符集内的短凭据形态串、
  合法常规 id、以及看起来像 ``sha256:`` 内部前缀的伪造串）一律转成 ``sha256:<32hex>``
  不可逆哈希引用（S2-J2-R1）；只有本模块自己产出的 :class:`RequestIdReference`
  实例（进程内类型标记，外部字节无法构造）会被幂等原样返回，供“客户端→预算包装→账本”
  多层调用不二次哈希；空/非字符串/全空白 → None，超长不截断原文、直接哈希；
- ``dimensions``：仅 int 非 bool、每项 1..MAX_DIMENSION、可选 expected 严格相等；
- ``http_status``：仅 int 非 bool 且 100..599，否则 None（由 J1 拒绝，不释放）；
- ``error_code``：只接受本仓生产适配器已声明的稳定错误码集合，其余一律 ``PROVIDER_ERROR``；
- ``usage``：按 kind 白名单过滤（只留 int 非 bool 非负），未知键/嵌套/凭据形态串一律丢弃；
- ``UsageEvidence``：只从**实际解析结果**构造；缺字段不补造（J1 会拒绝并全额保留）。

来源信任边界（S2-J2-R1 明确）：
1. 外部原始字符串不可信 → 永远哈希；**绝不按字符串前缀/字符集判断“已安全”**，因此外部伪造
   ``sha256:<32hex>`` 会被再次哈希，不能冒充内部引用绕过持久化白名单；
2. 内部已收敛引用以 :class:`RequestIdReference` 类型为准（是本模块返回值的 Python 类型，
   不是可被外部供应链伪造的文本前缀）；多层重复调用返回同一引用，保证同一供应商 request_id
   的追踪值稳定、不出现 hash-of-hash；
3. 需要外部原文关联时，只能由持有原文的一侧本地计算同一 SHA-256 引用做对照，账本/审计/异常/
   日志中永远只有不可逆引用。

边界：本模块不判断成功与否、不重算金额、不写账本；版本化结算与白名单余额校验仍在
``rag.budget.settle_usage`` / ``rag.settlement_policy``（J1 已接收，本包不改）。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .settlement_policy import (
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_RERANK,
    SettlementPolicy,
    UsageEvidence,
)

__all__ = [
    "CONTROLLED_ERROR_CODES",
    "ControlledFieldError",
    "MAX_DIMENSION",
    "REQUEST_ID_REFERENCE_PREFIX",
    "RequestIdReference",
    "SAFE_REQUEST_ID_MAX_CHARS",
    "build_chat_evidence",
    "build_total_evidence",
    "safe_dimensions",
    "safe_error_code",
    "safe_http_status",
    "safe_request_id",
    "safe_usage",
    "usage_for_evidence",
]

SAFE_REQUEST_ID_MAX_CHARS = 71  # "sha256:"(7) + 32 hex；引用长度上界
REQUEST_ID_REFERENCE_PREFIX = "sha256:"
_REFERENCE_HEX_CHARS = 32
_REFERENCE_RE = re.compile(r"^sha256:[0-9a-f]{32}$")
MAX_DIMENSION = 4096
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# 生产适配器（chat 两入口 / embedding / rerank / OCR / 账本拒绝）已使用的稳定错误码。
# 未列出的值一律收敛为 PROVIDER_ERROR：宁可丢失细粒度错误码，也不把外部原文写进账本/审计。
CONTROLLED_ERROR_CODES = frozenset(
    {
        "PROVIDER_ERROR",
        # chat（providers/budgeted.py + rag/providers.py + 客户端）
        "CHAT_CANCELLED",
        "CHAT_TIMEOUT",
        "CHAT_UNEXPECTED",
        "CHAT_USAGE_OVER_TOKEN_BOUND",
        "CHAT_POST_AUTH_DENIED",
        "CHAT_NETWORK",
        "CHAT_HTTP",
        "CHAT_RESPONSE_INVALID",
        "CHAT_USAGE_OVER_INPUT_MAX",
        "CHAT_USAGE_OVER_OUTPUT_MAX",
        # 产品 chat 发送前授权/预算复核拒绝（providers/budgeted.py）
        "MODEL_POST_SEND_AUTH_DENIED",
        # embedding
        "EMBEDDING_POST_AUTH_DENIED",
        "EMBEDDING_TIMEOUT",
        "EMBEDDING_NETWORK",
        "EMBEDDING_RATE_LIMITED",
        "EMBEDDING_UNAVAILABLE",
        "EMBEDDING_HTTP",
        "EMBEDDING_RESPONSE_INVALID",
        "EMBEDDING_USAGE_OVER_OFFICIAL_MAX",
        # rerank
        "RERANK_POST_AUTH_DENIED",
        "RERANK_TIMEOUT",
        "RERANK_NETWORK",
        "RERANK_RATE_LIMITED",
        "RERANK_UNAVAILABLE",
        "RERANK_HTTP",
        "RERANK_RESPONSE_INVALID",
        # OCR（providers/types.py 稳定码 + J2 预算包装新增的受控码）
        "OCR_NOT_CONFIGURED",
        "OCR_TIMEOUT",
        "OCR_UNAVAILABLE",
        "OCR_RATE_LIMITED",
        "OCR_QUOTA_UNAVAILABLE",
        "OCR_AUTH_FAILED",
        "OCR_INVALID_INPUT",
        "OCR_INVALID_OUTPUT",
        "OCR_INTERNAL",
        "OCR_BUDGET_REFUSED",
        "OCR_BUDGET_LEDGER_DENIED",
        "OCR_BUDGET_SEND_REFUSED",
        # 超时/中断的受控归因（不写异常原文）
        "PROVIDER_INTERRUPTED",
        "PROVIDER_CANCELLED",
    }
)

_CHAT_USAGE_FIELDS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "reasoning_tokens",
    }
)
_TOTAL_USAGE_FIELDS = frozenset(
    {
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    }
)


class ControlledFieldError(ValueError):
    """受控字段校验失败（fail closed；错误文本只给稳定类别与字段名，不回显原文）。"""


def _plain_int(value: Any) -> bool:
    return type(value) is int


class RequestIdReference(str):
    """内部已收敛 request_id 引用的**进程内类型标记**（外部字节无法构造）。

    - 由 :func:`safe_request_id` 对外部原始字符串做 SHA-256 后返回；
    - 本模块看到该类型时幂等原样返回（``客户端 → 预算包装 → 账本`` 多层重复收敛不会
      变成 hash-of-hash，同一供应商 request_id 的追踪引用稳定）；
    - 外部输入（HTTP/JSON 解析产物）一律是普通 ``str``，即使内容形如
      ``sha256:<32hex>`` 也只当外部原文再次哈希，不能借前缀冒充内部引用；
    - 只是不可逆引用，不保留任何可还原原文的能力；序列化后按普通字符串落盘即可。
    """

    __slots__ = ()


def _hash_request_id(text: str) -> RequestIdReference:
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return RequestIdReference(f"{REQUEST_ID_REFERENCE_PREFIX}{digest[:_REFERENCE_HEX_CHARS]}")


def safe_request_id(value: Any) -> str | None:
    """供应商 request_id → 统一 ``sha256:<32hex>`` 不可逆引用（S2-J2-R1）。

    信任边界：**任何**外部字符串（包括安全字符集内的短凭据形态串 / 合法常规 id /
    伪造内部前缀）都哈希，绝不原文持久化；只有本模块产出的 :class:`RequestIdReference`
    才幂等原样返回。空、全空白、非字符串 → ``None``；超长不截断原文、直接哈希。
    """
    if value is None:
        return None
    if isinstance(value, RequestIdReference):
        # 只接受本模块自己的规范引用；畸形标记（理论上只能由内部误构造）按外部原文收敛，
        # 既不原样放行，也不因类型存在而放宽。
        if _REFERENCE_RE.match(value):
            return value
        return _hash_request_id(str(value))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return _hash_request_id(text)


def safe_dimensions(value: Any, *, expected: tuple[int, ...] | None = None) -> tuple[int, ...] | None:
    """dimensions 只允许 1..MAX_DIMENSION 的 int 序列；非法 fail closed。"""
    if value is None:
        return None
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, (list, tuple)):
        raise ControlledFieldError("dimensions 必须是整数序列")
    cleaned: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ControlledFieldError("dimensions 必须是整数（bool 不算）")
        if not 1 <= int(item) <= MAX_DIMENSION:
            raise ControlledFieldError("dimensions 超出受控范围 1..4096")
        cleaned.append(int(item))
    if not cleaned:
        raise ControlledFieldError("dimensions 不能为空")
    result = tuple(cleaned)
    if expected is not None and result != tuple(expected):
        raise ControlledFieldError("dimensions 与期望值不一致")
    return result


def safe_http_status(value: Any) -> int | None:
    """HTTP 状态码只接受实际响应对象的 int（100..599）；其余返回 None 交由 J1 拒绝。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 100 <= int(value) <= 599:
        return None
    return int(value)


def safe_error_code(value: Any) -> str:
    """错误码白名单；非受控值收敛为 PROVIDER_ERROR（不写原文）。"""
    if not isinstance(value, str):
        return "PROVIDER_ERROR"
    text = value.strip()
    if text in CONTROLLED_ERROR_CODES:
        return text
    return "PROVIDER_ERROR"


def safe_usage(kind: str, usage: Any) -> dict[str, int]:
    """按 kind 白名单过滤 usage 计数（int 非 bool 非负）；未知键/嵌套一律丢弃。

    仅用于**旧结算路径/响应对象**的落盘白名单；版本化证据使用
    :func:`usage_for_evidence`，让 J1 对未知 usage 字段 fail closed。
    """
    if kind == KIND_CHAT:
        allowed = _CHAT_USAGE_FIELDS
    elif kind in (KIND_EMBEDDING, KIND_RERANK):
        allowed = _TOTAL_USAGE_FIELDS
    else:
        return {}
    clean: dict[str, int] = {}
    if not isinstance(usage, Mapping):
        return clean
    for key, value in usage.items():
        if not isinstance(key, str) or key not in allowed:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        clean[key] = int(value)
    return clean


def usage_for_evidence(kind: str, usage: Any) -> Mapping[str, Any]:
    """构造 ``UsageEvidence.usage``：保留原始键值让 J1 严格判非法。

    - chat：官方 ``completion_tokens_details.reasoning_tokens`` 是已知嵌套结构，映射为
      J1 白名单的顶层 ``reasoning_tokens``（仅当顶层未出现时）；其余键原样保留；
    - embedding/rerank：原样保留（J1 只接受 ``total_tokens`` 等官方字段；未知字段 fail closed）；
    - 非 Mapping 原样返回（J1 判 ``usage_not_mapping``）。
    """
    if not isinstance(usage, Mapping):
        return usage
    if kind != KIND_CHAT:
        return {key: value for key, value in usage.items()}
    normalized: dict[str, Any] = {key: value for key, value in usage.items()}
    details = normalized.pop("completion_tokens_details", None)
    if isinstance(details, Mapping) and "reasoning_tokens" not in normalized:
        reasoning = details.get("reasoning_tokens")
        if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0:
            normalized["reasoning_tokens"] = reasoning
    # 官方 Chat Completions 响应固定带 ``prompt_tokens_details.cached_tokens``
    # （= prompt_cache_hit_tokens 的重复字段，见 api-docs.deepseek.com/zh-cn/api/
    # create-chat-completion 的 usage 定义）。它是同一计量的嵌套副本，不是新的计费维度：
    # 顶层未给 prompt_cache_hit_tokens 时才用它兜底，绝不覆盖顶层已声明的值。
    prompt_details = normalized.pop("prompt_tokens_details", None)
    if isinstance(prompt_details, Mapping) and "prompt_cache_hit_tokens" not in normalized:
        cached = prompt_details.get("cached_tokens")
        if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
            normalized["prompt_cache_hit_tokens"] = cached
    return normalized


def _policy_for(kind: str, policy: Any) -> SettlementPolicy:
    if not isinstance(policy, SettlementPolicy):
        raise ControlledFieldError("settlement_policy 必须是 SettlementPolicy")
    if policy.kind != kind:
        raise ControlledFieldError("settlement_policy.kind 与证据 kind 不一致")
    return policy


def _request_sha256(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256_HEX_RE.match(value.strip().lower()):
        raise ControlledFieldError("request_sha256 必须是 64 位十六进制")
    return value.strip().lower()


def _optional_bool(value: Any, default: bool) -> Any:
    return value if type(value) is bool else default


def build_chat_evidence(
    policy: Any,
    *,
    request_sha256: str,
    usage: Any,
    http_status: Any = 200,
    streamed: Any = False,
    finish_reason: Any = "stop",
    content_complete: Any = True,
    content_parse_ok: Any = True,
) -> UsageEvidence:
    """由实际 chat 响应构造 J1 证据；只填白名单字段，不补造缺失 usage。"""
    policy = _policy_for(KIND_CHAT, policy)
    return UsageEvidence(
        kind=policy.kind,
        provider=policy.provider,
        model=policy.model,
        host=policy.host,
        region=policy.region,
        pricing_source=policy.pricing_source,
        request_sha256=_request_sha256(request_sha256),
        http_status=safe_http_status(http_status),
        streamed=_optional_bool(streamed, False),
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        content_complete=_optional_bool(content_complete, False),
        content_parse_ok=_optional_bool(content_parse_ok, False),
        usage=usage_for_evidence(KIND_CHAT, usage),
    )


def build_total_evidence(
    policy: Any,
    *,
    request_sha256: str,
    usage: Any,
    http_status: Any = 200,
    output_valid: Any = True,
) -> UsageEvidence:
    """由实际 embedding/rerank 响应构造 J1 证据；只认官方 ``total_tokens``（不强制 prompt_tokens）。"""
    if not isinstance(policy, SettlementPolicy):
        raise ControlledFieldError("settlement_policy 必须是 SettlementPolicy")
    if policy.kind not in (KIND_EMBEDDING, KIND_RERANK):
        raise ControlledFieldError("build_total_evidence 只接受 embedding/rerank policy")
    return UsageEvidence(
        kind=policy.kind,
        provider=policy.provider,
        model=policy.model,
        host=policy.host,
        region=policy.region,
        pricing_source=policy.pricing_source,
        request_sha256=_request_sha256(request_sha256),
        http_status=safe_http_status(http_status),
        streamed=False,
        finish_reason=None,
        content_complete=False,
        content_parse_ok=False,
        output_valid=_optional_bool(output_valid, False),
        usage=usage_for_evidence(policy.kind, usage),
    )
