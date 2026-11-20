"""P2-T207-R1 返工：R1—R6 机制的独立合成红例/正例（先 RED 后最小修复）。

返工开发会话新写，不复用开发/验收测试模块；主体/数值/布局独立
（公司“北辰物流”、门店“东莞店/西关店”、数值 5321/746/3.8、编号 BC-09、
年份 2027/日期 2027-05-06）。预期全部来自公开产品契约：
- 无依据（指标词后仅年份/日期形态）→ 模型前拒答 not_found / UNSUPPORTED_FINANCIAL_METRIC；
- 有直接证据（含负数/括号单位/千分位/无连接词合法样式）→ 正常可答；
- 指标题错误取值（省略指标名/缩写错值/组内误绑/单位倍率不符）→ MODEL_OUTPUT_INVALID；
- 真同义改写取正确值、多指标合法回答、日期/编号非指标数字、P-R1 前提值 → 保持可答。

零真实调用：t09_network_guard 外部出站即 fail；provider 为 conftest 合成替身。
不读真实 H2/私有缓存/.env；不修改任何既有测试或保护件。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from openpyxl import Workbook

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from conftest import current_csrf, login, upload_document, write_headers  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from mktkb.rag.query import (  # noqa: E402
    metric_value_bindings,
    texts_support_financial_metric,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

COMPANY = "北辰物流"
TWO_METRIC = "北辰物流 2027 年一季度经营数据：营业收入 5321 万元，净利润 746 万元。"
NET_PROFIT_Q = "北辰物流 2027 年一季度净利润是多少？"


def _session(app, username: str, password: str) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    login(client, username, password)
    csrf = current_csrf(client)
    return SimpleNamespace(
        client=client,
        csrf=csrf,
        headers=write_headers(csrf),
        upload=lambda **kwargs: upload_document(client, csrf=csrf, **kwargs),
    )


def _make_env(settings, chat_model, tmp_path, *, trace: bool) -> SimpleNamespace:
    if trace:
        settings = settings.model_copy(
            update={
                "trace_enabled": True,
                "trace_db_path": tmp_path / "observability" / "qa-traces.sqlite3",
                "trace_content_mode": "hash",
            }
        )
    app = create_app(settings, model_gateway=chat_model)
    admin = _session(app, "admin", "AdminPass-1")
    employee = _session(app, "employee", "EmployeePass-1")
    return SimpleNamespace(
        app=app, admin=admin, employee=employee, model=chat_model, tmp_path=tmp_path
    )


def _teardown(env: SimpleNamespace) -> None:
    qa = getattr(env.app.state, "qa", None)
    if qa is not None:
        qa.close()
    repo = getattr(env.app.state, "trace_repo", None)
    if repo is not None:
        repo.close()
    env.app.state.db.dispose()


@pytest.fixture
def rw_env(settings, chat_model, tmp_path: Path):
    env = _make_env(settings, chat_model, tmp_path, trace=False)
    try:
        yield env
    finally:
        _teardown(env)


@pytest.fixture
def rw_trace_env(settings, chat_model, tmp_path: Path):
    env = _make_env(settings, chat_model, tmp_path, trace=True)
    try:
        yield env
    finally:
        _teardown(env)


def _publish(env, name: str, *, paragraphs=None, sheet=None) -> dict:
    source = env.tmp_path / name
    if paragraphs is not None:
        document = DocxDocument()
        for paragraph in paragraphs:
            document.add_paragraph(paragraph)
        document.save(source)
    else:
        headers, rows = sheet
        workbook = Workbook()
        sheet_obj = workbook.active
        sheet_obj.append(headers)
        for row in rows:
            sheet_obj.append(row)
        workbook.save(source)
    receipt = env.admin.upload(path=source)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = env.app.state.db.session()
    try:
        assert run_one_job(db, env.app.state.store).state == "succeeded"
        revision = int(get_revision(db))
    finally:
        db.close()
    published = env.admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=env.admin.headers,
        json={"expected_active_version_id": None, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    return published.json()


def _new_conversation(session) -> str:
    created = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _post(session, conversation_id: str, question: str):
    return session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )


def _ask(session, question: str) -> dict:
    response = _post(session, _new_conversation(session), question)
    assert response.status_code == 200, response.text
    return response.json()


def _trace_of(env, response):
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id, "开启 Trace 时 QA POST 必须返回 X-Trace-ID"
    return env.app.state.trace_repo.get(trace_id)


# ---------------------------------------------------------------- R1：年份/日期紧随指标词（应拒答）

def test_rw_m1_year_after_metric_refuses(rw_env) -> None:
    """证据只有“毛利2027年度测算”年份紧随 → 模型前拒答，不得当取值放行。"""
    _publish(rw_env, "rw_year.docx", paragraphs=[
        "北辰物流运营简报：毛利2027年度测算尚待财务复核，暂无对外披露数值。",
    ])
    calls_before = len(rw_env.model.calls)
    answer = _ask(rw_env.employee, "北辰物流的毛利是多少？")
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rw_env.model.calls) == calls_before, rw_env.model.calls


def test_rw_m1_date_after_metric_refuses(rw_env) -> None:
    """证据只有“毛利2027-05-06 盘点”日期紧随 → 模型前拒答。"""
    _publish(rw_env, "rw_date.docx", paragraphs=[
        "北辰物流周报：毛利2027-05-06 盘点记录已归档，数值待财务确认。",
    ])
    calls_before = len(rw_env.model.calls)
    answer = _ask(rw_env.employee, "北辰物流的毛利是多少？")
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rw_env.model.calls) == calls_before, rw_env.model.calls


def test_rw_m1_no_connector_value_answers(rw_env) -> None:
    """R1 正例约束：合法无连接词样式“毛利5321万元”不得被改拒。"""
    _publish(rw_env, "rw_plain.docx", paragraphs=[
        "北辰物流一季度毛利5321万元。",
    ])
    calls_before = len(rw_env.model.calls)
    answer = _ask(rw_env.employee, "北辰物流一季度的毛利是多少？")
    assert answer["kind"] == "answer", answer
    assert "5321" in answer["text"], answer["text"]
    assert answer["sources"], answer
    assert len(rw_env.model.calls) > calls_before, rw_env.model.calls


# ---------------------------------------------------------------- R2/R3/O3：合法取值样式（应可答）

def test_rw_m1_negative_value_answers(rw_env) -> None:
    """R2：合法负数亏损原值 → 正常可答，不得模型前误拒。"""
    _publish(rw_env, "rw_negative.docx", paragraphs=[
        "北辰物流 2027 年一季度净利润为 -746 万元。",
    ])
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "746" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rw_m1_paren_unit_answers(rw_env) -> None:
    """R3：合法括号单位“毛利（万元）：5321” → 正常可答。"""
    _publish(rw_env, "rw_paren.docx", paragraphs=[
        "北辰物流 2027 年一季度毛利（万元）：5321。",
    ])
    answer = _ask(rw_env.employee, "北辰物流 2027 年一季度毛利是多少？")
    assert answer["kind"] == "answer", answer
    assert "5321" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rw_m1_thousands_echo_answers(rw_env) -> None:
    """O3 正例：千分位原值回显 → 正常可答（绑定数值完整性不得截断）。"""
    _publish(rw_env, "rw_thousands.docx", paragraphs=[
        "北辰物流 2027 年一季度营业收入为 5,321 万元。",
    ])
    answer = _ask(rw_env.employee, "北辰物流 2027 年一季度营业收入是多少？")
    assert answer["kind"] == "answer", answer
    assert "321" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- R4/R5/R6：错误取值（应拒绝）

def test_rw_m2_omitted_name_rejected(rw_env) -> None:
    """R4：省略指标名“经营成果为 5321 万元”仍是错误取值 → 不得空绑定绕过。"""
    _publish(rw_env, "rw_omit.docx", paragraphs=[TWO_METRIC])
    rw_env.model.answer_text = "北辰物流 2027 年一季度经营成果为 5321 万元。"
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    assert answer["sources"] == [], answer


def test_rw_m2_abbreviation_wrong_value_rejected(rw_env) -> None:
    """R4：真缩写“纯利为 5321 万元”绑到净利润却取营收值 → 应拒绝。"""
    _publish(rw_env, "rw_abbr.docx", paragraphs=[TWO_METRIC])
    rw_env.model.answer_text = "北辰物流 2027 年一季度纯利为 5321 万元。"
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer


def test_rw_m2_intra_group_rejected(rw_env) -> None:
    """R5：毛利值 5321 说成净利润（同“利润”组内误绑）→ 应拒绝。"""
    _publish(rw_env, "rw_intra.docx", paragraphs=[
        "北辰物流 2027 年一季度毛利 5321 万元，净利润 746 万元。",
    ])
    rw_env.model.answer_text = "北辰物流 2027 年一季度净利润为 5321 万元。"
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer


def test_rw_m2_unit_mismatch_rejected(rw_env) -> None:
    """R6：数字核心相同但“746 万元 → 746 元”单位/倍率不符 → 应拒绝。"""
    _publish(rw_env, "rw_unit.docx", paragraphs=[
        "北辰物流 2027 年一季度净利润为 746 万元。",
    ])
    rw_env.model.answer_text = "北辰物流 2027 年一季度净利润为 746 元。"
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer


# ---------------------------------------------------------------- 正例控制（不得一律拒答）

def test_rw_m2_correct_accepted(rw_env) -> None:
    """逐字取本指标原值 746 → 正常保存。"""
    _publish(rw_env, "rw_ok.docx", paragraphs=[TWO_METRIC])
    rw_env.model.answer_text = "北辰物流 2027 年一季度净利润为 746 万元。"
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "746" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rw_m2_true_synonym_correct_answers(rw_env) -> None:
    """R5 约束：真同义缩写“净利”取正确值 746 → 仍须可答，不得误拒。"""
    _publish(rw_env, "rw_syn.docx", paragraphs=[
        "北辰物流 2027 年一季度净利润为 746 万元。",
    ])
    rw_env.model.answer_text = "北辰物流 2027 年一季度净利为 746 万元。"
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "746" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rw_m2_revenue_synonym_correct_answers(rw_env) -> None:
    """R5 约束：营业收入/营收合法同义改写取正确值 → 仍须可答。"""
    _publish(rw_env, "rw_rev_syn.docx", paragraphs=[
        "北辰物流 2027 年一季度营业收入为 5321 万元。",
    ])
    rw_env.model.answer_text = "北辰物流 2027 年一季度营收为 5321 万元。"
    answer = _ask(rw_env.employee, "北辰物流 2027 年一季度营业收入是多少？")
    assert answer["kind"] == "answer", answer
    assert "5321" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rw_m2_multi_metric_answer_accepted(rw_env) -> None:
    """合法多指标回答：两值各绑本指标且均有被引证据背书 → 正常保存。"""
    _publish(rw_env, "rw_multi.docx", paragraphs=[TWO_METRIC])
    rw_env.model.answer_text = "北辰物流 2027 年一季度净利润为 746 万元，营业收入为 5321 万元。"
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "746" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rw_m2_non_metric_numbers_preserved(rw_env) -> None:
    """回答中的编号/日期等非指标数字沿用既有 token 口径 → 回显不得误拒。"""
    _publish(rw_env, "rw_ids.docx", paragraphs=[
        "北辰物流 2027 年一季度净利润为 746 万元，报告编号 BC-09，日期 2027-05-06。",
    ])
    answer = _ask(rw_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "746" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rw_m2_p_r1_premise_preserved(rw_env) -> None:
    """P-R1 已批准放宽：问题原文逐字出现的前提值 746 可复述 → 保持可答。"""
    _publish(rw_env, "rw_premise.docx", paragraphs=[
        "北辰物流 2027 年一季度净利润为 746 万元。",
    ])
    rw_env.model.answer_text = "是的，北辰物流 2027 年一季度净利润为 746 万元。"
    answer = _ask(rw_env.employee, "北辰物流 2027 年一季度净利润是 746 万元吗？")
    assert answer["kind"] == "answer", answer
    assert "746" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- R1 RAG 记录消费路径（共享函数）

RW_RECORD_HEADERS = ["门店", "物品", "位置"]


def test_rw_m1_rag_record_year_adjacent_refuses(rw_trace_env) -> None:
    """RAG record+enumerate：记录行“毛利2027年度测算”年份紧随 → 拒答，chat=0。"""
    _publish(rw_trace_env, "rw_rag_bad.xlsx", sheet=(RW_RECORD_HEADERS, [
        ["东莞店", "桁架海报", "A区1号货架"],
        ["东莞店", "毛利2027年度测算", "编号BC-09"],
    ]))
    calls_before = len(rw_trace_env.model.calls)
    response = _post(rw_trace_env.employee, _new_conversation(rw_trace_env.employee),
                     "列出东莞店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rw_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rw_trace_env.model.calls) == calls_before, rw_trace_env.model.calls


def test_rw_m1_rag_record_value_answers(rw_trace_env) -> None:
    """RAG 正向控制：记录行确有毛利取值 → 正常枚举作答。"""
    _publish(rw_trace_env, "rw_rag_ok.xlsx", sheet=(RW_RECORD_HEADERS, [
        ["东莞店", "桁架海报", "毛利 5321 万元"],
        ["东莞店", "灯箱片", "毛利 746 万元"],
    ]))
    response = _post(rw_trace_env.employee, _new_conversation(rw_trace_env.employee),
                     "列出东莞店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rw_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "answer", answer
    assert "5321" in answer["text"], answer["text"]


# ---------------------------------------------------------------- 单元口径补充（既有公共函数）

def test_rw_unit_value_slot_signs() -> None:
    """R2：值位置接受 -/−/负 三种负号前缀。"""
    for text in (
        "净利润为 -746 万元",
        "净利润为 −746 万元",
        "净利润为负746万元",
    ):
        assert texts_support_financial_metric("净利润", [text]), text


def test_rw_unit_value_slot_dates_rejected() -> None:
    """R1：年份/日期形态（含斜杠日期、年月）不得认作指标取值。"""
    for text in (
        "毛利2027年度测算尚待复核",
        "毛利2027-05-06 盘点",
        "毛利2027/05/06 盘点",
        "毛利2027年5月盘点",
    ):
        assert not texts_support_financial_metric("毛利", [text]), text


def test_rw_unit_value_slot_legal_forms() -> None:
    """R1/R3 正例：无连接词、括号单位（全/半角）、百分比/百分之仍支持。"""
    for metric, text in (
        ("毛利", "毛利5321万元"),
        ("毛利", "毛利（万元）：5321"),
        ("毛利", "毛利(万元):5321"),
        ("毛利率", "毛利率为 3.8%"),
        ("毛利率", "毛利率为百分之3.8"),
    ):
        assert texts_support_financial_metric(metric, [text]), text


def test_rw_unit_bindings_exclude_year_and_keep_thousands() -> None:
    """R1/O3：年份不构成绑定；千分位绑定取完整数值核心而非前导截断。"""
    assert metric_value_bindings("毛利2027年度测算尚待复核", "毛利") == set()
    assert metric_value_bindings("营业收入为 5,321 万元", "营业收入") == {"5321"}