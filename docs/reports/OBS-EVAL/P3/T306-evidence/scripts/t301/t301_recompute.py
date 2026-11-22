"""T301 独立复算：绕过应用查询代码，直接用 sqlite3 对隔离库计算指标预期值并对账。

口径（任务书 §2）：
- 问答量按完成时间 + 产品请求 ID 去重，只计已提交结果；幂等重放不增量；
- 六类结果 answer/clarification/not_found/conflict/service_error/knowledge_changed；
  未提交中断单列，不入六类；已逻辑删除会话的请求统计与明细两侧均排除；
- 时间按 Asia/Shanghai 聚合，日历日转左闭右开 UTC 窗口；
- 引用量按「结果消息+文档」去重、版本维度按「结果消息+版本」去重；同一回答引用同一资料多行只计一次；
  冲突消息不产生持久引用行，两方来源取自结果 JSON 的 conflicts，最终引用计数不含冲突；
- Trace 覆盖率 = 有普通执行 Trace 的已完成请求数 ÷ 已完成请求数；纯重放不计覆盖；
  关闭/不可用/未记录/部分覆盖为独立状态；库存指标按「当前」口径。

输出 evidence/recompute/recompute-results.json；不写业务 var/ 库。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import t301_common as common
from t301_common import BUSINESS_DB, MATRIX_DIR, RECOMPUTE_DIR, TRACE_DB

SHANGHAI = timezone(timedelta(hours=8))
SIX_KINDS = ("answer", "clarification", "not_found", "conflict", "service_error", "knowledge_changed")


def _hex(value: str | None) -> str | None:
    return value.replace("-", "") if value else None


def _load_matrix() -> dict[str, Any]:
    return json.loads((MATRIX_DIR / "sample-matrix.json").read_text(encoding="utf-8"))


def _connect(path: Path) -> sqlite3.Connection:
    # T306 复算副本：强制只读 URI，确保对 T301 冻结库零写操作。
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _kind_of(result_json: str | None) -> str | None:
    if not result_json:
        return None
    try:
        return json.loads(result_json).get("kind")
    except json.JSONDecodeError:
        return None


def _shanghai_day(finished_at: str | None) -> str | None:
    if not finished_at:
        return None
    parsed = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI).date().isoformat()


def compute() -> dict[str, Any]:
    matrix = _load_matrix()
    samples = {s["sample_id"]: s for s in matrix["samples"]}
    biz = _connect(BUSINESS_DB)
    trace = _connect(TRACE_DB) if TRACE_DB.exists() else None

    # ---- 范围：已逻辑删除会话两侧排除 ----
    request_rows = biz.execute(
        """
        SELECT r.id, r.conversation_id, r.client_request_id, r.status, r.attempt,
               r.result_message_id, r.result_json, r.error_code, r.finished_at,
               c.deleted_at IS NOT NULL AS deleted
        FROM conversation_requests r
        LEFT JOIN conversations c ON r.conversation_id = c.id
        """
    ).fetchall()

    in_scope: list[sqlite3.Row] = [r for r in request_rows if not r["deleted"]]
    deleted_rows = [r for r in request_rows if r["deleted"]]

    completed = [r for r in in_scope if r["status"] == "succeeded" and r["result_message_id"] and r["result_json"]]
    interrupted = [r for r in in_scope if r not in completed]

    # 问答量：产品请求 ID 去重（重放不新增请求行；同时给 client_request_id 口径对照）
    completed_by_request = {r["id"]: r for r in completed}
    completed_by_client = {r["client_request_id"]: r for r in completed}

    six_distribution: dict[str, int] = {k: 0 for k in SIX_KINDS}
    other_kind: dict[str, int] = {}
    for r in completed:
        kind = _kind_of(r["result_json"])
        if kind in six_distribution:
            six_distribution[kind] += 1
        else:
            other_kind[kind] = other_kind.get(kind, 0) + 1

    # 按日趋势（Asia/Shanghai）
    daily: dict[str, int] = {}
    for r in completed:
        day = _shanghai_day(r["finished_at"])
        daily[day] = daily.get(day, 0) + 1

    # ---- 引用量（直接对消息来源表计算；冲突消息最终计数剔除） ----
    source_rows = biz.execute(
        """
        SELECT s.message_id, s.document_id, s.version_id, m.kind, m.conversation_id,
               c.deleted_at IS NOT NULL AS deleted
        FROM conversation_message_sources s
        JOIN conversation_messages m ON m.id = s.message_id
        LEFT JOIN conversations c ON c.id = m.conversation_id
        """
    ).fetchall()

    citation_in_scope = [s for s in source_rows if not s["deleted"]]
    citation_conflict = [s for s in citation_in_scope if s["kind"] == "conflict"]
    citation_non_conflict = [s for s in citation_in_scope if s["kind"] != "conflict"]

    doc_pairs = {(s["message_id"], s["document_id"]) for s in citation_non_conflict}
    version_pairs = {(s["message_id"], s["version_id"]) for s in citation_non_conflict}

    # 冲突消息：result_json.conflicts 两方来源
    conflict_messages = biz.execute(
        """
        SELECT r.id AS request_id, r.result_json, m.id AS message_id
        FROM conversation_requests r
        JOIN conversation_messages m ON m.id = r.result_message_id
        WHERE m.kind = 'conflict'
        """
    ).fetchall()
    conflict_records = []
    for row in conflict_messages:
        rj = json.loads(row["result_json"] or "{}")
        conflict_records.append({
            "request_id": row["request_id"],
            "message_id": row["message_id"],
            "conflicts": rj.get("conflicts") or [],
            "persisted_source_rows": sum(1 for s in citation_conflict if s["message_id"] == row["message_id"]),
        })

    # ---- 库存指标（当前口径） ----
    versions = biz.execute("SELECT document_id, number, state FROM document_versions").fetchall()
    review_required = [v for v in versions if v["state"] == "review_required"]
    active_versions = [v for v in versions if v["state"] == "published"]
    failed_versions = [v for v in versions if v["state"] == "failed"]

    jobs = biz.execute("SELECT id, version_id, state, error_code, retryable FROM import_jobs").fetchall()
    failed_jobs = [j for j in jobs if j["state"] == "failed"]

    # ---- Trace 覆盖率 ----
    trace_rows: list[sqlite3.Row] = []
    if trace is not None:
        trace_rows = trace.execute("SELECT * FROM traces").fetchall()
    traces_by_request: dict[str, list[sqlite3.Row]] = {}
    replay_traces: list[sqlite3.Row] = []
    for t in trace_rows:
        traces_by_request.setdefault(_hex(t["request_id"]), []).append(t)
        if t["status"] == "replayed":
            replay_traces.append(t)

    coverage_states: dict[str, list[str]] = {"covered": [], "disabled": [], "untracked": []}
    for r in completed:
        traces = traces_by_request.get(r["id"], [])
        ordinary = [t for t in traces if t["status"] != "replayed"]
        if ordinary:
            coverage_states["covered"].append(r["id"])
        else:
            # 受控样本未写 Trace；关闭态样本无 Trace 行
            sample = next((s for s in samples.values() if (s.get("request") or {}).get("request_id", "").replace("-", "") == r["id"]), None)
            if sample and sample.get("trace_enabled") is False:
                coverage_states["disabled"].append(r["id"])
            else:
                coverage_states["untracked"].append(r["id"])

    covered = len(coverage_states["covered"])
    total_completed = len(completed)
    coverage = round(covered / total_completed, 4) if total_completed else None

    # ---- 午夜边界专项 ----
    midnight = []
    for sid in ("S17", "S18"):
        sample = samples[sid]
        rid = _hex(sample["request"]["request_id"])
        row = biz.execute("SELECT finished_at FROM conversation_requests WHERE id=?", (rid,)).fetchone()
        actual_day = _shanghai_day(row["finished_at"]) if row else None
        midnight.append({
            "sample_id": sid,
            "expected_shanghai_day": sample["extra"]["expected_shanghai_day"],
            "actual_shanghai_day": actual_day,
            "finished_at": row["finished_at"] if row else None,
            "consistent": actual_day == sample["extra"]["expected_shanghai_day"],
        })

    # ---- 已删除会话专项 ----
    deleted_check = []
    for sid in ("S10",):
        sample = samples[sid]
        rid = _hex(sample["request"]["request_id"])
        row = biz.execute(
            "SELECT r.id, c.deleted_at FROM conversation_requests r "
            "JOIN conversations c ON c.id = r.conversation_id WHERE r.id=?", (rid,)
        ).fetchone()
        in_stats = row is not None and row["deleted_at"] is None
        deleted_check.append({
            "sample_id": sid,
            "request_id": rid,
            "conversation_deleted": bool(row and row["deleted_at"]),
            "excluded_from_statistics": not in_stats,
            "consistent": bool(row and row["deleted_at"]) and not in_stats,
        })

    # ---- 预期值（来自样本矩阵设计）与对账 ----
    expected = {
        "completed_requests": 13,  # 10 正常启用 + 1 关闭态 + 2 受控午夜
        "completed_distinct_client_requests": 13,
        "six_distribution": {
            "answer": 8, "clarification": 1, "not_found": 1, "conflict": 1,
            "service_error": 1, "knowledge_changed": 1,
        },
        "interrupted_count": 2,
        "deleted_excluded_count": 1,
        "citation_raw_non_conflict": 13,
        "citation_document_dedup": 6,
        "citation_version_dedup": 6,
        "conflict_persisted_rows_actual": 2,  # 实测代码行为（口径缺口，见报告）
        "review_required_versions": 1,
        "failed_jobs": 1,
        "trace_covered": 10,
        "trace_replay_traces": 1,
        "trace_disabled": 1,
        "trace_untracked": 2,
    }

    actual = {
        "completed_requests": len(completed_by_request),
        "completed_distinct_client_requests": len(completed_by_client),
        "six_distribution": six_distribution,
        "interrupted_count": len(interrupted),
        "deleted_excluded_count": len(deleted_rows),
        "citation_raw_non_conflict": len(citation_non_conflict),
        "citation_document_dedup": len(doc_pairs),
        "citation_version_dedup": len(version_pairs),
        "conflict_persisted_rows_actual": len(citation_conflict),
        "review_required_versions": len(review_required),
        "failed_jobs": len(failed_jobs),
        "trace_covered": covered,
        "trace_replay_traces": len(replay_traces),
        "trace_disabled": len(coverage_states["disabled"]),
        "trace_untracked": len(coverage_states["untracked"]),
    }

    checks: list[dict[str, Any]] = []
    for key in (
        "completed_requests", "completed_distinct_client_requests", "interrupted_count",
        "deleted_excluded_count", "citation_raw_non_conflict", "citation_document_dedup",
        "citation_version_dedup", "review_required_versions", "failed_jobs",
        "trace_covered", "trace_replay_traces", "trace_disabled", "trace_untracked",
    ):
        checks.append({
            "metric": key, "expected": expected[key], "actual": actual[key],
            "consistent": expected[key] == actual[key],
        })
    for kind in SIX_KINDS:
        checks.append({
            "metric": f"six_distribution.{kind}",
            "expected": expected["six_distribution"][kind],
            "actual": six_distribution[kind],
            "consistent": expected["six_distribution"][kind] == six_distribution[kind],
        })

    result = {
        "scope": {
            "request_rows_total": len(request_rows),
            "in_scope_requests": len(in_scope),
            "deleted_excluded": len(deleted_rows),
        },
        "answer_volume": {
            "completed_requests": len(completed_by_request),
            "distinct_client_requests": len(completed_by_client),
            "note": "重放复用同一请求行，不新增请求；无重复请求 ID 需二次去重。",
        },
        "six_distribution": six_distribution,
        "other_kind": other_kind,
        "interrupted": [
            {"request_id": r["id"], "status": r["status"], "error_code": r["error_code"]}
            for r in interrupted
        ],
        "daily_trend_shanghai": daily,
        "citations": {
            "raw_rows_in_scope": len(citation_in_scope),
            "raw_rows_non_conflict": len(citation_non_conflict),
            "conflict_message_rows_excluded": len(citation_conflict),
            "document_dedup_pairs": len(doc_pairs),
            "version_dedup_pairs": len(version_pairs),
            "conflict_records": conflict_records,
        },
        "inventory": {
            "review_required_versions": len(review_required),
            "active_published_versions": len(active_versions),
            "failed_versions": len(failed_versions),
            "failed_jobs": [
                {"job_id": j["id"], "version_id": j["version_id"], "error_code": j["error_code"]}
                for j in failed_jobs
            ],
        },
        "trace_coverage": {
            "completed_denominator": total_completed,
            "covered": covered,
            "coverage_ratio": coverage,
            "replay_traces": [
                {"trace_id": t["trace_id"], "request_id": _hex(t["request_id"]),
                 "http_request_id": t["http_request_id"], "previous_trace_id": t["previous_trace_id"]}
                for t in replay_traces
            ],
            "states": {k: len(v) for k, v in coverage_states.items()},
            "state_requests": {k: v for k, v in coverage_states.items()},
        },
        "midnight_boundary": midnight,
        "deleted_conversation": deleted_check,
        "expected_vs_actual": {"expected": expected, "actual": actual, "checks": checks},
    }

    RECOMPUTE_DIR.mkdir(parents=True, exist_ok=True)
    (RECOMPUTE_DIR / "recompute-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    biz.close()
    if trace is not None:
        trace.close()
    return result


if __name__ == "__main__":
    out = compute()
    inconsistencies = [c for c in out["expected_vs_actual"]["checks"] if not c["consistent"]]
    print(f"completed={out['answer_volume']['completed_requests']} "
          f"coverage={out['trace_coverage']['coverage_ratio']} "
          f"inconsistent={len(inconsistencies)}")
    for item in inconsistencies:
        print("MISMATCH", item)
