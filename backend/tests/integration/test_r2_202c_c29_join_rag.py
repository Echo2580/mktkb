"""R2-202C / C29 跨实体取数最小修复：RAG 直答轮次并联结同门店店家行。

全部实体/表头/值均为虚构（青禾店/白鹭店/折叠桌/折叠椅/折叠凳），不读 fixtures、题面、
私有材料、真实 case_id、真实期望答案或真实实体值。只走产品链路：
上传 → 解析 → 发布 → ``POST /api/v1/conversations/{id}/messages``。

本文件覆盖四组：

1. **主例**：同一问题同时要物品级字段（位置）与店家级字段（合作状态）时，正文与
   ``sources`` 必须同时覆盖两类值/两个来源（两份不同资料、不同 sheet/行/版本）。
2. **反例**：只问物品字段、只问店家字段、物品+电话（安全拒答）、同名物品落两店、
   店家行过期、多物品目标、政策/正文回合——行为必须与修复前逐字一致。
3. **敏感性**：关掉新增的联结入口 → 主例回到红；关掉 R0 的 ``_store_join_ids`` →
   legacy 形态转红而主例仍绿，证明两处修复互不吞并。
4. **零出站**：``t09_network_guard`` + 本文件自备 ``no_subprocess``。
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
from docx import Document as DocxDocument

# ``acceptance.support.netguard`` 需要 ``backend/tests`` 在 sys.path 上；显式补一次，
# 避免依赖其它测试模块的导入顺序。
_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")

# --------------------------------------------------------------------------- #
# 合成数据集（虚构）
# --------------------------------------------------------------------------- #

ITEM_DOC = "物品位置台账.xlsx"
STORE_DOC = "合作店家信息.xlsx"
ITEM_DOC_TITLE = "物品位置台账"
STORE_DOC_TITLE = "合作店家信息"
ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["青禾店", "折叠桌", "P01", "甲区1号架", "4"],
    ["青禾店", "折叠椅", "P02", "甲区2号架", "6"],
    ["白鹭店", "折叠凳", "P03", "乙区1号架", "9"],
]
STORE_HEADERS = ["标识", "店家", "联系人", "合作状态"]
STORE_ROWS = [
    ["S01", "青禾店", "合成对接人·甲", "合作中"],
    ["S02", "白鹭店", "合成对接人·乙", "暂停合作"],
]
POLICY_DOC = "合作流程制度.docx"
POLICY_PARAGRAPHS = [
    "合作流程制度说明",
    "一、合作准入：新增合作店家须先完成资质登记，再由市场部复核。",
    "二、提报要求：每月五日前提交上月合作情况汇总，逾期视为未提报。",
    "三、退出机制：连续两个月未提报的店家转入观察名单。",
]

STORE = "青禾店"
ITEM = "折叠桌"
ITEM_LOCATION = "甲区1号架"
STORE_STATUS = "合作中"

#: R1（C29 历史 A 形：只点名物品 + 枚举词 → ``enumerate=True``、``filters=[item]``）。
QUESTION_A = "折叠桌的位置在哪里，合作状态分别是什么？"
#: R2（B 形：同时点名门店与物品；R0/C12 join 的触发条件满足，但枚举轮次仍由内核直答）。
QUESTION_B = "青禾店的折叠桌放在哪个位置，合作状态分别是什么？"
#: B-legacy：同 B 去掉枚举词 → 走 legacy 取证路径（R0 补丁的生效面）。
QUESTION_B_LEGACY = "青禾店的折叠桌放在哪个位置，合作状态如何？"
B_LEGACY_ANSWER = f"根据资料：{STORE}的{ITEM}位置：{ITEM_LOCATION}；合作状态：{STORE_STATUS}。"
#: C1/R3：只问物品位置（不得多出店家级值/来源）。
QUESTION_C1 = "折叠桌分别放在哪个位置？"
#: C2/R4：只问店家属性（目标不得被改写成物品）。
QUESTION_C2 = f"{STORE}的合作状态是什么？"
#: C3（相邻安全反例）：物品 + 电话仍在检索/模型之前整体拒答。
QUESTION_PHONE = f"{STORE}的{ITEM}电话是多少？"
#: C6：多物品目标枚举（不得联结、不得改变原枚举结果）。
QUESTION_MULTI_ITEM = "折叠桌和折叠椅分别在哪个位置，合作状态分别是什么？"
#: C7：正文/制度类回合（不得按记录行作答、不得多带店家级值）。
QUESTION_POLICY = "提报要求分别是怎么规定的？"


@pytest.fixture
def no_subprocess(monkeypatch):
    """合成链路不得启动子进程：拦截 ``subprocess`` 并逐个断言 0 次。

    ``t09_network_guard`` 只覆盖本进程内的 socket/httpx 出站；子进程会绕过它，
    所以这里额外封死 ``subprocess.Popen``/``run``（调用即失败，计数为 0）。
    """

    calls: list[tuple] = []

    def _blocked(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((args, tuple(sorted(kwargs))))
        raise AssertionError("合成链路不得启动子进程")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    yield calls
    assert calls == [], calls


# --------------------------------------------------------------------------- #
# 夹具装配（真实上传/解析/发布）
# --------------------------------------------------------------------------- #


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


def _publish(app, admin: SimpleNamespace, path: Path) -> None:
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


def _dataset(
    app,
    admin: SimpleNamespace,
    *,
    item_rows: list[list[object]] | None = None,
    store_rows: list[list[object]] | None = None,
    store_headers: list[str] | None = None,
) -> None:
    for name, headers, rows, title in (
        (ITEM_DOC, ITEM_HEADERS, item_rows or ITEM_ROWS, ITEM_DOC_TITLE),
        (STORE_DOC, store_headers or STORE_HEADERS, store_rows or STORE_ROWS, STORE_DOC_TITLE),
    ):
        _publish(app, admin, _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, title))


def _policy_dataset(app, admin: SimpleNamespace) -> None:
    path = Path(app.state.settings.data_dir) / POLICY_DOC
    document = DocxDocument()
    for paragraph in POLICY_PARAGRAPHS:
        document.add_paragraph(paragraph)
    document.save(path)
    _publish(app, admin, path)


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


def _plan(app, session: SimpleNamespace, conversation_id: str, question: str):
    """产品同一入口的查询计划（``QaEngine.prepare``）：只读 filters/roles 的**键**。"""

    qa = app.state.qa
    qa.ensure_ready()
    me = session.client.get("/api/v1/auth/me").json()
    return qa.prepare(question, str(me["user"]["id"]), conversation_id)[1]


def _source_docs(body: dict) -> list[str]:
    return [str(item.get("document_name") or "") for item in body.get("sources") or []]


def _ask_info(app, session: SimpleNamespace, question: str) -> dict:
    """一次真实产品链路问答 + 计划形态摘要（只计数/布尔/合成值）。"""

    conversation_id = _conversation(session)
    plan = _plan(app, session, conversation_id, question)
    body = _ask(session, conversation_id, question)
    return {
        "body": body,
        "kind": body.get("kind"),
        "text": body.get("text") or "",
        "sources": _source_docs(body),
        "pagination": body.get("pagination"),
        "mode": str(getattr(plan, "mode", "")),
        "enumerate": bool(getattr(plan, "enumerate", False)),
        "filters": sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})),
        "filter_values": dict(getattr(plan, "filters", {}) or {}),
        "field_role": getattr(plan, "field_role", None),
        "field_roles": tuple(getattr(plan, "field_roles", ()) or ()),
        "state_stores": tuple(getattr(plan.state, "stores", ()) or ()),
        "state_items": tuple(getattr(plan.state, "items", ()) or ()),
        "reason": getattr(plan, "reason", None),
    }


def _disable_join(monkeypatch) -> None:
    """敏感性对照：关掉本批新增的联结入口（检索层唯一入口）。"""

    from mktkb.rag import retrieval as rag_retrieval

    monkeypatch.setattr(rag_retrieval, "_store_join_chunks", lambda session, plan: ("", []))


# --------------------------------------------------------------------------- #
# 1) 主例（绿）
# --------------------------------------------------------------------------- #


def test_r1_item_only_cross_field_question_joins_store_row(
    chat_app, chat_admin, chat_employee, chat_model
):
    """R1（A 形）：只点名物品 + "分别" → 直答轮次同时覆盖物品级与店家级值/来源。

    修前实测（红）：``sources=[物品位置台账.xlsx]``、正文只有位置值、0 模型调用。
    修后实测（绿）：正文两行分属两份资料，``sources`` 两条分别来自两份资料。
    """

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_A)

    assert info["kind"] == "answer", info
    assert info["mode"] == "record", info
    assert info["enumerate"] is True, info
    assert info["filters"] == ["item"], info
    assert set(info["field_roles"]) == {"location", "status"}, info
    assert info["state_stores"] == (), info
    # 值：两类值同时出现。
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS in info["text"], info
    # 来源：两条、分别来自两份资料（顺序按记录标签，不按上传顺序）。
    assert sorted(set(info["sources"])) == sorted({ITEM_DOC, STORE_DOC}), info
    assert len(info["sources"]) == 2, info
    # 仍是结构化直答：模型 0 调用。
    assert chat_model.calls == [], chat_model.calls


def test_r2_store_plus_item_enumerate_turn_joins_store_row(
    chat_app, chat_admin, chat_employee, chat_model
):
    """R2（B 形）：点名门店 + 物品 + "分别" → 与 R1 一样同时覆盖两类值/两个来源。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_B)

    assert info["filters"] == ["item", "store"], info
    assert info["enumerate"] is True, info
    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS in info["text"], info
    assert sorted(set(info["sources"])) == sorted({ITEM_DOC, STORE_DOC}), info
    assert len(info["sources"]) == 2, info
    assert chat_model.calls == [], chat_model.calls


