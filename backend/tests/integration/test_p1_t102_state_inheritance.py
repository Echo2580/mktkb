"""T102：组 A 状态继承（ERR-01/ERR-02）产品路径多轮用例。

走真实 HTTP 入口（上传→worker→发布→提问），模型用 conftest 的可控替身（只回显证据）：
- ERR-01：先问城东店宣传海报，再问「城西区」这个资料未收录的区域形态词，不得沿用城东店，
  必须澄清（本包采用 PM 口径：未知区域词澄清，不做区域→门店展开）；
- ERR-02：先问不在当前位置表中的「卓刀河店马克杯 QF21」，再问档期物料政策，不得继承上轮
  门店/物品，答案须含 W02 的 21 天且不得回显「卓刀河店」「马克杯」。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import openpyxl
import pytest

from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
W02 = ROOT / "corpus" / "enterprise-20261101" / "word" / "W02_广宣物料与道具管理办法.docx"

LEDGER_HEADERS = ["门店", "物品", "数量", "标识", "位置"]
LEDGER_ROWS = [
    ["城东店", "宣传海报", 40, "QF01", "B区1号货架第二层"],
    ["城西店", "宣传海报", 20, "QF02", "C区2号货架第一层"],
    ["卓刀河店", "礼品袋", 8, "QF31", "赠品暂存架"],
    ["城东店", "马克杯", 6, "QF32", "仓库A架"],
]


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], *, sheet: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.cell(row=1, column=1, value=f"{sheet}（T102 夹具）")
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _publish(ns, app, path: Path) -> dict:
    receipt = ns.upload(path=path)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
        revision = int(get_revision(db))
    finally:
        db.close()
    published = ns.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=ns.headers,
        json={"expected_active_version_id": None, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    return record


@pytest.fixture
def t102_ready(chat_admin, chat_employee, chat_app, tmp_path: Path):
    ledger = _xlsx(tmp_path / "t102-ledger.xlsx", LEDGER_HEADERS, LEDGER_ROWS, sheet="物品位置")
    _publish(chat_admin, chat_app, ledger)
    _publish(chat_admin, chat_app, W02)
    return {"app": chat_app, "employee": chat_employee}


def _conversation(client) -> str:
    response = client.client.post("/api/v1/conversations", json={}, headers=client.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(client, conversation: str, question: str) -> dict:
    response = client.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=client.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_err01_unknown_region_does_not_reuse_previous_store(t102_ready) -> None:
    client = t102_ready["employee"]
    conversation = _conversation(client)
    first = _ask(client, conversation, "城东店的宣传海报在哪里？")
    assert first["kind"] == "answer", first
    assert "B区1号货架第二层" in first["text"], first

    second = _ask(client, conversation, "城西区的宣传海报在哪？")
    assert second["kind"] == "clarification", second
    assert "城东店" not in second["text"], second
    assert "B区1号货架第二层" not in second["text"], second


def test_err02_policy_question_does_not_inherit_entities(t102_ready) -> None:
    client = t102_ready["employee"]
    conversation = _conversation(client)
    first = _ask(client, conversation, "卓刀河店的马克杯（标识：QF21）放在哪里？")
    assert first["kind"] == "not_found", first

    second = _ask(client, conversation, "档期物料要提前多少天提报需求？给出所有内容")
    assert second["kind"] == "answer", second
    assert "21" in second["text"], second
    assert "卓刀河店" not in second["text"], second
    assert "马克杯" not in second["text"], second
