"""T103：强制 truncated 的产品路径集成测试（真实 HTTP + 可控模型 + Trace）。

不依赖 1200 行语料：monkeypatch ``service._retrieve`` 强制返回 ``truncated=True`` 的
证据，走真实领取→意图→检索分支→短事务提交：

- 正文型（Q37 原题）：limit=100 仍 truncated → 逐词回落取正文 → 真实 answer，
  不再返回「符合条件的记录过多」零候选澄清；trace 的 ``filter_decisions_json``
  里可见降级标记，且既有必需 Span/outcome 不被破坏。
- 记录型：同一 overshoot 分支返回真实命中量 + 候选/缩小方式，候选非空。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import current_csrf, login, write_headers
from mktkb.config import Settings
from mktkb.conversations import service
from mktkb.documents.lifecycle import get_revision
from mktkb.documents.models import SourceUnit
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.observability.contracts import validate_required_spans
from mktkb.retrieval.types import Candidate, EvidenceSet

BANNED = "符合条件的记录过多"
TRACE_DB = "qa-traces.sqlite3"


def _session(app, username: str, password: str) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    login(client, username, password)
    csrf = current_csrf(client)
    return SimpleNamespace(
        client=client,
        headers=write_headers(csrf),
        upload=lambda **kwargs: client.post(
            "/api/v1/documents",
            files={"file": (Path(kwargs["path"]).name, Path(kwargs["path"]).read_bytes(), "application/octet-stream")},
            data={},
            headers=write_headers(csrf),
        ),
    )


def _ask(session: SimpleNamespace, question: str) -> tuple[object, dict]:
    created = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert created.status_code == 201, created.text
    response = session.client.post(
        f"/api/v1/conversations/{created.json()['id']}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response, response.json()


@pytest.fixture
def t103_trace_env(settings: Settings, chat_model, tmp_path: Path) -> SimpleNamespace:
    trace_settings = settings.model_copy(
        update={
            "trace_enabled": True,
            "trace_db_path": tmp_path / "observability" / TRACE_DB,
            "trace_content_mode": "hash",
        }
    )
    app = create_app(trace_settings, model_gateway=chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        source = tmp_path / "t103_material.docx"
        document = DocxDocument()
        document.add_paragraph("T103 物料领用登记说明")
        document.add_paragraph("领取活动物料需要填写领用登记表，并由负责人确认。")
        document.save(source)

        receipt = admin.upload(path=source)
        assert receipt.status_code == 202, receipt.text
        record = receipt.json()
        db = app.state.db.session()
        try:
            assert run_one_job(db, app.state.store).state == "succeeded"
            revision = int(get_revision(db))
            unit = db.scalars(
                select(SourceUnit).where(
                    SourceUnit.document_id == uuid.UUID(record["document"]["id"])
                )
            ).all()
            assert unit, "导入后应有正文单元"
            target = next(item for item in unit if "领取活动物料" in (item.text or ""))
        finally:
            db.close()
        published = admin.client.post(
            f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
            headers=admin.headers,
            json={"expected_active_version_id": None, "expected_revision": revision},
        )
        assert published.status_code == 200, published.text
        yield SimpleNamespace(app=app, admin=admin, employee=employee, unit=target)
    finally:
        repo = getattr(app.state, "trace_repo", None)
        if repo is not None:
            repo.close()
        qa = getattr(app.state, "qa", None)
        if qa is not None:
            qa.close()
        app.state.db.dispose()


def _force_truncated(monkeypatch, unit, *, record: bool) -> None:
    def fake_retrieve(db_factory, intent, revision, limit=20, *, candidate_ids=None):
        if record:
            return EvidenceSet(
                units=[unit],
                kind="ambiguous",
                total_candidates=150,
                revision=revision,
                candidates=[
                    Candidate(
                        label="滨江店的宣传海报",
                        entity_filters={"store": "滨江店", "item": "宣传海报"},
                        source_ids=(str(unit.id),),
                    )
                ],
                truncated=True,
            )
        return EvidenceSet(
            units=[unit],
            kind="matches",
            total_candidates=150,
            revision=revision,
            candidates=[],
            truncated=True,
        )

    monkeypatch.setattr(service, "_retrieve", fake_retrieve)


def _trace(env: SimpleNamespace, response) -> tuple[object, list[object]]:
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id, "开启 Trace 时 QA POST 必须返回 X-Trace-ID"
    return env.app.state.trace_repo.get(trace_id)


def test_document_overshoot_falls_back_to_body_and_marks_trace(
    t103_trace_env: SimpleNamespace, monkeypatch
) -> None:
    env = t103_trace_env
    _force_truncated(monkeypatch, env.unit, record=False)

    response, body = _ask(env.employee, "物料领用通知图片要求先填写什么？")
    assert body["kind"] == "answer", body
    assert BANNED not in body["text"]
    assert "该历史消息" not in body["text"]
    assert "登记表" in body["text"]
    assert body["sources"], body

    trace, spans = _trace(env, response)
    flags = json.loads(trace.filter_decisions_json or "{}")
    assert flags["record_overshoot_fallback"] is True
    assert flags["record_overshoot_total"] == 150
    assert flags["record_overshoot_strategy"] == "document_term_union"
    assert validate_required_spans(trace, {span.name for span in spans}) == []


def test_record_overshoot_returns_honest_count_and_candidates(
    t103_trace_env: SimpleNamespace, monkeypatch
) -> None:
    env = t103_trace_env
    _force_truncated(monkeypatch, env.unit, record=True)

    response, body = _ask(env.employee, "滨江店的宣传海报在哪里？")
    assert body["kind"] == "clarification", body
    assert BANNED not in body["text"]
    assert "150" in body["text"] and "缩小范围" in body["text"]
    assert body["candidates"] and body["candidates"][0]["label"] == "滨江店"

    trace, spans = _trace(env, response)
    flags = json.loads(trace.filter_decisions_json or "{}")
    assert flags["record_overshoot_fallback"] is True
    assert flags["record_overshoot_total"] == 150
    assert flags["record_overshoot_strategy"] == "record_candidates"
    assert validate_required_spans(trace, {span.name for span in spans}) == []
