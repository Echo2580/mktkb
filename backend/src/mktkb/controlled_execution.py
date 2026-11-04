"""S2-J2 正式受控执行入口（Mock-only 自测；未来真实矩阵经此入口装配与运行）。

把 J1 已接收的版本化结算核心接到实际供应商适配层，并证明“GO ↔ 执行器 ↔ 运行期”的
请求计划绑定：请求数、caps、来源（provider/model/host/region/pricing_source）、串行、
OCR 价格/总次数/tile/attempt 上界、request plan 哈希。任一项无法证明则在**任何预留/发送
之前**抛 ``ControlledBindingError``（只报字段名/期望值，不回显 GO 原文）。

结构：
- :class:`ControlledRequestPlan`：经理批准的条件预算方案（Mock 值即计划值，不是实测 usage）；
- :class:`ControlledExecution`：用生产 ``resolve_live_gate`` / ``resolve_rag_config`` 构造
  共享账本与 GO 闸门，再构造**版本化** chat 网关、embedding/rerank provider、OCR 预算包装；
  ``run_chat / run_embedding / run_rerank / run_ocr`` 是受控调用边界（计数、串行、停机）；
- 本模块不读 .env、不签 GO、不发真实网络；``transport`` 仅 Mock/隔离测试注入。

边界：``provider_billed_cny`` 仍恒为 null；caps 是成功准入条件，不是真实 usage/账单；
本入口不证明真实矩阵能在 10 元内完成，也不承诺任何故障下都完成。
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .live_authorization import (
    LiveGate,
    LiveGateError,
    load_live_authorization,
    product_stage,
    project_total_limit_cny,
    resolve_live_gate,
)
from .official_chat_profile import (
    OFFICIAL_CONTEXT_CEILING_TOKENS,
    OFFICIAL_INPUT_PRICE_PER_MILLION_CNY,
    OFFICIAL_MAX_OUTPUT_TOKENS,
    OFFICIAL_OUTPUT_PRICE_PER_MILLION_CNY,
)
from .providers import build_gateway, build_ocr_gateway
from .providers.budgeted import BudgetedModelGateway, ChatPricing
from .providers.ocr_budgeted import (
    OCR_TABLE_PRICE_CNY,
    OCR_TEXT_PRICE_CNY,
    BudgetedOCRGateway,
    OCRBudgetRefused,
)
from .providers.types import OCRInput, OCRMode, OCRPageResult, CompletionInput, CompletionOutput
from .rag.config import positive_float_env, positive_int_env
from .rag.controlled_usage import safe_dimensions, safe_error_code, safe_request_id
from .rag.providers import post_counters
from .rag.settlement_policy import (
    CHAT_COMPLETION_TOKENS_CAP,
    CHAT_INPUT_PRICE_FLOOR,
    CHAT_OUTPUT_PRICE_FLOOR,
    CHAT_PROMPT_TOKENS_CAP,
    EMBEDDING_TOTAL_TOKENS_CAP,
    EMBEDDING_UNIT_PRICE_FLOOR,
    RERANK_TOTAL_TOKENS_CAP,
    RERANK_UNIT_PRICE_FLOOR,
    SETTLEMENT_VERSION,
    SettlementPolicy,
    build_policy,
    canonical_decimal,
)

__all__ = [
    "CONTROLLED_PLAN_VERSION",
    "ControlledBindingError",
    "ControlledExecution",
    "ControlledExecutionError",
    "ControlledRefused",
    "ControlledRequestPlan",
]

CONTROLLED_PLAN_VERSION = "s2j2-controlled-plan-v1"
_MILLION = Decimal(1_000_000)
_AMOUNT = Decimal("0.00000001")

# 计划来源（与 J1 v1 settlement_policy 的已知来源集合一致；不是新供应商）。
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
OCR_MAX_CALLS = 13
OCR_MAX_TILES_PER_PAGE = 1
OCR_MAX_ATTEMPTS = 1
PLAN_HISTORY_CNY = Decimal("0.03")
# 历史默认 10 元；实际生效值由 live_authorization.project_total_limit_cny() 决定
# （主人显式追加预算时用 MKTKB_PROJECT_TOTAL_LIMIT_CNY 提高，仍是硬上限）。
PROJECT_TOTAL_LIMIT_CNY = Decimal("10")


class ControlledExecutionError(ValueError):
    """受控执行入口的稳定错误基类（消息不承诺包含外部原文）。"""

    code = "CONTROLLED_EXECUTION_ERROR"


class ControlledBindingError(ControlledExecutionError):
    """GO/plan/运行期绑定无法证明：在首个预留/发送之前拒绝。"""

    code = "CONTROLLED_BINDING_INVALID"


class ControlledRefused(ControlledExecutionError):
    """受控执行边界拒绝（已停机/超计划计数/串行计划并发），未预留未发送。"""

    code = "CONTROLLED_REFUSED"


def _money(value: Decimal) -> Decimal:
    return value.quantize(_AMOUNT)


def _plain_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} 必须是正整数")
    return int(value)


@dataclass(frozen=True)
class ControlledRequestPlan:
    """条件预算请求计划（值来自 S2-I 修正计划/经理决定；不是实测 usage）。"""

    plan_version: str = CONTROLLED_PLAN_VERSION
    stage: str = "S2-DEV"
    chat_requests: int = 136
    embedding_requests: int = 111
    rerank_requests: int = 94
    ocr_text_requests: int = 12
    ocr_table_requests: int = 1
    serial: bool = True
    ocr_max_tiles_per_page: int = OCR_MAX_TILES_PER_PAGE
    ocr_max_attempts: int = OCR_MAX_ATTEMPTS
    chat_prompt_tokens_cap: int = CHAT_PROMPT_TOKENS_CAP
    chat_completion_tokens_cap: int = CHAT_COMPLETION_TOKENS_CAP
    embedding_total_tokens_cap: int = EMBEDDING_TOTAL_TOKENS_CAP
    rerank_total_tokens_cap: int = RERANK_TOTAL_TOKENS_CAP

    def __post_init__(self) -> None:
        for name in (
            "chat_requests",
            "embedding_requests",
            "rerank_requests",
            "ocr_text_requests",
            "ocr_table_requests",
        ):
            _plain_int(getattr(self, name), name)
        if self.serial is not True:
            raise ValueError("本路线只允许 serial=True（并发会改变资金峰值，不能外推）")
        if self.ocr_max_tiles_per_page != OCR_MAX_TILES_PER_PAGE:
            raise ValueError("本路线每页 tile 上限必须固化 1")
        if self.ocr_max_attempts != OCR_MAX_ATTEMPTS:
            raise ValueError("本路线 OCR attempts 必须固化 1")
        if (
            self.chat_prompt_tokens_cap != CHAT_PROMPT_TOKENS_CAP
            or self.chat_completion_tokens_cap != CHAT_COMPLETION_TOKENS_CAP
            or self.embedding_total_tokens_cap != EMBEDDING_TOTAL_TOKENS_CAP
            or self.rerank_total_tokens_cap != RERANK_TOTAL_TOKENS_CAP
        ):
            raise ValueError("请求计划 caps 必须精确等于 J1 v1 固化值")

    # ---------------------------------------------------------------- 派生金额

    @property
    def ocr_total_requests(self) -> int:
        return int(self.ocr_text_requests + self.ocr_table_requests)

    @property
    def total_calls(self) -> int:
        return (
            int(self.chat_requests)
            + int(self.embedding_requests)
            + int(self.rerank_requests)
            + self.ocr_total_requests
        )

    @property
    def chat_cap_charge_cny(self) -> Decimal:
        return _money(
            (
                Decimal(self.chat_prompt_tokens_cap) * CHAT_INPUT_PRICE_FLOOR
                + Decimal(self.chat_completion_tokens_cap) * CHAT_OUTPUT_PRICE_FLOOR
            )
            / _MILLION
        )

    @property
    def embedding_cap_charge_cny(self) -> Decimal:
        return _money(
            Decimal(self.embedding_total_tokens_cap) * EMBEDDING_UNIT_PRICE_FLOOR / _MILLION
        )

    @property
    def rerank_cap_charge_cny(self) -> Decimal:
        return _money(Decimal(self.rerank_total_tokens_cap) * RERANK_UNIT_PRICE_FLOOR / _MILLION)

    @property
    def ocr_charge_cny(self) -> Decimal:
        return _money(
            Decimal(self.ocr_text_requests) * OCR_TEXT_PRICE_CNY
            + Decimal(self.ocr_table_requests) * OCR_TABLE_PRICE_CNY
        )

    @property
    def conservative_settlement_cny(self) -> Decimal:
        return _money(
            Decimal(self.chat_requests) * self.chat_cap_charge_cny
            + Decimal(self.embedding_requests) * self.embedding_cap_charge_cny
            + Decimal(self.rerank_requests) * self.rerank_cap_charge_cny
            + self.ocr_charge_cny
        )

    @property
    def chat_reserve_cny(self) -> Decimal:
        """单次 chat 仍按官方 context ceiling 全额输入 + 固定 800 输出预留。"""
        return _money(
            (
                Decimal(OFFICIAL_CONTEXT_CEILING_TOKENS) * Decimal(str(OFFICIAL_INPUT_PRICE_PER_MILLION_CNY))
                + Decimal(OFFICIAL_MAX_OUTPUT_TOKENS) * Decimal(str(OFFICIAL_OUTPUT_PRICE_PER_MILLION_CNY))
            )
            / _MILLION
        )

    @property
    def max_single_reserve_cny(self) -> Decimal:
        """串行单次最大预留：chat 全额预留最大；E/R/OCR 均更小。"""
        return self.chat_reserve_cny

    @property
    def peak_include_history_cny(self) -> Decimal:
        return _money(
            self.conservative_settlement_cny
            + PLAN_HISTORY_CNY
            - self.chat_cap_charge_cny
            + self.chat_reserve_cny
        )

    # ---------------------------------------------------------------- 绑定序列化

    def _sources(self) -> dict[str, Any]:
        return {
            "chat_provider": CHAT_PROVIDER,
            "chat_model": CHAT_MODEL,
            "chat_host": CHAT_HOST,
            "chat_region": CHAT_REGION,
            "chat_pricing_source": CHAT_PRICING_SOURCE,
            "embedding_provider": EMBEDDING_PROVIDER,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_host": BAILIAN_HOST,
            "embedding_region": BAILIAN_REGION,
            "embedding_pricing_source": EMBEDDING_PRICING_SOURCE,
            "rerank_provider": RERANK_PROVIDER,
            "rerank_model": RERANK_MODEL,
            "rerank_host": BAILIAN_HOST,
            "rerank_region": BAILIAN_REGION,
            "rerank_pricing_source": RERANK_PRICING_SOURCE,
            "ocr_provider": OCR_PROVIDER,
            "ocr_host": OCR_HOST,
            "ocr_region": OCR_REGION,
            "ocr_text_model": OCR_TEXT_MODEL,
            "ocr_table_model": OCR_TABLE_MODEL,
            "ocr_pricing_source": OCR_PRICING_SOURCE,
        }

    def plan_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "stage": self.stage,
            "settlement_version": SETTLEMENT_VERSION,
            "serial": bool(self.serial),
            "chat_requests": self.chat_requests,
            "embedding_requests": self.embedding_requests,
            "rerank_requests": self.rerank_requests,
            "ocr_text_requests": self.ocr_text_requests,
            "ocr_table_requests": self.ocr_table_requests,
            "ocr_max_calls": self.ocr_total_requests,
            "ocr_max_tiles_per_page": self.ocr_max_tiles_per_page,
            "ocr_max_attempts": self.ocr_max_attempts,
            "chat_prompt_tokens_cap": self.chat_prompt_tokens_cap,
            "chat_completion_tokens_cap": self.chat_completion_tokens_cap,
            "embedding_total_tokens_cap": self.embedding_total_tokens_cap,
            "rerank_total_tokens_cap": self.rerank_total_tokens_cap,
            "ocr_text_price_cny": canonical_decimal(OCR_TEXT_PRICE_CNY),
            "ocr_table_price_cny": canonical_decimal(OCR_TABLE_PRICE_CNY),
            "conservative_settlement_cny": canonical_decimal(self.conservative_settlement_cny),
            "history_cny": canonical_decimal(PLAN_HISTORY_CNY),
            "peak_include_history_cny": canonical_decimal(self.peak_include_history_cny),
            "chat_reserve_cny": canonical_decimal(self.chat_reserve_cny),
            "sources": self._sources(),
        }

    @property
    def request_plan_sha256(self) -> str:
        encoded = json.dumps(
            self.plan_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------- 绑定核对


def _binding(authorization: Any, service: str) -> dict[str, Any]:
    bindings = getattr(authorization, "bindings", None)
    if not isinstance(bindings, Mapping):
        raise ControlledBindingError(f"GO 未声明 scope.bindings.{service}（无法证明请求计划绑定）")
    value = bindings.get(service)
    if not isinstance(value, Mapping) or not value:
        raise ControlledBindingError(f"GO scope.bindings 缺少服务 {service} 的绑定")
    return dict(value)


def _canonical_type_name(value: Any) -> str:
    """计划规范类型名（bool 必须与 int 区分；价格字段规范为 float）。"""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    raise ControlledBindingError("执行器计划绑定含不支持的规范类型（内部错误）")


def _strict_type_matches(declared: Any, wanted: Any) -> bool:
    """F-2：GO 绑定值必须与计划规范声明类型完全一致，禁止 int/float/bool/str 互冒。

    不能用 Python ``==`` 的数值相等替代类型证明（``1536.0 == 1536`` 成立但类型不同）。
    """
    if isinstance(wanted, bool):
        return isinstance(declared, bool)
    if isinstance(wanted, int):
        return isinstance(declared, int) and not isinstance(declared, bool)
    if isinstance(wanted, float):
        return isinstance(declared, float)
    if isinstance(wanted, str):
        return isinstance(declared, str)
    raise ControlledBindingError("执行器计划绑定含不支持的规范类型（内部错误）")


def _verify_fields(authorization: Any, service: str, expected: Mapping[str, Any]) -> dict[str, Any]:
    binding = _binding(authorization, service)
    for name, wanted in expected.items():
        if name not in binding:
            raise ControlledBindingError(f"GO 缺少绑定字段 {service}.{name}（期望 {wanted!r}）")
        declared = binding[name]
        if not _strict_type_matches(declared, wanted):
            # 只回显执行器期望的规范类型/值（本仓常量），绝不回显 GO 原文/外部秘密。
            raise ControlledBindingError(
                f"GO 绑定 {service}.{name} 类型必须是 {_canonical_type_name(wanted)}（期望 {wanted!r}）"
            )
        if declared != wanted:
            # 只回显执行器期望值（本仓常量），不回显 GO 原文。
            raise ControlledBindingError(f"GO 绑定 {service}.{name} 与执行器计划不一致（期望 {wanted!r}）")
    return binding


def _plan_bindings(plan: ControlledRequestPlan) -> dict[str, dict[str, Any]]:
    sources = plan._sources()
    rag_expected: dict[str, Any] = {
        "plan_version": plan.plan_version,
        "settlement_version": SETTLEMENT_VERSION,
        "request_plan_sha256": plan.request_plan_sha256,
        "serial": True,
        "embedding_requests": plan.embedding_requests,
        "rerank_requests": plan.rerank_requests,
        "ocr_text_requests": plan.ocr_text_requests,
        "ocr_table_requests": plan.ocr_table_requests,
        "ocr_max_calls": plan.ocr_total_requests,
        "ocr_max_tiles_per_page": plan.ocr_max_tiles_per_page,
        "ocr_max_attempts": plan.ocr_max_attempts,
        "embedding_total_tokens_cap": plan.embedding_total_tokens_cap,
        "rerank_total_tokens_cap": plan.rerank_total_tokens_cap,
        "ocr_text_price_cny": float(OCR_TEXT_PRICE_CNY),
        "ocr_table_price_cny": float(OCR_TABLE_PRICE_CNY),
        "ocr_provider": OCR_PROVIDER,
        "ocr_host": OCR_HOST,
        "ocr_region": OCR_REGION,
        "ocr_text_model": OCR_TEXT_MODEL,
        "ocr_table_model": OCR_TABLE_MODEL,
        "ocr_pricing_source": OCR_PRICING_SOURCE,
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_host": BAILIAN_HOST,
        "embedding_region": BAILIAN_REGION,
        "rerank_provider": RERANK_PROVIDER,
        "rerank_model": RERANK_MODEL,
        "rerank_host": BAILIAN_HOST,
        "rerank_region": BAILIAN_REGION,
    }
    # 既有 rag 产品入口（resolve_rag_config）的 provider 绑定字段；正式 GO 必须同时能过这层与
    # J2 的 plan 绑定，不允许“plan 通过但产品入口实际未绑定同一来源”。
    rag_expected.update(
        {
            "base_url_host": BAILIAN_HOST,
            "embedding_dimensions": 1024,
            "region": "beijing",
        }
    )
    chat_expected: dict[str, Any] = {
        "plan_version": plan.plan_version,
        "settlement_version": SETTLEMENT_VERSION,
        "request_plan_sha256": plan.request_plan_sha256,
        "serial": True,
        "chat_requests": plan.chat_requests,
        "chat_prompt_tokens_cap": plan.chat_prompt_tokens_cap,
        "chat_completion_tokens_cap": plan.chat_completion_tokens_cap,
        # 既有 build_gateway 的 chat provider 绑定字段（不能只依赖 plan 侧名字）。
        "base_url_host": CHAT_HOST,
        "model": CHAT_MODEL,
        "thinking": "disabled",
        "max_input_tokens": 6144,
        "max_output_tokens": OFFICIAL_MAX_OUTPUT_TOKENS,
        "reserve_profile": "model_context_ceiling",
        "context_ceiling_tokens": OFFICIAL_CONTEXT_CEILING_TOKENS,
        "input_price_per_million_cny": float(CHAT_INPUT_PRICE_FLOOR),
        "output_price_per_million_cny": float(CHAT_OUTPUT_PRICE_FLOOR),
    }
    for name in ("chat_provider", "chat_model", "chat_host", "chat_region", "chat_pricing_source"):
        # chat 供应商绑定里已有 model/host 等字段；这里只绑定 source 语义到独立名字，
        # 避免与既有 build_gateway 绑定字段（model/base_url_host）混用。
        chat_expected[name] = sources[name]
    return {"rag": rag_expected, "chat": chat_expected}


def _assert_gate_limits(
    plan: ControlledRequestPlan,
    *,
    chat_gate: LiveGate,
    rag_budget: Any,
    rag_config: Any,
    chat_reserve_cny: Decimal,
) -> None:
    if chat_gate.stage != plan.stage or getattr(rag_budget, "stage", None) != plan.stage:
        raise ControlledBindingError("执行器 plan.stage 与 GO/账本阶段不一致")
    if chat_gate.ledger_path.resolve() != Path(rag_budget.ledger_path).resolve():
        raise ControlledBindingError("chat/rag 闸门不是同一只共享账本")
    if chat_gate.budget_path.resolve() != Path(rag_budget.budget_json_path).resolve():
        raise ControlledBindingError("chat/rag 闸门不是同一份共享预算")
    expected_total_limit = Decimal(str(project_total_limit_cny()))
    if abs(Decimal(str(chat_gate.total_limit_cny)) - expected_total_limit) > Decimal("0.000000001"):
        raise ControlledBindingError(
            f"共享账本总上限必须等于当前项目上限 {canonical_decimal(expected_total_limit)} 元（拒绝放大预算）"
        )
    rag_max_requests = int(getattr(rag_budget, "max_requests", 0))
    if min(chat_gate.max_requests, rag_max_requests) < plan.total_calls:
        raise ControlledBindingError(
            f"GO 累计请求上限小于计划请求数 {plan.total_calls}（不允许外推容量）"
        )
    if float(chat_reserve_cny) > chat_gate.max_request_cny + 1e-12:
        raise ControlledBindingError("GO chat 单请求上界小于计划 chat 全额预留")
    ocr_bound = max(float(OCR_TEXT_PRICE_CNY), float(OCR_TABLE_PRICE_CNY))
    rag_max_request = float(getattr(rag_config, "max_request_cny", 0.0) or 0.0)
    if ocr_bound > rag_max_request + 1e-12:
        raise ControlledBindingError("GO rag 单请求上界小于 OCR 单次固定价")
    required_peak = float(plan.peak_include_history_cny)
    rag_stage_limit = float(getattr(rag_budget, "stage_limit_cny", 0.0) or 0.0)
    if min(chat_gate.stage_limit_cny, rag_stage_limit) + 1e-12 < required_peak:
        raise ControlledBindingError(
            "阶段额度小于计划串行峰值 "
            f"{canonical_decimal(plan.peak_include_history_cny)} 元（拒绝不可证明的预算）"
        )
    summary = chat_gate.ledger().summary()
    if abs(summary.historical_conservative_cny - float(PLAN_HISTORY_CNY)) > 1e-9:
        raise ControlledBindingError("共享账本历史保守占用不是 0.03 元（拒绝改历史/改预算）")
    if abs(Decimal(str(summary.total_limit_cny)) - expected_total_limit) > Decimal("0.000000001"):
        raise ControlledBindingError("共享账本总上限与计划不一致")


# ---------------------------------------------------------------- 受控付费边界
#
# F-1 返工：``create_app`` 之前只把底层 gateway/provider/ocr 注入产品，产品 HTTP 问答、
# 索引 embedding/rerank、生产 worker OCR 都绕过了执行器的 ``_begin/_finish/_fail``。
# 这里改为把“适配器内部的共享账本”包成受控代理：任何**真实供应商 POST 前的账本预留**
# 都必须先过执行器的每类计划计数/全局串行/停机门（``_begin``），成功结算后才计数
# （``_finish_mapped``）；失败/超时/中断/无效响应/拒结算则按是否已实际发送决定停机。
# 计数发生在实际付费边界而不是高层业务流程，因此 embedding 多批次不会被隐藏成一个请求。
#
# 直接 ``run_/arun_`` 与产品注入共享同一套包装（包装不做第二层计数），避免重复计数/死锁。

_OCR_TEXT_KIND = "ocr_text"
_OCR_TABLE_KIND = "ocr_table"


def _planned_kind(kind: str, model: Any = None) -> str:
    """把供应商 kind 映射到计划分类（OCR 按 text/table 分类，其余原样）。"""
    if kind == "ocr":
        return _OCR_TABLE_KIND if "table" in str(model or "").lower() else _OCR_TEXT_KIND
    return kind


class _ControlledBudget:
    """共享账本的受控代理：在真实预留/结算边界执行计划计数、全局串行与失败停机。"""

    def __init__(self, executor: "ControlledExecution", inner: Any) -> None:
        self._executor = executor
        self._inner = inner

    def __repr__(self) -> str:  # 不含账本原文
        return f"_ControlledBudget(inner={type(self._inner).__name__})"

    def __getattr__(self, name: str) -> Any:
        try:
            inner = object.__getattribute__(self, "_inner")
        except AttributeError:  # pragma: no cover - 初始化前访问
            raise AttributeError(name) from None
        return getattr(inner, name)

    # ------------------------------------------------------------ 预留/结算

    def reserve(
        self,
        *,
        kind: str,
        provider: str,
        model: str,
        max_cny: float,
        request_sha256: str,
        settlement_policy: Any = None,
        metadata: Any = None,
        stage_limit_cny: float | None = None,
        max_requests: int | None = None,
    ) -> Any:
        ex = self._executor
        mapped = _planned_kind(kind, model)
        # 计划计数/串行/停机门：拒绝发生在任何真实预留/发送之前（不多预留不 POST）。
        ex._begin(mapped)
        try:
            reservation = self._inner.reserve(
                kind=kind,
                provider=provider,
                model=model,
                max_cny=max_cny,
                request_sha256=request_sha256,
                settlement_policy=settlement_policy,
                metadata=metadata,
                stage_limit_cny=stage_limit_cny,
                max_requests=max_requests,
            )
        except BaseException:
            # 预算/授权/请求上限拒绝：释放串行占用，不计数、不停止（发送前拒绝）。
            ex._release(mapped)
            raise
        with ex._lock:
            ex._kinds_by_reservation[reservation.reservation_id] = mapped
        return reservation

    def recheck_reservation(self, reservation: Any) -> None:
        inner = getattr(self._inner, "recheck_reservation", None)
        if inner is None:
            return
        inner(reservation)

    def settle(self, reservation: Any, **kwargs: Any) -> Any:
        ex = self._executor
        kind = ex._pop_reservation_kind(reservation)
        try:
            event = self._inner.settle(reservation, **kwargs)
        except BaseException as exc:
            ex._fail(exc)
            raise
        if kwargs.get("status") == "succeeded":
            ex._finish_mapped(kind)
        else:
            # 非成功结算：只有确实发生过实际发送才停机；发送前复核拒绝按拒绝释放。
            if ex._post_sent_since_begin():
                ex._stop_with_code(kwargs.get("error_code"))
            else:
                ex._release(kind)
        return event

    def settle_usage(self, reservation: Any, **kwargs: Any) -> Any:
        ex = self._executor
        kind = ex._pop_reservation_kind(reservation)
        try:
            decision = self._inner.settle_usage(reservation, **kwargs)
        except BaseException as exc:
            # usage 超 cap/矛盾/拒结算：实际调用已发生 ⇒ 停机并全额保留（由 J1 账本写入）。
            ex._fail(exc)
            raise
        ex._finish_mapped(kind)
        return decision


class _ControlledChatGateway:
    """产品 chat 网关适配：真实计数/串行/停机由受控账本代理执行，这里只做失败/中断清理。"""

    def __init__(self, executor: "ControlledExecution", inner: Any) -> None:
        self._executor = executor
        self._inner = inner

    def __repr__(self) -> str:  # 不含密钥
        return f"_ControlledChatGateway(inner={self._inner!r})"

    def __getattr__(self, name: str) -> Any:
        try:
            inner = object.__getattribute__(self, "_inner")
        except AttributeError:  # pragma: no cover
            raise AttributeError(name) from None
        return getattr(inner, name)

    async def complete(self, request: CompletionInput, *, timeout_seconds: float) -> CompletionOutput:
        ex = self._executor
        inner = self._inner
        if inner is None:
            raise ControlledRefused("受控执行器未配置 chat 网关，拒绝调用（未预留未发送）")
        if ex._adapter_bound(inner, "chat"):
            try:
                return await inner.complete(request, timeout_seconds=timeout_seconds)
            except BaseException as exc:  # noqa: BLE001 - 失败即按边界归因，不吞不重试
                ex._handle_channel_exception(exc)
                raise
        # 非受控替身（单元测试）：回退到单层计数边界，避免双层重复计数。
        return await ex._execute_async(
            "chat", lambda: inner.complete(request, timeout_seconds=timeout_seconds)
        )

    async def aclose(self) -> None:
        closer = getattr(self._inner, "aclose", None)
        if closer is not None:
            await closer()

    def stats(self) -> Any:
        stats = getattr(self._inner, "stats", None)
        return stats() if callable(stats) else None


class _ControlledEmbeddingProvider:
    """产品 embedding 适配：多批次 POST 的计数由账本代理在每批真实预留边界执行。"""

    def __init__(self, executor: "ControlledExecution", inner: Any) -> None:
        self._executor = executor
        self._inner = inner

    def __repr__(self) -> str:
        return f"_ControlledEmbeddingProvider(inner={self._inner!r})"

    def __getattr__(self, name: str) -> Any:
        try:
            inner = object.__getattribute__(self, "_inner")
        except AttributeError:  # pragma: no cover
            raise AttributeError(name) from None
        return getattr(inner, name)

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()

    def embed(self, texts: Any, *, purpose: str = "document") -> Any:
        ex = self._executor
        inner = self._inner
        if inner is None:
            raise ControlledRefused("受控执行器未配置 embedding provider，拒绝调用（未预留未发送）")
        if ex._adapter_bound(inner, "embedding"):
            try:
                return inner.embed(texts, purpose=purpose)
            except BaseException as exc:  # noqa: BLE001
                ex._handle_channel_exception(exc)
                raise
        return ex._run("embedding", lambda: inner.embed(texts, purpose=purpose))


class _ControlledRerankProvider:
    """产品 rerank 适配：计数/串行/停机由账本代理在真实预留边界执行。"""

    def __init__(self, executor: "ControlledExecution", inner: Any) -> None:
        self._executor = executor
        self._inner = inner

    def __repr__(self) -> str:
        return f"_ControlledRerankProvider(inner={self._inner!r})"

    def __getattr__(self, name: str) -> Any:
        try:
            inner = object.__getattribute__(self, "_inner")
        except AttributeError:  # pragma: no cover
            raise AttributeError(name) from None
        return getattr(inner, name)

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()

    def rerank(self, query: str, documents: Any, *, top_n: int | None = None) -> Any:
        ex = self._executor
        inner = self._inner
        if inner is None:
            raise ControlledRefused("受控执行器未配置 rerank provider，拒绝调用（未预留未发送）")
        if ex._adapter_bound(inner, "rerank"):
            try:
                return inner.rerank(query, documents, top_n=top_n)
            except BaseException as exc:  # noqa: BLE001
                ex._handle_channel_exception(exc)
                raise
        return ex._run("rerank", lambda: inner.rerank(query, documents, top_n=top_n))


class _ControlledOCRGateway:
    """产品/实际 worker OCR 适配：每次实际 recognize（一次真实调用）先过计划分类计数与串行门。

    发送前拒绝（``OCRBudgetRefused``，如额外 tile/第 14 次/预算门）不计数也不停机；
    真实调用失败/超时/中断（原异常）则停机并全额保留。
    """

    def __init__(self, executor: "ControlledExecution", inner: Any) -> None:
        self._executor = executor
        self._inner = inner

    def __repr__(self) -> str:  # 不含凭据
        return f"_ControlledOCRGateway(inner={self._inner!r})"

    def __getattr__(self, name: str) -> Any:
        try:
            inner = object.__getattribute__(self, "_inner")
        except AttributeError:  # pragma: no cover
            raise AttributeError(name) from None
        return getattr(inner, name)

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()

    def stats(self) -> Any:
        stats = getattr(self._inner, "stats", None)
        return stats() if callable(stats) else None

    def recognize(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult:
        ex = self._executor
        inner = self._inner
        if inner is None:
            raise ControlledRefused("受控执行器未配置 OCR 网关，拒绝调用（未预留未发送）")
        kind = _OCR_TABLE_KIND if mode == "table" else _OCR_TEXT_KIND
        try:
            ex._begin(kind)
        except ControlledRefused as exc:
            # 实际 OCR 生产网关的统一预发送错误：worker 审计/重试逻辑按稳定 OCR 预算码处理，
            # 不把受控计数拒绝记成内部错误；单元测试替身维持 ControlledRefused。
            if isinstance(inner, BudgetedOCRGateway):
                raise OCRBudgetRefused(
                    f"受控 OCR 计划边界拒绝（{exc.code}），未预留未发送"
                ) from None
            raise
        try:
            result = inner.recognize(page, mode=mode)
        except OCRBudgetRefused:
            ex._release(kind)
            raise
        except BaseException as exc:  # noqa: BLE001 - 原异常原样传播，不吞不重试
            ex._fail(exc)
            raise
        ex._finish(kind)
        return result


class _ControlledRagChatProvider:
    """第二 chat 生产适配入口（``rag.providers.DeepSeekChatProvider``）的受控包装。"""

    def __init__(self, executor: "ControlledExecution", inner: Any) -> None:
        self._executor = executor
        self._inner = inner

    def __repr__(self) -> str:
        return f"_ControlledRagChatProvider(inner={self._inner!r})"

    def __getattr__(self, name: str) -> Any:
        try:
            inner = object.__getattribute__(self, "_inner")
        except AttributeError:  # pragma: no cover
            raise AttributeError(name) from None
        return getattr(inner, name)

    def close(self) -> None:
        # 该 provider 由受控执行器持有并跨调用复用，产品侧 ``finally: close()`` 不得关闭共享客户端。
        return None

    def complete(self, *, system: str, user: str, max_output_tokens: int | None = None) -> Any:
        ex = self._executor
        inner = self._inner
        if inner is None:
            raise ControlledRefused("受控执行器未配置第二 chat 适配入口，拒绝调用（未预留未发送）")
        if ex._adapter_bound(inner, "rag_chat"):
            try:
                return inner.complete(system=system, user=user, max_output_tokens=max_output_tokens)
            except BaseException as exc:  # noqa: BLE001
                ex._handle_channel_exception(exc)
                raise
        return ex._run(
            "chat",
            lambda: inner.complete(system=system, user=user, max_output_tokens=max_output_tokens),
        )


# ---------------------------------------------------------------- 执行入口


class ControlledExecution:
    """正式受控执行入口：GO/plan 绑定 + 共享账本 + 版本化适配器 + 受控计数。"""

    def __init__(
        self,
        *,
        plan: ControlledRequestPlan,
        chat_gate: LiveGate,
        rag_gate: LiveGate | None,
        chat_gateway: BudgetedModelGateway,
        rag_config: Any,
        rag_budget: Any,
        embedding_provider: Any,
        rerank_provider: Any,
        ocr_gateway: BudgetedOCRGateway,
        chat_policy: SettlementPolicy,
        embedding_policy: SettlementPolicy,
        rerank_policy: SettlementPolicy,
        rag_chat_provider: Any = None,
    ) -> None:
        self.plan = plan
        self.chat_gate = chat_gate
        self.rag_gate = rag_gate
        self.rag_config = rag_config
        self.rag_budget = rag_budget
        self.chat_policy = chat_policy
        self.embedding_policy = embedding_policy
        self.rerank_policy = rerank_policy
        # 原始适配器（计数/串行/停机门由受控账本代理在真实预留/结算边界执行）。
        self._raw_chat_gateway = chat_gateway
        self._raw_embedding_provider = embedding_provider
        self._raw_rerank_provider = rerank_provider
        self._raw_ocr_gateway = ocr_gateway
        self._raw_rag_chat_provider = rag_chat_provider
        self._lock = threading.Lock()
        self._in_flight: str | None = None
        self._stopped = False
        self._stop_code: str | None = None
        self._counts: dict[str, int] = {
            "chat": 0,
            "embedding": 0,
            "rerank": 0,
            "ocr_text": 0,
            "ocr_table": 0,
        }
        self._limits: dict[str, int] = {
            "chat": plan.chat_requests,
            "embedding": plan.embedding_requests,
            "rerank": plan.rerank_requests,
            "ocr_text": plan.ocr_text_requests,
            "ocr_table": plan.ocr_table_requests,
        }
        self._attempts_at_begin = 0
        self._kinds_by_reservation: dict[str, str] = {}
        self._chat_proxy: _ControlledBudget | None = None
        self._rag_proxy: _ControlledBudget | None = None
        self._attach_budget_boundaries()
        # 产品/直接入口统一注入同一套包装（包装不做第二层计数，避免重复计数/重入死锁）。
        self.chat_gateway = _ControlledChatGateway(self, chat_gateway)
        self.embedding_provider = _ControlledEmbeddingProvider(self, embedding_provider)
        self.rerank_provider = _ControlledRerankProvider(self, rerank_provider)
        self.ocr_gateway = _ControlledOCRGateway(self, ocr_gateway)
        self.rag_chat_provider = _ControlledRagChatProvider(self, rag_chat_provider)

    # ---------------------------------------------------------------- 账本边界

    def _attach_budget_boundaries(self) -> None:
        """把适配器内部的共享账本替换为受控代理（只在本执行器构造的适配器上生效）。"""
        gateway = self._raw_chat_gateway
        ledger = getattr(gateway, "_budget", None) if gateway is not None else None
        if isinstance(ledger, _ControlledBudget):
            self._chat_proxy = ledger
        elif ledger is not None:
            self._chat_proxy = _ControlledBudget(self, ledger)
            gateway._budget = self._chat_proxy  # noqa: SLF001 - 受控装配适配（同一包内）
        for provider in (
            self._raw_embedding_provider,
            self._raw_rerank_provider,
            self._raw_rag_chat_provider,
        ):
            if provider is None:
                continue
            inner = getattr(provider, "budget", None)
            if inner is None:
                continue
            if isinstance(inner, _ControlledBudget):
                if self._rag_proxy is None:
                    self._rag_proxy = inner
                continue
            if self._rag_proxy is None:
                self._rag_proxy = _ControlledBudget(self, inner)
            provider.budget = self._rag_proxy

    def _adapter_bound(self, raw: Any, channel: str) -> bool:
        """该适配器是否已处于受控账本边界（否则回退单层计数，供单元测试替身使用）。"""
        if channel in ("embedding", "rerank", "rag_chat"):
            return getattr(raw, "budget", None) is self._rag_proxy and self._rag_proxy is not None
        return getattr(raw, "_budget", None) is self._chat_proxy and self._chat_proxy is not None

    def _attempt_watermark(self) -> int:
        """实际供应商 POST 尝试水位：rag provider 计数 + chat 网关 send_attempts。"""
        total = 0
        try:
            attempts = post_counters().get("attempts") or {}
            total += sum(int(value) for value in attempts.values())
        except Exception:  # noqa: BLE001 - 诊断不改变主流程
            pass
        gateway = self._raw_chat_gateway
        stats = getattr(gateway, "stats", None)
        if callable(stats):
            try:
                counters = (stats() or {}).get("counters") or {}
                total += int(counters.get("send_attempts") or 0)
            except Exception:  # noqa: BLE001
                pass
        return total

    def _post_sent_since_begin(self) -> bool:
        return self._attempt_watermark() > self._attempts_at_begin

    def _handle_channel_exception(self, exc: BaseException) -> None:
        """渠道异常清理：受控拒绝不改变状态；仍有在途边界（中断/未结算异常）则停机。"""
        if isinstance(exc, ControlledRefused):
            return
        with self._lock:
            active = self._in_flight
        if active is not None:
            self._fail(exc)

    def _release(self, kind: str | None = None) -> None:
        with self._lock:
            if kind is None or self._in_flight == kind:
                self._in_flight = None

    def _finish_mapped(self, kind: str) -> None:
        with self._lock:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            self._in_flight = None

    def _stop_with_code(self, code: Any) -> None:
        with self._lock:
            self._in_flight = None
            self._stopped = True
            self._stop_code = safe_error_code(code) if isinstance(code, str) else "PROVIDER_ERROR"

    def _pop_reservation_kind(self, reservation: Any) -> str:
        with self._lock:
            kind = self._kinds_by_reservation.pop(
                getattr(reservation, "reservation_id", ""), None
            )
        if kind is None:
            kind = _planned_kind(
                str(getattr(reservation, "kind", "") or ""),
                getattr(reservation, "model", None),
            )
        return kind

    # ---------------------------------------------------------------- 构造

    @classmethod
    def build(
        cls,
        *,
        settings: Any,
        plan: ControlledRequestPlan | None = None,
        data_dir: Any = None,
        page_size: int = 10,
        top_k: int = 8,
        business_date: str | None = None,
        chat_transport: Any = None,
        rag_transport: Any = None,
        ocr_transport: Any = None,
        stage: str | None = None,
        chat_stage_limit_cny: float | None = None,
        chat_max_requests: int | None = None,
    ) -> "ControlledExecution":
        plan = plan or ControlledRequestPlan(stage=stage or product_stage())
        resolved_stage = str(stage or plan.stage or product_stage()).strip()
        if resolved_stage != plan.stage:
            raise ControlledBindingError("显式 stage 与 plan.stage 不一致")
        stage_limit = (
            float(chat_stage_limit_cny)
            if chat_stage_limit_cny is not None
            else positive_float_env("MKTKB_RAG_STAGE_LIMIT_CNY")
        )
        max_requests = (
            int(chat_max_requests)
            if chat_max_requests is not None
            else positive_int_env("MKTKB_RAG_MAX_REQUESTS")
        )
        if stage_limit is None or max_requests is None:
            raise ControlledBindingError(
                "受控执行入口必须显式给出阶段额度/累计请求上限（省略/0/负数一律拒绝）"
            )
        pricing = ChatPricing.from_env()
        if pricing is None:
            raise ControlledBindingError("chat 价格/官方上限未配置，受控执行入口拒绝构造")
        chat_reserve = Decimal(str(pricing.worst_case_cny()))
        try:
            chat_gate = resolve_live_gate(
                stage=resolved_stage,
                service="chat",
                requested_stage_limit_cny=stage_limit,
                requested_max_requests=max_requests,
                request_bound_cny=float(chat_reserve),
            )
        except LiveGateError as exc:
            raise ControlledBindingError(f"chat GO 闸门拒绝：{exc}") from None
        try:
            rag_authorization = load_live_authorization(stage=resolved_stage, service="rag")
        except LiveGateError as exc:
            raise ControlledBindingError(f"rag GO 授权读取拒绝：{exc}") from None
        expected = _plan_bindings(plan)
        # 先由 J2 的“只报字段名/期望值”核对计划绑定（不回显 GO 原文），再进入产品
        # resolve_rag_config 的既有绑定核对；避免把 GO 原文经旧异常路径带出。
        _verify_fields(chat_gate.authorization, "chat", expected["chat"])
        _verify_fields(rag_authorization, "rag", expected["rag"])
        from .qa.service import resolve_rag_config

        try:
            rag_config, rag_budget = resolve_rag_config(
                data_dir=data_dir,
                provider_mode="live",
                page_size=page_size,
                top_k=top_k,
                business_date=business_date,
            )
        except (LiveGateError, ValueError) as exc:
            raise ControlledBindingError(f"rag GO/预算入口拒绝：{exc}") from None
        _assert_gate_limits(
            plan,
            chat_gate=chat_gate,
            rag_budget=rag_budget,
            rag_config=rag_config,
            chat_reserve_cny=chat_reserve,
        )
        # GO 的 chat 供应商基础绑定由 build_gateway 再次核对；这里先构造版本化网关。
        chat_model = rag_config.chat_model or getattr(settings, "model_name", None)
        if not chat_model:
            raise ControlledBindingError("运行期缺少 chat model，无法绑定计划来源")
        chat_policy = build_policy("chat", model=str(chat_model))
        embedding_policy = build_policy("embedding", model=rag_config.embedding_model)
        rerank_policy = build_policy("rerank", model=rag_config.rerank_model)
        if chat_policy.model != CHAT_MODEL:
            raise ControlledBindingError("运行期 chat model 与计划来源不一致")
        if embedding_policy.model != EMBEDDING_MODEL or rerank_policy.model != RERANK_MODEL:
            raise ControlledBindingError("运行期 embedding/rerank model 与计划来源不一致")
        try:
            chat_gateway = build_gateway(
                settings,
                gate=chat_gate,
                transport=chat_transport,
                settlement_policy=chat_policy,
            )
        except (LiveGateError, ValueError, TypeError) as exc:
            raise ControlledBindingError(f"chat 受控网关构造拒绝：{exc}") from None
        if not isinstance(chat_gateway, BudgetedModelGateway):
            raise ControlledBindingError("chat 受控网关不是预算包装实例")
        from .rag.providers import BailianEmbeddingProvider, BailianRerankProvider, DeepSeekChatProvider

        try:
            embedding_provider = BailianEmbeddingProvider(
                rag_config,
                budget=rag_budget,
                transport=rag_transport,
                settlement_policy=embedding_policy,
            )
            rerank_provider = BailianRerankProvider(
                rag_config,
                budget=rag_budget,
                transport=rag_transport,
                settlement_policy=rerank_policy,
            )
            # 第二 chat 生产适配入口（rag 文档型回答使用的 DeepSeekChatProvider）也纳入同一
            # 执行器的预留/计数/串行/停机组；直接 Mock 入口与产品注入共用该实例。
            rag_chat_provider = DeepSeekChatProvider(
                rag_config,
                budget=rag_budget,
                transport=rag_transport,
                settlement_policy=chat_policy,
            )
        except (ValueError, TypeError) as exc:
            raise ControlledBindingError(f"rag 受控 provider 构造拒绝：{exc}") from None
        raw_ocr = build_ocr_gateway(settings, transport=ocr_transport)
        if raw_ocr is None:
            raise ControlledBindingError("运行期 OCR 网关未配置，受控 OCR 路线无法证明绑定")
        configured_region = str(getattr(settings, "ocr_region", "ap-guangzhou")).strip()
        if configured_region != OCR_REGION:
            raise ControlledBindingError("运行期 OCR region 与计划来源不一致")
        try:
            ocr_gateway = BudgetedOCRGateway(
                raw_ocr,
                ledger=rag_budget,
                max_calls=plan.ocr_total_requests,
                max_tiles_per_page=plan.ocr_max_tiles_per_page,
                attempts=plan.ocr_max_attempts,
                text_price_cny=OCR_TEXT_PRICE_CNY,
                table_price_cny=OCR_TABLE_PRICE_CNY,
            )
        except (ValueError, TypeError) as exc:
            raise ControlledBindingError(f"OCR 受控包装构造拒绝：{exc}") from None
        return cls(
            plan=plan,
            chat_gate=chat_gate,
            rag_gate=None,
            chat_gateway=chat_gateway,
            rag_config=rag_config,
            rag_budget=rag_budget,
            embedding_provider=embedding_provider,
            rerank_provider=rerank_provider,
            ocr_gateway=ocr_gateway,
            chat_policy=chat_policy,
            embedding_policy=embedding_policy,
            rerank_policy=rerank_policy,
            rag_chat_provider=rag_chat_provider,
        )

    # ---------------------------------------------------------------- 受控边界

    @property
    def stopped(self) -> bool:
        with self._lock:
            return self._stopped

    @property
    def stop_code(self) -> str | None:
        with self._lock:
            return self._stop_code

    def _begin(self, kind: str) -> None:
        with self._lock:
            if self._stopped:
                raise ControlledRefused(f"受控执行入口已停止（{self._stop_code}），拒绝后续调用")
            if self._in_flight is not None:
                raise ControlledRefused("串行计划不允许并发调用，拒绝（未预留未发送）")
            if self._counts.get(kind, 0) >= self._limits.get(kind, 0):
                raise ControlledRefused(f"{kind} 请求数达到计划上限，拒绝（未预留未发送）")
            self._in_flight = kind
            # 记录本次边界的实际 POST 水位（用于区分发送前拒绝与发送后失败停机）。
            self._attempts_at_begin = self._attempt_watermark()

    def _finish(self, kind: str) -> None:
        with self._lock:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            self._in_flight = None

    def _fail(self, exc: BaseException) -> None:
        with self._lock:
            self._in_flight = None
            self._stopped = True
            code = getattr(exc, "code", None)
            self._stop_code = safe_error_code(code) if isinstance(code, str) else "PROVIDER_ERROR"

    def _run(self, kind: str, call: Any) -> Any:
        self._begin(kind)
        try:
            value = call()
        except BaseException as exc:  # noqa: BLE001 - 失败即停；原样传播，不吞不重试
            self._fail(exc)
            raise
        self._finish(kind)
        return value

    async def _execute_async(self, kind: str, call: Any) -> Any:
        self._begin(kind)
        try:
            value = await call()
        except BaseException as exc:  # noqa: BLE001
            self._fail(exc)
            raise
        self._finish(kind)
        return value

    # ---------------------------------------------------------------- 调用面

    def run_chat(self, request: CompletionInput, *, timeout_seconds: float = 30.0) -> CompletionOutput:
        import asyncio

        return asyncio.run(self.arun_chat(request, timeout_seconds=timeout_seconds))

    async def arun_chat(self, request: CompletionInput, *, timeout_seconds: float = 30.0) -> CompletionOutput:
        return await self.chat_gateway.complete(request, timeout_seconds=timeout_seconds)

    def run_embedding(self, texts: Any, *, purpose: str = "document") -> Any:
        return self.embedding_provider.embed(texts, purpose=purpose)

    def run_rerank(self, query: str, documents: Any, *, top_n: int | None = None) -> Any:
        return self.rerank_provider.rerank(query, documents, top_n=top_n)

    def run_ocr(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult:
        return self.ocr_gateway.recognize(page, mode=mode)

    def run_rag_chat(
        self, *, system: str, user: str, max_output_tokens: int | None = None
    ) -> Any:
        """第二 chat 生产适配入口的直接受控调用（与产品注入共用同一计数/串行/停机门）。"""
        return self.rag_chat_provider.complete(
            system=system, user=user, max_output_tokens=max_output_tokens
        )

    # ---------------------------------------------------------------- 诊断

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self._counts)
            in_flight = self._in_flight
            stopped = self._stopped
            stop_code = self._stop_code
        try:
            summary = self.chat_gate.ledger().summary().as_dict()
        except Exception:  # noqa: BLE001 - 诊断不改变主流程
            summary = {"error": "summary_unavailable"}
        try:
            gate_payload = self.chat_gate.as_dict()
        except Exception:  # noqa: BLE001
            gate_payload = None
        return {
            "plan": self.plan.plan_dict(),
            "request_plan_sha256": self.plan.request_plan_sha256,
            "counts": counts,
            "limits": dict(self._limits),
            "in_flight": in_flight,
            "stopped": stopped,
            "stop_code": stop_code,
            "chat_gate": gate_payload,
            "ledger_summary": summary,
            "chat_gateway_stats": (
                self.chat_gateway.stats() if hasattr(self.chat_gateway, "stats") else None
            ),
            "ocr_stats": (
                self.ocr_gateway.stats() if hasattr(self.ocr_gateway, "stats") else None
            ),
            "controlled_boundaries": {
                "chat_budget_proxy": (
                    type(self._chat_proxy).__name__ if self._chat_proxy is not None else None
                ),
                "rag_budget_proxy": (
                    type(self._rag_proxy).__name__ if self._rag_proxy is not None else None
                ),
                "embedding_budget": type(
                    getattr(self._raw_embedding_provider, "budget", None)
                ).__name__,
                "rerank_budget": type(
                    getattr(self._raw_rerank_provider, "budget", None)
                ).__name__,
                "rag_chat_budget": type(
                    getattr(self._raw_rag_chat_provider, "budget", None)
                ).__name__,
                "rag_chat_provider": type(self._raw_rag_chat_provider).__name__,
                "ocr_ledger": type(getattr(self._raw_ocr_gateway, "_ledger", None)).__name__,
            },
            "settlement_versions": {
                "chat": getattr(self.chat_policy, "version", None),
                "embedding": getattr(self.embedding_policy, "version", None),
                "rerank": getattr(self.rerank_policy, "version", None),
            },
        }

    def create_app(self, settings: Any, *, initialize: bool = True) -> Any:
        """把受控适配器注入产品应用（未来真实矩阵使用；本包 Mock 只证明可注入）。

        注意：QaEngine 与 create_app 各建一个 Database 实例指向同一 SQLite URL；
        仅用于受控单写者运行，不改变任何既有产品默认路径。
        """
        from .db import Database
        from .qa.service import QaEngine

        database = Database(
            settings.resolved_database_url(),
            busy_timeout_ms=settings.sqlite_busy_timeout_ms,
            enable_wal=settings.enable_wal,
        )
        qa_engine = QaEngine(
            database,
            settings.resolved_rag_index_path,
            config=self.rag_config,
            embedder=self.embedding_provider,
            reranker=self.rerank_provider,
            budget=self.rag_budget,
            embedding_retry_seconds=settings.rag_embedding_retry_seconds,
        )
        from .main import create_app as _create_app

        app = _create_app(
            settings,
            initialize=initialize,
            model_gateway=self.chat_gateway,
            ocr_gateway=self.ocr_gateway,
            qa_engine=qa_engine,
        )
        app.state.controlled_execution = self
        # 实际生产 worker 的 OCR 网关：worker 必须以该受控网关构造，才受同一计数/串行/停机组约束。
        app.state.worker_ocr_gateway = self.ocr_gateway
        return app