def test_two_named_stores_keep_public_fields_in_their_own_scope(
    chat_app, chat_admin, chat_employee, chat_model, t09_network_guard
):
    _dataset(chat_app, chat_admin)
    info = _ask_info(
        chat_app, chat_employee,
        "青禾店的折叠桌放在哪个位置？顺便查白鹭店的合作状态，电话也告诉我。",
    )
    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert "暂停合作" in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert "电话" not in info["text"], info
    assert sorted(info["sources"]) == sorted([ITEM_DOC, STORE_DOC]), info
    assert chat_model.calls == []
    assert t09_network_guard.snapshot()["external"] == []


def test_r1_facts_and_citations_cover_both_entity_rows(
    chat_app, chat_admin, chat_employee, chat_model
):
    """证据面（RAG 直答不调模型）：事实按两类角色/两个实体标签分行绑定，引用覆盖两份资料。"""

    _dataset(chat_app, chat_admin)
    qa = chat_app.state.qa
    qa.ensure_ready()
    me = chat_employee.client.get("/api/v1/auth/me").json()
    answer = qa.answer(QUESTION_A, str(me["user"]["id"]), _conversation(chat_employee))

    assert answer.kind == "answer", answer.text
    assert answer.answer_source == "structured_enumeration", answer.answer_source
    roles = {(fact.field_role, fact.value) for fact in answer.facts}
    assert ("location", ITEM_LOCATION) in roles, roles
    assert ("status", STORE_STATUS) in roles, roles
    labels = {fact.entity_label for fact in answer.facts}
    assert labels == {f"{STORE}的{ITEM}", STORE}, labels
    doc_ids = {citation.doc_id for citation in answer.citations}
    assert len(doc_ids) == 2, answer.citations
    assert chat_model.calls == [], chat_model.calls


