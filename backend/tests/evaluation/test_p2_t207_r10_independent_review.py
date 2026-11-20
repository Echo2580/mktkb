"""T207-R1 第四轮返工（R10）独立复验：全新主体合成正反例，走真实产品装配链。

复验者（全新上下文，非首轮/返工 R1/R8/R9/R10 开发者、非任何验收/复验者）独立编写，
不复用既有测试模块。主体/数值/布局完全独立：公司“栖云茶业”、门店“听雨店/观山店”、
数值 4518/193/5.6/2.4、编号 QY-47、年份 2038、日期 2038-06-11
（不沿用 澜庭生物/浩辰光电/澄远能源/北辰物流/岚桥智造/云帆文创/霁月新材/砚池文具/松涛纸业
及其全部数值/编号/年份）。

预期全部先于运行按公开产品契约写明（不按产品实际行为倒推）：
- R10 字面核心：证据仅“毛利2038会计年度测算/会计年测算”（含空白）年份形态、无毛利取值
  → 模型前拒答 not_found / UNSUPPORTED_FINANCIAL_METRIC 文案“没有可支撑”/sources=[]/chat=0；
  覆盖 legacy 模型前支持闸（service.py:2526-2536）与 RAG record+enumerate（answer.py:202-203）；
- 正例保持：无连接词“毛利4518万元”、三种负号、全/半角括号单位、千分位回显、百分之、单独倍率、
  财年在前/财政年度在前/会计年度在前取值在后 → 正常可答；
- R1—R9 已修切片不回归；M2 组内双向误绑/单位倍率/空绑定拒绝、真同义/P-R1 可答；
  错误/trace/固定子因/隔离/幂等契约保持。

泛化类残留探测（主人 2026-11-14 一次性泛化裁决；披露≠豁免）：R10 开发按老任务做了最小补丁
（守卫仅加 会计年度/会计年）。主人裁决要求整类覆盖标准会计/日历年份术语。下方
test_rv4_*_generalized_* 按契约对 预算年度/报告年度/纳税年度/自然年/公历年/学年 写明拒答预期
（这些术语证据同样无毛利取值）；若产品放行即泛化未覆盖的新年份形态残留独立红例（保留失败证据，
按 I5 交新返工项 R11=实施泛化守卫，本复验不自行改产品、不逐词预设黑名单）。

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

COMPANY = "栖云茶业"
TWO_METRIC = "栖云茶业 2038 年一季度经营数据：营业收入 4518 万元，净利润 193 万元。"
NET_PROFIT_Q = "栖云茶业 2038 年一季度净利润是多少？"
GROSS_Q = "栖云茶业 2038 年一季度毛利是多少？"
REVENUE_Q = "栖云茶业 2038 年一季度营业收入是多少？"
RATE_Q = "栖云茶业 2038 年一季度毛利率是多少？"
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
def rv4_env(settings, chat_model, tmp_path: Path):
    env = _make_env(settings, chat_model, tmp_path, trace=False)
    try:
        yield env
    finally:
        _teardown(env)


@pytest.fixture
def rv4_trace_env(settings, chat_model, tmp_path: Path):
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

def test_rv4_unit_r10_accounting_forms_not_value() -> None:
    """R10 字面单元：“NNNN会计年度/会计年”（含空白）是年份形态，不构成指标支持/绑定。"""
    for text in (
        "毛利2038会计年度测算尚待复核",
        "毛利2038 会计年度预算仍在编制",
        "毛利2038会计年测算尚待复核",
        "毛利2038 会计年预算仍在编制",
    ):
        assert not texts_support_financial_metric("毛利", [text]), text
        assert metric_value_bindings(text, "毛利") == set(), text
    assert "毛利" not in metric_binding_values("毛利2038会计年度测算尚待复核")


def test_rv4_unit_r1_r9_forms_still_rejected() -> None:
    """R1/R8/R9 切片保持：财政年度/财政年/财年（含空白）/年度/年/年月/-日期//日期均不构成支持。"""
    for text in (
        "毛利2038财政年度测算尚待复核",
        "毛利2038 财政年度预算仍在编制",
        "毛利2038财政年测算尚待复核",
        "毛利2038财年测算尚待复核",
        "毛利2038 财年预算仍在编制",
        "毛利2038年度预算尚在编制",
        "毛利2038年测算尚待复核",
        "毛利2038年6月复盘",
        "毛利2038-06-11 巡检",
        "毛利2038/06/11 盘点",
    ):
        assert not texts_support_financial_metric("毛利", [text]), text


