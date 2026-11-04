"""T09-D4 回归：同一字段同值来自两条已发布来源（T09-D3-F01 最小修复）。

复现路径与 D3 B 层一致（真实 HTTP 上传 / worker / 发布 / T05 检索；模型为 conftest 可控替身，
不发起任何真实模型或 OCR 调用）：

1. 物品位置表槽：历史 V1（V03）→ 业务 V2（D01；城东店宣传海报=B区1号货架第二层）；
2. C05：发布 V01_临时物料位置通知（正文单元：城东店宣传海报=D区暂存柜）→ 冲突态；
3. U02：把 V04（P01 位置=D区暂存柜）作为该槽新版本发布（version_number=3）。

此时同一实体（城东店 / 宣传海报）的两条已发布来源给出同一个位置原值：
表格记录行与正文通知单元。T09-D3 记录的产品缺口（F01）是：修复前记录型准入
``_match_record_clause`` 对“同角色同值命中两行”按不可验证处理，于是返回
``service_error / MODEL_OUTPUT_INVALID``。

本文件锁定修复后的行为，同时锁定未被放宽的既有准入：
(a) 同值双来源 → answer，来源只取模型实际引用且能核对的行；
(b) 不同值仍必须 conflict（C05 语义不变）；
(c) 伪造值、未引用行回显仍必须拒绝；
(d) 跨门店不得借用别的门店的同值来源。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from mktkb.ingestion.worker import run_one_job
from mktkb.retrieval.index import resolve_requested_role

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
V01 = FIXTURES / "variants" / "V01_临时物料位置通知.pdf"
V04 = FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx"

QUESTION = "城东店的宣传海报在哪里？"
CONFLICT_QUESTION = "城东店的宣传海报现在放在哪里？"
SAME_VALUE = "D区暂存柜"
OLD_VALUE = "B区1号货架第二层"
# 替身模型按证据原值陈述的唯一一句事实（不内置业务答案：值取自证据行原值）
STATEMENT = f"城东店的宣传海报位置：{SAME_VALUE}。"


# ---------------------------------------------------------------- 辅助


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


def _seed_same_value_state(app, admin, employee) -> dict:
    """B0 物品位置表槽 → C05 冲突态 → U02 同值新版，返回关键身份。"""
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
    notice, third = _publish(app, admin, path=V01, revision=second["revision"])
    conflict = _ask(employee, CONFLICT_QUESTION)
    assert conflict["kind"] == "conflict", conflict  # C05 前置：不同值必须先能冲突
    v04, fourth = _publish(
        app,
        admin,
        path=V04,
        document_id=positions,
        expected_active=d01["version"]["id"],
        revision=third["revision"],
    )
    return {
        "positions": positions,
        "v2": d01["version"]["id"],
        "v3": v04["version"]["id"],
        "notice": notice["document"]["id"],
        "revision": fourth["revision"],
    }


def _answer_evidence(gateway) -> list[dict]:
    """最近一次 answer 目的调用的证据（模型实际看到的来源行）。"""
    calls = [call for call in gateway.calls if call["purpose"] == "answer"]
    assert calls, gateway.calls
    return calls[-1]["evidence"]


def _notice_source_id(evidence: list[dict]) -> str:
    """正文通知单元：证据里正文含“临时调整至”的那一条（fixture 正文，非产品常量）。"""
    for item in evidence:
        if "临时调整至" in item["text"]:
            return item["source_id"]
    raise AssertionError(evidence)


def _row_identifier(evidence: list[dict]) -> tuple[str, str]:
    """表格记录行的标识字段名与值（从证据原值取，不硬编码）。"""
    for item in evidence:
        for name, value in item["fields"].items():
            if resolve_requested_role(str(name)) == "identifier" and value not in (None, ""):
                return str(name), str(value)
    raise AssertionError(evidence)


# ---------------------------------------------------------------- (a) 同值双来源 → answer


def test_same_value_two_sources_answers_with_cited_sources(chat_app, chat_admin, chat_employee):
    """同值双来源、模型同时引用两条来源：必须 answer，且来源全部是本次证据里的被引用行。"""
    _seed_same_value_state(chat_app, chat_admin, chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.answer_text = STATEMENT
    gateway.source_ids = None  # 默认引用本次全部证据单元

    payload = _ask(chat_employee, QUESTION)

    assert payload["kind"] == "answer", payload
    assert payload.get("error_code") is None, payload
    assert SAME_VALUE in payload["text"], payload["text"]
    assert OLD_VALUE not in payload["text"], payload["text"]
    evidence = _answer_evidence(gateway)
    cited = {item["source_id"] for item in evidence}
    assert len(cited) == 2, evidence  # 表格行 + 正文通知单元
    returned = {source["source_id"] for source in payload["sources"]}
    assert returned, payload["sources"]
    assert returned <= cited, (returned, cited)


def test_same_value_single_cited_source_answers_with_that_source(chat_app, chat_admin, chat_employee):
    """同值双来源、模型只引用其中一条（正文通知）：必须 answer，来源就是被引用的那一条。"""
    _seed_same_value_state(chat_app, chat_admin, chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.answer_text = STATEMENT
    first = _ask(chat_employee, QUESTION)
    assert first["kind"] == "answer", first
    evidence = _answer_evidence(gateway)
    notice_id = _notice_source_id(evidence)

    gateway.source_ids = (notice_id,)
    payload = _ask(chat_employee, QUESTION)

    assert payload["kind"] == "answer", payload
    assert SAME_VALUE in payload["text"], payload["text"]
    returned = [source["source_id"] for source in payload["sources"]]
    assert returned == [notice_id], returned
    assert next(source for source in payload["sources"] if source["source_id"] == notice_id)[
        "document_name"
    ].startswith("V01"), payload["sources"]


# ---------------------------------------------------------------- (b) 不同值仍冲突


def test_same_value_state_does_not_weaken_different_value_conflict(chat_app, chat_admin, chat_employee):
    """C05 语义不变：两条来源给出不同位置时仍是 conflict，两值两来源。"""
    v03, first = _publish(chat_app, chat_admin, path=V03, revision=0)
    _d01, second = _publish(
        chat_app,
        chat_admin,
        path=D01,
        document_id=v03["document"]["id"],
        expected_active=v03["version"]["id"],
        revision=first["revision"],
    )
    _publish(chat_app, chat_admin, path=V01, revision=second["revision"])

    payload = _ask(chat_employee, CONFLICT_QUESTION)

    assert payload["kind"] == "conflict", payload
    values = {entry["value"] for conflict in payload["conflicts"] for entry in conflict["entries"]}
    assert values == {OLD_VALUE, SAME_VALUE}, values
    names = {source["document_name"]: source["version_number"] for source in payload["sources"]}
    assert names.get("V03_物品位置表_历史V1.xlsx") == 2, names
    assert "V01_临时物料位置通知.pdf" in names, names


# ---------------------------------------------------------------- (c) 既有拒绝口径


def test_same_value_rejects_forged_value(chat_app, chat_admin, chat_employee):
    """伪造/过期值（旧位置）仍然拒绝：不得借同值来源洗白。"""
    _seed_same_value_state(chat_app, chat_admin, chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.answer_text = f"城东店的宣传海报位置：{OLD_VALUE}。"
    gateway.source_ids = None

    payload = _ask(chat_employee, QUESTION)

    assert payload["kind"] == "service_error", payload
    assert payload["error_code"] == "MODEL_OUTPUT_INVALID", payload
    assert payload["sources"] == [], payload
    assert OLD_VALUE not in payload["text"], payload["text"]


def test_same_value_rejects_echo_from_uncited_row(chat_app, chat_admin, chat_employee):
    """未引用行不能为回答背书：只引用正文通知，却回显表格行的标识，仍必须拒绝。"""
    _seed_same_value_state(chat_app, chat_admin, chat_employee)
    gateway = chat_app.state.model_gateway
    gateway.answer_text = STATEMENT
    first = _ask(chat_employee, QUESTION)
    assert first["kind"] == "answer", first
    evidence = _answer_evidence(gateway)
    notice_id = _notice_source_id(evidence)
    field_name, field_value = _row_identifier(evidence)

    gateway.answer_text = f"城东店的宣传海报位置：{SAME_VALUE}；{field_name}：{field_value}。"
    gateway.source_ids = (notice_id,)
    payload = _ask(chat_employee, QUESTION)

    assert payload["kind"] == "service_error", payload
    assert payload["error_code"] == "MODEL_OUTPUT_INVALID", payload
    assert payload["sources"] == [], payload


# ---------------------------------------------------------------- (d) 跨门店不得借用


def test_same_value_other_store_does_not_borrow(chat_app, chat_admin, chat_employee):
    """同值来源属于城东店；问城西店时不得借用城东店的值或来源。"""
    _seed_same_value_state(chat_app, chat_admin, chat_employee)

    payload = _ask(chat_employee, "城西店的宣传海报在哪里？")

    assert payload["kind"] == "answer", payload
    assert SAME_VALUE not in payload["text"], payload["text"]
    names = [source["document_name"] for source in payload["sources"]]
    assert names and not any(name.startswith("V01") for name in names), names
