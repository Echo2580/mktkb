"""T-R2-204 独立预验收：外部执行者自建的对抗探针（不属于开发方的 202A/202C/203C 用例集）。

纪律：
- 本文件只读产品代码，不改 ``backend/src/**``；所有变异都在运行时用 ``monkeypatch``。
- 全部合成数据为虚构实体（云杉店/松涛店/样品柜/样品架/样品凳），不含任何真实 case_id、
  题面、期望值或实体值；业务日由 ``Settings.rag_business_date`` 显式钉住。
- 链路是产品正式链路：multipart 上传 → ``run_one_job``（解析/索引）→ publish →
  ``POST /api/v1/conversations/{id}/messages``；模型是 ``tests/conftest.py`` 的
  ``EvidenceEchoGateway`` 替身，索引 offline。零出站、零子进程。

判据映射（见 ``evidence/08-independent/R2-INDEPENDENT-REVIEW.md``）：
- A  ：``test_204_a_*``（同形红/绿 + 红态断言消息原文）
- B/G：``test_204_b_g_*``（同形键逐字节相等 → passed；还原 R0 派生 → unknown）
- D  ：``test_204_d1..d5*``（单问物品 / 单问店家 / 物品+电话 / 异店行对抗 / 三类异常）
- F  ：``test_204_f_*``（``total`` 新数字的结构 token 出处）
- G  ：``test_204_g_*``（legacy 联结开关、日期闭区间边界）
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.config import Settings  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402

ORIGIN = "http://testserver"
BUSINESS_DATE = "2026-11-20"

ITEM_DOC = "样例位置台账.xlsx"
STORE_DOC = "样例合作方信息.xlsx"
ITEM_DOC_TITLE = "样例位置台账"
STORE_DOC_TITLE = "样例合作方信息"

ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
#: 行号：标题 1 / 空 2 / 表头 3 / 数据自 4 起
ITEM_ROWS = [
    ["云杉店", "样品柜", "Y01", "北区2号架", "5"],
    ["云杉店", "样品架", "Y02", "北区3号架", "7"],
    ["松涛店", "样品凳", "Y03", "南区1号架", "9"],
]
STORE_HEADERS = ["标识", "店家", "对接人", "合作状态"]
#: 故意把**非目标店**放在第 4 行、目标店放在第 5 行 —— 引用行可由此分辨。
STORE_ROWS = [
    ["K02", "松涛店", "合成对接人·乙", "已终止"],
    ["K01", "云杉店", "合成对接人·甲", "合作中"],
]

STORE = "云杉店"
OTHER_STORE = "松涛店"
ITEM = "样品柜"
ITEM_LOCATION = "北区2号架"
STORE_STATUS = "合作中"
OTHER_STATUS = "已终止"
ITEM_TARGET_ROW = 4
STORE_TARGET_ROW = 5
STORE_OTHER_ROW = 4
HEADER_ROW = 3

Q_CROSS = "样品柜的位置在哪里，合作状态分别是什么？"
Q_CROSS_NAMED = "云杉店的样品柜放在哪个位置，合作状态分别是什么？"
Q_ITEM_ONLY = "样品柜分别放在哪个位置？"
Q_STORE_ONLY = "云杉店的合作状态是什么？"
Q_CONTACT = "样品柜的联系电话是多少？"
Q_MULTI_ITEM = "样品柜和样品凳的位置在哪里，合作状态分别是什么？"
Q_LEGACY = "云杉店的样品柜放在哪个位置，合作状态如何？"
LEGACY_ANSWER = f"根据资料：{STORE}的{ITEM}位置：{ITEM_LOCATION}；合作状态：{STORE_STATUS}。"


def _witness(tag: str, **fields: object) -> None:
    print("WITNESS204 " + json.dumps({"tag": tag, **fields}, ensure_ascii=False, sort_keys=True))


# --------------------------------------------------------------------------- #
# 守卫 / 装配
# --------------------------------------------------------------------------- #
@pytest.fixture
def no_subprocess(monkeypatch):
    calls: list[tuple] = []

    def _blocked(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((args, tuple(sorted(kwargs))))
        raise AssertionError("合成链路不得启动子进程")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    yield calls
    assert calls == [], calls


def _settings(root: Path, *, business_date: str | None) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=root,
        database_url=f"sqlite:///{(root / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="INFO",
        rag_business_date=business_date,
    )


def _build(root: Path, chat_model, *, business_date: str | None = BUSINESS_DATE):
    return create_app(_settings(root, business_date=business_date), model_gateway=chat_model)


def _session(app, username: str, password: str) -> SimpleNamespace:
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200, response.text
    body = client.get("/api/v1/auth/me").json()
    return SimpleNamespace(
        client=client,
        headers={"Origin": ORIGIN, "X-CSRF-Token": body["csrf_token"]},
        user_id=str(body["user"]["id"]),
    )


def _xlsx_sheets(path: Path, sheets: list[tuple[str, list[str], list[list[object]]]]) -> Path:
    """多 sheet 合成件（每个 sheet 各自一份表头 + 数据行）。"""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, headers, rows in sheets:
        worksheet = workbook.create_sheet(title)
        worksheet.cell(row=1, column=1, value=title)
        for column, header in enumerate(headers, start=1):
            worksheet.cell(row=3, column=column, value=header)
        for offset, row in enumerate(rows):
            for column, value in enumerate(row, start=1):
                worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


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


def _publish(app, admin: SimpleNamespace, path: Path) -> dict:
    receipt = admin.client.post(
        "/api/v1/documents",
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
        data={},
        headers=admin.headers,
    )
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
    return {
        "document_id": str(record["document"]["id"]),
        "version_id": str(record["version"]["id"]),
        "document_name": path.name,
        "version_number": int(published.json().get("version_number") or 1),
    }


def _dataset(
    app,
    admin: SimpleNamespace,
    *,
    item_rows: list[list[object]] | None = None,
    store_headers: list[str] | None = None,
    store_rows: list[list[object]] | None = None,
) -> dict:
    root = Path(app.state.settings.data_dir)
    return {
        ITEM_DOC: _publish(app, admin, _xlsx(root / ITEM_DOC, ITEM_HEADERS, item_rows or ITEM_ROWS, ITEM_DOC_TITLE)),
        STORE_DOC: _publish(
            app,
            admin,
            _xlsx(root / STORE_DOC, store_headers or STORE_HEADERS, store_rows or STORE_ROWS, STORE_DOC_TITLE),
        ),
    }


def _conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session: SimpleNamespace, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{_conversation(session)}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _plan(app, session: SimpleNamespace, question: str):
    qa = app.state.qa
    qa.ensure_ready()
    return qa.prepare(question, session.user_id, _conversation(session))[1]


def _answer(app, session: SimpleNamespace, question: str):
    qa = app.state.qa
    qa.ensure_ready()
    return qa.answer(question, session.user_id, _conversation(session))


def _docs(body: dict) -> list[str]:
    return [str(item.get("document_name") or "") for item in body.get("sources") or []]


def _store_join_diag(app, plan) -> dict:
    """202D 的判定码写在**检索结果**的 diagnostics 里（不是 RagAnswer.diagnostics）。"""
    result = app.state.qa.index().search(plan)
    payload = (getattr(result, "diagnostics", None) or {}).get("store_join")
    return dict(payload) if isinstance(payload, dict) else {}


def _shape(plan) -> dict:
    state = getattr(plan, "state", None)
    return {
        "mode": str(getattr(plan, "mode", "")),
        "enumerate": bool(getattr(plan, "enumerate", False)),
        "filters": sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})),
        "field_role": getattr(plan, "field_role", None),
        "field_roles": list(getattr(plan, "field_roles", ()) or ()),
        "items": list(getattr(state, "items", ()) or ()),
        "stores": list(getattr(state, "stores", ()) or ()),
    }


def _disable_c29_join(monkeypatch) -> None:
    """敏感性①：关掉 202C 的检索层唯一入口（等价于修前）。"""
    from mktkb.rag import retrieval as rag_retrieval

    monkeypatch.setattr(rag_retrieval, "_store_join_chunks", lambda session, plan: ("", []))


# 绿态断言包：**六条**都必须成立，任一条失败即说明该轮没做到「两类值 + 两条不同文档来源 +
# 版本/门店行约束」。敏感性对照失败时，报出来的就是这里的断言消息原文。
def _assert_cross_green(app, session: SimpleNamespace, question: str, versions: dict) -> dict:
    plan = _plan(app, session, question)
    body = _ask(session, question)
    sources = [dict(item) for item in body.get("sources") or []]
    text = body.get("text") or ""
    assert body.get("kind") == "answer", body
    # (1) 两类值同处一条正文
    assert ITEM_LOCATION in text, text
    assert STORE_STATUS in text, f"assert {STORE_STATUS!r} in text -> {text}"
    # (2) 恰两条来源、两份不同文档（不是"非空"）
    assert len(sources) == 2, sources
    names = sorted(str(s.get("document_name")) for s in sources)
    assert names == sorted([ITEM_DOC, STORE_DOC]), names
    # (3) 版本/状态/发布时刻与发布回执逐值一致
    for source in sources:
        pinned = versions[source["document_name"]]
        assert str(source.get("status")) == "active", source
        assert int(source.get("version_number") or 0) == pinned["version_number"], source
        assert source.get("published_at"), source
        assert dict(source.get("locator") or {}).get("header_row") == HEADER_ROW, source
    # (4) 门店行约束：店家级来源必须是**被问门店那一行**（第 5 行），不是同表另一店（第 4 行）
    by_doc = {str(s["document_name"]): s for s in sources}
    assert int(dict(by_doc[ITEM_DOC].get("locator") or {}).get("row") or 0) == ITEM_TARGET_ROW, by_doc[ITEM_DOC]
    assert int(dict(by_doc[STORE_DOC].get("locator") or {}).get("row") or 0) == STORE_TARGET_ROW, by_doc[STORE_DOC]
    # (5) 触发条件确实成立（否则"绿"可能来自别的分支）
    assert str(getattr(plan, "mode", "")) == "record", _shape(plan)
    assert bool(getattr(plan, "enumerate", False)) is True, _shape(plan)
    assert sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})) == ["item"], _shape(plan)
    assert set(getattr(plan, "field_roles", ()) or ()) == {"location", "status"}, _shape(plan)
    return {"plan": plan, "body": body, "sources": sources}


def _open_app(store, chat_model, *, business_date: str | None = BUSINESS_DATE):
    app = _build(store.root, chat_model, business_date=business_date)
    admin = _session(app, "admin", "AdminPass-1")
    employee = _session(app, "employee", "EmployeePass-1")
    versions = _dataset(app, admin)
    return app, admin, employee, versions


# --------------------------------------------------------------------------- #
# A. C29 同形：修前红 / 修后绿（红态断言消息原文留档）
# --------------------------------------------------------------------------- #
def test_204_a_same_shape_is_red_before_and_green_after(
    store, chat_model, monkeypatch, t09_network_guard, no_subprocess
):
    app, _admin, employee, versions = _open_app(store, chat_model)
    try:
        # ---- 修后（当前工作树）：绿 ----
        chat_model.calls.clear()
        green = _assert_cross_green(app, employee, Q_CROSS, versions)
        assert chat_model.calls == [], chat_model.calls
        # 202D：恰好 1 条时必须 `joined`（诊断码），且并入的就是那 1 条
        joined = _store_join_diag(app, green["plan"])
        _witness(
            "a-joined-diagnostics",
            store_join=joined,
            chunk_count=len(joined.get("chunk_ids") or []),
            store_key=sorted(joined),
        )
        assert joined.get("status") == "joined", joined
        assert len(joined.get("chunk_ids") or []) == 1, joined
        assert joined.get("store") == STORE, joined
        _witness(
            "a-green",
            kind=green["body"]["kind"],
            sources=_docs(green["body"]),
            text=green["body"]["text"],
            shape=_shape(green["plan"]),
        )

        # ---- 修前（运行时关掉检索层联结入口）：红，且红态可量化 ----
        _disable_c29_join(monkeypatch)
        chat_model.calls.clear()
        red = _ask(employee, Q_CROSS)
        red_text = red.get("text") or ""
        _witness(
            "a-red",
            kind=red.get("kind"),
            sources=_docs(red),
            text=red_text,
            has_location=ITEM_LOCATION in red_text,
            has_status=STORE_STATUS in red_text,
            model_calls=len(chat_model.calls),
        )
        assert red.get("kind") == "answer", red
        assert _docs(red) == [ITEM_DOC], red.get("sources")
        assert ITEM_LOCATION in red_text, red_text
        assert STORE_STATUS not in red_text, red_text
        # C29 的失败形态逐项同形：值 1/2、来源 1/2、kind=answer、模型 0 调用
        assert len(_docs(red)) == 1 and len(green["sources"]) == 2, red.get("sources")
        assert chat_model.calls == [], chat_model.calls

        # 红态断言消息原文：同一组绿态断言在修前必然失败，失败点必须正是「店家级值缺失」
        with pytest.raises(AssertionError) as excinfo:
            _assert_cross_green(app, employee, Q_CROSS, versions)
        message = str(excinfo.value)
        _witness("a-red-assertion-message", message=message[:400])
        assert f"assert {STORE_STATUS!r} in text" in message, message

        # ---- 恢复即回绿（同一 app，同一数据） ----
        monkeypatch.undo()
        restored = _assert_cross_green(app, employee, Q_CROSS, versions)
        assert STORE_STATUS in restored["body"]["text"]
        named_plan = _plan(app, employee, Q_CROSS_NAMED)
        named = _ask(employee, Q_CROSS_NAMED)
        assert sorted(str(k) for k in dict(getattr(named_plan, "filters", {}) or {})) == ["item", "store"], _shape(named_plan)
        assert STORE_STATUS in (named.get("text") or ""), named.get("text")
        assert len(named.get("sources") or []) == 2, named.get("sources")
        assert t09_network_guard.snapshot()["external"] == []
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# H. 202D 的"恰好 1 条"透明性：去掉 status 语义（返回裸二元组）后
#    kind / text / sources / pagination 必须**逐字相同**（含记录标记）
# --------------------------------------------------------------------------- #
def test_204_h_guard_is_transparent_for_unique_case(
    store, chat_model, monkeypatch, t09_network_guard, no_subprocess
):
    from mktkb.rag import retrieval as rag_retrieval

    app, _admin, employee, _versions = _open_app(store, chat_model)
    try:
        chat_model.calls.clear()
        guarded = _ask(employee, Q_CROSS)
        diag = _store_join_diag(app, _plan(app, employee, Q_CROSS))
        original = rag_retrieval._store_join_chunks

        def _bare(session, plan):  # noqa: ANN001, ANN202
            value = original(session, plan)
            store_value, rows = value
            return (store_value, rows) if rows else ("", [])

        monkeypatch.setattr(rag_retrieval, "_store_join_chunks", _bare)
        bare = _ask(employee, Q_CROSS)
        _witness(
            "h-transparent",
            kind_equal=guarded.get("kind") == bare.get("kind"),
            text_equal=guarded.get("text") == bare.get("text"),
            sources_equal=(guarded.get("sources") or []) == (bare.get("sources") or []),
            pagination_equal=(guarded.get("pagination") or {}) == (bare.get("pagination") or {}),
            guarded_pagination=guarded.get("pagination"),
            store_join=diag,
        )
        assert diag.get("status") == "joined", diag
        assert guarded.get("kind") == bare.get("kind") == "answer"
        assert guarded.get("text") == bare.get("text"), (guarded.get("text"), bare.get("text"))
        assert (guarded.get("sources") or []) == (bare.get("sources") or [])
        assert (guarded.get("pagination") or {}) == (bare.get("pagination") or {})
        assert chat_model.calls == [], chat_model.calls
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D1. 单问物品属性 → 不得多出店家级值 / 店家级来源
# --------------------------------------------------------------------------- #
def test_204_d1_item_only_question_has_no_store_level_value(
    store, chat_model, t09_network_guard, no_subprocess
):
    app, _admin, employee, _versions = _open_app(store, chat_model)
    try:
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_ITEM_ONLY)
        body = _ask(employee, Q_ITEM_ONLY)
        text = body.get("text") or ""
        _witness("d1", kind=body.get("kind"), sources=_docs(body), text=text, shape=_shape(plan))
        assert bool(getattr(plan, "enumerate", False)) is True, _shape(plan)
        assert set(getattr(plan, "field_roles", ()) or ()) == {"location"}, _shape(plan)
        assert body.get("kind") == "answer", body
        assert ITEM_LOCATION in text, text
        assert STORE_STATUS not in text, text
        assert "合作状态" not in text, text
        assert _docs(body) == [ITEM_DOC], body.get("sources")
        assert len(body.get("sources") or []) == 1, body.get("sources")
        assert chat_model.calls == [], chat_model.calls
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D2. 单问店家属性 → 目标不得被改写成物品
# --------------------------------------------------------------------------- #
def test_204_d2_store_only_question_keeps_store_target(
    store, chat_model, t09_network_guard, no_subprocess
):
    app, _admin, employee, _versions = _open_app(store, chat_model)
    try:
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_STORE_ONLY)
        answer = _answer(app, employee, Q_STORE_ONLY)
        body = _ask(employee, Q_STORE_ONLY)
        text = body.get("text") or ""
        _witness(
            "d2",
            kind=body.get("kind"),
            sources=_docs(body),
            text=text,
            shape=_shape(plan),
            facts=[(f.field_role, f.value, f.entity_label, f.entity_key) for f in answer.facts],
        )
        assert sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})) == ["store"], _shape(plan)
        assert getattr(plan, "field_role", None) == "status", _shape(plan)
        assert body.get("kind") == "answer", body
        assert STORE_STATUS in text, text
        assert ITEM_LOCATION not in text, text
        assert _docs(body) == [STORE_DOC], body.get("sources")
        assert answer.facts, answer
        assert {fact.entity_label for fact in answer.facts} == {STORE}, [f.entity_label for f in answer.facts]
        assert {fact.field_role for fact in answer.facts} == {"status"}, [f.field_role for f in answer.facts]
        # 店家级目标没有被改写成物品目标：事实的实体键不是 item 型
        assert all(str(fact.entity_key or "").startswith("store|") for fact in answer.facts), [
            fact.entity_key for fact in answer.facts
        ]
        # 店家单问走 legacy（与 202A C2 同形）：允许 ≤1 次模型调用，证据只允许店家行
        assert len(chat_model.calls) <= 1, chat_model.calls
        if chat_model.calls:
            evidence = chat_model.calls[0]["evidence"]
            assert len(evidence) == 1, evidence
            assert "合作状态" in evidence[0]["fields"], evidence
            assert "位置" not in evidence[0]["fields"], evidence
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D3. 物品 + 电话 → 仍整体拒答、sources=[]、0 模型调用
# --------------------------------------------------------------------------- #
def test_204_d3_contact_plus_item_still_refuses_without_model(
    store, chat_model, t09_network_guard, no_subprocess
):
    app, _admin, employee, _versions = _open_app(store, chat_model)
    try:
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_CONTACT)
        body = _ask(employee, Q_CONTACT)
        text = body.get("text") or ""
        _witness(
            "d3",
            kind=body.get("kind"),
            sources=_docs(body),
            text=text,
            shape=_shape(plan),
            model_calls=len(chat_model.calls),
        )
        assert body.get("kind") == "not_found", body
        assert body.get("sources") == [], body.get("sources")
        assert "个人联系信息" in text, text
        assert ITEM_LOCATION not in text, text
        assert STORE_STATUS not in text, text
        assert chat_model.calls == [], chat_model.calls
        assert getattr(plan, "field_role", None) == "phone", _shape(plan)
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D4（对抗）。把「联结到的店家行」换成**另一家门店**的行 → 必须被
# ``FactValidator._joined_store_row`` 的门拦下（payload 仍说被问门店，行本身是异店）。
# --------------------------------------------------------------------------- #
def test_204_d4_foreign_store_row_is_gated_out(
    store, chat_model, monkeypatch, t09_network_guard, no_subprocess
):
    from mktkb.rag import retrieval as rag_retrieval

    app, _admin, employee, _versions = _open_app(store, chat_model)
    try:
        def _foreign(session, plan):
            rows = [
                chunk
                for chunk in rag_retrieval._load(
                    session,
                    rag_retrieval._base_stmt(
                        session, replace(plan, filters={"store": OTHER_STORE}), require_record=True
                    ),
                )
                if chunk.entity_type == "store"
            ]
            # payload 声称联结的是被问门店（云杉店），行本身却是松涛店的行
            return STORE, rows

        monkeypatch.setattr(rag_retrieval, "_store_join_chunks", _foreign)
        chat_model.calls.clear()
        answer = _answer(app, employee, Q_CROSS)
        body = _ask(employee, Q_CROSS)
        text = body.get("text") or ""
        _witness(
            "d4",
            kind=answer.kind,
            reason=answer.reason,
            text=answer.text,
            http_kind=body.get("kind"),
            sources=_docs(body),
        )
        assert OTHER_STATUS not in text, text
        assert STORE_STATUS not in text, text
        assert answer.kind in {"no_answer", "not_found"}, answer.kind
        assert answer.reason == "CROSS_ENTITY", answer.reason
        assert "事实来源不满足问题实体条件" in answer.text, answer.text
        assert t09_network_guard.snapshot()["external"] == []
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D5a（对抗）。同一门店两行店家（互斥状态值）—— R2-REGRESSION §6 D1 登记项
# --------------------------------------------------------------------------- #
def test_204_d5a_same_store_two_rows_are_not_joined(
    store, chat_model, t09_network_guard, no_subprocess
):
    """R2-202D 后：同店两行 **必须 fail-closed 不联结**。

    该断言由「记录缺陷」（202C 时代的 `both is True`）改为「记录已修」：期望
    `sources` 只含物品 1 条、正文无任何店家级值、`store_join={"status":"store_row_ambiguous"}`。
    """
    extra_store_rows = [
        ["K02", OTHER_STORE, "合成对接人·乙", OTHER_STATUS],
        ["K01", STORE, "合成对接人·甲", STORE_STATUS],
        ["K01B", STORE, "合成对接人·丙", OTHER_STATUS],
    ]
    app = _build(store.root, chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _dataset(app, admin, store_rows=extra_store_rows)
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_CROSS)
        body = _ask(employee, Q_CROSS)
        text = body.get("text") or ""
        diag = _store_join_diag(app, plan)
        _witness(
            "d5a-fixed",
            kind=body.get("kind"),
            sources=_docs(body),
            text=text,
            both_statuses_present=(STORE_STATUS in text) and (OTHER_STATUS in text),
            store_join=diag,
        )
        assert body.get("kind") == "answer", body
        assert _docs(body) == [ITEM_DOC], body.get("sources")
        assert len(body.get("sources") or []) == 1, body.get("sources")
        assert STORE_STATUS not in text, text
        assert OTHER_STATUS not in text, text
        assert "合作状态" not in text, text
        assert diag == {"status": "store_row_ambiguous"}, diag
        assert chat_model.calls == [], chat_model.calls
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D5a-2（对抗绕过法 B）。同一门店两行**分属同一文档的两个 sheet / 同一版本** → 仍不联结
# --------------------------------------------------------------------------- #
def test_204_d5a2_same_store_across_two_sheets_is_ambiguous(
    store, chat_model, t09_network_guard, no_subprocess
):
    app = _build(store.root, chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        root = Path(app.state.settings.data_dir)
        _publish(app, admin, _xlsx(root / ITEM_DOC, ITEM_HEADERS, ITEM_ROWS, ITEM_DOC_TITLE))
        _publish(
            app,
            admin,
            _xlsx_sheets(
                root / STORE_DOC,
                [
                    ("甲表", STORE_HEADERS, [["K01", STORE, "合成对接人·甲", STORE_STATUS]]),
                    ("乙表", STORE_HEADERS, [["K01B", STORE, "合成对接人·丙", OTHER_STATUS]]),
                ],
            ),
        )
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_CROSS)
        body = _ask(employee, Q_CROSS)
        text = body.get("text") or ""
        diag = _store_join_diag(app, plan)
        _witness("d5a2-sheets", kind=body.get("kind"), sources=_docs(body), text=text, store_join=diag)
        assert body.get("kind") == "answer", body
        assert _docs(body) == [ITEM_DOC], body.get("sources")
        assert STORE_STATUS not in text, text
        assert OTHER_STATUS not in text, text
        assert diag == {"status": "store_row_ambiguous"}, diag
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D5a-3（对抗绕过法 C）。物品目标跨两家门店（门店值 >1）+ 同店多行同时出现 → 不联结
# --------------------------------------------------------------------------- #
def test_204_d5a3_multistore_item_group_plus_dup_store_rows(
    store, chat_model, t09_network_guard, no_subprocess
):
    item_rows = [
        ["云杉店", "样品柜", "Y01", "北区2号架", "5"],
        ["松涛店", "样品柜", "Y01B", "南区7号架", "2"],
    ]
    store_rows = [
        ["K02", OTHER_STORE, "合成对接人·乙", OTHER_STATUS],
        ["K01", STORE, "合成对接人·甲", STORE_STATUS],
        ["K01B", STORE, "合成对接人·丙", OTHER_STATUS],
    ]
    app = _build(store.root, chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _dataset(app, admin, item_rows=item_rows, store_rows=store_rows)
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_CROSS)
        answer = _answer(app, employee, Q_CROSS)
        body = _ask(employee, Q_CROSS)
        text = body.get("text") or ""
        diag = _store_join_diag(app, plan)
        _witness(
            "d5a3-multistore",
            kind=body.get("kind"),
            sources=_docs(body),
            text=text,
            store_join=diag,
            shape=_shape(plan),
        )
        assert body.get("kind") == "answer", body
        assert set(_docs(body)) == {ITEM_DOC}, body.get("sources")
        assert STORE_STATUS not in text, text
        assert OTHER_STATUS not in text, text
        assert not diag or diag.get("status") in {"store_row_ambiguous", "store_row_missing"}, diag
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D5a-4（对抗绕过法 D）。派生门店值命中的店家行为 0 条 → store_row_missing 且不联结
# --------------------------------------------------------------------------- #
def test_204_d5a4_store_row_missing_is_not_joined(
    store, chat_model, t09_network_guard, no_subprocess
):
    store_rows = [["K02", OTHER_STORE, "合成对接人·乙", OTHER_STATUS]]
    app = _build(store.root, chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _dataset(app, admin, store_rows=store_rows)
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_CROSS)
        body = _ask(employee, Q_CROSS)
        text = body.get("text") or ""
        diag = _store_join_diag(app, plan)
        _witness("d5a4-missing", kind=body.get("kind"), sources=_docs(body), text=text, store_join=diag)
        assert body.get("kind") == "answer", body
        assert _docs(body) == [ITEM_DOC], body.get("sources")
        assert STORE_STATUS not in text, text
        assert OTHER_STATUS not in text, text
        assert diag == {"status": "store_row_missing"}, diag
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D5a-5（对抗绕过法 A）。守卫按**记录身份计数==1**：同 id 两行会不会被欺骗
# --------------------------------------------------------------------------- #
def test_204_d5a5_unique_guard_counts_by_record_identity(store, chat_model, monkeypatch, t09_network_guard, no_subprocess):
    from dataclasses import replace as _replace

    from mktkb.rag import retrieval as rag_retrieval

    store_rows = [
        ["K02", OTHER_STORE, "合成对接人·乙", OTHER_STATUS],
        ["K01", STORE, "合成对接人·甲", STORE_STATUS],
        ["K01B", STORE, "合成对接人·丙", OTHER_STATUS],
    ]
    app = _build(store.root, chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _dataset(app, admin, store_rows=store_rows)

        # (1) 真实数据下"按记录身份计数"的前提成立：命中的店家行 id 互不相同
        qa = app.state.qa
        qa.ensure_ready()
        plan = _plan(app, employee, Q_CROSS)
        with qa.index().session() as session:
            rows = [
                chunk
                for chunk in rag_retrieval._load(
                    session,
                    rag_retrieval._base_stmt(
                        session, _replace(plan, filters={"store": STORE}), require_record=True
                    ),
                )
                if chunk.entity_type == "store"
            ]
        ids = [chunk.record_unit_id or chunk.chunk_id for chunk in rows]
        _witness("d5a5-real-ids", row_count=len(rows), distinct_ids=len(set(ids)), unique=rag_retrieval._store_row_is_unique(rows))
        assert len(rows) == 2 and len(set(ids)) == 2
        assert rag_retrieval._store_row_is_unique(rows) is False

        # (2) 代码级：把两行的记录身份强行改成同一个 → 计数被欺骗（这一形状不可由 ingest 产生）
        forged = _replace(rows[1], record_unit_id=rows[0].record_unit_id, chunk_id=rows[0].chunk_id)
        fooled = rag_retrieval._store_row_is_unique([rows[0], forged])
        _witness("d5a5-forged-ids", unique=fooled)
        assert fooled is True

        # (3) 端到端：即便把"同 id 两行"塞进联结载荷，事实校验仍会按 chunk_id 重新取源并拦下
        def _fake_join(session_, plan_):  # noqa: ANN001, ANN202
            forged_rows = [
                _replace(
                    rows[1],
                    record_unit_id=rows[0].record_unit_id,
                    chunk_id=rows[0].chunk_id,
                ),
                rows[0],
            ]
            return rag_retrieval._StoreJoin(STORE, forged_rows, rag_retrieval.STORE_JOIN_JOINED)

        monkeypatch.setattr(rag_retrieval, "_store_join_chunks", _fake_join)
        answer = _answer(app, employee, Q_CROSS)
        _witness("d5a5-forged-e2e", kind=answer.kind, reason=answer.reason, text=answer.text)
        assert OTHER_STATUS not in (answer.text or ""), answer.text
        assert answer.kind in {"no_answer", "not_found"}, (answer.kind, answer.reason)
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D5b（对抗）。多目标物品 → 不联结
# --------------------------------------------------------------------------- #
def test_204_d5b_multi_item_targets_do_not_join(
    store, chat_model, t09_network_guard, no_subprocess
):
    app, _admin, employee, _versions = _open_app(store, chat_model)
    try:
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_MULTI_ITEM)
        body = _ask(employee, Q_MULTI_ITEM)
        text = body.get("text") or ""
        _witness("d5b", kind=body.get("kind"), sources=_docs(body), text=text, shape=_shape(plan))
        assert len(getattr(plan.state, "items", ()) or ()) > 1, _shape(plan)
        assert STORE_STATUS not in text, text
        assert OTHER_STATUS not in text, text
        assert set(_docs(body)) == {ITEM_DOC}, body.get("sources")
        assert chat_model.calls == [], chat_model.calls
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# D5c（对抗）。物品行门店值缺失 → 不联结
# --------------------------------------------------------------------------- #
def test_204_d5c_missing_store_value_does_not_join(
    store, chat_model, t09_network_guard, no_subprocess
):
    item_rows = [
        [None, "样品柜", "Y09", "北区9号架", "3"],
        ["松涛店", "样品凳", "Y03", "南区1号架", "9"],
    ]
    app = _build(store.root, chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _dataset(app, admin, item_rows=item_rows)
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_CROSS)
        body = _ask(employee, Q_CROSS)
        text = body.get("text") or ""
        _witness("d5c", kind=body.get("kind"), sources=_docs(body), text=text, shape=_shape(plan))
        assert body.get("kind") == "answer", body
        assert ITEM_LOCATION.replace("2", "9") in text, text  # 北区9号架（本用例的物品行）
        assert STORE_STATUS not in text, text
        assert OTHER_STATUS not in text, text
        assert set(_docs(body)) == {ITEM_DOC}, body.get("sources")
        assert chat_model.calls == [], chat_model.calls
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# F. ``total`` 1→2 的新数字：有 pagination 才有出处；缺 pagination 仍 fail
# --------------------------------------------------------------------------- #
def test_204_f_pagination_is_required_for_the_new_total_number(t09_network_guard):
    from mktkb.evaluation.dataset import CaseSpec
    from mktkb.evaluation.p2_scoring import P2_PAGINATION_NUMBER_KEYS, _pagination_number_keys, score_public_case

    doc = "合成位置资料"
    store_doc = "合成合作方资料"
    case = CaseSpec(
        case_id="R204-PAGINATION",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date="2026-10-31",
        question="试样柜的位置在哪里，合作状态分别是什么？",
        expected_kind="answer",
        expected_values=("西区4号架",),
        reference_answer="试样柜的位置是西区4号架，合作状态是合作中",
    )
    text_after = (
        "共 2 条，当前第 1 页显示 2 条。\n"
        "- 云岭店的试样柜：位置 西区4号架（来源：合成位置资料）\n"
        "- 云岭店：合作状态 合作中（来源：合成合作方资料）\n"
        "已显示全部。"
    )
    locator = {"sheet": "台账", "row": 4, "header_row": 3, "cells": [{"column": "A", "display": "云岭店", "header": "门店"}]}

    def _score(pagination: dict | None) -> dict:
        product: dict = {
            "kind": "answer",
            "text": text_after,
            "sources": [
                {"source_id": "U-204-item", "document_name": doc, "locator": locator, "status": "active"},
                {"source_id": "U-204-store", "document_name": store_doc, "locator": locator, "status": "active"},
            ],
        }
        if pagination is not None:
            product["pagination"] = pagination
        row = {
            "case_id": case.case_id,
            "status": "ok",
            "planned_turns": 1,
            "turns": ({"turn": 1, "status": "ok", "product": product},),
        }
        scored = score_public_case(case, row, document_codes={doc: "D-204", store_doc: "D-204-S"})
        checks = [
            item if isinstance(item, dict) else {"check_id": item.check_id, "status": item.status, "evidence": dict(item.evidence or {})}
            for item in scored.score.checks
        ]
        found = [item for item in checks if item["check_id"] == "value_no_fabricated"]
        assert len(found) == 1, checks
        return found[0]

    with_pagination = _score({"page": 1, "page_size": 10, "total": 2, "returned": 2, "has_more": False, "next_page": None})
    without = _score(None)
    _witness(
        "f",
        with_pagination=with_pagination,
        without_pagination=without,
        whitelist=list(P2_PAGINATION_NUMBER_KEYS),
        keys_with_nonint=sorted(_pagination_number_keys({"total": 2, "returned": "2", "revision": 7, "has_more": 1})),
    )
    assert with_pagination["status"] == "pass", with_pagination
    assert without["status"] == "fail", without
    assert set(without["evidence"]["extra"]) == {"1", "2"}, without
    assert P2_PAGINATION_NUMBER_KEYS == ("total", "page", "page_size", "returned", "next_page")
    assert _pagination_number_keys({"total": 2, "returned": "2", "revision": 7, "has_more": 1}) == {"2"}
    assert _pagination_number_keys(None) == frozenset()
    assert t09_network_guard.snapshot()["external"] == []


# --------------------------------------------------------------------------- #
# G-②. 关 legacy 联结 → legacy 红；同开关下 C29 形态仍绿（两修复互不吞并）
# --------------------------------------------------------------------------- #
def test_204_g_legacy_join_switch_is_independent(
    store, chat_model, monkeypatch, t09_network_guard, no_subprocess
):
    from mktkb.retrieval import service as retrieval_service

    app, _admin, employee, versions = _open_app(store, chat_model)
    try:
        chat_model.answer_text = LEGACY_ANSWER
        chat_model.calls.clear()
        legacy_plan = _plan(app, employee, Q_LEGACY)
        green = _ask(employee, Q_LEGACY)
        _witness(
            "g-legacy-green",
            kind=green.get("kind"),
            sources=_docs(green),
            text=green.get("text"),
            shape=_shape(legacy_plan),
            model_calls=len(chat_model.calls),
        )
        assert bool(getattr(legacy_plan, "enumerate", False)) is False, _shape(legacy_plan)
        assert green.get("kind") == "answer", green
        assert ITEM_LOCATION in (green.get("text") or ""), green.get("text")
        assert STORE_STATUS in (green.get("text") or ""), green.get("text")
        assert sorted(_docs(green)) == sorted([ITEM_DOC, STORE_DOC]), green.get("sources")

        # 关掉 R0 的 legacy 入口 → legacy 红
        monkeypatch.setattr(retrieval_service, "_store_join_ids", lambda db, intent: set())
        chat_model.calls.clear()
        chat_model.answer_text = LEGACY_ANSWER
        red = _ask(employee, Q_LEGACY)
        red_evidence = chat_model.calls[0]["evidence"] if chat_model.calls else []
        _witness(
            "g-legacy-off-red",
            kind=red.get("kind"),
            error_code=red.get("error_code"),
            sources=_docs(red),
            text=red.get("text"),
            evidence_field_keys=[sorted(item["fields"]) for item in red_evidence],
        )
        assert STORE_STATUS not in (red.get("text") or ""), red.get("text")
        assert len(red_evidence) == 1, red_evidence
        assert "合作状态" not in red_evidence[0]["fields"], red_evidence

        # 同一开关下 C29 形态仍绿：本批联结不经过 R0 入口
        chat_model.calls.clear()
        still_green = _assert_cross_green(app, employee, Q_CROSS, versions)
        assert STORE_STATUS in still_green["body"]["text"]
        assert chat_model.calls == [], chat_model.calls
        assert t09_network_guard.snapshot()["external"] == []
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# G-④. 日期闭区间边界（店家行 生效 2026-11-20 / 失效 2026-11-21）
# --------------------------------------------------------------------------- #
DATE_STORE_HEADERS = ["标识", "店家", "对接人", "合作状态", "生效日期", "失效日期"]
DATE_STORE_ROWS = [
    ["K02", OTHER_STORE, "合成对接人·乙", OTHER_STATUS, "2026-11-20", "2026-11-21"],
    ["K01", STORE, "合成对接人·甲", STORE_STATUS, "2026-11-20", "2026-11-21"],
]


@pytest.mark.parametrize(
    ("business_date", "visible"),
    (("2026-11-19", False), ("2026-11-20", True), ("2026-11-21", True), ("2026-11-22", False)),
)
def test_204_g_business_date_closed_interval_boundary(
    store, chat_model, business_date: str, visible: bool, t09_network_guard, no_subprocess
):
    app = _build(store.root, chat_model, business_date=business_date)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _dataset(app, admin, store_headers=DATE_STORE_HEADERS, store_rows=DATE_STORE_ROWS)
        chat_model.calls.clear()
        plan = _plan(app, employee, Q_CROSS)
        body = _ask(employee, Q_CROSS)
        text = body.get("text") or ""
        _witness(
            "g-date",
            business_date=business_date,
            as_of=getattr(plan, "as_of", None),
            kind=body.get("kind"),
            sources=_docs(body),
            has_status=STORE_STATUS in text,
            text=text,
        )
        assert getattr(plan, "as_of", None) == business_date, getattr(plan, "as_of", None)
        assert ITEM_LOCATION in text, text
        assert (STORE_STATUS in text) is visible, (business_date, visible, text)
        assert (len(body.get("sources") or []) == 2) is visible, body.get("sources")
        assert (STORE_DOC in _docs(body)) is visible, body.get("sources")
        assert t09_network_guard.snapshot()["external"] == []
    finally:
        app.state.db.dispose()


# --------------------------------------------------------------------------- #
# B/G-③. 实体键单点派生：当前同形逐字节相等 → passed；还原 R0 前派生 → unknown
# --------------------------------------------------------------------------- #
def _legacy_entity(fields, *, doc, unit_id=None):  # noqa: ANN001, ANN202
    """还原 R0 之前的名称复合键派生（运行时替换，不动文件）：store→``store|名``，
    store+item→``item|店|物``。有标识也**不**走 ``build_entity_key``。"""
    from mktkb.rag import chunking as module

    values = module.role_values(fields)
    store = module.first_value(values, "store")
    item = module.first_value(values, "item")
    identifier = module.first_value(values, "identifier")
    if store and item:
        entity_type = "item"
        key = f"item|{module.normalize_field(store)}|{module.normalize_field(item)}"
        label = f"{store}的{item}"
    elif store:
        entity_type = "store"
        key = f"store|{module.normalize_field(store)}"
        label = store
    elif identifier:
        entity_type = "record"
        key = f"record|{module.normalize_field(identifier)}"
        label = identifier
    else:
        entity_type = "document"
        key = f"document|{doc.doc_id}"
        label = doc.title
    filters: dict[str, str] = {}
    filters_norm: dict[str, object] = {}
    for role in module._FILTER_ROLES:
        value = module.first_value(values, role)
        if value:
            filters[role] = value
            filters_norm[role] = module.normalize_field(value)
    return entity_type, key, label, filters, filters_norm


def _canonical(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        return str(value)


def _source_entity(root: Path, unit_id: str) -> dict:
    """从产品自己的主库 ``retrieval_unit_index`` 只读读单元侧实体身份（不另算键）。"""
    path = root / "mktkb.sqlite3"
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = list(
            connection.execute("SELECT unit_id, entity_type, entity_key, entity_filters FROM retrieval_unit_index")
        )
    finally:
        connection.close()
    for row in rows:
        if _canonical(row[0]) == _canonical(unit_id):
            return {
                "unit_id": _canonical(row[0]),
                "entity_type": row[1],
                "entity_key": row[2],
                "entity_filters": row[3],
            }
    raise AssertionError(f"unit {unit_id} 不在 retrieval_unit_index")


def _axes_verdict(unit_id: str, unit: dict, fact_key: str | None) -> tuple[str, str]:
    """用**评测公开入口**（``rescore_axes_case``）判 cross_entity：只喂产品自己持久化的键。"""
    from mktkb.evaluation import p2_evidence_rescore as rescore
    from mktkb.evaluation import p2_evidence_rescore_axes as axes

    bindings = {"run_id": "run-r204", "plan_id": "plan-r204", "plan_sha256": "0" * 64}
    target = {"entity_type": unit["entity_type"], "entity_key": unit["entity_key"], "filters": {"store": STORE}}
    evidence = axes.CrossEntityEvidenceView(
        units=(rescore.UnitView(unit_id=unit_id, layers=("direct_rag_fact",)),),
        unit_entity={
            unit_id: axes.EntityIdentityView(
                entity_type=unit["entity_type"], entity_key=unit["entity_key"], filters={"store": STORE}
            )
        },
        facts=(axes.EntityFactView(entity_key=fact_key, source_unit_id=unit_id),),
        plan_filters={"store": STORE},
        bindings=bindings,
    )
    contract = axes.CrossEntityContract.from_mapping(
        {
            "case_id": "R204-IDENTITY",
            "mode": "entity_bound",
            "targets": [target],
            "shared_background": [],
            "refs": {},
            "version_bindings": {},
            "bindings": bindings,
        }
    )
    annotation = axes.AxisAnnotation(
        axis="cross_entity",
        applicability="required",
        criterion="structured_target",
        reason="explicit_single_target",
        targets=(target,),
        as_of=None,
        temporal_intent="current",
        basis="frozen_contract",
        source=axes.SYNTHETIC_SOURCE,
    )
    old = rescore.OldCardCase(
        case_id="R204-IDENTITY",
        stratum="exact",
        quality_status="pass",
        axes={
            "safety": {"state": "not_applicable", "reason": rescore.NA_REASON},
            "cross_user": {"state": "passed", "reason": axes.PASS_REASONS["cross_user"]},
            "cross_entity": {"state": "unknown", "reason": "entity_identity_unresolved"},
            "stale_source": {"state": "passed", "reason": axes.PASS_REASONS["stale_source"]},
        },
    )
    view = axes.AxesCaseView(
        old=old,
        annotations={"cross_entity": annotation},
        cross_entity=evidence,
        cross_entity_contract=contract,
    )
    result = axes.rescore_axes_case(view, allow_synthetic_fixture=True)
    verdict = result.new_axes["cross_entity"]
    return str(verdict["state"]), str(verdict["reason"])


def test_204_b_g_entity_key_single_derivation_and_legacy_sensitivity(
    store, chat_model, monkeypatch, tmp_path, t09_network_guard, no_subprocess
):
    # ---- 当前工作树：两侧键逐字节相等 → passed ----
    app = _build(store.root, chat_model)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _dataset(app, admin)
        answer = _answer(app, employee, Q_STORE_ONLY)
        assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
        fact = answer.facts[0]
        unit = _source_entity(store.root, fact.source_unit_id)
        current = {"entity_type": unit["entity_type"], "entity_key": unit["entity_key"]}
        assert current["entity_key"] == fact.entity_key, (current, fact.entity_key)
        state, reason = _axes_verdict(unit["unit_id"], current, fact.entity_key)
        _witness("b-current", unit_key=current["entity_key"], fact_key=fact.entity_key, state=state, reason=reason)
        assert (state, reason) == ("passed", "frozen_targets_match_ok"), (state, reason)
    finally:
        app.state.db.dispose()


    # ---- 还原 R0 前派生（仅 chunking 侧）→ 两侧键分叉 → unknown ----
    from mktkb.rag import chunking as chunking_module

    monkeypatch.setattr(chunking_module, "_entity", _legacy_entity)
    legacy_root = tmp_path / "legacy-root"
    legacy_root.mkdir(parents=True, exist_ok=True)
    app2 = _build(legacy_root, chat_model)
    try:
        admin = _session(app2, "admin", "AdminPass-1")
        employee = _session(app2, "employee", "EmployeePass-1")
        _dataset(app2, admin)
        answer = _answer(app2, employee, Q_STORE_ONLY)
        assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
        fact = answer.facts[0]
        unit = _source_entity(legacy_root, fact.source_unit_id)
        legacy = {"entity_type": unit["entity_type"], "entity_key": unit["entity_key"]}
        _witness(
            "b-legacy",
            unit_key=legacy["entity_key"],
            fact_key=fact.entity_key,
            equal=legacy["entity_key"] == fact.entity_key,
            fact_bar_count=str(fact.entity_key).count("|"),
            unit_bar_count=str(legacy["entity_key"]).count("|"),
        )
        assert legacy["entity_key"] != fact.entity_key
        assert "|id:" in str(legacy["entity_key"]) and "|id:" not in str(fact.entity_key)
        state, reason = _axes_verdict(unit["unit_id"], legacy, fact.entity_key)
        _witness("b-legacy-verdict", state=state, reason=reason)
        assert (state, reason) == ("unknown", "entity_identity_unresolved"), (state, reason)
        assert t09_network_guard.snapshot()["external"] == []
    finally:
        app2.state.db.dispose()
