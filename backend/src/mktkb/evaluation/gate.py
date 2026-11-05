"""T006a：Release Gate 硬门禁层 + 退出码（设计 §8.1 / §8.4；P0 计划 Task 5 Step 1/3/5）。

本模块只做**硬门禁层 + 退出码 + 配置骨架**，不实现质量层：

- 8 项硬门禁（顺序同设计 §8.1 表）：任一失败 → ``exit_code=1``；
- 数据 / 配置 / gold 不可用或样本不足 → ``exit_code=3``；
- ``mode=live`` 未授权 → ``exit_code=4``（P0 恒未授权，不依赖内核拒绝 live）；
- 全部通过 → ``exit_code=0``；
- ``exit_code=2`` **保留给 T006b 的质量回退**，本包没有任何触发路径
  （:data:`EXIT_QUALITY_REGRESSION` 只是常量）。

判定口径（PM 裁决 2026-11-05，handoff §5.4 / §5.5 / §7）：

- 硬门禁**按 case 条件适用**：数据集里没有该类 case → ``not_applicable``（记
  INFO/warnings，不影响退出码）；有该类 case 但字段缺失 / 无法判定 → ``unknown``
  → ``exit_code=3``；
- 硬门禁不可豁免：没有 waiver API，也不接受 waiver 参数；
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
- ``min_sample`` 的分母是 ``scored_count``（``status`` 为 pass/fail 的行数，排除 OCR
  与 error 行），不用 ``case_count`` / ``metrics_scope.cases_in_denominator``；
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
``*_json`` 非法 JSON fail closed；``TRACE_SCHEMA_VERSION`` 不一致 fail。

输入只读：``RunResult``（``run_manifest.json`` 身份字段、``cases.jsonl`` 行）、
run 目录下的 ``traces.sqlite3``（只读打开）与数据集文件（重新解析 gold / forbidden，
不信任 run 自报的 gold）。本模块不写任何产物、不调用 provider、不建索引。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..observability.contracts import (
    GATE_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    TraceRecord,
    conditional_required_spans,
    required_spans,
)
from .dataset import CaseSpec, load_cases
from .runner import RunResult
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
    "GateResult",
    "GateUnknown",
    "HARD_GATE_IDS",
    "MetricSpec",
    "evaluate_gate",
    "load_gate_config",
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
    """Release Gate 配置 v0.1（只含硬门禁骨架；阈值留给 T006b 审批后填入）。"""

    gate_version: str
    schema_version: str
    status: str
    hard_gates: tuple[str, ...]
    min_sample: Mapping[str, int]
    metrics: tuple[MetricSpec, ...] = ()
    sensitive_patterns: tuple[str, ...] = ()
    source_path: str | None = None
    config_hash: str = ""

    def min_sample_for(self, suite: str) -> int | None:
        """返回 suite 的最小样本数；未配置返回 ``None``（调用方必须 fail closed）。"""
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

    raw_min_sample = _require_mapping(payload.get("min_sample"), "min_sample")
    min_sample: dict[str, int] = {}
    for suite, value in raw_min_sample.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"min_sample[{suite!r}] 必须是正整数，收到 {value!r}")
        min_sample[str(suite)] = value
    if not min_sample:
        raise ValueError("min_sample 不能为空")

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
    """一次门禁评估结果；``hard_failures`` 是失败的硬门禁 ID（可直接 ``in`` 判断）。"""

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
        text = str(outcome.get("text") or "") if outcome is not None else ""
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
        actual = dict(outcome.get("pagination") or {}) if outcome is not None else {}
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
        if str(outcome.get("kind") or "") != "answer":
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
# 公共入口
# --------------------------------------------------------------------------- #


def evaluate_gate(
    run: RunResult,
    baseline: Any | None = None,
    config: GateConfig | None = None,
    *,
    require_trace: bool = True,
    dataset_path: Path | str | None = None,
) -> GateResult:
    """评估一轮 run 的 8 项硬门禁并映射退出码（0 / 1 / 3 / 4；2 属 T006b）。

    - ``run``：``run_suite`` 的返回值（读 manifest 身份字段、``cases.jsonl`` 行与
      run 目录下的 trace 仓储）；
    - ``baseline``：P0 硬门禁层不使用；给了只记 warning（回退检测属 T006b）；
    - ``config``：``load_gate_config`` 的结果；``None`` 时读
      :data:`DEFAULT_GATE_CONFIG_PATH`；
    - ``require_trace``：``False`` 时显式跳过 ``trace_integrity``（记 not_applicable）；
    - ``dataset_path``：覆盖数据集路径（默认 ``manifest.dataset_path``，再回退冻结
      数据集）；gold / forbidden 一律从数据集重新解析，不信任 run 自报的值。

    优先级：``mode=live`` → 4；配置 / 数据不可用（含非法 mode）→ 3；任一硬门禁失败 → 1；
    存在 unknown → 3；否则 0。硬门禁失败优先于 unknown（handoff §5.4）。
    """
    manifest = _manifest_payload(run)
    rows = tuple(run.cases or ())
    bad_rows = [index for index, row in enumerate(rows) if not isinstance(row, Mapping)]
    rows = tuple(row for row in rows if isinstance(row, Mapping))
    scored_count = sum(1 for row in rows if _row_status(row) in SCORED_ROW_STATUSES)
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
            scored_count=scored_count,
            min_sample=None,
        )

    warnings: list[str] = []
    if baseline is not None:
        warnings.append("baseline 被忽略：质量层 / 回退检测属 T006b，本包不做质量判定")

    resolved_config = config if config is not None else load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    if bad_rows:
        return _config_data_failure(
            manifest,
            scored_count,
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
            scored_count,
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
            scored_count,
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
            scored_count,
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
            scored_count,
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
            scored_count,
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
    elif scored_count < min_sample:
        unknowns.append(
            GateUnknown(
                gate_id="min_sample",
                case_id=None,
                check_id="min_sample_not_met",
                reason=(
                    "可评分样本（scored_count，排除 OCR 与 error 行）不足 min_sample"
                ),
                evidence={
                    "scored_count": scored_count,
                    "min_sample": min_sample,
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

    if hard_failures:
        exit_code = EXIT_HARD_FAILURE
    elif unknowns:
        exit_code = EXIT_UNKNOWN
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
        scored_count=scored_count,
        min_sample=min_sample,
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


def _config_data_failure(
    manifest: Mapping[str, Any],
    scored_count: int,
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
        scored_count=scored_count,
        min_sample=None,
    )
