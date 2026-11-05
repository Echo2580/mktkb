"""T003b：Trace 配置与 HTTP 中间件接线测试（P0 第 4 包）。

覆盖范围严格限定为「观测开关 + 中间件」：

- 设计 §5（架构里 ``request_context`` 生成 trace_id）、§6.1（粒度与标识）、
  §6.2（独立 SQLite 存储）、§6.5（内容隐私/HMAC）、§6.6（写入语义）、§10（兼容性：
  唯一允许新增 ``X-Trace-ID`` 响应头）；
- handoff §5 八条验收：默认关闭零副作用 / 开启后落 trace / 范围只限 QA POST /
  写入失败不影响产品 / 行为不变 / mode 硬约束 / 配置安全 / 测试与回归。

T003b 只做「观测开关 + 中间件」接线；T003d 起业务层会补 legacy/RAG Span 与
``request_id`` / ``path`` / ``outcome``。本文件对固定问答的断言只锁定中间件职责
（响应头、mode/scope/content_mode、一次 POST 一条 trace、无原文），业务埋点细节由
``test_paths_e2e.py`` 覆盖。

零真实模型 / OCR / embedding / rerank 调用；测试只写 ``tmp_path``，不读 ``.env``，
不打印凭据、不访问外网。
"""

from __future__ import annotations

import ast
import io
import logging
import uuid
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

import mktkb.main as main_module
from conftest import ORIGIN
from mktkb.config import Settings
from mktkb.main import create_app
from mktkb.observability import TraceMode, current_trace
from mktkb.observability.store import TraceRepository, TraceWriteError
from observability.conftest import (
    FIXED_QUESTION,
    ask_question,
    create_conversation,
    open_session,
    trace_rows,
)

#: main.py 的唯一允许入口：QA 问答 POST。
QA_PATH = f"/api/v1/conversations/{{conversation_id}}/messages"
#: Trace 记录的 volatile 字段（归一化后比较两个设置下的响应 body）。
VOLATILE_RESPONSE_KEYS = frozenset({"request_id", "message_id", "conversation_id", "created_at", "updated_at"})
#: 测试用固定 client_request_id：两次请求用同一个值，模拟"同一固定请求"。
FIXED_CLIENT_REQUEST_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
#: 测试用 HMAC key：以明文常量参与断言，验证它不落库/不打印/不进响应/不进异常。
FAKE_HMAC_KEY = "pm-test-hmac-key-0123456789abcdef"


# ---- 辅助 ----


