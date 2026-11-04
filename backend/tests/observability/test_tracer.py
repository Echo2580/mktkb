"""T003a：请求级 Trace 内核测试（设计 §6.1 / §6.3 / §6.4 / §6.5 / §6.6；计划 Task 3）。

只依赖标准库 + T001/T002 已验收的 ``mktkb.observability`` 内核；所有 SQLite 数据库都写在
``tmp_path`` 下，不触碰 ``var/``、``mktkb.sqlite3`` / ``rag-index.sqlite3`` 与任何业务模块；
零真实模型 / OCR / embedding / rerank 调用，不读 ``.env``，不访问网络。

覆盖 handoff §5 八条验收：contextvars 隔离、trace_id 唯一与自动/幂等 finish、Span 计时与
状态与 attributes_json、setter/annotate 与 incomplete、best-effort 写入与无 repo no-op、
内容模式（off/hash、redacted/full fail closed）、路径感知完整性校验、全量回归（由命令证据覆盖）。
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import logging
import sys
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

import mktkb.observability as observability
from mktkb.observability import (
    OutcomeKind,
    SpanHandle,
    TraceContext,
    TraceMode,
    TracePath,
    TraceRecord,
    current_trace,
    required_spans,
    start_trace,
    validate_required_spans,
)
from mktkb.observability.store import TraceRepository, TraceWriteError
from mktkb.observability.versioning import key_fingerprint

TRACER_LOGGER = "mktkb.observability.tracer"

# ---- 测试替身与工具 ----


class _SpyRepo:
    """只实现 ``write_best_effort`` 的仓储替身：记录每次写入，不产生任何 DB 文件。"""

    def __init__(self) -> None:
        self.calls: list[tuple[TraceRecord, list[object]]] = []

    def write_best_effort(self, record: TraceRecord, spans: object) -> None:
        self.calls.append((record, list(spans)))  # type: ignore[arg-type]

    def only_call(self) -> tuple[TraceRecord, list[object]]:
        assert len(self.calls) == 1, f"应恰好写入 1 次，实际 {len(self.calls)} 次"
        return self.calls[0]


class _FailingRepo:
    """模拟写入失败（真实 store 的 write_best_effort 也不抛，这里验证内核自身兜底）。"""

    def write_best_effort(self, record: TraceRecord, spans: object) -> None:
        raise RuntimeError("模拟 trace 写入失败")


def _canonical_json(payload: object) -> str:
    """设计 §6.2 canonical JSON：ensure_ascii=False, sort_keys=True。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _span_by_name(spans: object) -> dict[str, object]:
    return {span.name: span for span in spans}  # type: ignore[attr-defined]


def _make_trace(**overrides: object) -> TraceRecord:
    base = TraceRecord(
        trace_id="t-validate",
        request_id="r-validate",
        http_request_id="http-validate",
        mode="local",
        scope="end_to_end",
        path="rag",
        content_mode="hash",
        status="ok",
    )
    return TraceRecord(**{**asdict(base), **overrides})


# ---- §5.1 contextvars 隔离 ----


def test_current_trace_is_none_without_start_trace() -> None:
    assert current_trace() is None


def test_start_trace_yields_trace_context_with_unique_ids() -> None:
    seen: set[str] = set()
    for _ in range(20):
        with start_trace(
            http_request_id="http-1", mode=TraceMode.LOCAL, scope="end_to_end"
        ) as trace:
            assert isinstance(trace, TraceContext)
            assert isinstance(trace.trace_id, str) and trace.trace_id
            uuid.UUID(hex=trace.trace_id)  # 32 位 hex，可被 X-Trace-ID 直接使用
            assert trace.trace_id not in seen
            seen.add(trace.trace_id)
            assert current_trace() is trace
        assert current_trace() is None
    assert len(seen) == 20


