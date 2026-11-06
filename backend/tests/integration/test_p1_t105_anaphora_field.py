"""T105/ERR-06：指代追问“继承了实体也要判断问什么”的产品路径多轮用例。

走真实 HTTP 入口（上传→worker→发布→提问），模型用 conftest 的可控替身（只回显证据）：
- 上文问位置 → 「那个海报呢」只答位置；
- 上文问数量/参考供价/规格型号 → 「那个海报呢」只答该字段；
- 无上文 → 澄清要哪项信息（不倾倒整条记录）；
- 产品结果里不得夹带未问字段（标识/数量/规格/价格/仓库等）。
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
W02 = ROOT / "corpus" / "enterprise-20261101" / "word" / "W02_广宣物料与道具管理办法.docx"
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
    ["QF01", "城东店", "宣传海报", "海报", "B区1号货架第二层", 40, 2.6, "A2 铜版纸 157g"],
]
UNASKED_IN_ANSWER = ("A2 铜版纸 157g", "C区2号货架第一层", "2.6", "20", "QF02", "QF01")

MANY_ROWS = LEDGER_ROWS + [
    [f"QF{index:02d}", store, "宣传海报", "海报", f"{store}位置", index, 2.6, "A2 铜版纸 157g"]
    for index, store in enumerate(
        ("城南店", "城北店", "湖滨店", "高新店", "经开店", "临港店", "中心店", "东湖店", "西湖店", "江湾店"),
        start=3,
    )
]


def _xlsx(path: Path, rows: list[list[object]] | None = None) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "物品位置"
    worksheet.cell(row=1, column=1, value="物品位置（T105 夹具）")
    for column, header in enumerate(LEDGER_HEADERS, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows or LEDGER_ROWS):
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
def t105_ready(chat_admin, chat_app, tmp_path: Path):
    _publish(chat_admin, chat_app, _xlsx(tmp_path / "t105-ledger.xlsx"))
    return {"app": chat_app}


@pytest.fixture
def t105_many_ready(chat_admin, chat_app, tmp_path: Path):
    _publish(chat_admin, chat_app, _xlsx(tmp_path / "t105-many.xlsx", MANY_ROWS))
    return {"app": chat_app}


def _docx(path: Path, title: str, paragraphs: list[str]) -> Path:
    document = docx.Document()
    document.add_paragraph(title)
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(path)
    return path


@pytest.fixture
def t105_policy_ready(chat_admin, chat_app, tmp_path: Path):
    """T105 R2：台账 + 制度正文 + 法规原文 + 海报流程正文。"""
    assert W02.is_file() and LEGAL.is_file()
    _publish(chat_admin, chat_app, _xlsx(tmp_path / "t105-policy-ledger.xlsx"))
    _publish(chat_admin, chat_app, W02)
    _publish(chat_admin, chat_app, LEGAL)
    _publish(
        chat_admin,
        chat_app,
        _docx(
            tmp_path / "t105-poster-spec.docx",
            "宣传海报制作与陈列规范",
            [
                "第三条 宣传海报盘点时间为每月最后一个工作日 16:00。",
                "第四条 宣传海报的审批流程：市场部通路行销组发起，门店店长确认。",
            ],
        ),
    )
    return {"app": chat_app}


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


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


def _assert_only(answer: dict, expected: str, *, unwanted: tuple[str, ...]) -> None:
    assert answer["kind"] == "answer", answer
    assert expected in answer["text"], answer["text"]
    for value in unwanted:
        assert value not in answer["text"], (value, answer["text"])
    # 不是枚举页：指代追问答一个字段，不应出现分页契约。
    assert not answer.get("pagination"), answer
    assert answer["sources"], answer


def test_anaphora_after_location_answers_location_only(t105_ready, chat_employee) -> None:
    conversation = _conversation(chat_employee)
    first = _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")
    assert first["kind"] == "answer", first
    assert "C区2号货架第一层" in first["text"], first["text"]

    followup = _ask(chat_employee, conversation, "那个海报呢")
    _assert_only(
        followup,
        "C区2号货架第一层",
        unwanted=("A2 铜版纸 157g", "2.6", "20", "QF02"),
    )


def test_anaphora_after_quantity_answers_quantity_only(t105_ready, chat_employee) -> None:
    conversation = _conversation(chat_employee)
    first = _ask(chat_employee, conversation, "城西店的宣传海报（标识：QF02）的数量是多少？")
    assert first["kind"] == "answer", first
    assert "20" in first["text"], first["text"]

    followup = _ask(chat_employee, conversation, "那个海报呢")
    _assert_only(
        followup,
        "20",
        unwanted=("A2 铜版纸 157g", "C区2号货架第一层", "2.6", "QF02"),
    )


def test_anaphora_after_price_answers_price_only(t105_ready, chat_employee) -> None:
    conversation = _conversation(chat_employee)
    first = _ask(chat_employee, conversation, "城西店的宣传海报（标识：QF02）的参考供价是多少？")
    assert first["kind"] == "answer", first
    assert "2.6" in first["text"], first["text"]

    followup = _ask(chat_employee, conversation, "那个海报呢")
    _assert_only(
        followup,
        "2.6",
        unwanted=("A2 铜版纸 157g", "C区2号货架第一层", "20", "QF02"),
    )


def test_anaphora_after_spec_answers_spec_only(t105_ready, chat_employee) -> None:
    conversation = _conversation(chat_employee)
    first = _ask(chat_employee, conversation, "城西店的宣传海报（标识：QF02）的规格型号是什么？")
    assert first["kind"] == "answer", first
    assert "A2 铜版纸 157g" in first["text"], first["text"]

    followup = _ask(chat_employee, conversation, "那个海报呢")
    _assert_only(
        followup,
        "A2 铜版纸 157g",
        unwanted=("C区2号货架第一层", "2.6", "20", "QF02"),
    )


def test_anaphora_without_context_clarifies_which_field(t105_ready, chat_employee) -> None:
    conversation = _conversation(chat_employee)
    answer = _ask(chat_employee, conversation, "那个海报呢")

    assert answer["kind"] == "clarification", answer
    assert "哪项信息" in answer["text"], answer["text"]
    for value in UNASKED_IN_ANSWER:
        assert value not in answer["text"], (value, answer["text"])
    assert answer["sources"] == []


def test_anaphora_with_other_anaphora_word_answers_inherited_field(t105_ready, chat_employee) -> None:
    """「刚才那个呢」同属纯指代追问：指代词本身不算新内容，仍应只答上一轮字段。"""
    conversation = _conversation(chat_employee)
    first = _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")
    assert first["kind"] == "answer", first

    followup = _ask(chat_employee, conversation, "刚才那个呢")
    _assert_only(
        followup,
        "C区2号货架第一层",
        unwanted=("A2 铜版纸 157g", "2.6", "20", "QF02"),
    )


def test_anaphora_page_after_enumeration_keeps_pagination(t105_many_ready, chat_employee) -> None:
    """T105 R1/B1：枚举后「那个海报的第2页」必须保留分页，不得被指代澄清劫持。"""
    conversation = _conversation(chat_employee)
    first = _ask(chat_employee, conversation, "把宣传海报都列出来")
    assert first["kind"] == "answer", first
    assert first["pagination"]["page"] == 1, first["pagination"]
    assert first["pagination"]["total"] == 12, first["pagination"]

    second = _ask(chat_employee, conversation, "那个海报的第2页")
    assert second["kind"] == "answer", second
    assert second["pagination"]["page"] == 2, second["pagination"]
    assert second["pagination"]["total"] == 12, second["pagination"]
    assert second["pagination"]["returned"] == 2, second["pagination"]
    assert second["pagination"]["has_more"] is False, second["pagination"]
    assert "第 2 页" in second["text"], second["text"]


def test_bare_page_after_enumeration_keeps_pagination(t105_many_ready, chat_employee) -> None:
    """单独「第2页」（无指代）行为不变。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "把宣传海报都列出来")

    second = _ask(chat_employee, conversation, "第2页")
    assert second["kind"] == "answer", second
    assert second["pagination"]["page"] == 2, second["pagination"]


