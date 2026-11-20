"""R2-203C F1：C29「物品级 + 店家级同问」在 **HTTP 正式链路**上的见证 + 敏感性对照。

链路：上传（multipart）→ 解析/索引（worker）→ 发布（publish）→
``POST /api/v1/conversations/{id}/messages``。所有断言的主证据都取自该 HTTP 响应
（``kind`` / ``text`` / ``sources[].document_name/version_number/status/locator``）；
``QaEngine.prepare`` 与 ``QaEngine.answer`` 只作为**补充**证据，用来证明（a）本问确实落在
C29 的触发条件上、（b）两条来源各带一条事实。

合成数据全部虚构（青禾店/白鹭店/折叠桌/折叠椅/折叠凳），不含真实 case_id、题面片段、
期望值或真实材料。业务日显式钉在 2026-11-20（产品无请求级日期注入）。

覆盖：
- F1-A 不点名门店 + "分别"（``enumerate`` 生效）；
- F1-B 点名门店（``filters`` 含 store）；
- 目标约束：``sources`` 的版本号/版本 id/门店行位置必须与物品行门店一致；
- 敏感性①：运行时关掉 ``rag.retrieval._store_join_chunks`` → A/B 转红（1 来源、缺店家级值）；
- legacy 见证：R0 ``retrieval.service._store_join_ids`` 形态单独一例为绿；敏感性②关掉它 →
  legacy 转红而 A 仍绿（两处修复互不吞并、各自可证伪）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
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

# --------------------------------------------------------------------------- #
# 合成数据集（虚构；行号固定：标题 1 行 / 空 1 行 / 表头第 3 行 / 数据第 4 行起）
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
#: 店家表故意把**非目标店**放在第 4 行：目标店行在**第 5 行**，
#: 于是"引用的是哪一行的店家值"可以用 ``sources[].locator.row`` 分辨（第 4 行 ≠ 第 5 行）。
STORE_HEADERS = ["标识", "店家", "联系人", "合作状态"]
STORE_ROWS = [
    ["S02", "白鹭店", "合成对接人·乙", "暂停合作"],
    ["S01", "青禾店", "合成对接人·甲", "合作中"],
]

STORE = "青禾店"
ITEM = "折叠桌"
ITEM_LOCATION = "甲区1号架"
STORE_STATUS = "合作中"

ITEM_HEADER_ROW = 3
ITEM_TARGET_ROW = 4  # 青禾店 / 折叠桌
STORE_HEADER_ROW = 3
STORE_TARGET_ROW = 5  # 青禾店（第 4 行是白鹭店）

QUESTION_A = "折叠桌的位置在哪里，合作状态分别是什么？"
QUESTION_B = "青禾店的折叠桌放在哪个位置，合作状态分别是什么？"
QUESTION_LEGACY = "青禾店的折叠桌放在哪个位置，合作状态如何？"
LEGACY_ANSWER = f"根据资料：{STORE}的{ITEM}位置：{ITEM_LOCATION}；合作状态：{STORE_STATUS}。"


def _witness(tag: str, **fields: object) -> None:
    """把本次实测的**观测值**打到 stdout（供报告/矩阵引用；`-s` 可见）。"""
    print("WITNESS " + json.dumps({"tag": tag, **fields}, ensure_ascii=False, sort_keys=True))


# --------------------------------------------------------------------------- #
# 出站守卫：网络 + 子进程（本文件全部用例显式请求并断言）
# --------------------------------------------------------------------------- #


@pytest.fixture
def no_subprocess(monkeypatch):
    """合成链路不得启动子进程：封死 ``Popen``/``run`` 并计数。"""
    calls: list[tuple] = []

    def _blocked(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((args, tuple(sorted(kwargs))))
        raise AssertionError("合成链路不得启动子进程")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    yield calls
    assert calls == [], calls


def _no_outbound(guard, calls) -> None:
    snapshot = guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]
    assert calls == [], calls


# --------------------------------------------------------------------------- #
# 装配（逐字段对齐 tests/conftest.py 的 settings，仅多钉业务日）
# --------------------------------------------------------------------------- #


def _settings(store: SimpleNamespace, *, business_date: str = BUSINESS_DATE) -> Settings:
    database = store.root / "mktkb.sqlite3"
    return Settings(
        _env_file=None,
        data_dir=store.root,
        database_url=f"sqlite:///{database.as_posix()}",
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


def _login(client, username: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200, response.text


def _session(app, username: str, password: str) -> SimpleNamespace:
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    _login(client, username, password)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    body = me.json()
    csrf = body["csrf_token"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
    return SimpleNamespace(client=client, headers=headers, user_id=str(body["user"]["id"]))


@pytest.fixture
def bd_app(store: SimpleNamespace, chat_model):
    application = create_app(_settings(store), model_gateway=chat_model)
    try:
        yield application
    finally:
        application.state.db.dispose()


@pytest.fixture
def admin(bd_app) -> SimpleNamespace:
    return _session(bd_app, "admin", "AdminPass-1")


@pytest.fixture
def employee(bd_app) -> SimpleNamespace:
    return _session(bd_app, "employee", "EmployeePass-1")


# --------------------------------------------------------------------------- #
# 上传 → 解析/索引 → 发布
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


def _dataset(app, admin: SimpleNamespace) -> dict[str, dict]:
    root = Path(app.state.settings.data_dir)
    return {
        ITEM_DOC: _publish(app, admin, _xlsx(root / ITEM_DOC, ITEM_HEADERS, ITEM_ROWS, ITEM_DOC_TITLE)),
        STORE_DOC: _publish(app, admin, _xlsx(root / STORE_DOC, STORE_HEADERS, STORE_ROWS, STORE_DOC_TITLE)),
    }


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
    """补充证据：产品同一入口的计划形态（只读键/布尔/枚举，用来证明落在 C29 触发条件上）。"""
    qa = app.state.qa
    qa.ensure_ready()
    return qa.prepare(question, session.user_id, conversation_id)[1]


def _facts(app, session: SimpleNamespace, question: str) -> list:
    qa = app.state.qa
    qa.ensure_ready()
    answer = qa.answer(question, session.user_id, _conversation(session))
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    return list(answer.facts)


def _sources(body: dict) -> list[dict]:
    return [dict(item) for item in body.get("sources") or []]


def _source_docs(body: dict) -> list[str]:
    return [str(item.get("document_name") or "") for item in _sources(body)]


def _disable_join(monkeypatch) -> None:
    """敏感性①：关掉本批新增的联结入口（检索层唯一入口）。"""
    from mktkb.rag import retrieval as rag_retrieval

    monkeypatch.setattr(rag_retrieval, "_store_join_chunks", lambda session, plan: ("", []))


# --------------------------------------------------------------------------- #
# 主断言包：HTTP 响应 + 目标约束（版本 / 门店行）
# --------------------------------------------------------------------------- #


def _assert_green(app, session: SimpleNamespace, question: str, versions: dict, *, tag: str) -> dict:
    conversation_id = _conversation(session)
    plan = _plan(app, session, conversation_id, question)
    body = _ask(session, conversation_id, question)
    sources = _sources(body)
    facts = _facts(app, session, question)
    _witness(
        tag,
        kind=body.get("kind"),
        source_docs=_source_docs(body),
        source_versions=[(s.get("document_name"), s.get("version_number"), s.get("status")) for s in sources],
        source_rows=[(s.get("document_name"), dict(s.get("locator") or {}).get("row")) for s in sources],
        text_has_location=ITEM_LOCATION in (body.get("text") or ""),
        text_has_status=STORE_STATUS in (body.get("text") or ""),
        modes=[str(getattr(plan, "mode", "")), bool(getattr(plan, "enumerate", False))],
        filters=sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})),
        field_roles=list(getattr(plan, "field_roles", ()) or ()),
        fact_roles=[(f.field_role, f.value, f.entity_label) for f in facts],
    )

    # (1) 结果类型与正文：两类值都在同一正文里。
    assert body.get("kind") == "answer", body
    text = body.get("text") or ""
    assert ITEM_LOCATION in text, text
    assert STORE_STATUS in text, text

    # (2) 来源：**恰好两条**，来自两份**不同文档**（不弱化成"非空"）。
    assert len(sources) == 2, sources
    names = [s["document_name"] for s in sources]
    assert sorted(names) == sorted([ITEM_DOC, STORE_DOC]), names
    assert len(set(names)) == 2, names

    # (3) 目标约束（版本）：两条来源各自是**该文档的当前活动版本**，且与发布回执逐字一致。
    for source in sources:
        pinned = versions[source["document_name"]]
        assert str(source.get("status")) == "active", source
        assert int(source.get("version_number") or 0) == pinned["version_number"], (source, pinned)
        assert source.get("published_at"), source
        locator = dict(source.get("locator") or {})
        assert locator.get("header_row") == (ITEM_HEADER_ROW if source["document_name"] == ITEM_DOC else STORE_HEADER_ROW), locator

    # (4) 目标约束（门店值）：店家级来源引用的是**物品行门店那一行**（第 5 行 = 青禾店），
    #     不是同一份店家表里的另一家店（第 4 行 = 白鹭店）。
    by_doc = {s["document_name"]: s for s in sources}
    assert int(dict(by_doc[ITEM_DOC].get("locator") or {}).get("row") or 0) == ITEM_TARGET_ROW, by_doc[ITEM_DOC]
    assert int(dict(by_doc[STORE_DOC].get("locator") or {}).get("row") or 0) == STORE_TARGET_ROW, by_doc[STORE_DOC]

    # (5) 事实面（补充证据）：两类角色都在，且各自绑定到自己的文档/版本。
    roles = {(fact.field_role, fact.value) for fact in facts}
    assert ("location", ITEM_LOCATION) in roles, roles
    assert ("status", STORE_STATUS) in roles, roles
    assert {fact.doc_id for fact in facts} == {versions[ITEM_DOC]["document_id"], versions[STORE_DOC]["document_id"]}, facts
    for fact in facts:
        name = ITEM_DOC if fact.doc_id == versions[ITEM_DOC]["document_id"] else STORE_DOC
        assert fact.version_id == versions[name]["version_id"], (fact, versions[name])
    labels = {fact.entity_label for fact in facts}
    assert labels == {f"{STORE}的{ITEM}", STORE}, labels

    return {"body": body, "sources": sources, "facts": facts, "plan": plan}


# --------------------------------------------------------------------------- #
# F1-A：不点名门店 + "分别"（enumerate 生效）
# --------------------------------------------------------------------------- #


def test_f1a_http_enumerate_turn_joins_store_level_value(
    bd_app, admin, employee, chat_model, t09_network_guard, no_subprocess
):
    versions = _dataset(bd_app, admin)
    result = _assert_green(bd_app, employee, QUESTION_A, versions, tag="f1a-green")

    plan = result["plan"]
    assert str(getattr(plan, "mode", "")) == "record"
    assert bool(getattr(plan, "enumerate", False)) is True
    assert sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})) == ["item"]
    assert set(getattr(plan, "field_roles", ()) or ()) == {"location", "status"}
    assert chat_model.calls == [], chat_model.calls
    _no_outbound(t09_network_guard, no_subprocess)


# --------------------------------------------------------------------------- #
# F1-B：点名门店（filters 含 store）
# --------------------------------------------------------------------------- #


def test_f1b_http_named_store_turn_joins_store_level_value(
    bd_app, admin, employee, chat_model, t09_network_guard, no_subprocess
):
    versions = _dataset(bd_app, admin)
    result = _assert_green(bd_app, employee, QUESTION_B, versions, tag="f1b-green")

    plan = result["plan"]
    assert sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})) == ["item", "store"]
    assert bool(getattr(plan, "enumerate", False)) is True
    assert chat_model.calls == [], chat_model.calls
    _no_outbound(t09_network_guard, no_subprocess)


# --------------------------------------------------------------------------- #
# 敏感性①：关掉本批联结入口 → A/B 回红（1 来源、缺店家级值）
# --------------------------------------------------------------------------- #


def test_f1_sensitivity_join_off_restores_red_for_both_questions(
    bd_app, admin, employee, chat_model, monkeypatch, t09_network_guard, no_subprocess
):
    versions = _dataset(bd_app, admin)
    _disable_join(monkeypatch)
    reds: list[dict] = []
    for question in (QUESTION_A, QUESTION_B):
        body = _ask(employee, _conversation(employee), question)
        sources = _sources(body)
        reds.append(
            {
                "question": question,
                "kind": body.get("kind"),
                "source_docs": _source_docs(body),
                "text": body.get("text"),
                "has_status": STORE_STATUS in (body.get("text") or ""),
            }
        )
        # 红态断言：只剩 1 条来源、店家级值缺失（不弱化）。
        assert body.get("kind") == "answer", body
        assert ITEM_LOCATION in (body.get("text") or ""), body
        assert STORE_STATUS not in (body.get("text") or ""), body
        assert _source_docs(body) == [ITEM_DOC], sources
        assert len(sources) == 1, sources
    _witness("f1-sensitivity-join-off-red", reds=reds)
    assert chat_model.calls == [], chat_model.calls

    # 红态**断言消息**留档：把同一组绿态断言在关掉联结入口后再跑一次，必然失败；
    # 这条消息就是"关掉修复 → 转红"的原始证据（不只保存绿态）。
    with pytest.raises(AssertionError) as excinfo:
        _assert_green(bd_app, employee, QUESTION_A, versions, tag="f1-join-off-as-green")
    _witness("f1-red-assertion-message-join-off", message=str(excinfo.value)[:300])
    # 失败点必须正是"店家级值不在正文里"这一条（而不是别的偶然断言）。
    assert f"assert '{STORE_STATUS}' in" in str(excinfo.value), str(excinfo.value)

    # 恢复（去掉 monkeypatch 的效果）= 独立重新装配一次，必须回绿。
    monkeypatch.undo()
    green = _assert_green(bd_app, employee, QUESTION_A, versions, tag="f1-join-restored-green")
    assert STORE_STATUS in green["body"]["text"]
    _no_outbound(t09_network_guard, no_subprocess)


# --------------------------------------------------------------------------- #
# legacy 见证：R0 ``_store_join_ids`` 形态（关掉它 → 转红，而 A 仍绿）
# --------------------------------------------------------------------------- #


def test_f1_legacy_join_is_witnessed_and_independently_falsifiable(
    bd_app, admin, employee, chat_model, monkeypatch, t09_network_guard, no_subprocess
):
    from mktkb.retrieval import service as retrieval_service

    versions = _dataset(bd_app, admin)
    chat_model.answer_text = LEGACY_ANSWER

    # (1) legacy 形态为绿（R0 补丁开着）：两类值 + 两条来源 + 两条证据各带一列。
    body = _ask(employee, _conversation(employee), QUESTION_LEGACY)
    assert body.get("kind") == "answer", body
    assert ITEM_LOCATION in body["text"], body["text"]
    assert STORE_STATUS in body["text"], body["text"]
    assert sorted(_source_docs(body)) == sorted([ITEM_DOC, STORE_DOC]), body["sources"]
    assert len(_sources(body)) == 2, body["sources"]
    evidence = chat_model.calls[0]["evidence"]
    assert any("位置" in item["fields"] for item in evidence), evidence
    assert any("合作状态" in item["fields"] for item in evidence), evidence
    _witness(
        "f1-legacy-green",
        kind=body.get("kind"),
        source_docs=_source_docs(body),
        evidence_field_keys=[sorted(item["fields"]) for item in evidence],
    )

    # (2) 敏感性②：关掉 R0 入口 → legacy 转红。
    monkeypatch.setattr(retrieval_service, "_store_join_ids", lambda db, intent: set())
    chat_model.calls.clear()
    chat_model.answer_text = LEGACY_ANSWER
    red = _ask(employee, _conversation(employee), QUESTION_LEGACY)
    red_evidence = chat_model.calls[0]["evidence"]
    _witness(
        "f1-sensitivity-legacy-off-red",
        kind=red.get("kind"),
        error_code=red.get("error_code"),
        source_docs=_source_docs(red),
        evidence_field_keys=[sorted(item["fields"]) for item in red_evidence],
    )
    assert len(red_evidence) == 1, red_evidence
    assert "合作状态" not in red_evidence[0]["fields"], red_evidence
    assert STORE_STATUS not in (red.get("text") or ""), red.get("text")
    assert red.get("kind") in {"service_error", "not_found"}, red
    # 红态**断言消息**留档：同一组 legacy 绿态断言在关掉 R0 入口后必然失败。
    with pytest.raises(AssertionError) as excinfo:
        assert STORE_STATUS in (red.get("text") or ""), red.get("text")
    _witness("f1-red-assertion-message-legacy-off", message=str(excinfo.value)[:300])

    # (3) 同一开关下 RAG 主例（F1-A）仍绿：本批联结不经过 R0 的 ``_store_join_ids``。
    chat_model.calls.clear()
    still_green = _assert_green(bd_app, employee, QUESTION_A, versions, tag="f1-r0-off-main-still-green")
    assert STORE_STATUS in still_green["body"]["text"]
    assert chat_model.calls == [], chat_model.calls
    _no_outbound(t09_network_guard, no_subprocess)


# --------------------------------------------------------------------------- #
# 零出站总账（一组用例结束后再显式审计一次）
# --------------------------------------------------------------------------- #


def test_f1_zero_outbound_ledger(bd_app, admin, employee, chat_model, t09_network_guard, no_subprocess):
    _dataset(bd_app, admin)
    for question in (QUESTION_A, QUESTION_B, QUESTION_LEGACY):
        _ask(employee, _conversation(employee), question)
    _no_outbound(t09_network_guard, no_subprocess)
