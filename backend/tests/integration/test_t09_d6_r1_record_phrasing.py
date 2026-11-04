"""T09-D6 R1 回归：记录型准入兼容 IA 真实模型自然措辞（标识括注 + 位于/在/是）。

背景（IA-T09-QWEN-20261031-74665ff1 §1.2 失败一）：
- 真实模型对 Q01 返回
  ``{"answer": "城东店的宣传海报（标识：P01）位于B区1号货架第二层。", "source_ids": [...]}``；
  业务值与所引用的真实单元都正确，但记录型句式准入把对象与地点之间的「（标识：P01）」
  当作残余文字、且位置句缺少字段标签，于是返回 ``service_error / MODEL_OUTPUT_INVALID``。
- 本文件用该**原文**与 fixtures 中的真实 D01 记录行复现：修复前必须红，修复后必须 answer，
  且来源可由 locator 核对。

同时锁定没有放宽的既有拒绝口径：
- 伪造标识值（未出现在被引用行）仍拒绝；
- 引用东店行却用西店行的标识/位置（跨实体借用）仍拒绝；
- 位置值不是被引用行原值（改写/来自其它来源）仍拒绝。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from mktkb.ingestion.worker import run_one_job
from mktkb.retrieval.index import resolve_requested_role

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"

QUESTION = "城东店的宣传海报在哪里？"
OTHER_STORE_QUESTION = "城西店的宣传海报在哪里？"
PHONE_QUESTION = "城东店的电话是什么？"

# IA 台账 live-02 捕获的模型原文（唯一差异是 source_id 为每轮真实单元，测试运行时从证据取得）。
IA_MODEL_ANSWER = "城东店的宣传海报（标识：P01）位于B区1号货架第二层。"
IA_IDENTIFIER_VALUE = "P01"
IA_LOCATION_VALUE = "B区1号货架第二层"

# 常见自然措辞：标识/编号括注 + 位于/在/是。占位符在运行时用被引用行的真实标识值填入。
NATURAL_TEMPLATES = (
    "城东店的宣传海报（标识：{identifier}）位于{location}。",
    "城东店的宣传海报（标识：{identifier}）在{location}。",
    "城东店的宣传海报（编号：{identifier}）是{location}。",
)


# ---------------------------------------------------------------- 辅助（真实 HTTP/worker/检索）


def _run_worker(app) -> None:
    db = app.state.db.session()
    try:
        result = run_one_job(db, app.state.store)
    finally:
        db.close()
    assert result.state == "succeeded", result


def _publish(app, admin, *, path=None, document_id=None, expected_active=None, revision=0) -> tuple[dict, dict]:
    receipt = admin.upload(path=path, document_id=document_id, expected_active_version_id=expected_active)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    _run_worker(app)
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        json={"expected_active_version_id": expected_active, "expected_revision": revision},
        headers=admin.headers,
    )
    assert published.status_code == 200, published.text
    return record, published.json()


def _base_positions(app, admin) -> dict:
    """与 B0 同构的位置表槽：历史 V1（V03）→ 业务 V2（D01）。"""
    v03, first = _publish(app, admin, path=V03, revision=0)
    positions = v03["document"]["id"]
    d01, second = _publish(
        app,
        admin,
        path=D01,
        document_id=positions,
        expected_active=v03["version"]["id"],
        revision=first["revision"],
    )
    return {"document": positions, "d01": d01, "revision": second["revision"]}


def _ask(ns, question: str) -> dict:
    created = ns.client.post("/api/v1/conversations", json={}, headers=ns.headers)
    assert created.status_code == 201, created.text
    conversation = created.json()["id"]
    response = ns.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=ns.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _answer_evidence(gateway) -> list[dict]:
    calls = [call for call in gateway.calls if call["purpose"] == "answer"]
    assert calls, gateway.calls
    return calls[-1]["evidence"]


def _row_for_store(evidence: list[dict], store: str) -> dict:
    for item in evidence:
        values = {str(value).strip() for value in item["fields"].values() if value not in (None, "")}
        if store in values:
            return item
    raise AssertionError(f"本次模型证据中没有 {store} 的记录行：{evidence}")


def _field_value(row: dict, role: str) -> str:
    for name, value in row["fields"].items():
        if resolve_requested_role(str(name)) == role and value not in (None, ""):
            return str(value).strip()
    raise AssertionError(f"记录行缺少 {role} 字段：{row}")


def _prime_evidence(app, employee, question: str) -> list[dict]:
    """先让受控替身按证据原值回答一次，取得本次真实候选行与 source_id。"""
    payload = _ask(employee, question)
    assert payload["kind"] == "answer", payload
    return _answer_evidence(app.state.model_gateway)


def _assert_rejected(payload: dict) -> None:
    assert payload["kind"] == "service_error", payload
    assert payload["error_code"] == "MODEL_OUTPUT_INVALID", payload
    assert payload["sources"] == [], payload
    assert IA_LOCATION_VALUE not in payload["text"], payload["text"]


# ---------------------------------------------------------------- 红 → 绿：IA 原文必须 answer


def test_ia_captured_model_answer_is_accepted(chat_app, chat_admin, chat_employee):
    """IA 真实模型原文（含「（标识：P01）位于…」）必须被记录型准入接受。"""
    _base_positions(chat_app, chat_admin)
    evidence = _prime_evidence(chat_app, chat_employee, QUESTION)
    row = _row_for_store(evidence, "城东店")
    assert _field_value(row, "identifier") == IA_IDENTIFIER_VALUE, row
    assert _field_value(row, "location") == IA_LOCATION_VALUE, row

    gateway = chat_app.state.model_gateway
    gateway.answer_text = IA_MODEL_ANSWER
    gateway.source_ids = (row["source_id"],)

    payload = _ask(chat_employee, QUESTION)

    assert payload["kind"] == "answer", payload
    assert payload.get("error_code") is None, payload
    assert IA_LOCATION_VALUE in payload["text"], payload["text"]
    returned = [source["source_id"] for source in payload["sources"]]
    assert returned == [row["source_id"]], returned
    source = payload["sources"][0]
    assert source["document_name"].startswith("V03"), source
    assert source["version_number"] == 2, source
    assert source["status"] == "active", source
    assert {"sheet", "row", "header_row"} <= set(source["locator"]), source


@pytest.mark.parametrize("template", NATURAL_TEMPLATES)
def test_natural_annotation_and_connector_variants_answer(chat_app, chat_admin, chat_employee, template):
    """「标识/编号括注 + 位于/在/是」等常见措辞同样必须 answer（值取自被引用行原值）。"""
    _base_positions(chat_app, chat_admin)
    evidence = _prime_evidence(chat_app, chat_employee, QUESTION)
    row = _row_for_store(evidence, "城东店")
    identifier = _field_value(row, "identifier")
    location = _field_value(row, "location")

    gateway = chat_app.state.model_gateway
    gateway.answer_text = template.format(identifier=identifier, location=location)
    gateway.source_ids = (row["source_id"],)

    payload = _ask(chat_employee, QUESTION)

    assert payload["kind"] == "answer", payload
    assert location in payload["text"], payload["text"]
    assert [source["source_id"] for source in payload["sources"]] == [row["source_id"]], payload["sources"]


def test_annotation_after_field_label_is_accepted(chat_app, chat_admin, chat_employee):
    """标识括注也可出现在字段标签之后（"城东店的电话（标识：S01）是…"），值仍须是行原值。"""
    base = _base_positions(chat_app, chat_admin)
    _publish(chat_app, chat_admin, path=D02, revision=base["revision"])
    evidence = _prime_evidence(chat_app, chat_employee, PHONE_QUESTION)
    row = _row_for_store(evidence, "城东店")
    identifier = _field_value(row, "identifier")
    phone = _field_value(row, "phone")

    gateway = chat_app.state.model_gateway
    gateway.answer_text = f"城东店的电话（标识：{identifier}）是{phone}。"
    gateway.source_ids = (row["source_id"],)

    payload = _ask(chat_employee, PHONE_QUESTION)

    assert payload["kind"] == "answer", payload
    assert phone in payload["text"], payload["text"]
    assert [source["source_id"] for source in payload["sources"]] == [row["source_id"]], payload["sources"]


# ---------------------------------------------------------------- 未放宽：既有拒绝口径


def test_forged_identifier_annotation_is_rejected(chat_app, chat_admin, chat_employee):
    """伪造的标识值（不在被引用行原值中）仍必须拒绝，不得因括注而放行。"""
    _base_positions(chat_app, chat_admin)
    evidence = _prime_evidence(chat_app, chat_employee, QUESTION)
    row = _row_for_store(evidence, "城东店")

    gateway = chat_app.state.model_gateway
    gateway.answer_text = "城东店的宣传海报（标识：P99）位于B区1号货架第二层。"
    gateway.source_ids = (row["source_id"],)

    _assert_rejected(_ask(chat_employee, QUESTION))


def test_identifier_from_uncited_row_is_rejected(chat_app, chat_admin, chat_employee):
    """引用东店的行、却用西店行的标识括注：跨实体借用仍必须拒绝。"""
    _base_positions(chat_app, chat_admin)
    east_evidence = _prime_evidence(chat_app, chat_employee, QUESTION)
    east_row = _row_for_store(east_evidence, "城东店")
    west_evidence = _prime_evidence(chat_app, chat_employee, OTHER_STORE_QUESTION)
    west_row = _row_for_store(west_evidence, "城西店")
    west_identifier = _field_value(west_row, "identifier")
    east_location = _field_value(east_row, "location")
    assert west_identifier != _field_value(east_row, "identifier"), (west_row, east_row)

    gateway = chat_app.state.model_gateway
    gateway.answer_text = f"城东店的宣传海报（标识：{west_identifier}）位于{east_location}。"
    gateway.source_ids = (east_row["source_id"],)

    _assert_rejected(_ask(chat_employee, QUESTION))


def test_other_store_statement_with_cited_east_row_is_rejected(chat_app, chat_admin, chat_employee):
    """整句改成西店的事实（值取西店行）却引用东店行：跨门店借用仍必须拒绝。"""
    _base_positions(chat_app, chat_admin)
    east_evidence = _prime_evidence(chat_app, chat_employee, QUESTION)
    east_row = _row_for_store(east_evidence, "城东店")
    west_evidence = _prime_evidence(chat_app, chat_employee, OTHER_STORE_QUESTION)
    west_row = _row_for_store(west_evidence, "城西店")

    gateway = chat_app.state.model_gateway
    gateway.answer_text = (
        f"城西店的宣传海报（标识：{_field_value(west_row, 'identifier')}）"
        f"位于{_field_value(west_row, 'location')}。"
    )
    gateway.source_ids = (east_row["source_id"],)

    _assert_rejected(_ask(chat_employee, QUESTION))


def test_altered_location_value_is_rejected(chat_app, chat_admin, chat_employee):
    """括注正确、但位置值不是被引用行原值（改写）：仍必须拒绝。"""
    _base_positions(chat_app, chat_admin)
    evidence = _prime_evidence(chat_app, chat_employee, QUESTION)
    row = _row_for_store(evidence, "城东店")
    identifier = _field_value(row, "identifier")

    gateway = chat_app.state.model_gateway
    gateway.answer_text = f"城东店的宣传海报（标识：{identifier}）位于B区1号货架第三层。"
    gateway.source_ids = (row["source_id"],)

    _assert_rejected(_ask(chat_employee, QUESTION))
