"""T-R1-107（R2）：C22 的**越店取值泄漏形态**在 HTTP 路径上的独立复核。

``test_r1_107_http_c13_c22.py`` 钉了业务基准日（2026-10-28），覆盖的是"异店未来生效 →
只写状态说明"形态；那时异店行被子句有效期窗口挡在证据之外，答案即便回归成改前行为也只能
表现为"未在资料中找到"（拒答形态）。

本文件**不钉业务基准日**：异店行按"未声明有效期窗口"参与候选，改前行为会直接把异店行渲染
进答案/引用（C22 的核心违规：数值与引用来自异店）。因此这里断言的是**取值面本身**：

- 答案含目标门店值 ``甲区一层``；
- 答案不得出现异店位置值 ``乙区二层``（也不得出现其生效日期 2026-12-01）；
- ``sources`` 只 1 条，定位到甲店那一行（row=4）。

全部合成数据；``t09_network_guard`` 断言外部出站尝试为 0。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

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

HEADERS = ["门店", "物品", "位置", "生效日期"]
ROWS = [
    ["甲店", "宣传海报", "甲区一层", None],
    ["乙店", "宣传海报", "乙区二层", "2026-12-01"],
]
QUESTION = "甲店的宣传海报放在哪？乙店有一条尚未生效的登记，现在能作为取用依据吗？"


@pytest.fixture
def settings(store) -> Settings:
    """与 ``tests/conftest.py`` 逐字段相同；**不设** ``rag_business_date``（见模块说明）。"""
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
    )


def _xlsx(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value="终端物料位置表")
    for column, header in enumerate(HEADERS, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(ROWS):
        for column, value in enumerate(row, start=1):
            if value is not None:
                worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _publish(app, admin, path: Path) -> None:
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


def test_c22_cross_store_value_never_rendered_over_http(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    _publish(
        chat_app,
        chat_admin,
        _xlsx(Path(chat_app.state.settings.data_dir) / "终端物料位置表.xlsx"),
    )
    created = chat_employee.client.post(
        "/api/v1/conversations", json={}, headers=chat_employee.headers
    )
    assert created.status_code == 201, created.text

    body = _ask(chat_employee, created.json()["id"], QUESTION)

    assert body["kind"] == "answer", body
    assert "甲区一层" in body["text"], body["text"]
    # 越店取值（改前行为）会把异店行渲染进答案：位置值与生效日期都不得出现。
    assert "乙区二层" not in body["text"], body["text"]
    assert "2026-12-01" not in body["text"], body["text"]
    assert len(body["sources"]) == 1, body["sources"]
    assert _source_rows(body) == {4}, body["sources"]
