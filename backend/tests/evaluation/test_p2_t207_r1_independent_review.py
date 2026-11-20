"""T207-R1 独立验收（I3/I4）：全新合成正反例，走真实产品装配链。

验收者独立编写，不复用开发测试模块；主体/数值/布局均不同于开发样例
（公司“岚桥智造”、门店“西岭店/南浦店”、数值 6175/908/7.4、编号 LB-12）。
预期全部来自公开产品契约（无依据拒答、有直接证据可答、错误取值拒绝、
P-R1 已批准放宽、错误/trace 契约），不按产品实际行为倒推预期。

零真实调用：t09_network_guard 外部出站即 fail；provider 为 conftest 合成替身。
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

pytestmark = pytest.mark.usefixtures("t09_network_guard")

COMPANY = "岚桥智造"


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
            display_name="独立验收员工二", role="employee", rounds=4,
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
def ind_env(settings, chat_model, tmp_path: Path):
    env = _make_env(settings, chat_model, tmp_path, trace=False)
    try:
        yield env
    finally:
        _teardown(env)


@pytest.fixture
def ind_trace_env(settings, chat_model, tmp_path: Path):
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


# ---------------------------------------------------------------- M1：年份/编号紧随指标词（应拒答）

def test_ind_m1_year_after_metric_must_refuse(ind_env) -> None:
    """契约：证据只有“毛利2026年度测算”这类年份紧邻，无毛利取值 → 模型前拒答。"""
    _publish(ind_env, "ind_year.docx", paragraphs=[
        "岚桥智造运营简报：毛利2026年度测算尚待财务复核，暂无对外披露数值。",
    ])
    calls_before = len(ind_env.model.calls)
    answer = _ask(ind_env.employee, "岚桥智造的毛利是多少？")
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(ind_env.model.calls) == calls_before, ind_env.model.calls


def test_ind_m1_date_after_metric_must_refuse(ind_env) -> None:
    """契约：证据只有“毛利2026-04-01 盘点”这类日期紧邻，无毛利取值 → 模型前拒答。"""
    _publish(ind_env, "ind_date.docx", paragraphs=[
        "岚桥智造周报：毛利2026-04-01 盘点记录已归档，数值待财务确认。",
    ])
    calls_before = len(ind_env.model.calls)
    answer = _ask(ind_env.employee, "岚桥智造的毛利是多少？")
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(ind_env.model.calls) == calls_before, ind_env.model.calls


# ---------------------------------------------------------------- M1：合法取值不得误拒（应可答）

def test_ind_m1_negative_value_must_answer(ind_env) -> None:
    """契约：证据确有净利润原值（负数亏损）→ 正常可答，不得一律拒答。"""
    _publish(ind_env, "ind_negative.docx", paragraphs=[
        "岚桥智造 2026 年一季度净利润为 -908 万元。",
    ])
    answer = _ask(ind_env.employee, "岚桥智造 2026 年一季度净利润是多少？")
    assert answer["kind"] == "answer", answer
    assert "908" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_ind_m1_thousands_separator_must_answer(ind_env) -> None:
    """契约：千分位写法的营业收入原值 → 正常可答。"""
    _publish(ind_env, "ind_thousands.docx", paragraphs=[
        "岚桥智造 2026 年一季度营业收入为 6,175 万元。",
    ])
    answer = _ask(ind_env.employee, "岚桥智造 2026 年一季度营业收入是多少？")
    assert answer["kind"] == "answer", answer
    assert "175" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_ind_m1_paren_unit_must_answer(ind_env) -> None:
    """契约：括号单位“毛利（万元）：6175”是合法业务样式 → 正常可答。"""
    _publish(ind_env, "ind_paren.docx", paragraphs=[
        "岚桥智造 2026 年一季度毛利（万元）：6175。",
    ])
    answer = _ask(ind_env.employee, "岚桥智造 2026 年一季度毛利是多少？")
    assert answer["kind"] == "answer", answer
    assert "6175" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_ind_m1_plain_value_control(ind_env) -> None:
    """正向控制：普通“毛利为 6175 万元”必须可答且实际调用模型。"""
    _publish(ind_env, "ind_plain.docx", paragraphs=[
        "岚桥智造 2026 年一季度毛利为 6175 万元。",
    ])
    calls_before = len(ind_env.model.calls)
    answer = _ask(ind_env.employee, "岚桥智造 2026 年一季度毛利是多少？")
    assert answer["kind"] == "answer", answer
    assert "6175" in answer["text"], answer["text"]
    assert answer["sources"], answer
    assert len(ind_env.model.calls) > calls_before, ind_env.model.calls


def test_ind_m1_percent_control(ind_env) -> None:
    """正向控制：毛利率百分比原值必须可答。"""
    _publish(ind_env, "ind_percent.docx", paragraphs=[
        "岚桥智造 2026 年一季度毛利率为 7.4%。",
    ])
    answer = _ask(ind_env.employee, "岚桥智造 2026 年一季度毛利率是多少？")
    assert answer["kind"] == "answer", answer
    assert "7.4" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- M2：取值绑定（应拒绝/应接受）

TWO_METRIC = "岚桥智造 2026 年一季度经营数据：营业收入 6175 万元，净利润 908 万元。"
NET_PROFIT_Q = "岚桥智造 2026 年一季度净利润是多少？"


def test_ind_m2_cross_group_rejected(ind_env) -> None:
    """契约：把营业收入值 6175 说成净利润（跨组误绑）→ MODEL_OUTPUT_INVALID，不保存。"""
    _publish(ind_env, "ind_two.docx", paragraphs=[TWO_METRIC])
    ind_env.model.answer_text = "岚桥智造 2026 年一季度净利润为 6175 万元。"
    answer = _ask(ind_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    assert answer["sources"] == [], answer


def test_ind_m2_correct_accepted(ind_env) -> None:
    """正向控制：逐字取本指标原值 908 → 正常保存。"""
    _publish(ind_env, "ind_two_ok.docx", paragraphs=[TWO_METRIC])
    ind_env.model.answer_text = "岚桥智造 2026 年一季度净利润为 908 万元。"
    answer = _ask(ind_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "answer", answer
    assert "908" in answer["text"], answer["text"]
    assert answer["sources"], answer


def test_ind_m2_omitted_metric_name_must_not_bypass(ind_env) -> None:
    """契约：回答省略指标名（“经营成果为 6175 万元”）仍是错误取值 → 应拒绝。

    证伪目标：空绑定集合是否绕过 M2 核对（6175 是营业收入值，不是净利润）。
    """
    _publish(ind_env, "ind_omit.docx", paragraphs=[TWO_METRIC])
    ind_env.model.answer_text = "岚桥智造 2026 年一季度经营成果为 6175 万元。"
    answer = _ask(ind_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer


def test_ind_m2_abbreviation_must_not_bypass(ind_env) -> None:
    """契约：常见缩写“净利为 6175 万元”仍是错误取值 → 应拒绝。"""
    _publish(ind_env, "ind_abbr.docx", paragraphs=[TWO_METRIC])
    ind_env.model.answer_text = "岚桥智造 2026 年一季度净利为 6175 万元。"
    answer = _ask(ind_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer


def test_ind_m2_intra_group_misbinding_rejected(ind_env) -> None:
    """契约：毛利值 6175 说成净利润（同组内误绑）→ 应拒绝，不保存错误事实。"""
    _publish(ind_env, "ind_intra.docx", paragraphs=[
        "岚桥智造 2026 年一季度毛利 6175 万元，净利润 908 万元。",
    ])
    ind_env.model.answer_text = "岚桥智造 2026 年一季度净利润为 6175 万元。"
    answer = _ask(ind_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer


def test_ind_m2_unit_multiplier_mismatch_rejected(ind_env) -> None:
    """契约：数字相同但单位/倍率不同（908 万元 → 908 元）→ 应拒绝。"""
    _publish(ind_env, "ind_unit.docx", paragraphs=[
        "岚桥智造 2026 年一季度净利润为 908 万元。",
    ])
    ind_env.model.answer_text = "岚桥智造 2026 年一季度净利润为 908 元。"
    answer = _ask(ind_env.employee, NET_PROFIT_Q)
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer


def test_ind_m2_p_r1_question_premise_preserved(ind_env) -> None:
    """P-R1 已批准放宽：问题原文逐字出现的前提值 908 可复述 → 保持可答。"""
    _publish(ind_env, "ind_premise.docx", paragraphs=[
        "岚桥智造 2026 年一季度净利润为 908 万元。",
    ])
    ind_env.model.answer_text = "是的，岚桥智造 2026 年一季度净利润为 908 万元。"
    answer = _ask(ind_env.employee, "岚桥智造 2026 年一季度净利润是 908 万元吗？")
    assert answer["kind"] == "answer", answer
    assert "908" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- 分流探针：RAG 正文路径可达性

RECORD_HEADERS = ["门店", "物品", "位置"]
RECORD_ROWS = [
    ["西岭店", "桁架海报", "A区1号货架"],
    ["西岭店", "灯箱片", "B区2号货架"],
]


def test_ind_route_single_turn_metric_legacy(ind_trace_env) -> None:
    """单轮直接指标题走 legacy（与开发结论一致的部分，独立复核）。"""
    _publish(ind_trace_env, "ind_route.docx", paragraphs=[
        "西岭店毛利审批流程须按财务制度执行，测算编号 LB-12，日期 2026-04-01。",
    ])
    response = _post(ind_trace_env.employee, _new_conversation(ind_trace_env.employee),
                     "岚桥智造的毛利是多少？")
    assert response.status_code == 200, response.text
    trace, _spans = _trace_of(ind_trace_env, response)
    assert trace.path == "legacy", trace.path


def test_ind_route_policy_followup_reaches_rag_document(ind_trace_env) -> None:
    """证伪“RAG 正文路径对指标题不可达”：政策追问含指标词，单轮即可进 RAG 正文计划。

    “西岭店那个毛利审批流程是什么？”含指代+政策词+显式门店 → parse_query 打
    POLICY_FOLLOWUP 并以 record+enumerate 交给内核；answer_question 换回正文计划。
    证据无毛利取值 → 应在 RAG 正文计划上 UNSUPPORTED_FINANCIAL_METRIC 拒答。
    """
    _publish(ind_trace_env, "ind_records.xlsx", sheet=(RECORD_HEADERS, RECORD_ROWS))
    _publish(ind_trace_env, "ind_policy.docx", paragraphs=[
        "西岭店毛利审批流程须按财务制度执行，测算编号 LB-12，日期 2026-04-01。",
    ])
    response = _post(ind_trace_env.employee, _new_conversation(ind_trace_env.employee),
                     "西岭店那个毛利审批流程是什么？")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, spans = _trace_of(ind_trace_env, response)
    parse_attrs = _span_attrs(spans, "parse")
    assert trace.path == "rag", (trace.path, parse_attrs, answer)
    assert parse_attrs.get("reason") == "POLICY_FOLLOWUP", parse_attrs
    assert answer["kind"] == "not_found", answer
    assert getattr(trace, "reason", None) == "UNSUPPORTED_FINANCIAL_METRIC", trace


def test_ind_route_multiturn_policy_followup_rag_document_answer(ind_trace_env) -> None:
    """多轮：先记录枚举，再政策追问（含指标词且有取值）→ RAG 正文直答实际执行。

    期望 answer_source=extractive_offline，即 _document_fallback →
    FactValidator.validate_document_text 真实运行（RAG 正文路径可达的直接证据）。
    """
    _publish(ind_trace_env, "ind_records2.xlsx", sheet=(RECORD_HEADERS, RECORD_ROWS))
    _publish(ind_trace_env, "ind_policy2.docx", paragraphs=[
        "西岭店毛利审批流程要求毛利 6175 万元的项目按财务制度复核。",
    ])
    conversation = _new_conversation(ind_trace_env.employee)
    first = _post(ind_trace_env.employee, conversation, "列出西岭店所有物品")
    assert first.status_code == 200, first.text
    assert first.json()["kind"] == "answer", first.json()
    trace1, _ = _trace_of(ind_trace_env, first)
    assert trace1.path == "rag", trace1.path
    second = _post(ind_trace_env.employee, conversation, "西岭店那个毛利审批流程是什么？")
    assert second.status_code == 200, second.text
    answer = second.json()
    trace, spans = _trace_of(ind_trace_env, second)
    parse_attrs = _span_attrs(spans, "parse")
    answer_attrs = _span_attrs(spans, "answer")
    assert trace.path == "rag", (trace.path, parse_attrs, answer)
    assert parse_attrs.get("reason") == "POLICY_FOLLOWUP", parse_attrs
    assert answer["kind"] == "answer", answer
    assert answer_attrs.get("answer_source") == "extractive_offline", answer_attrs


def test_ind_route_policy_topic_followup_rag_document(ind_trace_env) -> None:
    """另一政策分支 POLICY_TOPIC_FOLLOWUP（强话题词+字段同形词）同样进 RAG 正文。"""
    _publish(ind_trace_env, "ind_records3.xlsx", sheet=(RECORD_HEADERS, RECORD_ROWS))
    _publish(ind_trace_env, "ind_policy3.docx", paragraphs=[
        "西岭店毛利报销规则要求毛利 6175 万元以上的报销附财务复核单。",
    ])
    response = _post(ind_trace_env.employee, _new_conversation(ind_trace_env.employee),
                     "西岭店那个毛利报销规则是什么？")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, spans = _trace_of(ind_trace_env, response)
    parse_attrs = _span_attrs(spans, "parse")
    answer_attrs = _span_attrs(spans, "answer")
    assert trace.path == "rag", (trace.path, parse_attrs, answer)
    assert parse_attrs.get("reason") == "POLICY_TOPIC_FOLLOWUP", parse_attrs
    assert answer["kind"] == "answer", answer
    assert answer_attrs.get("answer_source") == "extractive_offline", answer_attrs


# ---------------------------------------------------------------- M1 RAG 记录消费路径（共享函数）

def test_ind_m1_rag_record_irrelevant_refuses(ind_trace_env) -> None:
    """RAG record+enumerate：记录行只有编号/日期邻近毛利词 → 拒答，chat=0。"""
    _publish(ind_trace_env, "ind_rag_bad.xlsx", sheet=(RECORD_HEADERS, [
        ["西岭店", "桁架海报", "A区1号货架"],
        ["西岭店", "毛利影响测算", "编号LB-12 日期2026-04-01"],
    ]))
    calls_before = len(ind_trace_env.model.calls)
    response = _post(ind_trace_env.employee, _new_conversation(ind_trace_env.employee),
                     "列出西岭店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(ind_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert answer["sources"] == [], answer
    assert len(ind_trace_env.model.calls) == calls_before, ind_trace_env.model.calls


def test_ind_m1_rag_record_supported_answers(ind_trace_env) -> None:
    """RAG 正向控制：记录行确有毛利取值 → 正常枚举作答，不一律拒答。"""
    _publish(ind_trace_env, "ind_rag_ok.xlsx", sheet=(RECORD_HEADERS, [
        ["西岭店", "桁架海报", "毛利 6175 万元"],
        ["西岭店", "灯箱片", "毛利 908 万元"],
    ]))
    response = _post(ind_trace_env.employee, _new_conversation(ind_trace_env.employee),
                     "列出西岭店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace, _ = _trace_of(ind_trace_env, response)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "answer", answer
    assert "6175" in answer["text"], answer["text"]


# ---------------------------------------------------------------- 隔离 / 幂等 / 错误契约

def test_ind_isolation_no_state_leak_between_users(ind_trace_env) -> None:
    """不同用户/会话不串状态：employee 锁定西岭店后，employee2 全新会话不受影响。"""
    _publish(ind_trace_env, "ind_iso.xlsx", sheet=(RECORD_HEADERS, [
        ["西岭店", "桁架海报", "A区1号货架"],
        ["南浦店", "灯箱片", "C区3号货架"],
    ]))
    conv1 = _new_conversation(ind_trace_env.employee)
    r1 = _post(ind_trace_env.employee, conv1, "列出西岭店所有物品")
    assert r1.status_code == 200 and r1.json()["kind"] == "answer", r1.text
    assert "南浦店" not in r1.json()["text"], r1.json()
    conv2 = _new_conversation(ind_trace_env.employee2)
    r2 = _post(ind_trace_env.employee2, conv2, "列出所有物品")
    assert r2.status_code == 200 and r2.json()["kind"] == "answer", r2.text
    assert "南浦店" in r2.json()["text"], r2.json()
    assert "西岭店" in r2.json()["text"], r2.json()


def test_ind_idempotent_replay_no_extra_model_call(ind_env) -> None:
    """幂等重放：同一 client_request_id 重放拒绝结果，不新增模型调用。"""
    _publish(ind_env, "ind_replay.docx", paragraphs=[TWO_METRIC])
    ind_env.model.answer_text = "岚桥智造 2026 年一季度净利润为 6175 万元。"
    conversation = _new_conversation(ind_env.employee)
    request_id = str(uuid.uuid4())
    first = _post(ind_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert first.status_code == 200, first.text
    calls_after_first = len(ind_env.model.calls)
    second = _post(ind_env.employee, conversation, NET_PROFIT_Q, request_id)
    assert second.status_code == 200, second.text
    assert second.json()["kind"] == first.json()["kind"], (first.json(), second.json())
    assert second.json()["error_code"] == first.json()["error_code"], (first.json(), second.json())
    assert len(ind_env.model.calls) == calls_after_first, ind_env.model.calls


def test_ind_error_contract_text_trace_subreason(ind_trace_env) -> None:
    """错误契约：公开文案=copy 模板、trace error_code/reason、固定子因 unknown 保全。"""
    _publish(ind_trace_env, "ind_err.docx", paragraphs=[TWO_METRIC])
    ind_trace_env.model.answer_text = "岚桥智造 2026 年一季度净利润为 6175 万元。"
    response = _post(ind_trace_env.employee, _new_conversation(ind_trace_env.employee), NET_PROFIT_Q)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    expected_text = copy_module.service_error_text("MODEL_OUTPUT_INVALID", retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(ind_trace_env, response)
    assert getattr(trace, "error_code", None) == "MODEL_OUTPUT_INVALID", trace
    assert getattr(trace, "reason", None) == "MODEL_OUTPUT_INVALID", trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs


def test_ind_provider_error_no_arbitrary_echo(ind_trace_env) -> None:
    """provider 异常文本不回显：稳定码 + copy 文案，恶意字符串不出现在公开回答。"""
    _publish(ind_trace_env, "ind_provider.docx", paragraphs=[
        "岚桥智造 2026 年一季度毛利为 6175 万元。",
    ])
    ind_trace_env.model.error = ModelTimeout("PM-SECRET-NEVER-REAL sk-fake-000 C:/private/path")
    response = _post(ind_trace_env.employee, _new_conversation(ind_trace_env.employee),
                     "岚桥智造 2026 年一季度毛利是多少？")
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"], answer
    assert "PM-SECRET" not in answer["text"], answer["text"]
    assert "sk-fake" not in answer["text"], answer["text"]
    expected_text = copy_module.service_error_text(answer["error_code"], retryable=answer["retryable"])
    assert answer["text"] == expected_text, (answer["text"], expected_text)
    trace, spans = _trace_of(ind_trace_env, response)
    assert getattr(trace, "error_code", None) == answer["error_code"], trace
    failure_attrs = _span_attrs(spans, "model_failure")
    assert failure_attrs.get("model_failure_reason") == "unknown", failure_attrs