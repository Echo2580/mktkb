"""S2-B：D-IA-1 编号定位 / D-IA-2 裸门店追问的最小回归（离线/Mock，无真实供应商）。

用正常 HTTP 入口（登录→上传→worker→发布→提问）验证：
- 同门店同物品多行时，问题里的标识能唯一定位正确行；未知标识/门店物品与标识冲突必须拒绝；
- 多义候选携带能收敛的约束，选择后真的收敛；删除行后旧标识不可用；
- 裸门店追问保留上一轮的物品与所问字段；换物品/门店级字段不错误继承。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from conftest import EvidenceEchoGateway, current_csrf, login, write_headers
from mktkb.config import Settings
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app

ORIGIN = "http://testserver"
LEDGER_HEADERS = ["门店", "物品", "数量", "标识", "位置"]
LEDGER_ROWS = [
    ["湖滨店", "展架", 31, "IB-201", "A区一层"],
    ["江湾店", "展架", 32, "IB-202", "A区二层"],
    ["梧桐店", "展架", 33, "IB-203", "A区三层"],
    ["湖滨店", "展架", 34, "IB-204", "A区四层"],
    ["江湾店", "展架", 35, "IB-205", "A区二层"],
    ["湖滨店", "礼品袋", 88, "IB-901", "B区一层"],
    ["梧桐店", "礼品袋", 89, "IB-902", "B区三层"],
]
DUP_ROWS = [
    ["江湾店", "立牌", 41, "IB-777", "C区一层"],
    ["梧桐店", "立牌", 42, "IB-777", "C区二层"],
]
STORE_HEADERS = ["门店", "联系人", "联系电话", "地址", "合作状态"]
STORE_ROWS = [
    ["湖滨店", "周敏", "021-5000-0001", "湖滨路1号", "合作中"],
    ["江湾店", "钱伟", "021-5000-0002", "江湾路2号", "合作中"],
    ["梧桐店", "孙岚", "021-5000-0003", "梧桐路3号", "暂停"],
]


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], *, sheet: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.cell(row=1, column=1, value=f"{sheet}（S2-B 夹具）")
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


@pytest.fixture
def b_settings(tmp_path: Path) -> Settings:
    root = tmp_path / "store"
    return Settings(
        _env_file=None,
        data_dir=root,
        database_url=f"sqlite:///{(root / 'b.sqlite3').as_posix()}",
        storage_dir=root / "storage",
        cookie_secure=False,
        csrf_secret="s2b-test-csrf-secret-0123456789",
        admin_password="S2bAdminPass-1",
        employee_password="S2bEmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
        rag_page_size=5,
        rag_top_k=8,
    )


@pytest.fixture
def b_app(b_settings: Settings):
    gateway = EvidenceEchoGateway()
    app = create_app(b_settings, model_gateway=gateway)
    app.state.test_gateway = gateway
    try:
        yield app
    finally:
        app.state.qa.close()
        app.state.db.dispose()


def _session(app, username: str, password: str):
    client = TestClient(app, raise_server_exceptions=False)
    login(client, username, password)
    return client, write_headers(current_csrf(client))


def _publish(app, admin, headers, path: Path, *, document_id: str | None = None) -> dict:
    url = "/api/v1/documents" if document_id is None else f"/api/v1/documents/{document_id}/versions"
    with path.open("rb") as handle:
        receipt = admin.post(
            url,
            files={"file": (path.name, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=headers,
        )
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
        revision = int(get_revision(db))
    finally:
        db.close()
    expected_active = None
    if document_id:
        detail = admin.get(f"/api/v1/documents/{document_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        expected_active = ((detail.json().get("document") or {}).get("active_version") or {}).get("id")
    published = admin.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=headers,
        json={"expected_active_version_id": expected_active, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    return record


def _conversation(client) -> str:
    response = client.post("/api/v1/conversations", json={}, headers=write_headers(_csrf(client)))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _csrf(client) -> str:
    return current_csrf(client)


def _ask(client, conversation: str, question: str) -> dict:
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=write_headers(_csrf(client)),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _rows(payload: dict) -> list[int]:
    return sorted(
        {
            (source.get("locator") or {}).get("row")
            for source in payload.get("sources") or []
            if (source.get("locator") or {}).get("row")
        }
    )


@pytest.fixture
def b_fixture(b_settings: Settings, b_app):
    admin, admin_headers = _session(b_app, "admin", b_settings.admin_password)
    base = Path(b_settings.data_dir)
    ledger = _publish(b_app, admin, admin_headers, _xlsx(base / "ledger.xlsx", LEDGER_HEADERS, LEDGER_ROWS, sheet="台账"))
    _publish(b_app, admin, admin_headers, _xlsx(base / "dup.xlsx", LEDGER_HEADERS, DUP_ROWS, sheet="重号表"))
    _publish(b_app, admin, admin_headers, _xlsx(base / "store.xlsx", STORE_HEADERS, STORE_ROWS, sheet="门店联系表"))
    employee, _ = _session(b_app, "employee", b_settings.employee_password)
    return {"app": b_app, "admin": admin, "admin_headers": admin_headers,
            "employee": employee, "ledger": ledger, "base": base}


def test_identifier_locates_the_unique_row(b_fixture):
    client = b_fixture["employee"]
    for question in ("湖滨店的展架 IB-201 在哪里？", "IB-201 在哪里？", "标识 IB-201 的位置是什么？"):
        payload = _ask(client, _conversation(client), question)
        assert payload["kind"] == "answer", (question, payload)
        assert _rows(payload) == [4], (question, payload)
        assert "A区一层" in payload["text"], (question, payload)


def test_unknown_identifier_and_conflicting_scope_are_refused(b_fixture):
    client = b_fixture["employee"]
    unknown = _ask(client, _conversation(client), "标识 IB-999 的位置是什么？")
    assert unknown["kind"] == "not_found", unknown
    assert not unknown["sources"], unknown
    # 门店/物品组合与标识冲突：IB-202 属于江湾店，不能拿它回答湖滨店
    conflict = _ask(client, _conversation(client), "湖滨店的展架 IB-202 在哪里？")
    assert conflict["kind"] == "not_found", conflict
    assert not conflict["sources"], conflict


def test_ambiguous_identifier_candidates_converge(b_fixture):
    client = b_fixture["employee"]
    conversation = _conversation(client)
    opening = _ask(client, conversation, "标识 IB-777 在哪里？")
    assert opening["kind"] == "clarification", opening
    followups = [item["followup_question"] for item in opening["candidates"]]
    assert followups, opening
    resolved = _ask(client, conversation, followups[0])
    assert resolved["kind"] == "answer", resolved
    assert "C区一层" in resolved["text"], resolved
    assert _rows(resolved) == [4], resolved


def test_multi_row_candidates_carry_identifier_and_converge(b_fixture):
    client = b_fixture["employee"]
    conversation = _conversation(client)
    opening = _ask(client, conversation, "湖滨店的展架在哪里？")
    assert opening["kind"] == "clarification", opening
    followups = [item["followup_question"] for item in opening["candidates"]]
    assert any("IB-201" in item for item in followups), followups
    resolved = _ask(client, conversation, next(item for item in followups if "IB-201" in item))
    assert resolved["kind"] == "answer", resolved
    assert _rows(resolved) == [4], resolved


def test_replaced_identifier_is_no_longer_available(b_fixture):
    app, admin, headers = b_fixture["app"], b_fixture["admin"], b_fixture["admin_headers"]
    v2_rows = [row for row in LEDGER_ROWS if row[3] != "IB-201"]
    _publish(
        app,
        admin,
        headers,
        _xlsx(b_fixture["base"] / "ledger-v2.xlsx", LEDGER_HEADERS, v2_rows, sheet="台账"),
        document_id=b_fixture["ledger"]["document"]["id"],
    )
    client = b_fixture["employee"]
    old = _ask(client, _conversation(client), "IB-201 在哪里？")
    assert old["kind"] == "not_found", old
    assert not old["sources"], old
    kept = _ask(client, _conversation(client), "IB-204 在哪里？")
    assert kept["kind"] == "answer", kept
    assert "A区四层" in kept["text"], kept


def test_bare_store_followup_keeps_item_and_field(b_fixture):
    client = b_fixture["employee"]
    conversation = _conversation(client)
    opening = _ask(client, conversation, "展架的数量是多少？")
    assert opening["kind"] == "answer", opening
    fill = _ask(client, conversation, "湖滨店")
    assert fill["kind"] == "answer", fill
    assert set(_rows(fill)) == {4, 7}, fill
    assert "88" not in fill["text"] and "礼品袋" not in fill["text"], fill


def test_item_switch_and_store_level_field_reset_slots(b_fixture):
    client = b_fixture["employee"]
    conversation = _conversation(client)
    assert _ask(client, conversation, "展架的数量是多少？")["kind"] == "answer"
    switched = _ask(client, conversation, "礼品袋的数量是多少？")
    assert switched["kind"] == "answer", switched
    assert set(_rows(switched)) == {9, 10}, switched
    assert "31" not in switched["text"] and "展架" not in switched["text"], switched

    conversation = _conversation(client)
    assert _ask(client, conversation, "展架的数量是多少？")["kind"] == "answer"
    phone = _ask(client, conversation, "湖滨店的电话是多少？")
    assert phone["kind"] == "answer", phone
    assert set(_rows(phone)) == {4}, phone
    assert "021-5000-0001" in phone["text"], phone
    assert "展架" not in phone["text"], phone


def test_bare_store_after_store_level_field_keeps_field(b_fixture):
    client = b_fixture["employee"]
    conversation = _conversation(client)
    assert _ask(client, conversation, "湖滨店的电话是多少？")["kind"] == "answer"
    follow = _ask(client, conversation, "江湾店")
    assert follow["kind"] == "answer", follow
    assert set(_rows(follow)) == {5}, follow
    assert "021-5000-0002" in follow["text"], follow
    assert "立牌" not in follow["text"] and "展架" not in follow["text"], follow
