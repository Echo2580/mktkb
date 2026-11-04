"""T06 G06 来源鉴权：本人消息引用 active 200、他人/伪 ID 拒绝、替换与删除后 410。

文件经真实 HTTP 上传/worker/发布；不调用真实模型（可控网关只回显证据）。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import current_csrf, login, write_headers
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
V04 = FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx"


def _session(app):
    return app.state.db.session()


def _revision(app) -> int:
    db = _session(app)
    try:
        return get_revision(db)
    finally:
        db.close()


def _run_worker(app):
    db = _session(app)
    try:
        return run_one_job(db, app.state.store)
    finally:
        db.close()


def _publish_ready(ns, app, *, path=None, document_id=None, expected_active=None, revision=0, allow_same_name=None):
    receipt = ns.upload(
        path=path,
        document_id=document_id,
        expected_active_version_id=expected_active,
        allow_same_name=allow_same_name,
    )
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    assert _run_worker(app).state == "succeeded"
    published = ns.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=ns.headers,
        json={"expected_active_version_id": expected_active, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    return record, published.json()


def _b0(ns, app) -> dict:
    v03, first = _publish_ready(ns, app, path=V03, revision=0)
    positions = v03["document"]["id"]
    d01, second = _publish_ready(
        ns, app, path=D01, document_id=positions, expected_active=v03["version"]["id"], revision=first["revision"]
    )
    d02, third = _publish_ready(ns, app, path=D02, revision=second["revision"])
    return {
        "positions": {"document": positions, "v1": v03["version"]["id"], "v2": d01["version"]["id"]},
        "stores": {"document": d02["document"]["id"], "version": d02["version"]["id"]},
        "revision": third["revision"],
    }


def _create(ns) -> str:
    response = ns.client.post("/api/v1/conversations", json={}, headers=ns.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(ns, conversation_id, question):
    return ns.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=ns.headers,
    )


def _answered_source(ns, conversation_id, question="城东店的宣传海报在哪里？"):
    response = _ask(ns, conversation_id, question)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "answer", payload
    assert payload["sources"], payload
    source = payload["sources"][0]
    return payload["message_id"], source["source_id"]


def test_g06_owner_source_detail_and_file(chat_admin, chat_employee, chat_app):
    _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    message_id, source_id = _answered_source(chat_employee, conversation)

    detail = chat_employee.client.get(f"/api/v1/messages/{message_id}/sources/{source_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "active"
    assert body["version_number"] == 2
    assert body["locator"]["sheet"] and body["locator"]["row"] == 8
    assert body["fields"]["位置"] == "B区1号货架第二层"
    assert body["file_url"] == f"/api/v1/messages/{message_id}/sources/{source_id}/file"
    assert body["published_at"]

    file_response = chat_employee.client.get(body["file_url"])
    assert file_response.status_code == 200, file_response.text
    assert file_response.content == D01.read_bytes()
    assert file_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert file_response.headers["cache-control"] == "no-store"
    assert file_response.headers["x-content-type-options"] == "nosniff"
    assert "filename*=UTF-8''" in file_response.headers["content-disposition"]


def test_g06_cross_user_and_forged_ids_are_rejected(chat_admin, chat_employee, chat_employee2, chat_app):
    _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    message_id, source_id = _answered_source(chat_employee, conversation)

    url = f"/api/v1/messages/{message_id}/sources/{source_id}"
    assert chat_employee2.client.get(url).status_code == 403
    assert chat_employee2.client.get(f"{url}/file").status_code == 403

    assert chat_employee.client.get(f"/api/v1/messages/{uuid.uuid4()}/sources/{source_id}").status_code == 404
    assert chat_employee.client.get(f"/api/v1/messages/{message_id}/sources/{uuid.uuid4()}").status_code == 404

    # 他人的来源 UUID 不能被本会话消息“认领”（换成另一条资料的联系人来源，ID 必然不同）
    other_conversation = _create(chat_employee2)
    other_message, other_source = _answered_source(
        chat_employee2, other_conversation, question="城东店的联系人是谁？"
    )
    assert other_source != source_id
    assert chat_employee.client.get(
        f"/api/v1/messages/{message_id}/sources/{other_source}"
    ).status_code == 404
    assert chat_employee2.client.get(
        f"/api/v1/messages/{other_message}/sources/{other_source}"
    ).status_code == 200

    # 员工不能借管理员 documents 原件路由绕过
    admin_document = chat_app.state.db.session()
    try:
        from sqlalchemy import select

        from mktkb.documents.models import Document

        document = admin_document.scalar(select(Document).where(Document.deleted.is_(False)))
        document_id = document.id
        version_id = document.active_version_id
    finally:
        admin_document.close()
    assert chat_employee.client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/file"
    ).status_code == 403


def test_g06_replaced_and_deleted_sources_return_410_without_old_content(chat_admin, chat_employee, chat_app):
    b0 = _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    message_id, source_id = _answered_source(chat_employee, conversation)
    detail_url = f"/api/v1/messages/{message_id}/sources/{source_id}"

    # 1) 替换：发布 V04 后旧引用变 superseded
    record, published = _publish_ready(
        chat_admin,
        chat_app,
        path=V04,
        document_id=b0["positions"]["document"],
        expected_active=b0["positions"]["v2"],
        revision=b0["revision"],
    )
    assert published["revision"] == b0["revision"] + 1
    stale = chat_employee.client.get(detail_url)
    assert stale.status_code == 410, stale.text
    assert stale.json()["error"]["code"] == "SOURCE_UNAVAILABLE"
    details = stale.json()["error"]["details"]
    assert details["status"] == "superseded"
    assert details["version_number"] == 2
    assert details["document_name"]
    assert "B区1号货架第二层" not in stale.text
    assert chat_employee.client.get(f"{detail_url}/file").status_code == 410

    # 历史答案文本保留，来源摘要实时显示 superseded
    messages = chat_employee.client.get(f"/api/v1/conversations/{conversation}/messages").json()
    assistant = [item for item in messages["items"] if item["role"] == "assistant"][0]
    assert assistant["text"]
    assert assistant["sources"][0]["status"] == "superseded"

    # 2) 删除资料：旧引用变 deleted，410 且不带正文
    revision = _revision(chat_app)
    deleted = chat_admin.client.delete(
        f"/api/v1/documents/{b0['positions']['document']}?expected_revision={revision}",
        headers=chat_admin.headers,
    )
    assert deleted.status_code == 200, deleted.text
    removed = chat_employee.client.get(detail_url)
    assert removed.status_code == 410, removed.text
    assert removed.json()["error"]["details"]["status"] == "deleted"
    assert "text" not in removed.json()["error"]
    assert chat_employee.client.get(f"{detail_url}/file").status_code == 410

    # 3) 同字节重导入不恢复旧链接
    revision = _revision(chat_app)
    new_record, new_published = _publish_ready(
        chat_admin, chat_app, path=D01, revision=revision, allow_same_name=True
    )
    assert new_published["revision"] == revision + 1
    still_stale = chat_employee.client.get(detail_url)
    assert still_stale.status_code == 410, still_stale.text
    assert still_stale.json()["error"]["details"]["status"] == "deleted"
    assert chat_employee.client.get(f"{detail_url}/file").status_code == 410

    # 新资料产生的是新来源，旧消息不能自动指向新来源
    assert new_record["document"]["id"] != b0["positions"]["document"]
