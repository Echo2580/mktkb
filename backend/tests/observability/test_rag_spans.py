"""T003c：RAG 路径 Span 埋点（handoff §5 八条验收的开发者自测）。

本文件只验证**观测行为**与**无 trace 时行为不变**，不重写业务期望：

- 每个用例都在 ``tmp_path`` 下建隔离 SQLite 索引，``provider_mode=offline``，
  零真实模型/OCR/embedding/rerank 调用；
- Trace 只通过 ``start_trace(..., repo=CapturingRepo())`` 捕获（内存，不写任何 DB），
  ``path=TracePath.RAG`` 由用例显式给出（真实 path/outcome 属 T003d 接线）；
- 断言 ``required_spans`` / ``validate_required_spans`` 的路径感知完整性、
  Span 父子结构、条件 Span 的 canonical 位置、attributes 的 canonical JSON 与
  内容隐私（不含问题/答案/上下文原文）、异常路径 status=error 且异常照旧上抛。

本包不改业务逻辑：固定问题的 ``RagIndex.ask`` 返回值在无 trace 与有 trace 两种
运行下必须一致（仅耗时字段可不同）。
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterator

import pytest

from mktkb.observability import trace_attrs
from mktkb.observability.contracts import (
    OutcomeKind,
    TraceMode,
    TracePath,
    conditional_required_spans,
    required_spans,
    validate_required_spans,
)
from mktkb.observability.tracer import current_trace, start_trace
from mktkb.rag import (
    AtomicUnit,
    DocumentSpec,
    RagAnswer,
    RagConfig,
    RagIndex,
    RetrievalResult,
)

BUSINESS_DATE = "2026-10-28"
#: 有答案的记录型问题（与既有 RAG 测试同一装配；答案文本含“店内外侧”）。
RECORD_QUESTION = "滨江店的宣传海报放在哪里？"
#: 空索引上的文档型问题：检索阶段真实执行后 no_answer（NO_EVIDENCE）。
DOCUMENT_QUESTION = "公司的年度愿景是什么？"
#: parse 阶段早退的澄清：无词项 → EMPTY_QUERY。
CLARIFICATION_QUESTION = "？"
#: 检索前早退的 no_answer：问题点名了未收录的资料 → DOCUMENT_NOT_FOUND。
MISSING_DOCUMENT_QUESTION = "促销活动台账在哪里？"

RECORD_ROW = {
    "标识": "QF01",
    "门店": "滨江店",
    "物品": "宣传海报",
    "别名": "海报",
    "位置": "店内外侧",
    "数量": 40,
}
ANSWER_ONLY_TEXT = "店内外侧"  # 只出现在答案/证据正文里，绝不能进 trace

#: 有 trace 的 answer 路径实际执行的全部 Span（未执行通道不得出现）。
EXPECTED_ANSWER_SPANS = {
    "parse",
    "recall",
    "exact_recall",
    "lexical_recall",
    "vector_recall",
    "embedding_query",
    "hard_filter",
    "fuse",
    "rerank",
    "answer",
    "fact_validate",
    "commit",
}

_OUTCOME_BY_KIND = {
    "answer": OutcomeKind.ANSWER,
    "clarification": OutcomeKind.CLARIFICATION,
    "no_answer": OutcomeKind.NO_ANSWER,
    "ambiguous": OutcomeKind.AMBIGUOUS,
    "conflict": OutcomeKind.CONFLICT,
    "error": OutcomeKind.ERROR,
}


# ---- 索引装配（只写 tmp_path，不读 .env、不访问外网） ----


def _config(root: Path, **overrides: Any) -> RagConfig:
    values: dict[str, Any] = {
        "provider_mode": "offline",
        "data_dir": root,
        "business_date": BUSINESS_DATE,
        "chunk_max_chars": 420,
        "chunk_max_units": 3,
        "chunk_overlap_units": 1,
        "top_k": 5,
        "page_size": 10,
        "vector_candidate_limit": 50,
        "rerank_top_n": 20,
    }
    values.update(overrides)
    return RagConfig(**values)


@contextmanager
def _rag_index(root: Path, *, name: str = "rag", **overrides: Any) -> Iterator[RagIndex]:
    index = RagIndex(root / f"{name}-{uuid.uuid4().hex}.sqlite3", config=_config(root, **overrides))
    try:
        yield index
    finally:
        index.close()


def _document(code: str, *, title: str = "测试资料") -> DocumentSpec:
    return DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=f"{code}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=(code * 64)[:64],
    )


def _add_records(index: RagIndex, rows: list[dict[str, Any]], *, code: str = "D01") -> DocumentSpec:
    doc = _document(code)
    units: list[AtomicUnit] = []
    for ordinal, row in enumerate(rows):
        row_number = 7 + ordinal
        units.append(
            AtomicUnit(
                unit_id=f"{code}-{ordinal}-{uuid.uuid4().hex[:6]}",
                doc_id=code,
                version_id=doc.version_id,
                kind="table_row",
                ordinal=ordinal,
                unit_key=f"sheet:物品位置:row:{row_number}",
                text="；".join(f"{name}: {value}" for name, value in row.items()),
                fields=dict(row),
                sheet="物品位置",
                locator={"sheet": "物品位置", "row": row_number, "header_row": 6},
                header_row=6,
                row_number=row_number,
                title=doc.title,
            )
        )
    index.add_document(doc, units, embed=True)
    return doc


# ---- Trace 捕获与断言辅助 ----


class CapturingRepo:
    """``write_best_effort(record, spans)`` 的内存替身（不建库、不写文件）。"""

    def __init__(self) -> None:
        self.writes: list[tuple[Any, list[Any]]] = []

    def write_best_effort(self, record: Any, spans: list[Any]) -> None:
        self.writes.append((record, list(spans)))

    @property
    def last(self) -> tuple[Any, list[Any]]:
        assert self.writes, "Trace 未写入：finish 没有调用 write_best_effort"
        return self.writes[-1]


@contextmanager
def _traced(repo: CapturingRepo, *, question: str, path: TracePath = TracePath.RAG):
    with start_trace(
        http_request_id="http-" + uuid.uuid4().hex,
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=path,
        question=question,
        repo=repo,
    ) as trace:
        yield trace


def _ask_traced(
    index: RagIndex,
    question: str,
    *,
    outcome: OutcomeKind | None = None,
    conversation_id: str | None = None,
    repo: CapturingRepo | None = None,
) -> tuple[RagAnswer, Any, list[Any]]:
    """在显式 RAG trace 中执行一次 ``RagIndex.ask``，返回答案与落库记录。"""
    repo = repo or CapturingRepo()
    conversation_id = conversation_id or "c-" + uuid.uuid4().hex
    with _traced(repo, question=question) as trace:
        answer = index.ask(question, user_id="u", conversation_id=conversation_id)
        trace.set_outcome(outcome or _OUTCOME_BY_KIND[answer.kind], answer.reason)
    record, spans = repo.last
    return answer, record, spans


def _names(spans: list[Any]) -> list[str]:
    return [span.name for span in spans]


def _one(spans: list[Any], name: str) -> Any:
    matches = [span for span in spans if span.name == name]
    assert len(matches) == 1, f"Span {name!r} 应恰有一个，实际 {[span.name for span in spans]}"
    return matches[0]


def _attributes(span: Any) -> dict[str, Any]:
    payload = json.loads(span.attributes_json or "{}")
    assert isinstance(payload, dict)
    return payload


def _canonical(value: str | None) -> Any:
    """断言文本是 canonical JSON（ensure_ascii=False, sort_keys=True, 紧凑分隔符）。"""
    assert value is not None, "期望 canonical JSON 文本，实际为 None"
    parsed = json.loads(value)
    assert trace_attrs.canonical_json(parsed) == value, f"不是 canonical JSON：{value!r}"
    return parsed


def _forbid_content(record: Any, spans: list[Any], *needles: str) -> None:
    """记录/属性里不得出现问题、答案或证据原文（设计 §6.5）。"""
    blobs: list[str] = []
    for field in fields(record):
        value = getattr(record, field.name)
        blobs.append("" if value is None else str(value))
    for span in spans:
        blobs.extend(
            [
                "" if span.name is None else span.name,
                "" if span.error_code is None else span.error_code,
                "" if span.attributes_json is None else span.attributes_json,
            ]
        )
    joined = "\n".join(blobs)
    for needle in needles:
        assert needle not in joined, f"trace 泄漏了内容原文：{needle!r}"


# ---- §5.1 无 trace 时零行为变化 ----


def _strip_timings(payload: Any) -> Any:
    """去掉所有机器相关的耗时字段，使“有无 trace”两次运行可逐字段对照。"""
    if isinstance(payload, dict):
        return {
            key: _strip_timings(value)
            for key, value in payload.items()
            if key not in {"elapsed_ms", "ms", "vector_query_ms", "latency_ms"}
        }
    if isinstance(payload, list):
        return [_strip_timings(item) for item in payload]
    return payload


def test_no_trace_matches_traced_answer_and_creates_nothing(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        plain = index.ask(RECORD_QUESTION, user_id="u", conversation_id="c-same")
        assert current_trace() is None, "未开启 trace 时不得有隐式 Trace"
        index.clear_state("u", "c-same")
        traced_answer, record, spans = _ask_traced(
            index, RECORD_QUESTION, conversation_id="c-same"
        )

    assert spans, "显式 trace 必须产生 Span（否则下面的对照没有意义）"
    plain_payload = _strip_timings(plain.to_dict())
    traced_payload = _strip_timings(traced_answer.to_dict())
    # 唯一允许的差异是耗时（业务字段、引用、事实、state、diagnostics 其余键必须一致）。
    assert traced_payload == plain_payload
    assert record.outcome_kind == "answer"
    assert record.status == "ok"


def test_no_trace_does_not_touch_observability(tmp_path: Path) -> None:
    """没有 repo/trace 时，观测入口全部 no-op，不会创建任何记录。"""
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        with trace_attrs.span("not-recorded") as handle:
            handle.annotate(count=1)
            trace_attrs.annotate_trace(fact_gate_json={"checked": False})
            answer = index.ask(RECORD_QUESTION, user_id="u", conversation_id="c-noop")
    assert current_trace() is None
    assert answer.kind == "answer"
    # 整个 tmp_path 下只有 RAG 索引本身，没有 trace 库/旁路文件。
    leftovers = sorted(path.name for path in tmp_path.rglob("*") if path.is_file())
    assert leftovers, "RAG 索引应存在"
    assert all("trace" not in name.lower() for name in leftovers)


# ---- §5.2 answer 路径 Span 完整且父子结构正确 ----


def test_answer_path_span_set_and_hierarchy(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        answer, record, spans = _ask_traced(index, RECORD_QUESTION)

    assert answer.kind == "answer"
    names = set(_names(spans))
    assert names == EXPECTED_ANSWER_SPANS, f"answer 路径 Span 集合不符：{sorted(names)}"
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER) <= names
    assert validate_required_spans(record, names) == []
    assert record.path == "rag"
    assert record.outcome_kind == "answer"
    assert record.status == "ok"

    recall = _one(spans, "recall")
    assert recall.parent_span_id is None
    for child in ("exact_recall", "lexical_recall", "vector_recall"):
        assert _one(spans, child).parent_span_id == recall.span_id, f"{child} 必须挂在 recall 下"
    assert _one(spans, "embedding_query").parent_span_id == _one(spans, "vector_recall").span_id

    fuse = _one(spans, "fuse")
    assert fuse.parent_span_id is None
    assert _one(spans, "hard_filter").parent_span_id == fuse.span_id
    assert _one(spans, "rerank").parent_span_id == fuse.span_id

    answer_span = _one(spans, "answer")
    assert answer_span.parent_span_id is None
    assert _one(spans, "fact_validate").parent_span_id == answer_span.span_id
    assert _one(spans, "parse").parent_span_id is None
    assert _one(spans, "commit").parent_span_id is None

    assert _names(spans)[0] == "parse"
    assert _names(spans)[-1] == "commit"
    assert all(span.status == "ok" for span in spans)
    assert all(span.error_code is None for span in spans)
    assert all(isinstance(span.duration_ms, int) and span.duration_ms >= 0 for span in spans)
    assert all(span.trace_id == record.trace_id for span in spans)
    for span in spans:
        assert _canonical(span.attributes_json) is not None

    assert _attributes(_one(spans, "parse"))["mode"] == "record"
    assert _attributes(recall) == {
        "exact": 1,
        "hints": 0,
        "lexical": 1,
        "vector": 1,
        "vector_enabled": True,
    }
    assert _attributes(_one(spans, "exact_recall")) == {"candidates": 1}
    assert _attributes(_one(spans, "vector_recall"))["candidates"] == 1
    assert _attributes(_one(spans, "hard_filter"))["candidates"] >= 1
    assert _attributes(_one(spans, "fuse"))["candidates"] >= 1


# ---- §5.3 条件 Span 与 canonical 位置 ----


def test_conditional_spans_agree_with_filter_decisions_json(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        _, record, spans = _ask_traced(index, RECORD_QUESTION)

    decisions = _canonical(record.filter_decisions_json)
    assert decisions["vector_enabled"] is True
    assert decisions["rerank_enabled"] is True
    conditional = conditional_required_spans(decisions)
    assert conditional == {"vector_recall", "rerank"}
    assert conditional <= set(_names(spans))
    assert validate_required_spans(record, set(_names(spans))) == []

    # 条件属性只按 tracer 约定并入 filter_decisions_json（顶层键），不再散落其它字段。
    for name in ("retrieval_counts_json", "fact_gate_json", "citation_refs_json", "pagination_json"):
        payload = getattr(record, name)
        if payload:
            parsed = json.loads(payload)
            for flag in ("vector_enabled", "rerank_enabled"):
                assert flag not in parsed, f"条件属性不应写进 {name}"


def test_vector_span_absent_when_query_embedding_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def _unexpected_embed(questions, purpose="document"):  # pragma: no cover - 断言不调用
        calls.append(tuple(questions))
        raise AssertionError("disable_query_embedding=True 时不得调用 embedding")

    with _rag_index(tmp_path, disable_query_embedding=True) as index:
        _add_records(index, [RECORD_ROW])
        monkeypatch.setattr(index.embedder, "embed", _unexpected_embed)
        answer, record, spans = _ask_traced(index, RECORD_QUESTION)

    assert calls == [], "查询向量面关闭时不得发生 embedding 调用"
    assert answer.kind == "answer"
    names = set(_names(spans))
    assert "vector_recall" not in names
    assert "embedding_query" not in names
    decisions = _canonical(record.filter_decisions_json)
    assert decisions["vector_enabled"] is False
    assert conditional_required_spans(decisions) == {"rerank"}
    assert validate_required_spans(record, names) == []
    counts = _canonical(record.retrieval_counts_json)
    assert counts["vector"] == 0


def test_rerank_span_only_when_rerank_actually_executes(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:  # 空索引：融合结果为空 → 不进入重排
        answer, record, spans = _ask_traced(index, DOCUMENT_QUESTION)

    assert answer.kind == "no_answer"
    names = set(_names(spans))
    assert "rerank" not in names
    assert "hard_filter" in names and "fuse" in names
    decisions = _canonical(record.filter_decisions_json)
    assert decisions["rerank_enabled"] is False
    assert conditional_required_spans(decisions) == {"vector_recall"}
    assert validate_required_spans(record, names) == []


# ---- §5.4 早退路径不伪造 Span ----


def test_clarification_early_exit_has_only_parse_and_commit(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        answer, record, spans = _ask_traced(index, CLARIFICATION_QUESTION)

    assert answer.kind == "clarification"
    assert set(_names(spans)) == {"parse", "commit"}
    assert "answer" not in _names(spans)
    assert "recall" not in _names(spans) and "fuse" not in _names(spans)
    assert validate_required_spans(record, set(_names(spans))) == []
    assert record.outcome_kind == "clarification"


def test_pre_retrieval_no_answer_does_not_fabricate_retrieval_spans(tmp_path: Path) -> None:
    """DOCUMENT_NOT_FOUND 在检索前返回：不得为凑 no_answer 必需集伪造 recall/fuse/answer。

    设计 §6.4 的 ``rag+no_answer`` 表按“检索后拒答”定义；本用例只锁定“未执行不伪造”。
    """
    with _rag_index(tmp_path) as index:  # 空词表 → 点名资料必然未收录
        answer, record, spans = _ask_traced(index, MISSING_DOCUMENT_QUESTION)

    assert answer.kind == "no_answer"
    assert answer.reason == "DOCUMENT_NOT_FOUND"
    assert set(_names(spans)) == {"parse", "commit"}
    assert not {"recall", "fuse", "answer", "fact_validate"} & set(_names(spans))
    assert record.outcome_kind == "no_answer"


def test_retrieval_no_answer_passes_integrity(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        answer, record, spans = _ask_traced(index, DOCUMENT_QUESTION)

    assert answer.kind == "no_answer"
    assert answer.reason == "NO_EVIDENCE"
    names = set(_names(spans))
    assert required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER) <= names
    assert "exact_recall" not in names, "document 模式没有精确通道，不应出现 exact_recall"
    assert "fact_validate" not in names, "没有答案时不得伪造 fact_validate"
    assert validate_required_spans(record, names) == []
    assert record.outcome_kind == "no_answer"


def test_conflict_path_includes_answer_and_fact_validate(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [{**RECORD_ROW, "位置": "店内外侧"}], code="A")
        _add_records(index, [{**RECORD_ROW, "位置": "D区暂存柜"}], code="B")
        answer, record, spans = _ask_traced(index, "滨江店的宣传海报位置")

    assert answer.kind == "conflict"
    assert answer.reason == "CONFLICTING_VALUES"
    names = set(_names(spans))
    assert {"parse", "recall", "fuse", "answer", "fact_validate", "commit"} <= names
    assert validate_required_spans(record, names) == []
    assert record.outcome_kind == "conflict"
    assert record.status == "ok"


def test_knowledge_changed_path_has_parse_and_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mktkb.rag.errors import KnowledgeChanged

    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])

        def _raise_changed(plan, *, limit=None):
            raise KnowledgeChanged("检索期间知识库版本发生变化")

        monkeypatch.setattr(index, "search", _raise_changed)
        answer, record, spans = _ask_traced(
            index, RECORD_QUESTION, outcome=OutcomeKind.KNOWLEDGE_CHANGED
        )

    assert answer.kind == "error"
    assert answer.reason == "KNOWLEDGE_CHANGED"
    assert set(_names(spans)) == {"parse", "commit"}
    assert validate_required_spans(record, set(_names(spans))) == []
    assert record.outcome_kind == "knowledge_changed"


# ---- §5.5 attributes：canonical JSON / 计数与稳定引用 / 无内容原文 ----


def test_trace_and_span_attributes_are_canonical_and_content_free(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        answer, record, spans = _ask_traced(index, RECORD_QUESTION)

    counts = _canonical(record.retrieval_counts_json)
    assert counts == dict(answer.diagnostics["recall"])
    assert all(isinstance(value, int) and value >= 0 for value in counts.values())

    decisions = _canonical(record.filter_decisions_json)
    assert decisions["mode"] == "record"
    assert isinstance(decisions["enumerate"], bool)
    assert all(isinstance(key, str) for key in decisions["applied_filters"])

    pagination = _canonical(record.pagination_json)
    assert pagination["total"] == int(answer.diagnostics["total"])
    assert pagination["returned"] == int(answer.diagnostics["returned"])
    assert pagination["has_more"] is False
    assert isinstance(pagination["page"], int) and isinstance(pagination["page_size"], int)

    fact_gate = _canonical(record.fact_gate_json)
    assert fact_gate == {"checked": True, "passed": True, "units": len(answer.facts), "code": None}

    refs = _canonical(record.citation_refs_json)
    assert refs, "有答案时 citation_refs_json 不应为空"
    for ref in refs:
        assert set(ref) == {"doc_id", "unit_id_hash", "locator"}
        assert isinstance(ref["doc_id"], str) and ref["doc_id"]
        assert isinstance(ref["unit_id_hash"], str) and len(ref["unit_id_hash"]) == 16
        assert isinstance(ref["locator"], dict)
    # 稳定引用不透出原始 chunk_id UUID，也不含正文。
    raw_chunk_id = answer.citations[0].source_id
    assert raw_chunk_id not in record.citation_refs_json
    assert ANSWER_ONLY_TEXT not in record.citation_refs_json

    assert _canonical(record.degraded_json) == []
    assert record.index_revision == str(answer.citations[0].revision)

    # 记录里只有问题摘要/长度，没有原文。
    assert record.question_hash is not None and len(record.question_hash) == 64
    assert RECORD_QUESTION not in record.question_hash
    assert record.question_chars == len(RECORD_QUESTION)

    _forbid_content(record, spans, RECORD_QUESTION, ANSWER_ONLY_TEXT, raw_chunk_id)

    # 每个 Span 的 attributes 也必须是 canonical JSON，且只含计数/布尔/稳定字符串。
    for span in spans:
        attributes = _canonical(span.attributes_json)
        assert isinstance(attributes, dict)
        for value in attributes.values():
            assert isinstance(value, (int, float, bool, str, list, dict, type(None)))


def test_commit_span_and_citation_refs_use_stable_references(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        _, record, spans = _ask_traced(index, RECORD_QUESTION)

    commit_attrs = _attributes(_one(spans, "commit"))
    assert commit_attrs == {"last_kind": "answer", "turn": 1}
    refs = json.loads(record.citation_refs_json)
    assert [ref["doc_id"] for ref in refs] == ["D01"]


# ---- §5.6 异常路径：Span status=error，异常类型/时机不变 ----


def test_internal_exception_marks_span_error_and_still_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mktkb.rag import retrieval

    def _boom(*args, **kwargs):
        raise RuntimeError("TRACE-TEST-BOOM")

    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        monkeypatch.setattr(retrieval, "_fuse", _boom)
        repo = CapturingRepo()
        with pytest.raises(RuntimeError, match="TRACE-TEST-BOOM"):
            with _traced(repo, question=RECORD_QUESTION):
                index.ask(RECORD_QUESTION, user_id="u", conversation_id="c-err")

    record, spans = repo.last
    assert current_trace() is None
    fuse = _one(spans, "fuse")
    assert fuse.status == "error"
    assert fuse.error_code == "RuntimeError"
    assert record.status == "error"
    assert record.error_code == "RuntimeError"


def test_embedding_failure_marks_embedding_span_error_without_new_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mktkb.rag.errors import EmbeddingUnavailable

    def _embed_down(questions, purpose="document"):
        raise EmbeddingUnavailable("embedding provider unavailable")

    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        monkeypatch.setattr(index.embedder, "embed", _embed_down)
        answer, record, spans = _ask_traced(index, RECORD_QUESTION)

    # 既有降级语义：查询向量失败不改变异常时机（不抛给调用方），精确/FTS 仍作答。
    assert answer.kind == "answer"
    embed_span = _one(spans, "embedding_query")
    assert embed_span.status == "error"
    assert embed_span.error_code == "EmbeddingUnavailable"
    assert _canonical(record.degraded_json) == ["vector"]
    assert _canonical(record.retrieval_counts_json)["vector"] == 0
    assert validate_required_spans(record, set(_names(spans))) == []


def test_fact_rejection_marks_fact_span_error_and_returns_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mktkb.rag.errors import ForgedValue
    from mktkb.rag.facts import FactValidator

    def _reject(self, text, facts, **kwargs):
        raise ForgedValue("测试注入：回答包含无依据的值")

    monkeypatch.setattr(FactValidator, "validate_record_text", _reject)
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        answer, record, spans = _ask_traced(index, RECORD_QUESTION)

    assert answer.kind == "no_answer"
    assert answer.reason == "FORGED_VALUE"
    fact_span = _one(spans, "fact_validate")
    assert fact_span.status == "error"
    assert fact_span.error_code == "ForgedValue"
    assert _canonical(record.fact_gate_json) == {
        "checked": True,
        "passed": False,
        "units": 1,
        "code": "FORGED_VALUE",
    }
    assert validate_required_spans(record, set(_names(spans))) == []


# ---- 结构不变 / 多次执行互不串扰 / trace_attrs 纯函数 ----


def test_public_result_structures_unchanged() -> None:
    assert [item.name for item in fields(RagAnswer)] == [
        "kind",
        "question",
        "text",
        "state",
        "citations",
        "facts",
        "reason",
        "answer_source",
        "diagnostics",
    ]
    assert [item.name for item in fields(RetrievalResult)] == [
        "plan",
        "revision",
        "exact",
        "lexical",
        "vector",
        "fused",
        "evidence",
        "total",
        "returned",
        "has_more",
        "next_page",
        "recall_counts",
        "diagnostics",
        "degraded",
        "effective_hints",
    ]


def test_each_ask_gets_its_own_trace(tmp_path: Path) -> None:
    with _rag_index(tmp_path) as index:
        _add_records(index, [RECORD_ROW])
        _, first_record, first_spans = _ask_traced(index, RECORD_QUESTION)
        _, second_record, second_spans = _ask_traced(index, RECORD_QUESTION)

    assert first_record.trace_id != second_record.trace_id
    assert {span.trace_id for span in first_spans} == {first_record.trace_id}
    assert {span.trace_id for span in second_spans} == {second_record.trace_id}
    assert _names(first_spans) == _names(second_spans)
    assert {span.span_id for span in first_spans}.isdisjoint(
        {span.span_id for span in second_spans}
    )


def test_trace_attrs_span_is_noop_without_trace() -> None:
    assert current_trace() is None
    with trace_attrs.span("ignored", answer="x") as handle:
        handle.annotate(count=1)
        trace_attrs.annotate_trace(fact_gate_json={"checked": False})
    assert current_trace() is None


def test_trace_attrs_helpers_are_pure_and_stable() -> None:
    assert trace_attrs.canonical_json({"b": 1, "a": "中文"}) == '{"a":"中文","b":1}'
    first = trace_attrs.hash_ref("unit-1")
    assert len(first) == 16
    assert first == trace_attrs.hash_ref("unit-1")
    assert first != trace_attrs.hash_ref("unit-2")
    assert "unit-1" not in first
    with pytest.raises(ValueError):
        trace_attrs.hash_ref("")
    with pytest.raises(ValueError):
        trace_attrs.hash_ref("unit-1", length=7)
