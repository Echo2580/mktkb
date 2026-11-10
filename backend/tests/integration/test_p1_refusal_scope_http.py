"""P1-FIX/A 产品路径：越界财务指标在检索后、chat 前拒答（spy 证明零模型调用）。

走真实 HTTP（上传→worker→发布→问答），模型用 ``conftest.EvidenceEchoGateway`` 可控替身
（零真实调用）；``chat_model.calls`` 即调用 spy：

1. 公司级经营/财务指标（RG005/RG007 及同义改写）→ ``kind=not_found``、无来源、
   文案不冒充服务故障，且 **模型调用次数不增加**（拒答路径没有 chat 生成）；
2. 正常的已发布台账问答仍走原路径（模型被调用、有来源）；
3. 采购价格等既有“未记录字段”问题不被新的越界规则误伤。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import current_csrf, login, upload_document, write_headers
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app

ROOT = Path(__file__).resolve().parents[3]
D01 = ROOT / "fixtures" / "acceptance" / "normal" / "D01_物品位置表.xlsx"
SUPPORTED_QUESTION = "城东店的宣传海报在哪里？"
OUT_OF_SCOPE_QUESTIONS = (
    "公司今年营收是多少",
    "公司今年的利润率是多少",
    "公司今年的营业收入是多少？",
    "帮我查一下公司今年的营收数据",
    "公司今年净利润是多少？",
    "公司今年的毛利率是多少？",
)


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
def readiness_app(settings, chat_model, tmp_path: Path) -> SimpleNamespace:
    """开启 Trace 的应用 + 已发布 D01（物品位置表）；``chat_model`` 是调用 spy。"""
    trace_settings = settings.model_copy(
        update={
            "trace_enabled": True,
            "trace_db_path": tmp_path / "observability" / "qa-traces.sqlite3",
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


def _new_conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session: SimpleNamespace, conversation: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_out_of_scope_financial_question_refuses_before_any_chat_call(
    readiness_app: SimpleNamespace,
) -> None:
    session = readiness_app.employee
    calls_before = len(readiness_app.model.calls)
    for question in OUT_OF_SCOPE_QUESTIONS:
        conversation = _new_conversation(session)
        answer = _ask(session, conversation, question)
        assert answer["kind"] == "not_found", (question, answer)
        assert answer["sources"] == [], (question, answer)
        assert "没有可支撑" in answer["text"], answer["text"]
        assert "服务暂不可用" not in answer["text"], answer["text"]
        assert "MODEL_UNAVAILABLE" not in answer["text"], answer["text"]
        # spy：明确越界的拒答路径没有进入 chat 生成。
        assert len(readiness_app.model.calls) == calls_before, (
            question,
            readiness_app.model.calls[-1] if readiness_app.model.calls else None,
        )


def test_supported_ledger_question_still_uses_normal_path(readiness_app: SimpleNamespace) -> None:
    session = readiness_app.employee
    calls_before = len(readiness_app.model.calls)
    conversation = _new_conversation(session)
    answer = _ask(session, conversation, SUPPORTED_QUESTION)
    assert answer["kind"] == "answer", answer
    assert "城东店" in answer["text"] and "宣传海报" in answer["text"], answer["text"]
    assert answer["sources"], answer
    # 正向控制：正常问题仍走既有模型措辞/事实准入路径（不是把整条链路关掉）。
    assert len(readiness_app.model.calls) > calls_before, readiness_app.model.calls


def test_purchase_price_question_is_not_treated_as_financial_metric(
    readiness_app: SimpleNamespace,
) -> None:
    session = readiness_app.employee
    conversation = _new_conversation(session)
    answer = _ask(session, conversation, "宣传海报的采购价格是多少？")
    assert answer["kind"] in {"not_found", "clarification", "conflict"}, answer
    assert "经营财务数据" not in answer["text"], answer["text"]
    assert "没有可支撑" not in answer["text"], answer["text"]
