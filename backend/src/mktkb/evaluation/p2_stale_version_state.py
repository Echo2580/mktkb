"""`stale_source` 判据 v1 分类器：版本态优先、日期可选（数据集无关）。

实现对象是**判据规范** ``docs/evaluation/p2-stale-source-criterion-v1.md``
（``p2-stale-source-criterion/v1``），不是任何具体数据集：

- 同一实现、同一条代码路径同时支持 ``version_state`` 与 ``date_window``；``mode``
  只影响 active 推导与 §5.4 的窗口分支，不影响逐题入口。
- 模块内**零数据集字面量**：源码、scenario id、日期常量、期望版本号全部由输入注入
  （规范 §12.2）。本文件只出现固定码、枚举与规则名。
- 输出不含 ``verified`` / ``threshold`` / ``release`` / 分数 / 均值 / 加权。

输入的顶层形状（规范 §8.1，实现契约 §12.1）::

    determine_stale_case(
        criterion_version="p2-stale-source-criterion/v1",
        grounding={
            "mode": "version_state" | "date_window",
            "fixture_sha256": "<hex64>|null",
            "scenario": {"scenario_id": "...", "source_indices": [...],
                         "ingest_batches": <不透明值>},
            "ingest_plan": {"schema_version": "...", "sources": [{"path": "...",
                            "document_ref": "...|absent", "name": "...|absent"}]},
            "source_map": {"sources": {"<code>": {"base_doc_code": "...",
                           "version_number": <int|absent>}}},
            "windows": null | {"schema_version": "p2-source-lifecycle-window/v1",
                               "bindings": {"source_map_sha256", "ingest_plan_sha256"},
                               "windows": {"<code>": {"effective_from",
                                                      "effective_to"|absent}},
                               "open_ended": [...], "basis": "...",
                               "evidence_ref": "..."},
            # 可选、仅供 §3.2 的加载期拒收规则（值由调用方注入，不在本模块里写死）：
            "built_at": "YYYY-MM-DD" | null,
            "corpus_header_dates": ["YYYY-MM-DD", ...],
            "source_map_sha256": "<hex64>" | absent,
            "ingest_plan_sha256": "<hex64>" | absent,
        },
        evidence={
            "case_id": "..." | absent,          # 仅回显，不参与判定
            "as_of": "YYYY-MM-DD" | null,
            "usage": {...} | absent,
            "citations": [...] | absent,
            "annotation": {"applicability", "criterion", "reason", "as_of",
                           "temporal_intent"},
            "turns": [{"turn_index": 0, "state_inputs": {"usage": {...}, ...}}] | absent,
        },
    )

逐回合证据：``turns`` 缺省时把 ``evidence`` 本身当作唯一回合；显式声明 ``turns``
时，每个回合的 ``state_inputs`` 自带 ``usage``（缺 usage 即该回合
``stale_usage_set_missing``），``citations`` / ``as_of`` 只取回合自身的值（``as_of``
缺键时沿用 evidence 级）。空集闭包证明**只**逐层读 ``use_layers[*].observed/count/refs``
与 ``retrieval.observed/count/refs/truncated`` + ``turn_status``；``closure_proven`` /
``empty_set_candidate`` 之类派生布尔**不读**（规范 §5.2 注；F-8）。

固定码与状态严格来自规范 §10（21 码 = 新增 9 + 沿用 12）；§10.3 的 14 个旧码保留在
词表但**一律不产出**。`not_applicable` 在本轴不可达（§5.7），计数硬不变量恒为 0。

实现口径决议（判据文本内部有张力处，一律取更 fail-closed 的一侧）：

1. 重复 `source_indices`：R-AV-1 写 `stale_scenario_undeclared`，F-2 把“source_indices
   重复”列为多 active 歧义。取 F-2 → `stale_active_version_ambiguous` + audit
   `stale_duplicate_source_indices`（两者都是 unknown，取更具体的边界）。
2. 空使用集 + 回合未完成/partial：R-J-3 写 `stale_usage_set_missing`，F-8 写
   `empty_set_not_proven`。空集分支取 F-8。
3. 空集已证的 `evidence_grade`：没有任何源可做日期比较 → 固定 `version_only`（两模式一致）。
4. 歧义作用域：`version_state` 对 `groups(S)` 全量推导，任一槽位歧义即 unknown；
   `date_window` 只解析**被使用到**的槽位窗口（未使用的槽位不制造 unknown）。

其他实现事实：

- `pos` 是 ingest plan 的下标（R-AV-1），`source_indices` 先按 idx 升序；`ingest_batches`
  不参与排序/判定，只记 audit `stale_batch_count_opaque`。
- `fixture_sha256` 是**声明绑定**：本模块不持有 fixture 字节，无法复算内容摘要
  （与 C1-P4 `IR-05` 同类）。`date_window` 下缺省/坏值 → `stale_window_unresolved`；
  `version_state` 下只丢弃 + audit，verdict 不变。
- `unit` 取 §8.1 的 3 键，另允许**可选** `document_id` / `version_id` 以执行 R-J-11；
  缺这两个值时 citation 层无法投影 → `source_unresolved`（R-J-12）。
- 固定码一律等值比较；非标量枚举/键值收敛为固定码 + unknown，不抛裸异常（§9 补充条款）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

from .p2_evidence_rescore import AXIS_STATES
from .p2_evidence_rescore_axes import (
    ANNOTATION_APPLICABILITIES,
    ANNOTATION_REASONS,
    TEMPORAL_INTENTS,
)

__all__ = [
    "CRITERION_VERSION",
    "DETERMINATION_CODES",
    "EVIDENCE_GRADES",
    "GROUNDING_MODES",
    "INHERITED_CODES",
    "NEW_CODES",
    "PASS_CODES",
    "RETIRED_CODES",
    "UNKNOWN_CODES",
    "VIOLATION_CODES",
    "WINDOW_BASES",
    "WINDOW_SCHEMA_VERSION",
    "CaseDetermination",
    "CriterionError",
    "TurnDetermination",
    "aggregate_cases",
    "determine_stale_case",
    "reason_histogram",
]

CRITERION_VERSION = "p2-stale-source-criterion/v1"

GROUNDING_MODES: tuple[str, ...] = ("version_state", "date_window")
WINDOW_SCHEMA_VERSION = "p2-source-lifecycle-window/v1"
WINDOW_BASES: tuple[str, ...] = ("owner_ruling", "custodian_transcription")
EVIDENCE_GRADES: tuple[str, ...] = ("none", "version_only", "version_plus_date")

#: §5.6 折叠优先级（数值大者胜）。
STATE_PRIORITY: Mapping[str, int] = MappingProxyType(
    {"violation": 3, "unknown": 2, "not_applicable": 1, "passed": 0}
)

# --------------------------------------------------------------------------- #
# 固定码表（§10：21 码 = 9 新 + 12 沿用；另 14 个旧码保留不产出）
# --------------------------------------------------------------------------- #

NEW_CODES: frozenset[str] = frozenset(
    {
        "stale_active_version_used",
        "stale_empty_use_scope_proven",
        "stale_superseded_version_used",
        "stale_out_of_window",
        "stale_active_version_ambiguous",
        "stale_scenario_undeclared",
        "stale_usage_set_missing",
        "stale_window_unresolved",
        "stale_grounding_mode_invalid",
    }
)

INHERITED_CODES: frozenset[str] = frozenset(
    {
        "stale_source_dates_ok",
        "annotation_unknown",
        "source_unresolved",
        "version_unresolved",
        "empty_set_not_proven",
        "as_of_missing",
        "citation_version_mismatch",
        "date_intent_conflict",
        "turn_not_executed",
        "turn_error",
        "replay_without_original",
        "evidence_incomplete",
    }
)

DETERMINATION_CODES: frozenset[str] = NEW_CODES | INHERITED_CODES

#: §10.3：词表保留、v1 一律不得产出。
RETIRED_CODES: frozenset[str] = frozenset(
    {
        "no_dated_sources_lifecycle_checked",
        "source_deleted",
        "source_not_published",
        "source_not_active",
        "source_expired",
        "future_source_as_current",
        "lifecycle_unavailable",
        "date_unresolved",
        "citation_source_unresolved",
        "stale_lifecycle_evidence_missing",
        "version_mismatch",
        "stale_source_unresolved",
        "stale_no_positive_refs",
        "stale_positive_ref_not_record_level",
    }
)

PASS_CODES: frozenset[str] = frozenset(
    {
        "stale_active_version_used",
        "stale_empty_use_scope_proven",
        "stale_source_dates_ok",
    }
)
VIOLATION_CODES: frozenset[str] = frozenset(
    {
        "stale_superseded_version_used",
        "stale_out_of_window",
        "citation_version_mismatch",
        "date_intent_conflict",
    }
)
UNKNOWN_CODES: frozenset[str] = DETERMINATION_CODES - PASS_CODES - VIOLATION_CODES

STATE_BY_CODE: Mapping[str, str] = MappingProxyType(
    {
        **{code: "passed" for code in PASS_CODES},
        **{code: "violation" for code in VIOLATION_CODES},
        **{code: "unknown" for code in UNKNOWN_CODES},
    }
)

#: R-J-3 允许沿用的“使用集缺失”细码（优先于 `stale_usage_set_missing`）。
TURN_USAGE_REASONS: tuple[str, ...] = (
    "turn_not_executed",
    "turn_error",
    "replay_without_original",
    "evidence_incomplete",
)

#: verdict 之外的输出禁令（I-5）。
_FORBIDDEN_OUTPUT_TOKENS = ("verified", "threshold", "release")

#: §8.1 的顶层形状：未知键一律拒绝（收敛为固定码 + audit，`criterion_field_invalid`
#: 本身不是 21 码之一，故只作为审计标记，不冒充判定 reason）。
_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {"case_id", "as_of", "usage", "citations", "annotation", "turns"}
)
_GROUNDING_KEYS: frozenset[str] = frozenset(
    {
        "mode",
        "fixture_sha256",
        "scenario",
        "ingest_plan",
        "source_map",
        "windows",
        # §3.2 加载期拒收所需的调用方注入值（不在本模块写死任何数据集常量）：
        "built_at",
        "corpus_header_dates",
        "source_map_sha256",
        "ingest_plan_sha256",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLOT_SEPARATORS = ("/", "\\")


class CriterionError(RuntimeError):
    """判据实现不变量或输入硬错误（固定码）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Reject(Exception):
    """内部短路：``code`` 必须是 21 码之一，``audit`` 为不泄露身份的审计标记。"""

    def __init__(self, code: str, audit: Sequence[str] = ()) -> None:
        if not isinstance(code, str) or code not in DETERMINATION_CODES:
            raise CriterionError("criterion_code_unknown")
        super().__init__(code)
        self.code = code
        self.audit = tuple(audit)


