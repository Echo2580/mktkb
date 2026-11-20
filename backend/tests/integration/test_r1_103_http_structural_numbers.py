"""T-R1-103：M1（整行渲染结构数字）与 M2（枚举页头计数）走产品 HTTP 路径，打到打分层。

只走产品入口（``POST /api/v1/conversations/{id}/messages``），再把**真实响应**作为
``product`` 交给 P2 打分（``score_public_case``）——断言的是 ``value_no_fabricated``
端到端是否被结构数字误判，不是评测器的单元行为。

每个"通过"都配一条**对照**：把该数字的唯一出处从产品响应副本里去掉（不改产品代码），
同一答案必须立刻被判编造。对照失败说明允许集合另有来源（断言不空转）。

全部合成数据（甲店/乙店、立牌、甲区/乙区、标识 PA…PN），零真实外呼：
``t09_network_guard`` 在用例结束前校验出站尝试为 0。
"""

from __future__ import annotations

import asyncio
import copy
import functools
import sys
import uuid
from pathlib import Path
from typing import Any

import openpyxl
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门（不复制实现）
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_scoring import score_public_case  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from mktkb.ingestion.worker import run_one_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ITEM_HEADERS = ["门店", "物品", "位置"]
TWO_ROWS = [
    ["甲店", "立牌", "甲区"],
    ["乙店", "立牌", "乙区"],
]
ENUM_QUESTION = "把甲店和乙店的立牌记录都列出来"

#: 14 行、10 行一页：页头的 ``total``(14) 与 ``returned``(10) 都不在首页被引记录的
#: locator 整数里（行号 4..17 的子集、表头行 3、列序号 1..5），只能由产品分页背书。
MANY_HEADERS = ["门店", "物品", "别名", "标识", "位置"]
_MANY_NAMES = "一二三四五六七八九十甲乙丙丁"
MANY_ROWS = [
    [
        "甲店" if index % 2 else "乙店",
        "立牌",
        f"立牌{cn}",
        f"P{chr(64 + index)}",
        "甲区" if index % 2 else "乙区",
    ]
    for index, cn in enumerate(_MANY_NAMES, start=1)
]


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], title: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _ingest(app, admin, table: tuple[str, list[str], list[list[object]], str]) -> None:
    """走产品上传 -> worker 解析 -> 发布；只写临时数据目录。"""
    name, headers, rows, title = table
    path = _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, title)
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


def _new_conversation(session) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _score(question: str, product: dict):
    """把真实 HTTP 响应当作 product 交给 P2 打分（文档名 -> 代号显式绑定，不猜）。"""
    case = CaseSpec(
        case_id="R1-103-M1M2",
        suite="p2-r1-103",
        split="public",
        stratum="synthetic",
        business_date="2026-11-17",
        question=question,
        turns=({"turn": 1, "question": question},),
        expected_kind="answer",
        expected_values=("甲区", "乙区"),
        reference_answer="",
    )
    document_codes = {
        str(item.get("document_name")): "D-R1103"
        for item in product.get("sources") or []
        if item.get("document_name")
    }
    case_row = {
        "case_id": case.case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": ({"turn": 1, "status": "ok", "product": product},),
    }
    return score_public_case(
        case,
        case_row,
        document_codes=document_codes,
        allowed_doc_codes=None,
    )


def _check(scored, check_id: str) -> dict:
    found = [item for item in scored.score.checks if item.get("check_id") == check_id]
    assert len(found) == 1, (check_id, scored.score.checks)
    return found[0]


def _strip_locator_row(product: dict) -> dict:
    """对照用：只从产品响应副本的 locator 去掉 `row`（不改产品代码/不改正文）。"""
    copied = copy.deepcopy(product)
    for source in copied.get("sources") or []:
        locator = source.get("locator")
        if isinstance(locator, dict):
            locator.pop("row", None)
    return copied


def _without_pagination(product: dict) -> dict:
    """对照用：只从产品响应副本去掉 `pagination`（正文页头保持原样）。"""
    copied = copy.deepcopy(product)
    copied["pagination"] = None
    return copied


# --------------------------------------------------------------------------- #
# M1：整行渲染（含「第 N 行」「（记录 …）」）在 P2 打分端到端不判编造
# --------------------------------------------------------------------------- #


