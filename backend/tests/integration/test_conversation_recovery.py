"""T06 G07 真实子进程恢复；G10 0004 真实快照升级保护。

G07 用独立 Python 子进程持有同一数据库与存储目录：进入模型等待后被杀，验证会话/消息持久、
running 请求按持久截止回收、显式同载荷重试新增 attempt、旧 attempt 不得提交、重开不自动再调模型。
G10 用本轮修改前保存的 0004 真实已发布快照副本升级到 0005，逐表比对旧数据、原件、索引与 revision。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import current_csrf, login, write_headers
from mktkb.config import Settings
from mktkb.db import Database, run_migrations
from mktkb.main import create_app

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "docs" / "evidence" / "T06" / "before" / "0004-snapshot"
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _settings(data_dir: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="t06-recovery-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
    )


CHILD_ASK = r'''
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[6])
from mktkb.config import Settings
from mktkb.main import create_app
from mktkb.auth.models import User
from mktkb.auth.service import UserContext
from mktkb.conversations import service
from mktkb.conversations.schemas import AskRequest
from sqlalchemy import select
from mktkb.providers.types import CompletionOutput

data_dir = Path(sys.argv[1]); conversation_id = sys.argv[2]; request_id = sys.argv[3]
question = sys.argv[4]; marker_dir = Path(sys.argv[5]); backend_src = sys.argv[6]

class BlockingGateway:
    async def complete(self, request, *, timeout_seconds):
        (marker_dir / "calls.txt").open("a", encoding="utf-8").write(request.purpose + "\n")
        (marker_dir / "entered").write_text("1", encoding="utf-8")
        deadline = time.time() + 120
        while time.time() < deadline:
            if (marker_dir / "release").exists():
                break
            await asyncio.sleep(0.05)
        ids = tuple(item.source_id for item in request.evidence)
        text = "根据资料：" + "；".join(item.text for item in request.evidence)
        return CompletionOutput(text=text, source_ids=ids)

settings = Settings(_env_file=None, data_dir=data_dir, database_url=f"sqlite:///{(data_dir/'mktkb.sqlite3').as_posix()}",
                    cookie_secure=False, csrf_secret="t06-recovery-csrf-secret-0123456789",
                    admin_password="AdminPass-1", employee_password="EmployeePass-1",
                    trusted_origins=["http://testserver"], bcrypt_rounds=4)
app = create_app(settings, model_gateway=BlockingGateway(), initialize=False)
db = app.state.db.session()
try:
    user_row = db.scalar(select(User).where(User.username == "employee"))
    user = UserContext(id=user_row.id, username=user_row.username, display_name=user_row.display_name,
                       role=user_row.role, session_id=None)
finally:
    db.close()
payload = AskRequest(client_request_id=request_id, question=question)
result = asyncio.run(service.ask(app.state.db.session, user, __import__("uuid").UUID(conversation_id), payload,
                                 model=app.state.model_gateway))
(marker_dir / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
'''

CHILD_REOPEN = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from sqlalchemy import func, select
from mktkb.config import Settings
from mktkb.main import create_app
from mktkb.conversations.models import Conversation, ConversationMessage, ConversationRequest
from mktkb.documents.lifecycle import get_revision

data_dir = Path(sys.argv[1]); backend_src = sys.argv[2]
settings = Settings(_env_file=None, data_dir=data_dir, database_url=f"sqlite:///{(data_dir/'mktkb.sqlite3').as_posix()}",
                    cookie_secure=False, csrf_secret="t06-recovery-csrf-secret-0123456789",
                    admin_password="AdminPass-1", employee_password="EmployeePass-1",
                    trusted_origins=["http://testserver"], bcrypt_rounds=4)
app = create_app(settings, initialize=False)
db = app.state.db.session()
try:
    payload = {
        "conversations": int(db.scalar(select(func.count()).select_from(Conversation)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(ConversationMessage)) or 0),
        "requests": [list(row) for row in db.execute(select(ConversationRequest.attempt, ConversationRequest.status))],
        "revision": get_revision(db),
        "titles": [row[0] for row in db.execute(select(Conversation.title))],
    }
finally:
    db.close()
print(json.dumps(payload, ensure_ascii=False))
'''


def _write_child_scripts(tmp_path: Path) -> tuple[Path, Path, str]:
    backend_src = str(ROOT / "backend" / "src")
    ask = tmp_path / "child_ask.py"
    reopen = tmp_path / "child_reopen.py"
    ask.write_text(CHILD_ASK, encoding="utf-8")
    reopen.write_text(CHILD_REOPEN, encoding="utf-8")
    return ask, reopen, backend_src


def _run_child(script: Path, argv: list[str], *, env_extra: dict | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-B", str(script), *argv], capture_output=True, timeout=timeout, env=env, cwd=str(ROOT)
    )


def _wait_for(path: Path, timeout: float = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def test_g07_subprocess_crash_then_persistent_retry(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    marker_dir = tmp_path / "marker"
    marker_dir.mkdir()
    ask_script, reopen_script, backend_src = _write_child_scripts(tmp_path)

    # 父进程建立会话与一份已发布资料（真实 HTTP 上传/worker/发布）
    from conftest import EvidenceEchoGateway

    parent_gateway = EvidenceEchoGateway()
    settings = _settings(data_dir)
    app = create_app(settings, model_gateway=parent_gateway)
    admin = TestClient(app, raise_server_exceptions=False)
    login(admin, "admin", "AdminPass-1")
    admin_headers = write_headers(current_csrf(admin))
    receipt = admin.post(
        "/api/v1/documents",
        files={"file": (D01.name, D01.read_bytes(), "application/octet-stream")},
        headers=admin_headers,
    )
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    from mktkb.ingestion.worker import run_one_job

    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
    finally:
        db.close()
    published = admin.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        json={"expected_active_version_id": None, "expected_revision": 0},
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text

    employee = TestClient(app, raise_server_exceptions=False)
    login(employee, "employee", "EmployeePass-1")
    conversation = employee.post("/api/v1/conversations", json={"title": "恢复用例"}, headers=write_headers(current_csrf(employee)))
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    # 第一个子进程：真实进程内进入模型等待，然后被强杀
    question = "城东店的宣传海报在哪里？"
    request_id = str(uuid.uuid4())
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    child = subprocess.Popen(
        [
            sys.executable,
            "-B",
            str(ask_script),
            str(data_dir),
            conversation_id,
            request_id,
            question,
            str(marker_dir),
            backend_src,
        ],
        stdout=(tmp_path / "child.out").open("wb"),
        stderr=(tmp_path / "child.err").open("wb"),
        env=env,
        cwd=str(ROOT),
    )
    try:
        assert _wait_for(marker_dir / "entered", 60), "子进程未进入模型等待"
    finally:
        child.terminate()
    child.wait(timeout=30)
    assert child.returncode is not None

    # 崩溃后：会话/用户消息持久，请求停在 running，未写助手消息
    check = _run_child(reopen_script, [str(data_dir), backend_src])
    assert check.returncode == 0, check.stderr.decode("utf-8", "replace")
    reopened = json.loads(check.stdout.decode("utf-8"))
    assert reopened["conversations"] == 1 and reopened["messages"] == 1
    assert reopened["requests"] == [[1, "running"]]
    assert (marker_dir / "calls.txt").read_text(encoding="utf-8").count("answer") == 1
    assert not (marker_dir / "release").exists()

    # 重开不自动重发模型请求：再次只读重开，调用计数不变
    check2 = _run_child(reopen_script, [str(data_dir), backend_src])
    assert check2.returncode == 0
    assert (marker_dir / "calls.txt").read_text(encoding="utf-8").count("answer") == 1

    # 模拟持久截止已过（不改消息），显式同载荷重试 -> 新 attempt 完成
    deadline_connection = sqlite3.connect(data_dir / "mktkb.sqlite3")
    try:
        deadline_connection.execute(
            "UPDATE conversation_requests SET deadline_at = '2000-01-01 00:00:00.000000' WHERE status = 'running'"
        )
        deadline_connection.commit()
    finally:
        deadline_connection.close()

    retry = employee.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": request_id, "question": question},
        headers=write_headers(current_csrf(employee)),
    )
    assert retry.status_code == 200, retry.text
    payload = retry.json()
    assert payload["kind"] == "answer", payload
    assert payload["sources"]

    history = employee.get(f"/api/v1/conversations/{conversation_id}/messages").json()
    assert history["total"] == 2
    roles = [item["role"] for item in history["items"]]
    assert roles == ["user", "assistant"]
    assert history["items"][1]["kind"] == "answer"
    assert len(parent_gateway.calls) == 1, "显式重试只新增一次模型调用"
    assert (marker_dir / "calls.txt").read_text(encoding="utf-8").count("answer") == 1, "被杀子进程只有一次调用"

    verify = _run_child(reopen_script, [str(data_dir), backend_src])
    final_state = json.loads(verify.stdout.decode("utf-8"))
    assert final_state["messages"] == 2
    assert final_state["requests"] == [[2, "succeeded"]]
    assert final_state["titles"] == ["恢复用例"]
    app.state.db.dispose()


def _dump_tables(database: Path) -> dict:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        old_tables = (
            "users",
            "login_sessions",
            "documents",
            "document_versions",
            "import_jobs",
            "source_units",
            "knowledge_state",
            "publication_receipts",
            "deletion_receipts",
        )
        result = {"alembic_version": [row[0] for row in connection.execute("SELECT version_num FROM alembic_version")]}
        for table in old_tables:
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            result[table] = {"count": len(rows), "rows": rows}
        fts = [dict(row) for row in connection.execute("SELECT rowid, body, version_id FROM source_unit_fts ORDER BY rowid")]
        result["fts"] = {"count": len(fts), "rows": fts}
        for table in ("retrieval_version_index", "retrieval_unit_index", "retrieval_field_index"):
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            result[table] = {
                "count": len(rows),
                "digest": hashlib.sha256(
                    ("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows) + "\n").encode("utf-8")
                ).hexdigest(),
            }
        result["tables"] = sorted(
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        )
        return result
    finally:
        connection.close()


def test_g10_upgrade_real_0004_snapshot_preserves_data(tmp_path):
    facts = json.loads((SNAPSHOT / "facts.json").read_text(encoding="utf-8"))
    data = tmp_path / "upgraded"
    import shutil

    shutil.copytree(SNAPSHOT / "data", data)
    database = data / "mktkb.sqlite3"
    before = _dump_tables(database)
    assert before["alembic_version"] == ["0004_retrieval"]

    url = f"sqlite:///{database.as_posix()}"
    run_migrations(url)
    after = _dump_tables(database)
    assert after["alembic_version"] == ["0006_ocr_call_records"]
    assert set(after["tables"]) - set(before["tables"]) == {
        "conversations",
        "conversation_messages",
        "conversation_requests",
        "conversation_message_sources",
        "ocr_call_records",
    }
    for table in (
        "users",
        "login_sessions",
        "documents",
        "document_versions",
        "import_jobs",
        "source_units",
        "knowledge_state",
        "publication_receipts",
        "deletion_receipts",
    ):
        assert after[table] == before[table], f"{table} 行值在升级后发生变化"
    assert after["fts"] == before["fts"]
    for table in ("retrieval_version_index", "retrieval_unit_index", "retrieval_field_index"):
        assert after[table] == before[table], f"{table} 摘要变化"

    # 与快照记录的 revision/计数/原件一致
    state = after["knowledge_state"]["rows"][0]
    assert state["revision"] == facts["knowledge_state"]["revision"] == 5
    assert state["active_document_count"] == 4
    assert state["active_excel_row_count"] == 13
    originals = {
        path.relative_to(data).as_posix(): _sha256(path)
        for path in (data / "storage" / "originals").rglob("*")
        if path.is_file()
    }
    expected_originals = {item["path"]: item["sha256"] for item in facts["storage"]["originals"]}
    assert originals == expected_originals

    # 重复升级不增数据
    run_migrations(url)
    repeat = _dump_tables(database)
    assert repeat == after

    # 空库升级到单一 head
    empty = tmp_path / "empty"
    empty.mkdir()
    empty_url = f"sqlite:///{(empty / 'empty.sqlite3').as_posix()}"
    run_migrations(empty_url)
    empty_dump = _dump_tables(empty / "empty.sqlite3")
    assert empty_dump["alembic_version"] == ["0006_ocr_call_records"]
    assert {"conversations", "conversation_messages", "conversation_requests", "conversation_message_sources"} <= set(
        empty_dump["tables"]
    )
    assert empty_dump["knowledge_state"]["count"] == 1
