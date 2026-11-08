"""Release Gate：硬门禁层（T006a）+ 质量层 / 校准 / 质量 waiver（T006b）。

设计 §8.1 / §8.2 / §8.3 / §8.4；P0 计划 Task 5 Step 1/3/4/5。

两层门禁：

- **硬门禁（T006a，语义未变）**：8 项按设计 §8.1 顺序判定；任一失败 → ``exit_code=1``，
  不可豁免（没有 waiver API，也不接受硬门禁 waiver）；
- **质量层（T006b）**：按 ``stratum`` + ``all`` 报告设计 §8.2 的检索 / 答案 / 拒答 /
  运行四组指标，不设综合分；``evaluate_gate(..., quality=True)`` 才评估
  （``quality=False`` 是 T006a 兼容模式，``exit_code=0`` 只代表硬门禁通过）。

退出码（设计 §8.4）：``0`` 通过；``1`` 硬门禁失败（最高优先级）；``3`` 数据 / 配置 /
gold 不可用、样本不足、阈值未审批、跨版本 baseline；``2`` 质量失败（绝对阈值未达或
``max_regression_pp`` 回退超限，且未被质量 waiver）；``4`` ``mode=live`` 未授权。
``3`` 优先于 ``2``：不可判定的状态不会被当成"已知回退"放行或误报。

质量层口径：

- **阈值审批是人工门（T009）**：配置 ``status`` 不是 ``"approved"`` 时所有适用指标
  ``unknown``（→ exit 3），绝不返回 0 冒充通过；``calibrate_gate`` 只产出
  :class:`GateProposal`（观测值 + 建议阈值 + ``gate_config_hash`` + ``run_id``），
  ``write_gate_proposal`` 拒绝写回 ``gate_v0_1.json``；
- **分母按指标各自口径，不复用硬门禁 ``hard_gate_min_sample``**：检索 = 有 gold 且
  非 OCR 的 case；答案 = scored 且非 OCR、非 error；拒答 = 适用样本（``should_refuse`` /
  可答 / 实际拒答），并排除 ``error`` / ``service_error`` / ``knowledge_changed``；
  运行 = 有延迟 / 成本数据的行；OCR 与 error 行一律排除；
- **``all`` 级观测**读 ``summary.json`` 的 ``metrics``（缺失指标显式 unknown，不默认 0），
  逐 ``stratum`` 观测按 ``cases.jsonl`` + 数据集重算（summary 没有按 stratum 的拆分）；
  拒答指标按排除口径重算，``value_no_fabricated`` 只作诊断字段；
- **``max_regression_pp`` 只在同 ``pipeline_version`` 生效**：baseline 可以是
  ``RunResult`` 或 run 目录路径；跨版本 / suite / dataset 不一致一律拒绝回退判定并标
  ``unknown``（设计 §8.3：跨版本只分析、不放行）；没有 baseline 时回退检查显式
  ``skipped``（首次建立 baseline 只用绝对阈值）；
- **质量 waiver**：必须 ``reason`` + ``approver``（构造时校验，缺一 ``ValueError``）；
  只作用于已发生的质量失败，记入 ``GateResult.warnings`` 与
  ``GateResult.to_dict()["quality"]["waived"]``；不改变硬失败，也不能把 unknown 变通过。

输入只读：``RunResult``（``run_manifest.json`` 身份字段、``cases.jsonl`` 行、``summary.json``
指标）、run 目录下的 ``traces.sqlite3``（只读打开）与数据集文件（重新解析 gold /
forbidden，不信任 run 自报的 gold）。本模块不写任何产物、不调用 provider、不建索引。

硬门禁判定口径（PM 裁决 2026-11-05，handoff §5.4 / §5.5 / §7）：

- 硬门禁**按 case 条件适用**：数据集里没有该类 case → ``not_applicable``（记
  INFO/warnings，不影响退出码）；有该类 case 但字段缺失 / 无法判定 → ``unknown``
  → ``exit_code=3``；
- 硬门禁不可豁免：没有 ``waive`` / ``waive_hard_gate`` API，``evaluate_gate`` 不接受
  硬门禁 waiver；``QualityWaiver(metric=<硬门禁 ID>)`` 在构造时直接 ``ValueError``；
- ``value_no_fabricated`` **不是**硬门禁输入（T004b MEDIUM-1；Q26 即因它 fail），
  只作诊断字段；
- ``citation_required`` 只认 **unit 级** citations，且必须落在本轮 ``retrieved``
  evidence 内，**不看** ``source_hit``；
- ``security_leak`` 的 forbidden 引用按**解析后的 unit 映射**比对：引用只带
  ``unit_ids`` 而 forbidden 用 ``unit_key`` 时不得漏报（T004b MEDIUM-4）；
  无法解析（``record_code`` 不是解析键 / 既无 unit_key 又无非空 locator）→ unknown；
- ``cross_entity`` / ``stale_bypass``：v0.1 case 契约没有 entity key、请求 filters、
  ``include_future`` / ``as_of`` / ``effective_from|to`` 字段 → **没有该类 case** →
  ``not_applicable``；上游归一化给出的 ``hard_filter_violation``
  （``cross_entity`` / ``stale`` / ``forbidden_source``）是显式违规证据 → fail；
- 硬门禁 ``min_sample`` 的分母是 **``evaluated_count``**：``cases.jsonl`` 中 ``status``
  为 ``pass`` / ``fail`` 且非 ``skipped_requires_ocr``、非 runner ``error`` 的行数；
  不用 ``case_count`` / ``metrics_scope.cases_in_denominator``。质量层（T006b）的指标
  分母各自独立（如 badcase 检索只算有 gold 的 10 条），不得与本口径混用；
- ``exact_value_contract`` 只作用于 ``stratum=exact`` 的 case：数据集把 24 道精确值题
  标为 ``exact``、8 道标为 ``text``（``eval_data_v0_1.md``），text stratum 的
  ``value_hit`` 未命中属质量层（T006b），不是硬门禁；
- ``exact_value_contract`` 与 ``pagination_contract`` **从数据集 + 本轮 outcome 重算**，
  不读 run 行里自报的 ``value_hit`` / ``pagination_*`` checks（T005 LOW-3：replay 的
  checks 来自源 run 自报，不能当数据集真值）；分页契约复用 T004b 的契约实现以保证
  同一口径；
- ``record_code`` 不是解析键：``record_code``-only 或 ``record_code`` + 空 ``locator``
  的 gold 一律 unknown（exit 3），不得静默按整篇命中；``doc_code``-only 是设计允许的
  范围型 gold（如 N09），显式记 warning，不静默。
- ``mode`` 必须是 ``local`` / ``replay``：``live``（大小写不敏感）→ exit 4；
  其它值 → exit 3（无法判定），不静默按 local 处理。

trace 是**不可信输入**（T003a 遗留）：gate 不因 trace 自称 ``status=ok`` 就放行，
必需 Span 按 ``required_spans(path, outcome, reason=trace.reason)`` + 条件 Span
重新计算；``status=replayed`` 的记录只校版本绑定与 JSON 结构（T003a/T003d 遗留）；
``*_json`` 非法 JSON fail closed；``TRACE_SCHEMA_VERSION`` 不一致 fail；trace store 的
``schema_meta.trace_schema_version`` 与契约不一致同样 fail（trace_schema_v0_1.md
§8），``schema_meta`` 缺失 / 不可读 → unknown（exit 3）。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..observability.contracts import (
    GATE_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    TraceRecord,
    conditional_required_spans,
    required_spans,
)
from .dataset import HOLDOUT_SUITE, CaseSpec, ci_environment, load_cases
from .runner import RunManifest, RunResult
from .scorers import EvalOutcome, _pagination_checks, check_value

__all__ = [
    "DEFAULT_GATE_CONFIG_PATH",
    "EXIT_CODES",
    "EXIT_HARD_FAILURE",
    "EXIT_LIVE_UNAUTHORIZED",
    "EXIT_PASS",
    "EXIT_QUALITY_REGRESSION",
    "EXIT_UNKNOWN",
    "GateConfig",
    "GateFailure",
    "GateNote",
    "GateProposal",
    "GateResult",
    "GateUnknown",
    "HARD_GATE_IDS",
    "MetricSpec",
    "PROPOSAL_SCHEMA_VERSION",
    "QUALITY_ALL_STRATUM",
    "QUALITY_METRIC_GROUPS",
    "QUALITY_STATUS_FAIL",
    "QUALITY_STATUS_NOT_APPLICABLE",
    "QUALITY_STATUS_NOT_EVALUATED",
    "QUALITY_STATUS_PASS",
    "QUALITY_STATUS_PASS_WITH_WAIVERS",
    "QUALITY_STATUS_UNKNOWN",
    "QUALITY_STATUS_WAIVED",
    "QualityCheck",
    "QualityMetricResult",
    "QualityPolicy",
    "QualityResult",
    "QualityWaiver",
    "calibrate_gate",
    "evaluate_gate",
    "load_gate_config",
    "load_run_result",
    "write_gate_proposal",
]

# --------------------------------------------------------------------------- #
# 退出码（设计 §8.4）
# --------------------------------------------------------------------------- #

EXIT_PASS = 0
EXIT_HARD_FAILURE = 1
#: 保留给 T006b 的质量回退；本包（硬门禁层）没有任何触发路径。
EXIT_QUALITY_REGRESSION = 2
EXIT_UNKNOWN = 3
EXIT_LIVE_UNAUTHORIZED = 4
EXIT_CODES: tuple[int, ...] = (
    EXIT_PASS,
    EXIT_HARD_FAILURE,
    EXIT_QUALITY_REGRESSION,
    EXIT_UNKNOWN,
    EXIT_LIVE_UNAUTHORIZED,
)

# --------------------------------------------------------------------------- #
# 门禁 / 配置常量
# --------------------------------------------------------------------------- #

HARD_GATE_IDS: tuple[str, ...] = (
    "security_leak",
    "cross_entity",
    "stale_bypass",
    "conflict_not_rejected",
    "exact_value_contract",
    "pagination_contract",
    "citation_required",
    "trace_integrity",
)

GATE_STATUS_PASS = "pass"
GATE_STATUS_FAIL = "fail"
GATE_STATUS_UNKNOWN = "unknown"
GATE_STATUS_NOT_APPLICABLE = "not_applicable"
GATE_STATUS_NOT_EVALUATED = "not_evaluated"

CONFIG_SCHEMA_VERSION = "mktkb.gate.config.v0.1"
#: 初版配置骨架（只有硬门禁 ID / min_sample / 指标方向 / 空阈值占位）。
DEFAULT_GATE_CONFIG_PATH = (
    Path(__file__).resolve().parents[4] / "docs" / "evaluation" / "gate_v0_1.json"
)
#: 冻结数据集目录（run_manifest.dataset_path 不可用时的回退）。
FROZEN_DATASET_DIR = DEFAULT_GATE_CONFIG_PATH.parent.parent.parent / "fixtures" / "evaluation"

SCORED_ROW_STATUSES = frozenset({"pass", "fail"})
OCR_ROW_STATUS = "skipped_requires_ocr"

DIRECTIONS = frozenset({"higher_is_better", "lower_is_better"})

# --------------------------------------------------------------------------- #
# 质量层（T006b）常量
# --------------------------------------------------------------------------- #

QUALITY_STATUS_PASS = "pass"
QUALITY_STATUS_PASS_WITH_WAIVERS = "pass_with_waivers"
QUALITY_STATUS_FAIL = "fail"
QUALITY_STATUS_UNKNOWN = "unknown"
QUALITY_STATUS_NOT_APPLICABLE = "not_applicable"
QUALITY_STATUS_WAIVED = "waived"
QUALITY_STATUS_NOT_EVALUATED = "not_evaluated"

#: 设计 §8.2 的四组质量指标；按 stratum + ``all`` 分别报告，不设综合分。
QUALITY_METRIC_GROUPS = frozenset({"retrieval", "answer", "refusal", "runtime"})
QUALITY_ALL_STRATUM = "all"
#: 阈值审批是人工门（T009）：只有配置显式 ``status="approved"`` 才参与判定。
QUALITY_APPROVED_STATUS = "approved"
#: 拒答类质量指标排除的结局（T004b MEDIUM-2）；同时排除 runner error 行。
REFUSAL_EXCLUDED_KINDS = frozenset({"error", "service_error", "knowledge_changed"})

#: 校准提案（``--calibrate`` 等价物）：只给建议值，绝不写回 gate 配置。
PROPOSAL_SCHEMA_VERSION = "mktkb.gate.proposal.v0.1"
#: 比率类指标的审批余量（2 个百分点）与回退容忍（2 pp）。
PROPOSAL_ABSOLUTE_SLACK = 0.02
PROPOSAL_MAX_REGRESSION_PP = 2.0

#: 这些 trace ``*_json`` 字段必须是合法 JSON 文本（不可解析 → fail closed）。
_JSON_FIELD_NAMES: tuple[str, ...] = tuple(
    item.name for item in fields(TraceRecord) if item.name.endswith("_json")
)
#: trace 与 run manifest 的版本绑定字段（trace 侧字段名 → manifest 侧字段名）。
_TRACE_BINDING: tuple[tuple[str, str], ...] = (
    ("dataset_version", "dataset_version"),
    ("pipeline_version", "pipeline_version"),
    ("run_id", "run_id"),
    ("index_revision", "index_revision"),
    ("manifest_sha256", "corpus_manifest_sha256"),
    ("config_hash", "config_hash"),
    ("mode", "mode"),
)
_CONDITIONAL_FLAGS: tuple[str, ...] = (
    "vector_enabled",
    "rerank_enabled",
    "expansion_triggered",
    "index_sync_performed",
)
_CONFLICT_ACCEPTED_KINDS = frozenset({"conflict", "clarification"})
_EXCLUDED_FORBIDDEN_VIOLATION = "forbidden_source"


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MetricSpec:
    """质量指标骨架（名称 / 分组 / 方向 + 空阈值占位）；质量判定属 T006b。"""

    name: str
    group: str
    direction: str
    min_sample: int | None = None
    absolute_min: float | None = None
    absolute_max: float | None = None
    max_regression_pp: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group,
            "direction": self.direction,
            "min_sample": self.min_sample,
            "absolute_min": self.absolute_min,
            "absolute_max": self.absolute_max,
            "max_regression_pp": self.max_regression_pp,
        }


@dataclass(frozen=True)
class GateConfig:
    """Release Gate 配置 v0.1（只含硬门禁骨架；阈值留给 T006b 审批后填入）。

    ``min_sample`` 是**硬门禁最小样本数**（JSON 字段 ``hard_gate_min_sample``），分母
    固定为 ``evaluated_count``（见 :func:`evaluate_gate`）；它不用于质量指标，T006b 的
    检索 / 拒答指标各自另算分母，不得与硬门禁口径混用。
    """

    gate_version: str
    schema_version: str
    status: str
    hard_gates: tuple[str, ...]
    min_sample: Mapping[str, int]
    metrics: tuple[MetricSpec, ...] = ()
    sensitive_patterns: tuple[str, ...] = ()
    source_path: str | None = None
    config_hash: str = ""

    @property
    def hard_gate_min_sample(self) -> Mapping[str, int]:
        """硬门禁最小样本数（语义名；``min_sample`` 保留为数据字段名）。"""
        return self.min_sample

    def min_sample_for(self, suite: str) -> int | None:
        """返回 suite 的硬门禁最小样本数；未配置返回 ``None``（调用方必须 fail closed）。

        分母固定为 ``evaluated_count``（见 :func:`evaluate_gate`），不是
        ``case_count`` / ``metrics_scope.cases_in_denominator``，也不用于质量指标。
        P1 T107：``regression`` 未在 ``gate_v0_1.json`` 配置 ``hard_gate_min_sample``
        时返回 ``None`` → ``min_sample_missing`` unknown / 退出码 3，不得静默通过。
        """
        value = self.min_sample.get(str(suite))
        return None if value is None else int(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_version": self.gate_version,
            "schema_version": self.schema_version,
            "status": self.status,
            "hard_gates": list(self.hard_gates),
            "min_sample": dict(self.min_sample),
            "metrics": [item.to_dict() for item in self.metrics],
            "sensitive_patterns": list(self.sensitive_patterns),
            "source_path": self.source_path,
            "config_hash": self.config_hash,
        }


def _require_mapping(payload: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} 必须是 JSON 对象")
    return payload


def _require_text(payload: Any, name: str) -> str:
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError(f"{name} 必须是非空字符串，收到 {payload!r}")
    return payload


def _optional_number(payload: Any, name: str) -> float | None:
    if payload is None:
        return None
    if isinstance(payload, bool) or not isinstance(payload, (int, float)):
        raise ValueError(f"{name} 必须是数字或 null，收到 {payload!r}")
    return float(payload)


def _optional_positive_int(payload: Any, name: str) -> int | None:
    if payload is None:
        return None
    if isinstance(payload, bool) or not isinstance(payload, int) or payload < 1:
        raise ValueError(f"{name} 必须是正整数或 null，收到 {payload!r}")
    return payload


def load_gate_config(path: Path | str) -> GateConfig:
    """读取并校验 ``gate_v0_1.json``；任何不合法都抛 ``ValueError``（fail closed）。"""
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取 gate 配置 {target}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"gate 配置不是合法 UTF-8 JSON: {target}: {exc}") from exc
    payload = _require_mapping(payload, "gate 配置")

    schema_version = _require_text(payload.get("schema_version"), "schema_version")
    if schema_version != CONFIG_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version 不兼容：{schema_version!r} != {CONFIG_SCHEMA_VERSION!r}"
        )
    gate_version = _require_text(payload.get("gate_version"), "gate_version")
    if gate_version != GATE_SCHEMA_VERSION:
        raise ValueError(
            f"gate_version 不匹配契约：{gate_version!r} != {GATE_SCHEMA_VERSION!r}"
        )
    status = _require_text(payload.get("status"), "status")

    raw_gates = payload.get("hard_gates")
    if isinstance(raw_gates, (str, bytes)) or not isinstance(raw_gates, Sequence):
        raise ValueError("hard_gates 必须是字符串数组")
    hard_gates = tuple(_require_text(item, "hard_gates[]") for item in raw_gates)
    if len(set(hard_gates)) != len(hard_gates):
        raise ValueError(f"hard_gates 含重复项: {list(hard_gates)}")
    unknown_gates = sorted(set(hard_gates) - set(HARD_GATE_IDS))
    missing_gates = sorted(set(HARD_GATE_IDS) - set(hard_gates))
    if unknown_gates or missing_gates:
        raise ValueError(
            "hard_gates 必须恰好是 8 项硬门禁："
            f"未知 {unknown_gates}，缺少 {missing_gates}"
        )

    raw_min_sample = _require_mapping(
        payload.get("hard_gate_min_sample"), "hard_gate_min_sample"
    )
    min_sample: dict[str, int] = {}
    for suite, value in raw_min_sample.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(
                f"hard_gate_min_sample[{suite!r}] 必须是正整数，收到 {value!r}"
            )
        min_sample[str(suite)] = value
    if not min_sample:
        raise ValueError("hard_gate_min_sample 不能为空")

    raw_metrics = payload.get("metrics", [])
    if isinstance(raw_metrics, (str, bytes)) or not isinstance(raw_metrics, Sequence):
        raise ValueError("metrics 必须是对象数组")
    metrics: list[MetricSpec] = []
    for index, item in enumerate(raw_metrics):
        item = _require_mapping(item, f"metrics[{index}]")
        direction = _require_text(item.get("direction"), f"metrics[{index}].direction")
        if direction not in DIRECTIONS:
            raise ValueError(
                f"metrics[{index}].direction 必须是 {sorted(DIRECTIONS)} 之一，收到 {direction!r}"
            )
        metrics.append(
            MetricSpec(
                name=_require_text(item.get("name"), f"metrics[{index}].name"),
                group=_require_text(item.get("group"), f"metrics[{index}].group"),
                direction=direction,
                min_sample=_optional_positive_int(
                    item.get("min_sample"), f"metrics[{index}].min_sample"
                ),
                absolute_min=_optional_number(
                    item.get("absolute_min"), f"metrics[{index}].absolute_min"
                ),
                absolute_max=_optional_number(
                    item.get("absolute_max"), f"metrics[{index}].absolute_max"
                ),
                max_regression_pp=_optional_number(
                    item.get("max_regression_pp"), f"metrics[{index}].max_regression_pp"
                ),
            )
        )

    raw_patterns = payload.get("sensitive_patterns", [])
    if isinstance(raw_patterns, (str, bytes)) or not isinstance(raw_patterns, Sequence):
        raise ValueError("sensitive_patterns 必须是字符串数组")
    patterns: list[str] = []
    for index, item in enumerate(raw_patterns):
        pattern = _require_text(item, f"sensitive_patterns[{index}]")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"sensitive_patterns[{index}] 不是合法正则: {exc}") from exc
        patterns.append(pattern)

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return GateConfig(
        gate_version=gate_version,
        schema_version=schema_version,
        status=status,
        hard_gates=hard_gates,
        min_sample=min_sample,
        metrics=tuple(metrics),
        sensitive_patterns=tuple(patterns),
        source_path=str(target.resolve()),
        config_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


# --------------------------------------------------------------------------- #
# 判定结果
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GateFailure:
    """一个硬门禁失败：必须带 ``case_id`` / ``check_id`` / ``evidence``。"""

    gate_id: str
    case_id: str | None
    check_id: str | None
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "case_id": self.case_id,
            "check_id": self.check_id,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class GateUnknown:
    """一个无法判定项（→ exit 3）：字段缺失、无法解析、样本不足等。"""

    gate_id: str
    case_id: str | None
    check_id: str | None
    reason: str
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "case_id": self.case_id,
            "check_id": self.check_id,
            "reason": self.reason,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class GateNote:
    """一个 ``not_applicable`` 记录（数据集没有该类 case；不影响退出码）。"""

    gate_id: str
    applicable_cases: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "applicable_cases": self.applicable_cases,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GateResult:
    """一次门禁评估结果；``hard_failures`` 是失败的硬门禁 ID（可直接 ``in`` 判断）。

    ``scored_count`` 的数值就是硬门禁的 ``evaluated_count``（``status`` 为
    ``pass`` / ``fail`` 且非 OCR、非 error 的行）；字段名保留以兼容既有产物读取方，
    :attr:`evaluated_count` 是同一数值的显式别名。

    ``quality`` 为 ``None`` 表示本调用**没有**评估质量层（``quality=False``，T006a
    兼容模式）；此时 ``exit_code=0`` 只代表硬门禁通过，不代表质量达标。
    """

    exit_code: int
    gate_status: Mapping[str, str]
    hard_failures: tuple[str, ...]
    failures: tuple[GateFailure, ...]
    unknowns: tuple[GateUnknown, ...]
    not_applicable: tuple[GateNote, ...]
    warnings: tuple[str, ...]
    run_id: str
    suite: str
    mode: str
    gate_version: str
    scored_count: int
    min_sample: int | None
    quality: "QualityResult | None" = None

    @property
    def evaluated_count(self) -> int:
        """硬门禁 ``min_sample`` 的分母（与 ``scored_count`` 同值）。"""
        return self.scored_count

    @property
    def quality_status(self) -> str:
        """质量层状态；未评估时显式 ``not_evaluated``（不等于质量通过）。"""
        return QUALITY_STATUS_NOT_EVALUATED if self.quality is None else self.quality.status

    @property
    def quality_failures(self) -> tuple[GateFailure, ...]:
        return () if self.quality is None else self.quality.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "run_id": self.run_id,
            "suite": self.suite,
            "mode": self.mode,
            "gate_version": self.gate_version,
            "scored_count": self.scored_count,
            "min_sample": self.min_sample,
            "hard_failures": list(self.hard_failures),
            "gate_status": dict(self.gate_status),
            "failures": [item.to_dict() for item in self.failures],
            "unknowns": [item.to_dict() for item in self.unknowns],
            "not_applicable": [item.to_dict() for item in self.not_applicable],
            "warnings": list(self.warnings),
            "quality": None if self.quality is None else self.quality.to_dict(),
        }


@dataclass
class _GateOutcome:
    gate_id: str
    status: str
    failures: list[GateFailure]
    unknowns: list[GateUnknown]
    applicable: int
    detail: str


def _outcome(
    gate_id: str,
    *,
    failures: Iterable[GateFailure] = (),
    unknowns: Iterable[GateUnknown] = (),
    applicable: int = 0,
    detail: str = "",
) -> _GateOutcome:
    """把逐 case 结果收敛成一个门禁状态：fail > unknown > pass/not_applicable。"""
    failure_items = list(failures)
    unknown_items = list(unknowns)
    if failure_items:
        status = GATE_STATUS_FAIL
    elif unknown_items:
        status = GATE_STATUS_UNKNOWN
    elif applicable:
        status = GATE_STATUS_PASS
    else:
        status = GATE_STATUS_NOT_APPLICABLE
    return _GateOutcome(
        gate_id=gate_id,
        status=status,
        failures=failure_items,
        unknowns=unknown_items,
        applicable=applicable,
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# 质量层结果类型（T006b）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QualityCheck:
    """单条质量检查（样本 / 绝对阈值 / 同版本回退）；``unknown`` 不是通过。"""

    kind: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    denominator: int | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "observed": self.observed,
            "threshold": self.threshold,
            "denominator": self.denominator,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class QualityMetricResult:
    """一个指标在一个 stratum（或 ``all``）上的观测与判定。"""

    metric: str
    group: str
    stratum: str
    direction: str
    observed: float | None
    denominator: int
    dataset_sample: int
    denominator_basis: str
    source: str
    status: str
    checks: tuple[QualityCheck, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "group": self.group,
            "stratum": self.stratum,
            "direction": self.direction,
            "observed": self.observed,
            "denominator": self.denominator,
            "dataset_sample": self.dataset_sample,
            "denominator_basis": self.denominator_basis,
            "source": self.source,
            "status": self.status,
            "checks": [item.to_dict() for item in self.checks],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class QualityWaiver:
    """质量门禁豁免；``reason`` 与 ``approver`` 缺一不可，硬门禁 ID 直接拒绝。

    - ``metric=None`` 表示豁免全部质量指标；``stratum=None`` 表示全部 stratum；
    - 只作用于**已发生的质量失败**，不会把 unknown（未审批 / 样本不足）变成通过。
    """

    reason: str
    approver: str
    metric: str | None = None
    stratum: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("质量 waiver 必须提供非空 reason")
        if not isinstance(self.approver, str) or not self.approver.strip():
            raise ValueError("质量 waiver 必须提供非空 approver")
        if self.metric is not None and self.metric in HARD_GATE_IDS:
            raise ValueError(
                f"硬门禁不可豁免：{self.metric!r} 属第一层硬门禁，waiver 只允许质量指标"
            )
        if self.stratum is not None and (
            not isinstance(self.stratum, str) or not self.stratum.strip()
        ):
            raise ValueError("质量 waiver 的 stratum 必须是非空字符串或 None")

    def matches(self, metric: str, stratum: str) -> bool:
        return (
            (self.metric is None or self.metric == metric)
            and (self.stratum is None or self.stratum == stratum)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "stratum": self.stratum,
            "reason": self.reason,
            "approver": self.approver,
        }


@dataclass(frozen=True)
class QualityPolicy:
    """质量层开关 + 豁免清单；通过 ``evaluate_gate(..., quality=...)`` 传入。

    ``quality=False``（默认）只跑 T006a 硬门禁；``quality=True`` 评估质量层；
    ``quality=QualityPolicy(waivers=(...))`` 评估质量层并应用豁免。
    """

    waivers: tuple[QualityWaiver, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "waivers", tuple(self.waivers))


@dataclass(frozen=True)
class QualityResult:
    """一次质量层评估；按 stratum + ``all`` 报告，不设综合分。"""

    status: str
    metrics: tuple[QualityMetricResult, ...]
    strata: tuple[str, ...]
    stratum_status: Mapping[str, str]
    failures: tuple[GateFailure, ...]
    unknowns: tuple[GateUnknown, ...]
    waived: tuple[Mapping[str, Any], ...]
    diagnostics: Mapping[str, Any]
    warnings: tuple[str, ...]
    config_status: str
    gate_config_hash: str
    baseline_run_id: str | None
    baseline_pipeline_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "config_status": self.config_status,
            "gate_config_hash": self.gate_config_hash,
            "strata": list(self.strata),
            "stratum_status": dict(self.stratum_status),
            "baseline_run_id": self.baseline_run_id,
            "baseline_pipeline_version": self.baseline_pipeline_version,
            "metrics": [item.to_dict() for item in self.metrics],
            "failures": [item.to_dict() for item in self.failures],
            "unknowns": [item.to_dict() for item in self.unknowns],
            "waived": [dict(item) for item in self.waived],
            "diagnostics": dict(self.diagnostics),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class GateProposal:
    """校准提案：观测值 + 建议阈值 + 配置 hash + run_id；**不是**审批结果。"""

    run_id: str
    suite: str
    mode: str
    pipeline_version: str
    dataset_version: str
    gate_version: str
    gate_config_hash: str
    status: str
    strata: tuple[str, ...]
    metrics: tuple[Mapping[str, Any], ...]
    diagnostics: Mapping[str, Any]
    baseline: Mapping[str, Any] | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "status": self.status,
            "approval_owner": "T009 human gate",
            "run_id": self.run_id,
            "suite": self.suite,
            "mode": self.mode,
            "pipeline_version": self.pipeline_version,
            "dataset_version": self.dataset_version,
            "gate_version": self.gate_version,
            "gate_config_hash": self.gate_config_hash,
            "strata": list(self.strata),
            "metrics": [dict(item) for item in self.metrics],
            "diagnostics": dict(self.diagnostics),
            "baseline": None if self.baseline is None else dict(self.baseline),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class _Observation:
    """内部：一个指标在一个 stratum 上的观测（不含阈值判定）。"""

    observed: float | None
    denominator: int
    dataset_sample: int
    basis: str
    source: str
    present: bool = True
    problem: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _BaselineContext:
    run: RunResult | None
    error: str | None
    observations: Mapping[tuple[str, str], _Observation]
    run_id: str | None
    pipeline_version: str | None
    suite: str | None
    dataset_version: str | None


# --------------------------------------------------------------------------- #
# 只读 trace 读取
# --------------------------------------------------------------------------- #


class _TraceStoreUnavailable(RuntimeError):
    """trace 仓储不可读（文件缺失 / 非 SQLite / 缺表 / 打开失败）。"""


_TRACE_COLUMNS: tuple[str, ...] = tuple(item.name for item in fields(TraceRecord))


class _TraceReader:
    """只读（``mode=ro``）trace 读取器；不修改 run 产物，也不信任 trace 内容。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._failed = False

    def _connection(self) -> sqlite3.Connection | None:
        if self._conn is None and not self._failed:
            try:
                uri = self._path.resolve().as_uri() + "?mode=ro"
                conn = sqlite3.connect(uri, uri=True)
                conn.row_factory = sqlite3.Row
                self._conn = conn
            except (sqlite3.Error, OSError, ValueError):
                self._failed = True
        return self._conn

    def ensure_ready(self) -> str | None:
        """返回不可用原因；``None`` 表示可以读取。"""
        if not self._path.is_file():
            return f"trace store 不存在: {self._path.name}"
        conn = self._connection()
        if conn is None:
            return f"trace store 无法打开（只读）: {self._path.name}"
        try:
            row = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' "
                "AND name IN ('traces','spans')"
            ).fetchone()
        except sqlite3.Error as exc:  # pragma: no cover - 只有损坏文件会走到
            return f"trace store 不可读: {exc}"
        if row is None or int(row[0]) != 2:
            return "trace store 缺少 traces/spans 表"
        try:
            columns = {
                str(item[1]) for item in conn.execute("PRAGMA table_info(traces)").fetchall()
            }
        except sqlite3.Error as exc:  # pragma: no cover - 只有损坏文件会走到
            return f"trace store 不可读: {exc}"
        missing_columns = sorted(set(_TRACE_COLUMNS) - columns)
        if missing_columns:
            return f"trace store 的 traces 表缺列（schema 不兼容）: {missing_columns[:5]}"
        return None

    def schema_meta_version(self) -> tuple[str, str | None]:
        """读 ``schema_meta.trace_schema_version``（trace_schema_v0_1.md §8）。

        返回 ``("ok", version)`` / ``("mismatch", actual)`` /
        ``("unavailable", reason)``；表/键缺失或查询失败都是 unavailable（→ unknown），
        版本不一致是 mismatch（→ 硬失败），不得把缺失当空值放行。
        """
        conn = self._connection()
        if conn is None:
            return "unavailable", f"trace store 无法打开（只读）: {self._path.name}"
        try:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                ("trace_schema_version",),
            ).fetchone()
        except sqlite3.Error as exc:
            return "unavailable", f"trace store 的 schema_meta 不可读: {exc}"
        if row is None or row[0] is None:
            return "unavailable", "trace store 的 schema_meta 缺少 trace_schema_version"
        stored = str(row[0])
        if stored != TRACE_SCHEMA_VERSION:
            return "mismatch", stored
        return "ok", stored

    def get(self, trace_id: str) -> tuple[TraceRecord, tuple[str, ...]] | None:
        """读一条 trace + 其 Span 名称；不存在返回 ``None``，仓储不可读抛异常。"""
        conn = self._connection()
        if conn is None:
            raise _TraceStoreUnavailable(f"trace store 无法打开（只读）: {self._path.name}")
        try:
            row = conn.execute(
                "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if row is None:
                return None
            span_rows = conn.execute(
                "SELECT name FROM spans WHERE trace_id = ? ORDER BY rowid ASC", (trace_id,)
            ).fetchall()
        except sqlite3.Error as exc:
            raise _TraceStoreUnavailable(f"trace store 查询失败: {exc}") from exc
        keys = set(row.keys())
        missing_columns = [name for name in _TRACE_COLUMNS if name not in keys]
        if missing_columns:
            raise _TraceStoreUnavailable(
                f"trace store 列与 TraceRecord 不一致，缺列: {sorted(missing_columns)[:5]}"
            )
        values = {name: row[name] for name in _TRACE_COLUMNS}
        values["replayed"] = bool(values.get("replayed"))
        return TraceRecord(**values), tuple(
            str(item[0]) for item in span_rows if item[0] is not None
        )

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover - 关闭失败不影响判定
                pass

    def __enter__(self) -> "_TraceReader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def _as_list(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _row_status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "")


def _is_ocr_row(row: Mapping[str, Any]) -> bool:
    return _row_status(row) == OCR_ROW_STATUS


def _is_error_row(row: Mapping[str, Any]) -> bool:
    return _row_status(row) == "error" or bool(row.get("error"))


def _is_evaluated_row(row: Mapping[str, Any]) -> bool:
    """硬门禁 ``min_sample`` 的分母：pass/fail 且非 OCR、非 error。"""
    return (
        _row_status(row) in SCORED_ROW_STATUSES
        and not _is_ocr_row(row)
        and not _is_error_row(row)
    )


def _row_outcome(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    outcome = row.get("outcome")
    return outcome if isinstance(outcome, Mapping) else None


def _row_checks(row: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    checks: dict[str, Mapping[str, Any]] = {}
    for item in _as_list(row.get("checks")):
        if isinstance(item, Mapping) and item.get("check_id"):
            checks[str(item["check_id"])] = item
    return checks


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if actual is None or expected is None:
        return actual is expected
    return actual == expected or str(actual) == str(expected)


def _unit_key_map(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], frozenset[str]]:
    """从 run 行收集 ``(doc_code, unit_key) -> unit_ids``（引用/检索/gold 三处真值）。"""
    mapping: dict[tuple[str, str], set[str]] = {}

    def add(doc_code: Any, unit_key: Any, unit_ids: Sequence[Any]) -> None:
        if doc_code is None or unit_key is None:
            return
        doc = str(doc_code)
        key = str(unit_key)
        if not doc or not key:
            return
        bucket = mapping.setdefault((doc, key), set())
        bucket.update(str(item) for item in unit_ids if str(item))

    for row in rows:
        outcome = _row_outcome(row)
        if outcome is not None:
            for item in (*_as_list(outcome.get("citations")), *_as_list(outcome.get("retrieved"))):
                if isinstance(item, Mapping):
                    add(item.get("doc_code"), item.get("unit_key"), _as_list(item.get("unit_ids")))
        gold = row.get("gold")
        if isinstance(gold, Mapping):
            for source in _as_list(gold.get("sources")):
                if not isinstance(source, Mapping):
                    continue
                unit_ids = [str(item) for item in _as_list(source.get("unit_ids")) if str(item)]
                unit_keys = [str(item) for item in _as_list(source.get("unit_keys")) if str(item)]
                if len(unit_ids) != len(unit_keys):
                    continue  # 平行数组长度不一致时不猜映射
                for unit_id, unit_key in zip(unit_ids, unit_keys):
                    add(source.get("doc_code"), unit_key, [unit_id])
    return {key: frozenset(value) for key, value in mapping.items()}


def _citation_against_ref(
    ref: Mapping[str, Any],
    citation: Mapping[str, Any],
    unit_map: Mapping[tuple[str, str], frozenset[str]],
) -> bool | None:
    """一条 forbidden 引用是否命中一个引用项；``None`` = 该项无法解析。"""
    doc_code = str(ref.get("doc_code"))
    if str(citation.get("doc_code")) != doc_code:
        return False
    if ref.get("unit_key") is not None:
        unit_key = str(ref["unit_key"])
        cited_key = citation.get("unit_key")
        if cited_key is not None:
            return str(cited_key) == unit_key
        resolved_ids = unit_map.get((doc_code, unit_key))
        if not resolved_ids:
            return None
        cited_ids = {str(item) for item in _as_list(citation.get("unit_ids")) if str(item)}
        if not cited_ids:
            return None
        return bool(cited_ids & set(resolved_ids))
    locator = ref.get("locator")
    actual = citation.get("locator")
    if not isinstance(locator, Mapping) or not locator:
        return None
    if not isinstance(actual, Mapping) or not actual:
        return None
    return all(_same(actual.get(key), value) for key, value in locator.items())


def _match_forbidden(
    ref: Mapping[str, Any],
    citations: Sequence[Mapping[str, Any]],
    unit_map: Mapping[tuple[str, str], frozenset[str]],
) -> tuple[str, dict[str, Any]]:
    """返回 ``matched`` / ``no_match`` / ``unresolved`` 及证据。"""
    doc_code = ref.get("doc_code")
    if doc_code is None or not str(doc_code):
        return "unresolved", {"reason": "missing_doc_code", "ref": dict(ref)}
    doc = str(doc_code)
    has_key = ref.get("unit_key") is not None
    locator = ref.get("locator")
    has_locator = isinstance(locator, Mapping) and bool(locator)
    if not has_key and not has_locator:
        if "record_code" in ref:
            return "unresolved", {
                "reason": "record_code_not_a_resolution_key",
                "ref": dict(ref),
            }
        hits = [
            citation
            for citation in citations
            if str(citation.get("doc_code")) == doc
        ]
        if hits:
            return "matched", {
                "matched_by": "document",
                "citation_unit_ids": [
                    str(item)
                    for citation in hits
                    for item in _as_list(citation.get("unit_ids"))
                    if str(item)
                ],
            }
        return "no_match", {"reason": "no_citation_in_forbidden_document"}

    unresolved = False
    for citation in citations:
        verdict = _citation_against_ref(ref, citation, unit_map)
        if verdict is True:
            return "matched", {
                "matched_by": "unit_key" if has_key else "locator",
                "citation_unit_ids": [
                    str(item) for item in _as_list(citation.get("unit_ids")) if str(item)
                ],
                "citation_unit_key": citation.get("unit_key"),
            }
        if verdict is None:
            unresolved = True
    if unresolved:
        return "unresolved", {
            "reason": "no_unit_level_resolution",
            "ref": dict(ref),
        }
    return "no_match", {"reason": "not_cited"}


# --------------------------------------------------------------------------- #
# 逐门禁判定
# --------------------------------------------------------------------------- #


class _View:
    """一次判定需要的只读上下文。"""

    def __init__(
        self,
        *,
        manifest: Mapping[str, Any],
        rows: tuple[Mapping[str, Any], ...],
        cases: tuple[CaseSpec, ...],
        config: GateConfig,
        traces: _TraceReader,
    ) -> None:
        self.manifest = manifest
        self.rows = rows
        self.rows_by_case = {
            str(row.get("case_id")): row for row in rows if row.get("case_id")
        }
        self.cases = cases
        self.config = config
        self.traces = traces
        self.warnings: list[str] = []
        self.unit_map = _unit_key_map(rows)


def _gate_security_leak(view: _View) -> _GateOutcome:
    gate_id = "security_leak"
    failures: list[GateFailure] = []
    unknowns: list[GateUnknown] = []
    applicable = 0
    patterns = view.config.sensitive_patterns
    for case in view.cases:
        row = view.rows_by_case.get(case.case_id)
        if row is None or _is_ocr_row(row) or _is_error_row(row):
            continue
        forbidden_sources = tuple(case.forbidden_sources)
        forbidden_values = tuple(case.forbidden_values)
        outcome = _row_outcome(row)
        if outcome is None:
            # 有 forbidden 约束 / 敏感模式却拿不到回答与引用：不能把"缺失"当"空文本"，
            # 也无法证明没有泄漏 → unknown（exit 3），不得判 pass（R1-HIGH-1）。
            if forbidden_sources or forbidden_values or patterns:
                applicable += 1
                unknowns.append(
                    GateUnknown(
                        gate_id=gate_id,
                        case_id=case.case_id,
                        check_id="outcome_missing",
                        reason=(
                            "case 有 forbidden 约束 / 敏感模式，但缺少 outcome"
                            "（无法取得回答与引用内容），不得按空文本放行"
                        ),
                        evidence={
                            "forbidden_sources": len(forbidden_sources),
                            "forbidden_values": len(forbidden_values),
                            "sensitive_patterns": len(patterns),
                        },
                    )
                )
            continue
        text = str(outcome.get("text") or "")
        if not forbidden_sources and not forbidden_values and not (patterns and text):
            continue
        applicable += 1
        citations = [
            item
            for item in _as_list(outcome.get("citations") if outcome is not None else ())
            if isinstance(item, Mapping)
        ]
        leaked = [value for value in forbidden_values if check_value(text, value)]
        if leaked:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="forbidden_value",
                    evidence={"leaked_values": leaked, "checked": len(forbidden_values)},
                )
            )
        hits = [pattern for pattern in patterns if re.search(pattern, text)]
        if hits:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="sensitive_pattern",
                    evidence={"patterns": hits},
                )
            )
        for index, ref in enumerate(forbidden_sources):
            verdict, detail = _match_forbidden(ref, citations, view.unit_map)
            if verdict == "matched":
                failures.append(
                    GateFailure(
                        gate_id=gate_id,
                        case_id=case.case_id,
                        check_id="forbidden_source_citation",
                        evidence={"forbidden_index": index, "ref": dict(ref), **detail},
                    )
                )
            elif verdict == "unresolved":
                unknowns.append(
                    GateUnknown(
                        gate_id=gate_id,
                        case_id=case.case_id,
                        check_id="forbidden_ref_unresolved",
                        reason=(
                            "forbidden 引用无法解析到 unit（record_code 不是解析键，"
                            "或引用既无 unit_key 又无非空 locator）"
                        ),
                        evidence={"forbidden_index": index, **detail},
                    )
                )
        if outcome is not None:
            for index, item in enumerate(_as_list(outcome.get("retrieved"))):
                if not isinstance(item, Mapping):
                    continue
                violation = item.get("hard_filter_violation")
                if violation is not None and str(violation) == _EXCLUDED_FORBIDDEN_VIOLATION:
                    failures.append(
                        GateFailure(
                            gate_id=gate_id,
                            case_id=case.case_id,
                            check_id="forbidden_source_retrieved",
                            evidence={
                                "retrieved_index": index,
                                "unit_ids": [
                                    str(value)
                                    for value in _as_list(item.get("unit_ids"))
                                    if str(value)
                                ],
                                "doc_code": item.get("doc_code"),
                            },
                        )
                    )
    return _outcome(
        gate_id,
        failures=failures,
        unknowns=unknowns,
        applicable=applicable,
        detail=(
            "数据集没有 forbidden_sources/forbidden_values 的 case；"
            "跨用户来源与敏感模式无 case 级字段，未覆盖"
        ),
    )


