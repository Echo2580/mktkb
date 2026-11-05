"""T003c 独立验收：RAG 路径 Span 埋点逐条探针（独立于开发测试）。

覆盖 handoff §5.1–§5.6 与硬约束；只使用公开 API（RagIndex / start_trace /
TraceRepository / contracts），不 import 开发测试的 helper，不写入仓库。

用法：python probe_traced.py <report.json> <work_root>
"""

from __future__ import annotations

import json
import socket
import sys
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterator

REPORT: list[dict[str, Any]] = []
RECORD_Q = "滨江店的宣传海报放在哪里？"
DOC_Q = "公司的年度愿景是什么？"
CLAR_Q = "？"
MISSING_Q = "促销活动台账在哪里？"
CONFLICT_Q = "滨江店的宣传海报位置"
ROW = {
    "标识": "QF01",
    "门店": "滨江店",
    "物品": "宣传海报",
    "别名": "海报",
    "位置": "店内外侧",
    "数量": 40,
}
ANSWER_TEXT = "店内外侧"
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


def check(name: str):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            try:
                detail = fn(*args, **kwargs)
                REPORT.append({"check": name, "ok": True, "detail": detail})
                print(f"PASS {name}")
                return detail
            except Exception as exc:  # noqa: BLE001
                REPORT.append(
                    {
                        "check": name,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    }
                )
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
                return None

        return wrapper

    return decorator


def canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assert_canonical_text(text: str | None, where: str) -> Any:
    assert isinstance(text, str) and text, f"{where} 不是非空 JSON 文本：{text!r}"
    parsed = json.loads(text)
    assert canonical(parsed) == text, f"{where} 不是 canonical JSON：{text!r}"
    return parsed


# ---- fixtures ----
def make_config(root: Path, **overrides: Any):
    from mktkb.rag import RagConfig

    values: dict[str, Any] = {
        "provider_mode": "offline",
        "data_dir": root,
        "business_date": "2026-10-28",
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
def make_index(root: Path, name: str = "rag", **overrides: Any) -> Iterator[Any]:
    from mktkb.rag import RagIndex

    root.mkdir(parents=True, exist_ok=True)
    index = RagIndex(
        root / f"{name}-{uuid.uuid4().hex}.sqlite3",
        config=make_config(root, **overrides),
    )
    try:
        yield index
    finally:
        index.close()


def add_records(index: Any, rows: list[dict[str, Any]], *, code: str = "D01") -> None:
    from mktkb.rag import AtomicUnit, DocumentSpec

    doc = DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=f"{code}.xlsx",
        title=f"测试资料{code}",
        file_kind="xlsx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=(code * 64)[:64],
    )
    units = []
    for ordinal, row in enumerate(rows):
        row_number = 7 + ordinal
        units.append(
            AtomicUnit(
                unit_id=f"{code}-fixed-{ordinal}",
                doc_id=code,
                version_id=f"{code}-v1",
                kind="table_row",
                ordinal=ordinal,
                unit_key=f"sheet:物品位置:row:{row_number}",
                text="；".join(f"{name}: {value}" for name, value in row.items()),
                fields=dict(row),
                sheet="物品位置",
                locator={"sheet": "物品位置", "row": row_number, "header_row": 6},
                header_row=6,
                row_number=row_number,
                title=f"测试资料{code}",
            )
        )
    index.add_document(doc, units, embed=True)


def add_text_document(index: Any, text: str, *, code: str = "D02") -> None:
    from mktkb.rag import AtomicUnit, DocumentSpec

    doc = DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=f"{code}.docx",
        title=f"测试资料{code}",
        file_kind="docx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=(code * 64)[:64],
    )
    unit = AtomicUnit(
        unit_id=f"{code}-fixed-0",
        doc_id=code,
        version_id=f"{code}-v1",
        kind="paragraph",
        ordinal=0,
        unit_key="paragraph:1",
        text=text,
        fields={},
        locator={"paragraph": 1, "page": 1},
        title=f"测试资料{code}",
    )
    index.add_document(doc, [unit], embed=True)


class Repo:
    def __init__(self) -> None:
        self.writes: list[tuple[Any, list[Any]]] = []
    def write_best_effort(self, record: Any, spans: list[Any]) -> None:
        self.writes.append((record, list(spans)))

    @property
    def last(self):
        assert self.writes, "no trace written"
        return self.writes[-1]


