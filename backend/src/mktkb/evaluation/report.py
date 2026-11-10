"""T007：run diff 与 Markdown / HTML 报告（设计 §8.3 / §8.5；P0 计划 Task 6 Step 4）。

**diff 口径**：

- ``new_failures`` / ``fixed_failures`` / ``still_failing`` 只看 ``status="fail"``，按
  ``case_id`` 排序；``status="error"`` 单独列（不混入失败集，也不当通过）；
- 指标差按 ``stratum`` + ``all`` 两组维度计算，复用 gate 的观测口径（检索=有 gold 且
  非 OCR；答案=scored 且非 OCR/error；拒答=适用样本；运行=有延迟/成本样本）。分母与
  ``dataset_sample`` 原样保留；``observed is None`` 一律 ``unknown``，**不补零**；
- 完全相同的两轮 run：new / fixed / status_changes 全为空列表，不抛异常（``empty``）；
- 放行资格：只有**同 ``pipeline_version``** 且 baseline 已审批的
  ``comparison="release_baseline"`` 才是 ``release_allowed=True``；
  ``comparison="explicit_cross_version"`` 只用于分析，``require_release_baseline`` 拒绝。

**发布放行证据链（P1 #59 修复；``release_allowed=True`` 的必要条件）**：

- ``comparison="release_baseline"`` 且非跨 ``pipeline_version``；
- current gate 结果**非空**并绑定**当前 run**（``run_id`` / ``suite`` / ``mode`` 与
  ``run.manifest`` 一致）、``exit_code=0``、``gate_version`` 与当前配置一致；
- current gate 的质量层 ``gate_config_hash`` == 当前配置 ``config_hash``
  （**同 ``gate_version`` 但阈值内容变化** → 旧 gate 结果不得复用）；
- baseline 的 ``approval`` 与 ``gate`` 快照都非空，且 ``approval.gate_result_sha256``
  绑定同一份门禁结果（``Baseline.__post_init__`` 已校验）；
- **审批时刻**的配置内容哈希 == 当前配置 ``config_hash``：旧 schema 的门禁快照没有
  config 哈希，此时从 ``baseline.run_dir/gate.json`` 重核——其 canonical JSON 的
  SHA-256 必须等于审批绑定的 ``gate_result_sha256``，再取其中的
  ``quality.gate_config_hash``；文件缺失 / 摘要不一致一律 fail closed
  （``baseline_gate_config_unverifiable``），**审批后阈值内容漂移**
  （``baseline_gate_config_drift``）直接拒绝。

任一条件不满足 → ``release_allowed=False`` 且 ``release_blocked_reason`` 给出稳定原因码
（``current_gate_missing`` / ``current_gate_run_mismatch`` / ``current_gate_exit_<n>`` /
``gate_config_drift`` / ``baseline_unapproved`` / ``baseline_gate_missing`` /
``baseline_gate_config_drift`` / ``explicit_cross_version_analysis_only`` 等）；
``RunDiff`` / ``RunDiff.to_dict()`` 的字段结构不变，只新增该字段的取值。

**配置更新后的规则**：gate 配置内容（阈值 / ``min_sample`` / ``status`` 等任意字节级
内容）一变，``config_hash`` 就变；旧的 gate 结果与旧审批只证明“旧配置下的通过”，不得
复用。必须按新配置重新 ``gate`` 评估并重新审批 baseline——即使 ``gate_version`` 字符串
没变也一样。

**报告口径**（设计 §8.5）：

- ``render_markdown`` / ``render_html`` 都由同一份 :func:`_report_data` 渲染，保证
  同源同数据；首段固定是硬门禁结果（置顶）；
- HTML **单文件**：内联 CSS、无 ``<script>``、无 http(s) / ``src=`` / ``href=`` 外部资源，
  无服务依赖；
- 两个渲染器都是纯函数：不写文件、不参与门禁判定，``report.html`` 不被 gate 读取；
- Diff 表的 ``regressed`` / ``improved`` 只是**数值方向**（按 ``direction``），不是质量/
  门禁状态；阈值判定看质量层，缺已审批阈值时仍是 ``unknown``；
- 阈值未审批（T009 人工门）、``quality=False`` 的 exit 0、``cost_per_case_cny`` 零样本、
  ``p95_latency_ms`` 无 SLA 都在报告里显式标 unknown / 未评估，绝不写成通过或 0。
"""

from __future__ import annotations

import hashlib
import html as _html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .baseline import (
    Baseline,
    BaselineComparabilityError,
    BaselineIdentity,
    CrossVersionBaselineError,
    _ensure_comparable,
    baseline_identity,
)
from .dataset import CaseSpec, load_cases
from .gate import (
    DEFAULT_GATE_CONFIG_PATH,
    FROZEN_DATASET_DIR,
    GateConfig,
    GateResult,
    QUALITY_ALL_STRATUM,
    _quality_observations,
    _summary_payload,
    load_gate_config,
)
from .runner import RunResult

__all__ = [
    "COMPARISON_ANALYSIS",
    "COMPARISON_CROSS_VERSION",
    "COMPARISON_RELEASE",
    "DiffResult",
    "MetricDelta",
    "RunDiff",
    "diff_runs",
    "render_html",
    "render_markdown",
    "require_release_baseline",
]

COMPARISON_RELEASE = "release_baseline"
COMPARISON_CROSS_VERSION = "explicit_cross_version"
COMPARISON_ANALYSIS = "analysis"

_EXIT_LABELS: dict[int, str] = {
    0: "通过",
    1: "硬门禁失败",
    2: "质量回退",
    3: "不可判定",
    4: "live 未授权",
}
_STATUS_ORDER = {"regressed": 0, "improved": 1, "unchanged": 2, "unknown": 3}

