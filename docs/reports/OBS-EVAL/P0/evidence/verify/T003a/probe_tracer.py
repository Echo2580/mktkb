"""T003a 独立验收探针（仓库外，仅用于验收取证，不是交付物）。

只认实际运行结果：对 handoff §5.1-§5.7 逐条独立断言，§5.8 由 pytest 全量命令覆盖。
用法：
    python -B probe_tracer.py
环境变量（可选）：
    EXPECT_MKTKB_ROOT  期望导入的 mktkb 源码根（用于变异探针确认命中的是被变异副本）。
退出码：0 = 全部通过；1 = 断言失败（PROBE-FAIL::<name>）；2 = 探针自身异常。
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path

import mktkb
import mktkb.observability as obs

CHECKS = 0
SECTIONS = []


class ProbeFailure(AssertionError):
    pass


def ck(cond: object, name: str) -> None:
    global CHECKS
    if not cond:
        raise ProbeFailure(name)
    CHECKS += 1


def section(name: str) -> None:
    SECTIONS.append(name)
    print(f"[section] {name}", flush=True)


# ---- 必须在 import store 之前做的导入边界检查 ----
CK_STORE_NOT_IMPORTED = "mktkb.observability.store" not in sys.modules
# 注：mktkb/__init__.py 既有设计会 import .main（进而 import 业务包），因此不能用
# “业务包是否在 sys.modules”判断 tracer；tracer 的导入边界改用下方 AST 断言。
# TYPE_CHECKING 只为类型标注，运行期不得 import store
from mktkb.observability import (  # noqa: E402
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
from mktkb.observability.store import TraceRepository  # noqa: E402
from mktkb.observability.versioning import hash_question, key_fingerprint  # noqa: E402

TRACER_LOGGER = "mktkb.observability.tracer"
SCOPE = "end_to_end"


class SpyRepo:
    """同时暴露 write / write_best_effort：验收“finish 只走 best effort”。"""

    def __init__(self) -> None:
        self.best_effort_calls: list[tuple[TraceRecord, list[object]]] = []
        self.write_calls: list[object] = []

    def write_best_effort(self, record: TraceRecord, spans: object) -> None:
        self.best_effort_calls.append((record, list(spans)))  # type: ignore[arg-type]

    def write(self, *args: object, **kwargs: object) -> None:
        self.write_calls.append((args, kwargs))
        raise RuntimeError("探针：tracer.finish 不允许直接调用 write()")


class FailingRepo:
    def write_best_effort(self, record: TraceRecord, spans: object) -> None:
        raise RuntimeError("探针：模拟写入失败")


class LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def serialized(record: TraceRecord, spans: list[object]) -> str:
    return json.dumps(
        {"trace": asdict(record), "spans": [asdict(s) for s in spans]},  # type: ignore[arg-type]
        ensure_ascii=False,
    )


def make_record(**overrides: object) -> TraceRecord:
    base = dict(
        trace_id="t-validate",
        request_id="r-validate",
        http_request_id="h-validate",
        attempt=1,
        replayed=False,
        mode="local",
        scope=SCOPE,
        path="rag",
        content_mode="hash",
        status="ok",
        outcome_kind="answer",
    )
    base.update(overrides)
    return TraceRecord(**base)


# ---- §5.0 导入边界 / 静态约束 ----

def p_import_boundaries() -> None:
    section("import-boundaries")
    ck(CK_STORE_NOT_IMPORTED, "p0.package_import_must_not_import_store")
    root = os.environ.get("EXPECT_MKTKB_ROOT")
    if root:
        got = os.path.abspath(mktkb.__file__).lower()
        want = os.path.abspath(root).lower()
        ck(got.startswith(want), f"p0.mktkb_root_mismatch got={got} want={want}")

    source = Path(obs.tracer.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    absolute: set[str] = set()
    relative: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.level == 0:
                absolute.add(node.module.split(".")[0])
            else:
                relative.add("." * node.level + node.module)
    ck(absolute <= set(sys.stdlib_module_names), f"p0.non_stdlib_import:{absolute}")
    ck(relative <= {".contracts", ".store", ".versioning"}, f"p0.relative_import:{relative}")
    ck("sqlite3" not in absolute, "p0.tracer_must_not_import_sqlite3")
    for token in ("os.environ", "load_dotenv", ".env"):
        ck(token not in source, f"p0.forbidden_source_token:{token}")

    # 包级导出（追加，不破坏既有导出）
    for name in (
        "SpanHandle",
        "TraceContext",
        "current_trace",
        "start_trace",
        "validate_required_spans",
        "required_spans",
        "TraceRecord",
        "SpanRecord",
        "hash_question",
    ):
        ck(name in obs.__all__, f"p0.missing_export:{name}")
        ck(getattr(obs, name, None) is not None, f"p0.missing_attr:{name}")
    # contracts.__all__ 按 §2 不得改动：报告偏离 #7 自认星号导入不含新函数
    import mktkb.observability.contracts as contracts

    ck("validate_required_spans" not in contracts.__all__, "p0.contracts_all_must_be_unmodified")
    ck(callable(contracts.validate_required_spans), "p0.contracts_has_appended_function")


# ---- §5.1 contextvars 隔离 ----

def p_contextvars() -> None:
    section("contextvars")
    ck(current_trace() is None, "p1.no_trace_none")

    # 两个并发线程：各自的 trace / span / 写入互不串
    barrier = threading.Barrier(2, timeout=30)
    results: dict[str, dict[str, object]] = {}
    errors: list[BaseException] = []

    def worker(label: str) -> None:
        repo = SpyRepo()
        try:
            with start_trace(
                http_request_id=f"http-{label}",
                mode=TraceMode.LOCAL,
                scope=SCOPE,
                repo=repo,  # type: ignore[arg-type]
            ) as trace:
                barrier.wait()
                inner = current_trace()
                with trace.span(f"span-{label}"):
                    barrier.wait()
                results[label] = {"trace_id": trace.trace_id, "inner": inner, "repo": repo}
        except BaseException as exc:  # noqa: BLE001 - 线程异常带回主线程
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(label,)) for label in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    ck(errors == [], f"p1.thread_errors:{errors}")
    ck(not any(t.is_alive() for t in threads), "p1.threads_finished")
    ck(current_trace() is None, "p1.main_thread_clean_after")
    ids = {results[label]["trace_id"] for label in ("a", "b")}
    ck(len(ids) == 2, "p1.threads_distinct_trace_ids")
    for label in ("a", "b"):
        data = results[label]
        repo = data["repo"]
        ck(isinstance(repo, SpyRepo), "p1.spy_type")
        ck(repo.best_effort_calls and len(repo.best_effort_calls) == 1, "p1.thread_wrote_once")
        record, spans = repo.best_effort_calls[0]
        ck(record.trace_id == data["trace_id"], "p1.thread_record_matches_own_trace")
        ck([s.name for s in spans] == [f"span-{label}"], "p1.thread_own_span_only")  # type: ignore[attr-defined]
        ck(all(s.trace_id == data["trace_id"] for s in spans), "p1.thread_span_trace_id")  # type: ignore[attr-defined]
        inner = data["inner"]
        ck(inner is not None and inner.trace_id == data["trace_id"], "p1.thread_current_is_own")  # type: ignore[attr-defined]

    # 嵌套 trace：内层不继承外层 trace / Span 栈，退出恢复外层
    outer_repo = SpyRepo()
    inner_repo = SpyRepo()
    with start_trace(
        http_request_id="http-outer", mode=TraceMode.LOCAL, scope=SCOPE,
        path=TracePath.RAG, repo=outer_repo,  # type: ignore[arg-type]
    ) as outer:
        outer_id = outer.trace_id
        with outer.span("outer-span"):
            with start_trace(
                http_request_id="http-inner", mode=TraceMode.LOCAL, scope="retrieval_only",
                path=TracePath.LEGACY, repo=inner_repo,  # type: ignore[arg-type]
            ) as inner:
                ck(current_trace() is inner, "p1.nested_current_inner")
                ck(inner.trace_id != outer_id, "p1.nested_distinct_ids")
                with inner.span("intent_parse"):
                    pass
            ck(current_trace() is outer, "p1.nested_restore_outer")
    ck(current_trace() is None, "p1.nested_clean_after")
    ck(len(outer_repo.best_effort_calls) == 1 and len(inner_repo.best_effort_calls) == 1, "p1.nested_each_wrote_once")
    outer_record, outer_spans = outer_repo.best_effort_calls[0]
    inner_record, inner_spans = inner_repo.best_effort_calls[0]
    ck(outer_record.trace_id == outer_id and inner_record.trace_id != outer_id, "p1.nested_write_ids")
    ck([s.name for s in outer_spans] == ["outer-span"], "p1.nested_outer_spans")  # type: ignore[attr-defined]
    ck([s.name for s in inner_spans] == ["intent_parse"], "p1.nested_inner_spans")  # type: ignore[attr-defined]
    ck(inner_spans[0].parent_span_id is None, "p1.nested_inner_root_no_parent")  # type: ignore[attr-defined]
    ck(outer_spans[0].parent_span_id is None, "p1.nested_outer_root_no_parent")  # type: ignore[attr-defined]

    # 异常退出也恢复 contextvar
    try:
        with start_trace(http_request_id="http-e", mode=TraceMode.LOCAL, scope=SCOPE):
            raise RuntimeError("业务失败")
    except RuntimeError:
        pass
    ck(current_trace() is None, "p1.exception_exit_cleans_contextvar")

    # asyncio task 隔离（contextvars 的协程语义）
    async def async_case() -> None:
        parent_repo = SpyRepo()
        with start_trace(
            http_request_id="http-parent", mode=TraceMode.LOCAL, scope=SCOPE,
            repo=parent_repo,  # type: ignore[arg-type]
        ) as parent:
            parent_id = parent.trace_id

            async def child(label: str) -> None:
                child_repo = SpyRepo()
                with start_trace(
                    http_request_id=f"http-async-{label}", mode=TraceMode.LOCAL,
                    scope="retrieval_only", repo=child_repo,  # type: ignore[arg-type]
                ) as child_trace:
                    await asyncio.sleep(0)
                    ck(current_trace() is child_trace, f"p1.async_child_current:{label}")
                    with child_trace.span(f"async-{label}"):
                        await asyncio.sleep(0)
                ck(len(child_repo.best_effort_calls) == 1, f"p1.async_child_wrote:{label}")
                child_record, child_spans = child_repo.best_effort_calls[0]
                ck(child_record.trace_id != parent_id, f"p1.async_child_id_differs:{label}")
                ck([s.name for s in child_spans] == [f"async-{label}"], f"p1.async_child_span:{label}")  # type: ignore[attr-defined]
                ck(current_trace() is parent, f"p1.async_child_restores_parent:{label}")

            await asyncio.gather(child("x"), child("y"))
            ck(current_trace() is parent, "p1.async_parent_restored")
        ck(current_trace() is None, "p1.async_outer_clean")

    asyncio.run(async_case())


# ---- §5.2 trace_id 唯一 / 自动 finish / 幂等 ----

def p_lifecycle() -> None:
    section("lifecycle")
    seen: set[str] = set()
    for _ in range(1000):
        with start_trace(http_request_id="http-u", mode=TraceMode.LOCAL, scope=SCOPE) as trace:
            seen.add(trace.trace_id)
    ck(len(seen) == 1000, "p2.unique_trace_ids_1000")
    for trace_id in seen:
        ck(len(trace_id) == 32 and all(c in "0123456789abcdef" for c in trace_id), "p2.trace_id_is_uuid4_hex")
        uuid.UUID(hex=trace_id)

    repo = SpyRepo()
    with start_trace(http_request_id="http-a", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo):  # type: ignore[arg-type]
        pass
    ck(len(repo.best_effort_calls) == 1, "p2.auto_finish_writes_once")

    repo = SpyRepo()
    with start_trace(http_request_id="http-a", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
        trace.finish()
        trace.finish()
        ck(len(repo.best_effort_calls) == 1, "p2.explicit_finish_idempotent_inside")
    ck(len(repo.best_effort_calls) == 1, "p2.explicit_finish_no_duplicate_on_exit")

    repo = SpyRepo()
    try:
        with start_trace(http_request_id="http-e", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
            trace.set_outcome("answer")
            raise RuntimeError("业务失败")
    except RuntimeError:
        pass
    ck(len(repo.best_effort_calls) == 1, "p2.exception_exit_writes_once")
    record, _ = repo.best_effort_calls[0]
    ck(record.status == "error", "p2.exception_trace_status_error")
    ck(record.error_code == "RuntimeError", "p2.exception_error_code")


# ---- §5.3 Span ----

def p_spans() -> None:
    section("spans")
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
        with trace.span("recall") as recall:
            with trace.span("exact_recall", hits=2):
                pass
            with trace.span("empty"):
                pass
        with trace.span("fuse"):
            pass
        trace.set_outcome("answer")
    record, spans = repo.best_effort_calls[0]
    ck([s.name for s in spans] == ["recall", "exact_recall", "empty", "fuse"], "p3.span_entry_order")  # type: ignore[attr-defined]
    ck(spans[0].parent_span_id is None, "p3.root_parent_none")  # type: ignore[attr-defined]
    ck(spans[1].parent_span_id == recall.span_id, "p3.child_parent_id")  # type: ignore[attr-defined]
    ck(spans[2].parent_span_id == recall.span_id, "p3.sibling_parent_id")  # type: ignore[attr-defined]
    ck(spans[3].parent_span_id is None, "p3.after_exit_new_root")  # type: ignore[attr-defined]
    ck(len({s.span_id for s in spans}) == 4, "p3.span_ids_unique")  # type: ignore[attr-defined]
    ck(spans[0].attributes_json == "{}", "p3.empty_attributes_object")  # type: ignore[attr-defined]
    expected_attrs = json.dumps({"hits": 2}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ck(spans[1].attributes_json == expected_attrs, "p3.attributes_canonical")  # type: ignore[attr-defined]
    ck(all(isinstance(s.duration_ms, int) and s.duration_ms >= 0 for s in spans), "p3.duration_int_nonneg")  # type: ignore[attr-defined]
    ck(all(s.status == "ok" for s in spans), "p3.default_status_ok")  # type: ignore[attr-defined]
    ck(all(s.trace_id == record.trace_id for s in spans), "p3.span_trace_id")  # type: ignore[attr-defined]
    ck(all(isinstance(s.started_at, str) and s.started_at for s in spans), "p3.started_at_present")  # type: ignore[attr-defined]

    # ensure_ascii=False + sort_keys：中文原样、键排序
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
        with trace.span("s", b=2, a=1, 中文="值"):
            pass
        trace.set_outcome("answer")
    _, spans = repo.best_effort_calls[0]
    attrs = spans[0].attributes_json  # type: ignore[attr-defined]
    ck(attrs == '{"a":1,"b":2,"中文":"值"}', f"p3.attributes_ensure_ascii_false_sort:{attrs}")
    ck("\\u" not in (attrs or ""), "p3.attributes_no_unicode_escape")

    # duration 真实计量（非常量 / 非恒 0）
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
        trace.set_outcome("answer")
        with trace.span("slow_stage"):
            time.sleep(0.06)
    record, spans = repo.best_effort_calls[0]
    ck(spans[0].duration_ms >= 30, f"p3.span_duration_measured:{spans[0].duration_ms}")  # type: ignore[attr-defined]
    ck(record.latency_ms >= 30, f"p3.trace_latency_measured:{record.latency_ms}")

    # 异常 Span：span + trace 双 error，异常类型名为 error_code
    repo = SpyRepo()
    try:
        with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
            trace.set_outcome("answer")
            with trace.span("recall"):
                raise ValueError("检索失败")
    except ValueError:
        pass
    record, spans = repo.best_effort_calls[0]
    ck(spans[0].status == "error", "p3.exception_span_status_error")  # type: ignore[attr-defined]
    ck(spans[0].error_code == "ValueError", "p3.exception_span_error_code")  # type: ignore[attr-defined]
    ck(record.status == "error", "p3.exception_trace_status_error")
    ck(record.error_code == "ValueError", "p3.exception_trace_error_code")

    # 未执行的 Span 不落库、不伪造
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
        condition = False
        if condition:
            with trace.span("vector_recall"):
                pass
        trace.set_outcome("clarification")
    ck([s.name for s in repo.best_effort_calls[0][1]] == [], "p3.unexecuted_span_absent")  # type: ignore[attr-defined]

    # finish 之后 span no-op
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
        with trace.span("parse"):
            pass
        trace.finish()
        with trace.span("late") as handle:
            handle.annotate(ignored=True)
    ck([s.name for s in repo.best_effort_calls[0][1]] == ["parse"], "p3.span_after_finish_noop")  # type: ignore[attr-defined]


# ---- §5.4 setter / annotate / incomplete ----

def p_setters() -> None:
    section("setters")
    repo = SpyRepo()
    with start_trace(
        http_request_id="http-1", mode="local", scope=SCOPE,
        path=TracePath.RAG, case_id="B0-001", attempt=2,
        previous_trace_id="t-previous", repo=repo,  # type: ignore[arg-type]
    ) as trace:
        trace.set_request_id("req-1")
        trace.set_question("城东店的宣传海报在哪里？")
        trace.set_path("legacy")
        trace.set_outcome(
            "not_found", reason="知识库无稳定事实", answer_source="legacy",
            retrieval_counts_json={"retrieve": 0, "精确命中": 0},
        )
        trace.annotate(user_id_hash="u-hash", degraded_json={"degraded": False})
    record, _ = repo.best_effort_calls[0]
    ck(record.request_id == "req-1", "p4.set_request_id")
    ck(record.path == "legacy", "p4.set_path")
    ck(record.outcome_kind == "not_found", "p4.set_outcome")
    ck(record.reason == "知识库无稳定事实", "p4.set_outcome_reason")
    ck(record.answer_source == "legacy", "p4.set_outcome_attrs")
    ck(json.loads(record.retrieval_counts_json or "{}") == {"retrieve": 0, "精确命中": 0}, "p4.retrieval_counts_canonical")
    ck(record.user_id_hash == "u-hash", "p4.annotate_scalar")
    ck(json.loads(record.degraded_json or "{}") == {"degraded": False}, "p4.annotate_json")
    ck(record.case_id == "B0-001" and record.attempt == 2 and record.previous_trace_id == "t-previous", "p4.start_args_kept")
    ck(record.mode == "local" and record.scope == SCOPE, "p4.mode_scope")
    ck(record.status == "ok", "p4.complete_status_ok")

    # 缺 outcome → incomplete，不抛
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, path=TracePath.RAG, repo=repo) as trace:  # type: ignore[arg-type]
        trace.set_request_id("req-1")
        with trace.span("parse"):
            pass
    record, _ = repo.best_effort_calls[0]
    ck(record.outcome_kind is None, "p4.missing_outcome_none")
    ck(record.status == "incomplete", f"p4.missing_outcome_incomplete:{record.status}")

    # 缺 path（显式 None）→ incomplete，不抛
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, path=None, repo=repo) as trace:  # type: ignore[arg-type]
        trace.set_outcome("answer")
    record, _ = repo.best_effort_calls[0]
    ck(record.path is None and record.outcome_kind == "answer", "p4.missing_path_fields")
    ck(record.status == "incomplete", f"p4.missing_path_incomplete:{record.status}")

    # finish 后 setter / annotate / span no-op
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, path=TracePath.RAG, repo=repo) as trace:  # type: ignore[arg-type]
        trace.set_outcome("answer")
        trace.finish()
        trace.set_request_id("late")
        trace.set_question("late")
        trace.set_path(TracePath.LEGACY)
        trace.set_outcome("error")
        trace.annotate(answer_source="late")
    record, _ = repo.best_effort_calls[0]
    ck(record.request_id is None and record.path == "rag" and record.outcome_kind == "answer", "p4.setters_after_finish_noop")
    ck(record.answer_source is None, "p4.annotate_after_finish_noop")

    # annotate 非法字段 fail closed
    try:
        with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE) as trace:
            try:
                trace.annotate(not_a_field=1)
                ck(False, "p4.annotate_unknown_must_raise")
            except ValueError:
                ck(True, "p4.annotate_unknown_raises")
            try:
                trace.annotate(trace_id="x")
                ck(False, "p4.annotate_reserved_must_raise")
            except ValueError:
                ck(True, "p4.annotate_reserved_raises")
    except ProbeFailure:
        raise


# ---- §5.5 写入语义 ----

def p_write_semantics() -> None:
    section("write-semantics")
    # 只走 write_best_effort
    spy = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=spy) as trace:  # type: ignore[arg-type]
        trace.set_outcome("answer")
        with trace.span("parse"):
            pass
    ck(len(spy.best_effort_calls) == 1, "p5.write_best_effort_once")
    ck(spy.write_calls == [], f"p5.must_not_call_write:{spy.write_calls}")

    # 写入失败不抛、不中断调用方，且记 trace_finish_error 日志
    capture = LogCapture()
    tracer_logger = logging.getLogger(TRACER_LOGGER)
    tracer_logger.addHandler(capture)
    try:
        with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=FailingRepo()) as trace:  # type: ignore[arg-type]
            trace.set_outcome("answer")
            with trace.span("parse"):
                pass
        ck(current_trace() is None, "p5.failing_repo_clean")
        ck(any("trace_finish_error" in m for m in capture.messages), f"p5.failing_repo_logged:{capture.messages}")
    finally:
        tracer_logger.removeHandler(capture)

    # 无 repo：全 API no-op 且不创建任何 DB 文件（在全新 cwd 下验证）
    empty_dir = tempfile.mkdtemp(prefix="t003a-norepo-")
    old_cwd = os.getcwd()
    os.chdir(empty_dir)
    try:
        with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE) as trace:
            trace.set_outcome("answer")
            with trace.span("parse"):
                pass
            trace.finish()
        ck(current_trace() is None, "p5.norepo_clean")
        created = sorted(str(p.relative_to(empty_dir)) for p in Path(empty_dir).rglob("*"))
        ck(created == [], f"p5.norepo_creates_no_files:{created}")
    finally:
        os.chdir(old_cwd)

    # 真实 SQLite 回环
    tmpdir = tempfile.mkdtemp(prefix="t003a-store-")
    repo = TraceRepository(Path(tmpdir) / "traces.sqlite3")
    try:
        with start_trace(
            http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE,
            path=TracePath.RAG, repo=repo,
        ) as trace:
            trace.set_request_id("req-1")
            trace.set_question("城东店的宣传海报在哪里？")
            with trace.span("parse"):
                pass
            with trace.span("recall") as recall:
                with trace.span("exact_recall", hits=2):
                    pass
            with trace.span("fuse"):
                pass
            with trace.span("answer"):
                pass
            with trace.span("commit"):
                pass
            trace.set_outcome("answer", answer_source="rag")
        record, spans = repo.get(trace.trace_id)
        ck(record.request_id == "req-1" and record.status == "ok", "p5.roundtrip_trace")
        ck([s.name for s in spans] == ["parse", "recall", "exact_recall", "fuse", "answer", "commit"], "p5.roundtrip_spans")  # type: ignore[attr-defined]
        ck(spans[2].parent_span_id == recall.span_id, "p5.roundtrip_parent")  # type: ignore[attr-defined]
        ck(validate_required_spans(record, [s.name for s in spans]) == [], "p5.roundtrip_integrity")  # type: ignore[attr-defined]
    finally:
        repo.close()

    # 已关闭 repo 不抛
    repo2 = TraceRepository(Path(tmpdir) / "closed.sqlite3")
    repo2.close()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo2) as trace:
        trace.set_outcome("answer")
    ck(current_trace() is None, "p5.closed_repo_clean")


# ---- §5.6 内容模式 ----

def p_content_modes() -> None:
    section("content-modes")
    question = "城东店的宣传海报在哪里？"

    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo) as trace:  # type: ignore[arg-type]
        trace.set_question(question)
        trace.set_outcome("answer")
    record, _ = repo.best_effort_calls[0]
    ck(record.content_mode == "hash", f"p6.default_hash:{record.content_mode}")
    ck(record.question_hash == hashlib.sha256(question.encode("utf-8")).hexdigest(), "p6.sha256_digest")
    ck(record.question_hash == hash_question(question, algo="sha256"), "p6.consistent_with_versioning_sha256")
    ck(record.question_chars == len(question), "p6.question_chars")
    ck(record.hash_algo == "sha256" and record.hmac_key_id is None, "p6.sha256_fields")
    ck(question not in serialized(record, []), "p6.no_plaintext")

    key = b"t003a-verify-hmac-key-32bytes!!"
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo, hmac_key=key) as trace:  # type: ignore[arg-type]
        trace.set_question(question)
        trace.set_outcome("answer")
    record, _ = repo.best_effort_calls[0]
    ck(record.question_hash == hmac.new(key, question.encode("utf-8"), hashlib.sha256).hexdigest(), "p6.hmac_digest")
    ck(record.question_hash == hash_question(question, key=key, algo="hmac-sha256"), "p6.consistent_with_versioning_hmac")
    ck(record.hash_algo == "hmac-sha256", "p6.hmac_algo")
    ck(record.hmac_key_id == key_fingerprint(key), "p6.hmac_key_id_fingerprint")
    blob = serialized(record, [])
    ck(key.decode() not in blob, "p6.key_not_stored")
    ck(record.hmac_key_id is not None and len(record.hmac_key_id) == 12, "p6.key_id_length")

    # 空 key：与 versioning.hash_question 口径一致 —— hmac 需非空 key 会抛，sha256 允许空 key
    hmac_empty_raises = False
    try:
        hash_question(question, key=b"", algo="hmac-sha256")
    except ValueError:
        hmac_empty_raises = True
    ck(hmac_empty_raises, "p6.versioning_hmac_empty_key_raises")
    ck(hash_question(question, key=b"", algo="sha256") == hashlib.sha256(question.encode()).hexdigest(), "p6.versioning_sha256_empty_key_ok")
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo, hmac_key=b"") as trace:  # type: ignore[arg-type]
        trace.set_question(question)
        trace.set_outcome("answer")
    record, _ = repo.best_effort_calls[0]
    ck(record.hash_algo == "sha256" and record.hmac_key_id is None, "p6.empty_key_degrades_to_sha256")
    ck(record.question_hash == hash_question(question, algo="sha256"), "p6.empty_key_sha256_digest")

    # off：只有计数与 ID，无问题文本
    repo = SpyRepo()
    with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, repo=repo, content_mode="off") as trace:  # type: ignore[arg-type]
        trace.set_question(question)
        trace.set_outcome("answer")
        with trace.span("parse", query_chars=len(question)):
            pass
    record, spans = repo.best_effort_calls[0]
    ck(record.content_mode == "off", "p6.off_recorded")
    ck(record.question_hash is None and record.hash_algo is None and record.hmac_key_id is None, "p6.off_no_digest")
    ck(record.question_chars == len(question), "p6.off_keeps_count")
    ck(question not in serialized(record, spans), "p6.off_no_plaintext")  # type: ignore[arg-type]

    # redacted / full 未实现 → 显式 fail closed，且不残留 contextvar
    for mode in ("redacted", "full"):
        raised = False
        try:
            with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, content_mode=mode):  # type: ignore[arg-type]
                pass
        except ValueError:
            raised = True
        ck(raised, f"p6.{mode}_fail_closed")
        ck(current_trace() is None, f"p6.{mode}_no_contextvar_left")

    raised = False
    try:
        with start_trace(http_request_id="http-1", mode=TraceMode.LOCAL, scope=SCOPE, content_mode="plaintext"):
            pass
    except ValueError:
        raised = True
    ck(raised, "p6.unknown_mode_fail_closed")
    ck(current_trace() is None, "p6.unknown_mode_clean")


# ---- §5.7 validate_required_spans ----

def p_validate() -> None:
    section("validate")
    rag_answer = ["parse", "recall", "fuse", "answer", "commit"]
    legacy_answer = ["intent_parse", "retrieve", "model_answer", "answer_validate", "commit"]

    # 设计 §6.4 表 8 行的完整集合均返回 []
    rows = [
        (make_record(path="rag", outcome_kind="answer"), rag_answer),
        (make_record(path="rag", outcome_kind="conflict"), rag_answer),
        (make_record(path="rag", outcome_kind="clarification"), ["parse", "commit"]),
        (make_record(path="rag", outcome_kind="no_answer"), ["parse", "recall", "fuse", "commit"]),
        (make_record(path="rag", outcome_kind="ambiguous"), ["parse", "recall", "fuse", "commit"]),
        (make_record(path="rag", outcome_kind="error"), ["parse", "commit"]),
        (make_record(path="rag", outcome_kind="knowledge_changed"), ["parse", "commit"]),
        (make_record(path="legacy", outcome_kind="answer"), legacy_answer),
        (make_record(path="legacy_with_rag_candidates", outcome_kind="answer"), legacy_answer),
        (make_record(path="legacy", outcome_kind="not_found"), ["intent_parse", "retrieve", "commit"]),
        (make_record(path="legacy", outcome_kind="clarification"), ["intent_parse", "commit"]),
        (make_record(path="legacy", outcome_kind="service_error"), ["intent_parse", "commit"]),
    ]
    for index, (record, names) in enumerate(rows):
        ck(validate_required_spans(record, names) == [], f"p7.row{index}_complete_empty:{record.path}+{record.outcome_kind}")
        ck(validate_required_spans(record, names[1:]) == sorted(names[:1]), f"p7.row{index}_missing_first:{record.path}+{record.outcome_kind}")

    # 缺失清单排序 + 多余 Span 不算缺失
    ck(validate_required_spans(make_record(path="rag", outcome_kind="answer"), ["parse", "recall"]) == ["answer", "commit", "fuse"], "p7.missing_sorted")
    ck(validate_required_spans(make_record(path="rag", outcome_kind="answer"), [*rag_answer, "rerank", "index_sync"]) == [], "p7.extra_spans_ok")

    # rag + clarification 不得误要求 answer（handoff 显式点）
    ck("answer" not in required_spans(TracePath.RAG, "clarification"), "p7.clarification_no_answer_rule")
    ck(validate_required_spans(make_record(path="rag", outcome_kind="clarification"), ["parse", "commit"]) == [], "p7.clarification_complete")
    ck(validate_required_spans(make_record(path="rag", outcome_kind="clarification"), ["parse"]) == ["commit"], "p7.clarification_missing_commit")

    # 条件 Span：四个属性分别 true/false，且可从任意 *_json 顶层键读到
    conditions = {
        "vector_enabled": "vector_recall",
        "rerank_enabled": "rerank",
        "expansion_triggered": "query_expansion",
        "index_sync_performed": "index_sync",
    }
    for flag, span_name in conditions.items():
        rec_true = make_record(
            path="rag", outcome_kind="answer",
            filter_decisions_json=json.dumps({flag: True}, ensure_ascii=False),
        )
        ck(validate_required_spans(rec_true, rag_answer) == [span_name], f"p7.conditional_true:{flag}")
        ck(validate_required_spans(rec_true, [*rag_answer, span_name]) == [], f"p7.conditional_present:{flag}")
        rec_false = make_record(
            path="rag", outcome_kind="answer",
            filter_decisions_json=json.dumps({flag: False}, ensure_ascii=False),
        )
        ck(validate_required_spans(rec_false, rag_answer) == [], f"p7.conditional_false:{flag}")
        rec_other = make_record(
            path="rag", outcome_kind="answer",
            retrieval_counts_json=json.dumps({flag: True}, ensure_ascii=False),
        )
        ck(validate_required_spans(rec_other, rag_answer) == [span_name], f"p7.conditional_other_json:{flag}")

    all_true = make_record(
        path="rag", outcome_kind="answer",
        filter_decisions_json=json.dumps({flag: True for flag in conditions}, ensure_ascii=False),
    )
    ck(validate_required_spans(all_true, rag_answer) == sorted(conditions.values()), "p7.conditional_all_true_sorted")

    # 设计未定义组合 fail closed
    for path, outcome in [
        ("rag", "service_error"),
        ("rag", "not_found"),
        ("legacy", "conflict"),
        ("legacy", "ambiguous"),
        ("legacy", "knowledge_changed"),
    ]:
        raised = False
        try:
            validate_required_spans(make_record(path=path, outcome_kind=outcome), [])
        except ValueError:
            raised = True
        ck(raised, f"p7.undefined_combo_fail_closed:{path}+{outcome}")

    # 缺 path / outcome fail closed
    for overrides in ({"path": None}, {"outcome_kind": None}):
        raised = False
        try:
            validate_required_spans(make_record(**overrides), [])
        except ValueError:
            raised = True
        ck(raised, f"p7.missing_field_fail_closed:{overrides}")

    # span_names 单字符串 TypeError；可迭代对象均可
    raised = False
    try:
        validate_required_spans(make_record(), "parse")  # type: ignore[arg-type]
    except TypeError:
        raised = True
    ck(raised, "p7.single_string_type_error")
    ck(validate_required_spans(make_record(), tuple(rag_answer)) == [], "p7.tuple_input")
    ck(validate_required_spans(make_record(), set(rag_answer)) == [], "p7.set_input")
    ck(validate_required_spans(make_record(), (n for n in rag_answer)) == [], "p7.generator_input")

    # 纯函数：不修改记录；缺 outcome 时仍保持原样
    record = make_record(path="rag", outcome_kind="answer")
    before = asdict(record)
    validate_required_spans(record, ["parse"])
    ck(asdict(record) == before, "p7.no_mutation")

    # 条件属性为 false 时不要求（避免“未执行不伪造”的反向误判）
    rec = make_record(
        path="rag", outcome_kind="answer",
        filter_decisions_json=json.dumps({"vector_enabled": False, "rerank_enabled": False}),
    )
    ck(validate_required_spans(rec, rag_answer) == [], "p7.false_flags_not_required")


def main() -> None:
    print(f"probe python={sys.version.split()[0]} mktkb={mktkb.__file__}", flush=True)
    sections = [
        p_import_boundaries,
        p_contextvars,
        p_lifecycle,
        p_spans,
        p_setters,
        p_write_semantics,
        p_content_modes,
        p_validate,
    ]
    for func in sections:
        func()
    print(f"PROBE-PASS::{CHECKS} checks in {len(sections)} sections", flush=True)


if __name__ == "__main__":
    try:
        main()
    except ProbeFailure as exc:
        print(f"PROBE-FAIL::{exc}", file=sys.stderr)
        raise SystemExit(1)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print("PROBE-ERROR", file=sys.stderr)
        raise SystemExit(2)
