# T301 只读探针：对原业务库 / Trace 库以 mode=ro 打开，只执行 SELECT / PRAGMA。
# 不在原库或副本上做任何写入；输出仅含计数、状态码、Span 名与哈希标识，
# 不含问题/答案正文、请求头或凭据。
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BIZ = ROOT / "var" / "mktkb.sqlite3"
TRC = ROOT / "var" / "observability" / "qa-traces.sqlite3"


def open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, check_same_thread=False)


def report(title: str, conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    print(f"\n== {title} ==")
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        print(f"  ERROR: {exc}")
        return
    for row in rows:
        print("  " + " | ".join("" if v is None else str(v) for v in row))
    if not rows:
        print("  (empty)")


biz = open_ro(BIZ)
trc = open_ro(TRC)

# ---------- 业务库 ----------
report("conversations 总数 / 已逻辑删除", biz,
       "SELECT COUNT(*), SUM(deleted_at IS NOT NULL) FROM conversations")

report("conversation_requests 按 status", biz,
       "SELECT status, COUNT(*) FROM conversation_requests GROUP BY status ORDER BY 1")

report("请求关联结果消息：result_message_id 为空 / 非空", biz,
       "SELECT (result_message_id IS NULL), COUNT(*) FROM conversation_requests GROUP BY 1")

report("结果消息按 kind（含已删除会话）", biz,
       "SELECT m.kind, COUNT(*) FROM conversation_messages m "
       "WHERE m.role='assistant' GROUP BY m.kind ORDER BY 1")

report("结果消息按 kind（排除已删除会话）", biz,
       "SELECT m.kind, COUNT(*) FROM conversation_messages m "
       "JOIN conversations c ON c.id=m.conversation_id "
       "WHERE m.role='assistant' AND c.deleted_at IS NULL GROUP BY m.kind ORDER BY 1")

report("冲突消息是否存在持久 MessageSource 行（核心口径核对）", biz,
       "SELECT m.kind, COUNT(DISTINCT m.id), COUNT(s.id) "
       "FROM conversation_messages m LEFT JOIN conversation_message_sources s "
       "ON s.message_id=m.id WHERE m.role='assistant' AND m.kind='conflict' "
       "GROUP BY m.kind")

report("MessageSource 按消息 kind 汇总（持久引用行归属）", biz,
       "SELECT m.kind, COUNT(s.id) AS source_rows, COUNT(DISTINCT s.message_id) AS messages "
       "FROM conversation_message_sources s JOIN conversation_messages m ON m.id=s.message_id "
       "GROUP BY m.kind ORDER BY 1")

report("document_versions 按 state", biz,
       "SELECT state, COUNT(*) FROM document_versions GROUP BY state ORDER BY 1")

report("documents 总数 / 已删除 / 有有效版本", biz,
       "SELECT COUNT(*), SUM(deleted), SUM(active_version_id IS NOT NULL) FROM documents")

report("import_jobs 按 state", biz,
       "SELECT state, COUNT(*) FROM import_jobs GROUP BY state ORDER BY 1")

report("import_jobs 按 stage（前 20）", biz,
       "SELECT stage, COUNT(*) FROM import_jobs GROUP BY stage ORDER BY 2 DESC LIMIT 20")

report("request 时间字段空值：finished_at 空 / started_at 空 / 总数", biz,
       "SELECT SUM(finished_at IS NULL), SUM(started_at IS NULL), COUNT(*) FROM conversation_requests")

# ---------- Trace 库 ----------
report("traces 总数", trc, "SELECT COUNT(*) FROM traces")
report("traces 按 mode", trc, "SELECT mode, COUNT(*) FROM traces GROUP BY mode ORDER BY 1")
report("traces 按 path", trc, "SELECT path, COUNT(*) FROM traces GROUP BY path ORDER BY 1")
report("traces 按 outcome_kind", trc, "SELECT outcome_kind, COUNT(*) FROM traces GROUP BY outcome_kind ORDER BY 1")
report("traces 按 status", trc, "SELECT status, COUNT(*) FROM traces GROUP BY status ORDER BY 1")
report("traces 按 replayed", trc, "SELECT replayed, COUNT(*) FROM traces GROUP BY 1")
report("traces 请求关联：request_id 为空 / 非空", trc,
       "SELECT (request_id IS NULL OR request_id=''), COUNT(*) FROM traces GROUP BY 1")
report("span 名称分布", trc,
       "SELECT name, COUNT(*) FROM spans GROUP BY name ORDER BY 2 DESC, 1")
report("重放记录的 trace 数与 span 数", trc,
       "SELECT t.replayed, COUNT(DISTINCT t.trace_id), COUNT(s.span_id) "
       "FROM traces t LEFT JOIN spans s ON s.trace_id=t.trace_id GROUP BY t.replayed")

biz.close()
trc.close()
print("\nDONE")
