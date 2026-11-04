"""T07 PDF/图片/OCR 集成检查：真实上传、数据库、worker、预览、发布与取消/删除/租约边界。

OCR 只使用本文件的可控替身；取消/删除使用真实 HTTP 接口与独立会话/连接，
不以直接修改状态代替用户操作。所有临时数据库/存储来自 pytest 隔离目录。
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from conftest import ORIGIN, current_csrf, login, upload_document, write_headers
from mktkb.db import Database, run_migrations, table_names
from mktkb.documents.models import Document, DocumentVersion, SourceUnit
from mktkb.ingestion.models import ImportJob, OCRCallRecord
from mktkb.ingestion.worker import OcrRateLimiter, claim_job, retry_job, run_one_job
from mktkb.main import create_app
from mktkb.providers.types import (
    OCRPageResult,
    OCRQuotaUnavailable,
    OCRRateLimited,
    OCRTimeout,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D05 = FIXTURES / "normal" / "D05_物料领用规范.pdf"
D07 = FIXTURES / "normal" / "D07_活动申请扫描件.pdf"
D09 = FIXTURES / "normal" / "D09_物料领用通知.png"
A08 = FIXTURES / "variants" / "A08_混合页含失败页文档.pdf"
B04 = FIXTURES / "boundary" / "B04_超过50页.pdf"
B08 = FIXTURES / "boundary" / "B08_超过2000万像素.png"


class StubOCR:
    """可控 OCR 替身：按页/模式返回或抛出稳定错误，记录每次调用与可选屏障。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.behaviors: dict = {}
        self.default = None
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def recognize(self, page, *, mode):
        self.calls.append({"page": page.page, "mode": mode, "bbox": page.bbox, "bytes": len(page.content)})
        if self.block:
            self.entered.set()
            if not self.release.wait(20):
                raise RuntimeError("stub barrier timeout")
        behavior = self.behaviors.get((page.page, mode))
        if behavior is None:
            behavior = self.behaviors.get(page.page, self.default)
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior(page, mode, len(self.calls))
        return OCRPageResult(
            text=f"扫描页第{page.page}页",
            provider_request_id=f"req-{page.page}",
            confidence=90.0,
        )


@pytest.fixture
def stub() -> StubOCR:
    return StubOCR()


@pytest.fixture
def ocr_app(settings, stub):
    application = create_app(settings, ocr_gateway=stub)
    yield application
    application.state.db.dispose()


def _admin(app) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    login(client, "admin", "AdminPass-1")
    csrf = current_csrf(client)
    return SimpleNamespace(
        client=client,
        csrf=csrf,
        headers=write_headers(csrf),
        upload=lambda **kwargs: upload_document(client, csrf=csrf, **kwargs),
    )


def _run(app, stub, **kwargs):
    db = app.state.db.session()
    try:
        return run_one_job(db, app.state.store, ocr=stub, **kwargs)
    finally:
        db.close()


def _job(app, job_id):
    db = app.state.db.session()
    try:
        return db.get(ImportJob, uuid.UUID(str(job_id)))
    finally:
        db.close()


def _version(app, version_id):
    db = app.state.db.session()
    try:
        return db.get(DocumentVersion, uuid.UUID(str(version_id)))
    finally:
        db.close()


def _document(app, document_id):
    db = app.state.db.session()
    try:
        return db.get(Document, uuid.UUID(str(document_id)))
    finally:
        db.close()


def _unit_count(app, version_id) -> int:
    db = app.state.db.session()
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


def _records(app, version_id) -> list[OCRCallRecord]:
    db = app.state.db.session()
    try:
        return list(
            db.scalars(
                select(OCRCallRecord)
                .where(OCRCallRecord.version_id == uuid.UUID(str(version_id)))
                .order_by(OCRCallRecord.created_at, OCRCallRecord.attempt)
            ).all()
        )
    finally:
        db.close()


def _publish(admin, document_id, version_id, expected_active_version_id=None):
    detail = admin.client.get(f"/api/v1/documents/{document_id}").json()
    return admin.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={
            "expected_active_version_id": expected_active_version_id,
            "expected_revision": detail["revision"],
        },
        headers=admin.headers,
    )