def test_m1_full_row_render_scores_without_fabrication(chat_app, chat_admin, chat_employee, chat_model) -> None:
    _ingest(chat_app, chat_admin, ("物品位置表.xlsx", ITEM_HEADERS, TWO_ROWS, "物品位置表"))
    conversation_id = _new_conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, ENUM_QUESTION)

    assert body["kind"] == "answer", body
    assert "第 4 行" in body["text"] and "第 5 行" in body["text"], body["text"]
    assert "（记录 " in body["text"], "整行渲染必须带稳定记录标记"
    assert "甲区" in body["text"] and "乙区" in body["text"], body["text"]

    scored = _score(ENUM_QUESTION, body)
    fabricated = _check(scored, "value_no_fabricated")
    assert fabricated["status"] == "pass", fabricated
    assert _check(scored, "value_hit")["status"] == "pass"

    # 对照：行的唯一结构出处被去掉后，同一答案里的行号必须被判编造。
    broken = _score(ENUM_QUESTION, _strip_locator_row(body))
    broken_check = _check(broken, "value_no_fabricated")
    assert broken_check["status"] == "fail", broken_check
    assert broken_check["evidence"]["extra"] == ["4", "5"], broken_check


# --------------------------------------------------------------------------- #
# M2：枚举页头计数由产品分页背书；缺分页时同一答案必须判编造
# --------------------------------------------------------------------------- #


def test_m2_enumeration_header_counts_are_grounded_by_product_pagination(
    chat_app, chat_admin, chat_employee, chat_model
) -> None:
    _ingest(chat_app, chat_admin, ("多行物料表.xlsx", MANY_HEADERS, MANY_ROWS, "多行物料表"))
    conversation_id = _new_conversation(chat_employee)

    body = _ask(chat_employee, conversation_id, ENUM_QUESTION)

    assert body["kind"] == "answer", body
    pagination = body.get("pagination")
    assert pagination == {
        "page": 1,
        "page_size": 10,
        "total": 14,
        "returned": 10,
        "has_more": True,
        "next_page": 2,
    }, pagination
    assert "共 14 条，当前第 1 页显示 10 条" in body["text"], body["text"]

    scored = _score(ENUM_QUESTION, body)
    fabricated = _check(scored, "value_no_fabricated")
    assert fabricated["status"] == "pass", fabricated
    assert _check(scored, "value_hit")["status"] == "pass"

    # 去掉分页后，页头总数、当前页、返回条数和续页提示均失去结构证据。
    broken = _score(ENUM_QUESTION, _without_pagination(body))
    broken_check = _check(broken, "value_no_fabricated")
    assert broken_check["status"] == "fail", broken_check
    extra = set(broken_check["evidence"]["extra"])
    assert extra == {"1", "2", "10", "14"}, broken_check


# --------------------------------------------------------------------------- #
# M2 端到端（评测采集侧）：ProductTurn.as_dict() 必须把分页带进打分行
# --------------------------------------------------------------------------- #


def asyncio_test(func):
    """仓库没有 pytest-asyncio：同一事件循环跑一个 async 用例（沿用 p2 e2e 写法）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _empty_dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "r1103-e2e-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "d" * 64,
            "case_count": 0,
        },
    )


@asyncio_test
async def test_m2_product_turn_carries_pagination_into_scoring(tmp_path: Path) -> None:
    """产品 HTTP 响应 -> ProductTurn.pagination -> as_dict -> 打分行（102d 的采集链路）。"""
    source = _xlsx(tmp_path / "多行物料表.xlsx", MANY_HEADERS, MANY_ROWS, "多行物料表")
    adapter = ProductEvalAdapter(
        tmp_path / "adapter",
        chat=MockChatBackend(),
        dataset=_empty_dataset(),
        ingest_plan=P2IngestPlan(sources=(IngestSource(path=source),), label="r1103-e2e"),
    )
    try:
        receipts = await adapter.ingest()
        assert receipts[0].published is True, receipts
        conversation_id = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            ENUM_QUESTION,
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id=str(uuid.uuid4()),
        )
        product = turn.as_dict(include_text=True)
    finally:
        await adapter.close()

    assert product["kind"] == "answer", product
    assert product["pagination"] == {
        "page": 1,
        "page_size": 10,
        "total": 14,
        "returned": 10,
        "has_more": True,
        "next_page": 2,
    }, product["pagination"]
    assert "共 14 条，当前第 1 页显示 10 条" in product["text"], product["text"]

    scored = _score(ENUM_QUESTION, product)
    fabricated = _check(scored, "value_no_fabricated")
    assert fabricated["status"] == "pass", fabricated

    broken = _check(_score(ENUM_QUESTION, _without_pagination(product)), "value_no_fabricated")
    assert broken["status"] == "fail", broken

