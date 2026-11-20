"""R2-202D / 联结唯一性守卫：同一门店多条店家行时 fail-closed **不联结**。

独立验收 ``R2-INDEPENDENT-REVIEW §2 D5a`` 判 D=FAIL：同一门店、同一 active 版本内存在
**2 条**店家行时，R2-202C 的联结把两条都并入 → 正文同时输出互斥状态值（如「合作中」与
「已终止」）、``sources`` 变成 3 条（物品 1 + 店家 2）。成因是**行基数**，不是版本过滤。

R2-202D 在 ``rag/retrieval.py::_store_join_chunks`` 里加一条 fail-closed 唯一性守卫：
按派生门店值命中的店家行**恰好 1 条**才联结；0 条 / >1 条一律不联结，并在
``diagnostics["store_join"]["status"]`` 里用固定码区分 ``joined`` /
``store_row_missing`` / ``store_row_ambiguous``（码里不带门店名、行数等业务值）。

本文件覆盖：

1. **主例（原红）**：同门店 2 行店家行 + 唯一物品目标 + 跨物品级/店家级字段 →
   守卫后不联结：只有物品文档 1 条来源、没有任何店家级值（更没有互斥状态值并出）。
2. **回归**：同门店 1 行 → 仍 ``total=2/returned=2/sources=2``、两个值都在（逐项不变）。
3. **另一侧 fail-closed**：同门店 0 行（门店值派生不出 / 店家表无该店）→ 不联结。
4. **既有反例 C1–C7**：只问位置 / 只问店家 / 物品+电话 / 同名两店 / 过期行 /
   多目标 / ``mode=document``。
5. **敏感性**：把新增的唯一性检查 monkeypatch 成恒真 → 同门店 2 行**回到红**；
   恢复即绿 —— 证明它就是那条红例的唯一开关。
6. **零出站/零子进程**：``t09_network_guard`` + 本文件自备 ``no_subprocess``。

全部实体/表头/值均为虚构（青禾店/白鹭店/折叠桌/折叠椅），不读 fixtures、题面、
私有材料、真实 case_id、真实期望答案或真实实体值；只走产品链路：
上传 → 解析 → 发布 → ``POST /api/v1/conversations/{id}/messages``。
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

# ``acceptance.support.netguard`` 需要 ``backend/tests`` 在 sys.path 上；显式补一次。
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
#: 每店恰好 1 行（既有行为：联结成立）。
STORE_ROWS_ONE_PER_STORE = [
    ["S01", "青禾店", "合成对接人·甲", "合作中"],
    ["S02", "白鹭店", "合成对接人·乙", "暂停合作"],
]
#: 同一门店（青禾店）2 行、同一 active 版本、同一 sheet、业务日窗口内 —— R2-202D 主例。
STORE_ROWS_TWO_FOR_STORE = [
    ["S02", "白鹭店", "合成对接人·乙", "暂停合作"],
    ["S01", "青禾店", "合成对接人·甲", "合作中"],
    ["S03", "青禾店", "合成对接人·丙", "已终止"],
]
#: 店家表里没有青禾店 —— 派生门店值命中 0 行。
STORE_ROWS_NO_TARGET_STORE = [
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
STORE_STATUS_ENDED = "已终止"

#: 跨物品级（位置）+ 店家级（合作状态）字段的枚举轮次：单点名物品 → 触发条件成立。
QUESTION_CROSS = "折叠桌的位置在哪里，合作状态分别是什么？"
#: C1：只问物品位置。
QUESTION_LOCATION_ONLY = "折叠桌分别放在哪个位置？"
#: C2：只问店家属性。
QUESTION_STORE_ONLY = f"{STORE}的合作状态是什么？"
#: C3：物品 + 电话（安全拒答）。
QUESTION_PHONE = f"{STORE}的{ITEM}电话是多少？"
#: C6：多物品目标。
QUESTION_MULTI_ITEM = "折叠桌和折叠椅分别在哪个位置，合作状态分别是什么？"
#: C7：正文/制度类回合。
QUESTION_POLICY = "提报要求分别是怎么规定的？"


@pytest.fixture
def no_subprocess(monkeypatch):
    """合成链路不得启动子进程：拦截 ``subprocess`` 并逐个断言 0 次。"""

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
        (STORE_DOC, store_headers or STORE_HEADERS, store_rows or STORE_ROWS_ONE_PER_STORE, STORE_DOC_TITLE),
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
    """产品同一入口的查询计划（``QaEngine.prepare``）。"""

    qa = app.state.qa
    qa.ensure_ready()
    me = session.client.get("/api/v1/auth/me").json()
    return qa.prepare(question, str(me["user"]["id"]), conversation_id)[1]


def _source_docs(body: dict) -> list[str]:
    return [str(item.get("document_name") or "") for item in body.get("sources") or []]


def _source_rows(body: dict) -> list[object]:
    return [dict(item.get("locator") or {}).get("row") for item in body.get("sources") or []]


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
        "rows": _source_rows(body),
        "pagination": dict(body.get("pagination") or {}) or None,
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


def _retrieval_diagnostics(app, session: SimpleNamespace, question: str) -> tuple[dict, list]:
    """``_exact_recall`` 层面的诊断与精确候选（只读；不写库、不反问）。"""

    from mktkb.rag import retrieval as rag_retrieval

    index = app.state.qa.index()
    conversation_id = _conversation(session)
    plan = _plan(app, session, conversation_id, question)
    with index.session() as db:
        diagnostics: dict = {}
        exact = rag_retrieval._exact_recall(db, index, plan, diagnostics)
    return diagnostics, exact


def _guard_on(monkeypatch) -> None:
    """敏感性：唯一性检查恒真（等价于没有守卫）。"""

    from mktkb.rag import retrieval as rag_retrieval

    monkeypatch.setattr(rag_retrieval, "_store_row_is_unique", lambda store_rows: True)


def _disable_join(monkeypatch) -> None:
    """敏感性对照：整个联结入口关掉（既有 202C 开关）。"""

    from mktkb.rag import retrieval as rag_retrieval

    monkeypatch.setattr(rag_retrieval, "_store_join_chunks", lambda session, plan: ("", []))


# --------------------------------------------------------------------------- #
# 1) 主例：同门店 2 行 → fail-closed 不联结（R2-202D 原红）
# --------------------------------------------------------------------------- #


def test_same_store_two_rows_does_not_join(chat_app, chat_admin, chat_employee, chat_model):
    """同门店 2 行店家行（同一 active 版本、业务日窗口内）→ 不联结、不并出互斥状态值。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_TWO_FOR_STORE)
    info = _ask_info(chat_app, chat_employee, QUESTION_CROSS)

    # 触发条件成立（不是靠"没进联结条件"取胜）：record + enumerate + 跨级角色 + filters 含 item。
    assert info["mode"] == "record", info
    assert info["enumerate"] is True, info
    assert info["filters"] == ["item"], info
    assert set(info["field_roles"]) == {"location", "status"}, info
    assert len(info["state_items"]) <= 1, info
    assert info["state_stores"] == (), info
    assert info["kind"] == "answer", info
    # 物品级值仍由唯一物品行给出（不因 fail-closed 丢物品答案）。
    assert ITEM_LOCATION in info["text"], info["text"]

    # ---- 红态断言：守卫缺失时这里会失败（两条店家行被并入）----------------
    both = (STORE_STATUS in info["text"], STORE_STATUS_ENDED in info["text"])
    store_sources = [name for name in info["sources"] if name == STORE_DOC]
    assert both == (False, False), (
        f"守卫缺失（红态）：同门店两行店家行被一并并入 → 合作中={both[0]}、已终止={both[1]}；"
        f"sources={info['sources']}（店家来源 {len(store_sources)} 条，rows={info['rows']}）；"
        f"pagination={info['pagination']}；text={info['text']!r}"
    )
    # ---- 绿态：只有物品文档 1 条来源，没有任何店家级值 --------------------
    assert info["sources"] == [ITEM_DOC], info["sources"]
    assert info["pagination"] is not None, info
    assert (info["pagination"]["total"], info["pagination"]["returned"]) == (1, 1), info["pagination"]
    assert chat_model.calls == [], chat_model.calls

    # 诊断：固定码区分（不带门店名/行数等业务值）。
    diagnostics, exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_CROSS)
    assert diagnostics["store_join"] == {"status": "store_row_ambiguous"}, diagnostics.get("store_join")
    assert [chunk.entity_type for chunk in exact] == ["item"], [c.entity_type for c in exact]


