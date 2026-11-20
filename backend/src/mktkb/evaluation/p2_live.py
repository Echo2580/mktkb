"""P2-T206-LIVE：真实 live 入口（门 + 适配器 + usage 证据 + 成本中心/请求计数接线）。

为什么单独一个模块（T206 准备发现 G1–G6 缺口）：
- T203 适配器恒为 Mock；T201 的 P2Gate 在 backend/src 里没有生产调用点。本模块只做**接线**，
  不重写产品逻辑、不改业务 API/schema、不复制预算规则：真实发送仍走产品 HTTP 入口
  （ProductEvalAdapter），资金事实仍只有 P2Gate + 共享账本。

四件事必须同时成立（缺一项都在**发送之前**拒绝）：

1. **显式 live**：适配器 mode="live" 才构造真实 provider/真实 OCR 传输；默认仍是 Mock。
2. **真实门**：P2Gate.open 从**固定路径**读 GO/预算/共享账本，且 authorization.production_ready
   必须为 True（缺 GO、预算未修订、缺 MKTKB_PROJECT_TOTAL_LIMIT_CNY 一律拒绝）。
3. **逐次尝试预留**：产品一次问答内部会先 embedding、再 rerank、再 chat（证据为空时还会先做
   一次 query_expansion）；OCR 在灌库时发生。除 runner 的逐轮 answer 预留外，其余**每次底层
   发送**都用 P2Gate.begin_attempt 单独预留（成本中心来自计划项、计数进账本 reservation_count），
   成功后用真实 usage 结算；计划项配额也按真实 HTTP 请求/批扣（T206-LIVE-R1/F2）。
4. **usage 缺失即停**：chat 的 usage 来自 DeepSeekClient 的响应（官方命名字段），
   embedding/rerank 走既有 build_total_evidence（只认 total_tokens）。拿不到 usage 时
   **不伪造金额**：runner 以 usage_evidence_missing 停住并保留保守占用。

零真实调用：本模块自己不建连接；测试用 httpx.MockTransport + 仓库既有 socket 闸门证明出站 0。
凭据只从**进程环境**读取（不读 .env），异常文本只给变量名/稳定码，不回显值。
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .p2_authorization import P2Gate, P2GateError, P2RequestTicket, P2SendRefused
from .p2_contracts import (
    CHAT_MODEL,
    OCR_TABLE_MODEL,
    OCR_TEXT_MODEL,
    P2RequestItem,
    P2RunPlan,
)
from ..rag.budget import Reservation
from ..rag.controlled_usage import build_chat_evidence
from ..rag.errors import BudgetLedgerInvalid
from ..rag.settlement_policy import KIND_CHAT, UsageEvidence, build_policy

__all__ = [
    "LIVE_CORE_OPERATIONS",
    "MODE_LIVE",
    "MODE_MOCK",
    "NO_PAID_ATTEMPT",
    "REQUIRED_ENV_VARS",
    "AttemptBudget",
    "AttemptReceipt",
    "GateAttemptLedger",
    "GatedChatGateway",
    "GatedEmbeddingProvider",
    "GatedOcrGateway",
    "GatedRerankProvider",
    "LiveEnv",
    "LiveWiring",
    "P2LiveConfigError",
    "P2LiveRefused",
    "PlanIndex",
    "RequestCeiling",
    "TurnContext",
    "build_live_adapter",
    "chat_output_validity",
    "chat_usage_evidence",
    "load_live_env",
    "make_settle_evidence",
    "open_live_gate",
    "provider_single_request_bounds",
    "required_live_operations",
    "resolve_request_ceiling",
    "run_live_p2",
]

MODE_MOCK = "mock"
MODE_LIVE = "live"

#: runner 的 settle_evidence 返回值：本轮**没有任何付费发送**（合法拒答/澄清/未找到）。
#: 它不是"缺 usage"：缺 usage 一律返回 None 并按 fail-closed 处理。
NO_PAID_ATTEMPT = "no_paid_attempt"

#: chat 输出"完整结束"的唯一合法完成态（与 providers/deepseek.py 的解析条件同值）。
CHAT_FINISH_STOP = "stop"

#: 真实发送需要的环境变量**名字**（值不进任何产物/日志）。
ENV_CHAT_API_KEY = "MKTKB_MODEL_API_KEY"
ENV_CHAT_BASE_URL = "MKTKB_MODEL_BASE_URL"
ENV_CHAT_MODEL = "MKTKB_MODEL_NAME"
ENV_DASHSCOPE_API_KEY = "DASHSCOPE_API_KEY"
ENV_DASHSCOPE_BASE_URL = "DASHSCOPE_BASE_URL"
ENV_OCR_SECRET_ID = "MKTKB_OCR_SECRET_ID"
ENV_OCR_SECRET_KEY = "MKTKB_OCR_SECRET_KEY"
ENV_OCR_REGION = "MKTKB_OCR_REGION"
ENV_OCR_DISABLED = "MKTKB_OCR_DISABLED"

REQUIRED_ENV_VARS: tuple[str, ...] = (
    ENV_CHAT_API_KEY,
    ENV_CHAT_BASE_URL,
    ENV_CHAT_MODEL,
    ENV_DASHSCOPE_API_KEY,
    ENV_OCR_SECRET_ID,
    ENV_OCR_SECRET_KEY,
)

_DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com"
_DEFAULT_OCR_REGION = "ap-guangzhou"


class P2LiveConfigError(ValueError):
    """live 配置/授权不成立：code 稳定可机读，文本只含码与变量名。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class P2LiveRefused(RuntimeError):
    """一次底层尝试在**发送之前**被拒（无计划项/配额用尽/门拒绝）：不发送、不记成功。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


# --------------------------------------------------------------------------- #
# 1. 进程环境（只读，不读 .env）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LiveEnv:
    """真实供应商配置（凭据只在内存；repr 不含任何值）。"""

    chat_api_key: str
    chat_base_url: str
    chat_model: str
    dashscope_api_key: str
    dashscope_base_url: str = _DEFAULT_DASHSCOPE_BASE_URL
    ocr_secret_id: str = ""
    ocr_secret_key: str = ""
    ocr_region: str = _DEFAULT_OCR_REGION
    ocr_enabled: bool = True

    def __repr__(self) -> str:  # pragma: no cover - 只在调试时用
        return (
            f"LiveEnv(chat_model={self.chat_model!r}, ocr_enabled={self.ocr_enabled!r}, "
            "credentials=<redacted>)"
        )

    def safe_as_dict(self) -> dict[str, Any]:
        def host(url: str) -> str:
            return url.split("//")[-1].split("/")[0]

        return {
            "chat_model": self.chat_model,
            "chat_host": host(self.chat_base_url),
            "dashscope_host": host(self.dashscope_base_url),
            "ocr_region": self.ocr_region,
            "ocr_enabled": bool(self.ocr_enabled),
        }


def _env_text(environ: Mapping[str, str], name: str) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise P2LiveConfigError("live_env_missing", f"缺少 {name}")
    return value


def load_live_env(
    environ: Mapping[str, str] | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> LiveEnv:
    """从**进程环境**收敛 live 配置；任何必填项缺失都在建应用/发送之前拒绝。

    overrides 只供测试注入（仍走同一套校验）；生产路径只用 os.environ。
    """
    env = os.environ if environ is None else environ
    pinned = dict(overrides or {})

    if str(env.get(ENV_OCR_DISABLED) or "").strip().lower() in {"1", "true", "yes"}:
        raise P2LiveConfigError("live_ocr_disabled", f"{ENV_OCR_DISABLED}=1 时不能执行真实 OCR")

    chat_api_key = pinned.get("chat_api_key") or _env_text(env, ENV_CHAT_API_KEY)
    chat_base_url = pinned.get("chat_base_url") or _env_text(env, ENV_CHAT_BASE_URL)
    chat_model = pinned.get("chat_model") or _env_text(env, ENV_CHAT_MODEL)
    dashscope_key = pinned.get("dashscope_api_key") or _env_text(env, ENV_DASHSCOPE_API_KEY)
    dashscope_base_url = (
        pinned.get("dashscope_base_url")
        or str(env.get(ENV_DASHSCOPE_BASE_URL) or "").strip()
        or _DEFAULT_DASHSCOPE_BASE_URL
    )
    ocr_secret_id = pinned.get("ocr_secret_id") or _env_text(env, ENV_OCR_SECRET_ID)
    ocr_secret_key = pinned.get("ocr_secret_key") or _env_text(env, ENV_OCR_SECRET_KEY)
    ocr_region = (
        pinned.get("ocr_region")
        or str(env.get(ENV_OCR_REGION) or "").strip()
        or _DEFAULT_OCR_REGION
    )
    if not chat_base_url.startswith(("http://", "https://")):
        raise P2LiveConfigError("live_env_invalid", f"{ENV_CHAT_BASE_URL} 必须是 http(s) 地址")
    if not dashscope_base_url.startswith(("http://", "https://")):
        raise P2LiveConfigError("live_env_invalid", f"{ENV_DASHSCOPE_BASE_URL} 必须是 http(s) 地址")
    if chat_model != CHAT_MODEL:
        raise P2LiveConfigError(
            "live_chat_model_not_authorized", f"chat 模型必须是已核模型 {CHAT_MODEL}"
        )
    return LiveEnv(
        chat_api_key=chat_api_key,
        chat_base_url=chat_base_url,
        chat_model=chat_model,
        dashscope_api_key=dashscope_key,
        dashscope_base_url=dashscope_base_url.rstrip("/"),
        ocr_secret_id=ocr_secret_id,
        ocr_secret_key=ocr_secret_key,
        ocr_region=ocr_region,
        ocr_enabled=True,
    )


# --------------------------------------------------------------------------- #
# 2. 计划项解析与尝试配额
# --------------------------------------------------------------------------- #


class PlanIndex:
    """把计划项按 (operation, case_id, turn) 建成只读索引；查不到一律 fail closed。"""

    def __init__(self, plan: P2RunPlan) -> None:
        self.plan = plan
        self._by_turn: dict[tuple[str, str, int], P2RequestItem] = {}
        self._ocr: list[P2RequestItem] = []
        self._index_embedding: list[P2RequestItem] = []
        self._answers: dict[tuple[str, int], P2RequestItem] = {}
        for item in plan.items:
            if item.operation == "ocr":
                self._ocr.append(item)
            if item.operation == "index_embedding":
                self._index_embedding.append(item)
            if item.operation == "answer":
                self._answers[(item.case_id, int(item.turn))] = item
            self._by_turn[(item.operation, item.case_id, int(item.turn))] = item

    def answer_item(self, case_id: str, turn: int) -> P2RequestItem:
        item = self._answers.get((str(case_id), int(turn)))
        if item is None:
            raise P2LiveRefused("attempt_item_unknown", f"计划没有 answer 项 {case_id}:t{turn}")
        return item

    def index_embedding_item(self) -> P2RequestItem:
        if len(self._index_embedding) != 1:
            raise P2LiveRefused(
                "attempt_item_ambiguous",
                f"计划必须恰好有 1 个 index_embedding 项，实际 {len(self._index_embedding)}",
            )
        return self._index_embedding[0]

    def turn_item(self, operation: str, case_id: str, turn: int) -> P2RequestItem:
        item = self._by_turn.get((str(operation), str(case_id), int(turn)))
        if item is None:
            raise P2LiveRefused(
                "attempt_item_unknown", f"计划没有 {operation} 项 {case_id}:t{turn}"
            )
        return item

    def next_ocr_item(self, consumed: int) -> P2RequestItem:
        """按计划顺序取"下一条"OCR 项（每页一次调用）；用尽即拒绝，不猜页号。"""
        if consumed >= len(self._ocr):
            raise P2LiveRefused(
                "attempt_item_exhausted", f"计划只有 {len(self._ocr)} 个 OCR 项，已全部使用"
            )
        return self._ocr[consumed]

    @property
    def ocr_count(self) -> int:
        return len(self._ocr)

    @property
    def answer_items(self) -> Mapping[tuple[str, int], P2RequestItem]:
        return dict(self._answers)


class AttemptBudget:
    """计划项级配额：每个 item 最多 item.requests 次底层尝试（G6）。

    计划的 requests 是**请求上界**而不是期望值；超过上界说明计划低估了产品调用数，
    必须在**发送之前**停住（不偷偷多发一次）。
    """

    def __init__(self, plan: P2RunPlan) -> None:
        self._allowed = {item.item_id: int(item.requests) for item in plan.items}
        self._used: dict[str, int] = {item_id: 0 for item_id in self._allowed}

    def take(self, item_id: str) -> None:
        allowed = self._allowed.get(item_id)
        if allowed is None:
            raise P2LiveRefused("attempt_item_unknown", f"计划没有 {item_id}")
        used = self._used.get(item_id, 0)
        if used >= allowed:
            raise P2LiveRefused("attempt_quota_exhausted", f"{item_id} 已用 {used}/{allowed} 次")
        self._used[item_id] = used + 1

    def used(self, item_id: str) -> int:
        return int(self._used.get(item_id, 0))

    def as_dict(self) -> dict[str, int]:
        return {item_id: int(count) for item_id, count in self._used.items() if count}


# --------------------------------------------------------------------------- #
# 2b. 单请求上限：必须覆盖**所有已接 provider** 的单次请求预留上界
# --------------------------------------------------------------------------- #

#: 金额比较容差（与 p2_authorization 的 _EPS 同量级）：只吸收浮点尾差，不放宽任何上界。
_MONEY_EPS = 1e-12


def _chat_single_request_reserve_cny() -> float:
    """chat 单次请求的预留上界：冻结 token cap × 官方费率（与 J1 结算同一 policy）。

    产品 live 的 chat 由 DeepSeekClient 直接发送，没有 provider 侧的自检上限；它的一次
    预留上界由 P2Gate 按计划项的钱数决定。这里仍把「provider 口径的上界」算出来参与
    effective 推导：GO 授权的单请求上界一旦低于它，P2Gate.begin_attempt 会在任何发送
    之前以预算身份拒绝，而不是让 chat 真的发出去之后才发现超限。
    """
    policy = build_policy(KIND_CHAT, model=CHAT_MODEL)
    amount = (
        Decimal(int(policy.prompt_tokens_cap)) * policy.input_price_per_million_cny
        + Decimal(int(policy.completion_tokens_cap)) * policy.output_price_per_million_cny
    ) / Decimal(1_000_000)
    return float(amount.quantize(Decimal("0.00000001"), rounding=ROUND_CEILING))


def provider_single_request_bounds(rag_config: Any) -> dict[str, float]:
    """每个**已接 provider** 单次请求的预留上界（元，按 kind 命名）。

    embedding/rerank 直接复用 P1 live 已有的权威公式（evaluation/live.py 的
    embedding_reserve_cny = 官方单请求 81,920 token × 费率、rerank_reserve_cny =
    请求 token 上限 × 费率），与 rag/providers.py 里 provider 发送前那道自检**同源同式**；
    本函数不另写一份常量，避免两处漂移。
    """
    from .live import embedding_reserve_cny, rerank_reserve_cny

    return {
        "embedding": float(embedding_reserve_cny(rag_config)),
        "rerank": float(rerank_reserve_cny(rag_config)),
        "chat": _chat_single_request_reserve_cny(),
    }


@dataclass(frozen=True)
class RequestCeiling:
    """一次 live 装配的单请求上限推导结果（只含金额，不含凭据）。"""

    plan_peak_cny: float
    provider_bounds_cny: Mapping[str, float]
    authorization_cny: float
    effective_cny: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_peak_cny": round(float(self.plan_peak_cny), 8),
            "provider_single_request_cny": {
                str(name): round(float(value), 8)
                for name, value in self.provider_bounds_cny.items()
            },
            "authorization_max_request_cny": round(float(self.authorization_cny), 8),
            "effective_max_request_cny": round(float(self.effective_cny), 8),
        }


def resolve_request_ceiling(
    rag_config: Any,
    *,
    plan_peak_cny: float,
    authorization_cny: float,
) -> RequestCeiling:
    """推导 provider 预检用的单请求上限；不足即**发送前** fail closed。

    T207-FIX-LIVECAP（R4PREP F-1）：产品过去把 RagConfig.max_request_cny 直接设成
    plan.reserve_peak_cny（串行单次峰值）。这对含 OCR 的计划成立（一页 0.5 高于所有
    provider 的单次预留），但对 page_count=0 的计划不成立：峰值只剩 chat 的 0.018688，
    而 embedding provider 每次 POST 前固定按官方 81,920 token 预留 0.04096
    （rag/providers.py:316-321）。0.04096 > 0.018688 ⇒ 每次 embed 都在发送前被拒，
    灌库降级为 degraded=embedding_error（不硬停），产出「看似通过、向量层全灭」的证据。

    规则（不写魔法数）：

    - effective = max(计划峰值, 每个已接 provider 的单次预留上界)；
    - effective 不得超过 GO 授权上限（authorization.max_request_cny）；
    - effective 若小于任一 provider 的单次预留（或小于计划峰值）一律拒绝，稳定码
      live_request_ceiling_insufficient，且发生在应用构建/provider 构造之前。

    含 OCR 的公开计划若峰值 0.5 高于全部 provider 上界，effective 逐字等于计划峰值，
    行为与修正前完全一致。
    """
    plan_peak = float(plan_peak_cny)
    authorization = float(authorization_cny)
    bounds = provider_single_request_bounds(rag_config)
    required = max([plan_peak, *bounds.values()])
    effective = min(required, authorization)
    shortfalls = {
        str(name): float(value)
        for name, value in bounds.items()
        if effective + _MONEY_EPS < float(value)
    }
    if effective + _MONEY_EPS < plan_peak:
        shortfalls["plan_peak"] = plan_peak
    if shortfalls:
        worst_name, worst = max(shortfalls.items(), key=lambda pair: pair[1])
        raise P2LiveConfigError(
            "live_request_ceiling_insufficient",
            f"单请求上限 {effective:.8f} 元覆盖不了 {worst_name} 的单次预留 "
            f"{worst:.8f} 元（GO 授权上限 {authorization:.8f}，计划串行峰值 "
            f"{plan_peak:.8f}）：拒绝装配，不发送、不降级",
        )
    return RequestCeiling(
        plan_peak_cny=plan_peak,
        provider_bounds_cny=bounds,
        authorization_cny=authorization,
        effective_cny=effective,
    )


# --------------------------------------------------------------------------- #
# 3. 从属尝试账本：真实 provider 的 budget 协议 -> P2Gate.begin_attempt
# --------------------------------------------------------------------------- #


@dataclass
class AttemptReceipt:
    """一次底层发送的真实回执（G4/G5/G6 的逐次证据；不含凭据）。"""

    operation: str
    item_id: str
    case_id: str
    turn: int
    page: int
    cost_center: str
    kind: str
    provider: str
    model: str
    phase: str
    status: str
    reservation_id: str | None
    request_id: str | None
    bound_cny: float
    charged_cny: float
    usage: dict[str, int] = field(default_factory=dict)
    provider_request_sha256: str | None = None
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "item_id": self.item_id,
            "case_id": self.case_id,
            "turn": int(self.turn),
            "page": int(self.page),
            "cost_center": self.cost_center,
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "phase": self.phase,
            "status": self.status,
            "reservation_id": self.reservation_id,
            "request_id": self.request_id,
            "bound_cny": round(float(self.bound_cny), 8),
            "charged_cny": round(float(self.charged_cny), 8),
            "usage": {str(key): int(value) for key, value in self.usage.items()},
            "provider_request_sha256": self.provider_request_sha256,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class _Decision:
    """settle_usage 的最小返回形状（provider 只读 charge_cny）。"""

    charge_cny: float
    accepted: bool = True
    reason: str | None = None


class GateAttemptLedger:
    """把真实 provider 的 BudgetLedger 协议**桥接**到 P2Gate 的从属尝试。

    真实 provider（Bailian embedding/rerank）在 reserve -> recheck -> POST -> settle_usage
    的固定位置调用账本；本类把同一组调用映射成
    begin_attempt -> confirm_before_send -> (真实 POST) -> settle_success/settle_failure，
    因此**每次底层发送**都有：计划项身份、成本中心、账本 reservation、usage 证据。

    刻意不做的事：
    - 不信任 provider 自报的 max_cny：预留额固定为该计划项 bound_cny（准入上界）；
    - 不构造第二个价目/结算规则：金额全部由 P2Gate/账本按预留时固化的 policy 重算；
    - 不吞拒绝：门拒绝一律转成 BudgetLedgerInvalid（provider 会在 POST 之前停）。
    """

    def __init__(
        self,
        gate: P2Gate,
        plan: P2RunPlan,
        *,
        on_receipt: Callable[[AttemptReceipt], None] | None = None,
        attempt_budget: AttemptBudget | None = None,
    ) -> None:
        self._gate = gate
        self._plan = plan
        self._on_receipt = on_receipt
        self._attempt_budget = attempt_budget
        self._current: P2RequestItem | None = None
        self._tickets: dict[str, P2RequestTicket] = {}
        self._settled_by_gate: set[str] = set()
        self._counts: dict[str, int] = {}

    # -- 观测面 ----------------------------------------------------------
    def attempts(self, *operations: str) -> int:
        """真实 POST 次数（= 本账本为该操作开出的 reservation 数）。"""
        return sum(int(self._counts.get(str(op), 0)) for op in operations)

    @property
    def attempt_counts(self) -> dict[str, int]:
        return {str(op): int(count) for op, count in self._counts.items() if count}

    # -- 绑定当前尝试的计划项 -------------------------------------------
    def bind(self, item: P2RequestItem) -> None:
        self._current = item

    def unbind(self) -> None:
        self._current = None

    def _item(self) -> P2RequestItem:
        if self._current is None:
            raise BudgetLedgerInvalid("S3 接线错误：没有绑定计划项，禁止预留")
        return self._current

    # -- BudgetLedger 协议 ---------------------------------------------
    def reserve(
        self,
        *,
        kind: str,
        provider: str,
        model: str,
        max_cny: float,
        request_sha256: str,
        settlement_policy: Any = None,
        metadata: Mapping[str, Any] | None = None,
        stage_limit_cny: float | None = None,
        max_requests: int | None = None,
        cost_center: str | None = None,
    ) -> Reservation:
        item = self._item()
        if kind != item.price_profile.kind:
            raise BudgetLedgerInvalid("S3 接线错误：provider kind 与计划项不一致")
        if provider != item.price_profile.provider or model != item.price_profile.model:
            raise BudgetLedgerInvalid("S3 接线错误：provider/model 与计划项不一致")
        if float(max_cny) <= 0:
            raise BudgetLedgerInvalid("provider 预留金额必须为正")
        # F2：计划项配额按**真实 HTTP 请求/批**计数 —— reserve 在这里就是一次底层 POST 的前一刻
        # （embedding 一个 embed() 可能拆成多批，各自 reserve 一次；rerank 恒为 1 次）。
        # 配额用尽时**不**开 reservation（发送前停住，不偷偷多发）。
        if self._attempt_budget is not None:
            try:
                self._attempt_budget.take(item.item_id)
            except P2LiveRefused as exc:
                raise BudgetLedgerInvalid(f"P2 计划项配额拒绝：{exc.code} {exc.detail}".strip()) from None
        try:
            ticket = self._gate.begin_attempt(item.item_id)
        except P2GateError as exc:
            raise BudgetLedgerInvalid(f"P2 从属尝试预留拒绝：{exc.reason}") from None
        self._counts[item.operation] = self._counts.get(item.operation, 0) + 1
        self._tickets[ticket.reservation_id] = ticket
        self._emit(
            ticket,
            phase="reserve",
            status="reserved",
            charged=0.0,
            provider_request_sha256=str(request_sha256)[:64],
        )
        return ticket.reservation

    def recheck_reservation(self, reservation: Reservation) -> None:
        ticket = self._tickets.get(reservation.reservation_id)
        if ticket is None:
            raise BudgetLedgerInvalid("找不到本次尝试的预留记录，禁发")
        try:
            self._gate.confirm_before_send(ticket)
        except P2SendRefused as exc:
            # 门已在预留后/发送前把该笔保守结算并停止；这里只需让 provider 在 POST 前停住。
            self._settled_by_gate.add(ticket.reservation_id)
            self._emit(
                ticket,
                phase="pre_send",
                status="refused_before_send",
                charged=float(ticket.bound_cny),
                error_code=f"pre_send_refused:{exc.reason}",
            )
            raise BudgetLedgerInvalid(f"P2 发送前复核拒绝：{exc.reason}") from None

    def settle(
        self,
        reservation: Reservation,
        *,
        status: str,
        usage: Mapping[str, int] | None = None,
        estimated_list_price_cny: float | None = None,
        provider_billed_cny: float | None = None,
        http_status: int | None = None,
        request_id: str | None = None,
        error_code: str | None = None,
        elapsed_seconds: float | None = None,
        dimensions: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        ticket = self._tickets.get(reservation.reservation_id)
        if ticket is None:
            raise BudgetLedgerInvalid("找不到本次尝试的预留记录，拒绝结算")
        if reservation.reservation_id in self._settled_by_gate:
            return {"reservation_id": reservation.reservation_id, "settled_by_gate": True}
        if status == "succeeded":
            raise BudgetLedgerInvalid("成功结算必须带 UsageEvidence（settle_usage）")
        self._tickets.pop(ticket.reservation_id, None)
        clean_status = "timeout" if status == "timeout" else ("unknown" if status == "unknown" else "failed")
        try:
            self._gate.settle_failure(
                ticket,
                error_code=str(error_code or f"PROVIDER_{status.upper()}"),
                status=clean_status,
                http_status=http_status,
                elapsed_seconds=elapsed_seconds,
            )
        finally:
            self._emit(
                ticket,
                phase="settle",
                status=clean_status,
                charged=float(ticket.bound_cny),
                usage=usage,
                error_code=error_code,
            )
        return {"reservation_id": reservation.reservation_id, "status": clean_status}

    def settle_usage(
        self,
        reservation: Reservation,
        *,
        evidence: UsageEvidence,
        request_id: str | None = None,
        elapsed_seconds: float | None = None,
        dimensions: tuple[int, ...] | None = None,
    ) -> _Decision:
        ticket = self._tickets.get(reservation.reservation_id)
        if ticket is None:
            raise BudgetLedgerInvalid("找不到本次尝试的预留记录，拒绝结算")
        if not isinstance(evidence, UsageEvidence):
            raise BudgetLedgerInvalid("settle_usage 需要 UsageEvidence")
        # 计划项是资金身份：证据必须绑定到**预留时的** request_sha256（provider 的 payload
        # 摘要另存进回执，供审计），否则账本会以 binding_request_sha256_mismatch 拒绝。
        rebound = dataclasses.replace(evidence, request_sha256=ticket.reservation.request_sha256)
        self._tickets.pop(ticket.reservation_id, None)
        try:
            charge = float(
                self._gate.settle_success(ticket, evidence=rebound, elapsed_seconds=elapsed_seconds)
            )
        finally:
            self._emit(
                ticket,
                phase="settle",
                status="succeeded",
                charged=charge,
                usage=evidence.usage if isinstance(evidence.usage, Mapping) else {},
            )
        return _Decision(charge_cny=charge)

    # -- 同步尝试（OCR / query_expansion：不走 provider 的 BudgetLedger 协议）--
    def begin_sync_attempt(self, item: P2RequestItem) -> P2RequestTicket:
        # 与 provider 协议路径同一口径：**每次真实尝试**先扣一次计划项配额（发送前停）。
        if self._attempt_budget is not None:
            self._attempt_budget.take(item.item_id)
        try:
            ticket = self._gate.begin_attempt(item.item_id)
        except P2GateError as exc:
            raise P2LiveRefused(f"attempt_gate:{exc.reason}", str(exc.detail)) from None
        try:
            self._gate.confirm_before_send(ticket)
        except P2SendRefused as exc:
            self._settled_by_gate.add(ticket.reservation_id)
            self._emit(
                ticket,
                phase="pre_send",
                status="refused_before_send",
                charged=float(ticket.bound_cny),
                error_code=f"pre_send_refused:{exc.reason}",
            )
            raise P2LiveRefused(f"attempt_pre_send_refused:{exc.reason}", str(exc.detail)) from None
        self._tickets[ticket.reservation_id] = ticket
        self._emit(ticket, phase="reserve", status="reserved", charged=0.0)
        return ticket

    def settle_sync_success(
        self,
        ticket: P2RequestTicket,
        *,
        amount_cny: float,
        usage: Mapping[str, Any] | None = None,
    ) -> float:
        self._tickets.pop(ticket.reservation_id, None)
        try:
            charge = float(
                self._gate.settle_success(ticket, estimated_cny=float(amount_cny), usage=dict(usage or {}))
            )
        finally:
            self._emit(
                ticket,
                phase="settle",
                status="succeeded",
                charged=charge,
                usage=usage,
            )
        return charge

    def settle_sync_failure(self, ticket: P2RequestTicket, *, error_code: str) -> None:
        self._tickets.pop(ticket.reservation_id, None)
        try:
            self._gate.settle_failure(ticket, error_code=str(error_code))
        finally:
            self._emit(
                ticket,
                phase="settle",
                status="failed",
                charged=float(ticket.bound_cny),
                error_code=error_code,
            )

    # -- 回执 ------------------------------------------------------------
    def _emit(
        self,
        ticket: P2RequestTicket,
        *,
        phase: str,
        status: str,
        charged: float,
        usage: Mapping[str, Any] | None = None,
        provider_request_sha256: str | None = None,
        error_code: str | None = None,
    ) -> None:
        if self._on_receipt is None:
            return
        clean_usage = {
            str(key): int(value)
            for key, value in dict(usage or {}).items()
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
        self._on_receipt(
            AttemptReceipt(
                operation=ticket.operation,
                item_id=ticket.item_id,
                case_id=ticket.case_id,
                turn=int(ticket.turn),
                page=int(ticket.page),
                cost_center=ticket.cost_center,
                kind=ticket.kind,
                provider=ticket.provider,
                model=ticket.model,
                phase=phase,
                status=status,
                reservation_id=ticket.reservation_id,
                request_id=ticket.request_id,
                bound_cny=float(ticket.bound_cny),
                charged_cny=float(charged),
                usage=clean_usage,
                provider_request_sha256=provider_request_sha256,
                error_code=error_code,
            )
        )


# --------------------------------------------------------------------------- #
# 4. 真实 provider 的门控包装（每次底层发送 = 一次预留）
# --------------------------------------------------------------------------- #


@dataclass
class TurnContext:
    """当前产品回合的 live 上下文：由适配器 ask_turn 进入/退出，包装层只读。"""

    request_id: str | None = None
    case_id: str | None = None
    turn: int | None = None
    #: **answer** 付费 chat 次数（query_expansion 现在单独走 expand-* 计划项，不计在这里）。
    answer_chat_calls: int = 0
    expansion_calls: int = 0
    chat_usage: dict[str, Any] | None = None
    chat_request_id: str | None = None
    #: T207-FIX-B/C：本轮 answer chat 输出的三段有效性判据（由 ``chat_output_validity`` 给）。
    #: 缺省全为"无效"：没有真实输出就不许声明 output_valid。
    chat_finish_reason: Any = None
    chat_content_present: bool = False
    chat_content_parsed: bool = False
    #: 本轮 answer chat 请求里**实际交给模型的检索候选**（source_id，即产品来源单元 id）。
    #: 零额外调用：直接从产品自己构造的 CompletionInput.evidence 取，不重放、不付费。
    retrieved_ids: tuple[str, ...] = ()
    #: 上一轮结束后的 usage/候选快照：runner 在 ask_turn **返回之后**才结算，上下文此时已退出，
    #: 若清空就会把"真的调用过"误判成"缺 usage"。只保留最近一轮（串行，不会混轮）。
    last_usage: dict[str, Any] | None = None
    last_retrieved_ids: tuple[str, ...] = ()

    def enter(self, *, request_id: str, case_id: str | None, turn: int | None) -> None:
        self.request_id = str(request_id)
        self.case_id = case_id
        self.turn = turn
        self.answer_chat_calls = 0
        self.expansion_calls = 0
        self.chat_usage = None
        self.chat_request_id = None
        self.chat_finish_reason = None
        self.chat_content_present = False
        self.chat_content_parsed = False
        self.retrieved_ids = ()
        self.last_usage = None
        self.last_retrieved_ids = ()

    def leave(self) -> None:
        if self.request_id is not None:
            self.last_usage = self.as_usage()
            self.last_retrieved_ids = tuple(self.retrieved_ids)
        self.request_id = None
        self.case_id = None
        self.turn = None

    def retrieved_candidates(self) -> tuple[str, ...]:
        """本轮（或刚结束那轮）answer chat 拿到过的候选 unit id；没有就是空。"""
        if self.request_id is not None:
            return tuple(self.retrieved_ids)
        return tuple(self.last_retrieved_ids)

    def case_turn(self) -> tuple[str, int]:
        if self.case_id is None or self.turn is None:
            raise P2LiveRefused(
                "attempt_outside_turn",
                "本产品回合没有对应的计划项（live 只允许在受预算的回合内发送）",
            )
        return str(self.case_id), int(self.turn)

    def as_usage(self) -> dict[str, Any] | None:
        if self.request_id is None:
            return self.last_usage
        return {
            "case_id": self.case_id,
            "turn": self.turn,
            # runner 的 settle_evidence 只认 answer chat：query_expansion 已单独结算。
            "chat_calls": int(self.answer_chat_calls),
            "expansion_calls": int(self.expansion_calls),
            "usage": dict(self.chat_usage or {}),
            "raw_usage": dict(self.chat_usage or {}),
            "provider_request_id": self.chat_request_id,
            # T207-FIX-B/C：结算有效性判据随 usage 一起交给 settle_evidence（同一轮、同一快照）。
            "finish_reason": self.chat_finish_reason,
            "content_present": bool(self.chat_content_present),
            "content_parsed": bool(self.chat_content_parsed),
        }


class GatedEmbeddingProvider:
    """真实 embedding provider 的门控包装：purpose 决定计划项（index/query）。"""

    def __init__(self, inner: Any, *, wiring: "LiveWiring") -> None:
        self._inner = inner
        self._wiring = wiring
        self.provider = str(getattr(inner, "provider", "bailian"))
        self.model = str(getattr(inner, "model", ""))
        self.dimensions = int(getattr(inner, "dimensions", 0) or 0)

    @property
    def calls(self) -> int:
        return int(self._wiring.embedding_calls)

    def embed(self, texts: Sequence[str], *, purpose: str = "document") -> Any:
        # F2：配额**不在**这里扣。一次 embed() 会被 provider 按 embedding_batch_size 拆成
        # 多个真实 POST；计划项 requests 是"真实 HTTP 请求/批"的上界，因此 take 放在
        # GateAttemptLedger.reserve（每次底层 POST 一次），批次被放大时在第二批发送前停住。
        item = self._wiring.embedding_item(str(purpose))
        self._wiring.embedding_calls += 1
        self._wiring.ledger.bind(item)
        try:
            return self._inner.embed(texts, purpose=purpose)
        finally:
            self._wiring.ledger.unbind()

    def as_dict(self) -> dict[str, Any]:
        return {
            # calls = 真实 POST 次数（= 账本 reservation 数）；embed_calls = 逻辑 embed() 调用数。
            "calls": int(
                self._wiring.ledger.attempts("index_embedding", "query_embedding")
            ),
            "embed_calls": int(self._wiring.embedding_calls),
            "provider": self.provider,
            "model": self.model,
            "impl": type(self._inner).__name__,
            "transport": type(getattr(self._inner, "transport", None)).__name__,
        }

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()


class GatedRerankProvider:
    """真实 rerank provider 的门控包装：一次 rerank = 一次请求。"""

    def __init__(self, inner: Any, *, wiring: "LiveWiring") -> None:
        self._inner = inner
        self._wiring = wiring
        self.provider = str(getattr(inner, "provider", "bailian"))
        self.model = str(getattr(inner, "model", ""))

    def rerank(self, query: str, documents: Sequence[str], *, top_n: int | None = None) -> Any:
        # F2：配额与其它从属尝试同一口径 —— 每次真实 POST 在 reserve 里 take 一次。
        item = self._wiring.rerank_item()
        self._wiring.rerank_calls += 1
        self._wiring.ledger.bind(item)
        try:
            return self._inner.rerank(query, documents, top_n=top_n)
        finally:
            self._wiring.ledger.unbind()

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": int(self._wiring.ledger.attempts("rerank")),
            "rerank_calls": int(self._wiring.rerank_calls),
            "provider": self.provider,
            "model": self.model,
            "impl": type(self._inner).__name__,
            "transport": type(getattr(self._inner, "transport", None)).__name__,
        }

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()


class GatedChatGateway:
    """产品 chat 网关的门控包装：按 **purpose** 选计划项，一次 chat = 一笔资金身份。

    - purpose="answer"：runner 已在每一轮之前 begin 了 answer-* 并 confirm_before_send；
      产品这一轮真正发出的那一次 chat 就是该预留对应的底层发送。本轮第二次 answer chat 会在
      发送前被拒（chat_attempt_exceeds_plan），绝不"多发一次不记账"。
    - purpose="query_expansion"：产品在 evidence.kind=="none" 时**真的**会调模型
      （conversations.service）；它有自己的计划项 expand-*，因此这里是
      begin_attempt -> confirm_before_send -> 真实 POST -> settle_success(usage)，
      预留/结算/成本中心/回执全按该项 —— 不再记到 answer-*。
    """

    def __init__(self, inner: Any, *, wiring: "LiveWiring") -> None:
        self._inner = inner
        self._wiring = wiring
        self.provider = str(getattr(inner, "provider", "deepseek"))
        self.model = str(getattr(inner, "model", ""))

    def __getattr__(self, name: str) -> Any:  # 只读属性透传；不做网络
        return getattr(self._inner, name)

    async def complete(self, request: Any, *, timeout_seconds: float, **_kwargs: Any) -> Any:
        purpose = str(getattr(request, "purpose", "answer") or "answer")
        if purpose == "query_expansion":
            return await self._complete_expansion(request, timeout_seconds=timeout_seconds)
        # answer（以及未来其它 purpose 的兜底）：沿用 runner 的 answer 预留，本轮只允许 1 次。
        self._wiring.answer_chat_before_send(request)
        output = await self._inner.complete(request, timeout_seconds=timeout_seconds)
        self._wiring.answer_chat_sent(output)
        return output

    async def _complete_expansion(self, request: Any, *, timeout_seconds: float) -> Any:
        """query_expansion 的逐次归属：计划项 expand-* 独立预留 + 真实 usage 结算。"""
        wiring = self._wiring
        item = wiring.expansion_item()  # 计划没有 expand-* 就在这里拒绝（不发送）
        wiring.expansion_before_send()
        ticket = wiring.ledger.begin_sync_attempt(item)
        try:
            output = await self._inner.complete(request, timeout_seconds=timeout_seconds)
        except Exception as exc:
            wiring.ledger.settle_sync_failure(ticket, error_code=type(exc).__name__)
            raise
        usage = getattr(output, "raw_usage", None) or getattr(output, "usage", None)
        validity = chat_output_validity(output, purpose="query_expansion")
        evidence = chat_usage_evidence(
            request_sha256=ticket.reservation.request_sha256,
            usage=dict(usage) if isinstance(usage, Mapping) else {},
            model=str(ticket.model or CHAT_MODEL),
            finish_reason=validity["finish_reason"],
            content_present=validity["content_present"],
            content_parsed=validity["content_parsed"],
        )
        if evidence is None or not validity["output_valid"]:
            # 声明"扩展"却拿不到官方 usage / 输出不完整：不伪造金额，保守占满上界并停止后续付费。
            wiring.ledger.settle_sync_failure(ticket, error_code="usage_evidence_missing")
            raise P2LiveRefused(
                "usage_evidence_missing", "query_expansion 响应缺少官方 usage（不伪造金额）"
            )
        wiring.ledger.settle_usage(ticket.reservation, evidence=evidence)
        return output

    async def aclose(self) -> None:
        closer = getattr(self._inner, "aclose", None)
        if callable(closer):
            await closer()

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": int(self._wiring.chat_calls),
            "expansion_calls": int(self._wiring.expansion_calls),
            "provider": self.provider,
            "model": self.model,
            "impl": type(self._inner).__name__,
            "transport": type(getattr(self._inner, "transport", None)).__name__,
        }


class GatedOcrGateway:
    """真实 OCR 传输的门控包装：每页一次调用 = 一次 ocr 计划项预留。"""

    code = "OCR_NOT_CONFIGURED"

    def __init__(self, inner: Any, *, wiring: "LiveWiring") -> None:
        self._inner = inner
        self._wiring = wiring
        self.code = str(getattr(inner, "code", self.code))
        self._consumed = 0

    #: 产品运行时的 OCR 模式 -> 计划项必须声明的模型（F5：口径与实现对齐）。
    _MODE_MODEL = {"text": OCR_TEXT_MODEL, "table": OCR_TABLE_MODEL}

    def recognize(self, page: Any, *, mode: str) -> Any:
        expected_model = self._MODE_MODEL.get(str(mode))
        if expected_model is None:
            raise P2LiveRefused("ocr_mode_invalid", f"未注册的 OCR 模式 {mode!r}")
        item = self._wiring.next_ocr_item(self._consumed)
        # F5：页价固定（text 0.5 / table 0.15），价格只由计划项的模型决定。运行时模式与计划项
        # 模型不一致时不得按"另一个模型的价格"结算：发送前拒绝（不预留、不发请求）。
        if str(item.price_profile.model) != expected_model:
            raise P2LiveRefused(
                "ocr_mode_plan_mismatch",
                f"计划项 {item.item_id} 模型 {item.price_profile.model} 与本次 mode={mode} 不一致",
            )
        # 配额在 begin_sync_attempt 里统一扣（每次真实尝试一次）。
        ticket = self._wiring.ledger.begin_sync_attempt(item)
        try:
            result = self._inner.recognize(page, mode=mode)
        except Exception as exc:
            self._wiring.ledger.settle_sync_failure(ticket, error_code=type(exc).__name__)
            raise
        price = item.price_profile.price_cny_per_page
        if price is None:
            self._wiring.ledger.settle_sync_failure(ticket, error_code="OCR_PRICE_MISSING")
            raise P2LiveRefused("ocr_price_missing", "计划项没有每页固定价")
        self._wiring.ledger.settle_sync_success(
            ticket, amount_cny=float(price), usage={"pages": 1}
        )
        self._consumed += 1
        self._wiring.ocr_calls += 1
        return result

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": int(self._wiring.ocr_calls),
            "provider": "tencent",
            "impl": type(self._inner).__name__,
            "pages": int(self._consumed),
        }

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()


# --------------------------------------------------------------------------- #
# 5. 适配器/门的装配与 runner 证据
# --------------------------------------------------------------------------- #


@dataclass
class LiveWiring:
    """live 装配的**可变**运行期：计划项解析、尝试配额、门控账本、回合上下文、计数。"""

    env: LiveEnv
    plan: P2RunPlan
    run_id: str
    gate: P2Gate
    ledger: GateAttemptLedger
    attempt_budget: AttemptBudget
    plan_index: PlanIndex
    transports: Mapping[str, Any] = field(default_factory=dict)
    #: T207-FIX-LIVECAP：本次装配的 provider 预检单请求上限推导（金额，不含凭据）。
    #: 由 product_adapter 在构建应用之前写入；未装配完成时为 None。
    request_ceiling: dict[str, Any] | None = None
    turn: TurnContext = field(default_factory=TurnContext)
    receipts: list[AttemptReceipt] = field(default_factory=list)
    #: answer 付费 chat 次数（query_expansion 单独计在 expansion_calls 并单独结算）。
    chat_calls: int = 0
    expansion_calls: int = 0
    #: 逻辑 embed()/rerank() 调用数；真实 POST 数见 ledger.attempt_counts。
    embedding_calls: int = 0
    rerank_calls: int = 0
    ocr_calls: int = 0
    _request_map: dict[str, tuple[str, int]] | None = None

    # -- 计划项解析 ------------------------------------------------------
    def _request_map_of(self) -> dict[str, tuple[str, int]]:
        if self._request_map is None:
            from .p2_runner import _request_uuid

            mapping: dict[str, tuple[str, int]] = {}
            for (case_id, turn), item in self.plan_index.answer_items.items():
                mapping[_request_uuid(self.run_id, case_id, turn)] = (case_id, turn)
            self._request_map = mapping
        return self._request_map

    def enter_turn(self, client_request_id: str) -> None:
        key = str(client_request_id or "")
        resolved = self._request_map_of().get(key)
        if resolved is None:
            raise P2LiveRefused(
                "attempt_turn_unknown",
                "本次产品回合的 client_request_id 不属于本 run 的 answer 计划项",
            )
        self.turn.enter(request_id=key, case_id=resolved[0], turn=resolved[1])

    def leave_turn(self) -> None:
        self.turn.leave()

    def embedding_item(self, purpose: str) -> P2RequestItem:
        if purpose == "document":
            return self.plan_index.index_embedding_item()
        case_id, turn = self.turn.case_turn()
        return self.plan_index.turn_item("query_embedding", case_id, turn)

    def rerank_item(self) -> P2RequestItem:
        case_id, turn = self.turn.case_turn()
        return self.plan_index.turn_item("rerank", case_id, turn)

    def expansion_item(self) -> P2RequestItem:
        """query_expansion 的**资金身份**：计划项 expand-*（缺失即发送前拒绝）。"""
        case_id, turn = self.turn.case_turn()
        return self.plan_index.turn_item("query_expansion", case_id, turn)

    def next_ocr_item(self, consumed: int) -> P2RequestItem:
        return self.plan_index.next_ocr_item(consumed)

    # -- chat（answer 由 runner 的预留覆盖；expand 走自己的计划项）--------
    def answer_chat_before_send(self, request: Any = None) -> None:
        if self.turn.request_id is None:
            raise P2LiveRefused(
                "attempt_outside_turn", "chat 只能在受预算的产品回合内发送"
            )
        if self.turn.answer_chat_calls >= 1:
            raise P2LiveRefused(
                "chat_attempt_exceeds_plan",
                "本轮已有一次付费 answer chat；第二次发送没有对应的计划项，禁止发送",
            )
        self.turn.answer_chat_calls += 1
        self.chat_calls += 1
        self._capture_retrieved(request)

    def answer_chat_sent(self, output: Any) -> None:
        usage = getattr(output, "raw_usage", None) or getattr(output, "usage", None)
        self.turn.chat_usage = dict(usage) if isinstance(usage, Mapping) else None
        self.turn.chat_request_id = getattr(output, "provider_request_id", None)
        # T207-FIX-B/C：把**这一份输出**的有效性判据留到结算时用（缺省=无效）。
        validity = chat_output_validity(output)
        self.turn.chat_finish_reason = validity["finish_reason"]
        self.turn.chat_content_present = bool(validity["content_present"])
        self.turn.chat_content_parsed = bool(validity["content_parsed"])

    def expansion_before_send(self) -> None:
        if self.turn.request_id is None:
            raise P2LiveRefused(
                "attempt_outside_turn", "query_expansion 只能在受预算的产品回合内发送"
            )
        self.turn.expansion_calls += 1
        self.expansion_calls += 1

    def _capture_retrieved(self, request: Any) -> None:
        """F6：把**产品自己交给模型**的证据集合记成本轮检索候选（零额外调用）。

        产品没有暴露"本轮候选集合"的 API，但 answer 请求的 CompletionInput.evidence 就是
        产品检索结果（legacy 记录型 = evidence.units，正文型 = 排序后的正文单元）；直接取
        source_id，既不重放也不再付费，也不把 citations 抄成候选。
        """
        evidence = getattr(request, "evidence", ()) or ()
        ids: list[str] = []
        for item in evidence:
            value = str(getattr(item, "source_id", "") or "").strip()
            if value and value not in ids:
                ids.append(value)
        if ids:
            self.turn.retrieved_ids = tuple(ids)

    def retrieved_ids(self) -> tuple[str, ...]:
        """本轮 answer 请求实际交给模型的候选 unit id（没有捕获到就是空）。"""
        return self.turn.retrieved_candidates()

    # -- 观测面 ----------------------------------------------------------
    def turn_usage(self) -> dict[str, Any] | None:
        return self.turn.as_usage()

    def receipt_payload(self) -> list[dict[str, Any]]:
        return [receipt.as_dict() for receipt in self.receipts]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": MODE_LIVE,
            "run_id": self.run_id,
            "provider": {
                "chat_model": self.env.chat_model,
                "embedding": "text-embedding-v4",
                "rerank": "gte-rerank-v2",
                "ocr": "tencent-ocr（真实传输）",
            },
            # T207-FIX-LIVECAP：单请求上限的推导（计划峰值 / provider 单次预留 / GO 授权）。
            "request_ceiling": dict(self.request_ceiling) if self.request_ceiling else None,
            "calls": {
                # chat = answer 付费 chat；expansion = 独立结算的 query_expansion。
                "chat": int(self.chat_calls),
                "expansion": int(self.expansion_calls),
                # embedding/rerank 按**真实 POST**计（= 账本 reservation 数），不是 embed() 次数。
                "embedding": int(self.ledger.attempts("index_embedding", "query_embedding")),
                "rerank": int(self.ledger.attempts("rerank")),
                "ocr": int(self.ocr_calls),
            },
            "logical_calls": {
                "embedding": int(self.embedding_calls),
                "rerank": int(self.rerank_calls),
            },
            "attempts": {
                "planned_requests": int(self.plan.total_requests),
                "budget_used": self.attempt_budget.as_dict(),
                "by_operation": self.ledger.attempt_counts,
                "receipts": len(self.receipts),
            },
        }


#: live 门**恒需**的四个核心操作：任何真实 run 都会发出 answer/rerank 与两次 embedding。
LIVE_CORE_OPERATIONS: tuple[str, ...] = (
    "answer",
    "index_embedding",
    "query_embedding",
    "rerank",
)


def required_live_operations(plan: P2RunPlan) -> tuple[str, ...]:
    """本计划真正需要的授权操作集：四核心恒需；``ocr`` 仅在计划含 OCR 项时才要求。

    为什么 OCR 要按计划判（T207-FIX-LIVEGATE）：``P2Gate.authorization.operations`` 直接取自
    **计划**（``p2_authorization.py:644`` = ``P2RunPlan.operations``），而 ``begin_attempt``
    只接受计划里存在的 item。计划没有 OCR 项时门里根本无从发起 OCR 发送，"计划无 OCR 项却
    要求 ocr 授权"只会把合法计划挡在门外（T207 H2：145 项/158 请求/无 OCR）。反过来，计划一旦
    含 OCR 项这里仍要求 ocr；GO 未授权时 ``authorize_p2`` 会先以 ``go_operation_unauthorized``
    拒绝（``p2_authorization.py:478``），本检查不会成为绕开 GO 的旁路。
    """
    required = set(LIVE_CORE_OPERATIONS)
    if "ocr" in plan.operations:
        required.add("ocr")
    return tuple(sorted(required))


def open_live_gate(
    plan: P2RunPlan,
    *,
    run_id: str,
    now: Any = None,
    go_payload: Any = None,
    budget_payload: Any = None,
    ledger_snapshot: Any = None,
    ledger_path: Any = None,
    budget_path: Any = None,
) -> P2Gate:
    """用**固定路径** GO/预算/共享账本开真实门；production_ready 不成立即拒绝。

    显式传 go_payload/budget_payload/ledger_snapshot 只供单元测试隔离副本；此时
    production_ready 会自然为 False（这是预期）。测试请在 tmp 里把副本 monkeypatch 成
    固定路径（与 T201 一致），否则这里会以 live_requires_production_ready 拒绝。

    操作校验按**计划能力**（``required_live_operations``）：四个核心操作恒需，``ocr`` 仅在
    计划存在 OCR 项时要求 —— 默认公开矩阵计划含 OCR 项，行为与修正前逐字相同。
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise P2LiveConfigError("run_id_missing", "live 需要非空 run_id")
    gate = P2Gate.open(
        plan,
        run_id=run_id.strip(),
        now=now,
        go_payload=go_payload,
        budget_payload=budget_payload,
        ledger_snapshot=ledger_snapshot,
        ledger_path=ledger_path,
        budget_path=budget_path,
    )
    authorization = gate.authorization
    if not authorization.production_ready:
        raise P2LiveConfigError(
            "live_requires_production_ready",
            "GO/预算必须来自固定路径、账本快照必须来自固定共享账本、"
            "且 MKTKB_PROJECT_TOTAL_LIMIT_CNY 已设置并与预算一致",
        )
    missing = sorted(set(required_live_operations(plan)) - set(authorization.operations))
    if missing:
        raise P2LiveConfigError("live_operation_not_authorized", f"GO 未授权 {missing}")
    return gate



