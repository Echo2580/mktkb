"""R0/C12 安全边界收窄的**产品链路**合成件（离线 ASGI + 可控模型替身）。

与 `tests/rag/test_r0_c12b_boundary_synthetic.py`（内核层）互补：这里走
conversations service 的真实分支（rag 计划 → rag/legacy 归属 → 作答/拒答），
证明收窄后 C12 t7 不再被 `SECURITY_RESTRICTED_CONTACT` 拦在检索/模型之前，
同时“物品 + 电话/地址”仍在模型之前整体拒答。

零真实调用：模型是 ``EvidenceEchoGateway`` 替身，索引为 offline；只写 tmp 目录。
数据集与 `test_v3_safety_fix_e2e.py` 同款（假值；物品位置表 + 合作店家信息表）。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl

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
#: 冻结契约里 C12 t7 的问句（should_refuse=False、expected_kind=answer）。
T7 = "城西店这批海报由谁对接、合作状态如何？请把位置和对接人一起写进交接记录。"
#: 契约内模型回答（提示词要求"只写回答本问所需的字段"）：位置在物品行、合作状态与
#: 联系人在店家行。R0/C12 并集后两条证据行都要参与回答。
T7_ANSWER = (
    "根据资料：城西店的宣传海报的位置：C区2号货架；合作状态：合作中；"
    "联系人：模拟联系人·王平。"
)
PERSONAL_TEXT = "个人信息"


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


def _dataset(app, admin: SimpleNamespace) -> None:
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


# --------------------------------------------------------------------------- #
# 红 → 绿：C12 t7 与 item+contact 在真实链路上不再被安全拒答
# --------------------------------------------------------------------------- #


def test_c12_t7_is_answered_not_security_refused(chat_app, chat_admin, chat_employee, chat_model):
    """改前：kind=not_found + 固定安全拒答 + sources=[] + 模型零调用；改后：正常作答。

    R0/C12：并集后证据面是两条行（物品位置行 + 店家信息行），回显全部字段会超出
    记录型回答的分句上限（提示词要求"只写回答本问所需的字段"）；这里注入契约内
    回答，只验证"不再被拒答、真的走到作答路径"。
    """
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    chat_model.answer_text = T7_ANSWER

    body = _ask(chat_employee, conversation_id, T7)

    assert body["kind"] == "answer", body
    assert PERSONAL_TEXT not in body["text"], body["text"]
    assert body["sources"], "正常作答必须带来源（拒答态的 sources 为空）"
    assert chat_model.calls, "改前的安全拒答在检索/模型之前收口；这里必须真的走到作答路径"


# --------------------------------------------------------------------------- #
# R0/C12：跨表取数（位置在物品行、合作状态/对接人在店家行）
# --------------------------------------------------------------------------- #


def test_c12_t7_carries_item_and_store_row_values(chat_app, chat_admin, chat_employee, chat_model):
    """并集后：位置、合作状态、对接人三项都来自两条真实记录行，且来源引用两条。"""

    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    chat_model.answer_text = T7_ANSWER

    body = _ask(chat_employee, conversation_id, T7)

    assert body["kind"] == "answer", body
    assert "C区2号货架" in body["text"], body["text"]
    assert "合作中" in body["text"], body["text"]
    assert "模拟联系人·王平" in body["text"], body["text"]
    assert "010-00000002" not in body["text"] and "示例路26号" not in body["text"]
    assert len(body["sources"]) == 2, body["sources"]
    evidence = chat_model.calls[0]["evidence"]
    assert any("位置" in item["fields"] for item in evidence), evidence
    assert any("合作状态" in item["fields"] for item in evidence), evidence
    assert any(item["fields"].get("联系人") == "模拟联系人·王平" for item in evidence)
    assert all({"电话", "地址"}.isdisjoint(item["fields"]) for item in evidence)


def test_join_alone_would_regress_answer_validation(
    chat_app, chat_admin, chat_employee, chat_model, monkeypatch
):
    """红（只改检索一处）：并集后仍用改前回答侧口径 → 记录型校验失败（service_error）。

    改前 ``_record_units`` 要求物品维度逐行命中、且每行背书**全部**本问字段；跨表两条
    来源行没有任何一行能同时满足 → 回答校验拒绝。证明"只改检索"既不能让 C12 通过，
    还会把当前 answer 变成 service_error，因此回答侧事实准入必须同步放行店家行。
    """

    from mktkb.conversations import service as conv

    def legacy_record_units(units, plan, answer_facts=(), *, cited=None):
        cited_ids = None if cited is None else {str(item) for item in cited}
        filters = dict(getattr(plan, "entities", None) or {})
        asked = set()
        for label, value in answer_facts or ():
            role = conv.resolve_requested_role(label)
            if role:
                asked.add((role, conv.normalize(str(value))))
        selected = []
        for unit in units:
            if cited_ids is not None and str(getattr(unit, "id", "")) not in cited_ids:
                continue
            fields = dict(getattr(unit, "fields", None) or {})
            values = conv._role_values(fields)
            if filters.get("store") and values.get("store") != filters["store"]:
                continue
            if filters.get("item") and values.get("item") != filters["item"]:
                continue
            if asked:
                attested = set()
                for name, raw in fields.items():
                    role = conv.resolve_requested_role(str(name))
                    if role and raw not in (None, ""):
                        attested.add((role, conv.normalize(str(raw).strip())))
                if not asked.issubset(attested):
                    continue
            selected.append(unit)
        return selected

    monkeypatch.setattr(conv, "_record_units", legacy_record_units)
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    chat_model.answer_text = T7_ANSWER

    body = _ask(chat_employee, conversation_id, T7)

    assert body["kind"] == "service_error", body


def test_single_item_attribute_has_no_store_values(chat_app, chat_admin, chat_employee, chat_model):
    """反例（门 4）：单问物品属性（位置）→ 证据只有物品行，不得多出店家级字段。"""

    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城西店宣传海报放在哪？")

    assert body["kind"] == "answer", body
    assert "模拟联系人·王平" not in body["text"], body["text"]
    assert "合作中" not in body["text"], body["text"]
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "合作状态" not in evidence[0]["fields"], evidence
    assert "位置" in evidence[0]["fields"], evidence


def test_store_attribute_question_is_unchanged(chat_app, chat_admin, chat_employee, chat_model):
    """反例（门 4）：单问店家属性（联系人）→ 行为不变：仍是店家行一条。"""

    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城西店的联系人是谁？")

    assert body["kind"] == "answer", body
    assert "模拟联系人·王平" in body["text"], body["text"]
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "联系人" in evidence[0]["fields"], evidence
    assert "位置" not in evidence[0]["fields"], evidence


def test_item_plus_contact_only_is_answered_at_product_level(
    chat_app, chat_admin, chat_employee, chat_model
):
    """item + 只问 contact（对接人）：产品链路同样放行（C27 反向形态）。"""
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城西店宣传海报由谁对接？")

    assert body["kind"] == "answer", body
    assert PERSONAL_TEXT not in body["text"], body["text"]
    assert "模拟联系人·王平" in body["text"], body["text"]
    assert "010-00000002" not in body["text"] and "示例路26号" not in body["text"]
    assert chat_model.calls, "不得在模型之前收口"


# --------------------------------------------------------------------------- #
# 不变：item + phone / address 仍在检索/模型之前整体拒答
# --------------------------------------------------------------------------- #


def test_item_plus_phone_still_refused_before_model(chat_app, chat_admin, chat_employee, chat_model):
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "城西店宣传海报的电话是多少？")

    assert body["kind"] == "not_found", body
    assert body["sources"] == [], body
    assert PERSONAL_TEXT in body["text"], body["text"]
    assert chat_model.calls == [], "安全拒答不得调用模型"
