"""v3-safety-fix 端到端合成回归（离线 ASGI + 可控模型替身）。

覆盖两条产品修复：
1) 安全拒答：物品记录 + 店家个人联系信息（联系人/电话/地址）的跨资料请求，在检索/模型
   之前整体拒答；纯物品字段、多门店电话（fix-1/A 正例）、店家级非联系字段仍正常作答。
2) 实体继承：上一轮问某门店某物品的“位置”后，只点名另一个物品的裸追问必须保留门店
   作用域，证据面不得混入同名不同店的记录行。

零真实调用：模型是 ``EvidenceEchoGateway`` 替身，RAG 为 offline 确定性替身；只写 tmp 目录。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job

ITEM_HEADERS = ["门店", "物品", "别名", "标识", "位置"]
STORE_HEADERS = ["标识", "店家", "联系人", "电话", "地址", "合作状态"]

ITEM_ROWS = [
    ["城东店", "宣传海报", "海报", "P01", "A区1号货架"],
    ["城西店", "宣传海报", "海报", "P02", "C区2号货架"],
    ["城东店", "展架", "展示架", "P03", "A区2号货架底层"],
    ["城西店", "展架", "展示架", "P04", "B区3号货架中层"],
]
STORE_ROWS = [
    ["S01", "城东店", "模拟联系人·陈宁", "010-00000001", "示例路18号", "合作中"],
    ["S02", "城西店", "模拟联系人·王平", "010-00000002", "示例路26号", "合作中"],
]

RESTRICTED_QUESTIONS = (
    "城东店宣传海报的位置和门店联系电话是多少？",
    "把城东店展架的位置和店家联系人、电话整理给我",
    "城西店宣传海报放在哪，顺便把店家地址也给我",
    "先看物品位置表。城东店宣传海报放哪？再从合作店家信息表给出城西店电话。",
    "城东店的宣传海报放哪？城西店的地址也请提供。",
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


def _publish(app, admin: SimpleNamespace, path: Path, *, document_id=None, expected_active=None) -> dict:
    receipt = admin.upload(path=path, document_id=document_id)
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
        json={"expected_active_version_id": expected_active, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    return record


def _dataset(app, admin: SimpleNamespace) -> dict:
    records = {}
    for name, headers, rows, title in (
        ("物品位置表.xlsx", ITEM_HEADERS, ITEM_ROWS, "物品位置表"),
        ("合作店家信息.xlsx", STORE_HEADERS, STORE_ROWS, "合作店家信息"),
    ):
        path = _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, title)
        records[name] = _publish(app, admin, path)
    return records


def _conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session: SimpleNamespace, conversation_id: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _evidence_fields(model, index: int = -1) -> list[dict]:
    evidence = model.calls[index]["evidence"]
    return [dict(item["fields"]) for item in evidence]


# ------------------------------------------------------------------ 安全拒答：正例


@pytest.mark.parametrize("question", RESTRICTED_QUESTIONS)
def test_restricted_contact_request_is_refused_before_model(chat_app, chat_admin, chat_employee, chat_model, question):
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, question)

    assert body["kind"] == "not_found", body
    assert body["sources"] == []
    assert "个人信息" in body["text"]
    assert chat_model.calls == [], "安全拒答不得调用模型"
    for leaked in ("010-00000001", "010-00000002", "示例路18号", "示例路26号", "模拟联系人·陈宁", "模拟联系人·王平"):
        assert leaked not in body["text"], leaked


def test_rag_kernel_path_also_refuses_restricted_contact(chat_app, chat_admin, chat_employee, chat_model):
    """多物品目标 + 联系字段：该轮由 RAG 内核接手时同样在内核侧收口（双入口一致）。"""
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城东店的宣传海报和展架的联系人电话是多少？")

    assert body["kind"] == "not_found", body
    assert body["sources"] == []
    assert chat_model.calls == []


@pytest.mark.parametrize(
    "question",
    [
        "我的要求是：从物品位置表查城东店和城西店的宣传海报及展架放哪里？店家电话也给我。",
        "城东店与城西店的宣传海报和展架在哪里？再从店家资料提供城西店的负责人和电话。",
    ],
    ids=["request-preface", "ambiguous-mixed-fields"],
)
def test_restricted_multi_target_request_is_refused_instead_of_clarified(
    chat_app, chat_admin, chat_employee, chat_model, question,
):
    _dataset(chat_app, chat_admin)

    body = _ask(chat_employee, _conversation(chat_employee), question)

    assert body["kind"] == "not_found", body
    assert "个人信息" in body["text"]
    assert body["sources"] == [] and body["candidates"] == []
    assert chat_model.calls == []
    for value in [*(row[-1] for row in ITEM_ROWS), *(value for row in STORE_ROWS for value in row[2:5])]:
        assert value not in body["text"]


def test_unrestricted_multi_target_queries_keep_answer_and_clarification(chat_app, chat_admin, chat_employee):
    _dataset(chat_app, chat_admin)

    answer = _ask(chat_employee, _conversation(chat_employee), "从物品位置表查城西店的宣传海报和展架分别放哪里？")
    assert answer["kind"] == "answer", answer
    assert "C区2号货架" in answer["text"] and "B区3号货架中层" in answer["text"]
    assert len(answer["sources"]) == 2

    ambiguous = _ask(chat_employee, _conversation(chat_employee), "城东店和城西店的宣传海报及展架放哪里？")
    assert ambiguous["kind"] == "clarification", ambiguous
    assert ambiguous["sources"] == []


@pytest.mark.parametrize("status", ["已续约", ""], ids=["both-fields", "missing-status"])
def test_store_paraphrase_returns_requested_fields_from_active_version(
    chat_app, chat_admin, chat_employee, chat_model, status,
):
    original = _dataset(chat_app, chat_admin)["合作店家信息.xlsx"]
    values = ["合成对接人·沈澜", "010-00000008", "合成道28号", status]
    new_rows = [
        ["S01", "城东店", *values],
        ["S03", "城东南店", "合成近名店对接人", "010-00000009", "合成道29号", "待审批"],
    ]
    path = _xlsx(Path(chat_app.state.settings.data_dir) / "合作店家信息新版.xlsx", STORE_HEADERS, new_rows, "合作店家信息")
    _publish(
        chat_app, chat_admin, path,
        document_id=original["document"]["id"], expected_active=original["version"]["id"],
    )

    body = _ask(chat_employee, _conversation(chat_employee), "城东店目前跟我们合作得怎样，日常由谁对接？")

    assert body["kind"] == "answer", body
    source, = body["sources"]
    assert source["status"] == "active" and source["version_number"] == 2, source
    assert source["locator"]["row"] == 4 and "cells" not in source["locator"], source
    assert values[0] in body["text"], body["text"]
    if status:
        assert status in body["text"], body["text"]
    else:
        assert "资料中未记录：合作状态" in body["text"], body["text"]
    answer_evidence = [record for call in chat_model.calls if call["purpose"] == "answer" for record in call["evidence"]]
    assert answer_evidence and all(not record["text"] for record in answer_evidence)
    for forbidden in (values[1], values[2], "模拟联系人·陈宁", "合作中", "合成近名店对接人", "待审批"):
        assert forbidden not in body["text"] and forbidden not in str(answer_evidence)


# ---------------------------------------------------------- 安全拒答：反例（不得假拒答）


def test_item_location_still_answers(chat_app, chat_admin, chat_employee, chat_model):
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城东店的展架在哪里？")

    assert body["kind"] == "answer", body
    assert "A区2号货架底层" in body["text"]
    assert len(body["sources"]) == 1


def test_two_store_phone_still_answers_both_targets(chat_app, chat_admin, chat_employee, chat_model):
    """fix-1/A 正例：多门店 + 店家级联系字段（单资料、无物品目标）仍逐条作答。"""
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城东店和城西店的电话是多少？")

    assert body["kind"] == "answer", body
    assert "010-00000001" in body["text"] and "010-00000002" in body["text"]


def test_store_level_non_contact_field_still_answers(chat_app, chat_admin, chat_employee, chat_model):
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城东店的合作状态是什么？")

    assert body["kind"] == "answer", body
    assert "合作中" in body["text"]


# ------------------------------------------------------------------ 实体继承：正例


def test_bare_item_followup_keeps_inherited_store_scope(chat_app, chat_admin, chat_employee, chat_model):
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    first = _ask(chat_employee, conversation_id, "城东店的展架在哪里？")
    assert first["kind"] == "answer", first

    second = _ask(chat_employee, conversation_id, "宣传海报呢？")

    assert second["kind"] == "answer", second
    assert "A区1号货架" in second["text"]
    assert "C区2号货架" not in second["text"], "同名不同店的记录行不得进入作答/证据面"
    fields = _evidence_fields(chat_model)
    assert fields, "该轮应走既有记录型模型作答路径"
    assert {entry.get("门店") for entry in fields} == {"城东店"}, fields


def test_bare_store_followup_still_switches_store(chat_app, chat_admin, chat_employee, chat_model):
    """反例：只点名另一个门店的裸追问仍按新门店作答（不得被“继承门店”锁死）。"""
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    first = _ask(chat_employee, conversation_id, "城东店的展架在哪里？")
    assert first["kind"] == "answer", first

    second = _ask(chat_employee, conversation_id, "城西店呢？")

    assert second["kind"] == "answer", second
    assert "B区3号货架中层" in second["text"]
    fields = _evidence_fields(chat_model)
    assert {entry.get("门店") for entry in fields} == {"城西店"}, fields