# ---------------------------------------------------------------- 正常完整路径


def test_pdf_upload_process_preview_publish_without_ocr(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D05, name="物料领用规范.pdf")
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    assert payload["document"]["file_type"] == "pdf"
    assert payload["version"]["state"] == "queued"

    result = _run(ocr_app, stub)
    assert result.state == "succeeded", result
    assert stub.calls == [], "文字型 PDF 不得调用 OCR"
    job = _job(ocr_app, payload["job"]["id"])
    version = _version(ocr_app, payload["version"]["id"])
    assert job.completed_pages == job.total_pages == 1
    assert version.state == "review_required"
    assert version.processing_report["kind"] == "pdf"
    assert version.processing_report["pages"][0]["source"] == "text"

    preview = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview",
        params={"page": 1, "limit": 100},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total"] >= 5
    assert all(item["locator"]["page"] == 1 for item in body["items"])
    assert body["report"]["total_pages"] == 1

    published = _publish(admin, payload["document"]["id"], payload["version"]["id"])
    assert published.status_code == 200, published.text
    assert published.json()["active_version_id"] == payload["version"]["id"]

    original = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/file"
    )
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("application/pdf")
    assert original.content == D05.read_bytes()


def test_scanned_pdf_all_pages_preview_publish_and_call_records(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    assert upload.status_code == 202, upload.text
    payload = upload.json()

    result = _run(ocr_app, stub)
    assert result.state == "succeeded", result
    assert [call["page"] for call in stub.calls] == list(range(1, 9))
    job = _job(ocr_app, payload["job"]["id"])
    version = _version(ocr_app, payload["version"]["id"])
    assert job.completed_pages == job.total_pages == 8
    assert version.state == "review_required"
    assert [entry["page"] for entry in version.processing_report["pages"]] == list(range(1, 9))

    preview = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview",
        params={"page": 3, "limit": 20},
    )
    assert preview.status_code == 200
    items = preview.json()["items"]
    assert len(items) == 1 and items[0]["locator"]["page"] == 3
    assert items[0]["kind"] == "image_text"

    published = _publish(admin, payload["document"]["id"], payload["version"]["id"])
    assert published.status_code == 200, published.text

    records = _records(ocr_app, payload["version"]["id"])
    assert len(records) == 8
    assert {record.state for record in records} == {"succeeded"}
    assert [record.page for record in records] == list(range(1, 9))
    assert {record.mode for record in records} == {"text"}
    assert {record.provider_request_id for record in records} == {f"req-{page}" for page in range(1, 9)}
    assert all(len(record.image_sha256) == 64 for record in records)


def test_image_upload_process_publish_and_protected_original(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D09, name="物料领用通知.png")
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    assert payload["document"]["file_type"] == "png"

    result = _run(ocr_app, stub)
    assert result.state == "succeeded", result
    assert len(stub.calls) == 1
    job = _job(ocr_app, payload["job"]["id"])
    assert job.completed_pages == job.total_pages == 1

    published = _publish(admin, payload["document"]["id"], payload["version"]["id"])
    assert published.status_code == 200, published.text

    original = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/file"
    )
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("image/png")
    assert original.content == D09.read_bytes()


# ---------------------------------------------------------------- 失败/额度/限流


def test_failed_page_blocks_publish_and_keeps_successful_pages(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    stub.behaviors[3] = OCRTimeout("simulated page timeout")

    result = _run(ocr_app, stub)
    assert result.state == "failed", result
    assert result.error_code == "OCR_TIMEOUT"
    job = _job(ocr_app, payload["job"]["id"])
    version = _version(ocr_app, payload["version"]["id"])
    assert job.state == "failed" and job.retryable is True
    assert version.state == "failed"
    assert version.processing_report["failed_pages"] == [3]
    assert [entry["page"] for entry in version.processing_report["pages"]] == list(range(1, 9))
    assert _unit_count(ocr_app, payload["version"]["id"]) == 7

    blocked = _publish(admin, payload["document"]["id"], payload["version"]["id"])
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"

    preview = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview",
        params={"limit": 100},
    )
    assert preview.status_code == 200
    assert preview.json()["total"] == 7, "已成功页仍可预览"


