"""P2-T207-PRODUCT-BEHAVIOR-REPAIR-R1：产品行为合成红例/正例（先 RED 后最小修复）。

只用公共/独立合成材料（独立主体“云帆文创”、独立数值/文档），零真实调用
（``t09_network_guard`` 外部出站即 fail）；不读真实 H2/私有缓存，不撤销 P-R1 已批准放宽。

两类目标机制（预期来自公开契约，非旧 4 fail 根因断言）：
- M1 拒答类：指标支持判定 ``_metric_value_context`` 用指标词邻近数字窗口判支持，
  无关编号/日期/其他指标数字会被误认作本指标取值。契约依据：验收矩阵 N05/A-12
  “无答案不编造”；P1-FIX/A 产品语义“证据里确有**该指标**的数值时才作答”。
  反例期望 ``kind=not_found``、文案含“没有可支撑”、无来源、chat=0（模型前拒答）。
- M2 取值/来源类：正文准入只查数据 token 存在于被引证据全集，不查值与所问指标绑定。
  契约依据：接口契约 §1“来源不符或添加无依据事实均判失败”、§6“字段由代码核对原值”。
  反例期望拒绝（复用既有准入错误 ``MODEL_OUTPUT_INVALID``），不保存错误事实。

实际分流：财务指标问题被 intent/rag 规划为 document 模式，``_rag_owns_turn`` 不接手，
走 legacy（service.py 检索后、模型前的 ``texts_support_financial_metric`` 判定）。
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

pytestmark = pytest.mark.usefixtures("t09_network_guard")


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


@pytest.fixture
def repair_env(settings, chat_model, tmp_path: Path) -> SimpleNamespace:
    """真实产品装配 + 合成模型替身；不预置资料，各用例上传独立合成文档避免污染。"""
    app = create_app(settings, model_gateway=chat_model)
    admin = _session(app, "admin", "AdminPass-1")
    employee = _session(app, "employee", "EmployeePass-1")
    try:
        yield SimpleNamespace(
            app=app, admin=admin, employee=employee, model=chat_model, tmp_path=tmp_path
        )
    finally:
        qa = getattr(app.state, "qa", None)
        if qa is not None:
            qa.close()
        app.state.db.dispose()


@pytest.fixture
def repair_trace_env(settings, chat_model, tmp_path: Path) -> SimpleNamespace:
    """开启 Trace（hash 内容模式，不落明文）的装配，用于钉住实际分流 path。"""
    trace_settings = settings.model_copy(
        update={
            "trace_enabled": True,
            "trace_db_path": tmp_path / "observability" / "qa-traces.sqlite3",
            "trace_content_mode": "hash",
        }
    )
    app = create_app(trace_settings, model_gateway=chat_model)
    admin = _session(app, "admin", "AdminPass-1")
    employee = _session(app, "employee", "EmployeePass-1")
    try:
        yield SimpleNamespace(
            app=app, admin=admin, employee=employee, model=chat_model, tmp_path=tmp_path
        )
    finally:
        qa = getattr(app.state, "qa", None)
        if qa is not None:
            qa.close()
        repo = getattr(app.state, "trace_repo", None)
        if repo is not None:
            repo.close()
        app.state.db.dispose()


def _publish_docx(env: SimpleNamespace, name: str, paragraphs: list[str]) -> dict:
    """合成 docx → 上传 → worker → 发布；返回发布响应 JSON。"""
    source = env.tmp_path / name
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(source)
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


def _ask(session: SimpleNamespace, question: str) -> dict:
    created = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert created.status_code == 201, created.text
    response = session.client.post(
        f"/api/v1/conversations/{created.json()['id']}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _publish_xlsx(env: SimpleNamespace, name: str, headers: list[str], rows: list[list[str]]) -> dict:
    """合成 xlsx 记录表 → 上传 → worker → 发布；返回发布响应 JSON。"""
    source = env.tmp_path / name
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
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


# ---------------------------------------------------------------- M1 拒答类（legacy 正文路径）

#: 反例资料：含“毛利”词，但邻近数字是门店编号/日期，不是毛利取值。
M1_UNSUPPORTED_PARAGRAPHS = [
    "云帆文创运营周报：门店编号 YF-07 于 2026-03-12 提交毛利影响测算，等待财务复核。",
]
#: 正例资料：指标词紧邻本指标数值（毛利 4812 万元）。
M1_SUPPORTED_PARAGRAPHS = [
    "云帆文创 2026 年一季度毛利为 4812 万元，较上年同期保持平稳。",
]


def test_m1_irrelevant_numbers_must_refuse_before_chat(repair_env: SimpleNamespace) -> None:
    """M1 红例：只有无关编号/日期邻近指标词时应模型前拒答，不得当作有依据作答。"""
    _publish_docx(repair_env, "m1_unsupported.docx", M1_UNSUPPORTED_PARAGRAPHS)
    calls_before = len(repair_env.model.calls)
    answer = _ask(repair_env.employee, "云帆文创本季度的毛利是多少？")
    assert answer["kind"] == "not_found", answer
    assert "没有可支撑" in answer["text"], answer["text"]
    assert answer["sources"] == [], answer
    assert "服务暂不可用" not in answer["text"], answer["text"]
    # 契约要求模型前拒答：chat 调用次数不增加。
    assert len(repair_env.model.calls) == calls_before, repair_env.model.calls


def test_m1_direct_metric_value_still_answers(repair_env: SimpleNamespace) -> None:
    """M1 正例：证据确有本指标数值时保持正常作答，拒答修复不得扩大为一律拒答。"""
    _publish_docx(repair_env, "m1_supported.docx", M1_SUPPORTED_PARAGRAPHS)
    calls_before = len(repair_env.model.calls)
    answer = _ask(repair_env.employee, "云帆文创 2026 年一季度毛利是多少？")
    assert answer["kind"] == "answer", answer
    assert "4812" in answer["text"], answer["text"]
    assert answer["sources"], answer
    assert len(repair_env.model.calls) > calls_before, repair_env.model.calls


# ---------------------------------------------------------------- M2 取值/来源类（legacy 正文路径）

#: 同一被引证据含两个指标的原值：营业收入 4812、净利润 300。
M2_TWO_METRIC_PARAGRAPHS = [
    "云帆文创 2026 年一季度经营数据：营业收入 4812 万元，净利润 300 万元。",
]


def test_m2_wrong_metric_value_binding_must_be_rejected(repair_env: SimpleNamespace) -> None:
    """M2 红例：引用含两指标的证据，却把营业收入值说成净利润 → 应拒绝，不保存错误事实。

    错误值 4812 逐字来自被引证据（token 存在），但绑定到错误指标；契约 §1/§6 要求
    字段由代码核对原值、来源不符判失败。复用既有准入错误 MODEL_OUTPUT_INVALID。
    """
    _publish_docx(repair_env, "m2_two_metric.docx", M2_TWO_METRIC_PARAGRAPHS)
    repair_env.model.answer_text = "云帆文创 2026 年一季度净利润为 4812 万元。"
    answer = _ask(repair_env.employee, "云帆文创 2026 年一季度净利润是多少？")
    assert answer["kind"] == "service_error", answer
    assert answer["error_code"] == "MODEL_OUTPUT_INVALID", answer
    assert answer["sources"] == [], answer
    assert not (answer["kind"] == "answer" and "4812" in answer["text"]), answer


def test_m2_correct_metric_value_is_accepted(repair_env: SimpleNamespace) -> None:
    """M2 正例：逐字取本指标原值（净利润 300）应正常保存，不误拒。"""
    _publish_docx(repair_env, "m2_two_metric_ok.docx", M2_TWO_METRIC_PARAGRAPHS)
    repair_env.model.answer_text = "云帆文创 2026 年一季度净利润为 300 万元。"
    answer = _ask(repair_env.employee, "云帆文创 2026 年一季度净利润是多少？")
    assert answer["kind"] == "answer", answer
    assert "300" in answer["text"], answer["text"]
    assert answer["sources"], answer


# ---------------------------------------------------------------- 实际分流钉住（trace path）


def _ask_raw(session: SimpleNamespace, question: str):
    created = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert created.status_code == 201, created.text
    return session.client.post(
        f"/api/v1/conversations/{created.json()['id']}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )


def test_m1_financial_question_routes_legacy_not_rag(repair_trace_env: SimpleNamespace) -> None:
    """分流证据：财务指标问题被规划为 document，_rag_owns_turn 不接手，实际走 legacy。

    本包对共享函数 texts_support_financial_metric 的修复以 legacy 消费路径为红例依据；
    不声称修了 RAG 直答路径（该路径对此类问题不可达，见 report）。
    """
    _publish_docx(repair_trace_env, "m1_route.docx", M1_UNSUPPORTED_PARAGRAPHS)
    response = _ask_raw(repair_trace_env.employee, "云帆文创本季度的毛利是多少？")
    assert response.status_code == 200, response.text
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id, "开启 Trace 时 QA POST 必须返回 X-Trace-ID"
    trace, _spans = repair_trace_env.app.state.trace_repo.get(trace_id)
    assert trace.path == "legacy", trace.path


# ---------------------------------------------------------------- M1 RAG 直答消费路径（共享函数）

#: 记录表：建立“城东店”门店实体，使“列出城东店所有物品的毛利”被规划为 record+enumerate。
M1_RAG_RECORD_HEADERS = ["门店", "物品", "位置"]
M1_RAG_RECORD_ROWS = [
    ["城东店", "宣传海报", "B区1号货架第二层"],
    ["城东店", "展架", "A区2号货架底层"],
]
#: 正文：含“毛利”词 + 无关编号/日期，无毛利取值。
M1_RAG_TEXT_PARAGRAPHS = [
    "城东店门店编号 YF-07 于 2026-03-12 提交毛利影响测算，等待财务复核。",
]


def test_m1_rag_enumerate_metric_with_irrelevant_numbers_refuses(
    repair_trace_env: SimpleNamespace,
) -> None:
    """M1 RAG 红例：record+enumerate 财务词问题走 RAG 直答，共享同一支持判定函数。

    “列出城东店所有物品的毛利”被规划为 record+enumerate+store → _rag_owns_turn=True；
    候选只有无关编号/日期邻近“毛利”时应拒答（UNSUPPORTED_FINANCIAL_METRIC），不得作答。
    """
    _publish_xlsx(repair_trace_env, "m1_rag_records.xlsx", M1_RAG_RECORD_HEADERS, M1_RAG_RECORD_ROWS)
    _publish_docx(repair_trace_env, "m1_rag_text.docx", M1_RAG_TEXT_PARAGRAPHS)
    calls_before = len(repair_trace_env.model.calls)
    response = _ask_raw(repair_trace_env.employee, "列出城东店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id
    trace, _spans = repair_trace_env.app.state.trace_repo.get(trace_id)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert "没有可支撑" in answer["text"], answer["text"]
    assert answer["sources"] == [], answer
    assert len(repair_trace_env.model.calls) == calls_before, repair_trace_env.model.calls


#: 记录行布局：把“毛利”词 + 无关编号/日期放进记录单元，使其进入 RAG 记录枚举候选集。
M1_RAG_RECORD_METRIC_HEADERS = ["门店", "物品", "位置"]
M1_RAG_RECORD_METRIC_ROWS = [
    ["城东店", "宣传海报", "B区1号货架第二层"],
    ["城东店", "毛利影响测算", "编号YF-07 日期2026-03-12"],
]


def test_m1_rag_record_metric_text_with_irrelevant_numbers_refuses(
    repair_trace_env: SimpleNamespace,
) -> None:
    """M1 RAG 红例（记录行布局）：指标词+无关数字进入 RAG 候选集时应拒答。

    与上一用例的区别：无关数字随记录行进入 record 枚举候选，共享函数
    texts_support_financial_metric 经 RAG 路径真实消费；窗口误判会使其作答。
    """
    _publish_xlsx(
        repair_trace_env,
        "m1_rag_record_metric.xlsx",
        M1_RAG_RECORD_METRIC_HEADERS,
        M1_RAG_RECORD_METRIC_ROWS,
    )
    calls_before = len(repair_trace_env.model.calls)
    response = _ask_raw(repair_trace_env.employee, "列出城东店所有物品的毛利")
    assert response.status_code == 200, response.text
    answer = response.json()
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id
    trace, _spans = repair_trace_env.app.state.trace_repo.get(trace_id)
    assert trace.path == "rag", trace.path
    assert answer["kind"] == "not_found", answer
    assert "没有可支撑" in answer["text"], answer["text"]
    assert answer["sources"] == [], answer
    assert len(repair_trace_env.model.calls) == calls_before, repair_trace_env.model.calls