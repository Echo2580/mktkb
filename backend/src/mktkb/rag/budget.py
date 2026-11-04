"""跨进程共享预算账本（LOCAL-R1）。

语义：
- 每次真实请求先原子预留一个覆盖最坏计费量的金额；预留失败即停止，不发请求。
- 成功/失败/超时/结果不明都保留结果事件；保守占用默认等于预留额，不因失败自动退款。
- `estimated_list_price_cny` 只按 usage 与官方标价估算，和保守占用、供应商账单分开。
- 历史 0.03 元只从既有 `historical_import` 事件读取一次，不重置、不重复导入。
- 锁使用 O_CREAT|O_EXCL 锁文件，跨线程/跨进程有效；崩溃遗留按时间判定 stale。
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from ..numeric import (
    NumericInvalid,
    finite_non_negative,
    finite_positive,
    positive_int,
)
from .errors import BudgetError, BudgetExceeded, BudgetLedgerInvalid, RequestLimitExceeded
from .settlement_policy import (
    SETTLEMENT_VERSION,
    SettlementDecision,
    SettlementPolicy,
    SettlementPolicyError,
    UsageEvidence,
    evaluate_settlement,
    evidence_snapshot_json,
    policy_from_snapshot,
    policy_to_snapshot,
    sanitize_settlement_reason,
    sanitize_usage_for_kind,
    usage_evidence_from_settlement_block,
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(text: str) -> str:
    """移除常见凭据形态；用于日志/诊断，不用于请求头。"""
    value = str(text)
    value = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}***", value)
    value = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}***", value)
    value = _SECRET_PATTERNS[2].sub("sk-***", value)
    return value


def redact_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in ("key", "secret", "token", "authorization", "password")):
            cleaned[str(key)] = "***"
        elif isinstance(value, str):
            cleaned[str(key)] = redact(value)
        else:
            cleaned[str(key)] = value
    return cleaned


def _clean_usage(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """只保留 int（bool 不算）、非负的 usage 计数；非法字段不写入日志/账本。"""
    clean: dict[str, int] = {}
    for key, value in dict(usage or {}).items():
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            clean[str(key)] = value
    return clean


class SettlementNotReleasable(BudgetError):
    """版本化结算拒绝释放：保持该笔预留全额占用，调用方必须停止。"""

    code = "SETTLEMENT_NOT_RELEASABLE"

    def __init__(
        self,
        message: str,
        *,
        reservation_id: str | None = None,
        reason: str | None = None,
        conservative_charge_cny: float | None = None,
    ) -> None:
        super().__init__(message)
        self.reservation_id = reservation_id
        self.reason = reason
        self.conservative_charge_cny = conservative_charge_cny


class SettlementBoundaryAnomaly(BudgetError):
    """重算金额高于预留：按更高保守额入账并标边界异常，调用方必须停止。"""

    code = "SETTLEMENT_BOUNDARY_ANOMALY"

    def __init__(
        self,
        message: str,
        *,
        reservation_id: str | None = None,
        recomputed_charge_cny: float | None = None,
        reserve_cny: float | None = None,
    ) -> None:
        super().__init__(message)
        self.reservation_id = reservation_id
        self.recomputed_charge_cny = recomputed_charge_cny
        self.reserve_cny = reserve_cny


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    stage: str
    kind: str
    provider: str
    model: str
    reserve_cny: float
    request_sha256: str
    created_utc: str


@dataclass(frozen=True)
class BudgetSummary:
    total_limit_cny: float
    historical_conservative_cny: float
    accounted_cny: float
    remaining_cny: float
    stage: str
    stage_limit_cny: float
    stage_accounted_cny: float
    stage_remaining_cny: float
    success_estimated_list_price_cny: float
    provider_billed_cny: float | None
    reservation_count: int
    result_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_limit_cny": round(self.total_limit_cny, 8),
            "historical_conservative_cny": round(self.historical_conservative_cny, 8),
            "accounted_cny": round(self.accounted_cny, 8),
            "remaining_cny": round(self.remaining_cny, 8),
            "stage": self.stage,
            "stage_limit_cny": round(self.stage_limit_cny, 8),
            "stage_accounted_cny": round(self.stage_accounted_cny, 8),
            "stage_remaining_cny": round(self.stage_remaining_cny, 8),
            "success_estimated_list_price_cny": round(self.success_estimated_list_price_cny, 10),
            "provider_billed_cny": self.provider_billed_cny,
            "reservation_count": self.reservation_count,
            "result_count": self.result_count,
        }


def _ledger_non_negative_int(value: Any, label: str) -> int:
    """非负整数；bool 不算整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetLedgerInvalid(f"{label} 必须是非负整数")
    if value < 0:
        raise BudgetLedgerInvalid(f"{label} 不得为负数")
    return value