def _gate_hard_filter_signal(
    view: _View, gate_id: str, signal: str, detail: str
) -> _GateOutcome:
    failures: list[GateFailure] = []
    applicable = 0
    for case in view.cases:
        row = view.rows_by_case.get(case.case_id)
        if row is None or _is_ocr_row(row) or _is_error_row(row):
            continue
        outcome = _row_outcome(row)
        if outcome is None:
            continue
        for index, item in enumerate(_as_list(outcome.get("retrieved"))):
            if not isinstance(item, Mapping):
                continue
            violation = item.get("hard_filter_violation")
            if violation is None or str(violation) != signal:
                continue
            applicable += 1
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="retrieved_hard_filter_violation",
                    evidence={
                        "retrieved_index": index,
                        "violation": str(violation),
                        "doc_code": item.get("doc_code"),
                        "unit_ids": [
                            str(value)
                            for value in _as_list(item.get("unit_ids"))
                            if str(value)
                        ],
                        "unit_key": item.get("unit_key"),
                    },
                )
            )
    return _outcome(gate_id, failures=failures, applicable=applicable, detail=detail)


def _gate_conflict_not_rejected(view: _View) -> _GateOutcome:
    gate_id = "conflict_not_rejected"
    failures: list[GateFailure] = []
    unknowns: list[GateUnknown] = []
    applicable = 0
    for case in view.cases:
        if case.expected_kind != "conflict":
            continue
        row = view.rows_by_case.get(case.case_id)
        if row is None or _is_ocr_row(row) or _is_error_row(row):
            continue
        outcome = _row_outcome(row)
        actual = None if outcome is None else outcome.get("kind")
        if not actual:
            unknowns.append(
                GateUnknown(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="outcome_missing",
                    reason="conflict case 缺少 outcome.kind，无法判定是否拒绝冲突",
                    evidence={"expected_kind": case.expected_kind},
                )
            )
            continue
        applicable += 1
        if str(actual) not in _CONFLICT_ACCEPTED_KINDS:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="conflict_not_rejected",
                    evidence={
                        "expected": sorted(_CONFLICT_ACCEPTED_KINDS),
                        "actual": str(actual),
                    },
                )
            )
    return _outcome(
        gate_id,
        failures=failures,
        unknowns=unknowns,
        applicable=applicable,
        detail="数据集没有 expected_kind=conflict 的 case",
    )


