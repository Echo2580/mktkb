"""T302 §5.2：权限矩阵、负例、不泄露与 OpenAPI（S1/S2/S3/S5/S6/S7）。"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mktkb.main import create_app
from operations.helpers import BASE, make_document, make_import, make_request

OPS = "/api/v1/operations"
ENDPOINTS = (
    "overview",
    "requests",
    "requests/{request_id}",
    "documents",
    "documents/{document_id}",
    "evaluation-runs",
)
FORBIDDEN_KEYS = frozenset(
    {
        "attributes_json",
        "retrieval_counts_json",
        "filter_decisions_json",
        "fact_gate_json",
        "citation_refs_json",
        "pagination_json",
        "token_usage_json",
        "cost_json",
        "degraded_json",
        "stored_path",
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "database_url",
        "password",
        "secret",
        "api_key",
    }
)
ERROR_TOP_LEVEL = frozenset({"error", "request_id"})
ERROR_FIELDS = frozenset({"code", "message", "retryable", "details"})
CANARY = "LEAK-CANARY-LEASE-TOKEN"
EXPECTED_PATHS = frozenset(
    {
        f"{OPS}/overview",
        f"{OPS}/requests",
        f"{OPS}/requests/{{request_id}}",
        f"{OPS}/documents",
        f"{OPS}/documents/{{document_id}}",
        f"{OPS}/evaluation-runs",
    }
)


def _walk_keys(payload: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            keys.add(str(key))
            keys |= _walk_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            keys |= _walk_keys(item)
    return keys


def _assert_no_forbidden(payload: object, text: str) -> None:
    leaked = _walk_keys(payload) & FORBIDDEN_KEYS
    assert not leaked, f"响应出现禁止字段：{sorted(leaked)}"
    assert CANARY not in text


def _assert_error(response, *, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == set(ERROR_TOP_LEVEL), body
    error = body["error"]
    assert set(error) == set(ERROR_FIELDS), error
    assert error["code"] == code
    assert isinstance(body["request_id"], str) and body["request_id"]
    return body


def _get(client: TestClient, endpoint: str, *, request_id: str, document_id: str):
    path = {
        "overview": f"{OPS}/overview",
        "requests": f"{OPS}/requests",
        "requests/{request_id}": f"{OPS}/requests/{request_id}",
        "documents": f"{OPS}/documents",
        "documents/{document_id}": f"{OPS}/documents/{document_id}",
        "evaluation-runs": f"{OPS}/evaluation-runs",
    }[endpoint]
    return client.get(path)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unauthenticated_gets_401(app, endpoint: str) -> None:
    anonymous = TestClient(app, raise_server_exceptions=False)
    response = _get(
        anonymous,
        endpoint,
        request_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
    )
    body = _assert_error(response, status=401, code="AUTH_REQUIRED")
    assert body["error"]["details"] is None


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_employee_gets_403(employee_client: TestClient, endpoint: str) -> None:
    response = _get(
        employee_client,
        endpoint,
        request_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
    )
    body = _assert_error(response, status=403, code="ROLE_REQUIRED")
    assert body["error"]["details"] == {"required_role": "admin"}


def test_deleted_conversation_is_excluded_on_both_sides(admin_client, db) -> None:
    alive = make_request(db, finished_at=BASE, kind="answer")
    removed = make_request(db, finished_at=BASE + timedelta(minutes=1), kind="not_found", deleted=True)
    db.commit()

    overview = admin_client.get(f"{OPS}/overview", params={"window": "7d"})
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["metrics"]["completed_requests"] == 1
    assert body["metrics"]["not_found"] == 0

    listing = admin_client.get(f"{OPS}/requests", params={"window": "7d"})
    assert listing.status_code == 200, listing.text
    ids = {item["request_id"] for item in listing.json()["items"]}
    assert str(alive.request.id) in ids
    assert str(removed.request.id) not in ids

    detail_path = f"{OPS}/requests/{removed.request.id}"
    _assert_error(admin_client.get(detail_path), status=404, code="REQUEST_NOT_FOUND")


@pytest.mark.parametrize(
    "path, code",
    [
        (f"{OPS}/requests/not-a-uuid", "REQUEST_NOT_FOUND"),
        (f"{OPS}/requests/bad..id", "REQUEST_NOT_FOUND"),
        (f"{OPS}/documents/not-a-uuid", "DOCUMENT_NOT_FOUND"),
    ],
)
def test_invalid_ids_are_404(admin_client, path: str, code: str) -> None:
    response = admin_client.get(path)
    _assert_error(response, status=404, code=code)
    assert response.status_code != 500


def test_missing_document_is_404(admin_client) -> None:
    response = admin_client.get(f"{OPS}/documents/{uuid.uuid4()}")
    _assert_error(response, status=404, code="DOCUMENT_NOT_FOUND")


def test_responses_are_whitelisted_and_secret_free(trace_admin, db) -> None:
    """成功与错误响应：无 ``*_json``/stored_path/lease_* 原文、无哨兵泄漏。"""
    doc = make_document(db, name="位置表", units=2)
    broken = make_document(db, name="失败导入资料")
    job = make_import(db, broken.versions[0])
    entry = make_request(
        db,
        finished_at=BASE,
        question="城东店的宣传海报在哪里？",
        sources=((str(doc.document.id), str(doc.versions[0].id)),),
    )
    db.commit()

    ids = dict(request_id=str(entry.request.id), document_id=str(doc.document.id))
    responses = {endpoint: _get(trace_admin, endpoint, **ids) for endpoint in ENDPOINTS}
    for endpoint, response in responses.items():
        assert response.status_code == 200, (endpoint, response.text)
        _assert_no_forbidden(response.json(), response.text)

    detail = responses["requests/{request_id}"].json()
    assert detail["question"] == "城东店的宣传海报在哪里？"
    assert detail["citations"][0]["status"] == "active"
    assert "cells" not in (detail["citations"][0].get("locator") or {})

    documents = responses["documents"].json()
    item = next(entry for entry in documents["items"] if entry["document_id"] == str(doc.document.id))
    assert item["final_citations"] == 1
    assert item["latest_import"] is None
    failed = next(
        entry
        for entry in documents["items"]
        if entry["document_id"] == str(broken.document.id)
    )
    assert failed["latest_import"]["error_code"] == "PARSE_INCOMPLETE"

    document_detail = responses["documents/{document_id}"].json()
    assert document_detail["document"]["name"] == "位置表"
    assert "stored_path" not in document_detail["document"]
    assert all("lease_token" not in item for item in document_detail["imports"])

    # 错误响应同样不得外泄。
    error_cases = [
        (trace_admin.get(f"{OPS}/requests/not-a-uuid"), 404, "REQUEST_NOT_FOUND"),
        (trace_admin.get(f"{OPS}/overview", params={"window": "bad"}), 422, "INVALID_WINDOW"),
        (trace_admin.get(f"{OPS}/requests", params={"page_size": 101}), 422, "INVALID_PAGE_SIZE"),
    ]
    for response, status, code in error_cases:
        body = _assert_error(response, status=status, code=code)
        _assert_no_forbidden(body, response.text)


def test_all_six_gets_are_read_only(trace_admin, trace_db) -> None:
    """6 个 GET 前后业务库与 Trace 库字节级不变：读取不产生任何写入。"""
    import hashlib
    from pathlib import Path

    doc = make_document(trace_db, name="只读探针资料")
    entry = make_request(
        trace_db, finished_at=BASE, kind="answer",
        sources=((str(doc.document.id), str(doc.versions[0].id)),),
    )
    trace_db.commit()

    settings = trace_admin.app.state.settings
    db_path = Path(str(settings.database_url).removeprefix("sqlite:///"))
    trace_path = Path(str(settings.trace_db_path))

    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"

    before = (_digest(db_path), _digest(trace_path))
    ids = dict(request_id=str(entry.request.id), document_id=str(doc.document.id))
    for endpoint in ENDPOINTS:
        assert _get(trace_admin, endpoint, **ids).status_code == 200
    after = (_digest(db_path), _digest(trace_path))
    assert after == before, "只读接口写入了数据库"


def test_openapi_only_six_get_paths_and_initialize_false_writes_nothing(settings) -> None:
    data_dir = Path(settings.data_dir)
    before = sorted(item.relative_to(data_dir) for item in data_dir.rglob("*"))
    application = create_app(settings, initialize=False)
    try:
        schema = application.openapi()
        paths = {
            path: operation
            for path, operation in schema["paths"].items()
            if path.startswith(OPS)
        }
        assert set(paths) == set(EXPECTED_PATHS)
        for path, operation in paths.items():
            assert set(operation) == {"get"}, (path, operation.keys())
            get = operation["get"]
            assert {"200", "401", "403"} <= set(get["responses"]), path
            for status in ("401", "403"):
                assert get["responses"][status].get("description"), (path, status)
    finally:
        application.state.db.dispose()
    after = sorted(item.relative_to(data_dir) for item in data_dir.rglob("*"))
    assert after == before, "create_app(initialize=False) 不得写数据目录"