def test_concurrent_threads_keep_traces_and_spans_isolated() -> None:
    barrier = threading.Barrier(2, timeout=10)
    results: dict[str, dict[str, object]] = {}
    failures: list[BaseException] = []

    def worker(label: str) -> None:
        repo = _SpyRepo()
        try:
            with start_trace(
                http_request_id=f"http-{label}",
                mode=TraceMode.LOCAL,
                scope="end_to_end",
                repo=repo,  # type: ignore[arg-type]
            ) as trace:
                barrier.wait()
                inner_current = current_trace()
                with trace.span(f"span-{label}"):
                    barrier.wait()
                assert current_trace() is trace
                captured: dict[str, object] = {
                    "trace_id": trace.trace_id,
                    "current": inner_current,
                }
            captured["record"] = repo.calls[0][0] if repo.calls else None
            captured["spans"] = repo.calls[0][1] if repo.calls else None
            results[label] = captured
        except BaseException as exc:  # noqa: BLE001 - 线程内异常要带回主线程断言
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(label,)) for label in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert failures == []
    assert not any(thread.is_alive() for thread in threads)
    assert current_trace() is None
    ids = {results[label]["trace_id"] for label in ("a", "b")}
    assert len(ids) == 2
    for label in ("a", "b"):
        result = results[label]
        assert result["current"] is not None
        assert result["current"].trace_id == result["trace_id"]  # type: ignore[attr-defined]
        record = result["record"]
        spans = result["spans"]
        assert isinstance(record, TraceRecord)
        assert record.trace_id == result["trace_id"]
        assert [span.name for span in spans] == [f"span-{label}"]  # type: ignore[attr-defined]
        assert all(span.trace_id == result["trace_id"] for span in spans)  # type: ignore[attr-defined]


def test_nested_traces_restore_outer_context() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-outer",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as outer:
        outer_id = outer.trace_id
        with start_trace(
            http_request_id="http-inner",
            mode=TraceMode.LOCAL,
            scope="retrieval_only",
            path=TracePath.LEGACY,
            repo=repo,  # type: ignore[arg-type]
        ) as inner:
            assert current_trace() is inner
            assert inner.trace_id != outer_id
            with inner.span("intent_parse"):
                pass
        assert current_trace() is outer
        with outer.span("parse"):
            pass
    assert current_trace() is None

    by_id = {call[0].trace_id: call for call in repo.calls}
    assert len(repo.calls) == 2
    assert outer_id in by_id
    names = {call[0].trace_id: [span.name for span in call[1]] for call in repo.calls}
    assert names[outer_id] == ["parse"]
    inner_id = next(key for key in names if key != outer_id)
    assert names[inner_id] == ["intent_parse"]
    assert by_id[inner_id][0].path == "legacy"


# ---- §5.2 生命周期：唯一 trace_id、自动 finish、显式 finish 幂等 ----


