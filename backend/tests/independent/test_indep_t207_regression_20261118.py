"""独立验收 2026-11-18：T207 其他回归零外发离线复验（检查2）。

独立验收人自建合成数据（湖南路店/滨江店、促销堆头/吊旗），措辞与开发用例不同：
- C12：位置+合作状态+对接人从两条记录取值、两引用；只问对接人也有值；
  正文与模型载荷无附带电话/地址；缺同店物品时店家记录不得兜底；
- R1：跨轮门店范围继承/换店、凭据族拒答、分页评分正负例（四个实际数字）；
- R2 C29：跨店两值、两引用、当前有效版本、引用摘要脱敏（locator 无 cells）；
- R3：终端版本生效、移除记录不得用旧版本作答。

零真实调用：模型为 EvidenceEchoGateway 替身；只写 tmp 目录。
"""

from __future__ import annotations

import copy
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_scoring import score_public_case  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ITEM_DOC = "物品摆放台账独立验收.xlsx"
STORE_DOC = "店家合作名册独立验收.xlsx"
ITEM_HEADERS = ["门店", "物品", "别名", "标识", "位置"]
STORE_HEADERS = ["标识", "店家", "联系人", "电话", "地址", "合作状态"]

STORE_A = "湖南路店"
STORE_B = "滨江店"
ITEM_A = "促销堆头"
ITEM_B = "吊旗"
LOC_A = "D区5号端架"
LOC_B = "G区3号通道上方"
CONTACT_A = "合成联系人·赵岚"
CONTACT_B = "合成联系人·周远"
PHONE_A = "021-55500001"
PHONE_B = "021-55500002"
ADDR_A = "合成大道1号"
ADDR_B = "合成大道9号"
STATUS_A = "合作中"
STATUS_B = "暂停合作"
RESTRICTED = (PHONE_A, PHONE_B, ADDR_A, ADDR_B, CONTACT_A, CONTACT_B)

ITEM_ROWS = [
    [STORE_A, ITEM_A, "堆头", "IN-P1", LOC_A],
    [STORE_B, ITEM_A, "堆头", "IN-P2", "F区2号堆位"],
    [STORE_A, ITEM_B, "挂旗", "IN-P3", "E区1号收银台旁"],
    [STORE_B, ITEM_B, "挂旗", "IN-P4", LOC_B],
]
STORE_ROWS = [
    ["IN-S1", STORE_A, CONTACT_A, PHONE_A, ADDR_A, STATUS_A],
    ["IN-S2", STORE_B, CONTACT_B, PHONE_B, ADDR_B, STATUS_B],
]

# C12 混合问法：位置（物品行）+ 合作状态/对接人（店家行）。
C12_MIXED = f"{STORE_A}的{ITEM_A}放在什么位置，合作状态如何，对接人是谁？"
C12_MIXED_ANSWER = (
    f"根据资料：{STORE_A}的{ITEM_A}的位置：{LOC_A}；合作状态：{STATUS_A}；"
    f"联系人：{CONTACT_A}。"
)
C12_CONTACT_ONLY = f"{STORE_A}的{ITEM_A}由谁对接？"
C12_CONTACT_WHO = f"{STORE_A}{ITEM_A}找谁对接？"
C12_CREDENTIAL = f"{STORE_A}的{ITEM_A}放在哪？合同编号和结算账号也给我。"
C29_MAIN = f"{STORE_A}的{ITEM_B}放在哪个位置？{STORE_B}的合作状态如何？"
C29_WITH_PHONE = f"{STORE_A}的{ITEM_B}放在哪个位置？{STORE_B}的合作状态如何，电话也告诉我。"


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


def _publish(app, admin: SimpleNamespace, path: Path, *, document_id=None,
             expected_active=None) -> dict:
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


def _dataset(app, admin: SimpleNamespace, *, item_rows=None) -> dict:
    records = {}
    for key, name, headers, rows in (
        ("item", ITEM_DOC, ITEM_HEADERS, ITEM_ROWS if item_rows is None else item_rows),
        ("store", STORE_DOC, STORE_HEADERS, STORE_ROWS),
    ):
        records[key] = _publish(
            app, admin,
            _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, name[:-5]),
        )
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


def _kernel_answer(app, session, question: str, conversation_id: str | None = None):
    qa = app.state.qa
    qa.ensure_ready()
    user_id = str(session.client.get("/api/v1/auth/me").json()["user"]["id"])
    return qa.answer(question, user_id, conversation_id or _conversation(session))


def _no_restricted(text: str) -> None:
    for value in RESTRICTED:
        assert value not in text, (value, text)


