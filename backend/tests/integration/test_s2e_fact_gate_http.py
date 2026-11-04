"""S2-E：非记录型（正文/清单）回答的事实准入接线回归（CD-F1）。

只补本轮窗口：``conversations/service.py`` 非 record 分支调用 ``_validate_answer`` 时
没有传 ``evidence``/门店作用域，导致：
- 引用一行却把未引用候选行的值（数量/电话等数据型 token）搬进展示文本；
- 明确单门店问题把其它已知门店的事实混进回答。
这些在正常 ``create_app`` + TestClient 入口（上传→worker→发布→提问）必须返回既有
``MODEL_OUTPUT_INVALID``，且不放宽记录型（B1–B5）路径。

独立夹具：云岭/松溪/南塘 × 封口机/封箱机，数量与电话均与 S2-IA/CD 探针不同，
恶意文本也是本轮新值，避免按旧值硬编码通过。零真实模型/账本：模型为脚本替身。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from conftest import current_csrf, login, write_headers
from mktkb.config import Settings
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.providers.types import CompletionOutput

ORIGIN = "http://testserver"

DEVICE_HEADERS = ["门店", "物品", "数量", "标识", "位置", "备注"]
DEVICE_ROWS = [
    ["云岭店", "封口机", 57, "YL-5701", "A区1号", "常规"],
    ["云岭店", "封箱机", 63, "YL-6301", "A区2号", "参照松溪店盘点"],
    ["松溪店", "封口机", 58, "SX-5801", "B区5号", "夜间停机"],
    ["南塘店", "封口机", 61, "NT-6101", "C区8号", "常规"],
    ["南塘店", "封箱机", 62, "NT-6201", "C区9号", "参照云岭店盘点"],
]
STORE_HEADERS = ["门店", "联系人", "联系电话", "地址", "合作状态"]
STORE_ROWS = [
    ["云岭店", "岑岚", "0598-7700-1001", "云岭路21号", "合作中"],
    ["松溪店", "祝禾", "0598-7700-1002", "松溪路22号", "暂停"],
    ["南塘店", "池野", "0598-7700-1003", "南塘路23号", "合作中"],
]
PROSE_MARK = "先断开电源"
PROSE_TAIL_MARK = "异响处理流程"
PROSE = "封口机的日常校验流程：先断开电源，再清洁加热片，最后记录运行状态。"
PROSE_TAIL = "异响处理流程：停止使用并联系设备管理员登记。"
PROSE_QUESTION = "校验流程是什么？"
SINGLE_STORE_QUESTION = "云岭店的封口机的数量是多少？"
LIST_QUESTION = "封口机的数量是多少？"
# CD-F1-R1：只锁门店、不锁物品，使同一门店的未引用行也进入候选（复现 C1 的必要条件）。
SCOPE_QUESTION = "云岭店的盘点记录有哪些？"
SCOPE_QUESTION_NT = "南塘店的盘点记录有哪些？"


# ---------------------------------------------------------------- 夹具与实际入口


class ScriptedAnswer:
    """只回显本用例指定的文本与引用；不内置任何业务答案。"""

    def __init__(self, text: str, pick=None) -> None:  # noqa: ANN001
        self.text = text
        self.pick = pick
        self.calls: list[dict] = []

    async def complete(self, request, *, timeout_seconds: float) -> CompletionOutput:  # noqa: ANN001
        self.calls.append(
            {
                "purpose": request.purpose,
                "question": request.question,
                "evidence": [
                    {"source_id": item.source_id, "text": item.text, "fields": dict(item.fields or {})}
                    for item in request.evidence
                ],
            }
        )
        if request.purpose != "answer":
            return CompletionOutput(text="", query_terms=())
        items = list(request.evidence)
        ids = list(self.pick(items)) if self.pick else [item.source_id for item in items]
        assert ids, f"本用例需要至少一条证据引用，实际证据数 {len(items)}"
        return CompletionOutput(text=self.text, source_ids=tuple(ids))


def _pick_by_text(items, needle: str) -> list[str]:
    return [item.source_id for item in items if needle in (item.text or "")]


def _pick_by_store(items, *stores: str) -> list[str]:
    picked = []
    for item in items:
        fields = dict(item.fields or {})
        if fields.get("门店") in stores and fields.get("物品") == "封口机":
            picked.append(item.source_id)
    return picked


def _pick_by_store_and_item(items, store: str, item: str) -> list[str]:
    """按门店 + 物品精确选行（用于引用含他店名备注的封箱机行）。"""
    picked = []
    for entry in items:
        fields = dict(entry.fields or {})
        if fields.get("门店") == store and fields.get("物品") == item:
            picked.append(entry.source_id)
    return picked


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], *, sheet: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.cell(row=1, column=1, value=f"{sheet}（S2-E 夹具）")
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _docx(path: Path) -> Path:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading("封口机操作说明", level=1)
    document.add_paragraph(PROSE)
    document.add_paragraph(PROSE_TAIL)
    document.save(path)
    return path


def _settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=root,
        database_url=f"sqlite:///{(root / 'e.sqlite3').as_posix()}",
        storage_dir=root / "storage",
        cookie_secure=False,
        csrf_secret="s2e-test-csrf-secret-0123456789",
        admin_password="S2eAdminPass-1",
        employee_password="S2eEmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
        rag_page_size=5,
        rag_top_k=8,
    )


def _session(app, username: str, password: str):
    client = TestClient(app, raise_server_exceptions=False)
    login(client, username, password)
    return client


def _publish(app, admin: TestClient, path: Path, revision: int | None = None) -> None:
    csrf = current_csrf(admin)
    with path.open("rb") as handle:
        receipt = admin.post(
            "/api/v1/documents",
            files={"file": (path.name, handle, "application/octet-stream")},
            headers=write_headers(csrf),
        )
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
        current = int(get_revision(db))
    finally:
        db.close()
    published = admin.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=write_headers(csrf),
        json={"expected_active_version_id": None, "expected_revision": current if revision is None else revision},
    )
    assert published.status_code == 200, published.text


@pytest.fixture
def e_app(tmp_path: Path):
    settings = _settings(tmp_path / "store")
    app = create_app(settings, model_gateway=ScriptedAnswer("占位回答"))
    admin = _session(app, "admin", settings.admin_password)
    base = Path(settings.data_dir)
    _publish(app, admin, _xlsx(base / "device.xlsx", DEVICE_HEADERS, DEVICE_ROWS, sheet="设备台账"))
    _publish(app, admin, _xlsx(base / "store.xlsx", STORE_HEADERS, STORE_ROWS, sheet="门店联系表"))
    _publish(app, admin, _docx(base / "manual.docx"))
    employee = _session(app, "employee", settings.employee_password)
    try:
        yield {"app": app, "employee": employee}
    finally:
        app.state.qa.close()
        app.state.db.dispose()


def _ask(app, client: TestClient, question: str) -> tuple[dict, ScriptedAnswer]:
    csrf = current_csrf(client)
    created = client.post("/api/v1/conversations", json={}, headers=write_headers(csrf))
    assert created.status_code == 201, created.text
    conversation = created.json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=write_headers(csrf),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    history = client.get(f"/api/v1/conversations/{conversation}/messages")
    assert history.status_code == 200, history.text
    payload["_history"] = history.json()
    return payload, app.state.model_gateway


def _rows(payload: dict) -> list[int]:
    return sorted(
        {
            (source.get("locator") or {}).get("row")
            for source in payload.get("sources") or []
            if (source.get("locator") or {}).get("row")
        }
    )


def _assert_refused(payload: dict, *, leaked: tuple[str, ...]) -> None:
    assert payload["kind"] == "service_error", payload
    assert payload["error_code"] == "MODEL_OUTPUT_INVALID", payload
    assert payload["sources"] == [] and payload["candidates"] == [], payload
    for token in leaked:
        assert token not in payload["text"], payload
    # 只比对消息正文，不扫整份 JSON（UUID/时间戳里的十六进制片段会误伤）。
    texts = [str(item.get("text") or "") for item in payload["_history"].get("items") or []]
    assert not any(token in text for text in texts for token in leaked), payload


# ---------------------------------------------------------------- 负向：CD-F1 原型


def test_single_store_question_rejects_forged_quantity_8888_style(e_app):
    """B6 原型（本轮新值 9001）：引用行只有数量 57，夹带 9001 必须拒绝且不回显。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer("根据资料：门店：云岭店；物品：封口机；数量：9001")
    payload, gateway = _ask(app, client, SINGLE_STORE_QUESTION)
    _assert_refused(payload, leaked=("9001",))
    assert app.state.model_gateway.calls[0]["purpose"] == "answer"
    assert len(gateway.calls) == 1, "拒绝后不得自动重发模型调用"