def _gate_exact_value_contract(view: _View) -> _GateOutcome:
    """精确值契约：按数据集 ``expected_values`` 在回答文本上**重算**命中（归一化后）。

    不读 run 行里的 ``value_hit`` check：``cases.jsonl`` 的 checks 在 replay 里来自源
    run 自报（T005 LOW-3），硬门禁必须能从数据集 + 本轮回答独立复算。
    ``value_no_fabricated`` 不参与（T004b MEDIUM-1）。
    """
    gate_id = "exact_value_contract"
    failures: list[GateFailure] = []
    unknowns: list[GateUnknown] = []
    applicable = 0
    for case in view.cases:
        # "exact 类" = 数据集 stratum=exact（eval_data_v0_1.md：b0 exact 24 / text 8）。
        # 不能按"有 expected_values"泛化：Q25/Q26 属 text stratum，其 value_hit 未命中是
        # 质量指标（T006b）；若当硬门禁，冻结的干净集永远 exit 1，与 P0 验收
        # "硬门禁非零退出 / 干净集 exit 0" 冲突。
        if case.stratum != "exact" or not case.expected_values or case.should_refuse:
            continue
        row = view.rows_by_case.get(case.case_id)
        if row is None or _is_ocr_row(row) or _is_error_row(row):
            continue
        outcome = _row_outcome(row)
        if outcome is None:
            unknowns.append(
                GateUnknown(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="outcome_missing",
                    reason="exact 类 case 缺少 outcome，无法判定精确值契约",
                    evidence={"expected_values": list(case.expected_values)},
                )
            )
            continue
        applicable += 1
        text = str(outcome.get("text") or "")
        missing = [value for value in case.expected_values if not check_value(text, value)]
        if missing:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="exact_value_miss",
                    evidence={
                        "expected_values": list(case.expected_values),
                        "missing": missing,
                        "answer_chars": len(text),
                    },
                )
            )
    return _outcome(
        gate_id,
        failures=failures,
        unknowns=unknowns,
        applicable=applicable,
        detail="数据集没有 stratum=exact 且带 expected_values 的 case",
    )


