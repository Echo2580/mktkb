"""P2-T203 产品端到端运行器：把 plan 逐轮喂给隔离产品，统一 trace/回执/停止语义。

职责边界（任务书 §5 / §6.2 / §8 T203）：
- **只编排，不评分**：本包不判定答案对错、不产质量门禁结论（T205 负责），也不复制产品
  逻辑；每一轮都是 ``ProductEvalAdapter.ask_turn`` -> 产品 HTTP -> 产品会话/检索/提交路径。
- **串行 + 自动重试 0**：一个 case 一个会话，多轮同会话逐轮执行；任何一轮出现传输错误、
  超时或产品 ``service_error`` 就**停**，后面的 case 显式记为未执行，不重试、不补跑、不挑题。
- **门控**：``authorization`` 是唯一授权输入；``gate`` 给出时每次都走
  begin -> confirm_before_send -> 发送 -> settle 的 T201 门序，且**只允许
  ``production_ready=True`` 才发送**；``gate=None`` 时是明确标注的 dry-run：只跑 Mock
  provider（适配器自证 ``is_mock``），不预留、不结算、真实请求 0 次。
- **产物**：``run_manifest.json``（绑定 dataset/manifest/pipeline/provider/plan/授权）、
  ``summary.json``、``run_result.json``（``P2RunResult``）、``requests.jsonl``（逐次请求身份与
  费用归属）、``gate.json``（授权/拒绝/停止结论，明确写着质量门禁归 T205）；
  公开 run 另写 ``cases.jsonl`` 逐题行；holdout run 只写 ``holdout_aggregate.json`` 聚合，
  临时 trace 在收尾时删除（不把 H2 逐题 trace 留在磁盘）。
- **失败保留现场**：失败阶段（stage）、在飞请求身份（ticket：request_id / reservation_id /
  cost_center / 是否已发送）与 ``stop_code`` 都写进产物，绝不"失败后当作成功"。

本模块不读 `.env`、不发真实 HTTP、不写共享账本/GO；真实发送/结算链在 T206 首次接入。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..observability import TRACE_IDENTITY_FIELDS as _TRACE_IDENTITY_FIELDS
from .p2_authorization import P2Gate, P2SendRefused
from .p2_contracts import (
    COST_CENTERS,
    P2_AUTHORIZATION_SCHEMA_VERSION,
    P2_STAGE,
    P2_RUN_RESULT_SCHEMA_VERSION,
    P2Authorization,
    P2PreflightResult,
    P2RunPlan,
    P2RunResult,
)
from .dataset import cases_to_jsonl
from .p2_scoring import (
    P2_BINDING_VERSION,
    binding_config_hash,
    citation_evidence_status,
)
from .product_adapter import (
    P2RunDataset,
    PRODUCT_TURN_TIMEOUT_SECONDS,
    ProductEvalAdapter,
    ProductTurn,
    case_questions,
    utc_iso,
)

__all__ = [
    "ANSWER_OPERATION",
    "DEFAULT_USER_ID",
    "P2RunDataset",
    "P2RunError",
    "P2RunLedger",
    "build_dry_run_authorization",
    "is_real_p2_gate",
    "run_p2",
]

P2_RUN_MANIFEST_SCHEMA_VERSION = "p2-run-manifest/v0.1"
P2_RUN_SUMMARY_SCHEMA_VERSION = "p2-run-summary/v0.1"
P2_RUN_CASE_SCHEMA_VERSION = "p2-run-case/v0.1"
P2_RUN_REQUEST_SCHEMA_VERSION = "p2-run-request/v0.1"
P2_RUN_GATE_SCHEMA_VERSION = "p2-run-gate/v0.1"
P2_HOLDOUT_AGGREGATE_SCHEMA_VERSION = "p2-holdout-aggregate/v0.1"

ANSWER_OPERATION = "answer"
"""本包只执行 answer 操作；ocr（T204）/judge（T208）/independent 仍只是计划项。"""

DEFAULT_USER_ID = "employee"
"""隔离库里的普通员工账号（P2 视角与真实用户一致：不是管理员特权）。"""

#: T206-PRE：产物/绑定校验的稳定错误码（R2-F-R2-2：不再只靠异常消息前缀）。
ERROR_PROVIDER_NETWORK_DETAIL_MISMATCH = "provider_network_detail_mismatch"
ERROR_RUN_ID_MISSING = "run_id_missing"
ERROR_BINDING_INCOMPLETE = "binding_incomplete"
ERROR_ARTIFACT_WRITE_FAILED = "artifact_write_failed"

EXECUTION_DRY_RUN = "dry_run"
EXECUTION_MOCK_GATE = "mock_gate"
EXECUTION_LIVE = "live"

#: 停止原因码（稳定、可机读；不拼接外部原文）。
STOP_AUTHORIZATION_MISMATCH = "plan_authorization_mismatch"
STOP_AUTHORIZATION_EXPIRED = "authorization_expired"
STOP_OPERATION_UNAUTHORIZED = "operation_unauthorized"
STOP_REQUEST_CAP = "request_cap_exceeded"
STOP_ADAPTER_NOT_MOCK = "adapter_must_be_mock"
STOP_MOCK_GATE_WITHOUT_STUB = "mock_gate_requires_stub_gate"
STOP_LIVE_REQUIRES_REAL_GATE = "live_requires_real_gate"
STOP_HOLDOUT_REQUIRES_PURGE = "holdout_requires_purge"
STOP_PRODUCTION_NOT_READY = "production_not_ready"
STOP_MOCK_REQUIRES_DRY_RUN = "mock_adapter_requires_dry_run"
STOP_CANCELLED = "cancelled"
STOP_INGEST_FAILED = "ingest_failed"
STOP_PLAN_ITEM_MISSING = "plan_item_missing"
STOP_PLAN_ITEM_AMBIGUOUS = "plan_item_ambiguous"
STOP_PRE_SEND_REFUSED = "pre_send_refused"
STOP_TURN_TIMEOUT = "turn_timeout"
STOP_SERVICE_ERROR = "product_service_error"
STOP_NO_CASE_EXECUTED = "no_case_executed"
STOP_GATE_ERROR = "gate_error"
STOP_ADAPTER_ERROR = "adapter_error"
STOP_OPEN_CONVERSATION_FAILED = "open_conversation_failed"
#: T206-PRE：产物校验失败也要落盘并带稳定 stop_code（R2-F-R2-1）。
STOP_ARTIFACT_VALIDATION_FAILED = "artifact_validation_failed"


class P2RunError(ValueError):
    """runner 的稳定错误：``code`` 可机读，消息以 code 开头（既有断言仍匹配）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


#: 产品结局里"可以继续"的集合；``service_error`` / 超时必须停。
CONTINUABLE_KINDS = frozenset(
    {"answer", "clarification", "not_found", "conflict", "knowledge_changed"}
)

_STOP_BY_CHECK = {
    "plan_identity": STOP_AUTHORIZATION_MISMATCH,
    "stage": STOP_AUTHORIZATION_MISMATCH,
    "not_expired": STOP_AUTHORIZATION_EXPIRED,
    "not_before_issue": STOP_AUTHORIZATION_EXPIRED,
    "operations": STOP_OPERATION_UNAUTHORIZED,
    "request_cap": STOP_REQUEST_CAP,
    "adapter_mock": STOP_ADAPTER_NOT_MOCK,
    "stub_gate": STOP_MOCK_GATE_WITHOUT_STUB,
    "mock_gate": STOP_MOCK_GATE_WITHOUT_STUB,
    "live_gate": STOP_LIVE_REQUIRES_REAL_GATE,
    "production_ready": STOP_PRODUCTION_NOT_READY,
}


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        return _sha256_bytes(Path(path).read_bytes())
    except OSError:
        return None


