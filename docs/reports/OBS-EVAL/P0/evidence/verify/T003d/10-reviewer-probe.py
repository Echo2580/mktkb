"""Reviewer-authored independent probe for T003d (b811f9f).

Not a delivered test. This file lives in the isolated verification copy only
(backend/tests/observability/ of the temp tree) and is copied verbatim into
docs/reports/OBS-EVAL/P0/evidence/verify/T003d/ as evidence.

It re-drives the real FastAPI app over HTTP and reads the real TraceRepository;
it does not import the delivered test bodies. Only the approved shared fixtures
(trace_chat_app / trace_app / chat_model) and three small helpers from
test_middleware (_make_settings / _close_app / _normalized) are reused.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import openpyxl
import pytest
from pydantic import SecretStr

from mktkb.conversations import service as conv_service
from mktkb.conversations.schemas import AskResult
from mktkb.documents import lifecycle
from mktkb.documents.models import KnowledgeState
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.observability import (
    OutcomeKind,
    TraceMode,
    TracePath,
    required_spans,
    start_trace,
    validate_required_spans,
)
from observability.conftest import T003D_HEADERS, T003D_ROWS, open_session
from observability.test_middleware import _close_app, _make_settings, _normalized

EARLY_QUESTIONS = ("滨江店的负责人是谁？", "滨江店宣传海报的负责人是谁？")
RAG_ENUMERATE = "把城东店和滨江店的宣传海报记录都列出来"
LEGACY_RECORD = "滨江店的宣传海报在哪里？"
EMPTY_QUESTION = "城东店的宣传海报在哪里？"


# ---- harness (reviewer re-implementation, same product endpoints) ----


def _xlsx(path: Path, rows) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="物品位置台账")
    for col, header in enumerate(T003D_HEADERS, start=1):
        ws.cell(row=6, column=col, value=header)
    for r, row in enumerate(rows):
        for c, value in enumerate(row, start=1):
            ws.cell(row=7 + r, column=c, value=value)
    wb.save(path)
    return path


def _revision(app) -> int:
    db = app.state.db.session()
    try:
        from mktkb.documents.lifecycle import get_revision
        return get_revision(db)
    finally:
        db.close()


def _upload(app, session, path: Path):
    receipt = session.upload(path=path)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
    finally:
        db.close()
    return record


def _publish(app, session, record):
    response = session.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=session.headers,
        json={"expected_active_version_id": None, "expected_revision": _revision(app)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _dataset(app, admin, rows=None, name="verify-dataset.xlsx"):
    path = _xlsx(Path(app.state.settings.data_dir) / name, rows or T003D_ROWS)
    record = _upload(app, admin, path)
    _publish(app, admin, record)
    return record


def _conversation(session) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session, conversation_id, question, client_request_id=None):
    return session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "client_request_id": str(client_request_id or uuid.uuid4()),
            "question": question,
        },
        headers=session.headers,
    )


def _trace_of(app, response):
    trace_id = response.headers["X-Trace-ID"]
    return app.state.trace_repo.get(trace_id)


def _names(spans) -> set[str]:
    return {span.name for span in spans}


def _blob(trace, spans) -> str:
    parts = [str(getattr(trace, f.name)) for f in dataclasses.fields(trace)]
    for span in spans:
        parts += [str(span.name), str(span.attributes_json), str(span.error_code)]
    return "\n".join(parts)


def _flags(trace) -> dict:
    return json.loads(trace.filter_decisions_json or "{}")


# ---- §5.1 RAG product path ----


def test_probe_s51_rag_answer(trace_chat_app):
    admin, employee = open_session(trace_chat_app, "admin", "AdminPass-1"), open_session(
        trace_chat_app, "employee", "EmployeePass-1"
    )
    _dataset(trace_chat_app, admin)
    response = _ask(employee, _conversation(employee), RAG_ENUMERATE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "answer", body
    trace, spans = _trace_of(trace_chat_app, response)
    names = _names(spans)
    assert trace.request_id == body["request_id"]
    assert trace.http_request_id == response.headers["X-Request-ID"]
    assert trace.path == "rag"
    assert trace.outcome_kind == "answer"
    assert trace.status == "ok"
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER) <= names
    assert validate_required_spans(trace, names) == []
    assert not {"intent_parse", "retrieve", "model_answer", "answer_validate"} & names
    assert trace.question_hash and len(trace.question_hash) == 64
    assert trace.hash_algo == "sha256" and trace.hmac_key_id is None
    assert trace.question_chars == len(RAG_ENUMERATE)
    assert RAG_ENUMERATE not in _blob(trace, spans)


# ---- §5.2/§5.3/§5.11 legacy early not_found (reason in trace, not in body) ----


@pytest.mark.parametrize("question", EARLY_QUESTIONS)
def test_probe_s511_legacy_early_not_found(trace_chat_app, question):
    admin, employee = open_session(trace_chat_app, "admin", "AdminPass-1"), open_session(
        trace_chat_app, "employee", "EmployeePass-1"
    )
    _dataset(trace_chat_app, admin)
    response = _ask(employee, _conversation(employee), question)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "not_found", body
    # The internal stable reason must not leak into the product response.
    assert set(body) == set(AskResult.model_fields), set(body) ^ set(AskResult.model_fields)
    assert "UNRECORDED_FIELD" not in response.text
    trace, spans = _trace_of(trace_chat_app, response)
    names = _names(spans)
    assert trace.path == "legacy"
    assert trace.outcome_kind == "not_found"
    assert trace.reason == "UNRECORDED_FIELD"
    assert names == {"intent_parse", "commit"}, names
    assert validate_required_spans(trace, names) == []
    assert trace.status == "ok"
    assert question not in _blob(trace, spans)


def test_probe_s52_legacy_retrieved_not_found_requires_retrieve(trace_app):
    """Empty DB fixed question: legacy not_found after retrieval (no early reason)."""
    employee = open_session(trace_app, "employee", "EmployeePass-1")
    response = _ask(employee, _conversation(employee), EMPTY_QUESTION)
    assert response.status_code == 200, response.text
    trace, spans = _trace_of(trace_app, response)
    names = _names(spans)
    assert trace.path == "legacy"
    assert trace.outcome_kind == "not_found"
    assert trace.reason is None
    assert {"intent_parse", "retrieve", "commit"} <= names, names
    assert validate_required_spans(trace, names) == []


def test_probe_s53_legacy_conflict_supplement_row(trace_chat_app):
    admin, employee = open_session(trace_chat_app, "admin", "AdminPass-1"), open_session(
        trace_chat_app, "employee", "EmployeePass-1"
    )
    _dataset(trace_chat_app, admin)
    _dataset(
        trace_chat_app,
        admin,
        rows=[["滨江店", "宣传海报", 40, "QF001", "D区暂存柜"]],
        name="verify-conflict.xlsx",
    )
    response = _ask(employee, _conversation(employee), LEGACY_RECORD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "conflict", body
    trace, spans = _trace_of(trace_chat_app, response)
    names = _names(spans)
    assert trace.path == "legacy_with_rag_candidates"
    assert trace.outcome_kind == "conflict"
    assert trace.reason == "CONFLICTING_VALUES"
    assert {"intent_parse", "retrieve", "commit"} <= names
    assert validate_required_spans(trace, names) == []


def test_probe_s511_commit_time_knowledge_changed_after_early_exit(trace_chat_app, monkeypatch):
    """Reachable race: a publish between claim and commit upgrades an early not_found
    to knowledge_changed *without* ever executing retrieve.

    §5.11 asks for rows '按实际执行、不伪造'. The implemented legacy+knowledge_changed
    row always requires retrieve, so this real execution shape fails integrity.
    """
    admin, employee = open_session(trace_chat_app, "admin", "AdminPass-1"), open_session(
        trace_chat_app, "employee", "EmployeePass-1"
    )
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)
    real_commit = conv_service._commit_result

    def _bump_revision_then_commit(*args, **kwargs):
        db = trace_chat_app.state.db.session()
        try:
            state = db.get(KnowledgeState, 1)
            state.revision = int(state.revision) + 1  # simulate concurrent publish
            db.commit()
        finally:
            db.close()
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(conv_service, "_commit_result", _bump_revision_then_commit)
    response = _ask(employee, conversation_id, EARLY_QUESTIONS[0])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "knowledge_changed", body
    trace, spans = _trace_of(trace_chat_app, response)
    names = _names(spans)
    print(
        "OBSERVED commit-upgrade trace:",
        "path=", trace.path,
        "outcome=", trace.outcome_kind,
        "reason=", trace.reason,
        "status=", trace.status,
        "spans=", sorted(names),
        "missing=", validate_required_spans(trace, names),
    )
    assert trace.path == "legacy"
    assert trace.outcome_kind == "knowledge_changed"
    assert names == {"intent_parse", "commit"}, names
    assert validate_required_spans(trace, names) == []


# ---- §5.7 replay ----


def test_probe_s57_replay(trace_app):
    employee = open_session(trace_app, "employee", "EmployeePass-1")
    conversation_id = _conversation(employee)
    rid = uuid.uuid4()
    first = _ask(employee, conversation_id, EMPTY_QUESTION, rid)
    first_trace, first_spans = _trace_of(trace_app, first)
    second = _ask(employee, conversation_id, EMPTY_QUESTION, rid)
    replay_trace, replay_spans = _trace_of(trace_app, second)
    print(
        "OBSERVED replay trace:",
        "status=", replay_trace.status,
        "path=", replay_trace.path,
        "outcome=", replay_trace.outcome_kind,
        "spans=", [s.name for s in replay_spans],
    )
    assert replay_trace.status == "replayed"
    assert replay_spans == []
    assert replay_trace.request_id == first_trace.request_id
    assert replay_trace.trace_id != first_trace.trace_id
    reread, reread_spans = trace_app.state.trace_repo.get(first_trace.trace_id)
    assert reread.status == "ok"
    assert [s.name for s in reread_spans] == [s.name for s in first_spans]


# ---- §5.6 index_sync only on real sync ----


def test_probe_s56_index_sync(trace_chat_app):
    admin, employee = open_session(trace_chat_app, "admin", "AdminPass-1"), open_session(
        trace_chat_app, "employee", "EmployeePass-1"
    )
    path = _xlsx(Path(trace_chat_app.state.settings.data_dir) / "verify-sync.xlsx", T003D_ROWS)
    record = _upload(trace_chat_app, admin, path)
    db = trace_chat_app.state.db.session()
    try:
        lifecycle.publish_version(
            db,
            uuid.UUID(record["document"]["id"]),
            uuid.UUID(record["version"]["id"]),
            expected_active_version_id=None,
            expected_revision=0,
        )
    finally:
        db.close()
    assert trace_chat_app.state.qa.status()["product_revision"] == 0
    conversation_id = _conversation(employee)
    first = _ask(employee, conversation_id, LEGACY_RECORD)
    t1, s1 = _trace_of(trace_chat_app, first)
    assert "index_sync" in _names(s1)
    assert _flags(t1)["index_sync_performed"] is True
    assert validate_required_spans(t1, _names(s1)) == []
    second = _ask(employee, conversation_id, LEGACY_RECORD)
    t2, s2 = _trace_of(trace_chat_app, second)
    assert "index_sync" not in _names(s2)
    assert "index_sync_performed" not in _flags(t2)
    assert validate_required_spans(t2, _names(s2)) == []


# ---- §5.4 behavior identical with trace off/on ----


def test_probe_s54_body_identical_off_on(tmp_path):
    off = _make_settings(tmp_path / "off")
    on = _make_settings(tmp_path / "on", trace_enabled=True)
    off_app, on_app = create_app(off), create_app(on)
    try:
        off_s = open_session(off_app, "employee", "EmployeePass-1")
        on_s = open_session(on_app, "employee", "EmployeePass-1")
        rid = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
        r_off = _ask(off_s, _conversation(off_s), EMPTY_QUESTION, rid)
        r_on = _ask(on_s, _conversation(on_s), EMPTY_QUESTION, rid)
        assert r_off.status_code == r_on.status_code == 200
        assert "X-Trace-ID" not in r_off.headers and r_on.headers.get("X-Trace-ID")
        assert set(r_off.json()) == set(r_on.json())
        assert _normalized(r_off.json()) == _normalized(r_on.json())
    finally:
        _close_app(off_app)
        _close_app(on_app)


# ---- §5.5 HMAC privacy ----


def test_probe_s55_hmac(trace_settings):
    key = "reviewer-hmac-key-0123456789abcdef"
    app = create_app(trace_settings.model_copy(update={"trace_hmac_key": SecretStr(key)}))
    try:
        employee = open_session(app, "employee", "EmployeePass-1")
        response = _ask(employee, _conversation(employee), EMPTY_QUESTION)
        trace, spans = _trace_of(app, response)
        assert trace.hash_algo == "hmac-sha256"
        assert trace.hmac_key_id
        assert len(trace.question_hash) == 64
        assert key not in _blob(trace, spans)
    finally:
        _close_app(app)


# ---- §5.9 RAG pre-retrieval no_answer on the real QaEngine ----


def test_probe_s59_rag_pre_retrieval_no_answer(trace_chat_app):
    trace_chat_app.state.qa.ensure_ready()  # keep index_sync out of the measured window

    class _Repo:
        def __init__(self):
            self.writes = []

        def write_best_effort(self, record, spans):
            self.writes.append((record, list(spans)))

    repo = _Repo()
    with start_trace(
        http_request_id="verify-" + uuid.uuid4().hex,
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        question="促销活动台账在哪里？",
        repo=repo,
    ) as trace:
        answer = trace_chat_app.state.qa.answer("促销活动台账在哪里？", "u-verify", "c-verify")
    record, spans = repo.writes[-1]
    names = _names(spans)
    assert answer.kind == "no_answer", answer
    assert answer.reason == "DOCUMENT_NOT_FOUND", answer
    assert record.outcome_kind == "no_answer"
    assert record.reason == "DOCUMENT_NOT_FOUND"
    assert names == {"parse", "commit"}, names
    assert validate_required_spans(record, names) == []
