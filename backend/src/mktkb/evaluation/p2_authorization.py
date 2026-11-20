"""P2-T201：P2 资金/授权门（固定共享账本 + P2 GO + 成本中心 + 每次发送前拒绝链）。

边界（任务书 §4.3 / §6.2 / §8 T201）：
- 复用**同一只**共享账本与同一份预算文件（不造第二套资金真账，不新空账本）；账本/预算/GO
  是仓库内固定常量，环境变量或调用参数最多只能“指名同一个文件”，不能替换成别的文件或软链；
- 旧 P1 GO（document=S2-LIVE-GO）**默认拒绝** P2：P2 只认 document=P2-LIVE-GO，且
  live_authorization 也拒绝 stage=P2-LIVE，所以 OCR/judge 不能借 rag/chat 旧 GO 偷渡；
- 预算分两层同时生效：P2 阶段硬顶（候选 20 元）与四个成本中心（12/3/3/2）。中心额度在
  **每次预留**时按同阶段已占用金额再判一次，累计（跨 run/跨进程）超限一样拒绝；
- 请求上限是**累计**口径：直接用账本里的 reservation 计数，新增预算不重置历史 505 次；
  unlimited 模式下计划项的逐项配额按 ``plan_sha256 + item_id`` 累计，换 run_id / 重启
  也不会清零（见 ``P2Gate._request_guard``）；
- 每次真实发送前有两次门：预留前（request_guard，锁内）与预留后/发送前
  （post_reserve_guard + 授权重校验）。任一失败都停在 HTTP 之前：不新增预留、不重试；
  已经发生的预留保持保守占用（写 status=failed 的 result，不回 0、不擅自释放），
  回执保留 reservation_id / request_id / plan_id / cost_center；
- 自动重试恒为 0：本模块没有任何重试路径，失败即置 stopped，后续 begin 直接拒绝。

本模块不读 .env、不读 H2/Holdout 题干、不发真实 HTTP：真实发送由 T203/T204 的适配器完成，
这里只提供“能不能发”的判定与资金归属。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ..live_authorization import (
    TOTAL_LIMIT_ENV,
    historical_prefix_sha256,
    ledger_binding_ok,
)
from ..rag.budget import BudgetLedger, Reservation
from ..rag.errors import BudgetError
from ..rag.settlement_policy import SettlementPolicy, UsageEvidence
from .p2_contracts import (
    COST_CENTERS,
    HARD_MAX_REQUESTS,
    UNLIMITED_REQUESTS,
    request_cap,
    OPERATION_COST_CENTER,
    OPERATIONS,
    P2_AUTHORIZATION_SCHEMA_VERSION,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
    P2_PREFLIGHT_SCHEMA_VERSION,
    P2_RUN_RESULT_SCHEMA_VERSION,
    P2_STAGE,
    P2Authorization,
    P2ContractError,
    P2LedgerSnapshot,
    P2PreflightResult,
    P2RequestItem,
    P2RunPlan,
    P2RunResult,
    canonical_decimal,
    payload_sha256,
)

__all__ = [
    "P2_BUDGET_PATH",
    "P2_GO_DOCUMENT",
    "P2_GO_PATH",
    "P2_GO_SCHEMA_VERSION",
    "P2_LEDGER_PATH",
    "P2AuthorizationError",
    "P2Gate",
    "P2GateError",
    "P2RequestTicket",
    "P2SendRefused",
    "authorize_p2",
    "load_budget_payload",
    "load_go_payload",
    "preflight_p2",
    "read_ledger_snapshot",
]

# backend/src/mktkb/evaluation/p2_authorization.py -> parents[4] 是仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[4]
P2_GO_DOCUMENT = "P2-LIVE-GO"
P2_GO_SCHEMA_VERSION = "p2-live-go/v0.1"
P1_GO_DOCUMENT = "S2-LIVE-GO"

# 固定共享路径（与 live_authorization 的共享账本/预算必须是同一文件）。
P2_LEDGER_PATH = _REPO_ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
P2_BUDGET_PATH = _REPO_ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
# 正式 P2 GO 的固定落点（T206 才由经理签发；本包只产候选，不创建该文件）。
P2_GO_PATH = _REPO_ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "P2-LIVE-GO.json"

MAX_GO_BYTES = 65536

_GO_KEYS = (
    "document",
    "schema_version",
    "stage",
    "authorization",
    "issued_by",
    "nonce",
    "issued_utc",
    "expires_utc",
    "budget_ledger_path",
    "budget_ledger_sha256",
    "budget_total_limit_cny",
    "scope",
)
_GO_SCOPE_KEYS = (
    "plan_id",
    "plan_sha256",
    "operations",
    "cost_centers_cny",
    "stage_limits_cny",
    "max_requests",
    "max_request_cny",
)
_EPS = 1e-9


class P2AuthorizationError(ValueError):
    """GO/预算/账本/计划绑定无法证明：在首个预留与首个 HTTP 之前拒绝。"""

    code = "P2_AUTHORIZATION_INVALID"

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = str(reason)
        self.detail = str(detail)


class P2GateError(ValueError):
    """每次发送前门控拒绝（未发请求）。reason 是稳定码。"""

    code = "P2_GATE_REFUSED"

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = str(reason)
        self.detail = str(detail)


class P2SendRefused(P2GateError):
    """预留已发生、发送前复核失败：保守记账并停止，回执保留请求身份。"""

    code = "P2_SEND_REFUSED"

    def __init__(self, reason: str, *, ticket: "P2RequestTicket") -> None:
        super().__init__(reason, "发送前复核失败，已保守留账")
        self.ticket = ticket
        self.reservation_id = ticket.reservation_id
        self.request_id = ticket.request_id
        self.cost_center = ticket.cost_center


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _instant(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise P2AuthorizationError("instant_missing", f"{label} 缺失")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise P2AuthorizationError("instant_invalid", f"{label} 不是 ISO 时间") from None
    if moment.tzinfo is None:
        raise P2AuthorizationError("instant_invalid", f"{label} 必须带时区")
    return moment


def _number(value: Any, label: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise P2AuthorizationError("number_invalid", f"{label} 必须是数字（拒绝 bool/字符串/None）")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise P2AuthorizationError("number_invalid", f"{label} 必须是有限数字")
    if number < 0 or (number == 0 and not allow_zero):
        raise P2AuthorizationError("number_invalid", f"{label} 必须是正数" if not allow_zero else f"{label} 不得为负")
    return number


def _int_value(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise P2AuthorizationError("integer_invalid", f"{label} 必须是整数（拒绝 bool）")
    if value < minimum:
        raise P2AuthorizationError("integer_invalid", f"{label} 不得小于 {minimum}")
    return int(value)


def _text(value: Any, label: str, *, maximum: int = 200, allow_space: bool = True) -> str:
    if not isinstance(value, str):
        raise P2AuthorizationError("text_invalid", f"{label} 必须是字符串")
    text = value.strip()
    if not text or len(text) > maximum:
        raise P2AuthorizationError("text_invalid", f"{label} 长度非法")
    if not allow_space and any(ch.isspace() for ch in text):
        raise P2AuthorizationError("text_invalid", f"{label} 不得含空白")
    return text


def _exact(mapping: Any, keys: tuple[str, ...], label: str) -> None:
    if not isinstance(mapping, Mapping):
        raise P2AuthorizationError("mapping_required", f"{label} 必须是对象")
    missing = sorted(set(keys) - set(mapping))
    unknown = sorted(set(mapping) - set(keys))
    if missing:
        raise P2AuthorizationError("field_missing", f"{label} 缺少字段 {missing}")
    if unknown:
        raise P2AuthorizationError("field_unknown", f"{label} 含未声明字段 {unknown}")


def _load_json_object(raw: str, label: str) -> Any:
    def _reject_constant(value: str) -> Any:
        raise ValueError(f"{label} 含非标准 JSON 常量")

    try:
        return json.loads(raw, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise P2AuthorizationError("json_invalid", f"{label} 不是合法 JSON") from None


# ---------------------------------------------------------------- 固定路径


def _require_fixed_file(path: Any, expected: Path, label: str) -> Path:
    candidate = Path(path)
    expected_path = Path(expected)
    if candidate.is_symlink() or expected_path.is_symlink():
        raise P2AuthorizationError("path_symlink", f"{label} 不得是软链")
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:  # pragma: no cover - 极端文件系统错误
        raise P2AuthorizationError("path_unresolvable", f"{label} 路径不可解析") from None
    if resolved != expected_path.resolve(strict=False):
        raise P2AuthorizationError(
            "path_not_fixed", f"{label} 必须是仓库内固定共享路径（拒绝替换账本/预算/GO）"
        )
    if not expected_path.is_file():
        raise P2AuthorizationError("path_missing", f"{label} 不存在")
    return expected_path


def load_go_payload(path: Any = None) -> dict[str, Any]:
    """从固定 P2 GO 路径读授权文件（只读，大小与 JSON 严格校验）。"""
    target = _require_fixed_file(P2_GO_PATH if path is None else path, P2_GO_PATH, "P2 GO")
    if target.stat().st_size > MAX_GO_BYTES:
        raise P2AuthorizationError("go_too_large", "P2 GO 文件过大")
    payload = _load_json_object(target.read_text(encoding="utf-8"), "P2 GO")
    if not isinstance(payload, dict):
        raise P2AuthorizationError("go_invalid", "P2 GO 顶层必须是对象")
    return payload


def load_budget_payload(path: Any = None) -> dict[str, Any]:
    target = _require_fixed_file(P2_BUDGET_PATH if path is None else path, P2_BUDGET_PATH, "共享预算")
    payload = _load_json_object(target.read_text(encoding="utf-8"), "共享预算")
    if not isinstance(payload, dict):
        raise P2AuthorizationError("budget_invalid", "共享预算顶层必须是对象")
    return payload


# ---------------------------------------------------------------- 只读快照


def read_ledger_snapshot(*, ledger_path: Any = None, budget_path: Any = None) -> P2LedgerSnapshot:
    """从固定共享账本/预算**只读**重算事实快照。

    复用账本自身的保守重算规则（BudgetLedger.summary，含版本化 result 重放），不另写一套
    会计；只读路径会在账本旁建/删一个瞬时 .lock（不追加事件、不改预算），前后文件
    SHA-256 一致即证明未写入。
    """
    ledger = _require_fixed_file(P2_LEDGER_PATH if ledger_path is None else ledger_path, P2_LEDGER_PATH, "共享账本")
    budget = _require_fixed_file(P2_BUDGET_PATH if budget_path is None else budget_path, P2_BUDGET_PATH, "共享预算")
    raw_ledger = ledger.read_bytes()
    raw_budget = budget.read_bytes()
    budget_payload = _load_json_object(raw_budget.decode("utf-8"), "共享预算")
    if not isinstance(budget_payload, dict):
        raise P2AuthorizationError("budget_invalid", "共享预算顶层必须是对象")
    stages = budget_payload.get("stages")
    if stages is not None and not isinstance(stages, Mapping):
        raise P2AuthorizationError("budget_stages_invalid", "共享预算 stages 必须是对象")
    allocations: dict[str, float] = {}
    for stage, amount in (stages or {}).items():
        allocations[str(stage)] = _number(amount, f"预算阶段 {stage} 的分配")
    stage_limit = allocations.get(P2_STAGE, 0.0)
    if stage_limit <= 0:
        # 没有 P2 阶段时预检必然拒绝；这里给账本一个合法占位值，只为读出事实。
        stage_limit = 1.0
    try:
        book = BudgetLedger(
            ledger,
            budget,
            stage=P2_STAGE,
            stage_limit_cny=stage_limit,
            max_requests=HARD_MAX_REQUESTS,
        )
        summary = book.summary()
    except BudgetError as exc:
        raise P2AuthorizationError("ledger_unreadable", type(exc).__name__) from None
    try:
        prefix_sha = historical_prefix_sha256(ledger)
    except Exception as exc:  # noqa: BLE001 - 共享账本结构非法时默认拒绝
        raise P2AuthorizationError("ledger_prefix_invalid", type(exc).__name__) from None
    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        ledger_path=str(ledger),
        ledger_sha256=hashlib.sha256(raw_ledger).hexdigest(),
        historical_prefix_sha256=prefix_sha,
        budget_sha256=hashlib.sha256(raw_budget).hexdigest(),
        total_limit_cny=float(summary.total_limit_cny),
        historical_accounted_cny=float(summary.historical_conservative_cny),
        accounted_cny=float(summary.accounted_cny),
        reservation_count=int(summary.reservation_count),
        result_count=int(summary.result_count),
        stage_allocations_cny=allocations,
        p2_stage_accounted_cny=float(summary.stage_accounted_cny),
        p2_center_accounted_cny={str(k): float(v) for k, v in dict(summary.center_accounted_cny).items()},
        source="fixed-paths",
    )


# ---------------------------------------------------------------- 预检


def _as_plan(plan: Any) -> P2RunPlan:
    if isinstance(plan, P2RunPlan):
        return plan
    if isinstance(plan, Mapping):
        return P2RunPlan.from_dict(plan)
    raise P2ContractError("mapping_required", "plan 必须是 P2RunPlan 或计划字典")


def _as_snapshot(snapshot: Any) -> P2LedgerSnapshot:
    if isinstance(snapshot, P2LedgerSnapshot):
        return snapshot
    if isinstance(snapshot, Mapping):
        return P2LedgerSnapshot.from_dict(snapshot)
    raise P2ContractError("mapping_required", "snapshot 必须是 P2LedgerSnapshot 或快照字典")


def preflight_p2(plan: P2RunPlan, snapshot: P2LedgerSnapshot) -> P2PreflightResult:
    """计划 vs 当前账本/预算事实的只读预检；不改任何文件、不预留。

    拒绝原因全部是稳定码（可枚举），顺序固定，便于 runner/报告逐项对齐。
    """
    frozen_plan = _as_plan(plan)
    frozen_snapshot = _as_snapshot(snapshot)
    reasons: list[str] = []

    if abs(frozen_snapshot.total_limit_cny - frozen_plan.project_total_limit_cny) > _EPS:
        reasons.append("budget_total_mismatch")
    allocation = frozen_snapshot.stage_allocations_cny.get(P2_STAGE)
    if allocation is None:
        reasons.append("stage_allocation_missing")
        effective_stage_limit = frozen_plan.stage_limit_cny
        stage_remaining = 0.0
    else:
        if allocation + _EPS < frozen_plan.stage_limit_cny:
            reasons.append("stage_allocation_below_plan")
        effective_stage_limit = min(allocation, frozen_plan.stage_limit_cny)
        stage_remaining = max(0.0, effective_stage_limit - frozen_snapshot.p2_stage_accounted_cny)
    total_remaining = max(0.0, frozen_snapshot.total_limit_cny - frozen_snapshot.accounted_cny)
    requests_remaining = (UNLIMITED_REQUESTS if frozen_plan.max_requests == UNLIMITED_REQUESTS
                          else max(0, frozen_plan.max_requests - frozen_snapshot.reservation_count))

    if frozen_plan.worst_case_cny > stage_remaining + _EPS:
        reasons.append("stage_budget_insufficient")
    if frozen_plan.worst_case_cny > total_remaining + _EPS:
        reasons.append("total_budget_insufficient")
    if requests_remaining != UNLIMITED_REQUESTS and frozen_plan.total_requests > requests_remaining:
        reasons.append("request_budget_insufficient")

    needs = frozen_plan.center_needs_cny()
    center_remaining: dict[str, float] = {}
    for center in COST_CENTERS:
        used = float(frozen_snapshot.p2_center_accounted_cny.get(center, 0.0))
        limit = float(frozen_plan.cost_centers_cny[center])
        center_remaining[center] = max(0.0, limit - used)
        if used + needs[center] > limit + _EPS:
            reasons.append(f"center_budget_insufficient:{center}")
    center_used_total = sum(
        float(amount) for amount in frozen_snapshot.p2_center_accounted_cny.values()
    )
    if abs(center_used_total - frozen_snapshot.p2_stage_accounted_cny) > _EPS:
        # 阶段占用必须能完整归到四个成本中心；有未归属占用就不能证明“换归属不会超”，拒绝。
        reasons.append("center_accounting_inconsistent")

    return P2PreflightResult(
        schema_version=P2_PREFLIGHT_SCHEMA_VERSION,
        ok=not reasons,
        reasons=tuple(reasons),
        plan_id=frozen_plan.plan_id,
        plan_sha256=frozen_plan.plan_sha256,
        stage=P2_STAGE,
        stage_limit_cny=float(effective_stage_limit),
        stage_remaining_cny=float(stage_remaining),
        total_limit_cny=float(frozen_snapshot.total_limit_cny),
        total_remaining_cny=float(total_remaining),
        max_requests=frozen_plan.max_requests,
        requests_used=int(frozen_snapshot.reservation_count),
        requests_remaining=requests_remaining,
        requests_planned=int(frozen_plan.total_requests),
        worst_case_cny=float(frozen_plan.worst_case_cny),
        reserve_peak_cny=float(frozen_plan.reserve_peak_cny),
        estimated_success_cny=float(frozen_plan.estimated_success_cny),
        by_operation=frozen_plan.requests_by_operation(),
        center_limits_cny={center: float(frozen_plan.cost_centers_cny[center]) for center in COST_CENTERS},
        center_needs_cny=needs,
        center_remaining_cny=center_remaining,
        production_ready=frozen_snapshot.production_ready,
    )


# ---------------------------------------------------------------- 授权


def _resolve_payload(
    value: Any, expected: Path, label: str, loader: Any
) -> tuple[dict[str, Any], bool]:
    """返回 (payload, 是否来自固定路径)。

    只有两种来源：内存字典（Mock/候选，production_ready=False）与固定路径文件
    （生产，production_ready 才可能为 True）。其他类型一律拒绝。
    """
    if isinstance(value, Mapping):
        return dict(value), False
    if isinstance(value, (str, Path)):
        return loader(value), True
    raise P2AuthorizationError("payload_invalid", f"{label} 必须是内存对象或固定路径")


def _check_go_payload(payload: Mapping[str, Any], plan: P2RunPlan, now: datetime) -> tuple[datetime, datetime]:
    # document 先判：真实 P1 GO 的字段集不同，先报“旧 GO”才是可归因的稳定原因。
    document = payload.get("document") if isinstance(payload, Mapping) else None
    if document == P1_GO_DOCUMENT:
        raise P2AuthorizationError(
            "legacy_go_document", "旧 P1 GO（S2-LIVE-GO）不获得 P2 权限（OCR/judge 不能偷渡）"
        )
    if document != P2_GO_DOCUMENT:
        raise P2AuthorizationError("go_document_invalid", f"GO document 必须是 {P2_GO_DOCUMENT}")
    _exact(payload, _GO_KEYS, "P2 GO")
    if payload.get("schema_version") != P2_GO_SCHEMA_VERSION:
        raise P2AuthorizationError("go_schema_invalid", f"GO schema_version 必须是 {P2_GO_SCHEMA_VERSION}")
    if payload.get("stage") != P2_STAGE or payload.get("stage") != plan.stage:
        raise P2AuthorizationError("go_stage_mismatch", f"GO stage 必须是 {plan.stage}")
    _text(payload.get("authorization"), "GO authorization")
    _text(payload.get("issued_by"), "GO issued_by")
    nonce = _text(payload.get("nonce"), "GO nonce", maximum=256, allow_space=False)
    if len(nonce) < 16:
        raise P2AuthorizationError("go_nonce_invalid", "GO nonce 不足 16 字符")
    issued = _instant(payload.get("issued_utc"), "GO issued_utc")
    expires = _instant(payload.get("expires_utc"), "GO expires_utc")
    if expires <= issued:
        raise P2AuthorizationError("go_time_invalid", "GO 过期时间必须晚于生效时间")
    if now < issued:
        raise P2AuthorizationError("go_not_yet_valid", "GO 尚未生效")
    if now >= expires:
        raise P2AuthorizationError("go_expired", "GO 已过期")
    _number(payload.get("budget_total_limit_cny"), "GO budget_total_limit_cny", allow_zero=False)
    if abs(float(payload["budget_total_limit_cny"]) - plan.project_total_limit_cny) > _EPS:
        raise P2AuthorizationError("go_budget_total_mismatch", "GO 声明的项目总上限与计划不一致")
    scope = payload.get("scope")
    _exact(scope, _GO_SCOPE_KEYS, "GO scope")
    if scope.get("plan_id") != plan.plan_id:
        raise P2AuthorizationError("go_plan_id_mismatch", "GO 绑定的 plan_id 与计划不一致")
    bound_sha = _text(scope.get("plan_sha256"), "GO scope.plan_sha256", maximum=64, allow_space=False)
    if bound_sha.lower() != plan.plan_sha256:
        raise P2AuthorizationError(
            "go_plan_sha256_mismatch", "GO 绑定的计划摘要与当前计划不一致（改计划/换 nonce 复用都拒绝）"
        )
    operations = scope.get("operations")
    if not isinstance(operations, list) or not operations or not all(isinstance(item, str) for item in operations):
        raise P2AuthorizationError("go_operations_invalid", "GO scope.operations 必须是非空字符串数组")
    unknown = sorted(set(operations) - set(OPERATIONS))
    if unknown:
        raise P2AuthorizationError("go_operation_invalid", "GO scope.operations 含未注册操作")
    missing = sorted(set(plan.operations) - set(operations))
    if missing:
        raise P2AuthorizationError("go_operation_unauthorized", "GO 未授权计划中的操作（如 OCR/judge）")
    centers = scope.get("cost_centers_cny")
    if not isinstance(centers, Mapping):
        raise P2AuthorizationError("go_cost_center_invalid", "GO scope.cost_centers_cny 必须是对象")
    unknown_centers = sorted(set(centers) - set(COST_CENTERS))
    if unknown_centers:
        raise P2AuthorizationError("go_cost_center_invalid", "GO scope.cost_centers_cny 含未注册中心")
    missing_centers = sorted(set(COST_CENTERS) - set(centers))
    if missing_centers:
        raise P2AuthorizationError("go_cost_center_unauthorized", "GO 未授权计划使用的成本中心")
    for center in COST_CENTERS:
        declared = _number(centers[center], f"GO 成本中心 {center}", allow_zero=False)
        if declared + _EPS < float(plan.cost_centers_cny[center]):
            raise P2AuthorizationError(
                "go_cost_center_below_plan", f"GO 成本中心 {center} 额度低于计划分配"
            )
    stage_limits = scope.get("stage_limits_cny")
    if not isinstance(stage_limits, Mapping) or P2_STAGE not in stage_limits:
        raise P2AuthorizationError("go_stage_limit_missing", f"GO stage_limits_cny 缺少 {P2_STAGE}")
    go_stage_limit = _number(stage_limits[P2_STAGE], f"GO 阶段 {P2_STAGE} 额度", allow_zero=False)
    if go_stage_limit + _EPS < plan.stage_limit_cny:
        raise P2AuthorizationError("go_stage_limit_below_plan", "GO 阶段额度低于计划阶段额度")
    try:
        go_max_requests = request_cap(scope.get("max_requests"), "GO scope.max_requests")
    except P2ContractError:
        raise P2AuthorizationError("go_max_requests_invalid", "GO 累计请求上限非法") from None
    if go_max_requests != UNLIMITED_REQUESTS and go_max_requests > HARD_MAX_REQUESTS:
        raise P2AuthorizationError(
            "go_max_requests_over_hard_cap", f"GO 累计请求上限不得超过 {HARD_MAX_REQUESTS}"
        )
    if go_max_requests != UNLIMITED_REQUESTS and go_max_requests < plan.total_requests:
        raise P2AuthorizationError("go_max_requests_below_plan", "GO 累计请求上限小于计划请求数")
    if go_max_requests != UNLIMITED_REQUESTS and (plan.max_requests == UNLIMITED_REQUESTS or plan.max_requests > go_max_requests):
        raise P2AuthorizationError("go_max_requests_below_plan", "计划累计请求上限高于 GO")
    go_max_request = _number(scope.get("max_request_cny"), "GO scope.max_request_cny", allow_zero=False)
    if go_max_request + _EPS < plan.reserve_peak_cny:
        raise P2AuthorizationError("go_max_request_cny_below_plan", "GO 单请求上界小于计划单次峰值预留")
    return issued, expires


def _check_budget_payload(payload: Mapping[str, Any], plan: P2RunPlan, snapshot: P2LedgerSnapshot) -> float:
    limit = _number(payload.get("limit_cny"), "预算 limit_cny", allow_zero=False)
    if abs(limit - plan.project_total_limit_cny) > _EPS:
        raise P2AuthorizationError(
            "budget_total_mismatch",
            f"共享预算总上限必须等于计划声明的 {canonical_decimal(Decimal(str(plan.project_total_limit_cny)))} 元",
        )
    stages = payload.get("stages")
    if not isinstance(stages, Mapping):
        raise P2AuthorizationError("budget_stages_invalid", "共享预算 stages 必须是对象")
    if P2_STAGE not in stages:
        raise P2AuthorizationError("budget_stage_missing", f"共享预算没有 {P2_STAGE} 阶段分配（默认拒绝）")
    allocation = _number(stages[P2_STAGE], f"预算阶段 {P2_STAGE} 的分配", allow_zero=False)
    if allocation + _EPS < plan.stage_limit_cny:
        raise P2AuthorizationError("budget_stage_below_plan", "共享预算阶段额度低于计划阶段额度")
    declared_ledger = payload.get("ledger")
    if isinstance(declared_ledger, str) and declared_ledger.strip():
        declared = (_REPO_ROOT / declared_ledger.strip()).resolve(strict=False)
        if declared != Path(P2_LEDGER_PATH).resolve(strict=False):
            raise P2AuthorizationError("budget_ledger_path_not_fixed", "共享预算声明的账本不是固定共享账本")
    history = payload.get("historical_conservative_accounted_cny")
    if history is not None:
        declared_history = _number(history, "预算历史占用")
        if abs(declared_history - snapshot.historical_accounted_cny) > _EPS:
            raise P2AuthorizationError(
                "budget_history_mismatch", "共享账本的历史占用与预算声明不一致（拒绝新账本/改历史）"
            )
    return allocation


def authorize_p2(
    plan: P2RunPlan,
    *,
    go_payload: Any,
    budget_payload: Any,
    ledger_snapshot: Any,
    now: datetime | None = None,
) -> P2Authorization:
    """把「计划 + P2 GO + 共享预算 + 账本快照」收敛成唯一授权；任何不合法都在预留前拒绝。"""
    frozen_plan = _as_plan(plan)
    moment = (now or _utcnow()).astimezone(timezone.utc)
    go, go_from_path = _resolve_payload(go_payload, P2_GO_PATH, "P2 GO", load_go_payload)
    budget, budget_from_path = _resolve_payload(
        budget_payload, P2_BUDGET_PATH, "共享预算", load_budget_payload
    )
    snapshot = _as_snapshot(ledger_snapshot)
    if Path(snapshot.ledger_path).resolve(strict=False) != Path(P2_LEDGER_PATH).resolve(strict=False):
        raise P2AuthorizationError("snapshot_ledger_path_not_fixed", "快照必须来自固定共享账本")

    preflight = preflight_p2(frozen_plan, snapshot)
    if not preflight.ok:
        raise P2AuthorizationError(preflight.reasons[0], "预检未通过: " + ",".join(preflight.reasons))

    issued, expires = _check_go_payload(go, frozen_plan, moment)
    scope = go["scope"]
    declared_ledger_path = go.get("budget_ledger_path")
    if not isinstance(declared_ledger_path, str) or not declared_ledger_path.strip():
        raise P2AuthorizationError("go_ledger_path_missing", "GO 未声明 budget_ledger_path")
    declared_path = Path(declared_ledger_path.strip())
    if not declared_path.is_absolute():
        declared_path = _REPO_ROOT / declared_path
    if declared_path.resolve(strict=False) != Path(P2_LEDGER_PATH).resolve(strict=False):
        raise P2AuthorizationError("go_ledger_path_not_fixed", "GO 绑定的账本不是固定共享账本")
    bound_hash = _text(
        go.get("budget_ledger_sha256"), "GO budget_ledger_sha256", maximum=64, allow_space=False
    ).lower()
    if bound_hash not in (snapshot.historical_prefix_sha256, snapshot.ledger_sha256):
        raise P2AuthorizationError(
            "go_ledger_binding_mismatch", "GO 未绑定当前共享账本（哈希/历史前缀不匹配）"
        )
    if not ledger_binding_ok(bound_hash, Path(P2_LEDGER_PATH)):
        raise P2AuthorizationError(
            "go_ledger_binding_mismatch", "GO 绑定的账本前缀与当前共享账本不一致"
        )

    allocation = _check_budget_payload(budget, frozen_plan, snapshot)
    env_limit = _env_total_limit()
    if env_limit is not None and abs(env_limit - float(budget["limit_cny"])) > _EPS:
        raise P2AuthorizationError(
            "env_total_limit_mismatch",
            f"{TOTAL_LIMIT_ENV} 必须与正式预算 limit_cny 逐值相等（拒绝放大/缩水预算）",
        )
    if go_from_path and budget_from_path and env_limit is None:
        raise P2AuthorizationError(
            "env_total_limit_missing", f"生产准入必须显式设置 {TOTAL_LIMIT_ENV} 且与预算一致"
        )

    stage_limit = min(
        float(frozen_plan.stage_limit_cny),
        float(scope["stage_limits_cny"][P2_STAGE]),
        allocation,
    )
    stage_remaining = max(0.0, stage_limit - snapshot.p2_stage_accounted_cny)
    center_limits = {
        center: min(
            float(frozen_plan.cost_centers_cny[center]), float(scope["cost_centers_cny"][center])
        )
        for center in COST_CENTERS
    }
    center_remaining = {
        center: max(0.0, center_limits[center] - float(snapshot.p2_center_accounted_cny.get(center, 0.0)))
        for center in COST_CENTERS
    }
    max_requests = frozen_plan.max_requests
    requests_used = int(snapshot.reservation_count)
    return P2Authorization(
        schema_version=P2_AUTHORIZATION_SCHEMA_VERSION,
        stage=P2_STAGE,
        plan_id=frozen_plan.plan_id,
        plan_sha256=frozen_plan.plan_sha256,
        go_document=P2_GO_DOCUMENT,
        go_sha256=payload_sha256(go),
        go_nonce_len=len(str(go["nonce"]).strip()),
        issued_by=str(go["issued_by"]).strip(),
        issued_utc=issued,
        expires_utc=expires,
        ledger_path=str(P2_LEDGER_PATH),
        ledger_sha256=snapshot.historical_prefix_sha256,
        budget_sha256=payload_sha256(budget),
        stage_limit_cny=float(stage_limit),
        stage_remaining_cny=float(stage_remaining),
        cost_center_limits_cny=center_limits,
        center_remaining_cny=center_remaining,
        max_requests=max_requests,
        requests_used=requests_used,
        requests_remaining=(UNLIMITED_REQUESTS if max_requests == UNLIMITED_REQUESTS else max(0, max_requests - requests_used)),
        max_request_cny=float(scope["max_request_cny"]),
        operations=tuple(sorted(frozen_plan.operations)),
        # 生产就绪 = GO/预算来自固定路径 + 环境总上限已核 + 账本快照真的来自固定共享账本。
        production_ready=bool(
            go_from_path and budget_from_path and env_limit is not None and snapshot.production_ready
        ),
    )


def _env_total_limit() -> float | None:
    raw = os.environ.get(TOTAL_LIMIT_ENV)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        raise P2AuthorizationError("env_total_limit_invalid", f"{TOTAL_LIMIT_ENV} 必须是有限正数") from None
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        raise P2AuthorizationError("env_total_limit_invalid", f"{TOTAL_LIMIT_ENV} 必须是有限正数")
    return value


# ---------------------------------------------------------------- 运行门


@dataclass(frozen=True)
class P2RequestTicket:
    """一次在飞请求的资金回执：预留已落账，发送前复核通过后才能发。"""

    reservation: Reservation
    request_id: str
    plan_id: str
    plan_sha256: str
    item_id: str
    operation: str
    cost_center: str
    kind: str
    provider: str
    model: str
    bound_cny: float
    case_id: str
    turn: int
    page: int
    nonce_len: int

    @property
    def reservation_id(self) -> str:
        return self.reservation.reservation_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "request_id": self.request_id,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "item_id": self.item_id,
            "operation": self.operation,
            "cost_center": self.cost_center,
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "bound_cny": round(float(self.bound_cny), 8),
            "case_id": self.case_id,
            "turn": int(self.turn),
            "page": int(self.page),
            "nonce_len": int(self.nonce_len),
        }


def _ledger_kind(item: P2RequestItem) -> str:
    return item.price_profile.kind


def _request_sha(item: P2RequestItem, run_id: str) -> str:
    return payload_sha256(
        {
            "run_id": run_id,
            "item_id": item.item_id,
            "operation": item.operation,
            "case_id": item.case_id,
            "turn": item.turn,
            "page": item.page,
            "requests": item.requests,
        }
    )


def _ledger_reason(exc: BaseException) -> str:
    name = type(exc).__name__
    mapping = {
        "RequestLimitExceeded": "request_limit",
        "BudgetExceeded": "budget_exceeded",
        "BudgetLedgerInvalid": "ledger_refused",
        "BudgetError": "budget_error",
    }
    return mapping.get(name, "ledger_error")


class P2Gate:
    """每次发送前的 P2 门控：串行、自动重试 0、失败即停。

    合法顺序：open -> begin(item_id) -> confirm_before_send(ticket) -> 适配器假/真发送
    -> settle_success(...)/settle_failure(...)。任一步拒绝都不会继续下一笔。
    """

    def __init__(
        self,
        plan: P2RunPlan,
        authorization: P2Authorization,
        ledger: BudgetLedger,
        *,
        budget_payload: Mapping[str, Any],
        go_payload: Mapping[str, Any],
        go_path: Path | None,
        run_id: str,
        now: datetime,
        clock: Any = None,
    ) -> None:
        self._plan = plan
        self._authorization = authorization
        self._ledger = ledger
        self._budget_payload = dict(budget_payload)
        self._go_payload = dict(go_payload)
        self._go_path = go_path
        self._run_id = run_id
        self._clock = clock or _utcnow
        self._lock = threading.Lock()
        self._now_hint: datetime | None = now
        self._pending_center: str | None = None
        self._pending_item: P2RequestItem | None = None
        self._inflight: P2RequestTicket | None = None
        #: T206-LIVE：与主请求同时在飞/先于主请求的**从属尝试**（embedding/rerank/ocr）。
        #: 每次底层尝试都必须单独预留并带成本中心，因此不能复用主 ticket。
        self._attempts: dict[str, P2RequestTicket] = {}
        self._stopped: str | None = None
        self._last_guard_reason: str | None = None
        self._notes: list[str] = []
        self._reserved = 0
        self._sent = 0
        self._reserved_cny = 0.0
        self._settled_cny = 0.0
        self._by_operation: dict[str, int] = {}
        self._by_center_cny: dict[str, float] = {}

    # ------------------------------------------------------------ 构造

    @classmethod
    def open(
        cls,
        plan: P2RunPlan,
        *,
        go_payload: Any = None,
        budget_payload: Any = None,
        ledger_snapshot: Any = None,
        now: datetime | None = None,
        clock: Any = None,
        run_id: str | None = None,
        ledger_path: Any = None,
        budget_path: Any = None,
    ) -> "P2Gate":
        frozen_plan = _as_plan(plan)
        moment = (now or _utcnow()).astimezone(timezone.utc)
        if clock is None:
            # 显式给 now 时冻结时钟（Mock/候选）；生产默认用真实 UTC 时钟。
            clock = _utcnow if now is None else (lambda: moment)
        # None = 用固定路径；显式给路径/内存对象都保留来源标记（生产判定依赖它）。
        go_source = P2_GO_PATH if go_payload is None else go_payload
        budget_source = P2_BUDGET_PATH if budget_payload is None else budget_payload
        go, go_from_path = _resolve_payload(go_source, P2_GO_PATH, "P2 GO", load_go_payload)
        budget, _budget_from_path = _resolve_payload(
            budget_source, P2_BUDGET_PATH, "共享预算", load_budget_payload
        )
        snapshot = (
            read_ledger_snapshot(ledger_path=ledger_path, budget_path=budget_path)
            if ledger_snapshot is None
            else _as_snapshot(ledger_snapshot)
        )
        authorization = authorize_p2(
            frozen_plan,
            go_payload=go_source,
            budget_payload=budget_source,
            ledger_snapshot=snapshot,
            now=moment,
        )
        ledger_file = _require_fixed_file(
            P2_LEDGER_PATH if ledger_path is None else ledger_path, P2_LEDGER_PATH, "共享账本"
        )
        budget_file = _require_fixed_file(
            P2_BUDGET_PATH if budget_path is None else budget_path, P2_BUDGET_PATH, "共享预算"
        )
        # 授权用的预算对象必须就是账本实际读取的那份文件：否则“授权额度”与“真账额度”会分叉。
        file_budget = _load_json_object(budget_file.read_text(encoding="utf-8"), "共享预算")
        if payload_sha256(file_budget) != authorization.budget_sha256:
            raise P2AuthorizationError(
                "budget_file_mismatch", "固定预算文件与本次授权使用的预算对象不一致"
            )
        ledger = BudgetLedger(
            ledger_file,
            budget_file,
            stage=P2_STAGE,
            stage_limit_cny=authorization.stage_limit_cny,
            max_requests=authorization.max_requests,
            run_id=run_id or ("p2run-" + uuid.uuid4().hex),
        )
        gate = cls(
            frozen_plan,
            authorization,
            ledger,
            budget_payload=budget,
            go_payload=go,
            go_path=P2_GO_PATH if go_from_path else None,
            run_id=ledger.run_id or "",
            now=moment,
            clock=clock,
        )
        # 门控回调在预留锁内执行：只能用锁内 facts + 内存/文件读取，不重复加锁。
        ledger._request_guard = gate._request_guard  # noqa: SLF001 - 同一把锁内的受控注入
        ledger._post_reserve_guard = gate._post_reserve_guard  # noqa: SLF001
        return gate

    # ------------------------------------------------------------ 只读属性

    @property
    def authorization(self) -> P2Authorization:
        return self._authorization

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def stopped_reason(self) -> str | None:
        return self._stopped

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(self._notes)

    def policy(self, kind: str) -> SettlementPolicy | None:
        for item in self._plan.items:
            if item.price_profile.kind == kind:
                return item.price_profile.settlement_policy()
        return None

    # ------------------------------------------------------------ 授权重校验

    def _current_go(self) -> dict[str, Any]:
        if self._go_path is not None:
            return load_go_payload(self._go_path)
        return dict(self._go_payload)

    def _assert_authorization_live(self, now: datetime) -> None:
        payload = self._current_go()
        if payload.get("document") != P2_GO_DOCUMENT:
            raise P2GateError("go_document_changed", "GO document 已变")
        scope = payload.get("scope")
        if not isinstance(scope, Mapping):
            raise P2GateError("go_scope_changed", "GO scope 已变")
        if scope.get("plan_id") != self._plan.plan_id:
            raise P2GateError("plan_id_changed", "GO 绑定的 plan_id 与本次计划不一致")
        if str(scope.get("plan_sha256") or "").lower() != self._plan.plan_sha256:
            raise P2GateError("plan_sha256_changed", "计划摘要与 GO 绑定不一致（改计划即失效）")
        expires = _instant(payload.get("expires_utc"), "GO expires_utc")
        if now >= expires:
            raise P2GateError("authorization_expired", "GO 已过期")
        if now < _instant(payload.get("issued_utc"), "GO issued_utc"):
            raise P2GateError("authorization_not_yet_valid", "GO 尚未生效")
        operations = scope.get("operations")
        if not isinstance(operations, list):
            raise P2GateError("go_operations_changed", "GO operations 已变")
        missing = sorted(set(self._plan.operations) - set(operations))
        if missing:
            raise P2GateError("operation_unauthorized", "GO 未授权计划中的操作")
        centers = scope.get("cost_centers_cny")
        if not isinstance(centers, Mapping):
            raise P2GateError("go_cost_center_changed", "GO 成本中心已变")
        for center in COST_CENTERS:
            declared = centers.get(center)
            if isinstance(declared, bool) or not isinstance(declared, (int, float)):
                raise P2GateError("cost_center_unauthorized", f"GO 未授权成本中心 {center}")
            if float(declared) + _EPS < float(self._plan.cost_centers_cny[center]):
                raise P2GateError("cost_center_unauthorized", f"GO 成本中心 {center} 额度低于计划")
        max_requests = scope.get("max_requests")
        try:
            max_requests = request_cap(max_requests, "GO scope.max_requests")
        except P2ContractError:
            raise P2GateError("request_cap_changed", "GO 请求上限已变")
        if max_requests != UNLIMITED_REQUESTS and (max_requests > HARD_MAX_REQUESTS or max_requests < self._plan.total_requests or self._plan.max_requests == UNLIMITED_REQUESTS or self._plan.max_requests > max_requests):
            raise P2GateError("request_cap_changed", "GO 请求上限已变")
        max_request_cny = scope.get("max_request_cny")
        if isinstance(max_request_cny, bool) or not isinstance(max_request_cny, (int, float)):
            raise P2GateError("max_request_cny_changed", "GO 单请求上界已变")
        if float(max_request_cny) + _EPS < self._plan.reserve_peak_cny:
            raise P2GateError("max_request_cny_changed", "GO 单请求上界已变")
        bound = str(payload.get("budget_ledger_sha256") or "").strip().lower()
        if not bound or not ledger_binding_ok(bound, Path(P2_LEDGER_PATH)):
            raise P2GateError("ledger_prefix_mismatch", "共享账本历史前缀与 GO 绑定不一致")

    # ------------------------------------------------------------ 锁内门控

    def _assert_center_room(self, amount: float, facts: Mapping[str, Any]) -> None:
        center = self._pending_center
        if center is None:
            raise P2GateError("cost_center_missing", "本次预留没有成本中心归属")
        limit = float(self._authorization.cost_center_limits_cny[center])
        centers = facts.get("center_accounted")
        if not isinstance(centers, Mapping):
            raise P2GateError("center_accounting_invalid", "账本未给出成本中心事实")
        used = float(centers.get(center, 0.0))
        if used + float(amount) > limit + _EPS:
            raise P2GateError(
                "center_budget_exceeded",
                f"成本中心 {center} 需 {used + float(amount):.8f} 元，上限 {limit:.8f} 元",
            )

    def _assert_center_accounting(self, facts: Mapping[str, Any]) -> None:
        centers = facts.get("center_accounted")
        if not isinstance(centers, Mapping):
            raise P2GateError("center_accounting_invalid", "账本未给出成本中心事实")
        # T203 小加固（T201 遗留 ②）：标签必须 ⊆ COST_CENTERS，别让拼错/伪造的中心既躲开
        # 中心额度、又靠"合计相等"混过归属检查。
        if set(centers) - set(COST_CENTERS):
            raise P2GateError("cost_center_unregistered", "账本含未注册成本中心")
        stage_accounted = float(facts.get("stage_accounted") or 0.0)
        if abs(sum(float(value) for value in centers.values()) - stage_accounted) > _EPS:
            raise P2GateError(
                "center_accounting_inconsistent", "阶段占用无法完整归属到成本中心，拒绝继续"
            )
        if stage_accounted > float(self._authorization.stage_limit_cny) + _EPS:
            raise P2GateError("stage_budget_exceeded", "阶段占用已超过阶段额度")

    def _guard_common(self, now: datetime, facts: Mapping[str, Any]) -> None:
        self._assert_authorization_live(now)
        self._assert_center_accounting(facts)
        count = facts.get("reservation_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise P2GateError("ledger_count_invalid", "账本累计请求数非法")
        if self._authorization.max_requests != UNLIMITED_REQUESTS and count > self._authorization.max_requests:
            raise P2GateError("request_limit", "累计请求数已超过授权上限")

    def _request_guard(self, amount: float, facts: Mapping[str, Any]) -> tuple[float, int | str]:
        from ..rag.errors import BudgetLedgerInvalid

        try:
            now = self._now_hint or self._clock()
            self._guard_common(now, facts)
            self._assert_center_room(amount, facts)
            if self._authorization.max_requests == UNLIMITED_REQUESTS:
                item = self._pending_item
                if item is None:
                    raise P2GateError("item_unknown", "缺少计划项")
                used = 0
                for event in self._ledger._events():  # noqa: SLF001 - called under ledger lock
                    if event.get("event") != "reserved":
                        continue
                    metadata = event.get("metadata")
                    if not isinstance(metadata, Mapping) or not isinstance(metadata.get("plan_sha256"), str):
                        # 账本里必然有更早阶段（S1/S2）的预留，它们不属于本计划，跳过；
                        # 但**同阶段**预留缺计划身份必须拒绝（否则等于给绕过门控的预留开口子）。
                        if event.get("stage") == self._plan.stage:
                            raise P2GateError("run_plan_unknown", "历史预留缺少计划身份")
                        continue
                    # R0-5：按 plan_sha256 + item_id 累计，**不看 run_id**。换 run_id / 重开
                    # gate / 重启进程都读同一份账本事实，不会把计划项次数清零。
                    if metadata["plan_sha256"] != self._plan.plan_sha256:
                        continue
                    if metadata.get("item_id") == item.item_id:
                        used += 1
                if used >= item.requests:
                    raise P2GateError("attempt_quota_exhausted", "计划项请求次数已用完")
        except P2GateError as exc:
            self._last_guard_reason = exc.reason
            raise BudgetLedgerInvalid(f"P2 预留前门控拒绝：{exc.reason}") from None
        return float(self._authorization.stage_limit_cny), self._authorization.max_requests

    def _post_reserve_guard(self, amount: float, facts: Mapping[str, Any]) -> None:
        from ..rag.errors import BudgetLedgerInvalid

        try:
            now = self._now_hint or self._clock()
            self._guard_common(now, facts)
            # 本笔已计入 facts：中心限额按“已计入”复核，不再加一次金额。
            center = self._pending_center
            if center is not None:
                limit = float(self._authorization.cost_center_limits_cny[center])
                used = float((facts.get("center_accounted") or {}).get(center, 0.0))
                if used > limit + _EPS:
                    raise P2GateError("center_budget_exceeded", "预留后复核：成本中心超限")
            if float(amount) > float(self._authorization.max_request_cny) + _EPS:
                raise P2GateError("max_request_cny_exceeded", "预留后复核：单请求上界超限")
        except P2GateError as exc:
            self._last_guard_reason = exc.reason
            raise BudgetLedgerInvalid(f"P2 发送前门控拒绝：{exc.reason}") from None

    # ------------------------------------------------------------ 预留

    def begin(self, item_id: str, *, now: datetime | None = None) -> P2RequestTicket:
        """主请求预留（run 的逐轮请求）：串行，上一笔未结算不得开下一笔。"""
        with self._lock:
            return self._begin_locked(item_id, now=now, nested=False)

    def begin_attempt(self, item_id: str, *, now: datetime | None = None) -> P2RequestTicket:
        """从属尝试预留（T206-LIVE）：embedding / rerank / OCR 每次底层发送各自一笔。

        与 :meth:`begin` 的差别只有三点：①允许在主请求在飞期间登记（产品一次问答内部会
        先查向量/重排、再调模型）；②不占用 ``_inflight`` 槽位，按 reservation_id 单独跟踪；
        ③从属尝试失败同样让整门停止（保守）。成本中心仍来自计划项 —— 计划项不存在或
        成本中心缺失都在预留前拒绝，不会出现"无归属预留"。
        """
        with self._lock:
            return self._begin_locked(item_id, now=now, nested=True)

    def _begin_locked(
        self, item_id: str, *, now: datetime | None, nested: bool
    ) -> P2RequestTicket:
        if self._stopped is not None:
            raise P2GateError("gate_stopped", f"已停止（{self._stopped}），不发起新请求")
        if self._inflight is not None and not nested:
            raise P2GateError("request_inflight", "串行门控：上一笔尚未结算")
        if not isinstance(item_id, str) or not item_id.strip():
            raise P2GateError("item_unknown", "item_id 必须是非空字符串")
        try:
            item = self._plan.item(item_id)
        except P2ContractError:
            raise P2GateError("item_unknown", "计划中没有该 item_id") from None
        moment = (now or self._clock()).astimezone(timezone.utc)
        self._now_hint = moment
        self._pending_center = item.cost_center
        self._pending_item = item
        self._last_guard_reason = None
        try:
            self._assert_authorization_live(moment)
            reservation = self._ledger.reserve(
                kind=_ledger_kind(item),
                provider=item.price_profile.provider,
                model=item.price_profile.model,
                max_cny=item.bound_cny,
                request_sha256=_request_sha(item, self._run_id),
                settlement_policy=item.price_profile.settlement_policy(),
                metadata={
                    "plan_id": self._plan.plan_id,
                    "plan_sha256": self._plan.plan_sha256,
                    "item_id": item.item_id,
                    "operation": item.operation,
                    "cost_center": item.cost_center,
                },
                cost_center=item.cost_center,
                stage_limit_cny=self._authorization.stage_limit_cny,
                max_requests=self._authorization.max_requests,
            )
        except BudgetError as exc:
            reason = self._last_guard_reason or _ledger_reason(exc)
            raise P2GateError(reason, type(exc).__name__) from None
        finally:
            self._pending_center = None
            self._pending_item = None
        ticket = P2RequestTicket(
            reservation=reservation,
            request_id="p2req-" + hashlib.sha256(
                (self._run_id + ":" + item.item_id).encode("utf-8")
            ).hexdigest()[:24],
            plan_id=self._plan.plan_id,
            plan_sha256=self._plan.plan_sha256,
            item_id=item.item_id,
            operation=item.operation,
            cost_center=item.cost_center,
            kind=_ledger_kind(item),
            provider=item.price_profile.provider,
            model=item.price_profile.model,
            bound_cny=float(item.bound_cny),
            case_id=item.case_id,
            turn=item.turn,
            page=item.page,
            nonce_len=self._authorization.go_nonce_len,
        )
        if nested:
            self._attempts[ticket.reservation_id] = ticket
        else:
            self._inflight = ticket
        self._reserved += 1
        self._reserved_cny += float(ticket.bound_cny)
        return ticket

    # ------------------------------------------------------------ 发送前后

    def _require_inflight(self, ticket: Any) -> bool:
        """校验 ticket 属于本门控，并返回它是否为**从属尝试**（T206-LIVE）。

        主请求在 ``_inflight`` 槽位；从属尝试（embedding/rerank/ocr）按 reservation_id
        记在 ``_attempts`` 里，二者都必须是本门开出的真实预留。
        """
        if not isinstance(ticket, P2RequestTicket):
            raise P2GateError("ticket_invalid", "需要 P2RequestTicket")
        reservation_id = ticket.reservation_id
        if reservation_id in self._attempts:
            return True
        if self._inflight is not None and self._inflight.reservation_id == reservation_id:
            return False
        raise P2GateError("ticket_not_inflight", "该预留在本门控中不处于在飞状态")

    def _release_slot(self, ticket: P2RequestTicket, *, nested: bool) -> None:
        if nested:
            self._attempts.pop(ticket.reservation_id, None)
        else:
            self._inflight = None

    def _refuse_before_send(self, ticket: P2RequestTicket, code: str, *, nested: bool = False) -> None:
        """预留已发生但发送前失效：保守留账（status=failed，全额占用），保留请求身份。"""
        try:
            self._ledger.settle(
                ticket.reservation,
                status="failed",
                error_code=f"P2_PRE_SEND_REFUSED:{code}",
                http_status=None,
                request_id=ticket.request_id,
                elapsed_seconds=0.0,
            )
        except BudgetError:
            # 结算写不进去也不释放：预留保持原额占用（保守），并记录一条稳定说明。
            self._notes.append("pre_send_settle_failed")
        self._settled_cny += float(ticket.bound_cny)
        self._by_center_cny[ticket.cost_center] = (
            self._by_center_cny.get(ticket.cost_center, 0.0) + float(ticket.bound_cny)
        )
        self._release_slot(ticket, nested=nested)
        self._stopped = code

    def confirm_before_send(self, ticket: P2RequestTicket, *, now: datetime | None = None) -> P2RequestTicket:
        with self._lock:
            nested = self._require_inflight(ticket)
            moment = (now or self._clock()).astimezone(timezone.utc)
            self._now_hint = moment
            self._pending_center = None
            try:
                self._assert_authorization_live(moment)
                self._ledger.recheck_reservation(ticket.reservation)
            except P2GateError as exc:
                self._refuse_before_send(ticket, exc.reason, nested=nested)
                raise P2SendRefused(exc.reason, ticket=ticket) from None
            except BudgetError as exc:
                code = "pre_send_" + _ledger_reason(exc)
                self._refuse_before_send(ticket, code, nested=nested)
                raise P2SendRefused(code, ticket=ticket) from None
            finally:
                self._pending_center = None
            return ticket

    def settle_success(
        self,
        ticket: P2RequestTicket,
        *,
        evidence: UsageEvidence | None = None,
        usage: Mapping[str, int] | None = None,
        estimated_cny: float | None = None,
        elapsed_seconds: float | None = None,
    ) -> float:
        """成功结算：按 J1 版本化 usage 释放未用预留；OCR 按固定价结算。"""
        with self._lock:
            nested = self._require_inflight(ticket)
            item = self._plan.item(ticket.item_id)
            policy = item.price_profile.settlement_policy()
            try:
                if policy is not None:
                    if not isinstance(evidence, UsageEvidence):
                        raise P2GateError("evidence_required", "版本化结算需要 UsageEvidence")
                    decision = self._ledger.settle_usage(
                        ticket.reservation,
                        evidence=evidence,
                        request_id=ticket.request_id,
                        elapsed_seconds=elapsed_seconds,
                    )
                    charge = float(decision.charge_cny)
                else:
                    amount = (
                        float(ticket.bound_cny)
                        if estimated_cny is None
                        else float(estimated_cny)
                    )
                    if amount <= 0 or amount > float(ticket.bound_cny) + _EPS:
                        raise P2GateError("estimate_out_of_bound", "OCR 结算金额必须在 (0, 上界] 内")
                    self._ledger.settle(
                        ticket.reservation,
                        status="succeeded",
                        usage=usage,
                        estimated_list_price_cny=amount,
                        request_id=ticket.request_id,
                        elapsed_seconds=elapsed_seconds,
                    )
                    charge = max(amount, float(ticket.bound_cny))
            except P2GateError:
                raise
            except BudgetError as exc:
                self._stopped = _ledger_reason(exc)
                raise P2GateError(self._stopped, type(exc).__name__) from None
            self._release_slot(ticket, nested=nested)
            self._sent += 1
            self._settled_cny += charge
            self._by_operation[ticket.operation] = self._by_operation.get(ticket.operation, 0) + 1
            self._by_center_cny[ticket.cost_center] = (
                self._by_center_cny.get(ticket.cost_center, 0.0) + charge
            )
            return charge

    def settle_failure(
        self,
        ticket: P2RequestTicket,
        *,
        error_code: str,
        status: str = "failed",
        http_status: int | None = None,
        elapsed_seconds: float | None = None,
    ) -> None:
        """失败/超时/未知：保守留账并**停止**后续付费（自动重试恒为 0）。"""
        with self._lock:
            nested = self._require_inflight(ticket)
            try:
                self._ledger.settle(
                    ticket.reservation,
                    status=status,
                    error_code=error_code,
                    http_status=http_status,
                    request_id=ticket.request_id,
                    elapsed_seconds=elapsed_seconds,
                )
            except BudgetError:
                self._notes.append("failure_settle_failed")
            self._release_slot(ticket, nested=nested)
            self._sent += 1
            self._settled_cny += float(ticket.bound_cny)
            self._by_center_cny[ticket.cost_center] = (
                self._by_center_cny.get(ticket.cost_center, 0.0) + float(ticket.bound_cny)
            )
            self._stopped = error_code

    def close_unused(self, ticket: P2RequestTicket, *, reason: str = "no_paid_attempt") -> None:
        """预留后**没有发生任何发送**：保守留账、保留请求身份，但**不停止**后续请求。

        唯一允许的零发送场景是产品自己给出零付费结局（合法拒答/澄清/未找到/知识变更）：
        此时既不能伪造 usage 去"释放"预留（J1 禁止），也不该把一次合法拒答当成付费失败。
        因此写一条 ``status=failed`` + ``P2_NO_PAID_ATTEMPT:<reason>`` 的 result，全额保守
        占用该笔上界（不回 0、不释放），后续请求继续走同一门控；失败/超时仍用
        :meth:`settle_failure` 并停止。
        """
        with self._lock:
            nested = self._require_inflight(ticket)
            try:
                self._ledger.settle(
                    ticket.reservation,
                    status="failed",
                    error_code=f"P2_NO_PAID_ATTEMPT:{reason}",
                    http_status=None,
                    request_id=ticket.request_id,
                    elapsed_seconds=0.0,
                )
            except BudgetError:
                self._notes.append("unused_settle_failed")
            self._release_slot(ticket, nested=nested)
            self._settled_cny += float(ticket.bound_cny)
            self._by_center_cny[ticket.cost_center] = (
                self._by_center_cny.get(ticket.cost_center, 0.0) + float(ticket.bound_cny)
            )

    def abort(self, code: str) -> None:
        with self._lock:
            self._notes.append(f"abort:{code}")
            if self._stopped is None:
                self._stopped = code

    # ------------------------------------------------------------ 回执

    def result(self, *, status: str | None = None) -> P2RunResult:
        with self._lock:
            final = status or ("succeeded" if self._stopped is None else "blocked")
            return P2RunResult(
                schema_version=P2_RUN_RESULT_SCHEMA_VERSION,
                run_id=self._run_id,
                plan_id=self._plan.plan_id,
                plan_sha256=self._plan.plan_sha256,
                status=final,
                stop_code=self._stopped,
                requests_planned=int(self._plan.total_requests),
                requests_reserved=int(self._reserved),
                requests_sent=int(self._sent),
                reserved_cny=float(self._reserved_cny),
                settled_cny=float(self._settled_cny),
                by_operation=dict(self._by_operation),
                by_center_cny={center: float(self._by_center_cny.get(center, 0.0)) for center in COST_CENTERS},
                production_ready=bool(self._authorization.production_ready),
            )