#: 报告口径声明（与 T005/T006a/T006b 分母一致；实际分母见质量表）。
_DENOMINATOR_RULES: tuple[str, ...] = (
    "检索指标：有 gold 且非 OCR 的 case（P0 真实口径 b0=32 / badcase=10）",
    "答案指标：status ∈ {pass,fail} 且非 OCR、非 error 的 case（P0 真实口径 b0=32 / badcase=13）",
    "拒答指标：适用样本，排除 error / service_error / knowledge_changed",
    "运行指标：有延迟 / 成本数据的行；OCR 与 error 行一律排除",
)


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MetricDelta:
    """一个指标在一个 stratum 上的 baseline/current 观测差（不参与门禁判定）。

    ``status`` 只是**数值方向**：``regressed`` / ``improved`` 表示数值按 ``direction``
    变差/变好，不是质量或门禁状态；阈值判定属于质量层（无已审批阈值时仍是 ``unknown``）。
    """

    metric: str
    group: str
    stratum: str
    direction: str
    baseline: float | None
    current: float | None
    delta: float | None
    delta_pp: float | None
    status: str
    reason: str | None
    baseline_denominator: int
    current_denominator: int
    baseline_dataset_sample: int
    current_dataset_sample: int
    denominator_basis: str
    threshold_configured: bool
    notes: tuple[str, ...] = ()

    @property
    def baseline_value(self) -> float | None:
        return self.baseline

    @property
    def current_value(self) -> float | None:
        return self.current

    @property
    def known(self) -> bool:
        return self.status != "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "group": self.group,
            "stratum": self.stratum,
            "direction": self.direction,
            "baseline": self.baseline,
            "current": self.current,
            "delta": self.delta,
            "delta_pp": self.delta_pp,
            "status": self.status,
            "reason": self.reason,
            "baseline_denominator": self.baseline_denominator,
            "current_denominator": self.current_denominator,
            "baseline_dataset_sample": self.baseline_dataset_sample,
            "current_dataset_sample": self.current_dataset_sample,
            "denominator_basis": self.denominator_basis,
            "threshold_configured": self.threshold_configured,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RunDiff:
    """两轮 run 的差异；``empty=True`` 表示没有任何失败/状态/指标变化。"""

    baseline_id: str
    baseline_run_id: str
    run_id: str
    baseline_pipeline_version: str
    pipeline_version: str
    suite: str
    mode: str
    scope: str
    comparison: str
    release_allowed: bool
    release_blocked_reason: str | None
    baseline_exit_code: int | None
    current_exit_code: int | None
    baseline_quality_status: str | None
    current_quality_status: str | None
    gate_exit_transition: str
    gate_exit_changed: bool | None
    strata: tuple[str, ...]
    new_failures: tuple[str, ...]
    fixed_failures: tuple[str, ...]
    still_failing: tuple[str, ...]
    new_errors: tuple[str, ...]
    resolved_errors: tuple[str, ...]
    persistent_errors: tuple[str, ...]
    status_changes: tuple[Mapping[str, str], ...]
    metric_deltas: tuple[MetricDelta, ...]
    config_status: str
    gate_config_hash: str
    warnings: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return (
            not self.new_failures
            and not self.fixed_failures
            and not self.new_errors
            and not self.resolved_errors
            and not self.status_changes
            and all(item.status in {"unchanged", "unknown"} for item in self.metric_deltas)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "baseline_run_id": self.baseline_run_id,
            "run_id": self.run_id,
            "baseline_pipeline_version": self.baseline_pipeline_version,
            "pipeline_version": self.pipeline_version,
            "suite": self.suite,
            "mode": self.mode,
            "scope": self.scope,
            "comparison": self.comparison,
            "release_allowed": self.release_allowed,
            "release_blocked_reason": self.release_blocked_reason,
            "baseline_exit_code": self.baseline_exit_code,
            "current_exit_code": self.current_exit_code,
            "baseline_quality_status": self.baseline_quality_status,
            "current_quality_status": self.current_quality_status,
            "gate_exit_transition": self.gate_exit_transition,
            "gate_exit_changed": self.gate_exit_changed,
            "strata": list(self.strata),
            "new_failures": list(self.new_failures),
            "fixed_failures": list(self.fixed_failures),
            "still_failing": list(self.still_failing),
            "new_errors": list(self.new_errors),
            "resolved_errors": list(self.resolved_errors),
            "persistent_errors": list(self.persistent_errors),
            "status_changes": [dict(item) for item in self.status_changes],
            "metric_deltas": [item.to_dict() for item in self.metric_deltas],
            "config_status": self.config_status,
            "gate_config_hash": self.gate_config_hash,
            "warnings": list(self.warnings),
            "empty": self.empty,
        }


#: 计划 Task 6 使用的名字；与 :class:`RunDiff` 同义。
DiffResult = RunDiff


# --------------------------------------------------------------------------- #
# diff
# --------------------------------------------------------------------------- #


def _run_dataset(run: RunResult, label: str) -> tuple[tuple[CaseSpec, ...], tuple[Mapping[str, Any], ...]]:
    manifest = run.manifest.to_dict()
    suite = str(manifest.get("suite") or "")
    raw_path = manifest.get("dataset_path")
    target = Path(str(raw_path)) if raw_path else FROZEN_DATASET_DIR / f"{suite}.jsonl"
    if not target.is_file():
        target = FROZEN_DATASET_DIR / f"{suite}.jsonl"
    if not target.is_file():
        raise BaselineComparabilityError(
            f"{label} 的数据集不可用（dataset_path={raw_path!r}，冻结目录回退也失败），"
            "无法按 stratum 计算指标差"
        )
    try:
        cases = tuple(load_cases(target))
    except (OSError, ValueError) as exc:
        raise BaselineComparabilityError(f"{label} 的数据集无法解析: {exc}") from exc
    rows = tuple(row for row in run.cases if isinstance(row, Mapping))
    if [case.case_id for case in cases] != [str(row.get("case_id") or "") for row in rows]:
        raise BaselineComparabilityError(
            f"{label} 的数据集 case 与 cases.jsonl 行不一致（集合/顺序），diff 不可比较"
        )
    return cases, rows


def _strata(cases: Sequence[CaseSpec]) -> tuple[str, ...]:
    levels = sorted(
        {case.stratum for case in cases if not (case.requires_ocr or case.stratum == "ocr")}
    )
    return (QUALITY_ALL_STRATUM, *levels)


def _observation_reason(observation: Any) -> str:
    if observation is None:
        return "metric_not_available"
    if getattr(observation, "problem", None):
        return str(observation.problem)
    if int(getattr(observation, "denominator", 0)) == 0:
        return "zero_sample"
    if getattr(observation, "observed", None) is None:
        return "observed_missing"
    return "unknown"


def _unknown_reason(left: Any, right: Any) -> str:
    reasons: list[str] = []
    if left is None or left.observed is None:
        reasons.append(f"baseline_{_observation_reason(left)}")
    if right is None or right.observed is None:
        reasons.append(f"current_{_observation_reason(right)}")
    return "+".join(dict.fromkeys(reasons)) or "unknown"


