"""S2-J1：版本化“成功 usage 保守结算”的纯校验 / 计价模块（Mock-only 核心）。

本模块只做**纯**判断与 Decimal 计价：不读环境、不发 HTTP、不读写账本、不碰供应商。
它是 ``mktkb.rag.budget`` 新结算分支的唯一 policy/校验来源；未来 J2 的受控 adapter
负责把真实响应字段整理成 :class:`UsageEvidence`，再由账本在同一把锁里结算。

版本 v1（唯一允许释放未用预留的版本）：
- chat：HTTP 200、非流式、finish_reason=stop、content 已完整合法解析；
  ``prompt_token/completion/total`` 为 int 非 bool 非负且 total=prompt+completion；
  cache hit/miss 均存在且合计为 prompt；reasoning 若出现为合法 int 且 <= completion；
  准入 cap 固化 prompt<=1536、completion<=256；
  保守价按 cache-miss/高峰输入 2 元/百万、输出 8 元/百万（所有 prompt 按 miss 价）。
- embedding：HTTP 200、输出合法、``usage.total_tokens`` 为 int 非 bool 且 >=1；
  准入 cap 固化 4096；保守价 text-embedding-v4 0.5 元/百万。
- rerank：同上，准入 cap 固化 6000；保守价 gte-rerank-v2 0.8 元/百万。

安全边界（刻意设计）：
- 只接受**预留时已固化**的 policy 快照；版本/caps/费率/来源绑定不能到结算时才声明。
- 调用方不能给金额：本模块从 evidence 的 usage 用 Decimal 重算，绝不相信外部 charge。
- 费率只允许 >= 已核实最低保守费率（更高保守允许，更低拒绝）；cap 精确等于 v1 固化值。
- 任何缺字段、类型不符（含 bool/浮点/NaN）、相互矛盾、超 cap、未知来源/绑定不一致，
  都返回 ``accepted=False``，由账本保持全额占用并给停止信号。
- 拒绝路径只记录**稳定 reason 码**与该 kind 的**白名单计数字段**：未知 usage 字段名/
  值、嵌套结构、非字符串键、凭据形态串一律不写入 reason、事件、异常文本或日志
  （S2-J1-R1 D-1 修复），也不依赖放宽通用 redactor。
- policy/快照校验失败时（S2-J1-R2 F-1）：异常文本只描述**稳定错误类别与内部字段名**，
  不回显快照里的 version/kind/model/caps/rates 等不可信原文；异常照旧 fail closed。
- 拒绝 reason 走显式白名单（S2-J1-R2 F-2）：只保留本模块与账本定义的稳定 reason 码及
  受控参数化后缀（后缀必须来自内部 usage 字段字面量），其余任意输入一律兜底为
  ``UNCLASSIFIED_REJECTION_REASON``；原文绝不进入 ``error_code``/事件/异常文本。
- 金额一律 Decimal 计算并向保守方向（ROUND_CEILING）取到 8 位小数；
  ``estimated_list_price_cny`` 是独立存放的保守标价估算，
  ``provider_billed_cny`` 恒为 null —— 标价估算不是供应商实际账单。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Mapping

SETTLEMENT_VERSION = "usage-conservative-v1"
SNAPSHOT_SCHEMA_VERSION = 1

KIND_CHAT = "chat"
KIND_EMBEDDING = "embedding"
KIND_RERANK = "rerank"
SUPPORTED_KINDS = (KIND_CHAT, KIND_EMBEDDING, KIND_RERANK)

# chat 准入 cap 必须等于**请求自身允许的用量**：输入闸门 MKTKB_MODEL_MAX_INPUT_TOKENS=6144、
# 请求 max_tokens=800。2026-11-04 真实 UI 验证发现旧值 1536/256 与请求上界不一致：
# 产品自己允许的合法回答（如 prompt 1522）会被自身 cap 拒付，且按规则全额留账 2.103552 元。
CHAT_PROMPT_TOKENS_CAP = 6144
CHAT_COMPLETION_TOKENS_CAP = 800
# 2026-11-04 之前签发的 chat 策略快照（历史账本重放必须继续可验）。
LEGACY_CHAT_CAPS = (1536, 256)
EMBEDDING_TOTAL_TOKENS_CAP = 4096
RERANK_TOTAL_TOKENS_CAP = 6000

CHAT_INPUT_PRICE_FLOOR = Decimal("2")
CHAT_OUTPUT_PRICE_FLOOR = Decimal("8")
EMBEDDING_UNIT_PRICE_FLOOR = Decimal("0.5")
RERANK_UNIT_PRICE_FLOOR = Decimal("0.8")

_MILLION = Decimal(1_000_000)
_AMOUNT_QUANTUM = Decimal("0.00000001")

_CHAT_SOURCE = {
    "provider": "deepseek",
    "host": "api.deepseek.com",
    "region": "global",
    "models": frozenset({"deepseek-flash", "deepseek-v4.1-flash-1017"}),
    "pricing_source": "official-list-price/deepseek-chat-cache-miss-v1",
}
_EMBEDDING_SOURCE = {
    "provider": "bailian",
    "host": "dashscope.aliyuncs.com",
    "region": "cn-beijing",
    "models": frozenset({"text-embedding-v4"}),
    "pricing_source": "official-list-price/bailian-text-embedding-v4-v1",
}
_RERANK_SOURCE = {
    "provider": "bailian",
    "host": "dashscope.aliyuncs.com",
    "region": "cn-beijing",
    "models": frozenset({"gte-rerank-v2"}),
    "pricing_source": "official-list-price/bailian-gte-rerank-v2-v1",
}

_SOURCES = {
    KIND_CHAT: _CHAT_SOURCE,
    KIND_EMBEDDING: _EMBEDDING_SOURCE,
    KIND_RERANK: _RERANK_SOURCE,
}

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

_POLICY_SNAPSHOT_KEYS = frozenset(
    {
        "schema_version",
        "version",
        "kind",
        "provider",
        "model",
        "host",
        "region",
        "pricing_source",
        "caps",
        "rates",
    }
)
_CAP_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens"})
_RATE_KEYS = frozenset(
    {"input_per_million_cny", "output_per_million_cny", "unit_per_million_cny"}
)
_SETTLEMENT_BLOCK_KEYS = frozenset(
    {
        "version",
        "kind",
        "provider",
        "model",
        "host",
        "region",
        "pricing_source",
        "request_sha256",
        "http_status",
        "streamed",
        "finish_reason",
        "content_complete",
        "content_parse_ok",
        "output_valid",
        "usage",
        "recomputed_conservative_charge_cny",
    }
)


class SettlementPolicyError(ValueError):
    """policy / 快照 / 事件持久化结构非法（fail closed，不释放）。"""


class _Rejected(Exception):
    """内部：evidence 不合格，带稳定 reason。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _plain_int(value: Any) -> bool:
    return type(value) is int