def _parsed_purpose_schema(output: Any, purpose: str) -> bool:
    """"JSON 解析成功"在 P2 层的凭据：客户端解析后才会产出的结构化字段。

    ``DeepSeekClient._parse`` 先 ``_loads_json_object``（失败即抛 ModelOutputInvalid），再按
    purpose 校验 schema 并构造 ``CompletionOutput``：answer 需要 ``answer`` 字符串 +
    ``source_ids`` 字符串列表（providers/deepseek.py:261-273），query_expansion 需要
    ``terms`` 字符串列表（:242-259）。这里复核该结构存在且类型正确 —— 拿得到它，说明 JSON
    对象确实解析成功；拿不到（或类型不对）一律按"未解析"处理。
    """
    if purpose == "query_expansion":
        terms = getattr(output, "query_terms", None)
        return isinstance(terms, tuple) and all(isinstance(item, str) for item in terms)
    sources = getattr(output, "source_ids", None)
    return isinstance(sources, tuple) and all(isinstance(item, str) for item in sources)


def chat_output_validity(output: Any, *, purpose: str = "answer") -> dict[str, Any]:
    """从**已返回的**真实 chat 输出判定结算有效性（三条件，不猜、不补造）。

    1. ``finish_reason``：输出对象自带该字段时必须 == ``stop``；不带时以客户端已受理为准
       （``DeepSeekClient._parse`` 在返回前就拒绝非 stop：providers/deepseek.py:228）；
    2. ``content_present``：输出 text 非空；
    3. ``content_parsed``：purpose 对应的解析结构存在（见 ``_parsed_purpose_schema``）。

    三条全成立才 ``output_valid=True``；缺任一条件 -> False（fail closed）：该笔结算证据会
    在 J1 侧被拒（content_incomplete / content_not_parsed / finish_reason_not_stop），
    按保守上界留账，绝不用假证据换"按 usage 结算"。
    """
    finish_reason = getattr(output, "finish_reason", CHAT_FINISH_STOP)
    text = getattr(output, "text", None)
    content_present = isinstance(text, str) and bool(text.strip())
    content_parsed = bool(content_present) and _parsed_purpose_schema(output, purpose)
    output_valid = bool(
        finish_reason == CHAT_FINISH_STOP and content_present and content_parsed
    )
    return {
        "finish_reason": finish_reason,
        "content_present": bool(content_present),
        "content_parsed": bool(content_parsed),
        "output_valid": output_valid,
    }


