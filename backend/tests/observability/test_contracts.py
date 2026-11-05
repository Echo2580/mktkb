"""T001：Trace 数据契约锁定测试（设计文档 §6.3 / §6.4）。

只依赖契约模块本身：不建索引、不读 .env、不访问网络、不调用模型 / OCR / embedding / rerank。
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from mktkb.observability.contracts import (
    CASE_SCHEMA_VERSION,
    GATE_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    OutcomeKind,
    SpanRecord,
    TraceMode,
    TracePath,
    TraceRecord,
    conditional_required_spans,
    required_spans,
    validate_required_spans,
)

RAG_FULL = frozenset({"parse", "recall", "fuse", "answer", "commit"})
RAG_RECALL = frozenset({"parse", "recall", "fuse", "commit"})
RAG_EARLY = frozenset({"parse", "commit"})
LEGACY_FULL = frozenset({"intent_parse", "retrieve", "model_answer", "answer_validate", "commit"})
LEGACY_NOT_FOUND = frozenset({"intent_parse", "retrieve", "commit"})
LEGACY_EARLY = frozenset({"intent_parse", "commit"})

# 设计 §6.4「基础必需 Span」表：8 行按 path/outcome 展开后的全部组合。
DESIGN_TABLE = [
    (TracePath.RAG, OutcomeKind.ANSWER, RAG_FULL),
    (TracePath.RAG, OutcomeKind.CONFLICT, RAG_FULL),
    (TracePath.RAG, OutcomeKind.CLARIFICATION, RAG_EARLY),
    (TracePath.RAG, OutcomeKind.NO_ANSWER, RAG_RECALL),
    (TracePath.RAG, OutcomeKind.AMBIGUOUS, RAG_RECALL),
    (TracePath.RAG, OutcomeKind.ERROR, RAG_EARLY),
    (TracePath.RAG, OutcomeKind.KNOWLEDGE_CHANGED, RAG_EARLY),
    (TracePath.LEGACY, OutcomeKind.ANSWER, LEGACY_FULL),
    (TracePath.LEGACY_WITH_RAG_CANDIDATES, OutcomeKind.ANSWER, LEGACY_FULL),
    (TracePath.LEGACY, OutcomeKind.NOT_FOUND, LEGACY_NOT_FOUND),
    (TracePath.LEGACY, OutcomeKind.CLARIFICATION, LEGACY_EARLY),
    (TracePath.LEGACY, OutcomeKind.SERVICE_ERROR, LEGACY_EARLY),
]

# 设计 §6.3 traces 全字段（顺序按文档，集合比较不看顺序）。
TRACE_FIELDS = {
    "trace_id",
    "request_id",
    "http_request_id",
    "attempt",
    "replayed",
    "previous_trace_id",
    "trace_schema_version",
    "mode",
    "scope",
    "path",
    "case_id",
    "dataset_version",
    "run_id",
    "index_revision",
    "manifest_sha256",
    "pipeline_version",
    "config_hash",
    "query_kind",
    "outcome_kind",
    "reason",
    "answer_source",
    "content_mode",
    "question_hash",
    "question_chars",
    "hash_algo",
    "hmac_key_id",
    "user_id_hash",
    "conversation_id_hash",
    "retrieval_counts_json",
    "filter_decisions_json",
    "fact_gate_json",
    "citation_refs_json",
    "pagination_json",
    "token_usage_json",
    "cost_json",
    "go_decision",
    "degraded_json",
    "latency_ms",
    "status",
    "error_code",
    "created_at",
}

# 设计 §6.3 spans 全字段。
SPAN_FIELDS = {
    "span_id",
    "trace_id",
    "parent_span_id",
    "name",
    "started_at",
    "duration_ms",
    "status",
    "attributes_json",
    "error_code",
}


# ---- §5.1 三套 Schema 版本常量 ----


def test_schema_version_constants_are_exact():
    assert TRACE_SCHEMA_VERSION == "mktkb.trace.v0.1"
    assert CASE_SCHEMA_VERSION == "mktkb.eval.case.v0.1"
    assert GATE_SCHEMA_VERSION == "mktkb.gate.v0.1"


# ---- §5.2 路径感知必需 Span：设计 §6.4 全表 ----


@pytest.mark.parametrize(("path", "outcome", "expected"), DESIGN_TABLE)
def test_required_spans_matches_design_table(path, outcome, expected):
    assert required_spans(path, outcome) == expected


def test_rag_clarification_does_not_require_answer_span():
    spans = required_spans(TracePath.RAG, OutcomeKind.CLARIFICATION)
    assert spans == frozenset({"parse", "commit"})
    assert "answer" not in spans
    assert "recall" not in spans


def test_legacy_not_found_does_not_require_expansion_or_answer():
    spans = required_spans(TracePath.LEGACY, OutcomeKind.NOT_FOUND)
    assert spans == frozenset({"intent_parse", "retrieve", "commit"})
    assert "query_expansion" not in spans
    assert "answer" not in spans
    assert "model_answer" not in spans


def test_legacy_with_rag_candidates_follows_legacy_rules():
    for outcome in (OutcomeKind.ANSWER, OutcomeKind.NOT_FOUND, OutcomeKind.CLARIFICATION, OutcomeKind.SERVICE_ERROR):
        assert required_spans(TracePath.LEGACY_WITH_RAG_CANDIDATES, outcome) == required_spans(
            TracePath.LEGACY, outcome
        )


def test_required_spans_accepts_plain_string_values():
    assert required_spans("rag", "answer") == RAG_FULL
    assert required_spans("legacy", "not_found") == LEGACY_NOT_FOUND


def test_required_spans_rejects_undefined_combination():
    # 设计 §6.4 表没有定义 RAG + not_found / service_error，也没有定义 legacy + error；
    # 契约 fail closed，而不是静默返回空集。
    with pytest.raises(ValueError):
        required_spans(TracePath.RAG, OutcomeKind.NOT_FOUND)
    with pytest.raises(ValueError):
        required_spans(TracePath.RAG, OutcomeKind.SERVICE_ERROR)
    with pytest.raises(ValueError):
        required_spans(TracePath.LEGACY, OutcomeKind.ERROR)


def test_required_spans_returns_frozenset():
    assert isinstance(required_spans(TracePath.RAG, OutcomeKind.ANSWER), frozenset)


# ---- T003d §5.9：rag+no_answer 的 reason-aware 例外（向后兼容的可选参数） ----

#: 检索前拒答的三种稳定 reason：parse+commit 后立即返回，没有 recall/fuse。
RAG_PRE_RETRIEVAL_REASONS = ("DOCUMENT_NOT_FOUND", "UNKNOWN_STORE", "RECORD_ONLY")


@pytest.mark.parametrize("reason", RAG_PRE_RETRIEVAL_REASONS)
def test_required_spans_rag_no_answer_pre_retrieval_reasons_need_only_parse_and_commit(reason):
    assert required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER, reason=reason) == RAG_EARLY
    assert required_spans("rag", "no_answer", reason=reason) == RAG_EARLY


@pytest.mark.parametrize(
    "reason", [None, "NO_EVIDENCE", "FIELD_NOT_RECORDED", "NO_RECORD_FOR_ENTITY", "document_not_found"]
)
def test_required_spans_rag_no_answer_other_reasons_still_require_recall_and_fuse(reason):
    """检索后拒答（以及未知/大小写不符的 reason）仍按设计 §6.4 原表要求 recall/fuse。"""
    assert required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER, reason=reason) == RAG_RECALL


def test_required_spans_reason_is_only_applied_to_rag_no_answer():
    """reason 例外只对 rag+no_answer 生效，其它 path/outcome 组合保持原表。"""
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER, reason="DOCUMENT_NOT_FOUND") == RAG_FULL
    assert (
        required_spans(TracePath.RAG, OutcomeKind.CLARIFICATION, reason="DOCUMENT_NOT_FOUND")
        == RAG_EARLY
    )
    assert (
        required_spans(TracePath.LEGACY, OutcomeKind.NOT_FOUND, reason="DOCUMENT_NOT_FOUND")
        == LEGACY_NOT_FOUND
    )


def test_required_spans_two_argument_calls_are_unchanged():
    """向后兼容：不传 reason 的旧调用行为与 §6.4 原表一致。"""
    assert required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER) == RAG_RECALL
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER) == RAG_FULL


def test_validate_required_spans_reads_reason_from_record():
    """``validate_required_spans`` 按 ``record.reason`` 应用 reason-aware 例外。"""
    early = TraceRecord(path="rag", outcome_kind="no_answer", reason="DOCUMENT_NOT_FOUND")
    assert validate_required_spans(early, ["parse", "commit"]) == []
    assert validate_required_spans(early, ["commit"]) == ["parse"]

    late = TraceRecord(path="rag", outcome_kind="no_answer", reason="NO_EVIDENCE")
    assert validate_required_spans(late, ["parse", "commit"]) == ["fuse", "recall"]
    assert validate_required_spans(late, ["parse", "recall", "fuse", "commit"]) == []

    no_reason = TraceRecord(path="rag", outcome_kind="no_answer")
    assert validate_required_spans(no_reason, ["parse", "commit"]) == ["fuse", "recall"]


# ---- T003d §5.11：legacy 解析级早退 reason-aware + 补充 outcome 行 ----

#: `_answer` 在 retrieve 之前返回 not_found 的四个稳定 reason（内部枚举）。
LEGACY_PRE_RETRIEVAL_REASONS = (
    "UNKNOWN_IDENTIFIER",
    "IDENTIFIER_NOT_RETRIEVABLE",
    "NO_INTENT",
    "UNRECORDED_FIELD",
)
LEGACY_PATHS = (TracePath.LEGACY, TracePath.LEGACY_WITH_RAG_CANDIDATES)


@pytest.mark.parametrize("path", LEGACY_PATHS)
@pytest.mark.parametrize("reason", LEGACY_PRE_RETRIEVAL_REASONS)
def test_required_spans_legacy_not_found_pre_retrieval_reasons_need_only_intent_parse_and_commit(
    path, reason
):
    """解析级早退（未执行 retrieve）只需 intent_parse + commit，两条 legacy 路径同规则。"""
    assert required_spans(path, OutcomeKind.NOT_FOUND, reason=reason) == LEGACY_EARLY
    assert required_spans(path.value, "not_found", reason=reason) == LEGACY_EARLY


@pytest.mark.parametrize("path", LEGACY_PATHS)
@pytest.mark.parametrize(
    "reason",
    [None, "NO_EVIDENCE", "UNKNOWN_STORE", "unrecorded_field", "DOCUMENT_NOT_FOUND"],
)
def test_required_spans_legacy_not_found_other_reasons_still_require_retrieve(path, reason):
    """检索后 not_found（及未知/大小写不符的 reason）仍要求 retrieve（fail safe）。"""
    assert required_spans(path, OutcomeKind.NOT_FOUND, reason=reason) == LEGACY_NOT_FOUND


def test_required_spans_legacy_supplement_rows_for_reachable_outcomes():
    """§5.11 补充行：legacy conflict 与“检索阶段” knowledge_changed 都在 retrieve 之后发生。"""
    supplement = frozenset({"intent_parse", "retrieve", "commit"})
    for path in LEGACY_PATHS:
        assert required_spans(path, OutcomeKind.CONFLICT) == supplement
        assert required_spans(path, OutcomeKind.KNOWLEDGE_CHANGED) == supplement


# T003d R1：legacy knowledge_changed 的两种真实执行形态（commit 升级 / 检索阶段或检索后）。
LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT = "KNOWLEDGE_CHANGED_AT_COMMIT"


@pytest.mark.parametrize("path", LEGACY_PATHS)
def test_required_spans_legacy_knowledge_changed_default_still_requires_retrieve(path):
    """R1 不降强度：缺省 / ``KNOWLEDGE_CHANGED`` / 未知大小写仍按补充行要求 retrieve。"""
    assert required_spans(path, OutcomeKind.KNOWLEDGE_CHANGED) == LEGACY_NOT_FOUND
    assert required_spans(path, OutcomeKind.KNOWLEDGE_CHANGED, reason="KNOWLEDGE_CHANGED") == LEGACY_NOT_FOUND
    assert (
        required_spans(path, OutcomeKind.KNOWLEDGE_CHANGED, reason="knowledge_changed_at_commit")
        == LEGACY_NOT_FOUND
    )


@pytest.mark.parametrize("path", LEGACY_PATHS)
def test_required_spans_legacy_knowledge_changed_at_commit_needs_only_intent_parse_and_commit(path):
    """R1：解析级早退后在 commit 阶段升级（未执行 retrieve）→ intent_parse + commit。"""
    assert (
        required_spans(path, OutcomeKind.KNOWLEDGE_CHANGED, reason=LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT)
        == LEGACY_EARLY
    )
    assert (
        required_spans(path.value, "knowledge_changed", reason=LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT)
        == LEGACY_EARLY
    )


def test_required_spans_commit_time_reason_does_not_cross_paths():
    """R1 的 reason 只作用于 legacy knowledge_changed，不改 RAG 行与其它 legacy outcome。"""
    assert (
        required_spans(
            TracePath.RAG, OutcomeKind.KNOWLEDGE_CHANGED, reason=LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT
        )
        == RAG_EARLY
    )
    assert (
        required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER, reason=LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT)
        == RAG_RECALL
    )
    assert (
        required_spans(TracePath.LEGACY, OutcomeKind.NOT_FOUND, reason=LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT)
        == LEGACY_NOT_FOUND
    )


def test_validate_required_spans_reads_commit_time_knowledge_changed_reason():
    """R1：``validate_required_spans`` 按 ``record.reason`` 应用 commit 升级形态。"""
    at_commit = TraceRecord(
        path="legacy",
        outcome_kind="knowledge_changed",
        reason=LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT,
    )
    assert validate_required_spans(at_commit, ["intent_parse", "commit"]) == []
    assert validate_required_spans(at_commit, ["commit"]) == ["intent_parse"]

    retrieved = TraceRecord(
        path="legacy", outcome_kind="knowledge_changed", reason="KNOWLEDGE_CHANGED"
    )
    assert validate_required_spans(retrieved, ["intent_parse", "commit"]) == ["retrieve"]
    assert validate_required_spans(retrieved, ["intent_parse", "retrieve", "commit"]) == []

    with_candidates = TraceRecord(
        path="legacy_with_rag_candidates",
        outcome_kind="knowledge_changed",
        reason=LEGACY_KNOWLEDGE_CHANGED_AT_COMMIT,
    )
    assert validate_required_spans(with_candidates, ["intent_parse", "commit"]) == []


def test_required_spans_legacy_unreachable_outcomes_stay_fail_closed():
    """legacy 产品路径不产生 no_answer / ambiguous / error：仍按契约缺口抛 ValueError。"""
    for outcome in (OutcomeKind.NO_ANSWER, OutcomeKind.AMBIGUOUS, OutcomeKind.ERROR):
        with pytest.raises(ValueError):
            required_spans(TracePath.LEGACY, outcome)


def test_required_spans_reason_does_not_cross_paths():
    """RAG 的 reason 集合不作用于 legacy，legacy 的 reason 集合也不作用于 RAG。"""
    assert required_spans(TracePath.LEGACY, OutcomeKind.NOT_FOUND, reason="DOCUMENT_NOT_FOUND") == LEGACY_NOT_FOUND
    assert required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER, reason="UNRECORDED_FIELD") == RAG_RECALL


def test_validate_required_spans_reads_legacy_reason_from_record():
    """``validate_required_spans`` 按 legacy 记录的 ``reason`` 应用 §5.11 例外。"""
    early = TraceRecord(path="legacy", outcome_kind="not_found", reason="UNRECORDED_FIELD")
    assert validate_required_spans(early, ["intent_parse", "commit"]) == []
    assert validate_required_spans(early, ["commit"]) == ["intent_parse"]

    no_reason = TraceRecord(path="legacy", outcome_kind="not_found")
    assert validate_required_spans(no_reason, ["intent_parse", "commit"]) == ["retrieve"]
    assert validate_required_spans(no_reason, ["intent_parse", "retrieve", "commit"]) == []

    conflict = TraceRecord(path="legacy_with_rag_candidates", outcome_kind="conflict")
    assert validate_required_spans(conflict, ["intent_parse", "retrieve", "commit"]) == []
    assert validate_required_spans(conflict, ["intent_parse", "commit"]) == ["retrieve"]


# ---- §5.3 条件必需 Span：只认四个键 ----


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"vector_enabled": True}, frozenset({"vector_recall"})),
        ({"rerank_enabled": True}, frozenset({"rerank"})),
        ({"expansion_triggered": True}, frozenset({"query_expansion"})),
        ({"index_sync_performed": True}, frozenset({"index_sync"})),
    ],
)
def test_conditional_spans_follow_execution_flags(attrs, expected):
    assert conditional_required_spans(attrs) == expected


def test_conditional_spans_empty_attrs_is_empty():
    assert conditional_required_spans({}) == frozenset()


def test_conditional_spans_unknown_keys_are_ignored():
    assert conditional_required_spans({"vector": True, "rerank": True, "unknown": True}) == frozenset()


def test_conditional_spans_multiple_flags_union():
    assert conditional_required_spans(
        {"vector_enabled": True, "rerank_enabled": True, "index_sync_performed": True}
    ) == frozenset({"vector_recall", "rerank", "index_sync"})


def test_conditional_spans_false_values_do_not_require():
    assert conditional_required_spans(
        {
            "vector_enabled": False,
            "rerank_enabled": False,
            "expansion_triggered": False,
            "index_sync_performed": False,
        }
    ) == frozenset()


# ---- 枚举取值 ----


def test_enum_values_match_design():
    assert {item.value for item in TraceMode} == {"replay", "local", "live"}
    assert {item.value for item in TracePath} == {"rag", "legacy", "legacy_with_rag_candidates"}
    assert {item.value for item in OutcomeKind} == {
        "answer",
        "clarification",
        "no_answer",
        "ambiguous",
        "conflict",
        "error",
        "not_found",
        "service_error",
        "knowledge_changed",
    }


# ---- §5.7 冻结 dataclass 与设计 §6.3 字段 ----


def test_trace_record_is_frozen_dataclass():
    assert dataclasses.is_dataclass(TraceRecord)
    assert TraceRecord.__dataclass_params__.frozen is True


def test_span_record_is_frozen_dataclass():
    assert dataclasses.is_dataclass(SpanRecord)
    assert SpanRecord.__dataclass_params__.frozen is True


def test_trace_record_covers_design_fields():
    assert {field.name for field in dataclasses.fields(TraceRecord)} == TRACE_FIELDS


def test_span_record_covers_design_fields():
    assert {field.name for field in dataclasses.fields(SpanRecord)} == SPAN_FIELDS


def test_trace_record_instantiates_and_serializes():
    record = TraceRecord(
        trace_id="trace-1",
        request_id="req-1",
        http_request_id="http-1",
        attempt=2,
        replayed=False,
        trace_schema_version=TRACE_SCHEMA_VERSION,
        mode="local",
        scope="retrieval_only",
        path="rag",
        case_id="B001",
        dataset_version="b0:label-1:0123456789ab",
        run_id="run-1",
        index_revision="rev-1",
        manifest_sha256="a" * 64,
        pipeline_version="0123456789ab",
        config_hash="0123456789ab",
        query_kind="record",
        outcome_kind="answer",
        reason="ok",
        answer_source="rag",
        content_mode="hash",
        question_hash="b" * 64,
        question_chars=5,
        hash_algo="hmac-sha256",
        hmac_key_id="k-0123456789ab",
        retrieval_counts_json='{"lexical": 3}',
        filter_decisions_json="{}",
        fact_gate_json="{}",
        citation_refs_json="[]",
        pagination_json="{}",
        token_usage_json="{}",
        cost_json="{}",
        go_decision="go",
        degraded_json="{}",
        latency_ms=42,
        status="ok",
        error_code=None,
        created_at="2026-11-04T00:00:00Z",
    )
    payload = dataclasses.asdict(record)
    assert payload["trace_id"] == "trace-1"
    assert payload["retrieval_counts_json"] == '{"lexical": 3}'
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert '"trace_id": "trace-1"' in text


def test_span_record_instantiates_and_serializes():
    span = SpanRecord(
        span_id="span-1",
        trace_id="trace-1",
        parent_span_id=None,
        name="parse",
        started_at="2026-11-04T00:00:00Z",
        duration_ms=3,
        status="ok",
        attributes_json="{}",
        error_code=None,
    )
    payload = dataclasses.asdict(span)
    assert payload["name"] == "parse"
    json.dumps(payload, ensure_ascii=False, sort_keys=True)


def test_default_optional_fields_are_none_and_schema_version_is_bound():
    payload = dataclasses.asdict(TraceRecord())
    assert payload["trace_id"] is None
    assert payload["previous_trace_id"] is None
    assert payload["case_id"] is None
    assert payload["latency_ms"] is None
    assert payload["trace_schema_version"] == TRACE_SCHEMA_VERSION
    assert dataclasses.asdict(SpanRecord())["parent_span_id"] is None


def test_records_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        TraceRecord().status = "error"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        SpanRecord().name = "parse"  # type: ignore[misc]
