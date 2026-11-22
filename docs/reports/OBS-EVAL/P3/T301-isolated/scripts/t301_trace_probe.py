"""T301 Trace 抽查：直接读隔离 Trace 库与业务库，记录关联方式、重放标记、两态 Span 清单。

脱敏约束：只记录 Span 名 / 时长 / 状态 / 关联键；不摘录 Trace 原始属性、密钥、原始请求头、原文问题。
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

import t301_common as common
from t301_common import BUSINESS_DB, MATRIX_DIR, TRACE_DB, TRACE_DIR


def _hex(value: str | None) -> str | None:
    return value.replace("-", "") if value else None


def compute() -> dict[str, Any]:
    matrix = json.loads((MATRIX_DIR / "sample-matrix.json").read_text(encoding="utf-8"))
    samples = {s["sample_id"]: s for s in matrix["samples"]}

    biz = sqlite3.connect(str(BUSINESS_DB))
    biz.row_factory = sqlite3.Row
    trace = sqlite3.connect(str(TRACE_DB)) if TRACE_DB.exists() else None
    trace.row_factory = sqlite3.Row if trace else None

    biz_request_ids = {
        row["id"] for row in biz.execute("SELECT id FROM conversation_requests")
    }

    traces: list[dict[str, Any]] = []
    span_inventory: dict[str, dict[str, Any]] = defaultdict(lambda: {"span_names": [], "examples": []})
    replay_pairs: list[dict[str, Any]] = []

    if trace is not None:
        for t in trace.execute("SELECT * FROM traces ORDER BY rowid ASC"):
            spans = [
                {"span_id": s["span_id"], "name": s["name"], "duration_ms": s["duration_ms"],
                 "status": s["status"], "parent_span_id": s["parent_span_id"]}
                for s in trace.execute(
                    "SELECT * FROM spans WHERE trace_id=? ORDER BY rowid ASC", (t["trace_id"],)
                )
            ]
            path = t["path"] or "unknown"
            record = {
                "trace_id": t["trace_id"],
                "request_id": t["request_id"],
                "http_request_id": t["http_request_id"],
                "attempt": t["attempt"],
                "replayed": bool(t["replayed"]),
                "previous_trace_id": t["previous_trace_id"],
                "path": path,
                "outcome_kind": t["outcome_kind"],
                "status": t["status"],
                "reason": t["reason"],
                "latency_ms": t["latency_ms"],
                "question_chars": t["question_chars"],
                "span_count": len(spans),
                "span_names": [s["name"] for s in spans],
            }
            traces.append(record)

            bucket = span_inventory[path]
            bucket["span_names"] = sorted({*bucket["span_names"], *[s["name"] for s in spans]})
            if len(bucket["examples"]) < 2:
                bucket["examples"].append({
                    "trace_id": t["trace_id"], "request_id": t["request_id"],
                    "outcome_kind": t["outcome_kind"], "status": t["status"],
                    "spans": [{"name": s["name"], "duration_ms": s["duration_ms"], "status": s["status"]} for s in spans],
                })

        # 重放配对：同一 request_id 下普通 Trace + replayed Trace
        by_request: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for t in trace.execute("SELECT * FROM traces ORDER BY rowid ASC"):
            by_request[_hex(t["request_id"])].append(t)
        for req_id, rows in by_request.items():
            replay_rows = [r for r in rows if r["replayed"]]
            ordinary = [r for r in rows if not r["replayed"]]
            if replay_rows:
                for r in replay_rows:
                    replay_pairs.append({
                        "request_id": req_id,
                        "replay_trace_id": r["trace_id"],
                        "replay_http_request_id": r["http_request_id"],
                        "replay_status": r["status"],
                        "replay_span_count": trace.execute(
                            "SELECT COUNT(*) FROM spans WHERE trace_id=?", (r["trace_id"],)
                        ).fetchone()[0],
                        "original_trace_ids": [o["trace_id"] for o in ordinary],
                        "original_http_request_ids": [o["http_request_id"] for o in ordinary],
                    })

    # 关联键核验：Trace.request_id 能否在业务库请求行命中
    linkage = []
    for t in traces:
        linkage.append({
            "trace_id": t["trace_id"],
            "request_id_in_business_db": _hex(t["request_id"]) in biz_request_ids,
            "http_request_id_recorded": bool(t["http_request_id"]),
        })

    # 关闭态样本：业务库有请求行，但 Trace 库无对应记录
    disabled = []
    for sid, sample in samples.items():
        if sample.get("trace_enabled") is False:
            rid = _hex((sample.get("request") or {}).get("request_id"))
            trace_row = None
            if trace is not None and rid:
                trace_row = trace.execute(
                    "SELECT trace_id, status FROM traces WHERE request_id=?",
                    (sample["request"]["request_id"],),
                ).fetchone()
            disabled.append({
                "sample_id": sid,
                "request_id": rid,
                "business_request_exists": rid in biz_request_ids,
                "trace_row_found": trace_row is not None,
                "trace_header_present": sample["extra"].get("trace_header_present"),
                "state": "disabled" if trace_row is None else "other",
            })

    # 旧版引用可展示字段（取换版前 S11 结果 JSON 中的来源键；只记字段名与版本标识）
    old_version_fields: list[str] = []
    old_version_sample = None
    s11 = samples.get("S11")
    if s11 and s11.get("request"):
        rid = s11["request"]["request_id"]
        row = biz.execute(
            "SELECT result_json FROM conversation_requests WHERE id=?", (_hex(rid),)
        ).fetchone()
        if row and row["result_json"]:
            rj = json.loads(row["result_json"])
            sources = rj.get("sources") or []
            if sources:
                old_version_fields = sorted(sources[0].keys())
                old_version_sample = {
                    "sample_id": "S11",
                    "version_number": sources[0].get("version_number"),
                    "document_name_present": "document_name" in sources[0],
                    "status": sources[0].get("status"),
                    "locator_present": "locator" in sources[0],
                    "published_at_present": "published_at" in sources[0],
                }

    result = {
        "trace_db": str(TRACE_DB.relative_to(common.EVIDENCE_DIR.parent)),
        "trace_count": len(traces),
        "linkage": {
            "request_id": "Trace.request_id = ConversationRequest.id（产品请求 ID）",
            "http_request_id": "Trace.http_request_id 对应响应头 X-Request-ID；重放为新 HTTP 请求，故 http_request_id 不同",
            "checks": linkage,
        },
        "path_span_inventory": dict(span_inventory),
        "traces": traces,
        "replay": {
            "pairs": replay_pairs,
            "note": "重放 Trace：replayed=1、status=replayed、Span 为空；复用同一产品请求 ID；previous_trace_id 在本重放链路中未回填（实测为 null）。",
        },
        "disabled_state": disabled,
        "old_version_citation_fields": {
            "sample": old_version_sample,
            "field_keys": old_version_fields,
            "note": "旧版引用结果 JSON 来源条目仍携带 document_name/version_number/status/locator/published_at；版本号 1 在换版后历史消息中保持可展示。",
        },
    }

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    (TRACE_DIR / "trace-probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    biz.close()
    if trace is not None:
        trace.close()
    return result


if __name__ == "__main__":
    out = compute()
    print(f"traces={out['trace_count']} replay={len(out['replay']['pairs'])} "
          f"paths={list(out['path_span_inventory'].keys())}")
