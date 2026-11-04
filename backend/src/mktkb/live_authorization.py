"""S2 产品真实调用闸门：固定 GO + 固定共享账本 + 阶段额度 + 累计请求上限。

为什么单独一个模块（任务单 B2）：
- 产品真实调用有两条入口：rag 内核（embedding/rerank/rag chat）与正文型 chat 网关。
  两者必须用**同一份**授权与**同一只**共享账本，不能各写一套；
- 账本/预算/GO 路径是仓库内固定常量。环境变量最多只能“指名同一个文件”，
  不能换成新账本、仓库外路径或软链（GAP-1/1b）；
- 未签/过期/错阶段/错服务/坏 scope/超累计限额一律在预留与首个 HTTP 之前拒绝（GAP-2）。

与共享账本持续增长的关系（保护前提，不是全状态防篡改）：
- 正常产品代码只以 ``O_APPEND`` 追加，从不截断；GO 绑定的是共享账本的**不可变历史
  前缀**（开头连续的 ``historical_import`` 行）。正常追加 ``reserved``/``result`` 事件后
  前缀不变，所以同一合法运行不会因为正常结算而自我失效；
- 当前实现只拒绝：新空/重置账本、缺失或替换历史前缀、历史占用与预算声明不一致、
  换账本/换固定路径。它**不保证**识别“外部把整份账本回退到签发时或某个仍保留历史前缀
  的较早状态”这种整体回退：累计占用与余额仍会按回退后的文件重算。这不是前缀 hash
  单独能防的，真实阶段必须靠账本文件的只追加/写权限保护，并由经理按保护记录核对；
- 累计请求上限来自账本里的 reservation 计数（跨进程/跨重启共享）。GO 的 nonce
  不是新账本，也不会重置累计预算。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .numeric import NumericInvalid, finite_non_negative, finite_positive, positive_int
from .rag.budget import BudgetLedger, BudgetLedgerInvalid
from .rag.errors import RagConfigError

_REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_LEDGER_PATH = _REPO_ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
SHARED_BUDGET_PATH = _REPO_ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
PRODUCT_GO_PATH = _REPO_ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "S2-LIVE-GO.json"

GO_DOCUMENT = "S2-LIVE-GO"
# 全项目总上限：默认 10 元（历史值）；累计追加由主人显式授权时用环境变量提高，
# 仍是**硬上限**——真实预算文件的 limit_cny 必须与它逐值相等，否则所有真实调用被拒。
TOTAL_LIMIT_CNY = 10.0
TOTAL_LIMIT_ENV = "MKTKB_PROJECT_TOTAL_LIMIT_CNY"
PRODUCT_STAGE_DEFAULT = "S2-DEV"
ALLOWED_SERVICES: tuple[str, ...] = ("rag", "chat")
# GO scope.bindings 字段名/值不得是凭据；计数与公开 artifact 哈希仍可绑定。
_SECRET_BINDING_NAMES = frozenset(
    {
        "key",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "secretkey",
        "password",
        "authorization",
        "auth",
        "cookie",
        "session",
        "session_id",
        "bearer",
        "credential",
        "credentials",
        "access_key",
        "access_key_id",
        "private_key",
        "token",
    }
)
_SECRET_BINDING_SUFFIXES: tuple[str, ...] = ("_key", "_secret", "_password", "_token", "_cookie")
_SECRET_BINDING_WORDS: tuple[str, ...] = ("authorization", "bearer", "apikey", "api_key")
GO_REQUIRED_FIELDS: tuple[str, ...] = (
    "document",
    "stage",
    "authorization",
    "issued_by",
    "nonce",
    "issued_utc",
    "expires_utc",
    "budget_ledger_sha256",
    "scope",
)
MAX_GO_BYTES = 65536
MAX_GO_REQUESTS = 1000


class LiveGateError(ValueError):
    """授权/锚定校验失败。调用方必须在首个 HTTP 之前把它变成拒绝。"""


def _gate_number(value: Any, label: str) -> float:
    try:
        return finite_positive(value, label)
    except NumericInvalid as exc:
        raise LiveGateError(str(exc)) from None


def _gate_non_negative(value: Any, label: str) -> float:
    try:
        return finite_non_negative(value, label)
    except NumericInvalid as exc:
        raise LiveGateError(str(exc)) from None


def _gate_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    try:
        return positive_int(value, label, maximum=maximum)
    except NumericInvalid as exc:
        raise LiveGateError(str(exc)) from None


def project_total_limit_cny() -> float:
    """当前生效的全项目总上限（元）。

    默认 ``TOTAL_LIMIT_CNY``；只有主人显式追加预算时才通过
    ``MKTKB_PROJECT_TOTAL_LIMIT_CNY`` 提高到另一个有限正数。
    该值仍是**硬上限**：真实 budget.json 的 ``limit_cny`` 必须与它逐值相等，
    否则 ``resolve_live_gate`` / ``refresh_request_limits`` 一律拒绝真实调用。
    """
    raw = os.environ.get(TOTAL_LIMIT_ENV)
    if raw is None or not str(raw).strip():
        return TOTAL_LIMIT_CNY
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        raise LiveGateError(f"{TOTAL_LIMIT_ENV} 必须是有限正数") from None
    if not math.isfinite(value) or value <= 0:
        raise LiveGateError(f"{TOTAL_LIMIT_ENV} 必须是有限正数")
    return value


@dataclass(frozen=True)
class LiveAuthorization:
    stage: str
    service: str
    issued_by: str
    nonce: str
    issued_utc: datetime
    expires_utc: datetime
    stage_limit_cny: float
    max_requests: int
    max_request_cny: float
    ledger_sha256: str
    source_path: str
    bindings: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _gate_number(self.stage_limit_cny, "GO 阶段额度")
        _gate_number(self.max_request_cny, "GO 单请求上界")
        _gate_int(self.max_requests, "GO 累计请求上限", maximum=MAX_GO_REQUESTS)

    def as_dict(self) -> dict[str, Any]:
        """可写入证据/诊断的摘要：不含 Key，也不含任何凭据。"""
        return {
            "document": GO_DOCUMENT,
            "stage": self.stage,
            "service": self.service,
            "issued_by": self.issued_by,
            "nonce_len": len(self.nonce),
            "issued_utc": self.issued_utc.isoformat(),
            "expires_utc": self.expires_utc.isoformat(),
            "stage_limit_cny": round(self.stage_limit_cny, 8),
            "max_requests": self.max_requests,
            "max_request_cny": round(self.max_request_cny, 8),
            "ledger_sha256": self.ledger_sha256,
            "source_path": self.source_path,
            "bindings": dict(self.bindings) if self.bindings else None,
        }


@dataclass(frozen=True)
class LiveGate:
    """已通过校验的产品真实调用闸门；``ledger()`` 返回固定路径上的共享账本。"""

    stage: str
    service: str
    ledger_path: Path
    budget_path: Path
    go_path: Path
    stage_limit_cny: float
    max_requests: int
    max_request_cny: float
    total_limit_cny: float
    authorization: LiveAuthorization

    def __post_init__(self) -> None:
        _gate_number(self.stage_limit_cny, "闸门阶段额度")
        _gate_number(self.max_request_cny, "闸门单请求上界")
        _gate_number(self.total_limit_cny, "闸门总预算")
        _gate_int(self.max_requests, "闸门累计请求上限", maximum=MAX_GO_REQUESTS)

    def ledger(self) -> BudgetLedger:
        return BudgetLedger(
            self.ledger_path,
            self.budget_path,
            stage=self.stage,
            stage_limit_cny=self.stage_limit_cny,
            max_requests=self.max_requests,
            request_guard=self.refresh_limits,
            post_reserve_guard=self.recheck_after_reserve,
        )

    def refresh_limits(self, request_bound_cny: float, facts: Mapping[str, Any]) -> tuple[float, int]:
        """请求期复核：GO 有效期/阶段/服务/上限 + 当前共享预算分配取交集。

        由共享账本在预留锁内调用（``facts`` 是同一锁内刚算出的账本事实，避免二次加锁）。
        失败统一抛 ``BudgetLedgerInvalid``：调用方在新增预留/HTTP 之前拒绝。
        """
        return refresh_request_limits(self, request_bound_cny=request_bound_cny, facts=facts)

    def recheck_after_reserve(self, reserved_cny: float, facts: Mapping[str, Any]) -> None:
        """预留成功后、实际 HTTP 发送前的第二次复核。

        与 ``refresh_limits`` 共用同一份 GO/预算事实校验，但本笔预留已经作为 ``reserved``
        事件写进账本、并计入 ``facts``，因此这里只判断“已计入的累计是否仍在上限内”，
        不把本笔再加一次（避免请求上限=1 的合法第 1 次被误拒）。
        失败抛 ``BudgetLedgerInvalid``：调用方在真实 POST 之前拒绝，预留保持原
        reservation_id、不清账、不退款。
        """
        refresh_request_limits(
            self,
            request_bound_cny=reserved_cny,
            facts=facts,
            already_reserved=True,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "service": self.service,
            "ledger_path": _relative(self.ledger_path),
            "budget_path": _relative(self.budget_path),
            "go_path": _relative(self.go_path),
            "stage_limit_cny": round(self.stage_limit_cny, 8),
            "max_requests": self.max_requests,
            "max_request_cny": round(self.max_request_cny, 8),
            "total_limit_cny": self.total_limit_cny,
            "authorization": self.authorization.as_dict(),
        }


def _binding_name_looks_secret(name: str) -> bool:
    """字段名是否像凭据。

    允许绑定公开 artifact 的哈希与计数（如 ``tokenizer_sha256``、``max_output_tokens``），
    但仍然拒绝把密钥/会话令牌写进 GO：完全同名的凭据字段、``*_key``/``*_secret``/
    ``*_password``/``*_token``/``*_cookie`` 后缀、以及包含 authorization/bearer 的名字。
    """
    lowered = name.strip().lower()
    if lowered in _SECRET_BINDING_NAMES:
        return True
    if lowered.endswith(_SECRET_BINDING_SUFFIXES):
        return True
    return any(word in lowered for word in _SECRET_BINDING_WORDS)


def _binding_value_looks_secret(raw: str) -> bool:
    text = raw.strip()
    lowered = text.lower()
    return lowered.startswith(("sk-", "sk_", "bearer ", "bearer_", "basic ")) or "authorization:" in lowered


def _parse_scope_bindings(value: Any) -> dict[str, dict[str, Any]] | None:
    """解析 GO scope.bindings（可选）。

    只允许 ALLOWED_SERVICES 两个服务；每项是扁平标量字典，禁止把密钥/令牌写进 GO。
    缺省返回 None（既有 Mock GO 兼容）；运行器可要求非 None 以强制绑定。
    """
    if value is None:
        return None
    if not isinstance(value, dict) or not value:
        raise LiveGateError("GO scope.bindings 必须是非空对象")
    parsed: dict[str, dict[str, Any]] = {}
    for service, item in value.items():
        if service not in ALLOWED_SERVICES:
            raise LiveGateError(f"GO scope.bindings 含未知服务 {service!r}")
        if not isinstance(item, dict) or not item:
            raise LiveGateError(f"GO scope.bindings[{service!r}] 必须是非空对象")
        clean: dict[str, Any] = {}
        for name, raw in item.items():
            if not isinstance(name, str) or not name:
                raise LiveGateError("GO scope.bindings 的键必须是非空字符串")
            if _binding_name_looks_secret(name):
                raise LiveGateError(f"GO scope.bindings 不允许字段 {name!r}（不得写入密钥/令牌）")
            if isinstance(raw, bool) or isinstance(raw, int):
                clean[name] = raw
            elif isinstance(raw, float):
                # S2-H-R2：价格上界等公开数值可以绑定；NaN/Inf/负数一律拒绝。
                if not math.isfinite(raw) or raw < 0:
                    raise LiveGateError(f"GO scope.bindings[{service!r}].{name} 数值不合法")
                clean[name] = raw
            elif isinstance(raw, str):
                if not raw or len(raw) > 200 or any(ch.isspace() for ch in raw):
                    raise LiveGateError(f"GO scope.bindings[{service!r}].{name} 字符串不合法")
                if _binding_value_looks_secret(raw):
                    raise LiveGateError(f"GO scope.bindings[{service!r}].{name} 的值像凭据，拒绝")
                clean[name] = raw
            else:
                raise LiveGateError(f"GO scope.bindings[{service!r}].{name} 必须是字符串/整数/有限小数/布尔")
        parsed[service] = clean
    return parsed


def assert_provider_binding(
    authorization: LiveAuthorization,
    service: str,
    **expected: Any,
) -> dict[str, Any]:
    """把运行期供应商配置逐项与 GO 绑定核对；任一不匹配在首个预留前拒绝。"""
    if service not in ALLOWED_SERVICES:
        raise LiveGateError(f"服务 {service!r} 不在允许清单")
    bindings = authorization.bindings
    if not bindings:
        raise LiveGateError("GO 未声明 scope.bindings，无法核对供应商/型号/区域绑定")
    binding = bindings.get(service)
    if not isinstance(binding, dict) or not binding:
        raise LiveGateError(f"GO scope.bindings 缺少服务 {service!r}")
    if not expected:
        raise LiveGateError("必须给出要核对的实际供应商配置")
    for key, actual in expected.items():
        if key not in binding:
            raise LiveGateError(f"GO 绑定缺少字段 {service}.{key}")
        declared = binding[key]
        if actual is None:
            raise LiveGateError(f"运行期 {service}.{key} 为空，无法匹配 GO 绑定")
        if isinstance(declared, bool) != isinstance(actual, bool):
            raise LiveGateError(f"{service}.{key} 类型与 GO 绑定不一致")
        if declared != actual:
            raise LiveGateError(
                f"{service}.{key} 运行期={actual!r} 与 GO 绑定={declared!r} 不一致"
            )
    return dict(binding)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- 固定路径


def _ensure_fixed_file(path: Path | str, expected: Path, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or expected.is_symlink():
        raise LiveGateError(f"{label} 不得是软链")
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:  # pragma: no cover - 极端文件系统错误
        raise LiveGateError(f"{label} 路径不可解析") from exc
    if resolved != expected.resolve(strict=False):
        raise LiveGateError(f"{label} 必须固定为 {_relative(expected)}（拒绝替换账本/预算/GO）")
    if not expected.is_file():
        raise LiveGateError(f"{label} 不存在：{_relative(expected)}")
    return expected


def assert_fixed_env_paths(ledger_env: str | None, budget_env: str | None) -> None:
    """环境变量只能指名固定共享账本/预算；省略则使用固定路径。"""
    for raw, expected, label in (
        (ledger_env, SHARED_LEDGER_PATH, "MKTKB_RAG_BUDGET_LEDGER"),
        (budget_env, SHARED_BUDGET_PATH, "MKTKB_RAG_BUDGET_JSON"),
    ):
        if raw is None or not str(raw).strip():
            continue
        _ensure_fixed_file(raw, expected, label)


def product_stage() -> str:
    """产品真实阶段：固定默认 S2-DEV；可用 MKTKB_LIVE_STAGE / MKTKB_RAG_STAGE 显式指定。"""
    for name in ("MKTKB_LIVE_STAGE", "MKTKB_RAG_STAGE"):
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return PRODUCT_STAGE_DEFAULT


# ---------------------------------------------------------------- 账本锚定


def _historical_prefix_bytes(raw: bytes) -> bytes:
    """共享账本的不可变历史前缀：开头连续的 ``historical_import`` 行（含换行）。"""
    prefix = bytearray()
    found = False
    for line in raw.splitlines(keepends=True):
        text = line.strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LiveGateError("共享账本不是逐行 JSON，拒绝真实调用") from exc
        if not isinstance(event, dict) or event.get("event") != "historical_import":
            break
        prefix.extend(line)
        found = True
    if not found:
        # 新空账本/被重置的账本没有历史占用记录，不能作为共享账本。
        raise LiveGateError("共享账本缺少 historical_import 历史记录（拒绝新空/重置账本）")
    return bytes(prefix)


def ledger_binding_ok(bound_sha256: str, ledger_path: Path) -> bool:
    try:
        raw = Path(ledger_path).read_bytes()
    except OSError:
        return False
    bound = str(bound_sha256 or "").strip().lower()
    if len(bound) != 64 or any(char not in "0123456789abcdef" for char in bound):
        return False
    if hashlib.sha256(raw).hexdigest() == bound:
        return True  # 签发后尚无新事件
    prefix = _historical_prefix_bytes(raw)
    if hashlib.sha256(prefix).hexdigest() != bound:
        return False
    return bytes(raw).startswith(prefix)


def _parse_json_object(raw: str, label: str) -> Any:
    """按严格 JSON 解析：拒绝 NaN/Infinity 等非标准常量。"""

    def _reject_constant(value: str) -> Any:
        raise ValueError(f"{label} 含非标准 JSON 常量 {value}")

    return json.loads(raw, parse_constant=_reject_constant)


def _load_budget_json(budget_path: Path) -> dict[str, Any]:
    try:
        data = _parse_json_object(budget_path.read_text(encoding="utf-8"), "共享预算")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise LiveGateError("共享预算文件不可读或不是 JSON") from exc
    if not isinstance(data, dict):
        raise LiveGateError("共享预算文件顶层必须是对象")
    return data


# ---------------------------------------------------------------- GO


def _parse_instant(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise LiveGateError(f"GO {label} 缺失")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveGateError(f"GO {label} 不是 ISO 时间") from exc
    if moment.tzinfo is None:
        raise LiveGateError(f"GO {label} 必须带时区")
    return moment


def _read_go_payload(go_path: Path) -> dict[str, Any]:
    if go_path.stat().st_size > MAX_GO_BYTES:
        raise LiveGateError("GO 文件过大")
    try:
        payload = _parse_json_object(go_path.read_text(encoding="utf-8"), "GO")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise LiveGateError("GO 不是合法结构化授权 JSON") from exc
    if not isinstance(payload, dict):
        raise LiveGateError("GO 顶层必须是对象")
    missing = [key for key in GO_REQUIRED_FIELDS if key not in payload]
    if missing:
        raise LiveGateError(f"GO 缺少字段 {missing}")
    return payload


def load_live_authorization(
    *,
    stage: str,
    service: str,
    go_path: Path | None = None,
    ledger_path: Path | None = None,
    now: datetime | None = None,
) -> LiveAuthorization:
    """按固定 GO 文件校验并返回本阶段/本服务的授权；任何不合法都在发请求前拒绝。"""
    requested_stage = str(stage or "").strip()
    requested_service = str(service or "").strip()
    if not requested_stage:
        raise LiveGateError("必须显式给出阶段")
    if requested_service not in ALLOWED_SERVICES:
        raise LiveGateError(f"服务 {requested_service!r} 不在允许清单 {ALLOWED_SERVICES}")
    fixed_ledger = _ensure_fixed_file(
        ledger_path if ledger_path is not None else SHARED_LEDGER_PATH,
        SHARED_LEDGER_PATH,
        "共享账本",
    )
    target = _ensure_fixed_file(
        go_path if go_path is not None else PRODUCT_GO_PATH,
        PRODUCT_GO_PATH,
        "产品 GO",
    )
    payload = _read_go_payload(target)
    if payload.get("document") != GO_DOCUMENT:
        raise LiveGateError("GO document 必须是 S2-LIVE-GO")
    if str(payload.get("stage") or "").strip() != requested_stage:
        raise LiveGateError(f"GO stage {payload.get('stage')!r} 与请求阶段 {requested_stage!r} 不一致")
    if not str(payload.get("authorization") or "").strip():
        raise LiveGateError("GO 未声明授权说明")
    issued_by = str(payload.get("issued_by") or "").strip()
    if not issued_by or len(issued_by) > 200:
        raise LiveGateError("GO 缺少合法签发人")
    nonce = str(payload.get("nonce") or "").strip()
    if len(nonce) < 16:
        raise LiveGateError("GO nonce 不足 16 字符")
    issued = _parse_instant(payload.get("issued_utc"), "issued_utc")
    expires = _parse_instant(payload.get("expires_utc"), "expires_utc")
    if expires <= issued:
        raise LiveGateError("GO 过期时间必须晚于生效时间")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if moment < issued:
        raise LiveGateError("GO 尚未生效")
    if moment >= expires:
        raise LiveGateError("GO 已过期")
    declared_ledger = str(payload.get("budget_ledger_path") or "").strip()
    if declared_ledger:
        _ensure_fixed_file(declared_ledger, SHARED_LEDGER_PATH, "GO budget_ledger_path")
    bound_hash = str(payload.get("budget_ledger_sha256") or "").strip().lower()
    if not ledger_binding_ok(bound_hash, fixed_ledger):
        raise LiveGateError("GO 未绑定当前共享账本（哈希/历史前缀不匹配）")
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        raise LiveGateError("GO scope 必须是对象")
    bindings = _parse_scope_bindings(scope.get("bindings"))
    services = scope.get("services")
    if not isinstance(services, list) or not services or not all(isinstance(item, str) for item in services):
        raise LiveGateError("GO scope.services 必须是非空字符串数组")
    unknown = [item for item in services if item not in ALLOWED_SERVICES]
    if unknown:
        raise LiveGateError(f"GO scope.services 含未知服务 {unknown}")
    if requested_service not in services:
        raise LiveGateError(f"GO 未授权服务 {requested_service}")
    stage_limits = scope.get("stage_limits_cny")
    if not isinstance(stage_limits, dict):
        raise LiveGateError("GO scope.stage_limits_cny 必须是对象")
    raw_limit = stage_limits.get(requested_stage)
    stage_limit_cny = _gate_number(raw_limit, f"GO 阶段 {requested_stage} 的额度")
    max_requests = _gate_int(
        scope.get("max_requests"), "GO scope.max_requests", maximum=MAX_GO_REQUESTS
    )
    max_request_cny = _gate_number(scope.get("max_request_cny"), "GO scope.max_request_cny")
    return LiveAuthorization(
        stage=requested_stage,
        service=requested_service,
        issued_by=issued_by,
        nonce=nonce,
        issued_utc=issued,
        expires_utc=expires,
        stage_limit_cny=stage_limit_cny,
        max_requests=max_requests,
        max_request_cny=max_request_cny,
        ledger_sha256=bound_hash,
        source_path=_relative(target),
        bindings=bindings,
    )


# ---------------------------------------------------------------- 已授权的调用面


def resolve_live_gate(
    *,
    stage: str,
    service: str,
    requested_stage_limit_cny: float,
    requested_max_requests: int,
    request_bound_cny: float | None = None,
    go_path: Path | None = None,
    ledger_path: Path | None = None,
    budget_path: Path | None = None,
    now: datetime | None = None,
) -> LiveGate:
    """把“环境请求值 + GO + 共享预算分配”收敛成唯一闸门。

    环境请求值只能收窄 GO：阶段额度与累计请求上限取三者最小值；省略/0/负数由调用方
    先行拒绝（这里也再校验一次），不允许回落到 GO 额度。
    """
    requested_limit = _gate_number(requested_stage_limit_cny, "阶段额度")
    requested_max_requests = _gate_int(requested_max_requests, "累计请求上限")
    fixed_budget = _ensure_fixed_file(
        budget_path if budget_path is not None else SHARED_BUDGET_PATH,
        SHARED_BUDGET_PATH,
        "共享预算",
    )
    authorization = load_live_authorization(
        stage=stage, service=service, go_path=go_path, ledger_path=ledger_path, now=now
    )
    budget = _load_budget_json(fixed_budget)
    total_limit = _gate_number(budget.get("limit_cny"), "共享预算 limit_cny")
    expected_total_limit = project_total_limit_cny()
    if abs(total_limit - expected_total_limit) > 1e-9:
        raise LiveGateError(
            f"共享预算总上限必须等于当前项目上限 {expected_total_limit} 元"
            f"（当前 {total_limit}，拒绝替换/放大预算）"
        )
    declared_ledger = str(budget.get("ledger") or "").strip()
    if declared_ledger:
        declared_path = (_REPO_ROOT / declared_ledger).resolve(strict=False)
        if declared_path != SHARED_LEDGER_PATH.resolve(strict=False):
            raise LiveGateError("共享预算声明的账本与固定共享账本不一致")
    stages = budget.get("stages")
    if not isinstance(stages, dict) or stage not in stages:
        raise LiveGateError(f"共享预算没有阶段 {stage} 的分配（默认拒绝）")
    try:
        allocation = _gate_number(stages[stage], f"共享预算阶段 {stage} 的分配")
    except LiveGateError:
        raise LiveGateError(f"共享预算阶段 {stage} 的分配必须是有限正数") from None
    stage_limit = min(requested_limit, authorization.stage_limit_cny, allocation)
    if not math.isfinite(stage_limit) or stage_limit <= 0:
        raise LiveGateError("阶段额度收敛后不是有限正数")
    max_requests = min(requested_max_requests, authorization.max_requests)
    if max_requests <= 0:
        raise LiveGateError("累计请求上限收敛后不是正数")
    if request_bound_cny is not None:
        bound = _gate_number(request_bound_cny, "单请求保守上界")
        if bound > authorization.max_request_cny + 1e-12:
            raise LiveGateError(
                f"单请求保守上界 {bound:.8f} 元超过 GO 允许的 {authorization.max_request_cny:.8f} 元"
            )
    fixed_ledger = _ensure_fixed_file(
        ledger_path if ledger_path is not None else SHARED_LEDGER_PATH,
        SHARED_LEDGER_PATH,
        "共享账本",
    )
    gate = LiveGate(
        stage=authorization.stage,
        service=authorization.service,
        ledger_path=fixed_ledger,
        budget_path=fixed_budget,
        go_path=_ensure_fixed_file(
            go_path if go_path is not None else PRODUCT_GO_PATH, PRODUCT_GO_PATH, "产品 GO"
        ),
        stage_limit_cny=stage_limit,
        max_requests=max_requests,
        max_request_cny=authorization.max_request_cny,
        total_limit_cny=total_limit,
        authorization=authorization,
    )
    ledger = gate.ledger()
    try:
        summary = ledger.summary()
    except BudgetLedgerInvalid as exc:
        raise LiveGateError(f"共享账本不可用：{exc}") from exc
    expected_history = budget.get("historical_conservative_accounted_cny")
    if expected_history is not None:
        expected = _gate_non_negative(expected_history, "共享预算的历史占用金额")
        if abs(summary.historical_conservative_cny - expected) > 1e-9:
            raise LiveGateError(
                "共享账本的历史占用与预算声明不一致（拒绝新账本/改过的历史）"
            )
    if summary.historical_conservative_cny <= 0:
        raise LiveGateError("共享账本没有历史占用记录（拒绝无历史账本）")
    if summary.accounted_cny > summary.total_limit_cny + 1e-9:
        raise LiveGateError("共享账本已超总上限，拒绝真实调用")
    return gate


def refresh_request_limits(
    gate: LiveGate,
    *,
    request_bound_cny: float,
    facts: Mapping[str, Any],
    now: datetime | None = None,
    already_reserved: bool = False,
) -> tuple[float, int]:
    """在真实预留边界复核当前 GO 与共享预算；返回本次可用的阶段额度/请求上限。

    - 构造期校验不能替代请求期：长期存活的 chat/embedding/rerank 实例在每次预留前都
      重新校验 GO 的时间/阶段/服务/单请求上限，以及当前 ``budget.json`` 的阶段分配；
    - 只收窄不放大：与构造期已收敛的额度取交集，GO/预算收窄后下一轮立即按更小额度判断；
    - ``facts`` 是共享账本在同一把锁内算出的历史/累计事实，避免在锁内二次加锁。
    - ``already_reserved=True`` 用于 **预留成功后、POST 前** 的第二次复核：本笔已经写进
      账本并计入 ``facts``，只判断已计入的累计是否仍在当前上限内，绝不把本笔重复计入，
      因此请求上限=1 的合法第 1 次不会被误拒。

    失败统一转成 ``BudgetLedgerInvalid``（稳定 RagError），保证调用方在新增预留与 HTTP
    之前失败，且错误可归因到本次请求期授权/预算复核。
    """
    try:
        bound = _gate_number(request_bound_cny, "单请求保守上界")
        _gate_number(gate.stage_limit_cny, "闸门阶段额度")
        _gate_int(gate.max_requests, "闸门累计请求上限", maximum=MAX_GO_REQUESTS)
        _ensure_fixed_file(gate.ledger_path, SHARED_LEDGER_PATH, "共享账本")
        _ensure_fixed_file(gate.budget_path, SHARED_BUDGET_PATH, "共享预算")
        _ensure_fixed_file(gate.go_path, PRODUCT_GO_PATH, "产品 GO")
        authorization = load_live_authorization(
            stage=gate.stage,
            service=gate.service,
            go_path=gate.go_path,
            ledger_path=gate.ledger_path,
            now=now,
        )
        budget = _load_budget_json(gate.budget_path)
        total_limit = _gate_number(budget.get("limit_cny"), "共享预算 limit_cny")
        expected_total_limit = project_total_limit_cny()
        if abs(total_limit - expected_total_limit) > 1e-9:
            raise LiveGateError(
                f"共享预算总上限必须等于当前项目上限 {expected_total_limit} 元（拒绝替换/放大预算）"
            )
        declared_ledger = str(budget.get("ledger") or "").strip()
        if declared_ledger:
            declared_path = (_REPO_ROOT / declared_ledger).resolve(strict=False)
            if declared_path != SHARED_LEDGER_PATH.resolve(strict=False):
                raise LiveGateError("共享预算声明的账本与固定共享账本不一致")
        stages = budget.get("stages")
        if not isinstance(stages, dict) or gate.stage not in stages:
            raise LiveGateError(f"共享预算没有阶段 {gate.stage} 的分配（默认拒绝）")
        allocation = _gate_number(
            stages[gate.stage], f"共享预算阶段 {gate.stage} 的分配"
        )
        stage_limit = min(gate.stage_limit_cny, authorization.stage_limit_cny, allocation)
        if not math.isfinite(stage_limit) or stage_limit <= 0:
            raise LiveGateError("请求期阶段额度收敛后不是有限正数")
        max_requests = min(gate.max_requests, authorization.max_requests)
        if max_requests <= 0:
            raise LiveGateError("请求期累计请求上限收敛后不是正数")
        if bound > authorization.max_request_cny + 1e-12:
            raise LiveGateError(
                f"单请求保守上界 {bound:.8f} 元超过当前 GO 允许的 "
                f"{authorization.max_request_cny:.8f} 元"
            )
        historical = _gate_non_negative(facts.get("historical"), "账本历史占用")
        expected_history = budget.get("historical_conservative_accounted_cny")
        if expected_history is not None:
            expected = _gate_non_negative(expected_history, "共享预算的历史占用金额")
            if abs(historical - expected) > 1e-9:
                raise LiveGateError("共享账本的历史占用与预算声明不一致")
        if historical <= 0:
            raise LiveGateError("共享账本没有历史占用记录（拒绝无历史账本）")
        accounted = _gate_non_negative(facts.get("accounted"), "账本累计占用")
        if accounted > total_limit + 1e-9:
            raise LiveGateError("共享账本已超总上限，拒绝真实调用")
        if already_reserved:
            # 本笔预留已写入账本并计入 facts：只校验“已计入的累计”是否仍在上限内。
            count = facts.get("reservation_count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise LiveGateError("账本累计请求数不合法")
            if count > max_requests:
                raise LiveGateError(
                    f"当前累计请求数 {count} 已超过请求期上限 {max_requests}（预留后复核）"
                )
            stage_accounted = _gate_non_negative(facts.get("stage_accounted"), "账本阶段占用")
            if stage_accounted > stage_limit + 1e-12:
                raise LiveGateError(
                    f"当前阶段占用 {stage_accounted:.8f} 元超过阶段额度 "
                    f"{stage_limit:.8f} 元（预留后复核）"
                )
        return stage_limit, max_requests
    except (LiveGateError, NumericInvalid) as exc:
        raise BudgetLedgerInvalid(f"请求期授权/预算复核失败：{exc}") from None
    except Exception as exc:  # noqa: BLE001 - 请求期任何读取/校验异常都必须默认拒绝
        raise BudgetLedgerInvalid(
            f"请求期授权/预算复核异常：{type(exc).__name__}"
        ) from None


def gate_refusal(exc: Exception) -> ValueError:
    """统一成 ValueError（产品 live 入口对外的稳定错误类型），保留原因。"""
    if isinstance(exc, RagConfigError):
        return exc
    return ValueError(str(exc) or type(exc).__name__)


__all__ = [
    "ALLOWED_SERVICES",
    "GO_DOCUMENT",
    "LiveAuthorization",
    "LiveGate",
    "LiveGateError",
    "PRODUCT_GO_PATH",
    "SHARED_BUDGET_PATH",
    "SHARED_LEDGER_PATH",
    "TOTAL_LIMIT_CNY",
    "TOTAL_LIMIT_ENV",
    "assert_fixed_env_paths",
    "gate_refusal",
    "ledger_binding_ok",
    "load_live_authorization",
    "product_stage",
    "project_total_limit_cny",
    "refresh_request_limits",
    "resolve_live_gate",
]