def test_single_store_question_rejects_forged_phone_400_style(e_app):
    """B7 原型（本轮新值）：合法数量 57 + 资料中不存在的电话 400-777-9090。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(
        "根据资料：门店：云岭店；物品：封口机；数量：57；联系电话：400-777-9090"
    )
    payload, _gateway = _ask(app, client, SINGLE_STORE_QUESTION)
    _assert_refused(payload, leaked=("400-777-9090",))
    assert "57" not in payload["text"], "拒绝不得静默改成正确答案"


def test_value_carried_from_uncited_candidate_row_is_rejected(e_app):
    """只引用云岭店一行，却把候选里松溪店的 58 搬进回答：未引用来源不能为值背书。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(
        "根据资料：门店：云岭店；物品：封口机；数量：57；松溪店封口机数量：58",
        pick=lambda items: _pick_by_store(items, "云岭店"),
    )
    payload, _gateway = _ask(app, client, LIST_QUESTION)
    _assert_refused(payload, leaked=("58",))


def test_other_store_fact_is_rejected_for_explicit_single_store_question(e_app):
    """明确单门店：把另一已知门店的真实状态（松溪店暂停）混进回答必须拒绝。

    这里没有新增数据型 token，只由门店作用域校验拦住，单独覆盖 CD-F1 的第二半。
    """
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(
        "根据资料：门店：云岭店；物品：封口机；数量：57；松溪店合作状态：暂停",
        pick=lambda items: _pick_by_store(items, "云岭店"),
    )
    payload, _gateway = _ask(app, client, SINGLE_STORE_QUESTION)
    _assert_refused(payload, leaked=("暂停",))