def test_nested_trace_does_not_inherit_outer_span_stack() -> None:
    repo = _SpyRepo()
    outer_handle: SpanHandle | None = None
    inner_handle: SpanHandle | None = None
    with start_trace(
        http_request_id="http-outer",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as outer:
        outer_id = outer.trace_id
        with outer.span("parse") as outer_handle:
            with start_trace(
                http_request_id="http-inner",
                mode=TraceMode.LOCAL,
                scope="retrieval_only",
                path=TracePath.LEGACY,
                repo=repo,  # type: ignore[arg-type]
            ) as inner:
                inner_id = inner.trace_id
                with inner.span("intent_parse") as inner_handle:
                    assert current_trace() is inner
            assert current_trace() is outer
        assert current_trace() is outer
    assert inner_handle is not None and inner_handle.parent_span_id is None
    spans_by_trace = {
        call[0].trace_id: _span_by_name(call[1]) for call in repo.calls
    }
    assert spans_by_trace[inner_id]["intent_parse"].parent_span_id is None
    assert spans_by_trace[outer_id]["parse"].parent_span_id is None
    assert outer_handle is not None


def test_context_exit_auto_finishes_and_writes_once() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_request_id("req-1")
        trace.set_outcome(OutcomeKind.ANSWER)
        assert repo.calls == []  # 退出上下文前不写
    record, spans = repo.only_call()
    assert isinstance(record, TraceRecord)
    assert record.trace_id == trace.trace_id
    assert record.request_id == "req-1"
    assert record.status == "ok"
    assert spans == []


def test_explicit_finish_is_idempotent_and_no_duplicate_write() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_outcome(OutcomeKind.CLARIFICATION)
        trace.finish()
        trace.finish()
        assert len(repo.calls) == 1
    assert len(repo.calls) == 1  # 上下文退出不会重复写
    record, _ = repo.only_call()
    assert record.trace_id == trace.trace_id


def test_context_exit_on_exception_still_finishes_and_cleans_contextvar() -> None:
    repo = _SpyRepo()
    with pytest.raises(RuntimeError, match="业务失败"):
        with start_trace(
            http_request_id="http-err",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            repo=repo,  # type: ignore[arg-type]
        ) as trace:
            trace.set_outcome(OutcomeKind.ANSWER)
            raise RuntimeError("业务失败")
    assert current_trace() is None
    record, _ = repo.only_call()
    assert record.trace_id == trace.trace_id
    assert record.status == "error"
    assert record.error_code == "RuntimeError"


def test_finish_without_repo_writes_no_database_file(tmp_path: Path) -> None:
    with start_trace(
        http_request_id="http-1", mode=TraceMode.LOCAL, scope="end_to_end"
    ) as trace:
        trace.set_outcome(OutcomeKind.ANSWER)
        with trace.span("parse"):
            pass
        trace.finish()
    assert current_trace() is None
    assert list(tmp_path.iterdir()) == []  # 无 repo：不创建任何 DB 文件


# ---- §5.3 Span：嵌套 parent、duration/status、attributes_json、未执行不记录 ----


def test_span_writes_duration_status_and_canonical_attributes() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        with trace.span("parse", step=1) as handle:
            assert isinstance(handle, SpanHandle)
            assert isinstance(handle.span_id, str) and handle.span_id
            handle.annotate(count=3, 中文键="中文值")
        trace.set_outcome(OutcomeKind.ANSWER)
    _, spans = repo.only_call()
    assert [span.name for span in spans] == ["parse"]
    span = spans[0]
    assert span.trace_id == trace.trace_id
    assert span.parent_span_id is None
    assert isinstance(span.duration_ms, int) and span.duration_ms >= 0
    assert span.status == "ok"
    assert span.error_code is None
    expected = _canonical_json({"count": 3, "step": 1, "中文键": "中文值"})
    assert span.attributes_json == expected
    assert "中文值" in (span.attributes_json or "")  # ensure_ascii=False
    assert "\\u" not in (span.attributes_json or "")


def test_span_duration_and_trace_latency_measure_elapsed_time() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_outcome(OutcomeKind.ANSWER)
        with trace.span("slow_stage"):
            time.sleep(0.05)
    record, spans = repo.only_call()
    assert spans[0].duration_ms >= 20
    assert record.latency_ms >= 20
    started_at = spans[0].started_at
    assert isinstance(started_at, str) and started_at
    assert datetime.fromisoformat(started_at).utcoffset() is not None


def test_span_attributes_json_is_empty_object_when_no_attributes() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        with trace.span("parse"):
            pass
        trace.set_outcome(OutcomeKind.ANSWER)
    _, spans = repo.only_call()
    assert spans[0].attributes_json == "{}"


def test_nested_spans_get_correct_parent_span_id() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        with trace.span("recall") as recall:
            with trace.span("exact_recall"):
                pass
            with trace.span("lexical_recall"):
                pass
        with trace.span("fuse"):
            pass
        trace.set_outcome(OutcomeKind.ANSWER)
    _, spans = repo.only_call()
    by_name = _span_by_name(spans)
    assert [span.name for span in spans] == [
        "recall",
        "exact_recall",
        "lexical_recall",
        "fuse",
    ]  # 按进入顺序记录，父 Span 在子 Span 之前
    assert by_name["recall"].parent_span_id is None
    assert by_name["exact_recall"].parent_span_id == recall.span_id
    assert by_name["lexical_recall"].parent_span_id == recall.span_id
    assert by_name["fuse"].parent_span_id is None
    assert len({span.span_id for span in spans}) == 4


def test_span_exception_sets_error_status_and_reraises() -> None:
    repo = _SpyRepo()
    with pytest.raises(ValueError, match="检索失败"):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            path=TracePath.RAG,
            repo=repo,  # type: ignore[arg-type]
        ) as trace:
            trace.set_outcome(OutcomeKind.ANSWER)
            with trace.span("recall"):
                raise ValueError("检索失败")
    record, spans = repo.only_call()
    assert record.status == "error"
    assert record.error_code == "ValueError"
    assert spans[0].name == "recall"
    assert spans[0].status == "error"
    assert spans[0].error_code == "ValueError"
    assert isinstance(spans[0].duration_ms, int)


