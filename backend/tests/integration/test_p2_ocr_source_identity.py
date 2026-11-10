"""P2-T204：OCR 导入 / 来源身份 / 缓存 / 发布 / 引用 的集成检查（Mock-only，零真实调用）。

全部动作都走**产品路径**（上传 → 真实 worker 解析 → 发布 → 索引 → 问答 → 来源详情），
评测侧只做驱动与观测：

- 上传/发布/问答/来源详情：产品 HTTP 路由（`TestClient`/ASGI，不出网）；
- OCR：`MockOcrTransport` 替换传输层，但走**真实** `TencentOCRClient` 编码/签名/解析；
- 账本：本文件自己的隔离账本（`P2OcrIngestion.isolated_mock`），不碰共享账本/GO；
- 产品业务库/索引库/存储/trace 全部在 `tmp_path` 下的隔离应用里（`ProductEvalAdapter`）。

覆盖任务书 T204：
1. B0 D07–D10 页级导入/发布/索引，12 页/图调用计划与实际调用逐页一致（页/图分别计数）；
2. document/version/page/input hash/provider/model/region 全绑定；两份资料的 page1 与同资料
   换版本都不串缓存；
3. 每页 reserve/settle 可归属 `ocr` 成本中心；缺 usage/空片段/页失败立即停止；
4. 上传→解析→发布→索引→问答引用能追到同一有效单元（document/version/page）；
5. 反例：取消/删除中断后续页，迟到响应不写成功也不得进缓存；页失败后重试只复用同版本检查点。
"""

from __future__ import annotations

import asyncio
import functools
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门与上传辅助（不复制实现）
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support import ocr_transcripts  # noqa: E402
from acceptance.support.netguard import t09_network_guard  # noqa: F401  (pytest fixture)
from conftest import current_csrf, login, upload_document, write_headers  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.evaluation.p2_ingestion import (  # noqa: E402
    CACHE_REJECTED,
    CACHE_SOURCE_IDENTITY_MISMATCH,
    OcrDocumentPlan,
    OcrImportPlan,
    OcrTranscript,
    P2OcrIngestion,
    ProductOcrSuccess,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ORIGIN as ADAPTER_ORIGIN,
    MockChatBackend,
    ProductEvalAdapter,
)
from mktkb.ingestion.models import OCRCallRecord  # noqa: E402
from mktkb.ingestion.worker import retry_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
NORMAL = ROOT / "fixtures" / "acceptance" / "normal"
ADMIN = ("admin", "P2EvalAdmin-1")
EMPLOYEE = ("employee", "P2EvalEmployee-1")

FILES: dict[str, dict[str, Any]] = {
    "D07": {
        "path": NORMAL / "D07_活动申请扫描件.pdf",
        "file_kind": "pdf",
        "page_count": 8,
        "image_count": 0,
        "expected_mode": "text",
    },
    "D08": {
        "path": NORMAL / "D08_仓库安全须知扫描件.pdf",
        "file_kind": "pdf",
        "page_count": 2,
        "image_count": 0,
        "expected_mode": "text",
    },
    "D09": {
        "path": NORMAL / "D09_物料领用通知.png",
        "file_kind": "png",
        "page_count": 1,
        "image_count": 1,
        "expected_mode": "text",
    },
    "D10": {
        "path": NORMAL / "D10_盘点通知.jpg",
        "file_kind": "jpg",
        "page_count": 1,
        "image_count": 1,
        "expected_mode": "table",
    },
}

TEXT_PRICE = 0.5
TABLE_PRICE = 0.15
ACTIVITY_QUESTION = "扫描的活动申请中，申请部门是什么？"
TABLE_QUESTION = "盘点通知中城东店的盘点时间是什么？"