def _plain_bool(value: Any) -> bool:
    return type(value) is bool


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise SettlementPolicyError(f"{label} 必须是十进制数字")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SettlementPolicyError(f"{label} 必须是十进制数字") from None
    if not number.is_finite():
        raise SettlementPolicyError(f"{label} 必须是有限十进制数字")
    return number


def canonical_decimal(value: Decimal) -> str:
    """稳定的十进制字符串（不用科学计数法，保证账本可审计/可重放）。"""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _amount(value: Decimal) -> Decimal:
    return value.quantize(_AMOUNT_QUANTUM, rounding=ROUND_CEILING)


@dataclass(frozen=True)
class SettlementPolicy:
    """预留时固化的结算 policy（v1）；构造即校验，非法直接拒绝。"""

    version: str
    kind: str
    provider: str
    model: str
    host: str
    region: str
    pricing_source: str
    prompt_tokens_cap: int | None
    completion_tokens_cap: int | None
    total_tokens_cap: int | None
    input_price_per_million_cny: Decimal | None
    output_price_per_million_cny: Decimal | None
    unit_price_per_million_cny: Decimal | None

    def __post_init__(self) -> None:
        _validate_policy(self)


def _validate_policy(policy: SettlementPolicy) -> None:
    # S2-J1-R2 F-1：本函数的所有错误文本都不得回显快照原文（version/kind/model 可能
    # 来自账本里的不可信数据，含 secret 形态串）；只给稳定错误类别与内部字段名。
    if policy.version != SETTLEMENT_VERSION:
        raise SettlementPolicyError(
            f"settlement_policy.version 非法：未知结算版本（仅支持 {SETTLEMENT_VERSION}）"
        )
    if policy.kind not in _SOURCES:
        raise SettlementPolicyError(
            "settlement_policy.kind 非法：未知结算 kind（仅支持 chat/embedding/rerank，"
            "OCR 不在 J1 范围）"
        )
    source = _SOURCES[policy.kind]
    if policy.model not in source["models"]:
        raise SettlementPolicyError("settlement_policy.model 非法：model 不在已知来源集合")
    if policy.provider != source["provider"]:
        raise SettlementPolicyError(f"{policy.kind} provider 与已知来源不一致")
    if policy.host != source["host"]:
        raise SettlementPolicyError(f"{policy.kind} host 与已知来源不一致")
    if policy.region != source["region"]:
        raise SettlementPolicyError(f"{policy.kind} region 与已知来源不一致")
    if policy.pricing_source != source["pricing_source"]:
        raise SettlementPolicyError(f"{policy.kind} pricing_source 与已知来源不一致")

    if policy.kind == KIND_CHAT:
        # 历史快照必须仍可重放：2026-11-04 之前签发的 chat 策略固化的是 1536/256，
        # 之后对齐到请求自身上界 6144/800。两套都是"当时有效的精确 cap"，其余一律拒绝。
        caps = (policy.prompt_tokens_cap, policy.completion_tokens_cap)
        allowed_caps = {
            (CHAT_PROMPT_TOKENS_CAP, CHAT_COMPLETION_TOKENS_CAP),
            LEGACY_CHAT_CAPS,
        }
        if policy.total_tokens_cap is not None or caps not in allowed_caps:
            raise SettlementPolicyError(
                "chat 准入 cap 必须精确固化 prompt=6144/completion=800"
                "（或历史快照 prompt=1536/completion=256）"
            )
        if policy.unit_price_per_million_cny is not None:
            raise SettlementPolicyError("chat 不接受 unit 费率")
        if policy.input_price_per_million_cny is None or policy.output_price_per_million_cny is None:
            raise SettlementPolicyError("chat 必须同时固化输入/输出费率")
        if (
            policy.input_price_per_million_cny < CHAT_INPUT_PRICE_FLOOR
            or policy.output_price_per_million_cny < CHAT_OUTPUT_PRICE_FLOOR
        ):
            raise SettlementPolicyError("chat 费率低于已核实最低保守费率，拒绝")
    else:
        expected_cap = (
            EMBEDDING_TOTAL_TOKENS_CAP
            if policy.kind == KIND_EMBEDDING
            else RERANK_TOTAL_TOKENS_CAP
        )
        if (
            policy.total_tokens_cap != expected_cap
            or policy.prompt_tokens_cap is not None
            or policy.completion_tokens_cap is not None
        ):
            raise SettlementPolicyError(
                f"{policy.kind} 准入 cap 必须精确固化 total={expected_cap}"
            )
        if (
            policy.input_price_per_million_cny is not None
            or policy.output_price_per_million_cny is not None
        ):
            raise SettlementPolicyError(f"{policy.kind} 不接受输入/输出分项费率")
        if policy.unit_price_per_million_cny is None:
            raise SettlementPolicyError(f"{policy.kind} 必须固化 unit 费率")
        floor = (
            EMBEDDING_UNIT_PRICE_FLOOR
            if policy.kind == KIND_EMBEDDING
            else RERANK_UNIT_PRICE_FLOOR
        )
        if policy.unit_price_per_million_cny < floor:
            raise SettlementPolicyError(f"{policy.kind} 费率低于已核实最低保守费率，拒绝")
        if not policy.unit_price_per_million_cny.is_finite():
            raise SettlementPolicyError(f"{policy.kind} 费率必须有限")