def _delta_status(spec: Any, left: Any, right: Any) -> tuple[float | None, str, str | None]:
    """返回 (差值, 方向状态, unknown 原因)；方向状态不是质量/门禁判定。"""
    if left is None or right is None or left.observed is None or right.observed is None:
        return None, "unknown", _unknown_reason(left, right)
    delta = float(right.observed) - float(left.observed)
    if abs(delta) <= 1e-12:
        return delta, "unchanged", None
    if spec.direction == "higher_is_better":
        return delta, ("improved" if delta > 0 else "regressed"), None
    return delta, ("improved" if delta < 0 else "regressed"), None


def _status_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {str(row.get("case_id") or ""): str(row.get("status") or "") for row in rows}


def _diff_with_rows(
    *,
    baseline: Baseline,
    run: RunResult,
    comparison: str,
    release_allowed: bool,
    release_blocked_reason: str | None,
    baseline_rows: Sequence[Mapping[str, Any]],
    current_rows: Sequence[Mapping[str, Any]],
    config: GateConfig,
    baseline_observations: Mapping[tuple[str, str], Any],
    current_observations: Mapping[tuple[str, str], Any],
    strata: tuple[str, ...],
    gate: GateResult | None,
    warnings: tuple[str, ...],
) -> RunDiff:
    base_status = _status_map(baseline_rows)
    cur_status = _status_map(current_rows)
    base_fail = {case_id for case_id, status in base_status.items() if status == "fail"}
    cur_fail = {case_id for case_id, status in cur_status.items() if status == "fail"}
    base_error = {case_id for case_id, status in base_status.items() if status == "error"}
    cur_error = {case_id for case_id, status in cur_status.items() if status == "error"}
    changes = tuple(
        {
            "case_id": case_id,
            "baseline_status": base_status.get(case_id, "absent"),
            "current_status": cur_status.get(case_id, "absent"),
        }
        for case_id in sorted(set(base_status) | set(cur_status))
        if base_status.get(case_id, "absent") != cur_status.get(case_id, "absent")
    )

    deltas: list[MetricDelta] = []
    for level in strata:
        for spec in config.metrics:
            left = baseline_observations.get((spec.name, level))
            right = current_observations.get((spec.name, level))
            value, status, reason = _delta_status(spec, left, right)
            delta_pp = None
            if value is not None and spec.group != "runtime":
                delta_pp = value * 100.0
            deltas.append(
                MetricDelta(
                    metric=spec.name,
                    group=spec.group,
                    stratum=level,
                    direction=spec.direction,
                    baseline=None if left is None else left.observed,
                    current=None if right is None else right.observed,
                    delta=value,
                    delta_pp=delta_pp,
                    status=status,
                    reason=reason,
                    baseline_denominator=0 if left is None else int(left.denominator),
                    current_denominator=0 if right is None else int(right.denominator),
                    baseline_dataset_sample=0 if left is None else int(left.dataset_sample),
                    current_dataset_sample=0 if right is None else int(right.dataset_sample),
                    denominator_basis=(
                        (left or right).basis if (left or right) is not None else "unknown"
                    ),
                    threshold_configured=any(
                        item is not None
                        for item in (
                            spec.absolute_min,
                            spec.absolute_max,
                            spec.max_regression_pp,
                        )
                    ),
                    notes=() if (left or right) is None else tuple((left or right).notes),
                )
            )

    baseline_exit = baseline.exit_code
    current_exit = None if gate is None else int(gate.exit_code)
    if baseline_exit is None or current_exit is None:
        transition = "unknown"
        changed: bool | None = None
    else:
        transition = f"{int(baseline_exit)}->{current_exit}"
        changed = int(baseline_exit) != current_exit

    baseline_quality = (
        baseline.gate.quality_status
        if baseline.gate is not None
        else (baseline.approval.quality_status if baseline.approval else None)
    )
    current_quality = None if gate is None else gate.quality_status

    return RunDiff(
        baseline_id=baseline.baseline_id,
        baseline_run_id=baseline.run_id,
        run_id=str(run.manifest.run_id),
        baseline_pipeline_version=baseline.identity.pipeline_version,
        pipeline_version=str(run.manifest.pipeline_version),
        suite=str(run.manifest.suite),
        mode=str(run.manifest.mode),
        scope=str(run.manifest.scope),
        comparison=comparison,
        release_allowed=release_allowed,
        release_blocked_reason=release_blocked_reason,
        baseline_exit_code=None if baseline_exit is None else int(baseline_exit),
        current_exit_code=current_exit,
        baseline_quality_status=baseline_quality,
        current_quality_status=current_quality,
        gate_exit_transition=transition,
        gate_exit_changed=changed,
        strata=strata,
        new_failures=tuple(sorted(cur_fail - base_fail)),
        fixed_failures=tuple(sorted(base_fail - cur_fail)),
        still_failing=tuple(sorted(base_fail & cur_fail)),
        new_errors=tuple(sorted(cur_error - base_error)),
        resolved_errors=tuple(sorted(base_error - cur_error)),
        persistent_errors=tuple(sorted(base_error & cur_error)),
        status_changes=changes,
        metric_deltas=tuple(deltas),
        config_status=str(config.status),
        gate_config_hash=str(config.config_hash),
        warnings=warnings,
    )


