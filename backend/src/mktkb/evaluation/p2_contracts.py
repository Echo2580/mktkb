"""P2-T201：请求计划 / 预检 / 授权 / 运行结果的纯契约（DTO + 严格校验）。

为什么单独一个模块（任务书 §6.2）：
- P2 的 runner（T203）、OCR（T204）、确定性评分（T205）、Ragas 裁判（T208）都要用
  **同一套** 计划/预检/授权/结果定义；接口一旦分散，后续包就会各自发明同名概念；
- 金额与请求的准入必须能**离线证明**：计划里的每一次底层调用（索引 embedding、查询
  embedding、rerank、query expansion、answer、每页 OCR、裁判框架嵌套调用、独立复验）
  都要单独列出成本上界；本模块只做纯校验与计价，不读环境、不读写账本、不发 HTTP；
- 价格不允许「填 0 或猜低上界」获得准入：chat/embedding/rerank 的准入 caps 与费率下限、
  OCR 的每页固定价都冻结在 J1/S2-J2 已核来源上，计划只能引用、不能自降；
- 阶段与内部成本中心同时限额：stage_limit_cny 是 P2 新增阶段的硬顶（候选 20 元），
  四个成本中心（answer_retrieval/ocr/judge/independent）各自有上限且合计必须等于阶段额度，
  所以「每个中心都能各花 20 元」这种读法在数据上不成立。

冻结的 schema_version：p2-run-plan/v0.1、p2-ledger-snapshot/v0.1、
p2-preflight/v0.1、p2-authorization/v0.1、p2-run-result/v0.1。
任何未声明字段/缺失字段/类型不符（含 bool 当 int、NaN/Inf、负数、0 价、缺 token 上界）
一律拒绝：错误只带稳定原因码与内部字段名，不回显外部原文。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Mapping

from ..numeric import finite_non_negative, finite_positive, positive_int
from ..rag.settlement_policy import (
    CHAT_COMPLETION_TOKENS_CAP,
    CHAT_INPUT_PRICE_FLOOR,
    CHAT_OUTPUT_PRICE_FLOOR,
    CHAT_PROMPT_TOKENS_CAP,
    EMBEDDING_TOTAL_TOKENS_CAP,
    EMBEDDING_UNIT_PRICE_FLOOR,
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_RERANK,
    RERANK_TOTAL_TOKENS_CAP,
    RERANK_UNIT_PRICE_FLOOR,
    build_policy,
)

__all__ = [
    "ATTEMPTS_SCOPES",
    "ATTEMPTS_SCOPE_ALL",
    "ATTEMPTS_SCOPE_UNAVAILABLE",
    "COST_CENTERS",
    "HARD_MAX_REQUESTS",
    "OPERATIONS",
    "OPERATION_COST_CENTER",
    "OPERATION_KIND",
    "P2_AUTHORIZATION_SCHEMA_VERSION",
    "P2_LEDGER_SNAPSHOT_SCHEMA_VERSION",
    "P2_PREFLIGHT_SCHEMA_VERSION",
    "P2_RUN_MODES",
    "P2_RUN_PLAN_SCHEMA_VERSION",
    "P2_RUN_RESULT_SCHEMA_VERSION",
    "P2_RUN_STATUSES",
    "P2_STAGE",
    "P2Authorization",
    "P2ContractError",
    "P2LedgerSnapshot",
    "P2PreflightResult",
    "P2PriceProfile",
    "P2RequestItem",
    "P2RunPlan",
    "P2RunResult",
    "PRICE_KINDS",
    "canonical_decimal",
    "payload_sha256",
]

P2_STAGE = "P2-LIVE"
"""P2 唯一新增阶段名。旧 P1/S2 阶段（S2-DEV/P1-RETRIEVAL 等）不因此获得 P2 权限。"""

P2_RUN_PLAN_SCHEMA_VERSION = "p2-run-plan/v0.1"
P2_LEDGER_SNAPSHOT_SCHEMA_VERSION = "p2-ledger-snapshot/v0.1"
P2_PREFLIGHT_SCHEMA_VERSION = "p2-preflight/v0.1"
P2_AUTHORIZATION_SCHEMA_VERSION = "p2-authorization/v0.1"
P2_RUN_RESULT_SCHEMA_VERSION = "p2-run-result/v0.1"

P2_RUN_MODES = frozenset({"end_to_end"})
"""P2 只允许产品端到端模式（不是「直接调 RagIndex.ask」的检索模式）。"""

P2_RUN_STATUSES = frozenset({"succeeded", "blocked", "aborted"})

ATTEMPTS_SCOPE_ALL = "all_attempts"
ATTEMPTS_SCOPE_UNAVAILABLE = "unavailable"
ATTEMPTS_SCOPES = frozenset({ATTEMPTS_SCOPE_ALL, ATTEMPTS_SCOPE_UNAVAILABLE})
"""run_result 里 attempts_* 字段的口径标签（T207-FIX-B/A，additive）。

- ``all_attempts``：attempts_* 由 runner 的逐次尝试核对（attempt_audit）填，覆盖
  answer 轮 + 从属尝试（index/query embedding、rerank、query_expansion、OCR）；
- ``unavailable``：本次结果没有逐次尝试账（如 ``P2Gate.result()`` 早于核对，或发送前就
  被拒），此时 attempts_* 必须为空/0 —— 不用 answer 口径冒充全量。
"""

HARD_MAX_REQUESTS = 1600
"""累计请求硬顶（= 现有 MAX_GO_REQUESTS，两处必须同值）。

2026-11-11 经理按主人 2026-11-10 预授权「必要时应实算提至 <=2000，且 GO 在 P2<=50 元、
累计请求<=2000 内由经理拟定」落盘：**1000 -> 1600**（记录见
docs/reports/OBS-EVAL/P2/T207/PM/T207-PM-decisions-01.md 的 §3）。

实算依据（逐项）：已用 547 + T207 公开 263 + H2 回合 144 + H2 灌库 <=20 +
T208 judge <=160 + T900 独立复验 <=107 = 1,241；+20% 余量 ≈ 1,489 -> 取整 1600。

**到值即停**：累计 reservation 到 1600 时，任何发送前的 request_limit（P2Gate）与
go_max_requests_over_hard_cap（授权）都会拒绝；各计划自身的 max_requests 永远是更早的闸门。
新增预算仍**不重置**已用计数。