def build_policy(
    kind: str,
    *,
    model: str,
    provider: str | None = None,
    host: str | None = None,
    region: str | None = None,
    input_price_per_million_cny: Any | None = None,
    output_price_per_million_cny: Any | None = None,
    unit_price_per_million_cny: Any | None = None,
) -> SettlementPolicy:
    """构造 v1 policy；来源只能取已知集合，费率可更高（>= 已核实最低保守费率）。"""
    if kind == KIND_CHAT:
        source = _CHAT_SOURCE
        return SettlementPolicy(
            version=SETTLEMENT_VERSION,
            kind=kind,
            provider=provider or source["provider"],
            model=model,
            host=host or source["host"],
            region=region or source["region"],
            pricing_source=source["pricing_source"],
            prompt_tokens_cap=CHAT_PROMPT_TOKENS_CAP,
            completion_tokens_cap=CHAT_COMPLETION_TOKENS_CAP,
            total_tokens_cap=None,
            input_price_per_million_cny=_decimal(
                input_price_per_million_cny
                if input_price_per_million_cny is not None
                else CHAT_INPUT_PRICE_FLOOR,
                "chat 输入费率",
            ),
            output_price_per_million_cny=_decimal(
                output_price_per_million_cny
                if output_price_per_million_cny is not None
                else CHAT_OUTPUT_PRICE_FLOOR,
                "chat 输出费率",
            ),
            unit_price_per_million_cny=None,
        )
    if kind in (KIND_EMBEDDING, KIND_RERANK):
        source = _EMBEDDING_SOURCE if kind == KIND_EMBEDDING else _RERANK_SOURCE
        floor = (
            EMBEDDING_UNIT_PRICE_FLOOR if kind == KIND_EMBEDDING else RERANK_UNIT_PRICE_FLOOR
        )
        return SettlementPolicy(
            version=SETTLEMENT_VERSION,
            kind=kind,
            provider=provider or source["provider"],
            model=model,
            host=host or source["host"],
            region=region or source["region"],
            pricing_source=source["pricing_source"],
            prompt_tokens_cap=None,
            completion_tokens_cap=None,
            total_tokens_cap=(
                EMBEDDING_TOTAL_TOKENS_CAP if kind == KIND_EMBEDDING else RERANK_TOTAL_TOKENS_CAP
            ),
            input_price_per_million_cny=None,
            output_price_per_million_cny=None,
            unit_price_per_million_cny=_decimal(
                unit_price_per_million_cny
                if unit_price_per_million_cny is not None
                else floor,
                f"{kind} unit 费率",
            ),
        )
    raise SettlementPolicyError(
        "未知结算 kind（仅支持 chat/embedding/rerank，OCR 不在 J1 范围）"
    )