def test_rv4_unit_legal_forms_supported() -> None:
    """正例单元口径：无连接词/三种负号/全半角括号单位/百分比/百分之/财年在前/财政年度在前/
    会计年度在前取值在后 均支持。"""
    for metric, text in (
        ("毛利", "毛利4518万元"),
        ("净利润", "净利润为 -193 万元"),
        ("净利润", "净利润为 −193 万元"),
        ("净利润", "净利润为负193万元"),
        ("毛利", "毛利（万元）：4518"),
        ("毛利", "毛利(万元):4518"),
        ("毛利率", "毛利率为 5.6%"),
        ("毛利率", "毛利率为百分之5.6"),
        ("毛利", "2038财年毛利为 4518 万元"),
        ("毛利", "2038财政年度毛利为 4518 万元"),
        ("毛利", "2038会计年度毛利为 4518 万元"),
    ):
        assert texts_support_financial_metric(metric, [text]), text


def test_rv4_unit_thousands_binding_complete() -> None:
    """O3 切片保持：千分位绑定核心完整（4518，不是 4）；会计年度年份形态不构成绑定。"""
    assert metric_value_bindings("营业收入为 4,518 万元", "营业收入") == {"4518"}
    assert metric_binding_values("营业收入为 4,518 万元")["营收"] == {("4518", "万", "元")}
    assert metric_value_bindings("毛利2038年度预算尚在编制", "毛利") == set()
    assert metric_value_bindings("毛利2038会计年度测算尚待复核", "毛利") == set()


def test_rv4_unit_generalized_year_forms_not_value() -> None:
    """泛化类残留探测（单元，主人一次性泛化裁决）：预算年度/报告年度/纳税年度/自然年/公历年/学年
    同为标准会计/日历年份术语，“NNNN+这些术语”是年份形态、无毛利取值，契约预期不构成支持/绑定。
    若 supported=True 即泛化未覆盖的残留候选。"""
    for text in (
        "毛利2038预算年度测算尚待复核",
        "毛利2038报告年度测算尚待复核",
        "毛利2038纳税年度测算尚待复核",
        "毛利2038自然年测算尚待复核",
        "毛利2038公历年测算尚待复核",
        "毛利2038学年测算尚待复核",
    ):
        assert not texts_support_financial_metric("毛利", [text]), text
        assert metric_value_bindings(text, "毛利") == set(), text


def test_rv4_unit_generalized_year_before_metric_supported() -> None:
    """泛化类正例：年份在前取值在后“2038预算年度/报告年度毛利为 4518 万元”须支持（不得误拒）。"""
    for text in (
        "2038预算年度毛利为 4518 万元",
        "2038报告年度毛利为 4518 万元",
        "2038自然年毛利为 4518 万元",
    ):
        assert texts_support_financial_metric("毛利", [text]), text


# ---------------------------------------------------------------- R10 字面：会计年度/会计年（legacy）

