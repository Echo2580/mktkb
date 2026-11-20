"""T-R1-107（R2 复验）：C13/C22 形的**产品 HTTP 真实路径**独立复核。

同形红例已在 RAG/legacy 层建立（`tests/rag/test_r1_106a_legacy_store_scope.py`、
`tests/rag/test_r1_106b_primary_store_target.py`）。本文件把两条案型搬到产品入口
``POST /api/v1/conversations/{id}/messages``，并走**真实摄取链**
（上传 → worker 解析/建索引 → 发布），与 ``test_r1_103_http_*`` 同一套夹具写法：

- C13 形：甲店立牌位置 → 政策题（docx 正文，无门店列，属共享背景）→ 裸追问楼层。
  第 1/3 回合的 ``sources`` 与模型证据都不得含乙店行，答案只出甲区；政策题不受
  单店作用域影响（正文照答）。
- C22 形：一句同时提甲店（问位置）与乙店（尚未生效登记）。答案只取甲店值，
  ``sources`` 只 1 条（甲店行）；乙店只出现名称/状态/有效期，不渲染其行值。
  反例对照：显式“两家都列出来”仍两家作答（不得误收窄）。

业务基准日钉在 ``2026-10-28``：C22 的“尚未生效”判定依赖进程级
``Settings.rag_business_date``（产品无请求级注入入口，故本模块覆盖装配）。
全部合成数据；``t09_network_guard`` 逐例校验外部出站尝试为 0。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import docx
import openpyxl
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.config import Settings  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

#: C22 业务基准日（乙店的 2026-12-01 登记在该日之后 → 尚未生效）。
BUSINESS_DATE = "2026-10-28"

# --------------------------------------------------------------------------- #
# 装配：与 tests/conftest.py 的 settings 逐字段相同，只额外钉住业务基准日
# --------------------------------------------------------------------------- #


@pytest.fixture
def settings(store) -> Settings:
    database = store.root / "mktkb.sqlite3"
    return Settings(
        _env_file=None,
        data_dir=store.root,
        database_url=f"sqlite:///{database.as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="INFO",
        rag_business_date=BUSINESS_DATE,
    )


# --------------------------------------------------------------------------- #
# 合成语料（假实体、假值）
# --------------------------------------------------------------------------- #

ITEM_HEADERS = ["门店", "物品", "位置"]
ITEM_ROWS = [
    ["甲店", "立牌", "甲区"],
    ["乙店", "立牌", "乙区"],
]
POLICY = "调拨必须由区域经理同意。"
C22_HEADERS = ["门店", "物品", "位置", "生效日期"]
C22_ROWS = [
    ["甲店", "宣传海报", "甲区一层", None],
    ["乙店", "宣传海报", "乙区二层", "2026-12-01"],
    # 反例对照用：两店各一行**当前有效**的易拉宝记录（显式“都列出来”仍要两家）。
    ["甲店", "易拉宝", "甲区三层", None],
    ["乙店", "易拉宝", "乙区四层", None],
]

#: C13 形三回合：点名甲店 → 换话题（政策正文）→ 裸追问楼层（不再提门店）。
TURN_SCOPE = "甲店的立牌位置在哪？"
TURN_TOPIC = "调拨需要谁同意？"
TURN_BARE = "立牌现在放在哪个货架？"
#: 106a 建立时实际走 legacy 的裸追问问法（真调模型，证据面可见）。
TURN_LEGACY = "“展示牌”和“立牌”是同一件吗？现在登记的货架是哪一层？"
TURN_OTHER_STORE = "乙店的立牌放在哪？"

#: C22 形冻结问句：两家门店同现，但只有甲店是被问目标。
C22_QUESTION = "甲店的宣传海报放在哪？乙店有一条尚未生效的登记，现在能作为取用依据吗？"


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], title: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            if value is not None:
                worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _docx(path: Path, paragraph: str) -> Path:
    document = docx.Document()
    document.add_paragraph(paragraph)
    document.save(str(path))
    return path


def _publish(app, admin, path: Path) -> str:
    """上传 → worker 解析/建索引 → 发布（真实摄取链，非直写数据库）。"""
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
    return str(record["document"]["id"])


def _corpus_c13(app, admin) -> str:
    data_dir = Path(app.state.settings.data_dir)
    _publish(
        app,
        admin,
        _xlsx(data_dir / "物品位置表.xlsx", ITEM_HEADERS, ITEM_ROWS, "物品位置表"),
    )
    return _publish(app, admin, _docx(data_dir / "调拨制度.docx", POLICY))


def _corpus_c22(app, admin) -> None:
    data_dir = Path(app.state.settings.data_dir)
    _publish(
        app,
        admin,
        _xlsx(data_dir / "终端物料位置表.xlsx", C22_HEADERS, C22_ROWS, "终端物料位置表"),
    )


# --------------------------------------------------------------------------- #
# 会话辅助
# --------------------------------------------------------------------------- #


def _new_conversation(session) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session, conversation_id: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _source_rows(body: dict) -> set[int]:
    return {
        int(item["locator"]["row"])
        for item in body.get("sources") or []
        if isinstance(item.get("locator"), dict) and isinstance(item["locator"].get("row"), int)
    }


def _answer_calls(chat_model, start: int) -> list[list[dict]]:
    return [call["evidence"] for call in chat_model.calls[start:] if call["purpose"] == "answer"]


def _evidence_texts(calls: list[list[dict]]) -> str:
    return "\n".join(str(item.get("text") or "") for evidence in calls for item in evidence)


# --------------------------------------------------------------------------- #
# C13：三回合（甲店 → 政策题 → 裸追问）只出甲店行
# --------------------------------------------------------------------------- #


def test_c13_bare_followup_over_http_keeps_unique_store_scope(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    _corpus_c13(chat_app, chat_admin)
    conversation_id = _new_conversation(chat_employee)

    mark = len(chat_model.calls)
    first = _ask(chat_employee, conversation_id, TURN_SCOPE)
    assert first["kind"] == "answer", first
    assert "甲区" in first["text"], first["text"]
    assert "乙区" not in first["text"], first["text"]
    assert _source_rows(first) == {4}, first["sources"]
    first_calls = _answer_calls(chat_model, mark)
    assert first_calls, "第 1 回合必须真实调用模型（legacy 路径）"
    assert "乙店" not in _evidence_texts(first_calls), _evidence_texts(first_calls)

    mark = len(chat_model.calls)
    topic = _ask(chat_employee, conversation_id, TURN_TOPIC)
    assert topic["kind"] == "answer", topic
    assert "区域经理" in topic["text"], topic["text"]
    # 政策题不受单店作用域影响：正文单元不是门店行，仍作为来源。
    assert _source_rows(topic) == set(), topic["sources"]
    assert topic["sources"], topic["sources"]

    mark = len(chat_model.calls)
    third = _ask(chat_employee, conversation_id, TURN_BARE)
    assert third["kind"] == "answer", third
    assert "甲区" in third["text"], third["text"]
    assert "乙区" not in third["text"], "裸追问不得混入另一门店的记录"
    assert third["sources"], third["sources"]
    assert _source_rows(third) == {4}, third["sources"]
    # 该问法可能落结构化内核（不动模型）；若走了模型，证据面同样不得含乙店行。
    third_calls = _answer_calls(chat_model, mark)
    assert "乙店" not in _evidence_texts(third_calls), _evidence_texts(third_calls)

    # 可达性对照：同一语料显式点名乙店必须答出乙区（乙区并非不可达）。
    other_conversation = _new_conversation(chat_employee)
    other = _ask(chat_employee, other_conversation, TURN_OTHER_STORE)
    assert other["kind"] == "answer", other
    assert "乙区" in other["text"], other["text"]
    assert "甲区" not in other["text"], other["text"]
    assert _source_rows(other) == {5}, other["sources"]


def test_c13_legacy_followup_evidence_excludes_other_store(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    """legacy 路径见证（106a 修复面）：裸追问真走模型时，证据面同样只有甲店行。"""
    _corpus_c13(chat_app, chat_admin)
    conversation_id = _new_conversation(chat_employee)

    _ask(chat_employee, conversation_id, TURN_SCOPE)
    _ask(chat_employee, conversation_id, TURN_TOPIC)

    mark = len(chat_model.calls)
    third = _ask(chat_employee, conversation_id, TURN_LEGACY)
    assert third["kind"] == "answer", third
    assert "甲区" in third["text"], third["text"]
    assert "乙区" not in third["text"], third["text"]
    assert 5 not in _source_rows(third), third["sources"]
    calls = _answer_calls(chat_model, mark)
    assert calls, "legacy 问法必须真实调用模型"
    assert "乙店" not in _evidence_texts(calls), _evidence_texts(calls)
    assert "乙区" not in _evidence_texts(calls), _evidence_texts(calls)


# --------------------------------------------------------------------------- #
# C22：多门店同现时只取被问目标门店
# --------------------------------------------------------------------------- #


def test_c22_primary_store_target_over_http(chat_app, chat_admin, chat_employee, chat_model) -> None:
    _corpus_c22(chat_app, chat_admin)
    conversation_id = _new_conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, C22_QUESTION)

    assert body["kind"] == "answer", body
    # 目标门店的值必须命中；异店那一行的位置值不得渲染。
    assert "甲区一层" in body["text"], body["text"]
    assert "乙区二层" not in body["text"], body["text"]
    # 目标门店有记录，不得反过来说它“没有匹配记录”。
    assert "未在资料中找到" not in body["text"], body["text"]
    # 引用只 1 条，且是甲店那一行（异店行不作为依据）。
    assert len(body["sources"]) == 1, body["sources"]
    assert _source_rows(body) == {4}, body["sources"]
    # 异店只出现名称 + 状态 + 有效期（日期以外的行值不渲染）。
    assert "乙店" in body["text"], body["text"]
    assert "尚未生效" in body["text"], body["text"]
    assert "2026-12-01" in body["text"], body["text"]


def test_c22_explicit_list_of_both_stores_still_answers_both(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    """反例对照：显式“都列出来”仍两家作答，不得因主目标判定误收窄。"""
    _corpus_c22(chat_app, chat_admin)
    conversation_id = _new_conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, "甲店和乙店的易拉宝位置都列出来。")

    assert body["kind"] == "answer", body
    assert "甲区三层" in body["text"], body["text"]
    assert "乙区四层" in body["text"], body["text"]
    assert _source_rows(body) == {6, 7}, body["sources"]