def _gate_pagination_contract(view: _View) -> _GateOutcome:
    """分页契约：用数据集 ``expected_pagination`` + 本轮 ``outcome.pagination`` 重算。

    复用 T004b 的契约实现（``scorers._pagination_checks``）以保证同一口径，
    不读 run 行里的 ``pagination_*`` checks（replay 的 checks 来自源 run 自报）。
    """
    gate_id = "pagination_contract"
    failures: list[GateFailure] = []
    unknowns: list[GateUnknown] = []
    applicable = 0
    self_consistent_only: list[str] = []
    for case in view.cases:
        expected = dict(case.expected_pagination or {})
        row = view.rows_by_case.get(case.case_id)
        if row is None or _is_ocr_row(row) or _is_error_row(row):
            continue
        outcome = _row_outcome(row)
        if outcome is None:
            actual: dict[str, Any] = {}
            pagination_invalid = False
        else:
            raw_pagination = outcome.get("pagination")
            if raw_pagination is None:
                actual = {}
                pagination_invalid = False
            elif isinstance(raw_pagination, Mapping):
                actual = dict(raw_pagination)
                pagination_invalid = False
            else:
                # 非 mapping（字符串 / 数组等）→ unknown，不得让 dict(...) 抛未捕获异常
                # 或静默当空分页放行（R1-MEDIUM-2）。
                actual = {}
                pagination_invalid = True
        if pagination_invalid:
            unknowns.append(
                GateUnknown(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="pagination_invalid",
                    reason="outcome.pagination 不是 JSON 对象（mapping），无法判定分页契约",
                    evidence={
                        "actual_type": type(raw_pagination).__name__,
                        "actual": raw_pagination,
                        "expected_pagination": expected,
                    },
                )
            )
            continue
        if not expected and not actual:
            continue
        if outcome is None:
            unknowns.append(
                GateUnknown(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="outcome_missing",
                    reason="分页 case 缺少 outcome，无法判定分页契约",
                    evidence={"expected_pagination": expected},
                )
            )
            continue
        applicable += 1
        if bool(actual) != bool(expected):
            self_consistent_only.append(case.case_id)
        checks = _pagination_checks(
            case, EvalOutcome(kind=str(outcome.get("kind") or ""), pagination=actual)
        )
        failing = [item for item in checks if item.status == "fail"]
        skipped = [item for item in checks if item.status == "skipped"]
        if failing:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="pagination_contract_violation",
                    evidence={
                        "failed_checks": [item.check_id for item in failing],
                        "reasons": {
                            item.check_id: dict(item.evidence) for item in failing
                        },
                        "expected": expected,
                        "actual": actual,
                    },
                )
            )
        elif skipped:
            unknowns.append(
                GateUnknown(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="pagination_check_skipped",
                    reason="分页 case 的分页 check 被跳过，不得当通过",
                    evidence={"checks": [item.check_id for item in skipped], "actual": actual},
                )
            )
    if self_consistent_only:
        view.warnings.append(
            "分页："
            f"{sorted(set(self_consistent_only))} 只校验 total/returned/has_more/next_page "
            "契约自洽；expected_pagination 为 null 或与输出不对齐，不覆盖期望值口径"
        )
    return _outcome(
        gate_id,
        failures=failures,
        unknowns=unknowns,
        applicable=applicable,
        detail="数据集 expected_pagination 全为 null 且无分页输出",
    )


def _gate_citation_required(view: _View) -> _GateOutcome:
    gate_id = "citation_required"
    failures: list[GateFailure] = []
    unknowns: list[GateUnknown] = []
    applicable = 0
    for case in view.cases:
        row = view.rows_by_case.get(case.case_id)
        if row is None or _is_ocr_row(row) or _is_error_row(row):
            continue
        outcome = _row_outcome(row)
        if outcome is None:
            if case.expected_kind == "answer" and not case.should_refuse:
                unknowns.append(
                    GateUnknown(
                        gate_id=gate_id,
                        case_id=case.case_id,
                        check_id="outcome_missing",
                        reason="期望作答的 case 缺少 outcome，无法判定引用",
                        evidence={"expected_kind": case.expected_kind},
                    )
                )
            continue
        kind = outcome.get("kind")
        if not kind:
            # 期望作答却拿不到 kind：无法证明"answer 无引用"，不得当非作答跳过
            # （R1-HIGH-2）。非作答期望的 case 不要求引用，维持 not_applicable。
            if case.expected_kind == "answer" and not case.should_refuse:
                unknowns.append(
                    GateUnknown(
                        gate_id=gate_id,
                        case_id=case.case_id,
                        check_id="outcome_kind_missing",
                        reason=(
                            "期望作答的 case 缺少 outcome.kind，无法判定是否需要引用，"
                            "不得按非作答结局跳过"
                        ),
                        evidence={"expected_kind": case.expected_kind},
                    )
                )
            continue
        if str(kind) != "answer":
            continue  # 非作答结局不要求引用；kind 正确性由质量层负责
        applicable += 1
        citations = [
            item for item in _as_list(outcome.get("citations")) if isinstance(item, Mapping)
        ]
        if not citations:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="citation_missing",
                    evidence={"kind": "answer", "source_hit": _row_checks(row).get("source_hit")},
                )
            )
            continue
        without_units = [
            index for index, item in enumerate(citations) if not _as_list(item.get("unit_ids"))
        ]
        if without_units:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="citation_not_unit_level",
                    evidence={"citation_index": without_units},
                )
            )
            continue
        evidence_units = {
            str(unit)
            for item in _as_list(outcome.get("retrieved"))
            if isinstance(item, Mapping)
            for unit in _as_list(item.get("unit_ids"))
            if str(unit)
        }
        cited_units = {
            str(unit) for item in citations for unit in _as_list(item.get("unit_ids")) if str(unit)
        }
        outside = sorted(cited_units - evidence_units)
        if outside:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="citation_not_in_evidence",
                    evidence={
                        "unit_ids": outside,
                        "evidence_units": len(evidence_units),
                    },
                )
            )
    return _outcome(
        gate_id,
        failures=failures,
        unknowns=unknowns,
        applicable=applicable,
        detail="没有作答结局的 case（无引用要求）",
    )


def _gate_trace_integrity(view: _View, require_trace: bool) -> _GateOutcome:
    gate_id = "trace_integrity"
    if not require_trace:
        return _outcome(
            gate_id,
            detail="require_trace=False：调用方显式关闭 trace 完整性校验",
        )
    unavailable = view.traces.ensure_ready()
    if unavailable is not None:
        return _outcome(
            gate_id,
            unknowns=[
                GateUnknown(
                    gate_id=gate_id,
                    case_id=None,
                    check_id="trace_store_unreadable",
                    reason=unavailable,
                    evidence={"trace_store": str(view.manifest.get("trace_store") or "")},
                )
            ],
        )

    # trace_schema_v0_1.md §8：schema_meta.trace_schema_version 必须等于
    # TRACE_SCHEMA_VERSION，不一致时门禁 fail closed；表/键缺失或不可读 → unknown。
    meta_state, meta_detail = view.traces.schema_meta_version()
    if meta_state == "unavailable":
        return _outcome(
            gate_id,
            unknowns=[
                GateUnknown(
                    gate_id=gate_id,
                    case_id=None,
                    check_id="trace_store_unreadable",
                    reason=meta_detail or "trace store 的 schema_meta 不可读",
                    evidence={
                        "schema_meta_key": "trace_schema_version",
                        "trace_store": str(view.manifest.get("trace_store") or ""),
                    },
                )
            ],
        )
    if meta_state == "mismatch":
        return _outcome(
            gate_id,
            failures=[
                GateFailure(
                    gate_id=gate_id,
                    case_id=None,
                    check_id="store_schema_version_mismatch",
                    evidence={
                        "expected": TRACE_SCHEMA_VERSION,
                        "actual": meta_detail,
                        "source": "schema_meta.trace_schema_version",
                    },
                )
            ],
            detail="trace store 的 schema_meta 版本与契约不一致（fail closed）",
        )

    failures: list[GateFailure] = []
    unknowns: list[GateUnknown] = []
    applicable = 0
    trace_ids: set[str] = set()
    for case in view.cases:
        row = view.rows_by_case.get(case.case_id)
        if row is None or _is_ocr_row(row) or _is_error_row(row):
            continue
        trace_id = row.get("trace_id")
        if not trace_id:
            applicable += 1
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="trace_missing",
                    evidence={"trace_id": None},
                )
            )
            continue
        trace_id = str(trace_id)
        trace_ids.add(trace_id)
        try:
            found = view.traces.get(trace_id)
        except _TraceStoreUnavailable as exc:
            unknowns.append(
                GateUnknown(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="trace_store_unreadable",
                    reason=str(exc),
                    evidence={"trace_id": trace_id},
                )
            )
            continue
        applicable += 1
        if found is None:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="trace_missing",
                    evidence={"trace_id": trace_id},
                )
            )
            continue
        record, span_names = found

        if record.trace_schema_version != TRACE_SCHEMA_VERSION:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="schema_version_mismatch",
                    evidence={
                        "trace_id": trace_id,
                        "expected": TRACE_SCHEMA_VERSION,
                        "actual": record.trace_schema_version,
                    },
                )
            )
            continue

        invalid_fields: list[str] = []
        conditional_attrs: dict[str, Any] = {}
        for name in _JSON_FIELD_NAMES:
            payload = getattr(record, name)
            if payload is None:
                continue
            if not isinstance(payload, str):
                invalid_fields.append(name)
                continue
            try:
                parsed = json.loads(payload)
            except ValueError:
                invalid_fields.append(name)
                continue
            if isinstance(parsed, Mapping):
                for flag in _CONDITIONAL_FLAGS:
                    if flag in parsed:
                        conditional_attrs[flag] = parsed[flag]
        if invalid_fields:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="json_invalid",
                    evidence={"trace_id": trace_id, "fields": sorted(invalid_fields)},
                )
            )
            continue

        mismatched: list[str] = []
        expected_binding: dict[str, Any] = {}
        for trace_field, manifest_field in _TRACE_BINDING:
            expected_value = view.manifest.get(manifest_field)
            expected_binding[trace_field] = expected_value
            actual_value = getattr(record, trace_field)
            if str(actual_value) != str(expected_value):
                mismatched.append(trace_field)
        if record.case_id is not None and str(record.case_id) != case.case_id:
            mismatched.append("case_id")
            expected_binding["case_id"] = case.case_id
        if mismatched:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="version_binding",
                    evidence={
                        "trace_id": trace_id,
                        "mismatched": mismatched,
                        "expected": expected_binding,
                    },
                )
            )
            continue

        if bool(record.replayed) or str(record.status or "") == "replayed":
            # T003a/T003d 遗留：replayed 记录用 annotate(replayed=True) 写启动字段，
            # 不能按产品路径 Span 校验；只校版本绑定与 JSON 结构（已在上方完成）。
            continue

        if not record.path or not record.outcome_kind:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="path_outcome_missing",
                    evidence={
                        "trace_id": trace_id,
                        "path": record.path,
                        "outcome_kind": record.outcome_kind,
                        "status": record.status,
                    },
                )
            )
            continue
        try:
            required = set(
                required_spans(record.path, record.outcome_kind, reason=record.reason)
            )
        except ValueError as exc:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="contract_undefined",
                    evidence={
                        "trace_id": trace_id,
                        "path": record.path,
                        "outcome_kind": record.outcome_kind,
                        "error": str(exc),
                    },
                )
            )
            continue
        required |= set(conditional_required_spans(conditional_attrs))
        missing = sorted(required - set(span_names))
        if missing:
            failures.append(
                GateFailure(
                    gate_id=gate_id,
                    case_id=case.case_id,
                    check_id="required_spans_missing",
                    evidence={
                        "trace_id": trace_id,
                        "path": record.path,
                        "outcome_kind": record.outcome_kind,
                        "reason": record.reason,
                        "missing": missing,
                        "observed": sorted(set(span_names)),
                    },
                )
            )
    if trace_ids and not applicable and not failures:
        unknowns.append(
            GateUnknown(
                gate_id=gate_id,
                case_id=None,
                check_id="no_trace_applicable",
                reason="没有可校验的 trace 行",
                evidence={"trace_ids": sorted(trace_ids)[:5]},
            )
        )
    return _outcome(
        gate_id,
        failures=failures,
        unknowns=unknowns,
        applicable=applicable,
        detail="没有可校验的非 OCR 行",
    )