def _normalise_comparison(
    baseline: Baseline,
    current: BaselineIdentity,
    *,
    comparison: str | None,
    compare_with: str | None,
) -> str:
    cross = baseline.identity.pipeline_version != current.pipeline_version
    if cross:
        if comparison in {"release", COMPARISON_RELEASE}:
            raise CrossVersionBaselineError(
                "跨 pipeline_version 的对比不能作为 release 比较；"
                "只能显式 compare_with=<baseline_id> 用于分析（设计 §8.3）"
            )
        return COMPARISON_CROSS_VERSION
    if comparison in (None, "release", COMPARISON_RELEASE):
        return COMPARISON_RELEASE
    if comparison in {COMPARISON_ANALYSIS, COMPARISON_CROSS_VERSION}:
        return comparison
    raise ValueError(
        f"comparison 只允许 None / 'release' / {COMPARISON_RELEASE!r} / "
        f"{COMPARISON_ANALYSIS!r} / {COMPARISON_CROSS_VERSION!r}，收到 {comparison!r}"
    )


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    """与 ``baseline.gate_result_digest`` 同口径（这里只有 JSON 映射，没有 GateResult）。"""
    canonical = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _baseline_approved_config_hash(baseline: Baseline) -> tuple[str | None, str | None]:
    """重核**审批时刻**的 gate 配置内容哈希；返回 ``(config_hash, blocked_reason)``。

    证据链（fail closed）：

    1. baseline 门禁快照若已记录 ``gate_config_hash``（后续 schema）直接使用；
    2. 旧 schema 快照没有 config 哈希时，读 ``baseline.run_dir/gate.json``：其 canonical
       JSON 的 SHA-256 必须等于门禁快照的 ``gate_result_sha256``（即 approval 绑定的
       **具体一份**门禁结果），再从 ``quality.gate_config_hash`` 取配置哈希；文件缺失 /
       解析失败 / 摘要不一致一律视为不可证明，不得放行；
    3. 都拿不到 → ``baseline_gate_config_unverifiable``。

    这样“审批后阈值内容漂移”（``gate_version`` 不变但内容变了）与“审批证据缺失”都能
    被拒绝，且不需要改 ``baseline.py`` 的既有 schema。
    """
    gate = baseline.gate
    if gate is None:
        return None, "baseline_gate_missing"
    direct = getattr(gate, "gate_config_hash", "")
    if isinstance(direct, str) and direct.strip():
        return direct, None
    path = Path(baseline.run_dir) / "gate.json"
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "baseline_gate_config_unverifiable"
    if not isinstance(payload, Mapping):
        return None, "baseline_gate_config_unverifiable"
    if _canonical_json_sha256(payload) != str(gate.gate_result_sha256):
        return None, "baseline_gate_config_unverifiable"
    quality = payload.get("quality")
    if not isinstance(quality, Mapping):
        return None, "baseline_gate_config_unverifiable"
    value = quality.get("gate_config_hash")
    if not isinstance(value, str) or not value.strip():
        return None, "baseline_gate_config_unverifiable"
    return value, None


def _release_blocked_reason(
    baseline: Baseline,
    run: RunResult,
    *,
    comparison: str,
    config: GateConfig,
    gate: GateResult | None,
) -> str | None:
    """返回放行阻断原因码；``None`` 表示放行证据链完整。

    顺序按“最根本的阻断先报”：跨版本 → baseline 审批/快照 → 当前 gate 绑定与退出码 →
    配置内容一致性（当前 gate 与审批时刻）→ 对比方式。所有原因码都是稳定字符串，便于
    报告/CI 断言；新增原因码不需要改 ``RunDiff`` 字段结构。
    """
    if comparison == COMPARISON_CROSS_VERSION:
        return "explicit_cross_version_analysis_only"
    if baseline.approval is None:
        return "baseline_unapproved"
    if baseline.gate is None:
        return "baseline_gate_missing"
    if str(baseline.approval.gate_result_sha256) != str(baseline.gate.gate_result_sha256):
        return "baseline_approval_gate_mismatch"
    if gate is None:
        return "current_gate_missing"
    manifest = run.manifest
    if (
        str(gate.run_id) != str(manifest.run_id)
        or str(gate.suite) != str(manifest.suite)
        or str(gate.mode) != str(manifest.mode)
    ):
        return "current_gate_run_mismatch"
    if str(gate.gate_version) != str(config.gate_version):
        return "current_gate_gate_version_mismatch"
    exit_code = int(gate.exit_code)
    if exit_code != 0:
        return f"current_gate_exit_{exit_code}"
    if gate.quality is None:
        return "current_gate_quality_missing"
    if str(gate.quality.gate_config_hash) != str(config.config_hash):
        return "gate_config_drift"
    approved_hash, evidence_reason = _baseline_approved_config_hash(baseline)
    if evidence_reason is not None:
        return evidence_reason
    if approved_hash != str(config.config_hash):
        return "baseline_gate_config_drift"
    if comparison != COMPARISON_RELEASE:
        return "comparison_not_release"
    return None


def diff_runs(
    baseline: Baseline,
    run: RunResult,
    *,
    comparison: str | None = None,
    compare_with: str | None = None,
    config: GateConfig | None = None,
    gate: GateResult | None = None,
) -> RunDiff:
    """计算 baseline 与当前 run 的差异；跨版本默认拒绝，显式 ``compare_with`` 仅分析。

    参数顺序兼容 handoff §5.4 的 ``diff_runs(baseline, run)`` 与计划 Task 6 的
    ``diff_runs(run, baseline)``（按类型自动换位）。

    ``release_allowed`` 不是“同版本 + 已审批”这么弱：见模块 docstring 的放行证据链——
    还要求当前 gate 非空且绑定当前 run、``exit_code=0``、``gate_version`` / 质量层
    ``gate_config_hash`` 与**当前配置**一致、审批时刻的配置内容哈希与当前配置一致。
    任一不满足都 fail closed（``release_blocked_reason`` 为稳定原因码），绝不因缺 gate /
    旧 gate / 审批后配置漂移而放行。
    """
    if isinstance(baseline, RunResult) and isinstance(run, Baseline):
        baseline, run = run, baseline
    if not isinstance(baseline, Baseline):
        raise BaselineComparabilityError(
            f"diff_runs 需要 Baseline，收到 {type(baseline).__name__}"
        )
    if not isinstance(run, RunResult):
        raise BaselineComparabilityError(f"diff_runs 需要 RunResult，收到 {type(run).__name__}")

    current_identity = baseline_identity(run.manifest)
    _ensure_comparable(
        baseline.identity,
        current_identity,
        baseline_id_value=baseline.baseline_id,
        compare_with=compare_with,
    )
    comparison_value = _normalise_comparison(
        baseline, current_identity, comparison=comparison, compare_with=compare_with
    )

    resolved_config = config if config is not None else load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    if resolved_config.gate_version != baseline.identity.gate_version:
        raise BaselineComparabilityError(
            "gate 配置版本与 baseline 身份不一致："
            f"{resolved_config.gate_version!r} != {baseline.identity.gate_version!r}"
        )

    blocked = _release_blocked_reason(
        baseline,
        run,
        comparison=comparison_value,
        config=resolved_config,
        gate=gate,
    )
    release_allowed = blocked is None

    base_run = baseline.load_run()
    base_cases, base_rows = _run_dataset(base_run, "baseline")
    cur_cases, cur_rows = _run_dataset(run, "current")

    base_warnings: list[str] = []
    cur_warnings: list[str] = []
    base_summary, base_has = _summary_payload(base_run)
    cur_summary, cur_has = _summary_payload(run)
    base_observations = _quality_observations(
        resolved_config, base_cases, base_rows, base_summary, base_has, base_warnings
    )
    cur_observations = _quality_observations(
        resolved_config, cur_cases, cur_rows, cur_summary, cur_has, cur_warnings
    )
    warnings = (
        tuple(f"baseline: {item}" for item in base_warnings)
        + tuple(f"current: {item}" for item in cur_warnings)
    )
    strata = tuple(dict.fromkeys((*_strata(base_cases), *_strata(cur_cases))))
    strata = tuple(sorted(strata, key=lambda item: (item != QUALITY_ALL_STRATUM, item)))

    return _diff_with_rows(
        baseline=baseline,
        run=run,
        comparison=comparison_value,
        release_allowed=release_allowed,
        release_blocked_reason=blocked,
        baseline_rows=base_rows,
        current_rows=cur_rows,
        config=resolved_config,
        baseline_observations=base_observations,
        current_observations=cur_observations,
        strata=strata,
        gate=gate,
        warnings=warnings,
    )


