"""T306 集成隔离库独立复算：只读 SQL，绕开应用查询代码，验证 overview 与下钻明细一致。

口径（任务书 §2 / T301 §2）：
- 已完成问答量 = status='succeeded' + result_message_id 非空 + finished_at 落在左闭右开 UTC 窗口，
  按产品请求行去重；未提交中断不入六类；
- 六类结果取自 result_json.kind；已删除会话两侧排除；
- 引用按「结果消息+文档」「结果消息+版本」去重；冲突不计入最终引用；
- 库存为当前口径；Trace 覆盖率分母为已完成请求，纯重放不计。

运行：
    .venv\\Scripts\\python.exe -B docs\\reports\\OBS-EVAL\\P3\\T306-evidence\\scripts\\t306_recompute_integration.py
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
T306_ROOT = Path(__file__).resolve().parents[1]
DB = T306_ROOT / "isolated-var" / "mktkb.sqlite3"
TRACE_DB = T306_ROOT / "isolated-var" / "observability" / "qa-traces.sqlite3"
SEED = T306_ROOT / "isolated-var" / "seed-summary.json"
OUT = T306_ROOT / "recompute-integration" / "recompute-results.json"

SHANGHAI = timezone(timedelta(hours=8))
SIX = ("answer", "clarification", "not_found", "conflict", "service_error", "knowledge_changed")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def window(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time.min, tzinfo=SHANGHAI).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=SHANGHAI).astimezone(timezone.utc)
    return start.isoformat(), end.isoformat()


def load_completed(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT r.id AS request_id, r.client_request_id, r.result_message_id, r.result_json
        FROM conversation_requests r
        LEFT JOIN conversations c ON r.conversation_id = c.id
        WHERE r.status = 'succeeded'
          AND r.result_message_id IS NOT NULL
          AND r.finished_at >= ? AND r.finished_at < ?
          AND (c.id IS NULL OR c.deleted_at IS NULL)
        ORDER BY r.finished_at, r.id
        """,
        (start, end),
    ).fetchall()