def test_quota_blocks_job_version_and_explicit_retry_recovers(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    stub.default = OCRQuotaUnavailable()

    result = _run(ocr_app, stub)
    assert result.state == "blocked", result
    assert result.error_code == "OCR_QUOTA_UNAVAILABLE"
    assert len(stub.calls) == 1, "额度不足后不得继续自动请求"
    job = _job(ocr_app, payload["job"]["id"])
    version = _version(ocr_app, payload["version"]["id"])
    assert job.state == "blocked" and job.retryable is True
    assert version.state == "failed"
    assert version.processing_report["failed_pages"] == list(range(1, 9))

    stub.default = None
    retried = admin.client.post(f"/api/v1/jobs/{payload['job']['id']}/retry", headers=admin.headers)
    assert retried.status_code == 202, retried.text
    assert retried.json()["state"] == "queued"

    recovered = _run(ocr_app, stub)
    assert recovered.state == "succeeded", recovered
    assert recovered.units_written == 8 and recovered.units_reused == 0
    assert _job(ocr_app, payload["job"]["id"]).state == "succeeded"
    assert _version(ocr_app, payload["version"]["id"]).state == "review_required"
    assert len(stub.calls) == 9, "首次仅第 1 页请求；重试后 8 页各一次"


def test_rate_limit_bounded_backoff_and_attempt_records(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D09, name="物料领用通知.png")
    payload = upload.json()
    state = {"calls": 0}

    def behavior(page, mode, call_number):
        state["calls"] += 1
        if state["calls"] <= 2:
            raise OCRRateLimited("simulated 429")
        return OCRPageResult(text="第三页成功", provider_request_id="req-ok", confidence=90.0)

    stub.default = behavior
    fake = {"now": 0.0, "sleeps": []}

    def clock():
        return fake["now"]

    def sleep(seconds):
        fake["sleeps"].append(seconds)
        fake["now"] += seconds

    limiter = OcrRateLimiter(max_per_second=2.0, clock=clock, sleep=sleep)
    result = _run(
        ocr_app,
        stub,
        ocr_limiter=limiter,
        ocr_options={
            "max_attempts": 3,
            "retry_base_seconds": 0.5,
            "retry_max_single_seconds": 0.5,
            "retry_total_seconds": 1.0,
            "sleep": sleep,
        },
    )
    assert result.state == "succeeded", result
    assert state["calls"] == 3
    assert sum(fake["sleeps"]) <= 1.0 + 1e-9, "总等待必须有上限"
    records = _records(ocr_app, payload["version"]["id"])
    assert [record.state for record in records] == ["failed", "failed", "succeeded"]
    assert [record.attempt for record in records] == [1, 2, 3]
    assert records[-1].error_code is None


def test_rate_limit_exhausted_stops_remaining_pages(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    stub.default = OCRRateLimited("always 429")
    fake = {"now": 0.0}

    def clock():
        return fake["now"]

    def sleep(seconds):
        fake["now"] += seconds

    result = _run(
        ocr_app,
        stub,
        ocr_limiter=OcrRateLimiter(max_per_second=2.0, clock=clock, sleep=sleep),
        ocr_options={"max_attempts": 2, "retry_total_seconds": 0.5, "sleep": sleep},
    )
    assert result.state == "failed", result
    assert result.error_code == "OCR_RATE_LIMITED"
    assert len(stub.calls) == 2, "有限重试后停止后续页"
    version = _version(ocr_app, payload["version"]["id"])
    assert version.state == "failed"
    assert version.processing_report["failed_pages"] == list(range(1, 9))
    assert all(entry["status"] == "failed" for entry in version.processing_report["pages"])


def test_retry_reuses_successful_pages_and_only_calls_failed_page(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    stub.behaviors[3] = OCRTimeout("page 3 fails once")
    first = _run(ocr_app, stub)
    assert first.state == "failed" and len(stub.calls) == 8
    assert _unit_count(ocr_app, payload["version"]["id"]) == 7

    stub.behaviors.pop(3)
    db = ocr_app.state.db.session()
    try:
        retry_job(db, uuid.UUID(payload["job"]["id"]))
    finally:
        db.close()

    calls_before = len(stub.calls)
    second = _run(ocr_app, stub)
    assert second.state == "succeeded", second
    assert second.units_written == 1 and second.units_reused == 7
    assert len(stub.calls) == calls_before + 1, "只重试失败页，不重复调用已成功页"
    assert stub.calls[-1]["page"] == 3
    assert _unit_count(ocr_app, payload["version"]["id"]) == 8
    records = _records(ocr_app, payload["version"]["id"])
    assert len([record for record in records if record.state == "succeeded"]) == 8
    preview = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview",
        params={"limit": 100},
    )
    assert [item["locator"]["page"] for item in preview.json()["items"]] == list(range(1, 9)), (
        "失败页补写不能打乱页码顺序"
    )


def test_text_and_table_cache_are_not_mixed(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D09, name="物料领用通知.png")
    payload = upload.json()
    db = ocr_app.state.db.session()
    try:
        from mktkb.ingestion.worker import OcrExecutor
        from mktkb.providers.types import OCRInput

        def behavior(page, mode, call_number):
            return OCRPageResult(
                text="text-mode" if mode == "text" else "table-mode",
                table_rows=(("A", "B"), ("1", "2")) if mode == "table" else (),
                provider_request_id=f"req-{mode}",
            )

        stub.default = behavior
        executor = OcrExecutor(
            db,
            version_id=uuid.UUID(payload["version"]["id"]),
            document_id=uuid.UUID(payload["document"]["id"]),
            gateway=stub,
            ensure_live=lambda: None,
        )
        source = OCRInput(content=b"same-image-bytes", mime_type="image/png", page=1)
        text_result = executor.recognize(source, mode="text")
        table_result = executor.recognize(source, mode="table")
        cached_text = executor.recognize(source, mode="text")
    finally:
        db.close()

    assert text_result.text == "text-mode"
    assert table_result.text == "table-mode"
    assert cached_text.text == "text-mode"
    assert [call["mode"] for call in stub.calls] == ["text", "table"], "不同模式不得混用缓存"


# ---------------------------------------------------------------- U09 取消/删除/租约


def _start_worker(app, stub, **kwargs):
    holder: dict = {}

    def worker():
        try:
            holder["result"] = _run(app, stub, **kwargs)
        except Exception as exc:  # 测试线程内异常需显式带回
            holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, holder


def test_cancel_during_ocr_discards_late_result(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    stub.block = True

    thread, holder = _start_worker(ocr_app, stub)
    assert stub.entered.wait(10), "OCR 替身未进入调用"
    cancel = admin.client.post(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/cancel",
        headers=admin.headers,
    )
    assert cancel.status_code == 204, cancel.text
    stub.release.set()
    thread.join(20)
    assert not thread.is_alive(), "worker 未在取消后退出"
    assert "error" not in holder, holder
    assert holder["result"].state == "cancelled", holder["result"]

    job = _job(ocr_app, payload["job"]["id"])
    version = _version(ocr_app, payload["version"]["id"])
    assert job.state == "cancelled" and version.state == "cancelled"
    assert _unit_count(ocr_app, payload["version"]["id"]) == 0
    assert len(stub.calls) == 1, "取消后不得继续下一页"
    records = _records(ocr_app, payload["version"]["id"])
    assert len(records) == 1 and records[0].state == "discarded"
    assert records[0].result is None


def test_delete_during_ocr_discards_late_result(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    stub.block = True

    thread, holder = _start_worker(ocr_app, stub)
    assert stub.entered.wait(10)
    detail = admin.client.get(f"/api/v1/documents/{payload['document']['id']}").json()
    deleted = admin.client.delete(
        f"/api/v1/documents/{payload['document']['id']}",
        params={"expected_revision": detail["revision"]},
        headers=admin.headers,
    )
    assert deleted.status_code == 200, deleted.text
    stub.release.set()
    thread.join(20)
    assert not thread.is_alive()
    assert holder["result"].state == "cancelled", holder["result"]

    document = _document(ocr_app, payload["document"]["id"])
    assert document.deleted is True
    assert _unit_count(ocr_app, payload["version"]["id"]) == 0
    assert len(stub.calls) == 1
    assert all(record.state == "discarded" for record in _records(ocr_app, payload["version"]["id"]))

    file_response = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/file"
    )
    assert file_response.status_code == 410


def test_lease_lost_during_ocr_discards_late_result(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    db = ocr_app.state.db.session()
    try:
        lease = claim_job(db, lease_seconds=1)
        assert lease is not None
    finally:
        db.close()
    stub.block = True

    thread, holder = _start_worker(ocr_app, stub, lease=lease)
    assert stub.entered.wait(10)
    time.sleep(1.2)
    stub.release.set()
    thread.join(20)
    assert not thread.is_alive()
    assert holder["result"].state == "lease_lost", holder["result"]
    assert _unit_count(ocr_app, payload["version"]["id"]) == 0
    assert all(record.state == "discarded" for record in _records(ocr_app, payload["version"]["id"]))
    job = _job(ocr_app, payload["job"]["id"])
    assert job.state == "running", "租约失效不得被旧 worker 提交为失败/成功"


# ---------------------------------------------------------------- 旧版/权限/边界


def test_old_active_version_survives_failed_new_scan(ocr_app, stub):
    admin = _admin(ocr_app)
    first = admin.upload(path=D05, name="物料领用规范.pdf").json()
    assert _run(ocr_app, stub).state == "succeeded"
    assert _publish(admin, first["document"]["id"], first["version"]["id"]).status_code == 200

    second = admin.upload(
        path=D07, name="物料领用规范.pdf", document_id=first["document"]["id"]
    )
    assert second.status_code == 202, second.text
    second_payload = second.json()
    stub.behaviors[3] = OCRTimeout("new version page 3")
    failed = _run(ocr_app, stub)
    assert failed.state == "failed"

    document = _document(ocr_app, first["document"]["id"])
    assert str(document.active_version_id) == first["version"]["id"]
    assert _version(ocr_app, second_payload["version"]["id"]).state == "failed"

    old_preview = admin.client.get(
        f"/api/v1/documents/{first['document']['id']}/versions/{first['version']['id']}/preview",
        params={"limit": 100},
    )
    assert old_preview.status_code == 200 and old_preview.json()["total"] >= 5
    blocked = _publish(
        admin,
        first["document"]["id"],
        second_payload["version"]["id"],
        expected_active_version_id=first["version"]["id"],
    )
    assert blocked.status_code == 409


def test_preview_page_filter_permissions_and_cancelled_content(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
    payload = upload.json()
    assert _run(ocr_app, stub).state == "succeeded"

    employee = TestClient(ocr_app, raise_server_exceptions=False)
    login(employee, "employee", "EmployeePass-1")
    denied = employee.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview"
    )
    assert denied.status_code == 403

    filtered = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview",
        params={"page": 2, "limit": 10},
    )
    assert filtered.status_code == 200
    assert [item["locator"]["page"] for item in filtered.json()["items"]] == [2]

    cancel = admin.client.post(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/cancel",
        headers=admin.headers,
    )
    assert cancel.status_code == 204
    after = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview"
    )
    assert after.status_code == 410


def test_upload_page_and_pixel_limits_are_rejected_before_worker(ocr_app, stub):
    admin = _admin(ocr_app)
    pages = admin.upload(path=B04, name="超过50页.pdf")
    assert pages.status_code == 422
    assert pages.json()["error"]["code"] == "PDF_PAGE_LIMIT"
    pixels = admin.upload(path=B08, name="超过2000万像素.png")
    assert pixels.status_code == 422
    assert pixels.json()["error"]["code"] == "IMAGE_PIXEL_LIMIT"
    db = ocr_app.state.db.session()
    try:
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(ImportJob)) == 0
    finally:
        db.close()
    assert stub.calls == []


def test_pdf_20mb_exact_boundary_and_one_byte_over(ocr_app, stub):
    admin = _admin(ocr_app)
    limit = 20 * 1024 * 1024
    source = D05.read_bytes()
    exact = source + b"\n%" + b"x" * (limit - len(source) - 2)
    assert len(exact) == limit
    accepted = admin.upload(content=exact, name="恰好20MB.pdf")
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["document"]["file_type"] == "pdf"

    over = admin.upload(content=exact + b"x", name="超过20MB一字节.pdf")
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert stub.calls == []


def test_ocr_not_configured_is_stable_failure(settings, stub):
    app = create_app(settings, ocr_gateway=None)
    try:
        admin = _admin(app)
        upload = admin.upload(path=D07, name="活动申请扫描件.pdf")
        payload = upload.json()
        result = _run(app, None)
        assert result.state == "failed"
        assert result.error_code == "OCR_NOT_CONFIGURED"
        version = _version(app, payload["version"]["id"])
        assert version.state == "failed"
        assert version.processing_report["failed_pages"] == list(range(1, 9))
    finally:
        app.state.db.dispose()


def test_migration_0006_upgrades_existing_database_and_preserves_data(tmp_path: Path):
    from alembic import command
    from alembic.config import Config

    from mktkb.auth.models import User
    from mktkb.db import MIGRATIONS_DIR

    database = tmp_path / "upgrade.sqlite3"
    url = f"sqlite:///{database.as_posix()}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0005_conversations")
    db = Database(url)
    try:
        with db.session_scope() as session:
            session.add(
                User(
                    username="preserved",
                    display_name="保留账号",
                    role="employee",
                    password_hash="x" * 60,
                    password_algo="bcrypt$4",
                )
            )
        before_tables = table_names(db.engine)
        assert "ocr_call_records" not in before_tables
    finally:
        db.dispose()

    run_migrations(url)
    db = Database(url)
    try:
        assert "ocr_call_records" in table_names(db.engine)
        with db.session_scope() as session:
            assert session.scalar(select(User.id).where(User.username == "preserved")) is not None
            assert session.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 1
    finally:
        db.dispose()


