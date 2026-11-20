"""C1-P4：消费侧适配 v2（合同 v2 + 运行期身份快照 v0.3）。

本模块只做**消费侧**：把调用方已解密并校验过的合同 v2
（``q1a-scope-targets-contract/v2``）与 P3 身份快照
（``p2-runtime-identity-snapshot/v0.1``）映射成 ``cross_entity`` /
``stale_source`` 的逐题判定。

边界：

- **零真实调用**：不读密文/key/``.env``，不读真实 H2 题面/标签/答案，不调用产品/
  模型/embedding/rerank/OCR/裁判/检索/鉴权/余额，不发起任何网络连接。
- **不改已接收模块**：Q1a-1（``p2_evidence_rescore.py``）、Q1a-1b
  （``p2_evidence_rescore_axes.py``）、P3（``p2_evidence_snapshot_v03.py``）与
  C 冻结 12 均为**只读** import；本模块只复用它们的公开常量与字段表。
- ``safety`` / ``cross_user`` 仍走 Q1a-1/Q1a-1b 现有路径；本适配器拒绝为它们出判定
  （固定码 ``axis_delegated_to_q1a1b``）。
- **版本分派显式**：v1 合同被本适配器以 ``contract_version_v1_rejected_by_v2_adapter``
  拒绝；v2 的 ``contract_schema_sha256`` 与 v1 常量不同，载荷若把 v1 schema 摘要绑到
  v2 版本上即 ``contract_schema_binding_mismatch``。不把 v1 常量放宽成“任意版本都收”。
- **M-C1P1-01（转换假象）**：document 级目标 + unit 级使用**不得**输出 violation，只能
  unknown ``target_granularity_incomparable``；唯一例外是目标已显式降为 doc_code 级
  （``entity_type="document"``、``entity_key`` 是语料 doc_code 而非运行期 uuid、``filters``
  为空）且使用侧逐条记录身份可解析（``record_level=true`` 且 ``record_code`` 非空）。
- **M-C1P2-01（class C）**：空使用集证明遇到 ``retrieval_observed.observed=false`` +
  ``candidates=[]`` 的 class C 形状，必须 ``empty_set_not_proven``（unknown），不得 proven。
- **fail closed**：缺合同/缺轴/缺快照字段/身份不可解析 → 固定码 + unknown；不 ``getattr``
  默认、不静默 pass、不把 unknown 改 N/A。
- ``basis`` 只进 provenance，不参与 verdict 折叠；输出不含 ``verified`` / ``threshold`` /
  ``release`` 任何结论。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any

from .p2_evidence_rescore import AXES, AXIS_STATES
from .p2_evidence_rescore_axes import (
    ANNOTATION_APPLICABILITIES,
    ANNOTATION_REASONS,
    Q1A2_AXIS_KEYS,
    Q1A2_BASIS_CODES,
    Q1A2_BINDING_KEYS,
    Q1A2_CASE_KEYS,
    Q1A2_CONTRACT_SCHEMA_VERSION,
    Q1A2_RUN_KEYS,
    Q1A2_SCENARIO_IDS,
    Q1A2_AXIS_CRITERIA,
    TEMPORAL_INTENTS,
)
from .p2_evidence_snapshot_v03 import (
    CANDIDATE_LAYER_NAMES,
    CONTRACT_VERSION as SNAPSHOT_CONTRACT_VERSION,
    ENTITY_CODES,
    ENTITY_ROLE_NAMES,
    FIXTURE_KINDS,
    LOCATOR_KINDS,
    MATCHABLE_ENTITY_TYPES,
    PRODUCT_ENTITY_TYPES,
    RECORD_IDENTITY_CODES,
    SNAPSHOT_SCHEMA_VERSION,
    USE_LAYER_NAMES,
    identity_field_table,
)
from ..rag.chunking import normalize_field

__all__ = [
    "ADAPTED_AXES",
    "ADAPTER_SCHEMA_VERSION",
    "AXIS_STATES",
    "CONTRACT_SCHEMA_VERSION_V1",
    "CONTRACT_SCHEMA_VERSION_V2",
    "DELEGATED_AXES",
    "FIXED_CODES",
    "KNOWN_CONTRACT_SCHEMA_SHA256",
    "PROJECTION_RULE_VERSION_V2",
    "AdapterError",
    "AxisCounts",
    "AxisDetermination",
    "CaseDetermination",
    "ContractAxisView",
    "ContractCaseView",
    "ContractV2View",
    "SnapshotRecordView",
    "SnapshotView",
    "TargetView",
    "aggregate_axis",
    "determine_axis",
    "determine_case",
    "reason_histogram",
    "determine_cross_entity",
    "determine_stale_source",
    "load_contract_v2",
    "load_snapshot_v03",
    "validate_determination",
]

#: 本适配器版本（不是合同/快照版本）。
ADAPTER_SCHEMA_VERSION = "p2-evidence-axes-adapter/v2"

CONTRACT_SCHEMA_VERSION_V1 = "q1a-scope-targets-contract/v1"
CONTRACT_SCHEMA_VERSION_V2 = "q1a-scope-targets-contract/v2"
PROJECTION_RULE_VERSION_V2 = "q1a-scope-targets-projection/v2"

#: 管理者回执钉住的公开 schema 摘要（v1 用于**拒绝**跨版本复用，v2 用于绑定核对）。
KNOWN_CONTRACT_SCHEMA_SHA256: Mapping[str, str] = MappingProxyType(
    {
        CONTRACT_SCHEMA_VERSION_V1: (
            "cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690"
        ),
        CONTRACT_SCHEMA_VERSION_V2: (
            "b98f9f4aab296dd3bec610dc81485142d9cb751a1402a117f14dc30fc515ce25"
        ),
    }
)

#: 本适配器负责的两轴；``safety`` / ``cross_user`` 仍走既有路径。
ADAPTED_AXES: tuple[str, ...] = ("cross_entity", "stale_source")
DELEGATED_AXES: tuple[str, ...] = ("safety", "cross_user")

TARGET_REF_COLLECTIONS: tuple[str, ...] = (
    "expected_sources",
    "relevant_units",
    "forbidden_sources",
)

#: 合同 v2 明文载荷的 6 个顶层键（v2 §3）。
CONTRACT_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"schema_version", "bindings", "runs", "case_count", "cases", "projection"}
)
#: v2 §3.5 的 projection 必须声明的规则版本。
PROJECTION_KEYS: frozenset[str] = frozenset(
    {
        "rule_version",
        "lineage",
        "corpus_bindings",
        "entity_rule",
        "record_identities",
        "target_provenance",
        "axis_codes",
        "shared_background_corpus",
        "coverage",
    }
)

#: 运行期 doc_code 的形态约束：非空、无 ``|``、非 uuid/长 hex、长度受限。
_DOC_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_LONG_HEX_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --------------------------------------------------------------------------- #
# 固定码表（每个 fail-closed 分支必须落到其中一个）
# --------------------------------------------------------------------------- #

#: 合同侧（含显式版本分派）。
CONTRACT_CODES: frozenset[str] = frozenset(
    {
        "contract_missing",
        "contract_schema_invalid",
        "contract_axis_invalid",
        "contract_target_invalid",
        "contract_basis_invalid",
        "contract_version_v1_rejected_by_v2_adapter",
        "contract_version_unsupported",
        "contract_binding_mismatch",
        "contract_schema_binding_mismatch",
        "contract_case_missing",
        "contract_run_missing",
        "contract_projection_invalid",
        "contract_unknown_downgraded",
    }
)

#: 快照侧；``<family>:<path>`` 用于字段级错误。
SNAPSHOT_CODES: frozenset[str] = frozenset(
    {
        "snapshot_missing",
        "snapshot_envelope_invalid",
        "snapshot_contract_version_invalid",
        "snapshot_schema_version_invalid",
        "snapshot_fixture_binding_mismatch",
        "snapshot_fixture_kind_invalid",
        "snapshot_run_binding_mismatch",
        "snapshot_scenario_binding_mismatch",
        "snapshot_turn_binding_mismatch",
        "snapshot_source_evidence_incomplete",
        "snapshot_source_evidence_replayed",
        "snapshot_summary_mismatch",
        "snapshot_field_missing",
        "snapshot_field_invalid",
        "snapshot_unknown_field",
        "snapshot_enum_invalid",
    }
)
SNAPSHOT_FIELD_CODE_FAMILIES: frozenset[str] = frozenset(
    {
        "snapshot_field_missing",
        "snapshot_field_invalid",
        "snapshot_unknown_field",
        "snapshot_enum_invalid",
    }
)

#: 判定语义 unknown 码。
SEMANTIC_UNKNOWN_CODES: frozenset[str] = frozenset(
    {
        "annotation_unknown",
        "targets_missing",
        "targets_unresolved",
        "multi_target_lt2",
        "target_granularity_incomparable",
        "entity_key_space_incompatible",
        "identity_unresolved",
        "empty_set_not_proven",
        "shared_background_runtime_identity_unavailable",
        "entity_scope_conflict",
        "stale_no_positive_refs",
        "stale_source_unresolved",
        "stale_positive_ref_not_record_level",
        "as_of_missing",
        "version_unresolved",
        "version_mismatch",
        "stale_lifecycle_evidence_missing",
    }
)

#: 适配器自身不变量（不是合同/快照语义）。
ADAPTER_CODES: frozenset[str] = frozenset(
    {
        "axis_delegated_to_q1a1b",
        "axis_not_adapted",
        "axis_counts_inconsistent",
        "adapter_invariant_violation",
        "unknown_to_not_applicable_forbidden",
    }
)

PASS_CODES: frozenset[str] = frozenset(
    {
        "cross_entity_targets_match_ok",
        "cross_entity_empty_use_scope_ok",
        "stale_source_dates_ok",
    }
)
NOT_APPLICABLE_CODE = "no_entity_scope_verified"
VIOLATION_CODES: frozenset[str] = frozenset(
    {
        "other_entity_used",
        "citation_entity_mismatch",
        "date_intent_conflict",
    }
)

UNKNOWN_CODES: frozenset[str] = (
    CONTRACT_CODES | SNAPSHOT_CODES | SEMANTIC_UNKNOWN_CODES | ADAPTER_CODES
)

FIXED_CODES: frozenset[str] = (
    CONTRACT_CODES | SNAPSHOT_CODES | SEMANTIC_UNKNOWN_CODES | ADAPTER_CODES | PASS_CODES | VIOLATION_CODES | {NOT_APPLICABLE_CODE}
)


class AdapterError(RuntimeError):
    """固定码异常：``code`` ∈ ``FIXED_CODES`` 或 ``<family>:<path>``。"""

    def __init__(self, code: str) -> None:
        head = str(code).split(":", 1)[0]
        _require(head in FIXED_CODES, f"adapter_invariant_violation:{code}")
        super().__init__(code)
        self.code = code


def _require(condition: Any, code: str) -> None:
    if not condition:
        raise AdapterError(code)


def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or _ISO_DATE_RE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_scalar(value: Any) -> bool:
    return value is None or type(value) in (str, int, float, bool)


def _enum_member(value: Any, allowed: Any) -> bool:
    """标量枚举成员判断（``IR-01``）。

    ``value in frozenset`` 对 JSON 数组/对象会抛 ``TypeError``（不可哈希）并逃出
    ``determine_case``。所有枚举校验必须先过 ``isinstance(value, str)``：
    非字符串一律当“不在枚举里”，落回既有固定码，**不抛裸异常**。
    """
    return isinstance(value, str) and value in allowed


#: 进入公开 provenance 的合同码只允许固定码形态，且不得含结论词。
_CODE_SHAPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_OUTPUT_FORBIDDEN_TOKENS = ("verified", "threshold", "release")


def _is_code_shape(value: Any) -> bool:
    if not isinstance(value, str) or _CODE_SHAPE_RE.fullmatch(value) is None:
        return False
    return not any(token in value for token in _OUTPUT_FORBIDDEN_TOKENS)


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


def _code_with_path(family: str, path: str) -> str:
    return f"{family}:{path}" if path else family


def _is_unknown_reason(reason: str) -> bool:
    head = reason.split(":", 1)[0]
    return head in UNKNOWN_CODES


# --------------------------------------------------------------------------- #
# 合同 v2 视图（只消费调用方已解密的明文载荷）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TargetView:
    """合同 v2 的 3 键 target + 消费侧 ``matchable``/粒度判定（v2 §3.4/§4.4）。"""

    index: int
    entity_type: str
    entity_key: str
    filters: Mapping[str, Any]
    matchable: bool
    granularity: str
    code: str

    def __post_init__(self) -> None:
        _require(type(self.index) is int and self.index >= 0, "contract_target_invalid")
        _require(_is_str(self.entity_type), "contract_target_invalid")
        _require(isinstance(self.entity_key, str), "contract_target_invalid")
        _require(isinstance(self.filters, Mapping), "contract_target_invalid")
        _require(self.granularity in {"record", "doc_code", "document", "unmatchable"}, "contract_target_invalid")


@dataclass(frozen=True)
class ContractAxisView:
    axis: str
    applicability: str
    criterion: str
    reason: str
    target_refs: tuple[Mapping[str, Any], ...]
    targets: tuple[TargetView, ...]
    as_of: str | None
    temporal_intent: str
    basis: str
    target_provenance: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _require(self.axis in AXES, "contract_axis_invalid")
        _require(_enum_member(self.applicability, ANNOTATION_APPLICABILITIES), "contract_axis_invalid")
        _require(_enum_member(self.criterion, Q1A2_AXIS_CRITERIA[self.axis]), "contract_axis_invalid")
        _require(_enum_member(self.reason, ANNOTATION_REASONS), "contract_axis_invalid")
        _require(_enum_member(self.temporal_intent, TEMPORAL_INTENTS), "contract_axis_invalid")
        _require(self.as_of is None or _is_iso_date(self.as_of), "contract_axis_invalid")
        _require(_enum_member(self.basis, Q1A2_BASIS_CODES), "contract_basis_invalid")
        _require(isinstance(self.targets, tuple), "contract_target_invalid")


@dataclass(frozen=True)
class ContractCaseView:
    case_id: str
    case_index: int
    scenario_id: str
    axes: Mapping[str, ContractAxisView]
    basis: Mapping[str, str]

    def __post_init__(self) -> None:
        _require(_is_str(self.case_id), "contract_schema_invalid")
        _require(type(self.case_index) is int and self.case_index >= 0, "contract_schema_invalid")
        _require(self.scenario_id in Q1A2_SCENARIO_IDS, "contract_schema_invalid")
        _require(set(self.axes) == set(AXES), "contract_axis_invalid")
        _require(set(self.basis) == set(AXES), "contract_basis_invalid")


@dataclass(frozen=True)
class ContractV2View:
    schema_version: str
    bindings: Mapping[str, str]
    runs: tuple[Mapping[str, Any], ...]
    cases: Mapping[str, ContractCaseView]
    case_count: int
    projection: Mapping[str, Any]

    def for_case(self, case_id: str) -> ContractCaseView | None:
        return self.cases.get(str(case_id))

    def run_for_scenario(self, scenario_id: str) -> Mapping[str, Any] | None:
        for run in self.runs:
            if run["scenario_id"] == scenario_id:
                return run
        return None


def _target_view(index: int, row: Any) -> TargetView:
    _require(
        isinstance(row, Mapping) and set(row) == {"entity_type", "entity_key", "filters"},
        "contract_target_invalid",
    )
    entity_type = row["entity_type"]
    entity_key = row["entity_key"]
    filters = row["filters"]
    _require(_is_str(entity_type) and len(entity_type) <= 256, "contract_target_invalid")
    _require(isinstance(entity_key, str) and len(entity_key) <= 256, "contract_target_invalid")
    _require(isinstance(filters, Mapping), "contract_target_invalid")
    _require(all(_is_str(key) and _is_scalar(value) for key, value in filters.items()), "contract_target_invalid")

    role_only = all(isinstance(key, str) and key in ENTITY_ROLE_NAMES for key in filters)
    if entity_type not in PRODUCT_ENTITY_TYPES:
        code = "target_entity_type_not_product_vocabulary"
        granularity = "unmatchable"
        matchable = False
    elif entity_type == "document":
        if not filters and _is_doc_code_level_key(entity_key):
            code = "target_doc_code_level"
            granularity = "doc_code"
        else:
            code = "target_document_level"
            granularity = "document"
        matchable = False
    elif entity_type in MATCHABLE_ENTITY_TYPES and bool(entity_key) and role_only:
        code = "target_matchable"
        granularity = "record"
        matchable = True
    else:
        code = "target_nonrole_filters" if not role_only else "target_not_matchable"
        granularity = "unmatchable"
        matchable = False
    return TargetView(
        index=index,
        entity_type=entity_type,
        entity_key=entity_key,
        filters=_freeze(filters),
        matchable=matchable,
        granularity=granularity,
        code=code,
    )


def _is_doc_code_level_key(entity_key: str) -> bool:
    """doc_code 级降级键：语料 doc_code 形态，且**不是**运行期 uuid/``document|…``。"""
    if not entity_key or "|" in entity_key:
        return False
    if _UUID_RE.fullmatch(entity_key) is not None:
        return False
    if _LONG_HEX_RE.fullmatch(entity_key) is not None:
        return False
    return _DOC_CODE_RE.fullmatch(entity_key) is not None


def _load_bindings(raw: Any, expected_schema_sha256: str | None) -> Mapping[str, str]:
    _require(isinstance(raw, Mapping), "contract_binding_mismatch")
    _require(set(raw) == set(Q1A2_BINDING_KEYS), "contract_binding_mismatch")
    values: dict[str, str] = {}
    for key in Q1A2_BINDING_KEYS:
        value = raw[key]
        _require(_is_str(value), "contract_binding_mismatch")
        if key not in {"dataset_version", "label_version"}:
            _require(_is_sha256(value), "contract_binding_mismatch")
        values[key] = value
    _require(values["dataset_version"] == "P2-HOLDOUT-v2", "contract_binding_mismatch")
    _require(values["label_version"] == "p2-holdout-v2-2026-11-10", "contract_binding_mismatch")
    schema_sha = values["contract_schema_sha256"]
    if schema_sha == KNOWN_CONTRACT_SCHEMA_SHA256[CONTRACT_SCHEMA_VERSION_V1]:
        # 显式版本分派：v1 的 schema 摘要不得被 v2 版本标签复用。
        raise AdapterError("contract_schema_binding_mismatch")
    if expected_schema_sha256 is None:
        # 默认只接受管理者回执钉住的 v2 schema 摘要，不接受“任意 64 hex”。
        _require(
            schema_sha == KNOWN_CONTRACT_SCHEMA_SHA256[CONTRACT_SCHEMA_VERSION_V2],
            "contract_schema_binding_mismatch",
        )
    else:
        _require(_is_sha256(expected_schema_sha256), "contract_schema_binding_mismatch")
        _require(
            expected_schema_sha256
            != KNOWN_CONTRACT_SCHEMA_SHA256[CONTRACT_SCHEMA_VERSION_V1],
            "contract_schema_binding_mismatch",
        )
        _require(expected_schema_sha256 == schema_sha, "contract_schema_binding_mismatch")
    return _freeze(values)


def _load_runs(raw: Any) -> tuple[Mapping[str, Any], ...]:
    _require(isinstance(raw, list) and len(raw) == len(Q1A2_SCENARIO_IDS), "contract_schema_invalid")
    runs: list[Mapping[str, Any]] = []
    for index, row in enumerate(raw):
        _require(isinstance(row, Mapping) and set(row) == Q1A2_RUN_KEYS, "contract_schema_invalid")
        _require(type(row["run_index"]) is int and row["run_index"] == index, "contract_schema_invalid")
        _require(row["scenario_id"] == Q1A2_SCENARIO_IDS[index], "contract_schema_invalid")
        _require(_is_str(row["run_id"]) and len(row["run_id"]) <= 96, "contract_schema_invalid")
        _require(_is_str(row["plan_id"]) and len(row["plan_id"]) <= 96, "contract_schema_invalid")
        _require(_is_sha256(row["plan_sha256"]), "contract_schema_invalid")
        runs.append(
            MappingProxyType(
                {
                    "run_index": index,
                    "scenario_id": row["scenario_id"],
                    "run_id": row["run_id"],
                    "plan_id": row["plan_id"],
                    "plan_sha256": row["plan_sha256"],
                }
            )
        )
    return tuple(runs)


def _load_projection(raw: Any) -> Mapping[str, Any]:
    _require(isinstance(raw, Mapping), "contract_projection_invalid")
    _require(set(raw) == set(PROJECTION_KEYS), "contract_projection_invalid")
    _require(raw["rule_version"] == PROJECTION_RULE_VERSION_V2, "contract_projection_invalid")
    for key in ("lineage", "corpus_bindings", "entity_rule", "shared_background_corpus", "coverage"):
        _require(isinstance(raw[key], Mapping), "contract_projection_invalid")
    _require(isinstance(raw["record_identities"], list), "contract_projection_invalid")
    for key in ("target_provenance", "axis_codes"):
        table = raw[key]
        _require(isinstance(table, Mapping), "contract_projection_invalid")
        for axis_key, rows in table.items():
            _require(isinstance(axis_key, str) and "|" in axis_key, "contract_projection_invalid")
            _require(isinstance(rows, list), "contract_projection_invalid")
            if key == "axis_codes":
                _require(all(isinstance(row, str) and bool(row) for row in rows), "contract_projection_invalid")
                continue
            for row in rows:
                _require(
                    isinstance(row, Mapping)
                    and set(row) == {"target_index", "action", "source", "basis"}
                    and type(row["target_index"]) is int
                    and row["target_index"] >= 0
                    and all(_is_str(row[name]) for name in ("action", "source", "basis"))
                    and all(_is_code_shape(row[name]) for name in ("action", "source", "basis")),
                    "contract_projection_invalid",
                )
    return MappingProxyType(dict(raw))


def _load_axis(case_index: int, axis: str, payload: Any, basis: str, projection: Mapping[str, Any]) -> ContractAxisView:
    _require(isinstance(payload, Mapping) and set(payload) == Q1A2_AXIS_KEYS, "contract_axis_invalid")
    applicability = payload["applicability"]
    criterion = payload["criterion"]
    reason = payload["reason"]
    target_refs = payload["target_refs"]
    targets_raw = payload["targets"]
    as_of = payload["as_of"]
    temporal_intent = payload["temporal_intent"]

    _require(_enum_member(applicability, ANNOTATION_APPLICABILITIES), "contract_axis_invalid")
    _require(_enum_member(criterion, Q1A2_AXIS_CRITERIA[axis]), "contract_axis_invalid")
    _require(_enum_member(reason, ANNOTATION_REASONS), "contract_axis_invalid")
    _require(as_of is None or _is_iso_date(as_of), "contract_axis_invalid")
    _require(_enum_member(temporal_intent, TEMPORAL_INTENTS), "contract_axis_invalid")
    _require(_enum_member(basis, Q1A2_BASIS_CODES), "contract_basis_invalid")
    if applicability == "not_applicable" and reason in {
        "ambiguous_semantics",
        "unresolved_target",
        "source_state_conflict",
        "third_state_required",
        "insufficient_annotation",
    }:
        raise AdapterError("contract_unknown_downgraded")
    if basis == "no_provable_basis_keep_unknown":
        _require(applicability == "unknown", "contract_basis_invalid")
    if axis in ("cross_user", "stale_source"):
        _require(applicability == "required", "contract_axis_invalid")
    if axis == "cross_entity" and applicability == "not_applicable":
        _require(criterion == "no_entity_claim", "contract_axis_invalid")

    _require(isinstance(target_refs, list), "contract_axis_invalid")
    resolved_refs: list[Mapping[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for index, ref in enumerate(target_refs):
        _require(isinstance(ref, Mapping) and set(ref) == {"collection", "index"}, "contract_axis_invalid")
        collection = ref["collection"]
        ref_index = ref["index"]
        _require(
            isinstance(collection, str)
            and collection in TARGET_REF_COLLECTIONS
            and type(ref_index) is int
            and ref_index >= 0,
            "contract_axis_invalid",
        )
        key = (collection, ref_index)
        _require(key not in seen, "contract_axis_invalid")
        seen.add(key)
        resolved_refs.append(MappingProxyType({"collection": collection, "index": ref_index}))

    _require(isinstance(targets_raw, list), "contract_target_invalid")
    targets = tuple(_target_view(index, row) for index, row in enumerate(targets_raw))
    if criterion == "shared_background":
        _require(not targets, "contract_axis_invalid")

    key = f"{case_index}|{axis}"
    provenance_rows = projection["target_provenance"].get(key, [])
    return ContractAxisView(
        axis=axis,
        applicability=applicability,
        criterion=criterion,
        reason=reason,
        target_refs=tuple(resolved_refs),
        targets=targets,
        as_of=as_of,
        temporal_intent=temporal_intent,
        basis=basis,
        target_provenance=tuple(MappingProxyType(dict(row)) for row in provenance_rows),
    )


def load_contract_v2(
    payload: Any,
    *,
    expected_schema_sha256: str | None = None,
) -> ContractV2View:
    """校验并加载合同 v2 明文载荷（不做解密、不读密文、不联网）。

    显式版本分派：v1 → ``contract_version_v1_rejected_by_v2_adapter``；其它 →
    ``contract_version_unsupported``。结构/绑定/覆盖/轴/projection 错误分别以固定码拒绝。
    """
    _require(isinstance(payload, Mapping), "contract_missing")
    _require("schema_version" in payload, "contract_missing")
    version = payload["schema_version"]
    if version == CONTRACT_SCHEMA_VERSION_V1 or version == Q1A2_CONTRACT_SCHEMA_VERSION:
        raise AdapterError("contract_version_v1_rejected_by_v2_adapter")
    if version != CONTRACT_SCHEMA_VERSION_V2:
        raise AdapterError("contract_version_unsupported")
    _require(set(payload) == set(CONTRACT_TOP_LEVEL_KEYS), "contract_schema_invalid")

    bindings = _load_bindings(payload["bindings"], expected_schema_sha256)
    runs = _load_runs(payload["runs"])
    projection = _load_projection(payload["projection"])

    case_count = payload["case_count"]
    cases_raw = payload["cases"]
    _require(type(case_count) is int and case_count == 30, "contract_schema_invalid")
    _require(isinstance(cases_raw, list) and len(cases_raw) == case_count, "contract_schema_invalid")

    cases: dict[str, ContractCaseView] = {}
    for index, row in enumerate(cases_raw):
        _require(isinstance(row, Mapping) and set(row) == Q1A2_CASE_KEYS, "contract_schema_invalid")
        _require(type(row["case_index"]) is int and row["case_index"] == index, "contract_schema_invalid")
        case_id = row["case_id"]
        _require(_is_str(case_id), "contract_schema_invalid")
        _require(case_id not in cases, "contract_schema_invalid")
        scenario_id = row["scenario_id"]
        _require(scenario_id in Q1A2_SCENARIO_IDS, "contract_schema_invalid")
        axes_raw = row["axes"]
        basis_raw = row["basis"]
        _require(isinstance(axes_raw, Mapping) and set(axes_raw) == set(AXES), "contract_axis_invalid")
        _require(isinstance(basis_raw, Mapping) and set(basis_raw) == set(AXES), "contract_basis_invalid")
        basis: dict[str, str] = {}
        for axis in AXES:
            value = basis_raw[axis]
            _require(_enum_member(value, Q1A2_BASIS_CODES), "contract_basis_invalid")
            basis[axis] = value
        axes = {
            axis: _load_axis(index, axis, axes_raw[axis], basis[axis], projection) for axis in AXES
        }
        cases[case_id] = ContractCaseView(
            case_id=case_id,
            case_index=index,
            scenario_id=scenario_id,
            axes=_freeze(axes),
            basis=_freeze(basis),
        )

    return ContractV2View(
        schema_version=CONTRACT_SCHEMA_VERSION_V2,
        bindings=bindings,
        runs=runs,
        cases=_freeze(cases),
        case_count=case_count,
        projection=projection,
    )


# --------------------------------------------------------------------------- #
# 快照 v0.3 视图（消费侧严格校验：只校验被消费的块 + 关键不变量）
# --------------------------------------------------------------------------- #

_FIELD_TABLE = identity_field_table()
_SNAPSHOT_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    row["path"]
    for row in _FIELD_TABLE
    if "." not in row["path"] and "[]" not in row["path"]
)


def _child_keys(prefix: str) -> frozenset[str]:
    marker = prefix + "."
    keys: set[str] = set()
    for row in _FIELD_TABLE:
        path = row["path"]
        if not path.startswith(marker):
            continue
        rest = path[len(marker) :]
        if rest and "." not in rest and "[]" not in rest:
            keys.add(rest)
    return frozenset(keys)


def _require_keys(value: Any, expected: frozenset[str], object_path: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), _code_with_path("snapshot_field_invalid", object_path))
    prefix = object_path + "." if object_path else ""
    for key in value:
        if key not in expected:
            raise AdapterError(_code_with_path("snapshot_unknown_field", prefix + str(key)))
    for key in expected:
        if key not in value:
            raise AdapterError(_code_with_path("snapshot_field_missing", prefix + str(key)))
    return value


def _field(value: Any, path: str, *, nullable: bool = False) -> Any:
    if value is None:
        _require(nullable, _code_with_path("snapshot_field_invalid", path))
        return None
    return value


def _str_field(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if value is None:
        _require(nullable, _code_with_path("snapshot_field_invalid", path))
        return None
    _require(isinstance(value, str), _code_with_path("snapshot_field_invalid", path))
    return value


def _int_field(value: Any, path: str, *, nullable: bool = False) -> int | None:
    if value is None:
        _require(nullable, _code_with_path("snapshot_field_invalid", path))
        return None
    _require(type(value) is int, _code_with_path("snapshot_field_invalid", path))
    return value


def _bool_field(value: Any, path: str) -> bool:
    _require(type(value) is bool, _code_with_path("snapshot_field_invalid", path))
    return value


@dataclass(frozen=True)
class SnapshotRecordView:
    source_ref: str
    layers: tuple[str, ...]
    locator_kind: str
    doc_code: str | None
    base_doc_code: str | None
    sheet: str | None
    row: int | None
    record_key: str | None
    record_code: str | None
    business_version: str | None
    version_number: int | None
    record_level: bool
    entity_type: str | None
    entity_key: str | None
    entity_filters: Mapping[str, Any]
    entity_matchable: bool
    code: str
    entity_code: str


@dataclass(frozen=True)
class DocumentVersionView:
    source_ref: str
    doc_code: str | None
    version_label: str | None
    runtime_version_number: int | None
    product_version_number: int | None
    code: str


@dataclass(frozen=True)
class TemporalView:
    availability: str
    as_of: str | None
    as_of_source: str
    document_versions: tuple[DocumentVersionView, ...]
    code: str
    baseline_used_as_effective: bool


@dataclass(frozen=True)
class EmptyUseView:
    turn_status: str
    all_use_layers_observed: bool
    empty_set_candidate: bool
    code: str
    use_layers: Mapping[str, Mapping[str, Any]]
    candidate_layers: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class SnapshotView:
    schema_version: str
    contract_version: str
    fixture_kind: str
    source_completeness: str
    binding: Mapping[str, Any]
    turn_ref: Mapping[str, Any]
    records: tuple[SnapshotRecordView, ...]
    summary: Mapping[str, Any]
    temporal: TemporalView
    empty_use: EmptyUseView


def _load_record(index: int, row: Any) -> SnapshotRecordView:
    path = f"record_identities[{index}]"
    expected = _child_keys("record_identities[]")
    _require_keys(row, expected, path)

    def at(name: str) -> str:
        return f"{path}.{name}"

    source_ref = _str_field(row["source_ref"], at("source_ref"))
    layers = row["layers"]
    _require(isinstance(layers, list) and all(_is_str(item) and item in USE_LAYER_NAMES for item in layers), _code_with_path("snapshot_field_invalid", at("layers")))
    locator_kind = row["locator_kind"]
    _require(locator_kind in LOCATOR_KINDS, _code_with_path("snapshot_enum_invalid", at("locator_kind")))
    doc_code = _str_field(row["doc_code"], at("doc_code"), nullable=True)
    base_doc_code = _str_field(row["base_doc_code"], at("base_doc_code"), nullable=True)
    sheet = _str_field(row["sheet"], at("sheet"), nullable=True)
    row_number = _int_field(row["row"], at("row"), nullable=True)
    record_key = _str_field(row["record_key"], at("record_key"), nullable=True)
    record_code = _str_field(row["record_code"], at("record_code"), nullable=True)
    business_version = _str_field(row["business_version"], at("business_version"), nullable=True)
    version_number = _int_field(row["version_number"], at("version_number"), nullable=True)
    record_level = _bool_field(row["record_level"], at("record_level"))
    entity_type = _str_field(row["entity_type"], at("entity_type"), nullable=True)
    entity_key = _str_field(row["entity_key"], at("entity_key"), nullable=True)
    entity_filters = row["entity_filters"]
    _require(
        isinstance(entity_filters, Mapping)
        and all(_is_str(key) and isinstance(value, str) for key, value in entity_filters.items()),
        _code_with_path("snapshot_field_invalid", at("entity_filters")),
    )
    entity_matchable = _bool_field(row["entity_matchable"], at("entity_matchable"))
    code = row["code"]
    _require(code in RECORD_IDENTITY_CODES, _code_with_path("snapshot_enum_invalid", at("code")))
    entity_code = row["entity_code"]
    _require(entity_code in ENTITY_CODES, _code_with_path("snapshot_enum_invalid", at("entity_code")))

    # 消费侧交叉不变量（与 P3 同语义；只针对被消费字段）。
    if record_level:
        _require(
            locator_kind == "record"
            and code == "record_row_reverse_lookup"
            and all(
                value is not None
                for value in (doc_code, base_doc_code, sheet, row_number, record_key, record_code)
            ),
            _code_with_path("snapshot_field_invalid", at("record_level")),
        )
    else:
        _require(
            record_code is None and record_key is None,
            _code_with_path("snapshot_field_invalid", at("record_code")),
        )
        _require(code != "record_row_reverse_lookup", _code_with_path("snapshot_field_invalid", at("code")))
    # 注意：``entity_matchable`` / ``entity_code`` 是 P3 的派生布尔，消费侧**不作为判定依据**
    # （P3 验收实测 entity_document_level 覆盖不足）。这里只做类型/枚举校验，不强制二者一致。
    _require(type(entity_matchable) is bool, _code_with_path("snapshot_field_invalid", at("entity_matchable")))

    return SnapshotRecordView(
        source_ref=str(source_ref),
        layers=tuple(layers),
        locator_kind=str(locator_kind),
        doc_code=doc_code,
        base_doc_code=base_doc_code,
        sheet=sheet,
        row=row_number,
        record_key=record_key,
        record_code=record_code,
        business_version=business_version,
        version_number=version_number,
        record_level=record_level,
        entity_type=entity_type,
        entity_key=entity_key,
        entity_filters=_freeze(entity_filters),
        entity_matchable=entity_matchable,
        code=str(code),
        entity_code=str(entity_code),
    )


def _load_summary(raw: Any, records: Sequence[SnapshotRecordView]) -> Mapping[str, Any]:
    expected = _child_keys("record_identity_summary")
    _require_keys(raw, expected, "record_identity_summary")
    computed = {
        "total": len(records),
        "record_level": sum(1 for row in records if row.record_level is True),
        "not_record_level": sum(1 for row in records if row.record_level is not True),
        "doc_code_unresolved": sum(1 for row in records if row.code == "runtime_doc_code_unresolved"),
        "entity_matchable": sum(1 for row in records if row.entity_matchable is True),
        "entity_document_level": sum(1 for row in records if row.entity_type == "document"),
        "unresolved_units": sum(1 for row in records if row.code == "runtime_unit_unresolved"),
        "doc_codes": sorted({row.base_doc_code for row in records if row.base_doc_code is not None}),
    }
    for name, value in computed.items():
        if name == "doc_codes":
            _require(
                raw[name] == value,
                "snapshot_summary_mismatch",
            )
            continue
        _require(
            _int_field(raw[name], f"record_identity_summary.{name}") == value,
            "snapshot_summary_mismatch",
        )
    return MappingProxyType(dict(raw))


def _load_temporal(raw: Any) -> TemporalView:
    expected = _child_keys("effective_temporal")
    _require_keys(raw, expected, "effective_temporal")
    availability = raw["availability"]
    _require(
        _enum_member(availability, {"observed", "partial", "not_observed"}),
        "snapshot_enum_invalid",
    )
    as_of = _field(raw["as_of"], "effective_temporal.as_of", nullable=True)
    _require(as_of is None or _is_iso_date(as_of), "snapshot_field_invalid")
    as_of_source = raw["as_of_source"]
    _require(
        _enum_member(as_of_source, {"plan_observed", "rag_business_date", "unavailable"}),
        "snapshot_enum_invalid",
    )
    observed_from = raw["observed_from"]
    _require(
        _enum_member(observed_from, {"db_projection_units", "unavailable"}),
        "snapshot_enum_invalid",
    )
    _bool_field(raw["baseline_used_as_effective"], "effective_temporal.baseline_used_as_effective")
    _require(
        raw["baseline_used_as_effective"] is False,
        "snapshot_field_invalid:effective_temporal.baseline_used_as_effective",
    )
    code = raw["code"]
    _require(
        _enum_member(
            code,
            {
                "effective_temporal_observed",
                "effective_temporal_partial",
                "effective_temporal_not_observed",
                "effective_as_of_not_observed",
                "effective_as_of_ambiguous",
            },
        ),
        "snapshot_enum_invalid",
    )
    if availability == "observed":
        _require(as_of is not None and code == "effective_temporal_observed", "snapshot_field_invalid:effective_temporal.as_of")
    elif availability == "not_observed":
        _require(as_of is None and as_of_source == "unavailable", "snapshot_field_invalid:effective_temporal.as_of")

    versions_raw = raw["document_versions"]
    _require(isinstance(versions_raw, list), "snapshot_field_invalid:effective_temporal.document_versions")
    versions: list[DocumentVersionView] = []
    for index, row in enumerate(versions_raw):
        path = f"effective_temporal.document_versions[{index}]"
        _require_keys(row, _child_keys("effective_temporal.document_versions[]"), path)
        source_ref = _str_field(row["source_ref"], path + ".source_ref")
        doc_code = _str_field(row["doc_code"], path + ".doc_code", nullable=True)
        label = _str_field(row["version_label"], path + ".version_label", nullable=True)
        runtime = _int_field(row["runtime_version_number"], path + ".runtime_version_number", nullable=True)
        product = _int_field(row["product_version_number"], path + ".product_version_number", nullable=True)
        version_code = row["code"]
        _require(
            _enum_member(
                version_code, {"version_observed", "version_mismatch", "version_unresolved"}
            ),
            "snapshot_enum_invalid:" + path + ".code",
        )
        if version_code == "version_observed":
            _require(runtime is not None, "snapshot_field_invalid:" + path + ".runtime_version_number")
        elif version_code == "version_mismatch":
            _require(
                runtime is not None and product is not None and runtime != product,
                "snapshot_field_invalid:" + path + ".code",
            )
        else:
            _require(runtime is None, "snapshot_field_invalid:" + path + ".code")
        versions.append(
            DocumentVersionView(
                source_ref=str(source_ref),
                doc_code=doc_code,
                version_label=label,
                runtime_version_number=runtime,
                product_version_number=product,
                code=str(version_code),
            )
        )
    return TemporalView(
        availability=availability,
        as_of=as_of,
        as_of_source=as_of_source,
        document_versions=tuple(versions),
        code=str(code),
        baseline_used_as_effective=False,
    )


def _load_empty_use(raw: Any) -> EmptyUseView:
    expected = _child_keys("empty_use_scope_input")
    _require_keys(raw, expected, "empty_use_scope_input")
    plan = _require_keys(raw["plan"], _child_keys("empty_use_scope_input.plan"), "empty_use_scope_input.plan")
    _bool_field(plan["availability"], "empty_use_scope_input.plan.availability")
    for name in ("path", "mode", "as_of", "include_future", "clarification"):
        _field(plan[name], f"empty_use_scope_input.plan.{name}", nullable=True)
    use_raw = _require_keys(
        raw["use_layers"], frozenset(USE_LAYER_NAMES), "empty_use_scope_input.use_layers"
    )
    use_layers: dict[str, Mapping[str, Any]] = {}
    observed_flags: list[bool] = []
    total = 0
    for name in USE_LAYER_NAMES:
        layer = _require_keys(
            use_raw[name],
            _child_keys("empty_use_scope_input.use_layers.model_evidence"),
            f"empty_use_scope_input.use_layers.{name}",
        )
        observed = _bool_field(layer["observed"], f"empty_use_scope_input.use_layers.{name}.observed")
        count = _int_field(layer["count"], f"empty_use_scope_input.use_layers.{name}.count")
        _require(count is not None and count >= 0, f"snapshot_field_invalid:empty_use_scope_input.use_layers.{name}.count")
        refs = layer["refs"]
        _require(
            isinstance(refs, list) and all(_is_str(item) for item in refs),
            f"snapshot_field_invalid:empty_use_scope_input.use_layers.{name}.refs",
        )
        if name == "direct_rag_fact_count":
            _require(not refs, f"snapshot_field_invalid:empty_use_scope_input.use_layers.{name}.refs")
        else:
            _require(count == len(refs), f"snapshot_field_invalid:empty_use_scope_input.use_layers.{name}.count")
        _require(
            observed or count == 0,
            f"snapshot_field_invalid:empty_use_scope_input.use_layers.{name}.count",
        )
        observed_flags.append(observed)
        total += count
        use_layers[name] = MappingProxyType(
            {"observed": observed, "count": count, "refs": tuple(refs)}
        )
    candidate_raw = _require_keys(
        raw["candidate_layers"],
        frozenset(CANDIDATE_LAYER_NAMES),
        "empty_use_scope_input.candidate_layers",
    )
    candidate_layers: dict[str, Mapping[str, Any]] = {}
    for name in CANDIDATE_LAYER_NAMES:
        path = f"empty_use_scope_input.candidate_layers.{name}"
        layer = _require_keys(candidate_raw[name], _child_keys("empty_use_scope_input.candidate_layers.retrieval_observed"), path)
        observed = _bool_field(layer["observed"], path + ".observed")
        count = _int_field(layer["count"], path + ".count")
        _require(count is not None and count >= 0, f"snapshot_field_invalid:{path}.count")
        refs = layer["refs"]
        _require(
            isinstance(refs, list) and all(_is_str(item) for item in refs),
            f"snapshot_field_invalid:{path}.refs",
        )
        truncated = _bool_field(layer["truncated"], path + ".truncated")
        _require(count == len(refs), f"snapshot_field_invalid:{path}.count")
        candidate_layers[name] = MappingProxyType(
            {"observed": observed, "count": count, "refs": tuple(refs), "truncated": truncated}
        )

    all_observed = _bool_field(raw["all_use_layers_observed"], "empty_use_scope_input.all_use_layers_observed")
    _require(
        all_observed is all(observed_flags),
        "snapshot_field_invalid:empty_use_scope_input.all_use_layers_observed",
    )
    empty_candidate = _bool_field(raw["empty_set_candidate"], "empty_use_scope_input.empty_set_candidate")
    code = raw["code"]
    _require(
        _enum_member(
            code,
            {
                "empty_use_input_complete_empty",
                "empty_use_input_nonempty",
                "empty_use_input_layers_not_observed",
                "empty_use_input_turn_partial",
                "empty_use_input_malformed_event",
            },
        ),
        "snapshot_enum_invalid",
    )
    turn_status = raw["turn_status"]
    _require(
        _enum_member(turn_status, {"complete", "partial", "unavailable"}),
        "snapshot_enum_invalid",
    )
    if code != "empty_use_input_malformed_event":
        _require(
            empty_candidate is (all_observed and total == 0),
            "snapshot_field_invalid:empty_use_scope_input.empty_set_candidate",
        )
        if turn_status in {"partial", "unavailable"}:
            _require(code == "empty_use_input_turn_partial", "snapshot_field_invalid:empty_use_scope_input.code")
        elif empty_candidate:
            _require(code == "empty_use_input_complete_empty", "snapshot_field_invalid:empty_use_scope_input.code")
        elif total > 0:
            _require(code == "empty_use_input_nonempty", "snapshot_field_invalid:empty_use_scope_input.code")
        else:
            _require(
                code == "empty_use_input_layers_not_observed",
                "snapshot_field_invalid:empty_use_scope_input.code",
            )
    else:
        _require(empty_candidate is False, "snapshot_field_invalid:empty_use_scope_input.empty_set_candidate")

    return EmptyUseView(
        turn_status=turn_status,
        all_use_layers_observed=all_observed,
        empty_set_candidate=empty_candidate,
        code=str(code),
        use_layers=_freeze(use_layers),
        candidate_layers=_freeze(candidate_layers),
    )


def load_snapshot_v03(
    payload: Any,
    *,
    expected_run_id: str | None = None,
    expected_scenario_id: str | None = None,
    expected_turn: Mapping[str, Any] | None = None,
) -> SnapshotView:
    """消费侧加载 P3 身份快照（``p2-runtime-identity-snapshot/v0.1``）。

    快照应已由 P3 ``read_snapshot_evidence`` 严格校验；这里再次校验**被消费**字段的
    键集/类型/枚举与关键不变量，并对版本、fixture 绑定、跨 run、跨回合 fail-closed。
    """
    _require(isinstance(payload, Mapping), "snapshot_envelope_invalid")
    _require_keys(payload, _SNAPSHOT_TOP_LEVEL_KEYS, "")

    _require(
        payload["contract_version"] == SNAPSHOT_CONTRACT_VERSION,
        "snapshot_contract_version_invalid",
    )
    _require(payload["schema_version"] == SNAPSHOT_SCHEMA_VERSION, "snapshot_schema_version_invalid")
    fixture_kind = payload["fixture_kind"]
    _require(fixture_kind in FIXTURE_KINDS, "snapshot_fixture_kind_invalid")
    _require(isinstance(payload["captured_utc"], str), "snapshot_field_invalid:captured_utc")
    _require(_is_sha256(payload["content_sha256"]), "snapshot_field_invalid:content_sha256")
    public_boundary = _require_keys(
        payload["public_boundary"], _child_keys("public_boundary"), "public_boundary"
    )
    _require(
        public_boundary["runtime_ids_only_in_declared_blocks"] is True,
        "snapshot_field_invalid:public_boundary.runtime_ids_only_in_declared_blocks",
    )

    source = _require_keys(payload["source_evidence"], _child_keys("source_evidence"), "source_evidence")
    _require(_is_sha256(source["sha256"]), "snapshot_field_invalid:source_evidence.sha256")
    _require(source["fixture_kind"] in FIXTURE_KINDS, "snapshot_enum_invalid")
    completeness = source["completeness_status"]
    _require(
        _enum_member(completeness, {"complete", "incomplete", "replayed"}),
        "snapshot_enum_invalid",
    )
    _require(source["fixture_kind"] == fixture_kind, "snapshot_fixture_binding_mismatch")

    binding = _require_keys(payload["binding"], _child_keys("binding"), "binding")
    binding_fixture = binding["fixture_kind"]
    _require(binding_fixture in FIXTURE_KINDS, "snapshot_enum_invalid")
    _require(binding_fixture == fixture_kind, "snapshot_fixture_binding_mismatch")
    run_id = _str_field(binding["run_id"], "binding.run_id")
    scenario_id = _str_field(binding["scenario_id"], "binding.scenario_id")
    _require(_is_sha256(binding["bindings_sha256"]), "snapshot_field_invalid:binding.bindings_sha256")
    _require(
        binding["run_binding_sha256"] is None or _is_sha256(binding["run_binding_sha256"]),
        "snapshot_field_invalid:binding.run_binding_sha256",
    )
    if expected_run_id is not None:
        _require(run_id == expected_run_id, "snapshot_run_binding_mismatch")
    if expected_scenario_id is not None:
        _require(scenario_id == expected_scenario_id, "snapshot_scenario_binding_mismatch")

    turn_ref = _require_keys(payload["turn_ref"], _child_keys("turn_ref"), "turn_ref")
    turn_index = _int_field(turn_ref["turn_index"], "turn_ref.turn_index")
    _str_field(turn_ref["client_request_id"], "turn_ref.client_request_id")
    _require(_is_sha256(turn_ref["question_sha256"]), "snapshot_field_invalid:turn_ref.question_sha256")
    if expected_turn is not None:
        _require(isinstance(expected_turn, Mapping), "snapshot_turn_binding_mismatch")
        _require(
            any(name in expected_turn for name in ("turn_index", "client_request_id")),
            "snapshot_turn_binding_mismatch",
        )
        if "turn_index" in expected_turn:
            _require(
                expected_turn["turn_index"] == turn_index,
                "snapshot_turn_binding_mismatch",
            )
        if "client_request_id" in expected_turn:
            _require(
                expected_turn["client_request_id"] == turn_ref["client_request_id"],
                "snapshot_turn_binding_mismatch",
            )

    records_raw = payload["record_identities"]
    _require(isinstance(records_raw, list), "snapshot_field_invalid:record_identities")
    records = tuple(_load_record(index, row) for index, row in enumerate(records_raw))
    summary = _load_summary(payload["record_identity_summary"], records)
    temporal = _load_temporal(payload["effective_temporal"])
    empty_use = _load_empty_use(payload["empty_use_scope_input"])
    _require(isinstance(payload["request_owner"], Mapping), "snapshot_field_invalid:request_owner")
    _require(isinstance(payload["runtime_identity"], Mapping), "snapshot_field_invalid:runtime_identity")

    return SnapshotView(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        contract_version=SNAPSHOT_CONTRACT_VERSION,
        fixture_kind=fixture_kind,
        source_completeness=completeness,
        binding=MappingProxyType(dict(binding)),
        turn_ref=MappingProxyType(dict(turn_ref)),
        records=records,
        summary=summary,
        temporal=temporal,
        empty_use=empty_use,
    )


# --------------------------------------------------------------------------- #
# 判定结果
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AxisDetermination:
    axis: str
    case_id: str
    state: str
    reason: str
    provenance: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(self.axis in ADAPTED_AXES, "axis_not_adapted")
        _require(self.state in AXIS_STATES, "adapter_invariant_violation")
        _require(_is_str(self.reason), "adapter_invariant_violation")
        _require(isinstance(self.evidence, tuple) and isinstance(self.missing, tuple), "adapter_invariant_violation")

    def as_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "case_id": self.case_id,
            "state": self.state,
            "reason": self.reason,
            "provenance": dict(self.provenance),
            "evidence": list(self.evidence),
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class CaseDetermination:
    case_id: str
    scenario_id: str | None
    axes: Mapping[str, AxisDetermination]
    contract_schema_version: str | None = None
    snapshot_schema_version: str | None = None
    delegated_axes: tuple[str, ...] = DELEGATED_AXES

    def __post_init__(self) -> None:
        _require(_is_str(self.case_id), "adapter_invariant_violation")
        _require(set(self.axes) == set(ADAPTED_AXES), "axis_not_adapted")

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scenario_id": self.scenario_id,
            "delegated_axes": list(self.delegated_axes),
            "contract_schema_version": self.contract_schema_version,
            "snapshot_schema_version": self.snapshot_schema_version,
            "axes": {axis: self.axes[axis].as_dict() for axis in ADAPTED_AXES},
        }


def validate_determination(
    determination: AxisDetermination,
    *,
    applicability: str | None = None,
    criterion: str | None = None,
) -> AxisDetermination:
    """状态/固定码一致性门：禁止 unknown→N/A，禁止把 unknown 码当 pass。"""
    _require(determination.axis in ADAPTED_AXES, "axis_not_adapted")
    if determination.state == "not_applicable":
        allowed = (
            determination.axis == "cross_entity"
            and applicability == "not_applicable"
            and criterion == "no_entity_claim"
            and determination.reason == NOT_APPLICABLE_CODE
        )
        _require(allowed, "unknown_to_not_applicable_forbidden")
        return determination
    if determination.state == "passed":
        _require(determination.reason in PASS_CODES, "adapter_invariant_violation")
        return determination
    if determination.state == "violation":
        _require(determination.reason in VIOLATION_CODES, "adapter_invariant_violation")
        return determination
    _require(_is_unknown_reason(determination.reason), "adapter_invariant_violation")
    return determination


# --------------------------------------------------------------------------- #
# 判定：cross_entity
# --------------------------------------------------------------------------- #


def _record_identity_code_counts(records: Sequence[SnapshotRecordView]) -> dict[str, int]:
    return dict(sorted(Counter(record.code for record in records).items()))


def _provenance(
    *,
    contract: ContractV2View,
    case: ContractCaseView,
    axis: ContractAxisView,
    snapshot: SnapshotView,
    audit: Sequence[str],
    extra: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    payload: dict[str, Any] = {
        "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
        "basis": axis.basis,
        "source": "frozen_contract",
        "contract_schema_version": contract.schema_version,
        "snapshot_schema_version": snapshot.schema_version,
        "fixture_kind": snapshot.fixture_kind,
        "case_index": case.case_index,
        "axis_criterion": axis.criterion,
        "axis_applicability": axis.applicability,
        "target_count": len(axis.targets),
        "matchable_target_count": sum(1 for target in axis.targets if target.matchable),
        "target_granularities": sorted({target.granularity for target in axis.targets}),
        "target_codes": sorted({target.code for target in axis.targets}),
        "target_provenance": [dict(row) for row in axis.target_provenance],
        "record_identity_codes": _record_identity_code_counts(snapshot.records),
        "record_key_spaces": _record_key_space_counts(snapshot.records),
        "key_space_rule": "canonical_role_filters_v2",
        "empty_use_proof_source": "adapter_derived_use_layers_and_retrieval_marker",
        "empty_use_code": snapshot.empty_use.code,
        "temporal_code": snapshot.temporal.code,
        "audit": list(audit),
    }
    if extra:
        payload.update(dict(extra))
    return _freeze(payload)


def _empty_use_proof(empty_use: EmptyUseView) -> tuple[bool, tuple[str, ...]]:
    """空使用集证明：**不采信** P3 的 ``empty_set_candidate`` / ``all_use_layers_observed``。

    M-C1P2-01：只有逐层读出的 9 个使用层全部 ``observed=true`` 且计数为 0，并且
    ``retrieval_observed`` 自身 ``observed=true`` 且携带空 ``refs``（即空 unit_ids）、
    未截断，才算是空集证明；``not_observed`` + ``candidates=[]`` 是 class C，一律不 proven。
    """
    audit: list[str] = []
    if empty_use.turn_status != "complete":
        return False, ("turn_status_not_complete",)
    layers = empty_use.use_layers
    if any(layer["observed"] is not True for layer in layers.values()):
        return False, ("use_layer_not_observed",)
    if any(layer["count"] != 0 for layer in layers.values()):
        return False, ("use_layer_nonzero",)
    retrieval = empty_use.candidate_layers["retrieval_observed"]
    if retrieval["observed"] is not True:
        return False, ("class_c_retrieval_not_observed",)
    if retrieval["truncated"] is not False:
        return False, ("retrieval_candidates_truncated",)
    if retrieval["count"] != 0 or retrieval["refs"]:
        return False, ("retrieval_candidates_nonempty",)
    audit.append("retrieval_observed_empty_unit_ids")
    return True, tuple(audit)


#: 运行期 id 型键（`item|id:p01`）与名称型 canonical 键的**唯一**合法对齐方式：
#: 用两侧同样的角色值 + 公开 normalization 复算 canonical key，逐值相等才算同一实体。
_ID_TYPE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\|id:", re.IGNORECASE)
_UUID_ANY_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_LONG_HEX_ANY_RE = re.compile(r"[0-9a-fA-F]{16,}")


def _canonical_entity_key(entity_type: str, filters: Mapping[str, Any]) -> str | None:
    """按合同 v2 §4.3 R-ENT-1 / R-ENT-2 复算“名称型 canonical key”。

    归一化只调用合同 v2 §1.7 允许的公开规则源
    ``mktkb.rag.chunking.normalize_field``（= ``tokenize.normalize`` + strip），
    不引入任何模糊/前缀/包含匹配；缺角色值即返回 ``None``（不可对齐）。
    """

    def norm(value: Any) -> str:
        return normalize_field(value)

    if entity_type == "item":
        store = filters.get("store")
        item = filters.get("item")
        if not _is_str(store) or not _is_str(item):
            return None
        return f"item|{norm(store)}|{norm(item)}"
    if entity_type == "store":
        store = filters.get("store")
        if not _is_str(store):
            return None
        return f"store|{norm(store)}"
    if entity_type == "record":
        identifier = filters.get("identifier")
        if not _is_str(identifier):
            return None
        return f"record|{norm(identifier)}"
    if entity_type == "product":
        product = filters.get("product")
        if not _is_str(product):
            return None
        return (
            f"product|{norm(product)}|{norm(filters.get('channel'))}"
            f"|{norm(filters.get('price_type'))}"
        )
    return None


def _key_carries_runtime_identity(entity_key: str) -> bool:
    """实体键携带 doc/unit uuid（或长 hex / `document|…`）即视为文档粒度，不做实体匹配。"""
    return (
        entity_key.startswith("document|")
        or _UUID_ANY_RE.search(entity_key) is not None
        or _LONG_HEX_ANY_RE.search(entity_key) is not None
    )


def _runtime_key_space(record: SnapshotRecordView) -> str:
    if not record.entity_type or not record.entity_key:
        return "absent"
    if record.entity_type == "document" or _key_carries_runtime_identity(record.entity_key):
        return "document"
    canonical = _canonical_entity_key(record.entity_type, record.entity_filters)
    if canonical is not None and canonical == record.entity_key:
        return "corpus_name"
    if _ID_TYPE_KEY_RE.match(record.entity_key) is not None:
        return "id_key"
    return "opaque"


def _target_key_space(target: TargetView) -> str:
    if target.entity_type == "document":
        return "doc_code" if target.granularity == "doc_code" else "document"
    if _key_carries_runtime_identity(target.entity_key):
        return "runtime_id"
    canonical = _canonical_entity_key(target.entity_type, target.filters)
    if canonical is not None and canonical == target.entity_key:
        return "corpus_name"
    if _ID_TYPE_KEY_RE.match(target.entity_key) is not None:
        return "id_key"
    return "opaque"


def _filters_subset(target: TargetView, record: SnapshotRecordView) -> bool:
    return all(
        record.entity_filters.get(str(key)) == value for key, value in target.filters.items()
    )


def _record_key_consistent_with_filters(record: SnapshotRecordView) -> bool:
    """运行期 ``entity_key`` 是否与 ``entity_filters`` 自洽（``IR-03``）。

    允许的形态只有三种：由同一组角色值复算出的 canonical 名称型键、``<type>|id:…``
    型键、以及 ``document|…``/携带 uuid 的运行期身份键（后者在调用前已被粒度分支
    截走）。**不**在此处做模糊/前缀匹配：三种形态之外一律不可对齐。

    背景：规则②（角色值复算 canonical key）原先只看 ``entity_filters``，不看
    ``entity_key`` 是否指向同一实体，于是“键指向 B、filters 指向 A”的自相矛盾行
    会被救成 pass（假通过）。这里按 IR-03 的建议在规则②入口加自洽闸门。
    """
    entity_key = record.entity_key
    if not _is_str(entity_key):
        return False
    canonical = _canonical_entity_key(record.entity_type, record.entity_filters)
    if canonical is not None and canonical == entity_key:
        return True
    if _ID_TYPE_KEY_RE.match(entity_key) is not None:
        return True
    return _key_carries_runtime_identity(entity_key)


def _match_entity_row(
    record: SnapshotRecordView, matchable_targets: Sequence[TargetView]
) -> tuple[str, str]:
    """返回 ``(kind, code)``：``matched`` / ``mismatch`` / ``incompatible``。

    只有“两侧同一键空间（均可由角色值复算为 canonical 名称型键）且逐值失配”才返回
    ``mismatch``（violation 候选）；键空间不可对齐一律 ``incompatible``（unknown），
    严禁用前缀/包含/模糊关系硬凑匹配。

    顺序（``IR-02``）：同键目标**全部**检查，任一条 filters 满足即 matched；只有
    同键目标全部 filters 矛盾才落 ``identity_unresolved``。不再在第一条同键目标处
    提前返回，消除“严目标在前就永远到不了松目标”的顺序依赖（合同 v2 §3.4(3)
    “任一条匹配即匹配”）。
    """
    same_type = [
        target for target in matchable_targets if target.entity_type == record.entity_type
    ]
    same_key = [target for target in same_type if target.entity_key == record.entity_key]
    for target in same_key:
        if _filters_subset(target, record):
            return "matched", "target_matched"
    if same_key:
        # 同键但角色值矛盾（且没有任何一条同键目标满足）：保留 unknown，不判 violation。
        return "incompatible", "identity_unresolved"
    if not _record_key_consistent_with_filters(record):
        # IR-03：键与角色值互相矛盾的行不得由规则②救成 pass。
        return "incompatible", "entity_key_space_incompatible"
    canonical = _canonical_entity_key(record.entity_type, record.entity_filters)
    for target in same_type:
        if _target_key_space(target) != "corpus_name":
            continue
        if not _filters_subset(target, record):
            continue
        if canonical is not None and canonical == target.entity_key:
            return "matched", "key_space_aligned_by_role_filters"
    row_space = _runtime_key_space(record)
    target_spaces = {_target_key_space(target) for target in matchable_targets}
    if row_space == "corpus_name" and target_spaces == {"corpus_name"}:
        return "mismatch", ""
    return "incompatible", "entity_key_space_incompatible"


def _record_key_space_counts(records: Sequence[SnapshotRecordView]) -> dict[str, int]:
    return dict(sorted(Counter(_runtime_key_space(record) for record in records).items()))


def _record_doc_codes(record: SnapshotRecordView) -> set[str]:
    return {
        value for value in (record.doc_code, record.base_doc_code) if isinstance(value, str) and value
    }


def _doc_code_comparable(record: SnapshotRecordView, doc_targets: Sequence[TargetView]) -> bool:
    """只允许“doc_code 级目标 + 逐条记录身份已解析”的比对。"""
    return (
        bool(doc_targets)
        and record.record_level is True
        and record.record_code is not None
        and bool(_record_doc_codes(record))
    )


def _doc_code_in_scope(record: SnapshotRecordView, doc_targets: Sequence[TargetView]) -> bool:
    codes = _record_doc_codes(record)
    return any(target.entity_key in codes for target in doc_targets)


def _determination(
    *,
    axis: str,
    case: ContractCaseView,
    state: str,
    reason: str,
    provenance: Mapping[str, Any],
    audit: Sequence[str],
    applicability: str,
    criterion: str,
) -> AxisDetermination:
    determination = AxisDetermination(
        axis=axis,
        case_id=case.case_id,
        state=state,
        reason=reason,
        provenance=provenance,
        evidence=tuple(audit),
        missing=tuple(
            sorted(
                {
                    item.split(":", 1)[-1]
                    for item in audit
                    if item.split(":", 1)[-1] in SEMANTIC_UNKNOWN_CODES
                }
            )
        ),
    )
    return validate_determination(determination, applicability=applicability, criterion=criterion)


def determine_cross_entity(
    contract: ContractV2View,
    case: ContractCaseView,
    snapshot: SnapshotView,
) -> AxisDetermination:
    axis = case.axes["cross_entity"]
    audit: list[str] = []
    base = {
        "contract": contract,
        "case": case,
        "axis": axis,
        "snapshot": snapshot,
    }

    if axis.applicability == "unknown" or axis.criterion == "unknown":
        audit.append("annotation_unknown")
        return _determination(
            axis="cross_entity",
            case=case,
            state="unknown",
            reason="annotation_unknown",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    if axis.criterion == "shared_background":
        # 合同 v2 §7 R-SB-4：消费侧 shared_background 一律为空；语料单元投影不得当运行期身份。
        audit.append("shared_background_runtime_identity_unavailable")
        return _determination(
            axis="cross_entity",
            case=case,
            state="unknown",
            reason="shared_background_runtime_identity_unavailable",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    if axis.criterion == "no_entity_claim":
        if axis.applicability != "not_applicable":
            audit.append("annotation_unknown")
            return _determination(
                axis="cross_entity",
                case=case,
                state="unknown",
                reason="annotation_unknown",
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )
        if any(record.entity_type is not None or record.entity_key is not None for record in snapshot.records):
            audit.append("entity_scope_conflict")
            return _determination(
                axis="cross_entity",
                case=case,
                state="unknown",
                reason="entity_scope_conflict",
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )
        if snapshot.records:
            return _determination(
                axis="cross_entity",
                case=case,
                state="not_applicable",
                reason=NOT_APPLICABLE_CODE,
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )
        proven, proof_audit = _empty_use_proof(snapshot.empty_use)
        audit.extend(proof_audit)
        if not proven:
            audit.append("empty_set_not_proven")
            return _determination(
                axis="cross_entity",
                case=case,
                state="unknown",
                reason="empty_set_not_proven",
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )
        return _determination(
            axis="cross_entity",
            case=case,
            state="not_applicable",
            reason=NOT_APPLICABLE_CODE,
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    if axis.criterion not in ("structured_target", "multi_target"):
        audit.append("annotation_unknown")
        return _determination(
            axis="cross_entity",
            case=case,
            state="unknown",
            reason="annotation_unknown",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    if not axis.targets:
        audit.append("targets_missing")
        return _determination(
            axis="cross_entity",
            case=case,
            state="unknown",
            reason="targets_missing",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    known_doc_codes: set[str] = set()
    for record in snapshot.records:
        known_doc_codes |= _record_doc_codes(record)
    doc_targets = tuple(
        target
        for target in axis.targets
        if target.granularity == "doc_code" and target.entity_key in known_doc_codes
    )
    matchable_targets = tuple(target for target in axis.targets if target.matchable)

    if not matchable_targets and not doc_targets:
        if any(target.granularity == "document" for target in axis.targets):
            # M-C1P1-01：document 级目标 + unit 级使用 → 只 unknown，绝不 violation。
            audit.append("target_granularity_incomparable")
            return _determination(
                axis="cross_entity",
                case=case,
                state="unknown",
                reason="target_granularity_incomparable",
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )
        audit.append("targets_unresolved")
        return _determination(
            axis="cross_entity",
            case=case,
            state="unknown",
            reason="targets_unresolved",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    if axis.criterion == "multi_target":
        distinct = {
            (target.entity_type, target.entity_key) for target in matchable_targets + doc_targets
        }
        if len(distinct) < 2:
            audit.append("multi_target_lt2")
            return _determination(
                axis="cross_entity",
                case=case,
                state="unknown",
                reason="multi_target_lt2",
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )

    if not snapshot.records:
        proven, proof_audit = _empty_use_proof(snapshot.empty_use)
        audit.extend(proof_audit)
        if not proven:
            audit.append("empty_set_not_proven")
            return _determination(
                axis="cross_entity",
                case=case,
                state="unknown",
                reason="empty_set_not_proven",
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )
        audit.append("cross_entity_empty_use_scope_ok")
        return _determination(
            axis="cross_entity",
            case=case,
            state="passed",
            reason="cross_entity_empty_use_scope_ok",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    for index, record in enumerate(snapshot.records):
        label = f"record_identities[{index}]"
        if record.code == "runtime_unit_unresolved":
            audit.append(label + ":identity_unresolved")
            continue
        if not record.entity_type or not record.entity_key:
            audit.append(label + ":identity_unresolved")
            continue
        comparable = _doc_code_comparable(record, doc_targets)
        row_space = _runtime_key_space(record)
        if row_space == "document" or record.entity_type not in MATCHABLE_ENTITY_TYPES:
            # M-C1P1-01：document 粒度 / 非产品实体身份 → 只能 unknown（或 doc_code 级替代）。
            if comparable and _doc_code_in_scope(record, doc_targets):
                audit.append(label + ":doc_code_level_comparison_used")
            else:
                audit.append(label + ":target_granularity_incomparable")
            continue
        kind, match_code = _match_entity_row(record, matchable_targets)
        if kind == "matched":
            audit.append(label + ":" + match_code)
            continue
        if comparable and _doc_code_in_scope(record, doc_targets):
            audit.append(label + ":doc_code_level_comparison_used")
            continue
        if comparable:
            audit.append(label + ":doc_code_level_mismatch")
            audit.append(label + ":other_entity_used")
            continue
        if kind == "mismatch":
            violation = (
                "other_entity_used"
                if ("model_evidence" in record.layers or "direct_rag_fact" in record.layers)
                else "citation_entity_mismatch"
            )
            audit.append(label + ":" + violation)
            continue
        audit.append(label + ":" + match_code)

    violations = [item for item in audit if item.split(":", 1)[-1] in VIOLATION_CODES]
    unknowns = [item for item in audit if item.split(":", 1)[-1] in SEMANTIC_UNKNOWN_CODES]
    if violations:
        reason = violations[0].split(":", 1)[-1]
        return _determination(
            axis="cross_entity",
            case=case,
            state="violation",
            reason=reason,
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )
    if unknowns:
        reason = unknowns[0].split(":", 1)[-1]
        return _determination(
            axis="cross_entity",
            case=case,
            state="unknown",
            reason=reason,
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )
    audit.append("cross_entity_targets_match_ok")
    return _determination(
        axis="cross_entity",
        case=case,
        state="passed",
        reason="cross_entity_targets_match_ok",
        provenance=_provenance(**base, audit=audit),
        audit=audit,
        applicability=axis.applicability,
        criterion=axis.criterion,
    )


# --------------------------------------------------------------------------- #
# 判定：stale_source
# --------------------------------------------------------------------------- #


def _resolve_ref_record_codes(
    axis: ContractAxisView,
    frozen_refs: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> tuple[set[str], str | None, tuple[str, ...]]:
    if not axis.target_refs:
        return set(), "stale_no_positive_refs", ()
    if frozen_refs is None:
        return set(), "stale_source_unresolved", ("frozen_refs_missing",)
    codes: set[str] = set()
    audit: list[str] = []
    for index, target_ref in enumerate(axis.target_refs):
        collection = target_ref["collection"]
        ref_index = target_ref["index"]
        rows = frozen_refs.get(collection)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or ref_index >= len(rows):
            return set(), "stale_source_unresolved", (f"target_refs[{index}]:unresolved",)
        ref = rows[ref_index]
        if not isinstance(ref, Mapping):
            return set(), "stale_source_unresolved", (f"target_refs[{index}]:unresolved",)
        record_code = ref.get("record_code")
        if not _is_str(record_code):
            return set(), "stale_positive_ref_not_record_level", (f"target_refs[{index}]:not_record_level",)
        codes.add(record_code)
        audit.append(f"target_refs[{index}]:record_identity_resolved")
    if not codes:
        return set(), "stale_source_unresolved", tuple(audit)
    return codes, None, tuple(audit)


def determine_stale_source(
    contract: ContractV2View,
    case: ContractCaseView,
    snapshot: SnapshotView,
    *,
    frozen_refs: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> AxisDetermination:
    axis = case.axes["stale_source"]
    audit: list[str] = []
    base = {
        "contract": contract,
        "case": case,
        "axis": axis,
        "snapshot": snapshot,
    }

    if axis.applicability == "unknown" or axis.criterion == "unknown":
        audit.append("annotation_unknown")
        return _determination(
            axis="stale_source",
            case=case,
            state="unknown",
            reason="annotation_unknown",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )
    if axis.applicability != "required" or axis.criterion != "lifecycle_dates":
        audit.append("annotation_unknown")
        return _determination(
            axis="stale_source",
            case=case,
            state="unknown",
            reason="annotation_unknown",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    codes, code, ref_audit = _resolve_ref_record_codes(axis, frozen_refs)
    audit.extend(ref_audit)
    if code is not None:
        return _determination(
            axis="stale_source",
            case=case,
            state="unknown",
            reason=code,
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    if not snapshot.records:
        proven, proof_audit = _empty_use_proof(snapshot.empty_use)
        audit.extend(proof_audit)
        if not proven:
            audit.append("empty_set_not_proven")
            return _determination(
                axis="stale_source",
                case=case,
                state="unknown",
                reason="empty_set_not_proven",
                provenance=_provenance(**base, audit=audit),
                audit=audit,
                applicability=axis.applicability,
                criterion=axis.criterion,
            )
        return _determination(
            axis="stale_source",
            case=case,
            state="passed",
            reason="stale_source_dates_ok",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    matched = [record for record in snapshot.records if record.record_code in codes]
    if not matched:
        audit.append("stale_source_unresolved")
        return _determination(
            axis="stale_source",
            case=case,
            state="unknown",
            reason="stale_source_unresolved",
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )

    violations: list[str] = []
    unknowns: list[str] = []

    if snapshot.temporal.availability != "observed" or snapshot.temporal.as_of is None:
        unknowns.append("as_of_missing")
        audit.append("as_of_missing")
    elif axis.as_of is not None and axis.as_of != snapshot.temporal.as_of:
        violations.append("date_intent_conflict")
        audit.append("date_intent_conflict")

    versions_by_source = {
        row.source_ref: row for row in snapshot.temporal.document_versions
    }
    seen_codes: set[str] = set()
    for record in matched:
        if record.record_code in seen_codes:
            continue
        seen_codes.add(str(record.record_code))
        version = versions_by_source.get(record.source_ref)
        if version is None:
            unknowns.append("version_unresolved")
            audit.append("version_row_missing")
            continue
        if version.code == "version_mismatch" or (
            version.runtime_version_number is not None
            and version.product_version_number is not None
            and version.runtime_version_number != version.product_version_number
        ):
            unknowns.append("version_mismatch")
            audit.append("version_mismatch")
            continue
        if version.code == "version_unresolved" or version.runtime_version_number is None:
            unknowns.append("version_unresolved")
            audit.append("version_unresolved")
            continue
        audit.append("version_observed")

    # 快照 v0.3 不含逐源 lifecycle（deleted/published/active/生效区间）：
    # 不把“日期/版本一致”扩大成 lifecycle 通过；保留 unknown 并记录该残余。
    unknowns.append("stale_lifecycle_evidence_missing")
    audit.append("stale_lifecycle_evidence_missing")

    if violations:
        return _determination(
            axis="stale_source",
            case=case,
            state="violation",
            reason=violations[0],
            provenance=_provenance(**base, audit=audit),
            audit=audit,
            applicability=axis.applicability,
            criterion=axis.criterion,
        )
    return _determination(
        axis="stale_source",
        case=case,
        state="unknown",
        reason=unknowns[0],
        provenance=_provenance(**base, audit=audit),
        audit=audit,
        applicability=axis.applicability,
        criterion=axis.criterion,
    )


# --------------------------------------------------------------------------- #
# 逐题入口 + 计数
# --------------------------------------------------------------------------- #


def _unknown_case(
    case_id: str,
    scenario_id: str | None,
    code: str,
    *,
    contract_schema_version: str | None = None,
    snapshot_schema_version: str | None = None,
) -> CaseDetermination:
    axes = {
        axis: AxisDetermination(
            axis=axis,
            case_id=case_id,
            state="unknown",
            reason=code,
            provenance=_freeze(
                {
                    "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
                    "basis": None,
                    "source": "unavailable",
                    "contract_schema_version": contract_schema_version,
                    "snapshot_schema_version": snapshot_schema_version,
                }
            ),
        )
        for axis in ADAPTED_AXES
    }
    return CaseDetermination(
        case_id=case_id,
        scenario_id=scenario_id,
        axes=_freeze(axes),
        contract_schema_version=contract_schema_version,
        snapshot_schema_version=snapshot_schema_version,
    )


def determine_case(
    *,
    contract: ContractV2View | Mapping[str, Any] | None,
    case_id: str,
    snapshot: SnapshotView | Mapping[str, Any] | None,
    expected_schema_sha256: str | None = None,
    expected_run_id: str | None = None,
    expected_scenario_id: str | None = None,
    expected_turn: Mapping[str, Any] | None = None,
    frozen_refs: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> CaseDetermination:
    """单题入口：任何缺项/版本不符/身份不可解析 → 固定码 + unknown。"""
    contract_view: ContractV2View | None = None
    if isinstance(contract, ContractV2View):
        contract_view = contract
    else:
        try:
            contract_view = load_contract_v2(contract, expected_schema_sha256=expected_schema_sha256)
        except AdapterError as exc:
            return _unknown_case(case_id, None, exc.code)

    case = contract_view.for_case(case_id)
    if case is None:
        return _unknown_case(
            case_id,
            None,
            "contract_case_missing",
            contract_schema_version=contract_view.schema_version,
        )

    if isinstance(snapshot, SnapshotView):
        snapshot_view = snapshot
    else:
        try:
            snapshot_view = load_snapshot_v03(
                snapshot,
                expected_run_id=expected_run_id,
                expected_scenario_id=expected_scenario_id or case.scenario_id,
                expected_turn=expected_turn,
            )
        except AdapterError as exc:
            return _unknown_case(
                case_id,
                case.scenario_id,
                exc.code,
                contract_schema_version=contract_view.schema_version,
            )

    if snapshot_view.binding["scenario_id"] != case.scenario_id:
        return _unknown_case(
            case_id,
            case.scenario_id,
            "snapshot_scenario_binding_mismatch",
            contract_schema_version=contract_view.schema_version,
            snapshot_schema_version=snapshot_view.schema_version,
        )
    if snapshot_view.source_completeness != "complete":
        code = (
            "snapshot_source_evidence_replayed"
            if snapshot_view.source_completeness == "replayed"
            else "snapshot_source_evidence_incomplete"
        )
        return _unknown_case(
            case_id,
            case.scenario_id,
            code,
            contract_schema_version=contract_view.schema_version,
            snapshot_schema_version=snapshot_view.schema_version,
        )
    run = contract_view.run_for_scenario(case.scenario_id)
    if run is None:
        return _unknown_case(
            case_id,
            case.scenario_id,
            "contract_run_missing",
            contract_schema_version=contract_view.schema_version,
            snapshot_schema_version=snapshot_view.schema_version,
        )
    if snapshot_view.binding["run_id"] != run["run_id"]:
        return _unknown_case(
            case_id,
            case.scenario_id,
            "snapshot_run_binding_mismatch",
            contract_schema_version=contract_view.schema_version,
            snapshot_schema_version=snapshot_view.schema_version,
        )

    axes = {
        "cross_entity": determine_cross_entity(contract_view, case, snapshot_view),
        "stale_source": determine_stale_source(
            contract_view, case, snapshot_view, frozen_refs=frozen_refs
        ),
    }
    return CaseDetermination(
        case_id=case_id,
        scenario_id=case.scenario_id,
        axes=_freeze(axes),
        contract_schema_version=contract_view.schema_version,
        snapshot_schema_version=snapshot_view.schema_version,
    )


def determine_axis(
    axis: str,
    contract: ContractV2View,
    case: ContractCaseView,
    snapshot: SnapshotView,
    *,
    frozen_refs: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> AxisDetermination:
    """按轴分派：``safety`` / ``cross_user`` 明确交回 Q1a-1/Q1a-1b，不在本模块出判定。"""
    if axis in DELEGATED_AXES:
        raise AdapterError("axis_delegated_to_q1a1b")
    if axis == "cross_entity":
        return determine_cross_entity(contract, case, snapshot)
    if axis == "stale_source":
        return determine_stale_source(contract, case, snapshot, frozen_refs=frozen_refs)
    raise AdapterError("axis_not_adapted")


@dataclass(frozen=True)
class AxisCounts:
    axis: str
    planned: int
    checked: int
    passed: int
    not_applicable: int
    unknown: int
    violations: int

    def verify(self) -> "AxisCounts":
        _require(self.axis in ADAPTED_AXES, "axis_not_adapted")
        _require(
            self.planned == self.passed + self.not_applicable + self.unknown + self.violations,
            "axis_counts_inconsistent",
        )
        _require(
            self.checked == self.passed + self.not_applicable + self.violations,
            "axis_counts_inconsistent",
        )
        _require(self.planned == self.checked + self.unknown, "axis_counts_inconsistent")
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "planned": self.planned,
            "checked": self.checked,
            "passed": self.passed,
            "not_applicable": self.not_applicable,
            "unknown": self.unknown,
            "violations": self.violations,
            "formulas": {
                "planned_eq_passed_na_unknown_violations": True,
                "checked_eq_passed_na_violations": True,
                "planned_eq_checked_unknown": True,
            },
        }


def aggregate_axis(
    determinations: Sequence[CaseDetermination],
    axis: str,
) -> AxisCounts:
    """聚合单轴计数并强制三条公式自洽。"""
    _require(axis in ADAPTED_AXES, "axis_not_adapted")
    states = [case.axes[axis].state for case in determinations]
    counts = AxisCounts(
        axis=axis,
        planned=len(states),
        checked=sum(1 for state in states if state != "unknown"),
        passed=states.count("passed"),
        not_applicable=states.count("not_applicable"),
        unknown=states.count("unknown"),
        violations=states.count("violation"),
    )
    return counts.verify()


def reason_histogram(
    determinations: Sequence[CaseDetermination],
    axis: str,
) -> dict[str, int]:
    """单轴 reason 直方图（用于“受影响轴数”统计，不改变任何判定）。"""
    _require(axis in ADAPTED_AXES, "axis_not_adapted")
    return dict(sorted(Counter(case.axes[axis].reason for case in determinations).items()))