def test_rv4_m1_accounting_year_full_refuses(rv4_env) -> None:
    """R10 字面核心：证据仅“毛利2038会计年度测算”年份形态、无毛利取值 → 模型前拒答，chat=0。"""
    _publish(rv4_env, "rv4_ay_full.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038会计年度测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_accounting_year_full_space_refuses(rv4_env) -> None:
    """R10 字面空白变体：“毛利2038 会计年度预算” → 模型前拒答，chat=0。"""
    _publish(rv4_env, "rv4_ay_full_space.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038 会计年度预算仍在编制，未形成对外数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_accounting_year_short_refuses(rv4_env) -> None:
    """R10 字面短形态：“毛利2038会计年测算” → 模型前拒答，chat=0。"""
    _publish(rv4_env, "rv4_ay_short.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038会计年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_accounting_year_short_space_refuses(rv4_env) -> None:
    """R10 字面短形态空白变体：“毛利2038 会计年预算” → 模型前拒答，chat=0。"""
    _publish(rv4_env, "rv4_ay_short_space.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038 会计年预算仍在编制，未形成对外数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


# ---------------------------------------------------------------- 正例控制（年份在前取值在后等）

def test_rv4_m1_accounting_year_before_metric_answers(rv4_env) -> None:
    """正例约束：会计年度在前、取值在后“2038会计年度毛利为 4518 万元” → 不得误拒，正常可答。"""
    _publish(rv4_env, "rv4_ay_ok.docx", paragraphs=[
        "栖云茶业2038会计年度毛利为 4518 万元。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_answered(rv4_env, answer, "4518", calls_before)


def test_rv4_m1_no_connector_answers(rv4_env) -> None:
    """正例约束：合法无连接词“毛利4518万元”不得回归为拒答，且实际调用模型。"""
    _publish(rv4_env, "rv4_plain.docx", paragraphs=[
        "栖云茶业一季度毛利4518万元。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业一季度的毛利是多少？")
    _assert_answered(rv4_env, answer, "4518", calls_before)


def test_rv4_m1_fiscal_year_before_metric_answers(rv4_env) -> None:
    """R9 正例保持：财政年度在前、取值在后“2038财政年度毛利为 4518 万元” → 正常可答。"""
    _publish(rv4_env, "rv4_fy_ok.docx", paragraphs=[
        "栖云茶业2038财政年度毛利为 4518 万元。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_answered(rv4_env, answer, "4518", calls_before)


def test_rv4_m1_fiscal_year_r8_before_metric_answers(rv4_env) -> None:
    """R8 正例保持：财年在前、取值在后“2038财年毛利为 4518 万元” → 正常可答。"""
    _publish(rv4_env, "rv4_fy_r8_ok.docx", paragraphs=[
        "栖云茶业2038财年毛利为 4518 万元。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_answered(rv4_env, answer, "4518", calls_before)


# ---------------------------------------------------------------- R1—R9 已修切片（legacy 拒答不回归）

def test_rv4_m1_r9_fiscal_full_refuses(rv4_env) -> None:
    """R9 切片保持：财政年度紧随“毛利2038财政年度测算” → 模型前拒答。"""
    _publish(rv4_env, "rv4_fy_full.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038财政年度测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_r9_fiscal_short_refuses(rv4_env) -> None:
    """R9 切片保持：财政年紧随“毛利2038财政年测算” → 模型前拒答。"""
    _publish(rv4_env, "rv4_fy_short.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038财政年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_r8_fiscal_year_refuses(rv4_env) -> None:
    """R8 切片保持：财年紧随“毛利2038财年测算” → 模型前拒答。"""
    _publish(rv4_env, "rv4_fy_r8.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038财年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_year_suffix_refuses(rv4_env) -> None:
    """R1 切片保持：年度紧随“毛利2038年度预算” → 模型前拒答。"""
    _publish(rv4_env, "rv4_year.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038年度预算尚在编制，未形成对外数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_dash_date_refuses(rv4_env) -> None:
    """R1 切片保持：-日期紧随“毛利2038-06-11 巡检” → 模型前拒答。"""
    _publish(rv4_env, "rv4_dash.docx", paragraphs=[
        "栖云茶业周报：毛利2038-06-11 巡检记录已归档，数值待财务确认。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_slash_date_refuses(rv4_env) -> None:
    """R1 切片保持：/日期“毛利2038/06/11 盘点” → 模型前拒答。"""
    _publish(rv4_env, "rv4_slash.docx", paragraphs=[
        "栖云茶业周报：毛利2038/06/11 盘点记录已归档，数值待财务确认。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_year_month_refuses(rv4_env) -> None:
    """R1 切片保持：年月“毛利2038年6月复盘” → 模型前拒答。"""
    _publish(rv4_env, "rv4_ym.docx", paragraphs=[
        "栖云茶业月报：毛利2038年6月复盘会议已召开，数值待财务确认。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_irrelevant_id_date_refuses(rv4_env) -> None:
    """M1 原机制控制：仅无关编号/日期邻近毛利词 → 仍须模型前拒答。"""
    _publish(rv4_env, "rv4_id.docx", paragraphs=[
        "栖云茶业运营周报：门店编号 QY-47 于 2038-06-11 提交毛利影响测算，等待财务复核。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业本季度的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


# ---------------------------------------------------------------- 泛化类残留探测（新红例候选，契约预期拒答）

def test_rv4_m1_generalized_budget_year_refuses(rv4_env) -> None:
    """泛化类残留（legacy）：证据仅“毛利2038预算年度测算”——“预算年度”是标准会计年份术语，
    证据明确无毛利取值，契约预期模型前拒答 not_found/chat=0。R10 守卫仅加会计年度/会计年；
    若此形态放行即泛化未覆盖的新红例（R11 候选）。"""
    _publish(rv4_env, "rv4_gen_budget.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038预算年度测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_generalized_reporting_year_refuses(rv4_env) -> None:
    """泛化类残留（legacy）：证据仅“毛利2038报告年度测算” → 契约预期模型前拒答；放行即新红例。"""
    _publish(rv4_env, "rv4_gen_report.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038报告年度测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_generalized_tax_year_refuses(rv4_env) -> None:
    """泛化类残留（legacy）：证据仅“毛利2038纳税年度测算” → 契约预期模型前拒答；放行即新红例。"""
    _publish(rv4_env, "rv4_gen_tax.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038纳税年度测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_generalized_natural_year_refuses(rv4_env) -> None:
    """泛化类残留（legacy）：证据仅“毛利2038自然年测算” → 契约预期模型前拒答；放行即新红例。"""
    _publish(rv4_env, "rv4_gen_natural.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038自然年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_generalized_gregorian_year_refuses(rv4_env) -> None:
    """泛化类残留（legacy）：证据仅“毛利2038公历年测算” → 契约预期模型前拒答；放行即新红例。"""
    _publish(rv4_env, "rv4_gen_greg.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038公历年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


def test_rv4_m1_generalized_school_year_refuses(rv4_env) -> None:
    """泛化类残留（legacy）：证据仅“毛利2038学年测算” → 契约预期模型前拒答；放行即新红例。"""
    _publish(rv4_env, "rv4_gen_school.docx", paragraphs=[
        "栖云茶业经营简报：毛利2038学年测算尚待复核，暂无披露数值。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


# ---------------------------------------------------------------- R2：三种负号（应可答）

def test_rv4_m1_negative_ascii_answers(rv4_env) -> None:
    """R2 切片保持：ASCII 负号亏损原值“-193 万元” → 正常可答。"""
    _publish(rv4_env, "rv4_neg_a.docx", paragraphs=[
        "栖云茶业 2038 年一季度净利润为 -193 万元。",
    ])
    answer = _ask(rv4_env.employee, NET_PROFIT_Q)
    _assert_answered(rv4_env, answer, "193")


def test_rv4_m1_negative_unicode_answers(rv4_env) -> None:
    """R2 切片保持：U+2212 负号“−193 万元” → 正常可答。"""
    _publish(rv4_env, "rv4_neg_u.docx", paragraphs=[
        "栖云茶业 2038 年一季度净利润为 −193 万元。",
    ])
    answer = _ask(rv4_env.employee, NET_PROFIT_Q)
    _assert_answered(rv4_env, answer, "193")


def test_rv4_m1_negative_cn_answers(rv4_env) -> None:
    """R2 切片保持：中文负号“负193万元” → 正常可答。"""
    _publish(rv4_env, "rv4_neg_c.docx", paragraphs=[
        "栖云茶业 2038 年一季度净利润为负193万元。",
    ])
    answer = _ask(rv4_env.employee, NET_PROFIT_Q)
    _assert_answered(rv4_env, answer, "193")


# ---------------------------------------------------------------- R3：括号单位（应可答）与非单位括号

def test_rv4_m1_paren_fullwidth_answers(rv4_env) -> None:
    """R3 切片保持：全角括号单位“毛利（万元）：4518” → 正常可答。"""
    _publish(rv4_env, "rv4_paren_f.docx", paragraphs=[
        "栖云茶业 2038 年一季度毛利（万元）：4518。",
    ])
    answer = _ask(rv4_env.employee, GROSS_Q)
    _assert_answered(rv4_env, answer, "4518")


def test_rv4_m1_paren_halfwidth_answers(rv4_env) -> None:
    """R3 切片保持：半角括号单位“毛利(万元):4518” → 正常可答。"""
    _publish(rv4_env, "rv4_paren_h.docx", paragraphs=[
        "栖云茶业 2038 年一季度毛利(万元):4518。",
    ])
    answer = _ask(rv4_env.employee, GROSS_Q)
    _assert_answered(rv4_env, answer, "4518")


def test_rv4_m1_paren_non_unit_no_support(rv4_env) -> None:
    """非单位括号内容“毛利（待复核）”无数值 → 不得制造误支持，模型前拒答。"""
    _publish(rv4_env, "rv4_paren_n.docx", paragraphs=[
        "栖云茶业通知：毛利（待复核）事项另行通知。",
    ])
    calls_before = len(rv4_env.model.calls)
    answer = _ask(rv4_env.employee, "栖云茶业的毛利是多少？")
    _assert_pre_model_refusal(rv4_env, answer, calls_before)


# ---------------------------------------------------------------- O3：千分位回显（应可答）

def test_rv4_m1_thousands_echo_answers(rv4_env) -> None:
    """O3 切片保持：千分位原值回显“4,518” → 可答，绑定核心不得截断。"""
    _publish(rv4_env, "rv4_thousands.docx", paragraphs=[
        "栖云茶业 2038 年一季度营业收入为 4,518 万元。",
    ])
    answer = _ask(rv4_env.employee, REVENUE_Q)
    _assert_answered(rv4_env, answer, "518")


# ---------------------------------------------------------------- R4：空绑定绕过（拒绝）与缩写正例

def test_rv4_m2_omitted_name_rejected(rv4_env) -> None:
    """R4 切片保持：省略指标名“经营成果为 4518 万元”（营收值冒充净利润）→ 拒绝。"""
    _publish(rv4_env, "rv4_omit.docx", paragraphs=[TWO_METRIC])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度经营成果为 4518 万元。"
    answer = _ask(rv4_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv4_m2_abbrev_correct_answers(rv4_env) -> None:
    """R4 正例保持：真缩写“净利”取正确值 193 → 仍须可答。"""
    _publish(rv4_env, "rv4_abbr_ok.docx", paragraphs=[
        "栖云茶业 2038 年一季度净利润为 193 万元。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度净利为 193 万元。"
    answer = _ask(rv4_env.employee, NET_PROFIT_Q)
    _assert_answered(rv4_env, answer, "193")


# ---------------------------------------------------------------- R5：组内双向误绑 / 真同义

def test_rv4_m2_intra_gross_to_net_rejected(rv4_env) -> None:
    """R5 切片保持：毛利值 4518 说成净利润（利润组内误绑）→ 拒绝。"""
    _publish(rv4_env, "rv4_intra_gn.docx", paragraphs=[
        "栖云茶业 2038 年一季度毛利 4518 万元，净利润 193 万元。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度净利润为 4518 万元。"
    answer = _ask(rv4_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv4_m2_intra_net_to_gross_rejected(rv4_env) -> None:
    """R5 切片保持：反向组内误绑——净利润值 193 说成毛利 → 同样拒绝。"""
    _publish(rv4_env, "rv4_intra_ng.docx", paragraphs=[
        "栖云茶业 2038 年一季度毛利 4518 万元，净利润 193 万元。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度毛利为 193 万元。"
    answer = _ask(rv4_env.employee, GROSS_Q)
    _assert_m2_rejected(answer)


def test_rv4_m2_revenue_synonym_answers(rv4_env) -> None:
    """R5 正例保持：营业收入→营收 真同义改写取正确值 → 可答。"""
    _publish(rv4_env, "rv4_rev_syn.docx", paragraphs=[
        "栖云茶业 2038 年一季度营业收入为 4518 万元。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度营收为 4518 万元。"
    answer = _ask(rv4_env.employee, REVENUE_Q)
    _assert_answered(rv4_env, answer, "4518")


# ---------------------------------------------------------------- R6：单位/倍率

def test_rv4_m2_wan_to_yuan_rejected(rv4_env) -> None:
    """R6 切片保持：193 万元 → 193 元（倍率不符）→ 拒绝。"""
    _publish(rv4_env, "rv4_unit_y.docx", paragraphs=[
        "栖云茶业 2038 年一季度净利润为 193 万元。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度净利润为 193 元。"
    answer = _ask(rv4_env.employee, NET_PROFIT_Q)
    _assert_m2_rejected(answer)


def test_rv4_m2_wan_to_yi_rejected(rv4_env) -> None:
    """R6 切片保持：4518 万元 → 4518 亿元（倍率不符）→ 拒绝。"""
    _publish(rv4_env, "rv4_unit_yi.docx", paragraphs=[
        "栖云茶业 2038 年一季度营业收入为 4518 万元。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度营业收入为 4518 亿元。"
    answer = _ask(rv4_env.employee, REVENUE_Q)
    _assert_m2_rejected(answer)


def test_rv4_m2_percent_cn_answers(rv4_env) -> None:
    """R6 归一正例保持：“百分之5.6” ≡ “5.6%” → 可答。"""
    _publish(rv4_env, "rv4_pct.docx", paragraphs=[
        "栖云茶业 2038 年一季度毛利率为 5.6%。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度毛利率为百分之5.6。"
    answer = _ask(rv4_env.employee, RATE_Q)
    _assert_answered(rv4_env, answer, "5.6")


def test_rv4_m2_bare_wan_answers(rv4_env) -> None:
    """R6 归一正例保持：单独倍率“4518万” ≡ “4518万元” → 可答。"""
    _publish(rv4_env, "rv4_bare_w.docx", paragraphs=[
        "栖云茶业 2038 年一季度营业收入为 4518 万元。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度营业收入为 4518万。"
    answer = _ask(rv4_env.employee, REVENUE_Q)
    _assert_answered(rv4_env, answer, "4518")


def test_rv4_m2_paren_unit_binding_answers(rv4_env) -> None:
    """R6 括号单位绑定正例保持：证据“毛利（万元）：4518”背书回答“毛利为 4518 万元”。"""
    _publish(rv4_env, "rv4_paren_bind.docx", paragraphs=[
        "栖云茶业 2038 年一季度毛利（万元）：4518。",
    ])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度毛利为 4518 万元。"
    answer = _ask(rv4_env.employee, GROSS_Q)
    _assert_answered(rv4_env, answer, "4518")


# ---------------------------------------------------------------- P-R1：问题前提值（已批准放宽）

def test_rv4_m2_p_r1_premise_answers(rv4_env) -> None:
    """P-R1 保持：问题前提值 193 逐字出现 → 复述可答，不得撤销。"""
    _publish(rv4_env, "rv4_premise.docx", paragraphs=[
        "栖云茶业 2038 年一季度净利润为 193 万元。",
    ])
    rv4_env.model.answer_text = "是的，栖云茶业 2038 年一季度净利润为 193 万元。"
    answer = _ask(rv4_env.employee, "栖云茶业 2038 年一季度净利润是 193 万元吗？")
    _assert_answered(rv4_env, answer, "193")


# ---------------------------------------------------------------- RAG record 消费路径（共享函数）

RV4_RECORD_HEADERS = ["门店", "物品", "位置"]


def test_rv4_m1_rag_record_accounting_year_full_refuses(rv4_trace_env) -> None:
    """R10 字面核心（RAG record+enumerate）：记录行“毛利2038会计年度测算” → rag 路径拒答，chat=0。"""
    _publish(rv4_trace_env, "rv4_rag_ay_full.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "A区1号货架"],
        ["听雨店", "毛利2038会计年度测算", "编号QY-47"],
    ]))
    calls_before = len(rv4_trace_env.model.calls)
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "列出听雨店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv4_trace_env.model.calls) == calls_before, rv4_trace_env.model.calls


def test_rv4_m1_rag_record_accounting_year_short_refuses(rv4_trace_env) -> None:
    """R10 字面短形态（RAG record）：记录行“毛利2038会计年测算” → rag 路径拒答，chat=0。"""
    _publish(rv4_trace_env, "rv4_rag_ay_short.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "A区1号货架"],
        ["听雨店", "毛利2038会计年测算", "编号QY-47"],
    ]))
    calls_before = len(rv4_trace_env.model.calls)
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "列出听雨店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv4_trace_env.model.calls) == calls_before, rv4_trace_env.model.calls


def test_rv4_m1_rag_record_r9_fiscal_full_refuses(rv4_trace_env) -> None:
    """R9 切片保持（RAG record）：记录行“毛利2038财政年度测算” → rag 路径拒答，chat=0。"""
    _publish(rv4_trace_env, "rv4_rag_fy_full.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "A区1号货架"],
        ["听雨店", "毛利2038财政年度测算", "编号QY-47"],
    ]))
    calls_before = len(rv4_trace_env.model.calls)
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "列出听雨店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv4_trace_env.model.calls) == calls_before, rv4_trace_env.model.calls


def test_rv4_m1_rag_record_r8_fiscal_year_refuses(rv4_trace_env) -> None:
    """R8 切片保持（RAG record）：记录行“毛利2038财年测算” → rag 路径拒答，chat=0。"""
    _publish(rv4_trace_env, "rv4_rag_fy_r8.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "A区1号货架"],
        ["听雨店", "毛利2038财年测算", "编号QY-47"],
    ]))
    calls_before = len(rv4_trace_env.model.calls)
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "列出听雨店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv4_trace_env.model.calls) == calls_before, rv4_trace_env.model.calls


def test_rv4_m1_rag_record_value_answers(rv4_trace_env) -> None:
    """RAG 正向控制：记录行确有毛利取值 → rag 路径正常枚举作答。"""
    _publish(rv4_trace_env, "rv4_rag_ok.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "毛利 4518 万元"],
        ["听雨店", "灯箱片", "毛利 193 万元"],
    ]))
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "列出听雨店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "answer", answer
    assert "4518" in answer["text"], answer["text"]


def test_rv4_m1_rag_record_generalized_budget_year_refuses(rv4_trace_env) -> None:
    """泛化类残留（RAG record）：记录行“毛利2038预算年度测算” → 契约预期 rag 路径拒答 not_found/chat=0；
    若放行即泛化未覆盖的新红例（R11 候选）。"""
    _publish(rv4_trace_env, "rv4_rag_gen_budget.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "A区1号货架"],
        ["听雨店", "毛利2038预算年度测算", "编号QY-47"],
    ]))
    calls_before = len(rv4_trace_env.model.calls)
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "列出听雨店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv4_trace_env.model.calls) == calls_before, rv4_trace_env.model.calls


def test_rv4_m1_rag_record_generalized_natural_year_refuses(rv4_trace_env) -> None:
    """泛化类残留（RAG record）：记录行“毛利2038自然年测算” → 契约预期 rag 路径拒答；放行即新红例。"""
    _publish(rv4_trace_env, "rv4_rag_gen_natural.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "A区1号货架"],
        ["听雨店", "毛利2038自然年测算", "编号QY-47"],
    ]))
    calls_before = len(rv4_trace_env.model.calls)
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "列出听雨店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(rv4_trace_env.model.calls) == calls_before, rv4_trace_env.model.calls


# ---------------------------------------------------------------- 分流基线（单轮直接指标题走 legacy）

def test_rv4_route_single_turn_metric_legacy(rv4_trace_env) -> None:
    """单轮直接指标题走 legacy（分流基线，独立复核）。"""
    _publish(rv4_trace_env, "rv4_route.docx", paragraphs=[
        "听雨店毛利审批流程须按财务制度执行，测算编号 QY-47，日期 2038-06-11。",
    ])
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee),
                     "栖云茶业的毛利是多少？")
    assert response.status_code == 200, response.text
    trace, _ = _trace_of(rv4_trace_env, response)
    assert trace.path == "legacy", trace.path


# ---------------------------------------------------------------- 错误契约 / 隔离 / 幂等

def test_rv4_error_contract_copy_trace_subreason(rv4_trace_env) -> None:
    """错误契约：公开文案=copy 模板、trace.error_code/reason=MODEL_OUTPUT_INVALID、固定子因 unknown。"""
    _publish(rv4_trace_env, "rv4_err.docx", paragraphs=[TWO_METRIC])
    rv4_trace_env.model.answer_text = "栖云茶业 2038 年一季度净利润为 4518 万元。"
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee), NET_PROFIT_Q)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    expected_text = copy_module.service_error_text("MODEL_OUTPUT_INVALID", retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(rv4_trace_env, response)
    assert getattr(trace, "error_code", None) == "MODEL_OUTPUT_INVALID", trace
    assert getattr(trace, "reason", None) == "MODEL_OUTPUT_INVALID", trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs


def test_rv4_provider_error_no_echo(rv4_trace_env) -> None:
    """provider 恶意异常文本零回显：稳定码 copy 文案，子因 unknown。"""
    _publish(rv4_trace_env, "rv4_provider.docx", paragraphs=[
        "栖云茶业 2038 年一季度毛利为 4518 万元。",
    ])
    rv4_trace_env.model.error = ModelTimeout("RV4-SECRET-NEVER-REAL sk-fake-999 D:/private/rv4")
    response = _post(rv4_trace_env.employee, _new_conversation(rv4_trace_env.employee), GROSS_Q)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"], answer
    assert "RV4-SECRET" not in answer["text"], answer["text"]
    assert "sk-fake" not in answer["text"], answer["text"]
    expected_text = copy_module.service_error_text(answer["error_code"], retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(rv4_trace_env, response)
    assert getattr(trace, "error_code", None) == answer["error_code"], trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs


def test_rv4_isolation_between_users(rv4_trace_env) -> None:
    """跨用户隔离：employee 锁定听雨店后，employee2 全新会话枚举两店不串状态。"""
    _publish(rv4_trace_env, "rv4_iso.xlsx", sheet=(RV4_RECORD_HEADERS, [
        ["听雨店", "桁架海报", "A区1号货架"],
        ["观山店", "灯箱片", "C区3号货架"],
    ]))
    conv1 = _new_conversation(rv4_trace_env.employee)
    r1 = _post(rv4_trace_env.employee, conv1, "列出听雨店所有物品")
    assert r1.status_code == 200 and r1.json()["kind"] == "answer", r1.text
    assert "观山店" not in r1.json()["text"], r1.json()
    conv2 = _new_conversation(rv4_trace_env.employee2)
    r2 = _post(rv4_trace_env.employee2, conv2, "列出所有物品")
    assert r2.status_code == 200 and r2.json()["kind"] == "answer", r2.text
    assert "观山店" in r2.json()["text"], r2.json()
    assert "听雨店" in r2.json()["text"], r2.json()


def test_rv4_idempotent_replay_no_extra_call(rv4_env) -> None:
    """幂等重放：同一 client_request_id 重放拒绝结果，模型调用数不增。"""
    _publish(rv4_env, "rv4_replay.docx", paragraphs=[TWO_METRIC])
    rv4_env.model.answer_text = "栖云茶业 2038 年一季度净利润为 4518 万元。"
    conversation = _new_conversation(rv4_env.employee)
    request_id = str(uuid.uuid4())
    first = _post(rv4_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert first.status_code == 200, first.text
    calls_after_first = len(rv4_env.model.calls)
    second = _post(rv4_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert second.status_code == 200, second.text
    assert second.json()["kind"] == first.json()["kind"], (first.json(), second.json())
    assert second.json()["error_code"] == first.json()["error_code"], (first.json(), second.json())
    assert len(rv4_env.model.calls) == calls_after_first, rv4_env.model.calls