# ---------------------------------------------------------------- C12 跨表取值


def test_indep_c12_mixed_three_values_two_sources(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin)
    chat_model.answer_text = C12_MIXED_ANSWER
    body = _ask(chat_employee, _conversation(chat_employee), C12_MIXED)

    assert body["kind"] == "answer", body
    assert LOC_A in body["text"] and STATUS_A in body["text"] and CONTACT_A in body["text"]
    for value in (PHONE_A, ADDR_A, PHONE_B, ADDR_B):
        assert value not in body["text"], (value, body["text"])
    assert len(body["sources"]) == 2, body["sources"]
    assert {s["document_name"] for s in body["sources"]} == {ITEM_DOC, STORE_DOC}

    evidence = chat_model.calls[0]["evidence"]
    assert any("位置" in item["fields"] for item in evidence), evidence
    assert any(item["fields"].get("合作状态") == STATUS_A for item in evidence), evidence
    assert any(item["fields"].get("联系人") == CONTACT_A for item in evidence), evidence
    assert all({"电话", "地址"}.isdisjoint(item["fields"]) for item in evidence), evidence


@pytest.mark.parametrize("question", [C12_CONTACT_ONLY, C12_CONTACT_WHO])
def test_indep_c12_contact_only_returns_value_without_phone_address(
    chat_app, chat_admin, chat_employee, chat_model, question
):
    _dataset(chat_app, chat_admin)
    body = _ask(chat_employee, _conversation(chat_employee), question)

    assert body["kind"] == "answer", body
    assert CONTACT_A in body["text"], body["text"]
    for value in (PHONE_A, ADDR_A):
        assert value not in body["text"], (value, body["text"])
    assert chat_model.calls, "只问对接人不得在模型之前收口"
    for call in chat_model.calls:
        for item in call["evidence"]:
            assert {"电话", "地址"}.isdisjoint(item["fields"]), item["fields"]


def test_indep_c12_missing_same_store_item_no_store_fallback(
    chat_app, chat_admin, chat_employee, chat_model
):
    """吊旗只登记在滨江店；问湖南路店吊旗的对接人，不得拿湖南路店店家行兜底。"""
    rows = [row for row in ITEM_ROWS if not (row[0] == STORE_A and row[1] == ITEM_B)]
    _dataset(chat_app, chat_admin, item_rows=rows)
    body = _ask(
        chat_employee, _conversation(chat_employee),
        f"{STORE_A}的{ITEM_B}由谁对接？",
    )
    assert body["kind"] in {"not_found", "clarification"}, body
    assert CONTACT_A not in body["text"], body["text"]
    for call in chat_model.calls:
        for item in call["evidence"]:
            assert item["fields"].get("联系人") != CONTACT_A, item["fields"]


def test_indep_c12_item_location_only_has_no_store_fields(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin)
    body = _ask(chat_employee, _conversation(chat_employee), f"{STORE_A}的{ITEM_A}放在哪？")
    assert body["kind"] == "answer", body
    assert LOC_A in body["text"]
    assert CONTACT_A not in body["text"] and STATUS_A not in body["text"]
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "位置" in evidence[0]["fields"]
    assert "合作状态" not in evidence[0]["fields"]


@pytest.mark.parametrize(
    "question",
    [
        f"{STORE_A}的{ITEM_A}的电话是多少？",
        f"{STORE_A}{ITEM_A}放在哪，店家地址也给我。",
        C12_CREDENTIAL,
    ],
)
def test_indep_c12_phone_address_credential_still_refused(
    chat_app, chat_admin, chat_employee, chat_model, question
):
    _dataset(chat_app, chat_admin)
    body = _ask(chat_employee, _conversation(chat_employee), question)
    assert body["kind"] == "not_found", body
    assert body["sources"] == []
    assert chat_model.calls == [], "安全/凭据拒答不得调用模型"
    _no_restricted(body["text"])


# ---------------------------------------------------------------- R1 门店范围


