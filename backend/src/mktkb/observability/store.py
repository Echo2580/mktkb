"""T002：SQLite Trace 仓储（设计 §6.2 存储 / §6.6 写入语义）。

本模块只使用标准库 ``sqlite3``，只依赖 T001 冻结的 ``contracts``；不 import 任何业务包
（``qa`` / ``rag`` / ``conversations`` / ``main``），也不触碰业务库。产品形态与设计一致：
``TraceRepository(Path("var/observability/qa-traces.sqlite3"))``，与 ``mktkb.sqlite3`` /
``rag-index.sqlite3`` 完全分离。

存储契约：

- 表 ``schema_meta`` / ``traces`` / ``spans``；``traces`` / ``spans`` 列名与
  ``TraceRecord`` / ``SpanRecord`` 字段一一对应，JSON 字段保持 TEXT 原样存取
  （序列化由写入方按设计 §6.2 的 ``ensure_ascii=False, sort_keys=True`` 完成），
  store 不重排、不转义；
- ``PRAGMA journal_mode=WAL``；``write`` 用单事务写 trace + spans；
- 写入失败：``write`` 抛 ``TraceWriteError``；``write_best_effort`` 只记
  ``trace_write_error`` 日志、不抛（设计 §6.6：不能影响产品响应）；
- 所有 SQL 参数化：值一律走 ``?`` 占位符，DDL / INSERT 的列名只来自本模块常量；
- 保留策略：``purge`` 的 30 天 / 100,000 条先到先清由调用方组合参数表达，
  无参数时不删任何数据（设计 §6.2）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from collections import defaultdict
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from .contracts import TRACE_SCHEMA_VERSION, SpanRecord, TraceRecord

LOGGER = logging.getLogger(__name__)

_META_SCHEMA_VERSION_KEY = "trace_schema_version"

_TRACE_COLUMNS: tuple[str, ...] = tuple(field.name for field in fields(TraceRecord))
_SPAN_COLUMNS: tuple[str, ...] = tuple(field.name for field in fields(SpanRecord))
_INSERT_TRACE_SQL = "INSERT INTO traces ({}) VALUES ({})".format(
    ", ".join(_TRACE_COLUMNS), ", ".join("?" for _ in _TRACE_COLUMNS)
)
_INSERT_SPAN_SQL = "INSERT INTO spans ({}) VALUES ({})".format(
    ", ".join(_SPAN_COLUMNS), ", ".join("?" for _ in _SPAN_COLUMNS)
)

#: WAL 模式下持久化在库头；重复执行幂等，两个连接同时建表也安全。
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY NOT NULL,
    request_id TEXT,
    http_request_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    replayed INTEGER NOT NULL DEFAULT 0,
    previous_trace_id TEXT,
    trace_schema_version TEXT,
    mode TEXT,
    scope TEXT,
    path TEXT,
    case_id TEXT,
    dataset_version TEXT,
    run_id TEXT,
    index_revision TEXT,
    manifest_sha256 TEXT,
    pipeline_version TEXT,
    config_hash TEXT,
    query_kind TEXT,
    outcome_kind TEXT,
    reason TEXT,
    answer_source TEXT,
    content_mode TEXT NOT NULL DEFAULT 'hash',
    question_hash TEXT,
    question_chars INTEGER,
    hash_algo TEXT,
    hmac_key_id TEXT,
    user_id_hash TEXT,
    conversation_id_hash TEXT,
    retrieval_counts_json TEXT,
    filter_decisions_json TEXT,
    fact_gate_json TEXT,
    citation_refs_json TEXT,
    pagination_json TEXT,
    token_usage_json TEXT,
    cost_json TEXT,
    go_decision TEXT,
    degraded_json TEXT,
    latency_ms INTEGER,
    status TEXT,
    error_code TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT PRIMARY KEY NOT NULL,
    trace_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT,
    started_at TEXT,
    duration_ms INTEGER,
    status TEXT,
    attributes_json TEXT,
    error_code TEXT,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_traces_request_id ON traces(request_id, attempt);
CREATE INDEX IF NOT EXISTS idx_traces_created_at ON traces(created_at);
CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
"""