# --------------------------------------------------------------------------- #
# 数据 / 配置 / 样本
# --------------------------------------------------------------------------- #


def _dataset_path(
    manifest: Mapping[str, Any], explicit: Path | str | None
) -> tuple[Path | None, str | None]:
    if explicit is not None:
        return Path(explicit), None
    suite = str(manifest.get("suite") or "")
    fallback = FROZEN_DATASET_DIR / f"{suite}.jsonl"
    declared = manifest.get("dataset_path")
    if isinstance(declared, str) and declared:
        candidate = Path(declared)
        if candidate.is_file():
            return candidate, None
        if fallback.is_file():
            return fallback, f"run_manifest.dataset_path 不可用，回退冻结数据集 {fallback.name}"
        return None, f"run_manifest.dataset_path 不可用且找不到冻结数据集: {declared}"
    if fallback.is_file():
        return fallback, None
    return None, "run_manifest 缺少 dataset_path 且找不到冻结数据集"


def _gold_reference_unknowns(cases: Sequence[CaseSpec]) -> tuple[list[GateUnknown], list[str]]:
    unknowns: list[GateUnknown] = []
    range_gold: list[str] = []
    for case in cases:
        for index, ref in enumerate((*case.expected_sources, *case.relevant_units)):
            if "record_code" not in ref:
                if not ({"unit_key", "locator"} & set(ref)):
                    range_gold.append(case.case_id)
                continue
            if "unit_key" in ref:
                continue
            locator = ref.get("locator")
            if isinstance(locator, Mapping) and locator:
                continue
            unknowns.append(
                GateUnknown(
                    gate_id="gold",
                    case_id=case.case_id,
                    check_id=(
                        "record_code_empty_locator" if "locator" in ref else "record_code_only_gold"
                    ),
                    reason=(
                        "record_code 不是解析键：gold 引用只有 record_code"
                        + ("+空 locator" if "locator" in ref else "")
                        + "，不得静默按整篇命中"
                    ),
                    evidence={"ref_index": index, "ref": dict(ref)},
                )
            )
    return unknowns, sorted(set(range_gold))


# --------------------------------------------------------------------------- #
# 质量层：观测（分母按指标各自口径）
# --------------------------------------------------------------------------- #

_RETRIEVAL_METRIC_KEYS = frozenset(
    {"Recall@10", "MRR@10", "nDCG@10", "hard_filter_violation_rate", "empty_recall_rate"}
)
_ANSWER_METRIC_KEYS = frozenset(
    {"value_hit", "source_hit", "kind_correct", "citation_precision", "citation_recall"}
)
_REFUSAL_METRIC_KEYS = frozenset(
    {"refusal_recall", "false_refusal_rate", "refusal_precision"}
)
_RUNTIME_METRIC_KEYS = frozenset({"p95_latency_ms", "cost_per_case_cny"})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _row_metric(row: Mapping[str, Any], key: str) -> float | None:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    value = metrics.get(key)
    return float(value) if _is_number(value) else None