# --------------------------------------------------------------------------- #
# 2) 反例（修复前后逐字一致）
# --------------------------------------------------------------------------- #


def test_c1_item_location_only_turn_does_not_carry_store_level_values(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C1/R3：只问物品位置 → 不得出现店家级值/来源（不因同门店存在店家行而多带）。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_C1)

    assert info["kind"] == "answer", info
    assert info["enumerate"] is True, info
    assert info["field_roles"] == ("location",), info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert "合作状态" not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info
    assert chat_model.calls == [], chat_model.calls


def test_c2_store_only_turn_keeps_store_target(chat_app, chat_admin, chat_employee, chat_model):
    """C2/R4：只问店家属性 → 目标仍是店家行，不被改写成物品、不多带位置。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_C2)

    assert info["kind"] == "answer", info
    assert info["filters"] == ["store"], info
    assert STORE_STATUS in info["text"], info
    assert ITEM_LOCATION not in info["text"], info
    assert info["sources"] == [STORE_DOC], info
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "合作状态" in evidence[0]["fields"], evidence
    assert "位置" not in evidence[0]["fields"], evidence


def test_c3_item_plus_phone_is_still_refused_before_retrieval_and_model(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C3（相邻安全反例）：物品 + 电话仍在检索/模型之前整体拒答。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_PHONE)

    assert info["kind"] == "not_found", info
    assert info["sources"] == [], info
    assert ITEM_LOCATION not in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert info["reason"] == "SECURITY_RESTRICTED_CONTACT", info
    assert chat_model.calls == [], "安全拒答不得调用模型"


def test_c4_same_item_in_two_stores_does_not_join(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C4（fail-closed）：同名物品落两家门店 → 物品目标不唯一 → 不联结。"""

    _dataset(
        chat_app,
        chat_admin,
        item_rows=[
            [STORE, ITEM, "P01", ITEM_LOCATION, "4"],
            ["白鹭店", ITEM, "P09", "乙区9号架", "2"],
            [STORE, "折叠椅", "P02", "甲区2号架", "6"],
        ],
    )
    info = _ask_info(chat_app, chat_employee, QUESTION_A)

    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert set(info["sources"]) == {ITEM_DOC}, info
    assert chat_model.calls == [], chat_model.calls