# ---------------------------------------------------------------- 正向：不误拒


def test_attested_original_value_still_answers(e_app):
    """合法原值：引用被验行、逐字原值 57 → answer，来源只指向该行。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(
        "根据资料：门店：云岭店；物品：封口机；数量：57", pick=lambda items: _pick_by_store(items, "云岭店")
    )
    payload, _gateway = _ask(app, client, SINGLE_STORE_QUESTION)
    assert payload["kind"] == "answer", payload
    assert payload["text"] == "根据资料：门店：云岭店；物品：封口机；数量：57", payload
    assert _rows(payload) == [4], payload


def test_legal_cross_store_enumeration_still_answers(e_app):
    """合法跨店枚举（问题不限门店）：引用两行、各用其原值 57/58 → answer。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(
        "根据资料：门店：云岭店；物品：封口机；数量：57；门店：松溪店；物品：封口机；数量：58",
        pick=lambda items: _pick_by_store(items, "云岭店", "松溪店"),
    )
    payload, _gateway = _ask(app, client, LIST_QUESTION)
    assert payload["kind"] == "answer", payload
    assert set(_rows(payload)) == {4, 6}, payload
    assert "57" in payload["text"] and "58" in payload["text"], payload


def test_multi_source_prose_answer_still_answers(e_app):
    """合法多来源正文：两段正文原句（无数值）同时引用 → answer，来源指向两段。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(
        f"{PROSE}{PROSE_TAIL}",
        pick=lambda items: _pick_by_text(items, PROSE_MARK) + _pick_by_text(items, PROSE_TAIL_MARK),
    )
    payload, _gateway = _ask(app, client, PROSE_QUESTION)
    assert payload["kind"] == "answer", payload
    assert payload["text"] == f"{PROSE}{PROSE_TAIL}", payload
    assert len(payload["sources"]) == 2, payload["sources"]
    assert all("paragraph" in (source.get("locator") or {}) for source in payload["sources"]), payload["sources"]


def test_mixed_prose_and_row_multi_source_answers(e_app):
    """合法多来源（正文 + 表格）：正文原句与表格原值 57 同时引用 → answer。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(
        f"{PROSE}门店：云岭店；物品：封口机；数量：57",
        pick=lambda items: _pick_by_text(items, PROSE_MARK) + _pick_by_store(items, "云岭店"),
    )
    payload, _gateway = _ask(app, client, "校验流程和数量是什么？")
    assert payload["kind"] == "answer", payload
    assert PROSE in payload["text"] and "57" in payload["text"], payload
    locators = [source.get("locator") or {} for source in payload["sources"]]
    assert len(locators) == 2, payload["sources"]
    assert any("row" in locator for locator in locators) and any("paragraph" in locator for locator in locators), locators


def test_prose_only_answer_without_numbers_still_answers(e_app):
    """无数值正文：只回显证据正文原句、无数据型 token → answer 不被全量拒绝。"""
    app, client = e_app["app"], e_app["employee"]
    app.state.model_gateway = ScriptedAnswer(PROSE, pick=lambda items: _pick_by_text(items, PROSE_MARK))
    payload, _gateway = _ask(app, client, PROSE_QUESTION)
    assert payload["kind"] == "answer", payload
    assert payload["text"] == PROSE, payload


# ---------------------------------------------------------------- CD-F1-R1：门店豁免只取实际引用