def test_same_store_one_row_still_joins(chat_app, chat_admin, chat_employee, chat_model, monkeypatch):
    """回归：同门店恰好 1 行 → 既有行为逐项不变（total=2 / returned=2 / sources=2 / 两值都在）。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_ONE_PER_STORE)
    info = _ask_info(chat_app, chat_employee, QUESTION_CROSS)

    assert info["kind"] == "answer", info
    assert info["filters"] == ["item"], info
    assert info["enumerate"] is True, info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS in info["text"], info
    assert STORE_STATUS_ENDED not in info["text"], info
    assert sorted(info["sources"]) == sorted({ITEM_DOC, STORE_DOC}), info["sources"]
    assert len(info["sources"]) == 2, info["sources"]
    assert info["pagination"] is not None, info
    assert (info["pagination"]["total"], info["pagination"]["returned"]) == (2, 2), info["pagination"]
    assert chat_model.calls == [], chat_model.calls

    diagnostics, exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_CROSS)
    payload = diagnostics["store_join"]
    assert payload["status"] == "joined", payload
    assert payload["store"] == STORE, payload
    assert payload["chunk_ids"] == [exact[-1].chunk_id], payload
    assert [chunk.entity_type for chunk in exact] == ["item", "store"], [c.entity_type for c in exact]

    # 逐字节等价：把唯一性检查强制恒真（= 加守卫前的判定）后，正文/来源/分页完全一致。
    _guard_on(monkeypatch)
    forced = _ask_info(chat_app, chat_employee, QUESTION_CROSS)
    assert forced["kind"] == info["kind"], (forced["kind"], info["kind"])
    assert forced["text"] == info["text"], (forced["text"], info["text"])
    assert forced["sources"] == info["sources"], (forced["sources"], info["sources"])
    assert forced["pagination"] == info["pagination"], (forced["pagination"], info["pagination"])


# --------------------------------------------------------------------------- #
# 2) 另一侧 fail-closed：0 条店家行（店家表无该店 / 门店值派生不出）
# --------------------------------------------------------------------------- #


def test_store_table_without_target_store_does_not_join(chat_app, chat_admin, chat_employee, chat_model):
    """派生门店值在店家表命中 0 行 → 不联结、``store_row_missing``。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_NO_TARGET_STORE)
    info = _ask_info(chat_app, chat_employee, QUESTION_CROSS)

    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info["sources"]
    assert chat_model.calls == [], chat_model.calls

    diagnostics, exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_CROSS)
    assert diagnostics["store_join"] == {"status": "store_row_missing"}, diagnostics.get("store_join")
    assert [chunk.entity_type for chunk in exact] == ["item"], [c.entity_type for c in exact]


