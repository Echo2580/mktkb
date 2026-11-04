"""S2-A：产品 HTTP 问答链路接入 rag 内核的端到端检查（离线/Mock，无真实供应商）。

覆盖：登录身份下的枚举/分页、追问/澄清恢复/话题切换、跨用户状态隔离、发布/替换/删除的
索引生命周期、按需同步（绕过发布钩子也不静默用旧索引）、重启后索引与会话保留、
索引不可用时的明确可重试错误。

所有模型调用使用 ``conftest.EvidenceEchoGateway``；嵌入/重排使用 rag 的离线确定性替身。
本文件证明产品接线与保护，不代表真实模型效果。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi.testclient import TestClient

from conftest import ORIGIN, current_csrf, login, probe_router, write_headers, upload_document
from mktkb.auth.service import create_account
from mktkb.config import Settings
from mktkb.documents import lifecycle
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.qa import QaEngine, QaNotReady
from mktkb.rag import RagConfig


HEADERS = ["门店", "物品", "数量", "标识", "位置"]
# 位置型问题走模型措辞时，证据里只放模型可核对的字段（多列会让“只回显证据”的替身
# 带上未请求的值，被既有事实准入拒绝——这是产品保护，不是缺陷）。
LOCATION_HEADERS = ["门店", "物品", "位置"]


def _xlsx(
    path: Path,
    rows: list[list[object]],
    *,
    sheet: str = "台账",
    header_row: int = 6,
    headers: list[str] | None = None,
) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.cell(row=1, column=1, value=f"{sheet}台账")
    for column, header in enumerate(headers or HEADERS, start=1):
        worksheet.cell(row=header_row, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=header_row + 1 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _session(app, username: str, password: str) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    login(client, username, password)
    csrf = current_csrf(client)
    return SimpleNamespace(client=client, csrf=csrf, headers=write_headers(csrf))


def _revision(app) -> int:
    db = app.state.db.session()
    try:
        from mktkb.documents.lifecycle import get_revision

        return get_revision(db)
    finally:
        db.close()


def _upload_and_worker(app, session: SimpleNamespace, path: Path, *, document_id=None) -> dict:
    receipt = upload_document(session.client, csrf=session.csrf, path=path, document_id=document_id)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
    finally:
        db.close()
    return record


def _publish(app, admin: SimpleNamespace, record: dict, *, expected_active=None, expected_revision=None) -> dict:
    response = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin.headers,
        json={
            "expected_active_version_id": expected_active,
            "expected_revision": _revision(app) if expected_revision is None else expected_revision,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _ask(session: SimpleNamespace, conversation_id: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def qa_settings(settings: Settings) -> Settings:
    settings.rag_page_size = 2
    settings.rag_top_k = 5
    return settings


@pytest.fixture
def qa_app(qa_settings: Settings, chat_model):
    application = create_app(qa_settings, model_gateway=chat_model)
    application.include_router(probe_router)
    yield application
    qa = application.state.qa
    if qa is not None:
        qa.close()
    application.state.db.dispose()


@pytest.fixture
def qa_admin(qa_app) -> SimpleNamespace:
    return _session(qa_app, "admin", "AdminPass-1")


@pytest.fixture
def qa_employee(qa_app) -> SimpleNamespace:
    return _session(qa_app, "employee", "EmployeePass-1")


@pytest.fixture
def qa_employee2(qa_app, qa_employee) -> SimpleNamespace:
    db = qa_app.state.db.session()
    try:
        create_account(
            db,
            username="employee2",
            password="EmployeePass-2",
            display_name="演示员工二",
            role="employee",
            rounds=4,
        )
    finally:
        db.close()
    return _session(qa_app, "employee2", "EmployeePass-2")


def _publish_positions(qa_app, qa_admin, qa_employee, tmp_path: Path, rows) -> tuple[dict, str]:
    path = _xlsx(tmp_path / f"positions-{uuid.uuid4().hex}.xlsx", rows)
    record = _upload_and_worker(qa_app, qa_admin, path)
    _publish(qa_app, qa_admin, record)
    return record, _conversation(qa_employee)


def test_enumeration_and_pagination_go_through_rag_without_model(qa_app, qa_admin, qa_employee):
    """完整枚举/分页由 rag 作答：不调用模型，返回产品来源与分页信息。"""
    _publish_positions(
        qa_app,
        qa_admin,
        qa_employee,
        Path(qa_app.state.settings.data_dir),
        [
            ["城东店", "宣传海报", 3, "P01", "B区1号货架第二层"],
            ["城西店", "宣传海报", 4, "P02", "C区2号货架第一层"],
            ["城北店", "宣传海报", 5, "P03", "A区2号货架底层"],
        ],
    )
    calls_before = len(qa_app.state.model_gateway.calls)
    conversation = _conversation(qa_employee)
    first = _ask(qa_employee, conversation, "把城东店和城西店的宣传海报记录都列出来")
    assert first["kind"] == "answer", first
    assert first["sources"], first
    assert {source["document_name"] for source in first["sources"]}
    assert first["pagination"] is not None, first
    assert first["pagination"]["page"] == 1
    assert first["pagination"]["page_size"] == 2
    assert first["pagination"]["total"] == 2
    assert first["pagination"]["has_more"] is False
    assert len(qa_app.state.model_gateway.calls) == calls_before, "枚举由 rag 结构化作答，不应调用模型"
    # 引用必须能回到具体工作表/行，而不是文件级标签
    for source in first["sources"]:
        assert source["locator"].get("sheet") == "台账"
        assert str(source["locator"].get("row")).isdigit()

    page_one = _ask(qa_employee, conversation, "把城东店、城西店和城北店的宣传海报记录都列出来")
    assert page_one["kind"] == "answer", page_one
    assert page_one["pagination"]["total"] == 3
    assert page_one["pagination"]["has_more"] is True
    assert page_one["pagination"]["next_page"] == 2
    page_two = _ask(qa_employee, conversation, "下一页")
    assert page_two["kind"] == "answer", page_two
    assert page_two["pagination"]["page"] == 2
    assert page_two["pagination"]["total"] == 3
    assert page_two["pagination"]["has_more"] is False
    assert page_two["sources"], "分页第二页仍需真实来源"
    assert page_two["sources"][0]["source_id"] not in {item["source_id"] for item in page_one["sources"]}
    # 状态持久化在 (user, conversation) 键上
    state = qa_app.state.qa.load_state(str(qa_employee_user_id(qa_app)), conversation)
    assert state.enumerate is True and state.page == 2


def qa_employee_user_id(app) -> str:
    db = app.state.db.session()
    try:
        from mktkb.auth.models import User

        return str(db.query(User).filter(User.username == "employee").one().id)
    finally:
        db.close()


def test_clarification_restore_and_topic_switch_use_persisted_state(qa_app, qa_admin, qa_employee):
    """澄清槽补齐由 rag 状态机完成；明确换话题后旧条件被重置。"""
    base = Path(qa_app.state.settings.data_dir)
    path = _xlsx(
        base / "contacts.xlsx",
        [
            ["城东店", "宣传海报", "模拟联系人·陈宁"],
            ["城西店", "宣传海报", "模拟联系人·王平"],
        ],
        headers=["门店", "物品", "联系人"],
    )
    record = _upload_and_worker(qa_app, qa_admin, path)
    _publish(qa_app, qa_admin, record)
    conversation = _conversation(qa_employee)
    calls_before = len(qa_app.state.model_gateway.calls)
    opening = _ask(qa_employee, conversation, "联系人是谁？")
    assert opening["kind"] == "clarification", opening
    assert opening["candidates"], opening
    stored = qa_app.state.qa.load_state(str(qa_employee_user_id(qa_app)), conversation)
    assert stored.pending_slot == "store", stored.to_dict()

    resolved = _ask(qa_employee, conversation, "城东店")
    assert resolved["kind"] == "answer", resolved
    assert "模拟联系人·陈宁" in resolved["text"], resolved
    assert resolved["sources"], resolved
    assert len(qa_app.state.model_gateway.calls) == calls_before, "澄清补齐由 rag 结构化作答"

    # 话题切换：换成另一实体+字段后，旧枚举/澄清条件不再沿用
    switched = _ask(qa_employee, conversation, "换成城西店的位置是什么？")
    assert switched["kind"] in {"answer", "service_error", "not_found"}, switched
    state = qa_app.state.qa.load_state(str(qa_employee_user_id(qa_app)), conversation)
    assert state.pending_slot is None
    assert state.store == "城西店"


def test_same_user_state_isolated_across_conversations_and_users(qa_app, qa_admin, qa_employee, qa_employee2):
    """查询状态按 (user_id, conversation_id) 隔离：不会跨会话/跨用户串页。"""
    _publish_positions(
        qa_app,
        qa_admin,
        qa_employee,
        Path(qa_app.state.settings.data_dir),
        [
            ["城东店", "宣传海报", 3, "P01", "B区1号货架第二层"],
            ["城西店", "宣传海报", 4, "P02", "C区2号货架第一层"],
            ["城北店", "宣传海报", 5, "P03", "A区2号货架底层"],
        ],
    )
    conversation_a = _conversation(qa_employee)
    conversation_b = _conversation(qa_employee)
    page_one = _ask(qa_employee, conversation_a, "把城东店、城西店和城北店的宣传海报记录都列出来")
    assert page_one["pagination"]["next_page"] == 2
    # 另一个会话没有枚举状态：不能说“下一页”就从别人的第 1 页继续
    other = _ask(qa_employee, conversation_b, "下一页")
    assert other["kind"] != "answer" or other["sources"] == [] or other["pagination"] is None, other
    employee_id = qa_employee_user_id(qa_app)
    employee2_id = _user_id(qa_app, "employee2")
    state_a = qa_app.state.qa.load_state(employee_id, conversation_a)
    state_other_user = qa_app.state.qa.load_state(employee2_id, conversation_a)
    assert state_a.enumerate is True
    assert state_other_user.enumerate is False and state_other_user.turn == 0
    # 其他用户在自己的会话里问下一页：不会拿到 employee 的状态
    conversation2 = _conversation(qa_employee2)
    response = _ask(qa_employee2, conversation2, "下一页")
    assert response.get("pagination") is None, response


def _user_id(app, username: str) -> str:
    db = app.state.db.session()
    try:
        from mktkb.auth.models import User

        return str(db.query(User).filter(User.username == username).one().id)
    finally:
        db.close()


def test_publish_replace_delete_invalidate_index_and_sources(qa_app, qa_admin, qa_employee):
    """发布/替换/删除后索引同步：新版本可答、旧值不再作为事实引用、删除后不可见。"""
    base = Path(qa_app.state.settings.data_dir)
    first_path = _xlsx(
        base / "positions-v1.xlsx",
        [["城东店", "宣传海报", "B区1号货架第二层"]],
        headers=LOCATION_HEADERS,
    )
    record = _upload_and_worker(qa_app, qa_admin, first_path)
    _publish(qa_app, qa_admin, record)
    conversation = _conversation(qa_employee)
    before = _ask(qa_employee, conversation, "城东店的宣传海报在哪里？")
    assert before["kind"] == "answer" and "B区1号货架第二层" in before["text"], before
    assert before["sources"][0]["version_number"] == 1

    # 同一资料的第二个版本：内容替换
    second_path = _xlsx(
        base / "positions-v2.xlsx",
        [["城东店", "宣传海报", "D区暂存柜"]],
        headers=LOCATION_HEADERS,
    )
    second = _upload_and_worker(qa_app, qa_admin, second_path, document_id=record["document"]["id"])
    _publish(qa_app, qa_admin, second, expected_active=record["version"]["id"])
    after = _ask(qa_employee, conversation, "城东店的宣传海报在哪里？")
    assert after["kind"] == "answer" and "D区暂存柜" in after["text"], after
    assert "B区1号货架第二层" not in after["text"]
    assert after["sources"][0]["version_number"] == 2

    # 删除资料：索引同步后不可再答，也不残留旧来源
    revision = _revision(qa_app)
    deleted = qa_admin.client.delete(
        f"/api/v1/documents/{record['document']['id']}?expected_revision={revision}",
        headers=qa_admin.headers,
    )
    assert deleted.status_code == 200, deleted.text
    gone = _ask(qa_employee, conversation, "城东店的宣传海报在哪里？")
    assert gone["kind"] == "not_found", gone
    assert gone["sources"] == []
    status = qa_app.state.qa.status()
    assert status["ready"] is True
    assert status["documents"] == 0


def test_index_syncs_on_demand_when_publish_hook_is_bypassed(qa_app, qa_admin, qa_employee):
    """绕过发布钩子直接改产品库后，首次查询按 revision 同步，不能用旧索引作答。"""
    base = Path(qa_app.state.settings.data_dir)
    path = _xlsx(
        base / "positions-direct.xlsx",
        [["城东店", "宣传海报", "B区1号货架第二层"]],
        headers=LOCATION_HEADERS,
    )
    record = _upload_and_worker(qa_app, qa_admin, path)
    # 直接调用生命周期发布，不经过 HTTP 路由的索引同步钩子
    db = qa_app.state.db.session()
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
    assert qa_app.state.qa.status()["product_revision"] == 0, "钩子被绕过时索引应仍是旧的"
    conversation = _conversation(qa_employee)
    answer = _ask(qa_employee, conversation, "城东店的宣传海报在哪里？")
    assert answer["kind"] == "answer" and "B区1号货架第二层" in answer["text"], answer
    assert qa_app.state.qa.status()["product_revision"] == 1


def test_index_unavailable_returns_retryable_error_not_stale_answer(qa_app, qa_admin, qa_employee, monkeypatch):
    """索引不可用时返回可重试 INDEX_NOT_READY，不静默走旧索引或旧检索。"""
    base = Path(qa_app.state.settings.data_dir)
    path = _xlsx(
        base / "positions-unavailable.xlsx",
        [["城东店", "宣传海报", "B区1号货架第二层"]],
        headers=LOCATION_HEADERS,
    )
    record = _upload_and_worker(qa_app, qa_admin, path)
    _publish(qa_app, qa_admin, record)
    conversation = _conversation(qa_employee)
    qa = qa_app.state.qa

    def _boom(*_args, **_kwargs):
        raise QaNotReady("索引同步失败", error_code="INDEX_SYNC_FAILED")

    monkeypatch.setattr(qa, "ensure_ready", _boom)
    response = _ask(qa_employee, conversation, "城东店的宣传海报在哪里？")
    assert response["kind"] == "service_error", response
    assert response["error_code"] == "INDEX_NOT_READY", response
    assert response["retryable"] is True
    assert response["sources"] == []

    monkeypatch.undo()
    recovered = _ask(qa_employee, conversation, "城东店的宣传海报在哪里？")
    assert recovered["kind"] == "answer" and recovered["sources"], recovered


def test_restart_keeps_index_and_query_state(qa_settings, chat_model, tmp_path):
    """重启（新 app、同一数据/索引路径）后索引与枚举状态仍在：第 2 页可继续。"""
    app1 = create_app(qa_settings, model_gateway=chat_model)
    try:
        admin = _session(app1, "admin", "AdminPass-1")
        employee = _session(app1, "employee", "EmployeePass-1")
        base = Path(qa_settings.data_dir)
        path = _xlsx(base / "positions-restart.xlsx", [
            ["城东店", "宣传海报", 3, "P01", "B区1号货架第二层"],
            ["城西店", "宣传海报", 4, "P02", "C区2号货架第一层"],
            ["城北店", "宣传海报", 5, "P03", "A区2号货架底层"],
        ])
        record = _upload_and_worker(app1, admin, path)
        _publish(app1, admin, record)
        conversation = _conversation(employee)
        page_one = _ask(employee, conversation, "把城东店、城西店和城北店的宣传海报记录都列出来")
        assert page_one["pagination"]["next_page"] == 2, page_one
        revision = _revision(app1)
    finally:
        app1.state.qa.close()
        app1.state.db.dispose()

    app2 = create_app(qa_settings, model_gateway=chat_model)
    try:
        employee2 = _session(app2, "employee", "EmployeePass-1")
        assert _revision(app2) == revision
        page_two = _ask(employee2, conversation, "下一页")
        assert page_two["kind"] == "answer", page_two
        assert page_two["pagination"]["page"] == 2
        assert page_two["pagination"]["total"] == 3
        assert page_two["sources"], "重启后引用仍需回到持久来源"
        # 会话历史也保留：同一个会话已有两轮助手消息
        history = employee2.client.get(f"/api/v1/conversations/{conversation}/messages")
        assert history.status_code == 200
        assistant = [item for item in history.json()["items"] if item["role"] == "assistant"]
        assert len(assistant) == 2
    finally:
        app2.state.qa.close()
        app2.state.db.dispose()


def test_document_question_keeps_model_path_with_rag_state(qa_app, qa_admin, qa_employee):
    """正文型问题仍走模型措辞（Mock），但同一会话的 rag 状态已持久化。"""
    from docx import Document as DocxDocument

    base = Path(qa_app.state.settings.data_dir)
    document = DocxDocument()
    document.add_heading("工作指南", level=1)
    document.add_paragraph("活动执行前需要先确认物料清单并登记。")
    docx_path = base / "guide.docx"
    document.save(docx_path)
    record = _upload_and_worker(qa_app, qa_admin, docx_path)
    _publish(qa_app, qa_admin, record)
    conversation = _conversation(qa_employee)
    response = _ask(qa_employee, conversation, "活动执行前需要做什么？")
    assert response["kind"] in {"answer", "not_found"}, response
    assert qa_app.state.model_gateway.calls, "正文型问题应仍调用受控模型替身"
    state = qa_app.state.qa.load_state(str(qa_employee_user_id(qa_app)), conversation)
    assert state.turn == 1


def test_qa_status_and_config_are_secret_free(qa_app):
    status = qa_app.state.qa.status()
    body = json.dumps(status, ensure_ascii=False)
    assert status["provider_mode"] == "offline"
    assert status["db_path"].endswith("rag-index.sqlite3")
    for marker in ("DASHSCOPE", "api_key", "Authorization", "sk-"):
        assert marker not in body


# ---------------------------------------------------------------- 启动配置 / 缓存 / 降级


def test_rag_disabled_keeps_existing_pipeline_and_creates_no_index(qa_settings, chat_model):
    qa_settings.rag_qa_enabled = False
    app = create_app(qa_settings, model_gateway=chat_model)
    try:
        assert app.state.qa is None
        assert not (Path(qa_settings.data_dir) / "rag-index.sqlite3").exists()
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        path = _xlsx(
            Path(qa_settings.data_dir) / "disabled.xlsx",
            [["城东店", "宣传海报", "B区1号货架第二层"]],
            headers=LOCATION_HEADERS,
        )
        record = _upload_and_worker(app, admin, path)
        _publish(app, admin, record)
        conversation = _conversation(employee)
        answer = _ask(employee, conversation, "城东店的宣传海报在哪里？")
        assert answer["kind"] == "answer", answer
        assert chat_model.calls, "关闭 rag 时应走既有模型链路"
    finally:
        app.state.db.dispose()


def test_live_provider_without_budget_entry_is_refused(qa_settings, monkeypatch):
    for key in (
        "MKTKB_RAG_BUDGET_LEDGER",
        "MKTKB_RAG_BUDGET_JSON",
        "MKTKB_RAG_STAGE_LIMIT_CNY",
        "MKTKB_RAG_MAX_REQUESTS",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    qa_settings.rag_provider_mode = "live"
    with pytest.raises(ValueError, match="rag live"):
        create_app(qa_settings)


def test_embedding_cache_key_includes_content_model_dimensions_and_index_version(monkeypatch):
    from mktkb.rag import index as rag_index

    base = rag_index._cache_key("sha-content", "text-embedding-v4", 1024, "mock")
    assert base != rag_index._cache_key("sha-other", "text-embedding-v4", 1024, "mock")
    assert base != rag_index._cache_key("sha-content", "text-embedding-v5", 1024, "mock")
    assert base != rag_index._cache_key("sha-content", "text-embedding-v4", 768, "mock")
    assert base != rag_index._cache_key("sha-content", "text-embedding-v4", 1024, "other")
    monkeypatch.setattr(rag_index, "INDEX_CACHE_VERSION", "s2-a-test-next")
    assert base != rag_index._cache_key("sha-content", "text-embedding-v4", 1024, "mock")


class _FailingEmbedder:
    provider = "mock-failing"
    model = "text-embedding-v4"
    dimensions = 1024

    def embed(self, texts, *, purpose="document"):
        raise RuntimeError("EMBEDDING_DOWN")


def test_degraded_embedding_is_explicit_then_retry_recovers(qa_settings, chat_model):
    from mktkb.rag import RagConfig
    from mktkb.rag.providers import FakeEmbeddingProvider

    app = create_app(qa_settings, model_gateway=chat_model)
    try:
        app.state.qa.close()
        degraded_index = Path(qa_settings.data_dir) / "rag-degraded.sqlite3"
        app.state.qa = QaEngine(
            app.state.db,
            degraded_index,
            config=RagConfig(
                provider_mode="offline",
                data_dir=Path(qa_settings.data_dir),
                page_size=2,
                top_k=5,
            ),
            embedder=_FailingEmbedder(),
            embedding_retry_seconds=0,
        )
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        path = _xlsx(
            Path(qa_settings.data_dir) / "degraded.xlsx",
            [["城东店", "宣传海报", "B区1号货架第二层"]],
            headers=LOCATION_HEADERS,
        )
        record = _upload_and_worker(app, admin, path)
        _publish(app, admin, record)
        status = app.state.qa.status()
        assert status["ready"] is True
        assert status["degraded"] == ["embedding_error"], status
        assert status["error_code"], status
        conversation = _conversation(employee)
        answer = _ask(employee, conversation, "城东店的宣传海报在哪里？")
        assert answer["kind"] == "answer", answer
        assert "B区1号货架第二层" in answer["text"]

        # 供应商恢复后：补齐缺失向量，状态回到 ready（不是静默继续 degraded）
        app.state.qa.index().embedder = FakeEmbeddingProvider(model="text-embedding-v4", dimensions=1024)
        recovered = app.state.qa.ensure_ready()
        assert recovered.degraded == (), recovered
        assert app.state.qa.status()["error_code"] is None
    finally:
        app.state.qa.close()
        app.state.db.dispose()
