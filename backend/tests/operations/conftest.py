"""T302 运营接口测试装配：隔离应用（Trace 开/关）与数据构造辅助。

全部数据落在 pytest ``tmp_path``；不读 ``.env``、不写 ``var/``、不调用真实模型 / OCR。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import ORIGIN, current_csrf, login
from mktkb.config import Settings
from mktkb.main import create_app


@pytest.fixture
def trace_ops_path(tmp_path) -> object:
    return tmp_path / "observability" / "qa-traces.sqlite3"


@pytest.fixture
def trace_settings(settings: Settings, trace_ops_path) -> Settings:
    """业务配置不变，仅打开 Trace；Trace 库落在 ``tmp_path``。"""
    return settings.model_copy(
        update={
            "trace_enabled": True,
            "trace_db_path": trace_ops_path,
            "trace_content_mode": "hash",
            "trace_hmac_key": None,
        }
    )


@pytest.fixture
def trace_ops_app(trace_settings: Settings):
    application = create_app(trace_settings)
    try:
        yield application
    finally:
        repo = getattr(application.state, "trace_repo", None)
        if repo is not None:
            repo.close()
        qa = getattr(application.state, "qa", None)
        if qa is not None:
            qa.close()
        application.state.db.dispose()


@pytest.fixture
def trace_admin(trace_ops_app) -> TestClient:
    client = TestClient(trace_ops_app, raise_server_exceptions=False)
    login(client, "admin", "AdminPass-1")
    return client


@pytest.fixture
def trace_employee(trace_ops_app) -> TestClient:
    client = TestClient(trace_ops_app, raise_server_exceptions=False)
    login(client, "employee", "EmployeePass-1")
    return client


@pytest.fixture
def trace_db(trace_ops_app):
    session = trace_ops_app.state.db.session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_write(admin_client: TestClient) -> dict:
    """管理员会话的写头（Origin + CSRF），供本包少量正常入口构造使用。"""
    return {"Origin": ORIGIN, "X-CSRF-Token": current_csrf(admin_client)}
