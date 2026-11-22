"""T306 性能实测（只读）：两库 × 三窗口 × 三类核心查询，各 5 次取中位数/最大值。

- 只用 sqlite3 只读连接（`mode=ro`），不建索引、不改任何库；
- 查询形状对齐 T302 运营查询的过滤/排序/聚合主路径（完成量、问答分页、资料引用聚合），
  属“等价形状”探针，不等同于应用逐行 Python 聚合的端到端耗时；
- 同时输出 `EXPLAIN QUERY PLAN` 原文，供评估索引收益（本次不执行 CREATE INDEX）。

运行：
    .venv\\Scripts\\python.exe -B docs\\reports\\OBS-EVAL\\P3\\T306-evidence\\scripts\\perf_probe.py
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
T306_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = T306_ROOT / "perf"
SHANGHAI = timezone(timedelta(hours=8))

DATABASES = {
    "integration": {
        "label": "T306 集成隔离库（受控种子）",
        "path": T306_ROOT / "isolated-var" / "mktkb.sqlite3",
        "reference": date(2026, 11, 22),
    },
    "t301": {
        "label": "T301 隔离基准库（冻结只读）",
        "path": Path(r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P3\T301-isolated\evidence\data\mktkb.sqlite3"),
        "reference": date(2026, 11, 21),
    },
}

QUERIES = {
    "overview_completed": """
        SELECT COUNT(DISTINCT r.client_request_id) AS completed
        FROM conversation_requests r
        LEFT JOIN conversations c ON c.id = r.conversation_id
        WHERE r.status = 'succeeded'
          AND r.result_message_id IS NOT NULL
          AND r.finished_at >= ? AND r.finished_at < ?
          AND (c.id IS NULL OR c.deleted_at IS NULL)
    """,
    "requests_page": """
        SELECT r.id AS request_id, r.result_json, r.finished_at
        FROM conversation_requests r
        LEFT JOIN conversations c ON c.id = r.conversation_id
        WHERE r.status = 'succeeded'
          AND r.result_message_id IS NOT NULL
          AND r.finished_at >= ? AND r.finished_at < ?
          AND (c.id IS NULL OR c.deleted_at IS NULL)
        ORDER BY r.finished_at DESC, r.id DESC
        LIMIT 21 OFFSET 0
    """,
    "documents_citations": """
        SELECT s.document_id, COUNT(DISTINCT s.message_id) AS messages
        FROM conversation_message_sources s
        JOIN conversation_messages m ON m.id = s.message_id
        JOIN conversation_requests r ON r.result_message_id = m.id
        LEFT JOIN conversations c ON c.id = r.conversation_id
        WHERE r.status = 'succeeded'
          AND r.finished_at >= ? AND r.finished_at < ?
          AND (c.id IS NULL OR c.deleted_at IS NULL)
          AND COALESCE(m.kind, '') <> 'conflict'
        GROUP BY s.document_id
        ORDER BY messages DESC
    """,
}


def connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def window(day: date, key: str) -> tuple[str, str]:
    if key == "today":
        start_day, end_day = day, day + timedelta(days=1)
    elif key == "7d":
        start_day, end_day = day - timedelta(days=6), day + timedelta(days=1)
    elif key == "30d":
        start_day, end_day = day - timedelta(days=29), day + timedelta(days=1)
    else:
        raise ValueError(key)
    start = datetime.combine(start_day, dtime.min, tzinfo=SHANGHAI).astimezone(timezone.utc)
    end = datetime.combine(end_day, dtime.min, tzinfo=SHANGHAI).astimezone(timezone.utc)
    return start.isoformat(), end.isoformat()


def scale(conn: sqlite3.Connection, start: str, end: str) -> dict:
    total_requests = conn.execute("SELECT COUNT(*) FROM conversation_requests").fetchone()[0]
    total_documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    total_sources = conn.execute("SELECT COUNT(*) FROM conversation_message_sources").fetchone()[0]
    in_window = conn.execute(
        "SELECT COUNT(*) FROM conversation_requests WHERE finished_at >= ? AND finished_at < ?",
        (start, end),
    ).fetchone()[0]
    return {
        "total_requests": total_requests,
        "total_documents": total_documents,
        "total_message_sources": total_sources,
        "requests_in_window": in_window,
    }


def measure(conn: sqlite3.Connection, sql: str, params: tuple[str, str], runs: int = 5) -> dict:
    timings: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        conn.execute(sql, params).fetchall()
        timings.append((time.perf_counter() - started) * 1000)
    timings_sorted = sorted(timings)
    return {
        "runs": runs,
        "median_ms": round(statistics.median(timings), 3),
        "max_ms": round(max(timings), 3),
        "min_ms": round(min(timings), 3),
        "samples_ms": [round(value, 3) for value in timings],
    }


def main() -> int:
    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "databases": {}, "plans": {}}
    for key, spec in DATABASES.items():
        conn = connect(spec["path"])
        dataset: dict = {"label": spec["label"], "path": str(spec["path"]), "reference_date": spec["reference"].isoformat(), "windows": {}}
        for window_key in ("today", "7d", "30d"):
            start, end = window(spec["reference"], window_key)
            dataset["windows"][window_key] = {
                "utc": [start, end],
                "scale": scale(conn, start, end),
                "timings": {name: measure(conn, sql, (start, end)) for name, sql in QUERIES.items()},
            }
        start, end = window(spec["reference"], "7d")
        report["plans"][key] = {
            name: [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", (start, end))]
            for name, sql in QUERIES.items()
        }
        conn.close()
        report["databases"][key] = dataset

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "perf-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# T306 性能实测（只读、未建索引）",
        "",
        "口径：进程内 sqlite3 只读连接，单查询 5 次取中位数/最大值；时间为毫秒；查询为 T302 主路径的等价形状，并非完整 API 端到端。",
        "",
    ]
    for key, dataset in report["databases"].items():
        lines.append(f"## {dataset['label']}")
        lines.append("")
        lines.append("| 窗口 | 窗口内请求行 | 总请求行 | 资料数 | 来源行 | 查询 | 中位 ms | 最大 ms |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for window_key, block in dataset["windows"].items():
            s = block["scale"]
            for name, timing in block["timings"].items():
                lines.append(
                    f"| {window_key} | {s['requests_in_window']} | {s['total_requests']} | {s['total_documents']} | "
                    f"{s['total_message_sources']} | {name} | {timing['median_ms']} | {timing['max_ms']} |"
                )
        lines.append("")
        lines.append("EXPLAIN QUERY PLAN（7d）：")
        lines.append("")
        for name, steps in report["plans"][key].items():
            lines.append(f"- `{name}`")
            for step in steps:
                lines.append(f"  - {step}")
        lines.append("")
    (OUT_DIR / "perf-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["databases"], ensure_ascii=False, indent=2))
    for key, plans in report["plans"].items():
        print(f"[{key}] EXPLAIN QUERY PLAN")
        for name, steps in plans.items():
            print(f"  {name}:")
            for step in steps:
                print(f"    {step}")
    print(f"PERF_JSON={OUT_DIR / 'perf-results.json'}")
    print("PERF_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
