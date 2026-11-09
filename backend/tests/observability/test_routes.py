"""T113：只读监控 API 验收测试（设计 §6 / handoff §3）。

覆盖：

- admin 200 ×4；employee 403；未登录 401；
- Trace 关闭时四个端点 200 降级（``degraded_reason="trace_disabled"``），不 500；
- trace / run 不存在 404；非法 window / trace_id / run_id 422；
- metrics 按 path/outcome 聚合的 count、P50/P95、tokens、cost、degraded；
- 响应无问题/答案原文、无 ``*_json`` 原文、无路径/凭据字段；
- holdout run 只返回聚合与 ``details_withheld``，不返回逐题/题干/答案；
- OpenAPI 含 4 条路径且仅 GET；``initialize=False`` 不写目录；
- 只读：请求前后 trace 库与 run 产物哈希不变。

全部数据来自 ``tmp_path``（应用 fixture 的临时数据目录）；零真实模型 / OCR /
embedding / rerank 调用；不读 ``.env``、不访问外网、不触碰 ``var/`` 或 ``docs/evidence``。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import ORIGIN
from mktkb.config import Settings
from mktkb.main import create_app
from mktkb.observability.contracts import SpanRecord, TraceRecord
from mktkb.observability.store import TraceRepository
from observability.conftest import open_session

BASE = "/api/v1/observability"
#: 响应里绝不允许出现的原文字段名（问题/答案/上下文/逐题/路径/内部 JSON）。
FORBIDDEN_KEYS = frozenset(
    {
        "question",
        "question_text",
        "answer",
        "answer_text",
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
    }
)
SECRET_TEXT = "SECRET-QUESTION-ANSWER-CONTEXT-NEVER-RETURNED"


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #


def _now(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat(
        timespec="milliseconds"
    )


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
    token_usage: Mapping[str, object] | None = None,
    cost: Mapping[str, object] | None = None,
    degraded: object | None = None,
    token_usage_raw: str | None = None,
    cost_raw: str | None = None,
) -> TraceRecord:
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
        token_usage_json=(
            token_usage_raw
            if token_usage_raw is not None
            else None if token_usage is None else json.dumps(token_usage, sort_keys=True)
        ),
        cost_json=(
            cost_raw
            if cost_raw is not None
            else None if cost is None else json.dumps(cost, sort_keys=True)
        ),
        degraded_json=None if degraded is None else json.dumps(degraded, sort_keys=True),
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
        "trace_store": "traces.sqlite3",
        "dataset_path": "C:/secret/dataset.jsonl",
        "corpus_dir": "C:/secret/corpus",
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
        "metrics_scope": {"excluded_error_case_ids": ["CASE-SECRET-001"]},
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
        "failures": [{"gate_id": "quality", "case_id": "CASE-SECRET-001", "evidence": {"text": SECRET_TEXT}}],
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_trace_id() -> str:
    return uuid.uuid4().hex


def _valid_request_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# admin 200 ×4 / 响应结构
# --------------------------------------------------------------------------- #


def test_admin_can_read_all_four_endpoints(trace_repo: TraceRepository, trace_admin) -> None:
    request_id = _valid_request_id()
    trace_id = _write(
        trace_repo,
        _record(request_id=request_id, token_usage={"input": 10, "output": 5}, cost={"cny": 0.01}),
        [SpanRecord(name="parse", duration_ms=1, status="ok", attributes_json='{"chars": 4}')],
    )
    run_id = "b0-local-20261101-abcdef12"
    _write_run(
        trace_admin.client.app.state.settings.data_dir,
        run_id,
        manifest=_manifest(run_id),
        summary=_summary(run_id),
        gate=_gate(run_id),
    )

    detail = trace_admin.client.get(f"{BASE}/traces/{trace_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["trace"]["trace_id"] == trace_id
    assert body["trace"]["question_hash"] == "a" * 64
    assert body["trace"]["question_chars"] == 42
    assert body["trace"]["span_count"] == 1
    assert body["spans"][0]["name"] == "parse"
    assert body["spans"][0]["attribute_keys"] == ["chars"]

    attempts = trace_admin.client.get(f"{BASE}/requests/{request_id}/traces")
    assert attempts.status_code == 200, attempts.text
    assert [item["attempt"] for item in attempts.json()["traces"]] == [1]

    metrics = trace_admin.client.get(f"{BASE}/metrics", params={"window": "24h"})
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["total_traces"] == 1

    run = trace_admin.client.get(f"{BASE}/runs/{run_id}")
    assert run.status_code == 200, run.text
    assert run.json()["manifest"]["run_id"] == run_id
    assert run.json()["summary"]["status_counts"]["pass"] == 29
    assert run.json()["gate"]["exit_code"] == 3


# --------------------------------------------------------------------------- #
# 权限矩阵（employee 403 / 未登录 401）
# --------------------------------------------------------------------------- #


def test_employee_is_forbidden_on_all_four(
    trace_repo: TraceRepository, trace_employee
) -> None:
    request_id = _valid_request_id()
    trace_id = _write(trace_repo, _record(request_id=request_id))
    run_id = "b0-local-20261101-abcdef12"
    _write_run(
        trace_employee.client.app.state.settings.data_dir,
        run_id,
        manifest=_manifest(run_id),
    )

    for path in (
        f"{BASE}/traces/{trace_id}",
        f"{BASE}/requests/{request_id}/traces",
        f"{BASE}/metrics?window=24h",
        f"{BASE}/runs/{run_id}",
    ):
        response = trace_employee.client.get(path)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["error"]["code"] == "ROLE_REQUIRED"


def test_unauthenticated_is_rejected(trace_app) -> None:
    anonymous = TestClient(trace_app, raise_server_exceptions=False)
    response = anonymous.get(f"{BASE}/metrics?window=24h")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


# --------------------------------------------------------------------------- #
# Trace 关闭降级（200，不 500）
# --------------------------------------------------------------------------- #


def test_trace_disabled_returns_empty_aggregate_and_reason(admin_client) -> None:
    assert admin_client.app.state.trace_repo is None
    run_id = "b0-local-20261101-abcdef12"
    _write_run(
        admin_client.app.state.settings.data_dir,
        run_id,
        manifest=_manifest(run_id),
        summary=_summary(run_id),
        gate=_gate(run_id),
    )
    request_id = _valid_request_id()
    trace_id = _valid_trace_id()

    detail = admin_client.get(f"{BASE}/traces/{trace_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json() == {
        "trace": None,
        "spans": [],
        "degraded_reason": "trace_disabled",
    }

    attempts = admin_client.get(f"{BASE}/requests/{request_id}/traces")
    assert attempts.status_code == 200, attempts.text
    assert attempts.json()["traces"] == []
    assert attempts.json()["degraded_reason"] == "trace_disabled"

    metrics = admin_client.get(f"{BASE}/metrics", params={"window": "24h"})
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["total_traces"] == 0
    assert metrics.json()["groups"] == []
    assert metrics.json()["degraded_reason"] == "trace_disabled"

    run = admin_client.get(f"{BASE}/runs/{run_id}")
    assert run.status_code == 200, run.text
    assert run.json()["manifest"]["run_id"] == run_id
    assert run.json()["degraded_reason"] == "trace_disabled"


# --------------------------------------------------------------------------- #
# 404 / 422
# --------------------------------------------------------------------------- #


def test_missing_trace_and_run_are_404(trace_admin) -> None:
    missing_trace = trace_admin.client.get(f"{BASE}/traces/{_valid_trace_id()}")
    assert missing_trace.status_code == 404
    assert missing_trace.json()["error"]["code"] == "TRACE_NOT_FOUND"

    missing_run = trace_admin.client.get(f"{BASE}/runs/run-does-not-exist")
    assert missing_run.status_code == 404
    assert missing_run.json()["error"]["code"] == "RUN_NOT_FOUND"


@pytest.mark.parametrize("window", ["abc", "0h", "24", "1.5h", "h", "-1h", "24d", "1H", " 24h"])
def test_invalid_window_is_422(trace_admin, window: str) -> None:
    response = trace_admin.client.get(f"{BASE}/metrics", params={"window": window})
    assert response.status_code == 422, (window, response.text)
    assert response.json()["error"]["code"] == "INVALID_WINDOW"


@pytest.mark.parametrize("run_id", [".hidden", "bad..id", "bad id", "x" * 129])
def test_invalid_run_id_is_422(trace_admin, run_id: str) -> None:
    response = trace_admin.client.get(f"{BASE}/runs/{run_id}")
    assert response.status_code == 422, (run_id, response.text)
    assert response.json()["error"]["code"] == "INVALID_RUN_ID"


@pytest.mark.parametrize("run_id", ["..", "run/../escape"])
def test_run_id_path_traversal_is_rejected(trace_admin, run_id: str) -> None:
    """客户端会把 ``..`` 规范化掉；无论 404 还是 422，都不得读到 runs 根目录之外。"""
    response = trace_admin.client.get(f"{BASE}/runs/{run_id}")
    assert response.status_code in {404, 422}, (run_id, response.text)
    assert response.status_code != 200


@pytest.mark.parametrize("trace_id", [".hidden", "bad..id", "bad id", "x" * 129])
def test_invalid_trace_id_is_422(trace_admin, trace_id: str) -> None:
    response = trace_admin.client.get(f"{BASE}/traces/{trace_id}")
    assert response.status_code == 422, (trace_id, response.text)
    assert response.json()["error"]["code"] == "INVALID_TRACE_ID"


def test_trace_id_path_traversal_is_rejected(trace_admin) -> None:
    response = trace_admin.client.get(f"{BASE}/traces/..")
    assert response.status_code in {404, 422}
    assert response.status_code != 200


# --------------------------------------------------------------------------- #
# metrics 聚合正确性
# --------------------------------------------------------------------------- #


def _seed_metrics(repo: TraceRepository, request_id: str) -> None:
    for latency, cost in ((10, 0.1), (20, 0.2), (30, 0.3), (40, 0.4)):
        _write(
            repo,
            _record(
                request_id=request_id,
                path="rag",
                outcome="answer",
                latency_ms=latency,
                token_usage={"input": 100, "output": 20, "total_tokens": 120},
                cost={"cny": cost},
                degraded=["vector_disabled"] if latency in {20, 40} else None,
            ),
        )
    _write(
        repo,
        _record(
            request_id=request_id,
            path="legacy",
            outcome="not_found",
            latency_ms=5,
            token_usage=None,
            cost=None,
        ),
    )
    _write(
        repo,
        _record(
            request_id=request_id,
            path="rag",
            outcome="error",
            status="error",
            latency_ms=50,
            token_usage={"input": 1, "output": 2},
            cost={"cost_cny": 0.5},
        ),
    )
    # 解析失败的数据：不能 500，必须计入 degraded/无效计数。
    _write(
        repo,
        _record(
            request_id=request_id,
            path="rag",
            outcome="no_answer",
            latency_ms=None,
            token_usage_raw="{not-json",
        ),
    )
    _write(
        repo,
        _record(
            request_id=request_id,
            path="rag",
            outcome="ambiguity",
            created_at="not-a-timestamp",
        ),
    )


def test_metrics_aggregates_count_percentiles_tokens_cost_degraded(
    trace_repo: TraceRepository, trace_admin
) -> None:
    request_id = _valid_request_id()
    _seed_metrics(trace_repo, request_id)

    response = trace_admin.client.get(f"{BASE}/metrics", params={"window": "24h"})
    assert response.status_code == 200, response.text
    body = response.json()
    groups = {(item["path"], item["outcome"]): item for item in body["groups"]}

    answer = groups[("rag", "answer")]
    assert answer["count"] == 4
    assert answer["latency_samples"] == 4
    assert answer["latency_ms_p50"] == 20  # 最近秩：ceil(0.5*4)=2 → 第 2 个
    assert answer["latency_ms_p95"] == 40  # 最近秩：ceil(0.95*4)=4 → 第 4 个
    assert answer["tokens_input"] == 400
    assert answer["tokens_output"] == 80
    assert answer["tokens_total"] == 480
    assert answer["cost_cny"] == pytest.approx(1.0)
    assert answer["degraded_count"] == 2
    assert answer["error_count"] == 0

    not_found = groups[("legacy", "not_found")]
    assert not_found["count"] == 1
    assert not_found["latency_ms_p50"] == 5
    assert not_found["latency_ms_p95"] == 5
    assert not_found["tokens_total"] == 0
    assert not_found["cost_cny"] == 0.0

    error = groups[("rag", "error")]
    assert error["count"] == 1
    assert error["error_count"] == 1
    assert error["tokens_input"] == 1
    assert error["tokens_output"] == 2
    assert error["tokens_total"] == 3
    assert error["cost_cny"] == pytest.approx(0.5)

    assert body["total_traces"] == 7
    assert body["invalid_created_at_count"] == 1
    assert body["invalid_payload_count"] == 1
    assert body["degraded_reason"] == "partial_data"


def test_metrics_window_filters_old_traces(trace_repo: TraceRepository, trace_admin) -> None:
    _write(
        trace_repo,
        _record(path="rag", outcome="answer", created_at=_now(-2 * 3600)),
    )
    _write(
        trace_repo,
        _record(path="legacy", outcome="answer", created_at=_now()),
    )

    hour = trace_admin.client.get(f"{BASE}/metrics", params={"window": "1h"})
    assert hour.status_code == 200, hour.text
    assert hour.json()["total_traces"] == 1
    assert hour.json()["groups"][0]["path"] == "legacy"

    day = trace_admin.client.get(f"{BASE}/metrics", params={"window": "24h"})
    assert day.status_code == 200, day.text
    assert day.json()["total_traces"] == 2


# --------------------------------------------------------------------------- #
# 无原文 / 无内部字段
# --------------------------------------------------------------------------- #


def test_responses_never_contain_question_answer_or_internal_json(
    trace_repo: TraceRepository, trace_admin
) -> None:
    request_id = _valid_request_id()
    trace_id = _write(
        trace_repo,
        _record(
            request_id=request_id,
            token_usage={"input": 3, "output": 2},
            cost={"cny": 0.01},
            degraded=["vector_disabled"],
        ),
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
    run_id = "b0-local-20261101-abcdef12"
    _write_run(
        trace_admin.client.app.state.settings.data_dir,
        run_id,
        manifest=_manifest(run_id),
        summary=_summary(run_id),
        gate=_gate(run_id),
    )

    responses = [
        trace_admin.client.get(f"{BASE}/traces/{trace_id}"),
        trace_admin.client.get(f"{BASE}/requests/{request_id}/traces"),
        trace_admin.client.get(f"{BASE}/metrics", params={"window": "24h"}),
        trace_admin.client.get(f"{BASE}/runs/{run_id}"),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        _assert_no_forbidden(response.json(), response.text)

    # span 只给属性键名/个数，不给属性值。
    span = responses[0].json()["spans"][0]
    assert span["attribute_keys"] == ["fact_count", "secret_note"]
    assert span["attribute_count"] == 2


# --------------------------------------------------------------------------- #
# Holdout：只聚合，不逐题
# --------------------------------------------------------------------------- #


def test_holdout_run_is_aggregate_only(trace_admin) -> None:
    run_id = "holdout-local-20261101-abcdef12"
    manifest = _manifest(run_id, suite="holdout", holdout_details=True)
    summary = _summary(
        run_id,
        suite="holdout",
        holdout={
            "aggregate_only": False,
            "details_written": True,
            "audit_file": "holdout_audit.json",
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
            {"case_id": "HOLDOUT-CASE-001", "question": SECRET_TEXT, "answer": SECRET_TEXT},
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
    assert "HOLDOUT-CASE-001" not in response.text
    _assert_no_forbidden(body, response.text)


def test_holdout_aggregate_run_is_not_marked_as_withheld(trace_admin) -> None:
    run_id = "holdout-local-20261101-abcdef12"
    manifest = _manifest(run_id, suite="holdout", holdout_details=False)
    summary = _summary(
        run_id,
        suite="holdout",
        holdout={
            "aggregate_only": True,
            "details_written": False,
            "label_version": "labels-v1",
            "strata": {"core": 30},
            "traces_persisted": False,
        },
    )
    _write_run(
        trace_admin.client.app.state.settings.data_dir,
        run_id,
        manifest=manifest,
        summary=summary,
    )

    response = trace_admin.client.get(f"{BASE}/runs/{run_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["holdout_detected"] is True
    assert body["details_withheld"] is False
    assert body["summary"]["holdout"]["aggregate_only"] is True
    _assert_no_forbidden(body, response.text)


# --------------------------------------------------------------------------- #
# OpenAPI / initialize=False / 只读
# --------------------------------------------------------------------------- #


def test_openapi_contains_four_get_paths(settings: Settings) -> None:
    application = create_app(settings, initialize=False)
    try:
        schema = application.openapi()
        paths = schema["paths"]
        expected = {
            f"{BASE}/traces/{{trace_id}}",
            f"{BASE}/requests/{{request_id}}/traces",
            f"{BASE}/metrics",
            f"{BASE}/runs/{{run_id}}",
        }
        assert expected <= set(paths)
        for path in expected:
            operation = paths[path]
            assert set(operation) >= {"get"}
            assert "post" not in operation and "put" not in operation and "delete" not in operation
            assert "401" in operation["get"]["responses"]
            assert "403" in operation["get"]["responses"]
    finally:
        application.state.db.dispose()


def test_initialize_false_does_not_write_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "must-not-exist"
    database = tmp_path / "explicit.sqlite3"
    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{database.as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
    )
    application = create_app(settings, initialize=False)
    try:
        schema = application.openapi()
        assert f"{BASE}/metrics" in schema["paths"]
        assert not data_dir.exists(), "initialize=False 的 OpenAPI 检查不得写数据目录"
    finally:
        application.state.db.dispose()


def test_endpoints_are_read_only_and_do_not_change_files(
    trace_repo: TraceRepository, trace_admin
) -> None:
    request_id = _valid_request_id()
    trace_id = _write(trace_repo, _record(request_id=request_id))
    run_id = "b0-local-20261101-abcdef12"
    data_dir = trace_admin.client.app.state.settings.data_dir
    run_dir = _write_run(
        data_dir,
        run_id,
        manifest=_manifest(run_id),
        summary=_summary(run_id),
        gate=_gate(run_id),
    )
    trace_db = Path(trace_admin.client.app.state.settings.resolved_trace_db_path)
    files = [trace_db, run_dir / "run_manifest.json", run_dir / "summary.json", run_dir / "gate.json"]
    before = {path: (_sha256(path), path.stat().st_mtime_ns) for path in files}

    for path in (
        f"{BASE}/traces/{trace_id}",
        f"{BASE}/requests/{request_id}/traces",
        f"{BASE}/metrics?window=24h",
        f"{BASE}/runs/{run_id}",
    ):
        response = trace_admin.client.get(path)
        assert response.status_code == 200, response.text

    after = {path: (_sha256(path), path.stat().st_mtime_ns) for path in files}
    assert before == after, "只读端点不得写 trace 库或 run 产物"


def test_malformed_run_json_does_not_500(trace_admin, tmp_path: Path) -> None:
    run_id = "run-malformed"
    run_dir = trace_admin.client.app.state.settings.data_dir / "eval" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text("{not-json", encoding="utf-8")

    response = trace_admin.client.get(f"{BASE}/runs/{run_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["manifest"] is None
    assert body["degraded_reason"] == "manifest_invalid"


def test_trace_unavailable_repo_degrades_without_500(trace_app, trace_repo) -> None:
    """仓储已关闭（库不可用）时读端点返回 200 + trace_unavailable，不 500。"""
    admin = open_session(trace_app, "admin", "AdminPass-1")
    trace_repo.close()

    detail = admin.client.get(f"{BASE}/traces/{_valid_trace_id()}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["degraded_reason"] == "trace_unavailable"

    metrics = admin.client.get(f"{BASE}/metrics", params={"window": "24h"})
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["degraded_reason"] == "trace_unavailable"