def require_release_baseline(diff: RunDiff) -> None:
    """发布放行路径：只接受“当前 gate 绑定当前 run 且配置未漂移”的已审批同版本对比。

    放行证据链在 :func:`diff_runs` 里已逐项核验（当前 gate 非空且绑定当前 run、
    ``exit_code=0``、``gate_version`` / 质量层 ``gate_config_hash`` 与当前配置一致、
    审批时刻配置哈希与当前配置一致、baseline 审批绑定具体门禁结果、非跨版本）；
    ``release_allowed=False`` 时这里直接拒绝，并带上稳定原因码。
    """
    if not isinstance(diff, RunDiff):
        raise TypeError(f"require_release_baseline 只接受 RunDiff，收到 {type(diff).__name__}")
    if not diff.release_allowed:
        raise CrossVersionBaselineError(
            f"comparison={diff.comparison!r} 不能作为发布放行依据"
            f"（{diff.release_blocked_reason or 'unknown'}）；设计 §8.3：跨版本只分析、不放行"
        )
    if diff.current_exit_code is not None and diff.current_exit_code != 0:
        raise CrossVersionBaselineError(
            f"当前 run 门禁 exit_code={diff.current_exit_code}，不能放行"
        )


# --------------------------------------------------------------------------- #
# 报告数据（markdown 与 html 的唯一来源）
# --------------------------------------------------------------------------- #


def _fmt_value(value: float | None) -> str:
    return "unknown" if value is None else f"{float(value):.4f}"


def _fmt_delta(value: float | None, *, pp: bool = False) -> str:
    if value is None:
        return "unknown"
    return f"{float(value):+.2f}pp" if pp else f"{float(value):+.4f}"


def _join(values: Sequence[str]) -> str:
    return "、".join(values) if values else "无"


