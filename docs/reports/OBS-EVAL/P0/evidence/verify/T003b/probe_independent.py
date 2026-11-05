"""T003b 独立验收探针（独立编写，不引用开发测试）。

只读目标仓库源码（sys.path 指向 backend/src），不改仓库任何文件：
- 全部临时目录使用 tempfile.mkdtemp()，不写 var/、docs/evidence/；
- 不读 .env（Settings(_env_file=None)）；
- 不发起真实网络请求（P9 段用 socket 守卫证明 QA 路径零外部网络）；
- 覆盖 handoff §5.1–§5.7 与 §10 兼容性，独立复算而非调用 test_middleware.py。

输出：PASS/FAIL 列表 + 末尾 JSON 摘要。退出码 0 表示全部 PASS。
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import sqlite3
import sys
import tempfile
import unittest.mock
import uuid
from pathlib import Path
from types import SimpleNamespace

REPO = Path(r"D:\GPT项目\市场部AI知识库")
SRC = REPO / "backend" / "src"
sys.path.insert(0, str(SRC))

import mktkb  # noqa: E402

MSG_PY = str(mktkb.__file__)
ASSERT_OK = str(SRC) in MSG_PY

from fastapi.testclient import TestClient  # noqa: E402
from pydantic import SecretStr, ValidationError  # noqa: E402

from mktkb.config import Settings  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from mktkb.observability import TraceMode  # noqa: E402
from mktkb.observability.store import TraceRepository  # noqa: E402

ORIGIN = "http://testserver"
FIXED_QUESTION = "城东店的宣传海报在哪里？"
FIXED_CLIENT_REQUEST_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
FAKE_HMAC_KEY = "pm-verify-hmac-key-0123456789abcdef"
VOLATILE_KEYS = frozenset({"request_id", "message_id", "conversation_id", "created_at", "updated_at"})

RESULTS: list[dict] = []
LOGLINES: list[str] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    RESULTS.append({"probe": name, "status": status, "detail": detail})
    line = f"{status} {name}" + (f" :: {detail}" if detail else "")
    print(line, flush=True)
    LOGLINES.append(line)


def check(name: str, condition: bool, detail: str = "") -> None:
    rec(name, bool(condition), detail if not condition else "")


def tmpdir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"t003b-verify-{prefix}-"))


def make_settings(data_dir: Path, **overrides: object) -> Settings:
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


def close_app(app) -> None:
    repo = getattr(app.state, "trace_repo", None)
    if repo is not None:
        repo.close()
    qa = getattr(app.state, "qa", None)
    if qa is not None:
        qa.close()
    app.state.db.dispose()


def open_session(app, username: str = "employee", password: str = "EmployeePass-1") -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    csrf = me.json()["csrf_token"]
    return SimpleNamespace(
        client=client,
        csrf=csrf,
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        login_response=response,
    )


def create_conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask_question(session: SimpleNamespace, conversation_id: str, *, client_request_id: uuid.UUID | None = None):
    return session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "client_request_id": str(client_request_id or uuid.uuid4()),
            "question": FIXED_QUESTION,
        },
        headers=session.headers,
    )


def read_trace_rows(db_path: Path) -> list[tuple]:
    path = Path(db_path)
    if not path.exists():
        return []
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT trace_id, request_id, http_request_id, mode, scope, path, "
            "content_mode, outcome_kind, status, replayed FROM traces ORDER BY rowid ASC"
        ).fetchall()
    finally:
        connection.close()


def normalize(payload: object) -> object:
    if isinstance(payload, dict):
        return {k: normalize(v) for k, v in payload.items() if k not in VOLATILE_KEYS}
    if isinstance(payload, list):
        return [normalize(item) for item in payload]
    return payload


def collect_logs() -> tuple[list[logging.LogRecord], logging.Handler]:
    records: list[logging.LogRecord] = []

    class Captor(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
            records.append(record)

    handler = Captor()
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    return records, handler


def xlsx_bytes() -> bytes:
    import io

    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.active.append(["门店", "位置"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------- §5.1


def probe_default_off() -> None:
    print("\n== P1 默认关闭：零副作用 ==", flush=True)
    root = tmpdir("p1")
    settings = make_settings(root / "data")
    check("P1.settings.trace_enabled 默认 False", settings.trace_enabled is False)
    check("P1.settings.trace_db_path 默认 None", settings.trace_db_path is None)
    check("P1.settings.trace_content_mode 默认 hash", settings.trace_content_mode == "hash")
    check("P1.settings.trace_hmac_key 默认 None", settings.trace_hmac_key is None)
    expected_default = root / "data" / "observability" / "qa-traces.sqlite3"
    check("P1.resolved_trace_db_path 默认 <data_dir>/observability/qa-traces.sqlite3",
          settings.resolved_trace_db_path == expected_default,
          str(settings.resolved_trace_db_path))

    app = create_app(settings)
    try:
        check("P1.app.state.trace_repo is None", app.state.trace_repo is None)
        session = open_session(app)
        check("P1.login 响应无 X-Trace-ID", "x-trace-id" not in session.login_response.headers)
        check("P1.login 响应有 X-Request-ID", bool(session.login_response.headers.get("X-Request-ID")))
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        check("P1.QA POST 状态码 200", response.status_code == 200, str(response.status_code))
        check("P1.QA POST 响应无 X-Trace-ID", "x-trace-id" not in response.headers)
        request_id = response.headers.get("X-Request-ID")
        check("P1.QA POST 有 X-Request-ID", bool(request_id))
        check("P1.X-Request-ID 是 UUID 形态", bool(request_id) and len(request_id) == 36 and uuid.UUID(request_id) is not None)
        check("P1.QA POST body 正常(kind)", response.json().get("kind") == "not_found", json.dumps(response.json(), ensure_ascii=False)[:200])
        check("P1.未创建 observability 目录", not (root / "data" / "observability").exists())
        check("P1.未创建 Trace DB 文件", not expected_default.exists())
        db_files = list((root / "data").rglob("*.sqlite3")) if (root / "data").exists() else []
        names = sorted(str(p.relative_to(root / "data")) for p in db_files)
        check("P1.data 目录下仅业务 DB，无 qa-traces", all("qa-traces" not in n for n in names), str(names))
        health = session.client.get("/api/v1/healthz")
        check("P1.GET /healthz 无 X-Trace-ID", "x-trace-id" not in health.headers)
        check("P1.GET /healthz 有 X-Request-ID", bool(health.headers.get("X-Request-ID")))
    finally:
        close_app(app)


# ---------------------------------------------------------------- §5.2


def probe_enabled() -> None:
    print("\n== P2 开启后：X-Trace-ID + 落一条 trace ==", flush=True)
    root = tmpdir("p2")
    db_path = root / "obs" / "qa-traces.sqlite3"
    settings = make_settings(root / "data", trace_enabled=True, trace_db_path=db_path)
    app = create_app(settings)
    try:
        check("P2.create_app 创建 trace_repo", isinstance(app.state.trace_repo, TraceRepository))
        check("P2.Trace DB 文件在配置路径", db_path.exists())
        session = open_session(app)
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        check("P2.QA POST 状态码 200", response.status_code == 200, str(response.status_code))
        trace_id = response.headers.get("X-Trace-ID")
        check("P2.响应有 X-Trace-ID", bool(trace_id))
        uuid_ok = False
        try:
            uuid.UUID(trace_id)
            uuid_ok = re.fullmatch(r"[0-9a-fA-F-]{32,36}", trace_id or "") is not None
        except (ValueError, TypeError):
            uuid_ok = False
        check("P2.X-Trace-ID 为合法 UUID 形态", uuid_ok, str(trace_id))
        http_request_id = response.headers.get("X-Request-ID")
        check("P2.响应有 X-Request-ID", bool(http_request_id))
        trace, spans = app.state.trace_repo.get(trace_id)
        fields = {
            "trace_id": trace.trace_id,
            "request_id": trace.request_id,
            "http_request_id": trace.http_request_id,
            "mode": trace.mode,
            "scope": trace.scope,
            "path": trace.path,
            "content_mode": trace.content_mode,
            "outcome_kind": trace.outcome_kind,
            "status": trace.status,
            "replayed": trace.replayed,
            "attempt": trace.attempt,
            "question_hash": trace.question_hash,
            "span_count": len(spans),
        }
        print("P2.trace fields = " + json.dumps(fields, ensure_ascii=False, default=str), flush=True)
        check("P2.trace_id 与响应头一致", trace.trace_id == trace_id)
        check("P2.http_request_id == X-Request-ID", trace.http_request_id == http_request_id)
        check("P2.mode == local", trace.mode == "local", str(trace.mode))
        check("P2.scope == end_to_end", trace.scope == "end_to_end", str(trace.scope))
        check("P2.content_mode == hash", trace.content_mode == "hash", str(trace.content_mode))
        check("P2.replayed is False", trace.replayed is False)
        check("P2.attempt == 1", trace.attempt == 1)
        check("P2.spans 为空（T003b 不埋业务 Span，预期）", spans == [])
        check("P2.request_id 为 None（T003c/d 前预期边界）", trace.request_id is None)
        check("P2.question_hash 为 None（未 set_question，预期）", trace.question_hash is None)
        check("P2.outcome_kind 为 None（未埋 outcome，预期）", trace.outcome_kind is None)
        check("P2.status == incomplete（T003c/d 前预期）", trace.status == "incomplete", str(trace.status))
        check("P2.path 记录值（内核默认）", True, f"实际 path={trace.path!r}（报告声称默认 RAG，独立观察）")
        rows = read_trace_rows(db_path)
        check("P2.恰写 1 行 trace", len(rows) == 1, str(len(rows)))
        check("P2.记录字段复核(mode/scope/path/status)",
              len(rows) == 1 and rows[0][3] == "local" and rows[0][4] == "end_to_end" and rows[0][8] == "incomplete",
              str(rows))

        second = ask_question(session, conversation_id)
        second_id = second.headers.get("X-Trace-ID")
        check("P2.第二次 QA POST 不同 trace_id", second.status_code == 200 and second_id != trace_id)
        rows = read_trace_rows(db_path)
        check("P2.两次 QA POST 共 2 行", len(rows) == 2, str(len(rows)))
        check("P2.两行 trace_id 集合正确", {row[0] for row in rows} == {trace_id, second_id})
    finally:
        close_app(app)

    # 默认路径（不显式给 trace_db_path）也必须落 <data_dir>/observability/qa-traces.sqlite3
    root2 = tmpdir("p2b")
    settings2 = make_settings(root2 / "data", trace_enabled=True)
    app2 = create_app(settings2)
    try:
        default_db = root2 / "data" / "observability" / "qa-traces.sqlite3"
        check("P2b.开启且未显式路径时创建默认 Trace DB", default_db.exists(), str(default_db))
        session = open_session(app2)
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        check("P2b.默认路径下 QA POST 200 且有头", response.status_code == 200 and bool(response.headers.get("X-Trace-ID")))
        rows = read_trace_rows(default_db)
        check("P2b.默认路径库中 1 行", len(rows) == 1, str(len(rows)))
    finally:
        close_app(app2)

    # content_mode=off 跟随配置
    root3 = tmpdir("p2c")
    db3 = root3 / "obs" / "traces.sqlite3"
    settings3 = make_settings(root3 / "data", trace_enabled=True, trace_db_path=db3, trace_content_mode="off")
    app3 = create_app(settings3)
    try:
        session = open_session(app3)
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        trace3, spans3 = app3.state.trace_repo.get(response.headers["X-Trace-ID"])
        check("P2c.content_mode=off 配置生效", trace3.content_mode == "off", str(trace3.content_mode))
        check("P2c.off 模式下 spans 仍空", spans3 == [])
    finally:
        close_app(app3)

    # HMAC key：不泄漏到响应/库文件/记录
    root4 = tmpdir("p2d")
    db4 = root4 / "obs" / "traces.sqlite3"
    settings4 = make_settings(
        root4 / "data", trace_enabled=True, trace_db_path=db4, trace_hmac_key=FAKE_HMAC_KEY
    )
    app4 = create_app(settings4)
    try:
        session = open_session(app4)
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        blob = b""
        for candidate in (db4, Path(str(db4) + "-wal"), Path(str(db4) + "-shm")):
            if candidate.exists():
                blob += candidate.read_bytes()
        trace4, _ = app4.state.trace_repo.get(response.headers["X-Trace-ID"])
        rec_text = json.dumps(trace4.__dict__, ensure_ascii=False, default=str)
        check("P2d.HMAC key 不在响应文本中", FAKE_HMAC_KEY not in response.text)
        check("P2d.HMAC key 不在响应头中", all(FAKE_HMAC_KEY not in str(v) for v in response.headers.values()))
        check("P2d.HMAC key 不在 Trace DB 字节中", FAKE_HMAC_KEY.encode() not in blob)
        check("P2d.HMAC key 不在 Trace 记录中", FAKE_HMAC_KEY not in rec_text)
    finally:
        close_app(app4)


# ---------------------------------------------------------------- §5.3


def route_probe_path(template: str) -> str:
    return re.sub(r"\{[^}]+\}", "probe-id", template)


def probe_scope_only_qa_post() -> None:
    print("\n== P3 范围只限 QA POST ==", flush=True)
    root = tmpdir("p3")
    db_path = root / "obs" / "traces.sqlite3"
    settings = make_settings(root / "data", trace_enabled=True, trace_db_path=db_path)
    app = create_app(settings)
    try:
        raw = TestClient(app, raise_server_exceptions=False)
        # 该 FastAPI 版本把 include_router 保存为 _IncludedRouter（app.routes 不展开），
        # 因此从 OpenAPI 规范枚举真实端点（与路由树同源）。
        api_routes = []
        qa_path = "/api/v1/conversations/{conversation_id}/messages"
        spec = app.openapi()
        for template, operations in spec.get("paths", {}).items():
            if not template.startswith("/api/v1"):
                continue
            for method in operations:
                upper = method.upper()
                if upper in {"HEAD", "OPTIONS", "PARAMETERS"}:
                    continue
                api_routes.append((upper, template))
        check("P3.OpenAPI 枚举到 >=20 个 /api/v1 端点方法", len(api_routes) >= 20, f"count={len(api_routes)}")
        checked = 0
        header_leaks: list[str] = []
        for method, template in api_routes:
            if method == "POST" and template == qa_path:
                continue  # QA POST 由正对照覆盖
            url = route_probe_path(template)
            response = raw.request(method, url)
            checked += 1
            if "X-Trace-ID" in response.headers or "x-trace-id" in response.headers:
                header_leaks.append(f"{method} {url} -> {response.status_code}")
            if "X-Request-ID" not in response.headers:
                header_leaks.append(f"{method} {url} 缺 X-Request-ID")
        check(f"P3.枚举非 QA POST 路由全部无 X-Trace-ID（{checked} 条）", not header_leaks, str(header_leaks))
        check("P3.枚举后 Trace 库 0 行", read_trace_rows(db_path) == [])

        # 已登录的非 QA 端点为对照（含上传 POST、会话 CRUD）
        employee = open_session(app)
        admin = open_session(app, "admin", "AdminPass-1")
        conversation_id = create_conversation(employee)
        responses = {
            "GET /conversations": employee.client.get("/api/v1/conversations"),
            "GET /conversations/{id}/messages": employee.client.get(
                f"/api/v1/conversations/{conversation_id}/messages"
            ),
            "POST /documents(upload)": admin.client.post(
                "/api/v1/documents",
                files={"file": ("T003b-scope.xlsx", xlsx_bytes(), "application/octet-stream")},
                headers=admin.headers,
            ),
            "POST /auth/logout": admin.client.post("/api/v1/auth/logout", headers=admin.headers),
        }
        bad = [label for label, resp in responses.items() if "x-trace-id" in resp.headers]
        check("P3.已登录非 QA 端点无 X-Trace-ID", not bad, str(bad))
        check("P3.已登录非 QA 请求后 Trace 库 0 行", read_trace_rows(db_path) == [], str(read_trace_rows(db_path)))

        # 边界变体：尾斜杠 / 多段路径 / GET 同路径 —— 都不应开启 trace
        variants = [
            ("POST", "/api/v1/conversations/probe-id/messages/"),
            ("POST", "/api/v1/conversations/probe-id/messages/extra"),
            ("GET", "/api/v1/conversations/probe-id/messages"),
            ("POST", "/api/v1/other/messages"),
            ("POST", "/api/v1/conversations/probe-id/messagesx"),
        ]
        variant_bad = []
        # 不许自动跟随 307 重定向：尾斜杠变体应停在重定向响应上（中间件尚未启动 trace）
        variant_client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        for method, url in variants:
            response = variant_client.request(method, url)
            if "x-trace-id" in response.headers:
                variant_bad.append(f"{method} {url} -> {response.status_code}")
        check("P3.非精确匹配变体无 X-Trace-ID", not variant_bad, str(variant_bad))
        check("P3.变体请求后 Trace 库 0 行", read_trace_rows(db_path) == [])

        # 端点内失败（未登录 QA POST）仍属 QA 端点：记录实际行为（报告 §4.3 的偏离）
        unauth_qa = raw.post(
            qa_path.replace("{conversation_id}", "probe-id"),
            json={"client_request_id": str(uuid.uuid4()), "question": "x"},
            headers={"Origin": ORIGIN},
        )
        check("P3.未登录 QA POST 仍返回 X-Trace-ID（端点级观测的已知行为）",
              "x-trace-id" in unauth_qa.headers,
              f"status={unauth_qa.status_code} trace_header={unauth_qa.headers.get('X-Trace-ID')}")
        rows_after_fail = read_trace_rows(db_path)
        check("P3.端点内失败也会写 1 条 incomplete trace（报告 §4.3 偏离属实）",
              len(rows_after_fail) == 1 and rows_after_fail[0][8] == "incomplete",
              str(rows_after_fail))

        # 正向对照
        qa_response = ask_question(employee, conversation_id)
        check("P3.正常 QA POST 有 X-Trace-ID", qa_response.status_code == 200 and bool(qa_response.headers.get("X-Trace-ID")))
        check("P3.正常 QA POST 后共 2 行", len(read_trace_rows(db_path)) == 2, str(len(read_trace_rows(db_path))))
    finally:
        close_app(app)


# ---------------------------------------------------------------- §5.4


def probe_write_failure() -> None:
    print("\n== P4 写入失败不影响产品 ==", flush=True)
    # 4a：monkeypatch write_best_effort 抛异常
    root = tmpdir("p4a")
    db_path = root / "obs" / "traces.sqlite3"
    settings = make_settings(root / "data", trace_enabled=True, trace_db_path=db_path)
    app = create_app(settings)
    records, handler = collect_logs()
    try:
        session = open_session(app)
        conversation_id = create_conversation(session)
        fail_detail = {"error": "boom"}

        def _boom(self, trace, spans):
            raise RuntimeError("VERIFY-SIMULATED-WRITE-FAILURE")

        with unittest.mock.patch.object(TraceRepository, "write_best_effort", _boom):
            response = ask_question(session, conversation_id)
        messages = [record.getMessage() for record in records]
        check("P4a.写入抛异常时 QA POST 仍 200", response.status_code == 200, str(response.status_code))
        check("P4a.响应仍有 X-Trace-ID", bool(response.headers.get("X-Trace-ID")))
        check("P4a.body 正常(kind=not_found)", response.json().get("kind") == "not_found",
              json.dumps(response.json(), ensure_ascii=False)[:200])
        leak_markers = ["trace_write_error", "TraceWriteError", "RuntimeError", "Traceback", "sqlite", "VERIFY-SIMULATED"]
        leaks = [marker for marker in leak_markers if marker in response.text]
        check("P4a.响应不泄漏内部错误", not leaks, str(leaks))
        check("P4a.日志命中内核兜底 trace_finish_error",
              any("trace_finish_error" in message for message in messages),
              str([m for m in messages if "trace" in m.lower()]))
        check("P4a.无半条 trace 落库", read_trace_rows(db_path) == [])
    finally:
        logging.getLogger().removeHandler(handler)
        close_app(app)

    # 4b：trace_db_path 不可写（父路径是普通文件）
    root2 = tmpdir("p4b")
    blocker = root2 / "blocked-parent"
    blocker.write_text("not a directory", encoding="utf-8")
    unwritable = blocker / "qa-traces.sqlite3"
    settings2 = make_settings(root2 / "data", trace_enabled=True, trace_db_path=unwritable)
    created_ok = True
    app2 = None
    try:
        app2 = create_app(settings2)
    except Exception as exc:  # noqa: BLE001
        created_ok = False
        rec("P4b.create_app 在不可写 Trace 路径下不崩溃", False, f"{type(exc).__name__}: {exc}")
    if app2 is not None:
        records2, handler2 = collect_logs()
        try:
            rec("P4b.create_app 在不可写 Trace 路径下不崩溃", created_ok)
            session = open_session(app2)
            conversation_id = create_conversation(session)
            response = ask_question(session, conversation_id)
            messages = [record.getMessage() for record in records2]
            check("P4b.不可写路径下 QA POST 仍 200", response.status_code == 200, str(response.status_code))
            check("P4b.响应有 X-Trace-ID", bool(response.headers.get("X-Trace-ID")))
            check("P4b.body 正常", response.json().get("kind") == "not_found")
            leaks = [m for m in ("trace_write_error", "TraceWriteError", "Traceback", "sqlite") if m in response.text]
            check("P4b.响应不泄漏内部错误", not leaks, str(leaks))
            check("P4b.仓储日志命中 trace_write_error",
                  any("trace_write_error" in message for message in messages),
                  str([m for m in messages if "trace" in m.lower()]))
            check("P4b.未创建 Trace DB", not unwritable.exists())
        finally:
            logging.getLogger().removeHandler(handler2)
            close_app(app2)


# ---------------------------------------------------------------- §5.5


def probe_body_equality() -> None:
    print("\n== P5 行为不变：off/on body 归一化一致 ==", flush=True)
    root = tmpdir("p5")
    off_settings = make_settings(root / "off-data")
    on_settings = make_settings(root / "on-data", trace_enabled=True)
    off_app = create_app(off_settings)
    on_app = create_app(on_settings)
    try:
        off_session = open_session(off_app)
        on_session = open_session(on_app)
        off_cid = create_conversation(off_session)
        on_cid = create_conversation(on_session)
        off_response = ask_question(off_session, off_cid, client_request_id=FIXED_CLIENT_REQUEST_ID)
        on_response = ask_question(on_session, on_cid, client_request_id=FIXED_CLIENT_REQUEST_ID)
        off_body = off_response.json()
        on_body = on_response.json()
        print("P5.off body = " + json.dumps(off_body, ensure_ascii=False)[:800], flush=True)
        print("P5.on  body = " + json.dumps(on_body, ensure_ascii=False)[:800], flush=True)
        check("P5.两设置状态码一致且为 200", off_response.status_code == on_response.status_code == 200,
              f"{off_response.status_code}/{on_response.status_code}")
        check("P5.off 无 X-Trace-ID", "x-trace-id" not in off_response.headers)
        check("P5.on 有 X-Trace-ID", bool(on_response.headers.get("X-Trace-ID")))
        check("P5.归一化后 body 完全一致", normalize(off_body) == normalize(on_body),
              json.dumps({"off": normalize(off_body), "on": normalize(on_body)}, ensure_ascii=False)[:800])
        check("P5.响应键集合一致", set(off_body) == set(on_body), f"{sorted(set(off_body))} vs {sorted(set(on_body))}")
        check("P5.归一化比较非空（防空比较）", isinstance(normalize(off_body), dict) and len(normalize(off_body)) > 0,
              str(normalize(off_body)))
        check("P5.两边都有既有 X-Request-ID",
              bool(off_response.headers.get("X-Request-ID")) and bool(on_response.headers.get("X-Request-ID")))
    finally:
        close_app(off_app)
        close_app(on_app)


# ---------------------------------------------------------------- §5.7


def probe_config() -> None:
    print("\n== P6 配置安全 ==", flush=True)
    for key in (
        "MKTKB_TRACE_ENABLED",
        "MKTKB_TRACE_DB_PATH",
        "MKTKB_TRACE_CONTENT_MODE",
        "MKTKB_TRACE_HMAC_KEY",
    ):
        os.environ.pop(key, None)
    root = tmpdir("p6")

    default_settings = make_settings(root / "default", )
    check("P6.默认 trace_enabled=False", default_settings.trace_enabled is False)
    check("P6.默认 trace_db_path=None", default_settings.trace_db_path is None)
    check("P6.默认 trace_content_mode=hash", default_settings.trace_content_mode == "hash")
    check("P6.默认 trace_hmac_key=None", default_settings.trace_hmac_key is None)
    check("P6.默认 resolved_trace_db_path",
          default_settings.resolved_trace_db_path == root / "default" / "observability" / "qa-traces.sqlite3",
          str(default_settings.resolved_trace_db_path))
    check("P6.无 key 时 trace_hmac_key_bytes=None", default_settings.trace_hmac_key_bytes is None)

    # 既有 Settings 构造不被破坏（仅旧字段，不传任何 trace 字段）
    old_only = Settings(
        _env_file=None,
        data_dir=root / "old-only",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
    )
    check("P6.仅旧字段构造 Settings 成功且 trace 默认关闭",
          old_only.trace_enabled is False and old_only.trace_content_mode == "hash")

    for mode in ("off", "hash", " HASH ", "Off"):
        try:
            ok = make_settings(root / f"mode-{mode.strip()}", trace_content_mode=mode).trace_content_mode in {"off", "hash"}
        except Exception:  # noqa: BLE001
            ok = False
        check(f"P6.trace_content_mode 接受 {mode!r}", ok)
    rejected = ("redacted", "full", "sampled", "", "live")
    for mode in rejected:
        rejected_ok = False
        message = ""
        try:
            make_settings(root / f"bad-{mode or 'empty'}", trace_content_mode=mode)
        except (ValidationError, ValueError) as exc:
            message = str(exc)
            rejected_ok = True
        check(f"P6.trace_content_mode 拒绝 {mode!r} 且信息含 off/hash",
              rejected_ok and "off" in message and "hash" in message, message[:160])

    secret_settings = make_settings(root / "secret", trace_hmac_key=FAKE_HMAC_KEY)
    check("P6.HMAC key 是 SecretStr", isinstance(secret_settings.trace_hmac_key, SecretStr))
    check("P6.HMAC key 可显式取原文", secret_settings.trace_hmac_key.get_secret_value() == FAKE_HMAC_KEY)
    check("P6.HMAC key bytes 正确", secret_settings.trace_hmac_key_bytes == FAKE_HMAC_KEY.encode())
    rendered = [repr(secret_settings), str(secret_settings), repr(secret_settings.trace_hmac_key),
                secret_settings.model_dump_json()]
    check("P6.HMAC key 不出现在 repr/str/JSON", all(FAKE_HMAC_KEY not in text for text in rendered))
    check("P6.HMAC key 渲染为掩码", "**********" in repr(secret_settings.trace_hmac_key))

    leak_message = ""
    try:
        make_settings(root / "leak", trace_hmac_key=FAKE_HMAC_KEY, trace_content_mode="full")
    except ValidationError as exc:
        leak_message = str(exc)
    check("P6.配置校验异常不回显 HMAC key", leak_message != "" and FAKE_HMAC_KEY not in leak_message)

    blank = make_settings(root / "blank", trace_hmac_key="   ", trace_db_path="   ")
    check("P6.空白 HMAC key 归一 None", blank.trace_hmac_key is None and blank.trace_hmac_key_bytes is None)
    check("P6.空白 trace_db_path 归一 None 且回落默认",
          blank.trace_db_path is None
          and blank.resolved_trace_db_path == root / "blank" / "observability" / "qa-traces.sqlite3")
    explicit = root / "custom" / "traces.sqlite3"
    explicit_settings = make_settings(root / "explicit", trace_db_path=str(explicit))
    check("P6.显式 trace_db_path 优先", explicit_settings.resolved_trace_db_path == explicit)

    # 环境变量载入
    os.environ["MKTKB_TRACE_ENABLED"] = "1"
    os.environ["MKTKB_TRACE_HMAC_KEY"] = FAKE_HMAC_KEY
    os.environ["MKTKB_TRACE_DB_PATH"] = str(root / "env-db" / "t.sqlite3")
    os.environ["MKTKB_TRACE_CONTENT_MODE"] = "off"
    try:
        env_settings = make_settings(root / "env")
    finally:
        for key in (
            "MKTKB_TRACE_ENABLED",
            "MKTKB_TRACE_HMAC_KEY",
            "MKTKB_TRACE_DB_PATH",
            "MKTKB_TRACE_CONTENT_MODE",
        ):
            os.environ.pop(key, None)
    check("P6.MKTKB_TRACE_ENABLED=1 生效", env_settings.trace_enabled is True)
    check("P6.MKTKB_TRACE_HMAC_KEY 载入为 SecretStr", isinstance(env_settings.trace_hmac_key, SecretStr))
    check("P6.MKTKB_TRACE_HMAC_KEY repr/JSON 不泄漏",
          FAKE_HMAC_KEY not in repr(env_settings) and FAKE_HMAC_KEY not in env_settings.model_dump_json())
    check("P6.MKTKB_TRACE_DB_PATH 生效", env_settings.resolved_trace_db_path == root / "env-db" / "t.sqlite3")
    check("P6.MKTKB_TRACE_CONTENT_MODE=off 生效", env_settings.trace_content_mode == "off")

    # 代码里不存在能传 trace mode=live 的配置入口
    trace_mode_fields = [
        name for name in Settings.model_fields
        if name == "trace_mode" or name.endswith("_trace_mode")
    ]
    check("P6.Settings 无 trace_mode 字段（无 live 配置入口）", trace_mode_fields == [], str(trace_mode_fields))


# ---------------------------------------------------------------- §5.6


def probe_mode_static_and_runtime() -> None:
    print("\n== P7 mode 硬约束 ==", flush=True)
    import ast

    main_source = (SRC / "mktkb" / "main.py").read_text(encoding="utf-8")
    check("P7.main.py 无 TraceMode.LIVE 文本", "TraceMode.LIVE" not in main_source)
    tree = ast.parse(main_source)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id == "start_trace")
             or (isinstance(node.func, ast.Attribute) and node.func.attr == "start_trace"))
    ]
    check("P7.main.py 仅一处 start_trace 调用", len(calls) == 1, f"count={len(calls)}")
    mode_ok = False
    mode_desc = ""
    if calls:
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        mode_node = keywords.get("mode")
        mode_desc = ast.dump(mode_node) if mode_node is not None else "MISSING"
        if isinstance(mode_node, ast.Name):
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == mode_node.id for target in node.targets
                ):
                    value = node.value
                    mode_ok = (
                        isinstance(value, ast.Attribute)
                        and value.attr == "LOCAL"
                        and isinstance(value.value, ast.Name)
                        and value.value.id == "TraceMode"
                    )
    check("P7.start_trace mode 静态绑定 TraceMode.LOCAL", mode_ok, mode_desc)
    live_attrs = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "LIVE"
    ]
    check("P7.main.py AST 无 LIVE 属性引用", live_attrs == [], str(live_attrs))

    # 全仓库 src 内 TraceMode.LIVE 只能出现在契约定义处
    live_sites = []
    for path in (SRC / "mktkb").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "TraceMode.LIVE" in line:
                live_sites.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    check("P7.全 src 无 TraceMode.LIVE 使用点（仅契约定义不存在该文本）", live_sites == [], str(live_sites))

    # 运行时 spy
    root = tmpdir("p7")
    db_path = root / "obs" / "traces.sqlite3"
    settings = make_settings(root / "data", trace_enabled=True, trace_db_path=db_path)
    app = create_app(settings)
    try:
        import mktkb.main as main_module

        captured: list[dict] = []
        real_start_trace = main_module.start_trace

        def _spy(**kwargs):
            captured.append(dict(kwargs))
            return real_start_trace(**kwargs)

        session = open_session(app)
        conversation_id = create_conversation(session)
        with unittest.mock.patch.object(main_module, "start_trace", _spy):
            response = ask_question(session, conversation_id)
        check("P7.中间件恰好调用 1 次 start_trace", len(captured) == 1, f"count={len(captured)}")
        if captured:
            args = captured[0]
            check("P7.运行时 mode is TraceMode.LOCAL", args.get("mode") is TraceMode.LOCAL, str(args.get("mode")))
            check("P7.运行时 mode != TraceMode.LIVE", args.get("mode") != TraceMode.LIVE)
            check("P7.运行时 mode 字符串为 local", str(args.get("mode")) == "local")
            check("P7.运行时 scope=end_to_end", args.get("scope") == "end_to_end")
            check("P7.运行时 content_mode=hash", args.get("content_mode") == "hash")
            check("P7.运行时 repo 为 app.state.trace_repo", args.get("repo") is app.state.trace_repo)
        trace, _ = app.state.trace_repo.get(response.headers["X-Trace-ID"])
        check("P7.落库记录 mode=local", trace.mode == "local", str(trace.mode))
    finally:
        close_app(app)


# ---------------------------------------------------------------- 零真实调用


def probe_zero_external_calls() -> None:
    print("\n== P8 零真实网络/模型调用 ==", flush=True)

    real_socket_connect = socket.socket.connect
    real_create_connection = socket.create_connection
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}

    def _dest_host(address):  # noqa: ANN001
        if isinstance(address, tuple) and address:
            return address[0]
        return str(address)

    def _guarded_socket_connect(self, address):  # noqa: ANN001
        if _dest_host(address) in loopback_hosts:
            return real_socket_connect(self, address)
        raise AssertionError(f"禁止外部网络连接：{address!r}")

    def _guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if _dest_host(address) in loopback_hosts:
            return real_create_connection(address, *args, **kwargs)
        raise AssertionError(f"禁止外部网络连接：{address!r}")

    root = tmpdir("p8")
    db_path = root / "obs" / "traces.sqlite3"
    settings = make_settings(root / "data", trace_enabled=True, trace_db_path=db_path)
    app = create_app(settings)
    try:
        session = open_session(app)
        conversation_id = create_conversation(session)
        with unittest.mock.patch.object(socket.socket, "connect", _guarded_socket_connect), \
             unittest.mock.patch.object(socket, "create_connection", _guarded_create_connection):
            response = ask_question(session, conversation_id)
        check("P8.socket 守卫下 QA POST 仍 200", response.status_code == 200, str(response.status_code))
        check("P8.socket 守卫下仍落 1 条 trace", len(read_trace_rows(db_path)) == 1)
        check("P8.model_gateway 为 None（无真实模型配置）", app.state.model_gateway is None)
        check("P8.ocr_gateway 为 None（无真实 OCR 配置）", app.state.ocr_gateway is None)
    finally:
        close_app(app)


def main() -> int:
    print(f"mktkb.__file__ = {MSG_PY}")
    print(f"sys.path[0] = {sys.path[0]}")
    rec("P0.导入的是目标仓库源码（非 .venv editable 副本）", ASSERT_OK, MSG_PY)
    probe_default_off()
    probe_enabled()
    probe_scope_only_qa_post()
    probe_write_failure()
    probe_body_equality()
    probe_config()
    probe_mode_static_and_runtime()
    probe_zero_external_calls()
    failed = [item for item in RESULTS if item["status"] != "PASS"]
    summary = {
        "python": sys.version,
        "mktkb_file": MSG_PY,
        "total": len(RESULTS),
        "passed": len(RESULTS) - len(failed),
        "failed": len(failed),
        "failed_items": failed,
    }
    print("\n===== SUMMARY =====")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