def start(question: str, repo: Repo, **kwargs: Any):
    from mktkb.observability.contracts import TraceMode, TracePath
    from mktkb.observability.tracer import start_trace

    return start_trace(
        http_request_id="probe-" + uuid.uuid4().hex,
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        question=question,
        repo=repo,
        **kwargs,
    )


def run_traced(index: Any, question: str, *, outcome: Any = None, conversation_id: str = "c-probe"):
    repo = Repo()
    with start(question, repo) as trace:
        answer = index.ask(question, user_id="u", conversation_id=conversation_id)
        if outcome is not None:
            trace.set_outcome(outcome, answer.reason)
        else:
            kind_map = {
                "answer": "answer",
                "clarification": "clarification",
                "no_answer": "no_answer",
                "ambiguous": "ambiguous",
                "conflict": "conflict",
                "error": "error",
            }
            trace.set_outcome(kind_map[answer.kind], answer.reason)
    record, spans = repo.last
    return answer, record, spans


def names(spans: list[Any]) -> list[str]:
    return [span.name for span in spans]


def one(spans: list[Any], name: str):
    matches = [span for span in spans if span.name == name]
    assert len(matches) == 1, f"span {name} count={len(matches)} all={names(spans)}"
    return matches[0]


def attrs(span: Any) -> dict[str, Any]:
    return assert_canonical_text(span.attributes_json, f"span {span.name} attributes_json")


def span_dump(spans: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": span.name,
            "parent": span.parent_span_id,
            "status": span.status,
            "error_code": span.error_code,
            "duration_ms": span.duration_ms,
            "attributes": attrs(span),
        }
        for span in spans
    ]


def record_dump(record: Any) -> dict[str, Any]:
    return {field.name: getattr(record, field.name) for field in fields(record)}


# ---- §5.1 无 trace ----
@check("5.1a no trace: current_trace None, no observability files, answer intact")
def check_no_trace(work: Path) -> dict[str, Any]:
    from mktkb.observability.tracer import current_trace

    root = work / "no-trace"
    with make_index(root) as index:
        add_records(index, [ROW])
        answer = index.ask(RECORD_Q, user_id="u", conversation_id="c-plain")
        active = current_trace()
        files = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
    assert active is None, f"无 trace 时 current_trace() 非 None：{active!r}"
    assert answer.kind == "answer"
    assert answer.text == "根据资料，滨江店的宣传海报的位置：店内外侧。", answer.text
    bad = [name for name in files if "trace" in name.lower() or "observ" in name.lower()]
    assert not bad, f"无 trace 运行产生了观测文件：{bad}"
    return {"answer_kind": answer.kind, "files": files, "current_trace": None}


# ---- §5.2 answer 路径 Span 集合与父子结构 ----
@check("5.2 answer path span set/hierarchy/status")
def check_answer_spans(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import (
        OutcomeKind,
        TracePath,
        required_spans,
        validate_required_spans,
    )

    root = work / "answer"
    with make_index(root) as index:
        add_records(index, [ROW])
        answer, record, spans = run_traced(index, RECORD_Q)
    assert answer.kind == "answer"
    got = set(names(spans))
    assert got == EXPECTED_ANSWER_SPANS, f"span set mismatch: got={sorted(got)}"
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER) <= got
    assert validate_required_spans(record, names(spans)) == []
    recall = one(spans, "recall")
    assert recall.parent_span_id is None
    for child in ("exact_recall", "lexical_recall", "vector_recall"):
        assert one(spans, child).parent_span_id == recall.span_id
    assert one(spans, "embedding_query").parent_span_id == one(spans, "vector_recall").span_id
    fuse = one(spans, "fuse")
    assert fuse.parent_span_id is None
    assert one(spans, "hard_filter").parent_span_id == fuse.span_id
    assert one(spans, "rerank").parent_span_id == fuse.span_id
    answer_span = one(spans, "answer")
    assert answer_span.parent_span_id is None
    assert one(spans, "fact_validate").parent_span_id == answer_span.span_id
    assert one(spans, "parse").parent_span_id is None
    assert one(spans, "commit").parent_span_id is None
    assert names(spans)[0] == "parse" and names(spans)[-1] == "commit"
    assert all(span.status == "ok" for span in spans), [s.status for s in spans]
    assert all(span.error_code is None for span in spans)
    assert all(isinstance(span.duration_ms, int) and span.duration_ms >= 0 for span in spans)
    assert {span.trace_id for span in spans} == {record.trace_id}
    assert record.path == "rag" and record.outcome_kind == "answer" and record.status == "ok"
    assert attrs(one(spans, "parse"))["mode"] == "record"
    assert attrs(recall) == {
        "exact": 1,
        "hints": 0,
        "lexical": 1,
        "vector": 1,
        "vector_enabled": True,
    }, attrs(recall)
    return {
        "spans": span_dump(spans),
        "record": record_dump(record),
    }


