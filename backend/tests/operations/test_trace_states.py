"""T302 §5.4 T-a~T-d：Trace 关闭 / 读取失败 / 未记录 / 部分覆盖。"""

from __future__ import annotations

import uuid
from datetime import timedelta

from mktkb.observability.contracts import SpanRecord, TraceRecord
from operations.helpers import BASE, make_document, make_request

OPS = "/api/v1/operations"


def _trace(repo, request_id: str, *, replayed: bool = False, attempt: int = 1) -> str:
    trace_id = uuid.uuid4().hex
    repo.write(
        TraceRecord(
            trace_id=trace_id,
            request_id=request_id,
            http_request_id="http-1",
            attempt=attempt,
            replayed=replayed,
            mode="local",
            scope="end_to_end",
            path="rag",
            outcome_kind="answer",
            status="replayed" if replayed else "ok",
            created_at=BASE.isoformat(),
        ),
        [] if replayed else [SpanRecord(name="parse", duration_ms=2, status="ok")],
    )
    return trace_id


def test_empty_window_with_trace_enabled_is_vacuous_not_percentage(trace_admin) -> None:
    """分母 0：不给伪造覆盖率，状态取未记录并注明空样本。"""
    body = trace_admin.get(
        f"{OPS}/overview", params={"since": "2020-01-01", "until": "2020-01-01"}
    ).json()
    coverage = body["trace_coverage"]
    assert coverage["covered"] == 0
    assert coverage["total"] == 0
    assert coverage["status"] == "not_recorded"
    assert "空样本" in (coverage["note"] or "")


def test_trace_disabled_keeps_business_data(admin_client, db) -> None:
    """T-a：Trace 关闭时业务照常返回；coverage status=disabled 且无数值。"""
    doc = make_document(db, name="位置表")
    entry = make_request(
        db, finished_at=BASE, kind="answer",
        sources=((str(doc.document.id), str(doc.versions[0].id)),),
    )
    db.commit()

    overview = admin_client.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert overview["metrics"]["completed_requests"] == 1
    assert overview["trace_coverage"]["status"] == "disabled"
    assert overview["trace_coverage"]["covered"] is None
    assert overview["trace_coverage"]["total"] is None

    listing = admin_client.get(f"{OPS}/requests", params={"window": "7d"}).json()["items"]
    assert listing[0]["trace_status"] == "not_recorded"

    detail = admin_client.get(f"{OPS}/requests/{entry.request.id}").json()
    assert detail["result"]["kind"] == "answer"
    assert detail["citations"][0]["status"] == "active"
    assert detail["trace"]["status"] == "disabled"
    assert detail["trace"]["attempts"] == []


def test_trace_unavailable_does_not_report_coverage(trace_admin, trace_db, trace_ops_app) -> None:
    """T-b：仓储读失败 → unavailable，不报覆盖率，不 500。"""
    entry = make_request(trace_db, finished_at=BASE, kind="answer")
    trace_db.commit()
    trace_ops_app.state.trace_repo.close()

    response = trace_admin.get(f"{OPS}/overview", params={"window": "7d"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metrics"]["completed_requests"] == 1
    assert body["trace_coverage"]["status"] == "unavailable"
    assert body["trace_coverage"]["covered"] is None
    assert body["trace_coverage"]["total"] is None

    detail = trace_admin.get(f"{OPS}/requests/{entry.request.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["trace"]["status"] == "unavailable"
    assert detail.json()["trace"]["attempts"] == []


def test_not_recorded_when_no_trace_rows(trace_admin, trace_db) -> None:
    """T-c：有请求无 Trace 行 → 详情 not_recorded；列表同口径。"""
    entry = make_request(trace_db, finished_at=BASE, kind="answer")
    trace_db.commit()

    overview = trace_admin.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert overview["trace_coverage"]["covered"] == 0
    assert overview["trace_coverage"]["total"] == 1
    assert overview["trace_coverage"]["status"] == "not_recorded"

    listing = trace_admin.get(f"{OPS}/requests", params={"window": "7d"}).json()["items"]
    assert listing[0]["trace_status"] == "not_recorded"

    detail = trace_admin.get(f"{OPS}/requests/{entry.request.id}").json()
    assert detail["trace"]["status"] == "not_recorded"
    assert detail["trace"]["attempts"] == []


def test_partial_coverage_when_some_requests_have_trace(trace_admin, trace_db) -> None:
    """T-d：2 条已完成请求，1 条有普通执行 Trace → partial 1/2。"""
    covered = make_request(trace_db, finished_at=BASE, kind="answer")
    make_request(trace_db, finished_at=BASE + timedelta(minutes=1), kind="not_found")
    trace_db.commit()
    _trace(trace_admin.app.state.trace_repo, str(covered.request.id))

    overview = trace_admin.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert overview["trace_coverage"]["covered"] == 1
    assert overview["trace_coverage"]["total"] == 2
    assert overview["trace_coverage"]["status"] == "partial"


def test_replay_only_does_not_count_towards_coverage(trace_admin, trace_db) -> None:
    """纯重放 Trace 不计入覆盖率分子；attempt 显式 replayed。"""
    entry = make_request(trace_db, finished_at=BASE, kind="answer")
    trace_db.commit()
    _trace(trace_admin.app.state.trace_repo, str(entry.request.id), replayed=True, attempt=2)

    overview = trace_admin.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert overview["trace_coverage"]["covered"] == 0
    assert overview["trace_coverage"]["status"] == "not_recorded"

    detail = trace_admin.get(f"{OPS}/requests/{entry.request.id}").json()
    assert detail["trace"]["attempts"][0]["replayed"] is True
    assert detail["trace"]["status"] == "not_recorded"


def test_span_summary_whitelists_attributes(trace_admin, trace_db) -> None:
    """Span 只回名字/耗时/状态/属性键名与个数，不回 attributes_json 原文。"""
    import json

    entry = make_request(trace_db, finished_at=BASE, kind="answer")
    trace_db.commit()
    repo = trace_admin.app.state.trace_repo
    repo.write(
        TraceRecord(
            trace_id=uuid.uuid4().hex,
            request_id=str(entry.request.id),
            attempt=1,
            mode="local",
            scope="end_to_end",
            path="rag",
            outcome_kind="answer",
            status="ok",
            created_at=BASE.isoformat(),
        ),
        [
            SpanRecord(
                name="recall",
                duration_ms=5,
                status="ok",
                attributes_json=json.dumps({"secret_note": "LEAK-CANARY-ATTR", "count": 3}),
            )
        ],
    )

    detail = trace_admin.get(f"{OPS}/requests/{entry.request.id}")
    span = detail.json()["trace"]["attempts"][0]["spans"][0]
    assert span["name"] == "recall"
    assert span["duration_ms"] == 5
    assert span["attribute_count"] == 2
    assert span["attribute_keys"] == ["count", "secret_note"]
    assert "LEAK-CANARY-ATTR" not in detail.text
    assert "attributes_json" not in detail.text
