"""T002：SQLite Trace 仓储测试（设计 §6.2 存储 / §6.6 写入语义；计划 Task 2）。

只依赖标准库 ``sqlite3`` 与 T001 冻结契约；所有数据库、导出文件都写在 ``tmp_path`` 下，
不触碰 ``var/``、``mktkb.sqlite3`` / ``rag-index.sqlite3``；零真实模型 / OCR / embedding /
rerank 调用，不读 ``.env``，不访问网络。

覆盖 handoff §5 八条验收：写读回环、best-effort、建表幂等/WAL、按 request 列表、
JSONL 导出、purge、SQL 参数化与并发、契约字段锁定。
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import sqlite3
import threading
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mktkb.observability import store as store_module
from mktkb.observability.contracts import TRACE_SCHEMA_VERSION, SpanRecord, TraceRecord
from mktkb.observability.store import TraceRepository, TraceWriteError

# ---- 测试数据：全字段 Trace 模板 + 构造辅助 ----


def _canonical_json(payload: object) -> str:
    """与设计 §6.2 一致的 canonical JSON（ensure_ascii=False, sort_keys=True）。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_RICH_TRACE = TraceRecord(
    trace_id="t-rich",
    request_id="r-rich",
    http_request_id="http-0001",
    attempt=2,
    replayed=False,
    previous_trace_id="t-previous",
    trace_schema_version=TRACE_SCHEMA_VERSION,
    mode="local",
    scope="end_to_end",
    path="rag",
    case_id="B0-001",
    dataset_version="b0:label-2026-11-04:0123456789ab",
    run_id="run-20261104",
    index_revision="idx-001",
    manifest_sha256="a" * 64,
    pipeline_version="pv-0123456789ab",
    config_hash="ch-0123456789ab",
    query_kind="record",
    outcome_kind="answer",
    reason="命中稳定事实",
    answer_source="fact",
    content_mode="hash",
    question_hash="b" * 64,
    question_chars=11,
    hash_algo="hmac-sha256",
    hmac_key_id="fp-0123456789ab",
    user_id_hash="u-hash",
    conversation_id_hash="c-hash",
    retrieval_counts_json=_canonical_json({"精确命中": 2, "词法命中": 3}),
    filter_decisions_json=_canonical_json({"hard_filters": {"doc_type": "policy"}}),
    fact_gate_json=_canonical_json({"passed": True, "reason": "引用完整"}),
    citation_refs_json=_canonical_json([{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}]),
    pagination_json=_canonical_json({"total": 1, "returned": 1, "has_more": False}),
    token_usage_json=_canonical_json({"input": 100, "output": 20}),
    cost_json=_canonical_json({"cny": 0.0, "source": "mock"}),
    go_decision="go",
    degraded_json=_canonical_json({"degraded": False}),
    latency_ms=123,
    status="success",
    error_code=None,
    created_at="2026-11-04T10:00:00+00:00",
)


def make_trace(**overrides: object) -> TraceRecord:
    """基于全字段模板构造 TraceRecord（未覆盖字段保持模板值）。"""
    return replace(_RICH_TRACE, **overrides)


def make_span(name: str, trace_id: str = "t-rich", **overrides: object) -> SpanRecord:
    base = SpanRecord(
        span_id=f"span-{trace_id}-{name}",
        trace_id=trace_id,
        parent_span_id=None,
        name=name,
        started_at="2026-11-04T10:00:01+00:00",
        duration_ms=7,
        status="ok",
        attributes_json=_canonical_json({"向量通道": "未执行", "count": 3}),
        error_code=None,
    )
    return replace(base, **overrides)