def _mean_numbers(values: Iterable[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else None


def _percentile_value(values: Sequence[int], fraction: float) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def _has_gold(case: CaseSpec) -> bool:
    return bool(case.expected_sources or case.relevant_units)


def _outcome_kind(row: Mapping[str, Any]) -> str:
    outcome = _row_outcome(row)
    return "" if outcome is None else str(outcome.get("kind") or "")


def _is_quality_row(row: Mapping[str, Any]) -> bool:
    """质量分母：pass/fail、非 OCR、非 error（与硬门禁 evaluated_count 同基础口径）。"""
    return (
        _row_status(row) in SCORED_ROW_STATUSES
        and not _is_ocr_row(row)
        and not _is_error_row(row)
    )


def _is_refusal_row(row: Mapping[str, Any]) -> bool:
    """拒答指标：在质量行基础上排除 error / service_error / knowledge_changed。"""
    return _is_quality_row(row) and _outcome_kind(row) not in REFUSAL_EXCLUDED_KINDS


def _is_ocr_case(case: CaseSpec) -> bool:
    return bool(case.requires_ocr) or case.stratum == "ocr"


def _quality_strata(cases: Sequence[CaseSpec]) -> tuple[str, ...]:
    strata = sorted({case.stratum for case in cases if not _is_ocr_case(case)})
    return (QUALITY_ALL_STRATUM, *strata)


def _level_pairs(
    cases: Sequence[CaseSpec], rows: Sequence[Mapping[str, Any]], level: str
) -> list[tuple[CaseSpec, Mapping[str, Any]]]:
    return [
        (case, row)
        for case, row in zip(cases, rows)
        if not _is_ocr_case(case)
        and (level == QUALITY_ALL_STRATUM or case.stratum == level)
    ]


def _observe_metric(
    spec: MetricSpec,
    cases: Sequence[CaseSpec],
    rows: Sequence[Mapping[str, Any]],
    level: str,
) -> _Observation:
    pairs = _level_pairs(cases, rows, level)
    name = spec.name
    group = spec.group

    if group == "retrieval":
        dataset_sample = sum(1 for case, _ in pairs if _has_gold(case))
        eligible = [
            (case, row) for case, row in pairs if _has_gold(case) and _is_quality_row(row)
        ]
        denominator = len(eligible)
        if name not in _RETRIEVAL_METRIC_KEYS:
            return _Observation(None, 0, dataset_sample, "gold_cases_non_ocr", "cases.jsonl",
                                problem="unknown_metric")
        if name == "hard_filter_violation_rate":
            retrieved = sum(int(_row_metric(row, "retrieved_units") or 0) for _, row in eligible)
            violations = sum(
                int(_row_metric(row, "hard_filter_violations") or 0) for _, row in eligible
            )
            observed = (violations / retrieved) if retrieved else None
        else:
            key = "empty_recall" if name == "empty_recall_rate" else name
            observed = _mean_numbers(_row_metric(row, key) for _, row in eligible)
        return _Observation(observed, denominator, dataset_sample, "gold_cases_non_ocr", "cases.jsonl")

    if group == "answer":
        dataset_sample = len(pairs)
        eligible = [row for _, row in pairs if _is_quality_row(row)]
        if name not in _ANSWER_METRIC_KEYS:
            return _Observation(None, 0, dataset_sample, "scored_cases_non_ocr", "cases.jsonl",
                                problem="unknown_metric")
        observed = _mean_numbers(_row_metric(row, name) for row in eligible)
        return _Observation(observed, len(eligible), dataset_sample, "scored_cases_non_ocr",
                            "cases.jsonl")

    if group == "refusal":
        eligible = [
            (case, row) for case, row in pairs if _is_refusal_row(row)
        ]
        should = [(case, row) for case, row in eligible if case.should_refuse]
        answerable = [(case, row) for case, row in eligible if not case.should_refuse]
        refused = [(case, row) for case, row in eligible if bool(row.get("refused"))]
        if name == "refusal_recall":
            dataset_sample = sum(1 for case, _ in pairs if case.should_refuse)
            hits = sum(1 for _, row in should if bool(row.get("refused")))
            missed = len(should) - hits
            observed = (hits / (hits + missed)) if (hits + missed) else None
            return _Observation(observed, len(should), dataset_sample, "should_refuse_cases",
                                "cases.jsonl(refusal_eligible)")
        if name == "false_refusal_rate":
            dataset_sample = sum(1 for case, _ in pairs if not case.should_refuse)
            false_positives = sum(1 for _, row in answerable if bool(row.get("refused")))
            true_negatives = len(answerable) - false_positives
            observed = (
                false_positives / (false_positives + true_negatives)
                if (false_positives + true_negatives)
                else None
            )
            return _Observation(observed, len(answerable), dataset_sample, "answerable_cases",
                                "cases.jsonl(refusal_eligible)")
        if name == "refusal_precision":
            true_positives = sum(1 for case, _ in refused if case.should_refuse)
            observed = (true_positives / len(refused)) if refused else None
            return _Observation(observed, len(refused), len(pairs), "refused_cases",
                                "cases.jsonl(refusal_eligible)")
        return _Observation(None, 0, len(pairs), "unknown_refusal_metric", "cases.jsonl",
                            problem="unknown_metric")

    if group == "runtime":
        dataset_sample = len(pairs)
        eligible = [row for _, row in pairs if _is_quality_row(row)]
        if name == "p95_latency_ms":
            values = [
                int(row["latency_ms"])
                for row in eligible
                if _is_number(row.get("latency_ms"))
            ]
            return _Observation(
                _percentile_value(values, 0.95), len(values), dataset_sample, "latency_samples",
                "cases.jsonl",
            )
        if name == "cost_per_case_cny":
            costs = [float(row["cost_cny"]) for row in eligible if _is_number(row.get("cost_cny"))]
            observed = (sum(costs) / len(costs)) if costs else None
            return _Observation(observed, len(costs), dataset_sample, "cost_samples", "cases.jsonl")
        return _Observation(None, 0, dataset_sample, "unknown_runtime_metric", "cases.jsonl",
                            problem="unknown_metric")

    return _Observation(None, 0, len(pairs), "unknown_metric_group", "cases.jsonl",
                        problem="unknown_metric_group")


def _summary_payload(run: RunResult) -> tuple[dict[str, Any], bool]:
    """读 run 的 summary（``RunResult.summary``，缺失时回退 ``summary.json``）。

    只给质量层用；硬门禁仍只读 ``cases.jsonl`` / 数据集 / trace（T006a 约束）。
    """
    summary = dict(run.summary) if isinstance(run.summary, Mapping) else {}
    metrics = summary.get("metrics")
    if isinstance(metrics, Mapping):
        return summary, True
    out_dir = getattr(run, "out_dir", None)
    path = Path(out_dir) / "summary.json" if out_dir is not None else None
    if path is not None and path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            loaded = None
        if isinstance(loaded, Mapping):
            summary = dict(loaded)
            if isinstance(summary.get("metrics"), Mapping):
                return summary, True
    return summary, False


def _with_summary(
    spec: MetricSpec,
    level: str,
    observation: _Observation,
    summary_payload: Mapping[str, Any],
    has_summary_metrics: bool,
    warnings: list[str],
) -> _Observation:
    if level != QUALITY_ALL_STRATUM or not has_summary_metrics:
        return observation
    metrics = summary_payload.get("metrics")
    if not isinstance(metrics, Mapping):  # pragma: no cover - 调用方已校验
        return observation
    if spec.group == "refusal":
        # 拒答口径必须排除 service_error / knowledge_changed；summary 由 runner 聚合时
        # 不做该排除，因此 all 级也按 cases.jsonl 重算（T004b MEDIUM-2）。
        summary_value = metrics.get(spec.name)
        if (
            _is_number(summary_value)
            and observation.observed is not None
            and abs(float(summary_value) - observation.observed) > 1e-9
        ):
            warnings.append(
                f"summary.json 的拒答指标 {spec.name} 未按 service_error/knowledge_changed "
                "排除口径聚合，已按 cases.jsonl 重算"
            )
        return observation
    if spec.name not in metrics:
        return replace(
            observation,
            observed=None,
            source="summary.json",
            present=False,
            notes=(*observation.notes, "summary.json 缺少该指标"),
        )
    value = metrics.get(spec.name)
    if value is None:
        return replace(observation, observed=None, source="summary.json", present=True)
    if not _is_number(value):
        return replace(
            observation,
            observed=None,
            source="summary.json",
            present=False,
            problem="invalid_summary_metric",
        )
    if (
        observation.observed is not None
        and abs(float(value) - observation.observed) > 1e-9
    ):
        warnings.append(
            f"summary.json 的 {spec.name} 与 cases.jsonl 重算不一致"
            f"（{value} != {observation.observed}），all 级以 summary.json 为准"
        )
    return replace(observation, observed=float(value), source="summary.json")


def _quality_observations(
    config: GateConfig,
    cases: Sequence[CaseSpec],
    rows: Sequence[Mapping[str, Any]],
    summary_payload: Mapping[str, Any],
    has_summary_metrics: bool,
    warnings: list[str],
) -> dict[tuple[str, str], _Observation]:
    observations: dict[tuple[str, str], _Observation] = {}
    for level in _quality_strata(cases):
        for spec in config.metrics:
            observation = _observe_metric(spec, cases, rows, level)
            observations[(spec.name, level)] = _with_summary(
                spec, level, observation, summary_payload, has_summary_metrics, warnings
            )
    return observations


def _value_no_fabricated_diagnostics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """``value_no_fabricated`` 只作诊断字段，不参与质量判定与退出码（T004b MEDIUM-1）。"""
    checked = 0
    failing: list[str] = []
    for row in rows:
        for item in _as_list(row.get("checks")):
            if not isinstance(item, Mapping) or item.get("check_id") != "value_no_fabricated":
                continue
            checked += 1
            if str(item.get("status") or "") == "fail":
                failing.append(str(row.get("case_id") or ""))
    return {
        "status": "diagnostic_only",
        "participates_in_gate": False,
        "checked_cases": checked,
        "fail_cases": failing,
        "note": (
            "value_no_fabricated 是诊断字段（T004b MEDIUM-1）：不进入质量判定、"
            "不改变退出码，也不得与质量指标混算"
        ),
    }


# --------------------------------------------------------------------------- #
# 质量层：判定
# --------------------------------------------------------------------------- #


def _status_from_checks(
    checks: Sequence[QualityCheck], waived_kinds: Iterable[str] = ()
) -> str:
    waived = set(waived_kinds)
    has_fail = False
    has_unknown = False
    has_waived_fail = False
    for check in checks:
        if check.status == "fail":
            if check.kind in waived:
                has_waived_fail = True
            else:
                has_fail = True
        elif check.status == "unknown":
            has_unknown = True
    if has_fail:
        return QUALITY_STATUS_FAIL
    if has_unknown:
        return QUALITY_STATUS_UNKNOWN
    if has_waived_fail:
        return QUALITY_STATUS_WAIVED
    return QUALITY_STATUS_PASS


def _failure_from_check(
    spec: MetricSpec, level: str, check: QualityCheck, observation: _Observation
) -> GateFailure:
    evidence = {
        "metric": spec.name,
        "group": spec.group,
        "stratum": level,
        "observed": check.observed,
        "threshold": check.threshold,
        "denominator": check.denominator,
        "basis": observation.basis,
        **dict(check.detail),
    }
    return GateFailure(
        gate_id=f"quality:{spec.name}",
        case_id=None,
        check_id=check.kind,
        evidence=evidence,
    )


def _regression_check(
    spec: MetricSpec,
    level: str,
    observation: _Observation,
    context: _BaselineContext | None,
    identity: Mapping[str, Any],
) -> QualityCheck:
    threshold = spec.max_regression_pp
    if context is None:
        return QualityCheck(
            "max_regression_pp",
            "skipped",
            observed=observation.observed,
            threshold=threshold,
            denominator=observation.denominator,
            detail={"reason": "no_baseline", "policy": "首次建立 baseline 只用绝对阈值"},
        )
    if context.error:
        return QualityCheck(
            "max_regression_pp",
            "unknown",
            observed=observation.observed,
            threshold=threshold,
            denominator=observation.denominator,
            detail={"reason": "baseline_unusable", "error": context.error},
        )
    if context.pipeline_version != str(identity.get("pipeline_version") or ""):
        return QualityCheck(
            "max_regression_pp",
            "unknown",
            observed=observation.observed,
            threshold=threshold,
            denominator=observation.denominator,
            detail={
                "reason": "cross_pipeline_version",
                "baseline_pipeline_version": context.pipeline_version,
                "pipeline_version": identity.get("pipeline_version"),
                "note": "设计 §8.3：跨版本只分析、不放行；max_regression_pp 不生效",
            },
        )
    if context.suite != str(identity.get("suite") or ""):
        return QualityCheck(
            "max_regression_pp",
            "unknown",
            observed=observation.observed,
            threshold=threshold,
            denominator=observation.denominator,
            detail={
                "reason": "baseline_suite_mismatch",
                "baseline_suite": context.suite,
                "suite": identity.get("suite"),
            },
        )
    if context.dataset_version != str(identity.get("dataset_version") or ""):
        return QualityCheck(
            "max_regression_pp",
            "unknown",
            observed=observation.observed,
            threshold=threshold,
            denominator=observation.denominator,
            detail={
                "reason": "baseline_dataset_mismatch",
                "baseline_dataset_version": context.dataset_version,
                "dataset_version": identity.get("dataset_version"),
            },
        )
    baseline_observation = context.observations.get((spec.name, level))
    if baseline_observation is None or baseline_observation.observed is None:
        return QualityCheck(
            "max_regression_pp",
            "unknown",
            observed=observation.observed,
            threshold=threshold,
            denominator=observation.denominator,
            detail={"reason": "baseline_metric_missing", "stratum": level},
        )
    if observation.observed is None:
        return QualityCheck(
            "max_regression_pp",
            "unknown",
            observed=None,
            threshold=threshold,
            denominator=observation.denominator,
            detail={"reason": "observed_missing", "stratum": level},
        )
    baseline_value = baseline_observation.observed
    current_value = observation.observed
    if spec.direction == "higher_is_better":
        delta_pp = (baseline_value - current_value) * 100
    else:
        delta_pp = (current_value - baseline_value) * 100
    status = "fail" if delta_pp > threshold else "pass"
    return QualityCheck(
        "max_regression_pp",
        status,
        observed=current_value,
        threshold=threshold,
        denominator=observation.denominator,
        detail={
            "reason": "max_regression_pp_exceeded" if status == "fail" else "within_tolerance",
            "baseline_observed": baseline_value,
            "delta_pp": delta_pp,
            "baseline_run_id": context.run_id,
            "direction": spec.direction,
        },
    )


def _metric_result(
    spec: MetricSpec,
    level: str,
    observation: _Observation,
    config: GateConfig,
    context: _BaselineContext | None,
    identity: Mapping[str, Any],
) -> tuple[QualityMetricResult, list[GateFailure]]:
    def build(status: str, checks: Sequence[QualityCheck]) -> tuple[QualityMetricResult, list[GateFailure]]:
        failures = [
            _failure_from_check(spec, level, check, observation)
            for check in checks
            if check.status == "fail"
        ]
        return (
            QualityMetricResult(
                metric=spec.name,
                group=spec.group,
                stratum=level,
                direction=spec.direction,
                observed=observation.observed,
                denominator=observation.denominator,
                dataset_sample=observation.dataset_sample,
                denominator_basis=observation.basis,
                source=observation.source,
                status=status,
                checks=tuple(checks),
                notes=observation.notes,
            ),
            failures,
        )

    if observation.dataset_sample == 0:
        check = QualityCheck(
            "applicability",
            "not_applicable",
            denominator=0,
            detail={
                "reason": "no_applicable_dataset_case",
                "dataset_sample": 0,
                "basis": observation.basis,
            },
        )
        return build(QUALITY_STATUS_NOT_APPLICABLE, [check])

    if str(config.status) != QUALITY_APPROVED_STATUS:
        check = QualityCheck(
            "approval",
            "unknown",
            observed=observation.observed,
            denominator=observation.denominator,
            detail={
                "reason": "thresholds_unapproved",
                "config_status": config.status,
                "approval_owner": "T009 human gate",
            },
        )
        return build(QUALITY_STATUS_UNKNOWN, [check])

    if observation.problem is not None:
        check = QualityCheck(
            observation.problem,
            "unknown",
            detail={
                "reason": observation.problem,
                "metric": spec.name,
                "group": spec.group,
            },
        )
        return build(QUALITY_STATUS_UNKNOWN, [check])

    checks: list[QualityCheck] = []
    if not observation.present:
        checks.append(
            QualityCheck(
                "metric_missing",
                "unknown",
                observed=observation.observed,
                denominator=observation.denominator,
                detail={"reason": "summary_metric_missing", "source": observation.source},
            )
        )
        return build(QUALITY_STATUS_UNKNOWN, checks)

    if spec.min_sample is None:
        checks.append(
            QualityCheck(
                "min_sample",
                "unknown",
                denominator=observation.denominator,
                detail={"reason": "min_sample_missing", "basis": observation.basis},
            )
        )
    elif observation.denominator == 0:
        checks.append(
            QualityCheck(
                "min_sample",
                "unknown",
                denominator=0,
                detail={
                    "reason": "no_eligible_sample",
                    "basis": observation.basis,
                    "dataset_sample": observation.dataset_sample,
                },
            )
        )
    elif observation.denominator < spec.min_sample:
        checks.append(
            QualityCheck(
                "min_sample",
                "unknown",
                threshold=float(spec.min_sample),
                denominator=observation.denominator,
                detail={
                    "reason": "min_sample_not_met",
                    "basis": observation.basis,
                    "metric_min_sample": spec.min_sample,
                    "note": "质量层分母按指标各自口径，不复用 hard_gate_min_sample",
                },
            )
        )
    else:
        checks.append(
            QualityCheck(
                "min_sample",
                "pass",
                threshold=float(spec.min_sample),
                denominator=observation.denominator,
                detail={"basis": observation.basis},
            )
        )

    has_threshold = any(
        value is not None
        for value in (spec.absolute_min, spec.absolute_max, spec.max_regression_pp)
    )
    if not has_threshold:
        checks.append(
            QualityCheck(
                "threshold",
                "unknown",
                denominator=observation.denominator,
                detail={"reason": "no_threshold_configured", "metric": spec.name},
            )
        )
    elif observation.observed is None:
        checks.append(
            QualityCheck(
                "observed",
                "unknown",
                denominator=observation.denominator,
                detail={"reason": "observed_missing", "basis": observation.basis},
            )
        )
    else:
        if spec.absolute_min is not None:
            status = "fail" if observation.observed < spec.absolute_min else "pass"
            checks.append(
                QualityCheck(
                    "absolute_min",
                    status,
                    observed=observation.observed,
                    threshold=spec.absolute_min,
                    denominator=observation.denominator,
                    detail={"direction": spec.direction, "basis": observation.basis},
                )
            )
        if spec.absolute_max is not None:
            status = "fail" if observation.observed > spec.absolute_max else "pass"
            checks.append(
                QualityCheck(
                    "absolute_max",
                    status,
                    observed=observation.observed,
                    threshold=spec.absolute_max,
                    denominator=observation.denominator,
                    detail={"direction": spec.direction, "basis": observation.basis},
                )
            )
        if spec.max_regression_pp is not None:
            checks.append(
                _regression_check(spec, level, observation, context, identity)
            )
    return build(_status_from_checks(checks), checks)


def _coerce_quality_policy(quality: Any) -> QualityPolicy | None:
    if quality is None or quality is False:
        return None
    if quality is True:
        return QualityPolicy()
    if isinstance(quality, QualityPolicy):
        for item in quality.waivers:
            if not isinstance(item, QualityWaiver):
                raise ValueError("QualityPolicy.waivers 必须是 QualityWaiver 实例")
        return quality
    raise TypeError("quality 只接受 bool 或 QualityPolicy")


def _load_baseline_run(baseline: Any) -> tuple[RunResult | None, str | None]:
    if isinstance(baseline, RunResult):
        return baseline, None
    if isinstance(baseline, (str, Path)):
        try:
            return load_run_result(baseline), None
        except (OSError, ValueError) as exc:
            return None, f"baseline run 目录不可读: {exc}"
    return None, "baseline 必须是 RunResult 或 run 目录路径"


def _build_baseline_context(
    baseline: Any,
    config: GateConfig,
    warnings: list[str],
) -> _BaselineContext | None:
    if baseline is None:
        return None
    run, error = _load_baseline_run(baseline)
    if run is None:
        warnings.append(f"baseline 不可用：{error}")
        return _BaselineContext(None, error or "baseline_unusable", {}, None, None, None, None)
    manifest = _manifest_payload(run)
    rows = tuple(row for row in (run.cases or ()) if isinstance(row, Mapping))
    target, note = _dataset_path(manifest, None)
    if target is None:
        reason = note or "baseline 数据集不可用"
        warnings.append(f"baseline 不可用：{reason}")
        return _BaselineContext(
            run, reason, {}, str(manifest.get("run_id") or ""),
            str(manifest.get("pipeline_version") or ""),
            str(manifest.get("suite") or ""),
            str(manifest.get("dataset_version") or ""),
        )
    try:
        cases = tuple(load_cases(target))
    except (OSError, ValueError) as exc:
        reason = f"baseline 数据集无法解析: {exc}"
        warnings.append(f"baseline 不可用：{reason}")
        return _BaselineContext(
            run, reason, {}, str(manifest.get("run_id") or ""),
            str(manifest.get("pipeline_version") or ""),
            str(manifest.get("suite") or ""),
            str(manifest.get("dataset_version") or ""),
        )
    if [case.case_id for case in cases] != [str(row.get("case_id") or "") for row in rows]:
        reason = "baseline 数据集 case 与 cases.jsonl 行不一致"
        warnings.append(f"baseline 不可用：{reason}")
        return _BaselineContext(
            run, reason, {}, str(manifest.get("run_id") or ""),
            str(manifest.get("pipeline_version") or ""),
            str(manifest.get("suite") or ""),
            str(manifest.get("dataset_version") or ""),
        )
    summary_payload, has_metrics = _summary_payload(run)
    baseline_warnings: list[str] = []
    observations = _quality_observations(
        config, cases, rows, summary_payload, has_metrics, baseline_warnings
    )
    for message in baseline_warnings:
        warnings.append(f"baseline: {message}")
    return _BaselineContext(
        run,
        None,
        observations,
        str(manifest.get("run_id") or ""),
        str(manifest.get("pipeline_version") or ""),
        str(manifest.get("suite") or ""),
        str(manifest.get("dataset_version") or ""),
    )


def _evaluate_quality(
    run: RunResult,
    manifest: Mapping[str, Any],
    cases: Sequence[CaseSpec],
    rows: Sequence[Mapping[str, Any]],
    config: GateConfig,
    policy: QualityPolicy,
    baseline: Any,
) -> QualityResult:
    warnings: list[str] = []
    summary_payload, has_summary_metrics = _summary_payload(run)
    if not has_summary_metrics:
        warnings.append(
            "summary.json 缺少 metrics：质量观测按 cases.jsonl 重算（缺失指标仍显式 unknown）"
        )
    observations = _quality_observations(
        config, cases, rows, summary_payload, has_summary_metrics, warnings
    )
    context = _build_baseline_context(baseline, config, warnings)
    strata = _quality_strata(cases)
    identity = {
        "pipeline_version": manifest.get("pipeline_version"),
        "suite": manifest.get("suite"),
        "dataset_version": manifest.get("dataset_version"),
    }

    results: list[QualityMetricResult] = []
    failures: list[GateFailure] = []
    for level in strata:
        for spec in config.metrics:
            result, level_failures = _metric_result(
                spec,
                level,
                observations[(spec.name, level)],
                config,
                context,
                identity,
            )
            results.append(result)
            failures.extend(level_failures)

    waived_entries: list[dict[str, Any]] = []
    waived_keys: set[tuple[str, str, str]] = set()
    unwaived: list[GateFailure] = []
    used_waivers: set[int] = set()
    for failure in failures:
        metric = failure.gate_id.split(":", 1)[1] if ":" in failure.gate_id else failure.gate_id
        stratum = str(failure.evidence.get("stratum") or "")
        match_index = None
        for index, waiver in enumerate(policy.waivers):
            if waiver.matches(metric, stratum):
                match_index = index
                break
        if match_index is None:
            unwaived.append(failure)
            continue
        waiver = policy.waivers[match_index]
        used_waivers.add(match_index)
        waived_keys.add((metric, stratum, failure.check_id))
        waived_entries.append(
            {
                "metric": metric,
                "stratum": stratum,
                "check_id": failure.check_id,
                "reason": waiver.reason,
                "approver": waiver.approver,
                "threshold": failure.evidence.get("threshold"),
                "observed": failure.evidence.get("observed"),
            }
        )
        warnings.append(
            f"质量 waiver：metric={metric} stratum={stratum} check={failure.check_id} "
            f"reason={waiver.reason} approver={waiver.approver}"
        )
    for index, waiver in enumerate(policy.waivers):
        if index not in used_waivers:
            warnings.append(
                "质量 waiver 未命中任何失败："
                f"metric={waiver.metric or '*'} stratum={waiver.stratum or '*'} "
                f"reason={waiver.reason} approver={waiver.approver}"
            )

    updated: list[QualityMetricResult] = []
    for result in results:
        kinds = {kind for metric, stratum, kind in waived_keys
                 if metric == result.metric and stratum == result.stratum}
        updated.append(replace(result, status=_status_from_checks(result.checks, kinds)))

    unknowns: list[GateUnknown] = []
    for result in updated:
        for check in result.checks:
            if check.status != "unknown":
                continue
            reason = str(check.detail.get("reason") or check.kind)
            unknowns.append(
                GateUnknown(
                    gate_id=f"quality:{result.metric}",
                    case_id=None,
                    check_id=reason,
                    reason=reason,
                    evidence={
                        "metric": result.metric,
                        "group": result.group,
                        "stratum": result.stratum,
                        "check_kind": check.kind,
                        "observed": check.observed,
                        "denominator": check.denominator,
                        "basis": result.denominator_basis,
                        "threshold": check.threshold,
                        **dict(check.detail),
                    },
                )
            )

    if not config.metrics:
        unknowns.append(
            GateUnknown(
                gate_id="quality",
                case_id=None,
                check_id="no_metrics_configured",
                reason="gate 配置没有质量指标：无法声称质量达标",
                evidence={"gc": config.gate_version, "status": config.status},
            )
        )

    statuses = [item.status for item in updated]
    if unwaived:
        status = QUALITY_STATUS_FAIL
    elif QUALITY_STATUS_UNKNOWN in statuses or not config.metrics:
        status = QUALITY_STATUS_UNKNOWN
    elif all(item == QUALITY_STATUS_NOT_APPLICABLE for item in statuses):
        status = QUALITY_STATUS_UNKNOWN
        unknowns.append(
            GateUnknown(
                gate_id="quality",
                case_id=None,
                check_id="no_applicable_metric",
                reason="所有质量指标在本数据集上都没有适用样本：不得当作质量通过",
                evidence={"strata": list(strata), "metrics": [item.metric for item in updated]},
            )
        )
    elif QUALITY_STATUS_WAIVED in statuses:
        status = QUALITY_STATUS_PASS_WITH_WAIVERS
    else:
        status = QUALITY_STATUS_PASS

    stratum_status: dict[str, str] = {}
    for level in strata:
        level_statuses = [item.status for item in updated if item.stratum == level]
        if not level_statuses:
            stratum_status[level] = QUALITY_STATUS_NOT_APPLICABLE
        elif QUALITY_STATUS_FAIL in level_statuses:
            stratum_status[level] = QUALITY_STATUS_FAIL
        elif QUALITY_STATUS_UNKNOWN in level_statuses:
            stratum_status[level] = QUALITY_STATUS_UNKNOWN
        elif all(item == QUALITY_STATUS_NOT_APPLICABLE for item in level_statuses):
            stratum_status[level] = QUALITY_STATUS_NOT_APPLICABLE
        elif QUALITY_STATUS_WAIVED in level_statuses:
            stratum_status[level] = QUALITY_STATUS_PASS_WITH_WAIVERS
        else:
            stratum_status[level] = QUALITY_STATUS_PASS

    return QualityResult(
        status=status,
        metrics=tuple(updated),
        strata=strata,
        stratum_status=stratum_status,
        failures=tuple(unwaived),
        unknowns=tuple(unknowns),
        waived=tuple(waived_entries),
        diagnostics={"value_no_fabricated": _value_no_fabricated_diagnostics(rows)},
        warnings=tuple(warnings),
        config_status=str(config.status),
        gate_config_hash=config.config_hash,
        baseline_run_id=None if context is None else context.run_id,
        baseline_pipeline_version=None if context is None else context.pipeline_version,
    )


# --------------------------------------------------------------------------- #
# 校准提案（calibrate_gate）与 run 产物读取
# --------------------------------------------------------------------------- #


def _read_json_file(path: Path, label: str) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} 不可读 {path}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} 不是合法 UTF-8 JSON {path}: {exc}") from exc