def test_item_row_without_store_value_never_reaches_the_join(chat_app, chat_admin, chat_employee, chat_model):
    """物品行门店值缺失 → 语料层就不是 item 行，联结触发条件不成立（逐字同 202C）。

    ``rag/chunking.py::_entity_of`` 的 ``entity_type`` 判据要求 store 与 item **同时**存在，
    门店值缺失的行因此落到 ``record``；``item_rows`` 为空 → 触发条件不成立 → 不写
    ``store_join``（与加守卫前逐字相同）。这一态由下面 ``test_underivable_store_value_maps_to_missing``
    在守卫层面单独钉住。
    """

    _dataset(
        chat_app,
        chat_admin,
        item_rows=[
            [None, ITEM, "P01", ITEM_LOCATION, "4"],
            ["白鹭店", "折叠椅", "P02", "乙区2号架", "6"],
        ],
    )
    info = _ask_info(chat_app, chat_employee, QUESTION_CROSS)

    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert STORE_STATUS_ENDED not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info["sources"]
    assert chat_model.calls == [], chat_model.calls

    diagnostics, exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_CROSS)
    assert "store_join" not in diagnostics, diagnostics
    assert [chunk.entity_type for chunk in exact] == ["record"], [c.entity_type for c in exact]


def test_underivable_store_value_maps_to_missing(monkeypatch):
    """守卫层面：派生门店值为空 → ``store_row_missing``（语料层不可达，故在函数层钉住）。"""

    from types import SimpleNamespace

    from mktkb.rag import retrieval as rag_retrieval

    chunk = SimpleNamespace(
        entity_type="item",
        record_unit_id="unit-1",
        chunk_id="chunk-1",
        filters_norm={},
        role_values={"location": "甲区1号架"},
    )
    plan = SimpleNamespace(
        mode="record",
        enumerate=True,
        field_role=None,
        field_roles=("location", "status"),
        filters={"item": ITEM},
        state=SimpleNamespace(items=(ITEM,), stores=()),
    )
    monkeypatch.setattr(rag_retrieval, "_base_stmt", lambda *args, **kwargs: None)
    monkeypatch.setattr(rag_retrieval, "_load", lambda session, stmt: [chunk])

    decision = rag_retrieval._store_join_chunks(None, plan)
    assert tuple(decision) == ("", []), decision
    assert decision.status == "store_row_missing", decision.status

    diagnostics: dict = {}
    rag_retrieval._exact_recall(None, None, plan, diagnostics)
    assert diagnostics["store_join"] == {"status": "store_row_missing"}, diagnostics["store_join"]


