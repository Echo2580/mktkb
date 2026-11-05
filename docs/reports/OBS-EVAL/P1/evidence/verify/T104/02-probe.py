"""T104 independent verification probe (not part of the deliverable).

Drives the real HTTP path with a controlled model gateway and an isolated
temporary data dir. No network, no .env, no real model.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

import conftest  # noqa: E402
from mktkb.config import Settings  # noqa: E402
from mktkb.conversations import service  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from mktkb.observability.contracts import validate_required_spans  # noqa: E402
from mktkb.providers.types import (  # noqa: E402
    CompletionOutput,
    ModelBudgetRefused,
    ModelOutputInvalid,
    ModelTimeout,
    ModelUnavailable,
)
from mktkb.qa import QaNotReady  # noqa: E402
from mktkb.retrieval.types import (  # noqa: E402
    IndexNotReady,
    KnowledgeRevisionChanged,
    QueryRejected,
)

D01 = ROOT / "fixtures" / "acceptance" / "normal" / "D01_物品位置表.xlsx"
QUESTION = "城东店的宣传海报在哪里？"
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

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""))


class ProbeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None

    async def complete(self, request, *, timeout_seconds: float) -> CompletionOutput:
        self.calls.append(request.purpose)
        if self.error is not None:
            raise self.error
        if request.purpose == "query_expansion":
            return CompletionOutput(text="expansion", query_terms=())
        parts = []
        for item in request.evidence[:8]:
            if item.fields:
                parts.append("；".join(f"{k}：{v}" for k, v in list(item.fields.items())[:12]))
            elif item.text:
                parts.append(item.text)
        return CompletionOutput(
            text="根据资料：" + "；".join(parts),
            source_ids=tuple(item.source_id for item in request.evidence),
        )


def make_session(app, username: str, password: str) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    conftest.login(client, username, password)
    csrf = conftest.current_csrf(client)
    return SimpleNamespace(
        client=client,
        csrf=csrf,
        headers=conftest.write_headers(csrf),
        upload=lambda **kwargs: conftest.upload_document(client, csrf=csrf, **kwargs),
    )


def ask(employee: SimpleNamespace, conversation: str, request_id: uuid.UUID | None = None):
    return employee.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(request_id or uuid.uuid4()), "question": QUESTION},
        headers=employee.headers,
    )


def new_conversation(employee: SimpleNamespace) -> str:
    response = employee.client.post("/api/v1/conversations", json={}, headers=employee.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def check_service_error(response, code: str, retryable: bool, gateway: ProbeGateway | None) -> dict:
    body = response.json()
    check(f"{code}: http200", response.status_code == 200, str(response.status_code))
    check(f"{code}: field-set", set(body) == ASK_FIELDS, str(sorted(set(body) ^ ASK_FIELDS)))
    check(f"{code}: kind", body.get("kind") == "service_error", str(body.get("kind")))
    check(f"{code}: code", body.get("error_code") == code, str(body.get("error_code")))
    check(f"{code}: retryable={retryable}", body.get("retryable") is retryable, str(body.get("retryable")))
    text = body.get("text", "")
    check(f"{code}: not-missing-template", ERR07_NOT_MISSING in text, text[:80])
    check(f"{code}: no-duplicate-template", ERR07_NO_DUPLICATE in text, text[:80])
    if retryable:
        check(f"{code}: retry-hint", "可稍后重新提问" in text, text[:80])
        check(f"{code}: no-hard-stop", "重试不会自行恢复" not in text, text[:80])
    else:
        check(f"{code}: no-retry-hint", "重试不会自行恢复" in text, text[:80])
        check(f"{code}: no-soft-retry", "可稍后重新提问" not in text, text[:80])
    if code != "MODEL_UNAVAILABLE":
        check(f"{code}: not-provider-code", body.get("error_code") != "MODEL_UNAVAILABLE")
    check(f"{code}: no-sources", body.get("sources") == [], str(body.get("sources"))[:80])
    trace_id = response.headers.get("X-Trace-ID")
    check(f"{code}: trace-id", bool(trace_id), str(trace_id))
    if trace_id:
        trace, spans = app.state.trace_repo.get(trace_id)
        check(f"{code}: trace-outcome", trace.outcome_kind == "service_error", str(trace.outcome_kind))
        check(
            f"{code}: trace-reason==code",
            trace.reason == body.get("error_code") == trace.error_code,
            f"{trace.reason}/{trace.error_code}/{body.get('error_code')}",
        )
        names = {span.name for span in spans}
        missing = validate_required_spans(trace, names)
        check(f"{code}: required-spans", missing == [], str(missing))
    return body


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t104-probe-"))
    store = tmp / "store"
    store.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        data_dir=store,
        database_url=f"sqlite:///{(store / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="INFO",
    ).model_copy(
        update={
            "trace_enabled": True,
            "trace_db_path": tmp / "observability" / "qa-traces.sqlite3",
            "trace_content_mode": "hash",
        }
    )
    gateway = ProbeGateway()
    global app
    app = create_app(settings, model_gateway=gateway)
    admin = make_session(app, "admin", "AdminPass-1")
    employee = make_session(app, "employee", "EmployeePass-1")
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

    # Schema identity: field set is read from the live Pydantic model.
    from mktkb.conversations.schemas import AskResult

    check("schema: 12 baseline fields", set(AskResult.model_fields) == ASK_FIELDS, str(sorted(AskResult.model_fields)))

    # ---- Provider / known gateway errors ----
    cases = [
        (ModelUnavailable("probe"), "MODEL_UNAVAILABLE", True),
        (ModelBudgetRefused("probe"), "MODEL_BUDGET_REFUSED", False),
        (ModelTimeout("probe"), "MODEL_TIMEOUT", True),
        (asyncio.TimeoutError(), "MODEL_TIMEOUT", True),
        (ModelOutputInvalid("probe"), "MODEL_OUTPUT_INVALID", True),
        (RuntimeError("local gateway boom"), "MODEL_CALL_FAILED", True),
    ]
    for error, code, retryable in cases:
        gateway.error = error
        gateway.calls.clear()
        try:
            body = check_service_error(
                ask(employee, new_conversation(employee)), code, retryable, gateway
            )
            check(f"{code}: gateway-called-once", len(gateway.calls) == 1, str(gateway.calls))
        finally:
            gateway.error = None
        if code == "MODEL_UNAVAILABLE":
            check("MODEL_UNAVAILABLE: text-prefix", body["text"].startswith("模型服务暂不可用"), body["text"][:40])
        if code == "MODEL_BUDGET_REFUSED":
            check("MODEL_BUDGET_REFUSED: mentions budget/auth/not-sent",
                  all(x in body["text"] for x in ("预算", "授权", "未发送请求")), body["text"][:90])
        if code == "MODEL_CALL_FAILED":
            check("MODEL_CALL_FAILED: names unclassified", "原因未能归类" in body["text"], body["text"][:90])

    # ---- Config: no gateway ----
    app.state.model_gateway = None
    try:
        gateway.calls.clear()
        body = check_service_error(
            ask(employee, new_conversation(employee)), "MODEL_NOT_CONFIGURED", False, gateway
        )
        check("MODEL_NOT_CONFIGURED: zero gateway calls", gateway.calls == [], str(gateway.calls))
        check("MODEL_NOT_CONFIGURED: says unconfigured", "尚未配置" in body["text"], body["text"][:60])
    finally:
        app.state.model_gateway = gateway

    # ---- Internal: local orchestration exception ----
    boom = "T104-PROBE-INTERNAL-SECRET"
    original_validate = service._validate_answer

    def broken_validate(*args, **kwargs):
        raise RuntimeError(boom)

    service._validate_answer = broken_validate
    try:
        response = ask(employee, new_conversation(employee))
        check_service_error(response, "QA_INTERNAL_ERROR", False, gateway)
        check("QA_INTERNAL_ERROR: no exception echo", boom not in response.text and "RuntimeError" not in response.text)
    finally:
        service._validate_answer = original_validate

    # ---- Idempotent replay for the new unknown code ----
    gateway.error = RuntimeError("replay-boom")
    try:
        conversation = new_conversation(employee)
        request_id = uuid.uuid4()
        first = ask(employee, conversation, request_id)
        calls = len(gateway.calls)
        replay = ask(employee, conversation, request_id)
        check("replay: same message_id", first.json()["message_id"] == replay.json()["message_id"])
        check("replay: same code", replay.json()["error_code"] == "MODEL_CALL_FAILED", str(replay.json().get("error_code")))
        check("replay: no second model call", len(gateway.calls) == calls, f"{calls}->{len(gateway.calls)}")
        history = employee.client.get(
            f"/api/v1/conversations/{conversation}/messages", headers=employee.headers
        ).json()
        check("replay: no duplicate row", history["total"] == 2, str(history["total"]))
    finally:
        gateway.error = None

    # ---- Existing domain exceptions must keep their final outcome/codes ----
    original_retrieve = service._retrieve

    def raise_domain(error):
        def _boom(*args, **kwargs):
            raise error
        return _boom

    for error, expected_kind, expected_code in [
        (KnowledgeRevisionChanged(), "knowledge_changed", None),
        (IndexNotReady("probe"), "service_error", "INDEX_NOT_READY"),
        (QueryRejected("probe"), "service_error", "INVALID_QUERY"),
    ]:
        service._retrieve = raise_domain(error)
        try:
            response = ask(employee, new_conversation(employee))
            body = response.json()
            check(
                f"domain {type(error).__name__}: kind={expected_kind}",
                body.get("kind") == expected_kind,
                str(body.get("kind")),
            )
            check(
                f"domain {type(error).__name__}: code",
                body.get("error_code") == expected_code,
                str(body.get("error_code")),
            )
            if expected_code:
                check(
                    f"domain {type(error).__name__}: retryable unchanged",
                    body.get("retryable") is (expected_code == "INDEX_NOT_READY"),
                    str(body.get("retryable")),
                )
        finally:
            service._retrieve = original_retrieve

    # QaNotReady from qa.prepare (outside the T104 blocks) keeps INDEX_NOT_READY.
    qa = app.state.qa
    original_prepare = qa.prepare
    qa.prepare = lambda *a, **k: (_ for _ in ()).throw(QaNotReady("probe"))
    try:
        response = ask(employee, new_conversation(employee))
        body = response.json()
        check("domain QaNotReady: kind", body.get("kind") == "service_error", str(body.get("kind")))
        check("domain QaNotReady: code", body.get("error_code") == "INDEX_NOT_READY", str(body.get("error_code")))
        check("domain QaNotReady: retryable", body.get("retryable") is True, str(body.get("retryable")))
    finally:
        qa.prepare = original_prepare

    # ---- cleanup ----
    qa_obj = getattr(app.state, "qa", None)
    if qa_obj is not None:
        qa_obj.close()
    repo = getattr(app.state, "trace_repo", None)
    if repo is not None:
        repo.close()
    app.state.db.dispose()

    failed = [item for item in results if not item[1]]
    print(f"\nSUMMARY {len(results) - len(failed)}/{len(results)} checks passed; {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
