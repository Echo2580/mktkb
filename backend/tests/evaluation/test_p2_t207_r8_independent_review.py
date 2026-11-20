"""T207-R1 第二轮返工（R8）独立复验：全新主体合成正反例，走真实产品装配链。

复验者（全新上下文，非首轮/返工 R1/R8 开发者、非任何验收复验者）独立编写，不复用既有测试模块。
主体/数值/布局完全独立：公司“澜庭生物”、门店“东篱店/北屿店”、数值 4762/318/7.1/3.6、
编号 YS-58、年份 2031、日期 2031-09-25（不沿用 浩辰光电/澄远能源/北辰物流/岚桥智造/云帆文创 及其数值）。

预期全部先于运行按公开产品契约写明（不按产品实际行为倒推）：
- R8 核心：证据仅“毛利2031财年测算/毛利2031 财年预算”年份形态、无毛利取值
  → 模型前拒答 not_found / UNSUPPORTED_FINANCIAL_METRIC 文案、sources=[]、chat=0；
  覆盖 legacy 模型前支持闸与 RAG record+enumerate 两条实际消费路径；
- 正例保持：无连接词/三种负号/全半角括号单位/千分位回显/百分之/单独倍率/财年在前取值在后 → 可答；
- R1—R6 切片不回归：年度/-日期//日期/年月拒答、组内双向误绑/单位倍率/空绑定拒绝、真同义可答、P-R1 前提值；
- 错误/trace/固定子因/隔离/幂等契约保持。

残留形态探测（任务书 V3 预设情形，披露≠豁免）：本轮 R8 为红例驱动最小修复，仅覆盖“财年”紧随。
“财政年度”是标准会计年份术语；证据仅“毛利2031财政年度测算”同样无毛利取值，按公开契约应模型前拒答。
下方 test_rv2_*_residual_* 按契约写明拒答预期；若产品放行即新产品接口层红例（保留失败证据，按 I5 交新返工项，
本复验不自行改产品、不预设更长黑名单要求）。

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
from mktkb import copy as copy_module  # noqa: E402
from mktkb.auth.service import create_account  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from mktkb.providers.types import ModelTimeout  # noqa: E402
from mktkb.rag.query import (  # noqa: E402
    metric_binding_values,
    metric_value_bindings,
    texts_support_financial_metric,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

COMPANY = "澜庭生物"
TWO_METRIC = "澜庭生物 2031 年一季度经营数据：营业收入 4762 万元，净利润 318 万元。"
NET_PROFIT_Q = "澜庭生物 2031 年一季度净利润是多少？"
GROSS_Q = "澜庭生物 2031 年一季度毛利是多少？"
REVENUE_Q = "澜庭生物 2031 年一季度营业收入是多少？"
RATE_Q = "澜庭生物 2031 年一季度毛利率是多少？"
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
    db = app.state.db.session()
    try:
        create_account(
            db, username="employee2", password="EmployeePass-2",
            display_name="复验员工二", role="employee", rounds=4,
        )
    finally:
        db.close()
    employee2 = _session(app, "employee2", "EmployeePass-2")
    return SimpleNamespace(
        app=app, admin=admin, employee=employee, employee2=employee2,
        model=chat_model, tmp_path=tmp_path,
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
def rv2_env(settings, chat_model, tmp_path: Path):
    env = _make_env(settings, chat_model, tmp_path, trace=False)
    try:
        yield env
    finally:
        _teardown(env)


@pytest.fixture
def rv2_trace_env(settings, chat_model, tmp_path: Path):
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


def _post(session, conversation_id: str, question: str, request_id: str | None = None):
    return session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": request_id or str(uuid.uuid4()), "question": question},
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


def _span_attrs(spans, name: str) -> dict:
    for span in spans:
        if span.name == name:
            return json.loads(span.attributes_json or "{}")
    return {}


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

def test_rv2_unit_fiscal_year_not_value() -> None:
    """R8 单元：财年形态（含空白变体）是年份形态，不构成指标支持/绑定。"""
    for text in ("毛利2031财年测算尚待复核", "毛利2031 财年预算仍在编制"):
        assert not texts_support_financial_metric("毛利", [text]), text
        assert metric_value_bindings(text, "毛利") == set(), text
    assert "毛利" not in metric_binding_values("毛利2031财年测算尚待复核")


def test_rv2_unit_date_forms_rejected() -> None:
    """R1 单元：年度/-日期//日期/年月形态均不构成指标支持。"""
    for text in (
        "毛利2031年度预算尚在编制",
        "毛利2031-09-25 巡检",
        "毛利2031/09/25 盘点",
        "毛利2031年9月复盘",
    ):
        assert not texts_support_financial_metric("毛利", [text]), text