def test_unexecuted_span_produces_no_record() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        with trace.span("parse"):
            pass
        condition = False
        if condition:
            with trace.span("vector_recall"):  # 未执行：不产生记录，也不伪造
                pass
        trace.set_outcome(OutcomeKind.CLARIFICATION)
    _, spans = repo.only_call()
    assert [span.name for span in spans] == ["parse"]


def test_span_after_finish_is_noop() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        with trace.span("parse"):
            pass
        trace.set_outcome(OutcomeKind.ANSWER)
        trace.finish()
        with trace.span("late") as handle:
            handle.annotate(ignored=True)
    record, spans = repo.only_call()
    assert [span.name for span in spans] == ["parse"]
    assert record.status == "ok"
    assert current_trace() is None


def test_span_annotate_can_mark_span_status_and_error_code() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        with trace.span("rerank") as handle:
            handle.annotate(status="error", error_code="rerank_unavailable")
        with trace.span("answer", status="ok"):
            pass
        trace.set_outcome(OutcomeKind.ANSWER)
    _, spans = repo.only_call()
    by_name = _span_by_name(spans)
    assert by_name["rerank"].status == "error"
    assert by_name["rerank"].error_code == "rerank_unavailable"
    assert by_name["rerank"].attributes_json == "{}"
    assert by_name["answer"].status == "ok"


def test_span_annotation_after_span_exit_does_not_change_record() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        with trace.span("parse") as handle:
            pass
        handle.annotate(too_late=True)
        trace.set_outcome(OutcomeKind.ANSWER)
    _, spans = repo.only_call()
    assert spans[0].attributes_json == "{}"


# ---- §5.4 setter / annotate 与 incomplete ----


def test_setters_and_annotate_take_effect() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        case_id="B0-001",
        attempt=2,
        previous_trace_id="t-previous",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_request_id("req-1")
        trace.set_question("城东店的宣传海报在哪里？")
        trace.set_path(TracePath.LEGACY)
        trace.set_outcome(
            OutcomeKind.NOT_FOUND,
            reason="知识库无稳定事实",
            answer_source="legacy",
            retrieval_counts_json={"retrieve": 0, "精确命中": 0},
            user_id_hash="u-hash",
        )
        trace.annotate(
            conversation_id_hash="c-hash",
            degraded_json={"degraded": False},
            go_decision="not_applicable",
        )
    record, _ = repo.only_call()
    assert record.request_id == "req-1"
    assert record.path == "legacy"
    assert record.outcome_kind == "not_found"
    assert record.reason == "知识库无稳定事实"
    assert record.answer_source == "legacy"
    assert json.loads(record.retrieval_counts_json or "{}") == {
        "retrieve": 0,
        "精确命中": 0,
    }
    assert record.user_id_hash == "u-hash"
    assert record.conversation_id_hash == "c-hash"
    assert json.loads(record.degraded_json or "{}") == {"degraded": False}
    assert record.go_decision == "not_applicable"
    assert record.case_id == "B0-001"
    assert record.attempt == 2
    assert record.previous_trace_id == "t-previous"
    assert record.http_request_id == "http-1"
    assert record.mode == "local"
    assert record.scope == "end_to_end"
    assert record.status == "ok"
    assert isinstance(record.latency_ms, int) and record.latency_ms >= 0
    assert datetime.fromisoformat(record.created_at or "").utcoffset() is not None


def test_set_path_and_outcome_accept_string_values() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode="local",  # 枚举或等值字符串都接受
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_path("legacy_with_rag_candidates")
        trace.set_outcome("not_found", reason="none")
    record, _ = repo.only_call()
    assert record.mode == "local"
    assert record.path == "legacy_with_rag_candidates"
    assert record.outcome_kind == "not_found"
    assert record.status == "ok"


def test_default_path_is_rag() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_outcome(OutcomeKind.CLARIFICATION)
    record, _ = repo.only_call()
    assert record.path == "rag"  # 计划默认 path=TracePath.RAG


def test_missing_outcome_writes_incomplete_status_without_raising() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_request_id("req-1")
        with trace.span("parse"):
            pass
    record, _ = repo.only_call()
    assert record.trace_id == trace.trace_id
    assert record.outcome_kind is None
    assert record.status == "incomplete"


def test_missing_path_writes_incomplete_status_without_raising() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=None,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_outcome(OutcomeKind.ANSWER)
    record, _ = repo.only_call()
    assert record.path is None
    assert record.outcome_kind == "answer"
    assert record.status == "incomplete"