# --------------------------------------------------------------------------- #
# 3) 既有反例 C1–C7（守卫前后必须逐项一致）
# --------------------------------------------------------------------------- #


def test_c1_location_only_has_no_store_level_value_or_join(chat_app, chat_admin, chat_employee, chat_model):
    """C1：只问位置 → 不触发联结，诊断里不出现 ``store_join``。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_TWO_FOR_STORE)
    info = _ask_info(chat_app, chat_employee, QUESTION_LOCATION_ONLY)

    assert info["kind"] == "answer", info
    assert info["field_roles"] == ("location",), info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert STORE_STATUS_ENDED not in info["text"], info
    assert "合作状态" not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info["sources"]
    assert chat_model.calls == [], chat_model.calls

    diagnostics, _exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_LOCATION_ONLY)
    assert "store_join" not in diagnostics, diagnostics


def test_c2_store_only_keeps_store_target(chat_app, chat_admin, chat_employee, chat_model):
    """C2：只问店家属性 → 目标仍是店家行；不触发联结。

    用「每店 1 行」的默认语料：同店 2 行时门店实体会先在实体解析层被判为多候选
    （clarification），那是守卫之外的既有行为，见报告风险节。
    """

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_STORE_ONLY)

    assert info["kind"] == "answer", info
    assert info["filters"] == ["store"], info
    assert ITEM_LOCATION not in info["text"], info
    assert info["sources"] == [STORE_DOC], info["sources"]
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "合作状态" in evidence[0]["fields"], evidence
    assert "位置" not in evidence[0]["fields"], evidence

    diagnostics, _exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_STORE_ONLY)
    assert "store_join" not in diagnostics, diagnostics


def test_c3_item_plus_phone_is_still_refused(chat_app, chat_admin, chat_employee, chat_model):
    """C3：物品 + 电话仍在检索/模型之前整体拒答（守卫不参与）。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_TWO_FOR_STORE)
    info = _ask_info(chat_app, chat_employee, QUESTION_PHONE)

    assert info["kind"] == "not_found", info
    assert info["sources"] == [], info
    assert info["reason"] == "SECURITY_RESTRICTED_CONTACT", info
    assert chat_model.calls == [], "安全拒答不得调用模型"

    diagnostics, _exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_PHONE)
    assert "store_join" not in diagnostics, diagnostics


def test_c4_same_item_in_two_stores_does_not_join(chat_app, chat_admin, chat_employee, chat_model):
    """C4：同名物品落两家门店 → 物品目标不唯一 → 不联结（守卫不参与，触发条件不成立）。"""

    _dataset(
        chat_app,
        chat_admin,
        item_rows=[
            [STORE, ITEM, "P01", ITEM_LOCATION, "4"],
            ["白鹭店", ITEM, "P09", "乙区9号架", "2"],
            [STORE, "折叠椅", "P02", "甲区2号架", "6"],
        ],
    )
    info = _ask_info(chat_app, chat_employee, QUESTION_CROSS)

    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert set(info["sources"]) == {ITEM_DOC}, info["sources"]
    assert chat_model.calls == [], chat_model.calls

    diagnostics, _exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_CROSS)
    assert "store_join" not in diagnostics, diagnostics


def test_c5_expired_store_row_is_not_joined(chat_app, chat_admin, chat_employee, chat_model):
    """C5：店家行已过有效期 → 记录面过滤后 0 行 → 不联结（``store_row_missing``）。"""

    _dataset(
        chat_app,
        chat_admin,
        store_rows=[
            ["S01", STORE, "合成对接人·甲", STORE_STATUS, "2026-10-31"],
            ["S02", "白鹭店", "合成对接人·乙", "暂停合作", "2026-12-31"],
        ],
        store_headers=[*STORE_HEADERS, "失效日期"],
    )
    question = f"截至2026-11-01，{ITEM}的位置在哪里，合作状态分别是什么？"
    info = _ask_info(chat_app, chat_employee, question)

    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info["sources"]
    assert chat_model.calls == [], chat_model.calls

    diagnostics, _exact = _retrieval_diagnostics(chat_app, chat_employee, question)
    assert diagnostics["store_join"] == {"status": "store_row_missing"}, diagnostics.get("store_join")