# ---------------------------------------------------------------- T07-R1 追加回归


def _r1_two_page_pdf(path: Path, draw_second) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 720, "R1 first page keeps its text.")
    pdf.showPage()
    draw_second(pdf)
    pdf.showPage()
    pdf.save()
    return path


@pytest.mark.parametrize("value", ["1", "12", "123", "1234"])
def test_r1_short_text_page_stays_in_preview_and_publish(ocr_app, stub, tmp_path: Path, value: str):
    def draw_second(pdf):
        from reportlab.lib.pagesizes import A4

        pdf.drawString(60, A4[1] - 100, value)

    admin = _admin(ocr_app)
    path = _r1_two_page_pdf(tmp_path / f"r1-short-{value}.pdf", draw_second)
    upload = admin.upload(path=path, name=f"r1-short-{value}.pdf")
    assert upload.status_code == 202, upload.text
    payload = upload.json()

    result = _run(ocr_app, stub)
    assert result.state == "succeeded", result
    version = _version(ocr_app, payload["version"]["id"])
    report = version.processing_report
    assert report["blank_pages"] == [], report
    assert report["pages"][1]["status"] == "success", report["pages"][1]
    assert report["pages"][1]["source"] == "text", report["pages"][1]
    assert stub.calls == [], "可提取短文字页不得调用 OCR"

    preview = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview",
        params={"limit": 100},
    )
    assert preview.status_code == 200, preview.text
    items = preview.json()["items"]
    assert any(item["locator"]["page"] == 2 and item["text"].strip() == value for item in items), items

    published = _publish(admin, payload["document"]["id"], payload["version"]["id"])
    assert published.status_code == 200, published.text