def test_rv2_unit_legal_forms_supported() -> None:
    """正例单元：无连接词/三种负号/全半角括号单位/百分比/百分之 均支持。"""
    for metric, text in (
        ("毛利", "毛利4762万元"),
        ("净利润", "净利润为 -318 万元"),
        ("净利润", "净利润为 −318 万元"),
        ("净利润", "净利润为负318万元"),
        ("毛利", "毛利（万元）：4762"),
        ("毛利", "毛利(万元):4762"),
        ("毛利率", "毛利率为 7.1%"),
        ("毛利率", "毛利率为百分之7.1"),
    ):
        assert texts_support_financial_metric(metric, [text]), text


def test_rv2_unit_thousands_binding_complete() -> None:
    """O3 单元：千分位绑定核心完整（4762，不是 4）；年份不构成绑定。"""
    assert metric_value_bindings("营业收入为 4,762 万元", "营业收入") == {"4762"}
    assert metric_binding_values("营业收入为 4,762 万元")["营收"] == {("4762", "万", "元")}
    assert metric_value_bindings("毛利2031年度预算尚在编制", "毛利") == set()


# ---------------------------------------------------------------- R8：财年形态（legacy 模型前支持闸）

def test_rv2_m1_fiscal_year_refuses(rv2_env) -> None:
    """R8 核心：证据仅“毛利2031财年测算”年份形态、无毛利取值 → 模型前拒答，chat=0。"""
    _publish(rv2_env, "rv2_fy.docx", paragraphs=[
        "澜庭生物经营简报：毛利2031财年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


def test_rv2_m1_fiscal_year_with_space_refuses(rv2_env) -> None:
    """R8 核心空白变体：“毛利2031 财年预算”同样不是取值 → 模型前拒答，chat=0。"""
    _publish(rv2_env, "rv2_fy_space.docx", paragraphs=[
        "澜庭生物经营简报：毛利2031 财年预算仍在编制，未形成对外数值。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


def test_rv2_m1_fiscal_year_before_metric_answers(rv2_env) -> None:
    """R8 正例约束：财年在前、取值在后“2031财年毛利为 4762 万元” → 不得误拒，正常可答。"""
    _publish(rv2_env, "rv2_fy_ok.docx", paragraphs=[
        "澜庭生物2031财年毛利为 4762 万元。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_answered(rv2_env, answer, "4762", calls_before)


def test_rv2_m1_year_suffix_refuses(rv2_env) -> None:
    """R1 切片：年度紧随“毛利2031年度预算” → 模型前拒答。"""
    _publish(rv2_env, "rv2_year.docx", paragraphs=[
        "澜庭生物经营简报：毛利2031年度预算尚在编制，未形成对外数值。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


def test_rv2_m1_dash_date_refuses(rv2_env) -> None:
    """R1 切片：-日期紧随“毛利2031-09-25 巡检” → 模型前拒答。"""
    _publish(rv2_env, "rv2_dash.docx", paragraphs=[
        "澜庭生物周报：毛利2031-09-25 巡检记录已归档，数值待财务确认。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


def test_rv2_m1_slash_date_refuses(rv2_env) -> None:
    """R1 切片：/日期“毛利2031/09/25 盘点” → 模型前拒答。"""
    _publish(rv2_env, "rv2_slash.docx", paragraphs=[
        "澜庭生物周报：毛利2031/09/25 盘点记录已归档，数值待财务确认。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


def test_rv2_m1_year_month_refuses(rv2_env) -> None:
    """R1 切片：年月“毛利2031年9月复盘” → 模型前拒答。"""
    _publish(rv2_env, "rv2_ym.docx", paragraphs=[
        "澜庭生物月报：毛利2031年9月复盘会议已召开，数值待财务确认。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


def test_rv2_m1_no_connector_answers(rv2_env) -> None:
    """正例约束：合法无连接词“毛利4762万元”不得回归为拒答，且实际调用模型。"""
    _publish(rv2_env, "rv2_plain.docx", paragraphs=[
        "澜庭生物一季度毛利4762万元。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物一季度的毛利是多少？")
    _assert_answered(rv2_env, answer, "4762", calls_before)


def test_rv2_m1_irrelevant_id_date_refuses(rv2_env) -> None:
    """M1 原机制控制：仅无关编号/日期邻近毛利词 → 仍须模型前拒答。"""
    _publish(rv2_env, "rv2_id.docx", paragraphs=[
        "澜庭生物运营周报：门店编号 YS-58 于 2031-09-25 提交毛利影响测算，等待财务复核。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物本季度的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


# ---------------------------------------------------------------- R2：三种负号（应可答）

def test_rv2_m1_negative_ascii_answers(rv2_env) -> None:
    """R2 切片：ASCII 负号亏损原值“-318 万元” → 正常可答。"""
    _publish(rv2_env, "rv2_neg_a.docx", paragraphs=[
        "澜庭生物 2031 年一季度净利润为 -318 万元。",
    ])
    answer = _ask(rv2_env.employee, NET_PROFIT_Q)
    _assert_answered(rv2_env, answer, "318")


def test_rv2_m1_negative_unicode_answers(rv2_env) -> None:
    """R2 切片：U+2212 负号“−318 万元” → 正常可答。"""
    _publish(rv2_env, "rv2_neg_u.docx", paragraphs=[
        "澜庭生物 2031 年一季度净利润为 −318 万元。",
    ])
    answer = _ask(rv2_env.employee, NET_PROFIT_Q)
    _assert_answered(rv2_env, answer, "318")


def test_rv2_m1_negative_cn_answers(rv2_env) -> None:
    """R2 切片：中文负号“负318万元” → 正常可答。"""
    _publish(rv2_env, "rv2_neg_c.docx", paragraphs=[
        "澜庭生物 2031 年一季度净利润为负318万元。",
    ])
    answer = _ask(rv2_env.employee, NET_PROFIT_Q)
    _assert_answered(rv2_env, answer, "318")


# ---------------------------------------------------------------- R3：括号单位（应可答）与非单位括号

def test_rv2_m1_paren_fullwidth_answers(rv2_env) -> None:
    """R3 切片：全角括号单位“毛利（万元）：4762” → 正常可答。"""
    _publish(rv2_env, "rv2_paren_f.docx", paragraphs=[
        "澜庭生物 2031 年一季度毛利（万元）：4762。",
    ])
    answer = _ask(rv2_env.employee, GROSS_Q)
    _assert_answered(rv2_env, answer, "4762")


def test_rv2_m1_paren_halfwidth_answers(rv2_env) -> None:
    """R3 切片：半角括号单位“毛利(万元):4762” → 正常可答。"""
    _publish(rv2_env, "rv2_paren_h.docx", paragraphs=[
        "澜庭生物 2031 年一季度毛利(万元):4762。",
    ])
    answer = _ask(rv2_env.employee, GROSS_Q)
    _assert_answered(rv2_env, answer, "4762")


def test_rv2_m1_paren_non_unit_no_support(rv2_env) -> None:
    """非单位括号内容“毛利（待复核）”无数值 → 不得制造误支持，模型前拒答。"""
    _publish(rv2_env, "rv2_paren_n.docx", paragraphs=[
        "澜庭生物通知：毛利（待复核）事项另行通知。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


# ---------------------------------------------------------------- O3：千分位回显（应可答）

def test_rv2_m1_thousands_echo_answers(rv2_env) -> None:
    """O3 切片：千分位原值回显“4,762” → 可答，绑定核心不得截断。"""
    _publish(rv2_env, "rv2_thousands.docx", paragraphs=[
        "澜庭生物 2031 年一季度营业收入为 4,762 万元。",
    ])
    answer = _ask(rv2_env.employee, REVENUE_Q)
    _assert_answered(rv2_env, answer, "762")


# ---------------------------------------------------------------- R4：空绑定绕过（拒绝）与缩写正例

def test_rv2_m2_omitted_name_rejected(rv2_env) -> None:
    """R4 切片：省略指标名“经营成果为 4762 万元”（营收值冒充净利润）→ 拒绝。"""
    _publish(rv2_env, "rv2_omit.docx", paragraphs=[TWO_METRIC])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度经营成果为 4762 万元。"
    answer = _ask(rv2_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv2_m2_abbrev_correct_answers(rv2_env) -> None:
    """R4 正例：真缩写“净利”取正确值 318 → 仍须可答。"""
    _publish(rv2_env, "rv2_abbr_ok.docx", paragraphs=[
        "澜庭生物 2031 年一季度净利润为 318 万元。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度净利为 318 万元。"
    answer = _ask(rv2_env.employee, NET_PROFIT_Q)
    _assert_answered(rv2_env, answer, "318")


# ---------------------------------------------------------------- R5：组内双向误绑 / 真同义

def test_rv2_m2_intra_gross_to_net_rejected(rv2_env) -> None:
    """R5 切片：毛利值 4762 说成净利润（利润组内误绑）→ 拒绝。"""
    _publish(rv2_env, "rv2_intra_gn.docx", paragraphs=[
        "澜庭生物 2031 年一季度毛利 4762 万元，净利润 318 万元。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度净利润为 4762 万元。"
    answer = _ask(rv2_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv2_m2_intra_net_to_gross_rejected(rv2_env) -> None:
    """R5 切片：反向组内误绑——净利润值 318 说成毛利 → 同样拒绝。"""
    _publish(rv2_env, "rv2_intra_ng.docx", paragraphs=[
        "澜庭生物 2031 年一季度毛利 4762 万元，净利润 318 万元。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度毛利为 318 万元。"
    answer = _ask(rv2_env.employee, GROSS_Q)
    _assert_m2_rejected(answer)


def test_rv2_m2_revenue_synonym_answers(rv2_env) -> None:
    """R5 正例：营业收入→营收 真同义改写取正确值 → 可答。"""
    _publish(rv2_env, "rv2_rev_syn.docx", paragraphs=[
        "澜庭生物 2031 年一季度营业收入为 4762 万元。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度营收为 4762 万元。"
    answer = _ask(rv2_env.employee, REVENUE_Q)
    _assert_answered(rv2_env, answer, "4762")


# ---------------------------------------------------------------- R6：单位/倍率

def test_rv2_m2_wan_to_yuan_rejected(rv2_env) -> None:
    """R6 切片：318 万元 → 318 元（倍率不符）→ 拒绝。"""
    _publish(rv2_env, "rv2_unit_y.docx", paragraphs=[
        "澜庭生物 2031 年一季度净利润为 318 万元。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度净利润为 318 元。"
    answer = _ask(rv2_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv2_m2_wan_to_yi_rejected(rv2_env) -> None:
    """R6 切片：4762 万元 → 4762 亿元（倍率不符）→ 拒绝。"""
    _publish(rv2_env, "rv2_unit_yi.docx", paragraphs=[
        "澜庭生物 2031 年一季度营业收入为 4762 万元。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度营业收入为 4762 亿元。"
    answer = _ask(rv2_env.employee, REVENUE_Q)
    _assert_m2_rejected(answer)


def test_rv2_m2_percent_cn_answers(rv2_env) -> None:
    """R6 归一正例：“百分之7.1” ≡ “7.1%” → 可答。"""
    _publish(rv2_env, "rv2_pct.docx", paragraphs=[
        "澜庭生物 2031 年一季度毛利率为 7.1%。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度毛利率为百分之7.1。"
    answer = _ask(rv2_env.employee, RATE_Q)
    _assert_answered(rv2_env, answer, "7.1")


def test_rv2_m2_bare_wan_answers(rv2_env) -> None:
    """R6 归一正例：单独倍率“4762万” ≡ “4762万元” → 可答。"""
    _publish(rv2_env, "rv2_bare_w.docx", paragraphs=[
        "澜庭生物 2031 年一季度营业收入为 4762 万元。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度营业收入为 4762万。"
    answer = _ask(rv2_env.employee, REVENUE_Q)
    _assert_answered(rv2_env, answer, "4762")


def test_rv2_m2_paren_unit_binding_answers(rv2_env) -> None:
    """R6 括号单位绑定正例：证据“毛利（万元）：4762”背书回答“毛利为 4762 万元”。"""
    _publish(rv2_env, "rv2_paren_bind.docx", paragraphs=[
        "澜庭生物 2031 年一季度毛利（万元）：4762。",
    ])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度毛利为 4762 万元。"
    answer = _ask(rv2_env.employee, GROSS_Q)
    _assert_answered(rv2_env, answer, "4762")


# ---------------------------------------------------------------- P-R1：问题前提值（已批准放宽）

def test_rv2_m2_p_r1_premise_answers(rv2_env) -> None:
    """P-R1 保持：问题前提值 318 逐字出现 → 复述可答，不得撤销。"""
    _publish(rv2_env, "rv2_premise.docx", paragraphs=[
        "澜庭生物 2031 年一季度净利润为 318 万元。",
    ])
    rv2_env.model.answer_text = "是的，澜庭生物 2031 年一季度净利润为 318 万元。"
    answer = _ask(rv2_env.employee, "澜庭生物 2031 年一季度净利润是 318 万元吗？")
    _assert_answered(rv2_env, answer, "318")


# ---------------------------------------------------------------- RAG record 消费路径（共享函数）

RV2_RECORD_HEADERS = ["门店", "物品", "位置"]


def test_rv2_m1_rag_record_fiscal_year_refuses(rv2_trace_env) -> None:
    """R8 核心（RAG record+enumerate）：记录行“毛利2031财年测算”年份形态
    → rag 路径模型前拒答，chat=0。"""
    _publish(rv2_trace_env, "rv2_rag_bad.xlsx", sheet=(RV2_RECORD_HEADERS, [
        ["东篱店", "桁架海报", "A区1号货架"],
        ["东篱店", "毛利2031财年测算", "编号YS-58"],
    ]))
    calls_before = len(rv2_trace_env.model.calls)
    response = _post(rv2_trace_env.employee, _new_conversation(rv2_trace_env.employee),
                     "列出东篱店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv2_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv2_trace_env.model.calls) == calls_before, rv2_trace_env.model.calls


def test_rv2_m1_rag_record_value_answers(rv2_trace_env) -> None:
    """RAG 正向控制：记录行确有毛利取值 → rag 路径正常枚举作答。"""
    _publish(rv2_trace_env, "rv2_rag_ok.xlsx", sheet=(RV2_RECORD_HEADERS, [
        ["东篱店", "桁架海报", "毛利 4762 万元"],
        ["东篱店", "灯箱片", "毛利 318 万元"],
    ]))
    response = _post(rv2_trace_env.employee, _new_conversation(rv2_trace_env.employee),
                     "列出东篱店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv2_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "answer", answer
    assert "4762" in answer["text"], answer["text"]


# ---------------------------------------------------------------- 残留形态探测（新红例候选，契约预期拒答）

def test_rv2_m1_residual_fiscal_year_full_form_refuses(rv2_env) -> None:
    """残留探测（legacy）：证据仅“毛利2031财政年度测算”——“财政年度”是标准会计年份术语，
    证据明确无毛利取值，按公开契约应模型前拒答 not_found/chat=0。
    本轮 R8 守卫仅覆盖“财年”紧随；若此形态放行即新产品接口层红例（R9 候选）。"""
    _publish(rv2_env, "rv2_residual_fy.docx", paragraphs=[
        "澜庭生物经营简报：毛利2031财政年度测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv2_env.model.calls)
    answer = _ask(rv2_env.employee, "澜庭生物的毛利是多少？")
    _assert_pre_model_refusal(rv2_env, answer, calls_before)


def test_rv2_m1_rag_record_residual_fiscal_year_refuses(rv2_trace_env) -> None:
    """残留探测（RAG record+enumerate）：记录行“毛利2031财政年度测算”年份形态
    → 契约预期 rag 路径模型前拒答 not_found/chat=0；若放行即新红例（R9 候选）。"""
    _publish(rv2_trace_env, "rv2_rag_residual.xlsx", sheet=(RV2_RECORD_HEADERS, [
        ["东篱店", "桁架海报", "A区1号货架"],
        ["东篱店", "毛利2031财政年度测算", "编号YS-58"],
    ]))
    calls_before = len(rv2_trace_env.model.calls)
    response = _post(rv2_trace_env.employee, _new_conversation(rv2_trace_env.employee),
                     "列出东篱店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv2_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv2_trace_env.model.calls) == calls_before, rv2_trace_env.model.calls


# ---------------------------------------------------------------- V5：错误契约 / 隔离 / 幂等

def test_rv2_error_contract_copy_trace_subreason(rv2_trace_env) -> None:
    """错误契约：公开文案=copy 模板、trace.error_code/reason=MODEL_OUTPUT_INVALID、
    固定子因 unknown 保全（新 raise 不带 failure_reason）。"""
    _publish(rv2_trace_env, "rv2_err.docx", paragraphs=[TWO_METRIC])
    rv2_trace_env.model.answer_text = "澜庭生物 2031 年一季度净利润为 4762 万元。"
    response = _post(rv2_trace_env.employee, _new_conversation(rv2_trace_env.employee), NET_PROFIT_Q)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    expected_text = copy_module.service_error_text("MODEL_OUTPUT_INVALID", retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(rv2_trace_env, response)
    assert getattr(trace, "error_code", None) == "MODEL_OUTPUT_INVALID", trace
    assert getattr(trace, "reason", None) == "MODEL_OUTPUT_INVALID", trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs


def test_rv2_provider_error_no_echo(rv2_trace_env) -> None:
    """provider 恶意异常文本零回显：稳定码 copy 文案，子因 unknown。"""
    _publish(rv2_trace_env, "rv2_provider.docx", paragraphs=[
        "澜庭生物 2031 年一季度毛利为 4762 万元。",
    ])
    rv2_trace_env.model.error = ModelTimeout("RV2-SECRET-NEVER-REAL sk-fake-777 D:/private/abc")
    response = _post(rv2_trace_env.employee, _new_conversation(rv2_trace_env.employee), GROSS_Q)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"], answer
    assert "RV2-SECRET" not in answer["text"], answer["text"]
    assert "sk-fake" not in answer["text"], answer["text"]
    expected_text = copy_module.service_error_text(answer["error_code"], retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(rv2_trace_env, response)
    assert getattr(trace, "error_code", None) == answer["error_code"], trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs


def test_rv2_isolation_between_users(rv2_trace_env) -> None:
    """跨用户隔离：employee 锁定东篱店后，employee2 全新会话枚举两店不串状态。"""
    _publish(rv2_trace_env, "rv2_iso.xlsx", sheet=(RV2_RECORD_HEADERS, [
        ["东篱店", "桁架海报", "A区1号货架"],
        ["北屿店", "灯箱片", "C区3号货架"],
    ]))
    conv1 = _new_conversation(rv2_trace_env.employee)
    r1 = _post(rv2_trace_env.employee, conv1, "列出东篱店所有物品")
    assert r1.status_code == 200 and r1.json()["kind"] == "answer", r1.text
    assert "北屿店" not in r1.json()["text"], r1.json()
    conv2 = _new_conversation(rv2_trace_env.employee2)
    r2 = _post(rv2_trace_env.employee2, conv2, "列出所有物品")
    assert r2.status_code == 200 and r2.json()["kind"] == "answer", r2.text
    assert "北屿店" in r2.json()["text"], r2.json()
    assert "东篱店" in r2.json()["text"], r2.json()


def test_rv2_idempotent_replay_no_extra_call(rv2_env) -> None:
    """幂等重放：同一 client_request_id 重放拒绝结果，模型调用数不增。"""
    _publish(rv2_env, "rv2_replay.docx", paragraphs=[TWO_METRIC])
    rv2_env.model.answer_text = "澜庭生物 2031 年一季度净利润为 4762 万元。"
    conversation = _new_conversation(rv2_env.employee)
    request_id = str(uuid.uuid4())
    first = _post(rv2_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert first.status_code == 200, first.text
    calls_after_first = len(rv2_env.model.calls)
    second = _post(rv2_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert second.status_code == 200, second.text
    assert second.json()["kind"] == first.json()["kind"], (first.json(), second.json())
    assert second.json()["error_code"] == first.json()["error_code"], (first.json(), second.json())
    assert len(rv2_env.model.calls) == calls_after_first, rv2_env.model.calls