def test_c6_multi_item_enumeration_is_unchanged(chat_app, chat_admin, chat_employee, monkeypatch):
    """C6：多物品目标 → 触发条件不成立；正文/来源与关掉联结入口时逐字相同。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_TWO_FOR_STORE)
    before = _ask_info(chat_app, chat_employee, QUESTION_MULTI_ITEM)
    _disable_join(monkeypatch)
    after = _ask_info(chat_app, chat_employee, QUESTION_MULTI_ITEM)

    assert before["reason"] == "MULTI_TARGET_ENUMERATE", before
    assert before["kind"] == after["kind"], (before["kind"], after["kind"])
    assert before["text"] == after["text"], (before["text"], after["text"])
    assert before["sources"] == after["sources"], (before["sources"], after["sources"])
    assert STORE_STATUS not in before["text"], before["text"]
    assert STORE_STATUS_ENDED not in before["text"], before["text"]


def test_c7_policy_turn_is_byte_identical(chat_app, chat_admin, chat_employee, chat_model, monkeypatch):
    """C7：``mode=document`` → 触发条件不成立；正文/来源与关掉联结入口时逐字相同。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_TWO_FOR_STORE)
    _policy_dataset(chat_app, chat_admin)
    before = _ask_info(chat_app, chat_employee, QUESTION_POLICY)
    chat_model.calls.clear()
    _disable_join(monkeypatch)
    after = _ask_info(chat_app, chat_employee, QUESTION_POLICY)

    assert before["mode"] == "document", before
    assert before["kind"] == after["kind"], (before["kind"], after["kind"])
    assert before["text"] == after["text"], (before["text"], after["text"])
    assert before["sources"] == after["sources"], (before["sources"], after["sources"])
    assert STORE_STATUS not in before["text"], before["text"]
    assert STORE_STATUS_ENDED not in before["text"], before["text"]

    diagnostics, _exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_POLICY)
    assert "store_join" not in diagnostics, diagnostics


# --------------------------------------------------------------------------- #
# 4) 敏感性：守卫是那条红例的唯一开关
# --------------------------------------------------------------------------- #


def test_uniqueness_guard_is_the_only_switch(chat_app, chat_admin, chat_employee, chat_model, monkeypatch):
    """把唯一性检查 monkeypatch 成恒真 → 同门店 2 行**回到红**；恢复即绿。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_TWO_FOR_STORE)

    green = _ask_info(chat_app, chat_employee, QUESTION_CROSS)
    assert STORE_STATUS not in green["text"], green["text"]
    assert STORE_STATUS_ENDED not in green["text"], green["text"]
    assert green["sources"] == [ITEM_DOC], green["sources"]

    _guard_on(monkeypatch)
    red = _ask_info(chat_app, chat_employee, QUESTION_CROSS)
    assert STORE_STATUS in red["text"], red["text"]
    assert STORE_STATUS_ENDED in red["text"], red["text"]
    assert red["sources"] == [ITEM_DOC, STORE_DOC, STORE_DOC], red["sources"]
    assert red["pagination"]["total"] == 3, red["pagination"]
    red_diagnostics, red_exact = _retrieval_diagnostics(chat_app, chat_employee, QUESTION_CROSS)
    assert red_diagnostics["store_join"]["status"] == "joined", red_diagnostics.get("store_join")
    assert len(red_diagnostics["store_join"]["chunk_ids"]) == 2, red_diagnostics.get("store_join")
    assert [chunk.entity_type for chunk in red_exact] == ["item", "store", "store"], [
        c.entity_type for c in red_exact
    ]

    monkeypatch.undo()
    restored = _ask_info(chat_app, chat_employee, QUESTION_CROSS)
    assert restored["text"] == green["text"], (restored["text"], green["text"])
    assert restored["sources"] == green["sources"], (restored["sources"], green["sources"])


# --------------------------------------------------------------------------- #
# 5) 零出站：模块级守卫 + 显式断言
# --------------------------------------------------------------------------- #


def test_offline_chain_has_zero_external_network_and_no_subprocess(
    t09_network_guard, no_subprocess, chat_app, chat_admin, chat_employee, chat_model
):
    """合成链路零出站、零子进程：跑完主例/回归/反例后审计守卫账本。"""

    _dataset(chat_app, chat_admin, store_rows=STORE_ROWS_TWO_FOR_STORE)
    for question in (QUESTION_CROSS, QUESTION_LOCATION_ONLY, QUESTION_STORE_ONLY, QUESTION_PHONE):
        _ask(chat_employee, _conversation(chat_employee), question)

    snapshot = t09_network_guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]
    assert no_subprocess == [], no_subprocess
