"""T06 G05 回答提交与并发关口：独立 Session + 真实事件屏障。

覆盖：模型等待期间发布/删除、模型返回后提交前变更、无关资料 revision 变更、会话删除、
旧 attempt 迟到、提交完成后再变更。全部用真实 HTTP 上传/worker/发布与真实数据库事务；
模型为可控替身（只回显证据），不调用真实服务。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
import uuid
from itertools import chain, repeat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from conftest import current_csrf, login, write_headers
from mktkb.auth.service import UserContext
from mktkb.auth.models import User
from mktkb.conversations import service
from mktkb.conversations.models import Conversation, ConversationMessage, ConversationRequest, MessageSource
from mktkb.conversations.schemas import AskRequest
from mktkb.documents.lifecycle import get_revision
from mktkb.documents.models import Document, SourceUnit
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
D03 = FIXTURES / "normal" / "D03_市场部工作指南.docx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
V04 = FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx"


def _dump(name: str, data: dict) -> None:
    target = os.environ.get("T06_ACTUAL_DIR")
    if not target:
        return
    path = Path(target)
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


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


def _publish_ready(ns, app, *, path=None, document_id=None, expected_active=None, revision=0):
    receipt = ns.upload(path=path, document_id=document_id, expected_active_version_id=expected_active)
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


def _user_context(app, username: str) -> UserContext:
    db = _session(app)
    try:
        user = db.scalar(select(User).where(User.username == username))
        return UserContext(
            id=user.id, username=user.username, display_name=user.display_name, role=user.role, session_id=uuid.uuid4()
        )
    finally:
        db.close()


def _ask_sync(app, user, conversation_id: str, question: str, request_id=None):
    payload = AskRequest(client_request_id=request_id or uuid.uuid4(), question=question)
    return asyncio.run(
        service.ask(app.state.db.session, user, uuid.UUID(conversation_id), payload, model=app.state.model_gateway)
    )


def _ask_thread(app, user, conversation_id: str, question: str, request_id=None):
    holder: dict = {}

    def run():
        try:
            holder["result"] = _ask_sync(app, user, conversation_id, question, request_id)
        except BaseException as exc:  # noqa: BLE001 - 记录异常供断言
            holder["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    return thread, holder


def _message_rows(app, conversation_id: str):
    db = _session(app)
    try:
        rows = db.execute(
            select(ConversationMessage.seq, ConversationMessage.role, ConversationMessage.kind, ConversationMessage.text)
            .where(ConversationMessage.conversation_id == uuid.UUID(conversation_id))
            .order_by(ConversationMessage.seq)
        ).all()
        sources = db.scalar(
            select(func.count())
            .select_from(MessageSource)
            .join(ConversationMessage, ConversationMessage.id == MessageSource.message_id)
            .where(ConversationMessage.conversation_id == uuid.UUID(conversation_id))
        )
        requests = db.execute(
            select(ConversationRequest.attempt, ConversationRequest.status, ConversationRequest.error_code)
            .where(ConversationRequest.conversation_id == uuid.UUID(conversation_id))
        ).all()
        return {
            "messages": [list(row) for row in rows],
            "source_links": int(sources or 0),
            "requests": [list(row) for row in requests],
        }
    finally:
        db.close()


def test_g05_publish_during_model_wait_returns_knowledge_changed(chat_admin, chat_employee, chat_app):
    b0 = _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.entered = threading.Event()
    gateway.block_after_entry = threading.Event()
    user = _user_context(chat_app, "employee")

    thread, holder = _ask_thread(chat_app, user, conversation, "城东店的宣传海报在哪里？")
    assert gateway.entered.wait(10), "模型调用未进入屏障"

    version_id = _upload_v04(chat_admin, chat_app, b0)
    published = chat_admin.client.post(
        f"/api/v1/documents/{b0['positions']['document']}/versions/{version_id}/publish",
        headers=chat_admin.headers,
        json={"expected_active_version_id": b0["positions"]["v2"], "expected_revision": b0["revision"]},
    )
    assert published.status_code == 200, published.text

    gateway.block_after_entry.set()
    thread.join(30)
    assert not thread.is_alive()
    assert "error" not in holder, holder.get("error")
    result = holder["result"]
    assert result.kind == "knowledge_changed", result
    assert result.sources == []
    assert "B区1号货架第二层" not in result.text
    rows = _message_rows(chat_app, conversation)
    assert rows["source_links"] == 0
    assert [item[1] for item in rows["messages"]] == ["user", "assistant"]
    assert rows["messages"][1][2] == "knowledge_changed"
    assert rows["requests"] == [[1, "succeeded", None]]
    _dump(
        "commit-race-publish-during-wait.json",
        {"result": result.model_dump(mode="json"), "rows": rows, "revision_after": _revision(chat_app)},
    )


def _upload_v04(ns, app, b0) -> str:
    receipt = ns.upload(
        path=V04, document_id=b0["positions"]["document"], expected_active_version_id=b0["positions"]["v2"]
    )
    assert receipt.status_code == 202, receipt.text
    assert _run_worker(app).state == "succeeded"
    return receipt.json()["version"]["id"]


def test_g05_change_after_model_returns_before_commit(chat_admin, chat_employee, chat_app, monkeypatch):
    b0 = _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.entered = None
    gateway.block_after_entry = None
    commit_entered = threading.Event()
    commit_release = threading.Event()
    original = service._commit_result

    def slow_commit(*args, **kwargs):
        commit_entered.set()
        assert commit_release.wait(15), "提交屏障超时"
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_commit_result", slow_commit)
    user = _user_context(chat_app, "employee")
    thread, holder = _ask_thread(chat_app, user, conversation, "城东店的宣传海报在哪里？")
    assert commit_entered.wait(10), "未进入提交前屏障"

    revision = _revision(chat_app)
    deleted = chat_admin.client.delete(
        f"/api/v1/documents/{b0['stores']['document']}?expected_revision={revision}", headers=chat_admin.headers
    )
    assert deleted.status_code == 200, deleted.text

    commit_release.set()
    thread.join(30)
    assert "error" not in holder, holder.get("error")
    result = holder["result"]
    assert result.kind == "knowledge_changed", result
    assert result.sources == []
    rows = _message_rows(chat_app, conversation)
    assert rows["source_links"] == 0
    assert rows["messages"][1][2] == "knowledge_changed"
    _dump(
        "commit-race-after-model-before-commit.json",
        {"result": result.model_dump(mode="json"), "rows": rows},
    )


def test_g05_unrelated_revision_change_also_aborts(chat_admin, chat_employee, chat_app):
    _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.entered = threading.Event()
    gateway.block_after_entry = threading.Event()
    user = _user_context(chat_app, "employee")

    thread, holder = _ask_thread(chat_app, user, conversation, "城东店的宣传海报在哪里？")
    assert gateway.entered.wait(10)

    revision = _revision(chat_app)
    _publish_ready(chat_admin, chat_app, path=D03, revision=revision)

    gateway.block_after_entry.set()
    thread.join(30)
    result = holder["result"]
    assert result.kind == "knowledge_changed", result
    assert result.sources == []
    _dump("commit-race-unrelated-change.json", {"result": result.model_dump(mode="json")})


def test_g05_conversation_deleted_during_model_wait_discards_result(chat_admin, chat_employee, chat_app):
    _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.entered = threading.Event()
    gateway.block_after_entry = threading.Event()
    user = _user_context(chat_app, "employee")

    thread, holder = _ask_thread(chat_app, user, conversation, "城东店的宣传海报在哪里？")
    assert gateway.entered.wait(10)

    deleted = chat_employee.client.delete(f"/api/v1/conversations/{conversation}", headers=chat_employee.headers)
    assert deleted.status_code == 204, deleted.text

    gateway.block_after_entry.set()
    thread.join(30)
    assert "result" not in holder
    error = holder.get("error")
    assert error is not None and getattr(error, "code", None) == "REQUEST_CANCELLED", error

    rows = _message_rows(chat_app, conversation)
    assert rows["messages"] == [[1, "user", None, "城东店的宣传海报在哪里？"]]
    assert rows["source_links"] == 0
    assert rows["requests"] == [[1, "cancelled", "REQUEST_CANCELLED"]]
    assert chat_employee.client.get(f"/api/v1/conversations/{conversation}/messages").status_code == 404
    _dump("commit-race-conversation-deleted.json", {"rows": rows, "error": str(error)})


def test_g05_late_attempt_is_fenced_after_retry(chat_admin, chat_employee, chat_app):
    _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.entered = threading.Event()
    first_block = threading.Event()
    gateway.block_after_entry = first_block
    user = _user_context(chat_app, "employee")
    request_id = uuid.uuid4()

    thread, holder = _ask_thread(chat_app, user, conversation, "城东店的宣传海报在哪里？", request_id)
    assert gateway.entered.wait(10)

    # 模拟进程崩溃：把持久 running 标记为过期（deadline 已过），不改消息
    db = _session(chat_app)
    try:
        row = db.scalar(
            select(ConversationRequest).where(ConversationRequest.conversation_id == uuid.UUID(conversation))
        )
        row.status = "expired"
        row.deadline_at = row.deadline_at.replace(year=2000)
        db.commit()
    finally:
        db.close()

    # 显式同载荷重试：新 attempt 完成，允许一次新的模型调用
    gateway.block_after_entry = None
    retry = _ask_sync(chat_app, user, conversation, "城东店的宣传海报在哪里？", request_id)
    assert retry.kind == "answer", retry
    assert len(gateway.calls) == 2

    first_block.set()
    thread.join(30)
    assert "result" not in holder
    error = holder.get("error")
    assert error is not None and getattr(error, "code", None) == "REQUEST_CANCELLED", error

    rows = _message_rows(chat_app, conversation)
    assert [item[1] for item in rows["messages"]] == ["user", "assistant"]
    assert rows["messages"][1][2] == "answer"
    assert rows["requests"] == [[2, "succeeded", None]]
    assert rows["source_links"] == 1
    assert len(chat_app.state.model_gateway.calls) == 2
    _dump("commit-race-late-attempt.json", {"rows": rows, "error": str(error), "calls": 2})


def test_g05_change_after_commit_keeps_history_and_new_question_uses_new_facts(chat_admin, chat_employee, chat_app):
    b0 = _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.entered = None
    gateway.block_after_entry = None

    first = _ask_sync(chat_app, _user_context(chat_app, "employee"), conversation, "城东店的宣传海报在哪里？")
    assert first.kind == "answer" and "B区1号货架第二层" in first.text

    _upload_v04(chat_admin, chat_app, b0)
    published = chat_admin.client.post(
        f"/api/v1/documents/{b0['positions']['document']}/versions/"
        f"{_latest_version(chat_app, b0['positions']['document'])}/publish",
        headers=chat_admin.headers,
        json={"expected_active_version_id": b0["positions"]["v2"], "expected_revision": b0["revision"]},
    )
    assert published.status_code == 200, published.text

    history = chat_employee.client.get(f"/api/v1/conversations/{conversation}/messages").json()
    assistant = [item for item in history["items"] if item["role"] == "assistant"][0]
    assert "B区1号货架第二层" in assistant["text"]
    assert assistant["sources"][0]["status"] == "superseded"

    second = _ask_sync(chat_app, _user_context(chat_app, "employee"), conversation, "城东店的宣传海报在哪里？")
    assert second.kind == "answer", second
    assert "D区暂存柜" in second.text
    assert second.sources[0].version_number == 3
    _dump(
        "commit-race-after-commit.json",
        {
            "first": first.model_dump(mode="json"),
            "history_text": assistant["text"],
            "history_sources": assistant["sources"],
            "second": second.model_dump(mode="json"),
        },
    )


def _latest_version(app, document_id) -> str:
    db = _session(app)
    try:
        from mktkb.documents.models import DocumentVersion

        version = db.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == uuid.UUID(document_id))
            .order_by(DocumentVersion.number.desc())
        )
        return str(version.id)
    finally:
        db.close()


# ---------------------------------------------------------------- R1：总预算与最终提交边界


def _dump_r1(name: str, data: dict) -> None:
    """仅在显式设置 T06_R1_ACTUAL_DIR 时写本轮证据；默认不写业务目录。"""
    target = os.environ.get("T06_R1_ACTUAL_DIR")
    if not target:
        return
    path = Path(target)
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def _db_file(app) -> Path:
    return Path(app.state.settings.data_dir) / "mktkb.sqlite3"


def test_g05_exhausted_budget_commit_lock_contention_exits_bounded(
    chat_admin, chat_employee, chat_app, monkeypatch
):
    """PM06-02：预算用尽后提交遇锁竞争必须及时失败，不重发模型、不落伪结果。"""
    _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.entered = threading.Event()
    gateway.block_after_entry = threading.Event()
    user = _user_context(chat_app, "employee")

    ticks = chain([1000.0, 1000.0, 1000.0], repeat(1061.0))
    monkeypatch.setattr(service, "monotonic", lambda: next(ticks))

    thread, holder = _ask_thread(chat_app, user, conversation, "城东店的宣传海报在哪里？")
    assert gateway.entered.wait(10), "模型调用未进入屏障"

    connection = sqlite3.connect(str(_db_file(chat_app)), timeout=0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        gateway.block_after_entry.set()
        started = time.monotonic()
        thread.join(30)
        elapsed = time.monotonic() - started
    finally:
        connection.rollback()
        connection.close()

    assert not thread.is_alive()
    assert "result" not in holder
    error = holder.get("error")
    assert getattr(error, "code", None) == "SERVER_OVERLOADED", error
    assert elapsed < 1.0, f"预算用尽后仍在等锁 {elapsed:.3f}s"
    rows = _message_rows(chat_app, conversation)
    assert [item[1] for item in rows["messages"]] == ["user"]
    assert rows["source_links"] == 0
    assert rows["requests"] == [[1, "running", None]]
    assert len(gateway.calls) == 1, "提交失败不得重发模型调用"
    _dump_r1(
        "r1-commit-lock-contention.json",
        {"error": str(error), "elapsed_seconds": round(elapsed, 3), "rows": rows, "calls": len(gateway.calls)},
    )


def test_g05_boundary_budget_still_commits(chat_admin, chat_employee, chat_app, monkeypatch):
    """PM06-02：恰在总预算边界返回的合法结果仍可提交（临界成功）。"""
    _b0(chat_admin, chat_app)
    conversation = _create(chat_employee)
    user = _user_context(chat_app, "employee")

    ticks = chain([1000.0, 1000.0, 1000.0], repeat(1060.0))
    monkeypatch.setattr(service, "monotonic", lambda: next(ticks))

    result = _ask_sync(chat_app, user, conversation, "城东店的宣传海报在哪里？")
    assert result.kind == "answer", result
    assert result.sources
    rows = _message_rows(chat_app, conversation)
    assert [item[1] for item in rows["messages"]] == ["user", "assistant"]
    assert rows["source_links"] == 1
    assert rows["requests"] == [[1, "succeeded", None]]
    _dump_r1(
        "r1-budget-boundary-commit.json",
        {"result": result.model_dump(mode="json"), "rows": rows},
    )


def test_commit_transaction_restores_connection_busy_timeout(tmp_path):
    """提交专用事务只临时收紧等锁时间，结束后恢复连接默认值，不污染连接池。"""
    from sqlalchemy import text

    from mktkb.db import Database

    database = Database(f"sqlite:///{(tmp_path / 'pragma.sqlite3').as_posix()}")
    try:
        with service._commit_transaction(database.session, service.monotonic() + 0.05) as session:
            inside = int(session.execute(text("PRAGMA busy_timeout")).scalar() or 0)
        session = database.session()
        try:
            restored = int(session.execute(text("PRAGMA busy_timeout")).scalar() or 0)
        finally:
            session.close()
    finally:
        database.dispose()
    assert 0 < inside <= 50, inside
    assert restored == 5000, restored