def test_setters_after_finish_are_noop() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_outcome(OutcomeKind.ANSWER)
        trace.finish()
        trace.set_outcome(OutcomeKind.ERROR)
        trace.set_path(TracePath.LEGACY)
        trace.annotate(answer_source="late")
    record, _ = repo.only_call()
    assert record.outcome_kind == "answer"
    assert record.path == "rag"
    assert record.answer_source is None
    assert record.status == "ok"


def test_annotate_rejects_unknown_and_reserved_fields() -> None:
    with start_trace(
        http_request_id="http-1", mode=TraceMode.LOCAL, scope="end_to_end"
    ) as trace:
        with pytest.raises(ValueError, match="未知的 Trace 字段"):
            trace.annotate(not_a_trace_field=1)
        for reserved in (
            "trace_id",
            "trace_schema_version",
            "status",
            "latency_ms",
            "question_hash",
        ):
            with pytest.raises(ValueError, match="保留字段"):
                trace.annotate(**{reserved: "x"})


def test_annotate_json_field_accepts_dict_and_is_canonical() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.annotate(
            filter_decisions_json={"policy": {"doc_type": "policy"}, "数目": 2},
        )
        trace.set_outcome(OutcomeKind.ANSWER)
    record, _ = repo.only_call()
    assert record.filter_decisions_json == _canonical_json(
        {"policy": {"doc_type": "policy"}, "数目": 2}
    )
    assert "数目" in (record.filter_decisions_json or "")


# ---- §5.5 写入语义：write_best_effort、失败不抛、无 repo no-op ----


def test_finish_calls_repository_write_best_effort() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_outcome(OutcomeKind.ANSWER)
        with trace.span("parse"):
            pass
    assert len(repo.calls) == 1
    record, spans = repo.calls[0]
    assert isinstance(record, TraceRecord)
    assert all(span.trace_id == trace.trace_id for span in spans)


def test_write_failure_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=TRACER_LOGGER):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            path=TracePath.RAG,
            repo=_FailingRepo(),  # type: ignore[arg-type]
        ) as trace:
            trace.set_outcome(OutcomeKind.ANSWER)
            with trace.span("parse"):
                pass
    assert current_trace() is None
    assert "trace_finish_error" in caplog.text


def test_closed_repository_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    repo.close()
    with caplog.at_level(logging.WARNING):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            path=TracePath.RAG,
            repo=repo,
        ) as trace:
            trace.set_outcome(OutcomeKind.ANSWER)
    assert current_trace() is None
    assert trace.trace_id


def test_tracer_writes_span_trace_id_and_record_roundtrip(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            path=TracePath.RAG,
            repo=repo,
        ) as trace:
            trace.set_request_id("req-1")
            trace.set_question("城东店的宣传海报在哪里？")
            with trace.span("parse", query_chars=12):
                pass
            with trace.span("recall") as recall:
                with trace.span("exact_recall", hits=2):
                    pass
            with trace.span("fuse"):
                pass
            with trace.span("answer", source="rag"):
                pass
            with trace.span("commit"):
                pass
            trace.set_outcome(
                OutcomeKind.ANSWER,
                answer_source="rag",
                retrieval_counts_json={"精确命中": 2, "向量命中": 0},
            )
        record, spans = repo.get(trace.trace_id)
        assert record.trace_id == trace.trace_id
        assert record.request_id == "req-1"
        assert record.path == "rag"
        assert record.outcome_kind == "answer"
        assert record.status == "ok"
        assert record.content_mode == "hash"
        assert record.question_chars == len("城东店的宣传海报在哪里？")
        assert all(span.trace_id == trace.trace_id for span in spans)
        assert [span.name for span in spans] == [
            "parse",
            "recall",
            "exact_recall",
            "fuse",
            "answer",
            "commit",
        ]
        by_name = _span_by_name(spans)
        assert by_name["exact_recall"].parent_span_id == recall.span_id
        assert validate_required_spans(record, [span.name for span in spans]) == []
    finally:
        repo.close()