def _ledger_number(value: Any, label: str) -> float:
    try:
        return finite_positive(value, label)
    except NumericInvalid as exc:
        raise BudgetLedgerInvalid(str(exc)) from None


def _ledger_non_negative(value: Any, label: str) -> float:
    try:
        return finite_non_negative(value, label)
    except NumericInvalid as exc:
        raise BudgetLedgerInvalid(str(exc)) from None


def _ledger_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    try:
        return positive_int(value, label, maximum=maximum)
    except NumericInvalid as exc:
        raise BudgetLedgerInvalid(str(exc)) from None


def _parse_json_object(raw: str, label: str) -> Any:
    """严格 JSON：拒绝 NaN/Infinity 等非标准常量（账本/预算不允许）。"""

    def _reject_constant(value: str) -> Any:
        raise ValueError(f"{label} 含非标准 JSON 常量 {value}")

    return json.loads(raw, parse_constant=_reject_constant)


class BudgetLedger:
    """一个账本文件 + 一个预算文件；所有读写经文件锁串行化。"""

    def __init__(
        self,
        ledger_path: Path | str,
        budget_json_path: Path | str,
        *,
        stage: str = "S1-DEV",
        stage_limit_cny: float = 3.0,
        lock_timeout_seconds: float = 10.0,
        stale_lock_seconds: float = 60.0,
        max_requests: int = 0,
        run_id: str | None = None,
        request_guard: Callable[[float, Mapping[str, Any]], tuple[float, int]] | None = None,
        post_reserve_guard: Callable[[float, Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.ledger_path = Path(ledger_path)
        self.budget_json_path = Path(budget_json_path)
        self.stage = stage
        self.stage_limit_cny = _ledger_number(stage_limit_cny, "stage_limit_cny")
        if isinstance(max_requests, bool) or not isinstance(max_requests, int):
            raise BudgetLedgerInvalid("max_requests 必须是非负整数")
        if max_requests < 0:
            raise BudgetLedgerInvalid("max_requests 必须是非负整数")
        self.max_requests = max_requests
        # 请求期复核回调（由产品 LiveGate 注入）：参数为 (本次预留金额, 锁内账本事实)。
        # 旧调用者不传，行为保持不变；产品路径每次预留前都重新校验 GO/预算。
        self._request_guard = request_guard
        # 预留成功后、真实发送前的第二次复核回调（同样由 LiveGate 注入）。参数为
        # (本笔预留金额, 已包含本笔的锁内账本事实)；回调只做拒绝/放行，不写账本。
        # 未传时旧调用者（S1 实验/既有单测）行为不变。
        self._post_reserve_guard = post_reserve_guard
        # 本轮运行归属：在锁内与预留一并落盘，因此“预留已持久化但 reserve 未返回”
        # 也能在事后认领（R6-2）。旧账行没有该字段，读取时按兼容处理。
        self.run_id = str(run_id) if run_id else None
        self.lock_path = self.ledger_path.with_name(self.ledger_path.name + ".lock")
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        self.stale_lock_seconds = float(stale_lock_seconds)
        self._budget = self._load_budget()
        self.total_limit_cny = _ledger_number(self._budget.get("limit_cny"), "budget.json limit_cny")
        stages = self._budget.get("stages")
        if stages is not None and not isinstance(stages, dict):
            raise BudgetLedgerInvalid("budget.json stages 必须是对象")
        stage_from_file = (stages or {}).get(self.stage)
        if stage_from_file is not None:
            self.stage_limit_cny = min(
                self.stage_limit_cny, _ledger_number(stage_from_file, f"budget.json stages.{self.stage}")
            )

    def _load_budget(self) -> dict[str, Any]:
        if not self.budget_json_path.exists():
            raise BudgetLedgerInvalid(f"预算文件不存在：{self.budget_json_path.name}")
        try:
            data = _parse_json_object(
                self.budget_json_path.read_text(encoding="utf-8"), "预算文件"
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise BudgetLedgerInvalid("预算文件不可读或不是 JSON") from exc
        if not isinstance(data, dict):
            raise BudgetLedgerInvalid("预算文件顶层必须是对象")
        return data

    # ---------------------------------------------------------------- 锁与事件

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        fd: int | None = None
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {utcnow_iso()}\n".encode("utf-8"))
                os.close(fd)
                fd = None
                break
            except FileExistsError:
                if self._stale_lock():
                    try:
                        self.lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise BudgetLedgerInvalid("预算账本锁超时，未发请求")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _stale_lock(self) -> bool:
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age > self.stale_lock_seconds

    def _events(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            raise BudgetLedgerInvalid(f"预算账本不存在：{self.ledger_path.name}")
        events: list[dict[str, Any]] = []
        try:
            with self.ledger_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        event = _parse_json_object(text, f"预算账本第 {line_number} 行")
                    except (json.JSONDecodeError, ValueError) as exc:
                        raise BudgetLedgerInvalid(f"预算账本第 {line_number} 行不是 JSON") from exc
                    if not isinstance(event, dict) or not event.get("event"):
                        raise BudgetLedgerInvalid(f"预算账本第 {line_number} 行缺少 event")
                    events.append(event)
        except OSError as exc:
            raise BudgetLedgerInvalid("预算账本不可读") from exc
        return events

    def _append(self, event: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":")) + "\n"
        fd = os.open(str(self.ledger_path), os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        try:
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def _accounting(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        historical = 0.0
        success_estimate = 0.0
        provider_billed: float | None = None
        reservations: dict[str, dict[str, Any]] = {}
        results: dict[str, dict[str, Any]] = {}
        for event in events:
            kind = event.get("event")
            if kind == "historical_import":
                historical += _ledger_non_negative(
                    event.get("accounted_cny") or 0.0, "historical_import.accounted_cny"
                )
            elif kind == "reserved":
                reservation_id = str(event.get("reservation_id") or "")
                if not reservation_id:
                    raise BudgetLedgerInvalid("reserved 事件缺少 reservation_id")
                if reservation_id in reservations:
                    raise BudgetLedgerInvalid("重复的 reservation_id")
                reservations[reservation_id] = event
            elif kind == "result":
                reservation_id = str(event.get("reservation_id") or "")
                if not reservation_id:
                    raise BudgetLedgerInvalid("result 事件缺少 reservation_id")
                if reservation_id in results:
                    raise BudgetLedgerInvalid("同一 reservation_id 有重复 result")
                results[reservation_id] = event
        accounted = historical
        stage_accounted = 0.0
        for reservation_id, reserved in reservations.items():
            reserve_cny = _ledger_non_negative(
                reserved.get("reserve_cny") or 0.0, "reserved.reserve_cny"
            )
            # 畸形/未知快照 fail closed：即使尚未结算，summary 重放也不能默默接受。
            snapshot = reserved.get("settlement_policy")
            if snapshot is not None:
                try:
                    policy_from_snapshot(snapshot)
                except SettlementPolicyError as exc:
                    raise BudgetLedgerInvalid(f"settlement_policy 快照非法：{exc}") from None
            result = results.get(reservation_id)
            if result is not None and "settlement" in result:
                # 版本化分支：不盲信事件里的低 charge，独立校验快照/证据/绑定并重算。
                charge, estimate = self._replay_versioned_result(reserved, result, reserve_cny)
                accounted += charge
                if reserved.get("stage") == self.stage:
                    stage_accounted += charge
                success_estimate += estimate
                continue
            if result is not None:
                charge = _ledger_non_negative(
                    result.get("conservative_charge_cny") or 0.0,
                    "result.conservative_charge_cny",
                )
                charge = max(charge, reserve_cny)
            else:
                charge = reserve_cny
            accounted += charge
            if reserved.get("stage") == self.stage:
                stage_accounted += charge
            if result is not None:
                success_estimate += _ledger_non_negative(
                    result.get("estimated_list_price_cny") or 0.0,
                    "result.estimated_list_price_cny",
                )
                billed = result.get("provider_billed_cny")
                if billed is not None:
                    provider_billed = (provider_billed or 0.0) + _ledger_non_negative(
                        billed, "result.provider_billed_cny"
                    )
        # 没有对应 reserved 的 result 仍按保守占用计入，不能静默丢掉失败记录。
        for reservation_id, result in results.items():
            if reservation_id in reservations:
                continue
            if "settlement" in result:
                # 版本化 result 无法关联预留 ⇒ 不能独立重算，显式拒绝而不是盲信低 charge。
                raise BudgetLedgerInvalid("版本化 result 缺少对应预留，拒绝重放")
            charge = _ledger_non_negative(
                result.get("conservative_charge_cny") or 0.0,
                "孤立 result 的 conservative_charge_cny",
            )
            accounted += charge
            if result.get("stage") == self.stage:
                stage_accounted += charge
        return {
            "historical": historical,
            "accounted": accounted,
            "stage_accounted": stage_accounted,
            "success_estimate": success_estimate,
            "provider_billed": provider_billed,
            "reservation_count": len(reservations),
            "result_count": len(results),
        }

    @staticmethod
    def _replay_versioned_result(
        reserved: Mapping[str, Any],
        result: Mapping[str, Any],
        reserve_cny: float,
    ) -> tuple[float, float]:
        """独立重放一条版本化 result：重建 policy/evidence、再校验、再重算。"""
        snapshot = reserved.get("settlement_policy")
        if snapshot is None:
            raise BudgetLedgerInvalid("版本化 result 的预留缺少 settlement_policy 快照")
        try:
            policy = policy_from_snapshot(snapshot)
            evidence, declared = usage_evidence_from_settlement_block(result.get("settlement"))
        except SettlementPolicyError as exc:
            raise BudgetLedgerInvalid(f"版本化结算重放结构非法：{exc}") from None
        if result.get("status") != "succeeded":
            raise BudgetLedgerInvalid("版本化 result 的 status 必须是 succeeded")
        for key in ("kind", "provider", "model"):
            if result.get(key) != reserved.get(key):
                raise BudgetLedgerInvalid("版本化 result 与预留的绑定字段不一致")
        if result.get("provider_billed_cny") is not None:
            raise BudgetLedgerInvalid("J1 版本化 result 不允许供应商账单金额")
        decision = evaluate_settlement(
            policy, reserved=reserved, evidence=evidence, reserve_cny=reserve_cny
        )
        if not decision.accepted:
            # S2-J1-R2 F-2：重放异常文本里的 reason 同样走白名单兜底，不回显原文。
            raise BudgetLedgerInvalid(
                f"版本化 result 重放不合格：{sanitize_settlement_reason(decision.reason)}"
            )
        if declared != decision.charge_cny:
            raise BudgetLedgerInvalid("版本化 result 声明金额与独立重算不一致")
        stored_charge = _ledger_non_negative(
            result.get("conservative_charge_cny") or 0.0,
            "版本化 result.conservative_charge_cny",
        )
        if stored_charge != float(decision.charge_cny):
            raise BudgetLedgerInvalid("版本化 result 的 conservative_charge_cny 与重算不一致")
        stored_estimate = _ledger_non_negative(
            result.get("estimated_list_price_cny") or 0.0,
            "版本化 result.estimated_list_price_cny",
        )
        if stored_estimate != float(decision.estimated_list_price_cny):
            raise BudgetLedgerInvalid("版本化 result 的 estimated_list_price_cny 与重算不一致")
        return float(decision.charge_cny), float(decision.estimated_list_price_cny)

    def summary(self) -> BudgetSummary:
        with self._locked():
            events = self._events()
            facts = self._accounting(events)
        remaining = max(0.0, self.total_limit_cny - facts["accounted"])
        stage_remaining = max(0.0, self.stage_limit_cny - facts["stage_accounted"])
        return BudgetSummary(
            total_limit_cny=self.total_limit_cny,
            historical_conservative_cny=facts["historical"],
            accounted_cny=facts["accounted"],
            remaining_cny=remaining,
            stage=self.stage,
            stage_limit_cny=self.stage_limit_cny,
            stage_accounted_cny=facts["stage_accounted"],
            stage_remaining_cny=stage_remaining,
            success_estimated_list_price_cny=facts["success_estimate"],
            provider_billed_cny=facts["provider_billed"],
            reservation_count=facts["reservation_count"],
            result_count=facts["result_count"],
        )

    def reserve(
        self,
        *,
        kind: str,
        provider: str,
        model: str,
        max_cny: float,
        request_sha256: str,
        settlement_policy: SettlementPolicy | None = None,
        metadata: Mapping[str, Any] | None = None,
        stage_limit_cny: float | None = None,
        max_requests: int | None = None,
    ) -> Reservation:
        amount = _ledger_number(max_cny, "预留金额")
        # S2-J1：新结算版本必须在**预留时**固化 policy/caps/费率/来源绑定快照；
        # 未显式传入的旧预留完全不改变事件结构，默认仍按 max(reserve,charge)。
        settlement_snapshot: dict[str, Any] | None = None
        if settlement_policy is not None:
            if not isinstance(settlement_policy, SettlementPolicy):
                raise BudgetLedgerInvalid("settlement_policy 必须是 SettlementPolicy 实例")
            if (
                settlement_policy.kind != kind
                or settlement_policy.provider != provider
                or settlement_policy.model != model
            ):
                raise BudgetLedgerInvalid("settlement_policy 与本次预留 kind/provider/model 不一致，拒绝预留")
            try:
                settlement_snapshot = policy_to_snapshot(settlement_policy)
            except SettlementPolicyError as exc:
                raise BudgetLedgerInvalid(f"settlement_policy 非法：{exc}") from None
        effective_stage_limit = (
            self.stage_limit_cny
            if stage_limit_cny is None
            else _ledger_number(stage_limit_cny, "请求期阶段额度")
        )
        effective_max_requests = (
            self.max_requests
            if max_requests is None
            else _ledger_non_negative_int(max_requests, "请求期累计请求上限")
        )
        with self._locked():
            events = self._events()
            facts = self._accounting(events)
            if self._request_guard is not None:
                # 请求期授权/预算复核与本次预留同一把锁：不重启也必须按当前 GO/预算收窄。
                guarded_limit, guarded_requests = self._request_guard(amount, facts)
                effective_stage_limit = min(
                    effective_stage_limit, _ledger_number(guarded_limit, "复核后的阶段额度")
                )
                effective_max_requests = min(
                    effective_max_requests,
                    _ledger_non_negative_int(guarded_requests, "复核后的累计请求上限"),
                )
            if facts["reservation_count"] >= effective_max_requests:
                raise RequestLimitExceeded(
                    f"请求数达到硬上限 {effective_max_requests}，未发请求"
                )
            remaining = self.total_limit_cny - facts["accounted"]
            stage_remaining = effective_stage_limit - facts["stage_accounted"]
            if amount > remaining + 1e-12:
                raise BudgetExceeded(
                    f"总预算不足：需预留 {amount:.6f} 元，剩余 {max(0.0, remaining):.6f} 元"
                )
            if amount > stage_remaining + 1e-12:
                raise BudgetExceeded(
                    f"阶段 {self.stage} 预算不足：需预留 {amount:.6f} 元，"
                    f"剩余 {max(0.0, stage_remaining):.6f} 元"
                )
            reservation = Reservation(
                reservation_id=uuid.uuid4().hex,
                stage=self.stage,
                kind=kind,
                provider=provider,
                model=model,
                reserve_cny=amount,
                request_sha256=request_sha256,
                created_utc=utcnow_iso(),
            )
            event: dict[str, Any] = {
                "event": "reserved",
                "reservation_id": reservation.reservation_id,
                "stage": self.stage,
                "kind": kind,
                "provider": provider,
                "model": model,
                "reserve_cny": round(amount, 8),
                "request_sha256": request_sha256,
                "prior_accounted_cny": round(facts["accounted"], 8),
                "stage_accounted_cny": round(facts["stage_accounted"], 8),
                "total_limit_cny": self.total_limit_cny,
                "stage_limit_cny": round(effective_stage_limit, 8),
                "time_utc": reservation.created_utc,
            }
            if self.run_id:
                event["run_id"] = self.run_id
            if settlement_snapshot is not None:
                # 白名单快照：计数/价格/来源绑定，不经通用 redactor，也不含任何 secret。
                event["settlement_policy"] = settlement_snapshot
            if metadata:
                event["metadata"] = redact_mapping(metadata)
            self._append(event)
        return reservation

    def recheck_reservation(self, reservation: Reservation) -> None:
        """预留成功后、真实 HTTP 发送前的第二次授权/预算复核。

        - 只读：不新增预留、不改账本、不清账、不退款，保留原 ``reservation_id``；
        - 在同一把账本锁内重算事实，``facts`` 已包含本笔预留（及其保守占用），
          因此不会把本笔重复计入；
        - 未注入 ``post_reserve_guard`` 的旧调用者直接返回，行为不变；
        - 拒绝统一抛 ``BudgetLedgerInvalid``，调用方必须在 POST 之前停住。
        """
        if self._post_reserve_guard is None:
            return
        amount = _ledger_number(reservation.reserve_cny, "复核预留金额")
        with self._locked():
            events = self._events()
            facts = self._accounting(events)
            if not any(
                event.get("event") == "reserved"
                and event.get("reservation_id") == reservation.reservation_id
                for event in events
            ):
                raise BudgetLedgerInvalid("发送前复核找不到本次预留记录，禁发")
            self._post_reserve_guard(amount, facts)

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
        if status not in ("succeeded", "failed", "timeout", "unknown"):
            raise BudgetLedgerInvalid("settle.status 非法")
        estimated = _ledger_non_negative(
            estimated_list_price_cny or 0.0, "estimated_list_price_cny"
        )
        reserved_cny = _ledger_non_negative(reservation.reserve_cny, "reservation.reserve_cny")
        charge = max(reserved_cny, estimated)
        if provider_billed_cny is not None:
            provider_billed_cny = _ledger_non_negative(
                provider_billed_cny, "provider_billed_cny"
            )
        clean_usage = _clean_usage(usage)
        event: dict[str, Any] = {
            "event": "result",
            "reservation_id": reservation.reservation_id,
            "stage": reservation.stage,
            "kind": reservation.kind,
            "provider": reservation.provider,
            "model": reservation.model,
            "status": status,
            "http_status": http_status,
            "request_id": request_id,
            "error_code": error_code,
            "usage": clean_usage or None,
            "estimated_list_price_cny": round(estimated, 10),
            "conservative_charge_cny": round(charge, 8),
            "provider_billed_cny": provider_billed_cny,
            "elapsed_seconds": round(float(elapsed_seconds), 3) if elapsed_seconds is not None else None,
            "dimensions": list(dimensions) if dimensions else None,
            "time_utc": utcnow_iso(),
        }
        if self.run_id:
            event["run_id"] = self.run_id
        with self._locked():
            events = self._events()
            existing = {
                str(event.get("reservation_id"))
                for event in events
                if event.get("event") == "result"
            }
            if reservation.reservation_id in existing:
                raise BudgetLedgerInvalid("该 reservation 已结算，不能重复记账")
            self._append(event)
        return event

    # ------------------------------------------------------- 版本化成功 usage 结算

    def settle_usage(
        self,
        reservation: Reservation,
        *,
        evidence: UsageEvidence,
        request_id: str | None = None,
        elapsed_seconds: float | None = None,
        dimensions: tuple[int, ...] | None = None,
    ) -> SettlementDecision:
        """S2-J1 版本化成功 usage 结算（Mock-only 核心）。

        与旧 ``settle`` 的边界：
        - 旧 ``settle`` 原样保留：无版本结果一律 ``max(reserve, charge)``，不释放；
        - 本方法只接受“预留时已固化 settlement_policy 快照”的预留，否则拒绝；
        - 同一把账本锁内：查同 reservation_id 的 reserved 事件 → 校验绑定 → 逐字段
          校验 usage/版本/来源/cap → Decimal 重算 → 拒重复 result → append-only 追加；
        - 只有合法新版本、成功且证据完整一致的结果可按重算额减少同一笔未用预留；
          ``reserved`` 原金额保留，不追加退款事件，不影响历史事件与请求数；
        - 不合格：保持全额，追加 ``status=unknown`` 的保守 result，再抛
          ``SettlementNotReleasable``（停止信号），不吞异常、不记成功；拒绝
          result 的 ``usage`` 只写该 kind 白名单计数字段、``error_code`` 只用稳定
          reason 码，未知键名/值/嵌套/凭据形态串不持久化（S2-J1-R1 D-1）；
          非法 policy 快照的异常文本只给稳定错误类别、不回显快照原文
          （S2-J1-R2 F-1）；拒绝 reason 全部经白名单/安全兜底后才写入事件与异常
          （S2-J1-R2 F-2）；
        - 重算额高于预留：按更高保守额入账并标 ``boundary_anomaly``，抛
          ``SettlementBoundaryAnomaly``（停止信号），绝不用 min 掩盖。
        """
        if not isinstance(reservation, Reservation):
            raise BudgetLedgerInvalid("settle_usage 需要 Reservation 实例")
        if not isinstance(evidence, UsageEvidence):
            raise BudgetLedgerInvalid("settle_usage 需要 UsageEvidence 实例")
        decision: SettlementDecision | None = None
        boundary: SettlementBoundaryAnomaly | None = None
        rejection: SettlementNotReleasable | None = None
        with self._locked():
            events = self._events()
            reserved: dict[str, Any] | None = None
            for event in events:
                if (
                    event.get("event") == "reserved"
                    and event.get("reservation_id") == reservation.reservation_id
                ):
                    reserved = event
                    break
            if reserved is None:
                raise BudgetLedgerInvalid("结算找不到对应预留记录，拒绝（孤立 result 不能减占用）")
            if any(
                event.get("event") == "result"
                and event.get("reservation_id") == reservation.reservation_id
                for event in events
            ):
                raise BudgetLedgerInvalid("该 reservation 已结算，不能重复记账")
            for key in ("kind", "provider", "model"):
                if reserved.get(key) != getattr(reservation, key):
                    raise BudgetLedgerInvalid("结算对象与账本预留的绑定字段不一致，拒绝")
            for key in ("kind", "provider", "model"):
                if getattr(evidence, key) != reserved.get(key):
                    raise BudgetLedgerInvalid("证据与预留的绑定字段不一致，拒绝")
            reserve_cny = _ledger_non_negative(
                reserved.get("reserve_cny") or 0.0, "reserved.reserve_cny"
            )
            snapshot = reserved.get("settlement_policy")
            if snapshot is None:
                self._append(
                    self._rejected_result_event(
                        reserved,
                        reserve_cny=reserve_cny,
                        reason="legacy_reservation_without_policy",
                        usage=evidence.usage,
                        request_id=request_id,
                        elapsed_seconds=elapsed_seconds,
                        dimensions=dimensions,
                    )
                )
                rejection = SettlementNotReleasable(
                    "旧预留没有 settlement_policy 快照，禁止新版本释放",
                    reservation_id=reservation.reservation_id,
                    reason="legacy_reservation_without_policy",
                    conservative_charge_cny=reserve_cny,
                )
            else:
                try:
                    policy = policy_from_snapshot(snapshot)
                except SettlementPolicyError as exc:
                    self._append(
                        self._rejected_result_event(
                            reserved,
                            reserve_cny=reserve_cny,
                            reason="invalid_policy_snapshot",
                            usage=evidence.usage,
                            request_id=request_id,
                            elapsed_seconds=elapsed_seconds,
                            dimensions=dimensions,
                        )
                    )
                    rejection = SettlementNotReleasable(
                        f"预留 settlement_policy 快照非法：{exc}",
                        reservation_id=reservation.reservation_id,
                        reason="invalid_policy_snapshot",
                        conservative_charge_cny=reserve_cny,
                    )
                else:
                    candidate = evaluate_settlement(
                        policy,
                        reserved=reserved,
                        evidence=evidence,
                        reserve_cny=reserve_cny,
                    )
                    if not candidate.accepted:
                        # S2-J1-R2 F-2：拒绝 reason 先过白名单，事件/异常共用同一安全码。
                        safe_reason = sanitize_settlement_reason(candidate.reason)
                        self._append(
                            self._rejected_result_event(
                                reserved,
                                reserve_cny=reserve_cny,
                                reason=safe_reason,
                                usage=evidence.usage,
                                request_id=request_id,
                                elapsed_seconds=elapsed_seconds,
                                dimensions=dimensions,
                            )
                        )
                        rejection = SettlementNotReleasable(
                            f"结算证据不合格（{safe_reason}），保持全额占用并停止",
                            reservation_id=reservation.reservation_id,
                            reason=safe_reason,
                            conservative_charge_cny=reserve_cny,
                        )
                    else:
                        event = {
                            "event": "result",
                            "reservation_id": reservation.reservation_id,
                            "stage": reserved.get("stage"),
                            "kind": reserved.get("kind"),
                            "provider": reserved.get("provider"),
                            "model": reserved.get("model"),
                            "status": "succeeded",
                            "http_status": (
                                evidence.http_status
                                if type(evidence.http_status) is int
                                else None
                            ),
                            "request_id": request_id,
                            "error_code": None,
                            "usage": dict(candidate.usage_fields) or None,
                            "estimated_list_price_cny": float(
                                candidate.estimated_list_price_cny
                            ),
                            "conservative_charge_cny": float(candidate.charge_cny),
                            "provider_billed_cny": None,
                            "elapsed_seconds": (
                                round(float(elapsed_seconds), 3)
                                if elapsed_seconds is not None
                                else None
                            ),
                            "dimensions": list(dimensions) if dimensions else None,
                            # 白名单证据块 + 声明金额：重放时必须独立重算并一致。
                            "settlement": evidence_snapshot_json(candidate),
                            "boundary_anomaly": bool(candidate.boundary_anomaly),
                            "time_utc": utcnow_iso(),
                        }
                        if self.run_id:
                            event["run_id"] = self.run_id
                        self._append(event)
                        decision = candidate
                        if candidate.boundary_anomaly:
                            boundary = SettlementBoundaryAnomaly(
                                "重算保守金额高于预留：按更高金额入账并停止",
                                reservation_id=reservation.reservation_id,
                                recomputed_charge_cny=float(candidate.charge_cny),
                                reserve_cny=reserve_cny,
                            )
        if rejection is not None:
            raise rejection
        if boundary is not None:
            raise boundary
        assert decision is not None
        return decision

    def _rejected_result_event(
        self,
        reserved: Mapping[str, Any],
        *,
        reserve_cny: float,
        reason: str,
        usage: Mapping[str, Any] | None,
        request_id: str | None,
        elapsed_seconds: float | None,
        dimensions: tuple[int, ...] | None,
    ) -> dict[str, Any]:
        """不合格结算的保守 result：原额占用、status=unknown、记录稳定 reason。

        D-1：``usage`` 按该 kind 的白名单字段过滤（只留 int 非 bool 非负计数），
        未知键名/值、嵌套结构、非字符串键、凭据形态串一律不持久化，也不经通用
        redactor 放行。

        F-2（S2-J1-R2）：``reason`` 先经 :func:`sanitize_settlement_reason` 显式白名单
        过滤——白名单内的稳定码原样保留，受控参数化后缀（usage_missing/usage_not_int/
        usage_negative + 内部 usage 字段名）保留，其余任意输入一律兜底为
        ``UNCLASSIFIED_REJECTION_REASON``；原文不会进入 ``error_code``、
        ``settlement_rejected.reason`` 或相关异常文本。
        """
        safe_reason = sanitize_settlement_reason(reason)
        clean_usage = sanitize_usage_for_kind(reserved.get("kind"), usage)
        event: dict[str, Any] = {
            "event": "result",
            "reservation_id": reserved.get("reservation_id"),
            "stage": reserved.get("stage"),
            "kind": reserved.get("kind"),
            "provider": reserved.get("provider"),
            "model": reserved.get("model"),
            "status": "unknown",
            "http_status": None,
            "request_id": request_id,
            "error_code": f"SETTLEMENT_NOT_RELEASABLE:{safe_reason}",
            "usage": clean_usage or None,
            "estimated_list_price_cny": 0.0,
            "conservative_charge_cny": round(reserve_cny, 8),
            "provider_billed_cny": None,
            "elapsed_seconds": (
                round(float(elapsed_seconds), 3) if elapsed_seconds is not None else None
            ),
            "dimensions": list(dimensions) if dimensions else None,
            "settlement_rejected": {
                "version": SETTLEMENT_VERSION,
                "reason": safe_reason,
            },
            "time_utc": utcnow_iso(),
        }
        if self.run_id:
            event["run_id"] = self.run_id
        return event
