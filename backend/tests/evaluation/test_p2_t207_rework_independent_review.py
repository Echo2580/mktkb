"""T207-R1 返工独立复验（V3/V4/V5）：全新主体合成正反例，走真实产品装配链。

复验者（全新上下文，非返工开发者、非首轮验收者）独立编写，不复用开发/首轮/返工测试模块。
主体/数值/布局均不同：公司“澄远能源”、门店“梧桐店/白沙店”、数值 8246/519/6.2/4.1、
编号 CY-23、年份 2028、日期 2028-03-14。

预期全部先于运行按公开产品契约写明（不按产品实际行为倒推）：
- 无依据（指标词后仅年份/日期/编号形态）→ 模型前拒答 not_found / UNSUPPORTED_FINANCIAL_METRIC 文案、chat=0；
- 有直接证据（负数/括号单位/千分位/无连接词/百分之/单独倍率）→ 正常可答；
- 指标题错误取值（省略指标名/缩写错值/组内双向误绑/单位倍率不符/利润率组身份互换）→ MODEL_OUTPUT_INVALID；
- 真同义取正确值、多指标、日期/编号回显、P-R1 前提值 → 保持可答；
- 报告披露口径核对（裸值拒答、泛称边界、O3 token 闸耦合）单独标注，披露≠豁免：
  “2028财年”残留按公开契约预期拒答，若放行即产品红例。

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

COMPANY = "澄远能源"
TWO_METRIC = "澄远能源 2028 年一季度经营数据：营业收入 8246 万元，净利润 519 万元。"
NET_PROFIT_Q = "澄远能源 2028 年一季度净利润是多少？"
GROSS_Q = "澄远能源 2028 年一季度毛利是多少？"
REVENUE_Q = "澄远能源 2028 年一季度营业收入是多少？"
RATE_Q = "澄远能源 2028 年一季度毛利率是多少？"
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
def rv_env(settings, chat_model, tmp_path: Path):
    env = _make_env(settings, chat_model, tmp_path, trace=False)
    try:
        yield env
    finally:
        _teardown(env)


@pytest.fixture
def rv_trace_env(settings, chat_model, tmp_path: Path):
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


# ---------------------------------------------------------------- R1：年份/日期紧随（应拒答）+ 残留披露核对

def test_rv_m1_year_suffix_refuses(rv_env) -> None:
    """契约：证据仅“毛利2028年度预算”年份紧随、无毛利取值 → 模型前拒答。"""
    _publish(rv_env, "rv_year.docx", paragraphs=[
        "澄远能源经营简报：毛利2028年度预算尚在编制，未形成对外数值。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


def test_rv_m1_dash_date_refuses(rv_env) -> None:
    """契约：证据仅“毛利2028-03-14 巡检”日期紧随 → 模型前拒答。"""
    _publish(rv_env, "rv_dash.docx", paragraphs=[
        "澄远能源周报：毛利2028-03-14 巡检记录已归档，数值待财务确认。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


def test_rv_m1_slash_date_refuses(rv_env) -> None:
    """契约：斜杠日期“毛利2028/03/14 盘点”同样不是取值 → 模型前拒答。"""
    _publish(rv_env, "rv_slash.docx", paragraphs=[
        "澄远能源周报：毛利2028/03/14 盘点记录已归档，数值待财务确认。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


def test_rv_m1_year_month_refuses(rv_env) -> None:
    """契约：年月形态“毛利2028年3月复盘”不是取值 → 模型前拒答。"""
    _publish(rv_env, "rv_ym.docx", paragraphs=[
        "澄远能源月报：毛利2028年3月复盘会议已召开，数值待财务确认。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


def test_rv_m1_fiscal_year_residual_contract(rv_env) -> None:
    """披露残留按公开契约归类（披露≠豁免）：证据仅“毛利2028财年测算”仍无毛利取值，
    契约预期模型前拒答。返工报告 §5 披露该形态未覆盖；若放行即残留误放行红例。"""
    _publish(rv_env, "rv_fy.docx", paragraphs=[
        "澄远能源经营简报：毛利2028财年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


def test_rv_m1_no_connector_plain_answers(rv_env) -> None:
    """R1 正例约束：合法无连接词“毛利8246万元”不得回归为拒答，且实际调用模型。"""
    _publish(rv_env, "rv_plain.docx", paragraphs=[
        "澄远能源一季度毛利8246万元。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源一季度的毛利是多少？")
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]
    assert answer["sources"], answer
    assert len(rv_env.model.calls) > calls_before, rv_env.model.calls


def test_rv_m1_irrelevant_id_date_refuses(rv_env) -> None:
    """M1 原机制红例控制：仅无关编号/日期邻近毛利词 → 仍须模型前拒答。"""
    _publish(rv_env, "rv_id.docx", paragraphs=[
        "澄远能源运营周报：门店编号 CY-23 于 2028-03-14 提交毛利影响测算，等待财务复核。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源本季度的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


# ---------------------------------------------------------------- R2：三种负号（应可答）

def test_rv_m1_negative_ascii_answers(rv_env) -> None:
    """契约：ASCII 负号亏损原值“-519 万元” → 正常可答。"""
    _publish(rv_env, "rv_neg_a.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 -519 万元。",
    ])
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "519" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m1_negative_unicode_answers(rv_env) -> None:
    """契约：U+2212 负号“−519 万元” → 正常可答。"""
    _publish(rv_env, "rv_neg_u.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 −519 万元。",
    ])
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "519" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m1_negative_cn_answers(rv_env) -> None:
    """契约：中文负号“负519万元” → 正常可答。"""
    _publish(rv_env, "rv_neg_c.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为负519万元。",
    ])
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "519" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- R3：括号单位（应可答）与非单位括号（不得误支持）

def test_rv_m1_paren_fullwidth_answers(rv_env) -> None:
    """契约：全角括号单位“毛利（万元）：8246” → 正常可答。"""
    _publish(rv_env, "rv_paren_f.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利（万元）：8246。",
    ])
    answer = _ask(rv_env.employee, GROSS_Q)
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m1_paren_halfwidth_answers(rv_env) -> None:
    """契约：半角括号单位“毛利(万元):8246” → 正常可答。"""
    _publish(rv_env, "rv_paren_h.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利(万元):8246。",
    ])
    answer = _ask(rv_env.employee, GROSS_Q)
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m1_paren_non_unit_no_support(rv_env) -> None:
    """契约：非单位括号内容“毛利（待复核）”无数值 → 不得制造误支持，模型前拒答。"""
    _publish(rv_env, "rv_paren_n.docx", paragraphs=[
        "澄远能源通知：毛利（待复核）事项另行通知。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


def test_rv_m1_paren_digits_no_support(rv_env) -> None:
    """契约：括号内编号数字“毛利（编号CY-23）”不是毛利取值 → 模型前拒答。"""
    _publish(rv_env, "rv_paren_d.docx", paragraphs=[
        "澄远能源通知：毛利（编号CY-23）档案已移交财务部。",
    ])
    calls_before = len(rv_env.model.calls)
    answer = _ask(rv_env.employee, "澄远能源的毛利是多少？")
    _assert_pre_model_refusal(rv_env, answer, calls_before)


# ---------------------------------------------------------------- R4：空绑定绕过（应拒绝）与正例

def test_rv_m2_omitted_name_rejected(rv_env) -> None:
    """契约：省略指标名“经营成果为 8246 万元”（营收值冒充净利润）→ 拒绝，不得空绑定绕过。"""
    _publish(rv_env, "rv_omit.docx", paragraphs=[TWO_METRIC])
    rv_env.model.answer_text = "澄远能源 2028 年一季度经营成果为 8246 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_abbrev_jingli_wrong_rejected(rv_env) -> None:
    """契约：缩写“净利为 8246 万元”取营收值 → 拒绝。"""
    _publish(rv_env, "rv_abbr_j.docx", paragraphs=[TWO_METRIC])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净利为 8246 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_abbrev_chunli_wrong_rejected(rv_env) -> None:
    """契约：缩写“纯利为 8246 万元”取营收值 → 拒绝。"""
    _publish(rv_env, "rv_abbr_c.docx", paragraphs=[TWO_METRIC])
    rv_env.model.answer_text = "澄远能源 2028 年一季度纯利为 8246 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_unknown_abbrev_wrong_rejected(rv_env) -> None:
    """契约：词表外缩写“净赚为 8246 万元”取营收值 → 未归属取值仍须拒绝。"""
    _publish(rv_env, "rv_abbr_x.docx", paragraphs=[TWO_METRIC])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净赚为 8246 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_abbrev_correct_answers(rv_env) -> None:
    """R4 正例约束：真缩写“净利”取正确值 519 → 仍须可答。"""
    _publish(rv_env, "rv_abbr_ok.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 519 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净利为 519 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "519" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_date_id_echo_answers(rv_env) -> None:
    """R4 正例约束：回答回显编号/日期等非指标数字 + 正确值 → 不得误拒。"""
    _publish(rv_env, "rv_echo.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 519 万元，报告编号 CY-23，日期 2028-03-14。",
    ])
    rv_env.model.answer_text = (
        "澄远能源 2028 年一季度净利润为 519 万元，报告编号 CY-23，日期 2028-03-14。"
    )
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "519" in answer["text"], answer["text"]
    assert "CY-23" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_p_r1_premise_answers(rv_env) -> None:
    """P-R1 已批准放宽：问题前提值 519 逐字出现 → 复述可答，不得撤销。"""
    _publish(rv_env, "rv_premise.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 519 万元。",
    ])
    rv_env.model.answer_text = "是的，澄远能源 2028 年一季度净利润为 519 万元。"
    answer = _ask(rv_env.employee, "澄远能源 2028 年一季度净利润是 519 万元吗？")
    assert answer["kind"] == "answer", answer
    assert "519" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- R5：组内双向误绑 / 真同义 / 利润率组身份

def test_rv_m2_intra_gross_to_net_rejected(rv_env) -> None:
    """契约：毛利值 8246 说成净利润（利润组内误绑）→ 拒绝。"""
    _publish(rv_env, "rv_intra_gn.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利 8246 万元，净利润 519 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净利润为 8246 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_intra_net_to_gross_rejected(rv_env) -> None:
    """契约：反向组内误绑——净利润值 519 说成毛利 → 同样拒绝。"""
    _publish(rv_env, "rv_intra_ng.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利 8246 万元，净利润 519 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度毛利为 519 万元。"
    answer = _ask(rv_env.employee, GROSS_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_revenue_synonym_answers(rv_env) -> None:
    """R5 正例约束：营业收入→营收 真同义改写取正确值 → 可答。"""
    _publish(rv_env, "rv_rev_syn.docx", paragraphs=[
        "澄远能源 2028 年一季度营业收入为 8246 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度营收为 8246 万元。"
    answer = _ask(rv_env.employee, REVENUE_Q)
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_turnover_synonym_answers(rv_env) -> None:
    """R5 正例约束：营业收入→营业额 真同义改写取正确值 → 可答。"""
    _publish(rv_env, "rv_turn_syn.docx", paragraphs=[
        "澄远能源 2028 年一季度营业收入为 8246 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度营业额为 8246 万元。"
    answer = _ask(rv_env.employee, REVENUE_Q)
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_rate_identity_rejected(rv_env) -> None:
    """契约：利润率组内身份独立——净利率值 4.1% 说成毛利率 → 拒绝。"""
    _publish(rv_env, "rv_rate.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利率为 6.2%，净利率为 4.1%。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度毛利率为 4.1%。"
    answer = _ask(rv_env.employee, RATE_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_rate_correct_answers(rv_env) -> None:
    """R5 正例约束：毛利率取本指标原值 6.2% → 可答。"""
    _publish(rv_env, "rv_rate_ok.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利率为 6.2%，净利率为 4.1%。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度毛利率为 6.2%。"
    answer = _ask(rv_env.employee, RATE_Q)
    assert answer["kind"] == "answer", answer
    assert "6.2" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_generic_echo_answers(rv_env) -> None:
    """披露口径核对（返工 §5 泛称边界）：证据“净利润 519”可背书泛称复述“利润为 519”。"""
    _publish(rv_env, "rv_generic.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 519 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度利润为 519 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "519" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_generic_not_back_specific_rejected(rv_env) -> None:
    """披露口径核对（返工 §5 泛称边界）：证据仅泛称“利润 519”不背书特指“净利润为 519”。"""
    _publish(rv_env, "rv_generic2.docx", paragraphs=[
        "澄远能源 2028 年一季度利润为 519 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净利润为 519 万元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


# ---------------------------------------------------------------- R6：单位/倍率

def test_rv_m2_wan_to_yuan_rejected(rv_env) -> None:
    """契约：519 万元 → 519 元（倍率不符）→ 拒绝。"""
    _publish(rv_env, "rv_unit_y.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 519 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净利润为 519 元。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_wan_to_yi_rejected(rv_env) -> None:
    """契约：8246 万元 → 8246 亿元（倍率不符）→ 拒绝。"""
    _publish(rv_env, "rv_unit_yi.docx", paragraphs=[
        "澄远能源 2028 年一季度营业收入为 8246 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度营业收入为 8246 亿元。"
    answer = _ask(rv_env.employee, REVENUE_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_percent_cn_answers(rv_env) -> None:
    """R6 归一正例：“百分之6.2” ≡ “6.2%” → 可答。"""
    _publish(rv_env, "rv_pct.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利率为 6.2%。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度毛利率为百分之6.2。"
    answer = _ask(rv_env.employee, RATE_Q)
    assert answer["kind"] == "answer", answer
    assert "6.2" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_bare_wan_answers(rv_env) -> None:
    """R6 归一正例：单独倍率“8246万” ≡ “8246万元” → 可答。"""
    _publish(rv_env, "rv_bare_w.docx", paragraphs=[
        "澄远能源 2028 年一季度营业收入为 8246 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度营业收入为 8246万。"
    answer = _ask(rv_env.employee, REVENUE_Q)
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_bare_value_rejected(rv_env) -> None:
    """披露口径核对（返工 §5 单位签名严格口径）：证据“519 万元”、回答裸“519”按不匹配拒绝。
    无冻结正例覆盖省略单位；若未来认定合法需主人裁决，此处仅核对与披露一致。"""
    _publish(rv_env, "rv_bare_v.docx", paragraphs=[
        "澄远能源 2028 年一季度净利润为 519 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净利润为 519。"
    answer = _ask(rv_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv_m2_paren_unit_binding_answers(rv_env) -> None:
    """R6 括号单位绑定正例：证据“毛利（万元）：8246”背书回答“毛利为 8246 万元”。"""
    _publish(rv_env, "rv_paren_bind.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利（万元）：8246。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度毛利为 8246 万元。"
    answer = _ask(rv_env.employee, GROSS_Q)
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- O3：千分位完整性与 token 闸耦合（待裁决口径核对）

def test_rv_m1_thousands_echo_answers(rv_env) -> None:
    """O3 正例：千分位原值回显“8,246” → 可答，绑定核心不得截断为前导数字。"""
    _publish(rv_env, "rv_thousands.docx", paragraphs=[
        "澄远能源 2028 年一季度营业收入为 8,246 万元。",
    ])
    answer = _ask(rv_env.employee, REVENUE_Q)
    assert answer["kind"] == "answer", answer
    assert "246" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_rv_m2_thousands_normalized_token_gate(rv_env) -> None:
    """待裁决项核对（非新缺陷）：回答把“8,246”规范化为“8246”仍被既有 _value_tokens
    逗号拆分闸拦截（返工 §2 O3 披露口径）。预期 service_error/MODEL_OUTPUT_INVALID；
    若放行则说明 token 闸被改动，与披露不符。"""
    _publish(rv_env, "rv_norm.docx", paragraphs=[
        "澄远能源 2028 年一季度营业收入为 8,246 万元。",
    ])
    rv_env.model.answer_text = "澄远能源 2028 年一季度营业收入为 8246 万元。"
    answer = _ask(rv_env.employee, REVENUE_Q)
    _assert_m2_rejected(answer)


def test_rv_unit_bindings_thousands_complete() -> None:
    """O3 单元口径：千分位绑定核心完整（8246，不是 8）；年份不构成绑定。"""
    assert metric_value_bindings("营业收入为 8,246 万元", "营业收入") == {"8246"}
    assert metric_value_bindings("毛利2028年度预算尚在编制", "毛利") == set()
    assert metric_binding_values("营业收入为 8,246 万元")["营收"] == {("8246", "万", "元")}


def test_rv_unit_value_slot_date_forms() -> None:
    """R1 单元口径：年度/-日期//日期/年月形态均不构成指标支持。"""
    for text in (
        "毛利2028年度预算尚在编制",
        "毛利2028-03-14 巡检",
        "毛利2028/03/14 盘点",
        "毛利2028年3月复盘",
    ):
        assert not texts_support_financial_metric("毛利", [text]), text