def test_finish_while_span_open_skips_unclosed_span(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = _SpyRepo()
    with caplog.at_level(logging.WARNING, logger=TRACER_LOGGER):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            path=TracePath.RAG,
            repo=repo,  # type: ignore[arg-type]
        ) as trace:
            with trace.span("outer"):
                trace.set_outcome(OutcomeKind.ANSWER)
                trace.finish()
    record, spans = repo.only_call()
    assert record.status == "ok"
    assert spans == []  # 未完成的 Span 不产生记录
    assert "trace_finish_with_open_spans" in caplog.text


# ---- §5.6 内容模式：off / hash（默认）、redacted/full fail closed ----


def test_default_content_mode_is_hash_with_sha256_when_no_key() -> None:
    repo = _SpyRepo()
    question = "城东店的宣传海报在哪里？"
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_question(question)
        trace.set_outcome(OutcomeKind.ANSWER)
    record, _ = repo.only_call()
    assert record.content_mode == "hash"
    assert record.question_hash == hashlib.sha256(question.encode("utf-8")).hexdigest()
    assert record.question_chars == len(question)
    assert record.hash_algo == "sha256"
    assert record.hmac_key_id is None
    assert question not in json.dumps(asdict(record), ensure_ascii=False)


def test_content_mode_hash_with_hmac_key() -> None:
    repo = _SpyRepo()
    question = "城东店的宣传海报在哪里？"
    key = b"t003a-unit-test-hmac-key"
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
        hmac_key=key,
    ) as trace:
        trace.set_question(question)
        trace.set_outcome(OutcomeKind.ANSWER)
    record, _ = repo.only_call()
    expected = hmac.new(key, question.encode("utf-8"), hashlib.sha256).hexdigest()
    assert record.question_hash == expected
    assert record.hash_algo == "hmac-sha256"
    assert record.hmac_key_id == key_fingerprint(key)
    assert key.decode() not in json.dumps(asdict(record), ensure_ascii=False)


def test_content_mode_hash_with_empty_hmac_key_falls_back_to_sha256() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
        hmac_key=b"",
    ) as trace:
        trace.set_question("q")
        trace.set_outcome(OutcomeKind.ANSWER)
    record, _ = repo.only_call()
    assert record.hash_algo == "sha256"
    assert record.hmac_key_id is None


def test_content_mode_off_stores_no_question_digest_but_counts() -> None:
    repo = _SpyRepo()
    question = "城东店的宣传海报在哪里？"
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
        content_mode="off",
    ) as trace:
        trace.set_question(question)
        trace.set_outcome(OutcomeKind.ANSWER)
        with trace.span("parse", query_chars=len(question)):
            pass
    record, spans = repo.only_call()
    assert record.content_mode == "off"
    assert record.question_hash is None
    assert record.hash_algo is None
    assert record.hmac_key_id is None
    assert record.question_chars == len(question)  # 只存计数与 ID
    serialized = json.dumps(asdict(record), ensure_ascii=False) + json.dumps(
        [asdict(span) for span in spans], ensure_ascii=False
    )
    assert question not in serialized


def test_question_unset_leaves_hash_fields_empty() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_outcome(OutcomeKind.ANSWER)
    record, _ = repo.only_call()
    assert record.question_hash is None
    assert record.question_chars is None
    assert record.hash_algo is None


@pytest.mark.parametrize("content_mode", ["redacted", "full"])
def test_unimplemented_content_modes_fail_closed(content_mode: str) -> None:
    with pytest.raises(ValueError, match="P0 未实现"):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            content_mode=content_mode,
        ):
            pass  # pragma: no cover - 进入前就应失败
    assert current_trace() is None


def test_unknown_content_mode_fails_closed() -> None:
    with pytest.raises(ValueError, match="content_mode"):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            content_mode="plaintext",
        ):
            pass  # pragma: no cover


# ---- §5.7 路径感知 Span 完整性校验 ----


def test_validate_required_spans_returns_missing_sorted_list() -> None:
    record = _make_trace(path="rag", outcome_kind="answer")
    assert validate_required_spans(record, ["parse", "recall"]) == [
        "answer",
        "commit",
        "fuse",
    ]


def test_validate_required_spans_complete_set_returns_empty() -> None:
    record = _make_trace(path="rag", outcome_kind="answer")
    names = ["parse", "recall", "fuse", "answer", "commit"]
    assert validate_required_spans(record, names) == []
    # 多余 / 条件未触发的 Span 不报缺失
    assert validate_required_spans(record, [*names, "rerank", "index_sync"]) == []