def test_other_store_name_only_in_uncited_candidate_row_is_rejected(e_app):
    """C1 精确复现：单店问题只引用 57 那行，他店名只出现在**未引用候选行**的备注里。

    修前：松溪店因“参照松溪店盘点”出现在候选行 5 而被豁免 → answer，他店“暂停”
    进入展示文本与持久历史（S2-IA §6 的 FAIL）。修后：豁免只取实际引用的 row 4。
    """
    app, client = e_app["app"], e_app["employee"]
    text = "根据资料：门店：云岭店；物品：封口机；数量：57，常规；松溪店合作状态：暂停"
    app.state.model_gateway = ScriptedAnswer(
        text, pick=lambda items: _pick_by_store_and_item(items, "云岭店", "封口机")
    )
    payload, gateway = _ask(app, client, SCOPE_QUESTION)
    _assert_refused(payload, leaked=("松溪店", "暂停"))
    assert len(gateway.calls) == 1, "拒绝后不得自动重发模型调用"


def test_other_store_name_absent_from_all_candidates_still_rejected(e_app):
    """对照：同问/同引用，混入**未在任何候选出现**的南塘店 → 修复前后都拒绝。

    这条证明门店关口本身生效，C1 的放行原因唯一指向“豁免集取了全部候选”。
    """
    app, client = e_app["app"], e_app["employee"]
    text = "根据资料：门店：云岭店；物品：封口机；数量：57，常规；南塘店合作状态：合作中"
    app.state.model_gateway = ScriptedAnswer(
        text, pick=lambda items: _pick_by_store_and_item(items, "云岭店", "封口机")
    )
    payload, _gateway = _ask(app, client, SCOPE_QUESTION)
    _assert_refused(payload, leaked=("南塘店",))


def test_cited_row_naming_other_store_can_be_quoted_verbatim(e_app):
    """正向：真正引用含他店名的备注行（row 5），逐字引用其内容 → answer。

    防止把豁免集改为 cited-only 后误拒合法引用。
    """
    app, client = e_app["app"], e_app["employee"]
    text = "根据资料：门店：云岭店；物品：封箱机；数量：63；备注：参照松溪店盘点"
    app.state.model_gateway = ScriptedAnswer(
        text, pick=lambda items: _pick_by_store_and_item(items, "云岭店", "封箱机")
    )
    payload, _gateway = _ask(app, client, SCOPE_QUESTION)
    assert payload["kind"] == "answer", payload
    assert payload["text"] == text, payload
    assert _rows(payload) == [5], payload
    history_texts = [str(item.get("text") or "") for item in payload["_history"].get("items") or []]
    assert text in history_texts, payload["_history"]


def test_second_store_unreferenced_candidate_note_is_rejected(e_app):
    """不同门店/数值的第二组：南塘店只引用 61 那行，未引用行 8 备注含云岭店。

    与 C1（云岭/松溪/57/63）不同值，防止按单组夹具硬编码通过。
    """
    app, client = e_app["app"], e_app["employee"]
    text = "根据资料：门店：南塘店；物品：封口机；数量：61，常规；云岭店合作状态：合作中"
    app.state.model_gateway = ScriptedAnswer(
        text, pick=lambda items: _pick_by_store_and_item(items, "南塘店", "封口机")
    )
    payload, _gateway = _ask(app, client, SCOPE_QUESTION_NT)
    _assert_refused(payload, leaked=("云岭店",))


def test_second_store_cited_note_row_can_be_quoted_verbatim(e_app):
    """正向：真正引用南塘店含“参照云岭店盘点”的备注行（row 8）→ answer。"""
    app, client = e_app["app"], e_app["employee"]
    text = "根据资料：门店：南塘店；物品：封箱机；数量：62；备注：参照云岭店盘点"
    app.state.model_gateway = ScriptedAnswer(
        text, pick=lambda items: _pick_by_store_and_item(items, "南塘店", "封箱机")
    )
    payload, _gateway = _ask(app, client, SCOPE_QUESTION_NT)
    assert payload["kind"] == "answer", payload
    assert payload["text"] == text, payload
    assert _rows(payload) == [8], payload


def test_cross_store_enumeration_with_second_value_set_still_answers(e_app):
    """正向：合法跨店多来源（云岭 57 + 南塘 61）→ answer，两个来源行均在。"""
    app, client = e_app["app"], e_app["employee"]
    text = (
        "根据资料：门店：云岭店；物品：封口机；数量：57；"
        "门店：南塘店；物品：封口机；数量：61"
    )
    app.state.model_gateway = ScriptedAnswer(
        text, pick=lambda items: _pick_by_store(items, "云岭店", "南塘店")
    )
    payload, _gateway = _ask(app, client, LIST_QUESTION)
    assert payload["kind"] == "answer", payload
    assert payload["text"] == text, payload
    assert set(_rows(payload)) == {4, 7}, payload
    history_texts = [str(item.get("text") or "") for item in payload["_history"].get("items") or []]
    assert text in history_texts, payload["_history"]
