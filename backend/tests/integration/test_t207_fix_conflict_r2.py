"""T207-FIX-CONFLICT-R2 回归：冲突回答的 text 必须披露冲突字段与双方取值。

冻结评分器的 value_hit 只读 outcome.text；HEAD 把双方取值只放进 API 的 conflicts 负载，
C05/C06 因此 value_hit 恒 fail（kind_correct / source_hit 本来就 pass）。本文件锁定：

1. C05/C06 的冲突轮文本同时包含双方原值（位置 / 电话），conflicts 结构与来源不变；
2. 文本按冲突视图通用渲染（单字段 / 多字段 / 空白折叠去重 / 截断），不依赖题面与文档名；
3. 用冻结 CaseSpec 走 p2_scoring.score_public_case，value_hit/source_hit/kind_correct 全 pass。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select

from mktkb.conversations import service as service_module
from mktkb.conversations.schemas import ConflictEntry, ConflictView
from mktkb.documents.models import SourceUnit
from mktkb.evaluation.p2_public_cases import load_acceptance_cases
from mktkb.evaluation.p2_scoring import score_public_case
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


def _narrow_to_table_rows(app, monkeypatch) -> None:
    """把 rag 候选裁成只含表格行（live 每轮 1 次 query embedding 的后果），锁定真实运行形状。"""

    db = app.state.db.session()
    try:
        table_rows = {
            str(unit_id)
            for unit_id in db.scalars(select(SourceUnit.id).where(SourceUnit.kind == "table_row")).all()
        }
    finally:
        db.close()
    qa = app.state.qa
    original = qa.candidate_unit_ids_for_intent

    def record_rows_only(*, mode, terms=(), entity_filters=None):
        ids = original(mode=mode, terms=terms, entity_filters=entity_filters)
        return {str(item) for item in ids if str(item) in table_rows}

    monkeypatch.setattr(qa, "candidate_unit_ids_for_intent", record_rows_only)


def _frozen_checks(case_id: str, payload: dict, document_codes: dict[str, str]) -> tuple[str, dict]:
    """用冻结 CaseSpec（fixtures/acceptance/questions.json）给一轮产品响应打分。"""

    case = next(item for item in load_acceptance_cases() if item.case_id == case_id)
    row = {
        "case_id": case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": [
            {
                "turn": 1,
                "status": "ok",
                "product": {"kind": payload["kind"], "text": payload["text"], "sources": payload["sources"]},
            }
        ],
    }
    scored = score_public_case(case, row, document_codes=document_codes)
    checks = {item["check_id"]: item["status"] for item in scored.score.checks}
    return scored.score.status, checks


def _assert_frozen_pass(case_id: str, payload: dict, document_codes: dict[str, str]) -> None:
    status, checks = _frozen_checks(case_id, payload, document_codes)
    assert status == "pass", checks
    for check_id in ("value_hit", "source_hit", "kind_correct"):
        assert checks[check_id] == "pass", (check_id, checks)


def _view(field: str, *values: str) -> ConflictView:
    return ConflictView(
        field=field,
        entries=[ConflictEntry(value=value, source_id=uuid.uuid4()) for value in values],
    )


def test_conflict_text_discloses_both_location_values(chat_app, chat_admin, chat_employee, monkeypatch):
    """C05：冲突轮文本必须同时披露两个位置取值，且来源/冲突结构不变。"""

    v03 = _publish(chat_app, chat_admin, path=V03)
    _publish(
        chat_app,
        chat_admin,
        path=D01,
        document_id=v03["document"]["id"],
        expected_active=v03["version"]["id"],
    )
    _publish(chat_app, chat_admin, path=V01)
    _narrow_to_table_rows(chat_app, monkeypatch)

    payload = _ask(chat_employee, "城东店的宣传海报现在放在哪里？")
    assert payload["kind"] == "conflict", payload
    text = payload["text"]
    for value in ("B区1号货架第二层", "D区暂存柜"):
        assert value in text, text
    assert "位置：[B区1号货架第二层、D区暂存柜]" in text, text
    values = {entry["value"] for conflict in payload["conflicts"] for entry in conflict["entries"]}
    assert values == {"B区1号货架第二层", "D区暂存柜"}, values
    names = {source["document_name"] for source in payload["sources"]}
    assert any(name.startswith("V01") for name in names), names
    assert any(name.startswith("V03") for name in names), names
    # 测试里历史版仍叫 V03_*（未按 R4 灌库改写文件名），故显式映射到 D01 槽（见 T207-import-recipe）。
    _assert_frozen_pass(
        "C05",
        payload,
        {"V03_物品位置表_历史V1.xlsx": "D01", "V01_临时物料位置通知.pdf": "V01"},
    )


def test_conflict_text_discloses_both_phone_values(chat_app, chat_admin, chat_employee, monkeypatch):
    """C06：电话冲突同样在文本里披露两个号码（两个独立有效来源）。"""

    _publish(chat_app, chat_admin, path=D02)
    _publish(chat_app, chat_admin, path=V02)
    _narrow_to_table_rows(chat_app, monkeypatch)

    payload = _ask(chat_employee, "城东店的联系电话是什么？")
    assert payload["kind"] == "conflict", payload
    text = payload["text"]
    for value in ("010-00000001", "010-00000099"):
        assert value in text, text
    assert "电话：[010-00000001、010-00000099]" in text, text
    values = {entry["value"] for conflict in payload["conflicts"] for entry in conflict["entries"]}
    assert values == {"010-00000001", "010-00000099"}, values
    _assert_frozen_pass(
        "C06",
        payload,
        {"D02_合作店家信息.xlsx": "D02", "V02_店家联系方式变更通知.pdf": "V02"},
    )


def test_conflict_values_text_is_rendered_from_fields_and_values():
    """文案由冲突视图通用渲染：单字段只给取值，多字段逐字段带名，截断显式声明。"""

    assert (
        service_module._conflict_values_text([_view("位置", "B区1号货架第二层", "D区暂存柜")])
        == "位置：[B区1号货架第二层、D区暂存柜]"
    )
    assert (
        service_module._conflict_values_text([_view("位置", "甲", "乙"), _view("电话", "1", "2")])
        == "位置：[甲、乙]；电话：[1、2]"
    )
    # 空白折叠后同值去重：同一个值不重复披露
    assert service_module._conflict_values_text([_view("位置", "A  区", "A 区")]) == "位置：[A 区]"
    # 超出披露上限时显式写"等"，不静默省略
    many = _view("位置", *[f"值{index}" for index in range(service_module.MAX_DISCLOSED_CONFLICT_VALUES + 1)])
    rendered = service_module._conflict_values_text([many])
    assert rendered.endswith(" 等]"), rendered
    assert f"值{service_module.MAX_DISCLOSED_CONFLICT_VALUES}" not in rendered, rendered