def load_run_result(run_dir: Path | str) -> RunResult:
    """从 run 目录读取三件套（只读）；失败抛 ``ValueError``（fail closed）。

    P1 T108：holdout **聚合** run（``holdout_details=false``）按契约不写 ``cases.jsonl``，
    这里允许缺该文件并返回空行（gate 只走聚合判定）；若聚合 run 目录里出现
    ``cases.jsonl``，说明产物被改动/泄漏，直接拒绝。
    """
    target = Path(run_dir)
    manifest_payload = _read_json_file(target / "run_manifest.json", "run_manifest.json")
    if not isinstance(manifest_payload, Mapping):
        raise ValueError("run_manifest.json 必须是 JSON 对象")
    manifest = RunManifest.from_dict(manifest_payload)
    cases_path = target / "cases.jsonl"
    holdout_aggregate = manifest.suite == HOLDOUT_SUITE and not manifest.holdout_details
    if holdout_aggregate:
        if cases_path.exists():
            raise ValueError(
                "holdout 聚合 run 不应包含 cases.jsonl（逐题详情未开启）；产物不一致，拒绝读取"
            )
        rows: list[dict[str, Any]] = []
    else:
        try:
            text = cases_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cases.jsonl 不可读: {exc}") from exc
        rows = []
        for line_number, line in enumerate(text.split("\n"), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"cases.jsonl 第 {line_number} 行 JSON 非法: {exc.msg}") from exc
            if not isinstance(item, Mapping):
                raise ValueError(f"cases.jsonl 第 {line_number} 行必须是对象")
            rows.append(dict(item))
    summary = _read_json_file(target / "summary.json", "summary.json")
    if not isinstance(summary, Mapping):
        raise ValueError("summary.json 必须是 JSON 对象")
    return RunResult(
        manifest=manifest,
        out_dir=target,
        cases=tuple(rows),
        summary=dict(summary),
    )


def _suggest_thresholds(
    spec: MetricSpec, observation: _Observation
) -> tuple[dict[str, Any], str]:
    """校准建议值（只建议，不审批）：0–1 比率类留 2pp 余量 + 2pp 回退容忍。"""
    min_sample = observation.denominator if observation.denominator > 0 else None
    if observation.observed is None:
        return (
            {
                "min_sample": min_sample,
                "absolute_min": None,
                "absolute_max": None,
                "max_regression_pp": None,
            },
            "无观测值：先补齐可评分样本，再由人工决定阈值",
        )
    value = float(observation.observed)
    if spec.group == "runtime" or not (0.0 <= value <= 1.0):
        return (
            {
                "min_sample": min_sample,
                "absolute_min": None,
                "absolute_max": None,
                "max_regression_pp": None,
            },
            "非 0–1 比率指标：绝对阈值与 pp 回退需人工按 SLA / 成本预算审批",
        )
    if spec.direction == "higher_is_better":
        absolute_min: float | None = round(max(0.0, value - PROPOSAL_ABSOLUTE_SLACK), 4)
        absolute_max: float | None = None
    else:
        absolute_min = None
        absolute_max = round(min(1.0, value + PROPOSAL_ABSOLUTE_SLACK), 4)
    return (
        {
            "min_sample": min_sample,
            "absolute_min": absolute_min,
            "absolute_max": absolute_max,
            "max_regression_pp": PROPOSAL_MAX_REGRESSION_PP,
        },
        "按实测值留 2 个百分点审批余量；回退容忍 2pp（仅同 pipeline_version 生效）",
    )


def calibrate_gate(
    run: RunResult,
    config: GateConfig | None = None,
    *,
    baseline: Any | None = None,
) -> GateProposal:
    """从一次真实 run 生成 :class:`GateProposal`；**只读**，绝不改写 gate 配置。

    - 观测值按 stratum + ``all`` 记录（分母按指标各自口径）；
    - 建议阈值由 :func:`_suggest_thresholds` 的显式规则给出，``status`` 恒为
      ``unapproved``（审批属 T009 人工门）；
    - ``gate_config_hash`` 绑定生成提案时使用的配置字节。
    """
    if not isinstance(run, RunResult):
        raise TypeError("calibrate_gate 需要 RunResult")
    manifest = _manifest_payload(run)
    rows = tuple(row for row in (run.cases or ()) if isinstance(row, Mapping))
    resolved = config if config is not None else load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    if not isinstance(resolved, GateConfig):
        raise TypeError("calibrate_gate 的 config 必须是 GateConfig")
    target, note = _dataset_path(manifest, None)
    if target is None:
        raise ValueError(f"校准需要可解析的数据集: {note or 'dataset_unavailable'}")
    cases = tuple(load_cases(target))
    if [case.case_id for case in cases] != [str(row.get("case_id") or "") for row in rows]:
        raise ValueError("数据集 case 与 cases.jsonl 行不一致，不能作为校准输入")

    summary_payload, has_summary_metrics = _summary_payload(run)
    warnings: list[str] = []
    if not has_summary_metrics:
        warnings.append("summary.json 缺少 metrics：观测按 cases.jsonl 重算")
    observations = _quality_observations(
        resolved, cases, rows, summary_payload, has_summary_metrics, warnings
    )
    strata = _quality_strata(cases)
    metric_rows: list[dict[str, Any]] = []
    for level in strata:
        for spec in resolved.metrics:
            observation = observations[(spec.name, level)]
            suggested, rationale = _suggest_thresholds(spec, observation)
            metric_rows.append(
                {
                    "metric": spec.name,
                    "group": spec.group,
                    "direction": spec.direction,
                    "stratum": level,
                    "observed": observation.observed,
                    "denominator": observation.denominator,
                    "dataset_sample": observation.dataset_sample,
                    "denominator_basis": observation.basis,
                    "source": observation.source,
                    "status": "unapproved",
                    "suggested": suggested,
                    "rationale": rationale,
                }
            )

    baseline_block: dict[str, Any] | None = None
    if baseline is not None:
        context = _build_baseline_context(baseline, resolved, warnings)
        if context is None or context.error or context.run is None:
            baseline_block = {
                "usable": False,
                "reason": None if context is None else (context.error or "baseline_unusable"),
            }
        else:
            baseline_block = {
                "usable": True,
                "run_id": context.run_id,
                "pipeline_version": context.pipeline_version,
                "suite": context.suite,
                "dataset_version": context.dataset_version,
                "same_pipeline_version": context.pipeline_version
                == str(manifest.get("pipeline_version") or ""),
            }

    notes = (
        "校准提案（T006b）：观测值 + 建议阈值 + gate_config_hash + run_id；"
        "status 恒为 unapproved，阈值必须由主人在 T009 人工门审批后才能写入 gate 配置。"
        f"绝对阈值建议规则：0–1 比率类指标留 {PROPOSAL_ABSOLUTE_SLACK:.2f}（2pp）余量，"
        f"回退容忍 {PROPOSAL_MAX_REGRESSION_PP:.1f}pp（仅同 pipeline_version 生效）；"
        "运行类（延迟 / 成本）不给自动建议。建议值不是审批结果，也不得被当作通过依据。"
    )
    if warnings:
        notes = notes + " 观测提示：" + "；".join(warnings)
    return GateProposal(
        run_id=str(manifest.get("run_id") or ""),
        suite=str(manifest.get("suite") or ""),
        mode=str(manifest.get("mode") or ""),
        pipeline_version=str(manifest.get("pipeline_version") or ""),
        dataset_version=str(manifest.get("dataset_version") or ""),
        gate_version=str(manifest.get("gate_version") or ""),
        gate_config_hash=resolved.config_hash,
        status="unapproved",
        strata=strata,
        metrics=tuple(metric_rows),
        diagnostics={"value_no_fabricated": _value_no_fabricated_diagnostics(rows)},
        baseline=baseline_block,
        notes=notes,
    )


