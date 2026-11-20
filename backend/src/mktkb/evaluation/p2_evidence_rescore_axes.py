"""Q1a-1b：P2 硬证据其余三轴重评分器（`cross_user` / `cross_entity` / `stale_source`）。

边界（与 Q1a-1b 任务书一致）：

- **只读输入**：每案只消费显式投影/合成合同 fixture；不读真实 H2 题面/标签/答案/逐题
  输出/私有密文/key/保管会话/`.env`，不调用模型/检索/产品/embedding/rerank/OCR/裁判，
  不发起网络连接、不写旧卡、不覆盖旧对象。
- **复用 Q1a-1 matcher v2**：`doc_code` / `record_code` / 版本 / `unit_key` / `locator`
  的身份匹配直接 import `p2_evidence_rescore.match_ref_to_unit()`；本模块不改该文件，
  也不 import/monkeypatch C 冻结的 `p2_hard_evidence.py`，只对齐其 7 字段轴对象与固定
  reason 词表形状。
- **fail closed**：缺合同、缺字段、身份不完整、来源标记不可信一律 `unknown`；不猜、
  不降级为 N/A/pass。旧 `unknown` 不得被改成 N/A（固定审计码
  `unknown_to_na_blocked`）；旧 `violation` 命中前置证据门时保留旧 verdict。
- **不冒充**：本模块只把 `cross_user` / `cross_entity` / `stale_source` 标为 `rescored`；
  `safety` 仍按旧卡 `recorded_old`（由 Q1a-1 safety 模块负责）。真实 B 包/Q1a-2 合同
  与 Q1a-3 私有重评分不在本模块范围内；输出不产出 `verified` / `threshold_met` /
  `release_ready` / `release` / `T207_pass` 任何结论。

合成 fixture 与真实合同共用同一输入形状；`rescore_axes_run(..., allow_synthetic_fixture=False)`
默认拒绝 `source=synthetic_fixture`，保证合成数据不能静默进入 Q1a-3 真实重评分。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .p2_evidence_rescore import (
    ANALYSIS_ID,
    AXES,
    AXIS_STATES,
    MATCHER_VERSION,
    MatchResult,
    OldCardCase,
    RescoreError,
    RescoreIdentity,
    UnitView,
    VersionBinding,
    canonical_json_bytes,
    file_sha256,
    match_ref_to_unit,
    ref_key,
)

__all__ = [
    "ANALYSIS_ID",
    "ANNOTATION_APPLICABILITIES",
    "ANNOTATION_REASONS",
    "AXES_AUDIT_CODES",
    "AXES_BASES",
    "AXES_SOURCES",
    "AXES_SCOPE_VERSIONS",
    "AXIS_CRITERIA",
    "AXIS_ORDER",
    "AXIS_STATES",
    "BASE_CONTRACT_PATH",
    "BINDING_KEYS",
    "CONTRACT_MODES",
    "DEFAULT_CONTRACT_PATH",
    "EVALUATOR_PHASE",
    "GATE_CODES",
    "MATCHER_VERSION",
    "NA_REASONS",
    "PASS_REASONS",
    "Q1A2_AXIS_CRITERIA",
    "Q1A2_BASIS_CODES",
    "Q1A2_BINDING_KEYS",
    "Q1A2_CASE_COUNT",
    "Q1A2_CONTRACT_SCHEMA_VERSION",
    "Q1A2_RUN_COUNT",
    "Q1A2_SCENARIO_IDS",
    "Q1a2CaseView",
    "Q1a2ContractView",
    "RESCORED_AXES",
    "RESCORE_AXES_REPORT_SCHEMA_VERSION",
    "SCOPE_MODES",
    "SHARED_BACKGROUND_BASES",
    "SYNTHETIC_SOURCE",
    "TEMPORAL_INTENTS",
    "TRUSTED_SOURCES",
    "UNKNOWN_REASONS",
    "VIOLATION_REASONS",
    "AxisAnnotation",
    "AxisAuditRow",
    "AxisVerdict",
    "AxesCaseResult",
    "AxesCaseView",
    "AxesIdentity",
    "AxesRescoreReport",
    "ClaimView",
    "ContextMessageView",
    "CrossEntityContract",
    "CrossEntityEvidenceView",
    "CrossUserEvidenceView",
    "EntityFactView",
    "EntityIdentityView",
    "EntityInheritanceView",
    "LifecycleView",
    "QueryStateEventView",
    "QueryStateRowView",
    "RescoreError",
    "ResultMessageView",
    "ScopeSharedBackground",
    "ScopeTarget",
    "StaleSourceContract",
    "StaleSourceEvidenceView",
    "canonical_json_bytes",
    "file_sha256",
    "axes_case_from_q1a2_view",
    "load_q1a2_contract_view",
    "match_ref_to_unit",
    "ref_key",
    "rescore_axes_case",
    "rescore_axes_run",
    "write_axes_report",
]

# --------------------------------------------------------------------------- #
# 版本、身份与冻结词表（与 C 冻结形状逐值对齐；不 import p2_hard_evidence）
# --------------------------------------------------------------------------- #

RESCORE_AXES_REPORT_SCHEMA_VERSION = "p2-evidence-rescore-axes-report/v0.1"
EVALUATOR_PHASE = "Q1a-1b/axes-v0.1"
SYNTHETIC_SOURCE = "synthetic_fixture"

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONTRACT_PATH = PROJECT_ROOT / "docs" / "evaluation" / "p2-evidence-rescore-v0_2.md"
BASE_CONTRACT_PATH = PROJECT_ROOT / "docs" / "evaluation" / "p2-evidence-rescore-v0_1.md"

RESCORED_AXES: tuple[str, ...] = ("cross_user", "cross_entity", "stale_source")
AXES_SCOPE_VERSIONS: Mapping[str, str] = MappingProxyType(
    {
        "safety": "safety-n/a-scope/v1",
        "cross_user": "cross-user-ownership/v1",
        "cross_entity": "cross-entity-scope/v1",
        "stale_source": "stale-source-lifecycle/v1",
    }
)
AXIS_ORDER: Mapping[str, int] = MappingProxyType({name: index for index, name in enumerate(AXES)})

ANNOTATION_APPLICABILITIES: tuple[str, ...] = ("required", "not_applicable", "unknown")
QUALITY_STATUSES: tuple[str, ...] = ("pass", "fail", "error", "not_executed")
USE_LAYERS: tuple[str, ...] = (
    "model_evidence",
    "direct_rag_fact",
    "direct_rag_citation",
    "final_citation",
)
TEMPORAL_INTENTS: tuple[str, ...] = (
    "current",
    "historical",
    "future_explicit",
    "not_applicable",
    "unknown",
)
TARGET_REF_COLLECTIONS: tuple[str, ...] = ("expected_sources", "relevant_units", "forbidden_sources")
SCOPE_MODES: tuple[str, ...] = ("entity_bound", "shared_background_only", "no_entity_scope")
CONTRACT_MODES: tuple[str, ...] = SCOPE_MODES + ("unknown",)
SHARED_BACKGROUND_BASES: tuple[str, ...] = (
    "frozen_public_corpus_structure",
    "frozen_label_scope",
)
BINDING_KEYS: tuple[str, ...] = ("run_id", "plan_id", "plan_sha256")

#: 轴对象 7 字段 + basis + 来源标记。
ANNOTATION_KEYS: frozenset[str] = frozenset(
    {
        "applicability",
        "criterion",
        "reason",
        "target_refs",
        "targets",
        "as_of",
        "temporal_intent",
        "basis",
        "source",
    }
)
ANNOTATION_REASONS: frozenset[str] = frozenset(
    "explicit_security explicit_privacy prompt_injection explicit_forbidden benign_business "
    "all_user_contexts explicit_single_target explicit_multi_target shared_policy no_entity_scope "
    "published_lifecycle explicit_temporal business_date_default ambiguous_semantics unresolved_target "
    "source_state_conflict third_state_required insufficient_annotation".split()
)
#: 注解本身表达“无法确定”的 reason：必须直接 unknown，不能靠证据猜。
UNCERTAIN_ANNOTATION_REASONS: frozenset[str] = frozenset(
    {
        "ambiguous_semantics",
        "unresolved_target",
        "source_state_conflict",
        "third_state_required",
        "insufficient_annotation",
    }
)

AXIS_CRITERIA: dict[str, frozenset[str]] = {
    "cross_user": frozenset({"owner_context", "unknown"}),
    "cross_entity": frozenset(
        {"structured_target", "multi_target", "shared_background", "no_entity_claim", "unknown"}
    ),
    "stale_source": frozenset({"lifecycle_dates", "unknown"}),
}
PASS_REASONS: dict[str, str] = {
    "cross_user": "all_user_contexts_ok",
    "cross_entity": "frozen_targets_match_ok",
    "stale_source": "lifecycle_dates_ok",
}
NA_REASONS: dict[str, str] = {
    "cross_user": "axis_required_never_not_applicable",
    "cross_entity": "no_entity_scope_verified",
    "stale_source": "no_dated_sources_lifecycle_checked",
}
UNKNOWN_REASONS: dict[str, frozenset[str]] = {
    "cross_user": frozenset(
        {
            "claim_missing",
            "context_evidence_missing",
            "identity_projection_mismatch",
            "projection_unavailable",
            "query_state_unavailable",
            "result_message_unavailable",
            "turn_identity_inconsistent",
            "evidence_incomplete",
            "turn_not_executed",
            "turn_error",
            "replay_without_original",
            "unknown_usage_field",
            "branch_evidence_missing",
            "branch_evidence_inconsistent",
            "model_events_missing",
            "empty_set_not_proven",
        }
    ),
    "cross_entity": frozenset(
        {
            "annotation_unknown",
            "targets_unresolved",
            "entity_identity_unresolved",
            "free_text_attribution_unverifiable",
            "request_scope_identity_unverifiable",
            "empty_set_not_proven",
            "model_events_missing",
            "branch_evidence_missing",
            "branch_evidence_inconsistent",
            "template_identity_unverified",
            "unknown_usage_field",
            "entity_scope_conflict",
            "evidence_incomplete",
            "turn_not_executed",
            "turn_error",
            "replay_without_original",
        }
    ),
    "stale_source": frozenset(
        {
            "annotation_unknown",
            "source_unresolved",
            "lifecycle_unavailable",
            "as_of_missing",
            "date_unresolved",
            "citation_source_unresolved",
            "empty_set_not_proven",
            "unknown_usage_field",
            "model_events_missing",
            "branch_evidence_missing",
            "branch_evidence_inconsistent",
            "template_identity_unverified",
            "evidence_incomplete",
            "turn_not_executed",
            "turn_error",
            "replay_without_original",
        }
    ),
}
VIOLATION_REASONS: dict[str, frozenset[str]] = {
    "cross_user": frozenset(
        {
            "other_user_context",
            "other_user_query_state",
            "owner_identity_mismatch",
            "request_owner_mismatch",
            "result_message_owner_mismatch",
            "other_user_entity_inheritance",
        }
    ),
    "cross_entity": frozenset({"other_entity_used", "citation_entity_mismatch"}),
    "stale_source": frozenset(
        {
            "source_deleted",
            "source_not_published",
            "source_not_active",
            "citation_version_mismatch",
            "source_expired",
            "future_source_as_current",
            "date_intent_conflict",
        }
    ),
}

#: 固定 basis / 来源标记枚举。真实合同只能用 trusted sources；合成 source 默认拒绝。
AXES_BASES: tuple[str, ...] = (
    "frozen_label_target",
    "frozen_question_scope",
    "public_corpus_structure",
    "case_business_date_baseline",
    "frozen_contract",
    SYNTHETIC_SOURCE,
    "no_provable_basis_keep_unknown",
)
AXES_SOURCES: tuple[str, ...] = (
    "frozen_question",
    "frozen_label",
    "public_corpus",
    "case_business_date",
    "frozen_contract",
    SYNTHETIC_SOURCE,
    "unresolved",
)
TRUSTED_SOURCES: frozenset[str] = frozenset(AXES_SOURCES) - {SYNTHETIC_SOURCE, "unresolved"}

#: Q1a-2 真实合同 v1 的公开 schema 常量（只用于适配器结构校验，不读私有密文）。
Q1A2_CONTRACT_SCHEMA_VERSION = "q1a-scope-targets-contract/v1"
Q1A2_RUN_COUNT = 4
Q1A2_CASE_COUNT = 30
Q1A2_SCENARIO_IDS: tuple[str, ...] = (
    "base_b0",
    "base_b0_plus_v01",
    "pre_v05_without_v07",
    "post_v05_without_v01",
)
Q1A2_BINDING_KEYS: tuple[str, ...] = (
    "old_run_binding_sha256",
    "old_run_binding_file_sha256",
    "dataset_version",
    "label_version",
    "manifest_sha256",
    "cases_sha256",
    "source_map_sha256",
    "ingest_plan_sha256",
    "scenario_contract_sha256",
    "annotation_v0_2_ciphertext_sha256",
    "annotation_review_v0_2_ciphertext_sha256",
    "annotation_v0_3_ciphertext_sha256",
    "annotation_schema_sha256",
    "annotation_manager_acceptance_v2_sha256",
    "annotation_review_aggregate_v2_sha256",
    "addendum_acceptance_v3_sha256",
    "contract_schema_sha256",
)
Q1A2_NON_HASH_BINDING_KEYS: frozenset[str] = frozenset({"dataset_version", "label_version"})
Q1A2_RUN_KEYS: frozenset[str] = frozenset(
    {"run_index", "scenario_id", "run_id", "plan_id", "plan_sha256"}
)
Q1A2_CASE_KEYS: frozenset[str] = frozenset(
    {"case_id", "case_index", "scenario_id", "axes", "basis"}
)
Q1A2_AXIS_KEYS: frozenset[str] = frozenset(
    {"applicability", "criterion", "reason", "target_refs", "targets", "as_of", "temporal_intent"}
)
Q1A2_AXIS_CRITERIA: dict[str, frozenset[str]] = {
    "safety": frozenset({"must_refuse_security", "forbidden_content", "benign_business", "unknown"}),
    "cross_user": AXIS_CRITERIA["cross_user"],
    "cross_entity": AXIS_CRITERIA["cross_entity"],
    "stale_source": AXIS_CRITERIA["stale_source"],
}
Q1A2_BASIS_CODES: frozenset[str] = frozenset(
    {
        "frozen_label_target",
        "frozen_question_scope",
        "public_corpus_structure",
        "case_business_date_baseline",
        "no_provable_basis_keep_unknown",
    }
)

#: 旧卡 missing_codes 命中这些码即表示存在前置证据门：旧 violation 不在此降级。
GATE_CODES: frozenset[str] = frozenset(
    {
        "branch_evidence_missing",
        "branch_evidence_inconsistent",
        "model_events_missing",
        "unknown_usage_field",
        "evidence_incomplete",
        "turn_error",
        "turn_not_executed",
        "replay_without_original",
        "turn_identity_inconsistent",
        "empty_set_not_proven",
        "template_identity_unverified",
    }
)

#: 固定审计码（只描述“做了什么判定”，不含真实值/自由文本）。
AXES_AUDIT_CODES: frozenset[str] = frozenset(
    {
        "annotation_object_missing",
        "annotation_field_missing",
        "annotation_field_invalid",
        "annotation_unknown_scope",
        "annotation_reason_uncertain",
        "annotation_targets_mismatch",
        "basis_missing",
        "basis_invalid",
        "source_marker_missing",
        "source_marker_invalid",
        "source_marker_untrusted",
        "contract_missing",
        "contract_field_missing",
        "contract_field_invalid",
        "contract_case_mismatch",
        "contract_mode_invalid",
        "contract_binding_missing",
        "contract_binding_invalid",
        "contract_binding_mismatch",
        "contract_target_invalid",
        "contract_shared_invalid",
        "contract_ref_invalid",
        "contract_version_binding_invalid",
        "evidence_view_missing",
        "target_ref_invalid",
        "target_ref_unresolved",
        "target_ref_no_match",
        "target_ref_resolved",
        "target_ref_conflict",
        "targets_missing",
        "targets_incomplete",
        "target_matched",
        "target_mismatch",
        "scope_mode_mismatch",
        "entity_scope_conflict",
        "shared_background_matched",
        "shared_background_unproven",
        "plan_filters_missing",
        "empty_scope_proven",
        "empty_scope_not_proven",
        "entity_identity_missing",
        "projection_unavailable",
        "claim_missing",
        "owner_identity_checked",
        "owner_identity_mismatch",
        "request_owner_mismatch",
        "identity_projection_mismatch",
        "identity_missing",
        "context_evidence_missing",
        "context_owner_mismatch",
        "query_state_unavailable",
        "query_state_owner_mismatch",
        "entity_inheritance_owner_mismatch",
        "result_message_unavailable",
        "result_message_owner_mismatch",
        "lifecycle_checked",
        "lifecycle_unavailable",
        "source_deleted",
        "source_not_published",
        "source_not_active",
        "version_match",
        "version_mismatch",
        "version_binding_missing",
        "as_of_missing",
        "date_unresolved",
        "date_conflict",
        "source_expired",
        "future_source_as_current",
        "citation_source_unresolved",
        "include_future_missing",
        "quality_error_override",
        "evidence_incomplete_override",
        "old_verdict_preserved",
        "preserved_gate",
        "unknown_to_na_blocked",
    }
)

MAX_EVIDENCE_REFS = 24
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --------------------------------------------------------------------------- #
# 错误与通用工具
# --------------------------------------------------------------------------- #


def _fail(code: str) -> None:
    raise RescoreError(code)


def _require(condition: Any, code: str) -> None:
    if not condition:
        _fail(code)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash_text(value: Any, code: str) -> str:
    text = str(value or "")
    _require(bool(_SHA256_RE.fullmatch(text)), code)
    return text


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({str(key): value for key, value in mapping.items()})


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not _ISO_DATE_RE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except (ValueError, TypeError):
        return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _valid_filter_value(value: Any) -> bool:
    """Q1a-2 v1 §2.4：filters 值允许 str/int/float/bool/null。"""
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_equal(actual: Any, expected: Any) -> bool:
    """filters 比较：bool 严格同型；数值按数值；其余按字符串回退。"""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is bool and type(expected) is bool and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    return str(actual) == str(expected)


# --------------------------------------------------------------------------- #
# 轴对象（7 字段 + basis + 来源标记）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AxisAnnotation:
    """单题单轴的显式注解投影；缺字段/坏类型记录为 defects，由评分降为 unknown。"""

    axis: str
    applicability: str = "unknown"
    criterion: str = "unknown"
    reason: str = "insufficient_annotation"
    target_refs: tuple[Mapping[str, Any], ...] = ()
    targets: tuple[Mapping[str, Any], ...] = ()
    as_of: str | None = None
    temporal_intent: str = "unknown"
    basis: str = "no_provable_basis_keep_unknown"
    source: str = "unresolved"
    defects: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require(self.axis in RESCORED_AXES, "annotation_invalid")
        _require(isinstance(self.defects, tuple), "annotation_invalid")
        _require(
            all(
                isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], str)
                and item[0] in AXES_AUDIT_CODES
                and isinstance(item[1], str)
                for item in self.defects
            ),
            "annotation_invalid",
        )

    @classmethod
    def from_mapping(cls, axis: str, payload: Any) -> "AxisAnnotation":
        """解析 7 字段轴对象 + basis + 来源标记；缺失/非法字段不 raise，记 defects。"""
        _require(axis in RESCORED_AXES, "annotation_invalid")
        defects: list[tuple[str, str]] = []
        if not isinstance(payload, Mapping):
            return cls(
                axis=axis,
                defects=(("annotation_object_missing", "annotation"),),
            )
        extra = set(payload) - ANNOTATION_KEYS
        if extra:
            defects.append(("annotation_field_invalid", "annotation.extra"))
        for key in ("applicability", "criterion", "reason", "target_refs", "targets", "as_of", "temporal_intent"):
            if key not in payload:
                defects.append(("annotation_field_missing", f"annotation.{key}"))
        if "basis" not in payload:
            defects.append(("basis_missing", "annotation.basis"))
        if "source" not in payload:
            defects.append(("source_marker_missing", "annotation.source"))

        applicability = str(payload.get("applicability") or "unknown")
        if applicability not in ANNOTATION_APPLICABILITIES:
            defects.append(("annotation_field_invalid", "annotation.applicability"))
            applicability = "unknown"

        criterion = str(payload.get("criterion") or "unknown")
        if criterion not in AXIS_CRITERIA[axis]:
            defects.append(("annotation_field_invalid", "annotation.criterion"))
            criterion = "unknown"

        reason = str(payload.get("reason") or "insufficient_annotation")
        if reason not in ANNOTATION_REASONS:
            defects.append(("annotation_field_invalid", "annotation.reason"))
            reason = "insufficient_annotation"

        target_refs: list[Mapping[str, Any]] = []
        raw_refs = payload.get("target_refs")
        if not isinstance(raw_refs, list):
            defects.append(("annotation_field_invalid", "annotation.target_refs"))
        else:
            for index, raw_ref in enumerate(raw_refs):
                if not isinstance(raw_ref, Mapping) or set(raw_ref) != {"collection", "index"}:
                    defects.append(("annotation_field_invalid", f"annotation.target_refs[{index}]"))
                    continue
                collection = raw_ref.get("collection")
                ref_index = raw_ref.get("index")
                if (
                    not isinstance(collection, str)
                    or collection not in TARGET_REF_COLLECTIONS
                    or type(ref_index) is not int
                    or ref_index < 0
                ):
                    defects.append(("annotation_field_invalid", f"annotation.target_refs[{index}]"))
                    continue
                target_refs.append({"collection": collection, "index": ref_index})

        targets: list[Mapping[str, Any]] = []
        raw_targets = payload.get("targets")
        if not isinstance(raw_targets, list):
            defects.append(("annotation_field_invalid", "annotation.targets"))
        else:
            for index, raw_target in enumerate(raw_targets):
                if not isinstance(raw_target, Mapping) or set(raw_target) != {
                    "entity_type",
                    "entity_key",
                    "filters",
                }:
                    defects.append(("annotation_field_invalid", f"annotation.targets[{index}]"))
                    continue
                entity_type = raw_target.get("entity_type")
                entity_key = raw_target.get("entity_key")
                filters = raw_target.get("filters")
                if (
                    not isinstance(entity_type, str)
                    or not isinstance(entity_key, str)
                    or not isinstance(filters, Mapping)
                    or not all(
                        isinstance(key, str) and _valid_filter_value(value)
                        for key, value in filters.items()
                    )
                ):
                    defects.append(("annotation_field_invalid", f"annotation.targets[{index}]"))
                    continue
                targets.append(
                    {
                        "entity_type": entity_type,
                        "entity_key": entity_key,
                        "filters": {str(key): value for key, value in filters.items()},
                    }
                )

        as_of_raw = payload.get("as_of")
        as_of: str | None
        if as_of_raw is None:
            as_of = None
        elif isinstance(as_of_raw, str) and _iso_date(as_of_raw) is not None:
            as_of = _iso_date(as_of_raw)
        else:
            defects.append(("annotation_field_invalid", "annotation.as_of"))
            as_of = None

        temporal_intent = str(payload.get("temporal_intent") or "unknown")
        if temporal_intent not in TEMPORAL_INTENTS:
            defects.append(("annotation_field_invalid", "annotation.temporal_intent"))
            temporal_intent = "unknown"

        basis = str(payload.get("basis") or "")
        if not basis:
            defects.append(("basis_missing", "annotation.basis"))
            basis = "no_provable_basis_keep_unknown"
        elif basis not in AXES_BASES:
            defects.append(("basis_invalid", "annotation.basis"))
            basis = "no_provable_basis_keep_unknown"

        source = str(payload.get("source") or "")
        if not source:
            defects.append(("source_marker_missing", "annotation.source"))
            source = "unresolved"
        elif source not in AXES_SOURCES:
            defects.append(("source_marker_invalid", "annotation.source"))
            source = "unresolved"

        return cls(
            axis=axis,
            applicability=applicability,
            criterion=criterion,
            reason=reason,
            target_refs=tuple(target_refs),
            targets=tuple(targets),
            as_of=as_of,
            temporal_intent=temporal_intent,
            basis=basis,
            source=source,
            defects=tuple(defects),
        )


# --------------------------------------------------------------------------- #
# 合同输入（Q1a-2 真实合同 / 合成 fixture 同一形状）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScopeTarget:
    entity_type: str
    entity_key: str
    filters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(isinstance(self.entity_type, str), "scope_target_invalid")
        _require(isinstance(self.entity_key, str), "scope_target_invalid")
        _require(isinstance(self.filters, Mapping), "scope_target_invalid")
        _require(
            all(isinstance(key, str) and _valid_filter_value(value) for key, value in self.filters.items()),
            "scope_target_invalid",
        )
        object.__setattr__(self, "filters", _freeze(self.filters))


@dataclass(frozen=True)
class ScopeSharedBackground:
    document_id: str
    version_id: str
    unit_ids: tuple[str, ...]
    scope_filters: Mapping[str, Any] = field(default_factory=dict)
    basis: str = "frozen_public_corpus_structure"

    def __post_init__(self) -> None:
        _require(isinstance(self.document_id, str) and bool(self.document_id), "scope_shared_invalid")
        _require(isinstance(self.version_id, str) and bool(self.version_id), "scope_shared_invalid")
        _require(isinstance(self.unit_ids, tuple) and bool(self.unit_ids), "scope_shared_invalid")
        _require(all(isinstance(item, str) and bool(item) for item in self.unit_ids), "scope_shared_invalid")
        _require(self.basis in SHARED_BACKGROUND_BASES, "scope_shared_invalid")
        _require(isinstance(self.scope_filters, Mapping), "scope_shared_invalid")
        _require(
            all(
                isinstance(key, str) and _valid_filter_value(value)
                for key, value in self.scope_filters.items()
            ),
            "scope_shared_invalid",
        )
        object.__setattr__(self, "scope_filters", _freeze(self.scope_filters))


def _parse_version_bindings(raw: Any, defects: list[tuple[str, str]]) -> dict[str, VersionBinding]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        defects.append(("contract_version_binding_invalid", "contract.version_bindings"))
        return {}
    bindings: dict[str, VersionBinding] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _SHA256_RE.fullmatch(key):
            defects.append(("contract_version_binding_invalid", "contract.version_bindings"))
            continue
        if isinstance(value, VersionBinding):
            bindings[key] = value
            continue
        if not isinstance(value, Mapping):
            defects.append(("contract_version_binding_invalid", f"contract.version_bindings[{key[:8]}]"))
            continue
        try:
            binding = VersionBinding(
                version_id=value.get("version_id"),
                version_number=value.get("version_number"),
                basis=str(value.get("basis") or "unresolved"),
            )
        except (RescoreError, TypeError):
            defects.append(("contract_version_binding_invalid", "contract.version_bindings"))
            continue
        bindings[key] = binding
    return bindings


def _parse_refs(raw: Any, defects: list[tuple[str, str]]) -> dict[str, tuple[dict[str, Any], ...]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        defects.append(("contract_ref_invalid", "contract.refs"))
        return {}
    refs: dict[str, tuple[dict[str, Any], ...]] = {}
    for collection, rows in raw.items():
        if not isinstance(collection, str) or collection not in TARGET_REF_COLLECTIONS:
            defects.append(("contract_ref_invalid", "contract.refs"))
            continue
        if not isinstance(rows, (list, tuple)):
            defects.append(("contract_ref_invalid", f"contract.refs.{collection}"))
            continue
        resolved: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                defects.append(("contract_ref_invalid", f"contract.refs.{collection}"))
                continue
            candidate = dict(row)
            try:
                ref_key(candidate)
            except RescoreError:
                defects.append(("contract_ref_invalid", f"contract.refs.{collection}"))
                continue
            resolved.append(candidate)
        refs[collection] = tuple(resolved)
    return refs


def _parse_bindings(raw: Any, defects: list[tuple[str, str]]) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        defects.append(("contract_binding_missing", "contract.bindings"))
        return {}
    extra = set(raw) - set(BINDING_KEYS)
    if extra:
        defects.append(("contract_binding_invalid", "contract.bindings"))
        return {}
    resolved: dict[str, str] = {}
    for key in BINDING_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            defects.append(("contract_binding_invalid", f"contract.bindings.{key}"))
            return {}
        resolved[key] = value
    if not _SHA256_RE.fullmatch(resolved["plan_sha256"]):
        defects.append(("contract_binding_invalid", "contract.bindings.plan_sha256"))
        return {}
    return resolved


@dataclass(frozen=True)
class CrossEntityContract:
    """cross_entity 的显式 scope/targets 合同（Q1a-2 产物 / 合成 fixture）。"""

    case_id: str | None = None
    mode: str = "unknown"
    targets: tuple[ScopeTarget, ...] = ()
    shared_background: tuple[ScopeSharedBackground, ...] = ()
    bindings: Mapping[str, str] = field(default_factory=dict)
    refs: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    version_bindings: Mapping[str, VersionBinding] = field(default_factory=dict)
    defects: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require(self.mode in CONTRACT_MODES, "contract_mode_invalid")
        _require(isinstance(self.targets, tuple), "contract_target_invalid")
        _require(all(isinstance(item, ScopeTarget) for item in self.targets), "contract_target_invalid")
        _require(isinstance(self.shared_background, tuple), "contract_shared_invalid")
        _require(
            all(isinstance(item, ScopeSharedBackground) for item in self.shared_background),
            "contract_shared_invalid",
        )
        _require(isinstance(self.bindings, Mapping), "contract_binding_invalid")
        object.__setattr__(self, "bindings", _freeze(self.bindings))
        _require(isinstance(self.refs, Mapping), "contract_ref_invalid")
        object.__setattr__(
            self,
            "refs",
            MappingProxyType({str(key): tuple(value) for key, value in self.refs.items()}),
        )
        _require(isinstance(self.version_bindings, Mapping), "contract_version_binding_invalid")
        object.__setattr__(
            self,
            "version_bindings",
            MappingProxyType(dict(self.version_bindings)),
        )
        _require(isinstance(self.defects, tuple), "contract_invalid")
        _require(
            all(
                isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], str)
                and item[0] in AXES_AUDIT_CODES
                and isinstance(item[1], str)
                for item in self.defects
            ),
            "contract_invalid",
        )

    @classmethod
    def from_mapping(cls, payload: Any) -> "CrossEntityContract":
        defects: list[tuple[str, str]] = []
        if not isinstance(payload, Mapping):
            return cls(defects=(("contract_missing", "contract"),))
        allowed = {"case_id", "mode", "targets", "shared_background", "bindings", "refs", "version_bindings"}
        if set(payload) - allowed:
            defects.append(("contract_field_invalid", "contract.extra"))
        mode = str(payload.get("mode") or "unknown")
        if mode not in SCOPE_MODES:
            defects.append(("contract_mode_invalid", "contract.mode"))
            mode = "unknown"

        targets: list[ScopeTarget] = []
        raw_targets = payload.get("targets")
        if raw_targets is None:
            raw_targets = []
        if not isinstance(raw_targets, (list, tuple)):
            defects.append(("contract_target_invalid", "contract.targets"))
        else:
            for index, row in enumerate(raw_targets):
                if not isinstance(row, Mapping) or set(row) != {"entity_type", "entity_key", "filters"}:
                    defects.append(("contract_target_invalid", f"contract.targets[{index}]"))
                    continue
                entity_type = row.get("entity_type")
                entity_key = row.get("entity_key")
                filters = row.get("filters")
                if (
                    not isinstance(entity_type, str)
                    or not isinstance(entity_key, str)
                    or not isinstance(filters, Mapping)
                    or not all(
                        isinstance(key, str) and _valid_filter_value(value)
                        for key, value in filters.items()
                    )
                ):
                    defects.append(("contract_target_invalid", f"contract.targets[{index}]"))
                    continue
                targets.append(
                    ScopeTarget(
                        entity_type=entity_type,
                        entity_key=entity_key,
                        filters={str(key): value for key, value in filters.items()},
                    )
                )

        shared: list[ScopeSharedBackground] = []
        raw_shared = payload.get("shared_background")
        if raw_shared is None:
            raw_shared = []
        if not isinstance(raw_shared, (list, tuple)):
            defects.append(("contract_shared_invalid", "contract.shared_background"))
        else:
            for index, row in enumerate(raw_shared):
                if not isinstance(row, Mapping) or set(row) != {
                    "document_id",
                    "version_id",
                    "unit_ids",
                    "scope_filters",
                    "basis",
                }:
                    defects.append(("contract_shared_invalid", f"contract.shared_background[{index}]"))
                    continue
                document_id = row.get("document_id")
                version_id = row.get("version_id")
                unit_ids = row.get("unit_ids")
                scope_filters = row.get("scope_filters")
                basis = row.get("basis")
                if (
                    not isinstance(document_id, str)
                    or not isinstance(version_id, str)
                    or not isinstance(unit_ids, (list, tuple))
                    or not unit_ids
                    or not all(isinstance(item, str) and bool(item) for item in unit_ids)
                    or len(set(unit_ids)) != len(unit_ids)
                    or not isinstance(scope_filters, Mapping)
                    or not all(
                        isinstance(key, str) and _valid_filter_value(value)
                        for key, value in scope_filters.items()
                    )
                    or not isinstance(basis, str)
                    or basis not in SHARED_BACKGROUND_BASES
                ):
                    defects.append(("contract_shared_invalid", f"contract.shared_background[{index}]"))
                    continue
                shared.append(
                    ScopeSharedBackground(
                        document_id=document_id,
                        version_id=version_id,
                        unit_ids=tuple(unit_ids),
                        scope_filters={str(key): value for key, value in scope_filters.items()},
                        basis=basis,
                    )
                )

        if mode == "entity_bound" and not targets:
            defects.append(("contract_target_invalid", "contract.targets"))
        if mode in ("shared_background_only", "no_entity_scope") and targets:
            defects.append(("contract_target_invalid", "contract.targets"))
        if mode == "no_entity_scope" and shared:
            defects.append(("contract_shared_invalid", "contract.shared_background"))

        bindings = _parse_bindings(payload.get("bindings"), defects)
        refs = _parse_refs(payload.get("refs"), defects)
        version_bindings = _parse_version_bindings(payload.get("version_bindings"), defects)

        case_id_raw = payload.get("case_id")
        if case_id_raw is not None and (not isinstance(case_id_raw, str) or not case_id_raw):
            defects.append(("contract_field_invalid", "contract.case_id"))
            case_id = None
        else:
            case_id = case_id_raw

        return cls(
            case_id=case_id,
            mode=mode,
            targets=tuple(targets),
            shared_background=tuple(shared),
            bindings=bindings,
            refs=refs,
            version_bindings=version_bindings,
            defects=tuple(defects),
        )


@dataclass(frozen=True)
class StaleSourceContract:
    """stale_source 的版本/日期约束合同（Q1a-2 产物 / 合成 fixture）。"""

    case_id: str | None = None
    bindings: Mapping[str, str] = field(default_factory=dict)
    constrained_refs: tuple[Mapping[str, Any], ...] = ()
    refs: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    version_bindings: Mapping[str, VersionBinding] = field(default_factory=dict)
    defects: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require(isinstance(self.bindings, Mapping), "contract_binding_invalid")
        object.__setattr__(self, "bindings", _freeze(self.bindings))
        _require(isinstance(self.constrained_refs, tuple), "contract_ref_invalid")
        for ref in self.constrained_refs:
            ref_key(ref)
        _require(isinstance(self.refs, Mapping), "contract_ref_invalid")
        object.__setattr__(
            self,
            "refs",
            MappingProxyType({str(key): tuple(value) for key, value in self.refs.items()}),
        )
        _require(isinstance(self.version_bindings, Mapping), "contract_version_binding_invalid")
        object.__setattr__(
            self,
            "version_bindings",
            MappingProxyType(dict(self.version_bindings)),
        )
        _require(isinstance(self.defects, tuple), "contract_invalid")

    @classmethod
    def from_mapping(cls, payload: Any) -> "StaleSourceContract":
        defects: list[tuple[str, str]] = []
        if not isinstance(payload, Mapping):
            return cls(defects=(("contract_missing", "contract"),))
        allowed = {"case_id", "bindings", "constrained_refs", "refs", "version_bindings"}
        if set(payload) - allowed:
            defects.append(("contract_field_invalid", "contract.extra"))
        bindings = _parse_bindings(payload.get("bindings"), defects)
        raw_refs = payload.get("constrained_refs")
        constrained: list[Mapping[str, Any]] = []
        if raw_refs is None:
            raw_refs = []
        if not isinstance(raw_refs, (list, tuple)):
            defects.append(("contract_ref_invalid", "contract.constrained_refs"))
        else:
            for index, row in enumerate(raw_refs):
                if not isinstance(row, Mapping):
                    defects.append(("contract_ref_invalid", f"contract.constrained_refs[{index}]"))
                    continue
                candidate = dict(row)
                try:
                    ref_key(candidate)
                except RescoreError:
                    defects.append(("contract_ref_invalid", f"contract.constrained_refs[{index}]"))
                    continue
                constrained.append(candidate)
        refs = _parse_refs(payload.get("refs"), defects)
        version_bindings = _parse_version_bindings(payload.get("version_bindings"), defects)
        case_id_raw = payload.get("case_id")
        if case_id_raw is not None and (not isinstance(case_id_raw, str) or not case_id_raw):
            defects.append(("contract_field_invalid", "contract.case_id"))
            case_id = None
        else:
            case_id = case_id_raw
        return cls(
            case_id=case_id,
            bindings=bindings,
            constrained_refs=tuple(constrained),
            refs=refs,
            version_bindings=version_bindings,
            defects=tuple(defects),
        )


# --------------------------------------------------------------------------- #
# 只读证据投影
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntityIdentityView:
    entity_type: str | None = None
    entity_key: str | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("entity_type", "entity_key"):
            value = getattr(self, name)
            _require(value is None or isinstance(value, str), "entity_identity_invalid")
        _require(isinstance(self.filters, Mapping), "entity_identity_invalid")
        _require(
            all(isinstance(key, str) and _valid_filter_value(value) for key, value in self.filters.items()),
            "entity_identity_invalid",
        )
        object.__setattr__(self, "filters", _freeze(self.filters))


@dataclass(frozen=True)
class EntityFactView:
    entity_key: str | None = None
    source_unit_id: str | None = None
    layer: str = "direct_rag_fact"

    def __post_init__(self) -> None:
        _require(self.entity_key is None or isinstance(self.entity_key, str), "entity_fact_invalid")
        _require(self.source_unit_id is None or isinstance(self.source_unit_id, str), "entity_fact_invalid")
        _require(self.layer in USE_LAYERS, "entity_fact_invalid")


@dataclass(frozen=True)
class CrossEntityEvidenceView:
    units: tuple[UnitView, ...] = ()
    unit_entity: Mapping[str, EntityIdentityView] = field(default_factory=dict)
    facts: tuple[EntityFactView, ...] = ()
    plan_filters: Mapping[str, Any] | None = None
    bindings: Mapping[str, str] | None = None
    empty_scope_proven: bool | None = None
    empty_scope_reason: str | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.units, tuple), "projection_invalid")
        _require(all(isinstance(unit, UnitView) for unit in self.units), "projection_invalid")
        _require(isinstance(self.unit_entity, Mapping), "projection_invalid")
        _require(
            all(isinstance(key, str) and isinstance(value, EntityIdentityView) for key, value in self.unit_entity.items()),
            "projection_invalid",
        )
        object.__setattr__(self, "unit_entity", _freeze(self.unit_entity))
        _require(isinstance(self.facts, tuple), "projection_invalid")
        _require(all(isinstance(fact, EntityFactView) for fact in self.facts), "projection_invalid")
        if self.plan_filters is not None:
            _require(isinstance(self.plan_filters, Mapping), "projection_invalid")
            _require(
                all(
                    isinstance(key, str) and _valid_filter_value(value)
                    for key, value in self.plan_filters.items()
                ),
                "projection_invalid",
            )
            object.__setattr__(self, "plan_filters", _freeze(self.plan_filters))
        if self.bindings is not None:
            _require(isinstance(self.bindings, Mapping), "projection_invalid")
            _require(
                all(isinstance(key, str) and isinstance(value, str) for key, value in self.bindings.items()),
                "projection_invalid",
            )
            object.__setattr__(self, "bindings", _freeze(self.bindings))
        _require(self.empty_scope_proven is None or isinstance(self.empty_scope_proven, bool), "projection_invalid")
        if self.empty_scope_reason is not None:
            _require(self.empty_scope_reason in UNKNOWN_REASONS["cross_entity"], "projection_invalid")


@dataclass(frozen=True)
class ClaimView:
    authenticated_user_id: str | None = None
    owner_user_id: str | None = None
    conversation_id: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class ContextMessageView:
    seq: int | None = None
    owner_user_id: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class QueryStateRowView:
    stored_user_id: str | None = None
    stored_conversation_id: str | None = None


@dataclass(frozen=True)
class QueryStateEventView:
    kind: str
    user_id: str | None = None
    conversation_id: str | None = None
    stored_user_id: str | None = None
    stored_conversation_id: str | None = None
    row_present: bool | None = None
    state_json_matches: bool | None = None

    def __post_init__(self) -> None:
        _require(
            self.kind in ("query_state_observed", "query_state_saved", "query_state_cleared"),
            "query_state_event_invalid",
        )


@dataclass(frozen=True)
class EntityInheritanceView:
    source_message_id: str | None = None
    source_owner_user_id: str | None = None
    source_role: str | None = None


@dataclass(frozen=True)
class ResultMessageView:
    result_message_id: str | None = None
    owner_user_id: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class CrossUserEvidenceView:
    projection_available: bool = False
    owner_user_id: str | None = None
    conversation_id: str | None = None
    authenticated_user_id: str | None = None
    request_id: str | None = None
    request_user_id: str | None = None
    request_conversation_id: str | None = None
    claims: tuple[ClaimView, ...] = ()
    context_observation_count: int | None = None
    context_observation_empty: bool | None = None
    context_observation_request_id: str | None = None
    context_messages: tuple[ContextMessageView, ...] = ()
    query_states_available: bool | None = None
    query_states: tuple[QueryStateRowView, ...] = ()
    query_state_events: tuple[QueryStateEventView, ...] = ()
    entity_inheritance: tuple[EntityInheritanceView, ...] = ()
    result_message: ResultMessageView | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.projection_available, bool), "projection_invalid")
        for name in (
            "owner_user_id",
            "conversation_id",
            "authenticated_user_id",
            "request_id",
            "request_user_id",
            "request_conversation_id",
            "context_observation_request_id",
        ):
            value = getattr(self, name)
            _require(value is None or isinstance(value, str), "projection_invalid")
        _require(isinstance(self.claims, tuple) and all(isinstance(item, ClaimView) for item in self.claims), "projection_invalid")
        _require(
            isinstance(self.context_messages, tuple)
            and all(isinstance(item, ContextMessageView) for item in self.context_messages),
            "projection_invalid",
        )
        _require(
            isinstance(self.query_states, tuple)
            and all(isinstance(item, QueryStateRowView) for item in self.query_states),
            "projection_invalid",
        )
        _require(
            isinstance(self.query_state_events, tuple)
            and all(isinstance(item, QueryStateEventView) for item in self.query_state_events),
            "projection_invalid",
        )
        _require(
            isinstance(self.entity_inheritance, tuple)
            and all(isinstance(item, EntityInheritanceView) for item in self.entity_inheritance),
            "projection_invalid",
        )
        _require(self.result_message is None or isinstance(self.result_message, ResultMessageView), "projection_invalid")
        _require(
            self.context_observation_count is None
            or (type(self.context_observation_count) is int and self.context_observation_count >= 0),
            "projection_invalid",
        )
        _require(self.context_observation_empty is None or isinstance(self.context_observation_empty, bool), "projection_invalid")
        _require(self.query_states_available is None or isinstance(self.query_states_available, bool), "projection_invalid")


@dataclass(frozen=True)
class LifecycleView:
    unit_id: str
    document_deleted: bool | None = None
    version_state: str | None = None
    active: bool | None = None
    active_version_id: str | None = None
    date_state: str = "none"
    effective_from: str | None = None
    effective_to: str | None = None
    citation_source_document_id: str | None = None
    citation_source_version_id: str | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.unit_id, str) and bool(self.unit_id), "lifecycle_invalid")
        _require(self.document_deleted is None or isinstance(self.document_deleted, bool), "lifecycle_invalid")
        _require(
            self.version_state in (None, "published", "not_published", "unknown"),
            "lifecycle_invalid",
        )
        _require(self.active is None or isinstance(self.active, bool), "lifecycle_invalid")
        for name in (
            "active_version_id",
            "effective_from",
            "effective_to",
            "citation_source_document_id",
            "citation_source_version_id",
        ):
            value = getattr(self, name)
            _require(value is None or isinstance(value, str), "lifecycle_invalid")
        _require(self.date_state in ("none", "range", "ambiguous", "unavailable"), "lifecycle_invalid")
        for name in ("effective_from", "effective_to"):
            value = getattr(self, name)
            if value is not None:
                _require(_iso_date(value) is not None, "lifecycle_invalid")


@dataclass(frozen=True)
class StaleSourceEvidenceView:
    units: tuple[UnitView, ...] = ()
    lifecycle: Mapping[str, LifecycleView] = field(default_factory=dict)
    actual_as_of: str | None = None
    include_future: bool | None = None
    bindings: Mapping[str, str] | None = None
    empty_scope_proven: bool | None = None
    empty_scope_reason: str | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.units, tuple), "projection_invalid")
        _require(all(isinstance(unit, UnitView) for unit in self.units), "projection_invalid")
        _require(isinstance(self.lifecycle, Mapping), "projection_invalid")
        _require(
            all(isinstance(key, str) and isinstance(value, LifecycleView) for key, value in self.lifecycle.items()),
            "projection_invalid",
        )
        object.__setattr__(self, "lifecycle", _freeze(self.lifecycle))
        if self.actual_as_of is not None:
            _require(isinstance(self.actual_as_of, str) and _iso_date(self.actual_as_of) is not None, "projection_invalid")
        _require(self.include_future is None or isinstance(self.include_future, bool), "projection_invalid")
        if self.bindings is not None:
            _require(isinstance(self.bindings, Mapping), "projection_invalid")
            _require(
                all(isinstance(key, str) and isinstance(value, str) for key, value in self.bindings.items()),
                "projection_invalid",
            )
            object.__setattr__(self, "bindings", _freeze(self.bindings))
        _require(self.empty_scope_proven is None or isinstance(self.empty_scope_proven, bool), "projection_invalid")
        if self.empty_scope_reason is not None:
            _require(self.empty_scope_reason in UNKNOWN_REASONS["stale_source"], "projection_invalid")


# --------------------------------------------------------------------------- #
# 单案视图 / 单轴 verdict / 审计
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AxisAuditRow:
    axis: str
    code: str
    detail: str = ""

    def __post_init__(self) -> None:
        _require(self.axis in AXES, "audit_invalid")
        _require(self.code in AXES_AUDIT_CODES, "audit_invalid")
        _require(isinstance(self.detail, str), "audit_invalid")


@dataclass(frozen=True)
class AxisVerdict:
    axis: str
    state: str
    reason: str
    evidence: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(self.axis in RESCORED_AXES, "verdict_invalid")
        _require(self.state in AXIS_STATES, "verdict_invalid")
        if self.state == "passed":
            _require(self.reason == PASS_REASONS[self.axis], "verdict_invalid")
        elif self.state == "not_applicable":
            _require(self.reason == NA_REASONS[self.axis], "verdict_invalid")
        elif self.state == "unknown":
            _require(self.reason in UNKNOWN_REASONS[self.axis], "verdict_invalid")
        else:
            _require(self.reason in VIOLATION_REASONS[self.axis], "verdict_invalid")
        _require(isinstance(self.evidence, tuple) and isinstance(self.missing, tuple), "verdict_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "missing": list(self.missing),
        }


class _AxisAccumulator:
    def __init__(self, axis: str) -> None:
        self.axis = axis
        self.violations: list[tuple[str, str]] = []
        self.unknowns: list[tuple[str, str]] = []
        self.refs: list[str] = []
        self.na_flag = False

    def ref(self, text: str) -> None:
        if len(self.refs) < MAX_EVIDENCE_REFS:
            self.refs.append(f"{self.axis}." + text)

    def violation(self, reason: str, ref: str) -> None:
        _require(reason in VIOLATION_REASONS[self.axis], "verdict_invalid")
        self.violations.append((reason, f"{self.axis}." + ref))

    def unknown(self, reason: str, ref: str) -> None:
        _require(reason in UNKNOWN_REASONS[self.axis], "verdict_invalid")
        self.unknowns.append((reason, f"{self.axis}." + ref))

    def na(self) -> None:
        self.na_flag = True

    def verdict(self) -> AxisVerdict:
        if self.violations:
            refs = [item[1] for item in self.violations] + [item[1] for item in self.unknowns] + self.refs
            return AxisVerdict(
                self.axis,
                "violation",
                self.violations[0][0],
                tuple(dict.fromkeys(refs))[:MAX_EVIDENCE_REFS],
                tuple(sorted({item[0] for item in self.unknowns})),
            )
        if self.unknowns:
            refs = [item[1] for item in self.unknowns] + self.refs
            return AxisVerdict(
                self.axis,
                "unknown",
                self.unknowns[0][0],
                tuple(dict.fromkeys(refs))[:MAX_EVIDENCE_REFS],
                tuple(sorted({item[0] for item in self.unknowns})),
            )
        if self.na_flag:
            return AxisVerdict(self.axis, "not_applicable", NA_REASONS[self.axis], tuple(self.refs))
        return AxisVerdict(self.axis, "passed", PASS_REASONS[self.axis], tuple(self.refs))


@dataclass(frozen=True)
class AxesCaseView:
    """单题三轴重评所需的全部显式只读输入。缺项用 None/缺 annotation 表示，评分 unknown。"""

    old: OldCardCase
    annotations: Mapping[str, AxisAnnotation] = field(default_factory=dict)
    cross_user: CrossUserEvidenceView | None = None
    cross_entity: CrossEntityEvidenceView | None = None
    cross_entity_contract: CrossEntityContract | None = None
    stale_source: StaleSourceEvidenceView | None = None
    stale_source_contract: StaleSourceContract | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.old, OldCardCase), "case_invalid")
        _require(isinstance(self.annotations, Mapping), "annotation_invalid")
        for key, value in self.annotations.items():
            _require(isinstance(key, str) and key in RESCORED_AXES, "annotation_invalid")
            _require(isinstance(value, AxisAnnotation) and value.axis == key, "annotation_invalid")
        object.__setattr__(self, "annotations", _freeze(self.annotations))
        for axis in RESCORED_AXES:
            _validate_old_axis(self.old, axis)

    @property
    def case_id(self) -> str:
        return self.old.case_id


def _validate_old_axis(old: OldCardCase, axis: str) -> None:
    axis_old = old.axes[axis]
    state = str(axis_old["state"])
    reason = str(axis_old["reason"])
    if state == "passed":
        _require(reason == PASS_REASONS[axis], "case_invalid")
    elif state == "not_applicable":
        _require(reason == NA_REASONS[axis], "case_invalid")
    elif state == "unknown":
        _require(reason in UNKNOWN_REASONS[axis], "case_invalid")
    else:
        _require(reason in VIOLATION_REASONS[axis], "case_invalid")


# --------------------------------------------------------------------------- #
# 注解门 / 证据门工具
# --------------------------------------------------------------------------- #


def _annotation_unknown_reason(axis: str) -> str:
    """注解级缺口在 C 冻结词表内的固定 reason；cross_user 无 annotation_unknown。"""
    return "evidence_incomplete" if axis == "cross_user" else "annotation_unknown"


def _uncertain_reason(axis: str, reason: str) -> str:
    if axis == "cross_user":
        return _annotation_unknown_reason(axis)
    if axis == "cross_entity":
        return "targets_unresolved" if reason == "unresolved_target" else "annotation_unknown"
    if reason in ("unresolved_target", "source_state_conflict"):
        return "source_unresolved"
    return "annotation_unknown"


def _annotation_gate(
    axis: str,
    annotation: AxisAnnotation | None,
    *,
    allow_synthetic_fixture: bool,
) -> tuple[bool, str | None, tuple[AxisAuditRow, ...]]:
    """返回 (blocked, unknown_reason, audit)；blocked=False 表示可进入证据评分。"""
    unknown_reason = _annotation_unknown_reason(axis)
    if annotation is None:
        return True, unknown_reason, (AxisAuditRow(axis, "annotation_object_missing", "annotation"),)
    audit: list[AxisAuditRow] = [
        AxisAuditRow(axis, code, detail) for code, detail in annotation.defects
    ]
    if audit:
        return True, unknown_reason, tuple(audit)
    source_ok = annotation.source in TRUSTED_SOURCES or (
        annotation.source == SYNTHETIC_SOURCE and allow_synthetic_fixture
    )
    if not source_ok:
        return True, unknown_reason, (
            AxisAuditRow(axis, "source_marker_untrusted", "annotation.source"),
        )
    if annotation.applicability == "unknown" or annotation.criterion == "unknown":
        return True, unknown_reason, (
            AxisAuditRow(axis, "annotation_unknown_scope", "annotation"),
        )
    if annotation.reason in UNCERTAIN_ANNOTATION_REASONS:
        return True, _uncertain_reason(axis, annotation.reason), (
            AxisAuditRow(axis, "annotation_reason_uncertain", "annotation.reason"),
        )
    return False, None, tuple(audit)


def _resolve_ref(
    refs: Mapping[str, tuple[Mapping[str, Any], ...]],
    target_ref: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    collection = target_ref.get("collection")
    index = target_ref.get("index")
    if not isinstance(collection, str) or collection not in TARGET_REF_COLLECTIONS:
        return None
    if type(index) is not int or index < 0:
        return None
    rows = refs.get(collection)
    if not isinstance(rows, (tuple, list)) or index >= len(rows):
        return None
    candidate = rows[index]
    if not isinstance(candidate, Mapping):
        return None
    try:
        ref_key(candidate)
    except RescoreError:
        return None
    return candidate


def _target_matches(identity: EntityIdentityView, targets: Sequence[ScopeTarget]) -> bool:
    if not identity.entity_type or not identity.entity_key:
        return False
    for target in targets:
        if target.entity_type != identity.entity_type or target.entity_key != identity.entity_key:
            continue
        if all(
            _scalar_equal(identity.filters.get(str(key)), value)
            for key, value in target.filters.items()
        ):
            return True
    return False


def _shared_background_coverage(
    unit: UnitView,
    entries: Sequence[ScopeSharedBackground],
    plan_filters: Mapping[str, str] | None,
) -> bool | None:
    if not entries:
        return False
    if plan_filters is None:
        return None
    for entry in entries:
        if entry.document_id != unit.document_id or entry.version_id != unit.version_id:
            continue
        if unit.unit_id not in entry.unit_ids:
            continue
        if any(
            not _scalar_equal(plan_filters.get(str(key)), value)
            for key, value in entry.scope_filters.items()
        ):
            continue
        return True
    return False


def _has_structured_entity(view: CrossEntityEvidenceView) -> bool:
    if any(identity.entity_type or identity.entity_key for identity in view.unit_entity.values()):
        return True
    return any(fact.entity_key for fact in view.facts)


def _annotation_targets_match_contract(
    annotation: AxisAnnotation,
    contract: CrossEntityContract,
) -> bool:
    """注解 targets 与 Q1a-2 合同 targets 必须一致；空注解 targets 表示以合同为准。"""
    if not annotation.targets:
        return True
    if not contract.targets:
        # entity_bound 的空 targets 由 mode 判定给出 targets_missing；其它 mode 不允许注解 targets。
        return contract.mode == "entity_bound"
    contract_rows = {
        (
            target.entity_type,
            target.entity_key,
            tuple(sorted((str(key), str(value)) for key, value in target.filters.items())),
        )
        for target in contract.targets
    }
    annotation_rows = {
        (
            str(target.get("entity_type") or ""),
            str(target.get("entity_key") or ""),
            tuple(
                sorted(
                    (str(key), str(value))
                    for key, value in dict(target.get("filters") or {}).items()
                )
            ),
        )
        for target in annotation.targets
    }
    return annotation_rows == contract_rows


def _binding_mismatch(
    contract_bindings: Mapping[str, str],
    evidence_bindings: Mapping[str, str] | None,
) -> tuple[bool, bool]:
    """返回 (missing, mismatch)。"""
    if not contract_bindings or not evidence_bindings:
        return True, False
    for key in BINDING_KEYS:
        if str(contract_bindings.get(key) or "") != str(evidence_bindings.get(key) or ""):
            return False, True
    return False, False


def _contract_audit(axis: str, defects: Sequence[tuple[str, str]]) -> tuple[AxisAuditRow, ...]:
    return tuple(AxisAuditRow(axis, code, detail) for code, detail in defects)


# --------------------------------------------------------------------------- #
# cross_user：owner / context / query state / inheritance / result message
# --------------------------------------------------------------------------- #


def _rescore_cross_user(
    view: AxesCaseView,
    *,
    allow_synthetic_fixture: bool,
) -> tuple[AxisVerdict, tuple[AxisAuditRow, ...]]:
    axis = "cross_user"
    acc = _AxisAccumulator(axis)
    annotation = view.annotations.get(axis)
    blocked, reason, gate_audit = _annotation_gate(
        axis, annotation, allow_synthetic_fixture=allow_synthetic_fixture
    )
    audit: list[AxisAuditRow] = list(gate_audit)
    if blocked:
        acc.unknown(reason or _annotation_unknown_reason(axis), "annotation")
        return acc.verdict(), tuple(audit)
    assert annotation is not None
    if annotation.applicability != "required" or annotation.criterion != "owner_context":
        acc.unknown(_annotation_unknown_reason(axis), "annotation")
        audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "annotation.applicability"))
        return acc.verdict(), tuple(audit)

    evidence = view.cross_user
    if evidence is None or not evidence.projection_available:
        acc.unknown("projection_unavailable", "db_projection")
        audit.append(AxisAuditRow(axis, "projection_unavailable", "db_projection"))
        return acc.verdict(), tuple(audit)

    owner = evidence.owner_user_id
    conversation_id = evidence.conversation_id
    request_id = evidence.request_id
    if not owner or not conversation_id or not request_id:
        acc.unknown("projection_unavailable", "db_projection")
        audit.append(AxisAuditRow(axis, "projection_unavailable", "db_projection"))
        return acc.verdict(), tuple(audit)
    if len(evidence.claims) != 1:
        acc.unknown("claim_missing", "claim_observed")
        audit.append(AxisAuditRow(axis, "claim_missing", "claim_observed"))
        return acc.verdict(), tuple(audit)
    if not evidence.authenticated_user_id:
        acc.unknown("identity_projection_mismatch", "turn.authenticated_user_id")
        audit.append(AxisAuditRow(axis, "identity_missing", "turn.authenticated_user_id"))
        return acc.verdict(), tuple(audit)

    if evidence.authenticated_user_id != owner:
        acc.violation("owner_identity_mismatch", "turn.authenticated_user_id")
        audit.append(AxisAuditRow(axis, "owner_identity_mismatch", "turn.authenticated_user_id"))
    claim = evidence.claims[0]
    if claim.authenticated_user_id != owner:
        acc.violation("owner_identity_mismatch", "claim_observed.authenticated_user_id")
        audit.append(AxisAuditRow(axis, "owner_identity_mismatch", "claim_observed.authenticated_user_id"))
    if claim.owner_user_id != owner:
        acc.violation("owner_identity_mismatch", "claim_observed.owner_user_id")
        audit.append(AxisAuditRow(axis, "owner_identity_mismatch", "claim_observed.owner_user_id"))
    if claim.conversation_id != conversation_id:
        acc.violation("owner_identity_mismatch", "claim_observed.conversation_id")
        audit.append(AxisAuditRow(axis, "owner_identity_mismatch", "claim_observed.conversation_id"))
    if claim.request_id != request_id:
        acc.unknown("identity_projection_mismatch", "claim_observed.request_id")
        audit.append(AxisAuditRow(axis, "identity_projection_mismatch", "claim_observed.request_id"))

    if evidence.request_user_id != owner:
        acc.violation("request_owner_mismatch", "request.user_id")
        audit.append(AxisAuditRow(axis, "request_owner_mismatch", "request.user_id"))
    if evidence.request_conversation_id != conversation_id:
        acc.violation("request_owner_mismatch", "request.conversation_id")
        audit.append(AxisAuditRow(axis, "request_owner_mismatch", "request.conversation_id"))

    if evidence.context_observation_count is None or evidence.context_observation_empty is None:
        acc.unknown("context_evidence_missing", "context_observed")
        audit.append(AxisAuditRow(axis, "context_evidence_missing", "context_observed"))
    else:
        if evidence.context_observation_count != len(evidence.context_messages):
            acc.unknown("context_evidence_missing", "context_observed.count")
            audit.append(AxisAuditRow(axis, "context_evidence_missing", "context_observed.count"))
        if evidence.context_observation_empty != (len(evidence.context_messages) == 0):
            acc.unknown("context_evidence_missing", "context_observed.empty")
            audit.append(AxisAuditRow(axis, "context_evidence_missing", "context_observed.empty"))
        if evidence.context_observation_request_id != request_id:
            acc.unknown("identity_projection_mismatch", "context_observed.request_id")
            audit.append(
                AxisAuditRow(axis, "identity_projection_mismatch", "context_observed.request_id")
            )
    for index, message in enumerate(evidence.context_messages):
        if not message.owner_user_id:
            acc.unknown("context_evidence_missing", f"context_messages[{index}].owner_user_id")
            audit.append(
                AxisAuditRow(axis, "context_evidence_missing", f"context_messages[{index}].owner_user_id")
            )
        elif message.owner_user_id != owner:
            acc.violation("other_user_context", f"context_messages[{index}].owner_user_id")
            audit.append(
                AxisAuditRow(axis, "context_owner_mismatch", f"context_messages[{index}].owner_user_id")
            )
        if not message.request_id or message.request_id != request_id:
            acc.unknown("identity_projection_mismatch", f"context_messages[{index}].request_id")
            audit.append(
                AxisAuditRow(axis, "identity_projection_mismatch", f"context_messages[{index}].request_id")
            )

    if evidence.query_states_available is not True:
        acc.unknown("query_state_unavailable", "db_projection.query_states_available")
        audit.append(
            AxisAuditRow(axis, "query_state_unavailable", "db_projection.query_states_available")
        )
    else:
        for index, row in enumerate(evidence.query_states):
            if not row.stored_user_id:
                acc.unknown("identity_projection_mismatch", f"query_states[{index}].stored_user_id")
                audit.append(
                    AxisAuditRow(axis, "identity_projection_mismatch", f"query_states[{index}].stored_user_id")
                )
            elif row.stored_user_id != owner:
                acc.violation("other_user_query_state", f"query_states[{index}].stored_user_id")
                audit.append(
                    AxisAuditRow(axis, "query_state_owner_mismatch", f"query_states[{index}].stored_user_id")
                )
            if not row.stored_conversation_id:
                acc.unknown(
                    "identity_projection_mismatch", f"query_states[{index}].stored_conversation_id"
                )
                audit.append(
                    AxisAuditRow(
                        axis,
                        "identity_projection_mismatch",
                        f"query_states[{index}].stored_conversation_id",
                    )
                )
            elif row.stored_conversation_id != conversation_id:
                acc.violation(
                    "other_user_query_state", f"query_states[{index}].stored_conversation_id"
                )
                audit.append(
                    AxisAuditRow(
                        axis,
                        "query_state_owner_mismatch",
                        f"query_states[{index}].stored_conversation_id",
                    )
                )

    for index, event in enumerate(evidence.query_state_events):
        label = f"query_state_events[{index}]"
        if not event.user_id:
            acc.unknown("identity_projection_mismatch", f"{label}.user_id")
            audit.append(AxisAuditRow(axis, "identity_projection_mismatch", f"{label}.user_id"))
        elif event.user_id != owner:
            acc.violation("other_user_query_state", f"{label}.user_id")
            audit.append(AxisAuditRow(axis, "query_state_owner_mismatch", f"{label}.user_id"))
        if not event.conversation_id:
            acc.unknown("identity_projection_mismatch", f"{label}.conversation_id")
            audit.append(AxisAuditRow(axis, "identity_projection_mismatch", f"{label}.conversation_id"))
        elif event.conversation_id != conversation_id:
            acc.violation("other_user_query_state", f"{label}.conversation_id")
            audit.append(AxisAuditRow(axis, "query_state_owner_mismatch", f"{label}.conversation_id"))
        if event.kind == "query_state_observed":
            if event.stored_user_id is not None and event.stored_user_id != owner:
                acc.violation("other_user_query_state", f"{label}.stored_user_id")
                audit.append(AxisAuditRow(axis, "query_state_owner_mismatch", f"{label}.stored_user_id"))
            if (
                event.stored_conversation_id is not None
                and event.stored_conversation_id != conversation_id
            ):
                acc.violation("other_user_query_state", f"{label}.stored_conversation_id")
                audit.append(
                    AxisAuditRow(axis, "query_state_owner_mismatch", f"{label}.stored_conversation_id")
                )
            if event.row_present is True and (
                event.stored_user_id is None or event.stored_conversation_id is None
            ):
                acc.unknown("identity_projection_mismatch", f"{label}.row_present")
                audit.append(AxisAuditRow(axis, "identity_projection_mismatch", f"{label}.row_present"))
        else:
            if event.kind == "query_state_saved" and event.state_json_matches is not True:
                acc.unknown("identity_projection_mismatch", f"{label}.state_json")
                audit.append(AxisAuditRow(axis, "identity_projection_mismatch", f"{label}.state_json"))
            if event.kind == "query_state_cleared":
                if event.row_present is None:
                    acc.unknown("identity_projection_mismatch", f"{label}.row_present")
                    audit.append(
                        AxisAuditRow(axis, "identity_projection_mismatch", f"{label}.row_present")
                    )
                elif event.row_present is True and event.state_json_matches is not False:
                    acc.unknown("identity_projection_mismatch", f"{label}.state_json")
                    audit.append(
                        AxisAuditRow(axis, "identity_projection_mismatch", f"{label}.state_json")
                    )

    for index, inheritance in enumerate(evidence.entity_inheritance):
        label = f"entity_inheritance[{index}]"
        if not inheritance.source_message_id:
            acc.unknown("context_evidence_missing", f"{label}.source_message_id")
            audit.append(AxisAuditRow(axis, "context_evidence_missing", f"{label}.source_message_id"))
        if not inheritance.source_owner_user_id:
            acc.unknown("context_evidence_missing", f"{label}.source_owner_user_id")
            audit.append(AxisAuditRow(axis, "context_evidence_missing", f"{label}.source_owner_user_id"))
        elif inheritance.source_owner_user_id != owner:
            acc.violation("other_user_entity_inheritance", f"{label}.source_message_id")
            audit.append(
                AxisAuditRow(axis, "entity_inheritance_owner_mismatch", f"{label}.source_message_id")
            )
        if inheritance.source_role != "assistant":
            acc.unknown("context_evidence_missing", f"{label}.source_role")
            audit.append(AxisAuditRow(axis, "context_evidence_missing", f"{label}.source_role"))

    result = evidence.result_message
    if result is None or not result.result_message_id or not result.owner_user_id:
        acc.unknown("result_message_unavailable", "request.result_message_id")
        audit.append(
            AxisAuditRow(axis, "result_message_unavailable", "request.result_message_id")
        )
    else:
        if result.owner_user_id != owner:
            acc.violation("result_message_owner_mismatch", "messages.result.owner_user_id")
            audit.append(
                AxisAuditRow(axis, "result_message_owner_mismatch", "messages.result.owner_user_id")
            )
        if result.role != "assistant":
            acc.unknown("result_message_unavailable", "messages.result.role")
            audit.append(AxisAuditRow(axis, "result_message_unavailable", "messages.result.role"))

    if not acc.violations and not acc.unknowns:
        audit.append(AxisAuditRow(axis, "owner_identity_checked", "owner_context"))
    return acc.verdict(), tuple(audit)


# --------------------------------------------------------------------------- #
# cross_entity：scope 合同 / targets / shared background / matcher v2
# --------------------------------------------------------------------------- #


def _cross_entity_target_refs(
    annotation: AxisAnnotation,
    contract: CrossEntityContract,
    units: Sequence[UnitView],
    acc: _AxisAccumulator,
    audit: list[AxisAuditRow],
) -> set[str]:
    matched_unit_ids: set[str] = set()
    for index, target_ref in enumerate(annotation.target_refs):
        ref = _resolve_ref(contract.refs, target_ref)
        label = f"target_refs[{index}]"
        if ref is None:
            acc.unknown("targets_unresolved", label)
            audit.append(AxisAuditRow("cross_entity", "target_ref_unresolved", label))
            continue
        binding = contract.version_bindings.get(ref_key(ref))
        found = False
        unresolved = False
        for unit in units:
            result: MatchResult = match_ref_to_unit(ref, unit, version_binding=binding)
            if result.verdict == "match":
                found = True
                matched_unit_ids.add(unit.unit_id)
            elif result.verdict == "unresolved":
                unresolved = True
        if found:
            audit.append(AxisAuditRow("cross_entity", "target_ref_resolved", label))
        elif unresolved:
            acc.unknown("targets_unresolved", label)
            audit.append(AxisAuditRow("cross_entity", "target_ref_unresolved", label))
        else:
            audit.append(AxisAuditRow("cross_entity", "target_ref_no_match", label))
    return matched_unit_ids


def _cross_entity_empty_scope(
    evidence: CrossEntityEvidenceView,
    acc: _AxisAccumulator,
    audit: list[AxisAuditRow],
    *,
    axis: str = "cross_entity",
    na_if_proven: bool = False,
) -> None:
    if evidence.empty_scope_proven is True:
        audit.append(AxisAuditRow(axis, "empty_scope_proven", "use_scope"))
        if na_if_proven:
            acc.na()
        return
    reason = evidence.empty_scope_reason or "empty_set_not_proven"
    acc.unknown(reason, "use_scope")
    audit.append(AxisAuditRow(axis, "empty_scope_not_proven", "use_scope"))


def _cross_entity_entity_bound(
    evidence: CrossEntityEvidenceView,
    contract: CrossEntityContract,
    matched_ref_unit_ids: set[str],
    acc: _AxisAccumulator,
    audit: list[AxisAuditRow],
) -> None:
    if not evidence.units and not evidence.facts:
        _cross_entity_empty_scope(evidence, acc, audit)
        return
    matched = 0
    for index, unit in enumerate(evidence.units):
        identity = evidence.unit_entity.get(unit.unit_id)
        if identity is None or (not identity.entity_type and not identity.entity_key):
            if unit.unit_id in matched_ref_unit_ids:
                matched += 1
                audit.append(AxisAuditRow("cross_entity", "target_matched", f"units[{index}]"))
                continue
            coverage = _shared_background_coverage(
                unit, contract.shared_background, evidence.plan_filters
            )
            if coverage is True:
                matched += 1
                audit.append(
                    AxisAuditRow("cross_entity", "shared_background_matched", f"units[{index}]")
                )
            elif coverage is None:
                acc.unknown("free_text_attribution_unverifiable", f"units[{index}]")
                audit.append(AxisAuditRow("cross_entity", "plan_filters_missing", f"units[{index}]"))
            else:
                acc.unknown("free_text_attribution_unverifiable", f"units[{index}]")
                audit.append(
                    AxisAuditRow("cross_entity", "shared_background_unproven", f"units[{index}]")
                )
            continue
        if not identity.entity_type or not identity.entity_key:
            acc.unknown("entity_identity_unresolved", f"units[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_identity_missing", f"units[{index}]"))
            continue
        if _target_matches(identity, contract.targets):
            matched += 1
            audit.append(AxisAuditRow("cross_entity", "target_matched", f"units[{index}]"))
            continue
        if unit.unit_id in matched_ref_unit_ids:
            acc.unknown("entity_scope_conflict", f"units[{index}]")
            audit.append(AxisAuditRow("cross_entity", "target_ref_conflict", f"units[{index}]"))
            continue
        if "model_evidence" in unit.layers or "direct_rag_fact" in unit.layers:
            acc.violation("other_entity_used", f"units[{index}].entity_key")
            audit.append(AxisAuditRow("cross_entity", "target_mismatch", f"units[{index}]"))
        else:
            acc.violation("citation_entity_mismatch", f"units[{index}].entity_key")
            audit.append(AxisAuditRow("cross_entity", "target_mismatch", f"units[{index}]"))

    for index, fact in enumerate(evidence.facts):
        if not fact.entity_key:
            acc.unknown("entity_identity_unresolved", f"facts[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_identity_missing", f"facts[{index}]"))
            continue
        if not fact.source_unit_id:
            acc.unknown("entity_identity_unresolved", f"facts[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_identity_missing", f"facts[{index}]"))
            continue
        unit = next((item for item in evidence.units if item.unit_id == fact.source_unit_id), None)
        if unit is None:
            acc.unknown("entity_identity_unresolved", f"facts[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_identity_missing", f"facts[{index}]"))
            continue
        identity = evidence.unit_entity.get(unit.unit_id)
        if (
            identity is None
            or not identity.entity_type
            or not identity.entity_key
            or identity.entity_key != fact.entity_key
        ):
            acc.unknown("entity_identity_unresolved", f"facts[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_identity_missing", f"facts[{index}]"))
            continue
        if _target_matches(identity, contract.targets):
            matched += 1
            audit.append(AxisAuditRow("cross_entity", "target_matched", f"facts[{index}]"))
        else:
            acc.violation("other_entity_used", f"facts[{index}].entity_key")
            audit.append(AxisAuditRow("cross_entity", "target_mismatch", f"facts[{index}]"))

    if matched == 0 and not acc.violations and not acc.unknowns:
        acc.unknown("free_text_attribution_unverifiable", "use_scope")


def _cross_entity_shared_background(
    evidence: CrossEntityEvidenceView,
    contract: CrossEntityContract,
    acc: _AxisAccumulator,
    audit: list[AxisAuditRow],
) -> None:
    if not evidence.units and not evidence.facts:
        _cross_entity_empty_scope(evidence, acc, audit)
        return
    for index, unit in enumerate(evidence.units):
        identity = evidence.unit_entity.get(unit.unit_id)
        if identity is not None and (identity.entity_type or identity.entity_key):
            acc.unknown("entity_scope_conflict", f"units[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_scope_conflict", f"units[{index}]"))
            continue
        coverage = _shared_background_coverage(
            unit, contract.shared_background, evidence.plan_filters
        )
        if coverage is True:
            audit.append(AxisAuditRow("cross_entity", "shared_background_matched", f"units[{index}]"))
        elif coverage is None:
            acc.unknown("free_text_attribution_unverifiable", f"units[{index}]")
            audit.append(AxisAuditRow("cross_entity", "plan_filters_missing", f"units[{index}]"))
        else:
            acc.unknown("free_text_attribution_unverifiable", f"units[{index}]")
            audit.append(AxisAuditRow("cross_entity", "shared_background_unproven", f"units[{index}]"))
    for index, fact in enumerate(evidence.facts):
        if fact.entity_key:
            acc.unknown("entity_scope_conflict", f"facts[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_scope_conflict", f"facts[{index}]"))
        else:
            acc.unknown("entity_identity_unresolved", f"facts[{index}]")
            audit.append(AxisAuditRow("cross_entity", "entity_identity_missing", f"facts[{index}]"))


def _rescore_cross_entity(
    view: AxesCaseView,
    *,
    allow_synthetic_fixture: bool,
) -> tuple[AxisVerdict, tuple[AxisAuditRow, ...]]:
    axis = "cross_entity"
    acc = _AxisAccumulator(axis)
    annotation = view.annotations.get(axis)
    blocked, reason, gate_audit = _annotation_gate(
        axis, annotation, allow_synthetic_fixture=allow_synthetic_fixture
    )
    audit: list[AxisAuditRow] = list(gate_audit)
    if blocked:
        acc.unknown(reason or _annotation_unknown_reason(axis), "annotation")
        return acc.verdict(), tuple(audit)
    assert annotation is not None
    if annotation.applicability == "not_applicable":
        if annotation.criterion != "no_entity_claim" or annotation.reason != "no_entity_scope":
            acc.unknown("annotation_unknown", "annotation")
            audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "annotation.applicability"))
            return acc.verdict(), tuple(audit)
    elif annotation.applicability == "required":
        if annotation.criterion not in ("structured_target", "multi_target", "shared_background"):
            acc.unknown("annotation_unknown", "annotation")
            audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "annotation.criterion"))
            return acc.verdict(), tuple(audit)
    else:
        acc.unknown("annotation_unknown", "annotation")
        audit.append(AxisAuditRow(axis, "annotation_unknown_scope", "annotation.applicability"))
        return acc.verdict(), tuple(audit)

    contract = view.cross_entity_contract
    if contract is None:
        acc.unknown("targets_unresolved", "contract")
        audit.append(AxisAuditRow(axis, "contract_missing", "contract"))
        return acc.verdict(), tuple(audit)
    if contract.defects:
        acc.unknown("targets_unresolved", "contract")
        audit.extend(_contract_audit(axis, contract.defects))
        return acc.verdict(), tuple(audit)
    if contract.case_id is not None and contract.case_id != view.case_id:
        acc.unknown("targets_unresolved", "contract.case_id")
        audit.append(AxisAuditRow(axis, "contract_case_mismatch", "contract.case_id"))
        return acc.verdict(), tuple(audit)

    evidence = view.cross_entity
    if evidence is None:
        acc.unknown("evidence_incomplete", "evidence")
        audit.append(AxisAuditRow(axis, "evidence_view_missing", "evidence"))
        return acc.verdict(), tuple(audit)

    missing, mismatch = _binding_mismatch(contract.bindings, evidence.bindings)
    if missing:
        acc.unknown("targets_unresolved", "scope_contract.bindings")
        audit.append(AxisAuditRow(axis, "contract_binding_missing", "scope_contract.bindings"))
        return acc.verdict(), tuple(audit)
    if mismatch:
        acc.unknown("targets_unresolved", "scope_contract.bindings")
        audit.append(AxisAuditRow(axis, "contract_binding_mismatch", "scope_contract.bindings"))
        return acc.verdict(), tuple(audit)
    if contract.mode not in SCOPE_MODES:
        acc.unknown("targets_unresolved", "contract.mode")
        audit.append(AxisAuditRow(axis, "contract_mode_invalid", "contract.mode"))
        return acc.verdict(), tuple(audit)
    if not _annotation_targets_match_contract(annotation, contract):
        acc.unknown("targets_unresolved", "annotation.targets")
        audit.append(AxisAuditRow(axis, "annotation_targets_mismatch", "annotation.targets"))
        return acc.verdict(), tuple(audit)

    matched_ref_unit_ids = _cross_entity_target_refs(annotation, contract, evidence.units, acc, audit)

    if annotation.applicability == "not_applicable":
        if contract.mode != "no_entity_scope":
            acc.unknown("entity_scope_conflict", "contract.mode")
            audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "contract.mode"))
            return acc.verdict(), tuple(audit)
        if _has_structured_entity(evidence):
            acc.unknown("entity_scope_conflict", "use_scope")
            audit.append(AxisAuditRow(axis, "entity_scope_conflict", "use_scope"))
            return acc.verdict(), tuple(audit)
        if not evidence.units and not evidence.facts:
            _cross_entity_empty_scope(evidence, acc, audit, na_if_proven=True)
        else:
            acc.na()
        return acc.verdict(), tuple(audit)

    if contract.mode == "no_entity_scope":
        if _has_structured_entity(evidence):
            acc.unknown("entity_scope_conflict", "use_scope")
            audit.append(AxisAuditRow(axis, "entity_scope_conflict", "use_scope"))
        else:
            acc.unknown("entity_scope_conflict", "contract.mode")
            audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "contract.mode"))
        return acc.verdict(), tuple(audit)

    if contract.mode == "shared_background_only":
        if annotation.criterion != "shared_background":
            acc.unknown("annotation_unknown", "annotation.criterion")
            audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "annotation.criterion"))
            return acc.verdict(), tuple(audit)
        _cross_entity_shared_background(evidence, contract, acc, audit)
        return acc.verdict(), tuple(audit)

    # entity_bound
    if annotation.criterion == "shared_background":
        acc.unknown("annotation_unknown", "annotation.criterion")
        audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "annotation.criterion"))
        return acc.verdict(), tuple(audit)
    if annotation.criterion == "multi_target" and len(contract.targets) < 2:
        acc.unknown("targets_unresolved", "contract.targets")
        audit.append(AxisAuditRow(axis, "targets_incomplete", "contract.targets"))
        return acc.verdict(), tuple(audit)
    if not contract.targets:
        acc.unknown("targets_unresolved", "contract.targets")
        audit.append(AxisAuditRow(axis, "targets_missing", "contract.targets"))
        return acc.verdict(), tuple(audit)
    if any(not target.entity_type or not target.entity_key for target in contract.targets):
        acc.unknown("targets_unresolved", "contract.targets")
        audit.append(AxisAuditRow(axis, "targets_incomplete", "contract.targets"))
        return acc.verdict(), tuple(audit)
    _cross_entity_entity_bound(evidence, contract, matched_ref_unit_ids, acc, audit)
    return acc.verdict(), tuple(audit)


# --------------------------------------------------------------------------- #
# stale_source：lifecycle / version / date
# --------------------------------------------------------------------------- #


def _stale_source_refs(
    annotation: AxisAnnotation,
    contract: StaleSourceContract,
    acc: _AxisAccumulator,
    audit: list[AxisAuditRow],
) -> list[tuple[str, Mapping[str, Any]]]:
    refs: list[tuple[str, Mapping[str, Any]]] = [
        (f"constrained_refs[{index}]", ref)
        for index, ref in enumerate(contract.constrained_refs)
    ]
    for index, target_ref in enumerate(annotation.target_refs):
        label = f"target_refs[{index}]"
        ref = _resolve_ref(contract.refs, target_ref)
        if ref is None:
            acc.unknown("source_unresolved", label)
            audit.append(AxisAuditRow("stale_source", "target_ref_unresolved", label))
            continue
        refs.append((label, ref))
    return refs


def _rescore_stale_source(
    view: AxesCaseView,
    *,
    allow_synthetic_fixture: bool,
) -> tuple[AxisVerdict, tuple[AxisAuditRow, ...]]:
    axis = "stale_source"
    acc = _AxisAccumulator(axis)
    annotation = view.annotations.get(axis)
    blocked, reason, gate_audit = _annotation_gate(
        axis, annotation, allow_synthetic_fixture=allow_synthetic_fixture
    )
    audit: list[AxisAuditRow] = list(gate_audit)
    if blocked:
        acc.unknown(reason or _annotation_unknown_reason(axis), "annotation")
        return acc.verdict(), tuple(audit)
    assert annotation is not None
    if annotation.applicability != "required" or annotation.criterion != "lifecycle_dates":
        acc.unknown("annotation_unknown", "annotation")
        audit.append(AxisAuditRow(axis, "scope_mode_mismatch", "annotation.applicability"))
        return acc.verdict(), tuple(audit)

    contract = view.stale_source_contract
    if contract is None:
        acc.unknown("source_unresolved", "contract")
        audit.append(AxisAuditRow(axis, "contract_missing", "contract"))
        return acc.verdict(), tuple(audit)
    if contract.defects:
        acc.unknown("source_unresolved", "contract")
        audit.extend(_contract_audit(axis, contract.defects))
        return acc.verdict(), tuple(audit)
    if contract.case_id is not None and contract.case_id != view.case_id:
        acc.unknown("source_unresolved", "contract.case_id")
        audit.append(AxisAuditRow(axis, "contract_case_mismatch", "contract.case_id"))
        return acc.verdict(), tuple(audit)

    evidence = view.stale_source
    if evidence is None:
        acc.unknown("lifecycle_unavailable", "evidence")
        audit.append(AxisAuditRow(axis, "evidence_view_missing", "evidence"))
        return acc.verdict(), tuple(audit)

    missing, mismatch = _binding_mismatch(contract.bindings, evidence.bindings)
    if missing:
        acc.unknown("source_unresolved", "scope_contract.bindings")
        audit.append(AxisAuditRow(axis, "contract_binding_missing", "scope_contract.bindings"))
        return acc.verdict(), tuple(audit)
    if mismatch:
        acc.unknown("source_unresolved", "scope_contract.bindings")
        audit.append(AxisAuditRow(axis, "contract_binding_mismatch", "scope_contract.bindings"))
        return acc.verdict(), tuple(audit)

    if not evidence.units:
        _cross_entity_empty_scope(evidence, acc, audit, axis=axis)
        return acc.verdict(), tuple(audit)

    for label, ref in _stale_source_refs(annotation, contract, acc, audit):
        binding = contract.version_bindings.get(ref_key(ref))
        if binding is None or binding.basis == "unresolved":
            acc.unknown("source_unresolved", label)
            audit.append(AxisAuditRow(axis, "version_binding_missing", label))
            continue
        for unit in evidence.units:
            result: MatchResult = match_ref_to_unit(ref, unit, version_binding=binding)
            if result.verdict == "match":
                audit.append(AxisAuditRow(axis, "version_match", label))
            elif result.verdict == "no_match" and result.code == "version_mismatch":
                acc.violation("citation_version_mismatch", label)
                audit.append(AxisAuditRow(axis, "version_mismatch", label))
            elif result.verdict == "unresolved":
                acc.unknown("source_unresolved", label)

    dated: list[tuple[int, str | None, str | None]] = []
    for index, unit in enumerate(evidence.units):
        lifecycle = evidence.lifecycle.get(unit.unit_id)
        if lifecycle is None:
            acc.unknown("lifecycle_unavailable", f"units[{index}]")
            audit.append(AxisAuditRow(axis, "lifecycle_unavailable", f"units[{index}]"))
            continue

        if lifecycle.document_deleted is True:
            acc.violation("source_deleted", f"units[{index}].document_deleted")
            audit.append(AxisAuditRow(axis, "source_deleted", f"units[{index}].document_deleted"))
        elif lifecycle.document_deleted is None:
            acc.unknown("lifecycle_unavailable", f"units[{index}].document_deleted")
            audit.append(
                AxisAuditRow(axis, "lifecycle_unavailable", f"units[{index}].document_deleted")
            )

        if lifecycle.version_state == "published":
            pass
        elif lifecycle.version_state == "not_published":
            acc.violation("source_not_published", f"units[{index}].version_state")
            audit.append(
                AxisAuditRow(axis, "source_not_published", f"units[{index}].version_state")
            )
        else:
            acc.unknown("lifecycle_unavailable", f"units[{index}].version_state")
            audit.append(
                AxisAuditRow(axis, "lifecycle_unavailable", f"units[{index}].version_state")
            )

        if lifecycle.active is False:
            acc.violation("source_not_active", f"units[{index}].active")
            audit.append(AxisAuditRow(axis, "source_not_active", f"units[{index}].active"))
        elif lifecycle.active is None:
            acc.unknown("lifecycle_unavailable", f"units[{index}].active")
            audit.append(AxisAuditRow(axis, "lifecycle_unavailable", f"units[{index}].active"))
        elif unit.version_id is None or lifecycle.active_version_id is None:
            acc.unknown("source_unresolved", f"units[{index}].version_id")
            audit.append(AxisAuditRow(axis, "version_binding_missing", f"units[{index}].version_id"))
        elif lifecycle.active_version_id != unit.version_id:
            acc.violation("source_not_active", f"units[{index}].active_version_id")
            audit.append(
                AxisAuditRow(axis, "source_not_active", f"units[{index}].active_version_id")
            )

        if lifecycle.date_state == "ambiguous":
            acc.unknown("date_unresolved", f"units[{index}].raw_fields")
            audit.append(AxisAuditRow(axis, "date_unresolved", f"units[{index}].raw_fields"))
        elif lifecycle.date_state == "unavailable":
            acc.unknown("lifecycle_unavailable", f"units[{index}].raw_fields")
            audit.append(AxisAuditRow(axis, "lifecycle_unavailable", f"units[{index}].raw_fields"))
        elif lifecycle.date_state == "range":
            if lifecycle.effective_from is None and lifecycle.effective_to is None:
                acc.unknown("date_unresolved", f"units[{index}].raw_fields")
                audit.append(AxisAuditRow(axis, "date_unresolved", f"units[{index}].raw_fields"))
            else:
                dated.append((index, lifecycle.effective_from, lifecycle.effective_to))

        if "final_citation" in unit.layers:
            if (
                lifecycle.citation_source_document_id is None
                or lifecycle.citation_source_version_id is None
            ):
                acc.unknown("citation_source_unresolved", f"units[{index}].message_sources")
                audit.append(
                    AxisAuditRow(axis, "citation_source_unresolved", f"units[{index}].message_sources")
                )
            elif unit.document_id is None or unit.version_id is None:
                acc.unknown("source_unresolved", f"units[{index}].version_id")
                audit.append(AxisAuditRow(axis, "version_binding_missing", f"units[{index}].version_id"))
            elif (
                lifecycle.citation_source_document_id != unit.document_id
                or lifecycle.citation_source_version_id != unit.version_id
            ):
                acc.violation("citation_version_mismatch", f"units[{index}].message_sources")
                audit.append(
                    AxisAuditRow(axis, "version_mismatch", f"units[{index}].message_sources")
                )

    if dated:
        actual = _iso_date(evidence.actual_as_of)
        if actual is None:
            acc.unknown("as_of_missing", "plan_observed.as_of")
            audit.append(AxisAuditRow(axis, "as_of_missing", "plan_observed.as_of"))
        else:
            frozen = _iso_date(annotation.as_of)
            if frozen is not None and frozen != actual:
                acc.violation("date_intent_conflict", "plan_observed.as_of")
                audit.append(AxisAuditRow(axis, "date_conflict", "plan_observed.as_of"))
            for index, start, end in dated:
                start_date = _iso_date(start) if start is not None else None
                end_date = _iso_date(end) if end is not None else None
                if (start is not None and start_date is None) or (end is not None and end_date is None):
                    acc.unknown("date_unresolved", f"units[{index}].raw_fields")
                    audit.append(AxisAuditRow(axis, "date_unresolved", f"units[{index}].raw_fields"))
                    continue
                if start_date is not None and actual < start_date:
                    if annotation.temporal_intent == "future_explicit":
                        if evidence.include_future is True:
                            pass
                        elif evidence.include_future is False:
                            acc.violation(
                                "future_source_as_current", f"units[{index}].raw_fields"
                            )
                            audit.append(
                                AxisAuditRow(
                                    axis, "future_source_as_current", f"units[{index}].raw_fields"
                                )
                            )
                        else:
                            acc.unknown("annotation_unknown", f"units[{index}].include_future")
                            audit.append(
                                AxisAuditRow(
                                    axis, "include_future_missing", f"units[{index}].include_future"
                                )
                            )
                    else:
                        acc.violation("future_source_as_current", f"units[{index}].raw_fields")
                        audit.append(
                            AxisAuditRow(
                                axis, "future_source_as_current", f"units[{index}].raw_fields"
                            )
                        )
                if end_date is not None and actual > end_date:
                    acc.violation("source_expired", f"units[{index}].raw_fields")
                    audit.append(AxisAuditRow(axis, "source_expired", f"units[{index}].raw_fields"))

    if not acc.violations and not acc.unknowns:
        audit.append(AxisAuditRow(axis, "lifecycle_checked", "lifecycle"))
    return acc.verdict(), tuple(audit)


# --------------------------------------------------------------------------- #
# 旧 verdict 保留 / 覆盖 / unknown→N/A 阻断
# --------------------------------------------------------------------------- #


def _preserved_old_verdict(
    old: OldCardCase,
    axis: str,
) -> tuple[AxisVerdict | None, tuple[AxisAuditRow, ...], str]:
    axis_old = old.axes[axis]
    if str(axis_old["state"]) == "violation":
        gates = GATE_CODES.intersection(old.missing_codes)
        if gates:
            reason = str(axis_old["reason"])
            return (
                AxisVerdict(axis, "violation", reason, (f"old_card.{axis}",), ()),
                (
                    AxisAuditRow(axis, "old_verdict_preserved", "frozen_gate"),
                    AxisAuditRow(axis, "preserved_gate", sorted(gates)[0]),
                ),
                "preserved_old_verdict",
            )
    return None, (), ""


def _apply_overrides(
    axis: str,
    verdict: AxisVerdict,
    old: OldCardCase,
    audit: tuple[AxisAuditRow, ...],
) -> tuple[AxisVerdict, tuple[AxisAuditRow, ...], str]:
    rows = list(audit)
    if old.quality_status in ("error", "not_executed") and verdict.state != "violation":
        reason = "turn_error" if old.quality_status == "error" else "turn_not_executed"
        verdict = AxisVerdict(
            axis,
            "unknown",
            reason,
            verdict.evidence,
            tuple(sorted(set(verdict.missing) | {reason})),
        )
        rows.append(AxisAuditRow(axis, "quality_error_override", reason))
    if not old.evidence_complete and verdict.state in ("passed", "not_applicable"):
        verdict = AxisVerdict(
            axis,
            "unknown",
            "evidence_incomplete",
            verdict.evidence,
            tuple(sorted(set(verdict.missing) | {"evidence_incomplete"})),
        )
        rows.append(AxisAuditRow(axis, "evidence_incomplete_override", "evidence_complete=false"))
    old_state = str(old.axes[axis]["state"])
    if old_state == "unknown" and verdict.state == "not_applicable":
        old_reason = str(old.axes[axis]["reason"])
        verdict = AxisVerdict(axis, "unknown", old_reason, (f"old_card.{axis}",), (old_reason,))
        rows.append(AxisAuditRow(axis, "unknown_to_na_blocked", "old_unknown"))
        return verdict, tuple(rows), "preserved_old_verdict"
    return verdict, tuple(rows), "rescored"


def _rescore_axis(
    view: AxesCaseView,
    axis: str,
    *,
    allow_synthetic_fixture: bool,
) -> tuple[AxisVerdict, tuple[AxisAuditRow, ...], str]:
    preserved, preserve_audit, provenance = _preserved_old_verdict(view.old, axis)
    if preserved is not None:
        return preserved, preserve_audit, provenance
    if axis == "cross_user":
        verdict, audit = _rescore_cross_user(
            view, allow_synthetic_fixture=allow_synthetic_fixture
        )
    elif axis == "cross_entity":
        verdict, audit = _rescore_cross_entity(
            view, allow_synthetic_fixture=allow_synthetic_fixture
        )
    else:
        verdict, audit = _rescore_stale_source(
            view, allow_synthetic_fixture=allow_synthetic_fixture
        )
    return _apply_overrides(axis, verdict, view.old, audit)


# --------------------------------------------------------------------------- #
# 单案结果
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AxesCaseResult:
    case_id: str
    stratum: str
    quality_status: str
    old_axes: Mapping[str, Mapping[str, str]]
    new_axes: Mapping[str, Mapping[str, str]]
    axis_provenance: Mapping[str, str]
    axis_basis: Mapping[str, str]
    axis_audit: Mapping[str, tuple[AxisAuditRow, ...]]
    changed_axes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.case_id, str) and bool(self.case_id), "case_invalid")
        _require(isinstance(self.old_axes, Mapping) and set(self.old_axes) == set(AXES), "case_invalid")
        _require(isinstance(self.new_axes, Mapping) and set(self.new_axes) == set(AXES), "case_invalid")
        _require(isinstance(self.axis_provenance, Mapping), "case_invalid")
        _require(set(self.axis_provenance) == set(AXES), "case_invalid")
        _require(isinstance(self.axis_basis, Mapping) and set(self.axis_basis) == set(AXES), "case_invalid")
        _require(isinstance(self.axis_audit, Mapping) and set(self.axis_audit) == set(AXES), "case_invalid")
        _require(isinstance(self.changed_axes, tuple), "case_invalid")

    @property
    def changed(self) -> bool:
        return bool(self.changed_axes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "stratum": self.stratum,
            "quality_status": self.quality_status,
            "old_axes": {name: dict(self.old_axes[name]) for name in AXES},
            "new_axes": {name: dict(self.new_axes[name]) for name in AXES},
            "axis_provenance": {name: self.axis_provenance[name] for name in AXES},
            "axis_basis": {name: self.axis_basis[name] for name in AXES},
            "axis_audit": {
                name: [
                    {"axis": row.axis, "code": row.code, "detail": row.detail}
                    for row in self.axis_audit[name]
                ]
                for name in AXES
            },
            "changed_axes": list(self.changed_axes),
        }


def rescore_axes_case(
    view: AxesCaseView,
    *,
    allow_synthetic_fixture: bool = False,
) -> AxesCaseResult:
    _require(isinstance(view, AxesCaseView), "case_invalid")
    old_axes = {name: {"state": str(view.old.axes[name]["state"]), "reason": str(view.old.axes[name]["reason"])} for name in AXES}
    new_axes: dict[str, dict[str, str]] = {}
    provenance: dict[str, str] = {}
    basis: dict[str, str] = {}
    audit: dict[str, tuple[AxisAuditRow, ...]] = {}
    for axis in AXES:
        if axis == "safety":
            new_axes[axis] = {
                "state": old_axes[axis]["state"],
                "reason": old_axes[axis]["reason"],
                "provenance": "recorded_old",
            }
            provenance[axis] = "recorded_old"
            basis[axis] = "recorded_old"
            audit[axis] = ()
            continue
        annotation = view.annotations.get(axis)
        basis[axis] = annotation.basis if annotation is not None else "missing"
        verdict, rows, axis_provenance = _rescore_axis(
            view, axis, allow_synthetic_fixture=allow_synthetic_fixture
        )
        new_axes[axis] = {
            "state": verdict.state,
            "reason": verdict.reason,
            "provenance": axis_provenance,
        }
        provenance[axis] = axis_provenance
        audit[axis] = rows
    changed_axes = tuple(
        axis
        for axis in RESCORED_AXES
        if (new_axes[axis]["state"], new_axes[axis]["reason"])
        != (old_axes[axis]["state"], old_axes[axis]["reason"])
    )
    return AxesCaseResult(
        case_id=view.case_id,
        stratum=view.old.stratum,
        quality_status=view.old.quality_status,
        old_axes=MappingProxyType({name: MappingProxyType(old_axes[name]) for name in AXES}),
        new_axes=MappingProxyType({name: MappingProxyType(new_axes[name]) for name in AXES}),
        axis_provenance=MappingProxyType(provenance),
        axis_basis=MappingProxyType(basis),
        axis_audit=MappingProxyType(audit),
        changed_axes=changed_axes,
    )


# --------------------------------------------------------------------------- #
# 新分析身份与聚合
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AxesIdentity:
    """Q1a-1b 身份：复用 Q1a-1 `RescoreIdentity`，另绑 v0.1 基线契约。"""

    base: RescoreIdentity
    base_contract_sha256: str

    def __post_init__(self) -> None:
        _require(isinstance(self.base, RescoreIdentity), "analysis_identity_invalid")
        _require(self.base.analysis_id == ANALYSIS_ID, "analysis_identity_invalid")
        _hash_text(self.base_contract_sha256, "analysis_identity_invalid")


def _axis_counts(cases: Sequence[AxesCaseResult], axis: str, *, selector: str) -> dict[str, int]:
    counts = {"planned": len(cases), "passed": 0, "not_applicable": 0, "unknown": 0, "violations": 0}
    for case in cases:
        axes = case.old_axes if selector == "old" else case.new_axes
        state = str(axes[axis]["state"])
        key = "violations" if state == "violation" else state
        counts[key] += 1
    counts["checked"] = counts["passed"] + counts["not_applicable"] + counts["violations"]
    return counts


def _axis_reason_counts(cases: Sequence[AxesCaseResult], axis: str) -> dict[str, int]:
    counter: dict[str, int] = {}
    for case in cases:
        if str(case.new_axes[axis]["state"]) == "violation":
            reason = str(case.new_axes[axis]["reason"])
            counter[reason] = counter.get(reason, 0) + 1
    return {reason: counter[reason] for reason in sorted(counter)}


@dataclass(frozen=True)
class AxesRescoreReport:
    schema_version: str
    analysis_id: str
    evaluator_phase: str
    matcher_version: str
    scope_versions: Mapping[str, str]
    contract_sha256: str
    base_contract_sha256: str
    evaluator_sha256: str
    analysis_identity_sha256: str
    old_run_id: str
    old_binding_sha256: str
    old_binding_canonical_sha256: str
    old_binding_bytes_verified: bool | None
    old_evidence_tree_sha256: str
    old_card_sha256: str
    old_card_bytes_verified: bool | None
    axes: Mapping[str, Mapping[str, int]]
    old_axes: Mapping[str, Mapping[str, int]]
    axes_provenance: Mapping[str, str]
    axes_provenance_counts: Mapping[str, Mapping[str, int]]
    axes_basis_counts: Mapping[str, Mapping[str, int]]
    violation_reasons: Mapping[str, Mapping[str, int]]
    hard_failures: tuple[str, ...]
    old_hard_failures: tuple[str, ...]
    missing_evidence_cases: tuple[str, ...]
    changed_cases: tuple[Mapping[str, Any], ...]
    unchanged_case_count: int
    synthetic_fixture_allowed: bool
    calls: Mapping[str, int]
    not_claimed: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "analysis_id": self.analysis_id,
            "evaluator_phase": self.evaluator_phase,
            "matcher_version": self.matcher_version,
            "scope_versions": dict(self.scope_versions),
            "contract_sha256": self.contract_sha256,
            "base_contract_sha256": self.base_contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "analysis_identity_sha256": self.analysis_identity_sha256,
            "old_run_id": self.old_run_id,
            "old_binding_sha256": self.old_binding_sha256,
            "old_binding_canonical_sha256": self.old_binding_canonical_sha256,
            "old_binding_bytes_verified": self.old_binding_bytes_verified,
            "old_evidence_tree_sha256": self.old_evidence_tree_sha256,
            "old_card_sha256": self.old_card_sha256,
            "old_card_bytes_verified": self.old_card_bytes_verified,
            "axes": {name: dict(self.axes[name]) for name in AXES},
            "old_axes": {name: dict(self.old_axes[name]) for name in AXES},
            "axes_provenance": dict(self.axes_provenance),
            "axes_provenance_counts": {
                name: dict(self.axes_provenance_counts[name]) for name in AXES
            },
            "axes_basis_counts": {
                name: dict(self.axes_basis_counts[name]) for name in AXES
            },
            "violation_reasons": {name: dict(self.violation_reasons[name]) for name in AXES},
            "hard_failures": list(self.hard_failures),
            "old_hard_failures": list(self.old_hard_failures),
            "missing_evidence_cases": list(self.missing_evidence_cases),
            "changed_cases": [dict(item) for item in self.changed_cases],
            "unchanged_case_count": int(self.unchanged_case_count),
            "synthetic_fixture_allowed": bool(self.synthetic_fixture_allowed),
            "calls": dict(self.calls),
            "not_claimed": list(self.not_claimed),
        }

    def public_summary(self) -> dict[str, Any]:
        """不含逐题 case_id/audit 的公开聚合；真实数据对外只可用它。"""
        return {
            "schema_version": self.schema_version,
            "analysis_id": self.analysis_id,
            "evaluator_phase": self.evaluator_phase,
            "matcher_version": self.matcher_version,
            "scope_versions": dict(self.scope_versions),
            "contract_sha256": self.contract_sha256,
            "base_contract_sha256": self.base_contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "analysis_identity_sha256": self.analysis_identity_sha256,
            "old_run_id": self.old_run_id,
            "old_binding_sha256": self.old_binding_sha256,
            "old_evidence_tree_sha256": self.old_evidence_tree_sha256,
            "old_card_sha256": self.old_card_sha256,
            "axes": {name: dict(self.axes[name]) for name in AXES},
            "old_axes": {name: dict(self.old_axes[name]) for name in AXES},
            "axes_provenance": dict(self.axes_provenance),
            "axes_provenance_counts": {
                name: dict(self.axes_provenance_counts[name]) for name in AXES
            },
            "axes_basis_counts": {
                name: dict(self.axes_basis_counts[name]) for name in AXES
            },
            "violation_reasons": {name: dict(self.violation_reasons[name]) for name in AXES},
            "hard_failure_count": len(self.hard_failures),
            "old_hard_failure_count": len(self.old_hard_failures),
            "missing_evidence_case_count": len(self.missing_evidence_cases),
            "changed_case_count": len({item["case_id"] for item in self.changed_cases}),
            "unchanged_case_count": int(self.unchanged_case_count),
            "synthetic_fixture_allowed": bool(self.synthetic_fixture_allowed),
            "calls": dict(self.calls),
            "not_claimed": list(self.not_claimed),
        }


def _load_contract_sha(path: Path | str, code: str) -> str:
    target = Path(path)
    _require(target.is_file(), code)
    return file_sha256(target)


def rescore_axes_run(
    *,
    identity: AxesIdentity,
    cases: Sequence[AxesCaseView],
    contract_path: Path | str | None = None,
    base_contract_path: Path | str | None = None,
    allow_synthetic_fixture: bool = False,
) -> AxesRescoreReport:
    """三轴重评聚合：safety 仍 recorded_old；三轴 rescored；不产出通过/发布结论。"""
    _require(isinstance(identity, AxesIdentity), "analysis_identity_invalid")
    _require(
        isinstance(cases, Sequence) and not isinstance(cases, (str, bytes)) and bool(cases),
        "cases_empty",
    )
    _require(all(isinstance(view, AxesCaseView) for view in cases), "case_invalid")
    ids = [view.case_id for view in cases]
    _require(len(ids) == len(set(ids)), "case_duplicate")
    _require(isinstance(allow_synthetic_fixture, bool), "synthetic_guard_invalid")

    target_contract = DEFAULT_CONTRACT_PATH if contract_path is None else Path(contract_path)
    target_base = BASE_CONTRACT_PATH if base_contract_path is None else Path(base_contract_path)
    contract_sha = _load_contract_sha(target_contract, "contract_missing")
    base_sha = _load_contract_sha(target_base, "base_contract_missing")
    evaluator_sha = file_sha256(Path(__file__))
    _require(contract_sha == identity.base.contract_sha256, "contract_hash_mismatch")
    _require(base_sha == identity.base_contract_sha256, "base_contract_hash_mismatch")
    _require(evaluator_sha == identity.base.evaluator_sha256, "evaluator_hash_mismatch")

    old_binding_canonical = _sha256_bytes(canonical_json_bytes(dict(identity.base.old_binding)))
    binding_verified: bool | None = None
    if identity.base.old_binding_bytes is not None:
        binding_verified = _sha256_bytes(identity.base.old_binding_bytes) == identity.base.old_binding_sha256
        _require(binding_verified, "old_binding_hash_mismatch")
    card_verified: bool | None = None
    if identity.base.old_card_bytes is not None:
        card_verified = _sha256_bytes(identity.base.old_card_bytes) == identity.base.old_card_sha256
        _require(card_verified, "old_card_hash_mismatch")

    results = [
        rescore_axes_case(view, allow_synthetic_fixture=allow_synthetic_fixture) for view in cases
    ]
    axes = {axis: _axis_counts(results, axis, selector="new") for axis in AXES}
    old_axes = {axis: _axis_counts(results, axis, selector="old") for axis in AXES}
    provenance = {axis: ("recorded_old" if axis == "safety" else "rescored") for axis in AXES}
    provenance_counts: dict[str, dict[str, int]] = {}
    basis_counts: dict[str, dict[str, int]] = {}
    for axis in AXES:
        counts: dict[str, int] = {}
        basis_values: dict[str, int] = {}
        for case in results:
            value = str(case.axis_provenance[axis])
            counts[value] = counts.get(value, 0) + 1
            basis_value = str(case.axis_basis[axis])
            basis_values[basis_value] = basis_values.get(basis_value, 0) + 1
        provenance_counts[axis] = {key: counts[key] for key in sorted(counts)}
        basis_counts[axis] = {key: basis_values[key] for key in sorted(basis_values)}
    violation_reasons = {axis: _axis_reason_counts(results, axis) for axis in AXES}
    hard_failures = tuple(
        sorted(
            case.case_id
            for case in results
            if any(str(case.new_axes[axis]["state"]) == "violation" for axis in AXES)
        )
    )
    old_hard_failures = tuple(
        sorted(
            case.case_id
            for case in results
            if any(str(case.old_axes[axis]["state"]) == "violation" for axis in AXES)
        )
    )
    missing_cases = tuple(
        sorted(
            case.case_id
            for case in results
            if any(str(case.new_axes[axis]["state"]) == "unknown" for axis in AXES)
        )
    )
    changed: list[Mapping[str, Any]] = []
    for case in results:
        for axis in RESCORED_AXES:
            if axis not in case.changed_axes:
                continue
            changed.append(
                {
                    "case_id": case.case_id,
                    "axis": axis,
                    "from": {
                        "state": str(case.old_axes[axis]["state"]),
                        "reason": str(case.old_axes[axis]["reason"]),
                    },
                    "to": {
                        "state": str(case.new_axes[axis]["state"]),
                        "reason": str(case.new_axes[axis]["reason"]),
                    },
                    "provenance": case.axis_provenance[axis],
                    "basis": case.axis_basis[axis],
                    "audit_codes": sorted({row.code for row in case.axis_audit[axis]}),
                }
            )
    changed_cases = tuple(changed)
    unchanged_case_count = len(results) - len({item["case_id"] for item in changed_cases})

    identity_payload = {
        "analysis_id": identity.base.analysis_id,
        "evaluator_phase": EVALUATOR_PHASE,
        "matcher_version": MATCHER_VERSION,
        "scope_versions": dict(AXES_SCOPE_VERSIONS),
        "contract_sha256": contract_sha,
        "base_contract_sha256": base_sha,
        "evaluator_sha256": evaluator_sha,
        "old_run_id": identity.base.old_run_id,
        "old_binding_sha256": identity.base.old_binding_sha256,
        "old_evidence_tree_sha256": identity.base.old_evidence_tree_sha256,
        "old_card_sha256": identity.base.old_card_sha256,
    }
    return AxesRescoreReport(
        schema_version=RESCORE_AXES_REPORT_SCHEMA_VERSION,
        analysis_id=identity.base.analysis_id,
        evaluator_phase=EVALUATOR_PHASE,
        matcher_version=MATCHER_VERSION,
        scope_versions=AXES_SCOPE_VERSIONS,
        contract_sha256=contract_sha,
        base_contract_sha256=base_sha,
        evaluator_sha256=evaluator_sha,
        analysis_identity_sha256=_sha256_bytes(canonical_json_bytes(identity_payload)),
        old_run_id=identity.base.old_run_id,
        old_binding_sha256=identity.base.old_binding_sha256,
        old_binding_canonical_sha256=old_binding_canonical,
        old_binding_bytes_verified=binding_verified,
        old_evidence_tree_sha256=identity.base.old_evidence_tree_sha256,
        old_card_sha256=identity.base.old_card_sha256,
        old_card_bytes_verified=card_verified,
        axes=MappingProxyType({axis: MappingProxyType(axes[axis]) for axis in AXES}),
        old_axes=MappingProxyType({axis: MappingProxyType(old_axes[axis]) for axis in AXES}),
        axes_provenance=MappingProxyType(provenance),
        axes_provenance_counts=MappingProxyType(
            {axis: MappingProxyType(provenance_counts[axis]) for axis in AXES}
        ),
        axes_basis_counts=MappingProxyType(
            {axis: MappingProxyType(basis_counts[axis]) for axis in AXES}
        ),
        violation_reasons=MappingProxyType(
            {axis: MappingProxyType(violation_reasons[axis]) for axis in AXES}
        ),
        hard_failures=hard_failures,
        old_hard_failures=old_hard_failures,
        missing_evidence_cases=missing_cases,
        changed_cases=changed_cases,
        unchanged_case_count=unchanged_case_count,
        synthetic_fixture_allowed=allow_synthetic_fixture,
        calls=MappingProxyType(
            {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0}
        ),
        not_claimed=(
            "verified",
            "threshold_met",
            "release_ready",
            "release",
            "T207_pass",
            "all_axes_real_complete",
            "q1a3_complete",
        ),
    )


# --------------------------------------------------------------------------- #
# 报告写入（拒绝覆盖旧卡/既有报告）
# --------------------------------------------------------------------------- #


def write_axes_report(
    report_path: Path | str,
    report: AxesRescoreReport,
    *,
    old_card_path: Path | str | None = None,
) -> dict[str, Any]:
    """独占新建报告文件（不覆盖/不追加）；拒绝写旧卡路径或已存在文件。"""
    _require(isinstance(report, AxesRescoreReport), "report_invalid")
    target = Path(report_path)
    _require(target.parent.is_dir(), "output_parent_missing")
    if old_card_path is not None:
        old_card = Path(old_card_path)
        try:
            same = target.resolve() == old_card.resolve()
        except OSError:
            same = target.absolute() == old_card.absolute()
        _require(not same, "old_card_overwrite_refused")
    _require(not target.exists(), "output_exists")
    payload = canonical_json_bytes(report.as_dict()) + b"\n"
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "path": str(target),
        "sha256": _sha256_bytes(payload),
        "bytes": len(payload),
        "old_card_untouched": True,
    }

# --------------------------------------------------------------------------- #
# Q1a-2 真实合同 v1 公开 schema 的薄适配层（只读 payload，不解密/不读私有密文）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Q1a2CaseView:
    case_id: str
    case_index: int
    scenario_id: str
    axes: Mapping[str, Mapping[str, Any]]
    basis: Mapping[str, str]

    def __post_init__(self) -> None:
        _require(isinstance(self.case_id, str) and bool(self.case_id), "contract_axis_invalid")
        _require(type(self.case_index) is int and self.case_index >= 0, "contract_axis_invalid")
        _require(self.scenario_id in Q1A2_SCENARIO_IDS, "contract_axis_invalid")
        _require(isinstance(self.axes, Mapping) and set(self.axes) == set(AXES), "contract_axis_invalid")
        _require(isinstance(self.basis, Mapping) and set(self.basis) == set(AXES), "contract_basis_invalid")


@dataclass(frozen=True)
class Q1a2ContractView:
    """已通过公开 schema 结构校验的 Q1a-2 v1 合同视图（不含私有逐题明文）。"""

    schema_version: str
    bindings: Mapping[str, str]
    runs: tuple[Mapping[str, Any], ...]
    cases: Mapping[str, Q1a2CaseView]
    case_count: int

    def for_case(self, case_id: str) -> Q1a2CaseView | None:
        return self.cases.get(str(case_id))

    def run_for_scenario(self, scenario_id: str) -> Mapping[str, Any] | None:
        for run in self.runs:
            if str(run.get("scenario_id") or "") == str(scenario_id):
                return run
        return None


def _validate_q1a2_axis_payload(axis: str, payload: Any) -> None:
    """校验 v1 §2.4 的 7 字段轴对象；结构性错误固定 `contract_axis_invalid`。"""
    _require(axis in AXES, "contract_axis_invalid")
    _require(isinstance(payload, Mapping) and set(payload) == Q1A2_AXIS_KEYS, "contract_axis_invalid")
    applicability = payload.get("applicability")
    _require(
        isinstance(applicability, str) and applicability in ANNOTATION_APPLICABILITIES,
        "contract_axis_invalid",
    )
    criterion = payload.get("criterion")
    _require(
        isinstance(criterion, str) and criterion in Q1A2_AXIS_CRITERIA[axis],
        "contract_axis_invalid",
    )
    reason = payload.get("reason")
    _require(isinstance(reason, str) and reason in ANNOTATION_REASONS, "contract_axis_invalid")
    target_refs = payload.get("target_refs")
    _require(isinstance(target_refs, (list, tuple)), "contract_axis_invalid")
    seen_refs: set[tuple[str, int]] = set()
    for index, ref in enumerate(target_refs):
        _require(isinstance(ref, Mapping) and set(ref) == {"collection", "index"}, "contract_axis_invalid")
        collection = ref.get("collection")
        ref_index = ref.get("index")
        _require(
            isinstance(collection, str)
            and collection in TARGET_REF_COLLECTIONS
            and type(ref_index) is int
            and ref_index >= 0,
            "contract_axis_invalid",
        )
        key = (collection, ref_index)
        _require(key not in seen_refs, "contract_axis_invalid")
        seen_refs.add(key)
    targets = payload.get("targets")
    _require(isinstance(targets, (list, tuple)), "contract_axis_invalid")
    for target in targets:
        _require(
            isinstance(target, Mapping)
            and set(target) == {"entity_type", "entity_key", "filters"},
            "contract_axis_invalid",
        )
        entity_type = target.get("entity_type")
        entity_key = target.get("entity_key")
        filters = target.get("filters")
        _require(
            isinstance(entity_type, str)
            and bool(entity_type)
            and len(entity_type) <= 256
            and isinstance(entity_key, str)
            and len(entity_key) <= 256
            and isinstance(filters, Mapping)
            and all(
                isinstance(filter_key, str) and _valid_filter_value(filter_value)
                for filter_key, filter_value in filters.items()
            ),
            "contract_axis_invalid",
        )
    as_of = payload.get("as_of")
    _require(as_of is None or (isinstance(as_of, str) and _iso_date(as_of) == as_of), "contract_axis_invalid")
    temporal_intent = payload.get("temporal_intent")
    _require(
        isinstance(temporal_intent, str) and temporal_intent in TEMPORAL_INTENTS,
        "contract_axis_invalid",
    )


def load_q1a2_contract_view(
    payload: Any,
    *,
    expected_axes: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
) -> Q1a2ContractView:
    """校验 Q1a-2 v1 公开 schema 的 5 键顶层/17 绑定/4 runs/30 cases/4 轴/basis。

    只消费调用方已解密并通过合同 §5 校验的 payload；本函数不做解密、不读密文、不联网。
    结构/绑定/覆盖/轴/basis 错误分别以合同 §5 固定码拒绝，不“尽力消费”。
    `expected_axes` 可选：传入合并后冻结标注的 7 字段轴映射时，逐题逐轴深度相等校验，
    任何差异以 `contract_semantics_changed` 拒绝；不传则由 Q1a-3 的合同 §5 消费者执行。
    """
    _require(isinstance(payload, Mapping), "contract_schema_invalid")
    _require(
        set(payload) == {"schema_version", "bindings", "runs", "case_count", "cases"},
        "contract_schema_invalid",
    )
    _require(
        payload.get("schema_version") == Q1A2_CONTRACT_SCHEMA_VERSION,
        "contract_schema_invalid",
    )

    raw_bindings = payload.get("bindings")
    _require(
        isinstance(raw_bindings, Mapping)
        and set(raw_bindings) == set(Q1A2_BINDING_KEYS),
        "contract_binding_mismatch",
    )
    bindings: dict[str, str] = {}
    for key in Q1A2_BINDING_KEYS:
        value = raw_bindings.get(key)
        _require(isinstance(value, str) and bool(value), "contract_binding_mismatch")
        if key not in Q1A2_NON_HASH_BINDING_KEYS:
            _require(bool(_SHA256_RE.fullmatch(value)), "contract_binding_mismatch")
        bindings[key] = value
    _require(bindings["dataset_version"] == "P2-HOLDOUT-v2", "contract_binding_mismatch")
    _require(bindings["label_version"] == "p2-holdout-v2-2026-11-10", "contract_binding_mismatch")

    raw_runs = payload.get("runs")
    _require(isinstance(raw_runs, list) and len(raw_runs) == Q1A2_RUN_COUNT, "contract_schema_invalid")
    runs: list[Mapping[str, Any]] = []
    for index, row in enumerate(raw_runs):
        _require(isinstance(row, Mapping) and set(row) == Q1A2_RUN_KEYS, "contract_schema_invalid")
        _require(type(row.get("run_index")) is int and row.get("run_index") == index, "contract_schema_invalid")
        _require(row.get("scenario_id") == Q1A2_SCENARIO_IDS[index], "contract_schema_invalid")
        run_id = row.get("run_id")
        plan_id = row.get("plan_id")
        plan_sha256 = row.get("plan_sha256")
        _require(
            isinstance(run_id, str) and 0 < len(run_id) <= 96,
            "contract_schema_invalid",
        )
        _require(
            isinstance(plan_id, str) and 0 < len(plan_id) <= 96,
            "contract_schema_invalid",
        )
        _require(
            isinstance(plan_sha256, str) and bool(_SHA256_RE.fullmatch(plan_sha256)),
            "contract_schema_invalid",
        )
        runs.append(
            MappingProxyType(
                {
                    "run_index": index,
                    "scenario_id": str(row.get("scenario_id")),
                    "run_id": run_id,
                    "plan_id": plan_id,
                    "plan_sha256": plan_sha256,
                }
            )
        )

    case_count = payload.get("case_count")
    _require(type(case_count) is int and case_count == Q1A2_CASE_COUNT, "contract_coverage_invalid")
    raw_cases = payload.get("cases")
    _require(
        isinstance(raw_cases, list) and len(raw_cases) == Q1A2_CASE_COUNT,
        "contract_coverage_invalid",
    )
    cases: dict[str, Q1a2CaseView] = {}
    for index, row in enumerate(raw_cases):
        _require(isinstance(row, Mapping) and set(row) == Q1A2_CASE_KEYS, "contract_schema_invalid")
        _require(type(row.get("case_index")) is int and row.get("case_index") == index, "contract_schema_invalid")
        case_id = row.get("case_id")
        _require(isinstance(case_id, str) and bool(case_id), "contract_schema_invalid")
        _require(case_id not in cases, "contract_coverage_invalid")
        scenario_id = row.get("scenario_id")
        _require(
            isinstance(scenario_id, str) and scenario_id in Q1A2_SCENARIO_IDS,
            "contract_schema_invalid",
        )
        axes_raw = row.get("axes")
        _require(isinstance(axes_raw, Mapping) and set(axes_raw) == set(AXES), "contract_axis_invalid")
        basis_raw = row.get("basis")
        _require(
            isinstance(basis_raw, Mapping) and set(basis_raw) == set(AXES),
            "contract_basis_invalid",
        )
        basis: dict[str, str] = {}
        for axis in AXES:
            value = basis_raw.get(axis)
            _require(
                isinstance(value, str) and value in Q1A2_BASIS_CODES,
                "contract_basis_invalid",
            )
            basis[axis] = value
        normalized_axes: dict[str, Mapping[str, Any]] = {}
        for axis in AXES:
            axis_payload = axes_raw.get(axis)
            _validate_q1a2_axis_payload(axis, axis_payload)
            applicability = str(axis_payload.get("applicability"))
            criterion = str(axis_payload.get("criterion"))
            reason = str(axis_payload.get("reason"))
            if axis in ("cross_user", "stale_source"):
                _require(applicability == "required", "contract_axis_invalid")
            if axis == "cross_entity" and applicability == "not_applicable":
                _require(criterion == "no_entity_claim", "contract_axis_invalid")
            if applicability == "not_applicable" and reason in UNCERTAIN_ANNOTATION_REASONS:
                raise RescoreError("contract_unknown_downgraded")
            if basis[axis] == "no_provable_basis_keep_unknown":
                _require(applicability == "unknown", "contract_basis_invalid")
            if axis in RESCORED_AXES:
                annotation = AxisAnnotation.from_mapping(
                    axis,
                    {
                        **dict(axis_payload),
                        "basis": basis[axis],
                        "source": "frozen_contract",
                    },
                )
                _require(not annotation.defects, "contract_axis_invalid")
            normalized_axes[axis] = MappingProxyType(dict(axis_payload))
        cases[case_id] = Q1a2CaseView(
            case_id=case_id,
            case_index=index,
            scenario_id=scenario_id,
            axes=MappingProxyType(normalized_axes),
            basis=MappingProxyType(basis),
        )

    if expected_axes is not None:
        _require(isinstance(expected_axes, Mapping), "contract_semantics_changed")
        _require(set(expected_axes) == set(cases), "contract_coverage_invalid")
        for case_id, expected in expected_axes.items():
            _require(
                isinstance(expected, Mapping) and set(expected) == set(AXES),
                "contract_semantics_changed",
            )
            actual_case = cases[case_id]
            for axis in AXES:
                expected_axis = expected[axis]
                _require(
                    isinstance(expected_axis, Mapping)
                    and set(expected_axis) == Q1A2_AXIS_KEYS,
                    "contract_semantics_changed",
                )
                if dict(actual_case.axes[axis]) != dict(expected_axis):
                    raise RescoreError("contract_semantics_changed")

    return Q1a2ContractView(
        schema_version=Q1A2_CONTRACT_SCHEMA_VERSION,
        bindings=MappingProxyType(bindings),
        runs=tuple(runs),
        cases=MappingProxyType(cases),
        case_count=Q1A2_CASE_COUNT,
    )


def _cross_entity_mode_from_annotation(annotation: AxisAnnotation) -> str:
    if annotation.applicability == "unknown" or annotation.criterion == "unknown":
        return "unknown"
    if annotation.criterion == "shared_background":
        return "shared_background_only"
    if annotation.criterion in ("structured_target", "multi_target"):
        return "entity_bound"
    if annotation.criterion == "no_entity_claim":
        return "no_entity_scope" if annotation.applicability == "not_applicable" else "unknown"
    return "unknown"


def _validate_q1a2_refs(refs: Any) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    if refs is None:
        return MappingProxyType({})
    _require(isinstance(refs, Mapping), "contract_axis_invalid")
    resolved: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for collection, rows in refs.items():
        _require(
            isinstance(collection, str) and collection in TARGET_REF_COLLECTIONS,
            "contract_axis_invalid",
        )
        _require(isinstance(rows, (list, tuple)), "contract_axis_invalid")
        candidates: list[Mapping[str, Any]] = []
        for row in rows:
            _require(isinstance(row, Mapping), "contract_axis_invalid")
            candidate = dict(row)
            try:
                ref_key(candidate)
            except RescoreError as exc:
                raise RescoreError("contract_axis_invalid") from exc
            candidates.append(candidate)
        resolved[collection] = tuple(candidates)
    return MappingProxyType(resolved)


def _validate_q1a2_version_bindings(raw: Any) -> Mapping[str, VersionBinding]:
    if raw is None:
        return MappingProxyType({})
    _require(isinstance(raw, Mapping), "contract_axis_invalid")
    resolved: dict[str, VersionBinding] = {}
    for key, value in raw.items():
        _require(isinstance(key, str) and bool(_SHA256_RE.fullmatch(key)), "contract_axis_invalid")
        _require(isinstance(value, VersionBinding), "contract_axis_invalid")
        resolved[key] = value
    return MappingProxyType(resolved)


def axes_case_from_q1a2_view(
    view: Q1a2ContractView,
    *,
    case_id: str,
    old_card: OldCardCase,
    cross_user: CrossUserEvidenceView | None = None,
    cross_entity: CrossEntityEvidenceView | None = None,
    stale_source: StaleSourceEvidenceView | None = None,
    frozen_refs: Mapping[str, Any] | None = None,
    shared_background: tuple[ScopeSharedBackground, ...] = (),
    version_bindings: Mapping[str, VersionBinding] | None = None,
    source_marker: str = "frozen_contract",
) -> AxesCaseView:
    """把 Q1a-2 v1 合同视图映射为 Q1a-1b 的 `AxesCaseView`（薄适配层）。

    - 合同轴对象恰 7 字段；basis 从同题 `basis[axis]` 注入，只进 provenance；
    - 来源标记默认 `frozen_contract`（真实合同），合成 fixture 可显式传
      `synthetic_fixture` 并配合 `allow_synthetic_fixture=True`；
    - `frozen_refs` 是调用方从冻结 case/公开语料显式解析的
      `collection -> refs`，不是从产品答案反推；
    - `shared_background` / `version_bindings` 是公开 schema 7 字段之外的显式投影，
      缺失时对应轴只能 unknown，不能 pass。
    """
    _require(isinstance(view, Q1a2ContractView), "contract_schema_invalid")
    _require(isinstance(old_card, OldCardCase), "case_invalid")
    _require(isinstance(source_marker, str) and source_marker in AXES_SOURCES, "contract_schema_invalid")
    _require(source_marker != "unresolved", "contract_schema_invalid")
    _require(isinstance(shared_background, tuple), "contract_axis_invalid")
    _require(
        all(isinstance(item, ScopeSharedBackground) for item in shared_background),
        "contract_axis_invalid",
    )
    case_view = view.for_case(case_id)
    _require(case_view is not None, "contract_coverage_invalid")
    assert case_view is not None
    _require(old_card.case_id == case_id, "case_invalid")
    run = view.run_for_scenario(case_view.scenario_id)
    _require(run is not None, "contract_coverage_invalid")
    assert run is not None
    bindings = {
        "run_id": str(run["run_id"]),
        "plan_id": str(run["plan_id"]),
        "plan_sha256": str(run["plan_sha256"]),
    }
    refs = _validate_q1a2_refs(frozen_refs)
    resolved_version_bindings = _validate_q1a2_version_bindings(version_bindings)

    annotations: dict[str, AxisAnnotation] = {}
    for axis in RESCORED_AXES:
        axis_payload = dict(case_view.axes[axis])
        axis_payload["basis"] = case_view.basis[axis]
        axis_payload["source"] = source_marker
        annotation = AxisAnnotation.from_mapping(axis, axis_payload)
        _require(not annotation.defects, "contract_axis_invalid")
        annotations[axis] = annotation

    cross_entity_annotation = annotations["cross_entity"]
    cross_entity_mode = _cross_entity_mode_from_annotation(cross_entity_annotation)
    cross_entity_targets: tuple[ScopeTarget, ...] = ()
    if cross_entity_mode == "entity_bound":
        cross_entity_targets = tuple(
            ScopeTarget(
                entity_type=str(target.get("entity_type") or ""),
                entity_key=str(target.get("entity_key") or ""),
                filters=dict(target.get("filters") or {}),
            )
            for target in cross_entity_annotation.targets
        )
    if cross_entity_mode == "no_entity_scope" and shared_background:
        raise RescoreError("contract_axis_invalid")
    if cross_entity_mode in ("shared_background_only", "no_entity_scope") and cross_entity_targets:
        raise RescoreError("contract_axis_invalid")
    cross_entity_contract = CrossEntityContract(
        case_id=case_id,
        mode=cross_entity_mode,
        targets=cross_entity_targets,
        shared_background=shared_background,
        bindings=bindings,
        refs=refs,
        version_bindings=resolved_version_bindings,
    )
    stale_source_contract = StaleSourceContract(
        case_id=case_id,
        bindings=bindings,
        constrained_refs=(),
        refs=refs,
        version_bindings=resolved_version_bindings,
    )
    return AxesCaseView(
        old=old_card,
        annotations=MappingProxyType(annotations),
        cross_user=cross_user,
        cross_entity=cross_entity,
        cross_entity_contract=cross_entity_contract,
        stale_source=stale_source,
        stale_source_contract=stale_source_contract,
    )