def test_c5_expired_store_row_is_not_joined(chat_app, chat_admin, chat_employee, chat_model):
    """C5（fail-closed）：店家行已过有效期 → 不并入（业务日窗口同样作用于联结行）。"""

    _dataset(
        chat_app,
        chat_admin,
        store_rows=[["S01", STORE, "合成对接人·甲", STORE_STATUS, "2026-10-31"]],
        store_headers=[*STORE_HEADERS, "失效日期"],
    )
    info = _ask_info(
        chat_app, chat_employee, f"截至2026-11-01，{ITEM}的位置在哪里，合作状态分别是什么？"
    )

    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info
    assert chat_model.calls == [], chat_model.calls


def test_c6_multi_item_enumeration_is_byte_identical(chat_app, chat_admin, chat_employee, monkeypatch):
    """C6：多物品目标枚举 → 不联结；正文/来源与关掉联结入口时逐字相同。"""

    _dataset(chat_app, chat_admin)
    before = _ask_info(chat_app, chat_employee, QUESTION_MULTI_ITEM)
    _disable_join(monkeypatch)
    after = _ask_info(chat_app, chat_employee, QUESTION_MULTI_ITEM)

    assert before["reason"] == "MULTI_TARGET_ENUMERATE", before
    assert before["kind"] == after["kind"], (before, after)
    assert before["text"] == after["text"], (before["text"], after["text"])
    assert before["sources"] == after["sources"], (before["sources"], after["sources"])
    assert STORE_STATUS not in before["text"], before["text"]


def test_c7_policy_turn_is_byte_identical(
    chat_app, chat_admin, chat_employee, chat_model, monkeypatch
):
    """C7：正文/制度类回合（mode=document）→ 不联结；正文/来源与关掉入口时逐字相同。"""

    _dataset(chat_app, chat_admin)
    _policy_dataset(chat_app, chat_admin)
    before = _ask_info(chat_app, chat_employee, QUESTION_POLICY)
    chat_model.calls.clear()
    _disable_join(monkeypatch)
    after = _ask_info(chat_app, chat_employee, QUESTION_POLICY)

    assert before["mode"] == "document", before
    assert before["kind"] == after["kind"], (before, after)
    assert before["text"] == after["text"], (before["text"], after["text"])
    assert before["sources"] == after["sources"], (before["sources"], after["sources"])
    assert STORE_STATUS not in before["text"], before["text"]
    assert ITEM_LOCATION not in before["text"], before["text"]


