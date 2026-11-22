"""T302 §5.1 C2/C3/C6 与 §5.2 S4：问答列表分页、重放、同文档多引用、失效引用。"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import select

from mktkb.observability.contracts import SpanRecord, TraceRecord
from operations.helpers import BASE, make_document, make_request

OPS = "/api/v1/operations"


def _walk_cursor(client, params: dict) -> tuple[list[dict], int]:
    items: list[dict] = []
    cursor = None
    pages = 0
    while True:
        query = dict(params)
        if cursor:
            query["cursor"] = cursor
        response = client.get(f"{OPS}/requests", params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        pages += 1
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            return items, pages
        assert pages < 20, "翻页未终止"


def test_pagination_has_no_duplicates_or_gaps(admin_client, db) -> None:
    """25 条 > page_size 7：翻完全部页，集合与总数一致且无重复。"""
    created = []
    for index in range(25):
        created.append(
            make_request(db, finished_at=BASE + timedelta(minutes=index), kind="answer")
        )
    db.commit()

    items, pages = _walk_cursor(admin_client, {"window": "7d", "page_size": 7})
    ids = [item["request_id"] for item in items]
    assert len(ids) == 25
    assert len(set(ids)) == 25
    assert set(ids) == {str(entry.request.id) for entry in created}
    assert pages == 4
    finished = [item["finished_at"] for item in items]
    assert finished == sorted(finished, reverse=True)
    assert items[0]["request_id"] == str(created[-1].request.id)


def test_kind_filter_matches_distribution(admin_client, db) -> None:
    make_request(db, finished_at=BASE, kind="answer")
    make_request(db, finished_at=BASE + timedelta(minutes=1), kind="answer")
    make_request(db, finished_at=BASE + timedelta(minutes=2), kind="not_found")
    db.commit()

    distribution = admin_client.get(f"{OPS}/overview", params={"window": "7d"}).json()["result_distribution"]
    for kind in ("answer", "not_found", "conflict"):
        listing = admin_client.get(
            f"{OPS}/requests", params={"window": "7d", "kind": kind}
        ).json()
        assert len(listing["items"]) == distribution[kind], kind
        assert all(item["kind"] == kind for item in listing["items"])


def test_same_document_multiple_rows_counts_once(admin_client, db) -> None:
    """同一回答引用同一资料多行：文档维/版本维去重后各计 1。"""
    doc = make_document(db, name="位置表", units=2)
    entry = make_request(
        db,
        finished_at=BASE,
        kind="answer",
        sources=(
            (str(doc.document.id), str(doc.versions[0].id), 0),
            (str(doc.document.id), str(doc.versions[0].id), 1),
        ),
    )
    db.commit()

    listing = admin_client.get(f"{OPS}/requests", params={"window": "7d"}).json()
    item = next(row for row in listing["items"] if row["request_id"] == str(entry.request.id))
    assert item["citation_count"] == 1

    detail = admin_client.get(f"{OPS}/requests/{entry.request.id}").json()
    assert detail["citation_count"] == 1
    assert len(detail["citations"]) == 1

    documents = admin_client.get(f"{OPS}/documents", params={"window": "7d"}).json()
    row = next(item for item in documents["items"] if item["document_id"] == str(doc.document.id))
    assert row["final_citations"] == 1
    assert row["related_requests_count"] == 1


def test_replay_keeps_counts_stable_and_marks_attempts(trace_admin, trace_db) -> None:
    """同一请求行的重放 Trace 不增加问答量，详情 attempt 带 replayed 标注。"""
    doc = make_document(trace_db, name="位置表")
    entry = make_request(trace_db, finished_at=BASE, kind="answer",
                         sources=((str(doc.document.id), str(doc.versions[0].id)),))
    trace_db.commit()

    repo = trace_admin.app.state.trace_repo
    repo.write(
        TraceRecord(
            trace_id=uuid.uuid4().hex,
            request_id=str(entry.request.id),
            http_request_id="http-1",
            attempt=1,
            replayed=False,
            mode="local",
            scope="end_to_end",
            path="rag",
            outcome_kind="answer",
            status="ok",
            created_at=BASE.isoformat(),
        ),
        [SpanRecord(name="parse", duration_ms=3, status="ok")],
    )
    repo.write(
        TraceRecord(
            trace_id=uuid.uuid4().hex,
            request_id=str(entry.request.id),
            http_request_id="http-2",
            attempt=2,
            replayed=True,
            mode="local",
            scope="end_to_end",
            status="replayed",
            created_at=BASE.isoformat(),
        ),
        [],
    )

    overview = trace_admin.get(f"{OPS}/overview", params={"window": "7d"}).json()
    assert overview["metrics"]["completed_requests"] == 1
    assert overview["result_distribution"]["answer"] == 1
    assert overview["trace_coverage"]["covered"] == 1
    assert overview["trace_coverage"]["total"] == 1
    assert overview["trace_coverage"]["status"] == "recorded"

    detail = trace_admin.get(f"{OPS}/requests/{entry.request.id}").json()
    assert detail["trace"]["status"] == "recorded"
    attempts = detail["trace"]["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert attempts[0]["replayed"] is False
    assert attempts[1]["replayed"] is True
    assert attempts[0]["spans"][0]["name"] == "parse"
    assert attempts[1]["spans"] == []
    assert "attributes_json" not in json.dumps(detail)


def test_document_filter_includes_conflict_and_flags_it(admin_client, db) -> None:
    """正常回答按持久引用匹配；冲突按 result_json.conflicts 匹配并标注 conflict_flag。"""
    doc = make_document(db, name="冲突资料A")
    other = make_document(db, name="其他资料")
    unit_id = str(next(iter(
        row.id
        for row in doc.units[doc.versions[0].id]
    )))
    conflict = make_request(
        db,
        finished_at=BASE + timedelta(minutes=1),
        kind="conflict",
        conflicts=(
            {"field": "位置", "entries": [{"value": "B区1号货架", "source_id": unit_id}]},
        ),
    )
    answer = make_request(
        db,
        finished_at=BASE,
        kind="answer",
        sources=((str(other.document.id), str(other.versions[0].id)),),
    )
    db.commit()

    filtered = admin_client.get(
        f"{OPS}/requests", params={"window": "7d", "document_id": str(doc.document.id)}
    ).json()["items"]
    assert [item["request_id"] for item in filtered] == [str(conflict.request.id)]
    assert filtered[0]["conflict_flag"] is True
    assert filtered[0]["citation_count"] == 0

    version_filtered = admin_client.get(
        f"{OPS}/requests",
        params={
            "window": "7d",
            "document_id": str(doc.document.id),
            "version_id": str(doc.versions[0].id),
        },
    ).json()["items"]
    assert len(version_filtered) == 1

    unrelated = admin_client.get(
        f"{OPS}/requests", params={"window": "7d", "document_id": str(other.document.id)}
    ).json()["items"]
    assert {item["request_id"] for item in unrelated} == {str(answer.request.id)}

    documents = admin_client.get(f"{OPS}/documents", params={"window": "7d"}).json()["items"]
    doc_row = next(item for item in documents if item["document_id"] == str(doc.document.id))
    assert doc_row["related_requests_count"] == 1
    assert doc_row["final_citations"] == 0


def test_superseded_and_deleted_citations_only_metadata(admin_client, db) -> None:
    """换版后的历史引用只给失效元信息：无 locator、无正文/字段/路径。"""
    doc = make_document(db, name="换版资料", states=("published", "published"))
    old_version, new_version = doc.versions[0], doc.versions[1]
    assert doc.document.active_version_id == new_version.id
    entry = make_request(
        db,
        finished_at=BASE,
        kind="answer",
        sources=((str(doc.document.id), str(old_version.id)),),
    )
    deleted_doc = make_document(db, name="删除资料", deleted=True, active=False)
    deleted_entry = make_request(
        db,
        finished_at=BASE + timedelta(minutes=1),
        kind="answer",
        sources=((str(deleted_doc.document.id), str(deleted_doc.versions[0].id)),),
    )
    db.commit()

    detail = admin_client.get(f"{OPS}/requests/{entry.request.id}").json()
    citation = detail["citations"][0]
    assert citation["status"] == "superseded"
    assert citation["locator"] is None
    assert "text" not in citation and "fields" not in citation
    assert citation["version_number"] == 1

    deleted_detail = admin_client.get(f"{OPS}/requests/{deleted_entry.request.id}").json()
    assert deleted_detail["citations"][0]["status"] == "deleted"
    assert deleted_detail["citations"][0]["locator"] is None
    body = json.dumps(deleted_detail)
    assert "storage/" not in body

    documents = admin_client.get(f"{OPS}/documents", params={"window": "7d"}).json()["items"]
    assert all(item["document_id"] != str(deleted_doc.document.id) for item in documents)


def test_list_does_not_return_question_or_conversation_id(admin_client, db) -> None:
    entry = make_request(db, finished_at=BASE, question="秘密问题不出口")
    db.commit()
    listing = admin_client.get(f"{OPS}/requests", params={"window": "7d"})
    body = listing.json()
    assert "秘密问题不出口" not in listing.text
    assert str(entry.conversation.id) not in listing.text
    assert body["items"][0]["conversation_id_hash"] != str(entry.conversation.id)
