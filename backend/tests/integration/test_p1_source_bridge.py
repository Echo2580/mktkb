"""P1-FIX/C 产品路径：文档/法规答案的内部 citations → API sources → 来源详情可访问。

走真实 HTTP（上传→worker→发布→问答→消息列表→来源详情），模型用 conftest 可控替身
（零真实调用）。修复前 T105 记录：制度/法规答案对外 ``sources=[]`` 但内核有 citations；
本文件验证：正常文档答案带来源归属（资料名/版本/有效状态/定位），且来源详情接口按
本人消息 + 当前有效版本可访问；拒答仍不带来源。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import docx
import openpyxl
import pytest

from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
LEGAL = (
    ROOT
    / "corpus"
    / "enterprise-20261101"
    / "legal"
    / "明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）.docx"
)
LEDGER_HEADERS = ["标识", "门店", "物品", "别名", "位置", "数量", "参考供价", "规格型号"]
LEDGER_ROWS = [
    ["QF02", "城西店", "宣传海报", "海报", "C区2号货架第一层", 20, 2.6, "A2 铜版纸 157g"],
]


def _xlsx(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "物品位置"
    worksheet.cell(row=1, column=1, value="物品位置（P1-FIX/C 夹具）")
    for column, header in enumerate(LEDGER_HEADERS, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(LEDGER_ROWS):
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
def sources_ready(chat_admin, chat_app, tmp_path: Path):
    assert LEGAL.is_file()
    _publish(chat_admin, chat_app, _xlsx(tmp_path / "p1fix-source-ledger.xlsx"))
    _publish(chat_admin, chat_app, LEGAL)
    return {"app": chat_app, "legal_name": LEGAL.stem}


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


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def test_regulation_anaphora_answer_exposes_sources_and_details(
    sources_ready, chat_employee, chat_employee2
) -> None:
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")
    answer = _ask(chat_employee, conversation, "那个海报的价格欺诈规定是什么？")

    assert answer["kind"] == "answer", answer
    assert "欺诈" in answer["text"], answer["text"]
    sources = answer["sources"]
    assert sources, answer

    # 来源归属/版本/有效状态：每条来源都指向当前有效版本，且带定位。
    for source in sources:
        assert source["source_id"]
        assert source["document_name"]
        assert isinstance(source["version_number"], int) and source["version_number"] >= 1
        assert source["status"] == "active", source
        assert isinstance(source["locator"], dict) and source["locator"], source

    legal_sources = [source for source in sources if "明码标价" in source["document_name"]]
    assert legal_sources, sources

    # 来源详情接口：本人消息 + 当前有效版本可读取真实片段（用户可访问的来源）。
    detail_url = f"/api/v1/messages/{answer['message_id']}/sources/{legal_sources[0]['source_id']}"
    detail = chat_employee.client.get(detail_url)
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["document_name"] == legal_sources[0]["document_name"]
    assert detail_body["version_number"] == legal_sources[0]["version_number"]
    assert detail_body["status"] == "active"
    assert _flat(detail_body["text"] or ""), detail_body

    # 访问权限：他人读不到这条消息的来源详情（先鉴权消息归属）。
    foreign = chat_employee2.client.get(detail_url)
    assert foreign.status_code in {403, 404}, foreign.text

    # 历史消息同样持久化来源（重启/刷新后前端仍能展示依据）。
    history = chat_employee.client.get(f"/api/v1/conversations/{conversation}/messages")
    assert history.status_code == 200, history.text
    assistant = [item for item in history.json()["items"] if item["role"] == "assistant"][-1]
    assert assistant["sources"], assistant
    assert {item["source_id"] for item in assistant["sources"]} == {
        item["source_id"] for item in sources
    }


def test_record_answer_source_is_preserved_and_accessible(sources_ready, chat_employee) -> None:
    conversation = _conversation(chat_employee)
    answer = _ask(chat_employee, conversation, "城西店的宣传海报的数量是多少？")
    assert answer["kind"] == "answer", answer
    assert "20" in answer["text"], answer["text"]
    assert answer["sources"], answer
    source = answer["sources"][0]
    detail = chat_employee.client.get(
        f"/api/v1/messages/{answer['message_id']}/sources/{source['source_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "active"


def test_refusal_does_not_expose_sources(sources_ready, chat_employee) -> None:
    conversation = _conversation(chat_employee)
    answer = _ask(chat_employee, conversation, "公司今年营收是多少")
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert "没有可支撑" in answer["text"], answer["text"]