def test_validate_required_spans_rag_clarification_does_not_require_answer() -> None:
    record = _make_trace(path="rag", outcome_kind="clarification")
    assert required_spans(TracePath.RAG, OutcomeKind.CLARIFICATION) == frozenset(
        {"parse", "commit"}
    )
    assert validate_required_spans(record, ["parse", "commit"]) == []
    assert validate_required_spans(record, ["parse"]) == ["commit"]
    assert "answer" not in required_spans(TracePath.RAG, OutcomeKind.CLARIFICATION)


def test_validate_required_spans_legacy_with_rag_candidates_uses_legacy_rules() -> None:
    record = _make_trace(path="legacy_with_rag_candidates", outcome_kind="answer")
    assert validate_required_spans(record, ["intent_parse", "retrieve"]) == [
        "answer_validate",
        "commit",
        "model_answer",
    ]
    assert (
        validate_required_spans(
            record,
            ["intent_parse", "retrieve", "model_answer", "answer_validate", "commit"],
        )
        == []
    )


def test_validate_required_spans_conditional_from_json_attributes() -> None:
    record = _make_trace(
        path="rag",
        outcome_kind="answer",
        filter_decisions_json=_canonical_json(
            {"vector_enabled": True, "rerank_enabled": False, "expansion_triggered": True}
        ),
    )
    base = ["parse", "recall", "fuse", "answer", "commit"]
    assert validate_required_spans(record, base) == ["query_expansion", "vector_recall"]
    assert validate_required_spans(record, [*base, "query_expansion", "vector_recall"]) == []


def test_validate_required_spans_conditional_false_not_required() -> None:
    record = _make_trace(
        path="rag",
        outcome_kind="answer",
        filter_decisions_json=_canonical_json(
            {"vector_enabled": False, "rerank_enabled": False}
        ),
    )
    base = ["parse", "recall", "fuse", "answer", "commit"]
    assert validate_required_spans(record, base) == []


def test_validate_required_spans_conditional_index_sync_from_other_json_field() -> None:
    record = _make_trace(
        path="legacy",
        outcome_kind="answer",
        retrieval_counts_json=_canonical_json({"index_sync_performed": True}),
    )
    base = ["intent_parse", "retrieve", "model_answer", "answer_validate", "commit"]
    assert validate_required_spans(record, base) == ["index_sync"]


def test_validate_required_spans_undefined_combination_fails_closed() -> None:
    record = _make_trace(path="rag", outcome_kind="not_found")
    with pytest.raises(ValueError, match="未定义"):
        validate_required_spans(record, [])


def test_validate_required_spans_missing_path_or_outcome_fails_closed() -> None:
    with pytest.raises(ValueError, match="path 或 outcome_kind"):
        validate_required_spans(_make_trace(path=None), [])
    with pytest.raises(ValueError, match="path 或 outcome_kind"):
        validate_required_spans(_make_trace(outcome_kind=None), [])


def test_validate_required_spans_rejects_single_string_argument() -> None:
    with pytest.raises(TypeError, match="span_names"):
        validate_required_spans(_make_trace(), "parse")  # type: ignore[arg-type]


def test_annotate_conditional_flags_merge_into_filter_decisions_json() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.annotate(
            filter_decisions_json={"hard_filters": {"doc_type": "policy"}},
            vector_enabled=True,
            rerank_enabled=False,
        )
        trace.set_outcome(OutcomeKind.ANSWER, reason="hit")
    record, _ = repo.only_call()
    payload = json.loads(record.filter_decisions_json or "{}")
    assert payload == {
        "hard_filters": {"doc_type": "policy"},
        "rerank_enabled": False,
        "vector_enabled": True,
    }
    base = ["parse", "recall", "fuse", "answer", "commit"]
    assert validate_required_spans(record, base) == ["vector_recall"]


def test_annotate_conditional_flags_without_filter_decisions_json() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.annotate(index_sync_performed=True)
        trace.set_outcome(OutcomeKind.ANSWER)
    record, _ = repo.only_call()
    assert json.loads(record.filter_decisions_json or "{}") == {
        "index_sync_performed": True
    }


# ---- 参数校验、状态语义与硬约束 ----