def policy_to_snapshot(policy: SettlementPolicy) -> dict[str, Any]:
    """白名单持久化：只写公共计数/价格/绑定，不含任何 key/secret/Authorization。"""
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "version": policy.version,
        "kind": policy.kind,
        "provider": policy.provider,
        "model": policy.model,
        "host": policy.host,
        "region": policy.region,
        "pricing_source": policy.pricing_source,
        "caps": {
            "prompt_tokens": policy.prompt_tokens_cap,
            "completion_tokens": policy.completion_tokens_cap,
            "total_tokens": policy.total_tokens_cap,
        },
        "rates": {
            "input_per_million_cny": (
                None
                if policy.input_price_per_million_cny is None
                else canonical_decimal(policy.input_price_per_million_cny)
            ),
            "output_per_million_cny": (
                None
                if policy.output_price_per_million_cny is None
                else canonical_decimal(policy.output_price_per_million_cny)
            ),
            "unit_per_million_cny": (
                None
                if policy.unit_price_per_million_cny is None
                else canonical_decimal(policy.unit_price_per_million_cny)
            ),
        },
    }


def policy_from_snapshot(snapshot: Any) -> SettlementPolicy:
    """严格重建快照；未知/缺字段/多字段/类型不符一律 fail closed。"""
    if not isinstance(snapshot, Mapping):
        raise SettlementPolicyError("settlement_policy 快照必须是对象")
    if set(snapshot) != _POLICY_SNAPSHOT_KEYS:
        raise SettlementPolicyError("settlement_policy 快照字段集合非法")
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise SettlementPolicyError("settlement_policy schema_version 非法")
    caps = snapshot.get("caps")
    rates = snapshot.get("rates")
    if not isinstance(caps, Mapping) or set(caps) != _CAP_KEYS:
        raise SettlementPolicyError("settlement_policy caps 非法")
    if not isinstance(rates, Mapping) or set(rates) != _RATE_KEYS:
        raise SettlementPolicyError("settlement_policy rates 非法")

    def optional_int(value: Any, label: str) -> int | None:
        if value is None:
            return None
        if not _plain_int(value) or value < 0:
            raise SettlementPolicyError(f"{label} 必须是非负整数或 null")
        return value

    def optional_rate(value: Any, label: str) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise SettlementPolicyError(f"{label} 必须是十进制字符串或 null")
        return _decimal(value, label)

    def required_text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value:
            raise SettlementPolicyError(f"{label} 必须是非空字符串")
        return value

    return SettlementPolicy(
        version=required_text(snapshot.get("version"), "version"),
        kind=required_text(snapshot.get("kind"), "kind"),
        provider=required_text(snapshot.get("provider"), "provider"),
        model=required_text(snapshot.get("model"), "model"),
        host=required_text(snapshot.get("host"), "host"),
        region=required_text(snapshot.get("region"), "region"),
        pricing_source=required_text(snapshot.get("pricing_source"), "pricing_source"),
        prompt_tokens_cap=optional_int(caps.get("prompt_tokens"), "caps.prompt_tokens"),
        completion_tokens_cap=optional_int(caps.get("completion_tokens"), "caps.completion_tokens"),
        total_tokens_cap=optional_int(caps.get("total_tokens"), "caps.total_tokens"),
        input_price_per_million_cny=optional_rate(
            rates.get("input_per_million_cny"), "rates.input_per_million_cny"
        ),
        output_price_per_million_cny=optional_rate(
            rates.get("output_per_million_cny"), "rates.output_per_million_cny"
        ),
        unit_price_per_million_cny=optional_rate(
            rates.get("unit_per_million_cny"), "rates.unit_per_million_cny"
        ),
    )