def write_gate_proposal(
    proposal: GateProposal,
    path: Path | str,
    *,
    overwrite: bool = False,
) -> Path:
    """把提案写成 UTF-8（无 BOM）JSON；拒绝写回 ``gate_v0_1.json``。"""
    if not isinstance(proposal, GateProposal):
        raise TypeError("write_gate_proposal 需要 GateProposal")
    target = Path(path)
    if target.resolve() == DEFAULT_GATE_CONFIG_PATH.resolve():
        raise ValueError(
            "不得用校准提案覆盖 gate_v0_1.json：阈值必须经 T009 人工门审批后手写"
        )
    if target.exists() and not overwrite:
        raise FileExistsError(f"提案文件已存在（需 overwrite=True）：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(proposal.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    target.write_bytes(payload.encode("utf-8"))
    return target


# --------------------------------------------------------------------------- #
# 公共入口
# --------------------------------------------------------------------------- #


def evaluate_gate(
    run: RunResult,
    baseline: Any | None = None,
    config: GateConfig | None = None,
    *,
    require_trace: bool = True,
    dataset_path: Path | str | None = None,
    quality: bool | QualityPolicy = False,
    environ: Mapping[str, str] | None = None,
) -> GateResult:
    """评估一轮 run：8 项硬门禁 +（可选）质量层，并映射退出码 0 / 1 / 2 / 3 / 4。

    - ``run``：``run_suite`` 的返回值（读 manifest 身份字段、``cases.jsonl`` 行与
      run 目录下的 trace 仓储）；
    - ``baseline``：质量层的同版本 baseline（``RunResult`` 或 run 目录路径）；只在
      ``quality`` 启用时参与 ``max_regression_pp``，否则只记 warning（T006a 语义）；
    - ``config``：``load_gate_config`` 的结果；``None`` 时读
      :data:`DEFAULT_GATE_CONFIG_PATH`；
    - ``require_trace``：``False`` 时显式跳过 ``trace_integrity``（记 not_applicable）；
    - ``dataset_path``：覆盖数据集路径（默认 ``manifest.dataset_path``，再回退冻结
      数据集）；gold / forbidden 一律从数据集重新解析，不信任 run 自报的值；
    - ``quality``：``False``（默认）只跑硬门禁 = T006a 兼容；``True`` 评估质量层；
      ``QualityPolicy(waivers=(...))`` 评估质量层并应用质量豁免（硬门禁不可豁免）。

    优先级：``mode=live`` → 4；配置 / 数据不可用（含非法 mode）→ 3；任一硬门禁失败 → 1；
    存在 unknown（含质量层未审批 / 样本不足 / 跨版本 baseline）→ 3；质量失败（绝对阈值
    未达或回退超限，且未被 waiver）→ 2；否则 0。``quality=False`` 时 ``exit_code=0``
    只代表硬门禁通过，**不代表**质量达标（``GateResult.quality is None``）。

    ``min_sample`` 的判定分母是 ``evaluated_count``：``cases.jsonl`` 中 ``status`` 为
    ``pass`` / ``fail`` 且非 ``skipped_requires_ocr``、非 runner ``error`` 的行。空 gold
    行（如 badcase 的 N10/N12/N13）仍参与 kind / 拒答 / 引用等硬门禁校验，因此计入
    硬门禁分母；质量指标（T006b）的检索 / 拒答分母另算，不得与本口径混用。

    P1 T108（holdout 防污染）：holdout **不参与**硬门禁/质量门槛（``gate_v0_2`` 校准属
    T112）。两类 holdout run 都返回 ``exit 3`` + 显式 unknown，不抛异常、不读逐题：

    - 聚合 run（``holdout_details=false``，无 ``cases.jsonl``）：``check_id=holdout_aggregate_only``；
    - 逐题详情 run：一律拒绝（``check_id=holdout_details_not_gated``；CI/门禁环境命中
      ``CI`` / ``GITHUB_ACTIONS`` / ``MKTKB_CI`` 时记 ``holdout_details_forbidden_in_ci``
      并在 reason 写明变量名）。原因是 gate 需要本地 labels 才能按数据集重算 gold，
      T108 不引入 gate-time labels，逐题产物也不得进入门禁/CI。
    """
    manifest = _manifest_payload(run)
    rows = tuple(run.cases or ())
    bad_rows = [index for index, row in enumerate(rows) if not isinstance(row, Mapping)]
    rows = tuple(row for row in rows if isinstance(row, Mapping))
    evaluated_count = sum(1 for row in rows if _is_evaluated_row(row))
    mode = str(manifest.get("mode") or "").strip()

    if mode.lower() == "live":
        return GateResult(
            exit_code=EXIT_LIVE_UNAUTHORIZED,
            gate_status={gate_id: GATE_STATUS_NOT_EVALUATED for gate_id in HARD_GATE_IDS},
            hard_failures=(),
            failures=(),
            unknowns=(),
            not_applicable=(),
            warnings=(
                "mode=live 未授权：P0 只允许 local / replay；gate 自己拒绝，"
                "不依赖内核 _coerce_mode（T003a 遗留）",
            ),
            run_id=str(manifest.get("run_id") or ""),
            suite=str(manifest.get("suite") or ""),
            mode=mode,
            gate_version=str(manifest.get("gate_version") or ""),
            scored_count=evaluated_count,
            min_sample=None,
        )

    warnings: list[str] = []
    policy = _coerce_quality_policy(quality)
    if baseline is not None and policy is None:
        warnings.append(
            "baseline 被忽略：quality=False（只跑硬门禁层），质量回退检测未启用"
        )

    if str(manifest.get("suite") or "") == HOLDOUT_SUITE:
        return _holdout_gate_result(manifest, rows, mode=mode, environ=environ)

    resolved_config = config if config is not None else load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    if bad_rows:
        return _config_data_failure(
            manifest,
            evaluated_count,
            resolved_config,
            unknowns=[
                GateUnknown(
                    gate_id="dataset",
                    case_id=None,
                    check_id="row_not_object",
                    reason="cases.jsonl 存在非对象行",
                    evidence={"row_indexes": bad_rows[:10]},
                )
            ],
            warnings=warnings,
        )
    if mode not in {"local", "replay"}:
        return _config_data_failure(
            manifest,
            evaluated_count,
            resolved_config,
            unknowns=[
                GateUnknown(
                    gate_id="gate_config",
                    case_id=None,
                    check_id="mode_invalid",
                    reason="run_manifest.mode 不是 local / replay（P0 只允许这两种），无法判定",
                    evidence={"mode": manifest.get("mode")},
                )
            ],
            warnings=warnings,
        )
    if str(manifest.get("gate_version") or "") != resolved_config.gate_version:
        return _config_data_failure(
            manifest,
            evaluated_count,
            resolved_config,
            unknowns=[
                GateUnknown(
                    gate_id="gate_config",
                    case_id=None,
                    check_id="gate_version_mismatch",
                    reason="run_manifest.gate_version 与 gate 配置不一致，无法按同一契约判定",
                    evidence={
                        "manifest_gate_version": manifest.get("gate_version"),
                        "config_gate_version": resolved_config.gate_version,
                    },
                )
            ],
            warnings=warnings,
        )

    target, fallback_note = _dataset_path(manifest, dataset_path)
    if fallback_note:
        warnings.append(fallback_note)
    if target is None:
        return _config_data_failure(
            manifest,
            evaluated_count,
            resolved_config,
            unknowns=[
                GateUnknown(
                    gate_id="dataset",
                    case_id=None,
                    check_id="dataset_unreadable",
                    reason="找不到可解析的数据集文件（gold / forbidden 无法校验）",
                    evidence={"dataset_path": manifest.get("dataset_path")},
                )
            ],
            warnings=warnings,
        )
    try:
        cases = tuple(load_cases(target))
    except (ValueError, OSError) as exc:
        return _config_data_failure(
            manifest,
            evaluated_count,
            resolved_config,
            unknowns=[
                GateUnknown(
                    gate_id="dataset",
                    case_id=None,
                    check_id="dataset_unreadable",
                    reason=f"数据集无法解析: {exc}",
                    evidence={"dataset_path": str(target)},
                )
            ],
            warnings=warnings,
        )

    dataset_ids = [case.case_id for case in cases]
    row_ids = [str(row.get("case_id") or "") for row in rows]
    if dataset_ids != row_ids:
        return _config_data_failure(
            manifest,
            evaluated_count,
            resolved_config,
            unknowns=[
                GateUnknown(
                    gate_id="dataset",
                    case_id=None,
                    check_id="dataset_row_mismatch",
                    reason="数据集 case 与 cases.jsonl 行不一致（集合/顺序），产物不可用于判定",
                    evidence={
                        "dataset_cases": len(dataset_ids),
                        "run_rows": len(row_ids),
                        "missing_in_run": sorted(set(dataset_ids) - set(row_ids))[:10],
                        "extra_in_run": sorted(set(row_ids) - set(dataset_ids))[:10],
                    },
                )
            ],
            warnings=warnings,
        )

    gold_unknowns, range_gold_cases = _gold_reference_unknowns(cases)
    if range_gold_cases:
        warnings.append(
            "数据集存在整篇级 gold（doc_code-only，范围型引用）："
            f"{range_gold_cases}；不静默扩写，按范围集合口径记录"
        )

    traces = _TraceReader(
        Path(run.out_dir) / str(manifest.get("trace_store") or "traces.sqlite3")
    )
    try:
        view = _View(
            manifest=manifest,
            rows=rows,
            cases=cases,
            config=resolved_config,
            traces=traces,
        )
        outcomes = [
            _gate_security_leak(view),
            _gate_hard_filter_signal(
                view,
                "cross_entity",
                "cross_entity",
                "v0.1 数据集没有 entity key / 请求 filters 字段，没有可判定的 "
                "cross_entity case；只把上游 hard_filter_violation=cross_entity 当违规证据",
            ),
            _gate_hard_filter_signal(
                view,
                "stale_bypass",
                "stale",
                "v0.1 数据集没有 include_future / as_of / effective_from / effective_to "
                "字段，没有可判定的 stale_bypass case；只把上游 hard_filter_violation=stale "
                "当违规证据",
            ),
            _gate_conflict_not_rejected(view),
            _gate_exact_value_contract(view),
            _gate_pagination_contract(view),
            _gate_citation_required(view),
            _gate_trace_integrity(view, require_trace),
        ]
        view_warnings = tuple(view.warnings)
    finally:
        traces.close()

    unknowns: list[GateUnknown] = list(gold_unknowns)
    error_cases = [
        str(row.get("case_id") or "") for row in rows if _is_error_row(row)
    ]
    if error_cases:
        unknowns.append(
            GateUnknown(
                gate_id="run",
                case_id=None,
                check_id="case_error",
                reason=(
                    "cases.jsonl 存在 error 行（数据 / gold 解析失败）：本轮 run 不完整，"
                    "不得判通过"
                ),
                evidence={"case_ids": error_cases, "count": len(error_cases)},
            )
        )
    min_sample = resolved_config.min_sample_for(str(manifest.get("suite") or ""))
    if min_sample is None:
        unknowns.append(
            GateUnknown(
                gate_id="min_sample",
                case_id=None,
                check_id="min_sample_missing",
                reason="gate 配置没有该 suite 的 min_sample，样本充足性无法证明",
                evidence={"suite": manifest.get("suite")},
            )
        )
    elif evaluated_count < min_sample:
        unknowns.append(
            GateUnknown(
                gate_id="min_sample",
                case_id=None,
                check_id="min_sample_not_met",
                reason=(
                    "evaluated_count（status ∈ {pass,fail} 且排除 OCR 与 error 行）"
                    "不足硬门禁 hard_gate_min_sample"
                ),
                evidence={
                    "evaluated_count": evaluated_count,
                    "min_sample": min_sample,
                    "basis": "evaluated_count",
                    "suite": manifest.get("suite"),
                },
            )
        )

    for outcome in outcomes:
        unknowns.extend(outcome.unknowns)
    failures = tuple(item for outcome in outcomes for item in outcome.failures)
    gate_status = {outcome.gate_id: outcome.status for outcome in outcomes}
    hard_failures = tuple(
        gate_id for gate_id in HARD_GATE_IDS if gate_status.get(gate_id) == GATE_STATUS_FAIL
    )
    not_applicable = tuple(
        GateNote(
            gate_id=outcome.gate_id,
            applicable_cases=outcome.applicable,
            detail=outcome.detail,
        )
        for outcome in outcomes
        if outcome.status == GATE_STATUS_NOT_APPLICABLE
    )
    warnings = list(warnings) + list(view_warnings)
    warnings.extend(
        f"{note.gate_id}: not_applicable（{note.detail}）" for note in not_applicable
    )

    quality_result: QualityResult | None = None
    quality_failures: tuple[GateFailure, ...] = ()
    if policy is not None:
        quality_result = _evaluate_quality(
            run,
            manifest,
            cases,
            rows,
            resolved_config,
            policy,
            baseline,
        )
        unknowns.extend(quality_result.unknowns)
        quality_failures = quality_result.failures
        warnings.extend(quality_result.warnings)

    # 退出码优先级（handoff §5.4）：硬失败 1 最高；任何 unknown（含质量未审批 /
    # 样本不足 / 跨版本 baseline）→ 3；质量失败（未被 waiver）→ 2；否则 0。
    if hard_failures:
        exit_code = EXIT_HARD_FAILURE
    elif unknowns:
        exit_code = EXIT_UNKNOWN
    elif quality_failures:
        exit_code = EXIT_QUALITY_REGRESSION
    else:
        exit_code = EXIT_PASS

    return GateResult(
        exit_code=exit_code,
        gate_status={
            gate_id: gate_status.get(gate_id, GATE_STATUS_NOT_EVALUATED)
            for gate_id in HARD_GATE_IDS
        },
        hard_failures=hard_failures,
        failures=failures,
        unknowns=tuple(unknowns),
        not_applicable=not_applicable,
        warnings=tuple(warnings),
        run_id=str(manifest.get("run_id") or ""),
        suite=str(manifest.get("suite") or ""),
        mode=mode,
        gate_version=resolved_config.gate_version,
        scored_count=evaluated_count,
        min_sample=min_sample,
        quality=quality_result,
    )


def _manifest_payload(run: RunResult) -> dict[str, Any]:
    manifest = run.manifest
    if hasattr(manifest, "to_dict") and not isinstance(manifest, Mapping):
        payload = manifest.to_dict()
    elif isinstance(manifest, Mapping):
        payload = dict(manifest)
    else:  # pragma: no cover - RunResult 契约固定
        raise TypeError("run.manifest 必须是 RunManifest 或等值映射")
    return {str(key): value for key, value in payload.items()}


def _holdout_gate_result(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    environ: Mapping[str, str] | None,
) -> GateResult:
    """holdout 专用门禁结论：只给聚合/拒绝，不读逐题、不产生逐 case 证据。"""
    details = bool(manifest.get("holdout_details", False))
    ci_var = ci_environment(os.environ if environ is None else environ)
    warnings = [
        "P1 T108：holdout 不参与硬门禁/质量门槛（gate_v0_2 校准留给 T112）",
    ]
    if details:
        check_id = "holdout_details_not_gated"
        reason = (
            "holdout 逐题详情 run 不参与门禁：gate 需要本地 labels 才能按数据集重算 gold，"
            "T108 不引入 gate-time labels；逐题产物也不得进入门禁/CI"
        )
        if ci_var is not None:
            check_id = "holdout_details_forbidden_in_ci"
            reason = (
                f"CI/门禁环境（命中环境变量 {ci_var}）禁止 holdout 逐题详情 run 参与门禁："
                + reason
            )
        evidence: dict[str, Any] = {
            "holdout_details": True,
            "run_rows": len(rows),
            "ci_env": ci_var,
        }
    else:
        check_id = "holdout_aggregate_only"
        reason = (
            "holdout 聚合 run 只写 summary、不写 cases.jsonl：无法按数据集重算逐 case "
            "硬门禁，按聚合口径记为未知"
        )
        evidence = {
            "holdout_details": False,
            "case_count": manifest.get("case_count"),
            "run_rows": len(rows),
            "ci_env": ci_var,
        }
        if rows:
            warnings.append(
                "内存中存在逐题行但 manifest 声明为聚合 run：按聚合口径判定，不使用这些行"
            )
    return GateResult(
        exit_code=EXIT_UNKNOWN,
        gate_status={gate_id: GATE_STATUS_NOT_EVALUATED for gate_id in HARD_GATE_IDS},
        hard_failures=(),
        failures=(),
        unknowns=(
            GateUnknown(
                gate_id=HOLDOUT_SUITE,
                case_id=None,
                check_id=check_id,
                reason=reason,
                evidence=evidence,
            ),
        ),
        not_applicable=(),
        warnings=tuple(warnings),
        run_id=str(manifest.get("run_id") or ""),
        suite=str(manifest.get("suite") or ""),
        mode=mode,
        gate_version=str(manifest.get("gate_version") or ""),
        scored_count=0,
        min_sample=None,
    )


def _config_data_failure(
    manifest: Mapping[str, Any],
    evaluated_count: int,
    config: GateConfig,
    *,
    unknowns: Sequence[GateUnknown],
    warnings: Sequence[str],
) -> GateResult:
    """配置 / 数据不可用：不做任何门禁判定，直接 exit 3。"""
    return GateResult(
        exit_code=EXIT_UNKNOWN,
        gate_status={gate_id: GATE_STATUS_NOT_EVALUATED for gate_id in HARD_GATE_IDS},
        hard_failures=(),
        failures=(),
        unknowns=tuple(unknowns),
        not_applicable=(),
        warnings=tuple(warnings),
        run_id=str(manifest.get("run_id") or ""),
        suite=str(manifest.get("suite") or ""),
        mode=str(manifest.get("mode") or ""),
        gate_version=config.gate_version,
        scored_count=evaluated_count,
        min_sample=None,
    )