def asyncio_test(func):
    """仓库没有 pytest-asyncio：同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def ocr_plan(keys: tuple[str, ...] = ("D07", "D08", "D09", "D10")) -> OcrImportPlan:
    return OcrImportPlan(
        documents=tuple(
            OcrDocumentPlan(document_key=key, **FILES[key]) for key in keys
        ),
        label="p2-t204-integration",
    )


def ocr_transcripts_for(keys: tuple[str, ...] = ("D07", "D08", "D09", "D10")) -> dict[str, OcrTranscript]:
    return {
        key: OcrTranscript(
            document_key=key,
            pages=dict(ocr_transcripts.OCR_BINDINGS[key]["pages"]),
            table=ocr_transcripts.OCR_BINDINGS[key].get("table"),
        )
        for key in keys
    }


async def started_adapter(tmp_path: Path) -> ProductEvalAdapter:
    adapter = ProductEvalAdapter(
        tmp_path / "p2-t204-app",
        chat=MockChatBackend(),
        users=(ADMIN, EMPLOYEE),
        label="p2-t204",
    )
    await adapter.start()
    return adapter


def admin_client(adapter: ProductEvalAdapter) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(adapter.app, raise_server_exceptions=False)
    login(client, ADMIN[0], ADMIN[1], origin=ADAPTER_ORIGIN)
    return client, write_headers(current_csrf(client), origin=ADAPTER_ORIGIN)


def upload(client: TestClient, headers: dict[str, str], path: Path, **kwargs: Any) -> dict[str, Any]:
    response = upload_document(client, csrf=None, path=path, headers=headers, **kwargs)
    assert response.status_code == 202, response.text
    return response.json()


def publish(client: TestClient, headers: dict[str, str], adapter: ProductEvalAdapter, document_id: str, version_id: str) -> int:
    db = adapter.app.state.db.session()
    try:
        revision = int(get_revision(db))
    finally:
        db.close()
    response = client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": None, "expected_revision": revision},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return int(response.json()["revision"])


def product_records(adapter: ProductEvalAdapter, version_id: str) -> list[ProductOcrSuccess]:
    """只读投影：产品 `ocr_call_records`（缓存准入/复用认证的依据）。"""
    db = adapter.app.state.db.session()
    try:
        rows = db.scalars(
            select(OCRCallRecord).where(OCRCallRecord.version_id == uuid.UUID(str(version_id)))
        ).all()
        return [
            ProductOcrSuccess(
                record_id=str(row.id),
                document_id=str(row.document_id),
                version_id=str(row.version_id),
                page=int(row.page),
                mode=str(row.mode),
                input_sha256=str(row.image_sha256),
                provider_request_id=row.provider_request_id,
                state=str(row.state),
            )
            for row in rows
        ]
    finally:
        db.close()


def unit_count(adapter: ProductEvalAdapter, version_id: str) -> int:
    from sqlalchemy import func

    from mktkb.documents.models import SourceUnit

    db = adapter.app.state.db.session()
    try:
        return int(
            db.scalar(
                select(func.count())
                .select_from(SourceUnit)
                .where(SourceUnit.version_id == uuid.UUID(str(version_id)))
            )
            or 0
        )
    finally:
        db.close()


def version_report(adapter: ProductEvalAdapter, version_id: str) -> dict[str, Any]:
    """只读：版本的 processing_report（逐页 OCR 成功/失败/停止原因）。"""
    from mktkb.documents.models import DocumentVersion

    db = adapter.app.state.db.session()
    try:
        version = db.get(DocumentVersion, uuid.UUID(str(version_id)))
        return dict(version.processing_report or {})
    finally:
        db.close()


def unit_of_source(adapter: ProductEvalAdapter, source_id: str) -> Any:
    from mktkb.documents.models import SourceUnit

    db = adapter.app.state.db.session()
    try:
        return db.get(SourceUnit, uuid.UUID(str(source_id)))
    finally:
        db.close()


def run_ocr_job(
    adapter: ProductEvalAdapter,
    ingestion: P2OcrIngestion,
    *,
    key: str,
    document_id: str,
    version_id: str,
):
    db = adapter.app.state.db.session()
    try:
        result = ingestion.run_job(
            db,
            adapter.app.state.store,
            document_key=key,
            document_id=document_id,
            version_id=version_id,
        )
    finally:
        db.close()
    summary = ingestion.finalize(
        document_id=document_id,
        version_id=version_id,
        records=product_records(adapter, version_id),
    )
    return result, summary


def resaved_png(source: Path, target: Path, *, marker: str) -> Path:
    """同一张图重新保存：像素不变（OCR 图块字节相同）、文件字节不同（避开重复内容守卫）。"""
    from PIL import Image, PngImagePlugin

    target.parent.mkdir(parents=True, exist_ok=True)
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", marker)
    with Image.open(source) as image:
        image.convert("RGB").save(target, format="PNG", pnginfo=info)
    assert target.read_bytes() != source.read_bytes()
    return target


# --------------------------------------------------------------------------- #
# 1. D07–D10：12 页/图导入、发布、索引、问答引用追到同一有效单元
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_d07_d10_ocr_import_publish_index_and_citation_trace_to_same_unit(
    tmp_path: Path,
) -> None:
    adapter = await started_adapter(tmp_path)
    try:
        client, headers = admin_client(adapter)
        plan = ocr_plan()
        assert plan.pages == 10 and plan.images == 2 and plan.planned_calls == 12
        ingestion = P2OcrIngestion.isolated_mock(
            tmp_path / "p2-t204-ocr", plan=plan, transcripts=ocr_transcripts_for()
        )
        assert ingestion.uses_mock_transport is True, "OCR 传输层必须是 Mock 替身（0 出网）"
        versions: dict[str, tuple[str, str]] = {}
        summaries = {}
        for key in ("D07", "D08", "D09", "D10"):
            payload = upload(client, headers, FILES[key]["path"])
            document_id = payload["document"]["id"]
            version_id = payload["version"]["id"]
            result, summary = run_ocr_job(
                adapter, ingestion, key=key, document_id=document_id, version_id=version_id
            )
            assert result.state == "succeeded", (key, result.state, result.error_code)
            assert summary.planned_calls == summary.provider_requests, summary.as_dict()
            assert summary.failed_pages == () and summary.missing_pages == ()
            summaries[key] = summary
            publish(client, headers, adapter, document_id, version_id)
            versions[key] = (document_id, version_id)

        # 页面/图片分别计数：D07 8 页 + D08 2 页 + D09 1 图 + D10 1 图 = 12 次
        assert {key: item.provider_requests for key, item in summaries.items()} == {
            "D07": 8,
            "D08": 2,
            "D09": 1,
            "D10": 1,
        }
        requests = ingestion.transport.requests
        assert len(requests) == 12 and ingestion.transport.violations == []
        assert [row["mode"] for row in requests].count("table") == 1, "只有 D10 走 table 模式"
        assert {row["region"] for row in requests} == {"ap-guangzhou"}
        assert all(row["input_sha256"] == row["expected_input_sha256"] for row in requests)

        reserved = [item for item in ingestion.ledger_events() if item.get("event") == "reserved"]
        settled = [item for item in ingestion.ledger_events() if item.get("event") == "result"]
        assert len(reserved) == len(settled) == 12
        assert all(item["cost_center"] == "ocr" for item in reserved)
        ledger = ingestion.ledger_summary()
        assert ledger["center_accounted_cny"] == {"ocr": 11 * TEXT_PRICE + TABLE_PRICE}
        assert ledger["stage_accounted_cny"] == pytest.approx(11 * TEXT_PRICE + TABLE_PRICE)

        receipts = ingestion.receipts
        assert len(receipts) == 12
        reservation_ids = {item["reservation_id"] for item in reserved}
        assert all(receipt.reservation_id in reservation_ids for receipt in receipts)
        assert all(
            receipt.ledger_request_sha256 == receipt.identity.request_sha256 for receipt in receipts
        )

        # 发布 -> 索引：4 份资料、13 个来源单元（D07/D08/D09 各 1 段/页 + D10 2 行）
        status = adapter.index_status()
        assert status["ready"] is True and int(status["documents"]) == 4
        assert int(status["units"]) == 13
        assert adapter.real_provider_built is False

        # 上传->解析->发布->索引->问答引用：引用要能追到同一有效单元（document/version/page）
        conversation_id = await adapter.open_conversation()
        unit_checks = 0
        for question, key in ((ACTIVITY_QUESTION, "D07"), (TABLE_QUESTION, "D10")):
            turn = await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation_id,
                client_request_id=str(uuid.uuid4()),
            )
            assert turn.http_status == 200 and turn.kind == "answer", turn.as_dict(include_text=True)
            assert turn.sources, "产品回答必须带引用"
            document_id, version_id = versions[key]
            matched = [
                source
                for source in turn.sources
                if str(source.get("document_name", "")).startswith(key)
            ]
            assert matched, turn.sources
            source = matched[0]
            code, detail = await adapter.source_detail(turn.message_id or "", source["source_id"])
            assert code == 200, detail
            assert detail["status"] == "active"
            unit = unit_of_source(adapter, source["source_id"])
            assert unit is not None
            assert str(unit.document_id) == document_id and str(unit.version_id) == version_id
            page = int(source["locator"]["page"])
            assert unit.locator.get("page") == page and page in range(1, int(FILES[key]["page_count"]) + 1)
            transcript = ocr_transcripts.OCR_BINDINGS[key]["pages"][page]
            if key == "D07":
                assert unit.text == "\n".join(transcript), "引用文本必须是该页的受控 OCR 转录"
            else:
                header, rows = ocr_transcripts.OCR_BINDINGS["D10"]["table"]
                assert int(source["locator"]["row"]) == 1
                assert unit.fields == dict(zip(header, rows[0]))
            unit_checks += 1
        assert unit_checks == 2
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 2. 跨文档 page1 与同文档新版本：不串缓存
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_cross_document_page1_and_new_version_do_not_share_ocr_cache(tmp_path: Path) -> None:
    adapter = await started_adapter(tmp_path)
    try:
        client, headers = admin_client(adapter)
        # 同一 Mock 批里要跑 3 个来源（第一份资料/第二份资料/新版本），共用受控 13 次上限。
        ingestion = P2OcrIngestion.isolated_mock(
            tmp_path / "p2-t204-ocr",
            plan=ocr_plan(("D09",)),
            transcripts=ocr_transcripts_for(("D09",)),
            max_calls=13,
        )
        source_path = FILES["D09"]["path"]

        first = upload(client, headers, source_path)
        first_ids = (first["document"]["id"], first["version"]["id"])
        result, summary = run_ocr_job(
            adapter, ingestion, key="D09", document_id=first_ids[0], version_id=first_ids[1]
        )
        assert result.state == "succeeded"
        assert summary.provider_requests == 1 and summary.cache_hits == 0
        assert summary.pages[0]["admission"] == "admitted"
        assert len(ingestion.cache) == 1

        # 第二份资料：同一张图重新保存（像素相同→OCR 图块字节相同；文件字节不同以避开产品
        # 的重复内容守卫）。page1 必须重新识别，不得复用第一份资料的缓存。
        second_path = resaved_png(source_path, tmp_path / "D09_docB.png", marker="p2-t204-doc-b")
        second = upload(client, headers, second_path, name="D09_物料领用通知_docB.png")
        second_ids = (second["document"]["id"], second["version"]["id"])
        assert second_ids[0] != first_ids[0]
        result, summary = run_ocr_job(
            adapter, ingestion, key="D09", document_id=second_ids[0], version_id=second_ids[1]
        )
        assert result.state == "succeeded"
        assert summary.provider_requests == 1, "第二份资料 page1 必须真的再调一次"
        assert summary.cache_hits == 0
        rejected = ingestion.receipts[-1]
        assert rejected.cache == f"{CACHE_REJECTED}:{CACHE_SOURCE_IDENTITY_MISMATCH}"
        first_request, second_request = ingestion.transport.requests[0], ingestion.transport.requests[1]
        assert first_request["input_sha256"] == second_request["input_sha256"], "图块字节相同（同一张图）"
        assert (first_request["document_id"], first_request["version_id"]) != (
            second_request["document_id"],
            second_request["version_id"],
        )

        # 同一资料换版本：图块字节仍相同，但 version 变了 → 仍然必须重新调用。
        revised_path = resaved_png(source_path, tmp_path / "D09_v2.png", marker="p2-t204-v2")
        revised = upload(
            client, headers, revised_path, name=source_path.name, document_id=first_ids[0]
        )
        revised_ids = (revised["document"]["id"], revised["version"]["id"])
        assert revised_ids[0] == first_ids[0] and revised_ids[1] != first_ids[1]
        result, summary = run_ocr_job(
            adapter, ingestion, key="D09", document_id=revised_ids[0], version_id=revised_ids[1]
        )
        assert result.state == "succeeded"
        assert summary.provider_requests == 1
        assert ingestion.receipts[-1].cache == f"{CACHE_REJECTED}:{CACHE_SOURCE_IDENTITY_MISMATCH}"

        assert len(ingestion.transport.requests) == 3
        assert {row["input_sha256"] for row in ingestion.transport.requests} == {
            first_request["input_sha256"]
        }, "三次调用识别的是同一张图（input hash 相同）"
        identities = {
            (row["document_id"], row["version_id"], row["page"]) for row in ingestion.transport.requests
        }
        assert len(identities) == 3, "三份身份各自独立调用"
        # 三次调用各自成为独立缓存条目（同一 input hash 不会变成同一个条目）。
        assert len(ingestion.cache) == 3
        assert len({entry.identity.key for entry in ingestion.cache.entries()}) == 3
        assert len([item for item in ingestion.ledger_events() if item.get("event") == "reserved"]) == 3
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 3. 页失败后重试：只复用同版本检查点，命中与真实调用分别计数
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_partial_page_failure_retry_reuses_only_same_version_checkpoints(tmp_path: Path) -> None:
    adapter = await started_adapter(tmp_path)
    try:
        client, headers = admin_client(adapter)
        ingestion = P2OcrIngestion.isolated_mock(
            tmp_path / "p2-t204-ocr", plan=ocr_plan(("D07",)), transcripts=ocr_transcripts_for(("D07",))
        )
        payload = upload(client, headers, FILES["D07"]["path"])
        document_id, version_id = payload["document"]["id"], payload["version"]["id"]
        job_id = payload["job"]["id"]

        ingestion.transport.fail_on(4, mode="unavailable")
        result, summary = run_ocr_job(
            adapter, ingestion, key="D07", document_id=document_id, version_id=version_id
        )
        assert result.state == "failed"
        assert result.error_code in {"OCR_UNAVAILABLE", "PARSE_INCOMPLETE"}, result.error_code
        assert summary.provider_requests == 4, "1-3 成功、第 4 页失败后立即停止"
        assert summary.failed_pages == (4,)
        assert summary.missing_pages == (5, 6, 7, 8)
        assert unit_count(adapter, version_id) == 3, "整份未完整成功，但已成功页仍可预览（产品既有行为）"
        report = version_report(adapter, version_id)
        reasons = {row["page"]: row.get("reason") for row in report["pages"]}
        assert reasons[4] == "OCR_UNAVAILABLE"
        assert reasons[5] == "OCR_INGESTION_STOPPED", "失败后后续页在网关处被拒绝，没有再发请求"
        failed_receipt = [item for item in ingestion.receipts if item.status == "failed"]
        assert len(failed_receipt) == 1 and failed_receipt[0].charged_cny == TEXT_PRICE

        ingestion.transport.clear_failures()
        db = adapter.app.state.db.session()
        try:
            retry_job(db, uuid.UUID(str(job_id)))
        finally:
            db.close()
        result, summary = run_ocr_job(
            adapter, ingestion, key="D07", document_id=document_id, version_id=version_id
        )
        assert result.state == "succeeded", (result.state, result.error_code)
        assert summary.product_checkpoint_reuses == 3, summary.as_dict()
        assert summary.provider_requests == 5, "第 4-8 页才是本轮真实调用"
        assert summary.cache_hits == 0
        assert summary.charged_cny == 5 * TEXT_PRICE
        reused = [row for row in summary.pages if row["source"] == "product_checkpoint"]
        assert [row["page"] for row in reused] == [1, 2, 3]
        assert all(row["certified"] and row["record_id"] for row in reused)
        assert all(row["provider_request_id"] for row in reused), "复用必须有 usage 证据"
        assert unit_count(adapter, version_id) == 8
        assert len(ingestion.transport.requests) == 9, "4 次失败尝试 + 5 次成功 = 9 次真实底层调用"
        assert len([item for item in ingestion.ledger_events() if item.get("event") == "reserved"]) == 9
        assert len(ingestion.cache) == 8, "8 页都有产品成功审计行后才准入缓存"
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 4. 取消/删除：不续下一页，迟到响应不写成功也不复活缓存
# --------------------------------------------------------------------------- #


@asyncio_test
@pytest.mark.parametrize("variant", ["cancel_version", "delete_document"])
async def test_cancel_or_delete_during_ocr_stops_later_pages_and_discards_late_result(
    tmp_path: Path, variant: str
) -> None:
    adapter = await started_adapter(tmp_path)
    try:
        client, headers = admin_client(adapter)
        ingestion = P2OcrIngestion.isolated_mock(
            tmp_path / "p2-t204-ocr", plan=ocr_plan(("D07",)), transcripts=ocr_transcripts_for(("D07",))
        )
        payload = upload(client, headers, FILES["D07"]["path"])
        document_id, version_id = payload["document"]["id"], payload["version"]["id"]
        ingestion.transport.block_on(3)

        holder: dict[str, Any] = {}

        def worker() -> None:
            try:
                db = adapter.app.state.db.session()
                try:
                    holder["result"] = ingestion.run_job(
                        db,
                        adapter.app.state.store,
                        document_key="D07",
                        document_id=document_id,
                        version_id=version_id,
                    )
                finally:
                    db.close()
            except BaseException as exc:  # noqa: BLE001 - 结果在断言里显式检查
                holder["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert ingestion.transport.entered.wait(30), "OCR 替身未进入第 3 页调用"
        calls_during = len(ingestion.transport.requests)
        assert calls_during == 3

        if variant == "cancel_version":
            response = client.post(
                f"/api/v1/documents/{document_id}/versions/{version_id}/cancel", headers=headers
            )
            assert response.status_code == 204, response.text
        else:
            db = adapter.app.state.db.session()
            try:
                revision = int(get_revision(db))
            finally:
                db.close()
            response = client.delete(
                f"/api/v1/documents/{document_id}", params={"expected_revision": revision}, headers=headers
            )
            assert response.status_code == 200, response.text

        ingestion.transport.unblock()
        thread.join(60)
        assert not thread.is_alive(), "worker 未在迟到响应后退出"
        assert "error" not in holder, holder.get("error")
        result = holder["result"]
        calls_after = len(ingestion.transport.requests)
        assert calls_after == calls_during == 3, "取消/删除后不得继续下一页"
        assert result.state == "cancelled", result

        assert unit_count(adapter, version_id) == 0
        records = product_records(adapter, version_id)
        late = [item for item in records if item.page == 3]
        assert late and all(item.state == "discarded" for item in late), records
        assert all(item.state == "succeeded" for item in records if item.page in (1, 2))

        summary = ingestion.finalize(
            document_id=document_id, version_id=version_id, records=records
        )
        page3 = [row for row in summary.pages if row["page"] == 3][0]
        assert page3["source"] == "provider_call", page3
        assert page3["admission"].startswith("rejected:"), page3
        assert summary.failed_pages == ()
        assert summary.missing_pages == (4, 5, 6, 7, 8)
        page3_identities = {
            receipt.identity.key for receipt in ingestion.receipts if receipt.identity.page == 3
        }
        assert page3_identities
        for entry in ingestion.cache.entries():
            assert entry.identity.page != 3, "迟到响应不得进入缓存"
        assert len(ingestion.cache) == 2, "只有已完成且产品成功落审计行的第 1-2 页可准入"
    finally:
        await adapter.close()
