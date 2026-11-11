"""T207-FIX-CONFLICT 回归：记录型冲突不依赖 rag 候选窗口 + 图片类问题按范围外拒答。

两处修复的动机（均为产品根因，不是单题补丁）：

1. **C05/C06**：记录型问题的证据上界来自 rag 本轮召回（top-k 排序窗口）。live 下每轮
   ��划只允许一次 query_embedding，正文通知那一路的召回会被门控拒绝，候选集只剩表格行，
   于是"同一实体同一字段的第二个有效值"永远进不了冲突比较。这里用"候选只含表格行"
   的形状复现该运行条件，锁定修复后仍能给出 conflict（两个值、两个来源）。
2. **N08**：以照片/图片为事实来源的问题，首版没有图片输入通道，不能退化成
   "请补充要查询的门店或物品"（那会暗示补槽后就能识别图片），必须按范围外拒答。
   同时锁定"资料名 + 图片"（如"物料领用通知图片要求…"）仍是对已发布资料的提问。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select

from mktkb.conversations import intent as intent_module
from mktkb.documents.models import SourceUnit
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
V01 = FIXTURES / "variants" / "V01_临时物料位置通知.pdf"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
V02 = FIXTURES / "variants" / "V02_店家联系方式变更通知.pdf"


def _run_worker(app) -> None:
    db = app.state.db.session()
    try:
        result = run_one_job(db, app.state.store)
    finally:
        db.close()
    assert result.state == "succeeded", result


def _publish(app, admin, *, path=None, document_id=None, expected_active=None) -> dict:
    receipt = admin.upload(path=path, document_id=document_id, expected_active_version_id=expected_active)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    _run_worker(app)
    detail = admin.client.get(f"/api/v1/documents/{record['document']['id']}").json()
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        json={"expected_active_version_id": expected_active, "expected_revision": detail["revision"]},
        headers=admin.headers,
    )
    assert published.status_code == 200, published.text
    return record


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


def _table_row_units(app) -> set[str]:
    """产品索引里 kind=table_row 的来源单元（表格记录行）。"""
    db = app.state.db.session()
    try:
        return {
            str(unit_id)
            for unit_id in db.scalars(
                select(SourceUnit.id).where(SourceUnit.kind == "table_row")
            ).all()
        }
    finally:
        db.close()


def test_conflict_survives_narrow_rag_candidate_window(chat_app, chat_admin, chat_employee, monkeypatch):
    """rag 候选只含表格行（live 门控形状）时，同一实体的正文通知仍要参与冲突比较。"""
    v03 = _publish(chat_app, chat_admin, path=V03)
    document = v03["document"]["id"]
    _publish(chat_app, chat_admin, path=D01, document_id=document, expected_active=v03["version"]["id"])
    _publish(chat_app, chat_admin, path=V01)

    qa = chat_app.state.qa
    original = qa.candidate_unit_ids_for_intent
    table_rows = _table_row_units(chat_app)

    def record_rows_only(*, mode, terms=(), entity_filters=None):
        ids = original(mode=mode, terms=terms, entity_filters=entity_filters)
        return {str(item) for item in ids if str(item) in table_rows}

    monkeypatch.setattr(qa, "candidate_unit_ids_for_intent", record_rows_only)

    payload = _ask(chat_employee, "城东店的宣传海报现在放在哪里？")
    assert payload["kind"] == "conflict", payload
    values = {entry["value"] for conflict in payload["conflicts"] for entry in conflict["entries"]}
    assert values == {"B区1号货架第二层", "D区暂存柜"}, values
    names = {source["document_name"] for source in payload["sources"]}
    assert any(name.startswith("V01") for name in names), names
    assert any(name.startswith("V03") for name in names), names


def test_phone_conflict_survives_narrow_rag_candidate_window(chat_app, chat_admin, chat_employee, monkeypatch):
    """店家电话同样按"同实体多有效值"处理，不受候选窗口影响。"""
    _publish(chat_app, chat_admin, path=D02)
    _publish(chat_app, chat_admin, path=V02)

    qa = chat_app.state.qa
    original = qa.candidate_unit_ids_for_intent
    table_rows = _table_row_units(chat_app)

    def record_rows_only(*, mode, terms=(), entity_filters=None):
        ids = original(mode=mode, terms=terms, entity_filters=entity_filters)
        return {str(item) for item in ids if str(item) in table_rows}

    monkeypatch.setattr(qa, "candidate_unit_ids_for_intent", record_rows_only)

    payload = _ask(chat_employee, "城东店的联系电话是什么？")
    assert payload["kind"] == "conflict", payload
    values = {entry["value"] for conflict in payload["conflicts"] for entry in conflict["entries"]}
    assert values == {"010-00000001", "010-00000099"}, values


def test_image_question_is_refused_not_clarified(chat_app, chat_admin, chat_employee):
    """以照片为事实来源的问题：not_found + 明确拒答，不得退化成补槽澄清。"""
    _publish(chat_app, chat_admin, path=D01)
    payload = _ask(chat_employee, "根据货架照片告诉我没有标记物品的位置")
    assert payload["kind"] == "not_found", payload
    assert payload["sources"] == []
    assert payload["candidates"] == [], "不得给出补门店/物品式的澄清候选"
    text = payload["text"]
    assert "范围外" in text and "无法" in text, text
    for forbidden in ("照片中", "已定位", "未标记物品位于"):
        assert forbidden not in text, text


def test_image_words_on_published_document_are_not_image_questions():
    """资料名 + "图片"（如"物料领用通知图片要求…"）是对已发布资料提问，不是图片输入。"""
    for question in (
        "物料领用通知图片要求先填写什么？",
        "物料领用通知图片要求谁确认？",
        "巡检照片重复使用或者跨店套用，会被认定成什么？",
    ):
        assert intent_module.image_source_question(question) is False, question
    for question in (
        "根据货架照片告诉我没有标记物品的位置",
        "看这张图，告诉我城东店海报在哪",
        "照片里没有标记的物品放在哪",
    ):
        assert intent_module.image_source_question(question) is True, question