def chat_usage_evidence(
    *,
    request_sha256: str,
    usage: Mapping[str, Any],
    model: str = CHAT_MODEL,
    finish_reason: Any = None,
    content_present: Any = None,
    content_parsed: Any = None,
) -> UsageEvidence | None:
    """由真实 chat 响应的 usage 构造 J1 证据；缺字段就返回 None（不补造）。

    ``output_valid`` 必须由调用方用**这一份真实输出**的三判据显式给出
    （``chat_output_validity``）：默认全部 None -> 一律按无效处理（fail closed），
    绝不为了"结算成功"恒置 True。content/finish 三段也按同一判据填进证据，
    因此"输出不完整"会在 J1 侧被拒，而不是被当成有效 usage 入账。
    """
    if not usage:
        return None
    valid = (
        finish_reason == CHAT_FINISH_STOP
        and content_present is True
        and content_parsed is True
    )
    policy = build_policy(KIND_CHAT, model=model)
    try:
        evidence = build_chat_evidence(
            policy,
            request_sha256=request_sha256,
            usage=dict(usage),
            http_status=200,
            streamed=False,
            finish_reason=CHAT_FINISH_STOP if valid else finish_reason,
            content_complete=content_present is True,
            content_parse_ok=content_parsed is True,
        )
        # build_chat_evidence 不接受 output_valid（J1 冻结签名），用等价 dataclass 替换补上；
        # 判据本身仍来自上面三项，不是常量。
        return dataclasses.replace(evidence, output_valid=bool(valid))
    except Exception:  # noqa: BLE001 - 任何证据构造失败都按"缺 usage"fail closed
        return None