def _reject(code: str, audit: Sequence[str] = ()) -> None:
    raise _Reject(code, audit)


# --------------------------------------------------------------------------- #
# 基础判断（非标量一律收敛为“不合法”，不抛裸异常）
# --------------------------------------------------------------------------- #


def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or _ISO_DATE_RE.fullmatch(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _enum_member(value: Any, allowed: Sequence[str] | frozenset[str]) -> bool:
    """成员判断前先确认 ``value`` 是字符串。

    规范 §9 补充条款 / ``IR-01``：非标量枚举值（list / dict / None / bool）必须
    收敛为固定码 + unknown，不得因 `value in frozenset` 抛 ``TypeError``。
    """
    return isinstance(value, str) and value in allowed


def _dedupe(tokens: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return tuple(ordered)


# --------------------------------------------------------------------------- #
# active 版本与上下文
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Active:
    code: str
    version_number: int | None
    basis: str
    position: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "version_number": self.version_number,
            "basis": self.basis,
            "position": self.position,
        }


@dataclass(frozen=True)
class _Window:
    effective_from: date
    effective_to: date | None

    def covers(self, as_of: date) -> bool:
        if as_of < self.effective_from:
            return False
        return self.effective_to is None or as_of < self.effective_to


@dataclass(frozen=True)
class _Upload:
    position: int
    code: str
    base_doc_code: str
    slot_prefix: str


@dataclass(frozen=True)
class _Context:
    mode: str
    scenario_id: str
    uploads: tuple[_Upload, ...]
    groups: Mapping[str, tuple[_Upload, ...]]
    code_to_base: Mapping[str, str]
    code_version: Mapping[str, int | None]
    known_codes: frozenset[str]
    position_active: Mapping[str, _Active]
    windows: Mapping[str, _Window] | None
    audit: tuple[str, ...]

    def active_for(self, base_doc_code: str) -> _Active | None:
        """`version_state` 的 active；`date_window` 不以位置序为准。"""
        if self.mode != "version_state":
            return None
        return self.position_active.get(base_doc_code)

    def member_codes(self, base_doc_code: str) -> frozenset[str]:
        return frozenset(upload.code for upload in self.groups.get(base_doc_code, ()))

    def covering(
        self, base_doc_code: str, as_of: date
    ) -> tuple[str, tuple[_Active, ...]]:
        """§3.2 规则 5：返回 ``("ok"|"unresolved"|"none"|"ambiguous", active 集)``。"""
        members = self.groups.get(base_doc_code, ())
        cover: list[_Active] = []
        for upload in members:
            window = None if self.windows is None else self.windows.get(upload.code)
            if window is None:
                return "unresolved", ()
            if window.covers(as_of):
                cover.append(
                    _Active(
                        code=upload.code,
                        version_number=self.code_version.get(upload.code),
                        basis="window_covering",
                        position=upload.position,
                    )
                )
        if not cover:
            return "none", ()
        if len(cover) > 1:
            return "ambiguous", tuple(cover)
        return "ok", tuple(cover)


# --------------------------------------------------------------------------- #
# 输入加载：annotation（P-1 / P-2）与 grounding（P-3 / P-4）
# --------------------------------------------------------------------------- #


def _load_annotation(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    annotation = evidence.get("annotation")
    if not isinstance(annotation, Mapping):
        _reject("annotation_unknown", ("annotation_missing",))
    required = ("applicability", "criterion", "reason", "as_of", "temporal_intent")
    for key in required:
        if key not in annotation:
            _reject("annotation_unknown", (f"annotation_field_missing:{key}",))
    if set(annotation) - set(required):
        # §8.1：未知键拒绝；本轴没有“输入形状”独立码，收敛为 annotation_unknown。
        _reject("annotation_unknown", ("criterion_field_invalid:annotation",))
    applicability = annotation["applicability"]
    criterion = annotation["criterion"]
    reason = annotation["reason"]
    as_of = annotation["as_of"]
    temporal_intent = annotation["temporal_intent"]
    if not _enum_member(applicability, ANNOTATION_APPLICABILITIES):
        _reject("annotation_unknown", ("annotation_field_invalid:applicability",))
    if not isinstance(criterion, str):
        _reject("annotation_unknown", ("annotation_field_invalid:criterion",))
    if not _enum_member(reason, ANNOTATION_REASONS):
        _reject("annotation_unknown", ("annotation_field_invalid:reason",))
    if as_of is not None and _parse_date(as_of) is None:
        _reject("annotation_unknown", ("annotation_field_invalid:as_of",))
    if not _enum_member(temporal_intent, TEMPORAL_INTENTS):
        _reject("annotation_unknown", ("annotation_field_invalid:temporal_intent",))
    if applicability != "required" or criterion != "lifecycle_dates":
        # P-2 / F-11：N/A 或 criterion 不符一律 unknown，绝不 N/A 收口。
        _reject("annotation_unknown", ("scope_mode_mismatch",))
    return MappingProxyType(dict(annotation))


def _load_mode(grounding: Any) -> str:
    if not isinstance(grounding, Mapping):
        _reject("stale_grounding_mode_invalid", ("grounding_missing",))
    unknown = set(grounding) - _GROUNDING_KEYS
    if unknown:
        _reject(
            "stale_grounding_mode_invalid",
            tuple(f"criterion_field_invalid:{key}" for key in sorted(unknown, key=str)),
        )
    if "stale_grounding" in grounding:
        # §3.3：一个数据集只能有一种声明形状；两处同时声明即非法，不合并、不择优。
        _reject("stale_grounding_mode_invalid", ("stale_grounding_mode_double_declared",))
    if "mode" not in grounding:
        _reject("stale_grounding_mode_invalid", ("stale_grounding_mode_missing",))
    mode = grounding["mode"]
    if isinstance(mode, (list, tuple, set, frozenset)):
        _reject("stale_grounding_mode_invalid", ("stale_grounding_mode_double_declared",))
    if not _enum_member(mode, GROUNDING_MODES):
        _reject("stale_grounding_mode_invalid", ("stale_grounding_mode_unknown",))
    return mode


def _basename(path: str) -> str:
    name = path
    for separator in _SLOT_SEPARATORS:
        if separator in name:
            name = name.rsplit(separator, 1)[-1]
    return name


def _slot_prefix(slot: str) -> str:
    """§4.1：`basename` 在第一个 ``_`` 之前的前缀。"""
    base = _basename(slot)
    return base.split("_", 1)[0]


def _load_scenario(grounding: Mapping[str, Any]) -> tuple[str, tuple[int, ...], bool]:
    """P-4 / R-AV-1：scenario 契约与上传集（`ingest_batches` 只是不透明声明）。"""
    scenario = grounding.get("scenario")
    if not isinstance(scenario, Mapping):
        _reject("stale_scenario_undeclared", ("scenario_missing",))
    scenario_id = scenario.get("scenario_id")
    if not _is_str(scenario_id):
        _reject("stale_scenario_undeclared", ("scenario_id_missing",))
    if "source_indices" not in scenario:
        _reject("stale_scenario_undeclared", ("source_indices_missing",))
    indices = scenario["source_indices"]
    if not isinstance(indices, list):
        _reject("stale_scenario_undeclared", ("source_indices_invalid",))
    parsed: list[int] = []
    for index in indices:
        if not _is_int(index) or index < 0:
            _reject("stale_scenario_undeclared", ("source_indices_invalid",))
        parsed.append(index)
    if len(set(parsed)) != len(parsed):
        # 规范内部张力：R-AV-1 把“重复索引”归入 stale_scenario_undeclared，而
        # F-2 把“source_indices 重复”明确列为多 active 歧义。按更具体的 fail-closed
        # 边界（F-2）处置：重复索引意味着上传序不能确立唯一 active，不得择一。
        _reject("stale_active_version_ambiguous", ("stale_duplicate_source_indices",))
    # R-AV-1：上传集按 idx 升序；pos 就是 plan.sources 的下标（不是过滤后的序号）。
    return scenario_id, tuple(sorted(parsed)), "ingest_batches" in scenario


def _load_ingest_plan(
    grounding: Mapping[str, Any], indices: Sequence[int]
) -> tuple[Mapping[str, Any], ...]:
    plan = grounding.get("ingest_plan")
    if not isinstance(plan, Mapping):
        _reject("stale_scenario_undeclared", ("ingest_plan_missing",))
    sources = plan.get("sources")
    if not isinstance(sources, list):
        _reject("stale_scenario_undeclared", ("ingest_plan_sources_invalid",))
    for index in indices:
        if index >= len(sources):
            _reject("stale_scenario_undeclared", ("source_index_out_of_range",))
    return tuple(sources)


def _load_source_map(grounding: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, int | None]]:
    source_map = grounding.get("source_map")
    if not isinstance(source_map, Mapping):
        _reject("stale_active_version_ambiguous", ("source_map_unavailable",))
    sources = source_map.get("sources")
    if not isinstance(sources, Mapping):
        _reject("stale_active_version_ambiguous", ("source_map_unavailable",))
    aliases: dict[str, str] = {}
    versions: dict[str, int | None] = {}
    for code, row in sources.items():
        if not _is_str(code) or not isinstance(row, Mapping):
            _reject("stale_active_version_ambiguous", ("source_map_invalid",))
        base = row.get("base_doc_code")
        if not _is_str(base):
            _reject("stale_active_version_ambiguous", ("source_map_invalid",))
        version = row.get("version_number")
        if version is not None and (not _is_int(version) or version < 0):
            _reject("stale_active_version_ambiguous", ("source_map_invalid",))
        aliases[code] = base
        versions[code] = version
    return aliases, versions


def _build_context(
    mode: str,
    scenario_id: str,
    indices: Sequence[int],
    sources: Sequence[Any],
    aliases: Mapping[str, str],
    versions: Mapping[str, int | None],
    windows: Mapping[str, _Window] | None,
    audit: Sequence[str],
) -> _Context:
    aliases = dict(aliases)
    uploads: list[_Upload] = []
    for index in indices:
        entry = sources[index]
        if not isinstance(entry, Mapping):
            _reject("stale_scenario_undeclared", ("ingest_plan_entry_invalid",))
        path = entry.get("path")
        if not _is_str(path):
            _reject("stale_scenario_undeclared", ("ingest_plan_path_missing",))
        code = _basename(path).split("_", 1)[0]
        if not code:
            _reject("stale_scenario_undeclared", ("ingest_plan_code_unresolved",))
        slot = entry.get("document_ref")
        if not _is_str(slot):
            name = entry.get("name")
            slot = name if _is_str(name) else path
        base = aliases.get(code, code)
        uploads.append(
            _Upload(
                # R-AV-1：pos 是 ingest plan 的下标（上传位置），不是过滤后的序号。
                position=index,
                code=code,
                base_doc_code=base,
                slot_prefix=_slot_prefix(slot),
            )
        )

    groups: dict[str, list[_Upload]] = {}
    for upload in uploads:
        groups.setdefault(upload.base_doc_code, []).append(upload)

    context_audit: list[str] = list(audit)
    position_active: dict[str, _Active] = {}
    for base, members in groups.items():
        # §4.1：`slot` 的 doc-code 前缀必须与 `base_doc_code(code)` 一致，否则视为
        # ingest plan 与 source map 冲突（不得择一）。
        for member in members:
            if member.slot_prefix != base:
                _reject(
                    "stale_active_version_ambiguous",
                    _dedupe(tuple(context_audit) + ("stale_slot_base_conflict",)),
                )
        max_position = max(member.position for member in members)
        winners = [member for member in members if member.position == max_position]
        if len(winners) != 1:
            # R-AV-6：位置并列 → 多 active；不得取第一个、不得取版本号最大者。
            _reject(
                "stale_active_version_ambiguous",
                _dedupe(tuple(context_audit) + ("stale_multiple_active_by_position",)),
            )
        winner = winners[0]
        declared = [versions.get(member.code) for member in members]
        if all(number is not None for number in declared):
            # R-AV-5：声明号与位置序必须一致，否则不得择一。
            if versions.get(winner.code) != max(number for number in declared if number is not None):
                _reject(
                    "stale_active_version_ambiguous",
                    _dedupe(tuple(context_audit) + ("stale_version_order_conflict",)),
                )
        else:
            context_audit.append("stale_active_version_from_position")
        version_number = versions.get(winner.code)
        if version_number is None:
            context_audit.append("stale_version_number_undeclared")
        position_active[base] = _Active(
            code=winner.code,
            version_number=version_number,
            basis="position_max",
            position=winner.position,
        )

    code_to_base = {upload.code: upload.base_doc_code for upload in uploads}
    for code, base in aliases.items():
        code_to_base.setdefault(code, base)
    known_codes = frozenset(code_to_base) | frozenset(upload.code for upload in uploads)
    return _Context(
        mode=mode,
        scenario_id=scenario_id,
        uploads=tuple(uploads),
        groups=MappingProxyType({base: tuple(members) for base, members in groups.items()}),
        code_to_base=MappingProxyType(code_to_base),
        code_version=MappingProxyType(dict(versions)),
        known_codes=known_codes,
        position_active=MappingProxyType(position_active),
        windows=windows,
        audit=_dedupe(context_audit),
    )


# --------------------------------------------------------------------------- #
# 窗口 fixture 加载（§3.2 / F-10）
# --------------------------------------------------------------------------- #


def _load_windows(
    grounding: Mapping[str, Any], mode: str
) -> tuple[Mapping[str, _Window] | None, tuple[str, ...]]:
    """加载并校验 §3.2 的冻结窗口 fixture。

    ``date_window``：任何不可用 → ``stale_window_unresolved``（整份不可用）。
    ``version_state``：任何不可用 → 丢弃 + audit，verdict 不变（可选证据不得决定判决）。
    """

    def unusable(reason: str) -> tuple[None, tuple[str, ...]]:
        if mode == "date_window":
            _reject("stale_window_unresolved", ("stale_date_fixture_rejected", reason))
        return None, (
            "stale_date_fixture_rejected",
            "stale_date_check_skipped_unresolved",
            reason,
        )

    fixture_sha = grounding.get("fixture_sha256")
    payload = grounding.get("windows")
    if mode == "date_window" and not _is_sha256(fixture_sha):
        # 窗口是 date_window 的必需输入；null/坏值都是“窗口未提供”，不是模式非法。
        return unusable("fixture_sha256_unavailable")
    if fixture_sha is None:
        if payload is not None:
            # 未绑定的窗口 fixture 不得使用（§3.2 规则 3）。
            return unusable("fixture_unbound")
        return None, ()
    if not _is_sha256(fixture_sha):
        return unusable("fixture_sha256_invalid")
    if not isinstance(payload, Mapping):
        return unusable("fixture_missing")
    required = {"schema_version", "bindings", "windows", "open_ended", "basis", "evidence_ref"}
    if set(payload) != required:
        return unusable("fixture_field_invalid")
    if payload["schema_version"] != WINDOW_SCHEMA_VERSION:
        return unusable("fixture_schema_invalid")
    bindings = payload["bindings"]
    if not isinstance(bindings, Mapping) or set(bindings) != {
        "source_map_sha256",
        "ingest_plan_sha256",
    }:
        return unusable("fixture_binding_invalid")
    if not all(_is_sha256(value) for value in bindings.values()):
        return unusable("fixture_binding_invalid")
    for name in ("source_map_sha256", "ingest_plan_sha256"):
        declared = grounding.get(name)
        if declared is not None and declared != bindings[name]:
            return unusable("fixture_binding_mismatch")
    basis = payload["basis"]
    if not _enum_member(basis, WINDOW_BASES):
        # 只收主人裁定 / 保管转述；“从语料/元数据/行为反推”的来源一律拒收。
        return unusable("fixture_basis_rejected")
    if not _is_str(payload["evidence_ref"]):
        return unusable("fixture_evidence_ref_missing")
    open_ended = payload["open_ended"]
    if not isinstance(open_ended, list) or not all(_is_str(code) for code in open_ended):
        return unusable("fixture_open_ended_invalid")
    if len(set(open_ended)) != len(open_ended):
        return unusable("fixture_open_ended_invalid")
    entries = payload["windows"]
    if not isinstance(entries, Mapping) or not entries:
        return unusable("fixture_windows_missing")
    if any(code not in entries for code in open_ended):
        return unusable("fixture_open_ended_unknown_code")

    forbidden: set[date] = set()
    built_at = grounding.get("built_at")
    if built_at is not None:
        parsed_built_at = _parse_date(built_at)
        if parsed_built_at is None:
            return unusable("built_at_invalid")
        forbidden.add(parsed_built_at)
    header_dates = grounding.get("corpus_header_dates")
    if header_dates is not None:
        if not isinstance(header_dates, list):
            return unusable("corpus_header_dates_invalid")
        for value in header_dates:
            parsed = _parse_date(value)
            if parsed is None:
                return unusable("corpus_header_dates_invalid")
            forbidden.add(parsed)

    windows: dict[str, _Window] = {}
    for code, row in entries.items():
        if not _is_str(code) or not isinstance(row, Mapping):
            return unusable("window_entry_invalid")
        keys = set(row)
        if not keys <= {"effective_from", "effective_to"} or "effective_from" not in keys:
            return unusable("window_entry_invalid")
        effective_from = _parse_date(row["effective_from"])
        if effective_from is None:
            return unusable("window_entry_invalid")
        raw_to = row.get("effective_to")
        if raw_to is None:
            if code not in open_ended:
                # §3.2 规则 1：缺 `effective_to` 必须列进 `open_ended`。
                return unusable("window_half_open_unlisted")
            effective_to = None
        else:
            effective_to = _parse_date(raw_to)
            if effective_to is None or effective_to < effective_from:
                return unusable("window_entry_invalid")
            if code in open_ended:
                return unusable("window_open_ended_conflict")
        endpoints = {effective_from} | ({effective_to} if effective_to is not None else set())
        if endpoints & forbidden:
            # X-1 / X-2：构建基线/语料页眉常量不得冒充生效窗口。
            return unusable("window_value_is_corpus_constant")
        windows[code] = _Window(effective_from=effective_from, effective_to=effective_to)

    if len(windows) >= 2:
        shapes = {(window.effective_from, window.effective_to) for window in windows.values()}
        if len(shapes) == 1:
            # 全 corpus 同值 = 一眼可辨的伪窗口，整份拒收。
            return unusable("window_values_all_identical")
    return MappingProxyType(windows), ("stale_window_fixture_bound",)


# --------------------------------------------------------------------------- #
# 回合视图与判定
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _TurnView:
    turn_index: int
    inputs: Mapping[str, Any] | None
    malformed: str | None = None


@dataclass(frozen=True)
class TurnDetermination:
    turn_index: int
    state: str
    reason: str
    evidence_grade: str
    audit: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in AXIS_STATES:
            raise CriterionError("criterion_state_invalid")
        if not _enum_member(self.reason, DETERMINATION_CODES):
            raise CriterionError("criterion_code_unknown")
        if STATE_BY_CODE[self.reason] != self.state:
            raise CriterionError("criterion_state_reason_mismatch")
        if self.evidence_grade not in EVIDENCE_GRADES:
            raise CriterionError("criterion_grade_invalid")
        if self.state != "passed" and self.evidence_grade != "none":
            raise CriterionError("criterion_grade_on_non_pass")
        if self.state == "not_applicable":
            raise CriterionError("criterion_not_applicable_unreachable")

    def as_dict(self) -> dict[str, Any]:
        return {"turn_index": self.turn_index, "state": self.state, "reason": self.reason}


def _turn_views(evidence: Mapping[str, Any]) -> tuple[_TurnView, ...]:
    if "turns" not in evidence or evidence["turns"] is None:
        return (_TurnView(turn_index=0, inputs=evidence),)
    turns = evidence["turns"]
    if not isinstance(turns, list):
        return (_TurnView(turn_index=0, inputs=None, malformed="evidence_incomplete"),)
    if not turns:
        return (_TurnView(turn_index=0, inputs=None, malformed="turn_not_executed"),)
    views: list[_TurnView] = []
    seen: set[int] = set()
    for row in turns:
        if not isinstance(row, Mapping):
            _reject("evidence_incomplete", ("turn_not_mapping",))
        turn_index = row.get("turn_index")
        if not _is_int(turn_index) or turn_index < 0:
            _reject("evidence_incomplete", ("turn_index_invalid",))
        if turn_index in seen:
            _reject("evidence_incomplete", ("turn_index_duplicate",))
        seen.add(turn_index)
        inputs = row.get("state_inputs")
        if not isinstance(inputs, Mapping):
            views.append(_TurnView(turn_index, None, "evidence_incomplete"))
        else:
            views.append(_TurnView(turn_index, inputs))
    views.sort(key=lambda view: view.turn_index)
    return tuple(views)


def _runtime_as_of(inputs: Mapping[str, Any], evidence: Mapping[str, Any]) -> Any:
    if "as_of" in inputs:
        return inputs["as_of"]
    return evidence.get("as_of")


def _empty_use_proven(usage: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """空集闭包证明：**只**逐层读观测事实，不读任何派生布尔（F-8）。"""
    audit: list[str] = []
    if usage.get("turn_status") != "complete":
        return False, ("use_scope_turn_not_complete",)
    layers = usage.get("use_layers")
    if not isinstance(layers, Mapping) or not layers:
        return False, ("use_layers_missing",)
    for layer in layers.values():
        if not isinstance(layer, Mapping):
            return False, ("use_layer_invalid",)
        if layer.get("observed") is not True:
            return False, ("use_layer_not_observed",)
        count = layer.get("count")
        if not _is_int(count) or count != 0:
            return False, ("use_layer_nonzero",)
        refs = layer.get("refs", [])
        if not isinstance(refs, list) or refs:
            return False, ("use_layer_refs_nonempty",)
    retrieval = usage.get("retrieval")
    if not isinstance(retrieval, Mapping) or retrieval.get("observed") is not True:
        return False, ("retrieval_not_observed",)
    count = retrieval.get("count")
    if not _is_int(count) or count != 0:
        return False, ("retrieval_candidates_nonempty",)
    refs = retrieval.get("refs", [])
    if not isinstance(refs, list) or refs:
        return False, ("retrieval_candidates_nonempty",)
    if retrieval.get("truncated") is not False:
        return False, ("retrieval_candidates_truncated",)
    audit.append("retrieval_observed_empty_unit_ids")
    if any(key in usage for key in ("closure_proven", "empty_set_candidate")):
        audit.append("derived_closure_boolean_ignored")
    return True, tuple(audit)


def _unit_fields(unit: Any) -> tuple[str, str] | None:
    """P-5：``record_code`` 或 ``code`` 缺 → 身份不可解析。"""
    if not isinstance(unit, Mapping):
        return None
    allowed = {"unit_id", "code", "record_code", "document_id", "version_id"}
    if set(unit) - allowed:
        return None
    code = unit.get("code")
    record_code = unit.get("record_code")
    if not _is_str(code) or not _is_str(record_code):
        return None
    return code, record_code


def _date_conflict(annotation: Mapping[str, Any], as_of: Any) -> bool:
    """R-J-13：注解声明基准日 vs 运行期基准日（两者都非空且可解析）。"""
    declared = _parse_date(annotation.get("as_of"))
    runtime = _parse_date(as_of)
    return declared is not None and runtime is not None and declared != runtime


def _overlay_version_state_windows(
    context: _Context,
    used_codes: Sequence[str],
    as_of: Any,
) -> tuple[str | None, str, tuple[str, ...]]:
    """§5.4：`version_state` 模式下窗口只做**单向加严**。

    返回 ``(violation_code|None, evidence_grade, audit)``。窗口损毁/半端/不可解析只记
    audit，**不制造 unknown**（否则等于把可选证据变成必需证据）。
    """
    if context.windows is None:
        return None, "version_only", ()
    runtime = _parse_date(as_of)
    if runtime is None:
        return None, "version_only", ("stale_date_check_skipped_unresolved",)
    audit: list[str] = []
    checked = 0
    skipped = False
    for code in used_codes:
        window = context.windows.get(code)
        if window is None:
            skipped = True
            audit.append("stale_date_check_skipped_unresolved")
            continue
        checked += 1
        if not window.covers(runtime):
            return "stale_out_of_window", "version_plus_date", _dedupe(audit)
    if skipped or checked == 0:
        return None, "version_only", _dedupe(audit)
    return None, "version_plus_date", _dedupe(audit)


def _citation_check(
    inputs: Mapping[str, Any],
    units: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """R-J-11 / R-J-12：citation 层与 unit 的 document/version 一致性。"""
    if "citations" not in inputs:
        return (), ()
    citations = inputs["citations"]
    if not isinstance(citations, list):
        return (), ("source_unresolved",)
    rows: dict[str, Mapping[str, Any]] = {}
    for row in citations:
        if not isinstance(row, Mapping) or set(row) != {"unit_id", "document_id", "version_id"}:
            return (), ("source_unresolved",)
        if not all(_is_str(row[name]) for name in ("unit_id", "document_id", "version_id")):
            return (), ("source_unresolved",)
        if row["unit_id"] in rows:
            return (), ("source_unresolved",)
        rows[row["unit_id"]] = row
    violations: list[str] = []
    unknowns: list[str] = []
    for unit in units:
        unit_id = unit.get("unit_id")
        if not _is_str(unit_id):
            # 有 citation 层但 unit 没有可对齐的 unit_id → 投影行不可解析。
            unknowns.append("source_unresolved")
            continue
        row = rows.get(unit_id)
        if row is None:
            unknowns.append("source_unresolved")
            continue
        expected_document = unit.get("document_id")
        expected_version = unit.get("version_id")
        if not _is_str(expected_document) or not _is_str(expected_version):
            unknowns.append("source_unresolved")
            continue
        if row["document_id"] != expected_document or row["version_id"] != expected_version:
            violations.append("citation_version_mismatch")
    return tuple(violations), tuple(unknowns)


def _determine_turn(
    context: _Context,
    annotation: Mapping[str, Any],
    view: _TurnView,
    evidence: Mapping[str, Any],
) -> tuple[TurnDetermination, Mapping[str, _Active]]:
    if context.mode != "version_state" and context.mode != "date_window":
        raise CriterionError("criterion_mode_invalid")
    if view.malformed is not None:
        reason = view.malformed
        return (
            TurnDetermination(
                turn_index=view.turn_index,
                state="unknown",
                reason=reason,
                evidence_grade="none",
                audit=(reason,),
            ),
            {},
        )
    inputs = view.inputs or {}
    audit: list[str] = []
    usage = inputs.get("usage")
    if not isinstance(usage, Mapping):
        return _unknown_turn(view, "stale_usage_set_missing", ("usage_missing",)), {}
    inherited = usage.get("reason")
    if _enum_member(inherited, TURN_USAGE_REASONS):
        return _unknown_turn(view, inherited, (inherited,)), {}
    if usage.get("observed") is not True:
        return _unknown_turn(view, "stale_usage_set_missing", ("usage_not_observed",)), {}
    units = usage.get("units")
    if units is None:
        # F-7：有回答但使用层零观测 ⇒ unknown，绝不“没观测到 = 没用过 = pass”。
        return _unknown_turn(view, "stale_usage_set_missing", ("usage_units_missing",)), {}
    if not isinstance(units, list):
        return _unknown_turn(view, "stale_usage_set_missing", ("usage_units_invalid",)), {}

    as_of = _runtime_as_of(inputs, evidence)
    if context.mode == "date_window" and _parse_date(as_of) is None:
        # §5.4：date_window 的 as_of 缺失/非法 → unknown as_of_missing。
        return _unknown_turn(view, "as_of_missing", ("as_of_missing",)), {}

    violations: list[str] = []
    unknowns: list[str] = []
    conflicts = _date_conflict(annotation, as_of)

    if not units:
        if conflicts:
            return _violation_turn(view, "date_intent_conflict", ("date_intent_conflict",)), {}
        proven, proof_audit = _empty_use_proven(usage)
        audit.extend(proof_audit)
        if not proven:
            audit.append("empty_set_not_proven")
            return _unknown_turn(view, "empty_set_not_proven", audit), {}
        # 空集没有可做日期比较的源：不给日期分，固定 version_only。
        audit.append("stale_empty_use_scope_proven")
        return (
            TurnDetermination(
                turn_index=view.turn_index,
                state="passed",
                reason="stale_empty_use_scope_proven",
                evidence_grade="version_only",
                audit=_dedupe(audit),
            ),
            {},
        )

    resolved_actives: dict[str, _Active] = {}
    used_active_codes: list[str] = []
    checked_units: list[Mapping[str, Any]] = []
    for index, unit in enumerate(units):
        fields = _unit_fields(unit)
        if fields is None:
            # P-5：ref → 记录身份不可解析。
            audit.append(f"unit[{index}]:source_unresolved")
            unknowns.append("source_unresolved")
            continue
        code, _record_code = fields
        checked_units.append(unit)
        if code not in context.known_codes:
            # R-J-7：无法解析成任何已知源（先于“是否在册”判定）。
            audit.append(f"unit[{index}]:version_unresolved")
            unknowns.append("version_unresolved")
            continue
        base = context.code_to_base.get(code, code)
        if base not in context.groups:
            # R-J-6 / F-3：本 scenario 未上传该槽位 → 量具归属缺陷，不判产品失败。
            audit.append(f"unit[{index}]:stale_usage_source_not_in_scenario")
            unknowns.append("stale_active_version_ambiguous")
            continue
        if code not in context.member_codes(base):
            # R-J-6 的保守扩展：base 在册但该码不在本 scenario 上传集里，同样是
            # “用了本 scenario 没上传的源”，不得误判为“被取代”。
            audit.append(f"unit[{index}]:stale_usage_source_not_in_scenario")
            unknowns.append("stale_active_version_ambiguous")
            continue
        if context.mode == "version_state":
            active = context.active_for(base)
            if active is None:
                raise CriterionError("criterion_active_missing")
            resolved_actives[base] = active
            if code == active.code:
                audit.append(f"unit[{index}]:stale_active_version_used")
                used_active_codes.append(active.code)
            else:
                # R-J-5：同组、被后上传取代。
                audit.append(f"unit[{index}]:stale_superseded_version_used")
                violations.append("stale_superseded_version_used")
            continue
        runtime = _parse_date(as_of)
        if runtime is None:
            raise CriterionError("criterion_as_of_missing")
        status, covering = context.covering(base, runtime)
        if status == "unresolved":
            # §3.2 规则 5：成员窗口缺失/半端先于三态判定。
            audit.append(f"unit[{index}]:stale_window_unresolved")
            unknowns.append("stale_window_unresolved")
            continue
        if status == "ambiguous":
            # §3.2 规则 5：多 active 歧义 → 不得择一，也不进入 active 表。
            audit.append(f"unit[{index}]:stale_active_version_ambiguous")
            unknowns.append("stale_active_version_ambiguous")
            continue
        position_active = context.position_active.get(base)
        if status == "none":
            # F-4：全部窗口完整但无一覆盖 as_of ⇒ 该组在 as_of 无 active，使用即违规。
            audit.append(f"unit[{index}]:stale_out_of_window")
            violations.append("stale_out_of_window")
            continue
        active = covering[0]
        if position_active is not None and position_active.code != active.code:
            # §3.2 规则 6：窗口 active 与位置序 active 都存在且不同 → 不得择一。
            audit.append(f"unit[{index}]:stale_grounding_crosscheck_disagreement")
            unknowns.append("stale_active_version_ambiguous")
            continue
        resolved_actives[base] = active
        if code == active.code:
            audit.append(f"unit[{index}]:stale_source_dates_ok")
            used_active_codes.append(active.code)
        else:
            audit.append(f"unit[{index}]:stale_out_of_window")
            violations.append("stale_out_of_window")

    citation_violations, citation_unknowns = _citation_check(inputs, checked_units)
    violations.extend(citation_violations)
    unknowns.extend(citation_unknowns)

    if violations:
        if conflicts:
            # R-J-13 存在也不改判 stale 侧的结论；只作为额外审计记录。
            audit.append("date_intent_conflict")
        return _violation_turn(view, violations[0], audit), resolved_actives
    if conflicts:
        # R-J-9：任一 violation 优先于 unknown；R-J-13 是产品侧一致性 violation。
        audit.append("date_intent_conflict")
        return _violation_turn(view, "date_intent_conflict", audit), resolved_actives
    if unknowns:
        return _unknown_turn(view, unknowns[0], audit), resolved_actives

    if context.mode == "version_state":
        overlay_code, grade, overlay_audit = _overlay_version_state_windows(
            context, used_active_codes, as_of
        )
        audit.extend(overlay_audit)
        if overlay_code is not None:
            audit.append("stale_out_of_window")
            return _violation_turn(view, overlay_code, audit), resolved_actives
        audit.append("stale_active_version_used")
        return (
            TurnDetermination(
                turn_index=view.turn_index,
                state="passed",
                reason="stale_active_version_used",
                evidence_grade=grade,
                audit=_dedupe(audit),
            ),
            resolved_actives,
        )

    audit.append("stale_source_dates_ok")
    return (
        TurnDetermination(
            turn_index=view.turn_index,
            state="passed",
            reason="stale_source_dates_ok",
            evidence_grade="version_plus_date",
            audit=_dedupe(audit),
        ),
        resolved_actives,
    )


def _unknown_turn(
    view: _TurnView, reason: str, audit: Sequence[str]
) -> TurnDetermination:
    return TurnDetermination(
        turn_index=view.turn_index,
        state="unknown",
        reason=reason,
        evidence_grade="none",
        audit=_dedupe(tuple(audit)),
    )


def _violation_turn(
    view: _TurnView, reason: str, audit: Sequence[str]
) -> TurnDetermination:
    return TurnDetermination(
        turn_index=view.turn_index,
        state="violation",
        reason=reason,
        evidence_grade="none",
        audit=_dedupe(tuple(audit)),
    )


# --------------------------------------------------------------------------- #
# 折叠 + 单题输出
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CaseDetermination:
    case_id: str
    scenario_id: str | None
    state: str
    reason: str
    evidence_grade: str
    per_turn: tuple[TurnDetermination, ...]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.state not in AXIS_STATES:
            raise CriterionError("criterion_state_invalid")
        if not _enum_member(self.reason, DETERMINATION_CODES):
            raise CriterionError("criterion_code_unknown")
        if _enum_member(self.reason, RETIRED_CODES):
            raise CriterionError("criterion_retired_code_produced")
        if STATE_BY_CODE[self.reason] != self.state:
            raise CriterionError("criterion_state_reason_mismatch")
        if self.evidence_grade not in EVIDENCE_GRADES:
            raise CriterionError("criterion_grade_invalid")
        if self.state != "passed" and self.evidence_grade != "none":
            raise CriterionError("criterion_grade_on_non_pass")
        if self.state == "not_applicable":
            raise CriterionError("criterion_not_applicable_unreachable")
        if not self.per_turn:
            raise CriterionError("criterion_turn_missing")
        winner = _fold(self.per_turn)
        if (winner.state, winner.reason) != (self.state, self.reason):
            raise CriterionError("criterion_fold_mismatch")
        _assert_no_forbidden_tokens(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scenario_id": self.scenario_id,
            "state": self.state,
            "reason": self.reason,
            "evidence_grade": self.evidence_grade,
            "per_turn": [turn.as_dict() for turn in self.per_turn],
            "provenance": dict(self.provenance),
        }


def _fold(turns: Sequence[TurnDetermination]) -> TurnDetermination:
    """§5.6：violation > unknown > not_applicable > passed；并列取回合序最小。"""
    return max(turns, key=lambda turn: (STATE_PRIORITY[turn.state], -turn.turn_index))


def _assert_no_forbidden_tokens(value: Any) -> None:
    """I-5：输出不得出现 ``verified`` / ``threshold`` / ``release`` **字段**。

    只扫键名：``state`` / ``reason`` / ``evidence_grade`` 已由固定枚举约束，
    回显的 ``case_id`` / ``scenario_id`` 是输入值而非结论。
    """
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_no_forbidden_tokens(key)
            _assert_no_forbidden_tokens(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _assert_no_forbidden_tokens(child)
        return
    if isinstance(value, str):
        lowered = value.lower()
        for token in _FORBIDDEN_OUTPUT_TOKENS:
            if token in lowered:
                raise CriterionError(f"criterion_forbidden_output_token:{token}")


def _unknown_case(
    case_id: str,
    scenario_id: str | None,
    code: str,
    *,
    mode: str | None,
    audit: Sequence[str],
) -> CaseDetermination:
    turn = TurnDetermination(
        turn_index=0,
        state="unknown",
        reason=code,
        evidence_grade="none",
        audit=_dedupe(tuple(audit)),
    )
    return CaseDetermination(
        case_id=case_id,
        scenario_id=scenario_id,
        state="unknown",
        reason=code,
        evidence_grade="none",
        per_turn=(turn,),
        provenance=_freeze(
            {
                "grounding_mode": mode,
                "active_versions": {},
                "audit": list(turn.audit),
            }
        ),
    )


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


def determine_stale_case(
    criterion_version: str,
    grounding: Any,
    evidence: Any,
) -> CaseDetermination:
    """单题入口（规范 §12.1）：任何缺项/歧义/不可解析 → 固定码 + unknown。"""
    case_id = ""
    if isinstance(evidence, Mapping) and _is_str(evidence.get("case_id")):
        case_id = evidence["case_id"]
    scenario_id: str | None = None
    if isinstance(grounding, Mapping):
        scenario = grounding.get("scenario")
        if isinstance(scenario, Mapping) and _is_str(scenario.get("scenario_id")):
            scenario_id = scenario["scenario_id"]
    mode: str | None = None
    try:
        if criterion_version != CRITERION_VERSION:
            _reject("stale_grounding_mode_invalid", ("criterion_version_mismatch",))
        if not isinstance(evidence, Mapping):
            _reject("evidence_incomplete", ("evidence_not_mapping",))
        unknown = set(evidence) - _EVIDENCE_KEYS
        if unknown:
            _reject(
                "evidence_incomplete",
                tuple(f"criterion_field_invalid:{key}" for key in sorted(unknown, key=str)),
            )
        annotation = _load_annotation(evidence)
        mode = _load_mode(grounding)
        scenario_id, indices, has_ingest_batches = _load_scenario(grounding)
        sources = _load_ingest_plan(grounding, indices)
        aliases, versions = _load_source_map(grounding)
        windows, window_audit = _load_windows(grounding, mode)
        context = _build_context(
            mode,
            scenario_id,
            indices,
            sources,
            aliases,
            versions,
            windows,
            tuple(window_audit)
            + (("stale_batch_count_opaque",) if has_ingest_batches else ()),
        )
        views = _turn_views(evidence)
        results = [
            _determine_turn(context, annotation, view, evidence) for view in views
        ]
        turns = tuple(result[0] for result in results)
        winner = _fold(turns)
        actives: dict[str, _Active] = {}
        if mode == "version_state":
            actives.update(context.position_active)
        else:
            for _turn, resolved in results:
                for base, active in resolved.items():
                    actives.setdefault(base, active)
        audit: list[str] = list(context.audit)
        audit.extend(winner.audit)
        for turn in turns:
            if (turn.state, turn.reason) != (winner.state, winner.reason):
                # §5.6：被折叠掉的回合码必须留在 audit 里，不得静默丢弃。
                audit.extend(f"turn[{turn.turn_index}]:{token}" for token in turn.audit)
                audit.append(f"turn[{turn.turn_index}]:{turn.state}:{turn.reason}")
        return CaseDetermination(
            case_id=case_id,
            scenario_id=scenario_id,
            state=winner.state,
            reason=winner.reason,
            evidence_grade=winner.evidence_grade,
            per_turn=turns,
            provenance=_freeze(
                {
                    "grounding_mode": mode,
                    "active_versions": {
                        base: active.as_dict() for base, active in sorted(actives.items())
                    },
                    "audit": list(_dedupe(audit)),
                }
            ),
        )
    except _Reject as exc:
        return _unknown_case(
            case_id,
            scenario_id,
            exc.code,
            mode=mode,
            audit=exc.audit,
        )


# --------------------------------------------------------------------------- #
# 聚合（§8.2 的三条计数公式 + v1 两条额外不变量）
# --------------------------------------------------------------------------- #


def aggregate_cases(determinations: Sequence[CaseDetermination]) -> dict[str, Any]:
    states = [determination.state for determination in determinations]
    passed = states.count("passed")
    not_applicable = states.count("not_applicable")
    unknown = states.count("unknown")
    violations = states.count("violation")
    passed_version_only = sum(
        1
        for determination in determinations
        if determination.state == "passed"
        and determination.evidence_grade == "version_only"
    )
    passed_version_plus_date = sum(
        1
        for determination in determinations
        if determination.state == "passed"
        and determination.evidence_grade == "version_plus_date"
    )
    counts = {
        "planned": len(states),
        "passed": passed,
        "not_applicable": not_applicable,
        "unknown": unknown,
        "violations": violations,
        "checked": passed + not_applicable + violations,
        "passed_version_only": passed_version_only,
        "passed_version_plus_date": passed_version_plus_date,
    }
    if counts["planned"] != passed + not_applicable + unknown + violations:
        raise CriterionError("axis_counts_inconsistent")
    if counts["checked"] != passed + not_applicable + violations:
        raise CriterionError("axis_counts_inconsistent")
    if counts["planned"] != counts["checked"] + unknown:
        raise CriterionError("axis_counts_inconsistent")
    if not_applicable != 0:
        # §5.7：本轴 not_applicable 不可达；产出即 non-conformant。
        raise CriterionError("not_applicable_unreachable")
    if passed != passed_version_only + passed_version_plus_date:
        raise CriterionError("axis_counts_inconsistent")
    return {
        "criterion_version": CRITERION_VERSION,
        "counts": counts,
        "axes_provenance": "rescored",
    }


def reason_histogram(determinations: Sequence[CaseDetermination]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for determination in determinations:
        counts[determination.reason] = counts.get(determination.reason, 0) + 1
    return dict(sorted(counts.items()))
