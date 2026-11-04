"""T09-D6 R2 回归：真实表格 OCR 返回形态可安全入库 + 失败态保留供应商 RequestId。

背景（IA-T09-QWEN-20261031-74665ff1 §1.2 失败二）：
- 真实 ``RecognizeTableAccurateOCR`` HTTP 200 返回 4 个表格（``Cells`` 数 ``[1,1,12,1]``），
  首个表格的唯一单元格 ``RowTl/ColTl/RowBr/ColBr`` 全为 ``-1``，单元格带 ``Type`` 字段；
- 旧实现 ``tencent_ocr.py:377-381`` 对任何负坐标直接抛 ``OCR_INVALID_OUTPUT``，D10 无法入库；
- 失败态 ``ocr_call_records.provider_request_id`` 为 ``None``，供应商 RequestId 丢失。

本文件用该**响应结构**（表格数/单元格数/首表 -1 坐标/Type 字段）加 D10 图片的真实表格事实
构造 mock（本地 ``httpx.MockTransport``，0 次真实调用）：
1. 可解析入库：D10 上传→worker→review_required→发布→Q39/Q40 可达，且不伪造坐标/置信度；
2. ``-1`` 单元格不再让整份资料失败；无法解析的坐标形态仍返回稳定 ``OCR_INVALID_OUTPUT``；
3. 成功与失败都把供应商 RequestId 的**不可逆哈希引用**（S2-J2-R1：不落原文）持久化到
   ``ocr_call_records.provider_request_id``；
4. ``GeneralAccurateOCR``（D09 路径）不回归。
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from mktkb.ingestion.models import OCRCallRecord
from mktkb.ingestion.worker import run_one_job
from mktkb.providers.tencent_ocr import TencentOCRClient
from mktkb.providers.types import OCRInput, OCRInvalidOutput

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D10 = FIXTURES / "normal" / "D10_盘点通知.jpg"

# IA 台账 live-04 捕获的真实 RequestId（``RecognizeTableAccurateOCR`` 200）。
IA_REQUEST_ID = "04903f3a-70fe-452e-8ade-c0a301857473"
GENERAL_REQUEST_ID = "5322b093-1e23-4c59-b25d-d4fc457f455a"  # IA 台账 R7（GeneralAccurateOCR）


def _expected_ref(raw: str) -> str:
    """S2-J2-R1：外部供应商 RequestId 在结果/审计/账本中只允许不可逆哈希引用。"""
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

# D10 图片的真实表格事实（与 support/ocr_transcripts.py 的 D10 转录同源：绘制生成器写入图片的原文）。
D10_HEADER: tuple[str, ...] = ("门店", "物品", "盘点时间", "盘点地点")
D10_ROWS: tuple[tuple[str, ...], ...] = (
    ("城东店", "宣传海报", "2026-10-30 16:00", "城东店物料区"),
    ("城西店", "宣传海报", "2026-10-31 15:30", "城西店二层仓库"),
)

SECRET_ID = "AKID-T09-D6-FAKE-OCR-ID"
SECRET_KEY = "T09-D6-FAKE-OCR-KEY-NEVER-REAL"
TIMESTAMP = 1_700_000_000


# ---------------------------------------------------------------- IA 响应结构构造


def _cell(
    text: str,
    row_tl: int,
    col_tl: int,
    row_br: int,
    col_br: int,
    *,
    confidence: int = 90,
    polygon: list[dict] | None = None,
    cell_type: str = "text",
) -> dict:
    """IA 台账观测到的单元格键：ColBr/ColTl/Confidence/Polygon/RowBr/RowTl/Text/Type。"""
    return {
        "RowTl": row_tl,
        "ColTl": col_tl,
        "RowBr": row_br,
        "ColBr": col_br,
        "Text": text,
        "Confidence": confidence,
        "Polygon": [] if polygon is None else polygon,
        "Type": cell_type,
    }


def _table_cells(header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> list[dict]:
    cells: list[dict] = []
    for row_index, row in enumerate((header, *rows)):
        for col_index, text in enumerate(row):
            polygon = (
                [
                    {"X": 10, "Y": 20},
                    {"X": 50, "Y": 20},
                    {"X": 50, "Y": 40},
                    {"X": 10, "Y": 40},
                ]
                if row_index == 0 and col_index == 0
                else []
            )
            cells.append(_cell(text, row_index, col_index, row_index + 1, col_index + 1, polygon=polygon))
    return cells


def _ia_table_response(*, first_cell_text: str = "") -> dict:
    """IA 捕获的表格响应结构：4 个表格、Cells [1,1,12,1]、首表唯一单元格坐标全 -1、含 Type。"""
    return {
        "Response": {
            "Angle": 0.0,
            "Data": {},
            "PdfPageSize": {"Width": 1240.0, "Height": 620.0},
            "RequestId": IA_REQUEST_ID,
            "TableDetections": [
                {
                    "Cells": [_cell(first_cell_text, -1, -1, -1, -1, confidence=0, cell_type="table")],
                    "TableCoordPoint": [],
                    "Type": "table",
                },
                {
                    "Cells": [_cell("", 0, 0, 1, 1, cell_type="table")],
                    "TableCoordPoint": [],
                    "Type": "table",
                },
                {
                    "Cells": _table_cells(D10_HEADER, D10_ROWS),
                    "TableCoordPoint": [
                        {"X": 10, "Y": 20},
                        {"X": 50, "Y": 20},
                        {"X": 50, "Y": 40},
                        {"X": 10, "Y": 40},
                    ],
                    "Type": "table",
                },
                {
                    "Cells": [_cell("", 0, 0, 1, 1, cell_type="table")],
                    "TableCoordPoint": [],
                    "Type": "table",
                },
            ],
        }
    }


def _client(handler) -> TencentOCRClient:
    return TencentOCRClient(
        secret_id=SECRET_ID,
        secret_key=SECRET_KEY,
        region="ap-guangzhou",
        timeout_seconds=10.0,
        transport=httpx.MockTransport(handler),
        clock=lambda: TIMESTAMP,
    )


def _input() -> OCRInput:
    return OCRInput(content=b"\x89PNG\r\n\x1a\nfake-d10-bytes", mime_type="image/png", page=1)


def _ocr_records(app, version_id) -> list[dict]:
    db = app.state.db.session()
    try:
        rows = db.scalars(
            select(OCRCallRecord)
            .where(OCRCallRecord.version_id == uuid.UUID(str(version_id)))
            .order_by(OCRCallRecord.created_at, OCRCallRecord.attempt)
        ).all()
        return [
            {
                "state": row.state,
                "error_code": row.error_code,
                "provider_request_id": row.provider_request_id,
                "confidence": row.confidence,
                "has_result": row.result is not None,
            }
            for row in rows
        ]
    finally:
        db.close()


# ---------------------------------------------------------------- 解析：IA 真实形态


def test_ia_table_shape_parses_without_fabricating_coordinates():
    """首表 -1 哨兵单元格不再让整份响应失败；表格按供应商行列恢复，坐标只来自 Polygon。"""
    client = _client(lambda request: httpx.Response(200, json=_ia_table_response()))

    result = client.recognize(_input(), mode="table")

    assert result.table_rows == (D10_HEADER, *D10_ROWS), result.table_rows
    assert result.provider_request_id == _expected_ref(IA_REQUEST_ID)
    assert result.confidence == 90.0, "置信度只取供应商返回值"
    regions = [region for region in result.regions if region.get("text")]
    assert len(regions) == len(D10_HEADER) + sum(len(row) for row in D10_ROWS), regions
    header_region = next(region for region in regions if region["text"] == "门店")
    assert header_region["bbox"] == [10.0, 20.0, 50.0, 40.0], "bbox 必须回映供应商 Polygon"
    assert all("bbox" not in region for region in regions if region["text"] != "门店")
    assert "门店 | 物品 | 盘点时间 | 盘点地点" in result.text


def test_unplaceable_cell_text_is_kept_without_coordinates():
    """``-1`` 单元格若带文字：只保留文字，不伪造坐标、不生成表格行。"""
    client = _client(lambda request: httpx.Response(200, json=_ia_table_response(first_cell_text="盘点通知")))

    result = client.recognize(_input(), mode="table")

    assert result.table_rows == (D10_HEADER, *D10_ROWS), result.table_rows
    assert result.text.splitlines()[0] == "盘点通知", result.text
    assert all(region.get("text") != "盘点通知" for region in result.regions)


@pytest.mark.parametrize("mutate", ["non_integer", "inverted_span"])
def test_unparseable_cell_still_returns_stable_error_with_request_id(mutate):
    """无法解析的坐标形态仍返回稳定 OCR_INVALID_OUTPUT，并携带供应商 RequestId。"""
    response = _ia_table_response()
    first_cell = response["Response"]["TableDetections"][2]["Cells"][0]
    if mutate == "non_integer":
        first_cell["RowTl"] = "0"
    else:
        first_cell["RowBr"] = first_cell["RowTl"]

    with pytest.raises(OCRInvalidOutput) as excinfo:
        _client(lambda request: httpx.Response(200, json=response)).recognize(_input(), mode="table")

    assert excinfo.value.code == "OCR_INVALID_OUTPUT"
    assert excinfo.value.provider_request_id == _expected_ref(IA_REQUEST_ID)


# ---------------------------------------------------------------- GeneralAccurateOCR 不回归


def test_general_ocr_path_unchanged_and_carries_request_id():
    response = {
        "Response": {
            "RequestId": GENERAL_REQUEST_ID,
            "TextDetections": [
                {
                    "DetectedText": "物料领用通知",
                    "Confidence": 99,
                    "Polygon": [
                        {"X": 10, "Y": 20},
                        {"X": 50, "Y": 20},
                        {"X": 50, "Y": 40},
                        {"X": 10, "Y": 40},
                    ],
                }
            ],
        }
    }
    result = _client(lambda request: httpx.Response(200, json=response)).recognize(_input(), mode="text")
    assert result.text == "物料领用通知"
    assert result.provider_request_id == _expected_ref(GENERAL_REQUEST_ID)
    assert result.confidence == 99.0
    assert result.regions[0]["bbox"] == [10.0, 20.0, 50.0, 40.0]

    bad = {"Response": {"RequestId": GENERAL_REQUEST_ID, "TextDetections": [{"DetectedText": 1}]}}
    with pytest.raises(OCRInvalidOutput) as excinfo:
        _client(lambda request: httpx.Response(200, json=bad)).recognize(_input(), mode="text")
    assert excinfo.value.provider_request_id == _expected_ref(GENERAL_REQUEST_ID)


# ---------------------------------------------------------------- 端到端：D10 入库/发布/问答


def _upload_and_run(chat_admin, app, response_handler) -> tuple[dict, object]:
    receipt = chat_admin.upload(path=D10)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    client = _client(response_handler)
    db = app.state.db.session()
    try:
        result = run_one_job(db, app.state.store, ocr=client)
    finally:
        db.close()
    return record, result


def test_d10_ia_table_shape_publishes_and_answers_q39_q40(chat_app, chat_admin, chat_employee):
    record, result = _upload_and_run(
        chat_admin, chat_app, lambda request: httpx.Response(200, json=_ia_table_response())
    )
    assert result.state == "succeeded", (result.state, result.error_code)

    document_id = record["document"]["id"]
    version_id = record["version"]["id"]
    detail = chat_admin.client.get(f"/api/v1/documents/{document_id}").json()
    version = next(item for item in detail["versions"] if item["id"] == version_id)
    assert version["state"] == "review_required", version

    published = chat_admin.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": None, "expected_revision": detail["revision"]},
        headers=chat_admin.headers,
    )
    assert published.status_code == 200, published.text

    q39 = _ask(chat_employee, "盘点通知中城东店海报的盘点时间是什么？")
    assert q39["kind"] == "answer", q39
    assert "2026-10-30 16:00" in q39["text"], q39["text"]
    assert "2026-10-31 15:30" not in q39["text"], q39["text"]
    assert any(source["document_name"].startswith("D10") for source in q39["sources"]), q39["sources"]

    q40 = _ask(chat_employee, "盘点通知中城东店海报的盘点地点是什么？")
    assert q40["kind"] == "answer", q40
    assert "城东店物料区" in q40["text"], q40["text"]
    assert "城西店二层仓库" not in q40["text"], q40["text"]

    records = _ocr_records(chat_app, version_id)
    assert records and all(item["state"] == "succeeded" for item in records), records
    assert all(
        item["provider_request_id"] == _expected_ref(IA_REQUEST_ID) for item in records
    ), records


def test_failed_table_ocr_persists_provider_request_id(chat_app, chat_admin):
    def handler(request):
        response = _ia_table_response()
        response["Response"]["TableDetections"][2]["Cells"][0]["RowTl"] = "0"
        return httpx.Response(200, json=response)

    record, result = _upload_and_run(chat_admin, chat_app, handler)
    assert result.state == "failed", result
    assert result.error_code == "OCR_INVALID_OUTPUT", result

    detail = chat_admin.client.get(f"/api/v1/documents/{record['document']['id']}").json()
    version = next(item for item in detail["versions"] if item["id"] == record["version"]["id"])
    assert version["state"] == "failed", version

    records = _ocr_records(chat_app, record["version"]["id"])
    assert len(records) == 1, records
    assert records[0]["state"] == "failed", records
    assert records[0]["error_code"] == "OCR_INVALID_OUTPUT", records
    assert records[0]["provider_request_id"] == _expected_ref(IA_REQUEST_ID), records
    assert records[0]["has_result"] is False, records


def _ask(ns, question: str) -> dict:
    created = ns.client.post("/api/v1/conversations", json={}, headers=ns.headers)
    assert created.status_code == 201, created.text
    conversation = created.json()["id"]
    response = ns.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=ns.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()