@dataclass(frozen=True)
class UsageEvidence:
    """未来受控 adapter 整理的“本地观测声明”；J1 只校验，不证明供应商账单。"""

    kind: str
    provider: str
    model: str
    host: str
    region: str
    pricing_source: str
    request_sha256: str
    http_status: Any
    streamed: Any = False
    finish_reason: Any = None
    content_complete: Any = False
    content_parse_ok: Any = False
    output_valid: Any = False
    usage: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SettlementDecision:
    accepted: bool
    reason: str | None
    stop_required: bool
    boundary_anomaly: bool
    charge_cny: Decimal
    estimated_list_price_cny: Decimal
    release_cny: Decimal
    usage_fields: Mapping[str, int]
    evidence_snapshot: Mapping[str, Any]


def _sanitized_usage(usage: Any, allowed: frozenset[str]) -> dict[str, int]:
    """白名单 usage 过滤：只保留 ``allowed`` 里的计数字段（int 非 bool 非负）。

    未知键（含把凭据形态串当键名的未知键）、非字符串键、嵌套结构、非计数
    值一律丢弃，绝不把原文写入 reason/事件/异常文本（S2-J1-R1 D-1）。
    """
    clean: dict[str, int] = {}
    if not isinstance(usage, Mapping):
        return clean
    for key, value in usage.items():
        if not isinstance(key, str) or key not in allowed:
            continue
        if _plain_int(value) and value >= 0:
            clean[key] = int(value)
    return clean


def sanitize_usage_for_kind(kind: Any, usage: Any) -> dict[str, int]:
    """拒绝 result 持久化用的白名单 usage（按 kind 选允许字段集合）。

    - 仅接受本版本支持的 chat / embedding / rerank；未知 kind 返回空（宁缺勿漏）；
    - 未知键、非字符串键、嵌套/非法值一律不落盘，避免绕过白名单持久化凭据形态串；
    - 正常白名单计数值原样保留，供拒绝审计。
    """
    if kind == KIND_CHAT:
        allowed = _CHAT_USAGE_FIELDS
    elif kind in (KIND_EMBEDDING, KIND_RERANK):
        allowed = _TOTAL_USAGE_FIELDS
    else:
        return {}
    return _sanitized_usage(usage, allowed)


# ---------------------------------------------------------------------------
# S2-J1-R2 F-2：拒绝 reason 的显式白名单与安全兜底
# ---------------------------------------------------------------------------

UNCLASSIFIED_REJECTION_REASON = "unclassified_rejection"
"""白名单外的拒绝 reason 统一兜底码：稳定、可枚举、不含任何输入原文。"""

_SETTLEMENT_REJECTION_REASONS = frozenset(
    {
        # settlement_policy._Rejected 的稳定码（只能由本模块内部字面量产生）
        "usage_not_mapping",
        "usage_key_not_string",
        "unknown_usage_field",
        "total_mismatch",
        "cache_split_mismatch",
        "reasoning_over_completion",
        "over_cap_prompt",
        "over_cap_completion",
        "http_status_invalid",
        "streamed_not_false",
        "finish_reason_not_stop",
        "content_incomplete",
        "content_not_parsed",
        "output_invalid",
        "total_tokens_zero",
        "usage_contradiction",
        "over_cap_total",
        "binding_kind_mismatch",
        "binding_provider_mismatch",
        "binding_model_mismatch",
        "binding_request_sha256_mismatch",
        "binding_evidence_kind_mismatch",
        "binding_evidence_provider_mismatch",
        "binding_evidence_model_mismatch",
        "binding_evidence_host_mismatch",
        "binding_evidence_region_mismatch",
        "binding_evidence_pricing_source_mismatch",
        "reservation_request_sha256_missing",
        # budget 账本层的稳定拒绝码（非法快照 / 无快照旧预留）
        "invalid_policy_snapshot",
        "legacy_reservation_without_policy",
    }
)
"""settle_usage 拒绝路径允许持久化/回显的完整稳定 reason 词汇表。"""

_REJECTION_REASON_PREFIXES = ("usage_missing:", "usage_not_int:", "usage_negative:")
_REJECTION_REASON_FIELD_NAMES = _CHAT_USAGE_FIELDS | _TOTAL_USAGE_FIELDS


def sanitize_settlement_reason(reason: Any) -> str:
    """拒绝 reason 白名单过滤（S2-J1-R2 F-2）。

    - 白名单内的稳定 reason 码原样返回（保持既有合法 reason 与事件语义不变）；
    - 允许 ``usage_missing:`` / ``usage_not_int:`` / ``usage_negative:`` 受控前缀，
      但后缀必须是**内部 usage 字段字面量**（prompt_tokens 等）；
    - 其余任意输入（未知码、外部原文、非字符串、空串、超长串）一律返回稳定兜底码
      ``UNCLASSIFIED_REJECTION_REASON``：原文绝不进入 ``error_code``、
      ``settlement_rejected.reason`` 或相关异常文本。
    """
    if isinstance(reason, str):
        if reason in _SETTLEMENT_REJECTION_REASONS:
            return reason
        for prefix in _REJECTION_REASON_PREFIXES:
            if (
                reason.startswith(prefix)
                and reason[len(prefix) :] in _REJECTION_REASON_FIELD_NAMES
            ):
                return reason
    return UNCLASSIFIED_REJECTION_REASON