def test_trace_status_semantics() -> None:
    assert _finish_status(_SpyRepo(), outcome=OutcomeKind.ANSWER) == "ok"
    assert _finish_status(_SpyRepo(), outcome=OutcomeKind.SERVICE_ERROR) == "error"
    assert _finish_status(_SpyRepo(), outcome=OutcomeKind.ERROR) == "error"
    assert _finish_status(_SpyRepo()) == "incomplete"


def _finish_status(
    repo: _SpyRepo,
    *,
    outcome: OutcomeKind | None = None,
    path: TracePath | None = TracePath.RAG,
) -> str:
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=path,
        repo=repo,  # type: ignore[arg-type]
    ) as trace:
        if outcome is not None:
            trace.set_outcome(outcome)
    return repo.only_call()[0].status


def test_replayed_trace_status_and_spans() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-1",
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        replayed=True,
        previous_trace_id="t-before",
        repo=repo,  # type: ignore[arg-type]
    ):
        pass
    record, spans = repo.only_call()
    assert record.replayed is True
    assert record.previous_trace_id == "t-before"
    assert record.status == "replayed"  # 设计 §6.1：只有重放时仍写一条 status=replayed
    assert spans == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "invalid-mode", "scope": "end_to_end"},
        {"mode": TraceMode.LOCAL, "scope": ""},
        {"mode": TraceMode.LOCAL, "scope": "end_to_end", "attempt": 0},
        {"mode": TraceMode.LOCAL, "scope": "end_to_end", "attempt": True},
        {"mode": TraceMode.LOCAL, "scope": "end_to_end", "path": "invalid-path"},
        {"mode": TraceMode.LOCAL, "scope": "end_to_end", "content_mode": 1},
        {"mode": TraceMode.LOCAL, "scope": "end_to_end", "previous_trace_id": 1},
        {"mode": TraceMode.LOCAL, "scope": "end_to_end", "case_id": 1},
    ],
)
def test_start_trace_rejects_invalid_arguments(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        with start_trace(http_request_id="http-1", **kwargs):  # type: ignore[arg-type]
            pass  # pragma: no cover
    assert current_trace() is None


def test_start_trace_rejects_non_str_http_request_id_and_question() -> None:
    with pytest.raises(TypeError):
        with start_trace(http_request_id=1, mode=TraceMode.LOCAL, scope="end_to_end"):  # type: ignore[arg-type]
            pass  # pragma: no cover
    with pytest.raises(TypeError):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            question=1,  # type: ignore[arg-type]
        ):
            pass  # pragma: no cover
    assert current_trace() is None


def test_start_trace_rejects_repo_without_write_best_effort() -> None:
    with pytest.raises(TypeError, match="write_best_effort"):
        with start_trace(
            http_request_id="http-1",
            mode=TraceMode.LOCAL,
            scope="end_to_end",
            repo=object(),  # type: ignore[arg-type]
        ):
            pass  # pragma: no cover
    assert current_trace() is None


def test_span_rejects_empty_name() -> None:
    with start_trace(
        http_request_id="http-1", mode=TraceMode.LOCAL, scope="end_to_end"
    ) as trace:
        with pytest.raises(ValueError, match="name"):
            with trace.span(""):
                pass  # pragma: no cover


def test_observability_package_exports_tracer_api() -> None:
    for name in (
        "SpanHandle",
        "TraceContext",
        "current_trace",
        "start_trace",
        "validate_required_spans",
    ):
        assert name in observability.__all__
        assert getattr(observability, name) is not None


def test_tracer_imports_stay_inside_stdlib_and_observability() -> None:
    source = Path(observability.tracer.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    absolute: set[str] = set()
    relative: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            target = f"{'.' * node.level}{node.module}"
            if node.level == 0:
                absolute.add(node.module.split(".")[0])
            else:
                relative.add(target)
    assert absolute <= set(sys.stdlib_module_names), f"出现非标准库依赖：{absolute}"
    assert relative <= {".contracts", ".store", ".versioning"}, relative
    forbidden = {
        "sqlite3",  # 只允许经 store 使用
        "socket",
        "urllib",
        "http",
        "requests",
        "httpx",
        "openai",
        "dotenv",
        "qa",
        "rag",
        "conversations",
        "main",
        "config",
    }
    assert not (absolute & forbidden), absolute & forbidden
    assert "os.environ" not in source
    assert ".env" not in source
    assert "load_dotenv" not in source