def test_new_content_record_field_followup_answers_that_field_only(t105_ready, chat_employee) -> None:
    """T105 R1/B2：带新内容的指代追问若问到记录字段，只答该字段。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")

    answer = _ask(chat_employee, conversation, "那个海报的规格型号呢")
    assert answer["kind"] == "answer", answer
    assert "A2 铜版纸 157g" in answer["text"], answer["text"]
    for value in ("C区2号货架第一层", "2.6", "20", "QF02", "QF01"):
        assert value not in answer["text"], (value, answer["text"])
    assert not answer.get("pagination"), answer


def test_new_content_non_field_followup_does_not_dump(t105_ready, chat_employee) -> None:
    """T105 R1/B2：打印材质/陈列要求不得整条倾倒，也不得列出未问字段值。"""
    for question in ("那个海报的打印材质呢", "那个海报的陈列要求呢"):
        conversation = _conversation(chat_employee)
        _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")

        answer = _ask(chat_employee, conversation, question)
        assert answer["kind"] == "not_found", (question, answer)
        assert "未记录" in answer["text"], answer["text"]
        for value in UNASKED_IN_ANSWER:
            assert value not in answer["text"], (question, value, answer["text"])
        assert answer["sources"] == [], answer


def test_policy_anaphora_followup_answers_from_policy_document(
    t105_policy_ready, chat_employee
) -> None:
    """T105 R2/C3：实体+指代+政策题从制度正文答 21 天，不得压成未记录。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")

    answer = _ask(chat_employee, conversation, "那个海报的档期物料要提前多少天提报需求？")
    assert answer["kind"] == "answer", answer
    assert "21" in answer["text"], answer["text"]
    assert "C区2号货架第一层" not in answer["text"], answer["text"]
    assert "标识：" not in answer["text"], answer["text"]
    assert not answer.get("pagination"), answer


