"""T302 §3.4/§3.5：资料列表与详情、过滤、失败原因、租约字段不外泄。"""

from __future__ import annotations

import json
from datetime import timedelta

from operations.helpers import BASE, make_document, make_import, make_request

OPS = "/api/v1/operations"


def test_document_filters_and_deleted_exclusion(admin_client, db) -> None:
    xlsx = make_document(db, name="位置表", file_type="xlsx")
    docx = make_document(db, name="工作指南", file_type="docx")
    review = make_document(db, name="待审核表", states=("review_required",), active=False)
    deleted = make_document(db, name="已删除资料", deleted=True, active=False)
    failed = make_document(db, name="失败导入表", states=("failed",), active=False)
    make_import(db, failed.versions[0], state="failed", stage="parse")
    db.commit()

    all_items = admin_client.get(f"{OPS}/documents").json()["items"]
    ids = {item["document_id"] for item in all_items}
    assert str(deleted.document.id) not in ids
    assert str(xlsx.document.id) in ids

    by_type = admin_client.get(f"{OPS}/documents", params={"file_type": "docx"}).json()["items"]
    assert [item["document_id"] for item in by_type] == [str(docx.document.id)]

    by_state = admin_client.get(
        f"{OPS}/documents", params={"version_state": "review_required"}
    ).json()["items"]
    assert [item["document_id"] for item in by_state] == [str(review.document.id)]

    by_job = admin_client.get(
        f"{OPS}/documents", params={"processing_state": "failed"}
    ).json()["items"]
    assert [item["document_id"] for item in by_job] == [str(failed.document.id)]


def test_document_list_cursor_pagination(admin_client, db) -> None:
    created = [make_document(db, name=f"资料{i}", file_type="xlsx") for i in range(5)]
    db.commit()
    items = []
    cursor = None
    pages = 0
    while True:
        params = {"page_size": 2}
        if cursor:
            params["cursor"] = cursor
        body = admin_client.get(f"{OPS}/documents", params=params).json()
        pages += 1
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            break
        assert pages < 10
    ids = [item["document_id"] for item in items]
    assert len(ids) == len(set(ids))
    assert set(ids) == {str(item.document.id) for item in created}
    assert ids == sorted(ids)


def test_document_detail_versions_and_retry_summary(admin_client, db) -> None:
    doc = make_document(db, name="换版资料", states=("published", "published"))
    job = make_import(db, doc.versions[1], state="failed", attempts=3, retryable=True,
                      message="解析未完成：缺少缓存值")
    db.commit()

    response = admin_client.get(f"{OPS}/documents/{doc.document.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document"]["name"] == "换版资料"
    assert "stored_path" not in body["document"]
    assert [item["number"] for item in body["versions"]] == [1, 2]
    detail = body["versions"][1]
    assert detail["error_code"] == "PARSE_INCOMPLETE"
    assert detail["message"] == "解析未完成：缺少缓存值"

    import_row = body["imports"][0]
    assert import_row["attempts"] == 3
    assert import_row["retryable"] is True
    assert not any(key.startswith("lease_") for key in import_row)
    assert "LEAK-CANARY" not in response.text

    assert body["drilldown"]["requests_filter"] == {
        "document_id": str(doc.document.id),
        "version_id": str(doc.versions[1].id),
    }


def test_failure_message_with_internal_path_is_reduced_to_code(admin_client, db) -> None:
    doc = make_document(db, name="路径泄漏资料", states=("failed",), active=False)
    job = make_import(
        db,
        doc.versions[0],
        message="解析失败：C:\\secret\\storage\\x.xlsx Traceback sqlite:///var/mktkb.sqlite3",
    )
    db.commit()

    body = admin_client.get(f"{OPS}/documents/{doc.document.id}").json()
    version = body["versions"][0]
    assert version["error_code"] == "PARSE_INCOMPLETE"
    assert version["message"] is None
    assert body["imports"][0]["message"] is None
    text = json.dumps(body)
    assert "C:\\\\secret" not in text and "storage" not in text and "sqlite" not in text


def test_deleted_document_detail_is_404(admin_client, db) -> None:
    doc = make_document(db, name="已删除资料", deleted=True, active=False)
    db.commit()
    response = admin_client.get(f"{OPS}/documents/{doc.document.id}")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_conflict_request_counts_related_but_not_final(admin_client, db) -> None:
    doc = make_document(db, name="冲突资料", units=1)
    unit_id = str(doc.units[doc.versions[0].id][0].id)
    conflict = make_request(
        db,
        finished_at=BASE,
        kind="conflict",
        conflicts=({"field": "位置", "entries": [{"value": "B区", "source_id": unit_id}]},),
    )
    normal = make_request(
        db,
        finished_at=BASE + timedelta(minutes=1),
        kind="answer",
        sources=((str(doc.document.id), str(doc.versions[0].id)),),
    )
    db.commit()

    row = next(
        item
        for item in admin_client.get(f"{OPS}/documents", params={"window": "7d"}).json()["items"]
        if item["document_id"] == str(doc.document.id)
    )
    assert row["final_citations"] == 1
    assert row["related_requests_count"] == 2

    detail = admin_client.get(f"{OPS}/requests/{conflict.request.id}").json()
    assert detail["citation_count"] == 0
    assert detail["conflicts"][0]["field"] == "位置"
    assert detail["conflicts"][0]["conflict_flag"] is True
    assert detail["conflicts"][0]["entries"][0]["document_id"] == str(doc.document.id)
    assert detail["conflicts"][0]["entries"][0]["status"] == "active"
    assert normal.request.id is not None