def test_r1_vector_only_page_is_ocr_published_not_blank(ocr_app, stub, tmp_path: Path):
    def draw_second(pdf):
        pdf.setFillColorRGB(0, 0, 0)
        pdf.rect(60, 500, 200, 150, fill=1)

    admin = _admin(ocr_app)
    path = _r1_two_page_pdf(tmp_path / "r1-vector.pdf", draw_second)
    upload = admin.upload(path=path, name="r1-vector.pdf")
    assert upload.status_code == 202, upload.text
    payload = upload.json()

    result = _run(ocr_app, stub)
    assert result.state == "succeeded", result
    version = _version(ocr_app, payload["version"]["id"])
    report = version.processing_report
    assert report["blank_pages"] == [], report
    assert report["pages"][1]["status"] == "success", report["pages"][1]
    assert report["pages"][1]["source"] == "ocr", report["pages"][1]
    assert [call["page"] for call in stub.calls] == [2]

    preview = admin.client.get(
        f"/api/v1/documents/{payload['document']['id']}/versions/{payload['version']['id']}/preview",
        params={"limit": 100},
    )
    assert preview.status_code == 200, preview.text
    assert any(item["locator"]["page"] == 2 for item in preview.json()["items"])

    published = _publish(admin, payload["document"]["id"], payload["version"]["id"])
    assert published.status_code == 200, published.text


