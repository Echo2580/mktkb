"""T302 §3.1：总览指标、六类分布、中断单列、待处理项与统计=下钻。"""

from __future__ import annotations

from datetime import timedelta

from operations.helpers import BASE, make_document, make_import, make_request

OPS = "/api/v1/operations"


def test_interrupted_is_listed_separately_not_in_distribution(admin_client, db) -> None:
    answered = make_request(db, finished_at=BASE, kind="answer")
    running = make_request(db, finished_at=BASE + timedelta(minutes=1), status="running", kind=None)
    expired = make_request(
        db, finished_at=BASE + timedelta(minutes=2), status="expired", kind=None
    )
    db.commit()

    body = admin_client.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert body["metrics"]["completed_requests"] == 1
    assert body["metrics"]["interrupted"] == 2
    assert sum(body["result_distribution"].values()) == 1
    # 中断请求不出现在六类分布下钻里
    for kind in ("answer", "not_found", "conflict"):
        assert str(running.request.id) not in {
            item["request_id"]
            for item in admin_client.get(
                f"{OPS}/requests", params={"window": "7d", "kind": kind}
            ).json()["items"]
        }
    assert answered.request.id is not None and expired.request.id is not None


def test_pending_items_carry_drilldown_conditions(admin_client, db) -> None:
    make_request(db, finished_at=BASE, kind="service_error", error_code="MODEL_UNAVAILABLE")
    make_request(db, finished_at=BASE + timedelta(minutes=1), kind="not_found")
    make_request(db, finished_at=BASE + timedelta(minutes=2), kind="conflict")
    make_request(db, finished_at=BASE + timedelta(minutes=3), kind="answer")
    broken = make_document(db, name="失败导入", states=("failed",), active=False)
    make_import(db, broken.versions[0])
    db.commit()

    body = admin_client.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert body["metrics"]["not_found"] == 1
    assert body["metrics"]["conflict"] == 1

    request_items = [item for item in body["pending"] if item["type"] == "request"]
    assert {item["kind"] for item in request_items} == {"service_error", "not_found", "conflict"}
    for item in request_items:
        assert item["drilldown"]["kind"] == item["kind"]
        assert item["drilldown"]["date"] == "2026-11-21"
        assert item["request_id"]

    import_items = [item for item in body["pending"] if item["type"] == "import"]
    assert len(import_items) == 1
    assert import_items[0]["document_id"] == str(broken.document.id)
    assert import_items[0]["version_id"] == str(broken.versions[0].id)
    assert import_items[0]["state"] == "failed"
    assert import_items[0]["error_code"] == "PARSE_INCOMPLETE"
    assert import_items[0]["drilldown"] == {
        "document_id": str(broken.document.id),
        "version_id": str(broken.versions[0].id),
        "state": "failed",
    }


def test_overview_counts_equal_drilldown_totals(admin_client, db) -> None:
    doc = make_document(db, name="位置表", units=2)
    make_request(db, finished_at=BASE, kind="answer",
                 sources=((str(doc.document.id), str(doc.versions[0].id), 0),
                          (str(doc.document.id), str(doc.versions[0].id), 1)))
    make_request(db, finished_at=BASE + timedelta(minutes=1), kind="clarification")
    make_request(db, finished_at=BASE + timedelta(minutes=2), kind="not_found")
    db.commit()

    overview = admin_client.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert overview["metrics"]["completed_requests"] == 3
    assert overview["trend"] == [{"date": "2026-11-21", "completed": 3, "citations": 1}]

    listed = admin_client.get(f"{OPS}/requests", params={"window": "7d"}).json()["items"]
    assert len(listed) == overview["metrics"]["completed_requests"]
    assert sum(item["citation_count"] for item in listed) == 1

    documents = admin_client.get(f"{OPS}/documents", params={"window": "7d"}).json()["items"]
    assert sum(item["final_citations"] for item in documents) == 1

    for kind in ("answer", "clarification", "not_found"):
        count = len(
            admin_client.get(
                f"{OPS}/requests", params={"window": "7d", "kind": kind}
            ).json()["items"]
        )
        assert count == overview["result_distribution"][kind]


def test_trend_days_cover_only_actual_data(admin_client, db) -> None:
    make_request(db, finished_at=BASE, kind="answer")
    make_request(db, finished_at=BASE + timedelta(days=1), kind="answer")
    db.commit()
    body = admin_client.get(
        f"{OPS}/overview", params={"since": "2026-11-21", "until": "2026-11-23"}
    ).json()
    assert [point["date"] for point in body["trend"]] == ["2026-11-21", "2026-11-22"]
    assert [point["completed"] for point in body["trend"]] == [1, 1]