def _make_settings(data_dir: Path, **overrides: object) -> Settings:
    """构造独立数据目录的 Settings（不读 ``.env``；默认关闭 Trace）。"""
    base: dict[str, object] = dict(
        _env_file=None,
        data_dir=data_dir,
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _close_app(app) -> None:
    """测试内自建应用的手工收尾（fixture 应用由 conftest 负责关闭）。"""
    repo = getattr(app.state, "trace_repo", None)
    if repo is not None:
        repo.close()
    qa = getattr(app.state, "qa", None)
    if qa is not None:
        qa.close()
    app.state.db.dispose()


def _xlsx_bytes() -> bytes:
    """最小合法 xlsx（用于验证上传端点没有 X-Trace-ID）。"""
    workbook = openpyxl.Workbook()
    workbook.active.append(["门店", "位置"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _normalized(payload: object) -> object:
    """去掉易变字段后的响应 body（handoff §5.5 的"归一化后完全一致"）。"""
    if isinstance(payload, dict):
        return {
            key: _normalized(value)
            for key, value in payload.items()
            if key not in VOLATILE_RESPONSE_KEYS
        }
    if isinstance(payload, list):
        return [_normalized(item) for item in payload]
    return payload


def _assert_no_internal_leak(text: str) -> None:
    """响应不得泄漏 trace 写入失败/配置类的内部错误。"""
    for marker in ("trace_write_error", "TraceWriteError", "RuntimeError", "Traceback", "sqlite"):
        assert marker not in text


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _module_constant(tree: ast.Module, name: str) -> ast.expr | None:
    """取模块顶层 ``NAME = <表达式>`` 的右值（静态断言常量绑定用）。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    return None


# ---- §5.1 默认关闭：零副作用、既有 X-Request-ID 不变 ----


def test_settings_trace_defaults_are_disabled_and_safe(monkeypatch, tmp_path: Path):
    """默认关闭：不建库、无请求头；内容模式默认 hash、无 HMAC key（设计 §6.5）。"""
    monkeypatch.delenv("MKTKB_TRACE_ENABLED", raising=False)
    settings = _make_settings(tmp_path / "defaults")
    assert settings.trace_enabled is False
    assert settings.trace_db_path is None
    assert settings.trace_content_mode == "hash"
    assert settings.trace_hmac_key is None
    assert settings.resolved_trace_db_path == settings.data_dir / "observability" / "qa-traces.sqlite3"
    assert settings.trace_hmac_key_bytes is None


def test_disabled_app_has_no_trace_repo_or_db_file_and_keeps_request_id(monkeypatch, tmp_path: Path):
    """关闭时：不构造 TraceRepository、不建任何 Trace DB 文件、不调用 start_trace。"""
    monkeypatch.delenv("MKTKB_TRACE_ENABLED", raising=False)
    settings = _make_settings(tmp_path / "disabled")
    app = create_app(settings)
    started: list[dict] = []

    def _forbid_start(**kwargs):  # noqa: ANN001 - 替身签名与 start_trace 一致即可
        started.append(kwargs)
        raise AssertionError("trace_enabled=False 时中间件不得启动 trace")

    monkeypatch.setattr(main_module, "start_trace", _forbid_start)
    try:
        assert app.state.trace_repo is None
        session = open_session(app, "employee", "EmployeePass-1")
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        assert response.status_code == 200, response.text
        # 既有 X-Request-ID 行为不变；不新增 X-Trace-ID。
        assert response.headers.get("X-Request-ID")
        assert "X-Trace-ID" not in response.headers
        # 全过程没有 trace 上下文、没有任何 Trace DB 文件/目录。
        assert current_trace() is None
        assert started == []
        assert not (Path(settings.data_dir) / "observability").exists()
        assert not Path(settings.resolved_trace_db_path).exists()
    finally:
        _close_app(app)


# ---- §5.2 开启后：返回 X-Trace-ID 并 best-effort 落一条 trace ----


def test_enabled_app_creates_repo_at_configured_path(trace_settings, trace_app, trace_repo, trace_db_path):
    """开启时 create_app 才创建 TraceRepository，且落到配置的独立路径。"""
    assert trace_settings.trace_enabled is True
    assert trace_settings.resolved_trace_db_path == trace_db_path
    assert isinstance(trace_repo, TraceRepository)
    assert trace_app.state.trace_repo is trace_repo
    assert Path(trace_db_path).exists()


def test_enabled_qa_post_returns_uuid_trace_header_and_persists_trace(trace_employee, trace_repo, trace_db_path):
    """QA POST 响应头 X-Trace-ID 指向已写入的一条 trace（T003d 接线后带业务 Span）。"""
    conversation_id = create_conversation(trace_employee)
    response = ask_question(trace_employee, conversation_id)
    assert response.status_code == 200, response.text
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id, "开启 Trace 时 QA POST 必须返回 X-Trace-ID"
    # 合法 UUID 形态（内核用 uuid4().hex；uuid.UUID 同时接受 32 位 hex 与带连字符形态）。
    assert uuid.UUID(trace_id) is not None
    http_request_id = response.headers.get("X-Request-ID")
    assert http_request_id

    trace, spans = trace_repo.get(trace_id)
    assert trace.trace_id == trace_id
    assert trace.http_request_id == http_request_id
    assert trace.mode == "local"  # P0 只允许 replay/local；中间件固定 local
    assert trace.scope == "end_to_end"
    assert trace.content_mode == "hash"
    assert trace.replayed is False
    assert trace.attempt == 1
    # T003d 接线：request_id 绑定本次产品请求；固定问答（空库）走 legacy 路径并稳定 not_found。
    assert trace.request_id == response.json()["request_id"]
    assert trace.path == "legacy"
    assert trace.outcome_kind == "not_found"
    assert trace.status == "ok"
    assert trace.question_hash is not None and len(trace.question_hash) == 64
    assert trace.question_chars == len(FIXED_QUESTION)
    assert spans and {"recall", "fuse", "hard_filter"} <= {span.name for span in spans}
    # 一条 QA POST 恰好写一行 trace。
    assert len(trace_rows(trace_db_path)) == 1


def test_each_qa_post_writes_exactly_one_trace(trace_employee, trace_db_path):
    conversation_id = create_conversation(trace_employee)
    first = ask_question(trace_employee, conversation_id)
    second = ask_question(trace_employee, conversation_id)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_id = first.headers["X-Trace-ID"]
    second_id = second.headers["X-Trace-ID"]
    assert first_id != second_id
    rows = trace_rows(trace_db_path)
    assert len(rows) == 2
    assert {row[0] for row in rows} == {first_id, second_id}


def test_middleware_passes_local_mode_and_settings_content_mode(monkeypatch, trace_employee, trace_repo):
    """运行时断言：中间件传给 start_trace 的 mode 固定 LOCAL（P0 禁止 live）。"""
    captured: list[dict] = []
    real_start_trace = main_module.start_trace

    def _spy(**kwargs):  # noqa: ANN001 - 转发真实内核
        captured.append(dict(kwargs))
        return real_start_trace(**kwargs)

    monkeypatch.setattr(main_module, "start_trace", _spy)
    conversation_id = create_conversation(trace_employee)
    response = ask_question(trace_employee, conversation_id)
    assert response.status_code == 200, response.text

    assert len(captured) == 1
    arguments = captured[0]
    assert arguments["mode"] is TraceMode.LOCAL
    assert arguments["mode"] != TraceMode.LIVE
    assert str(arguments["mode"]) == "local"
    assert arguments["scope"] == "end_to_end"
    assert arguments["repo"] is trace_repo
    assert arguments["content_mode"] == "hash"
    assert arguments["hmac_key"] is None
    assert arguments["http_request_id"] == response.headers["X-Request-ID"]
    trace, _spans = trace_repo.get(response.headers["X-Trace-ID"])
    assert trace.mode == "local"


def test_trace_context_is_visible_inside_qa_handler(monkeypatch, trace_employee):
    """contextvars 传导：业务 handler 内 ``current_trace()`` 必须是本请求的 Trace（T003c/d 依赖）。"""
    from mktkb.conversations import service as conversations_service

    seen: list[str | None] = []
    real_ask = conversations_service.ask

    async def _spy(*args, **kwargs):  # noqa: ANN002, ANN003 - 转发真实业务实现
        active = current_trace()
        seen.append(None if active is None else active.trace_id)
        return await real_ask(*args, **kwargs)

    monkeypatch.setattr(conversations_service, "ask", _spy)
    conversation_id = create_conversation(trace_employee)
    response = ask_question(trace_employee, conversation_id)
    assert response.status_code == 200, response.text
    assert seen == [response.headers["X-Trace-ID"]]


def test_trace_content_mode_off_is_wired(trace_settings):
    """构造 Settings 打开 off 模式：落库记录的 content_mode 跟随配置。"""
    settings = trace_settings.model_copy(
        update={"trace_content_mode": "off", "trace_db_path": trace_settings.data_dir / "off-traces" / "traces.sqlite3"}
    )
    app = create_app(settings)
    try:
        session = open_session(app, "employee", "EmployeePass-1")
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        assert response.status_code == 200, response.text
        trace, spans = app.state.trace_repo.get(response.headers["X-Trace-ID"])
        assert trace.content_mode == "off"
        assert spans and {"recall", "fuse", "hard_filter"} <= {span.name for span in spans}
    finally:
        _close_app(app)


# ---- §5.3 范围只限 QA POST ----


def test_only_qa_post_gets_trace_header_and_writes_trace(trace_app, trace_employee, trace_admin, trace_db_path):
    """登录/健康检查/会话 GET、创建会话 POST、上传 POST 均无 X-Trace-ID、不写 trace。"""
    # 上传需要管理员，且必须走真实 multipart（POST /api/v1/documents）。
    assert trace_admin.upload(content=_xlsx_bytes(), name="T003b-scope.xlsx").status_code == 202

    fresh = TestClient(trace_app, raise_server_exceptions=False)
    login_response = fresh.post(
        "/api/v1/auth/login",
        json={"username": "employee", "password": "EmployeePass-1"},
        headers={"Origin": ORIGIN},
    )
    assert login_response.status_code == 200, login_response.text

    healthz = fresh.get("/api/v1/healthz")
    assert healthz.status_code == 200, healthz.text

    listing = trace_employee.client.get("/api/v1/conversations")
    assert listing.status_code == 200, listing.text

    created = trace_employee.client.post("/api/v1/conversations", json={}, headers=trace_employee.headers)
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    messages = trace_employee.client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert messages.status_code == 200, messages.text

    non_qa_responses = (
        ("登录", login_response),
        ("健康检查", healthz),
        ("会话列表 GET", listing),
        ("创建会话 POST", created),
        ("消息列表 GET", messages),
    )
    for label, response in non_qa_responses:
        assert "X-Trace-ID" not in response.headers, f"{label}不应返回 X-Trace-ID"
        assert response.headers.get("X-Request-ID"), f"{label}应保留既有 X-Request-ID"
    assert trace_rows(trace_db_path) == []

    # 正向对照：QA POST 才有 X-Trace-ID 且写一条 trace。
    qa_response = ask_question(trace_employee, conversation_id)
    assert qa_response.status_code == 200, qa_response.text
    assert qa_response.headers.get("X-Trace-ID")
    assert len(trace_rows(trace_db_path)) == 1


# ---- §5.4 写入失败不影响产品 ----


def test_monkeypatched_write_failure_keeps_qa_response(monkeypatch, caplog, trace_employee, trace_db_path):
    """仓储写入抛异常：QA POST 仍返回正常状态码与 body，日志只记错误、不泄漏给响应。"""

    def _boom(self, trace, spans):  # noqa: ANN001 - 模拟真实 write_best_effort 抛异常
        raise RuntimeError("PM-SIMULATED-TRACE-WRITE-FAILURE")

    monkeypatch.setattr(TraceRepository, "write_best_effort", _boom)
    caplog.set_level(logging.WARNING)
    conversation_id = create_conversation(trace_employee)
    response = ask_question(trace_employee, conversation_id)

    assert response.status_code == 200, response.text
    assert response.headers.get("X-Trace-ID")
    assert response.json()["kind"] == "not_found"
    _assert_no_internal_leak(response.text)
    # 内核兜底：write_best_effort 抛异常时由 tracer.finish 捕获并记 trace_finish_error。
    messages = [record.getMessage() for record in caplog.records]
    assert any("trace_finish_error" in message for message in messages), messages
    # 写入失败 → 没有留下半条 trace。
    assert trace_rows(trace_db_path) == []


def test_unwritable_trace_db_path_keeps_qa_response(monkeypatch, caplog, settings, tmp_path: Path):
    """Trace 库路径不可写：QA POST 仍 200，仓储自身日志 trace_write_error，响应无内部错误。"""
    blocker = tmp_path / "blocked-parent"
    blocker.write_text("not a directory", encoding="utf-8")
    trace_path = blocker / "qa-traces.sqlite3"
    trace_settings = settings.model_copy(
        update={"trace_enabled": True, "trace_db_path": trace_path, "trace_content_mode": "hash"}
    )
    app = create_app(trace_settings)
    caplog.set_level(logging.WARNING)
    try:
        # 构造期打不开库不崩溃（TraceRepository 延迟失败），产品侧照常可用。
        assert app.state.trace_repo is not None
        session = open_session(app, "employee", "EmployeePass-1")
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        assert response.status_code == 200, response.text
        assert response.headers.get("X-Trace-ID")
        assert response.json()["kind"] == "not_found"
        _assert_no_internal_leak(response.text)
        store_messages = [
            record.getMessage()
            for record in caplog.records
            if record.name == "mktkb.observability.store"
        ]
        assert any("trace_write_error" in message for message in store_messages), store_messages
        assert not trace_path.exists()
    finally:
        _close_app(app)


# ---- §5.5 行为不变：同一固定请求 body 归一化后完全一致 ----


def test_fixed_request_body_is_identical_with_trace_off_and_on(tmp_path: Path):
    """trace 关闭 vs 开启：状态码与归一化后的响应 body 完全一致（仅多 X-Trace-ID）。"""
    off_settings = _make_settings(tmp_path / "off-data")
    on_settings = _make_settings(tmp_path / "on-data", trace_enabled=True)
    off_app = create_app(off_settings)
    on_app = create_app(on_settings)
    frames = []
    try:
        off_session = open_session(off_app, "employee", "EmployeePass-1")
        on_session = open_session(on_app, "employee", "EmployeePass-1")
        off_conversation = create_conversation(off_session)
        on_conversation = create_conversation(on_session)
        off_response = ask_question(
            off_session, off_conversation, client_request_id=FIXED_CLIENT_REQUEST_ID
        )
        on_response = ask_question(
            on_session, on_conversation, client_request_id=FIXED_CLIENT_REQUEST_ID
        )
        assert off_response.status_code == on_response.status_code == 200
        assert "X-Trace-ID" not in off_response.headers
        assert on_response.headers.get("X-Trace-ID")
        assert _normalized(off_response.json()) == _normalized(on_response.json())
        # 请求体/字段结构未变：两个响应键集合一致，仅易变字段不同。
        assert set(off_response.json()) == set(on_response.json())
        frames.append((off_response.json(), on_response.json()))
    finally:
        _close_app(off_app)
        _close_app(on_app)
    # 归一化后确曾比较过内容（防止空比较）。
    off_payload, on_payload = frames[0]
    assert _normalized(off_payload) == _normalized(on_payload)
    assert isinstance(_normalized(off_payload), dict)


# ---- §5.6 mode 硬约束：代码里没有按 provider 模式传 live 的路径 ----


def test_middleware_source_hardcodes_local_mode_never_live():
    """静态断言：main.py 的 start_trace 调用把 mode 写死为 TraceMode.LOCAL，无 LIVE。"""
    source = Path(main_module.__file__).read_text(encoding="utf-8")
    assert "TraceMode.LIVE" not in source

    tree = ast.parse(source)
    start_trace_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "start_trace"
    ]
    assert len(start_trace_calls) == 1, "中间件应只有一处 start_trace 调用"
    keywords = {keyword.arg: keyword.value for keyword in start_trace_calls[0].keywords}
    assert "mode" in keywords, "start_trace 必须显式传入 mode"
    mode_node = keywords["mode"]
    # 只允许静态绑定：`TraceMode.LOCAL`、字符串 "local"，或引用一个模块级常量，
    # 且该常量自身静态绑定 `TraceMode.LOCAL`；不允许变量/条件表达式/函数返回值。
    if isinstance(mode_node, ast.Name):
        bound = _module_constant(tree, mode_node.id)
        assert isinstance(bound, ast.Attribute), f"常量 {mode_node.id} 必须静态绑定 TraceMode"
        assert bound.attr == "LOCAL", f"常量 {mode_node.id} 必须绑定 TraceMode.LOCAL"
        assert isinstance(bound.value, ast.Name) and bound.value.id == "TraceMode"
    elif isinstance(mode_node, ast.Attribute):
        assert mode_node.attr == "LOCAL"
        assert isinstance(mode_node.value, ast.Name) and mode_node.value.id == "TraceMode"
    elif isinstance(mode_node, ast.Constant):
        assert mode_node.value == "local"
    else:  # pragma: no cover - 防御未来改成动态模式
        raise AssertionError(f"start_trace 的 mode 必须是静态常量，实际为 {ast.dump(mode_node)}")
    # 全文件不得引用 LIVE 枚举成员。
    assert all(
        not (isinstance(node, ast.Attribute) and node.attr == "LIVE")
        for node in ast.walk(tree)
    )


# ---- §5.7 配置安全：默认值、内容模式白名单、SecretStr、不泄漏 ----


def test_trace_enabled_accepts_env_flag(monkeypatch, tmp_path: Path):
    """``MKTKB_TRACE_ENABLED=1`` 是本地 P0 的开启方式（计划 Task 3 Interfaces）。"""
    monkeypatch.setenv("MKTKB_TRACE_ENABLED", "1")
    assert _make_settings(tmp_path / "env-on").trace_enabled is True

    monkeypatch.setenv("MKTKB_TRACE_ENABLED", "0")
    assert _make_settings(tmp_path / "env-off").trace_enabled is False


def test_trace_content_mode_accepts_only_off_and_hash(tmp_path: Path):
    """P0 只允许 off/hash；redacted/full 显式拒绝（设计 §6.5）。"""
    assert _make_settings(tmp_path / "hash-mode", trace_content_mode="hash").trace_content_mode == "hash"
    assert _make_settings(tmp_path / "off-mode", trace_content_mode="off").trace_content_mode == "off"
    # 大小写/空白为部署友好归一化，不改变白名单。
    assert _make_settings(tmp_path / "upper-mode", trace_content_mode=" HASH ").trace_content_mode == "hash"
    for rejected in ("redacted", "full", "sampled", ""):
        with pytest.raises(ValidationError) as excinfo:
            _make_settings(tmp_path / f"bad-{rejected or 'empty'}", trace_content_mode=rejected)
        message = str(excinfo.value)
        assert "off" in message and "hash" in message


def test_trace_hmac_key_is_secret_and_never_serialized(tmp_path: Path):
    """HMAC key 用 SecretStr：repr/JSON 均显示掩码，只能显式取值；空值归一为 None。"""
    settings = _make_settings(tmp_path / "secret", trace_hmac_key=FAKE_HMAC_KEY)
    assert isinstance(settings.trace_hmac_key, SecretStr)
    assert settings.trace_hmac_key.get_secret_value() == FAKE_HMAC_KEY
    assert settings.trace_hmac_key_bytes == FAKE_HMAC_KEY.encode("utf-8")
    for rendered in (repr(settings), str(settings), repr(settings.trace_hmac_key), settings.model_dump_json()):
        assert FAKE_HMAC_KEY not in rendered
    assert "**********" in repr(settings.trace_hmac_key)

    blank = _make_settings(tmp_path / "blank", trace_hmac_key="   ")
    assert blank.trace_hmac_key is None
    assert blank.trace_hmac_key_bytes is None


def test_invalid_trace_config_error_does_not_echo_hmac_key(tmp_path: Path):
    """配置校验失败时异常文本不回显任何密钥（全局 hide_input_in_errors）。"""
    with pytest.raises(ValidationError) as excinfo:
        _make_settings(tmp_path / "leak", trace_hmac_key=FAKE_HMAC_KEY, trace_content_mode="full")
    message = str(excinfo.value)
    assert FAKE_HMAC_KEY not in message
    assert "full" in message or "redacted" in message


def test_trace_hmac_key_from_env_is_secret(monkeypatch, tmp_path: Path):
    """``MKTKB_TRACE_HMAC_KEY`` 以 SecretStr 载入，可显式取字节但不进入 repr/JSON。"""
    monkeypatch.setenv("MKTKB_TRACE_HMAC_KEY", FAKE_HMAC_KEY)
    settings = _make_settings(tmp_path / "env-hmac")
    assert isinstance(settings.trace_hmac_key, SecretStr)
    assert settings.trace_hmac_key_bytes == FAKE_HMAC_KEY.encode("utf-8")
    assert FAKE_HMAC_KEY not in repr(settings)
    assert FAKE_HMAC_KEY not in settings.model_dump_json()


def test_trace_db_path_resolution_and_blank_normalization(settings, tmp_path: Path):
    """默认独立库路径；显式路径优先；空白路径归一为 None（回落到默认）。"""
    assert settings.resolved_trace_db_path == settings.data_dir / "observability" / "qa-traces.sqlite3"
    explicit = tmp_path / "custom" / "traces.sqlite3"
    custom = settings.model_copy(update={"trace_db_path": explicit})
    assert custom.resolved_trace_db_path == explicit
    blank = _make_settings(tmp_path / "blank-db", trace_db_path="   ")
    assert blank.trace_db_path is None
    assert blank.resolved_trace_db_path == blank.data_dir / "observability" / "qa-traces.sqlite3"


# ---- 生命周期：开启时仓储随应用关闭 ----


def test_lifespan_closes_trace_repo(trace_settings):
    """``create_app`` 的 lifespan 退出时必须关闭 Trace 仓储（不留 SQLite 连接）。"""
    app = create_app(trace_settings)
    repo = app.state.trace_repo
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/healthz").status_code == 200
        with pytest.raises(TraceWriteError):
            repo.get("after-lifespan")
    finally:
        app.state.db.dispose()
