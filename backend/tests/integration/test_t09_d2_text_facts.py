"""回归：正文型来源参与记录检索与冲突（T09-D2 P0 端到端）。

修复前：正文 PDF 段落一律 ``fields={}``，索引层拿不到门店/物品/字段角色，
- 发布"临时物料位置通知"后，同一实体仍是两个独立候选（歧义），拿不到冲突；
- 删除物品位置表后，只剩正文通知也无法回答位置题。
修复后（本文件锁定）：
1. 正文通知与表格记录指向同一实体时，能给出两个有效值及各自来源；
2. 只保留正文通知时仍能作答，且来源指向正文通知；
3. "发现店家…"这类流程句不会被当成门店，未知门店仍返回 not_found（不回归）。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D06 = FIXTURES / "normal" / "D06_店家资料维护说明.pdf"
V01 = FIXTURES / "variants" / "V01_临时物料位置通知.pdf"
V07 = FIXTURES / "variants" / "V07_物料位置独立通知.pdf"


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


def _base_positions(app, admin) -> dict:
    """与 B0 同构的位置表槽：历史 V1（V03）→ 业务 V2（D01）。"""
    v03 = _publish(app, admin, path=V03)
    document = v03["document"]["id"]
    _publish(app, admin, path=D01, document_id=document, expected_active=v03["version"]["id"])
    return {"document": document}


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


def test_text_notice_conflicts_with_table_record(chat_app, chat_admin, chat_employee):
    """正文通知与表格记录给出同一实体的不同位置 → conflict，且两值两来源。"""
    _base_positions(chat_app, chat_admin)
    _publish(chat_app, chat_admin, path=V01)

    payload = _ask(chat_employee, "城东店的宣传海报现在放在哪里？")
    assert payload["kind"] == "conflict", payload
    values = {entry["value"] for conflict in payload["conflicts"] for entry in conflict["entries"]}
    assert values == {"B区1号货架第二层", "D区暂存柜"}, values
    names = {source["document_name"]: source["version_number"] for source in payload["sources"]}
    assert names.get("V03_物品位置表_历史V1.xlsx") == 2, "参与冲突的必须是当前业务 V2，不是历史 V1"
    assert "V01_临时物料位置通知.pdf" in names, names


def test_only_text_notice_answers_location(chat_app, chat_admin, chat_employee):
    """删除表格资料后，仅剩正文通知也能回答位置，且来源指向通知本身。"""
    base = _base_positions(chat_app, chat_admin)
    _publish(chat_app, chat_admin, path=V07)

    detail = chat_admin.client.get(f"/api/v1/documents/{base['document']}").json()
    deleted = chat_admin.client.delete(
        f"/api/v1/documents/{base['document']}",
        params={"expected_revision": detail["revision"]},
        headers=chat_admin.headers,
    )
    assert deleted.status_code == 200, deleted.text

    payload = _ask(chat_employee, "城东店的宣传海报在哪里？")
    assert payload["kind"] == "answer", payload
    assert "B区1号货架第二层" in payload["text"], payload["text"]
    names = [source["document_name"] for source in payload["sources"]]
    assert names and all(name.startswith("V07") for name in names), names


def test_store_word_in_flow_sentence_is_not_a_store(chat_app, chat_admin, chat_employee):
    """「发现店家信息变化后…」应作为文档问题回答，而不是"未找到门店发现店"。"""
    _publish(chat_app, chat_admin, path=D06)
    payload = _ask(chat_employee, "发现店家信息变化后，应何时联系谁？")
    assert payload["kind"] == "answer", payload
    assert "资料管理员" in payload["text"], payload["text"]
    # 回答是 D06 原文（含"发现店家"），不能是"未找到某门店"的 not_found 文本
    assert "未找到" not in payload["text"], payload["text"]
    names = [source["document_name"] for source in payload["sources"]]
    assert any(name.startswith("D06") for name in names), names


def test_unknown_store_still_reports_not_found(chat_app, chat_admin, chat_employee):
    """未知门店（语料里确实没有）仍返回 not_found，不编造。"""
    _base_positions(chat_app, chat_admin)
    payload = _ask(chat_employee, "城南店联系人是谁？")
    assert payload["kind"] == "not_found", payload
    assert payload["sources"] == []
    assert "城南店" in payload["text"]