def kind_of(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return json.loads(raw).get("kind")
    except json.JSONDecodeError:
        return None


def main() -> int:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    conn = connect(DB)
    trace = connect(TRACE_DB)

    days = [
        ("today", date.fromisoformat(seed["dates"]["today"])),
        ("yesterday", date.fromisoformat(seed["dates"]["yesterday"])),
        ("empty", date.fromisoformat(seed["dates"]["empty_since"])),
    ]

    result: dict = {"windows": {}, "requests_detail": {}, "citations": {}, "inventory": {}, "trace": {}}
    problems: list[str] = []

    for label, day in days:
        start, end = window(day)
        rows = load_completed(conn, start, end)
        kinds = Counter(kind_of(row["result_json"]) for row in rows)
        distinct = len({row["client_request_id"] for row in rows if row["client_request_id"]})
        metrics = seed["metrics"][{"today": "today", "yesterday": "yesterday", "empty": "empty"}[label]]
        item = {
            "window_utc": [start, end],
            "completed": len(rows),
            "distinct_client_requests": distinct,
            "six": {kind: kinds.get(kind, 0) for kind in SIX},
            "other": {kind: count for kind, count in kinds.items() if kind not in SIX},
            "request_ids": [row["request_id"] for row in rows],
        }
        result["windows"][label] = item
        if item["completed"] != metrics["completed"]:
            problems.append(f"{label}: completed {item['completed']} != overview {metrics['completed']}")
        if distinct != item["completed"]:
            problems.append(f"{label}: distinct client_request_id {distinct} != completed")
        for key, observed in (
            ("not_found", item["six"]["not_found"]),
            ("conflict", item["six"]["conflict"]),
        ):
            if observed != metrics[key]:
                problems.append(f"{label}: {key} {observed} != overview {metrics[key]}")

    week_start, _ = window(date.fromisoformat(seed["dates"]["today"]) - timedelta(days=6))
    _, week_end = window(date.fromisoformat(seed["dates"]["today"]))
    week_end = (
        datetime.combine(date.fromisoformat(seed["dates"]["today"]) + timedelta(days=1), time.min, tzinfo=SHANGHAI)
        .astimezone(timezone.utc)
        .isoformat()
    )
    week_rows = load_completed(conn, week_start, week_end)
    week_kinds = Counter(kind_of(row["result_json"]) for row in week_rows)
    result["windows"]["week7d"] = {
        "completed": len(week_rows),
        "six": {kind: week_kinds.get(kind, 0) for kind in SIX},
    }
    if len(week_rows) != seed["metrics"]["week7d"]["completed"]:
        problems.append("week7d: completed mismatch")
    if len(week_rows) != seed["requests"]["week7d"]:
        problems.append("week7d: 明细页码累计数 != 独立复算")
    for label in ("today", "yesterday"):
        expected_total = seed["requests"].get(label, seed["metrics"][label]["completed"])
        if len(result["windows"][label]["request_ids"]) != expected_total:
            problems.append(f"{label}: 明细条数 != 独立复算")

    # 引用：按消息+文档 / 消息+版本去重；冲突问答不产生持久引用行（本种子 conflict 无 sources）。
    seen_docs: set[tuple[str, str]] = set()
    seen_versions: set[tuple[str, str]] = set()
    raw_rows = 0
    for row in week_rows:
        kind = kind_of(row["result_json"])
        if kind == "conflict":
            continue
        sources = conn.execute(
            "SELECT document_id, version_id FROM conversation_message_sources WHERE message_id = ?",
            (row["result_message_id"],),
        ).fetchall()
        raw_rows += len(sources)
        for source in sources:
            seen_docs.add((row["result_message_id"], source["document_id"]))
            seen_versions.add((row["result_message_id"], source["version_id"]))
    result["citations"] = {
        "raw_rows_non_conflict": raw_rows,
        "document_dedup_pairs": len(seen_docs),
        "version_dedup_pairs": len(seen_versions),
        "conflict_rows": conn.execute(
            """
            SELECT COUNT(*) FROM conversation_message_sources s
            JOIN conversation_messages m ON m.id = s.message_id
            WHERE m.kind = 'conflict'
            """
        ).fetchone()[0],
    }
    expected = seed["detail"]["answer_multi"]["citation_count"]
    if result["citations"]["document_dedup_pairs"] != 4 or expected != 1:
        problems.append("citations: 去重对数与种子不一致")

    result["inventory"] = {
        "review_required_versions": conn.execute(
            "SELECT COUNT(*) FROM document_versions WHERE state = 'review_required'"
        ).fetchone()[0],
        "active_published_versions": conn.execute(
            "SELECT COUNT(*) FROM document_versions WHERE state = 'published'"
        ).fetchone()[0],
        "failed_jobs": conn.execute(
            "SELECT COUNT(*) FROM import_jobs WHERE state = 'failed' AND error_code = 'PARSE_INCOMPLETE'"
        ).fetchone()[0],
    }
    if result["inventory"]["review_required_versions"] != seed["metrics"]["week7d"]["review"]:
        problems.append("inventory: review_required != overview")
    if result["inventory"]["failed_jobs"] != seed["documents_count"]["failed"]:
        problems.append("inventory: failed jobs != 物料列表筛选总数")

    trace_rows = trace.execute("SELECT request_id, status, replayed FROM traces").fetchall()
    recorded = {
        row["request_id"].replace("-", "")
        for row in trace_rows
        if row["status"] == "ok" and not row["replayed"]
    }
    completed_ids = {row["request_id"].replace("-", "") for row in week_rows}
    result["trace"] = {
        "completed_denominator": len(completed_ids),
        "covered": len(recorded & completed_ids),
        "untracked": len(completed_ids - recorded),
        "ratio": round(len(recorded & completed_ids) / len(completed_ids), 4) if completed_ids else None,
        "status_expected": "partial" if 0 < len(recorded & completed_ids) < len(completed_ids) else "full",
    }
    if result["trace"]["status_expected"] != seed["metrics"]["week7d"]["trace_status"]:
        problems.append("trace: coverage status != overview")

    result["problems"] = problems
    result["requests_detail"] = {
        "today": len(result["windows"]["today"]["request_ids"]),
        "yesterday": len(result["windows"]["yesterday"]["request_ids"]),
        "week7d": len(week_rows),
        "overview_today": seed["metrics"]["today"]["completed"],
        "overview_week7d": seed["metrics"]["week7d"]["completed"],
    }
    result["consistent"] = not problems
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"RECOMPUTE_RESULTS={OUT}")
    print("RECOMPUTE_OK" if not problems else "RECOMPUTE_MISMATCH")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
