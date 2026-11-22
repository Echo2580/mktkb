"""T302 §5.3：在 tmp 隔离环境按 T301 方式重建 S01-S19，逐项对账（预期值不得改）。

样本来源：正常入口 14 条（FastAPI 链路 + 受控替身模型 ``Mock``）、故障替身缝 1 条（S09）、
受控构造 4 条（S16/S19 未提交中断、S17/S18 午夜边界，直接写隔离库）。
所有文件落在 pytest ``tmp_path``；不读仓库 ``.env``、不写 ``var/``、无付费调用。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from conftest import current_csrf, login, upload_document, write_headers
from mktkb.config import Settings
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.operations.queries import SHANGHAI
from mktkb.providers.types import ModelUnavailable

OPS = "/api/v1/operations"
REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
D03 = FIXTURES / "normal" / "D03_市场部工作指南.docx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
LEGACY_QUESTION = "领取活动物料需要哪些步骤？"

#: T301-recomputation.md 冻结预期值
EXPECTED = {
    "completed": 13,
    "distribution": {
        "answer": 8,
        "clarification": 1,
        "not_found": 1,
        "conflict": 1,
        "service_error": 1,
        "knowledge_changed": 1,
    },
    "interrupted": 2,
    "persistent_rows": 13,
    "document_pairs": 6,
    "version_pairs": 6,
    "review_required": 1,
    "active_documents": 5,
    "coverage_covered": 10,
    "coverage_total": 13,
}


class _Harness:
    """隔离应用的登录会话 + 上传/发布/问答辅助（正常接口链路）。"""

    def __init__(self, app, username: str, password: str) -> None:
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)
        login(self.client, username, password)
        csrf = current_csrf(self.client)
        self.headers = write_headers(csrf)

    def upload(self, **kwargs):
        return upload_document(self.client, csrf=self.headers["X-CSRF-Token"], **kwargs)

    def conversation(self) -> str:
        response = self.client.post("/api/v1/conversations", json={}, headers=self.headers)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def ask(self, conversation_id: str, question: str, client_request_id=None):
        payload = {
            "client_request_id": str(client_request_id or uuid.uuid4()),
            "question": question,
        }
        return self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json=payload,
            headers=self.headers,
        )

    def delete_conversation(self, conversation_id: str):
        return self.client.delete(f"/api/v1/conversations/{conversation_id}", headers=self.headers)


def _run_worker(app):
    session = app.state.db.session()
    try:
        return run_one_job(session, app.state.store)
    finally:
        session.close()


def _revision(app) -> int:
    session = app.state.db.session()
    try:
        return get_revision(session)
    finally:
        session.close()


def _publish(app, session: _Harness, document_id: str, version_id: str, expected_active=None):
    response = session.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": expected_active, "expected_revision": _revision(app)},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_published(app, admin: _Harness, **kwargs):
    receipt = admin.upload(**kwargs)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    job = _run_worker(app)
    assert job.state == "succeeded", (job.state, job.error_code)
    _publish(app, admin, record["document"]["id"], record["version"]["id"],
             kwargs.get("expected_active_version_id"))
    return record


def _conflict_xlsx(path: Path, rows) -> bytes:
    import io

    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "物品位置"
    for row in [["标识", "门店", "物品", "别名", "位置"], *rows]:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _uncached_formula_xlsx() -> bytes:
    import io

    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "无缓存公式"
    sheet.append(["=1+1", "=2+2"])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _cached_formula_xlsx() -> bytes:
    import io
    import zipfile

    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "缓存公式"
    sheet.append(["标识", "结果"])
    sheet.append(["R1", "=1+2"])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    payload = stream.getvalue()
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as src, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                assert "<f>1+2</f>" in text
                data = text.replace("<f>1+2</f>", "<f>1+2</f><v>150</v>").encode("utf-8")
            dst.writestr(item, data)
    return buffer.getvalue()


@pytest.fixture
def t301_samples(tmp_path, settings: Settings, chat_model):
    """按 T301 方式重建 S01-S19，返回 (trace 应用, 管理员客户端, 样本登记)。"""
    data_dir = tmp_path / "t301"
    storage = data_dir / "storage"
    storage.mkdir(parents=True)
    base = settings.model_copy(
        update={
            "data_dir": data_dir,
            "database_url": f"sqlite:///{(data_dir / 'mktkb.sqlite3').as_posix()}",
            "storage_dir": storage,
            "rag_index_path": data_dir / "rag-index.sqlite3",
            "rag_provider_mode": "offline",
            "rag_sync_on_startup": True,
            "ocr_disabled": True,
            "trace_enabled": True,
            "trace_db_path": data_dir / "qa-traces.sqlite3",
            "log_level": "WARNING",
        }
    )
    app = create_app(base, model_gateway=chat_model)
    app_off = None
    admin = _Harness(app, "admin", "AdminPass-1")
    employee = _Harness(app, "employee", "EmployeePass-1")
    registry: dict[str, dict] = {}

    def ask_and_record(sample_id: str, scenario: str, question: str, *,
                       conversation_id: str | None = None, client_request_id=None):
        conv = conversation_id or employee.conversation()
        response = employee.ask(conv, question, client_request_id=client_request_id)
        assert response.status_code == 200, response.text
        body = response.json()
        from mktkb.conversations.models import ConversationRequest

        session = app.state.db.session()
        try:
            row = session.get(ConversationRequest, uuid.UUID(str(body["request_id"])))
            record = {
                "sample_id": sample_id,
                "scenario": scenario,
                "conversation_id": conv,
                "request_id": str(row.id),
                "kind": body.get("kind"),
                "finished_at": row.finished_at,
                "result_message_id": str(row.result_message_id) if row.result_message_id else None,
                "conflicts": body.get("conflicts") or [],
            }
        finally:
            session.close()
        registry[sample_id] = record
        return record

    try:
        # 基线语料：位置表先发布历史 V03 作为 v1，再换版为 D01 v2。
        positions = _upload_published(app, admin, path=V03, name="T301-物品位置表.xlsx")
        stores = _upload_published(app, admin, path=D02, name="D02_合作店家信息.xlsx")
        guide = _upload_published(app, admin, path=D03, name="D03_市场部工作指南.docx")
        conflict_a = _upload_published(
            app, admin,
            content=_conflict_xlsx(D01, [["QF001", "城北店", "指示牌", None, "B区1号货架第二层"]]),
            name="T301-冲突资料A.xlsx",
        )
        conflict_b = _upload_published(
            app, admin,
            content=_conflict_xlsx(D01, [["QF001", "城北店", "指示牌", None, "D区暂存柜"]]),
            name="T301-冲突资料B.xlsx",
        )
        corpus = {
            "positions": {"document_id": positions["document"]["id"],
                          "v1": positions["version"]["id"]},
            "stores": {"document_id": stores["document"]["id"]},
            "guide": {"document_id": guide["document"]["id"], "version_id": guide["version"]["id"]},
            "conflict_a": {"document_id": conflict_a["document"]["id"]},
            "conflict_b": {"document_id": conflict_b["document"]["id"]},
        }

        ask_and_record("S11", "换版前引用历史 v1", "城东店的宣传海报在哪里？")
        v2 = _upload_published(
            app, admin, path=D01, name="T301-物品位置表.xlsx",
            document_id=corpus["positions"]["document_id"],
            expected_active_version_id=corpus["positions"]["v1"],
            allow_same_name=True,
        )
        corpus["positions"]["v2"] = v2["version"]["id"]

        ask_and_record("S12", "换版后引用生效 v2", "城东店的宣传海报在哪里？")
        ask_and_record("S01", "同文档多条引用行", "把城东店和城西店的宣传海报记录都列出来")
        replay_conv = employee.conversation()
        replay_id = uuid.uuid4()
        ask_and_record("S02", "正常带引用（单引用）", "城东店的宣传海报在哪里？",
                       conversation_id=replay_conv, client_request_id=replay_id)
        ask_and_record("S03", "未找到", "城南店联系人是谁？")
        ask_and_record("S04", "澄清", "宣传海报在哪里？")
        ask_and_record("S05", "冲突", "QF001在哪里？")
        ask_and_record("S06", "幂等重放", "城东店的宣传海报在哪里？",
                       conversation_id=replay_conv, client_request_id=replay_id)
        ask_and_record("S07", "legacy 正文作答", LEGACY_QUESTION)

        chat_model.error = ModelUnavailable("T302 对账注入：模型暂不可用")
        ask_and_record("S08", "服务错误", LEGACY_QUESTION)
        chat_model.error = None

        from mktkb.conversations import service as conversations_service
        from mktkb.retrieval.types import KnowledgeRevisionChanged

        original = conversations_service._retrieve

        def _boom(*args, **kwargs):
            raise KnowledgeRevisionChanged("T302 对账注入：revision 变化")

        conversations_service._retrieve = _boom
        try:
            ask_and_record("S09", "知识库已变更", "城东店的展架在哪里？")
        finally:
            conversations_service._retrieve = original

        deleted_conv = employee.conversation()
        ask_and_record("S10", "已删除会话", "城西店的易拉宝在哪里？", conversation_id=deleted_conv)
        assert employee.delete_conversation(deleted_conv).status_code == 204

        # S13 失败导入 / S14 待审核版本
        fail = admin.upload(content=_uncached_formula_xlsx(), name="T301-失败导入.xlsx")
        assert fail.status_code == 202, fail.text
        fail_record = fail.json()
        fail_job = _run_worker(app)
        assert fail_job.state == "failed"
        registry["S13"] = {
            "sample_id": "S13",
            "document_id": fail_record["document"]["id"],
            "version_id": fail_record["version"]["id"],
            "error_code": fail_job.error_code,
        }

        review = admin.upload(content=_cached_formula_xlsx(), name="T301-待审核版本.xlsx")
        assert review.status_code == 202, review.text
        review_record = review.json()
        review_job = _run_worker(app)
        assert review_job.state == "succeeded", (review_job.state, review_job.error_code)
        registry["S14"] = {
            "sample_id": "S14",
            "document_id": review_record["document"]["id"],
            "version_id": review_record["version"]["id"],
        }

        # S15 Trace 关闭：同一业务库，另起 trace_enabled=False 应用
        off_settings = base.model_copy(update={"trace_enabled": False, "trace_db_path": data_dir / "off-traces.sqlite3"})
        app_off = create_app(off_settings, model_gateway=chat_model)
        employee_off = _Harness(app_off, "employee", "EmployeePass-1")
        off_conv = employee_off.conversation()
        off_response = employee_off.ask(off_conv, LEGACY_QUESTION)
        assert off_response.status_code == 200, off_response.text
        registry["S15"] = {
            "sample_id": "S15",
            "conversation_id": off_conv,
            "request_id": off_response.json()["request_id"],
            "kind": off_response.json().get("kind"),
            "trace_header": off_response.headers.get("X-Trace-ID"),
        }
        admin_off = TestClient(app_off, raise_server_exceptions=False)
        login(admin_off, "admin", "AdminPass-1")

        # 受控构造：未提交中断与午夜边界（直接写隔离库，标注来源）
        from mktkb.auth.models import User
        from mktkb.conversations.models import Conversation, ConversationMessage, ConversationRequest

        session = app.state.db.session()
        try:
            employee_user = session.scalar(select(User).where(User.username == "employee"))
            now = datetime.now(timezone.utc)

            def _interrupted(sample_id: str, status: str) -> None:
                conv = Conversation(user_id=employee_user.id, title=f"T302-受控-{sample_id}",
                                    created_at=now, updated_at=now)
                session.add(conv)
                session.flush()
                message = ConversationMessage(conversation_id=conv.id, user_id=employee_user.id,
                                              seq=1, role="user", text=f"受控中断 {status}", created_at=now)
                session.add(message)
                session.flush()
                row = ConversationRequest(
                    conversation_id=conv.id, user_id=employee_user.id,
                    client_request_id=uuid.uuid4(), payload_sha256="controlled",
                    question=message.text, status=status, attempt=1,
                    user_message_id=message.id, result_message_id=None, result_json=None,
                    created_at=now, started_at=now, deadline_at=now + timedelta(seconds=30),
                    finished_at=None if status == "running" else now,
                )
                session.add(row)
                session.flush()
                registry[sample_id] = {"sample_id": sample_id, "request_id": str(row.id)}

            _interrupted("S16", "running")
            _interrupted("S19", "expired")

            def _midnight(sample_id: str, shanghai: datetime) -> None:
                finished = shanghai.astimezone(timezone.utc)
                conv = Conversation(user_id=employee_user.id, title=f"T302-受控-{sample_id}",
                                    created_at=now, updated_at=now)
                session.add(conv)
                session.flush()
                user_message = ConversationMessage(conversation_id=conv.id, user_id=employee_user.id,
                                                   seq=1, role="user", text="受控午夜边界", created_at=now)
                session.add(user_message)
                session.flush()
                assistant = ConversationMessage(conversation_id=conv.id, user_id=employee_user.id,
                                                seq=2, role="assistant", text="受控午夜边界答案",
                                                kind="answer", revision=0, created_at=finished)
                session.add(assistant)
                session.flush()
                row = ConversationRequest(
                    conversation_id=conv.id, user_id=employee_user.id,
                    client_request_id=uuid.uuid4(), payload_sha256="controlled",
                    question=user_message.text, status="succeeded", attempt=1,
                    user_message_id=user_message.id, result_message_id=assistant.id,
                    result_json={"kind": "answer", "text": assistant.text, "sources": [], "conflicts": []},
                    created_at=now, started_at=now, deadline_at=now + timedelta(seconds=30),
                    finished_at=finished,
                )
                session.add(row)
                session.flush()
                registry[sample_id] = {"sample_id": sample_id, "request_id": str(row.id)}

            _midnight("S17", datetime(2026, 11, 20, 23, 59, 59, 750000, tzinfo=SHANGHAI))
            _midnight("S18", datetime(2026, 11, 21, 0, 0, 0, 250000, tzinfo=SHANGHAI))
            session.commit()
        finally:
            session.close()

        admin_client = TestClient(app, raise_server_exceptions=False)
        login(admin_client, "admin", "AdminPass-1")
        yield app, admin_client, registry, corpus, admin_off
    finally:
        app.state.qa.close()
        app.state.db.dispose()
        if app_off is not None:
            app_off.state.qa.close()
            app_off.state.db.dispose()


def _window_params() -> dict:
    today = datetime.now(SHANGHAI).date()
    start = min(date(2026, 11, 20), today).isoformat()
    end = max(date(2026, 11, 21), today).isoformat()
    return {"since": start, "until": end}


def test_t301_reconciliation(t301_samples) -> None:
    app, admin, registry, corpus, _admin_off = t301_samples
    params = _window_params()

    overview = admin.get(f"{OPS}/overview", params=params)
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["metrics"]["completed_requests"] == EXPECTED["completed"]
    assert body["result_distribution"] == EXPECTED["distribution"]
    assert body["metrics"]["interrupted"] == EXPECTED["interrupted"]
    assert body["metrics"]["review_required_versions"] == EXPECTED["review_required"]
    assert body["metrics"]["active_documents"] == EXPECTED["active_documents"]
    assert body["trace_coverage"] == {
        "covered": EXPECTED["coverage_covered"],
        "total": EXPECTED["coverage_total"],
        "status": "partial",
        "note": "覆盖 10/13",
    }

    # 统计 = 下钻：每个计数与对应条件下列表总数逐项相等
    for kind, expected in EXPECTED["distribution"].items():
        listing = admin.get(f"{OPS}/requests", params={**params, "kind": kind}).json()["items"]
        assert len(listing) == expected, kind

    scheduled = admin.get(f"{OPS}/requests", params={**params}).json()["items"]
    assert len(scheduled) == EXPECTED["completed"]
    assert sum(item["citation_count"] for item in scheduled) == EXPECTED["document_pairs"]


def test_t301_reference_rows_and_dimension_dedup(t301_samples) -> None:
    app, admin, registry, _corpus, _admin_off = t301_samples
    session = app.state.db.session()
    try:
        from mktkb.conversations.models import Conversation, ConversationMessage, MessageSource

        rows = session.scalar(
            select(func.count()).select_from(MessageSource)
            .join(ConversationMessage, ConversationMessage.id == MessageSource.message_id)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(
                ConversationMessage.kind != "conflict",
                Conversation.deleted_at.is_(None),
            )
        )
        assert int(rows or 0) == EXPECTED["persistent_rows"]

        # S10 已删除会话的引用行仍在库（14 行），但按删除会话口径不计入统计可见行；
        # T301 冻结的 13 为“未删除会话”的非冲突引用行。
        deleted_rows = session.scalar(
            select(func.count()).select_from(MessageSource)
            .join(ConversationMessage, ConversationMessage.id == MessageSource.message_id)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(
                ConversationMessage.kind != "conflict",
                Conversation.deleted_at.is_not(None),
            )
        )
        assert int(deleted_rows or 0) == 1
        raw_rows = session.scalar(
            select(func.count()).select_from(MessageSource)
            .join(ConversationMessage, ConversationMessage.id == MessageSource.message_id)
            .where(ConversationMessage.kind != "conflict")
        )
        assert int(raw_rows or 0) == 14

        # D5：S05 冲突消息确有 2 行持久引用（提交链路现状），但不得计入最终引用
        conflict_rows = session.scalar(
            select(func.count()).select_from(MessageSource)
            .where(MessageSource.message_id == uuid.UUID(registry["S05"]["result_message_id"]))
        )
        assert int(conflict_rows or 0) == 2
    finally:
        session.close()

    pairs = 0
    for item in admin.get(f"{OPS}/requests", params=_window_params()).json()["items"]:
        detail = admin.get(f"{OPS}/requests/{item['request_id']}").json()
        pairs += len(detail["citations"])
        assert len(detail["citations"]) == detail["citation_count"]
    assert pairs == EXPECTED["document_pairs"] == EXPECTED["version_pairs"]

    # D5 查询侧口径：S05 按文档过滤命中且 conflict_flag=true，citation_count=0
    conflict_filtered = admin.get(
        f"{OPS}/requests",
        params={**_window_params(), "document_id": _corpus["conflict_a"]["document_id"]},
    ).json()["items"]
    assert [item["request_id"] for item in conflict_filtered] == [registry["S05"]["request_id"]]
    assert conflict_filtered[0]["conflict_flag"] is True
    assert conflict_filtered[0]["citation_count"] == 0

    documents = admin.get(f"{OPS}/documents", params=_window_params()).json()["items"]
    conflict_row = next(item for item in documents if item["document_id"] == _corpus["conflict_a"]["document_id"])
    assert conflict_row["final_citations"] == 0
    assert conflict_row["related_requests_count"] == 1


def test_t301_midnight_attribution_and_deleted_exclusion(t301_samples) -> None:
    app, admin, registry, _corpus, _admin_off = t301_samples

    day_before = admin.get(f"{OPS}/requests", params={"since": "2026-11-20", "until": "2026-11-20"}).json()["items"]
    assert [item["request_id"] for item in day_before] == [registry["S17"]["request_id"]]
    day_after = admin.get(f"{OPS}/requests", params={"since": "2026-11-21", "until": "2026-11-21"}).json()["items"]
    assert registry["S18"]["request_id"] in {item["request_id"] for item in day_after}
    assert registry["S17"]["request_id"] not in {item["request_id"] for item in day_after}

    overview = admin.get(
        f"{OPS}/overview", params={"since": "2026-11-20", "until": "2026-11-20"}
    ).json()
    assert overview["trend"] == [{"date": "2026-11-20", "completed": 1, "citations": 0}]

    # S10 已删除会话：统计与下钻双侧排除
    deleted_request = registry["S10"]["request_id"]
    assert deleted_request not in {item["request_id"] for item in day_after}
    assert admin.get(
        f"{OPS}/requests/{deleted_request}"
    ).status_code == 404


def test_t301_failed_import_and_pending(t301_samples) -> None:
    app, admin, registry, _corpus, _admin_off = t301_samples
    overview = admin.get(f"{OPS}/overview", params=_window_params()).json()
    imports = [item for item in overview["pending"] if item["type"] == "import"]
    assert len(imports) == 1
    assert imports[0]["error_code"] == "PARSE_INCOMPLETE"
    assert imports[0]["state"] == "failed"
    assert imports[0]["version_id"] == registry["S13"]["version_id"]

    kinds = {item["kind"] for item in overview["pending"] if item["type"] == "request"}
    assert kinds == {"not_found", "conflict", "service_error"}

    documents = admin.get(f"{OPS}/documents", params=_window_params()).json()["items"]
    failed = next(item for item in documents if item["document_id"] == registry["S13"]["document_id"])
    assert failed["latest_import"]["error_code"] == "PARSE_INCOMPLETE"
    review = next(item for item in documents if item["document_id"] == registry["S14"]["document_id"])
    assert review["current_version"]["state"] == "review_required"


def test_t301_trace_coverage_details(t301_samples) -> None:
    app, admin, registry, _corpus, admin_off = t301_samples
    overview = admin.get(f"{OPS}/overview", params=_window_params()).json()
    assert overview["trace_coverage"]["covered"] == 10
    assert overview["trace_coverage"]["total"] == 13

    # S06 与 S02 同一请求：attempt 中可辨认纯重放，且不额外增加问答量
    detail = admin.get(f"{OPS}/requests/{registry['S02']['request_id']}").json()
    assert [item["replayed"] for item in detail["trace"]["attempts"]] == [False, True]
    assert detail["trace"]["status"] == "recorded"

    # S15 关闭 Trace：在关闭 Trace 的应用上详情 disabled；在开 Trace 的应用上无行可读，
    # 只能给 not_recorded（不伪造覆盖率）。
    off_detail = admin_off.get(f"{OPS}/requests/{registry['S15']['request_id']}")
    assert off_detail.status_code == 200, off_detail.text
    assert off_detail.json()["trace"]["status"] == "disabled"
    assert off_detail.json()["trace"]["attempts"] == []
    from_on_app = admin.get(f"{OPS}/requests/{registry['S15']['request_id']}").json()
    assert from_on_app["trace"]["status"] == "not_recorded"

    # S17/S18 受控样本未写 Trace：not_recorded
    for sample in ("S17", "S18"):
        row = admin.get(f"{OPS}/requests/{registry[sample]['request_id']}").json()
        assert row["trace"]["status"] == "not_recorded"