def _table_names(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def _schema_meta(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())
    finally:
        conn.close()


# ---- §5.1 写读回环：同一 TraceRecord + 按名称匹配的 SpanRecord ----


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        trace = make_trace(trace_id="t1", request_id="r1")
        spans = [make_span("parse", "t1"), make_span("answer", "t1")]
        repo.write(trace, spans)

        loaded_trace, loaded_spans = repo.get("t1")

        assert loaded_trace == trace
        assert [span.name for span in loaded_spans] == ["parse", "answer"]
        assert loaded_spans == spans
    finally:
        repo.close()


def test_roundtrip_bare_trace_with_defaults(tmp_path: Path) -> None:
    """只有 trace_id/request_id 的最小记录（其余字段 None/默认值）也必须无损往返。"""
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        trace = TraceRecord(trace_id="t-bare", request_id="r-bare")
        repo.write(trace, [])

        loaded_trace, loaded_spans = repo.get("t-bare")

        assert loaded_trace == trace
        assert loaded_spans == []
    finally:
        repo.close()


def test_roundtrip_span_without_ids_is_normalized(tmp_path: Path) -> None:
    """span_id / trace_id 缺省时由仓储补全，名称与其余字段不变。"""
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        trace = make_trace(trace_id="t-auto", request_id="r-auto")
        repo.write(trace, [SpanRecord(name="parse")])

        loaded_trace, loaded_spans = repo.get("t-auto")

        assert loaded_trace == trace
        assert [span.name for span in loaded_spans] == ["parse"]
        assert loaded_spans[0].trace_id == "t-auto"
        assert loaded_spans[0].span_id
    finally:
        repo.close()


# ---- §5.2 best-effort 不抛 / write 抛 TraceWriteError ----


def test_write_best_effort_swallows_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    repo.close()

    with caplog.at_level(logging.WARNING, logger="mktkb.observability.store"):
        repo.write_best_effort(make_trace(trace_id="t2", request_id="r2"), [])
    # 不抛异常即通过；且只记录 trace_write_error 日志（设计 §6.6）
    assert "trace_write_error" in caplog.text

    with pytest.raises(TraceWriteError):
        repo.write(make_trace(trace_id="t3", request_id="r3"), [])


def test_write_best_effort_when_parent_is_regular_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """父路径是普通文件导致 sqlite 打不开：构造与 best-effort 都不抛，write 抛。"""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("block", encoding="utf-8")

    repo = TraceRepository(blocker / "traces.sqlite3")
    with caplog.at_level(logging.WARNING, logger="mktkb.observability.store"):
        repo.write_best_effort(make_trace(trace_id="t4", request_id="r4"), [])
    assert "trace_write_error" in caplog.text

    with pytest.raises(TraceWriteError):
        repo.write(make_trace(trace_id="t5", request_id="r5"), [])
    repo.close()


def test_operations_after_close_raise_trace_write_error(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    repo.close()

    with pytest.raises(TraceWriteError):
        repo.get("t-missing")
    with pytest.raises(TraceWriteError):
        repo.list_by_request("r-missing")
    with pytest.raises(TraceWriteError):
        repo.export_jsonl(tmp_path / "closed.jsonl")
    with pytest.raises(TraceWriteError):
        repo.purge(keep_last=1)


# ---- §5.3 建表幂等 / schema_meta / WAL ----


def test_schema_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"

    TraceRepository(path).close()
    TraceRepository(path).close()

    assert {"schema_meta", "traces", "spans"} <= _table_names(path)
    assert _schema_meta(path)["trace_schema_version"] == TRACE_SCHEMA_VERSION

    repo = TraceRepository(path)
    repo.close()
    repo.close()  # close 自身幂等


def test_journal_mode_is_wal(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    TraceRepository(path).close()

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_schema_columns_match_contract_dataclasses(tmp_path: Path) -> None:
    """traces / spans 列名与 T001 冻结的 TraceRecord / SpanRecord 字段完全一致。"""
    path = tmp_path / "traces.sqlite3"
    TraceRepository(path).close()

    conn = sqlite3.connect(path)
    try:
        trace_columns = [row[1] for row in conn.execute("PRAGMA table_info(traces)")]
        span_columns = [row[1] for row in conn.execute("PRAGMA table_info(spans)")]
    finally:
        conn.close()

    assert trace_columns == [field.name for field in fields(TraceRecord)]
    assert span_columns == [field.name for field in fields(SpanRecord)]


def test_existing_incompatible_schema_version_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?, ?)",
            ("trace_schema_version", "mktkb.trace.v0.0"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(TraceWriteError, match="trace_schema_version"):
        TraceRepository(path)


# ---- §5.4 list_by_request：多 attempt 全量、未知 request 空列表 ----


def test_list_by_request_returns_multiple_attempts(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        repo.write(make_trace(trace_id="t-a1", request_id="r-multi", attempt=1), [])
        repo.write(make_trace(trace_id="t-a2", request_id="r-multi", attempt=2), [])
        repo.write(make_trace(trace_id="t-a3", request_id="r-multi", attempt=3), [])
        repo.write(make_trace(trace_id="t-other", request_id="r-other", attempt=1), [])

        traces = repo.list_by_request("r-multi")

        assert [trace.trace_id for trace in traces] == ["t-a1", "t-a2", "t-a3"]
        assert [trace.attempt for trace in traces] == [1, 2, 3]
        assert repo.list_by_request("r-unknown") == []
        assert [trace.trace_id for trace in repo.list_by_request("r-other")] == ["t-other"]
    finally:
        repo.close()


# ---- §5.5 export_jsonl：行数一致、可 json.loads、嵌套 spans、since 过滤 ----


def test_export_jsonl_matches_db(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        now = datetime.now(timezone.utc)
        old = make_trace(
            trace_id="t-old",
            request_id="r-export",
            created_at=(now - timedelta(days=10)).isoformat(),
        )
        recent = make_trace(
            trace_id="t-recent",
            request_id="r-export",
            created_at=(now - timedelta(hours=1)).isoformat(),
        )
        repo.write(old, [make_span("parse", "t-old"), make_span("answer", "t-old")])
        repo.write(recent, [])

        out = tmp_path / "export" / "traces.jsonl"
        count = repo.export_jsonl(out)

        assert count == 2
        raw = out.read_text(encoding="utf-8")
        lines = raw.splitlines()
        assert len(lines) == count == 2
        payloads = [json.loads(line) for line in lines]
        assert {payload["trace_id"] for payload in payloads} == {"t-old", "t-recent"}
        by_id = {payload["trace_id"]: payload for payload in payloads}
        assert [span["name"] for span in by_id["t-old"]["spans"]] == ["parse", "answer"]
        assert by_id["t-recent"]["spans"] == []
        # 每行是完整 TraceRecord 字段 + 嵌套 spans（JSONL 只做导出，不是第二写入源）
        assert set(by_id["t-old"]) == {field.name for field in fields(TraceRecord)} | {"spans"}
        assert by_id["t-old"]["request_id"] == "r-export"
        # ensure_ascii=False：中文原文直接落盘，不被 \uXXXX 转义
        assert "引用完整" in raw
        assert "\\u5f15\\u7528" not in raw

        # since 过滤：只导出最近 2 天
        out_recent = tmp_path / "recent.jsonl"
        assert repo.export_jsonl(out_recent, since=now - timedelta(days=2)) == 1
        only = json.loads(out_recent.read_text(encoding="utf-8").splitlines()[0])
        assert only["trace_id"] == "t-recent"
    finally:
        repo.close()


# ---- §5.6 purge：按天数 / 按条数 / 无参数不删 ----


def test_purge_by_age_and_count(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    repo = TraceRepository(path)
    try:
        now = datetime.now(timezone.utc)

        def created(*, days: int = 0, hours: int = 0) -> str:
            return (now - timedelta(days=days, hours=hours)).isoformat()

        repo.write(
            make_trace(trace_id="t-30d", request_id="r-purge", created_at=created(days=30)),
            [make_span("parse", "t-30d")],
        )
        repo.write(make_trace(trace_id="t-10d", request_id="r-purge", created_at=created(days=10)), [])
        repo.write(make_trace(trace_id="t-1h", request_id="r-purge", created_at=created(hours=1)), [])

        # 无参数：不删任何数据
        assert repo.purge() == 0
        assert len(repo.list_by_request("r-purge")) == 3

        # 按天数：30 天 + 10 天前的两条被清理，先到先清
        assert repo.purge(older_than_days=7) == 2
        assert [trace.trace_id for trace in repo.list_by_request("r-purge")] == ["t-1h"]

        conn = sqlite3.connect(path)
        try:
            remaining_spans = conn.execute(
                "SELECT COUNT(*) FROM spans WHERE trace_id IN (?, ?)", ("t-30d", "t-10d")
            ).fetchone()[0]
        finally:
            conn.close()
        assert remaining_spans == 0

        # 按条数：保留最新 2 条，删除最旧的 1 条（换独立库，避免上面的遗留 trace 干扰）
        keep_repo = TraceRepository(tmp_path / "keep.sqlite3")
        try:
            for index, hours in enumerate((3, 2, 1)):
                keep_repo.write(
                    make_trace(trace_id=f"t-keep-{index}", request_id="r-keep", created_at=created(hours=hours)),
                    [],
                )
            assert keep_repo.purge(keep_last=2) == 1
            assert sorted(trace.trace_id for trace in keep_repo.list_by_request("r-keep")) == [
                "t-keep-1",
                "t-keep-2",
            ]
        finally:
            keep_repo.close()
    finally:
        repo.close()


def test_purge_both_criteria_union_and_clear_spans(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    repo = TraceRepository(path)
    try:
        now = datetime.now(timezone.utc)

        def created(*, days: int = 0, hours: int = 0) -> str:
            return (now - timedelta(days=days, hours=hours)).isoformat()

        repo.write(
            make_trace(trace_id="t-both-old", request_id="r-both", created_at=created(days=30)),
            [make_span("parse", "t-both-old")],
        )
        repo.write(
            make_trace(trace_id="t-both-mid", request_id="r-both", created_at=created(days=2)),
            [make_span("recall", "t-both-mid")],
        )
        repo.write(make_trace(trace_id="t-both-new", request_id="r-both", created_at=created(hours=1)), [])

        # 两个条件同时给定时取并集：按天数删 old，按条数删 mid，返回去重后的 2
        assert repo.purge(older_than_days=7, keep_last=1) == 2
        assert [trace.trace_id for trace in repo.list_by_request("r-both")] == ["t-both-new"]

        conn = sqlite3.connect(path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        repo.close()


def test_purge_rejects_negative_arguments(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        with pytest.raises(ValueError):
            repo.purge(older_than_days=-1)
        with pytest.raises(ValueError):
            repo.purge(keep_last=-1)
        assert repo.purge() == 0
    finally:
        repo.close()


# ---- §5.7 SQL 参数化 / 并发与重复打开 ----


def test_sql_is_parameterized_against_injection(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    repo = TraceRepository(path)
    try:
        injection = "r1' OR '1'='1"
        repo.write(make_trace(trace_id="t-safe", request_id=injection), [])
        repo.write(make_trace(trace_id="t-normal", request_id="r-normal"), [])

        assert [trace.trace_id for trace in repo.list_by_request(injection)] == ["t-safe"]
        assert repo.list_by_request("' OR 1=1 --") == []
        assert [trace.trace_id for trace in repo.list_by_request("r-normal")] == ["t-normal"]
        assert repo.get("t-safe")[0].request_id == injection

        weird_id = "t' OR '1'='1"
        repo.write(make_trace(trace_id=weird_id, request_id="r-weird"), [])
        assert repo.get(weird_id)[0].trace_id == weird_id

        conn = sqlite3.connect(path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 3
        finally:
            conn.close()
    finally:
        repo.close()


def test_store_source_does_not_interpolate_sql_values() -> None:
    """抽查：SQL 执行点不得用 f-string / % 拼接值（值一律走 ? 占位符）。"""
    source = inspect.getsource(store_module)
    forbidden = (
        'execute(f"',
        "execute(f'",
        'executemany(f"',
        "executemany(f'",
        'execute("%',
        "execute('%",
        'executescript(f"',
        "executescript(f'",
    )
    for pattern in forbidden:
        assert pattern not in source, f"疑似 SQL 值拼接：{pattern}"


def test_store_module_imports_only_stdlib_and_contracts() -> None:
    """硬约束：store 只允许标准库 + 相对 ``.contracts``，不得引入第三方/业务包。"""
    tree = ast.parse(inspect.getsource(store_module))
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                imported.add((node.module or "").split(".")[0])
            else:
                imported.add(f"{'.' * node.level}{node.module or ''}")

    allowed = {
        "__future__",
        "collections",
        "dataclasses",
        "datetime",
        "json",
        "logging",
        "pathlib",
        "sqlite3",
        "threading",
        "typing",
        "uuid",
    }
    assert imported <= allowed | {".contracts"}


def test_repeated_open_same_file_keeps_schema_and_reads(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    first = TraceRepository(path)
    second = TraceRepository(path)  # 同一文件两个并发连接
    try:
        first.write(make_trace(trace_id="t-first", request_id="r-concurrent"), [])
        second.write(make_trace(trace_id="t-second", request_id="r-concurrent"), [])

        assert first.get("t-second")[0].trace_id == "t-second"
        assert second.get("t-first")[0].trace_id == "t-first"
        assert len(first.list_by_request("r-concurrent")) == 2
    finally:
        first.close()
        second.close()

    third = TraceRepository(path)
    try:
        assert len(third.list_by_request("r-concurrent")) == 2
    finally:
        third.close()
    assert _schema_meta(path)["trace_schema_version"] == TRACE_SCHEMA_VERSION


def test_concurrent_threads_write_without_corruption(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite3"
    TraceRepository(path).close()

    errors: list[BaseException] = []

    def worker(index: int) -> None:
        repo = TraceRepository(path)
        try:
            for item in range(5):
                repo.write(make_trace(trace_id=f"t-{index}-{item}", request_id=f"r-{index}"), [])
        except BaseException as exc:  # noqa: BLE001 - 收集线程异常回到主线程断言
            errors.append(exc)
        finally:
            repo.close()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []

    repo = TraceRepository(path)
    try:
        assert len(repo.list_by_request("r-0")) == 5
        assert len(repo.list_by_request("r-1")) == 5
    finally:
        repo.close()


# ---- 其它存储契约：未知 trace / 非法记录 / 原子性 ----


def test_get_unknown_trace_raises_key_error(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        with pytest.raises(KeyError):
            repo.get("t-missing")
    finally:
        repo.close()


def test_write_rejects_invalid_records(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        with pytest.raises(TraceWriteError):
            repo.write(TraceRecord(), [])  # 缺 trace_id
        with pytest.raises(TraceWriteError):
            repo.write(make_trace(trace_id="t-x"), [make_span("parse", "another-trace")])  # span 归属不一致
    finally:
        repo.close()


def test_write_is_atomic_on_duplicate_span_id(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        duplicate = SpanRecord(span_id="dup-span", trace_id="t-atomic", name="parse")
        with pytest.raises(TraceWriteError):
            repo.write(
                make_trace(trace_id="t-atomic", request_id="r-atomic"),
                [duplicate, replace(duplicate, name="answer")],
            )

        # 整条写入回滚：trace 与 spans 都不留痕，库仍可继续使用
        with pytest.raises(KeyError):
            repo.get("t-atomic")
        repo.write(make_trace(trace_id="t-after", request_id="r-after"), [])
        assert repo.get("t-after")[0].trace_id == "t-after"
    finally:
        repo.close()


def test_duplicate_trace_id_raises_and_keeps_original(tmp_path: Path) -> None:
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    try:
        repo.write(make_trace(trace_id="t-dup", request_id="r-original"), [make_span("parse", "t-dup")])

        with pytest.raises(TraceWriteError):
            repo.write(make_trace(trace_id="t-dup", request_id="r-other"), [make_span("answer", "t-dup")])

        trace, spans = repo.get("t-dup")
        assert trace.request_id == "r-original"
        assert [span.name for span in spans] == ["parse"]
    finally:
        repo.close()
