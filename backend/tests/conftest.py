"""测试装配：临时数据目录、隔离 SQLite、ASGI 客户端与角色探针。

所有临时路径来自 pytest 的 `tmp_path`，实际位置由 `--basetemp` 决定，避免依赖默认 TEMP。
T03 起同一装配也供上传/解析/worker 检查复用：数据目录与存储目录都在临时根下。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from mktkb.auth.routes import require_role
from mktkb.auth.service import create_account
from mktkb.config import Settings
from mktkb.main import create_app
from mktkb.providers.types import CompletionOutput

ORIGIN = "http://testserver"

probe_router = APIRouter(prefix="/api/v1/probe", tags=["test-probe"])


@probe_router.get("/admin")
def probe_admin(user=Depends(require_role("admin"))):  # noqa: ANN001
    return {"role": user.role}


@probe_router.get("/employee")
def probe_employee(user=Depends(require_role("employee"))):  # noqa: ANN001
    return {"role": user.role}


@probe_router.get("/boom")
def probe_boom():
    """测试专用：模拟未处理异常，异常消息含类秘密与路径，用于验证脱敏。"""
    raise RuntimeError("PM-SIMULATED-PASSWORD-NEVER-REAL sqlite:///C:/secret/db.sqlite3")


def login(client: TestClient, username: str, password: str, origin: str | None = ORIGIN) -> dict:
    headers = {"Origin": origin} if origin else {}
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def store(tmp_path: Path) -> SimpleNamespace:
    """隔离数据/存储根目录；应用工厂会在其下建立 storage 子目录。"""
    root = tmp_path / "store"
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(root=root)


@pytest.fixture(scope="session", autouse=True)
def isolate_dotenv_in_test_process():
    """T09-D3：测试进程内默认不读工作目录下的 ``.env``。

    背景：仓库根存在真实模型/OCR 配置的 ``.env``。从仓库根运行 pytest 时，测试里任何未显式
    指定 ``_env_file=None`` 的 ``Settings()`` 都会读到它（D2 §9 偏差 9 的事故点：构造了真实
    DeepSeek 客户端并可能发出 1 次请求）。这里把 ``Settings`` 的默认 env_file 源临时关闭，
    等价于对**整个测试进程**做隔离，覆盖 ``conftest.settings`` 之外的散落构造（如
    ``test_visible_index`` 的升级后装配）。显式传 ``_env_file=<临时文件>`` 的用例不受影响；
    真实入口的 ``.env`` 读取能力仍由 ``test_config::test_dotenv_is_read_from_working_directory``
    在子进程 + 临时 cwd 下验证，本 fixture 不改任何既有断言。
    """
    original = Settings.model_config.get("env_file")
    Settings.model_config = {**Settings.model_config, "env_file": None}
    try:
        yield
    finally:
        Settings.model_config = {**Settings.model_config, "env_file": original}


@pytest.fixture
def settings(store: SimpleNamespace) -> Settings:
    database = store.root / "mktkb.sqlite3"
    return Settings(
        _env_file=None,
        data_dir=store.root,
        database_url=f"sqlite:///{database.as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="INFO",
    )


@pytest.fixture
def app(settings: Settings):
    application = create_app(settings)
    application.include_router(probe_router)
    yield application
    application.state.db.dispose()


@pytest.fixture
def db(app):
    session = app.state.db.session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(app) -> TestClient:
    test_client = TestClient(app, raise_server_exceptions=False)
    login(test_client, "admin", "AdminPass-1")
    return test_client


@pytest.fixture
def employee_client(app) -> TestClient:
    test_client = TestClient(app, raise_server_exceptions=False)
    login(test_client, "employee", "EmployeePass-1")
    return test_client


@pytest.fixture
def second_employee_client(app, db) -> TestClient:
    create_account(db, username="employee2", password="EmployeePass-2", display_name="演示员工二", role="employee", rounds=4)
    test_client = TestClient(app, raise_server_exceptions=False)
    login(test_client, "employee2", "EmployeePass-2")
    return test_client


# ---- T03 起复用的上传/写操作辅助 ----
# 说明：辅助函数不导入 documents/ingestion 模块，避免在功能实现前让 T02 检查整体导入失败。


def current_csrf(client: TestClient) -> str:
    """登录后从 /auth/me 读取当前会话对应的 CSRF 令牌。"""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def write_headers(csrf: str | None, origin: str = ORIGIN) -> dict[str, str]:
    """受信任 Origin + 会话 CSRF；值缺失时省略对应头，用于验证拒绝路径。"""
    headers: dict[str, str] = {}
    if origin is not None:
        headers["Origin"] = origin
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    return headers


def upload_document(
    client: TestClient,
    *,
    csrf: str | None,
    path: Path | None = None,
    content: bytes | None = None,
    name: str | None = None,
    allow_same_name: bool | None = None,
    document_id: object | None = None,
    expected_active_version_id: object | None = None,
    content_type: str = "application/octet-stream",
    headers: dict[str, str] | None = None,
):
    """以管理员会话上传文件（multipart）；返回原始响应供状态码/结构断言。"""
    if content is None:
        assert path is not None
        content = Path(path).read_bytes()
    filename = name or (Path(path).name if path is not None else "upload.bin")
    data: dict[str, str] = {}
    if allow_same_name is not None:
        data["allow_same_name"] = "true" if allow_same_name else "false"
    if expected_active_version_id is not None:
        data["expected_active_version_id"] = str(expected_active_version_id)
    url = "/api/v1/documents"
    if document_id is not None:
        url = f"/api/v1/documents/{document_id}/versions"
    return client.post(
        url,
        files={"file": (filename, content, content_type)},
        data=data,
        headers=headers if headers is not None else write_headers(csrf),
    )


@pytest.fixture
def admin_write(admin_client: TestClient) -> SimpleNamespace:
    """管理员会话 + 当前 CSRF + 完整写头 + 上传快捷方法。"""
    csrf = current_csrf(admin_client)
    return SimpleNamespace(
        client=admin_client,
        csrf=csrf,
        headers=write_headers(csrf),
        upload=lambda **kwargs: upload_document(admin_client, csrf=csrf, **kwargs),
    )


@pytest.fixture
def employee_write(employee_client: TestClient) -> SimpleNamespace:
    csrf = current_csrf(employee_client)
    return SimpleNamespace(client=employee_client, csrf=csrf, headers=write_headers(csrf))


# ---- T06 可控模型注入与会话辅助（不改变上面既有 fixture 行为） ----


class EvidenceEchoGateway:
    """可控模型替身：只回显本次请求里的证据，不内置任何业务答案。

    - ``calls`` 记录每次调用的 purpose/问题/证据/超时，供调用计数与载荷断言；
    - ``error`` 可注入 MODEL_* 稳定错误；``answer_text``/``source_ids`` 可注入非法输出；
    - ``entered``/``block_after_entry`` 供事件屏障测试在模型等待期间制造并发变更。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.expansion_terms: tuple[str, ...] = ()
        self.answer_text: str | None = None
        self.source_ids: tuple[str, ...] | None = None
        self.error: Exception | None = None
        self.entered: threading.Event | None = None
        self.block_after_entry: threading.Event | None = None
        self.release_timeout = 15.0

    async def complete(self, request, *, timeout_seconds: float) -> CompletionOutput:
        self.calls.append(
            {
                "purpose": request.purpose,
                "question": request.question,
                "evidence": [
                    {"source_id": item.source_id, "text": item.text, "fields": dict(item.fields)}
                    for item in request.evidence
                ],
                "context": {
                    "questions": list(request.context.questions),
                    "entities": dict(request.context.entities),
                },
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.entered is not None:
            self.entered.set()
        if self.block_after_entry is not None:
            await asyncio.to_thread(self.block_after_entry.wait, self.release_timeout)
        if self.error is not None:
            raise self.error
        if request.purpose == "query_expansion":
            return CompletionOutput(text="expansion", query_terms=tuple(self.expansion_terms))
        text = self.answer_text if self.answer_text is not None else _compose_answer(request)
        source_ids = self.source_ids if self.source_ids is not None else tuple(item.source_id for item in request.evidence)
        return CompletionOutput(text=text, source_ids=tuple(source_ids))


def _compose_answer(request) -> str:
    parts: list[str] = []
    for item in request.evidence[:8]:
        if item.fields:
            pairs = "；".join(f"{key}：{value}" for key, value in list(item.fields.items())[:12])
            parts.append(pairs)
        elif item.text:
            parts.append(item.text)
    return "根据资料：" + "；".join(parts)


@pytest.fixture
def chat_model() -> EvidenceEchoGateway:
    return EvidenceEchoGateway()


@pytest.fixture
def chat_app(settings: Settings, chat_model: EvidenceEchoGateway):
    application = create_app(settings, model_gateway=chat_model)
    application.include_router(probe_router)
    yield application
    application.state.db.dispose()


def _write_session(app, username: str, password: str) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    login(client, username, password)
    csrf = current_csrf(client)
    return SimpleNamespace(
        client=client,
        csrf=csrf,
        headers=write_headers(csrf),
        upload=lambda **kwargs: upload_document(client, csrf=csrf, **kwargs),
    )


@pytest.fixture
def chat_admin(chat_app) -> SimpleNamespace:
    return _write_session(chat_app, "admin", "AdminPass-1")


@pytest.fixture
def chat_employee(chat_app) -> SimpleNamespace:
    return _write_session(chat_app, "employee", "EmployeePass-1")


@pytest.fixture
def chat_employee2(chat_app) -> SimpleNamespace:
    db = chat_app.state.db.session()
    try:
        create_account(
            db, username="employee2", password="EmployeePass-2", display_name="演示员工二", role="employee", rounds=4
        )
    finally:
        db.close()
    return _write_session(chat_app, "employee2", "EmployeePass-2")
