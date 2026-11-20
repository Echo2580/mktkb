"""C1-P2：请求使用集为空的闭包证明（C 冻结原语的独立替代实现）。

本模块只回答一个问题：**这一回合的“已使用来源集合”能否被证明为空**。
它不产生四轴 verdict、不读真实 H2 输入、不调用 provider/网络/模型。

与 C 冻结原语的关系
--------------------
- 不 import ``p2_hard_evidence`` / ``p2_evidence_capture`` / ``p2_evidence_io``。
  事件协议来自 :mod:`mktkb.observability.evaluation_capture`，产品文案来自
  :mod:`mktkb.copy`；两者都是产品契约，不是冻结证明逻辑。
- 冻结原语把“检索候选层”也当作使用层：``retrieval_observed.unit_ids``、
  ``query_states[].state_json.candidates`` 非空即不可证明。本实现把“使用”限定为
  真正进入回答/提交/模型输入/引用/事实/实体继承的来源；候选层单独归类。
  这是本实现能覆盖“检索有结果但未被使用”“多轮中部分轮空”等形状的原因，
  也是与冻结原语在少数形状上**有意不一致**的原因；差分证据逐例给固定码。
- 其余形状（缺字段、未知键、事件重复、模板不匹配、证据不完整等）一律
  fail-closed，返回 ``empty_set_not_proven``，不默认 proven。

固定码
------
- proven：``empty_use_scope_ok``
- not proven：``empty_set_not_proven``（所有未证明形状统一码；细分诊断在
  :attr:`EmptyScopeProof.shape` / :attr:`EmptyScopeProof.detail`）

本模块是 C1-1 / C1-P2 的新产物，**不修改**冻结件，也不把本模块的结论写回
任何旧卡、账本、GO 或真实 H2 产物。
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..copy import COPY
from ..observability.evaluation_capture import EVENT_FIELDS, clean_event_payload

__all__ = [
    "BRANCH_SHAPES",
    "EMPTY_SET_NOT_PROVEN",
    "EMPTY_USE_SCOPE_OK",
    "EmptyScopeProof",
    "OUTCOME_CLASSES",
    "PROOF_SCHEMA_VERSION",
    "RETRIEVAL_SHAPES",
    "empty_use_scope_proof",
    "prove_empty_use_scope",
]

PROOF_SCHEMA_VERSION = "p2-empty-scope-proof/v0.1"

EMPTY_USE_SCOPE_OK = "empty_use_scope_ok"
EMPTY_SET_NOT_PROVEN = "empty_set_not_proven"

# --------------------------------------------------------------------------- #
# 契约常量（只读参考：事件/投影 schema；逻辑不在本模块复用冻结实现）
# --------------------------------------------------------------------------- #

LIVE_FIXTURE_KIND = "live_h2"
RUNTIME_SNAPSHOT_SCHEMA_VERSION = "p2-runtime-snapshot/v0.1"
RUNTIME_SNAPSHOT_VERSIONS = (
    "p2-hard-evidence-capture/v0.3",
    "p2-hard-evidence-capture/v0.3-live",
)

ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "fixture_kind",
        "bindings",
        "adapter_components",
        "turn",
        "capture",
        "db_projection",
        "completeness",
        "sealed",
    }
)
ENVELOPE_KEYS_LIVE = ENVELOPE_KEYS | {"run_binding"}

CAPTURE_KEYS = frozenset(
    {"schema_version", "sink_id", "status", "seq", "event_count", "events", "errors"}
)
EVENT_KEYS = frozenset({"seq", "kind", "payload"})
TURN_KEYS = frozenset(
    {
        "turn_index",
        "client_request_id",
        "conversation_id",
        "authenticated_user_id",
        "question_sha256",
        "http_status",
        "timed_out",
        "started_utc",
        "captured_utc",
        "pre_revision",
        "post_revision",
        "capture_revision",
    }
)

PROJECTION_KEYS = frozenset(
    {
        "schema_version",
        "snapshot_utc",
        "pre_revision",
        "capture_revision",
        "conversation",
        "request",
        "messages",
        "message_sources",
        "units",
        "unresolved_unit_ids",
        "query_states",
        "query_states_available",
        "rag_business_date",
        "truncations",
        "errors",
    }
)
PROJECTION_REQUIRED_KEYS = (
    "conversation",
    "request",
    "messages",
    "units",
    "message_sources",
    "unresolved_unit_ids",
    "query_states",
    "query_states_available",
    "rag_business_date",
    "truncations",
    "errors",
)
PROJECTION_ROW_KEYS: dict[str, frozenset[str]] = {
    "conversation": frozenset(
        {"id", "owner_user_id", "deleted", "deleted_at", "created_at", "updated_at"}
    ),
    "request": frozenset(
        {
            "id",
            "conversation_id",
            "user_id",
            "status",
            "attempt",
            "payload_sha256",
            "user_message_id",
            "result_message_id",
            "error_code",
            "error_retryable",
            "created_at",
            "started_at",
            "finished_at",
        }
    ),
    "messages": frozenset(
        {
            "id",
            "conversation_id",
            "owner_user_id",
            "role",
            "seq",
            "kind",
            "revision",
            "error_code",
            "text",
            "created_at",
        }
    ),
    "message_sources": frozenset({"message_id", "source_id", "document_id", "version_id"}),
    "units": frozenset(
        {
            "unit_id",
            "unit_key",
            "kind",
            "locator",
            "text",
            "raw_fields",
            "date_fields",
            "entity_type",
            "entity_key",
            "entity_filters",
            "document_id",
            "document_name",
            "document_deleted",
            "version_id",
            "version_number",
            "version_state",
            "active_version_id",
            "active",
            "published_at",
        }
    ),
    "unresolved_unit_ids": frozenset({"unit_id", "reason"}),
    "query_states": frozenset({"stored_user_id", "stored_conversation_id", "state_json", "keys"}),
}
PROJECTION_ROW_GROUPS = ("messages", "message_sources", "units", "unresolved_unit_ids", "query_states")

REQUIRED_EVENTS = (
    "claim_observed",
    "context_observed",
    "plan_observed",
    "answer_result",
    "commit_observed",
)
QUERY_STATE_KINDS = (
    "query_state_observed",
    "query_state_saved",
    "query_state_cleared",
)
MODEL_PURPOSES = ("answer", "query_expansion")

NO_FACT_KINDS = frozenset({"not_found", "no_answer", "clarification", "knowledge_changed"})
NO_FACT_TEMPLATE_KEYS: dict[str, tuple[str, ...]] = {
    "not_found": (
        "LEGACY_NO_EVIDENCE",
        "LEGACY_UNKNOWN_STORE",
        "LEGACY_MULTIPLE_ENTITIES",
        "IMAGE_NOT_SUPPORTED",
        "FIELD_NOT_RECORDED",
        "UNKNOWN_IDENTIFIER",
        "IDENTIFIER_NOT_RETRIEVABLE",
        "NO_INTENT",
        "NO_EVIDENCE",
        "NO_SUPPORTING_SENTENCE",
        "UNKNOWN_STORE",
        "NO_RECORD_FOR_ENTITY",
        "NO_ENUMERABLE_RECORD",
        "PAGE_OUT_OF_RANGE",
        "EMPTY_QUERY",
        "DOCUMENT_NOT_FOUND",
        "POLICY_TOPIC_NOT_FOUND",
        "UNSUPPORTED_FINANCIAL_METRIC",
        "UNKNOWN_REGION",
    ),
    "no_answer": (
        "DOCUMENT_NOT_FOUND",
        "UNKNOWN_STORE",
        "RECORD_ONLY",
        "UNSUPPORTED_FINANCIAL_METRIC",
        "ANAPHORA_NEW_CONTENT",
        "NO_RECORD_FOR_ENTITY",
        "NO_ENUMERABLE_RECORD",
        "PAGE_OUT_OF_RANGE",
        "NO_EVIDENCE",
        "NO_SUPPORTING_SENTENCE",
        "POLICY_TOPIC_NOT_FOUND",
        "NOT_YET_EFFECTIVE",
        "EFFECTIVE_WINDOW_EXPIRED",
        "EFFECTIVE_WINDOW_CONFLICT",
        "FACT_REJECTED",
    ),
    "clarification": (
        "CLARIFICATION_REQUIRED",
        "MISSING_SLOT",
        "MULTIPLE_ENTITIES",
        "LEGACY_MULTIPLE_ENTITIES",
        "DOCUMENT_AMBIGUOUS",
        "PRODUCT_AMBIGUOUS",
        "ITEM_AMBIGUOUS",
        "CHANNEL_AMBIGUOUS",
        "PRICE_TYPE_AMBIGUOUS",
        "ANAPHORA_NO_ENTITY",
        "ANAPHORA_NO_FIELD",
        "EMPTY_QUERY",
    ),
    "knowledge_changed": ("KNOWLEDGE_CHANGED",),
}

_TEMPLATE_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_MAX_PLACEHOLDER_WIDTH = 512
_CLARIFICATION_SUFFIX = r"(?:可选：.{1,512})?"

RETRIEVAL_SHAPES = (
    "retrieval_absent",
    "retrieval_empty",
    "retrieval_candidates_unused",
    "unknown",
)
BRANCH_SHAPES = (
    "legacy_no_model",
    "legacy_model_answer",
    "rag_direct",
    "unknown",
)
OUTCOME_CLASSES = ("refusal", "clarification", "knowledge_changed", "factual", "unknown")


# --------------------------------------------------------------------------- #
# 返回类型
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EmptyScopeProof:
    """一次空使用集证明的完整读数（固定码 + 形状 + 诊断）。"""

    proven: bool
    code: str
    shape: str
    branch: str
    retrieval: str
    outcome: str
    outcome_class: str
    detail: str
    usage_layers: tuple[str, ...] = ()
    candidate_sources: tuple[str, ...] = ()

    def as_pair(self) -> tuple[bool, str]:
        """兼容冻结原语 ``(bool, reason)`` 的消费形状。"""

        return self.proven, self.code

    def as_dict(self) -> dict[str, Any]:
        return {
            "proven": self.proven,
            "code": self.code,
            "shape": self.shape,
            "branch": self.branch,
            "retrieval": self.retrieval,
            "outcome": self.outcome,
            "outcome_class": self.outcome_class,
            "detail": self.detail,
            "usage_layers": list(self.usage_layers),
            "candidate_sources": list(self.candidate_sources),
        }


# --------------------------------------------------------------------------- #
# 内部异常与状态
# --------------------------------------------------------------------------- #


class _ProofGap(Exception):
    """形状缺口：只携带固定诊断串，不回显任何原始文本/ID。"""

    def __init__(self, shape: str, detail: str) -> None:
        super().__init__(detail)
        self.shape = shape
        self.detail = detail


@dataclass
class _ProofState:
    branch: str = "unknown"
    retrieval: str = "unknown"
    outcome: str = "unknown"
    outcome_class: str = "unknown"
    usage_layers: tuple[str, ...] = ()
    candidate_sources: tuple[str, ...] = ()

    @property
    def shape(self) -> str:
        return f"{self.branch}/{self.retrieval}/{self.outcome}"


# --------------------------------------------------------------------------- #
# 基础类型/契约小工具（不 import 冻结实现）
# --------------------------------------------------------------------------- #


def _is_str(value: Any) -> bool:
    return type(value) is str


def _is_list(value: Any) -> bool:
    return isinstance(value, list)


def _is_int(value: Any) -> bool:
    # bool 是 int 子类：计数必须排除 bool 冒充。
    return type(value) is int


def _envelope_keys(fixture_kind: Any, schema_version: Any) -> frozenset[str]:
    keys = ENVELOPE_KEYS_LIVE if str(fixture_kind) == LIVE_FIXTURE_KIND else ENVELOPE_KEYS
    if str(schema_version) in RUNTIME_SNAPSHOT_VERSIONS:
        keys = keys | {"runtime_snapshot"}
    return keys


def _events(evidence: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    capture = evidence.get("capture")
    if not isinstance(capture, Mapping):
        return []
    rows = capture.get("events")
    if not _is_list(rows):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for event in events:
        if str(event.get("kind")) == kind:
            payload = event.get("payload")
            if isinstance(payload, Mapping):
                rows.append(payload)
    return rows


def _normalize_fixed_text(text: Any) -> str:
    return "".join(str(text).split())


@functools.lru_cache(maxsize=256)
def _template_pattern(template: str) -> re.Pattern[str]:
    normalized = _normalize_fixed_text(template)
    parts = _TEMPLATE_PLACEHOLDER.split(normalized)
    pattern = re.escape(parts[0])
    for part in parts[1:]:
        pattern += ".{1," + str(_MAX_PLACEHOLDER_WIDTH) + "}?" + re.escape(part)
    return re.compile(pattern)


def _matches_no_fact_template(kind: str, text: Any) -> bool:
    normalized = _normalize_fixed_text(text)
    if not normalized:
        return False
    for key in NO_FACT_TEMPLATE_KEYS.get(kind, ()):
        entry = COPY.get(key)
        if entry is None:
            continue
        pattern = _template_pattern(entry.template)
        if pattern.fullmatch(normalized) is not None:
            return True
        if kind == "clarification" and re.fullmatch(
            pattern.pattern + _CLARIFICATION_SUFFIX, normalized
        ) is not None:
            return True
    return False


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _ProofGap("branch_evidence_missing", f"{label}_not_mapping")
    return value


def _require_str(value: Any, label: str) -> str:
    if not _is_str(value):
        raise _ProofGap("branch_evidence_missing", f"{label}_not_str")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not _is_list(value):
        raise _ProofGap("branch_evidence_missing", f"{label}_not_list")
    return value


def _require_nonblank_str(value: Any, label: str) -> str:
    text = _require_str(value, label)
    if not text.strip():
        raise _ProofGap("branch_evidence_missing", f"{label}_blank")
    return text


def _model_groups(
    events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[Mapping[str, Any]]], dict[str, list[Mapping[str, Any]]]]:
    inputs: dict[str, list[Mapping[str, Any]]] = {}
    outputs: dict[str, list[Mapping[str, Any]]] = {}
    for payload in _payloads(events, "model_input"):
        inputs.setdefault(str(payload.get("purpose") or ""), []).append(payload)
    for payload in _payloads(events, "model_output"):
        outputs.setdefault(str(payload.get("purpose") or ""), []).append(payload)
    return inputs, outputs


def _add_layer(
    layers: dict[str, list[str]], layer: str, values: Any, *, field_name: str
) -> None:
    """登记使用层 ID；坏条目 fail-closed（不把空串/非字符串当空）。"""

    for value in _require_list(values, field_name):
        layers.setdefault(layer, []).append(_require_nonblank_str(value, field_name))


def _usage_layers(
    events: Sequence[Mapping[str, Any]], projection: Mapping[str, Any]
) -> dict[str, list[str]]:
    """使用层：真正进入模型/回答/提交/事实/引用/实体继承/DB 的来源。"""

    layers: dict[str, list[str]] = {}
    for payload in _payloads(events, "model_input"):
        evidence_rows = _require_list(payload.get("evidence"), "model_input.evidence")
        values: list[str] = []
        for row in evidence_rows:
            if not isinstance(row, Mapping):
                raise _ProofGap("branch_evidence_missing", "model_input.evidence_item_not_mapping")
            values.append(_require_nonblank_str(row.get("source_id"), "model_input.evidence.source_id"))
        layers.setdefault("model_evidence", []).extend(values)
    for payload in _payloads(events, "model_output"):
        _add_layer(layers, "model_output_sources", payload.get("source_ids"), field_name="model_output.source_ids")
    for payload in _payloads(events, "direct_rag_answer"):
        facts = _require_list(payload.get("facts"), "direct_rag_answer.facts")
        fact_ids: list[str] = []
        for row in facts:
            if not isinstance(row, Mapping):
                raise _ProofGap("branch_evidence_missing", "direct_rag_answer.fact_not_mapping")
            fact_ids.append(
                _require_nonblank_str(row.get("source_unit_id"), "direct_rag_answer.fact.source_unit_id")
            )
        layers.setdefault("direct_rag_facts", []).extend(fact_ids)
        _add_layer(
            layers,
            "direct_rag_citations",
            payload.get("cited_unit_ids"),
            field_name="direct_rag_answer.cited_unit_ids",
        )
        fact_count = payload.get("fact_count")
        if not _is_int(fact_count):
            raise _ProofGap("branch_evidence_missing", "direct_rag_answer.fact_count_not_int")
        if fact_count != len(facts):
            raise _ProofGap("branch_evidence_inconsistent", "direct_rag_answer.fact_count_mismatch")
        if fact_count:
            layers.setdefault("direct_rag_fact_count", []).append(str(fact_count))
    for kind in ("answer_result", "commit_observed"):
        for payload in _payloads(events, kind):
            _add_layer(layers, f"{kind}_sources", payload.get("source_ids"), field_name=f"{kind}.source_ids")
    for payload in _payloads(events, "entity_inheritance"):
        layers.setdefault("entity_inheritance", []).append(
            _require_nonblank_str(payload.get("source_unit_id"), "entity_inheritance.source_unit_id")
        )
    for row in _require_list(projection.get("message_sources"), "projection.message_sources"):
        if not isinstance(row, Mapping):
            raise _ProofGap("branch_evidence_missing", "projection.message_source_not_mapping")
        layers.setdefault("projection_message_sources", []).append(
            _require_nonblank_str(row.get("source_id"), "projection.message_sources.source_id")
        )
    return {layer: sorted(set(values)) for layer, values in layers.items() if values}


def _candidate_layers(
    events: Sequence[Mapping[str, Any]], projection: Mapping[str, Any]
) -> dict[str, list[str]]:
    """候选层：检索观察与 query_state.candidates；不是“已使用来源”。"""

    layers: dict[str, list[str]] = {}
    for payload in _payloads(events, "retrieval_observed"):
        _add_layer(layers, "retrieval_observed", payload.get("unit_ids"), field_name="retrieval_observed.unit_ids")
    for kind in QUERY_STATE_KINDS:
        for payload in _payloads(events, kind):
            state = _require_mapping(payload.get("state_json"), f"{kind}.state_json")
            if not state:
                continue
            candidates = _require_list(state.get("candidates"), f"{kind}.state_json.candidates")
            _add_layer(layers, "query_state_candidates", candidates, field_name=f"{kind}.candidates")
            row_present = payload.get("row_present")
            if type(row_present) is not bool:
                raise _ProofGap("branch_evidence_missing", f"{kind}.row_present_not_bool")
            if kind == "query_state_observed" and row_present is False:
                raise _ProofGap("branch_evidence_inconsistent", "query_state_observed_present_false_with_state")
    for row in _require_list(projection.get("query_states"), "projection.query_states"):
        if not isinstance(row, Mapping):
            raise _ProofGap("branch_evidence_missing", "projection.query_state_not_mapping")
        state = _require_mapping(row.get("state_json"), "projection.query_states.state_json")
        if not state:
            continue
        candidates = _require_list(state.get("candidates"), "projection.query_states.candidates")
        _add_layer(layers, "projection_query_state_candidates", candidates, field_name="projection.query_states.candidates")
    return {layer: sorted(set(values)) for layer, values in layers.items() if values}


def _positive_no_retrieval_marker(snapshot: Any) -> bool:
    """v0.3 runtime_snapshot 明确声明“本轮没有检索”才是正证据。"""

    if not isinstance(snapshot, Mapping):
        return False
    if str(snapshot.get("schema_version")) != RUNTIME_SNAPSHOT_SCHEMA_VERSION:
        return False
    usage = snapshot.get("retrieval_use")
    if not isinstance(usage, Mapping):
        return False
    if usage.get("availability") != "complete" or usage.get("reason") is not None:
        return False
    if usage.get("candidate_observation") != {
        "availability": "not_observed",
        "reason": "no_retrieval_observed",
    }:
        return False
    return usage.get("candidates") == []


def _classify_branch(
    events: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
    state: _ProofState,
) -> list[Mapping[str, Any]]:
    """分支 × 模型 purpose 矩阵；返回 direct_rag_answer 行。"""

    plan_path = _require_str(plan.get("path"), "plan_observed.path")
    inputs, outputs = _model_groups(events)
    direct_rows = _payloads(events, "direct_rag_answer")
    if plan_path == "legacy":
        if direct_rows:
            raise _ProofGap("branch_evidence_inconsistent", "legacy_has_direct_rag")
        purposes = set(inputs) | set(outputs)
        if not purposes:
            state.branch = "legacy_no_model"
            return direct_rows
        if purposes - {"answer"}:
            raise _ProofGap("branch_evidence_missing", "legacy_unexpected_model_purpose")
        if not inputs.get("answer") or not outputs.get("answer"):
            raise _ProofGap("model_events_missing", "legacy_answer_model_pair_incomplete")
        if len(inputs["answer"]) != 1 or len(outputs["answer"]) != 1:
            raise _ProofGap("branch_evidence_inconsistent", "legacy_answer_model_duplicate")
        state.branch = "legacy_model_answer"
        return direct_rows
    if plan_path == "rag":
        if len(direct_rows) != 1:
            raise _ProofGap("branch_evidence_missing", "rag_direct_rag_count_invalid")
        purposes = set(inputs) | set(outputs)
        for purpose in purposes:
            if purpose not in MODEL_PURPOSES or purpose == "answer":
                raise _ProofGap("branch_evidence_missing", "rag_unexpected_model_purpose")
            if not inputs.get(purpose) or not outputs.get(purpose):
                raise _ProofGap("model_events_missing", "rag_model_pair_incomplete")
            if len(inputs[purpose]) != 1 or len(outputs[purpose]) != 1:
                raise _ProofGap("branch_evidence_inconsistent", "rag_model_duplicate")
        state.branch = "rag_direct"
        return direct_rows
    raise _ProofGap("branch_evidence_missing", "unknown_plan_path")


def _check_projection(projection: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if set(projection) - PROJECTION_KEYS:
        raise _ProofGap("unknown_usage_field", "unknown_projection_key")
    for key in PROJECTION_REQUIRED_KEYS:
        if key not in projection:
            raise _ProofGap("branch_evidence_missing", f"projection_key_missing:{key}")
    for group in PROJECTION_ROW_GROUPS:
        rows = _require_list(projection.get(group), f"projection.{group}")
        allowed = PROJECTION_ROW_KEYS[group]
        for row in rows:
            if not isinstance(row, Mapping):
                raise _ProofGap("branch_evidence_missing", f"projection.{group}_row_not_mapping")
            if set(row) - allowed:
                raise _ProofGap("unknown_usage_field", f"projection.{group}_unknown_key")
    conversation = _require_mapping(projection.get("conversation"), "projection.conversation")
    request_row = _require_mapping(projection.get("request"), "projection.request")
    if set(conversation) - PROJECTION_ROW_KEYS["conversation"]:
        raise _ProofGap("unknown_usage_field", "projection.conversation_unknown_key")
    if set(request_row) - PROJECTION_ROW_KEYS["request"]:
        raise _ProofGap("unknown_usage_field", "projection.request_unknown_key")
    _require_str(conversation.get("id"), "projection.conversation.id")
    _require_str(conversation.get("owner_user_id"), "projection.conversation.owner_user_id")
    for key in ("id", "conversation_id", "user_id", "result_message_id"):
        _require_str(request_row.get(key), f"projection.request.{key}")
    if projection.get("query_states_available") is not True:
        raise _ProofGap("branch_evidence_missing", "projection.query_states_unavailable")
    if projection.get("truncations"):
        raise _ProofGap("evidence_incomplete", "projection_truncations_present")
    if projection.get("errors"):
        raise _ProofGap("evidence_incomplete", "projection_errors_present")
    return conversation, request_row


def _check_identity(
    claim: Mapping[str, Any],
    context: Mapping[str, Any],
    plan: Mapping[str, Any],
    answer: Mapping[str, Any],
    commit: Mapping[str, Any],
    conversation: Mapping[str, Any],
    request_row: Mapping[str, Any],
) -> None:
    for key in ("request_id", "conversation_id", "authenticated_user_id", "owner_user_id"):
        _require_str(claim.get(key), f"claim_observed.{key}")
    if not _is_int(context.get("count")) or type(context.get("empty")) is not bool:
        raise _ProofGap("branch_evidence_missing", "context_observed_type_invalid")
    _require_str(plan.get("path"), "plan_observed.path")
    _require_str(answer.get("kind"), "answer_result.kind")
    _require_str(answer.get("text"), "answer_result.text")
    _require_str(answer.get("request_id"), "answer_result.request_id")
    _require_str(commit.get("message_id"), "commit_observed.message_id")
    _require_str(commit.get("kind"), "commit_observed.kind")
    _require_str(commit.get("text"), "commit_observed.text")
    _require_str(commit.get("request_id"), "commit_observed.request_id")
    if str(claim.get("conversation_id")) != str(conversation.get("id")):
        raise _ProofGap("branch_evidence_inconsistent", "claim_conversation_mismatch")
    claim_request = str(claim.get("request_id"))
    if claim_request != str(request_row.get("id")):
        raise _ProofGap("branch_evidence_inconsistent", "claim_request_mismatch")
    if str(answer.get("request_id")) != claim_request or str(commit.get("request_id")) != claim_request:
        raise _ProofGap("branch_evidence_inconsistent", "result_request_mismatch")
    if str(commit.get("message_id")) != str(request_row.get("result_message_id")):
        raise _ProofGap("branch_evidence_inconsistent", "commit_message_mismatch")
    if str(commit.get("kind")) != str(answer.get("kind")):
        raise _ProofGap("branch_evidence_inconsistent", "answer_commit_kind_mismatch")
    if commit.get("text") != answer.get("text"):
        raise _ProofGap("branch_evidence_inconsistent", "answer_commit_text_mismatch")


def _attribute_projection_rows(
    projection: Mapping[str, Any], usage_ids: set[str], candidate_ids: set[str]
) -> None:
    """投影行必须可归因：使用层命中 → 不可证明；候选层命中 → 未使用。"""

    for group in ("units", "unresolved_unit_ids"):
        for row in _require_list(projection.get(group), f"projection.{group}"):
            if not isinstance(row, Mapping):
                raise _ProofGap("branch_evidence_missing", f"projection.{group}_row_not_mapping")
            unit_id = _require_nonblank_str(row.get("unit_id"), f"projection.{group}.unit_id")
            if unit_id in usage_ids:
                raise _ProofGap("empty_set_not_proven", f"projection_{group}_usage_present")
            if unit_id in candidate_ids:
                continue
            raise _ProofGap("branch_evidence_missing", f"projection_{group}_unattributable")


# --------------------------------------------------------------------------- #
# 主证明
# --------------------------------------------------------------------------- #


def _not_proven(gap: _ProofGap, state: _ProofState) -> EmptyScopeProof:
    return EmptyScopeProof(
        proven=False,
        code=EMPTY_SET_NOT_PROVEN,
        shape=state.shape if state.shape != "unknown/unknown/unknown" else gap.shape,
        branch=state.branch,
        retrieval=state.retrieval,
        outcome=state.outcome,
        outcome_class=state.outcome_class,
        detail=gap.detail,
        usage_layers=state.usage_layers,
        candidate_sources=state.candidate_sources,
    )


def _prove(evidence: Any) -> EmptyScopeProof:
    state = _ProofState()
    try:
        envelope = _require_mapping(evidence, "evidence")

        # ---- A. 完整性 + 封装层闭包 ----
        completeness = envelope.get("completeness")
        if not isinstance(completeness, Mapping) or str(completeness.get("status")) != "complete":
            raise _ProofGap("evidence_incomplete", "completeness_not_complete")
        if set(envelope) - _envelope_keys(envelope.get("fixture_kind"), envelope.get("schema_version")):
            raise _ProofGap("unknown_usage_field", "unknown_envelope_key")
        capture = _require_mapping(envelope.get("capture"), "capture")
        if set(capture) - CAPTURE_KEYS:
            raise _ProofGap("unknown_usage_field", "unknown_capture_key")
        raw_events = _require_list(capture.get("events"), "capture.events")
        capture_errors = _require_list(capture.get("errors"), "capture.errors")
        if capture_errors:
            raise _ProofGap("evidence_incomplete", "capture_errors_present")
        turn = _require_mapping(envelope.get("turn"), "turn")
        if set(turn) - TURN_KEYS:
            raise _ProofGap("unknown_usage_field", "unknown_turn_key")

        # ---- B. 事件闭包 + 契约 payload 自核 ----
        events: list[Mapping[str, Any]] = []
        for raw in raw_events:
            if not isinstance(raw, Mapping):
                raise _ProofGap("branch_evidence_missing", "event_not_mapping")
            if set(raw) - EVENT_KEYS:
                raise _ProofGap("unknown_usage_field", "unknown_event_key")
            if "kind" not in raw or "payload" not in raw:
                raise _ProofGap("branch_evidence_missing", "event_missing_kind_or_payload")
            kind = str(raw.get("kind") or "")
            if kind not in EVENT_FIELDS:
                raise _ProofGap("unknown_usage_field", "unknown_event_kind")
            payload = raw.get("payload")
            if not isinstance(payload, Mapping):
                raise _ProofGap("branch_evidence_missing", "event_payload_not_mapping")
            if set(payload) - set(EVENT_FIELDS[kind]):
                raise _ProofGap("unknown_usage_field", f"unknown_event_field:{kind}")
            try:
                clean_event_payload(kind, dict(payload))
            except Exception as exc:  # noqa: BLE001 - 统一转固定证据缺口
                raise _ProofGap("branch_evidence_missing", f"event_payload_invalid:{kind}") from exc
            if kind == "capture_error":
                raise _ProofGap("evidence_incomplete", "capture_error_event")
            events.append(raw)

        # ---- C. 必需事件各恰一条 ----
        required: dict[str, Mapping[str, Any]] = {}
        for kind in REQUIRED_EVENTS:
            rows = _payloads(events, kind)
            if len(rows) != 1:
                raise _ProofGap("branch_evidence_missing", f"required_event_count:{kind}")
            required[kind] = rows[0]
        claim = required["claim_observed"]
        context = required["context_observed"]
        plan = required["plan_observed"]
        answer = required["answer_result"]
        commit = required["commit_observed"]

        # ---- D. 投影闭包 ----
        projection = _require_mapping(envelope.get("db_projection"), "db_projection")
        conversation, request_row = _check_projection(projection)
        _check_identity(claim, context, plan, answer, commit, conversation, request_row)

        # ---- E. 分支 × 模型 purpose 矩阵 + direct_rag 一致性 ----
        direct_rows = _classify_branch(events, plan, state)
        if state.branch == "rag_direct":
            direct = direct_rows[0]
            if str(direct.get("kind")) != str(commit.get("kind")):
                raise _ProofGap("branch_evidence_inconsistent", "direct_rag_kind_mismatch")
            if direct.get("text") != commit.get("text"):
                raise _ProofGap("branch_evidence_inconsistent", "direct_rag_text_mismatch")

        # ---- F. 使用层：只要有一层非空就不可证明 ----
        usage = _usage_layers(events, projection)
        if usage:
            state.usage_layers = tuple(sorted(usage))
            counts = ",".join(f"{layer}={len(values)}" for layer, values in sorted(usage.items()))
            raise _ProofGap("empty_set_not_proven", f"usage_layers_nonempty:{counts}")

        # ---- G. 候选层/投影归因 ----
        candidates = _candidate_layers(events, projection)
        state.candidate_sources = tuple(sorted(candidates))
        candidate_ids = {value for values in candidates.values() for value in values}
        _attribute_projection_rows(projection, set(), candidate_ids)

        # ---- H. 检索形状（含“无检索”的正证据判定） ----
        retrieval_payloads = _payloads(events, "retrieval_observed")
        if retrieval_payloads:
            retrieval_ids: list[str] = []
            for payload in retrieval_payloads:
                for value in _require_list(payload.get("unit_ids"), "retrieval_observed.unit_ids"):
                    retrieval_ids.append(_require_nonblank_str(value, "retrieval_observed.unit_id"))
            state.retrieval = "retrieval_candidates_unused" if retrieval_ids else "retrieval_empty"
        elif state.branch == "legacy_no_model":
            if not _positive_no_retrieval_marker(envelope.get("runtime_snapshot")):
                raise _ProofGap(
                    "model_events_missing",
                    "legacy_no_model_without_retrieval_or_positive_no_retrieval_marker",
                )
            state.retrieval = "retrieval_absent"
        else:
            state.retrieval = "retrieval_absent"

        # ---- I. 结局 + 模板身份 ----
        kind = _require_str(commit.get("kind"), "commit_observed.kind")
        state.outcome = kind
        state.outcome_class = (
            "refusal"
            if kind in {"not_found", "no_answer"}
            else kind
            if kind in {"clarification", "knowledge_changed"}
            else "factual"
        )
        if kind not in NO_FACT_KINDS:
            raise _ProofGap("empty_set_not_proven", "outcome_kind_is_not_no_fact")
        if not _matches_no_fact_template(kind, commit.get("text")):
            raise _ProofGap("template_identity_unverified", f"template_mismatch:{kind}")

        return EmptyScopeProof(
            proven=True,
            code=EMPTY_USE_SCOPE_OK,
            shape=state.shape,
            branch=state.branch,
            retrieval=state.retrieval,
            outcome=state.outcome,
            outcome_class=state.outcome_class,
            detail="usage_layers_explicit_empty",
            usage_layers=(),
            candidate_sources=state.candidate_sources,
        )
    except _ProofGap as gap:
        return _not_proven(gap, state)
    except Exception as exc:  # noqa: BLE001 - 形状未知也必须 fail-closed
        return _not_proven(
            _ProofGap("internal_error", "unexpected_failure:" + type(exc).__name__), state
        )


def prove_empty_use_scope(evidence: Any) -> EmptyScopeProof:
    """证明（或拒绝证明）一次请求的已使用来源集合为空。"""

    return _prove(evidence)


def empty_use_scope_proof(evidence: Any) -> tuple[bool, str]:
    """冻结原语 ``(bool, reason)`` 形状的替代入口；未证明统一固定码。"""

    return prove_empty_use_scope(evidence).as_pair()
