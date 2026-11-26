"""T-R2-203A 探针：同门店「多条店家行」与「多页」下的计数/渲染自洽性。

背景（T-R2-202C 已上线行为，本探针**只观测、不改源码**）：

- ``rag/retrieval.py:282 _store_join_chunks`` 返回「同门店的全部店家行」（按记录面上界
  过滤，**没有**"取最新/只取一条"的收敛）；
- ``rag/retrieval.py:340-350 _exact_recall`` 把未出现过的店家行**全部**并入 ``exact``；
- ``rag/retrieval.py:672 _enumerate_base`` 按 ``record_unit_id or chunk_id`` 去重后
  ``total = len(base)``；
- ``rag/answer.py:902-906`` ``total = int(result.total)``、``returned = len(lines)``；
- ``conversations/service.py:2401-2412`` 由 ``answer_source == "structured_enumeration"``
  触发下发 ``pagination``。

要回答的问题：
1. 同一门店 2 条店家行 → 全部并入还是只取一条？
2. 并入后 ``total`` / 渲染行数 / ``sources`` 条数是否自洽？
3. 多页（``page_size=1``）时联结店家行是否被重复计入 ``total``？

全部合成数据（虚构门店/物品/人员），不读 fixtures、不读私有材料、不碰真实 case。
零出站：``t09_network_guard`` 在 teardown 断言 ``external == []``；本文件每个用例另外
**显式**断言一次 snapshot，并封死 ``subprocess``（见 ``no_subprocess``）。
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")

# 由本目录 ``conftest.py`` 从 ``backend/tests/conftest.py`` 搬运进来的符号：
from conftest import (  # noqa: E402
    ORIGIN,
    Settings,
    _write_session,
    create_app,
)
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402

_ARTIFACTS = Path(
    os.environ.get("PROBE_ARTIFACTS") or (Path(__file__).resolve().parent / "probe-artifacts")
)

# --------------------------------------------------------------------------- #
# 合成数据集（全部虚构）
# --------------------------------------------------------------------------- #
ITEM_DOC = "R203A物品位置台账.xlsx"
STORE_DOC = "R203A合作店家信息.xlsx"
ITEM_DOC_TITLE = "R203A物品位置台账"
STORE_DOC_TITLE = "R203A合作店家信息"

ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["澄江店", "样品桌", "Q01", "子区3号架", "4"],
    ["澄江店", "样品椅", "Q02", "子区4号架", "6"],
    ["槐序店", "样品凳", "Q03", "丑区1号架", "9"],
]

STORE_HEADERS = ["标识", "店家", "联系人", "合作状态"]
#: 对照：每个门店 1 条店家行。
STORE_ROWS_ONE_EACH = [
    ["T01", "澄江店", "合成对接人·子", "合作中"],
    ["T02", "槐序店", "合成对接人·丑", "暂停合作"],
]
#: 观测：**同一门店 2 条店家行**（同门店、同资料、无有效期列 ⇒ 两条都"当前有效"）。
STORE_ROWS_TWO_SAME_STORE = [
    ["T01", "澄江店", "合成对接人·子", "合作中"],
    ["T05", "澄江店", "合成对接人·寅", "暂停合作"],
    ["T02", "槐序店", "合成对接人·丑", "暂停合作"],
]

ITEM_LOCATION = "子区3号架"
#: C29 形态：只点名物品 + 枚举词 ⇒ ``mode=record``、``enumerate=True``、``filters=[item]``，
#: 且同时请求物品级（位置）与店家级（合作状态）字段。
QUESTION = "样品桌的位置在哪里，合作状态分别是什么？"


# --------------------------------------------------------------------------- #
# 守卫
# --------------------------------------------------------------------------- #

def _assert_zero_external(guard) -> None:
    snapshot = guard.snapshot()
    assert snapshot["external"] == [], f"检测到真实外部出站：{snapshot['external']}"


# --------------------------------------------------------------------------- #
# 隔离 app 工厂（每个用例一套独立 data_dir/SQLite，避免资料互相污染计数）
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_factory(tmp_path, chat_model):
    created: list[SimpleNamespace] = []
    counter = {"n": 0}

    def _make(store_rows: list[list[object]]) -> SimpleNamespace:
        counter["n"] += 1
        root = tmp_path / f"app{counter['n']}"
        root.mkdir(parents=True, exist_ok=True)
        settings = Settings(
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
        )
        app = create_app(settings, model_gateway=chat_model)
        admin = _write_session(app, "admin", "AdminPass-1")
        employee = _write_session(app, "employee", "EmployeePass-1")
        for name, headers, rows, title in (
            (ITEM_DOC, ITEM_HEADERS, ITEM_ROWS, ITEM_DOC_TITLE),
            (STORE_DOC, STORE_HEADERS, store_rows, STORE_DOC_TITLE),
        ):
            _publish(app, admin, _xlsx(root / name, headers, rows, title))
        bundle = SimpleNamespace(app=app, admin=admin, employee=employee)
        created.append(bundle)
        return bundle

    yield _make
    for bundle in created:
        bundle.app.state.db.dispose()


# --------------------------------------------------------------------------- #
# 产品链路辅助
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


def _ask(app, session: SimpleNamespace):
    conversation = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    qa = app.state.qa
    qa.ensure_ready()
    me = session.client.get("/api/v1/auth/me").json()
    _, plan = qa.prepare(QUESTION, str(me["user"]["id"]), conversation_id)

    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": QUESTION},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return plan, response.json()


def _summary(plan, body: dict) -> dict:
    text = str(body.get("text") or "")
    lines = [line for line in text.splitlines() if line.startswith("- ")]
    sources = [str(item.get("document_name") or "") for item in body.get("sources") or []]
    filters = {str(k): str(v) for k, v in dict(getattr(plan, "filters", {}) or {}).items()}
    return {
        "kind": body.get("kind"),
        "pagination": body.get("pagination"),
        "text": text,
        "rendered_lines": len(lines),
        "rendered_line_texts": lines,
        "source_count": len(sources),
        "source_docs": sources,
        "value_occurrences": {
            "合作中": text.count("合作中"),
            "暂停合作": text.count("暂停合作"),
            ITEM_LOCATION: text.count(ITEM_LOCATION),
        },
        "plan": {
            "mode": str(getattr(plan, "mode", "")),
            "enumerate": bool(getattr(plan, "enumerate", False)),
            "filters": sorted(filters),
            "filter_values": filters,
            "field_roles": [str(item) for item in (getattr(plan, "field_roles", ()) or ())],
            "field_role": getattr(plan, "field_role", None),
            "state_stores": [str(item) for item in (getattr(plan.state, "stores", ()) or ())],
            "state_items": [str(item) for item in (getattr(plan.state, "items", ()) or ())],
            "reason": getattr(plan, "reason", None),
            "page_size": int(getattr(plan, "page_size", 0) or 0),
        },
    }


def _dump(name: str, payload: dict) -> None:
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (_ARTIFACTS / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _assert_c29_shape(observed: dict, *, require_item_location: bool = True) -> None:
    assert observed["kind"] == "answer", observed["text"]
    assert observed["plan"]["mode"] == "record", observed["plan"]
    assert observed["plan"]["enumerate"] is True, observed["plan"]
    assert "item" in observed["plan"]["filters"], observed["plan"]
    assert observed["plan"]["state_items"] == ["样品桌"], observed["plan"]
    if require_item_location:
        assert ITEM_LOCATION in observed["text"], observed["text"]


def _disable_join(monkeypatch) -> None:
    """改前对照：关掉本批**唯一**联结入口（``retrieval._store_join_chunks``）。

    ``HEAD`` 导出树不能当 202C 的"改前"基线（HEAD 早于本批、也早于 R0/R1 的未提交成果），
    且只读纪律禁止改 ``backend/src``；因此用本批唯一入口的敏感性对照还原改前行为：
    ``store_join`` 诊断不写入 ⇒ ``answer.py`` 的身份渲染分支、``facts.py`` 的
    ``joined_store`` 放行全部保持惰性。202C 自己的 ``test_join_entry_sensitivity_restores_red``
    用的也是这个口径。
    """

    from mktkb.rag import retrieval as rag_retrieval

    monkeypatch.setattr(rag_retrieval, "_store_join_chunks", lambda session, plan: ("", []))


# --------------------------------------------------------------------------- #
# 探针 1：对照（每店 1 条店家行）
# --------------------------------------------------------------------------- #
def test_203a_control_one_store_row_each(app_factory, t09_network_guard):
    bundle = app_factory(STORE_ROWS_ONE_EACH)
    plan, body = _ask(bundle.app, bundle.employee)
    observed = _summary(plan, body)
    _dump("control-one-row-each", observed)
    _assert_zero_external(t09_network_guard)
    _assert_c29_shape(observed)

    pagination = observed["pagination"] or {}
    assert pagination.get("total") == 2, pagination
    assert pagination.get("returned") == 2, pagination
    assert pagination.get("has_more") is False, pagination
    assert observed["rendered_lines"] == 2, observed["rendered_line_texts"]
    assert observed["source_count"] == 2, observed["source_docs"]
    assert observed["value_occurrences"]["合作中"] == 1, observed["value_occurrences"]


# --------------------------------------------------------------------------- #
# 探针 2：同门店 2 条店家行
# --------------------------------------------------------------------------- #
def test_203a_same_store_two_rows_all_joined(app_factory, t09_network_guard):
    bundle = app_factory(STORE_ROWS_TWO_SAME_STORE)
    plan, body = _ask(bundle.app, bundle.employee)
    observed = _summary(plan, body)
    _dump("same-store-two-rows", observed)
    _assert_zero_external(t09_network_guard)
    _assert_c29_shape(observed)

    pagination = observed["pagination"] or {}
    # 自洽不变量：页头 returned == 渲染记录行数 == sources 条数 == total（单页）
    assert pagination.get("returned") == observed["rendered_lines"], (
        pagination,
        observed["rendered_line_texts"],
    )
    assert observed["source_count"] == observed["rendered_lines"], (
        observed["source_docs"],
        observed["rendered_line_texts"],
    )
    assert pagination.get("total") == pagination.get("returned"), pagination
    # 观测结论：同门店两条店家行**都**被并入（未做"取最新/取一条"）
    assert observed["rendered_lines"] == 3, observed["rendered_line_texts"]
    assert observed["value_occurrences"]["合作中"] == 1, observed["value_occurrences"]
    assert observed["value_occurrences"]["暂停合作"] == 1, observed["value_occurrences"]


# --------------------------------------------------------------------------- #
# 探针 3：多页（page_size=1）
# --------------------------------------------------------------------------- #
def test_203a_multipage_page_size_one(app_factory, t09_network_guard):
    bundle = app_factory(STORE_ROWS_TWO_SAME_STORE)

    # QueryState 初始 ``page_size`` 取自 ``RagIndex.config.page_size``（answer.py:82）；
    # RagConfig 是 frozen dataclass ⇒ 用 object.__setattr__ 模拟"一页一条"的配置。
    index = bundle.app.state.qa.index()
    object.__setattr__(index.config, "page_size", 1)

    plan, body = _ask(bundle.app, bundle.employee)
    observed = _summary(plan, body)
    _dump("multipage-page-size-1", observed)
    _assert_zero_external(t09_network_guard)
    # 多页下第一页可能整页都是联结店家行（排序按 label：店名 < 店名+物品），
    # 故这里不要求第一页就出现被问的"位置"值 —— 这本身是要报告的现象。
    _assert_c29_shape(observed, require_item_location=False)

    pagination = observed["pagination"] or {}
    assert pagination.get("page_size") == 1, pagination
    assert pagination.get("page") == 1, pagination
    assert pagination.get("returned") == observed["rendered_lines"], pagination
    assert observed["rendered_lines"] == 1, observed["rendered_line_texts"]
    # total 必须是"记录行数"（1 物品行 + 同门店 2 条店家行 = 3），不按页重复计
    assert pagination.get("total") == 3, pagination
    assert pagination.get("has_more") is True, pagination
    assert pagination.get("next_page") == 2, pagination

# --------------------------------------------------------------------------- #
# 探针 4：改前对照（关掉本批唯一联结入口）——"改前/改后"两组数字的改前一侧
# --------------------------------------------------------------------------- #
def test_203a_before_join_disabled_one_row_each(app_factory, monkeypatch, t09_network_guard):
    bundle = app_factory(STORE_ROWS_ONE_EACH)
    _disable_join(monkeypatch)
    plan, body = _ask(bundle.app, bundle.employee)
    observed = _summary(plan, body)
    _dump("before-join-disabled-one-row-each", observed)
    _assert_zero_external(t09_network_guard)

    pagination = observed["pagination"] or {}
    assert pagination.get("total") == 1, pagination
    assert pagination.get("returned") == 1, pagination
    assert observed["rendered_lines"] == 1, observed["rendered_line_texts"]
    assert observed["source_count"] == 1, observed["source_docs"]
    # 改前：店家级值根本没有来源（C29 的原始缺陷）
    assert observed["value_occurrences"]["合作中"] == 0, observed["value_occurrences"]


def test_203a_before_join_disabled_two_rows_same_store(app_factory, monkeypatch, t09_network_guard):
    """改前对照：同门店 2 条店家行也一条都不并入（total 仍为 1）。"""

    bundle = app_factory(STORE_ROWS_TWO_SAME_STORE)
    _disable_join(monkeypatch)
    plan, body = _ask(bundle.app, bundle.employee)
    observed = _summary(plan, body)
    _dump("before-join-disabled-two-rows", observed)
    _assert_zero_external(t09_network_guard)

    pagination = observed["pagination"] or {}
    assert pagination.get("total") == 1, pagination
    assert observed["rendered_lines"] == 1, observed["rendered_line_texts"]
    assert observed["source_count"] == 1, observed["source_docs"]
    assert observed["value_occurrences"]["合作中"] == 0, observed["value_occurrences"]
    assert observed["value_occurrences"]["暂停合作"] == 0, observed["value_occurrences"]

# --------------------------------------------------------------------------- #
# 探针 5：联结轮次的候选丢弃原因码（诊断面）——"联结行只进 exact 不进 fused"
# --------------------------------------------------------------------------- #
def test_203a_join_turn_records_filter_miss(app_factory, t09_network_guard):
    """同一次检索里，联结店家行进 exact 后过不了 ``item`` 硬过滤 ⇒ ``diag["filter"]``。"""

    bundle = app_factory(STORE_ROWS_TWO_SAME_STORE)
    plan, body = _ask(bundle.app, bundle.employee)
    assert body.get("kind") == "answer", body

    qa = bundle.app.state.qa
    diag: dict[str, str] = {}
    result = qa.search(plan, diag=diag)
    _dump("diag-join-enabled", {"diag": diag, "recall": dict(result.diagnostics.get("recall") or {})})
    _assert_zero_external(t09_network_guard)

    assert dict(result.diagnostics.get("store_join") or {}), result.diagnostics.get("store_join")
    assert diag.get("filter") == "filter_miss", diag
    assert "filter" not in (diag.keys() - {"filter"}), diag


def test_203a_join_disabled_turn_has_no_filter_miss(app_factory, monkeypatch, t09_network_guard):
    """改前对照：关掉联结入口后同一形态不再记 ``filter_miss``（证明是联结引入的）。"""

    bundle = app_factory(STORE_ROWS_TWO_SAME_STORE)
    _disable_join(monkeypatch)
    plan, body = _ask(bundle.app, bundle.employee)
    assert body.get("kind") == "answer", body

    qa = bundle.app.state.qa
    diag: dict[str, str] = {}
    result = qa.search(plan, diag=diag)
    _dump("diag-join-disabled", {"diag": diag, "recall": dict(result.diagnostics.get("recall") or {})})
    _assert_zero_external(t09_network_guard)

    assert not dict(result.diagnostics.get("store_join") or {}), result.diagnostics.get("store_join")
    assert "filter" not in diag, diag