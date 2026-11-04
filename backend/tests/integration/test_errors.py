"""T02-R1：统一错误结构与脱敏检查（请求校验、404/405、通用 500）。"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from conftest import ORIGIN

SECRET = "PM-SIMULATED-PASSWORD-NEVER-REAL"


def _assert_envelope(response, *, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message", "retryable", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert isinstance(body["error"]["retryable"], bool)
    assert body["request_id"] == response.headers.get("X-Request-ID")
    return body


@pytest.mark.parametrize(
    ("payload", "secret"),
    [
        ({"username": "admin", "password": "L" * 60 + SECRET}, SECRET),  # 远超 72 字符上限
        ({"username": "admin", "password": {"nested": SECRET}}, SECRET),
        ({"username": "", "password": SECRET}, SECRET),
        ({"username": "admin"}, SECRET),
    ],
)
def test_validation_errors_do_not_echo_input(client: TestClient, payload: dict, secret: str):
    response = client.post("/api/v1/auth/login", json=payload, headers={"Origin": ORIGIN})
    body = _assert_envelope(response, status=422, code="VALIDATION_ERROR")
    text = response.text
    assert secret not in text
    assert "input" not in {key for field in body["error"]["details"]["fields"] for key in field}
    for field in body["error"]["details"]["fields"]:
        assert set(field) == {"loc", "type"}
        assert all(isinstance(part, str) for part in field["loc"])
        assert field["loc"][0] == "body"


def test_malformed_json_body_returns_unified_error(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        content='{"username": "admin", "password": ' + SECRET,
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    _assert_envelope(response, status=422, code="VALIDATION_ERROR")
    assert SECRET not in response.text


def test_unknown_route_returns_unified_404(client: TestClient):
    response = client.get("/api/v1/not-an-existing-route")
    body = _assert_envelope(response, status=404, code="NOT_FOUND")
    assert body["error"]["message"] == "资源不存在"


def test_wrong_method_returns_unified_405_with_allow_header(client: TestClient):
    response = client.post("/api/v1/healthz")
    _assert_envelope(response, status=405, code="METHOD_NOT_ALLOWED")
    assert "GET" in response.headers.get("allow", "")


def test_unhandled_error_is_masked(client: TestClient, caplog):
    caplog.set_level(logging.DEBUG)
    response = client.get("/api/v1/probe/boom")
    body = _assert_envelope(response, status=500, code="INTERNAL_ERROR")
    assert body["error"]["retryable"] is True
    text = response.text
    for needle in (SECRET, "sqlite:///", "C:/secret", "RuntimeError", "Traceback"):
        assert needle not in text
    logs = caplog.text
    for needle in (SECRET, "sqlite:///", "C:/secret", "Traceback"):
        assert needle not in logs


def test_business_errors_keep_unified_shape(client: TestClient, admin_client: TestClient):
    unauthenticated = client.get("/api/v1/auth/me")
    _assert_envelope(unauthenticated, status=401, code="AUTH_REQUIRED")
    no_csrf = admin_client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    _assert_envelope(no_csrf, status=403, code="CSRF_INVALID")