def test_rv_unit_value_slot_legal_forms() -> None:
    """R1/R2/R3 单元正例：无连接词/三种负号/全半角括号/百分之 均支持。"""
    for metric, text in (
        ("毛利", "毛利8246万元"),
        ("净利润", "净利润为 -519 万元"),
        ("净利润", "净利润为 −519 万元"),
        ("净利润", "净利润为负519万元"),
        ("毛利", "毛利（万元）：8246"),
        ("毛利", "毛利(万元):8246"),
        ("毛利率", "毛利率为 6.2%"),
        ("毛利率", "毛利率为百分之6.2"),
    ):
        assert texts_support_financial_metric(metric, [text]), text


# ---------------------------------------------------------------- RAG record 消费路径（共享函数）

RV_RECORD_HEADERS = ["门店", "物品", "位置"]


def test_rv_m1_rag_record_year_refuses(rv_trace_env) -> None:
    """RAG record+enumerate：记录行“毛利2028年度测算”年份紧随 → rag 路径拒答，chat=0。"""
    _publish(rv_trace_env, "rv_rag_bad.xlsx", sheet=(RV_RECORD_HEADERS, [
        ["梧桐店", "桁架海报", "A区1号货架"],
        ["梧桐店", "毛利2028年度测算", "编号CY-23"],
    ]))
    calls_before = len(rv_trace_env.model.calls)
    response = _post(rv_trace_env.employee, _new_conversation(rv_trace_env.employee),
                     "列出梧桐店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv_trace_env.model.calls) == calls_before, rv_trace_env.model.calls


def test_rv_m1_rag_record_value_answers(rv_trace_env) -> None:
    """RAG 正向控制：记录行确有毛利取值 → rag 路径正常枚举作答。"""
    _publish(rv_trace_env, "rv_rag_ok.xlsx", sheet=(RV_RECORD_HEADERS, [
        ["梧桐店", "桁架海报", "毛利 8246 万元"],
        ["梧桐店", "灯箱片", "毛利 519 万元"],
    ]))
    response = _post(rv_trace_env.employee, _new_conversation(rv_trace_env.employee),
                     "列出梧桐店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "answer", answer
    assert "8246" in answer["text"], answer["text"]


# ---------------------------------------------------------------- V4/R7：路由探针（政策追问可达 RAG 正文）

def test_rv_route_single_turn_metric_legacy(rv_trace_env) -> None:
    """单轮直接指标题走 legacy（分流基线）。"""
    _publish(rv_trace_env, "rv_route.docx", paragraphs=[
        "梧桐店毛利审批流程须按财务制度执行，测算编号 CY-23，日期 2028-03-14。",
    ])
    response = _post(rv_trace_env.employee, _new_conversation(rv_trace_env.employee),
                     "澄远能源的毛利是多少？")
    assert response.status_code == 200, response.text
    trace, _ = _trace_of(rv_trace_env, response)
    assert trace.path == "legacy", trace.path


def test_rv_route_policy_followup_single_turn(rv_trace_env) -> None:
    """R7 复核：单轮政策追问含指标词 → rag + POLICY_FOLLOWUP；证据无取值 →
    RAG 正文计划上 UNSUPPORTED_FINANCIAL_METRIC 拒答。"""
    _publish(rv_trace_env, "rv_records.xlsx", sheet=(RV_RECORD_HEADERS, [
        ["梧桐店", "桁架海报", "A区1号货架"],
        ["梧桐店", "灯箱片", "B区2号货架"],
    ]))
    _publish(rv_trace_env, "rv_policy.docx", paragraphs=[
        "梧桐店毛利审批流程须按财务制度执行，测算编号 CY-23，日期 2028-03-14。",
    ])
    response = _post(rv_trace_env.employee, _new_conversation(rv_trace_env.employee),
                     "梧桐店那个毛利审批流程是什么？")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, spans = _trace_of(rv_trace_env, response)
    parse_attrs = _span_attrs(spans, "parse")
    assert trace.path == "rag", (trace.path, parse_attrs, answer)
    assert parse_attrs.get("reason") == "POLICY_FOLLOWUP", parse_attrs
    assert answer["kind"] == "not_found", answer
    assert getattr(trace, "reason", None) == "UNSUPPORTED_FINANCIAL_METRIC", trace


def test_rv_route_multiturn_policy_extractive(rv_trace_env) -> None:
    """R7 复核：多轮政策追问 → rag + extractive_offline，即 validate_document_text 真实执行。"""
    _publish(rv_trace_env, "rv_records2.xlsx", sheet=(RV_RECORD_HEADERS, [
        ["梧桐店", "桁架海报", "A区1号货架"],
        ["梧桐店", "灯箱片", "B区2号货架"],
    ]))
    _publish(rv_trace_env, "rv_policy2.docx", paragraphs=[
        "梧桐店毛利审批流程要求毛利 8246 万元的项目按财务制度复核。",
    ])
    conversation = _new_conversation(rv_trace_env.employee)
    first = _post(rv_trace_env.employee, conversation, "列出梧桐店所有物品")
    assert first.status_code == 200, first.text
    assert first.json()["kind"] == "answer", first.json()
    trace1, _ = _trace_of(rv_trace_env, first)
    assert trace1.path == "rag", trace1.path
    second = _post(rv_trace_env.employee, conversation, "梧桐店那个毛利审批流程是什么？")
    assert second.status_code == 200, second.text
    answer = second.json()
    trace, spans = _trace_of(rv_trace_env, second)
    parse_attrs = _span_attrs(spans, "parse")
    answer_attrs = _span_attrs(spans, "answer")
    assert trace.path == "rag", (trace.path, parse_attrs, answer)
    assert parse_attrs.get("reason") == "POLICY_FOLLOWUP", parse_attrs
    assert answer["kind"] == "answer", answer
    assert answer_attrs.get("answer_source") == "extractive_offline", answer_attrs


def test_rv_route_policy_topic_followup(rv_trace_env) -> None:
    """R7 复核：POLICY_TOPIC_FOLLOWUP 分支同样 rag + 正文直答 extractive_offline。"""
    _publish(rv_trace_env, "rv_records3.xlsx", sheet=(RV_RECORD_HEADERS, [
        ["梧桐店", "桁架海报", "A区1号货架"],
        ["梧桐店", "灯箱片", "B区2号货架"],
    ]))
    _publish(rv_trace_env, "rv_policy3.docx", paragraphs=[
        "梧桐店毛利报销规则要求毛利 8246 万元以上的报销附财务复核单。",
    ])
    response = _post(rv_trace_env.employee, _new_conversation(rv_trace_env.employee),
                     "梧桐店那个毛利报销规则是什么？")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, spans = _trace_of(rv_trace_env, response)
    parse_attrs = _span_attrs(spans, "parse")
    answer_attrs = _span_attrs(spans, "answer")
    assert trace.path == "rag", (trace.path, parse_attrs, answer)
    assert parse_attrs.get("reason") == "POLICY_TOPIC_FOLLOWUP", parse_attrs
    assert answer["kind"] == "answer", answer
    assert answer_attrs.get("answer_source") == "extractive_offline", answer_attrs


# ---------------------------------------------------------------- V5：错误契约 / 隔离 / 幂等

def test_rv_error_contract_copy_trace_subreason(rv_trace_env) -> None:
    """错误契约：公开文案=copy 模板、trace.error_code/reason=MODEL_OUTPUT_INVALID、
    固定子因 unknown 保全（新 raise 不带 failure_reason）。"""
    _publish(rv_trace_env, "rv_err.docx", paragraphs=[TWO_METRIC])
    rv_trace_env.model.answer_text = "澄远能源 2028 年一季度净利润为 8246 万元。"
    response = _post(rv_trace_env.employee, _new_conversation(rv_trace_env.employee), NET_PROFIT_Q)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    expected_text = copy_module.service_error_text("MODEL_OUTPUT_INVALID", retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(rv_trace_env, response)
    assert getattr(trace, "error_code", None) == "MODEL_OUTPUT_INVALID", trace
    assert getattr(trace, "reason", None) == "MODEL_OUTPUT_INVALID", trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs


def test_rv_provider_error_no_echo(rv_trace_env) -> None:
    """provider 恶意异常文本零回显：稳定码 copy 文案，子因 unknown。"""
    _publish(rv_trace_env, "rv_provider.docx", paragraphs=[
        "澄远能源 2028 年一季度毛利为 8246 万元。",
    ])
    rv_trace_env.model.error = ModelTimeout("RV-SECRET-NEVER-REAL sk-fake-999 D:/private/xyz")
    response = _post(rv_trace_env.employee, _new_conversation(rv_trace_env.employee), GROSS_Q)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"], answer
    assert "RV-SECRET" not in answer["text"], answer["text"]
    assert "sk-fake" not in answer["text"], answer["text"]
    expected_text = copy_module.service_error_text(answer["error_code"], retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(rv_trace_env, response)
    assert getattr(trace, "error_code", None) == answer["error_code"], trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs


def test_rv_isolation_between_users(rv_trace_env) -> None:
    """跨用户隔离：employee 锁定梧桐店后，employee2 全新会话枚举两店不串状态。"""
    _publish(rv_trace_env, "rv_iso.xlsx", sheet=(RV_RECORD_HEADERS, [
        ["梧桐店", "桁架海报", "A区1号货架"],
        ["白沙店", "灯箱片", "C区3号货架"],
    ]))
    conv1 = _new_conversation(rv_trace_env.employee)
    r1 = _post(rv_trace_env.employee, conv1, "列出梧桐店所有物品")
    assert r1.status_code == 200 and r1.json()["kind"] == "answer", r1.text
    assert "白沙店" not in r1.json()["text"], r1.json()
    conv2 = _new_conversation(rv_trace_env.employee2)
    r2 = _post(rv_trace_env.employee2, conv2, "列出所有物品")
    assert r2.status_code == 200 and r2.json()["kind"] == "answer", r2.text
    assert "白沙店" in r2.json()["text"], r2.json()
    assert "梧桐店" in r2.json()["text"], r2.json()


def test_rv_idempotent_replay_no_extra_call(rv_env) -> None:
    """幂等重放：同一 client_request_id 重放拒绝结果，模型调用数不增。"""
    _publish(rv_env, "rv_replay.docx", paragraphs=[TWO_METRIC])
    rv_env.model.answer_text = "澄远能源 2028 年一季度净利润为 8246 万元。"
    conversation = _new_conversation(rv_env.employee)
    request_id = str(uuid.uuid4())
    first = _post(rv_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert first.status_code == 200, first.text
    calls_after_first = len(rv_env.model.calls)
    second = _post(rv_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert second.status_code == 200, second.text
    assert second.json()["kind"] == first.json()["kind"], (first.json(), second.json())
    assert second.json()["error_code"] == first.json()["error_code"], (first.json(), second.json())
    assert len(rv_env.model.calls) == calls_after_first, rv_env.model.calls