def test_r1_vector_only_page_without_ocr_blocks_publish(settings, stub, tmp_path: Path):
    def draw_second(pdf):
        pdf.setFillColorRGB(0, 0, 0)
        pdf.rect(60, 500, 200, 150, fill=1)

    app = create_app(settings, ocr_gateway=None)
    try:
        admin = _admin(app)
        path = _r1_two_page_pdf(tmp_path / "r1-vector-no-ocr.pdf", draw_second)
        upload = admin.upload(path=path, name="r1-vector-no-ocr.pdf")
        assert upload.status_code == 202, upload.text
        payload = upload.json()

        result = _run(app, None)
        assert result.state == "failed", result
        assert result.error_code == "OCR_NOT_CONFIGURED"
        version = _version(app, payload["version"]["id"])
        assert version.processing_report["blank_pages"] == []
        assert version.processing_report["failed_pages"] == [2]
        assert _publish(admin, payload["document"]["id"], payload["version"]["id"]).status_code == 409
    finally:
        app.state.db.dispose()


def _r1_cancel_via_http(control, document_id: str, version_id: str) -> int:
    response = control.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/cancel",
        headers=control.headers,
    )
    return response.status_code


def test_r1_cancel_during_rate_limit_wait_sends_no_next_page(ocr_app, stub):
    admin = _admin(ocr_app)
    control = _admin(ocr_app)
    upload = admin.upload(path=D07, name="r1-cancel-wait.pdf")
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    fake = {"now": 0.0, "status": None, "sleeps": []}

    def sleep(seconds):
        fake["sleeps"].append(seconds)
        fake["now"] += seconds
        if fake["status"] is None:
            fake["status"] = _r1_cancel_via_http(
                control, payload["document"]["id"], payload["version"]["id"]
            )

    limiter = OcrRateLimiter(clock=lambda: fake["now"], sleep=sleep)
    result = _run(ocr_app, stub, ocr_limiter=limiter)

    assert fake["status"] == 204
    assert result.state == "cancelled", result
    assert [call["page"] for call in stub.calls] == [1], "限流等待期间取消后不得再发下一页"
    records = _records(ocr_app, payload["version"]["id"])
    assert [(record.page, record.state) for record in records] == [(1, "succeeded")]
    assert _unit_count(ocr_app, payload["version"]["id"]) == 0
    assert _job(ocr_app, payload["job"]["id"]).state == "cancelled"
    assert _version(ocr_app, payload["version"]["id"]).state == "cancelled"


