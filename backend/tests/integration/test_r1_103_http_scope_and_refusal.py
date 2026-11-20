"""T-R1-103：M3（三回合门店范围）与 M5（位置+对接+合同/结算账号拒答）走产品 HTTP 路径。

序列与 102b/102c 的 RAG 层红例**同形**，但这里每一步都是产品入口
``POST /api/v1/conversations/{id}/messages`` 的真实响应：

- M3：甲店立牌位置 -> 换话题（调拨审批，无实体/无记录字段）-> 裸追问（不再提门店）。
  修复后第三回合只能出甲店记录；同一序列里显式点名乙店必须能答出乙区（可达性对照）。
- M5：位置 + 由谁对接 + 完整合同/结算账号 -> 整体拒答，正文不得出现联系人/电话/地址/
  凭据值；同一句只问位置+对接人（不含凭据词）必须继续作答（不扩大拒答面对照）。

全部合成数据；``t09_network_guard`` 校验出站尝试为 0。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import openpyxl
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ITEM_HEADERS = ["门店", "物品", "位置"]
ITEM_ROWS = [
    ["甲店", "立牌", "甲区"],
    ["乙店", "立牌", "乙区"],
]
STORE_HEADERS = ["标识", "店家", "联系人", "电话", "地址", "合作状态", "结算账号"]
STORE_ROWS = [
    ["SA", "甲店", "甲某", "010-55550000", "示例路18号", "合作中", "SEQ-0001"],
    ["SB", "乙店", "乙某", "010-55550001", "示例路26号", "合作中", "SEQ-0002"],
]

TURN_SCOPE = "甲店的立牌位置在哪？"
TURN_TOPIC = "调拨需要谁同意？"
TURN_BARE = "立牌现在放在哪个货架？"
TURN_OTHER_STORE = "乙店的立牌放在哪？"
PAYMENT_QUESTION = "甲店立牌放在哪，由谁对接，完整合同和结算账号是多少？"
LOCATION_CONTACT_QUESTION = "甲店立牌放在哪，由谁对接？"

LEAK_VALUES = (
    "甲某",
    "乙某",
    "010-55550000",
    "010-55550001",
    "示例路18号",
    "示例路26号",
    "SEQ-0001",
    "SEQ-0002",
    "甲区",
)


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], title: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _ingest(app, admin) -> None:
    for name, headers, rows, title in (
        ("物品位置表.xlsx", ITEM_HEADERS, ITEM_ROWS, "物品位置表"),
        ("合作店家信息.xlsx", STORE_HEADERS, STORE_ROWS, "合作店家信息"),
    ):
        path = _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, title)
        receipt = admin.upload(path=path)
        assert receipt.status_code == 202, receipt.text
        record = receipt.json()
        db = app.state.db.session()
        try:
            assert run_one_job(db, app.state.store).state == "succeeded"
        finally:
            db.close()
        db = app.state.db.session()
        try:
            revision = get_revision(db)
        finally:
            db.close()
        published = admin.client.post(
            f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
            headers=admin.headers,
            json={"expected_active_version_id": None, "expected_revision": revision},
        )
        assert published.status_code == 200, published.text


def _new_conversation(session) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session, conversation_id: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _source_rows(body: dict) -> set[int]:
    return {
        int(item["locator"]["row"])
        for item in body.get("sources") or []
        if isinstance(item.get("locator"), dict) and isinstance(item["locator"].get("row"), int)
    }


# --------------------------------------------------------------------------- #
# M3：三回合（甲店 -> 换话题 -> 裸追问）只出甲店记录
# --------------------------------------------------------------------------- #


def test_m3_bare_followup_after_topic_turn_stays_on_first_store(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    _ingest(chat_app, chat_admin)
    conversation_id = _new_conversation(chat_employee)

    first = _ask(chat_employee, conversation_id, TURN_SCOPE)
    assert first["kind"] == "answer", first
    assert "甲区" in first["text"], first["text"]
    assert _source_rows(first) == {4}, first["sources"]

    topic = _ask(chat_employee, conversation_id, TURN_TOPIC)
    assert topic["kind"] != "service_error", topic

    third = _ask(chat_employee, conversation_id, TURN_BARE)
    assert third["kind"] == "answer", third
    assert "甲区" in third["text"], third["text"]
    assert "乙区" not in third["text"], "裸追问不得混入另一门店的记录"
    assert _source_rows(third) == {4}, third["sources"]

    # 可达性对照：同一序列里显式点名乙店必须答出乙区（乙区并非不可达）。
    other_conversation = _new_conversation(chat_employee)
    _ask(chat_employee, other_conversation, TURN_SCOPE)
    _ask(chat_employee, other_conversation, TURN_TOPIC)
    other = _ask(chat_employee, other_conversation, TURN_OTHER_STORE)
    assert other["kind"] == "answer", other
    assert "乙区" in other["text"] and "甲区" not in other["text"], other["text"]
    assert _source_rows(other) == {5}, other["sources"]


# --------------------------------------------------------------------------- #
# M5：位置 + 对接 + 合同/结算账号 -> 拒答且正文无联系人值
# --------------------------------------------------------------------------- #


def test_m5_contract_and_settlement_account_question_is_refused_over_http(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    _ingest(chat_app, chat_admin)
    conversation_id = _new_conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, PAYMENT_QUESTION)

    assert body["kind"] == "not_found", body
    assert body["sources"] == [], body["sources"]
    assert "受限" in body["text"], body["text"]
    for leaked in LEAK_VALUES:
        assert leaked not in body["text"], (leaked, body["text"])


def test_m5_location_plus_contact_only_still_answers(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    """不扩大拒答面：同一句去掉凭据词后仍是合法多字段题。"""
    _ingest(chat_app, chat_admin)
    conversation_id = _new_conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, LOCATION_CONTACT_QUESTION)

    assert body["kind"] == "answer", body
    assert "甲区" in body["text"], body["text"]
    for leaked in ("SEQ-0001", "SEQ-0002"):
        assert leaked not in body["text"], (leaked, body["text"])