def _report_data(
    summary: Mapping[str, Any] | None,
    diff: RunDiff,
    gate: GateResult | None,
) -> dict[str, Any]:
    if not isinstance(diff, RunDiff):
        raise TypeError(f"报告需要 RunDiff，收到 {type(diff).__name__}")

    if gate is None:
        hard_gate = {
            "available": False,
            "exit_code": None,
            "exit_label": "unknown（未提供门禁结果，不冒充通过）",
            "quality_note": None,
            "status_rows": [],
            "failures": [],
            "unknowns": [],
            "unknown_count": 0,
            "not_applicable_count": 0,
        }
    else:
        quality_note = None
        if gate.quality is None:
            quality_note = (
                "质量层未评估（quality=False）：exit_code=0 只代表硬门禁通过，"
                "不代表质量达标（T006b 约束 4）"
            )
        hard_gate = {
            "available": True,
            "exit_code": gate.exit_code,
            "exit_label": _EXIT_LABELS.get(gate.exit_code, "未知状态"),
            "quality_note": quality_note,
            "status_rows": [
                {"gate_id": str(key), "status": str(value)}
                for key, value in gate.gate_status.items()
            ],
            "failures": [
                {
                    "gate_id": item.gate_id,
                    "case_id": item.case_id or "-",
                    "check_id": item.check_id or "-",
                }
                for item in gate.failures
            ],
            "unknowns": [
                {
                    "gate_id": item.gate_id,
                    "check_id": item.check_id or "-",
                    "reason": item.reason,
                }
                for item in gate.unknowns
            ],
            "unknown_count": len(gate.unknowns),
            "not_applicable_count": len(gate.not_applicable),
        }

    quality: dict[str, Any]
    if gate is None or gate.quality is None:
        quality = {
            "available": False,
            "status": "not_evaluated",
            "config_status": "unknown",
            "note": "质量层未评估（quality=False）：不得写成质量通过",
            "min_sample_hint": None,
            "rows": [],
            "failures": [],
        }
    else:
        note = None
        if str(gate.quality.config_status) != "approved":
            note = (
                f"阈值未审批（thresholds_unapproved，config_status={gate.quality.config_status}，"
                "T009 人工门）：unknown 不是通过，报告不据此放行"
            )
        quality = {
            "available": True,
            "status": gate.quality.status,
            "config_status": gate.quality.config_status,
            "note": note,
            "min_sample_hint": None,
            "rows": [
                {
                    "metric": item.metric,
                    "group": item.group,
                    "stratum": item.stratum,
                    "observed": _fmt_value(item.observed),
                    "denominator": str(item.denominator),
                    "status": item.status,
                    "note": "、".join(
                        sorted(
                            {
                                str(check.detail.get("reason") or check.kind)
                                for check in item.checks
                                if check.status in {"unknown", "fail"}
                            }
                        )
                    ),
                }
                for item in gate.quality.metrics
            ],
            "failures": [
                {
                    "gate_id": item.gate_id,
                    "check_id": item.check_id or "-",
                    "stratum": str(item.evidence.get("stratum") or "-"),
                    "observed": item.evidence.get("observed"),
                    "threshold": item.evidence.get("threshold"),
                }
                for item in gate.quality.failures
            ],
        }
        # min_sample 提示只取**非零分母**：零样本指标（如 cost_per_case_cny）的 0 不是样本量，
        # 绝不能作为最小值；按指标分组各取最小非零 stratum 分母（R1-MEDIUM-1）。
        positive = [item for item in gate.quality.metrics if item.denominator > 0]
        zero_sample_metrics = sorted(
            {item.metric for item in gate.quality.metrics}
            - {item.metric for item in positive}
        )
        if positive:
            group_min: dict[str, Any] = {}
            for item in positive:
                current = group_min.get(item.group)
                if current is None or item.denominator < current.denominator:
                    group_min[item.group] = item
            hint = "最小非零 stratum 分母（按分组）：" + "、".join(
                f"{group}={item.denominator}（{item.metric}/{item.stratum}）"
                for group, item in group_min.items()
            )
            if zero_sample_metrics:
                hint += (
                    "；零样本指标（分母 0）不参与 min_sample 提示："
                    + _join(zero_sample_metrics)
                )
            hint += (
                "；单值配置的 min_sample 不得超过对应分组的最小非零分母，"
                "报告只提示、不自动改写配置"
            )
            quality["min_sample_hint"] = hint
        elif zero_sample_metrics:
            quality["min_sample_hint"] = (
                "全部指标为零样本（分母 0）：不给 min_sample 数值提示，零样本一律 unknown、不当 0"
            )

    delta_rows = [
        {
            "metric": item.metric,
            "group": item.group,
            "stratum": item.stratum,
            "baseline": _fmt_value(item.baseline),
            "current": _fmt_value(item.current),
            "delta": _fmt_delta(item.delta),
            "delta_pp": (
                "n/a（runtime）"
                if item.group == "runtime"
                else (_fmt_delta(item.delta_pp, pp=True) if item.delta_pp is not None else "unknown")
            ),
            "baseline_denominator": str(item.baseline_denominator),
            "current_denominator": str(item.current_denominator),
            "status": item.status if item.status != "unknown" or not item.reason else f"unknown（{item.reason}）",
            "order": _STATUS_ORDER.get(item.status, 9),
        }
        for item in diff.metric_deltas
    ]

    zero_sample = sorted(
        {
            f"{item.metric}/{item.stratum}"
            for item in diff.metric_deltas
            if item.metric == "cost_per_case_cny" and item.current_denominator == 0
        }
    )
    p95_items = [item for item in diff.metric_deltas if item.metric == "p95_latency_ms"]
    p95_note = (
        "p95_latency_ms 无 SLA（配置无已审批阈值）：只展示观测值与差值，质量/门禁状态 unknown，"
        "不判定通过；Diff 表该行的 regressed/improved 只是数值方向，不是质量或门禁状态"
        if p95_items and all(not item.threshold_configured for item in p95_items)
        else "p95_latency_ms 阈值由本次配置提供（有值）；SLA / 阈值审批口径以配置与审批记录为准"
    )
    unknown_notes = [
        "cost_per_case_cny 零样本分组："
        + _join(zero_sample if zero_sample else ["无（有成本样本）"])
        + "；零样本一律 unknown，不补 0",
        p95_note,
        "OCR（skipped_requires_ocr）与 error 行不进入任何指标分母；error 单独列在 diff 中",
    ]

    summary_note = "未提供 summary.json"
    if summary:
        summary_note = (
            f"run_id={summary.get('run_id', '-')}，suite={summary.get('suite', '-')}，"
            f"mode={summary.get('mode', '-')}，status_counts={summary.get('status_counts', '-')}，"
            f"metrics_scope={summary.get('metrics_scope', '-')}"
        )

    return {
        "title": "MKTKB 评测报告（P0 · T007）",
        "meta": [
            ("当前 run", diff.run_id),
            ("baseline", diff.baseline_id),
            ("baseline run", diff.baseline_run_id),
            ("suite / mode / scope", f"{diff.suite} / {diff.mode} / {diff.scope}"),
            ("pipeline_version", f"{diff.baseline_pipeline_version} → {diff.pipeline_version}"),
            ("comparison", diff.comparison),
        ],
        "hard_gate": hard_gate,
        "quality": quality,
        "diff": {
            "comparison": diff.comparison,
            "release_allowed": "是" if diff.release_allowed else "否",
            "release_note": diff.release_blocked_reason
            or "同版本且 baseline 已审批；当前 run 门禁见首段，最终放行需同时满足",
            "exit_transition": diff.gate_exit_transition,
            "exit_changed": (
                "unknown" if diff.gate_exit_changed is None else ("是" if diff.gate_exit_changed else "否")
            ),
            "new_failures": _join(list(diff.new_failures)),
            "fixed_failures": _join(list(diff.fixed_failures)),
            "still_failing": _join(list(diff.still_failing)),
            "new_errors": _join(list(diff.new_errors)),
            "resolved_errors": _join(list(diff.resolved_errors)),
            "persistent_errors": _join(list(diff.persistent_errors)),
            "status_changes": _join(
                [
                    f"{item['case_id']}:{item['baseline_status']}->{item['current_status']}"
                    for item in diff.status_changes
                ]
            ),
            "delta_rows": delta_rows,
            "empty": diff.empty,
        },
        "scope": {
            "summary_note": summary_note,
            "denominator_rules": list(_DENOMINATOR_RULES),
            "unknowns": unknown_notes,
            "warnings": list(diff.warnings),
        },
    }