def make_settle_evidence(adapter: Any) -> Callable[[Any, Any], Any]:
    """runner 的 settle_evidence(ticket, product) 实现：只读适配器实测 usage。

    返回三种值：
    - UsageEvidence：本轮确实发生了一次 chat 发送且拿到官方 usage；
    - NO_PAID_ATTEMPT：本轮零付费发送（合法拒答/澄清/未找到/知识变更），由 runner 走
      close_unused（保守留账、不停止）；
    - None：本轮**声称作答**却拿不到 usage —— fail closed（usage_evidence_missing）。
    """

    def settle(ticket: Any, product: Any) -> Any:
        meta = adapter.turn_usage() if hasattr(adapter, "turn_usage") else None
        if not isinstance(meta, Mapping):
            return None
        attempts = int(meta.get("chat_calls") or 0)
        if attempts <= 0:
            return NO_PAID_ATTEMPT
        usage = meta.get("raw_usage") or meta.get("usage") or {}
        if not isinstance(usage, Mapping) or not usage:
            return None
        return chat_usage_evidence(
            request_sha256=ticket.reservation.request_sha256,
            usage=usage,
            model=str(getattr(ticket, "model", CHAT_MODEL) or CHAT_MODEL),
            # T207-FIX-B/C：判据来自本轮**实际输出**（TurnContext 捕获），缺一项即无效。
            finish_reason=meta.get("finish_reason"),
            content_present=meta.get("content_present"),
            content_parsed=meta.get("content_parsed"),
        )

    return settle


