"""P2-T208-OFFLINE：Ragas 受控适配器（唯一产品侧模块）。

边界（见 ``docs/evaluation/p2-ragas-contract.md``）：

- **默认关闭、惰性导入**：``ragas`` 只在 :func:`score_ragas` 内按需导入；缺依赖时本模块
  仍可 import，返回稳定 blocked 结果，不影响既有评测模块/测试。
- **只读已有 run**：``run`` 是调用方给的 :class:`RagasRun`，必须是公共/合成答案；适配器
  不调用产品、不重新生成答案、不读取 H2 封存目录。
- **受控 judge**：judge 是注入的合成传输（``execution_mode="synthetic"``）；本模块从不
  构造真实 provider，也不读取 key/.env。
- **统一预算网关**：Ragas 框架内每一次 LLM/embedding/分解调用都经
  :class:`JudgeBudgetGateway`；自动重试固定 0，失败即停止；账本是临时合成账本
  （stage=``P2-RAGAS-OFFLINE``），不接共享真实账本/GO。
- **结果版本化**：固定 schema、指标/框架/judge 版本、unknown 原因码、调用计数与模拟
  费用；不输出自由异常文本、堆栈或 repr。
- **辅助定位**：软分只作辅助，不产生通过/发布判定，也不能抵消确定性硬失败。
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, TypeVar

from ..rag.budget import BudgetLedger, Reservation
from ..rag.errors import BudgetError, BudgetExceeded, BudgetLedgerInvalid, RequestLimitExceeded

__all__ = [
    "RAGAS_ADAPTER_VERSION",
    "RAGAS_AUTHORIZATION_SCHEMA_VERSION",
    "RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY",
    "RAGAS_FACTUAL_CORRECTNESS_CALLS",
    "RAGAS_FAITHFULNESS_CALLS",
    "RAGAS_FAITHFULNESS_SEQUENCE",
    "RAGAS_FACTUAL_CORRECTNESS_SEQUENCE",
    "RAGAS_LEDGER_STAGE",
    "RAGAS_LOCKED_RAGAS_VERSION",
    "RAGAS_REASON_CODES",
    "RAGAS_RESULT_SCHEMA_VERSION",
    "RAGAS_RUN_SCHEMA_VERSION",
    "RAGAS_WORST_CASE_JUDGE_CALLS",
    "JudgeBudgetGateway",
    "RagasAdapterError",
    "RagasAuthorization",
    "RagasBudgetError",
    "RagasCallTicket",
    "RagasCase",
    "RagasCaseScore",
    "RagasJudgeError",
    "RagasRun",
    "RagasScoreResult",
    "open_synthetic_ledger",
    "score_ragas",
]

RAGAS_ADAPTER_VERSION = "p2-ragas-adapter/v0.1"
RAGAS_RUN_SCHEMA_VERSION = "p2-ragas-run/v0.1"
RAGAS_AUTHORIZATION_SCHEMA_VERSION = "p2-ragas-authorization/v0.1"
RAGAS_RESULT_SCHEMA_VERSION = "p2-ragas-result/v0.1"

#: 本轮执行时锁定并实际安装的 Ragas 版本；不是范围、不是“最新版”。
RAGAS_LOCKED_RAGAS_VERSION = "0.4.4"

#: 独立合成账本阶段名：与共享真实账本/P2-LIVE 分开。
RAGAS_LEDGER_STAGE = "P2-RAGAS-OFFLINE"

#: 单 case 最坏 judge 调用数（先声明再执行）：
#: Faithfulness = 语句分解 1 + NLI 1；FactualCorrectness(f1) = 双向分解 2 + 双向 NLI 2。
RAGAS_FAITHFULNESS_CALLS = 2
RAGAS_FACTUAL_CORRECTNESS_CALLS = 4
RAGAS_WORST_CASE_JUDGE_CALLS = (
    RAGAS_FAITHFULNESS_CALLS + RAGAS_FACTUAL_CORRECTNESS_CALLS
)

#: 每个指标必须出现的**精确**结构化调用序列（顺序+次数）；不是“包含即通过”。
RAGAS_FAITHFULNESS_SEQUENCE = ("StatementGeneratorOutput", "NLIStatementOutput")
RAGAS_FACTUAL_CORRECTNESS_SEQUENCE = (
    "ClaimDecompositionOutput",
    "NLIStatementOutput",
    "ClaimDecompositionOutput",
    "NLIStatementOutput",
)
RAGAS_EXPECTED_METRIC_SEQUENCE = {
    "faithfulness": RAGAS_FAITHFULNESS_SEQUENCE,
    "factual_correctness": RAGAS_FACTUAL_CORRECTNESS_SEQUENCE,
}

#: 合成 judge 单次调用的模拟费用（元）。仅用于隔离预算网关演示，不是供应商报价。
RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY = 0.0005

#: 固定原因码集合：结果里只出现这些码，不出现自由异常文本。
RAGAS_REASON_CODES = frozenset(
    {
        "adapter_internal_error",
        "authorization_expired",
        "authorization_invalid_type",
        "authorization_missing",
        "authorization_mode_forbidden",
        "authorization_not_yet_valid",
        "authorization_plan_mismatch",
        "authorization_production_ready_forbidden",
        "authorization_run_mismatch",
        "authorization_value_invalid",
        "budget_exhausted",
        "call_budget_exhausted",
        "case_call_ceiling_exceeded",
        "case_context_missing",
        "clock_invalid",
        "duplicate_settlement",
        "framework_bypass_detected",
        "framework_error",
        "gateway_stopped",
        "invalid_metric_value",
        "judge_identity_mismatch",
        "judge_invalid",
        "judge_missing",
        "judge_not_synthetic",
        "judge_output_invalid",
        "judge_service_error",
        "ledger_refused",
        "per_call_budget_exceeded",
        "ragas_import_failed",
        "ragas_metrics_unavailable",
        "ragas_not_installed",
        "ragas_version_mismatch",
        "refusal_not_applicable",
        "run_invalid_type",
        "run_source_not_allowed",
        "synthetic_ledger_invalid",
        "ticket_unknown",
    }
)

_METRIC_NAMES = ("faithfulness", "factual_correctness")
_ALLOWED_RUN_SOURCES = ("synthetic", "public_fixture")


class RagasAdapterError(ValueError):
    """适配器稳定错误：只携带原因码，不携带原始异常文本。"""

    def __init__(self, code: str) -> None:
        clean = str(code)
        super().__init__(clean)
        self.code = clean


class RagasBudgetError(RagasAdapterError):
    """预算/授权网关拒绝（预留前或发送前）。"""


class RagasJudgeError(RagasAdapterError):
    """judge 传输失败或返回非法结构；原始异常文本不向上传播。"""


# --------------------------------------------------------------------------- #
# 严格 DTO
# --------------------------------------------------------------------------- #


def _text(value: Any, *, name: str, maximum: int = 20000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RagasAdapterError("run_invalid_type")
    return value


def _identifier(value: Any, *, name: str, maximum: int = 96) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RagasAdapterError("run_invalid_type")
    return value


def _sha256_hex(value: Any, *, name: str, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise RagasAdapterError(code)
    try:
        int(value, 16)
    except ValueError:
        raise RagasAdapterError(code) from None
    return value.lower()


def _aware_instant(value: Any, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RagasAdapterError(code)
    return value.astimezone(timezone.utc)


def _finite_positive(value: Any, *, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RagasAdapterError(code)
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise RagasAdapterError(code)
    return number


def _positive_int(value: Any, *, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RagasAdapterError(code)
    return int(value)


@dataclass(frozen=True)
class RagasCase:
    """一条已存在的公共/合成答案；适配器不生成、不改写、不重跑。"""

    case_id: str
    question: str
    answer: str
    contexts: tuple[str, ...]
    reference: str
    refusal: bool = False
    hard_failure: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.case_id, name="case_id", maximum=96)
        _text(self.question, name="question")
        _text(self.answer, name="answer")
        _text(self.reference, name="reference")
        if not isinstance(self.refusal, bool):
            raise RagasAdapterError("run_invalid_type")
        if isinstance(self.contexts, (str, bytes)) or not isinstance(self.contexts, Sequence):
            raise RagasAdapterError("run_invalid_type")
        contexts = tuple(self.contexts)
        if not contexts and not self.refusal:
            raise RagasAdapterError("run_invalid_type")
        for item in contexts:
            if not isinstance(item, str) or not item.strip():
                raise RagasAdapterError("run_invalid_type")
        object.__setattr__(self, "contexts", contexts)
        if self.hard_failure is not None:
            _identifier(self.hard_failure, name="hard_failure", maximum=64)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "answer": self.answer,
            "contexts": list(self.contexts),
            "reference": self.reference,
            "refusal": self.refusal,
            "hard_failure": self.hard_failure,
        }


@dataclass(frozen=True)
class RagasRun:
    """已冻结的离线 run：只含公共/自建合成答案。"""

    run_id: str
    plan_id: str
    plan_sha256: str
    source: str
    cases: tuple[RagasCase, ...]
    schema_version: str = RAGAS_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RAGAS_RUN_SCHEMA_VERSION:
            raise RagasAdapterError("run_invalid_type")
        _identifier(self.run_id, name="run_id", maximum=96)
        _identifier(self.plan_id, name="plan_id", maximum=96)
        _sha256_hex(self.plan_sha256, name="plan_sha256", code="run_invalid_type")
        if self.source not in _ALLOWED_RUN_SOURCES:
            raise RagasAdapterError("run_source_not_allowed")
        if isinstance(self.cases, (str, bytes)) or not isinstance(self.cases, Sequence):
            raise RagasAdapterError("run_invalid_type")
        cases = tuple(self.cases)
        if not cases or not all(isinstance(case, RagasCase) for case in cases):
            raise RagasAdapterError("run_invalid_type")
        identifiers = [case.case_id for case in cases]
        if len(set(identifiers)) != len(identifiers):
            raise RagasAdapterError("run_invalid_type")
        object.__setattr__(self, "cases", cases)

    @property
    def digest(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "source": self.source,
            "cases": [case.as_dict() for case in self.cases],
        }
        return _sha256_json(payload)


@dataclass(frozen=True)
class RagasAuthorization:
    """离线合成授权：只能用于 synthetic judge，不能冒充真实 GO/账本授权。"""

    authorization_id: str
    run_id: str
    plan_id: str
    plan_sha256: str
    judge_id: str
    judge_version: str
    issued_utc: datetime
    expires_utc: datetime
    max_calls_per_case: int
    max_calls_total: int
    max_cny_per_call: float
    max_cny_total: float
    mode: str = "offline_synthetic"
    production_ready: bool = False
    schema_version: str = RAGAS_AUTHORIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RAGAS_AUTHORIZATION_SCHEMA_VERSION:
            raise RagasAdapterError("authorization_value_invalid")
        for value, maximum in (
            (self.authorization_id, 96),
            (self.run_id, 96),
            (self.plan_id, 96),
            (self.judge_id, 96),
            (self.judge_version, 64),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise RagasAdapterError("authorization_value_invalid")
        _sha256_hex(
            self.plan_sha256, name="plan_sha256", code="authorization_value_invalid"
        )
        issued = _aware_instant(self.issued_utc, code="authorization_value_invalid")
        expires = _aware_instant(self.expires_utc, code="authorization_value_invalid")
        if expires <= issued:
            raise RagasAdapterError("authorization_value_invalid")
        _positive_int(self.max_calls_per_case, code="authorization_value_invalid")
        _positive_int(self.max_calls_total, code="authorization_value_invalid")
        _finite_positive(self.max_cny_per_call, code="authorization_value_invalid")
        _finite_positive(self.max_cny_total, code="authorization_value_invalid")
        if self.mode != "offline_synthetic":
            raise RagasAdapterError("authorization_mode_forbidden")
        if self.production_ready is not False:
            raise RagasAdapterError("authorization_production_ready_forbidden")

    def as_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "judge_id": self.judge_id,
            "judge_version": self.judge_version,
            "issued_utc": self.issued_utc.isoformat(),
            "expires_utc": self.expires_utc.isoformat(),
            "max_calls_per_case": int(self.max_calls_per_case),
            "max_calls_total": int(self.max_calls_total),
            "max_cny_per_call": float(self.max_cny_per_call),
            "max_cny_total": float(self.max_cny_total),
            "mode": self.mode,
            "production_ready": bool(self.production_ready),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RagasCaseScore:
    """单 case 固定结果；不包含题面/答案/上下文/参考原文。"""

    case_id: str
    status: str
    faithfulness: float | None
    factual_correctness: float | None
    reason_code: str | None
    judge_calls: int
    embedding_calls: int
    charged_cny: float
    hard_failure: str | None
    metric_call_sequence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "faithfulness": self.faithfulness,
            "factual_correctness": self.factual_correctness,
            "reason_code": self.reason_code,
            "judge_calls": int(self.judge_calls),
            "embedding_calls": int(self.embedding_calls),
            "charged_cny": round(float(self.charged_cny), 10),
            "hard_failure": self.hard_failure,
            "metric_call_sequence": list(self.metric_call_sequence),
        }


@dataclass(frozen=True)
class RagasScoreResult:
    """版本化离线辅助结果：不产生通过/发布判定。"""

    schema_version: str
    adapter_version: str
    run_id: str | None
    run_digest: str | None
    status: str
    complete: bool
    coverage_complete: bool
    auxiliary_only: bool
    quality_decision: None
    reason_code: str | None
    ragas_version: str | None
    python_version: str
    metric_specs: tuple[Mapping[str, Any], ...]
    prompt_digest: str | None
    judge: Mapping[str, Any] | None
    authorization: Mapping[str, Any] | None
    cases: tuple[RagasCaseScore, ...]
    counts: Mapping[str, int]
    cost: Mapping[str, Any]
    ledger: Mapping[str, Any] | None
    declared_worst_case_judge_calls: int
    hard_failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "adapter_version": self.adapter_version,
            "run_id": self.run_id,
            "run_digest": self.run_digest,
            "status": self.status,
            "complete": bool(self.complete),
            "coverage_complete": bool(self.coverage_complete),
            "auxiliary_only": bool(self.auxiliary_only),
            "quality_decision": self.quality_decision,
            "reason_code": self.reason_code,
            "ragas_version": self.ragas_version,
            "python_version": self.python_version,
            "metric_specs": [dict(spec) for spec in self.metric_specs],
            "prompt_digest": self.prompt_digest,
            "judge": None if self.judge is None else dict(self.judge),
            "authorization": None if self.authorization is None else dict(self.authorization),
            "cases": [case.to_dict() for case in self.cases],
            "counts": dict(self.counts),
            "cost": dict(self.cost),
            "ledger": None if self.ledger is None else dict(self.ledger),
            "declared_worst_case_judge_calls": int(self.declared_worst_case_judge_calls),
            "hard_failures": list(self.hard_failures),
        }


# --------------------------------------------------------------------------- #
# 哈希/时间/摘要辅助
# --------------------------------------------------------------------------- #


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_now(clock: Callable[[], datetime] | None) -> datetime | None:
    try:
        value = (clock or _utcnow)()
    except Exception:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    """对伪造/残缺 DTO 也安全的 getattr：属性缺失/属性抛错都返回默认值。"""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _safe_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _safe_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _safe_iso(value: Any) -> str | None:
    if isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc).isoformat()
    return None


def _safe_run_info(run: Any) -> tuple[str | None, str | None, int]:
    """从任意对象安全提取 run 摘要；伪造 RagasRun（缺字段/属性抛错）不得再抛。"""
    if not isinstance(run, RagasRun):
        return None, None, 0
    run_id = _safe_text(_safe_get(run, "run_id"))
    digest = None
    try:
        digest = _safe_text(run.digest)
    except Exception:
        digest = None
    cases = _safe_get(run, "cases", ())
    try:
        total = len(cases) if not isinstance(cases, (str, bytes)) else 0
    except Exception:
        total = 0
    return run_id, digest, int(total)


def _validate_run(run: Any) -> str | None:
    """二次校验 run（防 object.__new__ 伪造）；返回固定原因码或 None。"""
    if not isinstance(run, RagasRun):
        return "run_invalid_type"
    try:
        if _safe_get(run, "schema_version") != RAGAS_RUN_SCHEMA_VERSION:
            return "run_invalid_type"
        _identifier(_safe_get(run, "run_id"), name="run_id", maximum=96)
        _identifier(_safe_get(run, "plan_id"), name="plan_id", maximum=96)
        _sha256_hex(
            _safe_get(run, "plan_sha256"),
            name="plan_sha256",
            code="run_invalid_type",
        )
        source = _safe_get(run, "source")
        if source not in _ALLOWED_RUN_SOURCES:
            return "run_source_not_allowed"
        cases = _safe_get(run, "cases")
        if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence) or not cases:
            return "run_invalid_type"
        seen: set[str] = set()
        for case in cases:
            if not isinstance(case, RagasCase):
                return "run_invalid_type"
            case_id = _identifier(
                _safe_get(case, "case_id"), name="case_id", maximum=96
            )
            _text(_safe_get(case, "question"), name="question")
            _text(_safe_get(case, "answer"), name="answer")
            _text(_safe_get(case, "reference"), name="reference")
            refusal = _safe_get(case, "refusal")
            if not isinstance(refusal, bool):
                return "run_invalid_type"
            contexts = _safe_get(case, "contexts")
            if isinstance(contexts, (str, bytes)) or not isinstance(contexts, Sequence):
                return "run_invalid_type"
            if not contexts and not refusal:
                return "run_invalid_type"
            for item in contexts:
                if not isinstance(item, str) or not item.strip():
                    return "run_invalid_type"
            hard_failure = _safe_get(case, "hard_failure")
            if hard_failure is not None:
                _identifier(hard_failure, name="hard_failure", maximum=64)
            if case_id in seen:
                return "run_invalid_type"
            seen.add(case_id)
    except (RagasAdapterError, AttributeError, TypeError, ValueError):
        return "run_invalid_type"
    return None


def _judge_summary(judge: Any) -> dict[str, Any] | None:
    if judge is None:
        return None
    return {
        "judge_id": _safe_text(_safe_get(judge, "judge_id")),
        "judge_version": _safe_text(_safe_get(judge, "judge_version")),
        "execution_mode": _safe_text(_safe_get(judge, "execution_mode")),
    }


def _auth_summary(authorization: RagasAuthorization | None) -> dict[str, Any] | None:
    if authorization is None:
        return None
    return {
        "authorization_id": _safe_text(_safe_get(authorization, "authorization_id")),
        "run_id": _safe_text(_safe_get(authorization, "run_id")),
        "plan_id": _safe_text(_safe_get(authorization, "plan_id")),
        "plan_sha256": _safe_text(_safe_get(authorization, "plan_sha256")),
        "judge_id": _safe_text(_safe_get(authorization, "judge_id")),
        "judge_version": _safe_text(_safe_get(authorization, "judge_version")),
        "issued_utc": _safe_iso(_safe_get(authorization, "issued_utc")),
        "expires_utc": _safe_iso(_safe_get(authorization, "expires_utc")),
        "max_calls_per_case": _safe_int(_safe_get(authorization, "max_calls_per_case")),
        "max_calls_total": _safe_int(_safe_get(authorization, "max_calls_total")),
        "max_cny_per_call": _safe_float(_safe_get(authorization, "max_cny_per_call")),
        "max_cny_total": _safe_float(_safe_get(authorization, "max_cny_total")),
        "mode": _safe_text(_safe_get(authorization, "mode")),
        "production_ready": _safe_bool(_safe_get(authorization, "production_ready")),
    }


def _base_counts(total: int) -> dict[str, int]:
    return {
        "cases": int(total),
        "scored": 0,
        "unknown": 0,
        "blocked": 0,
        "judge_calls": 0,
        "embedding_calls": 0,
    }


def _base_cost(per_call_cny: float = RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY) -> dict[str, Any]:
    return {
        "currency": "CNY",
        "synthetic": True,
        "per_call_cny": float(per_call_cny),
        "reserved_cny": 0.0,
        "charged_cny": 0.0,
    }


def _blocked_result(
    reason: str,
    *,
    run: Any = None,
    authorization: RagasAuthorization | None = None,
    judge: Any = None,
    ragas_version: str | None = None,
    per_call_cny: float = RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY,
) -> RagasScoreResult:
    code = reason if reason in RAGAS_REASON_CODES else "adapter_internal_error"
    run_id, digest, total = _safe_run_info(run)
    counts = _base_counts(total)
    counts["blocked"] = total
    return RagasScoreResult(
        schema_version=RAGAS_RESULT_SCHEMA_VERSION,
        adapter_version=RAGAS_ADAPTER_VERSION,
        run_id=run_id,
        run_digest=digest,
        status="blocked",
        complete=False,
        coverage_complete=False,
        auxiliary_only=True,
        quality_decision=None,
        reason_code=code,
        ragas_version=ragas_version,
        python_version=_python_version(),
        metric_specs=(),
        prompt_digest=None,
        judge=_judge_summary(judge),
        authorization=_auth_summary(authorization),
        cases=(),
        counts=counts,
        cost=_base_cost(per_call_cny),
        ledger=None,
        declared_worst_case_judge_calls=RAGAS_WORST_CASE_JUDGE_CALLS,
        hard_failures=(),
    )


# --------------------------------------------------------------------------- #
# judge / 指标 / 提示词指纹
# --------------------------------------------------------------------------- #


def _load_ragas() -> Any:
    """惰性导入：缺依赖时抛 ImportError，由调用方转 blocked，不在 import 期联网。"""
    import ragas  # noqa: PLC0415 - 故意惰性

    return ragas


def _build_metrics(llm: Any) -> tuple[Any, Any]:
    """真实 Ragas collections 指标；测试可 monkeypatch 本函数模拟非法值/bypass。"""
    from ragas.metrics.collections import FactualCorrectness, Faithfulness  # noqa: PLC0415

    return (
        Faithfulness(llm=llm),
        FactualCorrectness(llm=llm, mode="f1", atomicity="low", coverage="low"),
    )


def _make_llm(gateway: "JudgeBudgetGateway") -> Any:
    from ragas.llms.base import InstructorBaseRagasLLM  # noqa: PLC0415

    class _BudgetedInstructorLLM(InstructorBaseRagasLLM):
        def __init__(self, inner: "JudgeBudgetGateway") -> None:
            self._inner = inner

        async def agenerate(self, prompt, response_model):  # noqa: ANN001
            return await self._inner.agenerate(prompt, response_model)

        def generate(self, prompt, response_model):  # noqa: ANN001
            raise RagasAdapterError("framework_error")

    return _BudgetedInstructorLLM(gateway)


def _prompt_digest(metrics: Sequence[Any]) -> str | None:
    parts: list[dict[str, Any]] = []
    for metric in metrics:
        for attribute in (
            "statement_generator_prompt",
            "nli_statement_prompt",
            "prompt",
            "nli_prompt",
        ):
            prompt = getattr(metric, attribute, None)
            if prompt is None:
                continue
            parts.append(
                {
                    "module": type(prompt).__module__,
                    "class": type(prompt).__name__,
                    "instruction": str(getattr(prompt, "instruction", "")),
                    "examples": repr(getattr(prompt, "examples", ())),
                }
            )
    if not parts:
        return None
    return _sha256_json({"prompts": parts})


def _metric_specs(ragas_module: Any, faith: Any, factual: Any) -> tuple[dict[str, Any], ...]:
    version = str(getattr(ragas_module, "__version__", ""))
    return (
        {
            "name": "faithfulness",
            "class": type(faith).__name__,
            "module": type(faith).__module__,
            "version": version,
            "calls_per_case": RAGAS_FAITHFULNESS_CALLS,
        },
        {
            "name": "factual_correctness",
            "class": type(factual).__name__,
            "module": type(factual).__module__,
            "version": version,
            "mode": "f1",
            "atomicity": "low",
            "coverage": "low",
            "calls_per_case": RAGAS_FACTUAL_CORRECTNESS_CALLS,
        },
    )


# --------------------------------------------------------------------------- #
# 预算网关
# --------------------------------------------------------------------------- #


class _SyntheticReserveGuard:
    """发送前的真实账本复核：存在、未结算、金额/绑定一致、限额未超。

    ``BudgetLedger.recheck_reservation`` 只做“存在 reserved 行”检查；本 guard 由
    ``post_reserve_guard`` 在账本锁内调用，补上“未被结算/金额未被篡改/上限未超”的检查。
    """

    def __init__(self, ledger_path: Path, authorization: RagasAuthorization) -> None:
        self._ledger_path = Path(ledger_path)
        self._authorization = authorization
        self._expected: Reservation | None = None

    def expect(self, reservation: Reservation) -> None:
        self._expected = reservation

    def clear(self) -> None:
        self._expected = None

    def _events(self) -> list[dict[str, Any]]:
        try:
            raw = self._ledger_path.read_text(encoding="utf-8")
        except OSError:
            raise BudgetLedgerInvalid("合成账本不可读，禁发") from None
        events: list[dict[str, Any]] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                raise BudgetLedgerInvalid("合成账本行不是 JSON，禁发") from None
            if not isinstance(event, dict):
                raise BudgetLedgerInvalid("合成账本事件不是对象，禁发")
            events.append(event)
        return events

    def check(self, amount: float, facts: Mapping[str, Any]) -> None:
        expected = self._expected
        if expected is None:
            raise BudgetLedgerInvalid("复核缺少当前 reservation 上下文，禁发")
        events = self._events()
        reserved = [
            event
            for event in events
            if event.get("event") == "reserved"
            and event.get("reservation_id") == expected.reservation_id
        ]
        results = [
            event
            for event in events
            if event.get("event") == "result"
            and event.get("reservation_id") == expected.reservation_id
        ]
        if len(reserved) != 1:
            raise BudgetLedgerInvalid("发送前复核找不到唯一 reserved 行，禁发")
        if results:
            raise BudgetLedgerInvalid("发送前复核发现该预留已被结算，禁发")
        row = reserved[0]
        try:
            reserved_amount = float(row.get("reserve_cny"))
            expected_amount = float(expected.reserve_cny)
        except (TypeError, ValueError):
            raise BudgetLedgerInvalid("发送前复核预留金额非法，禁发") from None
        if abs(reserved_amount - expected_amount) > 1e-12:
            raise BudgetLedgerInvalid("发送前复核预留金额被篡改，禁发")
        for key in ("stage", "kind", "provider", "model"):
            if row.get(key) != getattr(expected, key):
                raise BudgetLedgerInvalid("发送前复核预留绑定字段不一致，禁发")
        if abs(float(amount) - expected_amount) > 1e-12:
            raise BudgetLedgerInvalid("发送前复核金额参数不一致，禁发")
        if int(facts.get("reservation_count") or 0) > int(self._authorization.max_calls_total):
            raise BudgetLedgerInvalid("发送前复核累计请求数超上限，禁发")
        if float(facts.get("stage_accounted") or 0.0) > float(
            self._authorization.max_cny_total
        ) + 1e-12:
            raise BudgetLedgerInvalid("发送前复核阶段金额超上限，禁发")
        center_accounted = facts.get("center_accounted")
        center_value = (
            float(center_accounted.get("judge", 0.0))
            if isinstance(center_accounted, Mapping)
            else 0.0
        )
        if center_value > float(self._authorization.max_cny_total) + 1e-12:
            raise BudgetLedgerInvalid("发送前复核 judge 中心金额超上限，禁发")


def open_synthetic_ledger(
    directory: Path | str,
    *,
    run: RagasRun,
    authorization: RagasAuthorization,
) -> BudgetLedger:
    """在**本进程新建**的系统临时目录下创建独立合成账本；绝不接共享真实账本。"""
    if not isinstance(run, RagasRun) or not isinstance(authorization, RagasAuthorization):
        raise RagasAdapterError("synthetic_ledger_invalid")
    target = Path(directory)
    try:
        resolved = target.resolve(strict=False)
        temp_root = Path(tempfile.gettempdir()).resolve()
    except OSError:
        raise RagasAdapterError("synthetic_ledger_invalid") from None
    if not resolved.is_relative_to(temp_root):
        raise RagasAdapterError("synthetic_ledger_invalid")
    parts = [part.lower() for part in resolved.parts]
    for sequence in (
        ("docs", "evidence"),
        ("docs", "evidence", "local-r1-20261101", "budget"),
        ("docs", "evidence", "local-r1-20261101", "pm"),
    ):
        width = len(sequence)
        if any(
            tuple(parts[index : index + width]) == sequence
            for index in range(max(0, len(parts) - width + 1))
        ):
            raise RagasAdapterError("synthetic_ledger_invalid")
    if target.exists():
        # 目标目录必须由本进程新建；既有目录一律拒绝，避免污染/复用。
        raise RagasAdapterError("synthetic_ledger_invalid")
    try:
        target.mkdir(parents=True, exist_ok=False)
        budget_path = target / "p2-ragas-synthetic-budget.json"
        ledger_path = target / "p2-ragas-synthetic-ledger.jsonl"
        budget_path.write_text(
            json.dumps(
                {
                    "limit_cny": float(authorization.max_cny_total),
                    "stages": {RAGAS_LEDGER_STAGE: float(authorization.max_cny_total)},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        ledger_path.write_text("", encoding="utf-8")
        guard = _SyntheticReserveGuard(ledger_path, authorization)
        ledger = BudgetLedger(
            ledger_path,
            budget_path,
            stage=RAGAS_LEDGER_STAGE,
            stage_limit_cny=float(authorization.max_cny_total),
            max_requests=int(authorization.max_calls_total),
            run_id=run.run_id,
            post_reserve_guard=guard.check,
        )
        ledger._ragas_post_reserve_guard = guard  # noqa: SLF001 - 同一合成账本内部接线
        return ledger
    except RagasAdapterError:
        raise
    except (OSError, BudgetError, ValueError, TypeError):
        raise RagasAdapterError("synthetic_ledger_invalid") from None


@dataclass(frozen=True)
class RagasCallTicket:
    """一次已预留的 judge 调用；只在本进程内存中流转。"""

    call_id: str
    case_id: str
    metric: str
    sequence: int
    prompt_digest: str
    amount_cny: float
    reservation: Reservation

    @property
    def reservation_id(self) -> str:
        return self.reservation.reservation_id


class _JudgeTransport(Protocol):
    judge_id: str
    judge_version: str
    execution_mode: str

    async def complete(self, prompt: str, response_model: Any) -> Any:  # pragma: no cover
        ...


class JudgeBudgetGateway:
    """所有框架内 judge 调用的唯一入口：授权/预留/复核/结算/停止。

    - 串行、自动重试 0：一次失败即 ``stopped``，后续 ``begin_call`` 一律拒绝；
    - 每个 case 的调用数不超过 min(授权单 case 上限, 声明的最坏调用数)；
    - 每笔调用先 ``BudgetLedger.reserve``，发送前再次核对授权时间与账本；
    - 结算只接受本网关开出的 ticket；同一 ticket 二次结算一律拒绝。
    """

    def __init__(
        self,
        *,
        run: RagasRun,
        authorization: RagasAuthorization,
        ledger: BudgetLedger,
        transport: _JudgeTransport,
        cost_per_call_cny: float = RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(run, RagasRun):
            raise RagasAdapterError("run_invalid_type")
        if not isinstance(authorization, RagasAuthorization):
            raise RagasAdapterError("authorization_invalid_type")
        if not isinstance(ledger, BudgetLedger):
            raise RagasAdapterError("synthetic_ledger_invalid")
        if not _is_synthetic_judge(transport):
            raise RagasAdapterError("judge_not_synthetic")
        self._run = run
        self._authorization = authorization
        self._ledger = ledger
        self._transport = transport
        self._cost = _finite_positive(
            cost_per_call_cny, code="authorization_value_invalid"
        )
        self._clock = clock or _utcnow
        self._per_case_cap = min(
            int(authorization.max_calls_per_case), RAGAS_WORST_CASE_JUDGE_CALLS
        )
        self._case_id: str | None = None
        self._metric: str | None = None
        self._case_sequence = 0
        self._records: list[dict[str, Any]] = []
        self._open: dict[str, RagasCallTicket] = {}
        self._settled: set[str] = set()
        self._stopped: str | None = None
        self._reserved = 0.0
        self._charged = 0.0

    # -- 只读观测面 ------------------------------------------------------
    @property
    def authorization(self) -> RagasAuthorization:
        return self._authorization

    @property
    def stopped_reason(self) -> str | None:
        return self._stopped

    @property
    def reserved_cny(self) -> float:
        return round(float(self._reserved), 10)

    @property
    def charged_cny(self) -> float:
        return round(float(self._charged), 10)

    @property
    def call_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(record) for record in self._records)

    def calls_for_case(self, case_id: str) -> int:
        return sum(1 for record in self._records if record["case_id"] == case_id)

    def calls_for_metric(self, case_id: str, metric: str) -> int:
        return sum(
            1
            for record in self._records
            if record["case_id"] == case_id and record["metric"] == metric
        )

    def sequence_for_case(self, case_id: str) -> tuple[str, ...]:
        return tuple(
            str(record["response_model"])
            for record in self._records
            if record["case_id"] == case_id and record.get("response_model")
        )

    def sequence_for_metric(self, case_id: str, metric: str) -> tuple[str, ...]:
        return tuple(
            str(record["response_model"])
            for record in self._records
            if record["case_id"] == case_id
            and record["metric"] == metric
            and record.get("response_model")
        )

    def charged_for_case(self, case_id: str) -> float:
        total = sum(
            float(record["amount_cny"])
            for record in self._records
            if record["case_id"] == case_id and record["status"] in {"succeeded", "failed", "refused_before_send"}
        )
        return round(total, 10)

    # -- case / metric 上下文 -------------------------------------------
    def enter_case(self, case_id: str) -> None:
        if self._case_id is not None:
            raise RagasAdapterError("case_context_missing")
        self._case_id = str(case_id)
        self._metric = None
        self._case_sequence = 0

    def exit_case(self) -> None:
        self._case_id = None
        self._metric = None

    def set_metric(self, metric: str) -> None:
        if metric not in _METRIC_NAMES:
            raise RagasAdapterError("framework_error")
        self._metric = metric

    # -- 预留 / 复核 / 结算 ---------------------------------------------
    def _stop(self, reason: str) -> None:
        if self._stopped is None:
            self._stopped = reason if reason in RAGAS_REASON_CODES else "adapter_internal_error"

    def _case_calls(self) -> int:
        if self._case_id is None:
            return 0
        return self.calls_for_case(self._case_id)

    def begin_call(self, prompt_digest: str) -> RagasCallTicket:
        if self._stopped is not None:
            raise RagasBudgetError("gateway_stopped")
        if self._case_id is None:
            raise RagasBudgetError("case_context_missing")
        if self._case_calls() >= self._per_case_cap:
            self._stop("case_call_ceiling_exceeded")
            raise RagasBudgetError("case_call_ceiling_exceeded")
        if len(self._records) >= int(self._authorization.max_calls_total):
            self._stop("call_budget_exhausted")
            raise RagasBudgetError("call_budget_exhausted")
        if self._cost > float(self._authorization.max_cny_per_call) + 1e-12:
            self._stop("per_call_budget_exceeded")
            raise RagasBudgetError("per_call_budget_exceeded")
        moment = _safe_now(self._clock)
        if moment is None:
            self._stop("clock_invalid")
            raise RagasBudgetError("clock_invalid")
        if moment >= self._authorization.expires_utc:
            self._stop("authorization_expired")
            raise RagasBudgetError("authorization_expired")
        if moment < self._authorization.issued_utc:
            self._stop("authorization_not_yet_valid")
            raise RagasBudgetError("authorization_not_yet_valid")
        sequence = self._case_sequence + 1
        try:
            reservation = self._ledger.reserve(
                kind="chat",
                provider="synthetic",
                model=self._authorization.judge_id,
                max_cny=float(self._cost),
                request_sha256=_sha256_text(
                    f"{self._run.run_id}:{self._case_id}:{sequence}:{prompt_digest}"
                ),
                metadata={
                    "purpose": "p2-ragas-offline-judge",
                    "run_id": self._run.run_id,
                    "case_id": self._case_id,
                    "metric": self._metric,
                    "sequence": sequence,
                },
                cost_center="judge",
                stage_limit_cny=float(self._authorization.max_cny_total),
                max_requests=int(self._authorization.max_calls_total),
            )
        except RequestLimitExceeded:
            self._stop("call_budget_exhausted")
            raise RagasBudgetError("call_budget_exhausted") from None
        except BudgetExceeded:
            self._stop("budget_exhausted")
            raise RagasBudgetError("budget_exhausted") from None
        except BudgetError:
            self._stop("ledger_refused")
            raise RagasBudgetError("ledger_refused") from None
        self._case_sequence = sequence
        self._reserved = round(self._reserved + float(self._cost), 10)
        ticket = RagasCallTicket(
            call_id=hashlib.sha256(
                f"{reservation.reservation_id}:{self._case_id}:{sequence}".encode("utf-8")
            ).hexdigest()[:32],
            case_id=self._case_id,
            metric=self._metric or "unknown",
            sequence=sequence,
            prompt_digest=str(prompt_digest)[:64],
            amount_cny=float(self._cost),
            reservation=reservation,
        )
        self._open[ticket.call_id] = ticket
        self._records.append(
            {
                "call_id": ticket.call_id,
                "case_id": ticket.case_id,
                "metric": ticket.metric,
                "sequence": sequence,
                "response_model": None,
                "status": "reserved",
                "amount_cny": float(self._cost),
            }
        )
        return ticket

    def _record_for(self, ticket: RagasCallTicket) -> dict[str, Any]:
        for record in self._records:
            if record["call_id"] == ticket.call_id:
                return record
        raise RagasBudgetError("ticket_unknown")

    def set_response_model(self, ticket: RagasCallTicket, name: str) -> None:
        if ticket.call_id not in self._open:
            raise RagasBudgetError("ticket_unknown")
        self._record_for(ticket)["response_model"] = str(name)[:120]

    def confirm_call(self, ticket: RagasCallTicket) -> RagasCallTicket:
        if not isinstance(ticket, RagasCallTicket) or ticket.call_id not in self._open:
            raise RagasBudgetError("ticket_unknown")
        if self._stopped is not None:
            self._refuse_before_send(ticket, "gateway_stopped")
            raise RagasBudgetError("gateway_stopped")
        moment = _safe_now(self._clock)
        if moment is None:
            self._refuse_before_send(ticket, "clock_invalid")
            raise RagasBudgetError("clock_invalid")
        if moment >= self._authorization.expires_utc:
            self._refuse_before_send(ticket, "authorization_expired")
            raise RagasBudgetError("authorization_expired")
        if moment < self._authorization.issued_utc:
            self._refuse_before_send(ticket, "authorization_not_yet_valid")
            raise RagasBudgetError("authorization_not_yet_valid")
        guard = getattr(self._ledger, "_ragas_post_reserve_guard", None)
        try:
            if guard is not None:
                guard.expect(ticket.reservation)
            self._ledger.recheck_reservation(ticket.reservation)
        except BudgetError:
            self._refuse_before_send(ticket, "ledger_refused")
            raise RagasBudgetError("ledger_refused") from None
        finally:
            if guard is not None:
                guard.clear()
        self._record_for(ticket)["status"] = "confirmed"
        return ticket

    def _refuse_before_send(self, ticket: RagasCallTicket, code: str) -> None:
        """预留已发生但发送前失效：保守留账（failed，全额占用），保留请求身份。"""
        try:
            self._ledger.settle(
                ticket.reservation,
                status="failed",
                error_code=f"P2_RAGAS_PRE_SEND_REFUSED:{code}",
                request_id=ticket.call_id,
                elapsed_seconds=0.0,
            )
        except BudgetError:
            pass
        self._open.pop(ticket.call_id, None)
        self._settled.add(ticket.call_id)
        self._charged = round(self._charged + float(ticket.amount_cny), 10)
        record = self._record_for(ticket)
        record["status"] = "refused_before_send"
        record["error_code"] = code
        self._stop(code)

    def settle_success(self, ticket: RagasCallTicket) -> float:
        if not isinstance(ticket, RagasCallTicket):
            raise RagasBudgetError("ticket_unknown")
        if ticket.call_id in self._settled:
            raise RagasBudgetError("duplicate_settlement")
        if ticket.call_id not in self._open:
            raise RagasBudgetError("ticket_unknown")
        try:
            self._ledger.settle(
                ticket.reservation,
                status="succeeded",
                usage={"judge_calls": 1},
                estimated_list_price_cny=float(ticket.amount_cny),
                request_id=ticket.call_id,
            )
        except BudgetError:
            self._stop("ledger_refused")
            raise RagasBudgetError("ledger_refused") from None
        self._open.pop(ticket.call_id, None)
        self._settled.add(ticket.call_id)
        self._charged = round(self._charged + float(ticket.amount_cny), 10)
        self._record_for(ticket)["status"] = "succeeded"
        return float(ticket.amount_cny)

    def settle_failure(self, ticket: RagasCallTicket, code: str) -> None:
        if not isinstance(ticket, RagasCallTicket):
            raise RagasBudgetError("ticket_unknown")
        if ticket.call_id in self._settled:
            raise RagasBudgetError("duplicate_settlement")
        if ticket.call_id not in self._open:
            raise RagasBudgetError("ticket_unknown")
        clean = code if code in RAGAS_REASON_CODES else "framework_error"
        try:
            self._ledger.settle(
                ticket.reservation,
                status="failed",
                error_code=f"P2_RAGAS_FAILED:{clean}",
                request_id=ticket.call_id,
            )
        except BudgetError:
            pass
        self._open.pop(ticket.call_id, None)
        self._settled.add(ticket.call_id)
        self._charged = round(self._charged + float(ticket.amount_cny), 10)
        record = self._record_for(ticket)
        record["status"] = "failed"
        record["error_code"] = clean
        self._stop(clean)

    # -- Ragas Instructor 传输入口 --------------------------------------
    async def agenerate(self, prompt: str, response_model: Any) -> Any:
        if not isinstance(prompt, str):
            raise RagasJudgeError("framework_error")
        ticket = self.begin_call(_sha256_text(prompt))
        self.set_response_model(ticket, getattr(response_model, "__name__", "unknown"))
        self.confirm_call(ticket)
        try:
            result = await self._transport.complete(prompt, response_model)
        except Exception:
            self.settle_failure(ticket, "judge_service_error")
            raise RagasJudgeError("judge_service_error") from None
        if not isinstance(result, response_model):
            self.settle_failure(ticket, "judge_output_invalid")
            raise RagasJudgeError("judge_output_invalid")
        self.settle_success(ticket)
        return result


def _is_synthetic_judge(judge: Any) -> bool:
    return (
        judge is not None
        and getattr(judge, "execution_mode", None) == "synthetic"
        and isinstance(getattr(judge, "judge_id", None), str)
        and isinstance(getattr(judge, "judge_version", None), str)
        and callable(getattr(judge, "complete", None))
    )


# --------------------------------------------------------------------------- #
# 单 case 评分
# --------------------------------------------------------------------------- #


def _metric_value(result: Any) -> float:
    value = getattr(result, "value", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RagasAdapterError("invalid_metric_value")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise RagasAdapterError("invalid_metric_value")
    return number


def _metric_evidence_ok(name: str, sequence: Sequence[str]) -> bool:
    """合法分数必须伴随该指标**精确**的结构化调用序列（顺序+次数）。"""
    expected = RAGAS_EXPECTED_METRIC_SEQUENCE.get(name)
    if expected is None:
        return False
    return tuple(str(item) for item in sequence) == expected


def _unknown_case(
    case: RagasCase, reason: str, gateway: JudgeBudgetGateway
) -> RagasCaseScore:
    code = reason if reason in RAGAS_REASON_CODES else "framework_error"
    return RagasCaseScore(
        case_id=case.case_id,
        status="unknown",
        faithfulness=None,
        factual_correctness=None,
        reason_code=code,
        judge_calls=gateway.calls_for_case(case.case_id),
        embedding_calls=0,
        charged_cny=gateway.charged_for_case(case.case_id),
        hard_failure=case.hard_failure,
        metric_call_sequence=gateway.sequence_for_case(case.case_id),
    )


async def _score_case(
    case: RagasCase,
    *,
    gateway: JudgeBudgetGateway,
    faithfulness: Any,
    factual_correctness: Any,
) -> RagasCaseScore:
    gateway.enter_case(case.case_id)
    try:
        if case.refusal:
            return _unknown_case(case, "refusal_not_applicable", gateway)
        values: dict[str, float] = {}
        for name in _METRIC_NAMES:
            gateway.set_metric(name)
            before = gateway.calls_for_metric(case.case_id, name)
            try:
                if name == "faithfulness":
                    raw = await faithfulness.ascore(
                        user_input=case.question,
                        response=case.answer,
                        retrieved_contexts=list(case.contexts),
                    )
                else:
                    raw = await factual_correctness.ascore(
                        response=case.answer,
                        reference=case.reference,
                    )
            except RagasAdapterError as exc:
                return _unknown_case(case, exc.code, gateway)
            except Exception:
                return _unknown_case(case, "framework_error", gateway)
            if gateway.calls_for_metric(case.case_id, name) <= before:
                # 指标层给了分数却没有经过真实嵌套调用门：必须 FAIL，不能当通过。
                return _unknown_case(case, "framework_bypass_detected", gateway)
            try:
                values[name] = _metric_value(raw)
            except RagasAdapterError as exc:
                return _unknown_case(case, exc.code, gateway)
            if not _metric_evidence_ok(
                name, gateway.sequence_for_metric(case.case_id, name)
            ):
                # 即使分数“看起来合法”，只要没有该指标真实的结构化调用链，也必须 FAIL。
                return _unknown_case(case, "framework_bypass_detected", gateway)
        return RagasCaseScore(
            case_id=case.case_id,
            status="scored",
            faithfulness=values["faithfulness"],
            factual_correctness=values["factual_correctness"],
            reason_code=None,
            judge_calls=gateway.calls_for_case(case.case_id),
            embedding_calls=0,
            charged_cny=gateway.charged_for_case(case.case_id),
            hard_failure=case.hard_failure,
            metric_call_sequence=gateway.sequence_for_case(case.case_id),
        )
    finally:
        gateway.exit_case()


# --------------------------------------------------------------------------- #
# 对外主入口
# --------------------------------------------------------------------------- #


def _validate_authorization(authorization: RagasAuthorization) -> str | None:
    """二次校验（防对象构造被绕过）：返回稳定原因码或 None。"""
    try:
        if authorization.schema_version != RAGAS_AUTHORIZATION_SCHEMA_VERSION:
            return "authorization_value_invalid"
        if authorization.mode != "offline_synthetic":
            return "authorization_mode_forbidden"
        if authorization.production_ready is not False:
            return "authorization_production_ready_forbidden"
        for value, maximum in (
            (authorization.authorization_id, 96),
            (authorization.run_id, 96),
            (authorization.plan_id, 96),
            (authorization.judge_id, 96),
            (authorization.judge_version, 64),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                return "authorization_value_invalid"
        _sha256_hex(
            authorization.plan_sha256,
            name="plan_sha256",
            code="authorization_value_invalid",
        )
        issued = _aware_instant(
            authorization.issued_utc, code="authorization_value_invalid"
        )
        expires = _aware_instant(
            authorization.expires_utc, code="authorization_value_invalid"
        )
        if expires <= issued:
            return "authorization_value_invalid"
        _positive_int(
            authorization.max_calls_per_case, code="authorization_value_invalid"
        )
        _positive_int(authorization.max_calls_total, code="authorization_value_invalid")
        _finite_positive(
            authorization.max_cny_per_call, code="authorization_value_invalid"
        )
        _finite_positive(
            authorization.max_cny_total, code="authorization_value_invalid"
        )
    except (RagasAdapterError, AttributeError, TypeError, ValueError):
        return "authorization_value_invalid"
    return None


def _validate_judge(
    judge: Any, authorization: RagasAuthorization
) -> str | None:
    if judge is None:
        return "judge_missing"
    if not _is_synthetic_judge(judge):
        return "judge_not_synthetic"
    if (
        judge.judge_id != authorization.judge_id
        or judge.judge_version != authorization.judge_version
    ):
        return "judge_identity_mismatch"
    return None


async def _score_ragas_impl(
    run: RagasRun,
    *,
    judge: Any,
    authorization: RagasAuthorization | None,
    clock: Callable[[], datetime] | None = None,
    cost_per_call_cny: float = RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY,
) -> RagasScoreResult:
    """对已存在的公共/合成 run 做受控 Ragas 辅助评分。

    所有校验失败都以版本化 blocked 结果返回，不抛自由异常文本；框架内任何一次
    调用都经 :class:`JudgeBudgetGateway`。本轮只允许 synthetic judge。
    """
    invalid_run = _validate_run(run)
    if invalid_run is not None:
        return _blocked_result(invalid_run, run=run, judge=judge)
    moment = _safe_now(clock)
    if moment is None:
        return _blocked_result("clock_invalid", run=run, judge=judge)
    if authorization is None:
        return _blocked_result("authorization_missing", run=run, judge=judge)
    if not isinstance(authorization, RagasAuthorization):
        return _blocked_result(
            "authorization_invalid_type", run=run, judge=judge
        )
    invalid = _validate_authorization(authorization)
    if invalid is not None:
        return _blocked_result(invalid, run=run, judge=judge, authorization=authorization)
    if authorization.run_id != run.run_id:
        return _blocked_result(
            "authorization_run_mismatch", run=run, judge=judge, authorization=authorization
        )
    if (
        authorization.plan_id != run.plan_id
        or authorization.plan_sha256.lower() != run.plan_sha256.lower()
    ):
        return _blocked_result(
            "authorization_plan_mismatch", run=run, judge=judge, authorization=authorization
        )
    judge_invalid = _validate_judge(judge, authorization)
    if judge_invalid is not None:
        return _blocked_result(
            judge_invalid, run=run, judge=judge, authorization=authorization
        )
    if moment >= authorization.expires_utc:
        return _blocked_result(
            "authorization_expired", run=run, judge=judge, authorization=authorization
        )
    if moment < authorization.issued_utc:
        return _blocked_result(
            "authorization_not_yet_valid",
            run=run,
            judge=judge,
            authorization=authorization,
        )
    try:
        cost = _finite_positive(
            cost_per_call_cny, code="authorization_value_invalid"
        )
    except RagasAdapterError:
        return _blocked_result(
            "authorization_value_invalid", run=run, judge=judge, authorization=authorization
        )
    if cost > float(authorization.max_cny_per_call) + 1e-12:
        return _blocked_result(
            "per_call_budget_exceeded",
            run=run,
            judge=judge,
            authorization=authorization,
            per_call_cny=cost,
        )

    try:
        ragas_module = _load_ragas()
    except ImportError:
        return _blocked_result(
            "ragas_not_installed", run=run, judge=judge, authorization=authorization
        )
    except Exception:
        return _blocked_result(
            "ragas_import_failed", run=run, judge=judge, authorization=authorization
        )

    version = str(getattr(ragas_module, "__version__", "") or "")
    if version != RAGAS_LOCKED_RAGAS_VERSION:
        return _blocked_result(
            "ragas_version_mismatch",
            run=run,
            judge=judge,
            authorization=authorization,
            ragas_version=version or None,
        )

    with tempfile.TemporaryDirectory(prefix="p2-ragas-offline-") as directory:
        try:
            ledger = open_synthetic_ledger(
                Path(directory) / "ledger", run=run, authorization=authorization
            )
            gateway = JudgeBudgetGateway(
                run=run,
                authorization=authorization,
                ledger=ledger,
                transport=judge,
                cost_per_call_cny=cost,
                clock=clock,
            )
            llm = _make_llm(gateway)
            faithfulness, factual_correctness = _build_metrics(llm)
            specs = _metric_specs(ragas_module, faithfulness, factual_correctness)
            digest = _prompt_digest((faithfulness, factual_correctness))
        except RagasAdapterError as exc:
            return _blocked_result(
                exc.code,
                run=run,
                judge=judge,
                authorization=authorization,
                ragas_version=version,
                per_call_cny=cost,
            )
        except Exception:
            return _blocked_result(
                "ragas_metrics_unavailable",
                run=run,
                judge=judge,
                authorization=authorization,
                ragas_version=version,
                per_call_cny=cost,
            )

        case_results: list[RagasCaseScore] = []
        for case in run.cases:
            case_results.append(
                await _score_case(
                    case,
                    gateway=gateway,
                    faithfulness=faithfulness,
                    factual_correctness=factual_correctness,
                )
            )
            if gateway.stopped_reason is not None:
                for remaining in run.cases[len(case_results) :]:
                    case_results.append(
                        _unknown_case(remaining, gateway.stopped_reason, gateway)
                    )
                break

        counts = _base_counts(len(run.cases))
        counts["scored"] = sum(1 for case in case_results if case.status == "scored")
        counts["unknown"] = sum(1 for case in case_results if case.status == "unknown")
        counts["judge_calls"] = sum(case.judge_calls for case in case_results)
        counts["embedding_calls"] = 0
        if counts["scored"] == counts["cases"] and counts["cases"] > 0:
            status = "scored"
        elif counts["scored"] > 0:
            status = "partial"
        else:
            status = "unknown"
        hard_failures = tuple(
            sorted(
                {
                    case.hard_failure
                    for case in case_results
                    if case.hard_failure is not None
                }
            )
        )
        coverage_complete = status == "scored"
        complete = coverage_complete and not hard_failures
        reason_code = gateway.stopped_reason
        if reason_code is None:
            reason_code = next(
                (case.reason_code for case in case_results if case.reason_code), None
            )
        event_count = 0
        try:
            event_count = sum(
                1
                for line in Path(ledger.ledger_path)
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            )
        except OSError:
            event_count = 0
        return RagasScoreResult(
            schema_version=RAGAS_RESULT_SCHEMA_VERSION,
            adapter_version=RAGAS_ADAPTER_VERSION,
            run_id=run.run_id,
            run_digest=run.digest,
            status=status,
            complete=complete,
            coverage_complete=coverage_complete,
            auxiliary_only=True,
            quality_decision=None,
            reason_code=reason_code,
            ragas_version=version,
            python_version=_python_version(),
            metric_specs=specs,
            prompt_digest=digest,
            judge=_judge_summary(judge),
            authorization=_auth_summary(authorization),
            cases=tuple(case_results),
            counts=counts,
            cost={
                "currency": "CNY",
                "synthetic": True,
                "per_call_cny": float(cost),
                "reserved_cny": gateway.reserved_cny,
                "charged_cny": gateway.charged_cny,
            },
            ledger={
                "stage": RAGAS_LEDGER_STAGE,
                "synthetic": True,
                "event_count": int(event_count),
                "limit_cny": float(authorization.max_cny_total),
                "max_calls": int(authorization.max_calls_total),
            },
            declared_worst_case_judge_calls=RAGAS_WORST_CASE_JUDGE_CALLS,
            hard_failures=hard_failures,
        )

async def score_ragas(
    run: RagasRun,
    *,
    judge: Any,
    authorization: RagasAuthorization | None,
    clock: Callable[[], datetime] | None = None,
    cost_per_call_cny: float = RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY,
) -> RagasScoreResult:
    """主入口：保证任何内部异常都折成版本化 blocked 结果，不外泄异常原文。"""
    try:
        return await _score_ragas_impl(
            run,
            judge=judge,
            authorization=authorization,
            clock=clock,
            cost_per_call_cny=cost_per_call_cny,
        )
    except Exception:
        safe_auth = authorization if isinstance(authorization, RagasAuthorization) else None
        return _blocked_result(
            "adapter_internal_error",
            run=run,
            judge=judge,
            authorization=safe_auth,
            per_call_cny=RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY,
        )
