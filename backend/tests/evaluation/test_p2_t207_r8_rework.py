"""T207-R1 第二轮返工（R8）开发自写套件：全新主体合成正反例，走真实产品装配链。

第二轮返工开发者（全新上下文，非首轮开发/返工 R1 开发/任何验收复验者）独立编写，
不复用既有测试模块。主体/数值/布局均不同：公司“浩辰光电”、门店“临江店/望湖店”、
数值 3654/287/5.3/2.9、编号 HC-41、年份 2029、日期 2029-06-18。

预期全部先于运行按公开产品契约写明（不按产品实际行为倒推）：
- R8 红例：证据仅“毛利2029财年测算/毛利2029 财年预算”这类年份形态、无毛利取值
  → 模型前拒答 not_found / UNSUPPORTED_FINANCIAL_METRIC 文案、sources=[]、chat=0；
  覆盖 legacy 模型前支持闸与 RAG record+enumerate 两条实际消费路径；
- 正例保持：无连接词“毛利3654万元”、三种负号、全/半角括号单位、千分位回显、
  百分之、单独倍率、财年在前取值在后（“2029财年毛利为 3654 万元”）→ 正常可答；
- R1—R6 已修切片不回归：年度/年月拒答、组内双向误绑/单位倍率/空绑定拒绝、
  真同义可答、P-R1 前提值可答。

零真实调用：t09_network_guard 外部出站即 fail；provider 为 conftest 合成替身（未改）。
不读真实 H2/私有缓存/.env；不修改任何产品代码或既有测试。
"""

from __future__ import annotations

import json
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
    metric_binding_values,
    metric_value_bindings,
    texts_support_financial_metric,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

COMPANY = "浩辰光电"
TWO_METRIC = "浩辰光电 2029 年一季度经营数据：营业收入 3654 万元，净利润 287 万元。"
NET_PROFIT_Q = "浩辰光电 2029 年一季度净利润是多少？"
GROSS_Q = "浩辰光电 2029 年一季度毛利是多少？"
REVENUE_Q = "浩辰光电 2029 年一季度营业收入是多少？"
RATE_Q = "浩辰光电 2029 年一季度毛利率是多少？"
UNSUPPORTED_COPY = "没有可支撑"


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
        app=app, admin=admin, employee=employee, model=chat_model, tmp_path=tmp_path,
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
def r8_env(settings, chat_model, tmp_path: Path):
    env = _make_env(settings, chat_model, tmp_path, trace=False)
    try:
        yield env
    finally:
        _teardown(env)


@pytest.fixture
def r8_trace_env(settings, chat_model, tmp_path: Path):
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


def _assert_pre_model_refusal(env, answer: dict, calls_before: int) -> None:
    assert answer["kind"] == "not_found", answer
    assert UNSUPPORTED_COPY in answer["text"], answer["text"]
    assert answer["sources"] == [], answer
    assert len(env.model.calls) == calls_before, env.model.calls


def _assert_m2_rejected(answer: dict) -> None:
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    assert answer["sources"] == [], answer


def _assert_answered(env, answer: dict, fragment: str, calls_before: int | None = None) -> None:
    assert answer["kind"] == "answer", answer
    assert fragment in answer["text"], answer["text"]
    assert answer["sources"], answer
    if calls_before is not None:
        assert len(env.model.calls) > calls_before, env.model.calls


# ---------------------------------------------------------------- 单元口径（既有公共函数）

def test_r8_unit_fiscal_year_not_value() -> None:
    """R8 单元红例：“NNNN财年”（含空白变体）是年份形态，不构成指标支持/绑定。"""
    for text in ("毛利2029财年测算尚待复核", "毛利2029 财年预算仍在编制"):
        assert not texts_support_financial_metric("毛利", [text]), text
        assert metric_value_bindings(text, "毛利") == set(), text
    assert "毛利" not in metric_binding_values("毛利2029财年测算尚待复核")


def test_r8_unit_date_forms_rejected() -> None:
    """R1 切片保持：年度/-日期//日期/年月形态均不构成指标支持。"""
    for text in (
        "毛利2029年度预算尚在编制",
        "毛利2029-06-18 巡检",
        "毛利2029/06/18 盘点",
        "毛利2029年6月复盘",
    ):
        assert not texts_support_financial_metric("毛利", [text]), text


def test_r8_unit_legal_forms_supported() -> None:
    """正例单元口径：无连接词/三种负号/全半角括号单位/百分比/百分之 均支持。"""
    for metric, text in (
        ("毛利", "毛利3654万元"),
        ("净利润", "净利润为 -287 万元"),
        ("净利润", "净利润为 −287 万元"),
        ("净利润", "净利润为负287万元"),
        ("毛利", "毛利（万元）：3654"),
        ("毛利", "毛利(万元):3654"),
        ("毛利率", "毛利率为 5.3%"),
        ("毛利率", "毛利率为百分之5.3"),
    ):
        assert texts_support_financial_metric(metric, [text]), text