def test_indep_r1_bare_item_followup_inherits_store(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    first = _ask(chat_employee, conversation_id, f"{STORE_A}的{ITEM_A}在哪里？")
    assert first["kind"] == "answer", first

    second = _ask(chat_employee, conversation_id, f"{ITEM_B}呢？")
    assert second["kind"] == "answer", second
    assert "E区1号收银台旁" in second["text"], second["text"]
    assert LOC_B not in second["text"], "同名不同店的记录行不得进入作答面"
    fields = [dict(item["fields"]) for item in chat_model.calls[-1]["evidence"]]
    assert fields, fields
    assert {entry.get("门店") for entry in fields} == {STORE_A}, fields


def test_indep_r1_bare_store_followup_switches_store(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    first = _ask(chat_employee, conversation_id, f"{STORE_A}的{ITEM_A}在哪里？")
    assert first["kind"] == "answer", first

    second = _ask(chat_employee, conversation_id, f"{STORE_B}呢？")
    assert second["kind"] == "answer", second
    assert "F区2号堆位" in second["text"], second["text"]
    fields = [dict(item["fields"]) for item in chat_model.calls[-1]["evidence"]]
    assert {entry.get("门店") for entry in fields} == {STORE_B}, fields


# ---------------------------------------------------------------- R1 分页评分

# 枚举夹具刻意使用纯字母标识与无数字位置值：冻结评分口径下，标识单元格里的
# 数字（如 IM09 的 9）不在允许数字集合内，会触发 value_no_fabricated（既有边界，
# 与开发 M1/M2 夹具同口径避让）；本用例只隔离分页计数的背书行为。
# 14 行 7+7：排序在前的门店占偶数行（行号 5,7,...,17），首页引用行不含 10/14，
# 使页头四个计数（1/2/10/14）的唯一结构出处就是 pagination 本身。
ENUM_LOC_A = "D区端架甲"
ENUM_LOC_B = "F区堆位乙"
ENUM_MANY_ROWS = [
    [
        STORE_A if index % 2 == 0 else STORE_B,
        ITEM_A,
        f"堆头{cn}",
        f"IM{chr(64 + index)}",
        ENUM_LOC_A if index % 2 == 0 else ENUM_LOC_B,
    ]
    for index, cn in enumerate("一二三四五六七八九十甲乙丙丁", start=1)
]
ENUM_QUESTION = f"把{STORE_A}和{STORE_B}的{ITEM_A}记录都列出来"


def _score(question: str, product: dict, expected_values=(LOC_A, "F区2号堆位")):
    case = CaseSpec(
        case_id="INDEP-R1-PAGE",
        suite="p2-indep",
        split="public",
        stratum="synthetic",
        business_date="2026-11-18",
        question=question,
        turns=({"turn": 1, "question": question},),
        expected_kind="answer",
        expected_values=expected_values,
        reference_answer="",
    )
    document_codes = {
        str(item.get("document_name")): "D-INDEP"
        for item in product.get("sources") or []
        if item.get("document_name")
    }
    case_row = {
        "case_id": case.case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": ({"turn": 1, "status": "ok", "product": product},),
    }
    return score_public_case(
        case, case_row, document_codes=document_codes, allowed_doc_codes=None
    )


def _check(scored, check_id: str) -> dict:
    found = [item for item in scored.score.checks if item.get("check_id") == check_id]
    assert len(found) == 1, (check_id, scored.score.checks)
    return found[0]


def test_indep_r1_pagination_positive_and_negative(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin, item_rows=ENUM_MANY_ROWS)
    body = _ask(chat_employee, _conversation(chat_employee), ENUM_QUESTION)

    assert body["kind"] == "answer", body
    assert body["pagination"] == {
        "page": 1, "page_size": 10, "total": 14,
        "returned": 10, "has_more": True, "next_page": 2,
    }, body["pagination"]
    assert "共 14 条，当前第 1 页显示 10 条" in body["text"], body["text"]

    scored = _score(ENUM_QUESTION, body, expected_values=(ENUM_LOC_A, ENUM_LOC_B))
    assert _check(scored, "value_no_fabricated")["status"] == "pass"
    assert _check(scored, "value_hit")["status"] == "pass"

    broken_product = copy.deepcopy(body)
    broken_product["pagination"] = None
    broken = _check(
        _score(ENUM_QUESTION, broken_product, expected_values=(ENUM_LOC_A, ENUM_LOC_B)),
        "value_no_fabricated",
    )
    assert broken["status"] == "fail", broken
    assert set(broken["evidence"]["extra"]) == {"1", "2", "10", "14"}, broken


# ---------------------------------------------------------------- R2 C29


def test_indep_c29_two_values_two_citations_active_version_desensitized(
    chat_app, chat_admin, chat_employee, chat_model
):
    records = _dataset(chat_app, chat_admin)
    body = _ask(chat_employee, _conversation(chat_employee), C29_MAIN)

    assert body["kind"] == "answer", body
    assert "E区1号收银台旁" in body["text"] and STATUS_B in body["text"], body["text"]
    assert LOC_B not in body["text"] and STATUS_A not in body["text"], body["text"]
    _no_restricted(body["text"])
    assert chat_model.calls == [], chat_model.calls

    sources = body["sources"]
    assert len(sources) == 2, sources
    assert {s["document_name"] for s in sources} == {ITEM_DOC, STORE_DOC}
    assert all(s["status"] == "active" for s in sources), sources
    assert all(s["version_number"] == 1 for s in sources), sources
    rows = {
        str(s["document_name"]): int((s.get("locator") or {}).get("row", -1))
        for s in sources
    }
    assert rows == {ITEM_DOC: 6, STORE_DOC: 5}, rows
    for source in sources:
        assert "cells" not in (source.get("locator") or {}), source
    serialized = json.dumps(sources, ensure_ascii=False)
    for value in RESTRICTED:
        assert value not in serialized, (value, serialized)

    answer = _kernel_answer(chat_app, chat_employee, C29_MAIN)
    assert answer.kind == "answer", (answer.kind, answer.reason)
    assert {(f.field_role, f.value) for f in answer.facts} == {
        ("location", "E区1号收银台旁"), ("status", STATUS_B),
    }, [(f.field_role, f.value) for f in answer.facts]
    assert len(answer.citations) == 2, answer.citations
    published = {records["item"]["version"]["id"], records["store"]["version"]["id"]}
    assert {c.version_id for c in answer.citations} == published, answer.citations


def test_indep_c29_phone_request_stripped_keeps_scoped_values(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin)
    body = _ask(chat_employee, _conversation(chat_employee), C29_WITH_PHONE)
    assert body["kind"] == "answer", body
    assert "E区1号收银台旁" in body["text"] and STATUS_B in body["text"]
    assert LOC_B not in body["text"] and STATUS_A not in body["text"]
    _no_restricted(body["text"])
    assert "电话" not in body["text"], body["text"]
    assert len(body["sources"]) == 2, body["sources"]
    assert chat_model.calls == [], chat_model.calls

    answer = _kernel_answer(chat_app, chat_employee, C29_WITH_PHONE)
    assert {f.field_role for f in answer.facts} == {"location", "status"}, answer.facts
    assert {f.value for f in answer.facts}.isdisjoint(RESTRICTED), answer.facts


# ---------------------------------------------------------------- R3 版本生效/移除


def test_indep_r3_terminal_version_effective_and_removed_record_gone(
    chat_app, chat_admin, chat_employee, chat_model
):
    root = Path(chat_app.state.settings.data_dir)
    v1_rows = [
        [STORE_A, ITEM_A, "堆头", "IN-P1", LOC_A],
        [STORE_A, ITEM_B, "挂旗", "IN-P3", "E区1号收银台旁"],
    ]
    first = _publish(
        chat_app, chat_admin,
        _xlsx(root / ITEM_DOC, ITEM_HEADERS, v1_rows, ITEM_DOC[:-5]),
    )
    _publish(chat_app, chat_admin, _xlsx(root / STORE_DOC, STORE_HEADERS, STORE_ROWS, STORE_DOC[:-5]))
    conversation_id = _conversation(chat_employee)

    before = _ask(chat_employee, conversation_id, f"{STORE_A}的{ITEM_A}在哪里？")
    assert before["kind"] == "answer", before
    assert LOC_A in before["text"]
    assert all(s["version_number"] == 1 for s in before["sources"]), before["sources"]

    # v2：促销堆头位置更新；吊旗行被移除。
    v2_rows = [[STORE_A, ITEM_A, "堆头", "IN-P1", "H区9号新架"]]
    second = _publish(
        chat_app, chat_admin,
        _xlsx(root / "物品摆放台账独立验收v2.xlsx", ITEM_HEADERS, v2_rows, ITEM_DOC[:-5]),
        document_id=first["document"]["id"],
        expected_active=first["version"]["id"],
    )
    assert second["version"]["number"] == 2, second

    after = _ask(chat_employee, conversation_id, f"{STORE_A}的{ITEM_A}在哪里？")
    assert after["kind"] == "answer", after
    assert "H区9号新架" in after["text"], after["text"]
    assert LOC_A not in after["text"], "旧版本值不得继续输出"
    assert all(s["version_number"] == 2 for s in after["sources"]), after["sources"]

    removed = _ask(chat_employee, conversation_id, f"{STORE_A}的{ITEM_B}在哪里？")
    assert removed["kind"] == "not_found", removed
    assert "E区1号收银台旁" not in removed["text"], "已移除记录不得用旧版本兜底作答"
    assert removed["sources"] == [], removed