def test_r1_delete_during_rate_limit_wait_sends_no_next_page(ocr_app, stub):
    admin = _admin(ocr_app)
    control = _admin(ocr_app)
    upload = admin.upload(path=D07, name="r1-delete-wait.pdf")
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    revision = control.client.get(f"/api/v1/documents/{payload['document']['id']}").json()["revision"]
    fake = {"now": 0.0, "status": None, "sleeps": []}

    def sleep(seconds):
        fake["sleeps"].append(seconds)
        fake["now"] += seconds
        if fake["status"] is None:
            response = control.client.delete(
                f"/api/v1/documents/{payload['document']['id']}",
                params={"expected_revision": revision},
                headers=control.headers,
            )
            fake["status"] = response.status_code

    limiter = OcrRateLimiter(clock=lambda: fake["now"], sleep=sleep)
    result = _run(ocr_app, stub, ocr_limiter=limiter)

    assert fake["status"] == 200
    assert result.state == "cancelled", result
    assert [call["page"] for call in stub.calls] == [1], "限流等待期间删除后不得再发下一页"
    records = _records(ocr_app, payload["version"]["id"])
    assert [(record.page, record.state) for record in records] == [(1, "succeeded")]
    assert _document(ocr_app, payload["document"]["id"]).deleted is True
    assert _version(ocr_app, payload["version"]["id"]).state == "deleted"
    assert _job(ocr_app, payload["job"]["id"]).state == "cancelled"


