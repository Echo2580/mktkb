"""T08-R1A 专属回归：冲突来源可核对、候选/冲突历史重放与旧数据兼容。

真实 FastAPI/SQLite/迁移/解析/检索；模型使用 conftest 的可控回显替身，
不包含真实模型/OCR 调用。测试放在新文件，不修改任何旧测试断言。
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from conftest import login
from mktkb.conversations.models import ConversationRequest, MessageSource
from mktkb.conversations import service
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
V06 = FIXTURES / "variants" / "V06_合作店家信息_新电话.xlsx"
NOTICE_NAME = "R1A_店家电话通知.xlsx"


def _session(app):
    return app.state.db.session()


def _run_worker(app):
    db = _session(app)
    try:
        return run_one_job(db, app.state.store)
    finally:
        db.close()


def _revision(app) -> int:
    db = _session(app)
    try:
        return get_revision(db)
    finally:
        db.close()


def _xlsx(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "店家信息"
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _publish_ready(ns, app, *, path=None, content=None, name=None, document_id=None, expected_active=None):
    kwargs = {}
    if path is not None:
        kwargs["path"] = path
    if content is not None:
        kwargs["content"] = content
        kwargs["name"] = name
    receipt = ns.upload(**kwargs, document_id=document_id, expected_active_version_id=expected_active)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    assert _run_worker(app).state == "succeeded"
    published = ns.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=ns.headers,
        json={"expected_active_version_id": expected_active, "expected_revision": _revision(app)},
    )
    assert published.status_code == 200, published.text
    return record


def _create(ns) -> str:
    response = ns.client.post("/api/v1/conversations", json={}, headers=ns.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(ns, conversation_id, question: str, request_id=None):
    return ns.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(request_id or uuid.uuid4()), "question": question},
        headers=ns.headers,
    )


def _messages(ns, conversation_id: str) -> dict:
    response = ns.client.get(f"/api/v1/conversations/{conversation_id}/messages?limit=100")
    assert response.status_code == 200, response.text
    return response.json()


def _assistant(messages: dict) -> dict:
    rows = [item for item in messages["items"] if item["role"] == "assistant"]
    assert len(rows) == 1, messages
    return rows[0]


def _publish_conflict(chat_admin, app):
    base = _publish_ready(chat_admin, app, path=D02)
    notice = _publish_ready(
        chat_admin,
        app,
        content=_xlsx(
            ("标识", "店家", "联系人", "电话"),
            [("S01", "城东店", "模拟联系人·陈宁", "010-00000099")],
        ),
        name=NOTICE_NAME,
    )
    return base, notice


def test_conflict_entries_expose_real_sources_permissions_and_history(
    chat_admin, chat_employee, chat_employee2, chat_app
):
    base, notice = _publish_conflict(chat_admin, chat_app)
    conversation = _create(chat_employee)
    question = "城东店的联系电话是什么？"
    request_id = uuid.uuid4()

    response = _ask(chat_employee, conversation, question, request_id)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "conflict", payload
    entries = payload["conflicts"][0]["entries"]
    assert {entry["value"] for entry in entries} == {"010-00000001", "010-00000099"}
    assert len({entry["source_id"] for entry in entries}) == 2

    expected_names = {
        "010-00000001": base["document"]["name"],
        "010-00000099": NOTICE_NAME,
    }
    summaries = payload["sources"]
    assert len(summaries) == 2, payload
    by_id = {summary["source_id"]: summary for summary in summaries}
    assert set(by_id) == {entry["source_id"] for entry in entries}
    for entry in entries:
        summary = by_id[entry["source_id"]]
        assert summary["document_name"] == expected_names[entry["value"]]
        assert summary["status"] == "active"
        assert summary["version_number"] == 1
        assert summary["locator"].get("sheet") == "店家信息"
        assert int(summary["locator"].get("row", 0)) >= 1

    message_id = payload["message_id"]
    source_urls = {}
    for entry in entries:
        url = f"/api/v1/messages/{message_id}/sources/{entry['source_id']}"
        source_urls[entry["value"]] = url
        detail = chat_employee.client.get(url)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["document_name"] == expected_names[entry["value"]]
        assert body["version_number"] == 1
        assert body["locator"].get("sheet") == "店家信息"
        assert body["fields"]["电话"] == entry["value"]
        assert body["file_url"].endswith("/file")

    anonymous = TestClient(chat_app, raise_server_exceptions=False)
    assert anonymous.get(source_urls["010-00000001"]).status_code == 401
    assert chat_employee2.client.get(source_urls["010-00000001"]).status_code == 403

    messages = _messages(chat_employee, conversation)
    assistant = _assistant(messages)
    assert assistant["kind"] == "conflict"
    assert {entry["value"] for entry in assistant["conflicts"][0]["entries"]} == {
        "010-00000001",
        "010-00000099",
    }
    assert len(assistant["sources"]) == 2
    assert all(item["status"] == "active" for item in assistant["sources"])
    assert assistant["candidates"] == []

    replay = _ask(chat_employee, conversation, question, request_id)
    assert replay.status_code == 200, replay.text
    assert replay.json()["message_id"] == message_id
    assert {entry["value"] for entry in replay.json()["conflicts"][0]["entries"]} == {
        "010-00000001",
        "010-00000099",
    }
    assert len(_messages(chat_employee, conversation)["items"]) == len(messages["items"])

    fresh = TestClient(chat_app, raise_server_exceptions=False)
    login(fresh, "employee", "EmployeePass-1")
    relogin = fresh.get(f"/api/v1/conversations/{conversation}/messages?limit=100")
    assert relogin.status_code == 200, relogin.text
    relogin_assistant = _assistant(relogin.json())
    assert {entry["value"] for entry in relogin_assistant["conflicts"][0]["entries"]} == {
        "010-00000001",
        "010-00000099",
    }
    assert len(relogin_assistant["sources"]) == 2

    deleted = chat_admin.client.delete(
        f"/api/v1/documents/{notice['document']['id']}?expected_revision={_revision(chat_app)}",
        headers=chat_admin.headers,
    )
    assert deleted.status_code == 200, deleted.text

    after_delete = _assistant(_messages(chat_employee, conversation))
    assert {entry["value"] for entry in after_delete["conflicts"][0]["entries"]} == {
        "010-00000001",
        "010-00000099",
    }
    deleted_summary = next(item for item in after_delete["sources"] if item["document_name"] == NOTICE_NAME)
    assert deleted_summary["status"] == "deleted"
    active_summary = next(item for item in after_delete["sources"] if item["document_name"] == base["document"]["name"])
    assert active_summary["status"] == "active"

    gone = chat_employee.client.get(source_urls["010-00000099"])
    assert gone.status_code == 410, gone.text
    detail = gone.json()["error"]["details"]
    assert detail["status"] == "deleted"
    assert detail["document_name"] == NOTICE_NAME
    assert "text" not in detail and "fields" not in detail
    file_gone = chat_employee.client.get(source_urls["010-00000099"] + "/file")
    assert file_gone.status_code == 410
    file_error = file_gone.json()["error"]
    assert file_error["code"] == "SOURCE_UNAVAILABLE"
    assert set(file_error["details"]) == {"status", "document_name", "version_number"}
    assert chat_employee.client.get(source_urls["010-00000001"]).status_code == 200

    replay_after_delete = _ask(chat_employee, conversation, question, request_id)
    assert replay_after_delete.status_code == 200
    assert replay_after_delete.json()["message_id"] == message_id
    assert len(_messages(chat_employee, conversation)["items"]) == len(messages["items"])


def test_conflict_history_survives_replacement_of_one_source(chat_admin, chat_employee, chat_app):
    base, _notice = _publish_conflict(chat_admin, chat_app)
    conversation = _create(chat_employee)
    response = _ask(chat_employee, conversation, "城东店的联系电话是什么？")
    assert response.status_code == 200 and response.json()["kind"] == "conflict", response.text
    entries = response.json()["conflicts"][0]["entries"]
    old_phone_entry = next(entry for entry in entries if entry["value"] == "010-00000001")

    _publish_ready(
        chat_admin,
        chat_app,
        path=V06,
        document_id=base["document"]["id"],
        expected_active=base["version"]["id"],
    )

    assistant = _assistant(_messages(chat_employee, conversation))
    assert {entry["value"] for entry in assistant["conflicts"][0]["entries"]} == {
        "010-00000001",
        "010-00000099",
    }
    old_summary = next(item for item in assistant["sources"] if item["source_id"] == old_phone_entry["source_id"])
    assert old_summary["status"] == "superseded"
    url = f"/api/v1/messages/{response.json()['message_id']}/sources/{old_phone_entry['source_id']}"
    gone = chat_employee.client.get(url)
    assert gone.status_code == 410, gone.text
    detail = gone.json()["error"]["details"]
    assert detail["status"] == "superseded"
    assert "text" not in detail and "fields" not in detail


def test_clarification_candidates_replay_after_refresh(chat_admin, chat_employee, chat_app):
    _publish_ready(chat_admin, chat_app, path=D01)
    conversation = _create(chat_employee)
    response = _ask(chat_employee, conversation, "宣传海报在哪里？")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "clarification", payload
    labels = [item["label"] for item in payload["candidates"]]
    assert {"城东店", "城西店"} <= set(labels), payload

    assistant = _assistant(_messages(chat_employee, conversation))
    assert assistant["kind"] == "clarification"
    assert [item["label"] for item in assistant["candidates"]] == labels
    assert assistant["conflicts"] == []
    assert assistant["sources"] == []

    fresh = TestClient(chat_app, raise_server_exceptions=False)
    login(fresh, "employee", "EmployeePass-1")
    relogin = fresh.get(f"/api/v1/conversations/{conversation}/messages?limit=100")
    assert relogin.status_code == 200
    assert [item["label"] for item in _assistant(relogin.json())["candidates"]] == labels


def test_legacy_conflict_without_message_source_rows_is_recovered_from_result_json(
    chat_admin, chat_employee, chat_app
):
    _publish_conflict(chat_admin, chat_app)
    conversation = _create(chat_employee)
    request_id = uuid.uuid4()
    response = _ask(chat_employee, conversation, "城东店的联系电话是什么？", request_id)
    assert response.status_code == 200 and response.json()["kind"] == "conflict", response.text
    message_id = response.json()["message_id"]

    db = _session(chat_app)
    try:
        request_row = db.query(ConversationRequest).filter(
            ConversationRequest.result_message_id == uuid.UUID(message_id)
        ).one()
        stored = dict(request_row.result_json or {})
        # 模拟修复前的真实历史：result_json 只有 conflicts/source_id，没有来源摘要，
        # 消息也没有 MessageSource 行。
        stored["sources"] = []
        request_row.result_json = stored
        db.execute(delete(MessageSource).where(MessageSource.message_id == uuid.UUID(message_id)))
        db.commit()
    finally:
        db.close()
    assert stored.get("kind") == "conflict" and stored.get("conflicts"), stored

    assistant = _assistant(_messages(chat_employee, conversation))
    assert assistant["kind"] == "conflict"
    assert {entry["value"] for entry in assistant["conflicts"][0]["entries"]} == {
        "010-00000001",
        "010-00000099",
    }
    assert len(assistant["sources"]) == 2
    source_id = assistant["conflicts"][0]["entries"][0]["source_id"]
    url = f"/api/v1/messages/{message_id}/sources/{source_id}"
    detail = chat_employee.client.get(url)
    assert detail.status_code == 200, detail.text
    assert detail.json()["document_name"] in {item["document_name"] for item in assistant["sources"]}
    assert anonymous_status(chat_app, url) == 401

    replay = _ask(chat_employee, conversation, "城东店的联系电话是什么？", request_id)
    assert replay.status_code == 200, replay.text
    assert replay.json()["message_id"] == message_id
    assert {entry["value"] for entry in replay.json()["conflicts"][0]["entries"]} == {
        "010-00000001",
        "010-00000099",
    }
    assert len(replay.json()["sources"]) == 2


def anonymous_status(app, url: str) -> int:
    client = TestClient(app, raise_server_exceptions=False)
    return client.get(url).status_code


def test_conflict_revision_change_during_ask_returns_knowledge_changed(
    chat_admin, chat_employee, chat_app, monkeypatch
):
    _publish_conflict(chat_admin, chat_app)
    conversation = _create(chat_employee)
    original = service._retrieve

    def retrieve_with_revision_bump(db_factory, intent, revision, limit=20, **kwargs):
        evidence = original(db_factory, intent, revision, limit=limit, **kwargs)
        db = _session(chat_app)
        try:
            db.execute(text("UPDATE knowledge_state SET revision = revision + 1 WHERE id = 1"))
            db.commit()
        finally:
            db.close()
        return evidence

    monkeypatch.setattr(service, "_retrieve", retrieve_with_revision_bump)
    response = _ask(chat_employee, conversation, "城东店的联系电话是什么？")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "knowledge_changed", payload
    assert payload["conflicts"] == []
    assistant = _assistant(_messages(chat_employee, conversation))
    assert assistant["kind"] == "knowledge_changed"
    assert assistant["conflicts"] == [] and assistant["sources"] == []