def is_real_p2_gate(gate: Any) -> bool:
    """live 只认**真实** P2Gate：桩门（``is_mock_gate=True``）或鸭子门一律不算。

    F2：桩门在 live 链上会"照跑 begin/confirm/settle"，却没有任何账本/GO 事实，
    产物还会写 ``real_sends_allowed=true``——所以这里在发送之前就把它挡掉。
    """
    return isinstance(gate, P2Gate) and not bool(getattr(gate, "is_mock_gate", False))


def _measured_outbound(providers: Mapping[str, Any]) -> int:
    """取适配器**实测**的出站次数；没有这个字段就报错，不用常量 0 兜底（F1）。"""
    if "outbound_network" not in providers:
        raise ValueError("适配器 provider_calls() 必须报告实测 outbound_network")
    return max(0, int(providers["outbound_network"]))


#: A1：(F1-a) 顶层 outbound_attempts 与 network.detail 不一致时的稳定错误码。
NETWORK_DETAIL_MISMATCH = "provider_network_detail_mismatch"

#: network.detail 必须给出的分解分量（之和 = 顶层出站）。
_NETWORK_DETAIL_KEYS = ("outbound_attempts", "chat_outbound_attempts", "rag_provider_posts")


def _validated_network(providers: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    """核对 network.detail 只是顶层出站的**分解**，不是第二份"真值"（A1）。

    契约（`p2-runner-contract-v0_1` §5）规定：``providers.outbound_network`` 是唯一真值，
    ``providers.network`` 是它的分解（``chat_outbound_attempts`` + ``rag_provider_posts``）。
    两者不一致（或分解之和 ≠ detail 汇总）时直接报稳定错误码，**不静默拼接/覆盖**。
    """
    detail = providers.get("network")
    if not isinstance(detail, Mapping):
        raise P2RunError(ERROR_PROVIDER_NETWORK_DETAIL_MISMATCH, "provider_calls() 缺少 network detail")
    missing = [key for key in _NETWORK_DETAIL_KEYS if key not in detail]
    if missing:
        raise P2RunError(ERROR_PROVIDER_NETWORK_DETAIL_MISMATCH, f"network detail 缺少 {missing}")
    top = _measured_outbound(providers)
    detail_total = max(0, int(detail["outbound_attempts"]))
    parts = max(0, int(detail["chat_outbound_attempts"])) + max(
        0, int(detail["rag_provider_posts"])
    )
    if parts != detail_total:
        raise P2RunError(
            ERROR_PROVIDER_NETWORK_DETAIL_MISMATCH,
            f"detail 分解之和 {parts} != network.outbound_attempts {detail_total}",
        )
    if detail_total != top:
        raise P2RunError(
            ERROR_PROVIDER_NETWORK_DETAIL_MISMATCH,
            f"顶层 outbound_network {top} != network.outbound_attempts {detail_total}",
        )
    return top, dict(detail)


def _provider_counters(adapter: Any) -> dict[str, int]:
    """一次 provider 计数快照（chat/embedding/rerank/出站），用于算每轮增量。

    每轮取前后快照相减：某轮有没有真的出网、调了几次 chat，都由测量得出，
    而不是由 execution 标签或常量推断。
    """
    calls = adapter.provider_calls()
    if not isinstance(calls, Mapping):
        raise ValueError("适配器 provider_calls() 必须返回映射")
    snapshot = {"outbound": _measured_outbound(calls)}
    for name in ("chat", "embedding", "rerank"):
        entry = calls.get(name)
        if not isinstance(entry, Mapping) or "calls" not in entry:
            raise ValueError(f"适配器 provider_calls() 缺少实测 {name}.calls")
        snapshot[name] = int(entry["calls"])
    return snapshot


def _charged_cny(settled: Any, ticket: Any) -> float:
    """结算的实际入账金额：门返回数值就用它，否则退回该笔预留上界（保守）。"""
    if isinstance(settled, bool):
        return float(getattr(ticket, "bound_cny", 0.0))
    if isinstance(settled, (int, float)):
        return float(settled)
    return float(getattr(ticket, "bound_cny", 0.0))


def _json_default(value: Any) -> Any:  # pragma: no cover - 兜底，正常路径不触发
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"不可序列化的类型: {type(value).__name__}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, indent=2, default=_json_default
    )
    path.write_text(text + "\n", encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=_json_default)
        for row in rows
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _request_uuid(run_id: str, case_id: str, turn: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"p2:{run_id}:{case_id}:turn{turn}"))


def _answer_items(plan: P2RunPlan, dataset: P2RunDataset) -> dict[tuple[str, int], Any]:
    """按 (case_id, turn) 取 answer 计划项；缺失/重复都不猜，交给调用点 fail closed。"""
    found: dict[tuple[str, int], Any] = {}
    duplicated: set[tuple[str, int]] = set()
    for item in plan.items:
        if item.operation != ANSWER_OPERATION:
            continue
        key = (item.case_id, int(item.turn))
        if key in found:
            duplicated.add(key)
        found[key] = item
    for key in duplicated:
        found.pop(key, None)
    return found


# --------------------------------------------------------------------------- #
# 回执登记
# --------------------------------------------------------------------------- #