def _usage_mapping(evidence: UsageEvidence) -> dict[str, Any]:
    if not isinstance(evidence.usage, Mapping):
        raise _Rejected("usage_not_mapping")
    usage: dict[str, Any] = {}
    for key, value in evidence.usage.items():
        if not isinstance(key, str):
            raise _Rejected("usage_key_not_string")
        usage[key] = value
    return usage


def _require_int(usage: Mapping[str, Any], key: str) -> int:
    if key not in usage:
        raise _Rejected(f"usage_missing:{key}")
    value = usage[key]
    if not _plain_int(value):
        raise _Rejected(f"usage_not_int:{key}")
    if value < 0:
        raise _Rejected(f"usage_negative:{key}")
    return int(value)


def _optional_int(usage: Mapping[str, Any], key: str) -> int | None:
    if key not in usage:
        return None
    value = usage[key]
    if not _plain_int(value):
        raise _Rejected(f"usage_not_int:{key}")
    if value < 0:
        raise _Rejected(f"usage_negative:{key}")
    return int(value)


def _check_unknown_usage_fields(usage: Mapping[str, Any], allowed: frozenset[str]) -> None:
    if any(key not in allowed for key in usage):
        # D-1：拒绝 reason 只用稳定码，**不拼未知字段名**。未知键名可能本身就是
        # 凭据形态串（如 "api_key=sk-…"），一旦进入 reason 就会经 error_code、
        # settlement_rejected / 异常文本持久化，绕过白名单与通用 redactor。
        raise _Rejected("unknown_usage_field")


def _check_binding(policy: SettlementPolicy, reserved: Mapping[str, Any], evidence: UsageEvidence) -> None:
    if reserved.get("kind") != policy.kind:
        raise _Rejected("binding_kind_mismatch")
    if reserved.get("provider") != policy.provider:
        raise _Rejected("binding_provider_mismatch")
    if reserved.get("model") != policy.model:
        raise _Rejected("binding_model_mismatch")
    reserved_sha = reserved.get("request_sha256")
    if not isinstance(reserved_sha, str) or not reserved_sha:
        raise _Rejected("reservation_request_sha256_missing")
    if evidence.request_sha256 != reserved_sha:
        raise _Rejected("binding_request_sha256_mismatch")
    if evidence.kind != policy.kind:
        raise _Rejected("binding_evidence_kind_mismatch")
    if evidence.provider != policy.provider:
        raise _Rejected("binding_evidence_provider_mismatch")
    if evidence.model != policy.model:
        raise _Rejected("binding_evidence_model_mismatch")
    if evidence.host != policy.host:
        raise _Rejected("binding_evidence_host_mismatch")
    if evidence.region != policy.region:
        raise _Rejected("binding_evidence_region_mismatch")
    if evidence.pricing_source != policy.pricing_source:
        raise _Rejected("binding_evidence_pricing_source_mismatch")


def _validate_chat_evidence(evidence: UsageEvidence) -> dict[str, int]:
    if not _plain_int(evidence.http_status) or evidence.http_status != 200:
        raise _Rejected("http_status_invalid")
    if evidence.streamed is not False:
        raise _Rejected("streamed_not_false")
    if evidence.finish_reason != "stop":
        raise _Rejected("finish_reason_not_stop")
    if evidence.content_complete is not True:
        raise _Rejected("content_incomplete")
    if evidence.content_parse_ok is not True:
        raise _Rejected("content_not_parsed")
    usage = _usage_mapping(evidence)
    _check_unknown_usage_fields(usage, _CHAT_USAGE_FIELDS)
    prompt = _require_int(usage, "prompt_tokens")
    completion = _require_int(usage, "completion_tokens")
    total = _require_int(usage, "total_tokens")
    hit = _require_int(usage, "prompt_cache_hit_tokens")
    miss = _require_int(usage, "prompt_cache_miss_tokens")
    if total != prompt + completion:
        raise _Rejected("total_mismatch")
    if hit + miss != prompt:
        raise _Rejected("cache_split_mismatch")
    reasoning = _optional_int(usage, "reasoning_tokens")
    if reasoning is not None and reasoning > completion:
        raise _Rejected("reasoning_over_completion")
    if prompt > CHAT_PROMPT_TOKENS_CAP:
        raise _Rejected("over_cap_prompt")
    if completion > CHAT_COMPLETION_TOKENS_CAP:
        raise _Rejected("over_cap_completion")
    fields = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
    }
    if reasoning is not None:
        fields["reasoning_tokens"] = reasoning
    return fields