def test_r1_lease_expiry_during_rate_limit_wait_sends_no_next_page(ocr_app, stub):
    admin = _admin(ocr_app)
    upload = admin.upload(path=D07, name="r1-lease-wait.pdf")
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    base = datetime(2026, 10, 29, 0, 0, 0, tzinfo=timezone.utc)
    fake = {"mono": 0.0, "wall": 0.0, "sleeps": []}

    def sleep(seconds):
        fake["sleeps"].append(seconds)
        fake["mono"] += seconds
        fake["wall"] += 200.0

    limiter = OcrRateLimiter(clock=lambda: fake["mono"], sleep=sleep)
    result = _run(
        ocr_app,
        stub,
        ocr_limiter=limiter,
        lease_seconds=120,
        now_fn=lambda: base + timedelta(seconds=fake["wall"]),
    )

    assert result.state == "lease_lost", result
    assert [call["page"] for call in stub.calls] == [1], "租约在限流等待期间失效后不得再发下一页"
    records = _records(ocr_app, payload["version"]["id"])
    assert [(record.page, record.state) for record in records] == [(1, "succeeded")]
    assert _unit_count(ocr_app, payload["version"]["id"]) == 0
    assert _job(ocr_app, payload["job"]["id"]).state == "running"
    assert _version(ocr_app, payload["version"]["id"]).state == "processing"


def test_r1_cancel_during_retry_wait_sends_no_retry(ocr_app, stub):
    admin = _admin(ocr_app)
    control = _admin(ocr_app)
    upload = admin.upload(path=D09, name="r1-retry-wait.png")
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    state = {"calls": 0}

    def behavior(page, mode, call_number):
        state["calls"] += 1
        if state["calls"] == 1:
            raise OCRRateLimited("simulated 429")
        return OCRPageResult(text="retry ok", provider_request_id="req-retry", confidence=90.0)

    stub.default = behavior
    fake = {"cancelled": False}

    def on_sleep(seconds):
        if fake["cancelled"]:
            return
        fake["cancelled"] = True
        fake["status"] = _r1_cancel_via_http(
            control, payload["document"]["id"], payload["version"]["id"]
        )

    limiter = OcrRateLimiter(max_per_second=2.0, clock=lambda: 0.0, sleep=lambda _seconds: None)
    result = _run(
        ocr_app,
        stub,
        ocr_limiter=limiter,
        ocr_options={
            "max_attempts": 3,
            "retry_base_seconds": 0.25,
            "retry_max_single_seconds": 0.5,
            "retry_total_seconds": 2.0,
            "sleep": on_sleep,
        },
    )

    assert fake["status"] == 204
    assert result.state == "cancelled", result
    assert len(stub.calls) == 1, "重试等待期间取消后不得再发请求"
    records = _records(ocr_app, payload["version"]["id"])
    assert [(record.page, record.state) for record in records] == [(1, "failed")]
    assert records[0].error_code == "OCR_RATE_LIMITED"
