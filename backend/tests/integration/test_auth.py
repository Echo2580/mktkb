"""T02 登录、会话、CSRF/Origin 与角色权限的 ASGI 接口检查（L 层，不含浏览器验收）。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from mktkb.auth.models import LoginSession, User
from mktkb.auth.security import token_hash
from mktkb.config import Settings
from mktkb.main import create_app

from conftest import ORIGIN, login


def _cookie_token(client: TestClient) -> str:
    token = client.cookies.get("mktkb_session")
    assert token, "登录后应存在会话 Cookie"
    return token


def _client_with_token(app, token: str) -> TestClient:
    """用默认 Cookie 头构造独立客户端，避免共享 CookieJar 造成同名 Cookie 并存。"""
    client = TestClient(app)
    client.headers["Cookie"] = f"mktkb_session={token}"
    return client


def test_healthz_is_minimal(client: TestClient):
    response = client.get("/api/v1/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_me_requires_login(client: TestClient):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"
    assert body["error"]["retryable"] is False
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]


def test_login_rejects_bad_credentials_without_leaking_account(client: TestClient):
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
        headers={"Origin": ORIGIN},
    )
    unknown_user = client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "wrong-password"},
        headers={"Origin": ORIGIN},
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["error"]["code"] == unknown_user.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong_password.json()["error"]["message"] == unknown_user.json()["error"]["message"]
    assert "admin" not in wrong_password.text.lower()


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://evil.example"}])
def test_login_requires_trusted_origin(client: TestClient, headers: dict):
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "AdminPass-1"}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_REJECTED"


def test_login_sets_http_only_session_cookie(client: TestClient):
    payload = login(client, "admin", "AdminPass-1")
    assert set(payload) == {"user", "csrf_token"}
    assert payload["user"]["role"] == "admin"
    assert set(payload["user"]) == {"id", "display_name", "role"}
    token = _cookie_token(client)
    assert len(token) >= 32

    set_cookie = client.get("/api/v1/auth/me").headers.get("set-cookie")
    assert set_cookie is None or "mktkb_session" in set_cookie
    # 重新登录抓取 Set-Cookie 属性
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "AdminPass-1"}, headers={"Origin": ORIGIN}
    )
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "max-age=3600" in header
    assert "secure" not in header, "本地开发配置应可显式关闭 Secure"


def test_production_cookie_is_secure(store, settings: Settings):
    secure_settings = settings.model_copy(update={"cookie_secure": True})
    application = create_app(secure_settings)
    with TestClient(application) as secure_client:
        response = secure_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "AdminPass-1"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"].lower()


def test_me_returns_user_and_stable_csrf(admin_client: TestClient):
    first = admin_client.get("/api/v1/auth/me")
    second = admin_client.get("/api/v1/auth/me")
    assert first.status_code == second.status_code == 200
    assert first.json()["user"]["role"] == "admin"
    assert first.json()["csrf_token"] == second.json()["csrf_token"]
    assert len(first.json()["csrf_token"]) == 64


def test_session_token_is_stored_hashed(admin_client: TestClient, db):
    token = _cookie_token(admin_client)
    rows = db.scalars(select(LoginSession)).all()
    assert rows, "登录会话必须持久化到数据库"
    assert all(row.token_hash != token for row in rows)
    assert all(len(row.token_hash) == 64 for row in rows)
    assert any(row.token_hash == token_hash(token) for row in rows)


def test_employee_cannot_use_admin_role_dependency(employee_client: TestClient):
    assert employee_client.get("/api/v1/probe/employee").status_code == 200
    response = employee_client.get("/api/v1/probe/admin")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_REQUIRED"


def test_admin_can_use_admin_dependency(admin_client: TestClient):
    response = admin_client.get("/api/v1/probe/admin")
    assert response.status_code == 200
    assert response.json() == {"role": "admin"}


def test_second_employee_session_is_independent(second_employee_client: TestClient, employee_client: TestClient, app):
    me = second_employee_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["display_name"] == "演示员工二"
    assert second_employee_client.get("/api/v1/probe/admin").status_code == 403
    # 另一账号的 Cookie 只能代表它自己的身份
    other = _client_with_token(app, _cookie_token(employee_client))
    assert other.get("/api/v1/auth/me").json()["user"]["display_name"] == "演示员工"


def test_logout_requires_csrf_and_is_idempotent(admin_client: TestClient):
    missing = admin_client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "CSRF_INVALID"

    csrf = admin_client.get("/api/v1/auth/me").json()["csrf_token"]
    wrong = admin_client.post(
        "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf[:-1] + ("0" if csrf[-1] != "0" else "1")}
    )
    assert wrong.status_code == 403

    ok = admin_client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert ok.status_code == 204
    assert admin_client.get("/api/v1/auth/me").status_code == 401

    repeat = admin_client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    assert repeat.status_code == 204, "已退出后重复退出应保持 204"


def test_logout_rejects_untrusted_origin(admin_client: TestClient):
    csrf = admin_client.get("/api/v1/auth/me").json()["csrf_token"]
    response = admin_client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://evil.example", "X-CSRF-Token": csrf}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_REJECTED"


def test_csrf_token_cannot_be_reused_across_sessions(employee_client: TestClient, admin_client: TestClient):
    employee_csrf = employee_client.get("/api/v1/auth/me").json()["csrf_token"]
    admin_csrf = admin_client.get("/api/v1/auth/me").json()["csrf_token"]
    assert employee_csrf != admin_csrf
    response = admin_client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": employee_csrf})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_INVALID"


def test_expired_session_is_rejected(admin_client: TestClient, db):
    token = _cookie_token(admin_client)
    db.execute(
        update(LoginSession)
        .where(LoginSession.token_hash == token_hash(token))
        .values(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    )
    db.commit()
    response = admin_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


def test_logout_in_one_session_keeps_another_session(admin_client: TestClient, client: TestClient, app):
    first_token = _cookie_token(admin_client)
    second = login(client, "admin", "AdminPass-1")
    second_token = _cookie_token(client)
    assert first_token != second_token

    response = client.post(
        "/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": second["csrf_token"]}
    )
    assert response.status_code == 204

    assert _client_with_token(app, first_token).get("/api/v1/auth/me").status_code == 200
    assert _client_with_token(app, second_token).get("/api/v1/auth/me").status_code == 401


def test_bootstrap_is_idempotent_and_keeps_password(settings: Settings, db):
    first = create_app(settings)
    second = create_app(settings)  # 重跑初始化
    try:
        users = db.scalars(select(User)).all()
        assert sorted(user.username for user in users) == ["admin", "employee"]
        assert len({user.password_hash for user in users}) == 2
        with TestClient(second) as client:
            login(client, "employee", "EmployeePass-1")
            assert client.get("/api/v1/auth/me").status_code == 200
    finally:
        first.state.db.dispose()
        second.state.db.dispose()


def test_session_survives_app_rebuild(settings: Settings):
    first_app = create_app(settings)
    with TestClient(first_app) as client:
        login(client, "admin", "AdminPass-1")
        token = _cookie_token(client)
        csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
    first_app.state.db.dispose()

    second_app = create_app(settings)
    try:
        rebuilt = _client_with_token(second_app, token)
        me = rebuilt.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["csrf_token"] == csrf
    finally:
        second_app.state.db.dispose()


def test_errors_and_logs_do_not_leak_secrets(client: TestClient, caplog, store):
    caplog.set_level(logging.DEBUG)
    client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "AdminPass-1"}, headers={"Origin": ORIGIN}
    )
    token = _cookie_token(client)
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "SuperSecretWrong"}, headers={"Origin": ORIGIN}
    )
    body = response.text
    assert "SuperSecretWrong" not in body
    assert "sqlite" not in body.lower()
    assert "traceback" not in body.lower()
    assert str(store.root) not in body
    logs = caplog.text
    assert "SuperSecretWrong" not in logs
    assert "AdminPass-1" not in logs
    assert token not in logs
    assert "Traceback" not in logs