@dataclass(frozen=True)
class LiveBuild:
    """一次 live 装配的结果（适配器 + 门 + 尝试账本），供 CLI/测试复用。"""

    adapter: Any
    gate: P2Gate
    ledger: GateAttemptLedger
    wiring: LiveWiring
    env: LiveEnv


def build_live_adapter(
    plan: P2RunPlan,
    *,
    gate: P2Gate,
    env: LiveEnv,
    run_id: str,
    out_dir: Path | str,
    dataset: Any,
    ingest_plan: Any = None,
    transports: Mapping[str, Any] | None = None,
    turn_timeout_seconds: float | None = None,
    purge_traces_on_close: bool = False,
    scenario_contract: Any = None,
    evidence_capture: Any = None,
    # T207-04c：显式业务日期透传（默认 None = 既有行为逐值不变）。
    rag_business_date: str | None = None,
    manifest_business_date: str | None = None,
) -> LiveBuild:
    """装配 live 适配器：真实 provider + 真实 OCR 传输 + 逐次尝试预留。

    transports 只供测试注入（httpx.MockTransport / 假传输）；生产不传即真实传输。
    """
    from .product_adapter import ProductEvalAdapter
    from .p2_holdout_scenarios import validate_scenario_execution
    validate_scenario_execution(plan, dataset, ingest_plan, scenario_contract)

    plan_index = PlanIndex(plan)
    budget = AttemptBudget(plan)
    receipts: list[AttemptReceipt] = []
    ledger = GateAttemptLedger(
        gate, plan, on_receipt=receipts.append, attempt_budget=budget
    )
    wiring = LiveWiring(
        env=env,
        plan=plan,
        run_id=str(run_id),
        gate=gate,
        ledger=ledger,
        attempt_budget=budget,
        plan_index=plan_index,
        transports=dict(transports or {}),
        receipts=receipts,
    )
    adapter = ProductEvalAdapter(
        out_dir,
        mode=MODE_LIVE,
        dataset=dataset,
        ingest_plan=ingest_plan,
        turn_timeout_seconds=turn_timeout_seconds or 60.0,
        purge_traces_on_close=purge_traces_on_close,
        live_wiring=wiring,
        scenario_contract=scenario_contract,
        evidence_capture=evidence_capture,
        rag_business_date=rag_business_date,
        manifest_business_date=manifest_business_date,
    )
    return LiveBuild(adapter=adapter, gate=gate, ledger=ledger, wiring=wiring, env=env)


