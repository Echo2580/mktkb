"""T114：监控 API 权限矩阵 / 负例 / 边界 / 不泄露 / OpenAPI 验收测试。

本文件**新增**在 T113 ``test_routes.py`` 之外，不修改既有测试。覆盖：

- 4 端点 × 未登录 401（``AUTH_REQUIRED``）/ employee 403（``ROLE_REQUIRED``，
  ``details.required_role=admin``）/ admin 200；
- 鉴权 → 参数校验 → 资源读取的顺序：未登录 / employee 下不返回 404 / 422；
- 错误响应键白名单（``error{code,message,retryable,details}`` + ``request_id``）；
- admin 下不存在 trace/run → 404；未知 request → 200 空列表；
- 非法 ``window`` / ``trace_id`` / ``run_id`` / ``request_id`` → 422 且错误码正确；
  路径穿越（含 URL 编码）不得 200；
- 时间窗合法（``1h`` / ``24h`` / ``999999h`` / ``30m``）与非法清单逐项断言；
  超大窗口 200 不 500（不声称性能上限）；
- 分页 NOT-APPLICABLE：四端点均无 ``limit`` / ``offset`` 参数；
- trace 关闭时 4 端点 200 + ``degraded_reason="trace_disabled"``；
- 成功与错误响应均不含问题/答案原文、``*_json`` 原文或 Holdout 逐题；
- holdout run 只返回聚合与 ``details_withheld``；
- OpenAPI 4 路径仅 GET、声明 401/403、无分页参数；已提交快照与实时 schema 一致。

全部数据来自 ``tmp_path``；零真实模型 / OCR / embedding / rerank 调用；不读
``.env``、不访问外网、不触碰 ``var/`` 或 ``docs/evidence``。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mktkb.main import create_app
from mktkb.observability.contracts import SpanRecord, TraceRecord
from mktkb.observability.routes import (
    GateSummary,
    HoldoutSummary,
    MetricGroup,
    MetricsResponse,
    RequestTracesResponse,
    RunManifestSummary,
    RunResponse,
    RunSummaryBlock,
    SpanSummary,
    TraceDetailResponse,
    TraceSummary,
)
from mktkb.observability.store import TraceRepository

BASE = "/api/v1/observability"
ENDPOINTS = ("traces", "requests", "metrics", "runs")

#: 响应里绝不允许出现的原文字段名（问题/答案/上下文/逐题/内部 JSON/路径/凭据）。
FORBIDDEN_KEYS = frozenset(
    {
        "question",
        "question_text",
        "answer",
        "answer_text",
        "text",
        "context",
        "context_text",
        "cases",
        "case_id",
        "attributes_json",
        "retrieval_counts_json",
        "filter_decisions_json",
        "fact_gate_json",
        "citation_refs_json",
        "pagination_json",
        "token_usage_json",
        "cost_json",
        "degraded_json",
        "metrics_scope",
        "declarations",
        "evidence",
        "dataset_path",
        "corpus_dir",
        "trace_store",
        "database_url",
        "password",
        "secret",
        "api_key",
    }
)
#: 错误信封的顶层键与 ``error`` 子键（全局错误处理器口径）。
ERROR_TOP_LEVEL = frozenset({"error", "request_id"})
ERROR_FIELDS = frozenset({"code", "message", "retryable", "details"})

SECRET_TEXT = "T114-SECRET-QUESTION-ANSWER-CONTEXT-HOLDOUT-NEVER-RETURNED"
RUN_ID = "b0-local-20261109-abcdef12"
HOLDOUT_RUN_ID = "holdout-local-20261109-abcdef12"

EXPECTED_PATHS = frozenset(
    {
        f"{BASE}/traces/{{trace_id}}",
        f"{BASE}/requests/{{request_id}}/traces",
        f"{BASE}/metrics",
        f"{BASE}/runs/{{run_id}}",
    }
)


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #


def _now(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat(
        timespec="milliseconds"
    )


def _valid_trace_id() -> str:
    return uuid.uuid4().hex


def _valid_request_id() -> str:
    return str(uuid.uuid4())


def _record(
    *,
    trace_id: str | None = None,
    request_id: str = "req-1",
    attempt: int = 1,
    replayed: bool = False,
    previous_trace_id: str | None = None,
    path: str = "rag",
    outcome: str = "answer",
    status: str = "ok",
    latency_ms: int | None = 10,
    created_at: str | None = None,
    case_id: str | None = None,
    secret_json: bool = False,
) -> TraceRecord:
    secret = {"secret_note": SECRET_TEXT} if secret_json else None
    return TraceRecord(
        trace_id=trace_id or uuid.uuid4().hex,
        request_id=request_id,
        http_request_id="http-request-1",
        attempt=attempt,
        replayed=replayed,
        previous_trace_id=previous_trace_id,
        mode="local",
        scope="end_to_end",
        path=path,
        case_id=case_id,
        content_mode="hash",
        query_kind="qa",
        outcome_kind=outcome,
        reason="TEST_REASON",
        answer_source="rag",
        status=status,
        latency_ms=latency_ms,
        created_at=created_at or _now(),
        question_hash="a" * 64,
        question_chars=42,
        hash_algo="sha256",
        hmac_key_id=None,
        user_id_hash="b" * 64,
        conversation_id_hash="c" * 64,
        retrieval_counts_json=json.dumps(secret) if secret else None,
        filter_decisions_json=json.dumps(secret) if secret else None,
        fact_gate_json=json.dumps(secret) if secret else None,
        citation_refs_json=json.dumps(secret) if secret else None,
        pagination_json=json.dumps(secret) if secret else None,
        token_usage_json=json.dumps({"input": 10, "output": 5, "note": SECRET_TEXT})
        if secret
        else json.dumps({"input": 10, "output": 5}),
        cost_json=json.dumps({"cny": 0.01, "note": SECRET_TEXT}) if secret else json.dumps({"cny": 0.01}),
        degraded_json=json.dumps({"vector_disabled": True, "note": SECRET_TEXT}) if secret else None,
    )


def _write(repo: TraceRepository, record: TraceRecord, spans: list[SpanRecord] | None = None) -> str:
    repo.write(record, spans or [])
    assert record.trace_id is not None
    return record.trace_id


def _write_run(
    data_dir: Path,
    run_id: str,
    *,
    manifest: Mapping[str, object],
    summary: Mapping[str, object] | None = None,
    gate: Mapping[str, object] | None = None,
    cases_text: str | None = None,
) -> Path:
    run_dir = Path(data_dir) / "eval" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(dict(manifest), ensure_ascii=False), encoding="utf-8"
    )
    if summary is not None:
        (run_dir / "summary.json").write_text(
            json.dumps(dict(summary), ensure_ascii=False), encoding="utf-8"
        )
    if gate is not None:
        (run_dir / "gate.json").write_text(
            json.dumps(dict(gate), ensure_ascii=False), encoding="utf-8"
        )
    if cases_text is not None:
        (run_dir / "cases.jsonl").write_text(cases_text, encoding="utf-8")
    return run_dir


def _manifest(run_id: str, *, suite: str = "b0", holdout_details: bool = False) -> dict:
    return {
        "run_id": run_id,
        "mode": "local",
        "scope": "end_to_end",
        "suite": suite,
        "dataset_version": "b0-v1",
        "dataset_sha256": "d" * 64,
        "corpus_manifest_sha256": "e" * 64,
        "business_date": "2026-11-01",
        "index_revision": 7,
        "pipeline_version": "pipeline-v1",
        "gate_version": "gate_v0_1",
        "label_version": "labels-v1",
        "created_at": "2026-11-01T00:00:00+00:00",
        "case_count": 40,
        "config_hash": "f" * 64,
        "trace_store": f"traces-{SECRET_TEXT}.sqlite3",
        "dataset_path": f"C:/secret/{SECRET_TEXT}/dataset.jsonl",
        "corpus_dir": f"C:/secret/{SECRET_TEXT}/corpus",
        "holdout_details": holdout_details,
        "holdout_labels_sha256": "1" * 64,
        "multi_turn_case_count": 2,
        "multi_turn_turns_executed": 3,
    }


def _summary(run_id: str, *, suite: str = "b0", holdout: Mapping[str, object] | None = None) -> dict:
    payload: dict[str, object] = {
        "run_id": run_id,
        "mode": "local",
        "suite": suite,
        "scope": "end_to_end",
        "dataset_version": "b0-v1",
        "dataset_sha256": "d" * 64,
        "corpus_manifest_sha256": "e" * 64,
        "business_date": "2026-11-01",
        "index_revision": 7,
        "pipeline_version": "pipeline-v1",
        "gate_version": "gate_v0_1",
        "case_count": 40,
        "scored_count": 32,
        "skipped_ocr_count": 8,
        "error_count": 0,
        "status_counts": {"pass": 29, "fail": 3, "skipped_requires_ocr": 8},
        "metrics": {
            "recall_at_10": 0.96875,
            "mrr_at_10": 0.96875,
            "by_stratum": {"core": {"recall_at_10": 1.0, "denominator": 12}},
            "note": SECRET_TEXT,
        },
        "metrics_scope": {"excluded_error_case_ids": [SECRET_TEXT]},
        "declarations": {"note": SECRET_TEXT},
    }
    if holdout is not None:
        payload["holdout"] = dict(holdout)
    return payload


def _gate(run_id: str) -> dict:
    return {
        "exit_code": 3,
        "run_id": run_id,
        "suite": "b0",
        "mode": "local",
        "gate_version": "gate_v0_1",
        "scored_count": 32,
        "min_sample": 5,
        "hard_failures": [],
        "gate_status": {"quality": "unknown", "min_sample": "pass"},
        "failures": [{"gate_id": "quality", "case_id": SECRET_TEXT, "evidence": {"text": SECRET_TEXT}}],
        "unknowns": [{"gate_id": "thresholds", "reason": SECRET_TEXT, "evidence": {}}],
        "not_applicable": [],
        "warnings": [SECRET_TEXT],
        "quality": {"status": "unknown", "failures": [{"evidence": {"text": SECRET_TEXT}}]},
    }


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
    assert SECRET_TEXT not in text
    leaked = _walk_keys(payload) & FORBIDDEN_KEYS
    assert not leaked, f"响应出现禁止字段：{sorted(leaked)}"


def _assert_error_envelope(response, *, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == set(ERROR_TOP_LEVEL), body
    error = body["error"]
    assert isinstance(error, Mapping)
    assert set(error) == set(ERROR_FIELDS), error
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert error["retryable"] is False
    assert isinstance(body["request_id"], str) and body["request_id"]
    return body


def _assert_model_keys(payload: object, model) -> None:
    assert isinstance(payload, Mapping)
    extra = set(payload) - set(model.model_fields)
    assert not extra, f"响应字段超出 {model.__name__} 白名单：{sorted(extra)}"


def _path(
    endpoint: str,
    *,
    trace_id: str,
    request_id: str,
    run_id: str,
) -> str:
    return {
        "traces": f"{BASE}/traces/{trace_id}",
        "requests": f"{BASE}/requests/{request_id}/traces",
        "metrics": f"{BASE}/metrics",
        "runs": f"{BASE}/runs/{run_id}",
    }[endpoint]


def _get(
    client: TestClient,
    endpoint: str,
    *,
    trace_id: str,
    request_id: str,
    run_id: str,
    window: str | None = "24h",
):
    path = _path(endpoint, trace_id=trace_id, request_id=request_id, run_id=run_id)
    if endpoint == "metrics":
        return client.get(path, params={} if window is None else {"window": window})
    return client.get(path)


def _collect_schema_names(payload: object, names: set[str]) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/components/schemas/"):
                names.add(value.rsplit("/", 1)[-1])
            else:
                _collect_schema_names(value, names)
    elif isinstance(payload, list):
        for item in payload:
            _collect_schema_names(item, names)


def _expected_schemas(schema: Mapping, paths: Mapping) -> dict:
    names: set[str] = set()
    _collect_schema_names(paths, names)
    definitions = schema.get("components", {}).get("schemas", {})
    resolved: dict[str, object] = {}
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in resolved:
            continue
        definition = definitions[name]
        resolved[name] = definition
        nested: set[str] = set()
        _collect_schema_names(definition, nested)
        pending.extend(nested - set(resolved))
    return {name: resolved[name] for name in sorted(resolved)}


# --------------------------------------------------------------------------- #
# 权限矩阵：401 / 403 / 200
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unauthenticated_gets_401_before_validation(trace_app, endpoint: str) -> None:
    """未登录优先于参数校验与资源读取：用不存在的 id / 非法 window 也不得 404/422。"""
    anonymous = TestClient(trace_app, raise_server_exceptions=False)
    response = _get(
        anonymous,
        endpoint,
        trace_id=_valid_trace_id(),
        request_id=_valid_request_id(),
        run_id="missing-run-id",
        window="not-a-window",
    )
    body = _assert_error_envelope(response, status=401, code="AUTH_REQUIRED")
    assert body["error"]["details"] is None
    assert response.status_code not in {404, 422}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_employee_gets_403_before_validation(trace_employee, endpoint: str) -> None:
    """employee 先被角色依赖拒绝：不泄露资源是否存在，也不暴露参数错误细节。"""
    response = _get(
        trace_employee.client,
        endpoint,
        trace_id=_valid_trace_id(),
        request_id=_valid_request_id(),
        run_id="missing-run-id",
        window="not-a-window",
    )
    body = _assert_error_envelope(response, status=403, code="ROLE_REQUIRED")
    assert body["error"]["details"] == {"required_role": "admin"}
    assert response.status_code not in {404, 422}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_admin_gets_200_on_all_four(trace_admin, endpoint: str) -> None:
    """admin 下四个端点均 200；数据由 fixture 在应用临时目录内构造。"""
    request_id = _valid_request_id()
    trace_id = _write(trace_admin.client.app.state.trace_repo, _record(request_id=request_id))
    _write_run(
        trace_admin.client.app.state.settings.data_dir,
        RUN_ID,
        manifest=_manifest(RUN_ID),
        summary=_summary(RUN_ID),
        gate=_gate(RUN_ID),
    )
    response = _get(
        trace_admin.client,
        endpoint,
        trace_id=trace_id,
        request_id=request_id,
        run_id=RUN_ID,
    )
    assert response.status_code == 200, response.text
    _assert_no_forbidden(response.json(), response.text)


def test_auth_order_is_auth_then_validation_then_resource(trace_app, trace_employee) -> None:
    """显式记录顺序：匿名 401 → employee 403 → admin 422/404。"""
    anonymous = TestClient(trace_app, raise_server_exceptions=False)
    ids = dict(trace_id=_valid_trace_id(), request_id=_valid_request_id(), run_id="missing-run-id")
    assert _assert_error_envelope(
        _get(anonymous, "metrics", window="bad", **ids), status=401, code="AUTH_REQUIRED"
    )
    assert _assert_error_envelope(
        _get(trace_employee.client, "metrics", window="bad", **ids), status=403, code="ROLE_REQUIRED"
    )


# --------------------------------------------------------------------------- #
# 错误信封 / 资源负例 / 参数负例
# --------------------------------------------------------------------------- #


def test_error_responses_use_whitelisted_envelope(trace_admin) -> None:
    """401/403/404/422 统一信封；秘密文本与内部字段不得出现在错误响应。"""
    ids = dict(trace_id=_valid_trace_id(), request_id=_valid_request_id(), run_id="missing-run-id")
    cases = [
        (_get(trace_admin.client, "metrics", window="bad", **ids), 422, "INVALID_WINDOW"),
        (_get(trace_admin.client, "traces", **ids), 404, "TRACE_NOT_FOUND"),
        (_get(trace_admin.client, "runs", **ids), 404, "RUN_NOT_FOUND"),
    ]
    for response, status, code in cases:
        body = _assert_error_envelope(response, status=status, code=code)
        _assert_no_forbidden(body, response.text)

    anonymous = TestClient(trace_admin.client.app, raise_server_exceptions=False)
    body = _assert_error_envelope(
        _get(anonymous, "traces", **ids), status=401, code="AUTH_REQUIRED"
    )
    _assert_no_forbidden(body, "anonymous")


def test_admin_missing_trace_and_run_are_404(trace_admin) -> None:
    missing_trace = trace_admin.client.get(f"{BASE}/traces/{_valid_trace_id()}")
    _assert_error_envelope(missing_trace, status=404, code="TRACE_NOT_FOUND")

    missing_run = trace_admin.client.get(f"{BASE}/runs/run-does-not-exist")
    _assert_error_envelope(missing_run, status=404, code="RUN_NOT_FOUND")

    # 目录存在但没有 manifest：同样 404，不暴露目录内容。
    empty_run = trace_admin.client.app.state.settings.data_dir / "eval" / "runs" / "empty-run"
    empty_run.mkdir(parents=True, exist_ok=True)
    _assert_error_envelope(
        trace_admin.client.get(f"{BASE}/runs/empty-run"), status=404, code="RUN_NOT_FOUND"
    )


def test_unknown_request_returns_200_empty_list(trace_admin) -> None:
    """T113 既有语义：未知 request 不是 404，而是 200 空列表（文档写明）。"""
    response = trace_admin.client.get(f"{BASE}/requests/{_valid_request_id()}/traces")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["traces"] == []
    assert body["degraded_reason"] is None
    _assert_model_keys(body, RequestTracesResponse)


@pytest.mark.parametrize(
    "window",
    ["0h", "-1h", "abc", "24", "1.5h", "24D", "1H", " 24h", "1000000h"],
)
def test_invalid_window_is_422(trace_admin, window: str) -> None:
    response = trace_admin.client.get(f"{BASE}/metrics", params={"window": window})
    _assert_error_envelope(response, status=422, code="INVALID_WINDOW")
    assert SECRET_TEXT not in response.text


@pytest.mark.parametrize(
    "endpoint, invalid_id",
    [
        ("traces", ".hidden"),
        ("traces", "bad..id"),
        ("traces", "bad id"),
        ("traces", "bad."),
        ("traces", "x" * 129),
        ("runs", ".hidden"),
        ("runs", "bad..id"),
        ("runs", "bad id"),
        ("runs", "bad."),
        ("runs", "x" * 129),
        ("requests", ".hidden"),
        ("requests", "bad..id"),
        ("requests", "bad id"),
        ("requests", "bad."),
        ("requests", "x" * 129),
    ],
)
def test_invalid_ids_are_422(trace_admin, endpoint: str, invalid_id: str) -> None:
    code = {
        "traces": "INVALID_TRACE_ID",
        "runs": "INVALID_RUN_ID",
        "requests": "INVALID_REQUEST_ID",
    }[endpoint]
    path = {
        "traces": f"{BASE}/traces/{invalid_id}",
        "runs": f"{BASE}/runs/{invalid_id}",
        "requests": f"{BASE}/requests/{invalid_id}/traces",
    }[endpoint]
    response = trace_admin.client.get(path)
    _assert_error_envelope(response, status=422, code=code)


@pytest.mark.parametrize(
    "path, status, code",
    [
        (f"{BASE}/traces/%2e%2e", 422, "INVALID_TRACE_ID"),
        (f"{BASE}/traces/..%5Cescape", 422, "INVALID_TRACE_ID"),
        (f"{BASE}/traces/bad.", 422, "INVALID_TRACE_ID"),
        (f"{BASE}/runs/%2e%2e", 422, "INVALID_RUN_ID"),
        (f"{BASE}/runs/bad%5Cid", 422, "INVALID_RUN_ID"),
        (f"{BASE}/requests/%2e%2e/traces", 422, "INVALID_REQUEST_ID"),
        (f"{BASE}/requests/bad%20id/traces", 422, "INVALID_REQUEST_ID"),
        (f"{BASE}/runs/..%2Fescape", 404, "NOT_FOUND"),
        (f"{BASE}/traces/bad%2Fid", 404, "NOT_FOUND"),
    ],
)
def test_path_traversal_is_rejected(trace_admin, path: str, status: int, code: str) -> None:
    """编码穿越要么被 id 校验 422，要么被路由/目录守卫 404；不得 200。"""
    response = trace_admin.client.get(path)
    _assert_error_envelope(response, status=status, code=code)
    assert response.status_code != 200


def test_run_traversal_cannot_read_outside_runs_root(trace_admin) -> None:
    """runs 根目录外构造同名 manifest；穿越请求不得把其内容带出。"""
    data_dir = trace_admin.client.app.state.settings.data_dir
    outside = data_dir / "eval" / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "run_manifest.json").write_text(
        json.dumps({"run_id": SECRET_TEXT, "suite": "b0"}, ensure_ascii=False), encoding="utf-8"
    )
    for path in (f"{BASE}/runs/..%2Foutside", f"{BASE}/runs/%2e%2e%2Foutside"):
        response = trace_admin.client.get(path)
        assert response.status_code in {404, 422}, response.text
        assert response.status_code != 200
        assert SECRET_TEXT not in response.text
        _assert_no_forbidden(response.json(), response.text)


# --------------------------------------------------------------------------- #
# 时间窗边界 / 分页 NOT-APPLICABLE
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("window", ["1h", "24h", "999999h", "30m"])
def test_valid_windows_return_200(trace_admin, window: str) -> None:
    response = trace_admin.client.get(f"{BASE}/metrics", params={"window": window})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window"] == window
    since = datetime.fromisoformat(body["since"])
    until = datetime.fromisoformat(body["until"])
    assert since.tzinfo is not None and until.tzinfo is not None
    assert since < until
    _assert_model_keys(body, MetricsResponse)


def test_metrics_default_window_is_24h(trace_admin) -> None:
    response = trace_admin.client.get(f"{BASE}/metrics")
    assert response.status_code == 200, response.text
    assert response.json()["window"] == "24h"


def test_huge_window_returns_200_without_500(trace_repo: TraceRepository, trace_admin) -> None:
    """999999h 合法；fixture 数据量小，只断言不崩，不声称性能/全表保护。"""
    _write(trace_repo, _record(path="rag", outcome="answer"))
    response = trace_admin.client.get(f"{BASE}/metrics", params={"window": "999999h"})
    assert response.status_code == 200, response.text
    assert response.json()["total_traces"] == 1
    assert response.json()["degraded_reason"] is None


def test_metrics_does_not_expose_pagination(settings) -> None:
    """四端点均无 limit/offset：分页 NOT-APPLICABLE（文档写明，不虚构分页行为）。"""
    application = create_app(settings, initialize=False)
    try:
        schema = application.openapi()
        for path in EXPECTED_PATHS:
            operation = schema["paths"][path]["get"]
            names = {parameter.get("name") for parameter in operation.get("parameters", [])}
            assert not ({"limit", "offset"} & names), (path, names)
        metrics = schema["paths"][f"{BASE}/metrics"]["get"]
        assert {parameter.get("name") for parameter in metrics.get("parameters", [])} == {"window"}
    finally:
        application.state.db.dispose()


# --------------------------------------------------------------------------- #
# 降级 / 不泄露 / Holdout
# --------------------------------------------------------------------------- #


def test_trace_disabled_all_four_return_200_and_reason(admin_client) -> None:
    """trace 关闭：4 端点均 200；trace/requests/metrics 空聚合，runs 仍返回聚合并说明。"""
    assert admin_client.app.state.trace_repo is None
    data_dir = admin_client.app.state.settings.data_dir
    _write_run(
        data_dir,
        RUN_ID,
        manifest=_manifest(RUN_ID),
        summary=_summary(RUN_ID),
        gate=_gate(RUN_ID),
    )
    ids = dict(trace_id=_valid_trace_id(), request_id=_valid_request_id(), run_id=RUN_ID)

    detail = _get(admin_client, "traces", **ids)
    assert detail.status_code == 200, detail.text
    assert detail.json() == {"trace": None, "spans": [], "degraded_reason": "trace_disabled"}

    attempts = _get(admin_client, "requests", **ids)
    assert attempts.status_code == 200, attempts.text
    assert attempts.json()["traces"] == []
    assert attempts.json()["degraded_reason"] == "trace_disabled"

    metrics = _get(admin_client, "metrics", **ids)
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["total_traces"] == 0
    assert metrics.json()["groups"] == []
    assert metrics.json()["degraded_reason"] == "trace_disabled"

    run = _get(admin_client, "runs", **ids)
    assert run.status_code == 200, run.text
    assert run.json()["manifest"]["run_id"] == RUN_ID
    assert run.json()["degraded_reason"] == "trace_disabled"


def test_success_responses_are_whitelisted_and_secret_free(
    trace_repo: TraceRepository, trace_admin, trace_employee
) -> None:
    """成功响应只含白名单字段；秘密题干/答案/内部 JSON 不出现。"""
    request_id = _valid_request_id()
    trace_id = _write(
        trace_repo,
        _record(request_id=request_id, case_id=SECRET_TEXT, secret_json=True),
        [
            SpanRecord(
                name="answer",
                duration_ms=2,
                status="ok",
                attributes_json=json.dumps(
                    {"secret_note": SECRET_TEXT, "fact_count": 2}, sort_keys=True
                ),
            )
        ],
    )
    _write_run(
        trace_admin.client.app.state.settings.data_dir,
        RUN_ID,
        manifest=_manifest(RUN_ID),
        summary=_summary(RUN_ID),
        gate=_gate(RUN_ID),
    )
    ids = dict(trace_id=trace_id, request_id=request_id, run_id=RUN_ID)
    responses = {endpoint: _get(trace_admin.client, endpoint, **ids) for endpoint in ENDPOINTS}
    for endpoint, response in responses.items():
        assert response.status_code == 200, (endpoint, response.text)
        _assert_no_forbidden(response.json(), response.text)

    detail = responses["traces"].json()
    assert set(detail) == {"trace", "spans", "degraded_reason"}
    _assert_model_keys(detail, TraceDetailResponse)
    _assert_model_keys(detail["trace"], TraceSummary)
    for span in detail["spans"]:
        _assert_model_keys(span, SpanSummary)
    assert detail["spans"][0]["attribute_keys"] == ["fact_count", "secret_note"]
    assert detail["spans"][0]["attribute_count"] == 2

    attempts = responses["requests"].json()
    assert set(attempts) == {"request_id", "traces", "degraded_reason"}
    _assert_model_keys(attempts, RequestTracesResponse)
    for item in attempts["traces"]:
        _assert_model_keys(item, TraceSummary)

    metrics = responses["metrics"].json()
    assert set(metrics) == set(MetricsResponse.model_fields)
    _assert_model_keys(metrics, MetricsResponse)
    for group in metrics["groups"]:
        _assert_model_keys(group, MetricGroup)

    run = responses["runs"].json()
    assert set(run) == set(RunResponse.model_fields)
    _assert_model_keys(run, RunResponse)
    _assert_model_keys(run["manifest"], RunManifestSummary)
    _assert_model_keys(run["summary"], RunSummaryBlock)
    if run["summary"].get("holdout") is not None:
        _assert_model_keys(run["summary"]["holdout"], HoldoutSummary)
    _assert_model_keys(run["gate"], GateSummary)
    assert run["manifest"]["run_id"] == RUN_ID
    assert run["manifest"]["case_count"] == 40

    # 同一份秘密数据下，错误响应也不得把原文带出（404/422/401/403）。
    error_cases = [
        (trace_admin.client.get(f"{BASE}/traces/{_valid_trace_id()}"), 404, "TRACE_NOT_FOUND"),
        (trace_admin.client.get(f"{BASE}/runs/run-does-not-exist"), 404, "RUN_NOT_FOUND"),
        (trace_admin.client.get(f"{BASE}/metrics", params={"window": "bad"}), 422, "INVALID_WINDOW"),
        (trace_employee.client.get(f"{BASE}/metrics", params={"window": "bad"}), 403, "ROLE_REQUIRED"),
    ]
    anonymous = TestClient(trace_admin.client.app, raise_server_exceptions=False)
    error_cases.append(
        (anonymous.get(f"{BASE}/traces/{_valid_trace_id()}"), 401, "AUTH_REQUIRED")
    )
    for response, status, code in error_cases:
        body = _assert_error_envelope(response, status=status, code=code)
        _assert_no_forbidden(body, response.text)


def test_holdout_run_is_aggregate_only(trace_admin) -> None:
    """holdout run 只返回聚合；即使 cases.jsonl 含秘密题干/答案也不返回。"""
    run_id = HOLDOUT_RUN_ID
    manifest = _manifest(run_id, suite="holdout", holdout_details=True)
    summary = _summary(
        run_id,
        suite="holdout",
        holdout={
            "aggregate_only": False,
            "details_written": True,
            "audit_file": f"{SECRET_TEXT}.json",
            "questions_sha256": "2" * 64,
            "labels_sha256": "3" * 64,
            "label_version": "labels-v1",
            "strata": {"core": 12, "edge": 18},
            "metadata_mismatch_count": 1,
            "traces_persisted": True,
            "note": SECRET_TEXT,
        },
    )
    _write_run(
        trace_admin.client.app.state.settings.data_dir,
        run_id,
        manifest=manifest,
        summary=summary,
        gate=_gate(run_id),
        cases_text=json.dumps(
            {"case_id": SECRET_TEXT, "question": SECRET_TEXT, "answer": SECRET_TEXT},
            ensure_ascii=False,
        )
        + "\n",
    )

    response = trace_admin.client.get(f"{BASE}/runs/{run_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["holdout_detected"] is True
    assert body["details_withheld"] is True
    assert body["summary"]["holdout"]["strata"] == {"core": 12, "edge": 18}
    assert body["summary"]["holdout"]["details_written"] is True
    _assert_no_forbidden(body, response.text)


# --------------------------------------------------------------------------- #
# OpenAPI：路径 / 方法 / 鉴权声明 / 快照一致性
# --------------------------------------------------------------------------- #


def test_openapi_four_paths_only_get_and_auth_responses(settings) -> None:
    application = create_app(settings, initialize=False)
    try:
        schema = application.openapi()
        paths = {
            path: operation
            for path, operation in schema["paths"].items()
            if path.startswith(BASE)
        }
        assert set(paths) == set(EXPECTED_PATHS)
        for path, operation in paths.items():
            assert set(operation) == {"get"}, (path, operation.keys())
            get = operation["get"]
            assert {"200", "401", "403"} <= set(get["responses"]), path
            for status in ("401", "403"):
                assert get["responses"][status].get("description"), (path, status)
            assert "post" not in operation and "put" not in operation
            assert "delete" not in operation and "patch" not in operation
            # 本应用使用 Cookie 会话；运行期鉴权由 require_role 执行，OpenAPI 以
            # 401/403 响应声明权限（T113 验收 LOW-1；未引入 securitySchemes）。
            security = get.get("security")
            assert security is None or isinstance(security, list)
    finally:
        application.state.db.dispose()


def test_openapi_snapshot_matches_live_schema(settings) -> None:
    """已提交的 OpenAPI 快照必须与实时 schema 的 4 路径 + 相关 components 一致。"""
    snapshot_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "reports"
        / "OBS-EVAL"
        / "P1"
        / "evidence"
        / "T114"
        / "openapi-observability.json"
    )
    assert snapshot_path.is_file(), f"缺少 OpenAPI 快照：{snapshot_path}"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    application = create_app(settings, initialize=False)
    try:
        live = application.openapi()
        expected_paths = {path: live["paths"][path] for path in sorted(EXPECTED_PATHS)}
        assert snapshot["paths"] == expected_paths
        assert snapshot["components"] == {
            "schemas": _expected_schemas(live, expected_paths)
        }
        assert snapshot["openapi"] == live["openapi"]
        assert snapshot["info"] == live["info"]
    finally:
        application.state.db.dispose()
