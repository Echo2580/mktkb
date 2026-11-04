"""正文型/非 rag-owned 轮次的 chat 网关预算边界（GAP-3）。

`providers.build_gateway` 是产品 chat 的唯一构造入口。历史上它只要三项配置齐备就
直接构造真实客户端，既不进共享账本、也不受累计请求上限约束。这里用一个薄包装把
``ModelGateway`` 接口接上同一只共享账本与同一份 GO 授权：

- 每次实际 HTTP 尝试（含一次调用内的重试）之前，先按**可证明的最坏输入/输出上界**
  预留金额；预留失败（预算/累计请求/账本不可用）即不发请求；
- 成功后按 usage 估算标价；失败/超时/取消/断连都不清零（保守占用 = 预留额）；
- 价格、官方最大输入/输出上界缺失或超过 GO 单请求上界时，构造阶段就拒绝，
  不猜免费、不调用官方接口求证。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..live_authorization import LiveAuthorization, LiveGate, LiveGateError
from ..numeric import NumericInvalid, finite_positive, positive_int
from ..official_chat_profile import (
    OfficialChatProfileError,
    assert_official_chat_pricing_floor,
)
from ..rag.budget import BudgetExceeded, BudgetLedgerInvalid, RequestLimitExceeded
from ..rag.config import positive_float_env, positive_int_env
from ..rag.controlled_usage import (
    build_chat_evidence,
    safe_error_code,
    safe_request_id,
)
from ..rag.settlement_policy import KIND_CHAT, SETTLEMENT_VERSION, SettlementPolicy
from .deepseek import DeepSeekClient
from .types import (
    CompletionInput,
    CompletionOutput,
    ModelBudgetRefused,
    ModelError,
    ModelTimeout,
    ModelUnavailable,
)


def _pricing_positive(value: Any, label: str) -> float:
    try:
        return finite_positive(value, label)
    except NumericInvalid as exc:
        raise LiveGateError(str(exc)) from None


def _pricing_int(value: Any, label: str) -> int:
    try:
        return positive_int(value, label)
    except NumericInvalid as exc:
        raise LiveGateError(str(exc)) from None


class ModelPostSendDenied(ModelUnavailable):
    """预留成功后、真实 POST 前的授权/预算复核拒绝；该次请求未发出。"""

    code = "MODEL_POST_SEND_AUTH_DENIED"


def _accepts_pre_send_check(inner: Any) -> bool:
    """inner 是否接受发送边界回调（生产 DeepSeekClient 接受；旧替身忽略）。"""
    try:
        parameters = inspect.signature(inner.complete).parameters
    except (TypeError, ValueError):
        return False
    return "pre_send_check" in parameters or any(
        parameter.kind is parameter.VAR_KEYWORD for parameter in parameters.values()
    )


@dataclass(frozen=True)
class ChatPricing:
    """chat 的官方计费上界与价格（只来自服务端配置/环境，不接受调用方传入）。

    S2-H-R2：``reserve_profile=model_context_ceiling`` 时预留按 ``context_ceiling_tokens``
    全额输入 + 固定 800 输出；``max_input_tokens`` 仅作为 payload 字节闸门，
    不再作为可发送证明，也不再用本地 tokenizer 的小额上界压低预留。
    """

    input_price_per_million_cny: float
    output_price_per_million_cny: float
    max_input_tokens: int
    max_output_tokens: int
    reserve_profile: str
    context_ceiling_tokens: int

    def __post_init__(self) -> None:
        _pricing_positive(self.input_price_per_million_cny, "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY")
        _pricing_positive(
            self.output_price_per_million_cny, "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY"
        )
        _pricing_int(self.max_input_tokens, "MKTKB_MODEL_MAX_INPUT_TOKENS")
        _pricing_int(self.max_output_tokens, "MKTKB_MODEL_MAX_OUTPUT_TOKENS")
        _pricing_int(self.context_ceiling_tokens, "MKTKB_MODEL_CONTEXT_CEILING_TOKENS")
        if self.reserve_profile != "model_context_ceiling":
            raise LiveGateError("chat 只允许 model_context_ceiling 保守预留 profile")
        if self.context_ceiling_tokens < self.max_input_tokens:
            raise LiveGateError("官方 context 上限不能小于 payload 输入闸门")
        if self.max_output_tokens != 800:
            raise LiveGateError("model_context_ceiling 要求官方输出上界固定为 800")
        try:
            assert_official_chat_pricing_floor(
                reserve_profile=self.reserve_profile,
                context_ceiling_tokens=self.context_ceiling_tokens,
                input_price_per_million_cny=self.input_price_per_million_cny,
                output_price_per_million_cny=self.output_price_per_million_cny,
                max_output_tokens=self.max_output_tokens,
            )
        except OfficialChatProfileError as exc:
            raise LiveGateError(f"chat 官方 profile 校验拒绝：{exc}") from None

    @classmethod
    def from_env(cls) -> "ChatPricing | None":
        input_price = positive_float_env("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY")
        output_price = positive_float_env("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY")
        max_input = positive_int_env("MKTKB_MODEL_MAX_INPUT_TOKENS")
        max_output = positive_int_env("MKTKB_MODEL_MAX_OUTPUT_TOKENS")
        ceiling = positive_int_env("MKTKB_MODEL_CONTEXT_CEILING_TOKENS")
        profile = (__import__("os").environ.get("MKTKB_MODEL_RESERVE_PROFILE") or "").strip()
        if None in (input_price, output_price, max_input, max_output, ceiling) or not profile:
            return None
        return cls(
            input_price_per_million_cny=float(input_price),  # type: ignore[arg-type]
            output_price_per_million_cny=float(output_price),  # type: ignore[arg-type]
            max_input_tokens=int(max_input),  # type: ignore[arg-type]
            max_output_tokens=int(max_output),  # type: ignore[arg-type]
            reserve_profile=profile,
            context_ceiling_tokens=int(ceiling),  # type: ignore[arg-type]
        )

    def worst_case_cny(self) -> float:
        """单次调用的可证明最坏计费上界（官方 context 上限全额输入 + 固定 800 输出）。"""
        bound = (
            self.context_ceiling_tokens * self.input_price_per_million_cny / 1_000_000.0
            + 800 * self.output_price_per_million_cny / 1_000_000.0
        )
        return _pricing_positive(bound, "chat 单请求保守上界")

    def estimate_cny(self, usage: dict[str, int]) -> float:
        prompt = int(usage.get("prompt_tokens") or self.context_ceiling_tokens)
        completion = int(usage.get("completion_tokens") or self.max_output_tokens)
        return (
            max(prompt, 0) * self.input_price_per_million_cny / 1_000_000.0
            + max(completion, 0) * self.output_price_per_million_cny / 1_000_000.0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_price_per_million_cny": self.input_price_per_million_cny,
            "output_price_per_million_cny": self.output_price_per_million_cny,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "reserve_profile": self.reserve_profile,
            "context_ceiling_tokens": self.context_ceiling_tokens,
            "reserve_input_tokens": self.context_ceiling_tokens,
            "reserve_output_tokens": 800,
            "worst_case_cny": round(self.worst_case_cny(), 10),
        }


class BudgetedModelGateway:
    """ModelGateway 的预算/授权包装：预留-发送-结算三层可分别观测。"""

    def __init__(
        self,
        inner: DeepSeekClient,
        *,
        gate: LiveGate,
        pricing: ChatPricing,
        budget: Any | None = None,
        meter: Any | None = None,
        require_meter: bool = False,
        settlement_policy: SettlementPolicy | None = None,
    ) -> None:
        bound = pricing.worst_case_cny()
        if bound <= 0:
            raise LiveGateError("chat 单请求保守上界必须为正数")
        if require_meter and meter is None:
            raise LiveGateError("已要求官方 tokenizer 计量，但没有可用 meter，禁止发送")
        if bound > gate.max_request_cny + 1e-12:
            raise LiveGateError(
                f"chat 单请求保守上界 {bound:.8f} 元超过 GO 允许的 {gate.max_request_cny:.8f} 元"
            )
        if settlement_policy is not None:
            if not isinstance(settlement_policy, SettlementPolicy):
                raise LiveGateError("settlement_policy 必须是 SettlementPolicy")
            if settlement_policy.kind != KIND_CHAT or settlement_policy.provider != "deepseek":
                raise LiveGateError("settlement_policy 与 chat provider 不一致，禁止发送")
            if settlement_policy.model != str(getattr(inner, "_model", "")):
                raise LiveGateError("settlement_policy 与 chat 运行期模型不一致，禁止发送")
        inner_limit = getattr(inner, "max_output_tokens", None)
        if inner_limit is None:
            raise LiveGateError("chat 客户端未设置 max_tokens 输出上限，禁发")
        inner_limit = _pricing_int(inner_limit, "chat 客户端 max_output_tokens")
        if inner_limit > pricing.max_output_tokens:
            raise LiveGateError(
                "chat 客户端 max_tokens 超过预留采用的最大输出上界（拒绝发送超出预留的请求）"
            )
        self._inner = inner
        self._gate = gate
        self._pricing = pricing
        self._budget = budget if budget is not None else gate.ledger()
        self._bound_cny = bound
        self._meter = meter
        self._require_meter = require_meter
        self._settlement_policy = settlement_policy
        self._inner_accepts_pre_send_check = _accepts_pre_send_check(inner)
        self._counters: dict[str, Any] = {
            "reserved": 0,
            "send_attempts": 0,
            "pre_send_refused": 0,
            "refused": 0,
            "settle_errors": 0,
            "results": {},
        }

    # ---------------------------------------------------------------- 诊断

    @property
    def settlement_policy(self) -> SettlementPolicy | None:
        """当前生效的版本化结算策略（None = 历史旧结算语义，成功也按全额预留留账）。"""
        return self._settlement_policy

    def attach_settlement_policy(self, policy: SettlementPolicy) -> None:
        """把版本化结算策略挂到已构造的网关上（真实应用路径用；校验与构造期同一套）。

        - 只接受 chat 策略，provider/model 必须与内层客户端一致；
        - GO 的 chat 绑定必须显式声明同一 settlement_version（否则等于绕过授权声明）。
        """
        if not isinstance(policy, SettlementPolicy):
            raise LiveGateError("settlement_policy 必须是 SettlementPolicy")
        if policy.kind != KIND_CHAT or policy.provider != "deepseek":
            raise LiveGateError("settlement_policy 与 chat provider 不一致，禁止结算")
        if policy.model != str(getattr(self._inner, "_model", "")):
            raise LiveGateError("settlement_policy 与 chat 运行期模型不一致，禁止结算")
        bindings = getattr(getattr(self._gate, "authorization", None), "bindings", None) or {}
        chat_binding = (bindings or {}).get("chat") or {}
        if chat_binding.get("settlement_version") != SETTLEMENT_VERSION:
            raise LiveGateError("GO 未声明 settlement_version，拒绝版本化结算")
        self._settlement_policy = policy

    def __repr__(self) -> str:  # 不包含密钥
        return (
            f"BudgetedModelGateway(model={self._inner._model!r}, "  # noqa: SLF001
            f"stage={self._gate.stage!r}, bound_cny={self._bound_cny:.8f})"
        )

    def stats(self) -> dict[str, Any]:
        return {
            "gate": self._gate.as_dict(),
            "pricing": self._pricing.as_dict(),
            "request_bound_cny": round(self._bound_cny, 10),
            "token_meter": (
                self._meter.as_dict() if hasattr(self._meter, "as_dict") else None
            ),
            "token_meter_required": self._require_meter,
            "counters": {
                **{key: value for key, value in self._counters.items() if key != "results"},
                "results": dict(self._counters["results"]),
            },
        }

    @property
    def authorization(self) -> LiveAuthorization:
        return self._gate.authorization

    # ---------------------------------------------------------------- ModelGateway

    async def complete(self, request: CompletionInput, *, timeout_seconds: float) -> CompletionOutput:
        if timeout_seconds <= 0:
            raise ModelTimeout("剩余预算不足")
        upper_bytes = self._inner.request_upper_bytes(request)
        if upper_bytes > self._pricing.max_input_tokens:
            self._counters["refused"] += 1
            raise ModelUnavailable("chat 输入超过官方最大输入上界，禁发")
        # S2-H-R2：保守 profile —— 预留永远按官方 context 上限全额输入，
        # 不使用本地 tokenizer 的小额上界（该 artifact 与当前模型匹配未证）。
        input_tokens = int(self._pricing.context_ceiling_tokens)
        request_bound_cny = (
            input_tokens * self._pricing.input_price_per_million_cny / 1_000_000.0
            + 800 * self._pricing.output_price_per_million_cny / 1_000_000.0
        )
        if request_bound_cny > self._gate.max_request_cny + 1e-12:
            self._counters["refused"] += 1
            raise ModelUnavailable(
                f"chat 本次 token 上界 {request_bound_cny:.8f} 元超过 GO 单请求上限"
            )
        request_sha = hashlib.sha256(
            f"{request.purpose}|{upper_bytes}|{input_tokens}|{request_bound_cny:.10f}".encode("utf-8")
        ).hexdigest()
        try:
            reservation = self._budget.reserve(
                kind="chat",
                provider="deepseek",
                model=self._inner._model,  # noqa: SLF001 - 同包内只读模型名，不含密钥
                max_cny=request_bound_cny,
                request_sha256=request_sha,
                settlement_policy=self._settlement_policy,
            )
        except (BudgetExceeded, RequestLimitExceeded, BudgetLedgerInvalid) as exc:
            # 预算/累计请求/账本拒绝：这一步之前没有任何 HTTP。稳定码必须与“供应商不可用”分开，
            # 否则界面会把“阶段额度/授权不足”显示成服务故障（MODEL_BUDGET_REFUSED）。
            self._counters["refused"] += 1
            raise ModelBudgetRefused(f"预算/授权闸门拒绝：{type(exc).__name__}") from None
        self._counters["reserved"] += 1
        pre_send_check = self._pre_send_check(reservation)
        started = time.monotonic()
        try:
            if self._inner_accepts_pre_send_check:
                # 生产客户端在“client 已创建 / 锁等待 await 完成之后、真实 POST 之前”
                # 调用该回调；拒绝时没有任何 HTTP 发出。
                output = await self._inner.complete(
                    request, timeout_seconds=timeout_seconds, pre_send_check=pre_send_check
                )
            else:
                # 旧替身不支持发送边界钩子：在调用 inner 之前复核（仍先于任何 POST）。
                pre_send_check()
                output = await self._inner.complete(request, timeout_seconds=timeout_seconds)
        except asyncio.CancelledError:
            self._settle(
                reservation, status="unknown", error_code="CHAT_CANCELLED", started=started
            )
            raise
        except ModelTimeout:
            self._settle(reservation, status="timeout", error_code="CHAT_TIMEOUT", started=started)
            raise
        except ModelError as exc:
            self._settle(
                reservation,
                status="failed",
                error_code=str(getattr(exc, "code", None) or type(exc).__name__),
                started=started,
            )
            raise
        except Exception:  # noqa: BLE001 - 未预期错误也不清零占用
            self._settle(reservation, status="unknown", error_code="CHAT_UNEXPECTED", started=started)
            raise
        except BaseException as exc:  # noqa: BLE001 - 中断/退出前先留最小归因事件，再原样传播
            from .interrupt_trace import record_base_exception

            record_base_exception(
                exc,
                component="providers.BudgetedModelGateway",
                stage=self._gate.stage,
                reservation_id=getattr(reservation, "reservation_id", None),
            )
            raise
        usage = dict(output.usage or {})
        request_id = safe_request_id(output.provider_request_id)
        if self._settlement_policy is not None:
            # J2 受控版本化结算：仅当实际响应成功（客户端已校验 finish_reason=stop 且
            # content 可解析）才构造证据；缺 cache 拆分/超 cap/矛盾由 J1 拒绝并全额保留，
            # 异常原样向调用方传播（不 catch、不重试、不记成功）。
            evidence_usage: Any = (
                output.raw_usage
                if isinstance(getattr(output, "raw_usage", None), Mapping)
                else usage
            )
            evidence = build_chat_evidence(
                self._settlement_policy,
                request_sha256=request_sha,
                usage=evidence_usage,
                http_status=200,
                streamed=False,
                finish_reason="stop",
                content_complete=True,
                content_parse_ok=True,
            )
            self._budget.settle_usage(
                reservation,
                evidence=evidence,
                request_id=request_id,
                elapsed_seconds=time.monotonic() - started,
            )
            return output
        if int(usage.get("prompt_tokens") or 0) > input_tokens:
            # 回归闸门：服务端实际 prompt_tokens 超过本轮预留采用的官方 context 上限，
            # 说明该上界不成立；保留占用并标 unknown，绝不当成功结算。
            self._settle(
                reservation,
                status="unknown",
                usage=usage,
                request_id=output.provider_request_id,
                error_code="CHAT_USAGE_OVER_TOKEN_BOUND",
                started=started,
            )
            raise ModelUnavailable("chat usage.prompt_tokens 超过本轮预留上界，停止且标未证明")
        estimated = self._pricing.estimate_cny(usage)
        self._settle(
            reservation,
            status="succeeded",
            usage=usage,
            estimated=estimated,
            request_id=request_id,
            started=started,
        )
        return output

    async def aclose(self) -> None:
        closer = getattr(self._inner, "aclose", None)
        if closer is not None:
            await closer()

    # ---------------------------------------------------------------- 内部

    def _pre_send_check(self, reservation: Any) -> Callable[[], None]:
        """构造“发送前最后一次复核”回调；只读账本、不清账、不重新预留。"""
        recheck = getattr(self._budget, "recheck_reservation", None)

        def check() -> None:
            if recheck is None:
                # 既有测试/替身传入的自定义账本没有发送前复核能力。
                self._counters["send_attempts"] += 1
                return
            try:
                recheck(reservation)
            except BudgetLedgerInvalid as exc:
                self._counters["pre_send_refused"] += 1
                raise ModelPostSendDenied(f"发送前授权/预算复核拒绝：{exc}") from None
            except Exception as exc:  # noqa: BLE001 - 任何复核异常都必须默认拒绝发送
                self._counters["pre_send_refused"] += 1
                raise ModelPostSendDenied(
                    f"发送前授权/预算复核异常：{type(exc).__name__}"
                ) from None
            # 只有复核通过、即将调用 client.post 的尝试才计入 send_attempts。
            self._counters["send_attempts"] += 1

        return check

    def _settle(
        self,
        reservation: Any,
        *,
        status: str,
        error_code: str | None = None,
        usage: dict[str, int] | None = None,
        estimated: float = 0.0,
        request_id: str | None = None,
        started: float,
    ) -> None:
        try:
            self._budget.settle(
                reservation,
                status=status,
                usage=usage,
                estimated_list_price_cny=estimated,
                request_id=safe_request_id(request_id),
                error_code=None if error_code is None else safe_error_code(error_code),
                elapsed_seconds=time.monotonic() - started,
            )
        except BudgetLedgerInvalid:
            # 结算写失败不改变“预留已占用”的事实；只记录，不把占用清零。
            self._counters["settle_errors"] += 1
            return
        bucket = self._counters["results"]
        bucket[status] = bucket.get(status, 0) + 1


__all__ = ["BudgetedModelGateway", "ChatPricing", "ModelPostSendDenied"]