# --------------------------------------------------------------------------- #
# 3) 敏感性：关掉本批入口 → 主例回红；R0 入口关掉 → legacy 转红而主例仍绿
# --------------------------------------------------------------------------- #


def test_join_entry_sensitivity_restores_red(chat_app, chat_admin, chat_employee, chat_model, monkeypatch):
    """关掉 ``retrieval._store_join_chunks`` → R1/R2 回到修前形态（1 值 / 1 来源）。"""

    _dataset(chat_app, chat_admin)
    _disable_join(monkeypatch)
    for question in (QUESTION_A, QUESTION_B):
        info = _ask_info(chat_app, chat_employee, question)
        assert ITEM_LOCATION in info["text"], info
        assert STORE_STATUS not in info["text"], info
        assert info["sources"] == [ITEM_DOC], info
        assert chat_model.calls == [], chat_model.calls
        chat_model.calls.clear()


def test_r0_legacy_join_and_rag_join_do_not_swallow_each_other(
    chat_app, chat_admin, chat_employee, chat_model, monkeypatch
):
    """两个补丁互不吞并：R0 legacy 形态需 ``_store_join_ids``；RAG 主例不依赖它。"""

    from mktkb.retrieval import service as retrieval_service

    _dataset(chat_app, chat_admin)
    # (1) legacy 形态（无枚举词）：R0 补丁开着 → 两类值/两条来源。
    chat_model.answer_text = B_LEGACY_ANSWER
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_B_LEGACY)
    assert body["kind"] == "answer", body
    assert ITEM_LOCATION in body["text"], body["text"]
    assert STORE_STATUS in body["text"], body["text"]
    assert set(_source_docs(body)) == {ITEM_DOC, STORE_DOC}, body["sources"]
    evidence = chat_model.calls[0]["evidence"]
    assert any("位置" in item["fields"] for item in evidence), evidence
    assert any("合作状态" in item["fields"] for item in evidence), evidence
    # (2) 关掉 R0 入口：legacy 形态转红（回答无法背书）。
    monkeypatch.setattr(retrieval_service, "_store_join_ids", lambda db, intent: set())
    chat_model.calls.clear()
    chat_model.answer_text = B_LEGACY_ANSWER
    red = _ask(chat_employee, _conversation(chat_employee), QUESTION_B_LEGACY)
    assert red["kind"] == "service_error", red
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "合作状态" not in evidence[0]["fields"], evidence
    # (3) 同一开关下 RAG 主例仍绿：本批联结不经过 R0 的 ``_store_join_ids``。
    chat_model.calls.clear()
    info = _ask_info(chat_app, chat_employee, QUESTION_A)
    assert info["kind"] == "answer", info
    assert STORE_STATUS in info["text"], info
    assert sorted(set(info["sources"])) == sorted({ITEM_DOC, STORE_DOC}), info
    assert chat_model.calls == [], chat_model.calls


# --------------------------------------------------------------------------- #
# 4) 零出站：本文件全部用例都在模块级守卫下；这里再显式断言一次
# --------------------------------------------------------------------------- #


def test_offline_chain_has_zero_external_network_and_no_subprocess(
    t09_network_guard, no_subprocess, chat_app, chat_admin, chat_employee, chat_model
):
    """合成链路零出站、零子进程：跑完主例与反例后审计守卫账本。"""

    _dataset(chat_app, chat_admin)
    for question in (QUESTION_A, QUESTION_B, QUESTION_C1, QUESTION_C2, QUESTION_PHONE):
        _ask(chat_employee, _conversation(chat_employee), question)

    snapshot = t09_network_guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]
    assert no_subprocess == [], no_subprocess