async def run_live_p2(
    plan: P2RunPlan,
    *,
    run_id: str,
    out_dir: Path | str,
    dataset: Any,
    ingest_plan: Any = None,
    gate: P2Gate | None = None,
    env: Mapping[str, str] | None = None,
    env_overrides: Mapping[str, Any] | None = None,
    transports: Mapping[str, Any] | None = None,
    now: Any = None,
    gate_config: Any = None,
    cancel: Callable[[], bool] | None = None,
    purge_traces_on_close: bool = False,
    scenario_contract: Any = None,
    evidence_capture: Any = None,
    #: 05 live 证据：适配器 start 之后才拿得到实际 business_date/index_revision，
    #: 因此允许注入 factory(build) -> EvidenceCaptureConfig；与 evidence_capture 互斥。
    evidence_capture_factory: Callable[[LiveBuild], Any] | None = None,
    #: 05 受控入口：holdout 逐题质量 marks 的内存回调（默认 None = 行为逐值不变）。
    private_case_marks_sink: Callable[[Any], None] | None = None,
    # T207-04c：显式业务日期透传（默认 None = 既有行为逐值不变）。
    rag_business_date: str | None = None,
    manifest_business_date: str | None = None,
) -> tuple[Any, LiveBuild]:
    """一次性 live 执行入口：环境 -> 真实门 -> live 适配器 -> run_p2（串行、重试 0）。

    任何一步不成立都在**首个发送之前**抛 P2LiveConfigError；不构造第二套账本/授权。
    05 版本化扩展（默认 None 逐值不变）：evidence_capture_factory 在适配器 start
    之后、run_p2（ingest/首轮）之前构造 live 采集配置，使绑定能包含**实际**
    business_date/index_revision；private_case_marks_sink 只把逐题质量状态交给
    显式注入的内存回调，不改变任何公开产物。
    """
    from .p2_runner import run_p2
    from .p2_holdout_scenarios import validate_scenario_execution
    validate_scenario_execution(plan, dataset, ingest_plan, scenario_contract)

    b0_corpus = None
    if plan.b0_binding is not None or getattr(gate_config, "status", None) == "approved":
        from .p2_b0 import B0_BUSINESS_DATE, safe_path, validate_b0_live_inputs

        b0_corpus = validate_b0_live_inputs(
            plan, run_id=run_id, dataset=dataset, ingest_plan=ingest_plan,
            gate_config=gate_config, out_dir=out_dir,
        )
        if transports or env_overrides or gate or purge_traces_on_close or scenario_contract is not None:
            raise P2LiveConfigError("b0_live_override_invalid", "正式 B0 要求原生发送门与公开 trace")
        out_dir = safe_path(Path(out_dir))
        rag_business_date = manifest_business_date = B0_BUSINESS_DATE

    if evidence_capture is not None and evidence_capture_factory is not None:
        raise P2LiveConfigError(
            "evidence_capture_conflict", "evidence_capture 与 factory 只能给一个"
        )
    live_env = load_live_env(env, overrides=env_overrides)
    live_gate = gate or open_live_gate(plan, run_id=run_id, now=now)
    if plan.b0_binding is not None:
        Path(out_dir).mkdir(parents=True, exist_ok=False)
    build = build_live_adapter(
        plan,
        gate=live_gate,
        env=live_env,
        run_id=run_id,
        out_dir=out_dir,
        dataset=dataset,
        ingest_plan=ingest_plan,
        transports=transports,
        purge_traces_on_close=purge_traces_on_close,
        scenario_contract=scenario_contract,
        evidence_capture=evidence_capture,
        rag_business_date=rag_business_date,
        manifest_business_date=manifest_business_date,
    )
    try:
        # T207-FIX-LIVECAP：装配期就把适配器 start 起来（start 幂等，runner 之后照旧调用）。
        # 这样 provider 预检上限不足（live_request_ceiling_insufficient）这类**配置**拒绝
        # 会以稳定码抛给调用方，而不是被 runner 的 ingest 失败路径吞成 ingest_failed
        # （后者虽同样不发送，但会丢掉可机读的原因）。
        await build.adapter.start()
        run_capture = None
        if evidence_capture_factory is not None:
            # 只有 start 之后才知道产品**实际**业务日期/ingest 后 revision；此时构造配置，
            # 仍由 run_p2 在首个产品回合之前 enable（失败即拒，不追溯）。
            run_capture = evidence_capture_factory(build)
            if run_capture is None:
                raise P2LiveConfigError(
                    "evidence_capture_factory_empty", "受控入口必须产出显式采集配置"
                )
        result = await run_p2(
            plan,
            adapter=build.adapter,
            authorization=live_gate.authorization,
            dataset=dataset,
            gate=live_gate,
            run_id=run_id,
            gate_config=gate_config,
            settle_evidence=make_settle_evidence(build.adapter),
            cancel=cancel,
            now=now,
            evidence_capture=run_capture,
            private_case_marks_sink=private_case_marks_sink,
            **({"b0_corpus": b0_corpus} if b0_corpus is not None else {}),
        )
    finally:
        await build.adapter.close()
    return result, build
