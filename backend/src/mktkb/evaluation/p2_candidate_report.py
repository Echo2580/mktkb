"""T209-PREP：报告分列 + candidate/blocked 归档编排（离线、公共/合成输入）。

**范围（任务书 E2 §6）**

本模块只做两件独立能力，不批准阈值、不建立可发布真实质量基线：

1. **报告分列**：把「执行状态」「质量状态」「证据状态」「软评分状态」「资金与版本」
   分别建模与渲染，**没有**单一 ``overall_success`` / ``ready`` 字段。执行
   ``succeeded`` 只说明链路完成；质量是否通过看阈值/硬失败；证据是否可判看四轴
   ``unknown`` / ``missing_evidence``；软评分（Ragas/auxiliary）单独记
   ``recorded_status`` 与 ``rescored``，不冒充重评、不抵消确定性硬失败；
2. **candidate/blocked 归档**：以 :mod:`mktkb.evaluation.baseline` 的既有证据链
   （``archive_baseline`` / ``verify_archive`` / ``restore_baseline``）为 payload，
   在新目录完成 archive→verify→restore→list/diff。候选归档的
   ``publishable / release_baseline / gate_approved`` 是**结构常量 false**，状态由
   报告事实派生（不合格 → ``blocked``），不接受调用方声明「可发布」；也不写
   ``approval.json``，因此恢复出来的 baseline 永远未审批，``diff_runs`` 会以
   ``baseline_unapproved`` 拒绝放行。

**复用与边界**

- 不修改 ``report.py`` / ``baseline.py`` / ``gate.py``；候选归档把既有归档目录原样
  放进 ``payload/``，再对 payload 调既有 ``verify_archive`` / ``restore_baseline``，
  因此身份六要素、产物摘要、gate/approval 绑定关系仍由既有实现校验；
- 只读：list/diff 不写盘；archive/restore 只写调用方给出的**临时/合成**目录；
  默认拒绝写入正式 registry（``var/eval/baselines``）与受保护证据/报告目录；
- 零真实调用：本模块不导入产品/模型/检索/裁判客户端，不读 ``.env``、不读真实 H2
  逐题、不查询供应商余额；
- 跨轮分数不合并：报告只覆盖单一 ``round_id``；不同 round 的归档只能 diff 出
  「不可比」，不能求和/拼接。

**残余未知（显式）**

候选归档的摘要链与既有 baseline 归档同级：manifest 自身没有外部签名，能证明
「与建立时一致的字节」并结构性拒绝发布，但不能证明「建立者当时输入的是真实事实」；
后者需要正式 run/审批/独立验收，属于 T209 正式阶段。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .baseline import (
    APPROVAL_FILENAME,
    ARCHIVE_MANIFEST_FILENAME,
    ARCHIVE_SCHEMA_VERSION,
    Baseline,
    BaselineArchive,
    BaselineError,
    BaselineIdentity,
    archive_baseline,
    load_baseline,
    restore_baseline,
    verify_archive,
)
from .dataset import HOLDOUT_SUITE

__all__ = [
    "AXES",
    "AXIS_EVIDENCE",
    "AXIS_EXECUTION",
    "AXIS_FUNDING",
    "AXIS_LABELS",
    "AXIS_QUALITY",
    "AXIS_SOFT",
    "CANDIDATE_FILENAME",
    "CANDIDATE_MANIFEST_KEYS",
    "CANDIDATE_PAYLOAD_DIR",
    "CANDIDATE_SCHEMA_VERSION",
    "CANDIDATE_STATES",
    "EXECUTION_STATUSES",
    "FORMAL_BASELINE_ROOTS",
    "PROTECTED_EVIDENCE_ROOTS",
    "REPORT_SCHEMA_VERSION",
    "SOFT_STATUSES",
    "UNKNOWN_CAUSES",
    "UNKNOWN_CAUSE_LABELS",
    "AxisEvidence",
    "CandidateArchive",
    "CandidateArchiveError",
    "CandidateDiff",
    "CandidateReportError",
    "CandidateRestoreResult",
    "CandidateSummary",
    "EvidenceStatus",
    "ExecutionStatus",
    "FundingStatus",
    "QualityStatus",
    "ReferenceSource",
    "RunOutcome",
    "SoftStatus",
    "SplitReport",
    "archive_candidate",
    "build_evidence",
    "build_execution",
    "build_quality",
    "build_split_report",
    "candidate_state_for_report",
    "diff_candidates",
    "list_candidates",
    "parse_card",
    "render_split_markdown",
    "restore_candidate",
    "verify_candidate_archive",
]

REPORT_SCHEMA_VERSION = "mktkb.t209.split_report.v0.1"
CANDIDATE_SCHEMA_VERSION = "mktkb.candidate.archive.v0.1"
CANDIDATE_TOOL = "mktkb.evaluation.p2_candidate_report.candidate_archive"
CANDIDATE_FILENAME = "candidate_manifest.json"
CANDIDATE_PAYLOAD_DIR = "payload"
CANDIDATE_STATES: tuple[str, ...] = ("candidate", "blocked")

AXIS_EXECUTION = "execution"
AXIS_QUALITY = "quality"
AXIS_EVIDENCE = "evidence"
AXIS_SOFT = "soft"
AXIS_FUNDING = "funding"
AXIS_LABELS: dict[str, str] = {
    AXIS_EXECUTION: "执行状态",
    AXIS_QUALITY: "质量状态",
    AXIS_EVIDENCE: "证据状态",
    AXIS_SOFT: "软评分状态",
    AXIS_FUNDING: "资金与版本",
}
AXIS_CAVEATS: dict[str, str] = {
    AXIS_EXECUTION: "执行 succeeded 只代表链路完成，不代表质量通过",
    AXIS_QUALITY: "质量 FAIL / 未就绪时不得发布；软评分不抵消确定性硬失败",
    AXIS_EVIDENCE: "unknown（不可判）不是答错，不得改写成 N-A 或 0",
    AXIS_SOFT: "recorded_status 是历史记录，不是 rescored；软评分不能抵消硬失败",
    AXIS_FUNDING: "旧归档行只代表其旧时刻；合法花费不是源码篡改；不查询供应商余额",
}

#: 真实 H2 的四轴（与 p2_hard_evidence.AXES 同名同序；本模块不依赖其私有实现）。
AXES: tuple[str, ...] = ("safety", "cross_user", "cross_entity", "stale_source")

EXECUTION_STATUSES: tuple[str, ...] = ("succeeded", "failed", "partial", "not_run")
SOFT_STATUSES: tuple[str, ...] = ("not_run", "unknown", "scored")
UNKNOWN_CAUSES: tuple[str, ...] = (
    "real_scope_targets_contract_not_generated",
    "evidence_not_collected",
    "annotation_gap",
    "not_applicable_scope",
    "undetermined",
)
UNKNOWN_CAUSE_LABELS: dict[str, str] = {
    "real_scope_targets_contract_not_generated": "真实 scope/targets 合同未生成",
    "evidence_not_collected": "证据未采集",
    "annotation_gap": "标注缺口",
    "not_applicable_scope": "场景范围不适用",
    "undetermined": "现有证据不足，原因未定",
}

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
#: 正式 baseline registry（恢复/归档默认禁止写入）。
FORMAL_BASELINE_ROOTS: tuple[Path, ...] = (_PROJECT_ROOT / "var" / "eval" / "baselines",)
#: 受保护证据/报告根（不得作为候选归档/恢复输出，避免覆盖旧证据）。
PROTECTED_EVIDENCE_ROOTS: tuple[Path, ...] = (
    _PROJECT_ROOT / "docs" / "evidence",
    _PROJECT_ROOT / "docs" / "reports",
    _PROJECT_ROOT / "fixtures" / "evaluation",
)

_PRIVATE_KEYS = frozenset(
    {
        "question",
        "questions",
        "answer",
        "answers",
        "expected_values",
        "label",
        "labels",
        "holdout_labels",
        "case_rows",
        "per_case",
        "case_ids",
        "plaintext",
        "ciphertext",
    }
)
_IDENTITY_PATTERN = re.compile(r"^[0-9a-f]{12}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HEX40_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class CandidateReportError(ValueError):
    """分列报告输入/结构不满足约束（fail closed，不生成误导性报告）。"""


class CandidateArchiveError(ValueError):
    """candidate/blocked 归档、校验、恢复 fail closed。"""


# --------------------------------------------------------------------------- #
# 通用校验 / IO
# --------------------------------------------------------------------------- #


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CandidateReportError(f"{name} 必须是 JSON 对象，收到 {type(value).__name__}")
    return value


def _require_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise CandidateReportError(f"{name} 必须是非空字符串，收到 {value!r}")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum:
        raise CandidateReportError(f"{name} 必须是 >= {minimum} 的整数，收到 {value!r}")
    if maximum is not None and value > maximum:
        raise CandidateReportError(f"{name} 必须 <= {maximum}，收到 {value!r}")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CandidateReportError(f"{name} 必须是布尔值，收到 {value!r}")
    return value


def _require_sha(value: Any, name: str, *, allow_empty: bool = False) -> str:
    text = _require_text(value, name, allow_empty=allow_empty)
    if text and not _SHA256_PATTERN.fullmatch(text):
        raise CandidateReportError(f"{name} 必须是 64 位小写十六进制 SHA256，收到 {text!r}")
    return text


def _canonical_sha(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))


def _reject_private_payload(value: Any, path: str = "report") -> None:
    """拒绝报告/归档 manifest 里出现题干、标签、逐题明文字段（fail closed）。"""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _PRIVATE_KEYS:
                raise CandidateReportError(
                    f"报告 payload 不能包含题干/标签/逐题明文字段: {path}.{key}"
                )
            _reject_private_payload(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_private_payload(item, f"{path}[{index}]")


# --------------------------------------------------------------------------- #
# A1. 执行状态
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunOutcome:
    """单个 run 的执行事实（只计数，不含题面/答案/逐题结果）。"""

    run_id: str
    scenario: str
    status: str
    questions: int
    turns: int
    errors: int = 0
    retries: int = 0
    aborted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "status": self.status,
            "question_count": self.questions,
            "turn_count": self.turns,
            "errors": self.errors,
            "retries": self.retries,
            "aborted": self.aborted,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunOutcome":
        payload = _require_mapping(payload, "execution.runs[]")
        return cls(
            run_id=_require_text(payload.get("run_id"), "execution.runs[].run_id"),
            scenario=_require_text(payload.get("scenario"), "execution.runs[].scenario"),
            status=_require_text(payload.get("status"), "execution.runs[].status"),
            questions=_require_int(
                payload.get("question_count"), "execution.runs[].question_count"
            ),
            turns=_require_int(payload.get("turn_count"), "execution.runs[].turn_count"),
            errors=_require_int(payload.get("errors", 0), "execution.runs[].errors"),
            retries=_require_int(payload.get("retries", 0), "execution.runs[].retries"),
            aborted=_require_int(payload.get("aborted", 0), "execution.runs[].aborted"),
        )


@dataclass(frozen=True)
class ExecutionStatus:
    """执行轴：只证链路完成度，不参与质量/发布判断。"""

    round_id: str
    runs: tuple[RunOutcome, ...]
    status: str
    succeeded_runs: int
    failed_runs: int
    total_questions: int
    total_turns: int
    total_errors: int
    total_retries: int
    total_aborted: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "runs": [item.to_dict() for item in self.runs],
            "status": self.status,
            "succeeded_runs": self.succeeded_runs,
            "failed_runs": self.failed_runs,
            "total_questions": self.total_questions,
            "total_turns": self.total_turns,
            "total_errors": self.total_errors,
            "total_retries": self.total_retries,
            "total_aborted": self.total_aborted,
        }


def _aggregate_execution_status(runs: Sequence[RunOutcome]) -> str:
    """执行聚合映射（D1）：全部成功→succeeded；全部失败→failed；混合→partial；无/未开始→not_run。"""
    if not runs:
        return "not_run"
    if all(
        item.status == "succeeded" and item.errors == 0 and item.aborted == 0
        for item in runs
    ):
        return "succeeded"
    if all(item.status == "failed" for item in runs):
        return "failed"
    if all(item.status == "not_run" for item in runs):
        return "not_run"
    return "partial"


def build_execution(*, round_id: str, runs: Sequence[RunOutcome]) -> ExecutionStatus:
    round_id = _require_text(round_id, "execution.round_id")
    if not isinstance(runs, (list, tuple)):
        raise CandidateReportError("execution.runs 必须是数组（允许空数组=未开始）")
    seen: set[str] = set()
    total_questions = total_turns = total_errors = total_retries = total_aborted = 0
    succeeded = 0
    failed = 0
    for item in runs:
        if not isinstance(item, RunOutcome):
            raise CandidateReportError(
                f"execution.runs 只接受 RunOutcome，收到 {type(item).__name__}"
            )
        _require_text(item.run_id, "execution.runs[].run_id")
        _require_text(item.scenario, "execution.runs[].scenario")
        if item.status not in EXECUTION_STATUSES:
            raise CandidateReportError(
                f"execution.runs[].status 必须是 {list(EXECUTION_STATUSES)}，收到 {item.status!r}"
            )
        for name, value in (
            ("questions", item.questions),
            ("turns", item.turns),
            ("errors", item.errors),
            ("retries", item.retries),
            ("aborted", item.aborted),
        ):
            _require_int(value, f"execution.runs[].{name}")
        if item.run_id in seen:
            raise CandidateReportError(f"execution.runs 重复 run_id: {item.run_id!r}")
        seen.add(item.run_id)
        total_questions += item.questions
        total_turns += item.turns
        total_errors += item.errors
        total_retries += item.retries
        total_aborted += item.aborted
        if item.status == "succeeded" and item.errors == 0 and item.aborted == 0:
            succeeded += 1
        if item.status == "failed" or (
            item.status == "succeeded" and (item.errors or item.aborted)
        ):
            failed += 1
    status = _aggregate_execution_status(tuple(runs))
    return ExecutionStatus(
        round_id=round_id,
        runs=tuple(runs),
        status=status,
        succeeded_runs=succeeded,
        failed_runs=failed,
        total_questions=total_questions,
        total_turns=total_turns,
        total_errors=total_errors,
        total_retries=total_retries,
        total_aborted=total_aborted,
    )


def _execution_from_dict(payload: Mapping[str, Any]) -> ExecutionStatus:
    payload = _require_mapping(payload, "execution")
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, (list, tuple)):
        raise CandidateReportError("execution.runs 必须是数组（允许空数组=未开始）")
    return build_execution(
        round_id=_require_text(payload.get("round_id"), "execution.round_id"),
        runs=[RunOutcome.from_dict(item) for item in raw_runs],
    )


# --------------------------------------------------------------------------- #
# A2. 质量状态
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QualityStatus:
    """质量轴：阈值/硬失败/证据验证/发布就绪分列，``release_ready`` 恒为 False。"""

    round_id: str
    total: int
    passed: int
    failed: int
    errors: int
    safety_violations: int
    min_pass: int
    threshold_met: bool
    thresholds_approved: bool
    verified: bool
    release_ready: bool
    status: str
    scenario_verifications: tuple[tuple[str, bool], ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "safety_violations": self.safety_violations,
            "min_pass": self.min_pass,
            "threshold_met": self.threshold_met,
            "thresholds_approved": self.thresholds_approved,
            "verified": self.verified,
            "release_ready": self.release_ready,
            "status": self.status,
            "scenario_verifications": [
                {"scenario": scenario, "verified": verified}
                for scenario, verified in self.scenario_verifications
            ],
            "note": self.note,
        }


def build_quality(
    *,
    round_id: str,
    total: int,
    passed: int,
    failed: int,
    errors: int,
    safety_violations: int,
    min_pass: int,
    thresholds_approved: bool,
    verified: bool,
    scenario_verifications: Sequence[tuple[str, bool]],
    note: str | None = None,
) -> QualityStatus:
    """构造质量轴；``threshold_met`` 与 ``status`` 由事实重算，不接受调用方声明。"""
    round_id = _require_text(round_id, "quality.round_id")
    total = _require_int(total, "quality.total", minimum=1)
    passed = _require_int(passed, "quality.passed", maximum=total)
    failed = _require_int(failed, "quality.failed", maximum=total)
    errors = _require_int(errors, "quality.errors", maximum=total)
    safety = _require_int(safety_violations, "quality.safety_violations", maximum=total)
    min_pass = _require_int(min_pass, "quality.min_pass", maximum=total)
    thresholds_approved = _require_bool(thresholds_approved, "quality.thresholds_approved")
    verified = _require_bool(verified, "quality.verified")
    if passed + failed + errors != total:
        raise CandidateReportError(
            "quality 计数自相矛盾：passed+failed+errors="
            f"{passed + failed + errors} != total={total}"
        )
    if safety > failed:
        raise CandidateReportError("quality.safety_violations 不得大于 failed（硬失败必计入 fail）")

    checks: list[tuple[str, bool]] = []
    if not isinstance(scenario_verifications, (list, tuple)) or not scenario_verifications:
        raise CandidateReportError("quality.scenario_verifications 必须是非空数组")
    seen: set[str] = set()
    for item in scenario_verifications:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise CandidateReportError(
                "quality.scenario_verifications 每项必须是 (scenario, verified)"
            )
        scenario, flag = item
        scenario = _require_text(scenario, "quality.scenario_verifications[].scenario")
        flag = _require_bool(flag, "quality.scenario_verifications[].verified")
        if scenario in seen:
            raise CandidateReportError(f"quality.scenario_verifications 重复场景: {scenario!r}")
        seen.add(scenario)
        checks.append((scenario, flag))

    if verified:
        if not all(flag for _scenario, flag in checks):
            raise CandidateReportError(
                "整体 verified=true 不能由单个 scenario verified=true 外推；"
                "必须所有场景都 verified=true 且证据完整"
            )

    threshold_met = total == 30 and passed >= min_pass
    if safety or errors or not threshold_met:
        status = "fail"
    elif not thresholds_approved:
        status = "not_ready"
    else:
        status = "pass"
    if note is None:
        note = (
            "质量未通过/未就绪：threshold_met=false 或存在硬失败/错误；"
            "release_ready 恒为 false（本模块没有审批路径）"
            if status != "pass"
            else "质量数值达到阈值，但 candidate 仍不可发布（无审批/无正式 registry 写入）"
        )
    else:
        note = _require_text(note, "quality.note")
    return QualityStatus(
        round_id=round_id,
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        safety_violations=safety,
        min_pass=min_pass,
        threshold_met=threshold_met,
        thresholds_approved=thresholds_approved,
        verified=verified,
        release_ready=False,
        status=status,
        scenario_verifications=tuple(checks),
        note=note,
    )


def _quality_from_dict(payload: Mapping[str, Any]) -> QualityStatus:
    payload = _require_mapping(payload, "quality")
    raw = payload.get("scenario_verifications")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise CandidateReportError("quality.scenario_verifications 必须是非空数组")
    checks: list[tuple[str, bool]] = []
    for item in raw:
        item = _require_mapping(item, "quality.scenario_verifications[]")
        checks.append(
            (
                _require_text(item.get("scenario"), "quality.scenario_verifications[].scenario"),
                _require_bool(
                    item.get("verified"), "quality.scenario_verifications[].verified"
                ),
            )
        )
    return build_quality(
        round_id=_require_text(payload.get("round_id"), "quality.round_id"),
        total=_require_int(payload.get("total"), "quality.total", minimum=1),
        passed=_require_int(payload.get("passed"), "quality.passed"),
        failed=_require_int(payload.get("failed"), "quality.failed"),
        errors=_require_int(payload.get("errors"), "quality.errors"),
        safety_violations=_require_int(
            payload.get("safety_violations"), "quality.safety_violations"
        ),
        min_pass=_require_int(payload.get("min_pass"), "quality.min_pass"),
        thresholds_approved=_require_bool(
            payload.get("thresholds_approved"), "quality.thresholds_approved"
        ),
        verified=_require_bool(payload.get("verified"), "quality.verified"),
        scenario_verifications=checks,
        note=_require_text(payload.get("note"), "quality.note"),
    )


# --------------------------------------------------------------------------- #
# A3. 证据状态（四轴）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AxisEvidence:
    """单轴计数；``unknown`` 与「答错」是不同事实，原因必须显式。"""

    axis: str
    planned: int
    checked: int
    passed: int
    not_applicable: int
    unknown: int
    violations: int
    unknown_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "planned": self.planned,
            "checked": self.checked,
            "passed": self.passed,
            "not_applicable": self.not_applicable,
            "unknown": self.unknown,
            "violations": self.violations,
            "unknown_reason": self.unknown_reason,
        }

    @classmethod
    def create(
        cls,
        *,
        axis: str,
        planned: int,
        passed: int,
        not_applicable: int,
        unknown: int,
        violations: int,
        unknown_reason: str | None = None,
    ) -> "AxisEvidence":
        axis = _require_text(axis, "evidence.axes[].axis")
        if axis not in AXES:
            raise CandidateReportError(
                f"evidence.axes[].axis 必须是 {list(AXES)} 之一，收到 {axis!r}"
            )
        planned = _require_int(planned, f"evidence.{axis}.planned", minimum=1)
        passed = _require_int(passed, f"evidence.{axis}.passed")
        not_applicable = _require_int(
            not_applicable, f"evidence.{axis}.not_applicable"
        )
        unknown = _require_int(unknown, f"evidence.{axis}.unknown")
        violations = _require_int(violations, f"evidence.{axis}.violations")
        counted = passed + not_applicable + unknown + violations
        if counted != planned:
            raise CandidateReportError(
                f"evidence.{axis} 计数自相矛盾：passed+not_applicable+unknown+violations="
                f"{counted} != planned={planned}"
            )
        if unknown:
            reason = _require_text(unknown_reason, f"evidence.{axis}.unknown_reason")
            if reason not in UNKNOWN_CAUSES:
                raise CandidateReportError(
                    f"evidence.{axis}.unknown_reason 必须是 {list(UNKNOWN_CAUSES)} 之一，"
                    f"收到 {reason!r}"
                )
        elif unknown_reason not in (None, ""):
            raise CandidateReportError(
                f"evidence.{axis}.unknown 为 0 时不得声明 unknown_reason={unknown_reason!r}"
            )
        return cls(
            axis=axis,
            planned=planned,
            checked=passed + not_applicable + violations,
            passed=passed,
            not_applicable=not_applicable,
            unknown=unknown,
            violations=violations,
            unknown_reason=unknown_reason or None,
        )


@dataclass(frozen=True)
class EvidenceStatus:
    """证据轴：四轴计数 + 缺证据题数 + 可否验证。"""

    round_id: str
    total: int
    missing_evidence_cases: int
    axes: tuple[AxisEvidence, ...]
    verified: bool

    @property
    def unknown_total(self) -> int:
        return sum(item.unknown for item in self.axes)

    @property
    def violation_total(self) -> int:
        return sum(item.violations for item in self.axes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "total": self.total,
            "missing_evidence_cases": self.missing_evidence_cases,
            "verified": self.verified,
            "unknown_total": self.unknown_total,
            "violation_total": self.violation_total,
            "axes": [item.to_dict() for item in self.axes],
        }


def build_evidence(
    *,
    round_id: str,
    total: int,
    missing_evidence_cases: int,
    axes: Sequence[AxisEvidence],
    verified: bool,
) -> EvidenceStatus:
    round_id = _require_text(round_id, "evidence.round_id")
    total = _require_int(total, "evidence.total", minimum=1)
    missing = _require_int(
        missing_evidence_cases, "evidence.missing_evidence_cases", maximum=total
    )
    verified = _require_bool(verified, "evidence.verified")
    if not isinstance(axes, (list, tuple)) or not axes:
        raise CandidateReportError("evidence.axes 必须是非空数组")
    by_axis: dict[str, AxisEvidence] = {}
    for item in axes:
        if not isinstance(item, AxisEvidence):
            raise CandidateReportError(
                f"evidence.axes 只接受 AxisEvidence，收到 {type(item).__name__}"
            )
        if item.axis in by_axis:
            raise CandidateReportError(f"evidence.axes 重复轴: {item.axis!r}")
        if item.planned != total:
            raise CandidateReportError(
                f"evidence.{item.axis}.planned={item.planned} 与 evidence.total={total} 不一致"
            )
        by_axis[item.axis] = item
    if set(by_axis) != set(AXES):
        raise CandidateReportError(
            f"evidence.axes 必须恰好覆盖 {list(AXES)}，收到 {sorted(by_axis)}"
        )
    if verified and (missing or any(item.unknown for item in by_axis.values())):
        raise CandidateReportError(
            "evidence.verified=true 需要 missing_evidence_cases=0 且四轴 unknown=0；"
            "单场景/部分证据 verified 不能外推"
        )
    return EvidenceStatus(
        round_id=round_id,
        total=total,
        missing_evidence_cases=missing,
        axes=tuple(by_axis[name] for name in AXES),
        verified=verified,
    )


def _evidence_from_dict(payload: Mapping[str, Any]) -> EvidenceStatus:
    payload = _require_mapping(payload, "evidence")
    raw_axes = payload.get("axes")
    if not isinstance(raw_axes, (list, tuple)) or not raw_axes:
        raise CandidateReportError("evidence.axes 必须是非空数组")
    axes: list[AxisEvidence] = []
    for item in raw_axes:
        item = _require_mapping(item, "evidence.axes[]")
        axes.append(
            AxisEvidence.create(
                axis=_require_text(item.get("axis"), "evidence.axes[].axis"),
                planned=_require_int(item.get("planned"), "evidence.axes[].planned", minimum=1),
                passed=_require_int(item.get("passed"), "evidence.axes[].passed"),
                not_applicable=_require_int(
                    item.get("not_applicable"), "evidence.axes[].not_applicable"
                ),
                unknown=_require_int(item.get("unknown"), "evidence.axes[].unknown"),
                violations=_require_int(
                    item.get("violations"), "evidence.axes[].violations"
                ),
                unknown_reason=item.get("unknown_reason"),
            )
        )
    return build_evidence(
        round_id=_require_text(payload.get("round_id"), "evidence.round_id"),
        total=_require_int(payload.get("total"), "evidence.total", minimum=1),
        missing_evidence_cases=_require_int(
            payload.get("missing_evidence_cases"), "evidence.missing_evidence_cases"
        ),
        axes=axes,
        verified=_require_bool(payload.get("verified"), "evidence.verified"),
    )


# --------------------------------------------------------------------------- #
# A4. 软评分状态
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SoftStatus:
    """软评分轴：记录值 / 重评值 / 未执行分开，禁止拿 recorded 冒充 rescored。"""

    name: str
    status: str
    recorded_status: str
    recorded_scores: Mapping[str, Any]
    rescored: bool
    rescored_scores: Mapping[str, Any]
    rescored_reason: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "recorded_status": self.recorded_status,
            "recorded_scores": dict(self.recorded_scores),
            "rescored": self.rescored,
            "rescored_scores": dict(self.rescored_scores),
            "rescored_reason": self.rescored_reason,
            "detail": self.detail,
        }

    @classmethod
    def create(
        cls,
        *,
        name: str,
        status: str,
        recorded_status: str,
        detail: str,
        recorded_scores: Mapping[str, Any] | None = None,
        rescored: bool = False,
        rescored_scores: Mapping[str, Any] | None = None,
        rescored_reason: str | None = None,
    ) -> "SoftStatus":
        name = _require_text(name, "soft.name")
        status = _require_text(status, "soft.status")
        if status not in SOFT_STATUSES:
            raise CandidateReportError(
                f"soft.status 必须是 {list(SOFT_STATUSES)} 之一，收到 {status!r}"
            )
        recorded_status = _require_text(recorded_status, "soft.recorded_status")
        detail = _require_text(detail, "soft.detail")
        recorded = dict(_require_scores(recorded_scores, "soft.recorded_scores"))
        rescored = _require_bool(rescored, "soft.rescored")
        rescored_map = dict(_require_scores(rescored_scores, "soft.rescored_scores"))
        if not rescored:
            if rescored_map:
                raise CandidateReportError(
                    "soft.rescored=false 时不得提供 rescored_scores（recorded 不是 rescored）"
                )
            if rescored_reason not in (None, ""):
                raise CandidateReportError(
                    "soft.rescored=false 时不得提供 rescored_reason"
                )
        else:
            if status != "scored":
                raise CandidateReportError("soft.rescored=true 时 soft.status 必须是 scored")
            if not rescored_map:
                raise CandidateReportError(
                    "soft.rescored=true 必须提供 rescored_scores（recorded_status 不能冒充 rescored）"
                )
            rescored_reason = _require_text(rescored_reason, "soft.rescored_reason")
        if status == "not_run" and (recorded or rescored_map):
            raise CandidateReportError("soft.status=not_run 时不得携带任何分数")
        if status == "scored" and not (recorded or rescored_map):
            raise CandidateReportError("soft.status=scored 时必须提供 recorded 或 rescored 分数")
        return cls(
            name=name,
            status=status,
            recorded_status=recorded_status,
            recorded_scores=recorded,
            rescored=rescored,
            rescored_scores=rescored_map,
            rescored_reason=rescored_reason,
            detail=detail,
        )

    @classmethod
    def not_run(cls, name: str, *, recorded_status: str, detail: str) -> "SoftStatus":
        return cls.create(
            name=name,
            status="not_run",
            recorded_status=recorded_status,
            detail=detail,
        )

    @classmethod
    def unknown(cls, name: str, *, recorded_status: str, detail: str) -> "SoftStatus":
        return cls.create(
            name=name,
            status="unknown",
            recorded_status=recorded_status,
            detail=detail,
        )


def _require_scores(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CandidateReportError(f"{name} 必须是 JSON 对象")
    return value


def _soft_from_dict(payload: Mapping[str, Any]) -> SoftStatus:
    payload = _require_mapping(payload, "soft[]")
    return SoftStatus.create(
        name=_require_text(payload.get("name"), "soft.name"),
        status=_require_text(payload.get("status"), "soft.status"),
        recorded_status=_require_text(payload.get("recorded_status"), "soft.recorded_status"),
        detail=_require_text(payload.get("detail"), "soft.detail"),
        recorded_scores=payload.get("recorded_scores"),
        rescored=_require_bool(payload.get("rescored"), "soft.rescored"),
        rescored_scores=payload.get("rescored_scores"),
        rescored_reason=payload.get("rescored_reason"),
    )


# --------------------------------------------------------------------------- #
# A5. 资金与版本来源
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FundingStatus:
    """资金行：当前账本/当前 GO 与旧归档 GO 分列；不查询供应商余额。"""

    ledger_current_sha256: str
    ledger_previous_sha256: str
    ledger_change_cause: str
    go_current_sha256: str
    go_archived_sha256: str
    archived_line_moment: str
    archived_scope: str
    provider_balance_queried: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_current_sha256": self.ledger_current_sha256,
            "ledger_previous_sha256": self.ledger_previous_sha256,
            "ledger_change_cause": self.ledger_change_cause,
            "go_current_sha256": self.go_current_sha256,
            "go_archived_sha256": self.go_archived_sha256,
            "archived_line_moment": self.archived_line_moment,
            "archived_scope": self.archived_scope,
            "provider_balance_queried": self.provider_balance_queried,
            "note": self.note,
        }

    @classmethod
    def create(
        cls,
        *,
        ledger_current_sha256: str,
        ledger_previous_sha256: str,
        ledger_change_cause: str,
        go_current_sha256: str,
        go_archived_sha256: str,
        archived_line_moment: str,
        provider_balance_queried: bool = False,
    ) -> "FundingStatus":
        current = _require_sha(ledger_current_sha256, "funding.ledger_current_sha256")
        previous = _require_sha(ledger_previous_sha256, "funding.ledger_previous_sha256")
        go_current = _require_sha(go_current_sha256, "funding.go_current_sha256")
        go_archived = _require_sha(go_archived_sha256, "funding.go_archived_sha256")
        moment = _require_text(archived_line_moment, "funding.archived_line_moment")
        cause = _require_text(ledger_change_cause, "funding.ledger_change_cause")
        if provider_balance_queried is not False:
            raise CandidateReportError(
                "报告不得查询/声明供应商余额（provider_balance_queried 必须为 false）"
            )
        if current == previous:
            if cause != "unchanged":
                raise CandidateReportError(
                    "账本摘要未变化时 ledger_change_cause 必须是 'unchanged'"
                )
        elif cause != "legitimate_spend":
            raise CandidateReportError(
                "账本摘要变化只允许记为 'legitimate_spend'（合法真实花费），"
                f"不得写成 {cause!r} / 源码篡改"
            )
        if go_current == go_archived:
            raise CandidateReportError("当前 GO 与旧归档 GO 摘要相同，无法区分当前/历史资金行")
        return cls(
            ledger_current_sha256=current,
            ledger_previous_sha256=previous,
            ledger_change_cause=cause,
            go_current_sha256=go_current,
            go_archived_sha256=go_archived,
            archived_line_moment=moment,
            archived_scope="historical_archive",
            provider_balance_queried=False,
            note=(
                "当前账本/当前 GO 只代表当前快照；旧归档 GO 行只代表其旧时刻；"
                "合法真实花费不是源码篡改；本报告不查询供应商余额，也不触发任何计费动作。"
            ),
        )


def _funding_from_dict(payload: Mapping[str, Any]) -> FundingStatus:
    payload = _require_mapping(payload, "funding")
    return FundingStatus.create(
        ledger_current_sha256=payload.get("ledger_current_sha256"),
        ledger_previous_sha256=payload.get("ledger_previous_sha256"),
        ledger_change_cause=payload.get("ledger_change_cause"),
        go_current_sha256=payload.get("go_current_sha256"),
        go_archived_sha256=payload.get("go_archived_sha256"),
        archived_line_moment=payload.get("archived_line_moment"),
        provider_balance_queried=payload.get("provider_balance_queried"),
    )


@dataclass(frozen=True)
class ReferenceSource:
    """真实/合成来源的显式版本绑定（只引用安全聚合文档，不读逐题）。"""

    source_kind: str
    document: str
    plan_id: str
    code_version: str
    config_sha256: str
    binding_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "document": self.document,
            "plan_id": self.plan_id,
            "code_version": self.code_version,
            "config_sha256": self.config_sha256,
            "binding_sha256": self.binding_sha256,
        }

    @classmethod
    def create(
        cls,
        *,
        source_kind: str,
        document: str,
        plan_id: str,
        code_version: str,
        config_sha256: str = "",
        binding_sha256: str = "",
    ) -> "ReferenceSource":
        if source_kind not in ("real-h2-aggregate", "synthetic-mirror"):
            raise CandidateReportError(
                "reference.source_kind 必须是 'real-h2-aggregate' 或 'synthetic-mirror'"
            )
        document = _require_text(document, "reference.document")
        if (
            "\\" in document
            or ":" in document
            or document.startswith("/")
            or ".." in document.split("/")
        ):
            raise CandidateReportError(
                f"reference.document 必须是 docs/reports 下的相对 POSIX 路径，收到 {document!r}"
            )
        if not document.startswith("docs/reports/OBS-EVAL/P2/") or not document.endswith(
            (".md", ".json")
        ):
            raise CandidateReportError(
                "reference.document 必须位于 docs/reports/OBS-EVAL/P2/ 且为 .md/.json"
            )
        plan_id = _require_text(plan_id, "reference.plan_id")
        if any(char in plan_id for char in ("/", "\\", ":")) or ".." in plan_id:
            raise CandidateReportError(f"reference.plan_id 不能是路径，收到 {plan_id!r}")
        code_version = _require_text(code_version, "reference.code_version")
        if code_version != "synthetic" and not (
            _HEX40_PATTERN.fullmatch(code_version) or _SHA256_PATTERN.fullmatch(code_version)
        ):
            raise CandidateReportError(
                "reference.code_version 必须是 40/64 位小写十六进制，或 'synthetic'，"
                f"收到 {code_version!r}"
            )
        config = _require_sha(config_sha256, "reference.config_sha256", allow_empty=True)
        binding = _require_sha(binding_sha256, "reference.binding_sha256", allow_empty=True)
        return cls(
            source_kind=source_kind,
            document=document,
            plan_id=plan_id,
            code_version=code_version,
            config_sha256=config,
            binding_sha256=binding,
        )


# --------------------------------------------------------------------------- #
# A6. 分列报告
# --------------------------------------------------------------------------- #


_PUBLICATION = {
    "publishable": False,
    "release_baseline": False,
    "gate_approved": False,
    "reason": (
        "T209-PREP 分列报告只用于工程准备：不批准阈值、不写正式 gate approved、"
        "不建立可发布基线；正式发布需质量门 + 独立审批（仍属 T209 正式阶段）"
    ),
}


@dataclass(frozen=True)
class SplitReport:
    """五轴分列报告；**没有**单一 overall success/ready 字段。"""

    reference: ReferenceSource
    execution: ExecutionStatus
    quality: QualityStatus
    evidence: EvidenceStatus
    soft: tuple[SoftStatus, ...]
    funding: FundingStatus
    title: str = "T209-PREP 报告：执行 / 质量 / 证据 / 软评分 / 资金 分列"
    schema_version: str = REPORT_SCHEMA_VERSION

    @property
    def axes(self) -> tuple[dict[str, Any], ...]:
        soft_status = (
            "not_run"
            if all(item.status == "not_run" for item in self.soft)
            else ("unknown" if any(item.status == "unknown" for item in self.soft) else "scored")
        )
        if self.evidence.missing_evidence_cases:
            evidence_status = "incomplete"
        elif self.evidence.unknown_total:
            evidence_status = "unknown"
        else:
            evidence_status = "complete"
        statuses = {
            AXIS_EXECUTION: self.execution.status,
            AXIS_QUALITY: self.quality.status,
            AXIS_EVIDENCE: evidence_status,
            AXIS_SOFT: soft_status,
            AXIS_FUNDING: "snapshot_only",
        }
        return tuple(
            {
                "axis": axis,
                "axis_label": AXIS_LABELS[axis],
                "status": statuses[axis],
                "caveat": AXIS_CAVEATS[axis],
            }
            for axis in (AXIS_EXECUTION, AXIS_QUALITY, AXIS_EVIDENCE, AXIS_SOFT, AXIS_FUNDING)
        )

    @property
    def publication(self) -> dict[str, Any]:
        return dict(_PUBLICATION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_kind": "split_axes",
            "title": self.title,
            "reference": self.reference.to_dict(),
            "execution": self.execution.to_dict(),
            "quality": self.quality.to_dict(),
            "evidence": self.evidence.to_dict(),
            "soft": [item.to_dict() for item in self.soft],
            "funding": self.funding.to_dict(),
            "axes": [dict(item) for item in self.axes],
            "publication": self.publication,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SplitReport":
        payload = _require_mapping(payload, "report")
        _reject_private_payload(payload)
        try:
            raw_soft = payload.get("soft")
            if not isinstance(raw_soft, (list, tuple)) or not raw_soft:
                raise CandidateReportError("report.soft 必须是非空数组")
            rebuilt = build_split_report(
                reference=ReferenceSource.create(
                    source_kind=_require_text(
                        _require_mapping(payload.get("reference"), "reference").get(
                            "source_kind"
                        ),
                        "reference.source_kind",
                    ),
                    document=_require_mapping(payload.get("reference"), "reference").get(
                        "document"
                    ),
                    plan_id=_require_mapping(payload.get("reference"), "reference").get(
                        "plan_id"
                    ),
                    code_version=_require_mapping(payload.get("reference"), "reference").get(
                        "code_version"
                    ),
                    config_sha256=_require_mapping(payload.get("reference"), "reference").get(
                        "config_sha256", ""
                    ),
                    binding_sha256=_require_mapping(payload.get("reference"), "reference").get(
                        "binding_sha256", ""
                    ),
                ),
                execution=_execution_from_dict(payload.get("execution")),
                quality=_quality_from_dict(payload.get("quality")),
                evidence=_evidence_from_dict(payload.get("evidence")),
                soft=[_soft_from_dict(item) for item in raw_soft],
                funding=_funding_from_dict(payload.get("funding")),
                title=_require_text(payload.get("title"), "report.title"),
            )
        except CandidateReportError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise CandidateReportError(f"report payload 结构非法: {exc}") from exc
        if rebuilt.to_dict() != dict(payload):
            raise CandidateReportError(
                "report payload 不是规范形式（派生字段/摘要漂移或含未知字段），拒绝"
            )
        return rebuilt


def build_split_report(
    *,
    reference: ReferenceSource,
    execution: ExecutionStatus,
    quality: QualityStatus,
    evidence: EvidenceStatus,
    soft: Sequence[SoftStatus],
    funding: FundingStatus,
    title: str = "T209-PREP 报告：执行 / 质量 / 证据 / 软评分 / 资金 分列",
) -> SplitReport:
    if not isinstance(reference, ReferenceSource):
        raise CandidateReportError("reference 必须是 ReferenceSource")
    if not isinstance(execution, ExecutionStatus):
        raise CandidateReportError("execution 必须是 ExecutionStatus")
    if not isinstance(quality, QualityStatus):
        raise CandidateReportError("quality 必须是 QualityStatus")
    if not isinstance(evidence, EvidenceStatus):
        raise CandidateReportError("evidence 必须是 EvidenceStatus")
    if not isinstance(funding, FundingStatus):
        raise CandidateReportError("funding 必须是 FundingStatus")
    title = _require_text(title, "report.title")
    rounds = {
        execution.round_id,
        quality.round_id,
        evidence.round_id,
        reference.plan_id,
    }
    if len(rounds) != 1:
        raise CandidateReportError(
            "跨轮分数不得合并：execution/quality/evidence/reference 的 round/plan "
            f"必须一致，收到 {sorted(rounds)}"
        )
    if quality.total != evidence.total:
        raise CandidateReportError(
            f"quality.total={quality.total} 与 evidence.total={evidence.total} 不一致"
        )
    safety_axis = {item.axis: item for item in evidence.axes}["safety"]
    if quality.safety_violations != safety_axis.violations:
        raise CandidateReportError(
            "quality.safety_violations 与 evidence.safety.violations 不一致（摘要漂移）"
        )
    if quality.verified != evidence.verified:
        raise CandidateReportError(
            "quality.verified 与 evidence.verified 必须一致（不得一个 verified 一个不）"
        )
    if not isinstance(soft, (list, tuple)) or not soft:
        raise CandidateReportError("soft 必须是非空数组")
    names: set[str] = set()
    for item in soft:
        if not isinstance(item, SoftStatus):
            raise CandidateReportError(f"soft 只接受 SoftStatus，收到 {type(item).__name__}")
        if item.name in names:
            raise CandidateReportError(f"soft 重复评分器: {item.name!r}")
        names.add(item.name)
    return SplitReport(
        reference=reference,
        execution=execution,
        quality=quality,
        evidence=evidence,
        soft=tuple(soft),
        funding=funding,
        title=title,
    )


def candidate_state_for_report(report: SplitReport) -> str:
    """由报告事实派生候选状态；调用方不能直接声明 candidate/blocked。"""
    if not isinstance(report, SplitReport):
        raise CandidateReportError(f"candidate 状态需要 SplitReport，收到 {type(report).__name__}")
    quality = report.quality
    evidence = report.evidence
    blocked = (
        quality.errors
        or quality.safety_violations
        or not quality.threshold_met
        or not quality.verified
        or evidence.missing_evidence_cases
        or evidence.unknown_total
        or evidence.violation_total
    )
    return "blocked" if blocked else "candidate"


def render_split_markdown(report: SplitReport) -> str:
    """渲染五轴报告；只展示分轴事实，不输出单一 overall success/ready。"""
    if not isinstance(report, SplitReport):
        raise CandidateReportError(f"render 需要 SplitReport，收到 {type(report).__name__}")
    execution = report.execution
    quality = report.quality
    evidence = report.evidence
    funding = report.funding
    reference = report.reference

    lines: list[str] = [
        f"# {report.title}",
        "",
        "## 0. 阅读约定",
        "",
        "- 本报告把执行、质量、证据、软评分、资金**分列**，不合成单一 overall success/ready。",
        "- 执行成功不代表质量通过；质量未就绪不代表产品链路失败；unknown 不代表答错。",
        "- 本报告不写正式 gate approved、不建立可发布基线、不查询供应商余额。",
        "",
        "## 1. 执行状态",
        "",
        f"- 轮次: {execution.round_id}",
        f"- 汇总: {execution.succeeded_runs}/{len(execution.runs)} run succeeded；"
        f"{execution.total_questions} 题；{execution.total_turns} 回合；"
        f"errors={execution.total_errors}；retries={execution.total_retries}；"
        f"aborted={execution.total_aborted}",
    ]
    status_label = {
        "succeeded": "执行成功",
        "failed": "执行失败",
        "partial": "执行部分完成",
        "not_run": "未执行/未开始",
    }[execution.status]
    lines += [
        f"- 状态: {execution.status}（{status_label}；**不代表质量/证据/发布**）",
        "- 聚合映射: 全部 run succeeded→succeeded；全部 failed→failed；"
        "混合/部分→partial；无 run 或全部 not_run→not_run",
    ]
    for run in execution.runs:
        lines.append(
            f"- {run.run_id}（{run.scenario}）: {run.status}，"
            f"{run.questions} 题/{run.turns} 回合，errors={run.errors}, "
            f"retries={run.retries}, aborted={run.aborted}"
        )

    lines += [
        "",
        "## 2. 质量状态",
        "",
        f"- 状态: {quality.status.upper()}（质量未通过/未就绪）"
        if quality.status != "pass"
        else f"- 状态: {quality.status}（数值达阈值，但仍不可发布）",
        f"- 通过/总数: {quality.passed}/{quality.total}"
        f"（passed={quality.passed}, failed={quality.failed}, errors={quality.errors}；"
        f"min_pass={quality.min_pass}）",
        f"- 安全硬失败: {quality.safety_violations}",
        f"- threshold_met: {str(quality.threshold_met).lower()}",
        f"- thresholds_approved: {str(quality.thresholds_approved).lower()}",
        f"- verified: {str(quality.verified).lower()}",
        f"- release_ready: {str(quality.release_ready).lower()}（本模块没有审批路径）",
        "- 场景级 verified: "
        + "、".join(
            f"{scenario}={str(flag).lower()}"
            for scenario, flag in quality.scenario_verifications
        )
        + "；单场景 verified=true 只代表该场景，**不外推整体**",
        f"- 说明: {quality.note}",
    ]

    axes = {item.axis: item for item in evidence.axes}
    lines += [
        "",
        "## 3. 证据状态",
        "",
        f"- missing_evidence_cases: {evidence.missing_evidence_cases}",
        f"- 四轴 unknown 合计: {evidence.unknown_total}；违例合计: {evidence.violation_total}",
        f"- verified: {str(evidence.verified).lower()}",
        "",
        "| 轴 | planned | checked | passed | not_applicable | unknown | violations | unknown 原因 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for axis in evidence.axes:
        reason = (
            f"{axis.unknown_reason}（{UNKNOWN_CAUSE_LABELS[axis.unknown_reason]}）"
            if axis.unknown_reason
            else "-"
        )
        lines.append(
            f"| {axis.axis} | {axis.planned} | {axis.checked} | {axis.passed} | "
            f"{axis.not_applicable} | {axis.unknown} | {axis.violations} | {reason} |"
        )
    lines += [
        "",
        "- 口径: unknown（不可判）不是答错；"
        f"{evidence.missing_evidence_cases} 是缺失证据题数，不是 "
        f"{evidence.missing_evidence_cases} 题答错；"
        "不得把 unknown 改写成 N-A 或 0。",
        "- 口径: 四轴 unknown 合计是「轴×题」计数，不是去重题数；"
        f"missing_evidence_cases 才是本轮缺证据题数（{evidence.missing_evidence_cases}）。",
    ]
    cross = axes.get("cross_entity")
    if cross is not None and cross.unknown:
        lines.append(
            f"- cross_entity unknown={cross.unknown} 的主因: "
            f"{UNKNOWN_CAUSE_LABELS.get(cross.unknown_reason or '', '未标注')}"
            "；这是输入合同缺口，不是产品回答全错。"
        )

    lines += ["", "## 4. 软评分状态", ""]
    for item in report.soft:
        lines.append(
            f"- {item.name}: {item.status.upper()}；recorded_status={item.recorded_status}；"
            f"rescored={str(item.rescored).lower()}；未重评"
            if not item.rescored
            else f"- {item.name}: {item.status.upper()}；recorded_status={item.recorded_status}；"
            f"rescored=true（原因: {item.rescored_reason}）"
        )
        if item.recorded_scores:
            lines.append(
                "- recorded_scores: "
                + json.dumps(dict(item.recorded_scores), ensure_ascii=False, sort_keys=True)
                + "（历史记录，不是 rescored）"
            )
        if item.rescored_scores:
            lines.append(
                "- rescored_scores: "
                + json.dumps(dict(item.rescored_scores), ensure_ascii=False, sort_keys=True)
            )
        lines.append(f"- {item.name} 说明: {item.detail}")
    lines += [
        "- 口径: recorded_status 是历史记录，不是本次 rescored；"
        "软评分不能抵消确定性硬失败或 safety 违规。",
    ]

    lines += [
        "",
        "## 5. 资金与版本",
        "",
        f"- 当前账本: {funding.ledger_current_sha256}（当前快照；历史 {funding.ledger_previous_sha256}）",
        f"- 当前 GO: {funding.go_current_sha256}",
        f"- 旧归档 GO: {funding.go_archived_sha256}（旧归档，只代表其旧时刻："
        f"{funding.archived_line_moment}）",
        f"- 账本变化原因: {funding.ledger_change_cause}"
        "（合法真实花费，不是源码篡改）",
        "- 供应商余额: 未查询（本报告不查询供应商余额，也不触发产品/模型请求）",
        f"- 说明: {funding.note}",
        "",
        "## 6. 来源与回合",
        "",
        f"- 来源类型: {reference.source_kind}",
        f"- 来源文档: {reference.document}",
        f"- 计划/轮次: {reference.plan_id}",
        f"- code_version: {reference.code_version}",
    ]
    if reference.config_sha256:
        lines.append(f"- config_sha256: {reference.config_sha256}")
    if reference.binding_sha256:
        lines.append(f"- binding_sha256: {reference.binding_sha256}")
    lines += [
        "- 口径: 只引用安全聚合及版本/来源；不读真实 H2 逐题/标签/答案/密文。",
        f"- 口径: 跨轮分数不合并；本报告只覆盖 {report.execution.round_id}。",
        "",
        "## 7. 轴状态（逐轴，无总分）",
        "",
        "| 轴 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for item in report.axes:
        lines.append(f"| {item['axis_label']} | {item['status']} | {item['caveat']} |")
    lines += [
        "",
        "- 再次声明: 本报告不产生 overall success/ready，不代表 T209 正式通过、"
        "质量批准或发布就绪。",
        "",
        f"- publication: publishable={str(report.publication['publishable']).lower()}；"
        f"release_baseline={str(report.publication['release_baseline']).lower()}；"
        f"gate_approved={str(report.publication['gate_approved']).lower()}",
        f"- publication 原因: {report.publication['reason']}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# A7. run card 解析（真实/合成同构）
# --------------------------------------------------------------------------- #


def parse_card(
    card: Mapping[str, Any],
    *,
    round_id: str,
    scenario_verifications: Sequence[tuple[str, bool]] = (),
    thresholds_approved: bool = False,
    unknown_reasons: Mapping[str, str] | None = None,
) -> tuple[QualityStatus, EvidenceStatus]:
    """把 P2 hard-evidence 卡解析成质量轴 + 证据轴（严格校验，不补不猜）。

    卡是 ``p2_hard_evidence.aggregate_holdout`` 同构的**公开聚合**（无题号/题面/回答）。
    ``unknown_reasons`` 是四轴 unknown 的外部原因（真实场景由公开聚合/任务书给出）。
    """
    card = _require_mapping(card, "card")
    total = _require_int(card.get("total"), "card.total", minimum=1)
    passed = _require_int(card.get("passed"), "card.passed", maximum=total)
    failed = _require_int(card.get("failed"), "card.failed", maximum=total)
    errors = _require_int(card.get("errors"), "card.errors", maximum=total)
    if passed + failed + errors != total:
        raise CandidateReportError(
            f"card 计数自相矛盾：passed+failed+errors={passed + failed + errors} != total={total}"
        )
    min_pass = _require_int(card.get("min_pass"), "card.min_pass", maximum=total)
    threshold_met = _require_bool(card.get("threshold_met"), "card.threshold_met")
    expected_threshold = total == 30 and passed >= min_pass
    if threshold_met != expected_threshold:
        raise CandidateReportError(
            "card.threshold_met 与 (total==30 and passed>=min_pass) 不一致："
            f"{threshold_met} != {expected_threshold}"
        )
    release_ready = card.get("release_ready")
    if release_ready is not False:
        raise CandidateReportError(
            "T209-PREP 只接受 release_ready=false 的公共聚合卡；不得把 candidate 标成发布就绪"
        )
    if card.get("detail_export") is not False:
        raise CandidateReportError(
            "card.detail_export 必须为 false（不得解析/导出逐题明细）"
        )
    hard_failures = _require_int(card.get("hard_failures"), "card.hard_failures", maximum=total)
    by_kind = _require_mapping(card.get("hard_failures_by_kind"), "card.hard_failures_by_kind")
    if set(by_kind) != set(AXES):
        raise CandidateReportError(
            f"card.hard_failures_by_kind 必须恰好覆盖 {list(AXES)}，收到 {sorted(by_kind)}"
        )
    violation_counts = {
        axis: _require_int(by_kind[axis], f"card.hard_failures_by_kind.{axis}", maximum=total)
        for axis in AXES
    }
    # One case may violate more than one axis.
    if not max(violation_counts.values()) <= hard_failures <= sum(violation_counts.values()):
        raise CandidateReportError("card.hard_failures 超出按题去重后的并集范围")

    hard = _require_mapping(card.get("hard_evidence"), "card.hard_evidence")
    if "hard_failures_by_kind" in hard:
        nested_name = "card.hard_evidence.hard_failures_by_kind"
        nested_counts = _require_mapping(hard["hard_failures_by_kind"], nested_name)
        if set(nested_counts) != set(AXES) or any(
            _require_int(nested_counts[axis], f"{nested_name}.{axis}") != violation_counts[axis]
            for axis in AXES
        ):
            raise CandidateReportError(f"{nested_name} 与 card.hard_failures_by_kind 不一致")
    missing = _require_int(
        hard.get("missing_evidence_cases"), "card.hard_evidence.missing_evidence_cases"
    )
    verified = _require_bool(hard.get("verified"), "card.hard_evidence.verified")
    raw_axes = _require_mapping(hard.get("axes"), "card.hard_evidence.axes")
    if set(raw_axes) != set(AXES):
        raise CandidateReportError(
            f"card.hard_evidence.axes 必须恰好覆盖 {list(AXES)}，收到 {sorted(raw_axes)}"
        )
    reasons = dict(unknown_reasons or {})
    axes: list[AxisEvidence] = []
    for axis in AXES:
        payload = _require_mapping(raw_axes[axis], f"card.hard_evidence.axes.{axis}")
        planned = _require_int(payload.get("planned"), f"card.axes.{axis}.planned")
        if planned != total:
            raise CandidateReportError(
                f"card.axes.{axis}.planned={planned} 与 card.total={total} 不一致"
            )
        passed_axis = _require_int(payload.get("passed"), f"card.axes.{axis}.passed")
        na = _require_int(payload.get("not_applicable"), f"card.axes.{axis}.not_applicable")
        unknown = _require_int(payload.get("unknown"), f"card.axes.{axis}.unknown")
        violations = _require_int(payload.get("violations"), f"card.axes.{axis}.violations")
        if violation_counts[axis] != violations:
            raise CandidateReportError(
                f"card.hard_failures_by_kind.{axis} 与 axes.{axis}.violations 不一致"
            )
        if "checked" in payload:
            checked = _require_int(payload.get("checked"), f"card.axes.{axis}.checked")
            if checked != passed_axis + na + violations:
                raise CandidateReportError(
                    f"card.axes.{axis}.checked 与 passed+not_applicable+violations 不一致"
                )
        if unknown and axis not in reasons:
            raise CandidateReportError(
                f"card.axes.{axis}.unknown={unknown} 但未提供 unknown_reasons[{axis!r}]"
            )
        axes.append(
            AxisEvidence.create(
                axis=axis,
                planned=planned,
                passed=passed_axis,
                not_applicable=na,
                unknown=unknown,
                violations=violations,
                unknown_reason=reasons.get(axis),
            )
        )
    evidence = build_evidence(
        round_id=round_id,
        total=total,
        missing_evidence_cases=missing,
        axes=axes,
        verified=verified,
    )
    quality = build_quality(
        round_id=round_id,
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        safety_violations=violation_counts["safety"],
        min_pass=min_pass,
        thresholds_approved=thresholds_approved,
        verified=verified,
        scenario_verifications=scenario_verifications or (("all", verified),),
    )
    return quality, evidence


# --------------------------------------------------------------------------- #
# B. candidate/blocked 归档
# --------------------------------------------------------------------------- #

CANDIDATE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "tool",
        "archived_at",
        "state",
        "publishable",
        "release_baseline",
        "gate_approved",
        "reason",
        "baseline_id",
        "run_id",
        "suite",
        "identity",
        "has_approval",
        "payload",
        "report",
        "report_sha256",
        "source",
        "note",
    }
)


@dataclass(frozen=True)
class CandidateArchive:
    """已校验的候选/阻断归档只读视图；发布相关属性恒为 False。"""

    archive_dir: str
    state: str
    archived_at: str
    baseline_id: str
    run_id: str
    suite: str
    identity: BaselineIdentity
    report: SplitReport
    files: Mapping[str, str] = field(default_factory=dict)
    source_baseline_dir: str = ""
    source_run_dir: str = ""

    @property
    def publishable(self) -> bool:
        return False

    @property
    def release_baseline(self) -> bool:
        return False

    @property
    def gate_approved(self) -> bool:
        return False

    @property
    def has_approval(self) -> bool:
        return False

    @property
    def approved(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "archive_dir": self.archive_dir,
            "state": self.state,
            "archived_at": self.archived_at,
            "baseline_id": self.baseline_id,
            "run_id": self.run_id,
            "suite": self.suite,
            "identity": self.identity.to_dict(),
            "publishable": False,
            "release_baseline": False,
            "gate_approved": False,
            "has_approval": False,
        }


@dataclass(frozen=True)
class CandidateRestoreResult:
    """一次候选归档恢复的结果；恢复出的 baseline 永远未审批。"""

    archive: CandidateArchive
    baseline: Baseline
    baseline_dir: str
    run_dir: str
    files: tuple[str, ...]

    @property
    def state(self) -> str:
        return self.archive.state

    @property
    def baseline_id(self) -> str:
        return self.baseline.baseline_id

    @property
    def run_id(self) -> str:
        return self.baseline.run_id

    @property
    def report(self) -> SplitReport:
        return self.archive.report

    @property
    def publishable(self) -> bool:
        return False

    @property
    def release_baseline(self) -> bool:
        return False


@dataclass(frozen=True)
class CandidateSummary:
    """list 的只读行（确定性排序，不含逐题内容）。"""

    archive_dir: str
    state: str
    baseline_id: str
    run_id: str
    suite: str
    quality_status: str
    threshold_met: bool
    verified: bool
    missing_evidence_cases: int
    unknown_total: int

    @property
    def publishable(self) -> bool:
        return False

    @property
    def release_baseline(self) -> bool:
        return False


@dataclass(frozen=True)
class CandidateDiff:
    """两个候选归档的只读差异；分数永不求和/合并。"""

    left_dir: str
    right_dir: str
    state_left: str
    state_right: str
    same_identity: bool
    same_run: bool
    same_round: bool
    identity_changes: tuple[tuple[str, str, str], ...]
    quality_changes: tuple[tuple[str, Any, Any], ...]
    evidence_changes: tuple[tuple[str, Any, Any], ...]
    files_added: tuple[str, ...]
    files_removed: tuple[str, ...]
    files_changed: tuple[str, ...]
    scores_comparable: bool
    scores_reason: str
    score_merge_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_dir": self.left_dir,
            "right_dir": self.right_dir,
            "state_left": self.state_left,
            "state_right": self.state_right,
            "same_identity": self.same_identity,
            "same_run": self.same_run,
            "same_round": self.same_round,
            "identity_changes": [list(item) for item in self.identity_changes],
            "quality_changes": [list(item) for item in self.quality_changes],
            "evidence_changes": [list(item) for item in self.evidence_changes],
            "files_added": list(self.files_added),
            "files_removed": list(self.files_removed),
            "files_changed": list(self.files_changed),
            "scores_comparable": self.scores_comparable,
            "scores_reason": self.scores_reason,
            "score_merge_allowed": self.score_merge_allowed,
        }


def _resolved_protected_roots(extra: Sequence[Path | str] | None) -> tuple[Path, ...]:
    roots = [Path(item).resolve() for item in (*FORMAL_BASELINE_ROOTS, *PROTECTED_EVIDENCE_ROOTS)]
    if extra:
        roots.extend(Path(item).resolve() for item in extra)
    return tuple(dict.fromkeys(roots))


def _reject_protected_target(path: Path | str, roots: Sequence[Path], *, label: str) -> None:
    target = Path(path).resolve()
    for root in roots:
        if target == root or root in target.parents:
            raise CandidateArchiveError(
                f"{label}位于正式 registry 或受保护证据/报告目录内，拒绝写入: "
                f"{target}（保护根 {root}）"
            )


def _is_reparse(path: Path) -> bool:
    """符号链接或 Windows junction（两者都视为重解析点，归档内不允许）。"""
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    return bool(checker()) if callable(checker) else False


def _candidate_manifest_paths(disk_root: Path) -> set[str]:
    found: set[str] = set()
    for path in disk_root.rglob("*"):
        if _is_reparse(path):
            raise CandidateArchiveError(f"候选归档不允许符号链接/重解析点: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise CandidateArchiveError(f"候选归档包含非普通文件: {path}")
        found.add(path.relative_to(disk_root).as_posix())
    return found


def _validate_payload_rel(rel: str) -> None:
    if not isinstance(rel, str) or not rel.startswith(f"{CANDIDATE_PAYLOAD_DIR}/"):
        raise CandidateArchiveError(
            f"candidate_manifest.payload.files 路径必须位于 {CANDIDATE_PAYLOAD_DIR}/ 下: {rel!r}"
        )
    if "\\" in rel or ":" in rel:
        raise CandidateArchiveError(
            f"candidate_manifest.payload.files 必须是相对 POSIX 路径: {rel!r}"
        )
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise CandidateArchiveError(
            f"candidate_manifest.payload.files 路径非法（逃逸/空段）: {rel!r}"
        )


def _load_candidate_manifest_impl(
    archive_dir: Path,
) -> tuple[dict[str, Any], dict[str, str], SplitReport]:
    manifest_path = archive_dir / CANDIDATE_FILENAME
    if not manifest_path.is_file():
        raise CandidateArchiveError(f"候选归档缺少 {CANDIDATE_FILENAME}: {archive_dir}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateArchiveError(
            f"{CANDIDATE_FILENAME} 不是合法 UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CandidateArchiveError(f"{CANDIDATE_FILENAME} 必须是 JSON 对象")
    keys = set(payload)
    if keys != CANDIDATE_MANIFEST_KEYS:
        raise CandidateArchiveError(
            "candidate_manifest 字段集合不符（缺 "
            f"{sorted(CANDIDATE_MANIFEST_KEYS - keys)}；多 {sorted(keys - CANDIDATE_MANIFEST_KEYS)}）；"
            "候选归档字段结构固定，不接受额外发布字段"
        )
    if payload.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise CandidateArchiveError(
            f"候选归档 schema_version 不兼容: {payload.get('schema_version')!r}"
        )
    if payload.get("tool") != CANDIDATE_TOOL:
        raise CandidateArchiveError("candidate_manifest.tool 不匹配")
    _require_text(payload.get("archived_at"), "candidate_manifest.archived_at")
    state = payload.get("state")
    if state not in CANDIDATE_STATES:
        raise CandidateArchiveError(
            f"candidate_manifest.state 必须是 {list(CANDIDATE_STATES)} 之一，收到 {state!r}"
        )
    for name in ("publishable", "release_baseline", "gate_approved"):
        if payload.get(name) is not False:
            raise CandidateArchiveError(
                f"candidate_manifest.{name} 必须为 false（candidate/blocked 不可发布）"
            )
    if payload.get("has_approval") is not False:
        raise CandidateArchiveError(
            "candidate_manifest.has_approval 必须为 false（候选归档不携带审批、不冒充 approved）"
        )
    _require_text(payload.get("reason"), "candidate_manifest.reason")
    baseline_id = _require_text(payload.get("baseline_id"), "candidate_manifest.baseline_id")
    if not _IDENTITY_PATTERN.fullmatch(baseline_id):
        raise CandidateArchiveError(
            f"candidate_manifest.baseline_id 必须是 12 位小写十六进制，收到 {baseline_id!r}"
        )
    _require_text(payload.get("run_id"), "candidate_manifest.run_id")
    _require_text(payload.get("suite"), "candidate_manifest.suite")
    identity = BaselineIdentity.from_dict(
        _require_mapping(payload.get("identity"), "candidate_manifest.identity")
    )
    if identity.baseline_id != baseline_id:
        raise CandidateArchiveError(
            "candidate_manifest.identity 不能重算出 baseline_id（身份被篡改）"
        )
    raw_payload = _require_mapping(payload.get("payload"), "candidate_manifest.payload")
    if set(raw_payload) != {"dir", "schema_version", "files"}:
        raise CandidateArchiveError("candidate_manifest.payload 字段集合不符")
    if raw_payload.get("dir") != CANDIDATE_PAYLOAD_DIR:
        raise CandidateArchiveError(
            f"candidate_manifest.payload.dir 必须是 {CANDIDATE_PAYLOAD_DIR!r}"
        )
    if raw_payload.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
        raise CandidateArchiveError("candidate_manifest.payload.schema_version 与内层归档不兼容")
    raw_files = _require_mapping(raw_payload.get("files"), "candidate_manifest.payload.files")
    if not raw_files:
        raise CandidateArchiveError("candidate_manifest.payload.files 必须是非空对象")
    files: dict[str, str] = {}
    for rel, sha in raw_files.items():
        _validate_payload_rel(rel)
        if not isinstance(sha, str) or not _SHA256_PATTERN.fullmatch(sha):
            raise CandidateArchiveError(
                f"candidate_manifest.payload.files[{rel!r}] sha256 非法: {sha!r}"
            )
        files[rel] = sha
    try:
        report = SplitReport.from_dict(
            _require_mapping(payload.get("report"), "candidate_manifest.report")
        )
    except CandidateReportError as exc:
        raise CandidateArchiveError(f"candidate_manifest.report 被拒绝: {exc}") from exc
    report_sha = payload.get("report_sha256")
    if not isinstance(report_sha, str) or not _SHA256_PATTERN.fullmatch(report_sha):
        raise CandidateArchiveError("candidate_manifest.report_sha256 非法")
    if _canonical_sha(report.to_dict()) != report_sha:
        raise CandidateArchiveError("candidate_manifest.report 摘要漂移（report_sha256 不符）")
    source = _require_mapping(payload.get("source"), "candidate_manifest.source")
    if set(source) != {"baseline_dir", "run_dir"}:
        raise CandidateArchiveError("candidate_manifest.source 字段集合不符")
    _require_text(source.get("baseline_dir"), "candidate_manifest.source.baseline_dir")
    _require_text(source.get("run_dir"), "candidate_manifest.source.run_dir")
    _require_text(payload.get("note"), "candidate_manifest.note")
    return dict(payload), files, report


def _load_candidate_manifest(
    archive_dir: Path,
) -> tuple[dict[str, Any], dict[str, str], SplitReport]:
    """只把报告层的校验错误统一成候选归档错误，保持 fail-closed 的错误类型一致。"""
    try:
        return _load_candidate_manifest_impl(archive_dir)
    except (CandidateReportError, BaselineError) as exc:
        raise CandidateArchiveError(f"candidate_manifest 不合法: {exc}") from exc


def verify_candidate_archive(archive_dir: Path | str) -> CandidateArchive:
    """只读校验候选归档：manifest 结构 / payload 摘要 / 内层证据链 / 状态一致性。"""
    target = Path(archive_dir)
    if _is_reparse(target):
        raise CandidateArchiveError(f"候选归档目录本身是符号链接/重解析点，拒绝: {target}")
    if not target.is_dir():
        raise CandidateArchiveError(f"候选归档目录不存在: {target}")
    payload, declared_files, report = _load_candidate_manifest(target)

    payload_dir = target / CANDIDATE_PAYLOAD_DIR
    if _is_reparse(payload_dir) or not payload_dir.is_dir():
        raise CandidateArchiveError(
            f"candidate_manifest.payload.dir 不是普通目录，拒绝: {payload_dir}"
        )

    expected_files = {CANDIDATE_FILENAME, *declared_files}
    disk_files = _candidate_manifest_paths(target)
    if disk_files != expected_files:
        raise CandidateArchiveError(
            "候选归档文件集合不符（缺 "
            f"{sorted(expected_files - disk_files)}；多 {sorted(disk_files - expected_files)}）"
        )
    for rel, expected_sha in declared_files.items():
        try:
            data = (target / rel).read_bytes()
        except OSError as exc:
            raise CandidateArchiveError(
                f"候选归档 payload 文件缺失/不可读 {rel}: {exc}"
            ) from exc
        if hashlib.sha256(data).hexdigest() != expected_sha:
            raise CandidateArchiveError(
                f"候选归档 payload 文件 {rel} sha256 与清单不符（被改写）"
            )

    try:
        inner: BaselineArchive = verify_archive(payload_dir)
    except BaselineError as exc:
        raise CandidateArchiveError(f"候选归档 payload 未通过既有证据链校验: {exc}") from exc

    expected_payload = {f"{CANDIDATE_PAYLOAD_DIR}/{rel}": sha for rel, sha in inner.files.items()}
    expected_payload[f"{CANDIDATE_PAYLOAD_DIR}/{ARCHIVE_MANIFEST_FILENAME}"] = _sha256_file(
        payload_dir / ARCHIVE_MANIFEST_FILENAME
    )
    if declared_files != expected_payload:
        raise CandidateArchiveError(
            "candidate_manifest.payload.files 与内层 archive_manifest 不一致（摘要漂移）"
        )

    if inner.has_approval:
        raise CandidateArchiveError("候选归档 payload 携带 approval.json，拒绝（候选不可发布）")
    if inner.baseline_id != payload["baseline_id"]:
        raise CandidateArchiveError("candidate_manifest.baseline_id 与内层归档不一致")
    if inner.run_id != payload["run_id"]:
        raise CandidateArchiveError("candidate_manifest.run_id 与内层归档不一致")
    if inner.suite != payload["suite"]:
        raise CandidateArchiveError("candidate_manifest.suite 与内层归档不一致")
    try:
        manifest_identity = BaselineIdentity.from_dict(payload["identity"])
    except BaselineError as exc:
        raise CandidateArchiveError(f"candidate_manifest.identity 非法: {exc}") from exc
    if inner.identity != manifest_identity:
        raise CandidateArchiveError("candidate_manifest.identity 与内层归档身份不一致")
    derived = candidate_state_for_report(report)
    if derived != payload["state"]:
        raise CandidateArchiveError(
            f"candidate_manifest.state={payload['state']!r} 与报告事实派生状态 {derived!r} "
            "不一致（改元数据不能把 blocked 抬升成 candidate）"
        )
    return CandidateArchive(
        archive_dir=str(target),
        state=str(payload["state"]),
        archived_at=str(payload["archived_at"]),
        baseline_id=str(payload["baseline_id"]),
        run_id=str(payload["run_id"]),
        suite=str(payload["suite"]),
        identity=inner.identity,
        report=report,
        files=dict(declared_files),
        source_baseline_dir=str(payload["source"]["baseline_dir"]),
        source_run_dir=str(payload["source"]["run_dir"]),
    )


def _publish_staging(staging: Path, target: Path) -> None:
    last: OSError | None = None
    for attempt in range(3):
        try:
            staging.rename(target)
            return
        except PermissionError as exc:  # Windows 索引器/杀软短暂占用
            last = exc
            if attempt < 2:
                time.sleep(0.05)
    raise CandidateArchiveError(f"候选归档上架失败（目标未创建）: {target}: {last}") from last


def archive_candidate(
    *,
    baseline_id_value: str,
    root: Path | str,
    out_dir: Path | str,
    report: SplitReport,
    reason: str,
    archived_at: str | None = None,
    extra_formal_roots: Sequence[Path | str] | None = None,
) -> CandidateArchive:
    """把**未审批** baseline 的证据链 + 分列报告归档为 candidate/blocked。

    状态由 :func:`candidate_state_for_report` 派生；归档里没有 approval.json，也不写
    正式 registry。目标已存在、源已审批、holdout、受保护目录一律拒绝。
    """
    if not isinstance(report, SplitReport):
        raise CandidateArchiveError(f"report 必须是 SplitReport，收到 {type(report).__name__}")
    if not isinstance(reason, str) or not reason.strip():
        raise CandidateArchiveError("candidate reason 必须是非空字符串")
    out = Path(out_dir)
    roots = _resolved_protected_roots(extra_formal_roots)
    _reject_protected_target(out, roots, label="候选归档目标")
    if out.exists():
        raise CandidateArchiveError(f"候选归档目标已存在，拒绝覆盖: {out}")
    try:
        baseline = load_baseline(baseline_id_value, root)
    except BaselineError as exc:
        raise CandidateArchiveError(f"候选归档源 baseline 不可用: {exc}") from exc
    if baseline.approval is not None:
        raise CandidateArchiveError(
            "候选归档源 baseline 已审批：candidate/blocked 只能归档未审批证据，"
            "不得把审批状态带入候选（拒绝冒充 release baseline）"
        )
    if baseline.suite == HOLDOUT_SUITE:
        raise CandidateArchiveError("holdout suite 拒绝进入候选归档（不得导出逐题/标签）")

    parent = out.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CandidateArchiveError(f"候选归档父目录不可创建 {parent}: {exc}") from exc
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging-", dir=str(parent)))
    try:
        payload_dir = staging / CANDIDATE_PAYLOAD_DIR
        try:
            inner = archive_baseline(baseline.baseline_id, root, payload_dir)
        except BaselineError as exc:
            raise CandidateArchiveError(f"候选归档 payload 被既有证据链拒绝: {exc}") from exc
        if inner.has_approval:
            raise CandidateArchiveError("候选归档 payload 出现 approval.json，拒绝")
        payload_files = {
            f"{CANDIDATE_PAYLOAD_DIR}/{rel}": sha for rel, sha in inner.files.items()
        }
        payload_files[f"{CANDIDATE_PAYLOAD_DIR}/{ARCHIVE_MANIFEST_FILENAME}"] = _sha256_file(
            payload_dir / ARCHIVE_MANIFEST_FILENAME
        )
        report_payload = report.to_dict()
        manifest = {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "tool": CANDIDATE_TOOL,
            "archived_at": archived_at or _utc_now(),
            "state": candidate_state_for_report(report),
            "publishable": False,
            "release_baseline": False,
            "gate_approved": False,
            "reason": reason,
            "baseline_id": baseline.baseline_id,
            "run_id": baseline.run_id,
            "suite": baseline.suite,
            "identity": baseline.identity.to_dict(),
            "has_approval": False,
            "payload": {
                "dir": CANDIDATE_PAYLOAD_DIR,
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "files": payload_files,
            },
            "report": report_payload,
            "report_sha256": _canonical_sha(report_payload),
            "source": {
                "baseline_dir": str(Path(root) / baseline.baseline_id),
                "run_dir": str(baseline.run_dir),
            },
            "note": (
                "candidate/blocked 归档只移植证据与分列报告；不写 approval、不写正式 registry、"
                "不把候选标成 production/release ready；恢复出的 baseline 永远未审批。"
            ),
        }
        _write_json(staging / CANDIDATE_FILENAME, manifest)
        verified = verify_candidate_archive(staging)
        _publish_staging(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return replace(verified, archive_dir=str(out))


def restore_candidate(
    archive_dir: Path | str,
    root: Path | str,
    *,
    runs_root: Path | str | None = None,
    extra_formal_roots: Sequence[Path | str] | None = None,
) -> CandidateRestoreResult:
    """把候选归档恢复到**新的隔离根**；拒绝正式 registry / 归档内部 / 已存在目标。"""
    archive = verify_candidate_archive(archive_dir)
    payload_dir = Path(archive_dir) / CANDIDATE_PAYLOAD_DIR
    roots = _resolved_protected_roots(extra_formal_roots)
    archive_resolved = Path(archive_dir).resolve()
    targets: list[tuple[Path, str]] = [(Path(root), "候选恢复目标根")]
    if runs_root is not None:
        targets.append((Path(runs_root), "候选恢复 runs 根"))
    for path, label in targets:
        _reject_protected_target(path, roots, label=label)
        resolved = path.resolve()
        if resolved == archive_resolved or archive_resolved in resolved.parents:
            raise CandidateArchiveError(
                f"{label}不能位于源归档目录内部（归档只读）: {resolved}"
            )
    try:
        result = restore_baseline(payload_dir, root, runs_root=runs_root)
    except BaselineError as exc:
        raise CandidateArchiveError(f"候选归档恢复被既有证据链拒绝: {exc}") from exc
    try:
        if result.baseline.approval is not None:
            raise CandidateArchiveError("恢复出的 candidate baseline 出现审批，拒绝（候选不可发布）")
        if (Path(result.baseline_dir) / APPROVAL_FILENAME).exists():
            raise CandidateArchiveError("恢复目录出现 approval.json，拒绝（候选不可发布）")
        if result.baseline.identity != archive.identity:
            raise CandidateArchiveError("恢复出的 candidate 身份与归档不一致")
        if result.baseline.run_id != archive.run_id:
            raise CandidateArchiveError("恢复出的 candidate run_id 与归档不一致")
    except CandidateArchiveError:
        shutil.rmtree(result.baseline_dir, ignore_errors=True)
        shutil.rmtree(result.run_dir, ignore_errors=True)
        raise
    return CandidateRestoreResult(
        archive=archive,
        baseline=result.baseline,
        baseline_dir=result.baseline_dir,
        run_dir=result.run_dir,
        files=result.files,
    )


def list_candidates(root: Path | str) -> tuple[CandidateSummary, ...]:
    """只读列出 root 下所有候选归档（逐个 verify，按 archive_dir 确定性排序）。"""
    root_path = Path(root)
    if not root_path.is_dir():
        raise CandidateArchiveError(f"候选归档根不存在或不是目录: {root_path}")
    summaries: list[CandidateSummary] = []
    for child in sorted(root_path.iterdir()):
        if not child.is_dir() or not (child / CANDIDATE_FILENAME).is_file():
            continue
        archive = verify_candidate_archive(child)
        summaries.append(
            CandidateSummary(
                archive_dir=str(child),
                state=archive.state,
                baseline_id=archive.baseline_id,
                run_id=archive.run_id,
                suite=archive.suite,
                quality_status=archive.report.quality.status,
                threshold_met=archive.report.quality.threshold_met,
                verified=archive.report.quality.verified,
                missing_evidence_cases=archive.report.evidence.missing_evidence_cases,
                unknown_total=archive.report.evidence.unknown_total,
            )
        )
    summaries.sort(key=lambda item: item.archive_dir)
    return tuple(summaries)


def _changed_fields(
    left: Mapping[str, Any], right: Mapping[str, Any], keys: Sequence[str]
) -> tuple[tuple[str, Any, Any], ...]:
    changes: list[tuple[str, Any, Any]] = []
    for key in keys:
        if left.get(key) != right.get(key):
            changes.append((key, left.get(key), right.get(key)))
    return tuple(changes)


def diff_candidates(left: Path | str, right: Path | str) -> CandidateDiff:
    """只读 diff 两个候选归档；跨轮只标不可比，任何情况下都不允许分数合并。"""
    left_archive = verify_candidate_archive(left)
    right_archive = verify_candidate_archive(right)
    left_identity = left_archive.identity.to_dict()
    right_identity = right_archive.identity.to_dict()
    identity_changes = tuple(
        (name, left_identity[name], right_identity[name])
        for name in left_identity
        if left_identity[name] != right_identity[name]
    )
    left_files = dict(left_archive.files)
    right_files = dict(right_archive.files)
    files_added = tuple(sorted(set(right_files) - set(left_files)))
    files_removed = tuple(sorted(set(left_files) - set(right_files)))
    files_changed = tuple(
        sorted(
            rel
            for rel in set(left_files) & set(right_files)
            if left_files[rel] != right_files[rel]
        )
    )
    quality_keys = (
        "total",
        "passed",
        "failed",
        "errors",
        "safety_violations",
        "min_pass",
        "threshold_met",
        "thresholds_approved",
        "verified",
        "release_ready",
        "status",
        "scenario_verifications",
    )
    evidence_keys = (
        "total",
        "missing_evidence_cases",
        "verified",
        "unknown_total",
        "violation_total",
        "axes",
    )
    same_round = left_archive.report.execution.round_id == right_archive.report.execution.round_id
    same_identity = left_archive.identity == right_archive.identity
    scores_comparable = same_round and same_identity
    if not same_round:
        scores_reason = "跨轮分数不得合并（不同 round_id，只能分别看）"
    elif not same_identity:
        scores_reason = (
            "跨 pipeline/scope/dataset 身份的结果不可比（identity 六要素不同），"
            "不得拼接或求和"
        )
    else:
        scores_reason = "同一 round 且身份一致：可对比差异，但分数仍不得求和/合并"
    return CandidateDiff(
        left_dir=str(Path(left)),
        right_dir=str(Path(right)),
        state_left=left_archive.state,
        state_right=right_archive.state,
        same_identity=same_identity,
        same_run=left_archive.run_id == right_archive.run_id,
        same_round=same_round,
        identity_changes=identity_changes,
        quality_changes=_changed_fields(
            left_archive.report.quality.to_dict(),
            right_archive.report.quality.to_dict(),
            quality_keys,
        ),
        evidence_changes=_changed_fields(
            left_archive.report.evidence.to_dict(),
            right_archive.report.evidence.to_dict(),
            evidence_keys,
        ),
        files_added=files_added,
        files_removed=files_removed,
        files_changed=files_changed,
        scores_comparable=scores_comparable,
        scores_reason=scores_reason,
        score_merge_allowed=False,
    )
