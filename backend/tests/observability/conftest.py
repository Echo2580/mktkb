"""T003b：可观测性接线（config + 中间件）共享测试装配。

本文件只提供后续 T003c/d、评测/门禁包可复用的 fixture，不改变既有测试装配
（``backend/tests/conftest.py``）的任何 fixture 与断言：

- ``trace_settings``：在既有测试配置上**只**打开观测开关（业务库、数据目录、账号、
  会话、校验强度与默认配置完全相同），Trace 库落在 ``tmp_path`` 下；
- ``trace_app`` / ``trace_repo``：开启 Trace 的应用与仓储；
- ``trace_employee`` / ``trace_admin``：开启 Trace 应用里已登录、带 CSRF 写头的会话。

所有路径来自 pytest ``tmp_path``；不读 ``.env``、不访问外网、不调用真实模型 / OCR /
embedding / rerank。本文件的 helper 只用内存与临时 SQLite，不触碰 ``var/``、``docs/evidence``。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import current_csrf, login, upload_document, write_headers
from mktkb.config import Settings
from mktkb.main import create_app
from mktkb.observability.store import TraceRepository

#: 固定问题：没有已发布资料时会稳定返回 ``kind=not_found`` 的 200 响应，不触发模型调用。
FIXED_QUESTION = "城东店的宣传海报在哪里？"


# ---- 可复用辅助（测试文件直接 import 使用） ----


def open_session(app, username: str, password: str) -> SimpleNamespace:
    """在指定应用上登录并返回带 CSRF 写头 / 上传快捷方法 / 固定问答的会话。"""
    client = TestClient(app, raise_server_exceptions=False)
    login(client, username, password)
    csrf = current_csrf(client)
    session = SimpleNamespace(
        client=client,
        csrf=csrf,
        headers=write_headers(csrf),
        upload=lambda **kwargs: upload_document(client, csrf=csrf, **kwargs),
    )
    return session


def create_conversation(session: SimpleNamespace, *, title: str | None = None) -> str:
    """新建一个会话，返回会话 id。"""
    payload: dict[str, str] = {} if title is None else {"title": title}
    response = session.client.post("/api/v1/conversations", json=payload, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask_question(
    session: SimpleNamespace,
    conversation_id: str,
    question: str = FIXED_QUESTION,
    *,
    client_request_id: uuid.UUID | None = None,
):
    """向会话提问（产品 QA POST），返回原始响应供状态码/响应头/body 断言。"""
    return session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "client_request_id": str(client_request_id or uuid.uuid4()),
            "question": question,
        },
        headers=session.headers,
    )


def trace_rows(db_path: Path) -> list[tuple]:
    """以只读连接读取 Trace 库全部行（按写入顺序）；库不存在时返回空列表。

    只用于测试断言“写了几条 trace”，不写任何数据；应用自己的 TraceRepository 仍在写。
    """
    path = Path(db_path)
    if not path.exists():
        return []
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT * FROM traces ORDER BY rowid ASC").fetchall()
    except sqlite3.OperationalError:
        # 库文件已存在但 schema 尚未建好（不应发生）；按“无记录”处理并在断言处暴露
        return []
    finally:
        connection.close()


# ---- fixture ----


@pytest.fixture
def trace_db_path(tmp_path: Path) -> Path:
    """每次测试独立的 Trace 库路径：与业务库/数据目录分离，且不在 ``var/`` 下。"""
    return tmp_path / "observability" / "qa-traces.sqlite3"


@pytest.fixture
def trace_settings(settings: Settings, trace_db_path: Path) -> Settings:
    """既有测试配置 + 开启 Trace（业务配置不变；默认内容模式 ``hash``、无 HMAC key）。"""
    return settings.model_copy(
        update={
            "trace_enabled": True,
            "trace_db_path": trace_db_path,
            "trace_content_mode": "hash",
            "trace_hmac_key": None,
        }
    )


@pytest.fixture
def trace_app(trace_settings: Settings):
    """开启 Trace 的应用；测试结束关闭 Trace 仓储 / rag 内核 / 业务库连接。"""
    application = create_app(trace_settings)
    try:
        yield application
    finally:
        state = application.state
        repo = getattr(state, "trace_repo", None)
        if repo is not None:
            repo.close()
        qa = getattr(state, "qa", None)
        if qa is not None:
            qa.close()
        state.db.dispose()


@pytest.fixture
def trace_repo(trace_app) -> TraceRepository:
    """``trace_enabled=True`` 时 ``create_app`` 必须挂上的 Trace 仓储。"""
    repo = trace_app.state.trace_repo
    assert isinstance(repo, TraceRepository), "trace_enabled=True 必须创建 app.state.trace_repo"
    return repo


@pytest.fixture
def trace_employee(trace_app) -> SimpleNamespace:
    """开启 Trace 应用里的员工会话（可创建会话、发 QA POST）。"""
    return open_session(trace_app, "employee", "EmployeePass-1")


@pytest.fixture
def trace_admin(trace_app) -> SimpleNamespace:
    """开启 Trace 应用里的管理员会话（可上传资料）。"""
    return open_session(trace_app, "admin", "AdminPass-1")
