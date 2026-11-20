"""R2-203C F3：C14 两回合继承 + 业务日/闭区间边界对照。

链路：上传（multipart）→ 解析/索引（worker）→ 发布（publish）→
``POST /api/v1/conversations/{id}/messages``（同一会话连续两回合）。

合成数据全部虚构（青禾店/白鹭店/折叠桌）。业务日由 ``Settings.rag_business_date`` 显式钉住
（产品无请求级日期注入），因此下面的断言**不读宿主当前日**。

覆盖：
- F3-1 两回合：第 1 回合建立目标（门店+物品+位置），第 2 回合裸追问（无门店名、无物品名）
  继承同一目标/范围；两回合 ``revision`` 与产品 revision 快照一致；``as_of`` == 2026-11-20。
- F3-2 捕获面：同一产品的捕获 envelope 里 ``plan_observed.as_of`` / ``state_as_of`` ==
  2026-11-20，且 ``AskResult.revision`` == ``db_projection.pre_revision``（逐回合）。
- F3-3 边界对照（闭区间）：载体行 生效日期=2026-11-20 / 失效日期=2026-11-21。
  业务日 2026-11-19 → 不可见（红）；2026-11-20 / 2026-11-21 → 可见（绿）。
  对照 ``rag_business_date=None`` → ``as_of`` 为空 → 不做窗口过滤、该行可见：
  宿主当日 2026-11-17 不在区间内却仍可见 ⇒ 判定不取宿主日期。
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest
from cryptography.fernet import Fernet

_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.config import Settings  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EvidenceCaptureConfig,
)
from mktkb.evaluation.p2_evidence_io import EvidenceWriter, read_encrypted_evidence  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402

ORIGIN = "http://testserver"
BUSINESS_DATE = "2026-11-20"

ITEM_DOC = "物品位置台账.xlsx"
STORE_DOC = "合作店家信息.xlsx"
ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["青禾店", "折叠桌", "P01", "甲区1号架", "4"],
    ["白鹭店", "折叠凳", "P03", "乙区1号架", "9"],
]
#: 店家行带生效窗口：[2026-11-20, 2026-11-21] —— 闭区间两端都应可见。
STORE_HEADERS = ["标识", "店家", "联系人", "合作状态", "生效日期", "失效日期"]
STORE_ROWS = [
    ["S02", "白鹭店", "合成对接人·乙", "暂停合作", "2026-11-20", "2026-11-21"],
    ["S01", "青禾店", "合成对接人·甲", "合作中", "2026-11-20", "2026-11-21"],
]

STORE = "青禾店"
ITEM = "折叠桌"
ITEM_LOCATION = "甲区1号架"
STORE_STATUS = "合作中"

#: 第 1 回合：点名门店 + 物品 + 所问字段（建立目标/范围）。
TURN1 = f"{STORE}的{ITEM}放在哪个位置？"
#: 第 2 回合：**裸追问**（不再出现门店名与物品名），靠回合状态继承目标与范围。
TURN2 = "位置分别是什么？"
#: 边界对照用：只问店家级字段（唯一载体行就是带生效窗口的那一行）。
TURN_STORE = f"{STORE}的合作状态是什么？"


def _witness(tag: str, **fields: object) -> None:
    print("WITNESS " + json.dumps({"tag": tag, **fields}, ensure_ascii=False, sort_keys=True))


# --------------------------------------------------------------------------- #
# 出站守卫
# --------------------------------------------------------------------------- #


def _no_outbound(guard) -> None:
    snapshot = guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]


# --------------------------------------------------------------------------- #
# 装配（逐字段对齐 tests/conftest.py，仅多钉业务日）
# --------------------------------------------------------------------------- #


def _settings(data_root: Path, *, business_date: str | None) -> Settings:
    database = data_root / "mktkb.sqlite3"
    return Settings(
        _env_file=None,
        data_dir=data_root,
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
    body = client.get("/api/v1/auth/me").json()
    headers = {"Origin": ORIGIN, "X-CSRF-Token": body["csrf_token"]}
    return SimpleNamespace(client=client, headers=headers, user_id=str(body["user"]["id"]))


@pytest.fixture
def make_app(tmp_path: Path, chat_model):
    """按业务日构建一个真实产品应用 + 管理员/员工会话（每个业务日一份独立库）。"""
    created: list[Any] = []

    def _build(business_date: str | None, name: str):
        root = tmp_path / f"app-{name}"
        root.mkdir(parents=True, exist_ok=True)
        application = create_app(_settings(root, business_date=business_date), model_gateway=chat_model)
        created.append(application)
        return SimpleNamespace(
            app=application,
            admin=_session(application, "admin", "AdminPass-1"),
            employee=_session(application, "employee", "EmployeePass-1"),
        )

    yield _build
    for application in created:
        application.state.db.dispose()


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
        ITEM_DOC: _publish(app, admin, _xlsx(root / ITEM_DOC, ITEM_HEADERS, ITEM_ROWS, "物品位置台账")),
        STORE_DOC: _publish(app, admin, _xlsx(root / STORE_DOC, STORE_HEADERS, STORE_ROWS, "合作店家信息")),
    }


# --------------------------------------------------------------------------- #
# HTTP 回合
# --------------------------------------------------------------------------- #


def _conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _revision_now(app) -> int:
    db = app.state.db.session()
    try:
        return int(get_revision(db))
    finally:
        db.close()


def _ask(app, session: SimpleNamespace, conversation_id: str, question: str) -> dict:
    """真实 HTTP 回合；返回值额外带上**发送前**的产品 revision（= 捕获里的 pre_revision）。"""
    pre_revision = _revision_now(app)
    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "kind": body.get("kind"),
        "text": body.get("text") or "",
        "revision": body.get("revision"),
        "source_docs": [str(item.get("document_name") or "") for item in body.get("sources") or []],
        "source_versions": [
            (str(item.get("document_name") or ""), item.get("version_number"), str(item.get("status") or ""))
            for item in body.get("sources") or []
        ],
        "sources": list(body.get("sources") or []),
        "pre_revision": pre_revision,
    }


def _plan(app, session: SimpleNamespace, conversation_id: str, question: str):
    qa = app.state.qa
    qa.ensure_ready()
    return qa.prepare(question, session.user_id, conversation_id)[1]


# --------------------------------------------------------------------------- #
# F3-1：两回合继承（HTTP）
# --------------------------------------------------------------------------- #


def test_f3_two_turn_inheritance_and_revision_over_http(
    make_app, chat_model, t09_network_guard
):
    built = make_app(BUSINESS_DATE, "bd-2026-11-20")
    app, admin, employee = built.app, built.admin, built.employee
    versions = _dataset(app, admin)

    assert app.state.qa.config.business_date == BUSINESS_DATE
    conversation_id = _conversation(employee)

    # 第 1 回合：建立目标（门店 + 物品）与所问字段。
    plan1 = _plan(app, employee, conversation_id, TURN1)
    first = _ask(app, employee, conversation_id, TURN1)
    # 第 2 回合：裸追问（不含门店名/物品名）。
    plan2 = _plan(app, employee, conversation_id, TURN2)
    second = _ask(app, employee, conversation_id, TURN2)
    _witness(
        "f3-1-two-turn",
        turn1={"kind": first["kind"], "docs": first["source_docs"], "revision": first["revision"], "pre": first["pre_revision"]},
        turn2={"kind": second["kind"], "docs": second["source_docs"], "revision": second["revision"], "pre": second["pre_revision"]},
        as_of=[getattr(plan1, "as_of", None), getattr(plan2, "as_of", None)],
        filters1=sorted(dict(getattr(plan1, "filters", {}) or {})),
        filters2=sorted(dict(getattr(plan2, "filters", {}) or {})),
        state_store2=getattr(getattr(plan2, "state", None), "store", None),
        state_item2=getattr(getattr(plan2, "state", None), "item", None),
    )

    # 第 1 回合：位置值 + 唯一来源 = 物品表当前活动版本。
    assert first["kind"] == "answer", first
    assert ITEM_LOCATION in first["text"], first["text"]
    assert first["source_docs"] == [ITEM_DOC], first["source_docs"]
    assert first["source_versions"] == [(ITEM_DOC, versions[ITEM_DOC]["version_number"], "active")], first["source_versions"]

    # 第 2 回合：继承目标/范围 —— 正文与 sources 仍指向第 1 回合那一条记录（同一份资料同一版本）。
    assert second["kind"] == "answer", second
    assert ITEM_LOCATION in second["text"], second["text"]
    assert second["source_docs"] == [ITEM_DOC], second["source_docs"]
    assert second["source_versions"] == [(ITEM_DOC, versions[ITEM_DOC]["version_number"], "active")], second["source_versions"]
    # 范围继承：第 2 回合自己不带门店名/物品名，计划里的门店与物品只能来自回合状态。
    assert sorted(dict(getattr(plan2, "filters", {}) or {})) == ["item", "store"], getattr(plan2, "filters", {})
    assert getattr(getattr(plan2, "state", None), "store", None) == STORE
    assert getattr(getattr(plan2, "state", None), "item", None) == ITEM
    # 两回合的 sources 指向同一实体行：同一 document_name + version_number + locator。
    assert second["sources"] == first["sources"], (first["sources"], second["sources"])

    # revision：两回合都等于**发送前**的产品 revision（= 捕获里 db_projection.pre_revision 同源），
    # 且未被提问推高（本文件不做资料变更）。
    assert first["revision"] == first["pre_revision"], (first["revision"], first["pre_revision"])
    assert second["revision"] == second["pre_revision"], (second["revision"], second["pre_revision"])
    assert second["revision"] == first["revision"], (first["revision"], second["revision"])

    # 业务日：两回合 as_of 都等于显式钉住的值（不依赖宿主当前日）。
    assert getattr(plan1, "as_of", None) == BUSINESS_DATE, getattr(plan1, "as_of", None)
    assert getattr(plan2, "as_of", None) == BUSINESS_DATE, getattr(plan2, "as_of", None)
    # 该问法是单字段轮次（走 legacy 取证 + 模型），但证据面只含本目标记录，绝不带另一家店。
    assert len(chat_model.calls) <= 2, chat_model.calls
    for call in chat_model.calls:
        payload = json.dumps(call["evidence"], ensure_ascii=False)
        assert "白鹭店" not in payload, payload
    _no_outbound(t09_network_guard)


# --------------------------------------------------------------------------- #
# F3-2：捕获面（as_of / pre_revision）
# --------------------------------------------------------------------------- #

_SHA = "d" * 64


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "r2c-v1"
    values["plan_sha256"] = "e" * 64
    return values


def _dataset_spec() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "r2c-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )


def _corpus(tmp_path: Path) -> tuple[Path, Path]:
    items = _xlsx(tmp_path / "R2C-物品位置表.xlsx", ITEM_HEADERS, ITEM_ROWS, "物品位置台账")
    stores = _xlsx(tmp_path / "R2C-合作店家信息.xlsx", STORE_HEADERS, STORE_ROWS, "合作店家信息")
    return items, stores


def _events(envelope: dict) -> list[dict]:
    return [e for e in (envelope.get("capture") or {}).get("events") or () if isinstance(e, dict)]


def _payloads(envelope: dict, kind: str) -> list[dict]:
    return [e.get("payload") or {} for e in _events(envelope) if str(e.get("kind")) == kind]


async def _capture_two_turns(tmp_path: Path) -> list[dict]:
    items, stores = _corpus(tmp_path)
    bindings = _bindings("r2c-f3")
    writer = EvidenceWriter(
        root_dir=tmp_path / "evidence", key=Fernet.generate_key(), bindings=bindings, run_name="run"
    )
    adapter = ProductEvalAdapter(
        tmp_path / "product",
        chat=MockChatBackend(),
        dataset=_dataset_spec(),
        ingest_plan=P2IngestPlan(sources=(IngestSource(items), IngestSource(stores)), label="r2c"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=tmp_path / "evidence", bindings=bindings, writer=writer
        ),
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
        purge_traces_on_close=False,
    )
    try:
        await adapter.start()
        await adapter.ingest()
        session = adapter._evidence_session
        assert session is not None
        session.bind(adapter.binding_components())
        conversation = await adapter.open_conversation()
        turns = []
        for question in (TURN1, TURN2):
            turns.append(
                await adapter.ask_turn(
                    question,
                    user_id="employee",
                    conversation_id=conversation,
                    client_request_id=str(uuid.uuid4()),
                )
            )
    finally:
        await adapter.close()
    receipts = sorted(
        (item for item in writer.written if item["kind"] == "turn"), key=lambda item: item["turn_index"]
    )
    assert len(receipts) == 2, receipts
    envelopes = []
    for receipt in receipts:
        envelope = read_encrypted_evidence(
            Path(receipt["path"]), key=writer.key, expected_bindings=writer.bindings
        )
        envelopes.append(
            {
                "turn_index": int(receipt["turn_index"]),
                "envelope": envelope,
                "turn": turns[int(receipt["turn_index"])],
            }
        )
    return envelopes


@asyncio_test
async def test_f3_two_turn_capture_as_of_and_pre_revision(tmp_path: Path, t09_network_guard) -> None:
    captured = await _capture_two_turns(tmp_path)
    observed = []
    for row in captured:
        envelope = row["envelope"]
        projection = dict(envelope.get("db_projection") or {})
        plans = _payloads(envelope, "plan_observed")
        commits = _payloads(envelope, "commit_observed")
        assert len(plans) == 1, plans
        plan = plans[0]
        assert len(commits) == 1, commits
        observed.append(
            {
                "turn_index": row["turn_index"],
                "as_of": plan.get("as_of"),
                "state_as_of": plan.get("state_as_of"),
                "pre_revision": projection.get("pre_revision"),
                "result_revision": row["turn"].revision,
                "capture_revision": projection.get("capture_revision"),
                "commit_before": commits[0].get("revision_before"),
                "commit_after": commits[0].get("revision_after"),
                "mode": plan.get("mode"),
                "filters": sorted(dict(plan.get("filters") or {})),
            }
        )
    _witness("f3-2-capture", turns=observed)

    for row in observed:
        # 业务日：捕获里的计划 as_of / 回合状态 as_of 都是显式钉住值。
        assert row["as_of"] == BUSINESS_DATE, row
        assert row["state_as_of"] == BUSINESS_DATE, row
        # revision：产品响应里的 revision == 捕获里 db_projection.pre_revision
        # == 提交事件的 revision_before/after（本文件两回合之间不改资料）。
        assert row["pre_revision"] is not None, row
        assert int(row["result_revision"]) == int(row["pre_revision"]), row
        assert int(row["commit_before"]) == int(row["pre_revision"]), row
        assert int(row["commit_after"]) == int(row["pre_revision"]), row
        assert int(row["capture_revision"]) == int(row["pre_revision"]), row
    # 两回合的 pre_revision 一致（资料未变），第 2 回合仍是 record 面且带 store+item 过滤。
    assert observed[0]["pre_revision"] == observed[1]["pre_revision"], observed
    assert observed[1]["mode"] == "record", observed[1]
    assert observed[1]["filters"] == ["item", "store"], observed[1]
    _no_outbound(t09_network_guard)


# --------------------------------------------------------------------------- #
# F3-3：业务日闭区间边界对照（不依赖宿主当前日）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("business_date", "visible"),
    [
        ("2026-11-19", False),  # 区间左侧外一天
        ("2026-11-20", True),  # 闭区间左端
        ("2026-11-21", True),  # 闭区间右端
        ("2026-11-22", False),  # 区间右侧外一天
    ],
)
def test_f3_business_date_closed_interval_boundary(
    make_app, chat_model, t09_network_guard, business_date: str, visible: bool
):
    built = make_app(business_date, f"bd-{business_date}")
    app, admin, employee = built.app, built.admin, built.employee
    _dataset(app, admin)
    assert app.state.qa.config.business_date == business_date

    conversation_id = _conversation(employee)
    plan = _plan(app, employee, conversation_id, TURN_STORE)
    body = _ask(app, employee, conversation_id, TURN_STORE)
    _witness(
        "f3-3-boundary",
        business_date=business_date,
        expected_visible=visible,
        as_of=getattr(plan, "as_of", None),
        kind=body["kind"],
        docs=body["source_docs"],
        has_status=STORE_STATUS in body["text"],
    )

    # 业务日只影响"载体行是否落在窗口内"，不影响钉住值本身。
    assert getattr(plan, "as_of", None) == business_date
    if visible:
        assert body["kind"] == "answer", body
        assert STORE_STATUS in body["text"], body["text"]
        assert body["source_docs"] == [STORE_DOC], body["source_docs"]
    else:
        assert STORE_STATUS not in body["text"], body["text"]
        assert STORE_DOC not in body["source_docs"], body["source_docs"]
        # 红态**断言消息**留档：把"可见"那一侧的断言在本业务日再跑一次，必然失败。
        with pytest.raises(AssertionError) as excinfo:
            assert STORE_STATUS in body["text"], body["text"]
        _witness(
            "f3-red-assertion-message-boundary",
            business_date=business_date,
            message=str(excinfo.value)[:200],
        )
    # 证据面不得混入另一家店的记录（窗口过滤只作用于本目标行）。
    for call in chat_model.calls:
        payload = json.dumps(call["evidence"], ensure_ascii=False)
        assert "白鹭店" not in payload, payload
    _no_outbound(t09_network_guard)


def test_f3_no_host_clock_control_without_business_date(
    make_app, chat_model, t09_network_guard
):
    """``rag_business_date=None`` 对照：``as_of`` 为空 → 不做窗口过滤 → 该行仍可见。

    宿主当日 2026-11-17 不在 [2026-11-20, 2026-11-21] 内；若产品用宿主 now() 判定，
    这一例必须看不到该行。实测可见 ⇒ 日期判定只取配置，不取宿主时钟。
    """

    built = make_app(None, "no-business-date")
    app, admin, employee = built.app, built.admin, built.employee
    _dataset(app, admin)
    assert app.state.qa.config.business_date is None

    conversation_id = _conversation(employee)
    plan = _plan(app, employee, conversation_id, TURN_STORE)
    body = _ask(app, employee, conversation_id, TURN_STORE)
    _witness(
        "f3-3-no-host-clock",
        as_of=getattr(plan, "as_of", None),
        kind=body["kind"],
        docs=body["source_docs"],
        has_status=STORE_STATUS in body["text"],
    )
    assert getattr(plan, "as_of", None) is None
    assert body["kind"] == "answer", body
    assert STORE_STATUS in body["text"], body["text"]
    assert body["source_docs"] == [STORE_DOC], body["source_docs"]
    for call in chat_model.calls:
        payload = json.dumps(call["evidence"], ensure_ascii=False)
        assert "白鹭店" not in payload, payload
    _no_outbound(t09_network_guard)
