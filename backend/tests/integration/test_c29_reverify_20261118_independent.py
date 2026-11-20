"""C29 修复独立复测探针（2026-11-18，外部复验者自建，全部合成虚构数据）。

复验对象：工作树未提交的 C29 按子句绑定门店修复（rag/query.py、types.py、
retrieval.py、answer.py、facts.py）。实体/值/文档名与开发方 202C、外部 206B
探针均不重叠（枫杨店/云杉店、亚克力牌、丙区3号架/丁区5号架、020-00000021/22）。

只走产品链路：上传 → 解析 → 发布 → POST /api/v1/conversations/{id}/messages。
不读 fixtures、题面、私有材料、真实 case_id 或真实期望值。
本文件为新增未跟踪文件，不修改任何既有产品代码、测试、评分器或标签。
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
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

# --------------------------------------------------------------------------- #
# 合成数据集（虚构）
# --------------------------------------------------------------------------- #

ITEM_DOC = "物料摆放台账C29复验.xlsx"
STORE_DOC = "店家合作名册C29复验.xlsx"
ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["枫杨店", "亚克力牌", "M11", "丙区3号架", "5"],
    ["云杉店", "亚克力牌", "M12", "丁区5号架", "2"],
]
STORE_HEADERS = ["标识", "店家", "联系人", "电话", "合作状态"]
STORE_ROWS = [
    ["T11", "枫杨店", "合成对接人·戊", "020-00000021", "合作中"],
    ["T12", "云杉店", "合成对接人·己", "020-00000022", "暂停合作"],
]
STORE_A = "枫杨店"
STORE_B = "云杉店"
ITEM = "亚克力牌"
LOC_A = "丙区3号架"
LOC_B = "丁区5号架"
STATUS_A = "合作中"
STATUS_B = "暂停合作"
PHONE_A = "020-00000021"
PHONE_B = "020-00000022"
CONTACT_A = "合成对接人·戊"
CONTACT_B = "合成对接人·己"
RESTRICTED = (PHONE_A, PHONE_B, CONTACT_A, CONTACT_B)

QUESTION_MAIN = f"{STORE_A}的{ITEM}放在哪个位置？{STORE_B}的合作状态如何？"
QUESTION_PHONE = f"{STORE_A}的{ITEM}放在哪个位置？{STORE_B}的合作状态如何，电话也告诉我。"

BUSINESS_DATE = "2026-11-18"


@pytest.fixture
def settings(store):
    """独立装配：业务日固定、页容量默认 10；小页用例再单独覆写为 1。"""
    from mktkb.config import Settings

    database = store.root / "mktkb.sqlite3"
    return Settings(
        _env_file=None,
        data_dir=store.root,
        database_url=f"sqlite:///{database.as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="INFO",
        rag_business_date=BUSINESS_DATE,
    )


@pytest.fixture
def small_page_settings(settings):
    return settings.model_copy(update={"rag_page_size": 1})


@pytest.fixture
def no_subprocess(monkeypatch):
    calls: list[tuple] = []

    def _blocked(*args, **kwargs):
        calls.append((args, tuple(sorted(kwargs))))
        raise AssertionError("合成链路不得启动子进程")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    yield calls
    assert calls == [], calls


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
    return record


def _dataset(app, admin, *, item_rows=None, store_rows=None, store_headers=None,
             item_headers=None) -> dict:
    records = {}
    for key, name, headers, rows in (
        ("item", ITEM_DOC, item_headers or ITEM_HEADERS,
         item_rows if item_rows is not None else ITEM_ROWS),
        ("store", STORE_DOC, store_headers or STORE_HEADERS,
         store_rows if store_rows is not None else STORE_ROWS),
    ):
        records[key] = _publish(
            app, admin, _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, name[:-5])
        )
    return records


def _conversation(session) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session, conversation_id: str, question: str) -> dict:
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


def _locator_rows(sources: list[dict]) -> dict[str, int]:
    return {str(item.get("document_name")): int((item.get("locator") or {}).get("row", -1))
            for item in sources}


# --------------------------------------------------------------------------- #
# 1) 主例：跨店按子句取值（HTTP 用户面 + 内核事实/引用面 + 重排输入面）
# --------------------------------------------------------------------------- #


def test_main_cross_store_values_rows_versions_and_rerank(
    chat_app, chat_admin, chat_employee, chat_model, no_subprocess, t09_network_guard
):
    records = _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    body = _ask(chat_employee, conversation_id, QUESTION_MAIN)

    # 用户面：两值各归其店，不串店。
    assert body["kind"] == "answer", body
    assert LOC_A in body["text"] and STATUS_B in body["text"], body["text"]
    assert LOC_B not in body["text"] and STATUS_A not in body["text"], body["text"]
    for value in RESTRICTED:
        assert value not in body["text"], (value, body["text"])
    assert chat_model.calls == [], chat_model.calls

    # 来源：两条、两份资料、均为当前活动版本，行号指向正确记录行。
    sources = body["sources"]
    assert len(sources) == 2, sources
    assert {s["document_name"] for s in sources} == {ITEM_DOC, STORE_DOC}, sources
    assert all(s["status"] == "active" for s in sources), sources
    assert all(s["version_number"] == 1 for s in sources), sources
    rows = _locator_rows(sources)
    assert rows == {ITEM_DOC: 4, STORE_DOC: 5}, rows  # 枫杨店物品行=4；云杉店店家行=5

    # 内核面：事实按角色绑定到正确门店标签；引用版本=刚发布的版本。
    answer = _kernel_answer(chat_app, chat_employee, QUESTION_MAIN)
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert {(f.field_role, f.value) for f in answer.facts} == {
        ("location", LOC_A), ("status", STATUS_B),
    }, [(f.field_role, f.value, f.entity_label) for f in answer.facts]
    labels = {f.entity_label for f in answer.facts}
    assert labels == {f"{STORE_A}的{ITEM}", STORE_B}, labels
    assert len(answer.citations) == 2, answer.citations
    published_versions = {
        records["item"]["version"]["id"], records["store"]["version"]["id"],
    }
    assert {c.version_id for c in answer.citations} == published_versions, answer.citations
    cite_rows = {c.title: int((c.locator or {}).get("row", -1)) for c in answer.citations}
    assert cite_rows == {ITEM_DOC: 4, STORE_DOC: 5}, cite_rows

    # 重排输入面： scoped 店家行只作精确证据，不进融合/重排候选。
    qa = chat_app.state.qa
    qa.ensure_ready()
    user_id = str(chat_employee.client.get("/api/v1/auth/me").json()["user"]["id"])
    state, plan = qa.prepare(QUESTION_MAIN, user_id, _conversation(chat_employee))
    assert dict(plan.record_field_stores) == {"location": STORE_A, "status": STORE_B}, plan
    result = qa.index().search(plan)
    store_chunk_ids = {
        chunk.chunk_id for chunk in result.exact if chunk.entity_type == "store"
    }
    assert store_chunk_ids, "店家行必须被取到（精确证据面）"
    fused_ids = {chunk.chunk_id for chunk, _ in result.fused}
    assert store_chunk_ids.isdisjoint(fused_ids), (store_chunk_ids, fused_ids)
    rerank_diag = result.diagnostics.get("rerank")
    print("RERANK_OBSERVATION", json.dumps(
        {"rerank": rerank_diag, "fused_count": len(result.fused),
         "exact_count": len(result.exact),
         "store_chunk_in_fused": bool(store_chunk_ids & fused_ids)}, ensure_ascii=False))
    if rerank_diag and "error" not in rerank_diag:
        texts = [chunk.text for chunk, _ in result.fused]
        assert all(chunk.text not in texts for chunk in result.exact
                   if chunk.chunk_id in store_chunk_ids), "店家整行不得进入重排输入"

    # 引用定位载荷的实际表现（记录项，不作放行断言）：整行 cells 快照是否带出受限列。
    serialized = json.dumps(sources, ensure_ascii=False)
    locator_leak = sorted(value for value in RESTRICTED if value in serialized)
    print("LOCATOR_PAYLOAD_OBSERVATION", json.dumps(
        {"restricted_values_in_locator": locator_leak,
         "locator_keys": sorted({k for s in sources for k in (s.get("locator") or {})})},
        ensure_ascii=False))

    assert t09_network_guard.snapshot()["external"] == []
    assert no_subprocess == []


def test_main_with_phone_request_strips_phone_and_keeps_scoped_values(
    chat_app, chat_admin, chat_employee, chat_model, no_subprocess
):
    _dataset(chat_app, chat_admin)
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_PHONE)
    assert body["kind"] == "answer", body
    assert LOC_A in body["text"] and STATUS_B in body["text"], body["text"]
    assert LOC_B not in body["text"] and STATUS_A not in body["text"], body["text"]
    for value in RESTRICTED:
        assert value not in body["text"], (value, body["text"])
    assert "电话" not in body["text"], body["text"]
    assert len(body["sources"]) == 2, body["sources"]
    assert _locator_rows(body["sources"]) == {ITEM_DOC: 4, STORE_DOC: 5}, body["sources"]
    assert chat_model.calls == [], chat_model.calls

    answer = _kernel_answer(chat_app, chat_employee, QUESTION_PHONE)
    assert {f.field_role for f in answer.facts} == {"location", "status"}, answer.facts
    assert {f.value for f in answer.facts}.isdisjoint(RESTRICTED), answer.facts


# --------------------------------------------------------------------------- #
# 2) 反例：多条有效记录 / 目标行缺失 / 过期 —— 不得从错误门店补值
# --------------------------------------------------------------------------- #


def test_duplicate_valid_store_rows_refuse_not_cross_fill(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin, store_rows=[
        ["T11", STORE_A, CONTACT_A, PHONE_A, STATUS_A],
        ["T12", STORE_B, CONTACT_B, PHONE_B, STATUS_B],
        ["T13", STORE_B, "合成对接人·庚", "020-00000023", "观察名单"],
    ])
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_MAIN)
    assert body["kind"] != "answer", body
    assert "多个符合条件的对象" in body["text"], body["text"]
    assert STATUS_B not in body["text"] and "观察名单" not in body["text"], body["text"]
    assert LOC_B not in body["text"], body["text"]
    assert body["sources"] == [], body["sources"]
    assert chat_model.calls == [], chat_model.calls
    kernel = _kernel_answer(chat_app, chat_employee, QUESTION_MAIN)
    assert kernel.reason == "MULTIPLE_ENTITIES", (kernel.kind, kernel.reason)
    assert kernel.facts == [] and kernel.citations == [], kernel


def test_duplicate_valid_item_rows_refuse_not_cross_fill(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin, item_rows=[
        [STORE_A, ITEM, "M11", LOC_A, "5"],
        [STORE_A, ITEM, "M13", "戊区7号架", "1"],
        [STORE_B, ITEM, "M12", LOC_B, "2"],
    ])
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_MAIN)
    assert body["kind"] != "answer", body
    assert LOC_A not in body["text"] and "戊区7号架" not in body["text"], body["text"]
    assert LOC_B not in body["text"], body["text"]
    assert body["sources"] == [], body["sources"]
    assert chat_model.calls == [], chat_model.calls


def test_missing_store_row_does_not_backfill_from_other_store(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin, store_rows=[
        ["T11", STORE_A, CONTACT_A, PHONE_A, STATUS_A],
    ])
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_MAIN)
    assert STATUS_A not in body["text"], body["text"]
    assert STATUS_B not in body["text"], body["text"]
    assert LOC_B not in body["text"], body["text"]
    assert STORE_DOC not in [s["document_name"] for s in body["sources"]], body["sources"]
    assert chat_model.calls == [], chat_model.calls
    print("MISSING_STORE_ROW_OBSERVATION", json.dumps(
        {"kind": body["kind"], "has_location": LOC_A in body["text"],
         "error_code": body.get("error_code")}, ensure_ascii=False))


def test_expired_store_row_does_not_backfill_from_other_store(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin,
             store_headers=[*STORE_HEADERS, "失效日期"],
             store_rows=[
                 ["T11", STORE_A, CONTACT_A, PHONE_A, STATUS_A, ""],
                 ["T12", STORE_B, CONTACT_B, PHONE_B, STATUS_B, "2026-10-31"],
             ])
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_MAIN)
    assert STATUS_B not in body["text"], body["text"]
    assert STATUS_A not in body["text"], body["text"]
    assert LOC_B not in body["text"], body["text"]
    assert STORE_DOC not in [s["document_name"] for s in body["sources"]], body["sources"]
    assert chat_model.calls == [], chat_model.calls
    print("EXPIRED_STORE_ROW_OBSERVATION", json.dumps(
        {"kind": body["kind"], "has_location": LOC_A in body["text"],
         "error_code": body.get("error_code")}, ensure_ascii=False))


def test_expired_item_row_does_not_backfill_from_other_store(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin,
             item_headers=[*ITEM_HEADERS, "失效日期"],
             item_rows=[
                 [STORE_A, ITEM, "M11", LOC_A, "5", "2026-10-31"],
                 [STORE_B, ITEM, "M12", LOC_B, "2", ""],
             ])
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_MAIN)
    assert LOC_A not in body["text"], body["text"]
    assert LOC_B not in body["text"], body["text"]
    assert chat_model.calls == [], chat_model.calls
    print("EXPIRED_ITEM_ROW_OBSERVATION", json.dumps(
        {"kind": body["kind"], "error_code": body.get("error_code"),
         "has_status_b": STATUS_B in body["text"], "has_status_a": STATUS_A in body["text"],
         "sources": [s["document_name"] for s in body["sources"]]}, ensure_ascii=False))


def test_scoped_binding_entry_sensitivity_restores_pre_fix_shape(
    chat_app, chat_admin, chat_employee, chat_model, monkeypatch
):
    """关掉本轮新增的按子句绑定入口 → 主例回到修前形态（无店家级值/来源）。"""
    from mktkb.rag import query as rag_query

    _dataset(chat_app, chat_admin)
    monkeypatch.setattr(rag_query, "_record_field_stores", lambda *a, **k: {})
    body = _ask(chat_employee, _conversation(chat_employee), QUESTION_MAIN)
    assert STATUS_B not in body["text"] and STATUS_A not in body["text"], body["text"]
    assert STORE_DOC not in [s["document_name"] for s in body["sources"]], body["sources"]
    assert chat_model.calls == [], chat_model.calls
    print("SENSITIVITY_OBSERVATION", json.dumps(
        {"kind": body["kind"], "has_loc_a": LOC_A in body["text"],
         "has_loc_b": LOC_B in body["text"],
         "sources": [s["document_name"] for s in body["sources"]]}, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# 3) 小页容量翻页：字段与门店绑定跨页保持
# --------------------------------------------------------------------------- #


def test_small_page_paging_keeps_field_store_binding(
    small_page_settings, chat_model, no_subprocess, t09_network_guard
):
    from fastapi.testclient import TestClient

    from mktkb.main import create_app
    from conftest import login, current_csrf, write_headers, upload_document

    app = create_app(small_page_settings, model_gateway=chat_model)
    try:
        admin_client = TestClient(app, raise_server_exceptions=False)
        login(admin_client, "admin", "AdminPass-1")
        admin_csrf = current_csrf(admin_client)
        admin = SimpleNamespace(
            client=admin_client, csrf=admin_csrf, headers=write_headers(admin_csrf),
            upload=lambda **kw: upload_document(admin_client, csrf=admin_csrf, **kw),
        )
        employee_client = TestClient(app, raise_server_exceptions=False)
        login(employee_client, "employee", "EmployeePass-1")
        employee_csrf = current_csrf(employee_client)
        employee = SimpleNamespace(
            client=employee_client, csrf=employee_csrf, headers=write_headers(employee_csrf),
        )
        _dataset(app, admin)
        conversation_id = _conversation(employee)

        page1 = _ask(employee, conversation_id, QUESTION_MAIN)
        assert page1["kind"] == "answer", page1
        assert page1["pagination"]["total"] == 2, page1["pagination"]
        assert page1["pagination"]["has_more"] is True, page1["pagination"]
        assert page1["pagination"]["returned"] == 1, page1["pagination"]
        # 页内顺序按记录标签排序，不假设物品行先出；只锁「每页一个值、绑定正确」。
        if LOC_A in page1["text"]:
            first, second = ("location", LOC_A, ITEM_DOC, 4), ("status", STATUS_B, STORE_DOC, 5)
        else:
            assert STATUS_B in page1["text"], page1["text"]
            first, second = ("status", STATUS_B, STORE_DOC, 5), ("location", LOC_A, ITEM_DOC, 4)
        for value in (LOC_B, STATUS_A, *RESTRICTED):
            assert value not in page1["text"], (value, page1["text"])
        assert [s["document_name"] for s in page1["sources"]] == [first[2]], page1["sources"]
        assert _locator_rows(page1["sources"]) == {first[2]: first[3]}, page1["sources"]

        # 内核面：首轮计划 vs 首页后持久化状态下的翻页计划，字段-门店绑定逐字一致。
        qa = app.state.qa
        qa.ensure_ready()
        user_id = str(employee_client.get("/api/v1/auth/me").json()["user"]["id"])
        state1, plan1 = qa.prepare(QUESTION_MAIN, user_id, _conversation(employee))
        state2, plan2 = qa.prepare("第2页", user_id, conversation_id)
        assert dict(plan1.record_field_stores) == dict(plan2.record_field_stores) == {
            "location": STORE_A, "status": STORE_B,
        }, (plan1.record_field_stores, plan2.record_field_stores)
        assert plan2.page == 2, plan2.page

        page2 = _ask(employee, conversation_id, "第2页")
        assert page2["kind"] == "answer", page2
        assert second[1] in page2["text"], page2["text"]
        assert first[1] not in page2["text"], page2["text"]
        for value in (LOC_B, STATUS_A, *RESTRICTED):
            assert value not in page2["text"], (value, page2["text"])
        assert [s["document_name"] for s in page2["sources"]] == [second[2]], page2["sources"]
        assert _locator_rows(page2["sources"]) == {second[2]: second[3]}, page2["sources"]
        assert all(s["status"] == "active" for s in page2["sources"]), page2["sources"]
        assert page2["pagination"]["has_more"] is False, page2["pagination"]
        assert chat_model.calls == [], chat_model.calls
        assert t09_network_guard.snapshot()["external"] == []
        assert no_subprocess == []
    finally:
        app.state.db.dispose()