@check("5.2b document-mode answer path: required spans present, no exact_recall")
def check_document_answer(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import (
        OutcomeKind,
        TracePath,
        required_spans,
        validate_required_spans,
    )

    root = work / "document-answer"
    with make_index(root) as index:
        add_text_document(index, "公司年度愿景是成为行业领先的智能知识库服务商。")
        answer, record, spans = run_traced(index, DOC_Q)
    got = set(names(spans))
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER) <= got, sorted(got)
    assert "exact_recall" not in got, "document 模式没有精确通道"
    assert validate_required_spans(record, names(spans)) == []
    return {"span_names": names(spans), "text": answer.text, "requirement": sorted(got)}


# ---- §5.3 条件 Span ----

@check("5.3a conditional attrs canonical and agree with spans")
def check_conditional(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import (
        conditional_required_spans,
        validate_required_spans,
    )

    root = work / "conditional"
    with make_index(root) as index:
        add_records(index, [ROW])
        _answer, record, spans = run_traced(index, RECORD_Q)
    decisions = assert_canonical_text(record.filter_decisions_json, "filter_decisions_json")
    assert decisions["vector_enabled"] is True
    assert decisions["rerank_enabled"] is True
    conditional = conditional_required_spans(decisions)
    assert conditional == {"vector_recall", "rerank"}, conditional
    assert conditional <= set(names(spans))
    assert validate_required_spans(record, names(spans)) == []
    for field_name in (
        "retrieval_counts_json",
        "fact_gate_json",
        "citation_refs_json",
        "pagination_json",
        "degraded_json",
    ):
        payload = getattr(record, field_name)
        if not payload:
            continue
        parsed = assert_canonical_text(payload, field_name)
        if isinstance(parsed, dict):
            for flag in ("vector_enabled", "rerank_enabled"):
                assert flag not in parsed, f"{flag} 出现在非约定字段 {field_name}"
    return {"filter_decisions": decisions, "conditional": sorted(conditional)}


@check("5.3b vector span absent when query embedding disabled; no embed call")
def check_vector_disabled(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import (
        conditional_required_spans,
        validate_required_spans,
    )

    calls: list[Any] = []
    root = work / "vector-disabled"
    with make_index(root, disable_query_embedding=True) as index:
        add_records(index, [ROW])
        original = index.embedder.embed

        def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("disable_query_embedding=True 时不得调用 embedding")

        index.embedder.embed = forbidden
        try:
            answer, record, spans = run_traced(index, RECORD_Q)
        finally:
            index.embedder.embed = original
    assert calls == [], calls
    assert answer.kind == "answer"
    got = set(names(spans))
    assert "vector_recall" not in got and "embedding_query" not in got, got
    decisions = assert_canonical_text(record.filter_decisions_json, "filter_decisions_json")
    assert decisions["vector_enabled"] is False
    assert conditional_required_spans(decisions) == {"rerank"}, conditional_required_spans(decisions)
    assert validate_required_spans(record, names(spans)) == []
    counts = assert_canonical_text(record.retrieval_counts_json, "retrieval_counts_json")
    assert counts["vector"] == 0, counts
    return {"span_names": sorted(got), "filter_decisions": decisions, "embedding_calls": 0}


@check("5.3c rerank span absent when fusion empty; flag false")
def check_rerank_absent(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import (
        conditional_required_spans,
        validate_required_spans,
    )

    root = work / "rerank-absent"
    with make_index(root) as index:
        answer, record, spans = run_traced(index, DOC_Q)
    assert answer.kind == "no_answer"
    got = set(names(spans))
    assert "rerank" not in got, got
    assert {"hard_filter", "fuse"} <= got, got
    decisions = assert_canonical_text(record.filter_decisions_json, "filter_decisions_json")
    assert decisions["rerank_enabled"] is False
    assert conditional_required_spans(decisions) == {"vector_recall"}
    assert validate_required_spans(record, names(spans)) == []
    return {"span_names": sorted(got), "filter_decisions": decisions}


# ---- §5.4 早退路径 ----
@check("5.4a clarification: only parse+commit, validate ok")
def check_clarification(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import validate_required_spans

    root = work / "clarification"
    with make_index(root) as index:
        add_records(index, [ROW])
        answer, record, spans = run_traced(index, CLAR_Q)
    assert answer.kind == "clarification", answer.kind
    assert set(names(spans)) == {"parse", "commit"}, names(spans)
    assert validate_required_spans(record, names(spans)) == []
    assert record.outcome_kind == "clarification"
    return {"span_names": names(spans), "kind": answer.kind, "reason": answer.reason}


@check("5.4b DOCUMENT_NOT_FOUND: only parse+commit, no fabricated retrieval/answer")
def check_document_not_found(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import validate_required_spans

    root = work / "doc-not-found"
    with make_index(root) as index:
        answer, record, spans = run_traced(index, MISSING_Q)
    assert answer.kind == "no_answer", answer.kind
    assert answer.reason == "DOCUMENT_NOT_FOUND", answer.reason
    assert set(names(spans)) == {"parse", "commit"}, names(spans)
    assert not {"recall", "fuse", "answer", "fact_validate"} & set(names(spans))
    missing = validate_required_spans(record, names(spans))
    assert missing == [], f"validate_required_spans 缺失={missing}"
    return {"span_names": names(spans), "reason": answer.reason}


@check("5.4c retrieval no_answer: required set ok, no fabricated fact_validate")
def check_retrieval_no_answer(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import (
        OutcomeKind,
        TracePath,
        required_spans,
        validate_required_spans,
    )

    root = work / "retrieval-no-answer"
    with make_index(root) as index:
        answer, record, spans = run_traced(index, DOC_Q)
    got = set(names(spans))
    assert answer.kind == "no_answer", answer.kind
    assert answer.reason == "NO_EVIDENCE", answer.reason
    assert required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER) <= got, sorted(got)
    assert "exact_recall" not in got, "document 模式没有精确通道"
    assert "fact_validate" not in got, "没有答案时不得伪造 fact_validate"
    assert validate_required_spans(record, names(spans)) == []
    return {
        "span_names": names(spans),
        "answer_span_present": "answer" in got,
        "note": "answer span 存在，但 answer 阶段真实执行（_answer_document 判定 NO_EVIDENCE）",
    }


@check("5.4d conflict: required answer/fact_validate, validate ok")
def check_conflict(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import validate_required_spans

    root = work / "conflict"
    with make_index(root) as index:
        add_records(index, [{**ROW, "位置": "店内外侧"}], code="A")
        add_records(index, [{**ROW, "位置": "D区暂存柜"}], code="B")
        answer, record, spans = run_traced(index, CONFLICT_Q)
    got = set(names(spans))
    assert answer.kind == "conflict", (answer.kind, answer.reason)
    assert {"parse", "recall", "fuse", "answer", "fact_validate", "commit"} <= got, sorted(got)
    assert validate_required_spans(record, names(spans)) == []
    assert record.outcome_kind == "conflict"
    return {"span_names": names(spans), "kind": answer.kind, "reason": answer.reason}


@check("5.4e knowledge_changed: only parse+commit, validate ok")
def check_knowledge_changed(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import OutcomeKind, validate_required_spans
    from mktkb.rag.errors import KnowledgeChanged

    root = work / "knowledge-changed"
    with make_index(root) as index:
        add_records(index, [ROW])

        def raise_changed(plan, *, limit=None):
            raise KnowledgeChanged("检索期间知识库版本发生变化")

        original = index.search
        index.search = raise_changed
        try:
            answer, record, spans = run_traced(
                index, RECORD_Q, outcome=OutcomeKind.KNOWLEDGE_CHANGED
            )
        finally:
            index.search = original
    assert answer.kind == "error" and answer.reason == "KNOWLEDGE_CHANGED"
    assert set(names(spans)) == {"parse", "commit"}, names(spans)
    assert validate_required_spans(record, names(spans)) == []
    assert record.outcome_kind == "knowledge_changed"
    return {"span_names": names(spans), "reason": answer.reason}


# ---- §5.5 attributes 合规与隐私 ----
@check("5.5a canonical JSON + no question/answer/evidence/chunk-id text in trace")
def check_attributes_privacy(work: Path) -> dict[str, Any]:
    root = work / "privacy"
    with make_index(root) as index:
        add_records(index, [ROW])
        answer, record, spans = run_traced(index, RECORD_Q)
    assert answer.kind == "answer"
    record_json: dict[str, Any] = {}
    for field in fields(record):
        if field.name.endswith("_json"):
            payload = getattr(record, field.name)
            if payload is not None:
                record_json[field.name] = assert_canonical_text(payload, field.name)
    for span in spans:
        attrs(span)
    raw_source_id = answer.citations[0].source_id
    evidence_text = "；".join(f"{name}: {value}" for name, value in ROW.items())
    needles = [RECORD_Q, ANSWER_TEXT, answer.text, evidence_text, raw_source_id]
    blobs = []
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
    leaked = [needle for needle in needles if needle and needle in joined]
    assert not leaked, f"trace 记录了内容原文：{leaked}"
    assert record.question_hash and len(record.question_hash) == 64
    assert record.question_hash != RECORD_Q
    assert record.question_chars == len(RECORD_Q)
    assert record.content_mode == "hash"
    refs = record_json["citation_refs_json"]
    assert refs and refs[0]["doc_id"] == "D01"
    assert len(refs[0]["unit_id_hash"]) == 16
    assert raw_source_id not in json.dumps(refs, ensure_ascii=False)
    counts = record_json["retrieval_counts_json"]
    assert counts == dict(answer.diagnostics["recall"]), (counts, answer.diagnostics["recall"])
    assert all(isinstance(v, int) and v >= 0 for v in counts.values())
    assert record_json["degraded_json"] == []
    assert record.index_revision == str(answer.citations[0].revision)
    pagination = record_json["pagination_json"]
    assert pagination["total"] == int(answer.diagnostics["total"])
    fact_gate = record_json["fact_gate_json"]
    assert fact_gate == {"checked": True, "passed": True, "units": len(answer.facts), "code": None}
    # 允许的字符串叶子（稳定引用/代码）：仅做人工可审计输出，不据此判 FAIL
    string_leaves: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            string_leaves.add(value)

    for span in spans:
        walk(attrs(span))
    for payload in record_json.values():
        walk(payload)
    assert "物品位置" in string_leaves  # locator 的 sheet 名（设计 §6.3 允许 doc_code+locator）
    return {
        "record_json_fields": sorted(record_json),
        "string_leaves": sorted(string_leaves),
        "leaked": leaked,
        "question_hash_len": len(record.question_hash),
    }


@check("5.5b trace DB at rest contains no question/answer text")
def check_db_at_rest(work: Path) -> dict[str, Any]:
    from mktkb.observability.store import TraceRepository

    root = work / "at-rest"
    trace_db = root / "traces" / "qa-traces.sqlite3"
    trace_db.parent.mkdir(parents=True, exist_ok=True)
    repo = TraceRepository(trace_db)
    with make_index(root / "rag") as index:
        add_records(index, [ROW])
        with start(RECORD_Q, repo) as trace:
            answer = index.ask(RECORD_Q, user_id="u", conversation_id="c-db")
            trace.set_outcome("answer", answer.reason)
    repo.close()
    raw = b""
    files = []
    for path in sorted(trace_db.parent.rglob("*")):
        if path.is_file():
            files.append(str(path.relative_to(trace_db.parent)))
            raw += path.read_bytes()
    text = raw.decode("utf-8", errors="ignore")
    needles = [RECORD_Q, ANSWER_TEXT, answer.text]
    leaked = [needle for needle in needles if needle in text]
    assert not leaked, f"trace DB 落盘含内容原文：{leaked}"
    # 记录里只有摘要，可检索到 question_chars
    assert str(len(RECORD_Q)) in text
    return {"db_files": files, "leaked": leaked, "db_bytes": len(raw)}


# ---- §5.6 异常路径 ----
@check("5.6a internal exception: span status=error, exception type/message unchanged")
def check_exception(work: Path) -> dict[str, Any]:
    from mktkb.rag import retrieval

    root = work / "exception"
    with make_index(root) as index:
        add_records(index, [ROW])
        original = retrieval._fuse

        def boom(*args, **kwargs):
            raise RuntimeError("PROBE-T003C-BOOM")

        retrieval._fuse = boom
        repo = Repo()
        caught = None
        try:
            with start(RECORD_Q, repo):
                index.ask(RECORD_Q, user_id="u", conversation_id="c-boom")
        except RuntimeError as exc:
            caught = exc
        finally:
            retrieval._fuse = original
    assert caught is not None, "异常没有原样上抛"
    assert str(caught) == "PROBE-T003C-BOOM", str(caught)
    record, spans = repo.last
    fuse = one(spans, "fuse")
    assert fuse.status == "error" and fuse.error_code == "RuntimeError", (fuse.status, fuse.error_code)
    assert record.status == "error" and record.error_code == "RuntimeError"
    return {"exception": repr(caught), "fuse": {"status": fuse.status, "error_code": fuse.error_code},
            "trace": {"status": record.status, "error_code": record.error_code}}


@check("5.6b embedding failure: embedding span error, degradation unchanged, no new exception")
def check_embedding_failure(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import validate_required_spans
    from mktkb.rag.errors import EmbeddingUnavailable

    root = work / "embedding-failure"
    with make_index(root) as index:
        add_records(index, [ROW])
        original = index.embedder.embed

        def embed_down(questions, purpose="document"):
            raise EmbeddingUnavailable("embedding provider unavailable")

        index.embedder.embed = embed_down
        try:
            answer, record, spans = run_traced(index, RECORD_Q)
        finally:
            index.embedder.embed = original
    assert answer.kind == "answer", answer.kind
    embed_span = one(spans, "embedding_query")
    assert embed_span.status == "error"
    assert embed_span.error_code == "EmbeddingUnavailable"
    degraded = assert_canonical_text(record.degraded_json, "degraded_json")
    assert degraded == ["vector"], degraded
    counts = assert_canonical_text(record.retrieval_counts_json, "retrieval_counts_json")
    assert counts["vector"] == 0
    assert validate_required_spans(record, names(spans)) == []
    return {"span": {"status": embed_span.status, "error_code": embed_span.error_code},
            "degraded": degraded, "kind": answer.kind}


@check("5.6c fact rejection: fact_validate error, refusal answer unchanged")
def check_fact_rejection(work: Path) -> dict[str, Any]:
    from mktkb.observability.contracts import validate_required_spans
    from mktkb.rag.errors import ForgedValue
    from mktkb.rag.facts import FactValidator

    root = work / "fact-rejection"
    original = FactValidator.validate_record_text

    def reject(self, text, facts, **kwargs):
        raise ForgedValue("probe injected: 回答包含无依据的值")

    FactValidator.validate_record_text = reject
    try:
        with make_index(root) as index:
            add_records(index, [ROW])
            answer, record, spans = run_traced(index, RECORD_Q)
    finally:
        FactValidator.validate_record_text = original
    assert answer.kind == "no_answer" and answer.reason == "FORGED_VALUE", (answer.kind, answer.reason)
    fact_span = one(spans, "fact_validate")
    assert fact_span.status == "error" and fact_span.error_code == "ForgedValue"
    gate = assert_canonical_text(record.fact_gate_json, "fact_gate_json")
    assert gate == {"checked": True, "passed": False, "units": 1, "code": "FORGED_VALUE"}, gate
    assert validate_required_spans(record, names(spans)) == []
    return {"kind": answer.kind, "reason": answer.reason, "fact_gate": gate,
            "span": {"status": fact_span.status, "error_code": fact_span.error_code}}


@check("5.6d rerank failure: fallback semantics kept, rerank span error")
def check_rerank_failure(work: Path) -> dict[str, Any]:
    root = work / "rerank-failure"
    with make_index(root) as index:
        add_records(index, [ROW])
        original = index.reranker.rerank

        def rerank_down(*args, **kwargs):
            raise RuntimeError("PROBE-RERANK-DOWN")

        index.reranker.rerank = rerank_down
        try:
            answer, record, spans = run_traced(index, RECORD_Q)
        finally:
            index.reranker.rerank = original
    assert answer.kind == "answer", answer.kind
    rerank = one(spans, "rerank")
    assert rerank.status == "error" and rerank.error_code == "RuntimeError", (
        rerank.status,
        rerank.error_code,
    )
    assert record.status == "ok", record.status
    return {"kind": answer.kind, "rerank": {"status": rerank.status, "error_code": rerank.error_code},
            "trace_status": record.status}


# ---- 硬约束 ----
@check("hard constraint: public result structures unchanged")
def check_structure(_work: Path) -> dict[str, Any]:
    from mktkb.rag import RagAnswer, RetrievalResult

    answer_fields = [item.name for item in fields(RagAnswer)]
    retrieval_fields = [item.name for item in fields(RetrievalResult)]
    assert answer_fields == [
        "kind", "question", "text", "state", "citations", "facts", "reason",
        "answer_source", "diagnostics",
    ], answer_fields
    assert retrieval_fields == [
        "plan", "revision", "exact", "lexical", "vector", "fused", "evidence",
        "total", "returned", "has_more", "next_page", "recall_counts",
        "diagnostics", "degraded", "effective_hints",
    ], retrieval_fields
    return {"RagAnswer": answer_fields, "RetrievalResult": retrieval_fields}


@check("hard constraint: zero network calls during offline ask")
def check_zero_network(work: Path) -> dict[str, Any]:
    root = work / "no-network"
    originals = (socket.socket.connect, socket.create_connection)
    calls: list[Any] = []

    def forbid(self, address, *args, **kwargs):
        calls.append(("socket.connect", address))
        raise AssertionError(f"探针检测到网络调用：{address!r}")

    def forbid_create(address, *args, **kwargs):
        calls.append(("create_connection", address))
        raise AssertionError(f"探针检测到网络调用：{address!r}")

    socket.socket.connect = forbid
    socket.create_connection = forbid_create
    try:
        with make_index(root) as index:
            add_records(index, [ROW])
            answer = index.ask(RECORD_Q, user_id="u", conversation_id="c-net")
    finally:
        socket.socket.connect, socket.create_connection = originals
    assert answer.kind == "answer"
    assert calls == [], calls
    return {"network_calls": calls, "kind": answer.kind}


@check("trace_attrs helpers: canonical JSON / stable short hash")
def check_helpers(_work: Path) -> dict[str, Any]:
    from mktkb.observability import trace_attrs

    assert trace_attrs.canonical_json({"b": 1, "a": "中文"}) == '{"a":"中文","b":1}'
    first = trace_attrs.hash_ref("unit-1")
    assert len(first) == 16 and first == trace_attrs.hash_ref("unit-1")
    assert first != trace_attrs.hash_ref("unit-2")
    assert "unit-1" not in first
    for bad in ("", None, 123):
        try:
            trace_attrs.hash_ref(bad)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"hash_ref 未拒绝非法输入 {bad!r}")
    return {"canonical": trace_attrs.canonical_json({"b": 1, "a": "中文"}), "hash": first}


def main() -> int:
    out_path = Path(sys.argv[1])
    work = Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    checks = [
        check_no_trace,
        check_answer_spans,
        check_document_answer,
        check_conditional,
        check_vector_disabled,
        check_rerank_absent,
        check_clarification,
        check_document_not_found,
        check_retrieval_no_answer,
        check_conflict,
        check_knowledge_changed,
        check_attributes_privacy,
        check_db_at_rest,
        check_exception,
        check_embedding_failure,
        check_fact_rejection,
        check_rerank_failure,
        check_structure,
        check_zero_network,
        check_helpers,
    ]
    for fn in checks:
        fn(work)
    passed = sum(1 for item in REPORT if item["ok"])
    report = {
        "mktkb_file": __import__("mktkb").__file__,
        "checks": REPORT,
        "passed": passed,
        "failed": len(REPORT) - passed,
    }
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"SUMMARY passed={passed} failed={len(REPORT) - passed} -> {out_path}")
    return 0 if passed == len(REPORT) else 1


if __name__ == "__main__":
    raise SystemExit(main())
