"""T101：ERR-03 词表语境与法规优先（产品路径集成用例）。

走真实 HTTP 入口（上传→worker→发布→提问），模型用 conftest 的可控替身（只回显证据）：
- 法规题（E118/E120/E116/E122）不再被判成“资料中未记录：采购价格/销售额”；
- 价格/销售类正文题（E087/E095）不再被缺失字段词表提前截断；
- E120 能给出 2022-07-01 与两项废止规定，并引用原法规资料；
- 真实缺字段（宣传海报的采购价格）、有物品实体的「价格」仍保持 not_found。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import openpyxl
import pytest

from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
LEGAL = ROOT / "corpus" / "enterprise-20261101" / "legal"
L01 = LEGAL / "规范促销行为暂行规定（国家市场监督管理总局令第32号）.docx"
L02 = LEGAL / "明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）.docx"
L03 = LEGAL / "中华人民共和国反不正当竞争法（2025年修订）.docx"

#: ERR-20261104-03 影响面的代表题（corpus/enterprise-20261101/questions.json）
AFFECTED_QUESTIONS = (
    "进行价格比较时，未标明被比较价格详细信息的，被比较价格有什么限制？",  # E118
    "《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？",  # E120
    "2025 年 Q4 柠檬茶在 NKA卖场的特价还是现在的有效价格吗？",  # E087
    "柠檬茶 500ml 在 CVS 和 NKA 的价格一样吗？各是多少？",  # E095
    "抽奖式有奖销售的最高奖金额上限是多少？",  # E116
    "违反反不正当竞争法第十一条进行有奖销售的，罚款幅度是多少？",  # E122
)


def _flat(text: str) -> str:
    """忽略空白的逐字比较（语料里写作“2022年7月1日”，问题写作“2022 年 7 月 1 日”）。"""
    return re.sub(r"\s+", "", str(text or ""))


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], *, sheet: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.cell(row=1, column=1, value=f"{sheet}（T101 夹具）")
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
def t101_ready(chat_admin, chat_employee, chat_app, tmp_path: Path):
    """三份法规原文 + 一份物品位置表；法规题与记录题都能走真实检索。"""
    for path in (L01, L02, L03):
        assert path.is_file(), path
        _publish(chat_admin, chat_app, path)
    ledger = _xlsx(
        tmp_path / "t101-ledger.xlsx",
        ["门店", "物品", "数量", "位置"],
        [["滨江店", "柠檬茶 500ml", 40, "A区一层"], ["滨江店", "宣传海报", 40, "入口堆头"]],
        sheet="物品位置",
    )
    _publish(chat_admin, chat_app, ledger)
    return {"app": chat_app, "employee": chat_employee}


def _ask(client, conversation: str, question: str) -> dict:
    response = client.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=client.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _conversation(client) -> str:
    response = client.client.post("/api/v1/conversations", json={}, headers=client.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_affected_questions_are_not_truncated_as_missing_fields(t101_ready) -> None:
    client = t101_ready["employee"]
    for question in AFFECTED_QUESTIONS:
        payload = _ask(client, _conversation(client), question)
        assert payload["missing_fields"] == [], (question, payload)
        assert "资料中未记录" not in payload["text"], (question, payload)
        assert payload["error_code"] is None, (question, payload)
        assert payload["kind"] != "clarification", (question, payload)


def test_e120_answers_effective_date_and_repealed_rules(t101_ready) -> None:
    client = t101_ready["employee"]
    payload = _ask(
        client,
        _conversation(client),
        "《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？",
    )

    assert payload["kind"] == "answer", payload
    text = _flat(payload["text"])
    assert "2022年7月1日" in text, payload
    assert "《关于商品和服务实行明码标价的规定》" in text, payload
    assert "《禁止价格欺诈行为的规定》" in text, payload
    assert payload["sources"], payload
    assert any("明码标价" in source.get("document_name", "") for source in payload["sources"]), payload


def test_purchase_price_without_item_context_still_not_found(t101_ready) -> None:
    client = t101_ready["employee"]
    payload = _ask(client, _conversation(client), "宣传海报的采购价格是多少？")

    assert payload["kind"] == "not_found", payload
    assert payload["missing_fields"] == ["采购价格"], payload
    assert "资料中未记录" in payload["text"], payload
    assert not payload["sources"], payload


def test_generic_price_word_with_item_entity_still_not_found(t101_ready) -> None:
    client = t101_ready["employee"]
    payload = _ask(client, _conversation(client), "滨江店柠檬茶 500ml 的价格是多少？")

    assert payload["kind"] == "not_found", payload
    assert payload["missing_fields"] == ["采购价格"], payload
    assert not payload["sources"], payload