#: 无法解析创建时间的记录在“保留最新 N 条”排序中的落点（视作最旧）。
_EPOCH_FLOOR = datetime.min.replace(tzinfo=timezone.utc)


class TraceWriteError(RuntimeError):
    """Trace 仓储读写失败。

    ``write`` 直接抛该异常；``write_best_effort`` 捕获后只记 ``trace_write_error``
    日志（设计 §6.6）。读 / 导出 / purge 在仓储不可用（已 ``close()``、库文件打不开、
    schema 版本不兼容）时同样抛该异常，便于调用方区分“没有数据”与“库不可用”。
    """


def _parse_created_at(value: object) -> datetime | None:
    """把 ``created_at`` 文本解析成 UTC ``datetime``；缺失/不可解析返回 ``None``。

    接受 ISO-8601（含 ``Z`` 后缀与偏移）；无时区按 UTC 解释。解析失败不猜测时间。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _recency_key(row: sqlite3.Row) -> tuple[datetime, int]:
    """``purge(keep_last=...)`` 的“旧 → 新”排序键（rowid 做同刻兜底）。"""
    created = _parse_created_at(row["created_at"]) or _EPOCH_FLOOR
    return (created, int(row["store_rowid"]))


def _validate_non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} 必须是非负整数，收到 {value!r}")


class TraceRepository:
    """SQLite Trace 仓储：写读回环、按 request 列表、JSONL 导出与保留期清理。"""

    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self._path = Path(path)
        self._timeout = float(timeout)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._closed = False
        # 构造期打不开库（父路径是普通文件、sqlite 拒绝打开等）时延迟失败：产品写入是
        # best-effort，观测库不可用不应让进程在启动期崩溃。首次实际操作会重试并抛
        # TraceWriteError；schema 版本不兼容属于配置错误，直接 fail closed。
        try:
            self._conn = self._open_connection()
        except (sqlite3.Error, OSError):
            self._conn = None

    def __enter__(self) -> TraceRepository:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---- 公共 API ----

    def write(self, trace: TraceRecord, spans: Sequence[SpanRecord]) -> None:
        """单事务写入一条 trace 及其 spans；失败抛 ``TraceWriteError`` 并整体回滚。"""
        prepared_trace, prepared_spans = self._prepare(trace, spans)
        with self._lock:
            conn = self._connection()
            try:
                with conn:
                    conn.execute(_INSERT_TRACE_SQL, self._trace_values(prepared_trace))
                    span_rows = [self._span_values(span) for span in prepared_spans]
                    if span_rows:
                        conn.executemany(_INSERT_SPAN_SQL, span_rows)
            except sqlite3.Error as exc:
                raise TraceWriteError(f"写入 trace {prepared_trace.trace_id!r} 失败：{exc}") from exc

    def write_best_effort(self, trace: TraceRecord, spans: Sequence[SpanRecord]) -> None:
        """best-effort 写入：任何失败只记 ``trace_write_error`` 日志，绝不向调用方抛出。"""
        try:
            self.write(trace, spans)
        except Exception:  # noqa: BLE001 - best-effort 不得影响产品响应（设计 §6.6）
            LOGGER.warning(
                "trace_write_error: trace_id=%r request_id=%r",
                getattr(trace, "trace_id", None),
                getattr(trace, "request_id", None),
                exc_info=True,
            )

    def get(self, trace_id: str) -> tuple[TraceRecord, list[SpanRecord]]:
        """按 ``trace_id`` 读取一条 trace 与其 spans（按写入顺序）；不存在抛 ``KeyError``。"""
        if not isinstance(trace_id, str) or not trace_id:
            raise ValueError("trace_id 必须是非空 str")
        with self._lock:
            conn = self._connection()
            try:
                trace_row = conn.execute(
                    "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
                ).fetchone()
                if trace_row is None:
                    raise KeyError(trace_id)
                span_rows = conn.execute(
                    "SELECT * FROM spans WHERE trace_id = ? ORDER BY rowid ASC", (trace_id,)
                ).fetchall()
            except sqlite3.Error as exc:
                raise TraceWriteError(f"读取 trace {trace_id!r} 失败：{exc}") from exc
        return self._row_to_trace(trace_row), [self._row_to_span(row) for row in span_rows]

    def list_by_request(self, request_id: str) -> list[TraceRecord]:
        """同一产品请求的全部尝试（按 ``attempt`` 升序、同 attempt 按写入顺序）；未知返回空。"""
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id 必须是非空 str")
        with self._lock:
            conn = self._connection()
            try:
                rows = conn.execute(
                    "SELECT * FROM traces WHERE request_id = ? ORDER BY attempt ASC, rowid ASC",
                    (request_id,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise TraceWriteError(f"读取 request {request_id!r} 的 trace 失败：{exc}") from exc
        return [self._row_to_trace(row) for row in rows]

    def export_jsonl(self, out: Path, *, since: datetime | None = None) -> int:
        """导出为 JSONL（每行是 ``TraceRecord`` 全部字段 + 嵌套 ``spans`` 数组），返回导出条数。

        - 行数 = 满足 ``since`` 的 trace 数，按写入顺序；
        - ``since`` 为 None 时导出全部；带时区/无时区均按 UTC 解释；
        - 只导出、不并行写，JSONL 不是第二写入源（设计 §6.2）。
        """
        since_utc = self._coerce_since(since)
        with self._lock:
            conn = self._connection()
            try:
                conn.execute("BEGIN")
                try:
                    trace_rows = conn.execute("SELECT * FROM traces ORDER BY rowid ASC").fetchall()
                    span_rows = conn.execute("SELECT * FROM spans ORDER BY rowid ASC").fetchall()
                finally:
                    conn.rollback()
            except sqlite3.Error as exc:
                raise TraceWriteError(f"导出前读取 trace 失败：{exc}") from exc

        spans_by_trace: dict[str, list[SpanRecord]] = defaultdict(list)
        for row in span_rows:
            spans_by_trace[row["trace_id"]].append(self._row_to_span(row))

        count = 0
        try:
            out = Path(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8", newline="\n") as handle:
                for row in trace_rows:
                    trace = self._row_to_trace(row)
                    if since_utc is not None:
                        created = _parse_created_at(trace.created_at)
                        # 无法证明“新”的记录在 since 过滤下不导出
                        if created is None or created < since_utc:
                            continue
                    payload = asdict(trace)
                    payload["spans"] = [
                        asdict(span) for span in spans_by_trace.get(trace.trace_id or "", [])
                    ]
                    handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                    handle.write("\n")
                    count += 1
        except OSError as exc:
            raise TraceWriteError(f"导出 JSONL 到 {out} 失败：{exc}") from exc
        return count

    def purge(self, *, older_than_days: int | None = None, keep_last: int | None = None) -> int:
        """清理过期/超量 trace，返回删除的 trace 条数（spans 一并清理）。

        - ``older_than_days``：删除 ``created_at`` 早于该天数的记录；创建时间缺失或不可
          解析的记录不按年龄清理（不能证明它旧）；
        - ``keep_last``：只保留最近 N 条，其余删除；同刻按写入顺序；
        - 两者同时给出时取并集（先到先清）；
        - 无参数时不删任何数据（返回 0），负值抛 ``ValueError``。
        """
        if older_than_days is None and keep_last is None:
            return 0
        if older_than_days is not None:
            _validate_non_negative_int("older_than_days", older_than_days)
        if keep_last is not None:
            _validate_non_negative_int("keep_last", keep_last)

        delete_ids: list[str] = []
        with self._lock:
            conn = self._connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    rows = conn.execute(
                        "SELECT rowid AS store_rowid, trace_id, created_at "
                        "FROM traces ORDER BY rowid ASC"
                    ).fetchall()
                    delete_ids = self._select_purge_ids(rows, older_than_days, keep_last)
                    if delete_ids:
                        ids = [(trace_id,) for trace_id in delete_ids]
                        conn.executemany("DELETE FROM spans WHERE trace_id = ?", ids)
                        conn.executemany("DELETE FROM traces WHERE trace_id = ?", ids)
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
            except sqlite3.Error as exc:
                raise TraceWriteError(f"清理 trace 失败：{exc}") from exc
        return len(delete_ids)

    def close(self) -> None:
        """关闭仓储；可重复调用，之后所有访问抛 ``TraceWriteError``。"""
        with self._lock:
            self._closed = True
            conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover - 关闭失败不改变已关闭状态
                LOGGER.warning("trace_store_close_error", exc_info=True)

    # ---- 连接与 schema ----

    def _open_connection(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._path), timeout=self._timeout, check_same_thread=False
        )
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta (key, value) VALUES (?, ?)",
            (_META_SCHEMA_VERSION_KEY, TRACE_SCHEMA_VERSION),
        )
        conn.commit()
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (_META_SCHEMA_VERSION_KEY,)
        ).fetchone()
        stored = None if row is None else row[0]
        if stored != TRACE_SCHEMA_VERSION:
            raise TraceWriteError(
                "trace_schema_version 不兼容：库内 "
                f"{stored!r}，当前契约 {TRACE_SCHEMA_VERSION!r}"
            )

    def _connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise TraceWriteError("TraceRepository 已关闭，不能访问 trace 数据库")
            if self._conn is None:
                try:
                    self._conn = self._open_connection()
                except (sqlite3.Error, OSError) as exc:
                    raise TraceWriteError(f"无法打开 trace 数据库 {self._path}：{exc}") from exc
            return self._conn

    # ---- 行转换与写入准备 ----

    @staticmethod
    def _prepare(
        trace: TraceRecord, spans: Sequence[SpanRecord]
    ) -> tuple[TraceRecord, list[SpanRecord]]:
        if not isinstance(trace, TraceRecord):
            raise TypeError("trace 必须是 TraceRecord")
        if not trace.trace_id:
            raise TraceWriteError("TraceRecord.trace_id 不能为空：无法写入 trace")
        prepared_spans: list[SpanRecord] = []
        for span in spans:
            if not isinstance(span, SpanRecord):
                raise TypeError("spans 只接受 SpanRecord")
            if span.trace_id is not None and span.trace_id != trace.trace_id:
                raise TraceWriteError(
                    f"SpanRecord.trace_id={span.trace_id!r} "
                    f"与 trace_id={trace.trace_id!r} 不一致"
                )
            prepared_spans.append(
                replace(span, span_id=span.span_id or uuid.uuid4().hex, trace_id=trace.trace_id)
            )
        return trace, prepared_spans

    @staticmethod
    def _trace_values(trace: TraceRecord) -> tuple[Any, ...]:
        return tuple(getattr(trace, name) for name in _TRACE_COLUMNS)

    @staticmethod
    def _span_values(span: SpanRecord) -> tuple[Any, ...]:
        return tuple(getattr(span, name) for name in _SPAN_COLUMNS)

    @staticmethod
    def _row_to_trace(row: sqlite3.Row) -> TraceRecord:
        values = {name: row[name] for name in _TRACE_COLUMNS}
        values["replayed"] = bool(values["replayed"])
        return TraceRecord(**values)

    @staticmethod
    def _row_to_span(row: sqlite3.Row) -> SpanRecord:
        return SpanRecord(**{name: row[name] for name in _SPAN_COLUMNS})

    @staticmethod
    def _coerce_since(since: datetime | None) -> datetime | None:
        if since is None:
            return None
        if not isinstance(since, datetime):
            raise TypeError("since 必须是 datetime 或 None")
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return since.astimezone(timezone.utc)

    @staticmethod
    def _select_purge_ids(
        rows: Sequence[sqlite3.Row],
        older_than_days: int | None,
        keep_last: int | None,
    ) -> list[str]:
        delete_ids: set[str] = set()
        if older_than_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
            for row in rows:
                created = _parse_created_at(row["created_at"])
                if created is not None and created < cutoff:
                    delete_ids.add(row["trace_id"])
        if keep_last is not None and len(rows) > keep_last:
            ordered = sorted(rows, key=_recency_key)
            for row in ordered[: len(ordered) - keep_last]:
                delete_ids.add(row["trace_id"])
        return sorted(delete_ids)


__all__ = ["TraceRepository", "TraceWriteError"]
