"""T08-R1B 后端回归：版本任务发现、跨会话重试、旧有效版/检查点与权限边界。

只使用受控 OCR 替身与隔离 SQLite；不调用真实 OCR/模型，不修改既有测试。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from conftest import current_csrf, login, upload_document, write_headers
from mktkb.documents.models import DocumentVersion
from mktkb.ingestion.models import ImportJob
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.providers.types import OCRPageResult, OCRQuotaUnavailable

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance" / "normal"
D01 = FIXTURES / "D01_物品位置表.xlsx"
D05 = FIXTURES / "D05_物料领用规范.pdf"
D07 = FIXTURES / "D07_活动申请扫描件.pdf"
D09 = FIXTURES / "D09_物料领用通知.png"
V03 = ROOT / "fixtures" / "acceptance" / "variants" / "V03_物品位置表_历史V1.xlsx"


class StubOCR:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.behaviors: dict = {}
        self.default = None

    def recognize(self, page, *, mode):
        self.calls.append({"page": page.page, "mode": mode})
        behavior = self.behaviors.get(page.page, self.default)
        if isinstance(behavior, Exception):
            raise behavior
        return OCRPageResult(
            text=f"扫描页第{page.page}页",
            provider_request_id=f"r1b-{page.page}",
            confidence=90.0,
        )


@pytest.fixture
def stub() -> StubOCR:
    return StubOCR()


@pytest.fixture
def r1b_app(settings, stub):
    application = create_app(settings, ocr_gateway=stub)
    yield application
    application.state.db.dispose()


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


def _admin(app) -> SimpleNamespace:
    return _session(app, "admin", "AdminPass-1")


def _run(app, stub: StubOCR):
    db = app.state.db.session()
    try:
        return run_one_job(db, app.state.store, ocr=stub)
    finally:
        db.close()


def _detail(session, document_id: str) -> dict:
    response = session.client.get(f"/api/v1/documents/{document_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _publish(session, document_id: str, version_id: str) -> None:
    detail = _detail(session, document_id)
    response = session.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={
            "expected_active_version_id": (detail["document"]["active_version"] or {}).get("id"),
            "expected_revision": detail["revision"],
        },
        headers=session.headers,
    )
    assert response.status_code == 200, response.text


def _jobs_by_version(detail: dict) -> dict[str, dict]:
    return {job["version_id"]: job for job in detail["jobs"]}


def test_document_detail_exposes_jobs_scoped_to_own_document_versions(r1b_app, stub):
    admin = _admin(r1b_app)

    first = admin.upload(path=D01, name="物品位置表.xlsx").json()
    assert _run(r1b_app, stub).state == "succeeded"
    _publish(admin, first["document"]["id"], first["version"]["id"])
    second = admin.upload(
        path=V03,
        name="物品位置表.xlsx",
        document_id=first["document"]["id"],
        expected_active_version_id=first["version"]["id"],
    ).json()
    assert _run(r1b_app, stub).state == "succeeded"

    other = admin.upload(path=D09, name="物料领用通知.png").json()
    stub.default = OCRQuotaUnavailable()
    blocked = _run(r1b_app, stub)
    assert blocked.state == "blocked"

    detail = _detail(admin, first["document"]["id"])
    jobs = _jobs_by_version(detail)
    assert set(jobs) == {first["version"]["id"], second["version"]["id"]}
    assert jobs[first["version"]["id"]]["id"] == first["job"]["id"]
    assert jobs[first["version"]["id"]]["state"] == "succeeded"
    assert jobs[second["version"]["id"]]["id"] == second["job"]["id"]
    assert other["job"]["id"] not in {job["id"] for job in detail["jobs"]}, "不得混入其它资料的任务"

    other_detail = _detail(admin, other["document"]["id"])
    other_jobs = _jobs_by_version(other_detail)
    assert set(other_jobs) == {other["version"]["id"]}
    assert other_jobs[other["version"]["id"]]["id"] == other["job"]["id"]
    assert other_jobs[other["version"]["id"]]["state"] == "blocked"
    assert other_jobs[other["version"]["id"]]["retryable"] is True
    assert other_jobs[other["version"]["id"]]["error_code"] == "OCR_QUOTA_UNAVAILABLE"

    employee = _session(r1b_app, "employee", "EmployeePass-1")
    anonymous = TestClient(r1b_app, raise_server_exceptions=False)
    assert employee.client.get(f"/api/v1/documents/{first['document']['id']}").status_code == 403
    assert anonymous.get(f"/api/v1/documents/{first['document']['id']}").status_code == 401
    assert (
        employee.client.post(
            f"/api/v1/jobs/{other['job']['id']}/retry", headers=employee.headers
        ).status_code
        == 403
    )
    assert anonymous.post(f"/api/v1/jobs/{other['job']['id']}/retry").status_code == 401


def test_blocked_job_retry_from_fresh_admin_session_preserves_active_and_checkpoint(r1b_app, stub):
    admin = _admin(r1b_app)
    active = admin.upload(path=D05, name="物料领用规范.pdf").json()
    db = r1b_app.state.db.session()
    try:
        assert run_one_job(db, r1b_app.state.store, ocr=stub).state == "succeeded"
    finally:
        db.close()
    _publish(admin, active["document"]["id"], active["version"]["id"])

    pending = admin.upload(
        path=D07,
        name="物料领用规范.pdf",
        document_id=active["document"]["id"],
        expected_active_version_id=active["version"]["id"],
    ).json()
    stub.behaviors[3] = OCRQuotaUnavailable()
    first = _run(r1b_app, stub)
    assert first.state == "blocked" and first.error_code == "OCR_QUOTA_UNAVAILABLE"

    before = _detail(admin, active["document"]["id"])
    assert before["document"]["active_version"]["id"] == active["version"]["id"]
    assert before["document"]["active_version"]["state"] == "published"
    pending_before = _jobs_by_version(before)[pending["version"]["id"]]
    assert pending_before["id"] == pending["job"]["id"]
    assert pending_before["state"] == "blocked"
    assert pending_before["retryable"] is True
    assert pending_before["error_code"] == "OCR_QUOTA_UNAVAILABLE"

    # 新浏览器上下文/退出重登等价：全新会话重新登录后只凭服务端详情发现同一任务。
    fresh = _admin(r1b_app)
    fresh_detail = _detail(fresh, active["document"]["id"])
    discovered = _jobs_by_version(fresh_detail)[pending["version"]["id"]]
    assert discovered["id"] == pending["job"]["id"]
    retried = fresh.client.post(f"/api/v1/jobs/{discovered['id']}/retry", headers=fresh.headers)
    assert retried.status_code == 202, retried.text
    assert retried.json()["id"] == pending["job"]["id"]
    assert retried.json()["state"] == "queued"
    duplicate = fresh.client.post(f"/api/v1/jobs/{discovered['id']}/retry", headers=fresh.headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "JOB_ALREADY_QUEUED"

    db = r1b_app.state.db.session()
    try:
        job_count = int(
            db.scalar(
                select(func.count())
                .select_from(ImportJob)
                .where(ImportJob.version_id == uuid.UUID(pending["version"]["id"]))
            )
            or 0
        )
        assert job_count == 1, "重试必须复用同一任务，不产生重复任务"
    finally:
        db.close()

    stub.behaviors.pop(3)
    calls_before = len(stub.calls)
    recovered = _run(r1b_app, stub)
    assert recovered.state == "succeeded", recovered
    assert recovered.units_written == 6 and recovered.units_reused == 2
    pages_called = [call["page"] for call in stub.calls[calls_before:]]
    assert pages_called == [3, 4, 5, 6, 7, 8], "已成功页复用检查点，不重复 OCR"

    after = _detail(_admin(r1b_app), active["document"]["id"])
    assert after["document"]["active_version"]["id"] == active["version"]["id"], "重试成功不切换有效版本"
    pending_after = _jobs_by_version(after)[pending["version"]["id"]]
    assert pending_after["id"] == pending["job"]["id"]
    assert pending_after["state"] == "succeeded"
    version_after = next(item for item in after["versions"] if item["id"] == pending["version"]["id"])
    assert version_after["state"] == "review_required"
    preview = admin.client.get(
        f"/api/v1/documents/{active['document']['id']}/versions/{pending['version']['id']}/preview",
        params={"limit": 100},
    )
    assert preview.status_code == 200
    assert [item["locator"]["page"] for item in preview.json()["items"]] == list(range(1, 9))


def test_cancelled_and_deleted_documents_expose_non_retryable_jobs_and_reject_retry(r1b_app, stub):
    admin = _admin(r1b_app)
    stub.default = OCRQuotaUnavailable()

    cancelled = admin.upload(path=D07, name="待取消扫描件.pdf").json()
    assert _run(r1b_app, stub).state == "blocked"
    cancel = admin.client.post(
        f"/api/v1/documents/{cancelled['document']['id']}/versions/{cancelled['version']['id']}/cancel",
        headers=admin.headers,
    )
    assert cancel.status_code == 204, cancel.text
    cancelled_detail = _detail(admin, cancelled["document"]["id"])
    cancelled_job = _jobs_by_version(cancelled_detail)[cancelled["version"]["id"]]
    assert cancelled_job["state"] == "blocked"
    assert cancelled_job["retryable"] is False
    cancelled_retry = admin.client.post(f"/api/v1/jobs/{cancelled['job']['id']}/retry", headers=admin.headers)
    assert cancelled_retry.status_code == 409
    assert cancelled_retry.json()["error"]["code"] == "JOB_NOT_RETRYABLE"

    deleted = admin.upload(path=D09, name="待删除通知.png").json()
    assert _run(r1b_app, stub).state == "blocked"
    revision = _detail(admin, deleted["document"]["id"])["revision"]
    removed = admin.client.delete(
        f"/api/v1/documents/{deleted['document']['id']}?expected_revision={revision}",
        headers=admin.headers,
    )
    assert removed.status_code == 200, removed.text
    deleted_detail = _detail(admin, deleted["document"]["id"])
    deleted_job = _jobs_by_version(deleted_detail)[deleted["version"]["id"]]
    assert deleted_job["state"] == "blocked"
    assert deleted_job["retryable"] is False
    deleted_retry = admin.client.post(f"/api/v1/jobs/{deleted['job']['id']}/retry", headers=admin.headers)
    assert deleted_retry.status_code == 410
    assert deleted_retry.json()["error"]["code"] == "CONTENT_UNAVAILABLE"

    db = r1b_app.state.db.session()
    try:
        states = {
            row.id: row.state
            for row in db.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.id.in_(
                        [uuid.UUID(cancelled["version"]["id"]), uuid.UUID(deleted["version"]["id"])]
                    )
                )
            ).all()
        }
    finally:
        db.close()
    assert states[uuid.UUID(cancelled["version"]["id"])] == "cancelled"
    assert states[uuid.UUID(deleted["version"]["id"])] == "deleted"