def test_r8_unit_thousands_binding_complete() -> None:
    """O3 切片保持：千分位绑定核心完整（3654，不是 3）；年份不构成绑定。"""
    assert metric_value_bindings("营业收入为 3,654 万元", "营业收入") == {"3654"}
    assert metric_binding_values("营业收入为 3,654 万元")["营收"] == {("3654", "万", "元")}
    assert metric_value_bindings("毛利2029年度预算尚在编制", "毛利") == set()


# ---------------------------------------------------------------- R8：财年形态（legacy 模型前支持闸）

def test_r8_m1_fiscal_year_refuses(r8_env) -> None:
    """R8 红例：证据仅“毛利2029财年测算”年份形态、无毛利取值 → 模型前拒答，chat=0。"""
    _publish(r8_env, "r8_fy.docx", paragraphs=[
        "浩辰光电经营简报：毛利2029财年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(r8_env.model.calls)
    answer = _ask(r8_env.employee, "浩辰光电的毛利是多少？")
    _assert_pre_model_refusal(r8_env, answer, calls_before)


def test_r8_m1_fiscal_year_with_space_refuses(r8_env) -> None:
    """R8 红例空白变体：“毛利2029 财年预算”同样不是取值 → 模型前拒答，chat=0。"""
    _publish(r8_env, "r8_fy_space.docx", paragraphs=[
        "浩辰光电经营简报：毛利2029 财年预算仍在编制，未形成对外数值。",
    ])
    calls_before = len(r8_env.model.calls)
    answer = _ask(r8_env.employee, "浩辰光电的毛利是多少？")
    _assert_pre_model_refusal(r8_env, answer, calls_before)


def test_r8_m1_fiscal_year_before_metric_answers(r8_env) -> None:
    """R8 正例约束：财年在前、取值在后“2029财年毛利为 3654 万元” → 不得误拒，正常可答。"""
    _publish(r8_env, "r8_fy_ok.docx", paragraphs=[
        "浩辰光电2029财年毛利为 3654 万元。",
    ])
    calls_before = len(r8_env.model.calls)
    answer = _ask(r8_env.employee, "浩辰光电的毛利是多少？")
    _assert_answered(r8_env, answer, "3654", calls_before)


def test_r8_m1_year_suffix_refuses(r8_env) -> None:
    """R1 切片保持：年度紧随“毛利2029年度预算” → 模型前拒答。"""
    _publish(r8_env, "r8_year.docx", paragraphs=[
        "浩辰光电经营简报：毛利2029年度预算尚在编制，未形成对外数值。",
    ])
    calls_before = len(r8_env.model.calls)
    answer = _ask(r8_env.employee, "浩辰光电的毛利是多少？")
    _assert_pre_model_refusal(r8_env, answer, calls_before)


def test_r8_m1_year_month_refuses(r8_env) -> None:
    """R1 切片保持：年月形态“毛利2029年6月复盘” → 模型前拒答。"""
    _publish(r8_env, "r8_ym.docx", paragraphs=[
        "浩辰光电月报：毛利2029年6月复盘会议已召开，数值待财务确认。",
    ])
    calls_before = len(r8_env.model.calls)
    answer = _ask(r8_env.employee, "浩辰光电的毛利是多少？")
    _assert_pre_model_refusal(r8_env, answer, calls_before)


def test_r8_m1_no_connector_answers(r8_env) -> None:
    """正例约束：合法无连接词“毛利3654万元”不得回归为拒答，且实际调用模型。"""
    _publish(r8_env, "r8_plain.docx", paragraphs=[
        "浩辰光电一季度毛利3654万元。",
    ])
    calls_before = len(r8_env.model.calls)
    answer = _ask(r8_env.employee, "浩辰光电一季度的毛利是多少？")
    _assert_answered(r8_env, answer, "3654", calls_before)


# ---------------------------------------------------------------- R2：三种负号（应可答）

def test_r8_m1_negative_ascii_answers(r8_env) -> None:
    """R2 切片保持：ASCII 负号亏损原值“-287 万元” → 正常可答。"""
    _publish(r8_env, "r8_neg_a.docx", paragraphs=[
        "浩辰光电 2029 年一季度净利润为 -287 万元。",
    ])
    answer = _ask(r8_env.employee, NET_PROFIT_Q)
    _assert_answered(r8_env, answer, "287")


def test_r8_m1_negative_unicode_answers(r8_env) -> None:
    """R2 切片保持：U+2212 负号“−287 万元” → 正常可答。"""
    _publish(r8_env, "r8_neg_u.docx", paragraphs=[
        "浩辰光电 2029 年一季度净利润为 −287 万元。",
    ])
    answer = _ask(r8_env.employee, NET_PROFIT_Q)
    _assert_answered(r8_env, answer, "287")


def test_r8_m1_negative_cn_answers(r8_env) -> None:
    """R2 切片保持：中文负号“负287万元” → 正常可答。"""
    _publish(r8_env, "r8_neg_c.docx", paragraphs=[
        "浩辰光电 2029 年一季度净利润为负287万元。",
    ])
    answer = _ask(r8_env.employee, NET_PROFIT_Q)
    _assert_answered(r8_env, answer, "287")


# ---------------------------------------------------------------- R3：括号单位（应可答）

def test_r8_m1_paren_fullwidth_answers(r8_env) -> None:
    """R3 切片保持：全角括号单位“毛利（万元）：3654” → 正常可答。"""
    _publish(r8_env, "r8_paren_f.docx", paragraphs=[
        "浩辰光电 2029 年一季度毛利（万元）：3654。",
    ])
    answer = _ask(r8_env.employee, GROSS_Q)
    _assert_answered(r8_env, answer, "3654")


def test_r8_m1_paren_halfwidth_answers(r8_env) -> None:
    """R3 切片保持：半角括号单位“毛利(万元):3654” → 正常可答。"""
    _publish(r8_env, "r8_paren_h.docx", paragraphs=[
        "浩辰光电 2029 年一季度毛利(万元):3654。",
    ])
    answer = _ask(r8_env.employee, GROSS_Q)
    _assert_answered(r8_env, answer, "3654")


# ---------------------------------------------------------------- O3：千分位回显（应可答）

def test_r8_m1_thousands_echo_answers(r8_env) -> None:
    """O3 切片保持：千分位原值回显“3,654” → 可答，绑定核心不得截断。"""
    _publish(r8_env, "r8_thousands.docx", paragraphs=[
        "浩辰光电 2029 年一季度营业收入为 3,654 万元。",
    ])
    answer = _ask(r8_env.employee, REVENUE_Q)
    _assert_answered(r8_env, answer, "654")


# ---------------------------------------------------------------- R4：空绑定绕过（拒绝）与缩写正例

def test_r8_m2_omitted_name_rejected(r8_env) -> None:
    """R4 切片保持：省略指标名“经营成果为 3654 万元”（营收值冒充净利润）→ 拒绝。"""
    _publish(r8_env, "r8_omit.docx", paragraphs=[TWO_METRIC])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度经营成果为 3654 万元。"
    answer = _ask(r8_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_r8_m2_abbrev_correct_answers(r8_env) -> None:
    """R4 正例保持：真缩写“净利”取正确值 287 → 仍须可答。"""
    _publish(r8_env, "r8_abbr_ok.docx", paragraphs=[
        "浩辰光电 2029 年一季度净利润为 287 万元。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度净利为 287 万元。"
    answer = _ask(r8_env.employee, NET_PROFIT_Q)
    _assert_answered(r8_env, answer, "287")


# ---------------------------------------------------------------- R5：组内双向误绑 / 真同义

def test_r8_m2_intra_gross_to_net_rejected(r8_env) -> None:
    """R5 切片保持：毛利值 3654 说成净利润（利润组内误绑）→ 拒绝。"""
    _publish(r8_env, "r8_intra_gn.docx", paragraphs=[
        "浩辰光电 2029 年一季度毛利 3654 万元，净利润 287 万元。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度净利润为 3654 万元。"
    answer = _ask(r8_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_r8_m2_intra_net_to_gross_rejected(r8_env) -> None:
    """R5 切片保持：反向组内误绑——净利润值 287 说成毛利 → 同样拒绝。"""
    _publish(r8_env, "r8_intra_ng.docx", paragraphs=[
        "浩辰光电 2029 年一季度毛利 3654 万元，净利润 287 万元。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度毛利为 287 万元。"
    answer = _ask(r8_env.employee, GROSS_Q)
    _assert_m2_rejected(answer)


def test_r8_m2_revenue_synonym_answers(r8_env) -> None:
    """R5 正例保持：营业收入→营收 真同义改写取正确值 → 可答。"""
    _publish(r8_env, "r8_rev_syn.docx", paragraphs=[
        "浩辰光电 2029 年一季度营业收入为 3654 万元。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度营收为 3654 万元。"
    answer = _ask(r8_env.employee, REVENUE_Q)
    _assert_answered(r8_env, answer, "3654")


# ---------------------------------------------------------------- R6：单位/倍率

def test_r8_m2_wan_to_yuan_rejected(r8_env) -> None:
    """R6 切片保持：287 万元 → 287 元（倍率不符）→ 拒绝。"""
    _publish(r8_env, "r8_unit_y.docx", paragraphs=[
        "浩辰光电 2029 年一季度净利润为 287 万元。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度净利润为 287 元。"
    answer = _ask(r8_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_r8_m2_wan_to_yi_rejected(r8_env) -> None:
    """R6 切片保持：3654 万元 → 3654 亿元（倍率不符）→ 拒绝。"""
    _publish(r8_env, "r8_unit_yi.docx", paragraphs=[
        "浩辰光电 2029 年一季度营业收入为 3654 万元。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度营业收入为 3654 亿元。"
    answer = _ask(r8_env.employee, REVENUE_Q)
    _assert_m2_rejected(answer)


def test_r8_m2_percent_cn_answers(r8_env) -> None:
    """R6 归一正例保持：“百分之5.3” ≡ “5.3%” → 可答。"""
    _publish(r8_env, "r8_pct.docx", paragraphs=[
        "浩辰光电 2029 年一季度毛利率为 5.3%。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度毛利率为百分之5.3。"
    answer = _ask(r8_env.employee, RATE_Q)
    _assert_answered(r8_env, answer, "5.3")


def test_r8_m2_bare_wan_answers(r8_env) -> None:
    """R6 归一正例保持：单独倍率“3654万” ≡ “3654万元” → 可答。"""
    _publish(r8_env, "r8_bare_w.docx", paragraphs=[
        "浩辰光电 2029 年一季度营业收入为 3654 万元。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度营业收入为 3654万。"
    answer = _ask(r8_env.employee, REVENUE_Q)
    _assert_answered(r8_env, answer, "3654")


def test_r8_m2_paren_unit_binding_answers(r8_env) -> None:
    """R6 括号单位绑定正例保持：证据“毛利（万元）：3654”背书回答“毛利为 3654 万元”。"""
    _publish(r8_env, "r8_paren_bind.docx", paragraphs=[
        "浩辰光电 2029 年一季度毛利（万元）：3654。",
    ])
    r8_env.model.answer_text = "浩辰光电 2029 年一季度毛利为 3654 万元。"
    answer = _ask(r8_env.employee, GROSS_Q)
    _assert_answered(r8_env, answer, "3654")


# ---------------------------------------------------------------- P-R1：问题前提值（已批准放宽）

def test_r8_m2_p_r1_premise_answers(r8_env) -> None:
    """P-R1 保持：问题前提值 287 逐字出现 → 复述可答，不得撤销。"""
    _publish(r8_env, "r8_premise.docx", paragraphs=[
        "浩辰光电 2029 年一季度净利润为 287 万元。",
    ])
    r8_env.model.answer_text = "是的，浩辰光电 2029 年一季度净利润为 287 万元。"
    answer = _ask(r8_env.employee, "浩辰光电 2029 年一季度净利润是 287 万元吗？")
    _assert_answered(r8_env, answer, "287")


# ---------------------------------------------------------------- RAG record 消费路径（共享函数）

R8_RECORD_HEADERS = ["门店", "物品", "位置"]


def test_r8_m1_rag_record_fiscal_year_refuses(r8_trace_env) -> None:
    """R8 红例（RAG record+enumerate）：记录行“毛利2029财年测算”年份形态
    → rag 路径模型前拒答，chat=0。"""
    _publish(r8_trace_env, "r8_rag_bad.xlsx", sheet=(R8_RECORD_HEADERS, [
        ["临江店", "桁架海报", "A区1号货架"],
        ["临江店", "毛利2029财年测算", "编号HC-41"],
    ]))
    calls_before = len(r8_trace_env.model.calls)
    response = _post(r8_trace_env.employee, _new_conversation(r8_trace_env.employee),
                     "列出临江店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(r8_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(r8_trace_env.model.calls) == calls_before, r8_trace_env.model.calls


def test_r8_m1_rag_record_value_answers(r8_trace_env) -> None:
    """RAG 正向控制：记录行确有毛利取值 → rag 路径正常枚举作答。"""
    _publish(r8_trace_env, "r8_rag_ok.xlsx", sheet=(R8_RECORD_HEADERS, [
        ["临江店", "桁架海报", "毛利 3654 万元"],
        ["临江店", "灯箱片", "毛利 287 万元"],
    ]))
    response = _post(r8_trace_env.employee, _new_conversation(r8_trace_env.employee),
                     "列出临江店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(r8_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "answer", answer
    assert "3654" in answer["text"], answer["text"]