@dataclass
class P2RunLedger:
    """本 run 的请求/费用回执：只记录**实际发生**的尝试，不预填、不估算成功。"""

    run_id: str
    plan_id: str
    plan_sha256: str
    execution: str
    production_ready: bool
    requests_planned: int = 0
    requests: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    stop_code: str | None = None
    failure: dict[str, Any] | None = None
    reserved: int = 0
    settled_success: int = 0
    settled_failure: int = 0
    reserved_cny: float = 0.0
    settled_cny: float = 0.0
    by_operation: dict[str, int] = field(default_factory=dict)
    by_center_cny: dict[str, float] = field(default_factory=dict)
    gate_notes: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    # -------------------------------------------------------------- 记录
    def add_check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"name": str(name), "ok": bool(ok), "detail": str(detail)})

    def stop(self, code: str) -> None:
        if self.stop_code is None:
            self.stop_code = str(code)

    def record_request(
        self,
        *,
        case_id: str,
        turn: int,
        item_id: str,
        client_request_id: str,
        ticket: Mapping[str, Any],
        billed: bool,
        status: str,
        product: ProductTurn | None,
        error_code: str | None,
        elapsed_ms: int,
        include_question: bool,
        provider_calls: Mapping[str, int] | None = None,
        charged_cny: float | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "schema_version": P2_RUN_REQUEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "case_id": case_id,
            "turn": int(turn),
            "item_id": item_id,
            "client_request_id": client_request_id,
            "ticket": dict(ticket),
            "billed": bool(billed),
            "status": str(status),
            "error_code": error_code,
            "elapsed_ms": int(elapsed_ms),
            "execution": self.execution,
            # 实测：这一轮各 provider 的调用增量与该笔的实际入账金额（F1）。
            "provider_calls": {
                str(name): int(value) for name, value in (provider_calls or {}).items()
            },
            "charged_cny": float(charged_cny or 0.0),
        }
        if product is not None:
            row["product"] = {
                "http_status": int(product.http_status),
                "kind": product.kind,
                "message_id": product.message_id,
                "request_id": product.request_id,
                "trace_id": product.trace_id,
                "trace_path": product.trace_path,
                "trace_outcome": product.trace_outcome,
                "trace_status": product.trace_status,
                "source_ids": list(product.source_ids),
            }
            if include_question:
                row["product"]["question_sha256"] = product.question_sha256
        self.requests.append(row)
        return row

    def record_case(self, row: Mapping[str, Any]) -> None:
        self.cases.append(dict(row))

    # -------------------------------------------------------------- 汇总
    def counts(self, key: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for case in self.cases:
            for turn in case.get("turns") or ():
                value = str(turn.get(key) or "unknown")
                result[value] = result.get(value, 0) + 1
        return result

    def turns_executed(self) -> int:
        return sum(len(case.get("turns") or ()) for case in self.cases)

    def result(self, *, status: str) -> P2RunResult:
        return P2RunResult(
            schema_version=P2_RUN_RESULT_SCHEMA_VERSION,
            run_id=self.run_id,
            plan_id=self.plan_id,
            plan_sha256=self.plan_sha256,
            status=status,
            stop_code=self.stop_code,
            requests_planned=int(self.requests_planned),
            requests_reserved=int(self.reserved),
            requests_sent=int(self.settled_success + self.settled_failure),
            reserved_cny=float(self.reserved_cny),
            settled_cny=float(self.settled_cny),
            by_operation=dict(self.by_operation),
            by_center_cny={
                center: float(self.by_center_cny.get(center, 0.0)) for center in COST_CENTERS
            },
            production_ready=bool(self.production_ready),
        )


# --------------------------------------------------------------------------- #
# dry-run 授权（不与固定账本/GO 抢身份）
# --------------------------------------------------------------------------- #


def build_dry_run_authorization(
    plan: P2RunPlan,
    preflight: P2PreflightResult,
    *,
    issued_by: str = "p2-t203-dry-run",
    ttl_seconds: float = 900.0,
    now: datetime | None = None,
    nonce: str | None = None,
) -> P2Authorization:
    """由离线预检结果构造**空跑**授权：``production_ready=False``，只能跑 Mock。

    这不是 GO，也不能被当成 GO：``go_document`` 明确写 P2-DRY-RUN，``ledger_path`` 写
    in-memory:dry-run，``production_ready=False`` 让 ``run_p2`` 的发送门直接拒绝任何真实
    发送。``go_nonce_len`` 是本 dry-run 自己的随机串长度（DTO 要求 >=16 位），不冒充 GO 的
    nonce。真实授权只来自 T206 的固定 GO 路径。
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not preflight.ok:
        raise ValueError(f"预检未通过，不能构造空跑授权: {list(preflight.reasons)}")
    if preflight.plan_sha256 != plan.plan_sha256 or preflight.plan_id != plan.plan_id:
        raise ValueError("预检结果与计划身份不一致")
    dry_nonce = str(nonce) if nonce is not None else uuid.uuid4().hex
    if len(dry_nonce) < 16:
        raise ValueError("dry-run nonce 至少 16 位（P2Authorization 的 DTO 下限）")
    payload = {
        "document": "P2-DRY-RUN",
        "stage": P2_STAGE,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "issued_by": issued_by,
        "issued_utc": utc_iso(moment),
        "nonce": dry_nonce,
    }
    return P2Authorization(
        schema_version=P2_AUTHORIZATION_SCHEMA_VERSION,
        stage=P2_STAGE,
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        go_document=str(payload["document"]),
        go_sha256=_sha256_bytes(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ),
        go_nonce_len=len(dry_nonce),
        issued_by=str(issued_by),
        issued_utc=moment,
        expires_utc=moment + timedelta(seconds=float(ttl_seconds)),
        ledger_path="in-memory:dry-run",
        ledger_sha256=plan.plan_sha256,
        budget_sha256=plan.plan_sha256,
        stage_limit_cny=float(plan.stage_limit_cny),
        stage_remaining_cny=float(plan.stage_limit_cny),
        cost_center_limits_cny={
            center: float(plan.cost_centers_cny[center]) for center in COST_CENTERS
        },
        center_remaining_cny={
            center: float(plan.cost_centers_cny[center]) for center in COST_CENTERS
        },
        max_requests=int(plan.max_requests),
        requests_used=0,
        requests_remaining=max(0, int(plan.max_requests) - int(plan.total_requests)),
        max_request_cny=float(plan.reserve_peak_cny),
        operations=tuple(plan.operations),
        production_ready=False,
    )


# --------------------------------------------------------------------------- #
# 授权/模式校验
# --------------------------------------------------------------------------- #


def _prepare(
    plan: P2RunPlan,
    authorization: P2Authorization,
    adapter: ProductEvalAdapter,
    gate: Any | None,
    now: datetime,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """决定本次 run 的执行类别与停止码；任一检查失败都必须**在发送之前**停。

    三种执行类别（产物里的 ``execution`` 字段，别混着读）：
    - ``dry_run``：没有 gate。只允许 Mock 适配器；不预留、不结算、真实请求 0 次；
    - ``mock_gate``：Mock 适配器 + **桩门**（``is_mock_gate=True``）。只用来验证 runner
      真的走了 begin -> confirm_before_send -> settle 的门序；真实 ``P2Gate`` 没有这个标记，
      因此绝不会在 Mock 链上写账本；
    - ``live``：真实适配器 + **真实 ``P2Gate``**（桩门不算），且**必须**
      ``production_ready=True``（T201 遗留 ① + F2：live 的资金事实不能来自桩门）。
    """
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": str(name), "ok": bool(ok), "detail": str(detail)})

    unauthorized = sorted(set(plan.operations) - set(authorization.operations))
    is_stub_gate = gate is not None and bool(getattr(gate, "is_mock_gate", False))
    if gate is None:
        execution = EXECUTION_DRY_RUN
    elif adapter.is_mock:
        execution = EXECUTION_MOCK_GATE if is_stub_gate else EXECUTION_DRY_RUN
    else:
        execution = EXECUTION_LIVE

    add(
        "plan_identity",
        authorization.plan_id == plan.plan_id and authorization.plan_sha256 == plan.plan_sha256,
        "authorization 必须绑定本次 plan",
    )
    add("stage", authorization.stage == P2_STAGE, "authorization.stage 必须是 P2-LIVE")
    add("not_expired", now < authorization.expires_utc, "授权已过期")
    add("not_before_issue", now >= authorization.issued_utc, "授权尚未生效")
    add("operations", not unauthorized, f"未授权操作: {unauthorized}" if unauthorized else "")
    add(
        "request_cap",
        int(plan.total_requests) <= int(authorization.requests_remaining),
        "计划请求数超出授权剩余",
    )
    if gate is None:
        add(
            "adapter_mock",
            bool(adapter.is_mock),
            "dry-run 只接受 Mock 适配器（真实适配器必须配门，否则等于无账发送）",
        )
        add("dry_run", True, "gate=None -> dry-run：不预留、不结算、真实请求 0 次")
    elif adapter.is_mock:
        add(
            "stub_gate",
            is_stub_gate,
            "Mock 适配器只允许配桩门（is_mock_gate=True）；真实 P2Gate 必须配真实 provider",
        )
        add("mock_gate", is_stub_gate, "mock_gate：只验证门序，不产生资金事实")
    else:
        # T201 遗留 ①：没有 production_ready 的授权绝不发送真实请求。
        add(
            "production_ready",
            bool(authorization.production_ready),
            "authorization.production_ready=False，拒绝真实发送",
        )
        # F2：live 必须配真实 P2Gate；桩门/鸭子门只能在 Mock 链上验证门序。
        add(
            "live_gate",
            is_real_p2_gate(gate),
            "live 只接受真实 P2Gate（桩门只能配 Mock 适配器）",
        )
    for check in checks:
        if not check["ok"]:
            return execution, checks, _STOP_BY_CHECK.get(str(check["name"]))
    return execution, checks, None

# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def _dataset_sha256(dataset: P2RunDataset) -> str:
    """数据集内容的 sha256（与 P1 ``dataset_version`` 同一份规范 JSONL 字节）。

    只算摘要、不落题面：H2 路径同样可用，产物里只有 64 位十六进制。
    """
    return _sha256_bytes(cases_to_jsonl(dataset.cases).encode("utf-8"))


def _gate_identity(gate_config: Any | None) -> tuple[str | None, str | None]:
    """从 P2GateConfig 取 gate 身份；不是 P2GateConfig 就当作"没有"（不猜）。"""
    if gate_config is None:
        return None, None
    version = str(getattr(gate_config, "gate_version", "") or "").strip()
    digest = str(getattr(gate_config, "config_hash", "") or "").strip()
    return (version or None), (digest or None)


def _empty_binding(dataset: P2RunDataset, run_id: str) -> dict[str, Any]:
    """绑定状态的"未完成"基线（不含摘要）：仅数据集侧已知的部分，其余显式 None。"""
    return {
        "binding_version": P2_BINDING_VERSION,
        "run_id": run_id,
        "dataset_version": str(dataset.identity.get("dataset_version") or ""),
        "manifest_sha256": str(dataset.identity.get("manifest_sha256") or ""),
        "label_version": str(dataset.identity.get("label_version") or ""),
        "suite": str(dataset.identity.get("suite") or ""),
        "case_count": len(dataset.cases),
        "dataset_sha256": _dataset_sha256(dataset),
        "pipeline_version": None,
        "index_revision": None,
        "provider": None,
        "gate_version": None,
        "gate_config_hash": None,
        "config_hash": None,
        "complete": False,
        "missing": [],
    }


def _binding_state(
    adapter: Any,
    dataset: P2RunDataset,
    run_id: str,
    gate_config: Any | None,
) -> dict[str, Any]:
    """组装本次 run 的绑定组件与确定性 config_hash（T206-PRE 要求 3）。

    - 适配器必须提供 ``binding_components()``（真实/Mock 产品适配器都有）；没有就记
      ``complete=False`，绝不拿常量冒充；
    - gate 身份来自 ``P2GateConfig``（gate_version + gate_config_hash）；没给也算缺项
      —— 这正是 evaluate_p2_gate 的 ``gate_config_unbound``/``config_hash_unbound``
      路径，不是"默认通过"；
    - 任一组件缺失 → ``config_hash=None`` 且 ``complete=False`，调用方不得把它当身份。
    """
    gate_version, gate_config_hash = _gate_identity(gate_config)
    state = _empty_binding(dataset, run_id)
    state["gate_version"] = gate_version
    state["gate_config_hash"] = gate_config_hash
    missing: list[str] = state["missing"]
    components = getattr(adapter, "binding_components", None)
    try:
        raw = components() if callable(components) else None
    except Exception:  # noqa: BLE001 - 适配器未 start：绑定只能记"未完成"，不能编造
        raw = None
    if not isinstance(raw, Mapping):
        missing.append("adapter_binding_components")
        raw = {}
    for name in ("pipeline_version", "index_revision", "provider"):
        if raw.get(name) in (None, ""):
            missing.append(name)
        else:
            state[name] = raw[name]
    for name in ("gate_version", "gate_config_hash", "dataset_version", "manifest_sha256", "label_version"):
        if not state.get(name):
            missing.append(name)
    if missing:
        return state
    try:
        state["config_hash"] = binding_config_hash(
            dataset_version=state["dataset_version"],
            manifest_sha256=state["manifest_sha256"],
            label_version=state["label_version"],
            pipeline_version=str(state["pipeline_version"]),
            index_revision=int(state["index_revision"]),
            provider=state["provider"],
            gate_version=str(state["gate_version"]),
            gate_config_hash=str(state["gate_config_hash"]),
        )
    except ValueError as exc:  # binding_config_hash 的 P2ScoringError 也是 ValueError
        missing.append(f"config_hash:{type(exc).__name__}")
        return state
    state["complete"] = True
    return state


def _trace_identity_from_binding(binding: Mapping[str, Any]) -> dict[str, str]:
    """把绑定状态转成 trace 身份六元组；缺一项就整体不给（fail closed，不绑半套）。"""
    fields = ("dataset_version", "run_id", "index_revision", "manifest_sha256", "pipeline_version", "config_hash")
    resolved: dict[str, str] = {}
    for name in fields:
        value = binding.get(name)
        if value in (None, ""):
            return {}
        resolved[name] = str(value)
    return resolved


async def run_p2(
    plan: P2RunPlan,
    *,
    adapter: ProductEvalAdapter,
    authorization: P2Authorization,
    dataset: P2RunDataset | None = None,
    gate: Any | None = None,
    cancel: Callable[[], bool] | None = None,
    now: datetime | None = None,
    settle_evidence: Callable[[Any, ProductTurn], Any] | None = None,
    run_id: str | None = None,
    gate_config: Any | None = None,
) -> P2RunResult:
    """按 plan 逐轮驱动隔离产品；返回请求/费用回执 ``P2RunResult``（产物同时落盘）。

    ``gate=None`` 是 dry-run（Mock only，真实请求 0）；给出 ``gate`` 时走 P2Gate 的
    begin/confirm/settle 门序，且 ``production_ready=False`` 一律拒绝发送。
    ``settle_evidence`` 供 T206 注入真实 ``UsageEvidence`（本包 Mock 链不需要）。
    """
    frozen_dataset = dataset if dataset is not None else getattr(adapter, "dataset", None)
    if not isinstance(frozen_dataset, P2RunDataset):
        raise ValueError("run_p2 需要 P2RunDataset（adapter.dataset 或显式 dataset=）")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    started = time.perf_counter()
    # T206-PRE（R2-F-R2-3）：run_id 是身份必填项 —— 显式给空/non-str 就在**任何发送前**
    # 用稳定码拒绝，而不是悄悄生成一个新身份。
    if run_id is not None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise P2RunError(ERROR_RUN_ID_MISSING, f"run_id 必须是非空 str，收到 {run_id!r}")
        run_id = run_id.strip()
    else:
        run_id = "p2run-" + uuid.uuid4().hex[:16]
    execution, checks, stop_code = _prepare(plan, authorization, adapter, gate, moment)
    if frozen_dataset.visibility == "holdout":
        if not bool(getattr(adapter, "purge_traces_on_close", False)):
            # F3：H2 的逐题 trace 不允许留在磁盘上。不满足就一行都不跑（fail closed）。
            checks.append(
                {
                    "name": "holdout_purge",
                    "ok": False,
                    "detail": "holdout run 必须 purge_traces_on_close=True，拒绝执行",
                }
            )
            if stop_code is None:
                stop_code = STOP_HOLDOUT_REQUIRES_PURGE
        else:
            checks.append(
                {
                    "name": "holdout_purge",
                    "ok": True,
                    "detail": "holdout：trace 在 close 时删除，业务库题干在 close 时封存删除",
                }
            )
            seal = getattr(adapter, "require_holdout_sealing", None)
            if callable(seal):
                seal()
    ledger = P2RunLedger(
        run_id=run_id,
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        execution=execution,
        production_ready=bool(getattr(authorization, "production_ready", False)),
        requests_planned=int(plan.total_requests),
    )
    for check in checks:
        ledger.add_check(str(check["name"]), bool(check["ok"]), str(check["detail"]))
    run_dir = adapter.paths.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    planned_turns = sum(len(case_questions(case)) for case in frozen_dataset.cases)

    status = "succeeded"
    binding: dict[str, Any] = _empty_binding(frozen_dataset, run_id)
    binding["missing"] = ["run_not_started"]
    if stop_code is not None:
        ledger.stop(stop_code)
        ledger.failure = {
            "stage": (
                "holdout_policy"
                if stop_code == STOP_HOLDOUT_REQUIRES_PURGE
                else "authorization"
            ),
            "stop_code": stop_code,
            "error_code": stop_code,
            "case_id": None,
            "turn": None,
            "item_id": None,
            "ticket": None,
        }
        status = "blocked"
    else:
        if adapter.ingest_plan is not None:
            try:
                await adapter.ingest()
            except Exception as exc:  # noqa: BLE001 - 灌库失败即停，不重试
                ledger.stop(STOP_INGEST_FAILED)
                ledger.failure = {
                    "stage": "ingest",
                    "stop_code": STOP_INGEST_FAILED,
                    "error_code": type(exc).__name__,
                    "case_id": None,
                    "turn": None,
                    "item_id": None,
                    "ticket": None,
                }
        if ledger.stop_code is None:
            # T206-PRE：灌库/发布之后 index_revision 已定型，这里才算绑定并写进 trace 身份。
            binding = _binding_state(adapter, frozen_dataset, run_id, gate_config)
            identity = _trace_identity_from_binding(binding)
            bind = getattr(adapter, "bind_trace_identity", None)
            if identity and callable(bind):
                bind(identity)
            elif not identity:
                binding["missing"] = sorted(set(binding["missing"]) | {"trace_identity"})
            await _execute(
                plan=plan,
                adapter=adapter,
                dataset=frozen_dataset,
                ledger=ledger,
                gate=gate,
                cancel=cancel,
                run_id=run_id,
                settle_evidence=settle_evidence,
            )
        if ledger.stop_code is None and ledger.turns_executed() == 0:
            # 空跑 != 成功：没有真正执行任何一轮，必须是 blocked。
            ledger.stop(STOP_NO_CASE_EXECUTED)
            ledger.failure = {
                "stage": "execute",
                "stop_code": STOP_NO_CASE_EXECUTED,
                "error_code": STOP_NO_CASE_EXECUTED,
                "case_id": None,
                "turn": None,
                "item_id": None,
                "ticket": None,
            }
        if ledger.stop_code is not None:
            status = "blocked" if ledger.stop_code == STOP_NO_CASE_EXECUTED or not ledger.cases else "aborted"

    result = ledger.result(status=status)
    # T206-PRE（R2-F-R2-1）：任何"发过请求 / 校验失败"都必须留下 run_result+summary+gate。
    # 校验先失败 → 先补失败现场（stop_code/error_code/stage），写完全部产物再抛出。
    try:
        providers = adapter.provider_calls()
        network = _validated_network(providers)
    except P2RunError as exc:
        ledger.stop(exc.code)
        ledger.failure = {
            "stage": "artifact_validation",
            "stop_code": exc.code,
            "error_code": exc.code,
            "case_id": None,
            "turn": None,
            "item_id": None,
            "ticket": None,
            "detail": exc.detail,
        }
        failed_status = "blocked" if not ledger.cases else "aborted"
        result = ledger.result(status=failed_status)
        _write_artifacts(
            plan=plan,
            authorization=authorization,
            adapter=adapter,
            dataset=frozen_dataset,
            ledger=ledger,
            result=result,
            execution=execution,
            checks=checks,
            planned_turns=planned_turns,
            executed_turns=ledger.turns_executed(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            started_utc=utc_iso(moment),
            binding=binding,
            providers=None,
            network=None,
            artifact_failure=exc,
        )
        raise
    _write_artifacts(
        plan=plan,
        authorization=authorization,
        adapter=adapter,
        dataset=frozen_dataset,
        ledger=ledger,
        result=result,
        execution=execution,
        checks=checks,
        planned_turns=planned_turns,
        executed_turns=ledger.turns_executed(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        started_utc=utc_iso(moment),
        binding=binding,
        providers=providers,
        network=network,
        artifact_failure=None,
    )
    return result


def _case_item_failure(
    ledger: P2RunLedger,
    *,
    stop_code: str,
    stage: str,
    case_id: str,
    turn: int | None,
    item_id: str | None,
    ticket: Mapping[str, Any] | None = None,
    error_code: str | None = None,
    http_status: int | None = None,
    timeout_seconds: float | None = None,
) -> None:
    ledger.stop(stop_code)
    if ledger.failure is not None:
        return
    failure: dict[str, Any] = {
        "stage": stage,
        "stop_code": stop_code,
        "error_code": error_code or stop_code,
        "case_id": case_id,
        "turn": turn,
        "item_id": item_id,
        "ticket": None if ticket is None else dict(ticket),
    }
    if http_status is not None:
        failure["http_status"] = int(http_status)
    if timeout_seconds is not None:
        failure["timeout_seconds"] = float(timeout_seconds)
    ledger.failure = failure


async def _execute(
    *,
    plan: P2RunPlan,
    adapter: ProductEvalAdapter,
    dataset: P2RunDataset,
    ledger: P2RunLedger,
    gate: Any | None,
    cancel: Callable[[], bool] | None,
    run_id: str,
    settle_evidence: Callable[[Any, ProductTurn], Any] | None,
) -> None:
    items = _answer_items(plan, dataset)
    include_question = dataset.public_details
    for case in dataset.cases:
        if ledger.stop_code is not None:
            break
        if cancel is not None and cancel():
            _case_item_failure(
                ledger,
                stop_code=STOP_CANCELLED,
                stage="cancel",
                case_id=case.case_id,
                turn=None,
                item_id=None,
            )
            break
        questions = case_questions(case)
        missing = [n for n in range(1, len(questions) + 1) if (case.case_id, n) not in items]
        if missing:
            _case_item_failure(
                ledger,
                stop_code=STOP_PLAN_ITEM_MISSING,
                stage="plan",
                case_id=case.case_id,
                turn=missing[0],
                item_id=f"{case.case_id}:turn{missing[0]}:{ANSWER_OPERATION}",
            )
            break
        try:
            conversation_id = await adapter.open_conversation(user_id=DEFAULT_USER_ID)
        except Exception as exc:  # noqa: BLE001 - 建会话失败即停
            _case_item_failure(
                ledger,
                stop_code=STOP_OPEN_CONVERSATION_FAILED,
                stage="open_conversation",
                case_id=case.case_id,
                turn=None,
                item_id=None,
                error_code=type(exc).__name__,
            )
            ledger.record_case(
                {
                    "schema_version": P2_RUN_CASE_SCHEMA_VERSION,
                    "run_id": run_id,
                    "case_id": case.case_id,
                    "suite": case.suite,
                    "stratum": case.stratum,
                    "visibility": dataset.visibility,
                    "conversation_id": None,
                    "turns": [],
                    "status": "error",
                    "error_code": STOP_OPEN_CONVERSATION_FAILED,
                    "planned_turns": len(questions),
                    "turns_executed": 0,
                }
            )
            break
        case_row: dict[str, Any] = {
            "schema_version": P2_RUN_CASE_SCHEMA_VERSION,
            "run_id": run_id,
            "case_id": case.case_id,
            "suite": case.suite,
            "stratum": case.stratum,
            "visibility": dataset.visibility,
            "conversation_id": conversation_id,
            "turns": [],
            "status": "ok",
            "error_code": None,
            "planned_turns": len(questions),
            "turns_executed": 0,
        }
        for turn, question in enumerate(questions, start=1):
            if ledger.stop_code is not None:
                break
            item = items[(case.case_id, turn)]
            item_id = item.item_id
            client_request_id = _request_uuid(run_id, case.case_id, turn)
            ticket: Any | None = None
            billed = False
            if gate is not None:
                try:
                    ticket = gate.begin(item_id)
                    gate.confirm_before_send(ticket)
                except P2SendRefused as exc:
                    refused = exc.ticket.as_dict()
                    _case_item_failure(
                        ledger,
                        stop_code=STOP_PRE_SEND_REFUSED,
                        stage="gate_confirm",
                        case_id=case.case_id,
                        turn=turn,
                        item_id=item_id,
                        ticket=refused,
                        error_code=str(getattr(exc, "reason", "") or STOP_PRE_SEND_REFUSED),
                    )
                    ledger.record_request(
                        case_id=case.case_id,
                        turn=turn,
                        item_id=item_id,
                        client_request_id=client_request_id,
                        ticket=refused,
                        billed=False,
                        status="refused_before_send",
                        product=None,
                        error_code=STOP_PRE_SEND_REFUSED,
                        elapsed_ms=0,
                        include_question=include_question,
                    )
                    case_row["turns"].append(
                        {
                            "turn": turn,
                            "item_id": item_id,
                            "status": "refused_before_send",
                            "error_code": STOP_PRE_SEND_REFUSED,
                            "ticket": refused,
                        }
                    )
                    case_row["status"] = "error"
                    case_row["error_code"] = STOP_PRE_SEND_REFUSED
                    break
                except Exception as exc:  # noqa: BLE001 - 门内部错误按停止处理
                    dry = _dry_ticket(item, item_id, client_request_id)
                    _case_item_failure(
                        ledger,
                        stop_code=STOP_GATE_ERROR,
                        stage="gate_begin",
                        case_id=case.case_id,
                        turn=turn,
                        item_id=item_id,
                        ticket=dry,
                        error_code=type(exc).__name__,
                    )
                    ledger.record_request(
                        case_id=case.case_id,
                        turn=turn,
                        item_id=item_id,
                        client_request_id=client_request_id,
                        ticket=dry,
                        billed=False,
                        status="gate_error",
                        product=None,
                        error_code=STOP_GATE_ERROR,
                        elapsed_ms=0,
                        include_question=include_question,
                    )
                    case_row["turns"].append(
                        {
                            "turn": turn,
                            "item_id": item_id,
                            "status": "gate_error",
                            "error_code": STOP_GATE_ERROR,
                            "ticket": dry,
                        }
                    )
                    case_row["status"] = "error"
                    case_row["error_code"] = STOP_GATE_ERROR
                    break
                ticket_payload = ticket.as_dict()
                ledger.reserved += 1
                ledger.reserved_cny += float(getattr(ticket, "bound_cny", 0.0))
            else:
                ticket_payload = _dry_ticket(item, item_id, client_request_id)

            # 每轮前后各取一次实测快照：这轮有没有真的出网、调了几次 provider。
            counters_before = _provider_counters(adapter)
            turn_started = time.perf_counter()
            product: ProductTurn | None = None
            error_code: str | None = None
            try:
                product = await adapter.ask_turn(
                    question,
                    user_id=DEFAULT_USER_ID,
                    conversation_id=conversation_id,
                    client_request_id=client_request_id,
                )
            except Exception as exc:  # noqa: BLE001 - 适配器内部异常按停止处理
                error_code = type(exc).__name__
                _case_item_failure(
                    ledger,
                    stop_code=STOP_ADAPTER_ERROR,
                    stage="product_call",
                    case_id=case.case_id,
                    turn=turn,
                    item_id=item_id,
                    ticket=ticket_payload,
                    error_code=error_code,
                )
            elapsed_ms = int((time.perf_counter() - turn_started) * 1000)
            counters_after = _provider_counters(adapter)
            turn_calls = {
                name: max(0, counters_after[name] - counters_before[name])
                for name in counters_before
            }

            turn_row: dict[str, Any] = {
                "turn": turn,
                "item_id": item_id,
                "status": "ok",
                "error_code": None,
                "ticket": ticket_payload,
                "product": None,
            }
            if product is None:
                turn_row["status"] = "error"
                turn_row["error_code"] = error_code or STOP_ADAPTER_ERROR
            else:
                turn_row["product"] = product.as_dict(include_text=include_question)
                turn_row["http_status"] = int(product.http_status)
                turn_row["kind"] = product.kind
                turn_row["trace_id"] = product.trace_id
                turn_row["trace_path"] = product.trace_path
                turn_row["trace_outcome"] = product.trace_outcome
                if product.kind == "timeout":
                    _case_item_failure(
                        ledger,
                        stop_code=STOP_TURN_TIMEOUT,
                        stage="product_wait",
                        case_id=case.case_id,
                        turn=turn,
                        item_id=item_id,
                        ticket=ticket_payload,
                        error_code=product.error_code or STOP_TURN_TIMEOUT,
                        timeout_seconds=float(adapter.turn_timeout_seconds),
                    )
                    turn_row["status"] = "error"
                    turn_row["error_code"] = product.error_code or STOP_TURN_TIMEOUT
                elif product.kind not in CONTINUABLE_KINDS or product.http_status != 200:
                    _case_item_failure(
                        ledger,
                        stop_code=STOP_SERVICE_ERROR,
                        stage="product_answer",
                        case_id=case.case_id,
                        turn=turn,
                        item_id=item_id,
                        ticket=ticket_payload,
                        error_code=str(product.error_code or product.kind),
                        http_status=int(product.http_status),
                    )
                    turn_row["status"] = "error"
                    turn_row["error_code"] = str(product.error_code or product.kind)

            charged_cny = 0.0
            if gate is not None and ticket is not None:
                try:
                    if turn_row["status"] == "error":
                        gate.settle_failure(
                            ticket,
                            error_code=str(turn_row["error_code"] or STOP_SERVICE_ERROR),
                            elapsed_seconds=elapsed_ms / 1000.0,
                        )
                        ledger.settled_failure += 1
                        ledger.settled_cny += float(getattr(ticket, "bound_cny", 0.0))
                        # 失败结算按门的保守口径占用该笔上界（与 T201 P2Gate 一致）。
                        charged_cny = float(getattr(ticket, "bound_cny", 0.0))
                    else:
                        evidence = (
                            settle_evidence(ticket, product)
                            if settle_evidence is not None and product is not None
                            else None
                        )
                        settled = gate.settle_success(
                            ticket,
                            evidence=evidence,
                            elapsed_seconds=elapsed_ms / 1000.0,
                        )
                        ledger.settled_success += 1
                        charged_cny = _charged_cny(settled, ticket)
                        # 成功路径过去不累计 settled_cny（只有失败才加），会表现成"成功却 0 元"；
                        # 这里按门返回的实际金额记，与 P2Gate.settle_success 的口径一致。
                        ledger.settled_cny += charged_cny
                    billed = True
                    ledger.by_operation[item.operation] = (
                        ledger.by_operation.get(item.operation, 0) + 1
                    )
                    ledger.by_center_cny[item.cost_center] = ledger.by_center_cny.get(
                        item.cost_center, 0.0
                    ) + float(charged_cny)
                except Exception as exc:  # noqa: BLE001 - 结算失败同样停
                    _case_item_failure(
                        ledger,
                        stop_code=STOP_GATE_ERROR,
                        stage="gate_settle",
                        case_id=case.case_id,
                        turn=turn,
                        item_id=item_id,
                        ticket=ticket_payload,
                        error_code=type(exc).__name__,
                    )
                    ledger.gate_notes.append(f"settle:{type(exc).__name__}")
                    turn_row["status"] = "error"
                    turn_row["error_code"] = turn_row["error_code"] or STOP_GATE_ERROR

            ledger.record_request(
                case_id=case.case_id,
                turn=turn,
                item_id=item_id,
                client_request_id=client_request_id,
                ticket=ticket_payload,
                billed=billed,
                status=str(turn_row["status"]),
                product=product,
                error_code=turn_row.get("error_code"),
                elapsed_ms=elapsed_ms,
                include_question=include_question,
                provider_calls=turn_calls,
                charged_cny=charged_cny,
            )
            case_row["turns"].append(turn_row)
            if turn_row["status"] == "error":
                case_row["status"] = "error"
                case_row["error_code"] = turn_row.get("error_code")
                break
        case_row["turns_executed"] = len(case_row["turns"])
        ledger.record_case(case_row)
        if ledger.stop_code is not None:
            break


def _dry_ticket(item: Any, item_id: str, client_request_id: str) -> dict[str, Any]:
    """dry-run 的「在飞请求身份」：字段与 P2RequestTicket 同形，但明确没有预留/计费。"""
    request_id = "p2dry-" + _sha256_bytes(f"{item_id}:{client_request_id}".encode("utf-8"))[:24]
    return {
        "reservation_id": None,
        "request_id": request_id,
        "plan_id": None,
        "plan_sha256": None,
        "item_id": item_id,
        "operation": item.operation,
        "cost_center": item.cost_center,
        "kind": item.price_profile.kind,
        "provider": item.price_profile.provider,
        "model": item.price_profile.model,
        "bound_cny": float(item.bound_cny),
        "case_id": item.case_id,
        "turn": int(item.turn),
        "page": int(item.page),
        "nonce_len": 0,
        "dry_run": True,
    }


# --------------------------------------------------------------------------- #
# 产物
# --------------------------------------------------------------------------- #


def _sanitize_failure(failure: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """holdout 用：只留阶段/停止码/计数与在飞请求身份，不含 case_id/题干。"""
    if not failure:
        return None
    allowed = {"stage", "stop_code", "error_code", "turn", "http_status", "timeout_seconds"}
    payload: dict[str, Any] = {key: failure.get(key) for key in allowed if key in failure}
    ticket = failure.get("ticket")
    if isinstance(ticket, Mapping):
        payload["ticket"] = {
            key: ticket.get(key)
            for key in (
                "request_id",
                "reservation_id",
                "cost_center",
                "operation",
                "bound_cny",
                "dry_run",
            )
        }
    item_id = failure.get("item_id")
    if isinstance(item_id, str):
        payload["item_id_sha256"] = _sha256_bytes(item_id.encode("utf-8"))
    return payload


def _trace_retention(dataset: P2RunDataset, adapter: Any, result: P2RunResult) -> str:
    """trace 保留策略：holdout 未 purge 时本 runner 在发送前就拒了，trace 根本没建。"""
    if dataset.visibility == "holdout" and result.stop_code == STOP_HOLDOUT_REQUIRES_PURGE:
        return "refused-before-start"
    if getattr(adapter, "purge_traces_on_close", False):
        return "purged-at-close"
    return "kept-in-isolated-dir"


def _holdout_aggregate(ledger: P2RunLedger, dataset: P2RunDataset) -> dict[str, Any]:
    turns = [turn for case in ledger.cases for turn in case.get("turns") or ()]
    kinds = ledger.counts("kind")
    branches: dict[str, int] = {}
    for turn in turns:
        branch = str(turn.get("trace_path") or "none")
        branches[branch] = branches.get(branch, 0) + 1
    strata: dict[str, int] = {}
    for case in ledger.cases:
        stratum = str(case.get("stratum") or "unknown")
        strata[stratum] = strata.get(stratum, 0) + 1
    return {
        "schema_version": P2_HOLDOUT_AGGREGATE_SCHEMA_VERSION,
        "run_id": ledger.run_id,
        "plan_id": ledger.plan_id,
        "dataset": {
            "visibility": dataset.visibility,
            "dataset_version": dataset.identity["dataset_version"],
            "manifest_sha256": dataset.identity["manifest_sha256"],
        },
        "cases": {
            "planned": len(dataset.cases),
            "executed": len(ledger.cases),
            "with_error": len([case for case in ledger.cases if case.get("status") == "error"]),
        },
        "turns": {
            "executed": len(turns),
            "with_product_result": len([turn for turn in turns if turn.get("product")]),
        },
        "kinds": kinds,
        "branches": branches,
        "strata_executed": strata,
        "stop_code": ledger.stop_code,
        "failure": _sanitize_failure(ledger.failure),
        "detail_export": False,
    }


def _write_artifacts(
    *,
    plan: P2RunPlan,
    authorization: P2Authorization,
    adapter: ProductEvalAdapter,
    dataset: P2RunDataset,
    ledger: P2RunLedger,
    result: P2RunResult,
    execution: str,
    checks: Sequence[Mapping[str, Any]],
    planned_turns: int,
    executed_turns: int,
    duration_ms: int,
    started_utc: str,
    binding: Mapping[str, Any],
    providers: Mapping[str, Any] | None,
    network: tuple[int, Mapping[str, Any]] | None,
    artifact_failure: P2RunError | None = None,
) -> None:
    """写全部产物；**校验失败也要写**（R2-F-R2-1：不能"已发生请求但无产物"）。

    ``providers/network`` 为 None 表示本轮实测网络边界**没有通过交叉校验**：此时产物里
    明确写 ``available=False`` + 稳定错误码，绝不把未核对的计数当事实落盘。
    """
    run_dir = adapter.paths.run_dir
    measured = [row for row in ledger.requests if int((row.get("provider_calls") or {}).get("outbound", 0)) > 0]
    real_requests = len(measured)
    billed_cny = round(sum(float(row.get("charged_cny") or 0.0) for row in measured), 8)
    if network is None:
        network_payload: dict[str, Any] = {
            "available": False,
            "outbound_attempts": None,
            "code": None if artifact_failure is None else artifact_failure.code,
            "detail": None,
            "measurement": "未通过交叉校验：不把未核对的计数当实测事实",
        }
        providers_payload: dict[str, Any] | None = None
    else:
        outbound_attempts, network_detail = network
        network_payload = {
            "available": True,
            "outbound_attempts": int(outbound_attempts),
            "code": None,
            "measurement": "实测：chat 注入传输 + RAG 供应商 POST 计数（非常量）",
            "detail": dict(network_detail),
        }
        providers_payload = dict(providers or {})

    index_status = adapter.index_status()
    module_dir = Path(__file__).resolve().parent
    # T206-PRE：引用证据只按逐题行判定；H2 不写 case_id（聚合路径不给明细）。
    evidence_status = citation_evidence_status(
        ledger.cases, include_case_ids=dataset.public_details
    )
    binding_payload = {
        "binding_version": binding.get("binding_version"),
        "config_hash": binding.get("config_hash"),
        "complete": bool(binding.get("complete")),
        "missing": list(binding.get("missing") or ()),
        "dataset_version": binding.get("dataset_version"),
        "dataset_sha256": binding.get("dataset_sha256"),
        "manifest_sha256": binding.get("manifest_sha256"),
        "label_version": binding.get("label_version"),
        "pipeline_version": binding.get("pipeline_version"),
        "index_revision": binding.get("index_revision"),
        "provider": binding.get("provider"),
        "gate_version": binding.get("gate_version"),
        "gate_config_hash": binding.get("gate_config_hash"),
        "trace_identity_bound": bool(getattr(adapter, "trace_identity_bound", False)),
    }
    # gate 产物（build_gate_run）要求的身份字段：顶层逐个给，缺就留空让 gate 拒绝。
    business_dates = sorted({str(case.business_date) for case in dataset.cases if str(case.business_date or "")})
    business_date = business_dates[0] if len(business_dates) == 1 else ""
    identity_fields = {
        "suite": str(dataset.identity.get("suite") or ""),
        "dataset_version": str(dataset.identity.get("dataset_version") or ""),
        "dataset_sha256": binding.get("dataset_sha256"),
        "corpus_manifest_sha256": str(dataset.identity.get("manifest_sha256") or ""),
        "business_date": business_date,
        "index_revision": binding.get("index_revision"),
        "pipeline_version": binding.get("pipeline_version"),
        "gate_version": binding.get("gate_version"),
        "label_version": str(dataset.identity.get("label_version") or ""),
        "created_at": started_utc,
        "case_count": int(len(dataset.cases)),
        "config_hash": binding.get("config_hash"),
        "gate_config_hash": binding.get("gate_config_hash"),
        "trace_store": str(adapter.paths.trace_db),
    }
    # 公开 run 把本轮实际加载的题面写成规范 JSONL：既有 gate 需要可解析的数据集才能
    # 做逐题核对（H2 绝不落题面，只留空串 → 由 gate 记 unknown，不放行）。
    dataset_path = ""
    if dataset.public_details:
        target = run_dir / "dataset.jsonl"
        target.write_text(cases_to_jsonl(dataset.cases), encoding="utf-8")
        dataset_path = str(target)
    identity_fields["dataset_path"] = dataset_path
    manifest = {
        "schema_version": P2_RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": ledger.run_id,
        "mode": plan.mode,
        "execution": execution,
        "scope": "end_to_end",
        **identity_fields,
        "business_dates": business_dates,
        "dataset": dataset.as_dict(),
        "binding": binding_payload,
        "plan": {
            "plan_id": plan.plan_id,
            "plan_version": plan.plan_version,
            "plan_sha256": plan.plan_sha256,
            "stage": plan.stage,
            "total_requests": int(plan.total_requests),
            "operations": list(plan.operations),
            "by_operation": plan.requests_by_operation(),
            "worst_case_cny": float(plan.worst_case_cny),
            "reserve_peak_cny": float(plan.reserve_peak_cny),
            "estimated_success_cny": float(plan.estimated_success_cny),
        },
        "authorization": {
            "schema_version": authorization.schema_version,
            "go_document": authorization.go_document,
            "go_sha256": authorization.go_sha256,
            "go_nonce_len": int(authorization.go_nonce_len),
            "issued_by": authorization.issued_by,
            "issued_utc": authorization.issued_utc.isoformat(),
            "expires_utc": authorization.expires_utc.isoformat(),
            "stage": authorization.stage,
            "production_ready": bool(authorization.production_ready),
            "operations": list(authorization.operations),
            "max_requests": int(authorization.max_requests),
            "requests_remaining": int(authorization.requests_remaining),
            "ledger_path": authorization.ledger_path,
        },
        "pipeline": {
            "package": "mktkb-evaluation-p2",
            "package_schema_version": "p2-product-adapter/v0.1",
            "entrypoint": "POST /api/v1/conversations/{id}/messages -> conversations.ask",
            "turn_timeout_seconds": float(
                getattr(adapter, "turn_timeout_seconds", PRODUCT_TURN_TIMEOUT_SECONDS)
            ),
            "trace": {
                "enabled": bool(getattr(adapter, "trace_enabled", False)),
                "content_mode": str(getattr(adapter, "trace_content_mode", "off")),
                "mode": "local",
                "scope": "end_to_end",
                "identity_bound": bool(getattr(adapter, "trace_identity_bound", False)),
                "identity_fields": list(_TRACE_IDENTITY_FIELDS),
            },
            "index": {
                "engine_version": index_status.get("engine_version"),
                "provider_mode": index_status.get("provider_mode"),
                "documents": index_status.get("documents"),
                "units": index_status.get("units"),
                "chunks": index_status.get("chunks"),
            },
            "code_sha256": {
                "product_adapter.py": _sha256_file(module_dir / "product_adapter.py"),
                "p2_runner.py": _sha256_file(module_dir / "p2_runner.py"),
            },
        },
        "providers": providers_payload,
        "paths": adapter.paths.as_dict(),
        "ingest": [receipt.as_dict() for receipt in adapter.ingest_receipts],
        "started_utc": started_utc,
        "finished_utc": utc_iso(),
        "duration_ms": int(duration_ms),
    }
    _write_json(run_dir / "run_manifest.json", manifest)

    branches: dict[str, int] = {}
    for case in ledger.cases:
        for turn in case.get("turns") or ():
            branch = str(turn.get("trace_path") or "none")
            branches[branch] = branches.get(branch, 0) + 1
    summary = {
        "schema_version": P2_RUN_SUMMARY_SCHEMA_VERSION,
        "run_id": ledger.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "status": result.status,
        "stop_code": result.stop_code,
        "execution": execution,
        "visibility": dataset.visibility,
        "binding": binding_payload,
        "citation_evidence": evidence_status,
        "cases": {
            "planned": len(dataset.cases),
            "executed": len(ledger.cases),
            "with_error": len(
                [case for case in ledger.cases if case.get("status") == "error"]
            ),
            "not_executed": max(0, len(dataset.cases) - len(ledger.cases)),
        },
        "turns": {
            "planned": int(planned_turns),
            "executed": int(executed_turns),
            "with_product_result": len(
                [
                    turn
                    for case in ledger.cases
                    for turn in case.get("turns") or ()
                    if turn.get("product")
                ]
            ),
        },
        "kinds": ledger.counts("kind"),
        "branches": branches,
        "requests": {
            "planned": int(plan.total_requests),
            "attempted": len(ledger.requests),
            "reserved": int(ledger.reserved),
            "settled_success": int(ledger.settled_success),
            "settled_failure": int(ledger.settled_failure),
            "real_requests": int(real_requests),
            "billed_cny": float(billed_cny),
        },
        "providers": providers_payload,
        "network": network_payload,
        "holdout": {
            "aggregate_only": dataset.visibility == "holdout",
            "trace_retention": _trace_retention(dataset, adapter, result),
            # A4(F3-a)：这是**策略标签**，不是"已删"的测量结论。真正的证据是
            # close() 返回的 seal_receipt（删不干净即抛错）；产物本身不自证已删。
            "question_store": (
                "policy:delete-at-close"
                if dataset.visibility == "holdout"
                else "policy:keep-in-isolated-dir"
            ),
            "question_store_measurement": (
                "close() 返回 seal_receipt；未删净即报错，summary 不自证已删除"
            ),
        },
        "failure": (
            _sanitize_failure(ledger.failure)
            if dataset.visibility == "holdout"
            else ledger.failure
        ),
        "duration_ms": int(duration_ms),
    }
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "run_result.json", result.as_dict())
    _write_json(
        run_dir / "gate.json",
        {
            "schema_version": P2_RUN_GATE_SCHEMA_VERSION,
            "stage": P2_STAGE,
            "run_id": ledger.run_id,
            "status": result.status,
            "stop_code": result.stop_code,
            "execution": execution,
            "production_ready": bool(authorization.production_ready),
            "binding": binding_payload,
            "citation_evidence": evidence_status,
            "artifact_validation": {
                "ok": artifact_failure is None,
                "code": None if artifact_failure is None else artifact_failure.code,
                "detail": None if artifact_failure is None else artifact_failure.detail,
            },
            "failure": (
                _sanitize_failure(ledger.failure)
                if dataset.visibility == "holdout"
                else ledger.failure
            ),
            # F2：live 且所有发送前检查都过才算"允许真实发送"（桩门会让 live_gate 不通过）。
            "real_sends_allowed": bool(
                execution == EXECUTION_LIVE
                and authorization.production_ready
                and all(bool(check["ok"]) for check in checks)
                and artifact_failure is None
            ),
            "checks": [dict(check) for check in checks],
            "authorization": authorization.as_dict(),
            "gate_notes": list(ledger.gate_notes),
            "quality_gate": "deferred-to-T205",
        },
    )

    public_details = dataset.public_details
    if public_details:
        _write_jsonl(run_dir / "cases.jsonl", ledger.cases)
        _write_jsonl(run_dir / "requests.jsonl", ledger.requests)
        for name in ("holdout_aggregate.json",):
            try:
                (run_dir / name).unlink()
            except FileNotFoundError:
                pass
    else:
        # H2：只留聚合；逐题行/请求行一律不落盘。
        _write_json(run_dir / "holdout_aggregate.json", _holdout_aggregate(ledger, dataset))
        for stale in (run_dir / "cases.jsonl", run_dir / "requests.jsonl"):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass
    # 临时 trace 的清理放在 ``ProductEvalAdapter.close()``：Windows 上仓储未关闭时不能删文件，
    # 所以这里只声明保留策略，真正的 purge 在 close 里（此时已关闭连接）。
