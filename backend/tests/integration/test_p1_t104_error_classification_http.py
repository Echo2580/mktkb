"""T104：异常原因分类的产品路径集成测试（真实 HTTP + 可控模型 + Trace）。

不建真实外网连接：模型用 ``conftest.EvidenceEchoGateway``，异常由用例注入；资料来自
``fixtures/acceptance/normal/D01_物品位置表.xlsx``，经真实上传/worker/发布。

覆盖验收标准：
- 七类原因（配置/预算/provider/超时/输出校验/内部/未知）经真实 API 得到可区分
  ``error_code`` 与正确 ``retryable``，非 provider 原因不再报 ``MODEL_UNAVAILABLE``；
- 每类文案都套用 ERR-07 模板（服务调用失败≠资料没有答案 / 可否重试 / 不重复落库）；
- ``AskResult`` 响应字段集合与改动前一致（D-3 只允许取值变化）；
- Trace 的 ``reason`` / ``error_code`` 与响应一致，必需 Span 不破坏；
- service_error 幂等重放：同 ``client_request_id`` 不重复调用模型、不重复落库。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import current_csrf, login, upload_document, write_headers
from mktkb.conversations import service
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.observability.contracts import validate_required_spans
from mktkb.providers.types import (
    ModelBudgetRefused,
    ModelOutputInvalid,
    ModelTimeout,
    ModelUnavailable,
)

ROOT = Path(__file__).resolve().parents[3]
D01 = ROOT / "fixtures" / "acceptance" / "normal" / "D01_物品位置表.xlsx"
QUESTION = "城东店的宣传海报在哪里？"
TRACE_DB = "qa-traces.sqlite3"

#: ``AskResult`` 对外字段集合（D-3：结构不变，只允许取值变化）。
ASK_FIELDS = {
    "request_id",
    "message_id",
    "kind",
    "text",
    "revision",
    "sources",
    "candidates",
    "conflicts",
    "missing_fields",
    "pagination",
    "error_code",
    "retryable",
}

ERR07_NOT_MISSING = "这是服务调用失败，不是资料中没有答案"
ERR07_NO_DUPLICATE = "服务端不会因重试而重复保存同一条回答。"


def _session(app, username: str, password: str) -> SimpleNamespace:
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
def t104_app(settings, chat_model, tmp_path: Path) -> SimpleNamespace:
    """开启 Trace 的应用 + 一份已发布资料（D01）；结束后关闭仓储/内核/业务库。"""
    trace_settings = settings.model_copy(
        update={
            "trace_enabled": True,
            "trace_db_path": tmp_path / "observability" / TRACE_DB,
            "trace_content_mode": "hash",
        }
    )
    app = create_app(trace_settings, model_gateway=chat_model)
    admin = _session(app, "admin", "AdminPass-1")
    employee = _session(app, "employee", "EmployeePass-1")
    receipt = admin.upload(path=D01)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
        revision = int(get_revision(db))
    finally:
        db.close()
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin.headers,
        json={"expected_active_version_id": None, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    try:
        yield SimpleNamespace(app=app, admin=admin, employee=employee, model=chat_model)
    finally:
        qa = getattr(app.state, "qa", None)
        if qa is not None:
            qa.close()
        repo = getattr(app.state, "trace_repo", None)
        if repo is not None:
            repo.close()
        app.state.db.dispose()


def _new_conversation(employee: SimpleNamespace) -> str:
    response = employee.client.post("/api/v1/conversations", json={}, headers=employee.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(employee: SimpleNamespace, conversation_id: str, request_id: uuid.UUID | None = None):
    return employee.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(request_id or uuid.uuid4()), "question": QUESTION},
        headers=employee.headers,
    )


def _trace_of(app, response) -> tuple[object, list[object]]:
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id, "开启 Trace 时 QA POST 必须返回 X-Trace-ID"
    return app.state.trace_repo.get(trace_id)


def _assert_service_error(
    response,
    *,
    code: str,
    retryable: bool,
) -> dict:
    """一个 service_error 响应的完整口径：结构、码值、可重试性、ERR-07 文案、无来源。"""
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ASK_FIELDS, "T104/D-3：响应字段集合不得变化"
    assert body["kind"] == "service_error", body
    assert body["error_code"] == code, body
    assert body["retryable"] is retryable, body
    assert body["sources"] == [] and body["candidates"] == [] and body["conflicts"] == []
    assert ERR07_NOT_MISSING in body["text"], body["text"]
    assert ERR07_NO_DUPLICATE in body["text"], body["text"]
    if retryable:
        assert "可稍后重新提问" in body["text"], body["text"]
    else:
        assert "重试不会自行恢复" in body["text"], body["text"]
    return body


def _assert_trace_matches(app, response, body: dict) -> None:
    trace, spans = _trace_of(app, response)
    assert trace.outcome_kind == "service_error", trace.outcome_kind
    assert trace.reason == body["error_code"] == trace.error_code
    names = {span.name for span in spans}
    assert validate_required_spans(trace, names) == []


# ---------------------------------------------------------------- 逐类错误码


def test_provider_failure_keeps_model_unavailable_and_err07_text(t104_app) -> None:
    t104_app.model.error = ModelUnavailable("T104 注入：供应商不可用")
    try:
        conversation = _new_conversation(t104_app.employee)
        response = _ask(t104_app.employee, conversation)
        body = _assert_service_error(response, code="MODEL_UNAVAILABLE", retryable=True)
        assert body["text"].startswith("模型服务暂不可用")
        assert len(t104_app.model.calls) == 1
        _assert_trace_matches(t104_app.app, response, body)
    finally:
        t104_app.model.error = None


@pytest.mark.parametrize(
    ("error", "code", "retryable", "needle"),
    [
        (ModelBudgetRefused("T104 注入：预算/授权拒绝"), "MODEL_BUDGET_REFUSED", False, "未发送请求"),
        (ModelTimeout("T104 注入：超时"), "MODEL_TIMEOUT", True, "响应超时"),
        (ModelOutputInvalid("T104 注入：输出校验失败"), "MODEL_OUTPUT_INVALID", True, "未通过来源与字段校验"),
        (RuntimeError("T104 注入：无法归类"), "MODEL_CALL_FAILED", True, "原因未能归类"),
    ],
)
def test_each_failure_reason_has_distinct_code_and_retryability(
    t104_app, error, code, retryable, needle
) -> None:
    t104_app.model.error = error
    try:
        conversation = _new_conversation(t104_app.employee)
        response = _ask(t104_app.employee, conversation)
        body = _assert_service_error(response, code=code, retryable=retryable)
        assert needle in body["text"], body["text"]
        assert body["error_code"] != "MODEL_UNAVAILABLE"
        _assert_trace_matches(t104_app.app, response, body)
    finally:
        t104_app.model.error = None


def test_asyncio_timeout_maps_to_timeout(t104_app) -> None:
    t104_app.model.error = asyncio.TimeoutError()
    try:
        conversation = _new_conversation(t104_app.employee)
        response = _ask(t104_app.employee, conversation)
        body = _assert_service_error(response, code="MODEL_TIMEOUT", retryable=True)
        _assert_trace_matches(t104_app.app, response, body)
    finally:
        t104_app.model.error = None


def test_missing_gateway_reports_not_configured(t104_app, monkeypatch) -> None:
    """配置缺失：请求未进入模型调用，不可重试，但不是“资料中没有答案”。"""
    monkeypatch.setattr(t104_app.app.state, "model_gateway", None)
    conversation = _new_conversation(t104_app.employee)
    response = _ask(t104_app.employee, conversation)
    body = _assert_service_error(response, code="MODEL_NOT_CONFIGURED", retryable=False)
    assert "尚未配置" in body["text"], body["text"]
    assert t104_app.model.calls == [], "配置缺失不得发起任何模型调用"
    _assert_trace_matches(t104_app.app, response, body)


def test_internal_failure_is_stable_and_does_not_leak_details(t104_app, monkeypatch) -> None:
    """内部：本地校验的非预期异常 → 稳定码、不可重试、不回显异常文本。"""
    boom = "T104-INTERNAL-BOOM pm-simulated-secret"

    def broken_validate(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError(boom)

    monkeypatch.setattr(service, "_validate_answer", broken_validate)
    conversation = _new_conversation(t104_app.employee)
    response = _ask(t104_app.employee, conversation)
    body = _assert_service_error(response, code="QA_INTERNAL_ERROR", retryable=False)
    assert "内部处理异常" in body["text"]
    assert boom not in response.text and "RuntimeError" not in response.text
    _assert_trace_matches(t104_app.app, response, body)


# ---------------------------------------------------------------- 幂等与结构


def test_service_error_replay_is_idempotent_for_new_code(t104_app) -> None:
    """未知原因码同样幂等：同 client_request_id 重放不重复调用模型、不重复落库。"""
    t104_app.model.error = RuntimeError("T104 注入：无法归类")
    try:
        conversation = _new_conversation(t104_app.employee)
        request_id = uuid.uuid4()
        first = _ask(t104_app.employee, conversation, request_id)
        body = _assert_service_error(first, code="MODEL_CALL_FAILED", retryable=True)
        calls = len(t104_app.model.calls)
        assert calls == 1

        replay = _ask(t104_app.employee, conversation, request_id)
        assert replay.status_code == 200, replay.text
        assert replay.json()["message_id"] == body["message_id"]
        assert replay.json()["error_code"] == "MODEL_CALL_FAILED"
        assert len(t104_app.model.calls) == calls, "重放不得重复调用模型"
        history = t104_app.employee.client.get(
            f"/api/v1/conversations/{conversation}/messages", headers=t104_app.employee.headers
        )
        assert history.json()["total"] == 2
    finally:
        t104_app.model.error = None