跨范围影响：MAX_GO_REQUESTS 同时是 P1 live_authorization 的天花板，本值只抬高「共同
天花板」；P1 已签 GO 的 max_requests 仍各自生效（两侧取 min），因此**不构成**对 P1 的
追加授权。
"""

COST_CENTERS: tuple[str, ...] = ("answer_retrieval", "ocr", "judge", "independent")
"""四个内部成本中心（不是四个可各花满额的阶段）。"""

OPERATIONS: tuple[str, ...] = (
    "index_embedding",
    "query_embedding",
    "rerank",
    "query_expansion",
    "answer",
    "ocr",
    "judge",
    "independent",
)
"""P2 计划必须逐项列出的底层调用种类（case/turn/page/request 分开计，1 题 != 1 请求）。"""

OPERATION_COST_CENTER: Mapping[str, str] = {
    "index_embedding": "answer_retrieval",
    "query_embedding": "answer_retrieval",
    "rerank": "answer_retrieval",
    "query_expansion": "answer_retrieval",
    "answer": "answer_retrieval",
    "ocr": "ocr",
    "judge": "judge",
    "independent": "independent",
}
"""操作到成本中心的唯一映射：计划可以声明 cost_center，但必须与之逐值一致。"""

OPERATION_KIND: Mapping[str, str] = {
    "index_embedding": KIND_EMBEDDING,
    "query_embedding": KIND_EMBEDDING,
    "rerank": KIND_RERANK,
    "query_expansion": KIND_CHAT,
    "answer": KIND_CHAT,
    "judge": KIND_CHAT,
    "independent": KIND_CHAT,
    "ocr": "ocr",
}
"""操作到计价 kind 的映射。judge 底层仍走 chat 供应商，但计价与授权归属独立。"""

PRICE_KINDS: tuple[str, ...] = (KIND_CHAT, KIND_EMBEDDING, KIND_RERANK, "ocr")

# 已核来源（与 J1 settlement_policy / S2-J2 OCR 受控价格同源；测试里交叉核对，防漂移）。
CHAT_PROVIDER = "deepseek"
CHAT_MODEL = "deepseek-flash"
CHAT_HOST = "api.deepseek.com"
CHAT_REGION = "global"
CHAT_PRICING_SOURCE = "official-list-price/deepseek-chat-cache-miss-v1"

EMBEDDING_PROVIDER = "bailian"
EMBEDDING_MODEL = "text-embedding-v4"
RERANK_PROVIDER = "bailian"
RERANK_MODEL = "gte-rerank-v2"
BAILIAN_HOST = "dashscope.aliyuncs.com"
BAILIAN_REGION = "cn-beijing"
EMBEDDING_PRICING_SOURCE = "official-list-price/bailian-text-embedding-v4-v1"
RERANK_PRICING_SOURCE = "official-list-price/bailian-gte-rerank-v2-v1"

OCR_PROVIDER = "tencent"
OCR_HOST = "ocr.tencentcloudapi.com"
OCR_REGION = "ap-guangzhou"
OCR_PRICING_SOURCE = "official-list-price/tencent-ocr-postpaid-highest-v1"
OCR_TEXT_MODEL = "GeneralAccurateOCR"
OCR_TABLE_MODEL = "RecognizeTableAccurateOCR"
OCR_TEXT_PRICE_CNY = 0.5
OCR_TABLE_PRICE_CNY = 0.15
OCR_PAGES_PER_REQUEST = 1

P2_PRICE_PROVIDER_BINDINGS: Mapping[str, Mapping[str, Any]] = {
    KIND_CHAT: {
        "provider": CHAT_PROVIDER,
        "host": CHAT_HOST,
        "region": CHAT_REGION,
        "pricing_source": CHAT_PRICING_SOURCE,
        "models": (CHAT_MODEL,),
    },
    KIND_EMBEDDING: {
        "provider": EMBEDDING_PROVIDER,
        "host": BAILIAN_HOST,
        "region": BAILIAN_REGION,
        "pricing_source": EMBEDDING_PRICING_SOURCE,
        "models": (EMBEDDING_MODEL,),
    },
    KIND_RERANK: {
        "provider": RERANK_PROVIDER,
        "host": BAILIAN_HOST,
        "region": BAILIAN_REGION,
        "pricing_source": RERANK_PRICING_SOURCE,
        "models": (RERANK_MODEL,),
    },
    "ocr": {
        "provider": OCR_PROVIDER,
        "host": OCR_HOST,
        "region": OCR_REGION,
        "pricing_source": OCR_PRICING_SOURCE,
        "models": (OCR_TEXT_MODEL, OCR_TABLE_MODEL),
    },
}

_OCR_PAGE_PRICE_CNY: Mapping[str, float] = {
    OCR_TEXT_MODEL: OCR_TEXT_PRICE_CNY,
    OCR_TABLE_MODEL: OCR_TABLE_PRICE_CNY,
}

_MILLION = Decimal(1_000_000)
_AMOUNT = Decimal("0.00000001")
_EPS = Decimal("0.000000001")
_MAX_TEXT = 200


class P2ContractError(ValueError):
    """P2 契约非法（计划/快照/DTO）。reason 是稳定原因码，文本只含内部字段名。"""

    code = "P2_CONTRACT_INVALID"

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = str(reason)
        self.detail = str(detail)


# ---------------------------------------------------------------- 通用严格校验


def canonical_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _money(value: Decimal) -> Decimal:
    return value.quantize(_AMOUNT, rounding=ROUND_CEILING)


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise P2ContractError("number_invalid", f"{label} 必须是数字（拒绝 bool/字符串/None）")
    number = float(value)
    if not (number == number) or number in (float("inf"), float("-inf")):
        raise P2ContractError("number_invalid", f"{label} 必须是有限数字（拒绝 NaN/±Infinity）")
    return Decimal(str(number))


def _positive_money(value: Any, label: str) -> Decimal:
    amount = _decimal(value, label)
    if amount <= 0:
        raise P2ContractError("amount_not_positive", f"{label} 必须为正数（拒绝 0 价/负数）")
    return amount


def _non_negative_money(value: Any, label: str) -> Decimal:
    amount = _decimal(value, label)
    if amount < 0:
        raise P2ContractError("amount_negative", f"{label} 不得为负数")
    return amount


def _plain_float(value: Any, label: str, *, minimum: float = 0.0) -> float:
    try:
        if minimum > 0:
            return float(finite_positive(value, label))
        return float(finite_non_negative(value, label))
    except ValueError as exc:  # NumericInvalid 是 ValueError
        raise P2ContractError("number_invalid", str(exc)) from None


def _plain_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if minimum > 0:
        try:
            return int(positive_int(value, label))
        except ValueError as exc:
            raise P2ContractError("integer_invalid", str(exc)) from None
    if isinstance(value, bool) or not isinstance(value, int):
        raise P2ContractError("integer_invalid", f"{label} 必须是整数（拒绝 bool）")
    if value < minimum:
        raise P2ContractError("integer_invalid", f"{label} 不得小于 {minimum}")
    return int(value)


def _text(value: Any, label: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise P2ContractError("text_invalid", f"{label} 必须是字符串")
    text = value.strip()
    if not text:
        raise P2ContractError("text_invalid", f"{label} 不得为空")
    if len(text) > maximum:
        raise P2ContractError("text_invalid", f"{label} 过长")
    if any(ch.isspace() for ch in text):
        raise P2ContractError("text_invalid", f"{label} 不得含空白")
    return text


def _plain_text(value: Any, label: str, *, maximum: int = _MAX_TEXT) -> str:
    """允许空格的文本（用于 issued_by 之类的自由文本）。"""
    if not isinstance(value, str):
        raise P2ContractError("text_invalid", f"{label} 必须是字符串")
    text = value.strip()
    if not text:
        raise P2ContractError("text_invalid", f"{label} 不得为空")
    if len(text) > maximum:
        raise P2ContractError("text_invalid", f"{label} 过长")
    return text


def _sha256_hex(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise P2ContractError("sha256_invalid", f"{label} 必须是字符串")
    text = value.strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise P2ContractError("sha256_invalid", f"{label} 必须是 64 位十六进制")
    return text


def _instant(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise P2ContractError("instant_missing", f"{label} 缺失")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise P2ContractError("instant_invalid", f"{label} 不是 ISO 时间") from None
    if moment.tzinfo is None:
        raise P2ContractError("instant_invalid", f"{label} 必须带时区")
    return moment


def _instant_text(value: Any, label: str) -> str:
    _instant(value, label)
    return str(value).strip()


def _exact_keys(data: Any, expected: tuple[str, ...] | frozenset[str], label: str) -> None:
    if not isinstance(data, Mapping):
        raise P2ContractError("mapping_required", f"{label} 必须是对象")
    keys = set(data)
    missing = sorted(set(expected) - keys)
    unknown = sorted(keys - set(expected))
    if missing:
        raise P2ContractError("field_missing", f"{label} 缺少字段 {missing}")
    if unknown:
        raise P2ContractError("field_unknown", f"{label} 含未声明字段 {unknown}")


def _optional_exact_keys(
    data: Any,
    required: frozenset[str],
    optional: frozenset[str],
    label: str,
) -> None:
    """必填键必须齐、未知键一律拒绝；``optional`` 里的 additive 键允许缺席（旧产物可读）。"""
    if not isinstance(data, Mapping):
        raise P2ContractError("mapping_required", f"{label} 必须是对象")
    keys = set(data)
    missing = sorted(set(required) - keys)
    unknown = sorted(keys - (set(required) | set(optional)))
    if missing:
        raise P2ContractError("field_missing", f"{label} 缺少字段 {missing}")
    if unknown:
        raise P2ContractError("field_unknown", f"{label} 含未声明字段 {unknown}")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def payload_sha256(payload: Mapping[str, Any]) -> str:
    """稳定摘要（排序键、紧凑分隔符、拒绝 NaN）。"""
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


# ---------------------------------------------------------------- 价格画像


_PROFILE_KEYS: Mapping[str, frozenset[str]] = {
    KIND_CHAT: frozenset(
        {
            "kind",
            "model",
            "provider",
            "host",
            "region",
            "pricing_source",
            "input_price_per_million_cny",
            "output_price_per_million_cny",
            "prompt_tokens_cap",
            "completion_tokens_cap",
        }
    ),
    KIND_EMBEDDING: frozenset(
        {
            "kind",
            "model",
            "provider",
            "host",
            "region",
            "pricing_source",
            "unit_price_per_million_cny",
            "total_tokens_cap",
        }
    ),
    KIND_RERANK: frozenset(
        {
            "kind",
            "model",
            "provider",
            "host",
            "region",
            "pricing_source",
            "unit_price_per_million_cny",
            "total_tokens_cap",
        }
    ),
    "ocr": frozenset(
        {
            "kind",
            "model",
            "provider",
            "host",
            "region",
            "pricing_source",
            "price_cny_per_page",
            "pages_per_request",
        }
    ),
}


@dataclass(frozen=True)
class P2PriceProfile:
    """冻结的单次请求价格/上界画像。

    - 结构与来源不能自造：provider/host/region/pricing_source/model 必须与已核来源逐值
      一致，费率只能 >= 已核下限（更高更保守允许，更低拒绝），OCR 每页价必须等于固定价；
    - token/页数上界必须显式声明且等于冻结 caps：拼错/漏填/写小都在构造期拒绝，因此
      「猜低 token 上界」不会换来更低的准入价。
    """

    kind: str
    model: str
    provider: str
    host: str
    region: str
    pricing_source: str
    prompt_tokens_cap: int | None = None
    completion_tokens_cap: int | None = None
    total_tokens_cap: int | None = None
    input_price_per_million_cny: float | None = None
    output_price_per_million_cny: float | None = None
    unit_price_per_million_cny: float | None = None
    price_cny_per_page: float | None = None
    pages_per_request: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in PRICE_KINDS:
            raise P2ContractError("price_kind_invalid", "price_profile.kind 未注册")
        binding = P2_PRICE_PROVIDER_BINDINGS[self.kind]
        for name in ("provider", "host", "region", "pricing_source"):
            if getattr(self, name) != binding[name]:
                raise P2ContractError("price_source_mismatch", f"price_profile.{name} 与已核来源不一致")
        if self.model not in binding["models"]:
            raise P2ContractError("price_model_invalid", "price_profile.model 不在已核模型集合")
        if self.kind == KIND_CHAT:
            self._validate_chat()
        elif self.kind in (KIND_EMBEDDING, KIND_RERANK):
            self._validate_total()
        else:
            self._validate_ocr()

    # ------------------------------------------------------------ 分 kind 校验

    def _validate_chat(self) -> None:
        if self.total_tokens_cap is not None or self.unit_price_per_million_cny is not None:
            raise P2ContractError("price_profile_shape", "chat 不接受 unit/total cap 字段")
        if self.prompt_tokens_cap != CHAT_PROMPT_TOKENS_CAP:
            raise P2ContractError(
                "cap_not_frozen", f"chat prompt_tokens_cap 必须冻结为 {CHAT_PROMPT_TOKENS_CAP}"
            )
        if self.completion_tokens_cap != CHAT_COMPLETION_TOKENS_CAP:
            raise P2ContractError(
                "cap_not_frozen",
                f"chat completion_tokens_cap 必须冻结为 {CHAT_COMPLETION_TOKENS_CAP}",
            )
        if self.input_price_per_million_cny is None or self.output_price_per_million_cny is None:
            raise P2ContractError("price_missing", "chat 必须声明输入/输出单价")
        if self.price_cny_per_page is not None or self.pages_per_request is not None:
            raise P2ContractError("price_profile_shape", "chat 不接受 OCR 价格字段")
        for label, value, floor in (
            ("input_price_per_million_cny", self.input_price_per_million_cny, CHAT_INPUT_PRICE_FLOOR),
            ("output_price_per_million_cny", self.output_price_per_million_cny, CHAT_OUTPUT_PRICE_FLOOR),
        ):
            amount = _positive_money(value, f"chat {label}")
            if amount < floor:
                raise P2ContractError(
                    "price_below_floor",
                    f"chat {label} 低于已核下限 {canonical_decimal(floor)}/百万",
                )

    def _validate_total(self) -> None:
        expected = (
            EMBEDDING_TOTAL_TOKENS_CAP if self.kind == KIND_EMBEDDING else RERANK_TOTAL_TOKENS_CAP
        )
        if self.total_tokens_cap != expected:
            raise P2ContractError(
                "cap_not_frozen", f"{self.kind} total_tokens_cap 必须冻结为 {expected}"
            )
        if (
            self.prompt_tokens_cap is not None
            or self.completion_tokens_cap is not None
            or self.input_price_per_million_cny is not None
            or self.output_price_per_million_cny is not None
            or self.price_cny_per_page is not None
            or self.pages_per_request is not None
        ):
            raise P2ContractError(
                "price_profile_shape", f"{self.kind} 不接受 prompt/completion 或 OCR 字段"
            )
        if self.unit_price_per_million_cny is None:
            raise P2ContractError("price_missing", f"{self.kind} 必须声明 unit 单价")
        floor = (
            EMBEDDING_UNIT_PRICE_FLOOR if self.kind == KIND_EMBEDDING else RERANK_UNIT_PRICE_FLOOR
        )
        amount = _positive_money(self.unit_price_per_million_cny, f"{self.kind} unit 单价")
        if amount < floor:
            raise P2ContractError(
                "price_below_floor",
                f"{self.kind} unit 单价低于已核下限 {canonical_decimal(floor)}/百万",
            )

    def _validate_ocr(self) -> None:
        if any(
            item is not None
            for item in (
                self.prompt_tokens_cap,
                self.completion_tokens_cap,
                self.total_tokens_cap,
                self.input_price_per_million_cny,
                self.output_price_per_million_cny,
                self.unit_price_per_million_cny,
            )
        ):
            raise P2ContractError("price_profile_shape", "ocr 不接受 token 价格/cap 字段")
        if self.pages_per_request != OCR_PAGES_PER_REQUEST:
            raise P2ContractError(
                "cap_not_frozen",
                f"ocr pages_per_request 必须冻结为 {OCR_PAGES_PER_REQUEST}（每页一次调用）",
            )
        expected = _OCR_PAGE_PRICE_CNY[self.model]
        amount = _positive_money(self.price_cny_per_page, "ocr 每页价")
        if amount != Decimal(str(expected)):
            raise P2ContractError(
                "price_below_floor",
                f"ocr 每页价必须等于固定价 {expected}（text/table 分别计价）",
            )

    # ------------------------------------------------------------ 派生金额

    @property
    def bound_cny(self) -> float:
        """单次请求的保守上界（元）；它是**准入**用的钱，不是成功估价。"""
        if self.kind == KIND_CHAT:
            total = (
                Decimal(self.prompt_tokens_cap)
                * _positive_money(self.input_price_per_million_cny, "chat 输入费率")
                + Decimal(self.completion_tokens_cap)
                * _positive_money(self.output_price_per_million_cny, "chat 输出费率")
            ) / _MILLION
            return float(_money(total))
        if self.kind in (KIND_EMBEDDING, KIND_RERANK):
            total = (
                Decimal(self.total_tokens_cap)
                * _positive_money(self.unit_price_per_million_cny, f"{self.kind} unit 费率")
                / _MILLION
            )
            return float(_money(total))
        return float(_money(_positive_money(self.price_cny_per_page, "ocr 每页价")))

    def settlement_policy(self):
        """按画像构造 J1 v1 结算 policy（chat/embedding/rerank）；OCR 固定价返回 None。"""
        if self.kind == KIND_CHAT:
            return build_policy(
                KIND_CHAT,
                model=self.model,
                input_price_per_million_cny=self.input_price_per_million_cny,
                output_price_per_million_cny=self.output_price_per_million_cny,
            )
        if self.kind in (KIND_EMBEDDING, KIND_RERANK):
            return build_policy(
                self.kind,
                model=self.model,
                unit_price_per_million_cny=self.unit_price_per_million_cny,
            )
        return None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "model": self.model,
            "provider": self.provider,
            "host": self.host,
            "region": self.region,
            "pricing_source": self.pricing_source,
        }
        if self.kind == KIND_CHAT:
            payload.update(
                {
                    "input_price_per_million_cny": float(self.input_price_per_million_cny),
                    "output_price_per_million_cny": float(self.output_price_per_million_cny),
                    "prompt_tokens_cap": int(self.prompt_tokens_cap),
                    "completion_tokens_cap": int(self.completion_tokens_cap),
                }
            )
        elif self.kind in (KIND_EMBEDDING, KIND_RERANK):
            payload.update(
                {
                    "unit_price_per_million_cny": float(self.unit_price_per_million_cny),
                    "total_tokens_cap": int(self.total_tokens_cap),
                }
            )
        else:
            payload.update(
                {
                    "price_cny_per_page": float(self.price_cny_per_page),
                    "pages_per_request": int(self.pages_per_request),
                }
            )
        return payload

    @classmethod
    def from_dict(cls, data: Any) -> "P2PriceProfile":
        if not isinstance(data, Mapping):
            raise P2ContractError("mapping_required", "price_profile 必须是对象")
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in _PROFILE_KEYS:
            raise P2ContractError("price_kind_invalid", "price_profile.kind 未注册")
        _exact_keys(data, _PROFILE_KEYS[kind], "price_profile")
        common = {
            "kind": kind,
            "model": _text(data["model"], "price_profile.model", maximum=64),
            "provider": _text(data["provider"], "price_profile.provider", maximum=64),
            "host": _text(data["host"], "price_profile.host"),
            "region": _text(data["region"], "price_profile.region", maximum=64),
            "pricing_source": _plain_text(data["pricing_source"], "price_profile.pricing_source"),
        }
        if kind == KIND_CHAT:
            return cls(
                **common,
                input_price_per_million_cny=_plain_float(
                    data["input_price_per_million_cny"],
                    "input_price_per_million_cny",
                    minimum=1e-12,
                ),
                output_price_per_million_cny=_plain_float(
                    data["output_price_per_million_cny"],
                    "output_price_per_million_cny",
                    minimum=1e-12,
                ),
                prompt_tokens_cap=_plain_int(
                    data["prompt_tokens_cap"], "prompt_tokens_cap", minimum=1
                ),
                completion_tokens_cap=_plain_int(
                    data["completion_tokens_cap"], "completion_tokens_cap", minimum=1
                ),
            )
        if kind in (KIND_EMBEDDING, KIND_RERANK):
            return cls(
                **common,
                unit_price_per_million_cny=_plain_float(
                    data["unit_price_per_million_cny"], "unit_price_per_million_cny", minimum=1e-12
                ),
                total_tokens_cap=_plain_int(
                    data["total_tokens_cap"], "total_tokens_cap", minimum=1
                ),
            )
        return cls(
            **common,
            price_cny_per_page=_plain_float(
                data["price_cny_per_page"], "price_cny_per_page", minimum=1e-12
            ),
            pages_per_request=_plain_int(
                data["pages_per_request"], "pages_per_request", minimum=1
            ),
        )


# ---------------------------------------------------------------- 计划项


_ITEM_KEYS = (
    "item_id",
    "operation",
    "cost_center",
    "case_id",
    "turn",
    "page",
    "requests",
    "price_profile",
    "expected_success_cny",
)


@dataclass(frozen=True)
class P2RequestItem:
    """一次（或一组同质）底层调用：case/turn/page/requests 分开列，1 题 != 1 请求。"""

    item_id: str
    operation: str
    cost_center: str
    case_id: str
    turn: int
    page: int
    requests: int
    price_profile: P2PriceProfile
    expected_success_cny: float = 0.0

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise P2ContractError("operation_unregistered", "operation 未注册")
        if self.cost_center != OPERATION_COST_CENTER[self.operation]:
            raise P2ContractError(
                "cost_center_mismatch",
                f"{self.operation} 的 cost_center 必须是 {OPERATION_COST_CENTER[self.operation]}",
            )
        if self.price_profile.kind != OPERATION_KIND[self.operation]:
            raise P2ContractError(
                "operation_price_kind_mismatch",
                f"{self.operation} 必须使用 {OPERATION_KIND[self.operation]} 价格画像",
            )
        if self.operation == "ocr":
            if self.page < 1:
                raise P2ContractError("page_required", "ocr 项必须给出 page>=1")
            if self.requests != self.price_profile.pages_per_request:
                raise P2ContractError(
                    "ocr_page_count_mismatch",
                    "ocr 每项必须恰好 1 次调用（逐页列条目：页号见 page，不按题数估算）",
                )
        elif self.page != 0:
            raise P2ContractError("page_forbidden", f"{self.operation} 不接受 page")
        estimate = _non_negative_money(self.expected_success_cny, "expected_success_cny")
        if estimate > Decimal(str(self.bound_cny)) + _EPS:
            raise P2ContractError("success_estimate_over_bound", "成功估价不得超过单次成本上界")

    @property
    def bound_cny(self) -> float:
        return self.price_profile.bound_cny

    @property
    def worst_case_cny(self) -> float:
        return float(_money(Decimal(str(self.bound_cny)) * Decimal(self.requests)))

    @property
    def estimated_success_total_cny(self) -> float:
        return float(_money(Decimal(str(self.expected_success_cny)) * Decimal(self.requests)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "operation": self.operation,
            "cost_center": self.cost_center,
            "case_id": self.case_id,
            "turn": int(self.turn),
            "page": int(self.page),
            "requests": int(self.requests),
            "price_profile": self.price_profile.as_dict(),
            "expected_success_cny": float(self.expected_success_cny),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "P2RequestItem":
        _exact_keys(data, _ITEM_KEYS, "plan.items[]")
        return cls(
            item_id=_text(data["item_id"], "item_id", maximum=96),
            operation=_text(data["operation"], "operation", maximum=48),
            cost_center=_text(data["cost_center"], "cost_center", maximum=48),
            case_id=_text(data["case_id"], "case_id", maximum=96),
            turn=_plain_int(data["turn"], "turn", minimum=1),
            page=_plain_int(data["page"], "page", minimum=0),
            requests=_plain_int(data["requests"], "requests", minimum=1),
            price_profile=P2PriceProfile.from_dict(data["price_profile"]),
            expected_success_cny=_plain_float(data["expected_success_cny"], "expected_success_cny"),
        )


# ---------------------------------------------------------------- 计划


_PLAN_KEYS = (
    "schema_version",
    "plan_id",
    "plan_version",
    "mode",
    "stage",
    "created_utc",
    "project_total_limit_cny",
    "stage_limit_cny",
    "max_requests",
    "cost_centers_cny",
    "items",
)


@dataclass(frozen=True)
class P2RunPlan:
    """冻结的 P2 请求计划（准入的唯一输入）。

    - stage 只能是 P2-LIVE：旧 P1/S2 阶段名一律拒绝；
    - cost_centers_cny 必须恰好四个已注册中心、各自为正、合计等于 stage_limit_cny；
      因此阶段额度是**硬顶**，不是「每个中心各得一份」；
    - max_requests 是**累计**口径（跨 kind/run，不因新增预算重置），上限
      HARD_MAX_REQUESTS；items 的请求总数不得超过它。
    """

    schema_version: str
    plan_id: str
    plan_version: str
    mode: str
    stage: str
    created_utc: str
    project_total_limit_cny: float
    stage_limit_cny: float
    max_requests: int
    cost_centers_cny: Mapping[str, float]
    items: tuple[P2RequestItem, ...]
    scenario_binding: Mapping[str, str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.scenario_binding is not None:
            from types import MappingProxyType
            from .p2_holdout_scenarios import validate_plan_scenario_binding
            validate_plan_scenario_binding(self.scenario_binding)
            object.__setattr__(self, 'scenario_binding', MappingProxyType(dict(self.scenario_binding)))
        if self.schema_version != P2_RUN_PLAN_SCHEMA_VERSION:
            raise P2ContractError(
                "schema_version_invalid",
                f"plan.schema_version 必须是 {P2_RUN_PLAN_SCHEMA_VERSION}",
            )
        _text(self.plan_id, "plan_id", maximum=96)
        _text(self.plan_version, "plan_version", maximum=32)
        if self.mode not in P2_RUN_MODES:
            raise P2ContractError("mode_invalid", f"plan.mode 必须是 {sorted(P2_RUN_MODES)} 之一")
        if self.stage != P2_STAGE:
            raise P2ContractError(
                "stage_invalid", f"plan.stage 必须是 {P2_STAGE}（旧阶段不获得 P2 权限）"
            )
        _instant(self.created_utc, "created_utc")
        project_total = _positive_money(self.project_total_limit_cny, "project_total_limit_cny")
        stage_limit = _positive_money(self.stage_limit_cny, "stage_limit_cny")
        if project_total < stage_limit:
            raise P2ContractError("plan_total_below_stage", "项目总上限不得小于 P2 阶段额度")
        _plain_int(self.max_requests, "max_requests", minimum=1)
        if self.max_requests > HARD_MAX_REQUESTS:
            raise P2ContractError(
                "request_cap_over_hard_limit",
                f"plan.max_requests 不得超过累计硬顶 {HARD_MAX_REQUESTS}",
            )
        if not isinstance(self.cost_centers_cny, Mapping):
            raise P2ContractError("mapping_required", "cost_centers_cny 必须是对象")
        if set(self.cost_centers_cny) != set(COST_CENTERS):
            raise P2ContractError(
                "cost_center_set_invalid",
                f"cost_centers_cny 必须恰好是 {list(COST_CENTERS)}（缺失/多出的中心默认拒绝）",
            )
        center_total = Decimal(0)
        for center in COST_CENTERS:
            center_total += _positive_money(
                self.cost_centers_cny[center], f"cost_centers_cny.{center}"
            )
        if center_total != stage_limit:
            raise P2ContractError(
                "cost_center_total_mismatch",
                f"四个成本中心合计必须等于阶段额度 {canonical_decimal(stage_limit)} 元",
            )
        if not isinstance(self.items, tuple) or not self.items:
            raise P2ContractError("items_required", "plan.items 必须是非空元组（空计划拒绝）")
        seen: set[str] = set()
        for item in self.items:
            if not isinstance(item, P2RequestItem):
                raise P2ContractError("items_required", "plan.items 只接受 P2RequestItem")
            if item.item_id in seen:
                raise P2ContractError("item_id_duplicate", "plan.items 存在重复 item_id")
            seen.add(item.item_id)
        needs = self.center_needs_cny()
        for center in COST_CENTERS:
            limit = Decimal(str(self.cost_centers_cny[center]))
            if Decimal(str(needs[center])) > limit + _EPS:
                raise P2ContractError(
                    "center_budget_exceeded",
                    f"成本中心 {center} 的计划上界超过其额度 {canonical_decimal(limit)} 元",
                )
        if self.total_requests > self.max_requests:
            raise P2ContractError("plan_requests_over_cap", "计划请求总数超过 plan.max_requests")
        if Decimal(str(self.worst_case_cny)) > stage_limit + _EPS:
            raise P2ContractError("plan_exceeds_stage_limit", "计划总成本上界超过阶段额度")

    # ------------------------------------------------------------ 派生统计

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(sorted({item.operation for item in self.items}))

    @property
    def total_requests(self) -> int:
        return sum(item.requests for item in self.items)

    @property
    def case_count(self) -> int:
        return len({item.case_id for item in self.items})

    @property
    def turn_count(self) -> int:
        return len({(item.case_id, item.turn) for item in self.items})

    @property
    def page_count(self) -> int:
        return len({(item.case_id, item.page) for item in self.items if item.operation == "ocr"})

    @property
    def worst_case_cny(self) -> float:
        return float(
            _money(sum((Decimal(str(item.worst_case_cny)) for item in self.items), Decimal(0)))
        )

    @property
    def reserve_peak_cny(self) -> float:
        """串行 + 自动重试 0 下的**单次在飞**峰值预留（不是成功估价）。"""
        return float(_money(max(Decimal(str(item.bound_cny)) for item in self.items)))

    @property
    def estimated_success_cny(self) -> float:
        return float(
            _money(
                sum(
                    (Decimal(str(item.estimated_success_total_cny)) for item in self.items),
                    Decimal(0),
                )
            )
        )

    def requests_by_operation(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.operation] = counts.get(item.operation, 0) + item.requests
        return counts

    def center_needs_cny(self) -> dict[str, float]:
        needs = {center: Decimal(0) for center in COST_CENTERS}
        for item in self.items:
            needs[item.cost_center] += Decimal(str(item.worst_case_cny))
        return {center: float(_money(value)) for center, value in needs.items()}

    def center_estimates_cny(self) -> dict[str, float]:
        estimates = {center: Decimal(0) for center in COST_CENTERS}
        for item in self.items:
            estimates[item.cost_center] += Decimal(str(item.estimated_success_total_cny))
        return {center: float(_money(value)) for center, value in estimates.items()}

    def item(self, item_id: str) -> P2RequestItem:
        for item in self.items:
            if item.item_id == item_id:
                return item
        raise P2ContractError("item_unknown", "计划中没有该 item_id")

    # ------------------------------------------------------------ 序列化

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "mode": self.mode,
            "stage": self.stage,
            "created_utc": self.created_utc,
            "project_total_limit_cny": float(self.project_total_limit_cny),
            "stage_limit_cny": float(self.stage_limit_cny),
            "max_requests": int(self.max_requests),
            "cost_centers_cny": {
                center: float(self.cost_centers_cny[center]) for center in COST_CENTERS
            },
            "items": [item.as_dict() for item in self.items],
        }
        if self.scenario_binding is not None:
            payload['scenario_binding'] = dict(self.scenario_binding)
        return payload

    @property
    def plan_sha256(self) -> str:
        return payload_sha256(self.as_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "P2RunPlan":
        _optional_exact_keys(data, _PLAN_KEYS, frozenset({'scenario_binding'}), "plan")
        raw_items = data["items"]
        if not isinstance(raw_items, list):
            raise P2ContractError("items_required", "plan.items 必须是数组")
        centers = data["cost_centers_cny"]
        if not isinstance(centers, Mapping):
            raise P2ContractError("mapping_required", "plan.cost_centers_cny 必须是对象")
        return cls(
            schema_version=_plain_text(data["schema_version"], "schema_version"),
            plan_id=_text(data["plan_id"], "plan_id", maximum=96),
            plan_version=_text(data["plan_version"], "plan_version", maximum=32),
            mode=_text(data["mode"], "mode", maximum=32),
            stage=_text(data["stage"], "stage", maximum=32),
            created_utc=_instant_text(data["created_utc"], "created_utc"),
            project_total_limit_cny=_plain_float(
                data["project_total_limit_cny"], "project_total_limit_cny", minimum=1e-12
            ),
            stage_limit_cny=_plain_float(data["stage_limit_cny"], "stage_limit_cny", minimum=1e-12),
            max_requests=_plain_int(data["max_requests"], "max_requests", minimum=1),
            cost_centers_cny={
                str(center): _plain_float(value, f"cost_centers_cny.{center}", minimum=1e-12)
                for center, value in centers.items()
            },
            items=tuple(P2RequestItem.from_dict(item) for item in raw_items),
            scenario_binding=data.get('scenario_binding'),
        )


# ---------------------------------------------------------------- 账本快照


_SNAPSHOT_KEYS = (
    "schema_version",
    "ledger_path",
    "ledger_sha256",
    "historical_prefix_sha256",
    "budget_sha256",
    "total_limit_cny",
    "historical_accounted_cny",
    "accounted_cny",
    "reservation_count",
    "result_count",
    "stage_allocations_cny",
    "p2_stage_accounted_cny",
    "p2_center_accounted_cny",
    "source",
)


@dataclass(frozen=True)
class P2LedgerSnapshot:
    """共享账本 + 预算的**只读**事实快照（预检/授权的唯一资金输入）。

    source="fixed-paths" 表示由 p2_authorization.read_ledger_snapshot 从固定共享路径
    真实读出；"in-memory" 只用于 Mock/候选推演，不能当作真实准入。
    """

    schema_version: str
    ledger_path: str
    ledger_sha256: str
    historical_prefix_sha256: str
    budget_sha256: str
    total_limit_cny: float
    historical_accounted_cny: float
    accounted_cny: float
    reservation_count: int
    result_count: int
    stage_allocations_cny: Mapping[str, float]
    p2_stage_accounted_cny: float
    p2_center_accounted_cny: Mapping[str, float]
    source: str

    def __post_init__(self) -> None:
        if self.schema_version != P2_LEDGER_SNAPSHOT_SCHEMA_VERSION:
            raise P2ContractError(
                "schema_version_invalid",
                f"snapshot.schema_version 必须是 {P2_LEDGER_SNAPSHOT_SCHEMA_VERSION}",
            )
        _plain_text(self.ledger_path, "snapshot.ledger_path", maximum=1024)
        _sha256_hex(self.ledger_sha256, "snapshot.ledger_sha256")
        _sha256_hex(self.historical_prefix_sha256, "snapshot.historical_prefix_sha256")
        _sha256_hex(self.budget_sha256, "snapshot.budget_sha256")
        _positive_money(self.total_limit_cny, "snapshot.total_limit_cny")
        _non_negative_money(self.historical_accounted_cny, "snapshot.historical_accounted_cny")
        _non_negative_money(self.accounted_cny, "snapshot.accounted_cny")
        _non_negative_money(self.p2_stage_accounted_cny, "snapshot.p2_stage_accounted_cny")
        _plain_int(self.reservation_count, "snapshot.reservation_count", minimum=0)
        _plain_int(self.result_count, "snapshot.result_count", minimum=0)
        if self.source not in ("fixed-paths", "in-memory"):
            raise P2ContractError(
                "snapshot_source_invalid", "snapshot.source 只能是 fixed-paths/in-memory"
            )
        if not isinstance(self.stage_allocations_cny, Mapping):
            raise P2ContractError("mapping_required", "snapshot.stage_allocations_cny 必须是对象")
        for stage, amount in self.stage_allocations_cny.items():
            _plain_text(stage, "snapshot.stage_allocations_cny.key", maximum=64)
            _non_negative_money(amount, f"snapshot.stage_allocations_cny.{stage}")
        if not isinstance(self.p2_center_accounted_cny, Mapping):
            raise P2ContractError("mapping_required", "snapshot.p2_center_accounted_cny 必须是对象")
        unknown = sorted(set(self.p2_center_accounted_cny) - set(COST_CENTERS))
        if unknown:
            raise P2ContractError("cost_center_unregistered", "snapshot 含未注册成本中心")
        for center, amount in self.p2_center_accounted_cny.items():
            _non_negative_money(amount, f"snapshot.p2_center_accounted_cny.{center}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ledger_path": self.ledger_path,
            "ledger_sha256": self.ledger_sha256,
            "historical_prefix_sha256": self.historical_prefix_sha256,
            "budget_sha256": self.budget_sha256,
            "total_limit_cny": float(self.total_limit_cny),
            "historical_accounted_cny": float(self.historical_accounted_cny),
            "accounted_cny": float(self.accounted_cny),
            "reservation_count": int(self.reservation_count),
            "result_count": int(self.result_count),
            "stage_allocations_cny": {
                str(stage): float(amount) for stage, amount in self.stage_allocations_cny.items()
            },
            "p2_stage_accounted_cny": float(self.p2_stage_accounted_cny),
            "p2_center_accounted_cny": {
                str(center): float(amount)
                for center, amount in self.p2_center_accounted_cny.items()
            },
            "source": self.source,
        }

    @property
    def production_ready(self) -> bool:
        return self.source == "fixed-paths"

    @classmethod
    def from_dict(cls, data: Any) -> "P2LedgerSnapshot":
        _exact_keys(data, _SNAPSHOT_KEYS, "ledger_snapshot")
        stages = data["stage_allocations_cny"]
        centers = data["p2_center_accounted_cny"]
        for label, value in (
            ("stage_allocations_cny", stages),
            ("p2_center_accounted_cny", centers),
        ):
            if not isinstance(value, Mapping):
                raise P2ContractError("mapping_required", f"ledger_snapshot.{label} 必须是对象")
        return cls(
            schema_version=_plain_text(data["schema_version"], "schema_version"),
            ledger_path=_plain_text(data["ledger_path"], "ledger_path", maximum=1024),
            ledger_sha256=_sha256_hex(data["ledger_sha256"], "ledger_sha256"),
            historical_prefix_sha256=_sha256_hex(
                data["historical_prefix_sha256"], "historical_prefix_sha256"
            ),
            budget_sha256=_sha256_hex(data["budget_sha256"], "budget_sha256"),
            total_limit_cny=_plain_float(data["total_limit_cny"], "total_limit_cny", minimum=1e-12),
            historical_accounted_cny=_plain_float(
                data["historical_accounted_cny"], "historical_accounted_cny"
            ),
            accounted_cny=_plain_float(data["accounted_cny"], "accounted_cny"),
            reservation_count=_plain_int(data["reservation_count"], "reservation_count", minimum=0),
            result_count=_plain_int(data["result_count"], "result_count", minimum=0),
            stage_allocations_cny={
                str(stage): _plain_float(amount, f"stage_allocations_cny.{stage}")
                for stage, amount in stages.items()
            },
            p2_stage_accounted_cny=_plain_float(
                data["p2_stage_accounted_cny"], "p2_stage_accounted_cny"
            ),
            p2_center_accounted_cny={
                str(center): _plain_float(amount, f"p2_center_accounted_cny.{center}")
                for center, amount in centers.items()
            },
            source=_plain_text(data["source"], "source"),
        )


# ---------------------------------------------------------------- 预检结果


@dataclass(frozen=True)
class P2PreflightResult:
    """预检结论：ok=False 时 reasons 是稳定原因码（不含外部原文）。

    worst_case_cny 是准入用上界，reserve_peak_cny 是串行单次峰值预留，
    estimated_success_cny 是成功结算估价：三者分列，不互相冒充。
    """

    schema_version: str
    ok: bool
    reasons: tuple[str, ...]
    plan_id: str
    plan_sha256: str
    stage: str
    stage_limit_cny: float
    stage_remaining_cny: float
    total_limit_cny: float
    total_remaining_cny: float
    max_requests: int
    requests_used: int
    requests_remaining: int
    requests_planned: int
    worst_case_cny: float
    reserve_peak_cny: float
    estimated_success_cny: float
    by_operation: Mapping[str, int]
    center_limits_cny: Mapping[str, float]
    center_needs_cny: Mapping[str, float]
    center_remaining_cny: Mapping[str, float]
    production_ready: bool

    def __post_init__(self) -> None:
        if self.schema_version != P2_PREFLIGHT_SCHEMA_VERSION:
            raise P2ContractError("schema_version_invalid", "preflight.schema_version 非法")
        if not isinstance(self.ok, bool):
            raise P2ContractError("bool_invalid", "preflight.ok 必须是布尔")
        if self.ok and self.reasons:
            raise P2ContractError("preflight_inconsistent", "ok=True 不能带拒绝原因")
        if not self.ok and not self.reasons:
            raise P2ContractError("preflight_inconsistent", "ok=False 必须给出稳定原因码")
        for name in (
            "stage_limit_cny",
            "total_limit_cny",
            "worst_case_cny",
            "reserve_peak_cny",
        ):
            _positive_money(getattr(self, name), f"preflight.{name}")
        for name in ("stage_remaining_cny", "total_remaining_cny", "estimated_success_cny"):
            _non_negative_money(getattr(self, name), f"preflight.{name}")
        for name in ("max_requests", "requests_planned"):
            _plain_int(getattr(self, name), f"preflight.{name}", minimum=1)
        for name in ("requests_used", "requests_remaining"):
            _plain_int(getattr(self, name), f"preflight.{name}", minimum=0)
        if not isinstance(self.production_ready, bool):
            raise P2ContractError("bool_invalid", "preflight.production_ready 必须是布尔")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": bool(self.ok),
            "reasons": list(self.reasons),
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "stage": self.stage,
            "stage_limit_cny": float(self.stage_limit_cny),
            "stage_remaining_cny": float(self.stage_remaining_cny),
            "total_limit_cny": float(self.total_limit_cny),
            "total_remaining_cny": float(self.total_remaining_cny),
            "max_requests": int(self.max_requests),
            "requests_used": int(self.requests_used),
            "requests_remaining": int(self.requests_remaining),
            "requests_planned": int(self.requests_planned),
            "worst_case_cny": float(self.worst_case_cny),
            "reserve_peak_cny": float(self.reserve_peak_cny),
            "estimated_success_cny": float(self.estimated_success_cny),
            "by_operation": dict(self.by_operation),
            "center_limits_cny": dict(self.center_limits_cny),
            "center_needs_cny": dict(self.center_needs_cny),
            "center_remaining_cny": dict(self.center_remaining_cny),
            "production_ready": bool(self.production_ready),
        }


# ---------------------------------------------------------------- 授权


_AUTH_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "plan_id",
        "plan_sha256",
        "go_document",
        "go_sha256",
        "go_nonce_len",
        "issued_by",
        "issued_utc",
        "expires_utc",
        "ledger_path",
        "ledger_sha256",
        "budget_sha256",
        "stage_limit_cny",
        "stage_remaining_cny",
        "cost_center_limits_cny",
        "center_remaining_cny",
        "max_requests",
        "requests_used",
        "requests_remaining",
        "max_request_cny",
        "operations",
        "production_ready",
    }
)


@dataclass(frozen=True)
class P2Authorization:
    """一次 P2 运行的有效授权（GO ∩ 计划 ∩ 预算 ∩ 当前账本事实）。"""

    schema_version: str
    stage: str
    plan_id: str
    plan_sha256: str
    go_document: str
    go_sha256: str
    go_nonce_len: int
    issued_by: str
    issued_utc: datetime
    expires_utc: datetime
    ledger_path: str
    ledger_sha256: str
    budget_sha256: str
    stage_limit_cny: float
    stage_remaining_cny: float
    cost_center_limits_cny: Mapping[str, float]
    center_remaining_cny: Mapping[str, float]
    max_requests: int
    requests_used: int
    requests_remaining: int
    max_request_cny: float
    operations: tuple[str, ...]
    production_ready: bool

    def __post_init__(self) -> None:
        if self.schema_version != P2_AUTHORIZATION_SCHEMA_VERSION:
            raise P2ContractError("schema_version_invalid", "authorization.schema_version 非法")
        if self.stage != P2_STAGE:
            raise P2ContractError("stage_invalid", f"authorization.stage 必须是 {P2_STAGE}")
        _text(self.plan_id, "plan_id", maximum=96)
        _sha256_hex(self.plan_sha256, "plan_sha256")
        _plain_text(self.go_document, "go_document")
        _sha256_hex(self.go_sha256, "go_sha256")
        _plain_int(self.go_nonce_len, "go_nonce_len", minimum=16)
        _plain_text(self.issued_by, "issued_by")
        if self.expires_utc <= self.issued_utc:
            raise P2ContractError("instant_invalid", "expires_utc 必须晚于 issued_utc")
        _plain_text(self.ledger_path, "ledger_path", maximum=1024)
        _sha256_hex(self.ledger_sha256, "ledger_sha256")
        _sha256_hex(self.budget_sha256, "budget_sha256")
        _positive_money(self.stage_limit_cny, "authorization.stage_limit_cny")
        _non_negative_money(self.stage_remaining_cny, "authorization.stage_remaining_cny")
        _positive_money(self.max_request_cny, "authorization.max_request_cny")
        _plain_int(self.max_requests, "authorization.max_requests", minimum=1)
        _plain_int(self.requests_used, "authorization.requests_used", minimum=0)
        _plain_int(self.requests_remaining, "authorization.requests_remaining", minimum=0)
        if not self.operations:
            raise P2ContractError("operation_unregistered", "authorization.operations 不得为空")
        for operation in self.operations:
            if operation not in OPERATIONS:
                raise P2ContractError(
                    "operation_unregistered", "authorization.operations 含未注册操作"
                )
        if set(self.cost_center_limits_cny) != set(COST_CENTERS):
            raise P2ContractError("cost_center_set_invalid", "authorization 必须带四个成本中心额度")
        for center in COST_CENTERS:
            _positive_money(self.cost_center_limits_cny[center], f"authorization.center.{center}")
            _non_negative_money(
                self.center_remaining_cny.get(center, 0.0), f"authorization.center_remaining.{center}"
            )
        if not isinstance(self.production_ready, bool):
            raise P2ContractError("bool_invalid", "authorization.production_ready 必须是布尔")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "go_document": self.go_document,
            "go_sha256": self.go_sha256,
            "go_nonce_len": int(self.go_nonce_len),
            "issued_by": self.issued_by,
            "issued_utc": self.issued_utc.isoformat(),
            "expires_utc": self.expires_utc.isoformat(),
            "ledger_path": self.ledger_path,
            "ledger_sha256": self.ledger_sha256,
            "budget_sha256": self.budget_sha256,
            "stage_limit_cny": float(self.stage_limit_cny),
            "stage_remaining_cny": float(self.stage_remaining_cny),
            "cost_center_limits_cny": {
                center: float(self.cost_center_limits_cny[center]) for center in COST_CENTERS
            },
            "center_remaining_cny": {
                center: float(self.center_remaining_cny.get(center, 0.0))
                for center in COST_CENTERS
            },
            "max_requests": int(self.max_requests),
            "requests_used": int(self.requests_used),
            "requests_remaining": int(self.requests_remaining),
            "max_request_cny": float(self.max_request_cny),
            "operations": list(self.operations),
            "production_ready": bool(self.production_ready),
        }

    def expires_at(self) -> datetime:
        return self.expires_utc


# ---------------------------------------------------------------- 运行结果


#: p2-run-result/v0.1 的必填键（answer 单侧口径；**语义不变**）。
_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "plan_id",
        "plan_sha256",
        "status",
        "stop_code",
        "requests_planned",
        "requests_reserved",
        "requests_sent",
        "reserved_cny",
        "settled_cny",
        "by_operation",
        "by_center_cny",
        "production_ready",
    }
)

#: T207-FIX-B/A 的 additive 键：全量尝试口径，旧产物没有它们也能读（缺省=unavailable）。
_RESULT_ATTEMPT_KEYS = frozenset(
    {
        "attempts_scope",
        "attempts_reserved",
        "attempts_by_operation",
        "attempts_by_center_cny",
    }
)


@dataclass(frozen=True)
class P2RunResult:
    """一次 P2 运行的资金/请求回执（T203 统一填写，T209 归档）。

    两组口径**互不冒充**（T207-FIX-B/A，additive，不改旧键语义）：

    - ``requests_*`` / ``by_operation`` / ``by_center_cny``：**answer 轮单侧**（runner 逐轮
      的 answer 预留与结算；旧键语义逐字不变）；
    - ``attempts_*``：**全量底层尝试**（answer 轮 + 从属尝试），由 runner 的逐次尝试核对
      （``attempt_audit``）填；等价于门控登记的唯一 reservation 数，也是「同一 run 的规模」
      唯一可与 ``gate.json.attempts`` 对齐的口径。

    ``attempts_scope == "unavailable"`` 表示本结果没有全量尝试账（例如 ``P2Gate.result()``
    只知道自己那一侧，或发送前就停），此时 attempts_* 必须为空/0，**不得**用 answer 口径
    冒充全量。
    """

    schema_version: str
    run_id: str
    plan_id: str
    plan_sha256: str
    status: str
    stop_code: str | None
    requests_planned: int
    requests_reserved: int
    requests_sent: int
    reserved_cny: float
    settled_cny: float
    by_operation: Mapping[str, int]
    by_center_cny: Mapping[str, float]
    production_ready: bool
    attempts_scope: str = ATTEMPTS_SCOPE_UNAVAILABLE
    attempts_reserved: int = 0
    attempts_by_operation: Mapping[str, int] = field(default_factory=dict)
    attempts_by_center_cny: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != P2_RUN_RESULT_SCHEMA_VERSION:
            raise P2ContractError("schema_version_invalid", "result.schema_version 非法")
        _text(self.run_id, "run_id", maximum=96)
        _text(self.plan_id, "plan_id", maximum=96)
        _sha256_hex(self.plan_sha256, "plan_sha256")
        if self.status not in P2_RUN_STATUSES:
            raise P2ContractError("status_invalid", f"result.status 必须是 {sorted(P2_RUN_STATUSES)}")
        if self.status == "succeeded":
            if self.stop_code is not None:
                raise P2ContractError("result_inconsistent", "succeeded 不得带 stop_code")
        elif not self.stop_code:
            raise P2ContractError("result_inconsistent", "blocked/aborted 必须带稳定 stop_code")
        _plain_int(self.requests_planned, "requests_planned", minimum=0)
        _plain_int(self.requests_reserved, "requests_reserved", minimum=0)
        _plain_int(self.requests_sent, "requests_sent", minimum=0)
        if self.requests_sent > self.requests_reserved or self.requests_reserved > self.requests_planned:
            raise P2ContractError("result_inconsistent", "必须满足 sent <= reserved <= planned")
        _non_negative_money(self.reserved_cny, "reserved_cny")
        _non_negative_money(self.settled_cny, "settled_cny")
        if not isinstance(self.by_operation, Mapping):
            raise P2ContractError("mapping_required", "result.by_operation 必须是对象")
        for operation, count in self.by_operation.items():
            if operation not in OPERATIONS:
                raise P2ContractError("operation_unregistered", "result.by_operation 含未注册操作")
            _plain_int(count, f"by_operation.{operation}", minimum=0)
        if not isinstance(self.by_center_cny, Mapping):
            raise P2ContractError("mapping_required", "result.by_center_cny 必须是对象")
        for center, amount in self.by_center_cny.items():
            if center not in COST_CENTERS:
                raise P2ContractError("cost_center_unregistered", "result.by_center_cny 含未注册中心")
            _non_negative_money(amount, f"by_center_cny.{center}")
        if not isinstance(self.production_ready, bool):
            raise P2ContractError("bool_invalid", "result.production_ready 必须是布尔")
        self._validate_attempts()

    def _validate_attempts(self) -> None:
        if self.attempts_scope not in ATTEMPTS_SCOPES:
            raise P2ContractError("attempts_scope_invalid", f"attempts_scope 必须是 {sorted(ATTEMPTS_SCOPES)}")
        _plain_int(self.attempts_reserved, "attempts_reserved", minimum=0)
        if not isinstance(self.attempts_by_operation, Mapping):
            raise P2ContractError("mapping_required", "result.attempts_by_operation 必须是对象")
        for operation, count in self.attempts_by_operation.items():
            if operation not in OPERATIONS:
                raise P2ContractError(
                    "operation_unregistered", "result.attempts_by_operation 含未注册操作"
                )
            _plain_int(count, f"attempts_by_operation.{operation}", minimum=0)
        if not isinstance(self.attempts_by_center_cny, Mapping):
            raise P2ContractError("mapping_required", "result.attempts_by_center_cny 必须是对象")
        for center, amount in self.attempts_by_center_cny.items():
            if center not in COST_CENTERS:
                raise P2ContractError(
                    "cost_center_unregistered", "result.attempts_by_center_cny 含未注册中心"
                )
            _non_negative_money(amount, f"attempts_by_center_cny.{center}")
        if self.attempts_scope == ATTEMPTS_SCOPE_UNAVAILABLE and (
            int(self.attempts_reserved)
            or dict(self.attempts_by_operation)
            or dict(self.attempts_by_center_cny)
        ):
            raise P2ContractError(
                "result_inconsistent", "attempts_scope=unavailable 时 attempts_* 必须为空/0"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "status": self.status,
            "stop_code": self.stop_code,
            "requests_planned": int(self.requests_planned),
            "requests_reserved": int(self.requests_reserved),
            "requests_sent": int(self.requests_sent),
            "reserved_cny": float(self.reserved_cny),
            "settled_cny": float(self.settled_cny),
            "by_operation": {str(key): int(value) for key, value in self.by_operation.items()},
            "by_center_cny": {
                str(key): float(value) for key, value in self.by_center_cny.items()
            },
            "production_ready": bool(self.production_ready),
            "attempts_scope": str(self.attempts_scope),
            "attempts_reserved": int(self.attempts_reserved),
            "attempts_by_operation": {
                str(key): int(value) for key, value in self.attempts_by_operation.items()
            },
            "attempts_by_center_cny": {
                str(key): float(value) for key, value in self.attempts_by_center_cny.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Any) -> "P2RunResult":
        # 旧产物（没有 attempts_* 键）仍然可读：缺省 = unavailable + 0/空。
        _optional_exact_keys(data, _RESULT_KEYS, _RESULT_ATTEMPT_KEYS, "run_result")
        stop_code = data["stop_code"]
        if stop_code is not None:
            stop_code = _text(stop_code, "stop_code", maximum=96)
        by_operation = data["by_operation"]
        by_center = data["by_center_cny"]
        attempts_by_operation = data.get("attempts_by_operation", {})
        attempts_by_center = data.get("attempts_by_center_cny", {})
        attempts_scope = data.get("attempts_scope", ATTEMPTS_SCOPE_UNAVAILABLE)
        for label, value in (
            ("by_operation", by_operation),
            ("by_center_cny", by_center),
            ("attempts_by_operation", attempts_by_operation),
            ("attempts_by_center_cny", attempts_by_center),
        ):
            if not isinstance(value, Mapping):
                raise P2ContractError("mapping_required", f"run_result.{label} 必须是对象")
        return cls(
            schema_version=_plain_text(data["schema_version"], "schema_version"),
            run_id=_text(data["run_id"], "run_id", maximum=96),
            plan_id=_text(data["plan_id"], "plan_id", maximum=96),
            plan_sha256=_sha256_hex(data["plan_sha256"], "plan_sha256"),
            status=_text(data["status"], "status", maximum=32),
            stop_code=stop_code,
            requests_planned=_plain_int(data["requests_planned"], "requests_planned", minimum=0),
            requests_reserved=_plain_int(data["requests_reserved"], "requests_reserved", minimum=0),
            requests_sent=_plain_int(data["requests_sent"], "requests_sent", minimum=0),
            reserved_cny=_plain_float(data["reserved_cny"], "reserved_cny"),
            settled_cny=_plain_float(data["settled_cny"], "settled_cny"),
            by_operation={
                str(key): _plain_int(value, f"by_operation.{key}", minimum=0)
                for key, value in by_operation.items()
            },
            by_center_cny={
                str(key): _plain_float(value, f"by_center_cny.{key}")
                for key, value in by_center.items()
            },
            production_ready=bool(data["production_ready"]),
            attempts_scope=_plain_text(attempts_scope, "attempts_scope", maximum=32),
            attempts_reserved=_plain_int(
                data.get("attempts_reserved", 0), "attempts_reserved", minimum=0
            ),
            attempts_by_operation={
                str(key): _plain_int(value, f"attempts_by_operation.{key}", minimum=0)
                for key, value in attempts_by_operation.items()
            },
            attempts_by_center_cny={
                str(key): _plain_float(value, f"attempts_by_center_cny.{key}")
                for key, value in attempts_by_center.items()
            },
        )
