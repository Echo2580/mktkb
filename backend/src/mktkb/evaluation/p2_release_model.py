"""P2 正式跨场景门禁的共享模型：固定原因码、门禁行、摘要工具。

本模块只放词表与纯函数：不读文件、不碰网络、不发起任何真实请求。
固定原因码是**对外稳定词表**（报告、CLI、下游复算都引用同一套字面量），
具体内层失败原因放在 ``ReleaseRow.detail["cause"]`` 里，不改变对外码。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

# --------------------------------------------------------------------------- #
# 契约版本
# --------------------------------------------------------------------------- #

#: 正式门禁输入清单（单一入口的显式绑定）。
INPUTS_SCHEMA_VERSION = "p2-release-gate-inputs/v0.1"
#: 门禁结果（脱敏；只出计数、摘要与判定）。
RESULT_SCHEMA_VERSION = "p2-release-gate-result/v0.1"
#: 旧版本适用性证明（绑定原证据 + 目标配置 + 派生评分器身份）。
APPLICABILITY_SCHEMA_VERSION = "p2-release-applicability/v0.1"
#: 冻结选题范围（先去重再计分；不在计分后挑分数）。
SELECTION_SCHEMA_VERSION = "p2-release-selection/v0.1"
#: H2 同批来源证明（原运行身份 + 派生评分器身份两套）。
H2_SOURCE_PROOF_SCHEMA_VERSION = "p2-release-h2-source-proof/v0.1"

# --------------------------------------------------------------------------- #
# 判定值与原因码
# --------------------------------------------------------------------------- #

#: 该行证据齐备且达标。
DECISION_PASS = "pass"
#: 该行证据齐备但不达标 / 不闭合。
DECISION_BLOCKED = "blocked"
#: 该行依赖的外部输入尚未交付（任务 2/3）。
DECISION_PENDING = "pending"
#: 只展示、不参与总门（必需/非必需分列、整卡 verified 等）。
DECISION_OBSERVED = "observed"

DECISIONS: tuple[str, ...] = (DECISION_PASS, DECISION_BLOCKED, DECISION_PENDING, DECISION_OBSERVED)

#: 缺证：必需工件不存在或未绑定。
R_EVIDENCE_MISSING = "release_evidence_missing"
#: 未执行：缺题、error、skipped、not_executed。
R_NOT_EXECUTED = "release_not_executed"
#: 必需未知：适用范围内存在 unknown / 未评估。
R_REQUIRED_UNKNOWN = "release_required_unknown"
#: 硬失败：任一硬门禁 fail 或已观测硬失败 > 0。
R_HARD_FAILURE = "release_hard_failure"
#: 版本不符：schema/配置版本/题集版本与冻结口径不一致。
R_VERSION_MISMATCH = "release_version_mismatch"
#: 身份不符：run_id/计划/套件/基线/题号归属不一致。
R_IDENTITY_MISMATCH = "release_identity_mismatch"
#: 摘要错配：声明的 sha256 与实算不符（含回执/来源证明错配）。
R_DIGEST_MISMATCH = "release_digest_mismatch"
#: 重复证据：同一题/同一 U 被两个来源重复计入。
R_DUPLICATE_EVIDENCE = "release_duplicate_evidence"
#: 跨计划合并：一次判定把不同冻结计划的题混合并重算成同一分母。
R_CROSS_PLAN_MERGE = "release_cross_plan_merge"
#: 适用性证明不可核（伪造、过期、与实算不等）。
R_APPLICABILITY_INVALID = "release_applicability_invalid"
#: 样本不足：适用题数低于批准的最小样本。
R_SAMPLE_BELOW_MIN = "release_sample_below_min"
#: 质量未达标：通过数低于批准阈值。
R_QUALITY_BELOW_THRESHOLD = "release_quality_below_threshold"
#: 陈旧配置：仍在用未批准的冻结模板（历史口径），不得当正式配置。
R_STALE_CONFIG = "release_stale_config"
#: 外部输入未交付（任务 2/3 占位）。
R_PENDING_INPUT = "release_pending_input"
#: 输入清单本身不合约（缺字段/多字段/类型错）。
R_INPUTS_INVALID = "release_inputs_invalid"
#: 批准配置不可用（实算摘要 ≠ 已批准摘要）。
R_GATE_CONFIG_UNAPPROVED = "release_gate_config_unapproved"
#: 已登记基线不存在或未在登记处。
R_BASELINE_UNREGISTERED = "release_baseline_unregistered"
#: 历史绑定适用性证明缺失（需要证明的 run 没给）。
R_BINDING_PROOF_MISSING = "release_binding_proof_missing"
#: 绑定证明与重算不符（伪造/错配/跨 run/无修正）。
R_BINDING_ATTESTATION_INVALID = "release_binding_attestation_invalid"
#: 引用落在证据字段（retrieved 为空）而同轮 evidence 有单元：须主人裁量。
R_CITATION_GROUNDING_MISSING = "citation_grounding_field_missing"
#: 批准配置的硬门禁最小样本未满足（run 级 evaluated_count < required）：交主人裁量。
R_HARD_GATE_MIN_SAMPLE_UNMET = "hard_gate_min_sample_unmet"
#: 门禁结果行不完整（某个 run 缺 binding/applicability 行）：内部不变量被破坏，阻断。
R_ROWS_INCOMPLETE = "release_rows_incomplete"

#: 稳定词表（报告与 CLI 都只引用这里）。
REASON_CODES: tuple[str, ...] = (
    R_EVIDENCE_MISSING,
    R_NOT_EXECUTED,
    R_REQUIRED_UNKNOWN,
    R_HARD_FAILURE,
    R_VERSION_MISMATCH,
    R_IDENTITY_MISMATCH,
    R_DIGEST_MISMATCH,
    R_DUPLICATE_EVIDENCE,
    R_CROSS_PLAN_MERGE,
    R_APPLICABILITY_INVALID,
    R_SAMPLE_BELOW_MIN,
    R_QUALITY_BELOW_THRESHOLD,
    R_STALE_CONFIG,
    R_PENDING_INPUT,
    R_INPUTS_INVALID,
    R_GATE_CONFIG_UNAPPROVED,
    R_BASELINE_UNREGISTERED,
    R_BINDING_PROOF_MISSING,
    R_BINDING_ATTESTATION_INVALID,
    R_CITATION_GROUNDING_MISSING,
    R_HARD_GATE_MIN_SAMPLE_UNMET,
    R_ROWS_INCOMPLETE,
)

#: 外部输入的固定占位标记（谁的活谁填，门禁只认字面量）。
PENDING_TASK2 = "PENDING-TASK2"
PENDING_TASK3 = "PENDING-TASK3"
PENDING_MARKERS: tuple[str, ...] = (PENDING_TASK2, PENDING_TASK3)

#: 允许被标记为待交付的输入段。
PENDING_SECTIONS: tuple[str, ...] = ("public", "u", "h2")


class ReleaseGateError(ValueError):
    """门禁可预期的阻断：稳定原因码 + 内层原因（不吞、不猜、不放行）。"""

    def __init__(self, code: str, cause: str = "", detail: Any = None) -> None:
        if code not in REASON_CODES:
            raise ValueError(f"未登记的原因码: {code!r}")
        self.code = str(code)
        self.cause = str(cause)
        self.detail = detail if detail is not None else {}
        super().__init__(f"{self.code}: {self.cause}" if self.cause else self.code)

    def to_row(self, row_id: str, title: str) -> "ReleaseRow":
        payload = {"cause": self.cause}
        if self.detail:
            payload["evidence"] = self.detail
        return ReleaseRow(row_id=row_id, title=title, decision=DECISION_BLOCKED,
                          reasons=(self.code,), detail=payload)


# --------------------------------------------------------------------------- #
# 门禁行
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReleaseRow:
    """一行判定：判定值 + 固定原因码 + 证据引用（脱敏）。"""

    row_id: str
    title: str
    decision: str
    reasons: tuple[str, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(f"未登记的判定值: {self.decision!r}")
        for code in self.reasons:
            if code not in REASON_CODES:
                raise ValueError(f"未登记的原因码: {code!r}")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def blocks(self) -> bool:
        return self.decision == DECISION_BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "title": self.title,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "detail": dict(self.detail),
            "evidence": list(self.evidence),
        }


def row_ok(row_id: str, title: str, *, detail: Mapping[str, Any] | None = None,
           evidence: Sequence[str] = ()) -> ReleaseRow:
    return ReleaseRow(row_id=row_id, title=title, decision=DECISION_PASS,
                      detail=dict(detail or {}), evidence=tuple(evidence))


def row_blocked(row_id: str, title: str, *reasons: str, cause: str = "",
                detail: Mapping[str, Any] | None = None,
                evidence: Sequence[str] = ()) -> ReleaseRow:
    payload: dict[str, Any] = {}
    if cause:
        payload["cause"] = cause
    if detail:
        payload["evidence"] = dict(detail)
    return ReleaseRow(row_id=row_id, title=title, decision=DECISION_BLOCKED,
                      reasons=tuple(reasons), detail=payload, evidence=tuple(evidence))


def row_pending(row_id: str, title: str, marker: str, *, detail: Mapping[str, Any] | None = None,
                reason: str = R_PENDING_INPUT) -> ReleaseRow:
    payload: dict[str, Any] = {"marker": marker}
    if detail:
        payload["evidence"] = dict(detail)
    return ReleaseRow(row_id=row_id, title=title, decision=DECISION_PENDING,
                      reasons=(reason,), detail=payload)


def row_observed(row_id: str, title: str, *, detail: Mapping[str, Any] | None = None,
                 evidence: Sequence[str] = ()) -> ReleaseRow:
    return ReleaseRow(row_id=row_id, title=title, decision=DECISION_OBSERVED,
                      detail=dict(detail or {}), evidence=tuple(evidence))


def gate_decision(rows: Sequence[ReleaseRow]) -> str:
    """总门：任一阻断即阻断；否则任一待交付即待交付；否则通过。"""
    decisions = {row.decision for row in rows}
    if DECISION_BLOCKED in decisions:
        return DECISION_BLOCKED
    if DECISION_PENDING in decisions:
        return DECISION_PENDING
    return DECISION_PASS


# --------------------------------------------------------------------------- #
# 摘要工具
# --------------------------------------------------------------------------- #


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path | str) -> str:
    target = Path(path)
    return sha256_bytes(target.read_bytes())


def canonical_json_bytes(payload: Any) -> bytes:
    """稳定序列化（排序键、紧凑分隔符、拒绝 NaN），与 p2_contracts 同口径。"""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def source_bundle_sha256(paths: Sequence[Path | str]) -> str:
    """把若干源文件折成一个身份摘要（派生评分器/分类器身份）。"""
    rows = {}
    for item in paths:
        path = Path(item)
        rows[path.name] = file_sha256(path)
    return payload_sha256(rows)


# --------------------------------------------------------------------------- #
# 严格 schema 小工具
# --------------------------------------------------------------------------- #


def exact_keys(payload: Any, keys: Sequence[str], *, what: str, code: str = R_INPUTS_INVALID,
               optional: Sequence[str] = ()) -> Mapping[str, Any]:
    """键集合必须精确匹配（可选键允许缺席）；任何偏差都按固定原因码阻断。"""
    if not isinstance(payload, Mapping):
        raise ReleaseGateError(code, f"{what} 必须是对象")
    allowed = set(keys) | set(optional)
    missing = sorted(set(keys) - set(payload))
    unknown = sorted(set(payload) - allowed)
    if missing or unknown:
        raise ReleaseGateError(code, f"{what} 键不符", {"missing": missing, "unknown": unknown})
    return payload


def require_text(value: Any, what: str, *, code: str = R_INPUTS_INVALID) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseGateError(code, f"{what} 必须是非空字符串")
    return value


def require_digest(value: Any, what: str, *, code: str = R_INPUTS_INVALID) -> str:
    text = require_text(value, what, code=code)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ReleaseGateError(code, f"{what} 必须是 64 位小写十六进制摘要")
    return text


def require_int(value: Any, what: str, *, minimum: int = 0, code: str = R_INPUTS_INVALID) -> int:
    if type(value) is not int or value < minimum:
        raise ReleaseGateError(code, f"{what} 必须是不小于 {minimum} 的整数")
    return value


__all__ = [
    "APPLICABILITY_SCHEMA_VERSION",
    "DECISIONS",
    "DECISION_BLOCKED",
    "DECISION_OBSERVED",
    "DECISION_PASS",
    "DECISION_PENDING",
    "H2_SOURCE_PROOF_SCHEMA_VERSION",
    "INPUTS_SCHEMA_VERSION",
    "PENDING_MARKERS",
    "PENDING_SECTIONS",
    "PENDING_TASK2",
    "PENDING_TASK3",
    "REASON_CODES",
    "RESULT_SCHEMA_VERSION",
    "R_APPLICABILITY_INVALID",
    "R_BASELINE_UNREGISTERED",
    "R_BINDING_ATTESTATION_INVALID",
    "R_BINDING_PROOF_MISSING",
    "R_CITATION_GROUNDING_MISSING",
    "R_HARD_GATE_MIN_SAMPLE_UNMET",
    "R_ROWS_INCOMPLETE",
    "R_CROSS_PLAN_MERGE",
    "R_DIGEST_MISMATCH",
    "R_DUPLICATE_EVIDENCE",
    "R_EVIDENCE_MISSING",
    "R_GATE_CONFIG_UNAPPROVED",
    "R_HARD_FAILURE",
    "R_IDENTITY_MISMATCH",
    "R_INPUTS_INVALID",
    "R_NOT_EXECUTED",
    "R_PENDING_INPUT",
    "R_QUALITY_BELOW_THRESHOLD",
    "R_REQUIRED_UNKNOWN",
    "R_SAMPLE_BELOW_MIN",
    "R_STALE_CONFIG",
    "R_VERSION_MISMATCH",
    "ReleaseGateError",
    "ReleaseRow",
    "SELECTION_SCHEMA_VERSION",
    "canonical_json_bytes",
    "exact_keys",
    "file_sha256",
    "gate_decision",
    "payload_sha256",
    "require_digest",
    "require_int",
    "require_text",
    "row_blocked",
    "row_observed",
    "row_ok",
    "row_pending",
    "sha256_bytes",
    "source_bundle_sha256",
]