def _hard_gate_first_note() -> str:
    return (
        "报告只展示门禁结果，不参与门禁判定；report.html 是 P0 非门禁展示层，"
        "不被 gate 读取（设计 §8.5）"
    )


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render_markdown(
    diff: RunDiff,
    gate: GateResult | None = None,
    *,
    summary: Mapping[str, Any] | None = None,
) -> str:
    """渲染 Markdown；首段固定是硬门禁结果（置顶），与 HTML 同源同数据。"""
    data = _report_data(summary, diff, gate)
    lines: list[str] = [f"# {data['title']}", "", "## 1. 硬门禁（置顶）", ""]

    hard = data["hard_gate"]
    if not hard["available"]:
        lines.append("- exit_code: unknown（未提供门禁结果，不冒充通过）")
    else:
        status_text = _join(
            [f"{item['gate_id']}={item['status']}" for item in hard["status_rows"]]
        )
        lines.append(f"- exit_code: {hard['exit_code']}（{hard['exit_label']}）")
        lines.append(f"- 门禁状态: {status_text}")
        lines.append(f"- 硬门禁失败: {_join(sorted({item['gate_id'] for item in hard['failures']}))}")
        lines.append(f"- unknown: {hard['unknown_count']} 项；not_applicable: {hard['not_applicable_count']} 项")
        if hard["quality_note"]:
            lines.append(f"- 质量层说明: {hard['quality_note']}")
        for item in hard["failures"]:
            lines.append(
                f"- 失败项: gate={item['gate_id']} case={item['case_id']} check={item['check_id']}"
            )
        for item in hard["unknowns"]:
            lines.append(f"- 无法判定: gate={item['gate_id']} check={item['check_id']} 原因={item['reason']}")
    lines.append(f"- 说明: {_hard_gate_first_note()}")
    lines += ["", "## 2. 报告对象", ""]
    for label, value in data["meta"]:
        lines.append(f"- {label}: {value}")
    lines += ["", "## 3. 质量层（按 stratum + 总体，不设综合分）", ""]

    quality = data["quality"]
    if not quality["available"]:
        lines.append(f"- 状态: not_evaluated；{quality['note']}")
    else:
        lines.append(f"- 状态: {quality['status']}")
        lines.append(f"- 配置状态: {quality['config_status']}")
        if quality["note"]:
            lines.append(f"- 说明: {quality['note']}")
        if quality.get("min_sample_hint"):
            lines.append(f"- min_sample 提示: {quality['min_sample_hint']}")
        lines += [""]
        if quality["rows"]:
            lines += _md_table(
                ("指标", "分组", "stratum", "观测", "分母", "状态", "说明"),
                [
                    (
                        item["metric"],
                        item["group"],
                        item["stratum"],
                        item["observed"],
                        item["denominator"],
                        item["status"],
                        item["note"] or "-",
                    )
                    for item in quality["rows"]
                ],
            )
        else:
            lines.append("- 质量指标: 无（配置 metrics 为空）")
    lines += ["", "## 4. Diff（baseline vs 当前 run）", ""]

    diff_data = data["diff"]
    lines += [
        f"- comparison: {diff_data['comparison']}",
        f"- 放行资格: {diff_data['release_allowed']}（{diff_data['release_note']}）",
        f"- 门禁退出码: {diff_data['exit_transition']}（changed={diff_data['exit_changed']}）",
        f"- 新增失败（new_failures）: {diff_data['new_failures']}",
        f"- 已修复（fixed_failures）: {diff_data['fixed_failures']}",
        f"- 仍失败（still_failing）: {diff_data['still_failing']}",
        f"- 新增 error: {diff_data['new_errors']}；已消除 error: {diff_data['resolved_errors']}；"
        f"持续 error: {diff_data['persistent_errors']}",
        f"- 状态变化（按 case_id）: {diff_data['status_changes']}",
        "- 说明: 空 diff（无变化）为全空列表，不是异常；new/fixed/still 按 case_id 排序",
        "- 说明: 放行资格只表示 baseline/对比方式可用于发布比较；当前 run 门禁必须同时为 "
        "exit_code 0（见首段）",
        "- 说明: Diff 表『状态』列的 regressed/improved 只是数值方向（按指标 direction），"
        "不是质量/门禁状态；阈值判定见质量层，缺已审批阈值时仍为 unknown",
        "",
    ]
    if diff_data["delta_rows"]:
        lines += _md_table(
            ("指标", "stratum", "baseline", "current", "Δ", "Δpp", "分母(b/c)", "状态"),
            [
                (
                    item["metric"],
                    item["stratum"],
                    item["baseline"],
                    item["current"],
                    item["delta"],
                    item["delta_pp"],
                    f"{item['baseline_denominator']}/{item['current_denominator']}",
                    item["status"],
                )
                for item in diff_data["delta_rows"]
            ],
        )
    else:
        lines.append("- 指标差: 无（配置 metrics 为空）")

    scope = data["scope"]
    lines += ["", "## 5. 口径与未知", ""]
    lines.append(f"- summary: {scope['summary_note']}")
    for rule in scope["denominator_rules"]:
        lines.append(f"- 分母口径: {rule}")
    for note in scope["unknowns"]:
        lines.append(f"- unknown 口径: {note}")
    if scope["warnings"]:
        for warning in scope["warnings"]:
            lines.append(f"- warning: {warning}")
    lines += [
        "",
        "---",
        "报告由 diff_runs + gate 结果生成；不是门禁判定层，不改变退出码，"
        "也不被 gate 读取。",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #


def _e(value: Any) -> str:
    return _html.escape("" if value is None else str(value), quote=True)


def _html_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    head = "".join(f"<th>{_e(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


_STYLE = """
:root { color-scheme: light; }
body { margin: 0; padding: 24px; background: #f6f7f9; color: #1f2328;
  font: 14px/1.6 "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }
main { max-width: 1180px; margin: 0 auto; background: #fff; border: 1px solid #d8dee4;
  border-radius: 10px; padding: 24px 28px; box-shadow: 0 1px 3px rgba(31,35,40,.06); }
h1 { margin: 0 0 8px; font-size: 24px; }
h2 { margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #e5e9ef; font-size: 18px; }
.meta { margin: 0 0 8px; padding: 10px 14px; background: #f3f6fa; border-radius: 8px; }
.meta div { margin: 2px 0; }
.exit { display: inline-block; padding: 2px 10px; border-radius: 999px; font-weight: 600; }
.exit-ok { background: #dafbe1; color: #116329; }
.exit-bad { background: #ffebe9; color: #a40e26; }
.note { color: #57606a; }
ul { margin: 6px 0; padding-left: 22px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 14px; font-size: 13px; }
th, td { border: 1px solid #d8dee4; padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: #f3f6fa; }
tr:nth-child(even) td { background: #fbfcfd; }
.tag { font-weight: 600; }
footer { margin-top: 26px; color: #6e7781; font-size: 12px; border-top: 1px solid #e5e9ef; padding-top: 10px; }
""".strip()


def render_html(
    summary: Mapping[str, Any] | None = None,
    diff: RunDiff | None = None,
    gate: GateResult | None = None,
    *,
    title: str | None = None,
) -> str:
    """渲染单文件 HTML（内联 CSS、无脚本、无外链）；数据与 Markdown 完全同源。"""
    if isinstance(summary, RunDiff):
        summary, diff, gate = None, summary, diff
    data = _report_data(summary, diff, gate)
    page_title = title or data["title"]
    hard = data["hard_gate"]
    quality = data["quality"]
    diff_data = data["diff"]
    scope = data["scope"]

    meta_html = "".join(
        f"<div><span class='tag'>{_e(label)}</span>：{_e(value)}</div>"
        for label, value in data["meta"]
    )

    if hard["available"]:
        exit_class = "exit-ok" if hard["exit_code"] == 0 else "exit-bad"
        hard_status_text = _join(
            [f"{item['gate_id']}={item['status']}" for item in hard["status_rows"]]
        )
        hard_lines = [
            f"<p><span class='exit {exit_class}'>exit_code: {_e(hard['exit_code'])}"
            f"（{_e(hard['exit_label'])}）</span></p>",
            "<ul>",
            f"<li>门禁状态：{_e(hard_status_text)}</li>",
            f"<li>硬门禁失败：{_e(_join(sorted({item['gate_id'] for item in hard['failures']})))}</li>",
            f"<li>unknown：{_e(hard['unknown_count'])} 项；not_applicable：{_e(hard['not_applicable_count'])} 项</li>",
        ]
        if hard["quality_note"]:
            hard_lines.append(f"<li class='note'>质量层说明：{_e(hard['quality_note'])}</li>")
        hard_lines.append("</ul>")
        if hard["failures"]:
            hard_lines.append(
                _html_table(
                    ("门禁", "case", "check"),
                    [(item["gate_id"], item["case_id"], item["check_id"]) for item in hard["failures"]],
                )
            )
        if hard["unknowns"]:
            hard_lines.append(
                _html_table(
                    ("门禁", "check", "原因"),
                    [(item["gate_id"], item["check_id"], item["reason"]) for item in hard["unknowns"]],
                )
            )
    else:
        hard_lines = ["<p><span class='exit exit-bad'>exit_code: unknown（未提供门禁结果，不冒充通过）</span></p>"]
    hard_lines.append(f"<p class='note'>{_e(_hard_gate_first_note())}</p>")

    quality_lines: list[str] = []
    if not quality["available"]:
        quality_lines.append(f"<p class='note'>{_e(quality['note'])}</p>")
    else:
        quality_lines.append(
            f"<p>状态：<span class='tag'>{_e(quality['status'])}</span>；"
            f"配置状态：{_e(quality['config_status'])}</p>"
        )
        if quality["note"]:
            quality_lines.append(f"<p class='note'>{_e(quality['note'])}</p>")
        if quality.get("min_sample_hint"):
            quality_lines.append(
                f"<p class='note'>min_sample 提示：{_e(quality['min_sample_hint'])}</p>"
            )
        if quality["rows"]:
            quality_lines.append(
                _html_table(
                    ("指标", "分组", "stratum", "观测", "分母", "状态", "说明"),
                    [
                        (
                            item["metric"], item["group"], item["stratum"], item["observed"],
                            item["denominator"], item["status"], item["note"] or "-",
                        )
                        for item in quality["rows"]
                    ],
                )
            )
        else:
            quality_lines.append("<p class='note'>质量指标：无（配置 metrics 为空）</p>")

    diff_lines = [
        "<ul>",
        f"<li>comparison：{_e(diff_data['comparison'])}</li>",
        f"<li>放行资格：{_e(diff_data['release_allowed'])}（{_e(diff_data['release_note'])}）</li>",
        f"<li>门禁退出码：{_e(diff_data['exit_transition'])}（changed={_e(diff_data['exit_changed'])}）</li>",
        f"<li>新增失败（new_failures）：{_e(diff_data['new_failures'])}</li>",
        f"<li>已修复（fixed_failures）：{_e(diff_data['fixed_failures'])}</li>",
        f"<li>仍失败（still_failing）：{_e(diff_data['still_failing'])}</li>",
        f"<li>新增 error：{_e(diff_data['new_errors'])}；已消除 error：{_e(diff_data['resolved_errors'])}；"
        f"持续 error：{_e(diff_data['persistent_errors'])}</li>",
        f"<li>状态变化（按 case_id）：{_e(diff_data['status_changes'])}</li>",
        "<li class='note'>空 diff（无变化）为全空列表，不是异常；new/fixed/still 按 case_id 排序</li>",
        "<li class='note'>放行资格只表示 baseline/对比方式可用于发布比较；当前 run 门禁必须同时为 "
        "exit_code 0（见首段）</li>",
        "<li class='note'>Diff 表『状态』列的 regressed/improved 只是数值方向（按指标 direction），"
        "不是质量/门禁状态；阈值判定见质量层，缺已审批阈值时仍为 unknown</li>",
        "</ul>",
    ]
    if diff_data["delta_rows"]:
        diff_lines.append(
            _html_table(
                ("指标", "stratum", "baseline", "current", "Δ", "Δpp", "分母(b/c)", "状态"),
                [
                    (
                        item["metric"], item["stratum"], item["baseline"], item["current"],
                        item["delta"], item["delta_pp"],
                        f"{item['baseline_denominator']}/{item['current_denominator']}",
                        item["status"],
                    )
                    for item in diff_data["delta_rows"]
                ],
            )
        )
    else:
        diff_lines.append("<p class='note'>指标差：无（配置 metrics 为空）</p>")

    scope_lines = ["<ul>", f"<li>summary：{_e(scope['summary_note'])}</li>"]
    for rule in scope["denominator_rules"]:
        scope_lines.append(f"<li>分母口径：{_e(rule)}</li>")
    for note in scope["unknowns"]:
        scope_lines.append(f"<li class='note'>unknown 口径：{_e(note)}</li>")
    for warning in scope["warnings"]:
        scope_lines.append(f"<li class='note'>warning：{_e(warning)}</li>")
    scope_lines.append("</ul>")

    sections = [
        ("硬门禁（置顶）", "hard-gate", hard_lines),
        ("报告对象", "identity", [f"<div class='meta'>{meta_html}</div>"]),
        ("质量层（按 stratum + 总体，不设综合分）", "quality", quality_lines),
        ("Diff（baseline vs 当前 run）", "diff", diff_lines),
        ("口径与未知", "scope", scope_lines),
    ]
    body = "".join(
        f"<section id='{anchor}'><h2>{_e(heading)}</h2>{''.join(parts)}</section>"
        for heading, anchor, parts in sections
    )
    return (
        "<!DOCTYPE html>\n"
        "<html lang='zh-CN'>\n<head>\n<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        f"<title>{_e(page_title)}</title>\n<style>\n{_STYLE}\n</style>\n</head>\n<body>\n<main>\n"
        f"<h1>{_e(page_title)}</h1>\n{body}\n"
        "<footer>单文件 · 内联 CSS · 无脚本 · 无外部资源 · P0 非门禁展示层（不改变退出码，"
        "不被 gate 读取）</footer>\n</main>\n</body>\n</html>\n"
    )