def _validate_total_evidence(
    policy: SettlementPolicy, evidence: UsageEvidence
) -> dict[str, int]:
    if not _plain_int(evidence.http_status) or evidence.http_status != 200:
        raise _Rejected("http_status_invalid")
    if evidence.output_valid is not True:
        raise _Rejected("output_invalid")
    usage = _usage_mapping(evidence)
    _check_unknown_usage_fields(usage, _TOTAL_USAGE_FIELDS)
    total = _require_int(usage, "total_tokens")
    if total < 1:
        raise _Rejected("total_tokens_zero")
    extras: dict[str, int] = {"total_tokens": total}
    for key in usage:
        if key == "total_tokens":
            continue
        value = _require_int(usage, key)
        extras[key] = value
    # 额外字段只允许“不矛盾”的存在；计价一律用 total_tokens，绝不用它们覆盖 total。
    if "prompt_tokens" in extras and extras["prompt_tokens"] > total:
        raise _Rejected("usage_contradiction")
    if "completion_tokens" in extras and extras["completion_tokens"] > 0:
        raise _Rejected("usage_contradiction")
    for key in ("reasoning_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        if key in extras and extras[key] > total:
            raise _Rejected("usage_contradiction")
    if policy.total_tokens_cap is not None and total > policy.total_tokens_cap:
        raise _Rejected("over_cap_total")
    return extras


def _charge(policy: SettlementPolicy, fields: Mapping[str, int]) -> Decimal:
    if policy.kind == KIND_CHAT:
        assert policy.input_price_per_million_cny is not None  # 由 policy 校验保证
        assert policy.output_price_per_million_cny is not None
        total = (
            Decimal(fields["prompt_tokens"]) * policy.input_price_per_million_cny
            + Decimal(fields["completion_tokens"]) * policy.output_price_per_million_cny
        ) / _MILLION
    else:
        assert policy.unit_price_per_million_cny is not None  # 由 policy 校验保证
        total = Decimal(fields["total_tokens"]) * policy.unit_price_per_million_cny / _MILLION
    return _amount(total)


def _evidence_snapshot_prefix(
    evidence: UsageEvidence,
) -> dict[str, Any]:
    return {
        "version": SETTLEMENT_VERSION,
        "kind": evidence.kind,
        "provider": evidence.provider,
        "model": evidence.model,
        "host": evidence.host,
        "region": evidence.region,
        "pricing_source": evidence.pricing_source,
        "request_sha256": evidence.request_sha256,
        "http_status": evidence.http_status if _plain_int(evidence.http_status) else None,
        "streamed": evidence.streamed if _plain_bool(evidence.streamed) else None,
        "finish_reason": evidence.finish_reason if isinstance(evidence.finish_reason, str) else None,
        "content_complete": evidence.content_complete if _plain_bool(evidence.content_complete) else None,
        "content_parse_ok": (
            evidence.content_parse_ok if _plain_bool(evidence.content_parse_ok) else None
        ),
        "output_valid": evidence.output_valid if _plain_bool(evidence.output_valid) else None,
    }


def evaluate_settlement(
    policy: SettlementPolicy,
    *,
    reserved: Mapping[str, Any],
    evidence: UsageEvidence,
    reserve_cny: Any,
) -> SettlementDecision:
    """校验 evidence 并按 policy 重算。任何不合格都返回 accepted=False（不抛业务异常）。"""
    if not isinstance(policy, SettlementPolicy) or not isinstance(reserved, Mapping):
        raise SettlementPolicyError("evaluate_settlement 参数类型非法")
    reserve = _decimal(reserve_cny, "reserve_cny")
    if reserve < 0:
        raise SettlementPolicyError("reserve_cny 不得为负")
    # D-1：拒绝路径同样只返回该 kind 的白名单计数字段；未知键/嵌套/凭据形态串
    # 一律不进入决策（更不会进入事件/异常文本/日志）。
    allowed_usage_fields = _CHAT_USAGE_FIELDS if policy.kind == KIND_CHAT else _TOTAL_USAGE_FIELDS
    try:
        _check_binding(policy, reserved, evidence)
        if policy.kind == KIND_CHAT:
            fields = _validate_chat_evidence(evidence)
        else:
            fields = _validate_total_evidence(policy, evidence)
        charge = _charge(policy, fields)
    except _Rejected as rejected:
        return SettlementDecision(
            accepted=False,
            reason=rejected.reason,
            stop_required=True,
            boundary_anomaly=False,
            charge_cny=_amount(reserve),
            estimated_list_price_cny=Decimal("0"),
            release_cny=Decimal("0"),
            usage_fields=_sanitized_usage(evidence.usage, allowed_usage_fields),
            evidence_snapshot=_evidence_snapshot_prefix(evidence),
        )
    boundary = charge > reserve
    release = reserve - charge if charge < reserve else Decimal("0")
    snapshot = _evidence_snapshot_prefix(evidence)
    snapshot["usage"] = fields
    snapshot["recomputed_conservative_charge_cny"] = canonical_decimal(charge)
    return SettlementDecision(
        accepted=True,
        reason=None,
        stop_required=boundary,
        boundary_anomaly=boundary,
        charge_cny=charge,
        estimated_list_price_cny=charge,
        release_cny=_amount(release),
        usage_fields=fields,
        evidence_snapshot=snapshot,
    )


def usage_evidence_from_settlement_block(block: Any) -> tuple[UsageEvidence, Decimal]:
    """重放：从账本 result 的 settlement 块严格重建 evidence + 声明金额。"""
    if not isinstance(block, Mapping):
        raise SettlementPolicyError("settlement 块必须是对象")
    if set(block) != _SETTLEMENT_BLOCK_KEYS:
        raise SettlementPolicyError("settlement 块字段集合非法")
    if block.get("version") != SETTLEMENT_VERSION:
        raise SettlementPolicyError("settlement 块版本非法")

    def text(key: str) -> str:
        value = block.get(key)
        if not isinstance(value, str) or not value:
            raise SettlementPolicyError(f"settlement.{key} 必须是非空字符串")
        return value

    def optional_int_value(key: str) -> int | None:
        value = block.get(key)
        if value is None:
            return None
        if not _plain_int(value):
            raise SettlementPolicyError(f"settlement.{key} 必须是整数或 null")
        return int(value)

    usage = block.get("usage")
    if not isinstance(usage, Mapping) or not usage:
        raise SettlementPolicyError("settlement.usage 必须是非空对象")

    def optional_bool(key: str) -> bool | None:
        value = block.get(key)
        if value is None:
            return None
        if not _plain_bool(value):
            raise SettlementPolicyError(f"settlement.{key} 必须是布尔或 null")
        return value

    evidence = UsageEvidence(
        kind=text("kind"),
        provider=text("provider"),
        model=text("model"),
        host=text("host"),
        region=text("region"),
        pricing_source=text("pricing_source"),
        request_sha256=text("request_sha256"),
        http_status=optional_int_value("http_status"),
        streamed=optional_bool("streamed"),
        finish_reason=block.get("finish_reason"),
        content_complete=optional_bool("content_complete"),
        content_parse_ok=optional_bool("content_parse_ok"),
        output_valid=optional_bool("output_valid"),
        usage=dict(usage),
    )
    declared = _decimal(block.get("recomputed_conservative_charge_cny"), "recomputed_conservative_charge_cny")
    if declared < 0:
        raise SettlementPolicyError("recomputed_conservative_charge_cny 不得为负")
    return evidence, _amount(declared)


def evidence_snapshot_json(decision: SettlementDecision) -> dict[str, Any]:
    """账本事件里可持久化的白名单证据块（计数/价格/绑定，无 secret）。"""
    if not decision.accepted or decision.evidence_snapshot is None:
        raise SettlementPolicyError("只有 accepted 决策才有可持久化证据块")
    block = dict(decision.evidence_snapshot)
    block["usage"] = dict(decision.usage_fields)
    block["recomputed_conservative_charge_cny"] = canonical_decimal(decision.charge_cny)
    return block


__all__ = [
    "CHAT_COMPLETION_TOKENS_CAP",
    "CHAT_INPUT_PRICE_FLOOR",
    "CHAT_OUTPUT_PRICE_FLOOR",
    "CHAT_PROMPT_TOKENS_CAP",
    "EMBEDDING_TOTAL_TOKENS_CAP",
    "EMBEDDING_UNIT_PRICE_FLOOR",
    "KIND_CHAT",
    "KIND_EMBEDDING",
    "KIND_RERANK",
    "RERANK_TOTAL_TOKENS_CAP",
    "RERANK_UNIT_PRICE_FLOOR",
    "SETTLEMENT_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "SUPPORTED_KINDS",
    "UNCLASSIFIED_REJECTION_REASON",
    "SettlementDecision",
    "SettlementPolicy",
    "SettlementPolicyError",
    "UsageEvidence",
    "build_policy",
    "canonical_decimal",
    "evaluate_settlement",
    "evidence_snapshot_json",
    "policy_from_snapshot",
    "policy_to_snapshot",
    "sanitize_settlement_reason",
    "sanitize_usage_for_kind",
    "usage_evidence_from_settlement_block",
]