def test_process_anaphora_followup_answers_from_document(t105_policy_ready, chat_employee) -> None:
    """T105 R2/C6：实体+指代+流程题从正文作答，不得压成未记录。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")

    answer = _ask(chat_employee, conversation, "那个海报的审批流程是什么？")
    assert answer["kind"] == "answer", answer
    assert "审批流程" in answer["text"] or "店长确认" in answer["text"], answer["text"]
    assert "C区2号货架第一层" not in answer["text"], answer["text"]
    assert not answer.get("pagination"), answer


@pytest.mark.parametrize(
    "question",
    (
        "那个海报的价格欺诈规定是什么？",
        "那个海报的相关规定是什么？",
        "那个海报适用的价格欺诈规定是什么？",
    ),
)
def test_regulation_anaphora_followup_answers_regulation_not_inherited_field(
    t105_policy_ready, chat_employee, question: str
) -> None:
    """T105 R2/C5 系列：法规追问不得返回继承的位置字段。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")

    answer = _ask(chat_employee, conversation, question)
    assert answer["kind"] == "answer", answer
    assert "规定" in answer["text"], answer["text"]
    assert "C区2号货架第一层" not in answer["text"], answer["text"]
    assert "标识：" not in answer["text"], answer["text"]
    assert not answer.get("pagination"), answer


def test_regulation_anaphora_followup_after_spec_does_not_inherit_spec(
    t105_policy_ready, chat_employee
) -> None:
    """T105 R2/C5d：上文问规格后，法规追问也不得随上文返回规格字段。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报的规格型号是什么？")

    answer = _ask(chat_employee, conversation, "那个海报的价格欺诈规定是什么？")
    assert answer["kind"] == "answer", answer
    assert "欺诈" in answer["text"], answer["text"]
    assert "A2 铜版纸 157g" not in answer["text"], answer["text"]


def test_regulation_anaphora_followup_answers_effective_date(t105_policy_ready, chat_employee) -> None:
    """T105 R2/C4：带实体+指代的法规题按法规题作答（2022-07-01 + 废止规定）。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")

    answer = _ask(
        chat_employee, conversation, "那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？"
    )
    assert answer["kind"] == "answer", answer
    text = _flat(answer["text"])
    assert "2022年7月1日" in text, answer["text"]
    assert "禁止价格欺诈行为的规定" in text, answer["text"]
    assert "C区2号货架第一层" not in answer["text"], answer["text"]


def test_date_anaphora_followup_without_field_does_not_claim_no_record(
    t105_policy_ready, chat_employee
) -> None:
    """T105 R2/C7（P2）：记录存在、仅缺日期字段时，文案不得称“未找到记录”。"""
    conversation = _conversation(chat_employee)
    _ask(chat_employee, conversation, "城西店的宣传海报在哪里？")

    answer = _ask(chat_employee, conversation, "那个海报的盘点时间是什么？")
    assert answer["kind"] == "not_found", answer
    assert "未记录" in answer["text"], answer["text"]
    assert "未在资料中找到" not in answer["text"], answer["text"]
    assert "C区2号货架第一层" not in answer["text"], answer["text"]


def test_bare_policy_and_regulation_questions_unchanged(t105_policy_ready, chat_employee) -> None:
    """控制组：单独政策题/法规题（无指代）行为不变。"""
    conversation = _conversation(chat_employee)
    policy = _ask(chat_employee, conversation, "档期物料要提前多少天提报需求？")
    assert policy["kind"] == "answer", policy
    assert "21" in policy["text"], policy["text"]
    assert "城西店" not in policy["text"], policy["text"]

    conversation = _conversation(chat_employee)
    legal = _ask(
        chat_employee,
        conversation,
        "《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？",
    )
    assert legal["kind"] == "answer", legal
    text = _flat(legal["text"])
    assert "2022年7月1日" in text, legal["text"]
    assert "禁止价格欺诈行为的规定" in text, legal["text"]
