"""T04 生命周期集成检查：发布、取消、逻辑删除、revision/有效总量与迟到 worker 保护。

只使用项目临时数据目录、真实 HTTP 上传/查询与单次 worker；并发用独立 Session/连接与
可控屏障。故障注入（报告缺失/quality=false/任务状态改写/commit 失败）与真实成功链路分开标注。
"""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import docx
import openpyxl
import pytest
from sqlalchemy import func, select

from mktkb.documents.lifecycle import (
    cancel_version,
    delete_document,
    get_revision,
    publish_version,
    visible_source_units_stmt,
)
from mktkb.documents.models import (
    DeletionReceipt,
    Document,
    DocumentVersion,
    KnowledgeState,
    PublicationReceipt,
    SourceUnit,
)
from mktkb.documents.service import stage_upload, UploadInput
from mktkb.errors import (
    ApiError,
    ContentUnavailable,
    PublishConflict,
    VersionNotCancellable,
    VersionNotPublishable,
)
from mktkb.ingestion.models import ImportJob
from mktkb.ingestion.parsers.types import ParseError, ParsedUnit
from mktkb.ingestion.worker import claim_job, retry_job, run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
D03 = FIXTURES / "normal" / "D03_市场部工作指南.docx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
V04 = FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx"
V05 = FIXTURES / "variants" / "V05_物品位置表_新版V3_移除P01.xlsx"


# ---------------------------------------------------------------- 辅助


def _session(app):
    return app.state.db.session()


def _run_worker(app, **kwargs):
    db = _session(app)
    try:
        return run_one_job(db, app.state.store, **kwargs)
    finally:
        db.close()


def _upload(
    admin_write,
    *,
    path=None,
    content=None,
    name=None,
    document_id=None,
    expected_active_version_id=None,
    allow_same_name=None,
):
    response = admin_write.upload(
        path=path,
        content=content,
        name=name,
        document_id=document_id,
        expected_active_version_id=expected_active_version_id,
        allow_same_name=allow_same_name,
    )
    assert response.status_code == 202, response.text
    return response.json()


def _detail(admin_write, document_id):
    response = admin_write.client.get(f"/api/v1/documents/{document_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _publish_http(admin_write, document_id, version_id, *, expected_active_version_id, expected_revision):
    return admin_write.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={
            "expected_active_version_id": expected_active_version_id,
            "expected_revision": expected_revision,
        },
        headers=admin_write.headers,
    )


def _cancel_http(admin_write, document_id, version_id):
    return admin_write.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/cancel", headers=admin_write.headers
    )


def _delete_http(admin_write, document_id, expected_revision):
    return admin_write.client.delete(
        f"/api/v1/documents/{document_id}",
        params={"expected_revision": expected_revision},
        headers=admin_write.headers,
    )


def _preview_http(admin_write, document_id, version_id):
    return admin_write.client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/preview", params={"limit": 20}
    )


def _file_http(admin_write, document_id, version_id):
    return admin_write.client.get(f"/api/v1/documents/{document_id}/versions/{version_id}/file")


def _state(app):
    db = _session(app)
    try:
        row = db.get(KnowledgeState, 1)
        return (int(row.revision), int(row.active_document_count), int(row.active_excel_row_count))
    finally:
        db.close()


def _revision(app) -> int:
    return _state(app)[0]


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _recomputed_totals(app):
    db = _session(app)
    try:
        documents = db.scalar(
            select(func.count()).select_from(Document).where(Document.deleted.is_(False), Document.active_version_id.is_not(None))
        )
        rows = db.scalar(
            select(func.count())
            .select_from(SourceUnit)
            .join(DocumentVersion, SourceUnit.version_id == DocumentVersion.id)
            .join(Document, SourceUnit.document_id == Document.id)
            .where(
                Document.deleted.is_(False),
                Document.active_version_id == DocumentVersion.id,
                DocumentVersion.state == "published",
                Document.file_type == "xlsx",
                SourceUnit.kind == "table_row",
            )
        )
        return int(documents or 0), int(rows or 0)
    finally:
        db.close()


def _published(app, admin_write, path=None, *, content=None, name=None):
    record = _upload(admin_write, path=path, content=content, name=name)
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, record["document"]["id"])
    active = detail["document"]["active_version"]["id"] if detail["document"]["active_version"] else None
    response = _publish_http(
        admin_write,
        record["document"]["id"],
        record["version"]["id"],
        expected_active_version_id=active,
        expected_revision=detail["revision"],
    )
    assert response.status_code == 200, response.text
    return record, response.json(), detail


def _uncached_formula_xlsx() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "公式"
    sheet.append(["=1+1", "=2+2"])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _simple_xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "记录"
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _docx_with_table(paragraph: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(paragraph)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "名称", "数量"
    table.cell(1, 0).text, table.cell(1, 1).text = "展架", "2"
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def _preview_units(admin_write, document_id, version_id):
    response = _preview_http(admin_write, document_id, version_id)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _document_row(app, document_id):
    db = _session(app)
    try:
        db.expire_all()
        return db.get(Document, _as_uuid(document_id))
    finally:
        db.close()


def _version_row(app, version_id):
    db = _session(app)
    try:
        db.expire_all()
        return db.get(DocumentVersion, _as_uuid(version_id))
    finally:
        db.close()


def _job_row(app, job_id):
    db = _session(app)
    try:
        db.expire_all()
        return db.get(ImportJob, _as_uuid(job_id))
    finally:
        db.close()


def _unit_count(app, version_id) -> int:
    db = _session(app)
    try:
        return int(
            db.scalar(
                select(func.count()).select_from(SourceUnit).where(SourceUnit.version_id == _as_uuid(version_id))
            )
            or 0
        )
    finally:
        db.close()


# ---------------------------------------------------------------- P01 权限、参数与发布前置条件


def test_publish_requires_admin_and_complete_review(app, admin_write, client, employee_write):
    record = _upload(admin_write, path=D01, name="物品位置表.xlsx")
    assert _run_worker(app).state == "succeeded"
    document_id, version_id = record["document"]["id"], record["version"]["id"]
    detail = _detail(admin_write, document_id)
    revision = detail["revision"]
    body = {"expected_active_version_id": None, "expected_revision": revision}
    publish_url = f"/api/v1/documents/{document_id}/versions/{version_id}/publish"
    cancel_url = f"/api/v1/documents/{document_id}/versions/{version_id}/cancel"
    delete_url = f"/api/v1/documents/{document_id}"

    assert client.post(publish_url, json=body).status_code == 401
    assert employee_write.client.post(publish_url, json=body, headers=employee_write.headers).status_code == 403
    assert client.post(cancel_url).status_code == 401
    assert employee_write.client.post(cancel_url, headers=employee_write.headers).status_code == 403
    assert client.delete(delete_url, params={"expected_revision": revision}).status_code == 401
    assert (
        employee_write.client.delete(
            delete_url, params={"expected_revision": revision}, headers=employee_write.headers
        ).status_code
        == 403
    )

    csrf = admin_write.csrf
    assert admin_write.client.post(publish_url, json=body, headers={"X-CSRF-Token": csrf}).status_code == 403
    assert admin_write.client.post(publish_url, json=body, headers={"Origin": "http://testserver"}).status_code == 403
    assert (
        admin_write.client.post(
            publish_url, json=body, headers={"Origin": "http://evil.test", "X-CSRF-Token": csrf}
        ).status_code
        == 403
    )
    assert (
        admin_write.client.post(
            publish_url, json=body, headers={"Origin": "http://testserver", "X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert admin_write.client.post(publish_url, json={"expected_revision": revision}, headers=admin_write.headers).status_code == 422
    assert (
        admin_write.client.post(
            publish_url, json={"expected_active_version_id": None, "expected_revision": True}, headers=admin_write.headers
        ).status_code
        == 422
    )
    assert (
        admin_write.client.post(
            publish_url, json={"expected_active_version_id": None, "expected_revision": -1}, headers=admin_write.headers
        ).status_code
        == 422
    )
    assert admin_write.client.delete(delete_url, headers=admin_write.headers).status_code == 422
    assert (
        admin_write.client.delete(
            delete_url, params={"expected_revision": "true"}, headers=admin_write.headers
        ).status_code
        == 422
    )

    other = _upload(admin_write, path=D02, name="合作店家信息.xlsx")
    assert _run_worker(app).state == "succeeded"
    cross = admin_write.client.post(
        f"/api/v1/documents/{other['document']['id']}/versions/{version_id}/publish",
        json=body,
        headers=admin_write.headers,
    )
    assert cross.status_code == 404

    # 不可发布状态：failed / 报告缺失 / quality=false / 任务未成功 / processing / queued
    before = _state(app)

    failed = _upload(admin_write, content=_uncached_formula_xlsx(), name="无缓存公式.xlsx")
    assert _run_worker(app).state == "failed"
    response = _publish_http(
        admin_write,
        failed["document"]["id"],
        failed["version"]["id"],
        expected_active_version_id=None,
        expected_revision=revision,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"

    missing_report = _upload(admin_write, path=D03, name="工作指南.docx")
    assert _run_worker(app).state == "succeeded"
    db = _session(app)
    try:
        version = db.get(DocumentVersion, uuid.UUID(missing_report["version"]["id"]))
        report_backup = version.processing_report
        version.processing_report = None
        db.commit()
    finally:
        db.close()
    response = _publish_http(
        admin_write,
        missing_report["document"]["id"],
        missing_report["version"]["id"],
        expected_active_version_id=None,
        expected_revision=revision,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"
    db = _session(app)
    try:
        db.get(DocumentVersion, uuid.UUID(missing_report["version"]["id"])).processing_report = report_backup
        db.commit()
    finally:
        db.close()

    quality_false = _upload(admin_write, content=_docx_with_table("报价单说明"), name="带表格说明.docx")
    assert _run_worker(app).state == "succeeded"
    db = _session(app)
    try:
        version = db.get(DocumentVersion, uuid.UUID(quality_false["version"]["id"]))
        report = dict(version.processing_report)
        report["quality"] = {"complete": False, "issues": [{"issue": "simulated"}]}
        version.processing_report = report
        db.commit()
    finally:
        db.close()
    response = _publish_http(
        admin_write,
        quality_false["document"]["id"],
        quality_false["version"]["id"],
        expected_active_version_id=None,
        expected_revision=revision,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"

    job_not_succeeded = _upload(admin_write, path=D04, name="活动策划流程.docx")
    assert _run_worker(app).state == "succeeded"
    db = _session(app)
    try:
        job = db.get(ImportJob, uuid.UUID(job_not_succeeded["job"]["id"]))
        job.state = "running"
        db.commit()
    finally:
        db.close()
    response = _publish_http(
        admin_write,
        job_not_succeeded["document"]["id"],
        job_not_succeeded["version"]["id"],
        expected_active_version_id=None,
        expected_revision=revision,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"
    db = _session(app)
    try:
        job = db.get(ImportJob, uuid.UUID(job_not_succeeded["job"]["id"]))
        job.state = "succeeded"
        db.commit()
    finally:
        db.close()

    processing = _upload(admin_write, path=V05, name="移除P01.xlsx")
    db = _session(app)
    try:
        lease = claim_job(db)
        assert lease is not None and str(lease.version_id) == processing["version"]["id"]
    finally:
        db.close()
    response = _publish_http(
        admin_write,
        processing["document"]["id"],
        processing["version"]["id"],
        expected_active_version_id=None,
        expected_revision=revision,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"

    queued = _upload(admin_write, path=V04, name="新版V3.xlsx")
    response = _publish_http(
        admin_write,
        queued["document"]["id"],
        queued["version"]["id"],
        expected_active_version_id=None,
        expected_revision=revision,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"

    assert _state(app) == before, "非法发布不得改变 revision/有效总量"

    # 真实完整 xlsx 与 docx 发布
    detail = _detail(admin_write, document_id)
    response = _publish_http(
        admin_write,
        document_id,
        version_id,
        expected_active_version_id=None,
        expected_revision=detail["revision"],
    )
    assert response.status_code == 200, response.text
    publication = response.json()
    assert publication["document_id"] == document_id and publication["active_version_id"] == version_id
    assert publication["revision"] == detail["revision"] + 1

    detail = _detail(admin_write, missing_report["document"]["id"])
    response = _publish_http(
        admin_write,
        missing_report["document"]["id"],
        missing_report["version"]["id"],
        expected_active_version_id=None,
        expected_revision=detail["revision"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == detail["revision"] + 1


# ---------------------------------------------------------------- P02 位置更新与旧有效版保留


def test_positions_update_keeps_old_until_publish(app, admin_write):
    v3_record, publication, _ = _published(app, admin_write, V03, name="历史V1.xlsx")
    document_id = v3_record["document"]["id"]
    v3_id = v3_record["version"]["id"]
    revision = publication["revision"]

    v1_units = _preview_units(admin_write, document_id, v3_id)
    p01 = next(unit for unit in v1_units if unit["fields"].get("标识") == "P01")
    assert p01["locator"]["row"] == 8 and p01["fields"]["位置"] == "A区3号货架第二层"

    d01 = _upload(admin_write, path=D01, document_id=document_id, expected_active_version_id=v3_id, name="D01.xlsx")
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, document_id)
    assert detail["document"]["active_version"]["id"] == v3_id, "新版待确认不得切换有效版本"
    assert detail["document"]["latest_version"]["id"] == d01["version"]["id"]
    p01 = next(unit for unit in _preview_units(admin_write, document_id, v3_id) if unit["fields"].get("标识") == "P01")
    assert p01["fields"]["位置"] == "A区3号货架第二层", "发布前当前有效版仍为历史V1"

    detail = _detail(admin_write, document_id)
    response = _publish_http(
        admin_write,
        document_id,
        d01["version"]["id"],
        expected_active_version_id=v3_id,
        expected_revision=detail["revision"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == revision + 1
    detail = _detail(admin_write, document_id)
    assert detail["document"]["active_version"]["id"] == d01["version"]["id"]
    assert _version_row(app, v3_id).state == "superseded"
    p01 = next(unit for unit in _preview_units(admin_write, document_id, d01["version"]["id"]) if unit["fields"].get("标识") == "P01")
    assert p01["locator"]["row"] == 8 and p01["fields"]["位置"] == "B区1号货架第二层"

    old_file = _version_row(app, d01["version"]["id"])
    old_published_at = old_file.published_at
    old_sha = (app.state.store.root / old_file.stored_path).read_bytes()
    old_summary = detail["document"]["active_version"]

    # 失败的新版：保留旧有效版、原件字节与发布时间
    bad = _upload(
        admin_write,
        content=_uncached_formula_xlsx(),
        name="失败新版.xlsx",
        document_id=document_id,
        expected_active_version_id=old_file.id,
    )
    assert _run_worker(app).state == "failed"
    detail = _detail(admin_write, document_id)
    assert detail["document"]["active_version"]["id"] == str(old_file.id)
    assert detail["document"]["active_version"]["published_at"] == old_summary["published_at"]
    assert detail["document"]["active_version"]["sha256"] == old_summary["sha256"]
    assert _version_row(app, bad["version"]["id"]).state == "failed"

    # 取消的新版：同样保留旧有效版
    pending = _upload(
        admin_write,
        path=V05,
        document_id=document_id,
        expected_active_version_id=old_file.id,
        name="取消新版.xlsx",
    )
    assert _cancel_http(admin_write, document_id, pending["version"]["id"]).status_code == 204
    detail = _detail(admin_write, document_id)
    assert detail["document"]["active_version"]["id"] == str(old_file.id)
    assert _version_row(app, pending["version"]["id"]).state == "cancelled"

    # 发布 V04（D区暂存柜）后旧版被替换
    v4 = _upload(
        admin_write,
        path=V04,
        document_id=document_id,
        expected_active_version_id=old_file.id,
        name="新版V3.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, document_id)
    response = _publish_http(
        admin_write,
        document_id,
        v4["version"]["id"],
        expected_active_version_id=str(old_file.id),
        expected_revision=detail["revision"],
    )
    assert response.status_code == 200, response.text
    p01 = next(
        unit for unit in _preview_units(admin_write, document_id, v4["version"]["id"]) if unit["fields"].get("标识") == "P01"
    )
    assert p01["fields"]["位置"] == "D区暂存柜"
    assert _version_row(app, old_file.id).state == "superseded"
    assert (app.state.store.root / _version_row(app, old_file.id).stored_path).read_bytes() == old_sha
    assert _version_row(app, old_file.id).published_at == old_published_at
    # superseded 旧版仍可供管理员核对（T06 员工历史来源另有限制）
    old_preview = _preview_http(admin_write, document_id, old_file.id)
    assert old_preview.status_code == 200
    old_p01 = next(unit for unit in old_preview.json()["items"] if unit["fields"].get("标识") == "P01")
    assert old_p01["fields"]["位置"] == "B区1号货架第二层"
    # 已被替换的历史版本不得被旧发布请求重新激活
    revive = _publish_http(
        admin_write,
        document_id,
        old_file.id,
        expected_active_version_id=v3_id,
        expected_revision=revision,
    )
    assert revive.status_code == 409 and revive.json()["error"]["code"] == "PUBLISH_CONFLICT"


# ---------------------------------------------------------------- P03 删除行与另一有效来源


def test_removed_row_and_other_document_visibility(app, admin_write):
    v3_record, _, _ = _published(app, admin_write, V03, name="历史V1.xlsx")
    document_id = v3_record["document"]["id"]
    d01 = _upload(
        admin_write,
        path=D01,
        document_id=document_id,
        expected_active_version_id=v3_record["version"]["id"],
        name="D01.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, document_id)
    assert (
        _publish_http(
            admin_write,
            document_id,
            d01["version"]["id"],
            expected_active_version_id=v3_record["version"]["id"],
            expected_revision=detail["revision"],
        ).status_code
        == 200
    )

    v5 = _upload(
        admin_write,
        path=V05,
        document_id=document_id,
        expected_active_version_id=d01["version"]["id"],
        name="移除P01.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, document_id)
    assert (
        _publish_http(
            admin_write,
            document_id,
            v5["version"]["id"],
            expected_active_version_id=d01["version"]["id"],
            expected_revision=detail["revision"],
        ).status_code
        == 200
    )

    db = _session(app)
    try:
        old_units = db.scalars(
            select(SourceUnit).where(SourceUnit.version_id == uuid.UUID(d01["version"]["id"]))
        ).all()
        assert any(unit.fields.get("标识") == "P01" for unit in old_units), "历史单元保留用于审计"
        visible = db.scalars(visible_source_units_stmt()).all()
        assert visible, "当前有效版本应仍有可见单元"
        assert all(unit.fields.get("标识") != "P01" for unit in visible), "删行后不得再出现 P01"
        assert {unit.version_id for unit in visible} == {uuid.UUID(v5["version"]["id"])}
    finally:
        db.close()

    # 同一事实存在于两份有效资料：删除一份后另一份仍可见
    xlsx_record, _, _ = _published(
        app,
        admin_write,
        content=_simple_xlsx([["标识", "位置"], ["P900", "B区1号货架第二层"]]),
        name="替代位置表.xlsx",
    )
    docx_record, _, _ = _published(
        app, admin_write, content=_docx_with_table("P900 位于 B区1号货架第二层"), name="位置通知.docx"
    )

    db = _session(app)
    try:
        visible_ids = {str(unit.document_id) for unit in db.scalars(visible_source_units_stmt()).all()}
    finally:
        db.close()
    assert xlsx_record["document"]["id"] in visible_ids and docx_record["document"]["id"] in visible_ids

    detail = _detail(admin_write, xlsx_record["document"]["id"])
    response = _delete_http(admin_write, xlsx_record["document"]["id"], detail["revision"])
    assert response.status_code == 200, response.text

    db = _session(app)
    try:
        remaining = db.scalars(visible_source_units_stmt()).all()
        assert all(unit.document_id != uuid.UUID(xlsx_record["document"]["id"]) for unit in remaining)
        assert any(unit.document_id == uuid.UUID(docx_record["document"]["id"]) for unit in remaining)
        assert any("P900" in unit.text for unit in remaining), "另一份有效资料仍保留同一事实"
    finally:
        db.close()


# ---------------------------------------------------------------- P04 并发发布与全库 revision


def _race_publish(app, document_id, version_ids, expected_active, expected_revision, delays):
    results: dict = {}
    barrier = threading.Barrier(len(version_ids))

    def worker(key: str, version_id: str, delay: float):
        db = _session(app)
        try:
            barrier.wait(timeout=10)
            if delay:
                time.sleep(delay)
            publication = publish_version(
                db,
                uuid.UUID(document_id),
                uuid.UUID(version_id),
                expected_active_version_id=uuid.UUID(expected_active) if expected_active else None,
                expected_revision=expected_revision,
            )
            results[key] = {"ok": True, "revision": publication.revision}
        except ApiError as exc:
            results[key] = {"ok": False, "code": exc.code, "status": exc.status_code}
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=(key, version_id, delays[key]), daemon=True)
        for key, version_id in version_ids.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive(), "并发发布线程未在限时内结束"
    return results


@pytest.mark.parametrize("winner", ["v04", "v05"])
def test_concurrent_publish_and_global_revision_cas(app, admin_write, winner):
    record, publication, _ = _published(app, admin_write, V03, name="历史V1.xlsx")
    document_id = record["document"]["id"]
    v04 = _upload(
        admin_write, path=V04, document_id=document_id, expected_active_version_id=record["version"]["id"], name="V04.xlsx"
    )
    assert _run_worker(app).state == "succeeded"
    v05 = _upload(
        admin_write, path=V05, document_id=document_id, expected_active_version_id=record["version"]["id"], name="V05.xlsx"
    )
    assert _run_worker(app).state == "succeeded"
    base_revision = _revision(app)
    delays = {"v04": 0.0, "v05": 0.0}
    delays["v05" if winner == "v04" else "v04"] = 0.2

    results = _race_publish(
        app,
        document_id,
        {"v04": v04["version"]["id"], "v05": v05["version"]["id"]},
        record["version"]["id"],
        base_revision,
        delays,
    )
    winners = [key for key, value in results.items() if value.get("ok")]
    losers = [key for key, value in results.items() if not value.get("ok")]
    assert winners == [winner], results
    assert results[losers[0]]["code"] == "PUBLISH_CONFLICT"
    assert _revision(app) == base_revision + 1
    detail = _detail(admin_write, document_id)
    expected_active = {"v04": v04["version"]["id"], "v05": v05["version"]["id"]}[winner]
    assert detail["document"]["active_version"]["id"] == expected_active
    loser_version = {"v04": v04["version"]["id"], "v05": v05["version"]["id"]}[losers[0]]
    assert _version_row(app, loser_version).state == "review_required"


def test_concurrent_publish_different_documents_share_global_revision(app, admin_write):
    _, _, _ = _published(app, admin_write, D01, name="位置表.xlsx")
    d02 = _upload(admin_write, path=D02, name="店家信息.xlsx")
    assert _run_worker(app).state == "succeeded"
    d03 = _upload(admin_write, path=D03, name="工作指南.docx")
    assert _run_worker(app).state == "succeeded"
    base_revision = _revision(app)

    results: dict = {}
    barrier = threading.Barrier(2)

    def worker(key: str, record: dict):
        db = _session(app)
        try:
            barrier.wait(timeout=10)
            publication = publish_version(
                db,
                uuid.UUID(record["document"]["id"]),
                uuid.UUID(record["version"]["id"]),
                expected_active_version_id=None,
                expected_revision=base_revision,
            )
            results[key] = {"ok": True, "revision": publication.revision}
        except ApiError as exc:
            results[key] = {"ok": False, "code": exc.code}
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("d02", d02), daemon=True),
        threading.Thread(target=worker, args=("d03", d03), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert sum(1 for value in results.values() if value.get("ok")) == 1, results
    assert any(value.get("code") == "PUBLISH_CONFLICT" for value in results.values() if not value.get("ok"))
    assert _revision(app) == base_revision + 1


# ---------------------------------------------------------------- P05 幂等重放与回滚


def test_publish_replay_conflict_and_rollback(app, admin_write):
    record, publication, detail = _published(app, admin_write, D01, name="位置表.xlsx")
    document_id, version_id = record["document"]["id"], record["version"]["id"]
    body_revision = publication["revision"] - 1

    replay = _publish_http(
        admin_write, document_id, version_id, expected_active_version_id=None, expected_revision=body_revision
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["revision"] == publication["revision"]
    assert replay.json()["published_at"] == publication["published_at"]

    db = _session(app)
    try:
        via_service = publish_version(
            db,
            uuid.UUID(document_id),
            uuid.UUID(version_id),
            expected_active_version_id=None,
            expected_revision=body_revision,
        )
    finally:
        db.close()
    assert via_service.revision == publication["revision"]
    assert _as_utc(via_service.published_at).timestamp() == _parse_ts(publication["published_at"])

    # 全库 revision 改变后旧请求不得覆盖
    _published(app, admin_write, D02, name="店家信息.xlsx")
    stale = _publish_http(
        admin_write, document_id, version_id, expected_active_version_id=None, expected_revision=body_revision
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "PUBLISH_CONFLICT"

    # 另一种旧请求（不同 expected_active_version_id）不得被泛化成成功
    mismatched = _publish_http(
        admin_write,
        document_id,
        version_id,
        expected_active_version_id=record["version"]["id"],
        expected_revision=body_revision,
    )
    assert mismatched.status_code == 409 and mismatched.json()["error"]["code"] == "PUBLISH_CONFLICT"

    # commit 失败注入：状态、revision、计数、凭据全部回滚；原件保留；修复后只成功一次
    candidate = _upload(admin_write, path=D03, name="工作指南.docx")
    assert _run_worker(app).state == "succeeded"
    before_state = _state(app)
    before_detail = _detail(admin_write, candidate["document"]["id"])
    db = _session(app)
    try:
        receipt_before = db.scalar(
            select(func.count())
            .select_from(PublicationReceipt)
            .where(PublicationReceipt.version_id == uuid.UUID(candidate["version"]["id"]))
        )
        original_commit = db.commit
        calls = {"count": 0}

        def failing_commit():
            calls["count"] += 1
            raise RuntimeError("simulated commit failure")

        db.commit = failing_commit
        try:
            with pytest.raises(RuntimeError):
                publish_version(
                    db,
                    uuid.UUID(candidate["document"]["id"]),
                    uuid.UUID(candidate["version"]["id"]),
                    expected_active_version_id=None,
                    expected_revision=before_detail["revision"],
                )
        finally:
            db.commit = original_commit
        assert calls["count"] >= 1
    finally:
        db.close()

    assert _state(app) == before_state, "commit 失败不得留下 revision/计数变化"
    assert _document_row(app, candidate["document"]["id"]).active_version_id is None
    assert _version_row(app, candidate["version"]["id"]).state == "review_required"
    db = _session(app)
    try:
        receipt_after = db.scalar(
            select(func.count())
            .select_from(PublicationReceipt)
            .where(PublicationReceipt.version_id == uuid.UUID(candidate["version"]["id"]))
        )
    finally:
        db.close()
    assert receipt_before == receipt_after == 0
    stored = _version_row(app, candidate["version"]["id"]).stored_path
    assert (app.state.store.root / stored).is_file(), "发布失败不得提前清理原件"

    detail = _detail(admin_write, candidate["document"]["id"])
    retry = _publish_http(
        admin_write,
        candidate["document"]["id"],
        candidate["version"]["id"],
        expected_active_version_id=None,
        expected_revision=detail["revision"],
    )
    assert retry.status_code == 200, retry.text
    assert _state(app)[0] == before_state[0] + 1
    again = _publish_http(
        admin_write,
        candidate["document"]["id"],
        candidate["version"]["id"],
        expected_active_version_id=None,
        expected_revision=detail["revision"],
    )
    assert again.status_code == 200
    assert again.json()["revision"] == retry.json()["revision"]
    assert _state(app)[0] == before_state[0] + 1, "重放不得二次递增 revision"


# ---------------------------------------------------------------- P06 取消


@pytest.mark.parametrize("kind", ["queued", "processing", "review_required", "failed", "cancelled"])
def test_cancel_pending_preserves_active(app, admin_write, kind):
    base_record, _, _ = _published(app, admin_write, D01, name="位置表.xlsx")
    document_id = base_record["document"]["id"]
    active_version = base_record["version"]["id"]
    active_row = _version_row(app, active_version)
    active_sha = (app.state.store.root / active_row.stored_path).read_bytes()
    active_published_at = active_row.published_at

    if kind == "failed":
        target = _upload(
            admin_write,
            content=_uncached_formula_xlsx(),
            name="取消失败版.xlsx",
            document_id=document_id,
            expected_active_version_id=active_version,
        )
    else:
        target = _upload(
            admin_write,
            path=V04,
            name="取消候选.xlsx",
            document_id=document_id,
            expected_active_version_id=active_version,
        )
    if kind == "processing":
        db = _session(app)
        try:
            lease = claim_job(db)
            assert lease is not None and str(lease.version_id) == target["version"]["id"]
        finally:
            db.close()
    elif kind == "review_required":
        assert _run_worker(app).state == "succeeded"
    elif kind == "failed":
        assert _run_worker(app).state == "failed"
    elif kind == "cancelled":
        assert _cancel_http(admin_write, document_id, target["version"]["id"]).status_code == 204

    # 另一个待处理版本（不得被连带取消）
    other = _upload(
        admin_write,
        path=V05,
        name="另一个待处理.xlsx",
        document_id=document_id,
        expected_active_version_id=active_version,
    )

    before_state = _state(app)
    response = _cancel_http(admin_write, document_id, target["version"]["id"])
    assert response.status_code == 204
    assert _cancel_http(admin_write, document_id, target["version"]["id"]).status_code == 204, "重复取消保持 204"
    assert _state(app) == before_state, "取消不得递增 revision 或改变有效总量"
    detail = _detail(admin_write, document_id)
    assert detail["document"]["active_version"]["id"] == active_version
    assert detail["document"]["latest_version"]["id"] == other["version"]["id"]
    target_summary = next(item for item in detail["versions"] if item["id"] == target["version"]["id"])
    assert target_summary["state"] == "cancelled"
    assert target_summary["processing_report"] is None, "取消版本不得通过摘要泄露处理内容"
    other_summary = next(item for item in detail["versions"] if item["id"] == other["version"]["id"])
    assert other_summary["state"] == "queued"

    assert active_row.state == "published"
    assert _version_row(app, active_version).published_at == active_published_at
    assert (app.state.store.root / _version_row(app, active_version).stored_path).read_bytes() == active_sha

    assert _preview_http(admin_write, document_id, target["version"]["id"]).status_code == 410
    file_response = _file_http(admin_write, document_id, target["version"]["id"])
    assert file_response.status_code == 410
    assert file_response.json()["error"]["code"] == "CONTENT_UNAVAILABLE"
    assert not file_response.headers.get("content-disposition")
    retry = admin_write.client.post(
        f"/api/v1/jobs/{target['job']['id']}/retry", headers=admin_write.headers
    )
    assert retry.status_code == 409

    db = _session(app)
    try:
        lease = claim_job(db)
        assert lease is not None and str(lease.version_id) == other["version"]["id"], "取消任务不得被重新领取"
    finally:
        db.close()

    published_cancel = _cancel_http(admin_write, document_id, active_version)
    assert published_cancel.status_code == 409
    assert published_cancel.json()["error"]["code"] == "VERSION_NOT_CANCELLABLE"

    # 已被替换的版本同样不可取消：真实上传并发布替换版本后旧有效版 superseded
    replacement = _upload(
        admin_write,
        path=V03,
        document_id=document_id,
        expected_active_version_id=active_version,
        name="替换历史版.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, document_id)
    replacement_response = _publish_http(
        admin_write,
        document_id,
        replacement["version"]["id"],
        expected_active_version_id=active_version,
        expected_revision=detail["revision"],
    )
    assert replacement_response.status_code == 200, replacement_response.text
    assert _version_row(app, active_version).state == "superseded"
    superseded_cancel = _cancel_http(admin_write, document_id, active_version)
    assert superseded_cancel.status_code == 409
    assert superseded_cancel.json()["error"]["code"] == "VERSION_NOT_CANCELLABLE"


# ---------------------------------------------------------------- P07 删除


def test_delete_revokes_all_content_and_is_idempotent(app, admin_write):
    # 失败资料先处理，避免后续队列顺序影响
    failed = _upload(admin_write, content=_uncached_formula_xlsx(), name="失败资料.xlsx")
    assert _run_worker(app).state == "failed"

    published, _, _ = _published(app, admin_write, D01, name="已发布资料.xlsx")
    published_id = published["document"]["id"]
    pending = _upload(
        admin_write,
        path=V04,
        name="待处理新版.xlsx",
        document_id=published_id,
        expected_active_version_id=published["version"]["id"],
    )
    never_published = _upload(admin_write, path=D02, name="未发布资料.xlsx")

    base_revision = _revision(app)

    # 旧 expected 首次删除 409 且无副作用
    stale = _delete_http(admin_write, published_id, base_revision - 1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "DELETE_CONFLICT"
    assert _state(app)[0] == base_revision
    assert _document_row(app, published_id).deleted is False

    revision = _revision(app)
    first = _delete_http(admin_write, published_id, revision)
    assert first.status_code == 200, first.text
    assert first.json() == {"document_id": published_id, "deleted": True, "revision": revision + 1}
    assert _state(app)[0] == revision + 1

    document = _document_row(app, published_id)
    assert document.deleted is True and document.active_version_id is None and document.name_key is None
    assert str(_version_row(app, published["version"]["id"]).state) == "deleted"
    assert str(_version_row(app, pending["version"]["id"]).state) == "deleted"
    assert _job_row(app, pending["job"]["id"]).state == "cancelled"
    assert _job_row(app, pending["job"]["id"]).retryable is False

    detail = _detail(admin_write, published_id)
    assert detail["document"]["deleted"] is True and detail["document"]["active_version"] is None
    assert all(item["processing_report"] is None for item in detail["versions"]), "删除后不得返回处理摘要"
    listing = admin_write.client.get("/api/v1/documents", params={"limit": 100}).json()
    assert published_id not in {item["id"] for item in listing["items"]}

    assert _preview_http(admin_write, published_id, published["version"]["id"]).status_code == 410
    file_response = _file_http(admin_write, published_id, published["version"]["id"])
    assert file_response.status_code == 410
    assert file_response.json()["error"]["code"] == "CONTENT_UNAVAILABLE"
    assert not file_response.headers.get("content-disposition")

    # 原件与旧单元保留但业务访问被状态过滤拒绝
    stored = _version_row(app, published["version"]["id"]).stored_path
    assert (app.state.store.root / stored).is_file()
    assert _unit_count(app, published["version"]["id"]) > 0

    # 删除后发布/取消/任务查询：发布与取消 410，任务仅保留无正文的稳定状态
    deleted_publish = _publish_http(
        admin_write,
        published_id,
        published["version"]["id"],
        expected_active_version_id=None,
        expected_revision=_revision(app),
    )
    assert deleted_publish.status_code == 410 and deleted_publish.json()["error"]["code"] == "CONTENT_UNAVAILABLE"
    assert _cancel_http(admin_write, published_id, pending["version"]["id"]).status_code == 410
    job_status = admin_write.client.get(f"/api/v1/jobs/{pending['job']['id']}")
    assert job_status.status_code == 200
    job_body = job_status.json()
    assert job_body["state"] == "cancelled" and job_body["message"] and "processing_report" not in job_body
    assert "text" not in job_body and "locator" not in job_body

    # 未发布资料首次删除同样 revision+1
    never_revision = _revision(app)
    never = _delete_http(admin_write, never_published["document"]["id"], never_revision)
    assert never.status_code == 200 and never.json()["revision"] == never_revision + 1

    failed_revision = _revision(app)
    failed_delete = _delete_http(admin_write, failed["document"]["id"], failed_revision)
    assert failed_delete.status_code == 200 and failed_delete.json()["revision"] == failed_revision + 1

    # 全库后来变化 + 重开连接后重复删除：返回原 Deletion，不再次递增
    _published(app, admin_write, D03, name="工作指南.docx")
    db = _session(app)
    db.close()
    repeat = _delete_http(admin_write, published_id, _revision(app))
    assert repeat.status_code == 200
    assert repeat.json() == first.json()

    # 已释放名称与指纹：相同名称/字节可作为新资料重传，旧地址仍失效
    reupload = _upload(admin_write, path=D01, name="已发布资料.xlsx")
    assert reupload["document"]["id"] != published_id
    assert _preview_http(admin_write, published_id, published["version"]["id"]).status_code == 410
    assert _preview_http(admin_write, reupload["document"]["id"], reupload["version"]["id"]).status_code in {200}

    missing = _delete_http(admin_write, str(uuid.uuid4()), _revision(app))
    assert missing.status_code == 404


# ---------------------------------------------------------------- P08 迟到 worker 结果


class _ControlledParser:
    """可控解析器：记录 next() 次数，并可在第二单元前阻塞/抛错。"""

    def __init__(self, *, gate: bool = False, raise_error: bool = False):
        self.gate_enabled = gate
        self.raise_error = raise_error
        self.resumed = threading.Event()
        self.release = threading.Event()
        self.yielded = 0

    def __call__(self, path, kind, services):
        return self._generate()

    def _generate(self):
        for index in range(2):
            if index == 1 and self.gate_enabled:
                self.resumed.set()
                assert self.release.wait(timeout=15), "测试未在限时内释放解析器"
                if self.raise_error:
                    raise ParseError("模拟迟到失败", code="PARSE_INTERNAL")
            self.yielded += 1
            yield ParsedUnit(
                kind="table_row",
                locator={"sheet": "S", "row": index + 1, "header_row": 1, "cells": [], "cell_types": {}},
                text=f"行{index + 1}",
                fields={"序号": str(index + 1)},
                warnings=[],
                unit_key=f"sheet:S:row:{index + 1}",
                sheet="S",
            )


class _CheckpointParser:
    """产出 120 个单元，在第 61 个之前阻塞；用于验证已提交检查点与未提交批次的边界。"""

    def __init__(self, total: int = 120, gate_before: int = 60):
        self.total = total
        self.gate_before = gate_before
        self.reached = threading.Event()
        self.release = threading.Event()
        self.yielded = 0

    def __call__(self, path, kind, services):
        return self._generate()

    def _generate(self):
        for index in range(self.total):
            if index == self.gate_before:
                self.reached.set()
                assert self.release.wait(timeout=15), "测试未在限时内释放解析器"
            self.yielded += 1
            yield ParsedUnit(
                kind="table_row",
                locator={"sheet": "S", "row": index + 1, "header_row": 1, "cells": [], "cell_types": {}},
                text=f"批量行{index + 1}",
                fields={"序号": str(index + 1)},
                warnings=[],
                unit_key=f"sheet:S:row:{index + 1}",
                sheet="S",
            )


def _start_worker(app, parser, lease):
    results: dict = {}

    def run():
        db = _session(app)
        try:
            results["result"] = run_one_job(db, app.state.store, parsers={"xlsx": parser}, lease=lease)
        except Exception as exc:  # 测试线程内异常也要可见
            results["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            db.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, results


def test_late_worker_results_cannot_restore_content(app, admin_write):
    # a) 取消/删除后不再调用 parser 下一单元（取消先于运行）
    record = _upload(admin_write, path=D01, name="位置表.xlsx")
    document_id, version_id = record["document"]["id"], record["version"]["id"]
    db = _session(app)
    try:
        lease = claim_job(db)
        assert lease is not None
    finally:
        db.close()
    assert _cancel_http(admin_write, document_id, version_id).status_code == 204
    parser = _ControlledParser()
    result = _run_worker(app, parsers={"xlsx": parser}, lease=lease)
    assert result.state == "cancelled"
    assert parser.yielded == 0, "取消后不得再推进解析器"
    assert _unit_count(app, version_id) == 0
    assert _version_row(app, version_id).state == "cancelled"

    # b) 删除先于运行：版本/任务不复活，解析器不被调用
    second = _upload(admin_write, path=D02, name="店家信息.xlsx")
    db = _session(app)
    try:
        lease = claim_job(db)
        assert lease is not None
    finally:
        db.close()
    revision = _revision(app)
    assert _delete_http(admin_write, second["document"]["id"], revision).status_code == 200
    parser = _ControlledParser()
    result = _run_worker(app, parsers={"xlsx": parser}, lease=lease)
    assert result.state == "cancelled"
    assert parser.yielded == 0
    assert _unit_count(app, second["version"]["id"]) == 0
    assert _version_row(app, second["version"]["id"]).state == "deleted"
    assert _job_row(app, second["job"]["id"]).state == "cancelled"
    db = _session(app)
    try:
        assert claim_job(db) is None, "删除后不得再有可领取任务"
    finally:
        db.close()

    # c) 迟到异常：解析器在第二单元前阻塞，期间取消，释放后异常不得写回状态/单元
    third = _upload(admin_write, path=D01, name="迟到异常.xlsx")
    db = _session(app)
    try:
        lease = claim_job(db)
        assert lease is not None
    finally:
        db.close()
    parser = _ControlledParser(gate=True, raise_error=True)
    thread, results = _start_worker(app, parser, lease)
    assert parser.resumed.wait(timeout=10), "解析器未进入第二单元"
    assert _cancel_http(admin_write, third["document"]["id"], third["version"]["id"]).status_code == 204
    parser.release.set()
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert "error" not in results, results
    assert results["result"].state == "cancelled"
    assert parser.yielded == 1, "第一单元未提交即取消，之后不得再产出"
    assert _unit_count(app, third["version"]["id"]) == 0
    assert _version_row(app, third["version"]["id"]).state == "cancelled"
    assert _job_row(app, third["job"]["id"]).state == "cancelled"

    # d) 租约失效：旧租约不能提交；新持有者可以合法继续
    fourth = _upload(admin_write, path=D01, name="换名位置表.xlsx", allow_same_name=True)
    db = _session(app)
    try:
        lease_a = claim_job(db, lease_seconds=1)
        assert lease_a is not None
    finally:
        db.close()
    time.sleep(1.2)
    db = _session(app)
    try:
        lease_b = claim_job(db)
        assert lease_b is not None and lease_b.token != lease_a.token
    finally:
        db.close()
    stale_result = _run_worker(app, lease=lease_a)
    assert stale_result.state == "lease_lost"
    fresh_result = _run_worker(app, lease=lease_b)
    assert fresh_result.state == "succeeded"
    assert _version_row(app, fourth["version"]["id"]).state == "review_required"

    # e) 检查点已提交 50 个单元后取消：已提交部分保留，之后未提交/迟到单元全部回滚
    bulk_rows = [["序号", "值"]] + [[str(index), f"值{index}"] for index in range(1, 120)]
    bulk = _upload(admin_write, content=_simple_xlsx(bulk_rows), name="检查点竞态.xlsx")
    db = _session(app)
    try:
        lease = claim_job(db)
        assert lease is not None and str(lease.version_id) == bulk["version"]["id"]
    finally:
        db.close()
    parser = _CheckpointParser()
    thread, results = _start_worker(app, parser, lease)
    assert parser.reached.wait(timeout=10), "未到达检查点后的阻塞点"
    assert _cancel_http(admin_write, bulk["document"]["id"], bulk["version"]["id"]).status_code == 204
    parser.release.set()
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert "error" not in results, results
    assert results["result"].state == "cancelled"
    assert _unit_count(app, bulk["version"]["id"]) == 50, "已提交检查点保留 50 个，未提交批次不得落库"
    assert parser.yielded == 61
    assert _version_row(app, bulk["version"]["id"]).state == "cancelled"

    # f) 删除后重试不得复活任务
    failed = _upload(admin_write, content=_uncached_formula_xlsx(), name="失败可重试.xlsx")
    assert _run_worker(app).state == "failed"
    revision = _revision(app)
    assert _delete_http(admin_write, failed["document"]["id"], revision).status_code == 200
    db = _session(app)
    try:
        with pytest.raises(ContentUnavailable):
            retry_job(db, uuid.UUID(failed["job"]["id"]))
    finally:
        db.close()


# ---------------------------------------------------------------- P09 revision、计数与迁移


def test_counts_migrations_and_expected_revision_read(app, admin_write):
    first = _upload(admin_write, path=D01, name="位置表.xlsx")
    assert _run_worker(app).state == "succeeded"
    assert _state(app) == (0, 0, 0), "上传/处理成功不得递增 revision 或有效总量"
    detail = _detail(admin_write, first["document"]["id"])
    response = _publish_http(
        admin_write,
        first["document"]["id"],
        first["version"]["id"],
        expected_active_version_id=None,
        expected_revision=detail["revision"],
    )
    assert response.status_code == 200, response.text
    publication = response.json()
    assert publication["revision"] == 1
    documents, rows = _recomputed_totals(app)
    assert _state(app)[1:] == (documents, rows) == (1, 9)

    detail = _detail(admin_write, first["document"]["id"])
    assert detail["revision"] == publication["revision"]
    second = _upload(admin_write, path=D02, name="店家信息.xlsx")
    assert _run_worker(app).state == "succeeded"
    response = _publish_http(
        admin_write,
        second["document"]["id"],
        second["version"]["id"],
        expected_active_version_id=None,
        expected_revision=detail["revision"],
    )
    assert response.status_code == 200, "详情读取的 revision 可直接用于下一次写请求"
    documents, rows = _recomputed_totals(app)
    assert _state(app)[1:] == (documents, rows) == (2, 13)

    # Word 表格行不计入 Excel 总量
    docx_record = _upload(admin_write, content=_docx_with_table("流程说明"), name="流程说明.docx")
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, docx_record["document"]["id"])
    assert (
        _publish_http(
            admin_write,
            docx_record["document"]["id"],
            docx_record["version"]["id"],
            expected_active_version_id=None,
            expected_revision=detail["revision"],
        ).status_code
        == 200
    )
    documents, rows = _recomputed_totals(app)
    assert _state(app)[1:] == (documents, rows) == (3, 13), "Word 表格不计 Excel 行"

    # 替换：V05 比 D01 少 P01 一行
    v5 = _upload(
        admin_write,
        path=V05,
        document_id=first["document"]["id"],
        expected_active_version_id=first["version"]["id"],
        name="移除P01.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    detail = _detail(admin_write, first["document"]["id"])
    assert (
        _publish_http(
            admin_write,
            first["document"]["id"],
            v5["version"]["id"],
            expected_active_version_id=first["version"]["id"],
            expected_revision=detail["revision"],
        ).status_code
        == 200
    )
    documents, rows = _recomputed_totals(app)
    assert _state(app)[1:] == (documents, rows) == (3, 12), "替换先减旧版再加新版"

    # 取消不改变总量；删除只减一次
    pending = _upload(
        admin_write,
        path=V04,
        document_id=first["document"]["id"],
        expected_active_version_id=v5["version"]["id"],
        name="取消候选.xlsx",
    )
    before = _state(app)
    assert _cancel_http(admin_write, first["document"]["id"], pending["version"]["id"]).status_code == 204
    assert _state(app) == before
    revision = _revision(app)
    assert _delete_http(admin_write, second["document"]["id"], revision).status_code == 200
    documents, rows = _recomputed_totals(app)
    assert _state(app)[1:] == (documents, rows) == (2, 8)


def test_migrations_upgrade_from_0002_and_reopen(tmp_path: Path):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from mktkb.auth.models import LoginSession, User
    from mktkb.auth.service import bootstrap_accounts
    from mktkb.db import Database, MIGRATIONS_DIR, current_revision, run_migrations

    root = tmp_path / "migrate"
    root.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{(root / 'mktkb.sqlite3').as_posix()}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0002_documents")

    storage = root / "storage" / "originals" / "aa"
    storage.mkdir(parents=True, exist_ok=True)
    (storage / "old.xlsx").write_bytes(b"PK-old-original")
    (storage / "pub.xlsx").write_bytes(b"PK-published-original")

    database = Database(url)
    now = datetime.now(timezone.utc)
    with database.session_scope() as session:
        bootstrap_accounts(
            session,
            admin_username="admin",
            admin_password="AdminPass-1",
            admin_display_name="演示管理员",
            employee_username="employee",
            employee_password="EmployeePass-1",
            employee_display_name="演示员工",
            rounds=4,
        )
        admin = session.scalar(select(User).where(User.username == "admin"))
        session.add(LoginSession(user_id=admin.id, token_hash="a" * 64, expires_at=now + timedelta(hours=1)))

        pending_doc = Document(
            id=uuid.uuid4(),
            name="旧库资料.xlsx",
            name_key="旧库资料.xlsx",
            file_type="xlsx",
            active_version_id=None,
            latest_version_number=1,
            deleted=False,
            created_at=now,
        )
        session.add(pending_doc)
        session.flush()
        pending_version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=pending_doc.id,
            number=1,
            state="processing",
            sha256="b" * 64,
            size_bytes=15,
            stored_path="originals/aa/old.xlsx",
            uploaded_at=now,
        )
        session.add(pending_version)
        session.flush()
        session.add(
            ImportJob(
                id=uuid.uuid4(),
                version_id=pending_version.id,
                state="running",
                stage="parsing",
                completed_pages=1,
                total_pages=2,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            SourceUnit(
                document_id=pending_doc.id,
                version_id=pending_version.id,
                kind="table_row",
                ordinal=0,
                unit_key="old:k1",
                sheet="S",
                locator={"sheet": "S", "row": 2},
                text="旧单元",
                fields={"标识": "P900"},
            )
        )

        published_doc = Document(
            id=uuid.uuid4(),
            name="已发布资料.xlsx",
            name_key="已发布资料.xlsx",
            file_type="xlsx",
            latest_version_number=1,
            deleted=False,
            created_at=now,
        )
        session.add(published_doc)
        session.flush()
        published_version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=published_doc.id,
            number=1,
            state="published",
            sha256="c" * 64,
            size_bytes=20,
            stored_path="originals/aa/pub.xlsx",
            uploaded_at=now,
            published_at=now,
        )
        session.add(published_version)
        session.flush()
        published_doc.active_version_id = published_version.id
        session.add(
            SourceUnit(
                document_id=published_doc.id,
                version_id=published_version.id,
                kind="table_row",
                ordinal=0,
                unit_key="pub:k1",
                sheet="S",
                locator={"sheet": "S", "row": 2},
                text="有效单元",
                fields={"标识": "P901"},
            )
        )
        session.add(
            SourceUnit(
                document_id=published_doc.id,
                version_id=published_version.id,
                kind="paragraph",
                ordinal=1,
                unit_key="pub:p1",
                sheet=None,
                locator={"paragraph": 1},
                text="段落不计 Excel 行",
                fields={},
            )
        )
    database.dispose()

    run_migrations(url)
    assert current_revision(url) == "0006_ocr_call_records"
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0006_ocr_call_records"]

    database = Database(url)
    try:
        with database.session_scope() as session:
            state = session.get(KnowledgeState, 1)
            assert int(state.revision) == 0, "旧库升级初始化 revision=0，不按应用版本推算"
            assert (int(state.active_document_count), int(state.active_excel_row_count)) == (1, 1)
            assert session.scalar(select(func.count()).select_from(User)) == 2
            assert session.scalar(select(func.count()).select_from(LoginSession)) == 1
            assert session.scalar(select(func.count()).select_from(Document)) == 2
            assert session.scalar(select(func.count()).select_from(ImportJob)) == 1
            pending_version = session.scalar(
                select(DocumentVersion).where(DocumentVersion.state == "processing")
            )
            assert pending_version is not None
            assert session.scalar(select(func.count()).select_from(SourceUnit)) == 3
        assert (storage / "old.xlsx").read_bytes() == b"PK-old-original"
        assert (storage / "pub.xlsx").read_bytes() == b"PK-published-original"
        # 二次升级与重开连接不重置状态、计数或数据
        run_migrations(url)
        with database.session_scope() as session:
            state = session.get(KnowledgeState, 1)
            assert int(state.revision) == 0
            assert (int(state.active_document_count), int(state.active_excel_row_count)) == (1, 1)
    finally:
        database.dispose()
    database = Database(url)
    try:
        with database.session_scope() as session:
            assert int(session.get(KnowledgeState, 1).revision) == 0
    finally:
        database.dispose()

    # 空库升级：新库 revision/有效总量从 0 开始
    empty_url = f"sqlite:///{(root / 'empty.sqlite3').as_posix()}"
    run_migrations(empty_url)
    empty_database = Database(empty_url)
    try:
        with empty_database.session_scope() as session:
            state = session.get(KnowledgeState, 1)
            assert state is not None
            assert (int(state.revision), int(state.active_document_count), int(state.active_excel_row_count)) == (0, 0, 0)
            assert session.scalar(select(func.count()).select_from(User)) == 0
    finally:
        empty_database.dispose()

# ---------------------------------------------------------------- P10 生命周期竞态


def _threaded(fn, results, key, barrier=None, delay=0.0):
    def run():
        try:
            if barrier is not None:
                barrier.wait(timeout=10)
            if delay:
                time.sleep(delay)
            results[key] = {"ok": True, "value": fn()}
        except ApiError as exc:
            results[key] = {"ok": False, "code": exc.code, "status": exc.status_code}
        except Exception as exc:  # noqa: BLE001 - 测试需记录任何未预期异常
            results[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _join(threads):
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive(), "竞态线程未在限时内结束"


def test_publish_delete_cancel_races(app, admin_write):
    # 发布 vs 删除
    record, _, _ = _published(app, admin_write, D01, name="发布删除竞态.xlsx")
    candidate = _upload(
        admin_write,
        path=V04,
        document_id=record["document"]["id"],
        expected_active_version_id=record["version"]["id"],
        name="候选.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    base_revision = _revision(app)
    results: dict = {}
    barrier = threading.Barrier(2)

    def do_publish():
        db = _session(app)
        try:
            return publish_version(
                db,
                uuid.UUID(record["document"]["id"]),
                uuid.UUID(candidate["version"]["id"]),
                expected_active_version_id=uuid.UUID(record["version"]["id"]),
                expected_revision=base_revision,
            ).revision
        finally:
            db.close()

    def do_delete():
        db = _session(app)
        try:
            return delete_document(db, uuid.UUID(record["document"]["id"]), expected_revision=base_revision).revision
        finally:
            db.close()

    threads = [
        _threaded(do_publish, results, "publish", barrier),
        _threaded(do_delete, results, "delete", barrier, delay=0.1),
    ]
    _join(threads)
    assert "error" not in results["publish"] and "error" not in results["delete"], results
    document = _document_row(app, record["document"]["id"])
    assert not (document.deleted and document.active_version_id is not None), "不得出现 deleted+active"
    if results["publish"]["ok"]:
        assert results["delete"]["code"] == "DELETE_CONFLICT"
        assert _revision(app) == base_revision + 1
        # 刷新 revision 后删除合法完成
        revision = _revision(app)
        assert _delete_http(admin_write, record["document"]["id"], revision).status_code == 200
    else:
        assert results["delete"]["ok"]
        assert _revision(app) == base_revision + 1
    assert _document_row(app, record["document"]["id"]).deleted is True
    assert _document_row(app, record["document"]["id"]).active_version_id is None

    # 发布 vs 取消
    record2, _, _ = _published(app, admin_write, D02, name="发布取消竞态.xlsx")
    candidate2 = _upload(
        admin_write,
        path=V05,
        document_id=record2["document"]["id"],
        expected_active_version_id=record2["version"]["id"],
        name="取消候选.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    base_revision = _revision(app)
    results = {}
    barrier = threading.Barrier(2)

    def do_publish2():
        db = _session(app)
        try:
            return publish_version(
                db,
                uuid.UUID(record2["document"]["id"]),
                uuid.UUID(candidate2["version"]["id"]),
                expected_active_version_id=uuid.UUID(record2["version"]["id"]),
                expected_revision=base_revision,
            ).revision
        finally:
            db.close()

    def do_cancel2():
        db = _session(app)
        try:
            cancel_version(db, uuid.UUID(record2["document"]["id"]), uuid.UUID(candidate2["version"]["id"]))
            return "cancelled"
        finally:
            db.close()

    threads = [
        _threaded(do_cancel2, results, "cancel", barrier),
        _threaded(do_publish2, results, "publish", barrier, delay=0.1),
    ]
    _join(threads)
    assert "error" not in results["cancel"] and "error" not in results["publish"], results
    version_state = _version_row(app, candidate2["version"]["id"]).state
    assert version_state in {"cancelled", "published"}
    assert not (version_state == "cancelled" and results["publish"]["ok"]), "不得同时 cancelled+published"
    if results["publish"]["ok"]:
        assert results["cancel"]["code"] == "VERSION_NOT_CANCELLABLE"
        assert _revision(app) == base_revision + 1
    else:
        assert _revision(app) == base_revision
        assert version_state == "cancelled"

    # 上传/重试 vs 删除
    record3, _, _ = _published(app, admin_write, D01, name="上传删除竞态.xlsx", )
    base_revision = _revision(app)
    results = {}
    barrier = threading.Barrier(2)

    def do_upload():
        db = _session(app)
        try:
            receipt = stage_upload(
                db,
                app.state.store,
                UploadInput("竞态新版.xlsx", io.BytesIO(V04.read_bytes())),
                document_id=uuid.UUID(record3["document"]["id"]),
                expected_active_version_id=uuid.UUID(record3["version"]["id"]),
            )
            return str(receipt.version.id)
        finally:
            db.close()

    def do_delete3():
        db = _session(app)
        try:
            return delete_document(db, uuid.UUID(record3["document"]["id"]), expected_revision=base_revision).revision
        finally:
            db.close()

    threads = [
        _threaded(do_upload, results, "upload", barrier),
        _threaded(do_delete3, results, "delete", barrier, delay=0.1),
    ]
    _join(threads)
    assert "error" not in results["upload"] and "error" not in results["delete"], results
    document = _document_row(app, record3["document"]["id"])
    assert document.deleted is True and document.active_version_id is None
    db = _session(app)
    try:
        claimable = db.scalars(
            select(ImportJob).where(
                ImportJob.version_id.in_(
                    select(DocumentVersion.id).where(DocumentVersion.document_id == uuid.UUID(record3["document"]["id"]))
                ),
                ImportJob.state.in_(("queued", "running")),
            )
        ).all()
        assert claimable == [], "已删除资料不得留下可领取任务"
        if results["upload"]["ok"]:
            assert results["delete"]["ok"], "上传不影响删除的 revision 前置"
    finally:
        db.close()

    # 重试 vs 删除
    failed = _upload(admin_write, content=_uncached_formula_xlsx(), name="重试删除竞态.xlsx")
    assert _run_worker(app).state == "failed"
    base_revision = _revision(app)
    results = {}
    barrier = threading.Barrier(2)

    def do_retry():
        db = _session(app)
        try:
            job = retry_job(db, uuid.UUID(failed["job"]["id"]))
            return job.state
        finally:
            db.close()

    def do_delete4():
        db = _session(app)
        try:
            return delete_document(db, uuid.UUID(failed["document"]["id"]), expected_revision=base_revision).revision
        finally:
            db.close()

    threads = [
        _threaded(do_retry, results, "retry", barrier),
        _threaded(do_delete4, results, "delete", barrier, delay=0.1),
    ]
    _join(threads)
    assert "error" not in results["retry"] and "error" not in results["delete"], results
    assert results["delete"]["ok"], "删除应成功"
    document = _document_row(app, failed["document"]["id"])
    assert document.deleted is True
    assert _version_row(app, failed["version"]["id"]).state == "deleted"
    assert _job_row(app, failed["job"]["id"]).state in {"cancelled", "failed"}


# ---------------------------------------------------------------- T04-R1：摘要撤销与删除参数


def _marker_paths(value, term: str, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(_marker_paths(item, term, prefix + "." + key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_marker_paths(item, term, prefix + f"[{index}]"))
    elif isinstance(value, str) and term in value:
        found.append(prefix)
    return found


def _delete_state_snapshot(app, document_id):
    db = _session(app)
    try:
        document = db.get(Document, _as_uuid(document_id))
        versions = list(
            db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id)).all()
        )
        jobs = list(
            db.scalars(select(ImportJob).where(ImportJob.version_id.in_([version.id for version in versions]))).all()
        )
        state = db.get(KnowledgeState, 1)
        receipts = int(db.scalar(select(func.count()).select_from(DeletionReceipt)) or 0)
        return {
            "deleted": document.deleted,
            "active": str(document.active_version_id) if document.active_version_id else None,
            "name_key": document.name_key,
            "versions": sorted((str(version.id), version.state) for version in versions),
            "jobs": sorted((str(job.id), job.state, job.retryable) for job in jobs),
            "revision": int(state.revision),
            "counts": (int(state.active_document_count), int(state.active_excel_row_count)),
            "receipts": receipts,
        }
    finally:
        db.close()


def _assert_validation_error_envelope(response, submitted: str | None = None) -> dict:
    """PM04-R2-01：422 错误封装的正确检查范围。

    只对真正承载错误信息的 error 对象检查“不回显提交值”，请求 ID 是响应元数据而独立校验：
    合法的规范 UUID 形态且与 X-Request-ID 一致。旧的整响应子串搜索会把随机 request_id
    里的十六进制字符误判成输入泄漏。
    """
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"error", "request_id"}, body
    error = body["error"]
    assert set(error) == {"code", "message", "retryable", "details"}, error
    assert error["code"] == "VALIDATION_ERROR"
    assert error["retryable"] is False
    details = error["details"]
    assert isinstance(details, dict) and set(details) == {"fields"}, details
    for field in details["fields"]:
        assert set(field) == {"loc", "type"}, field
        assert all(isinstance(part, str) for part in field["loc"]), field
        assert field["loc"][:1] == ["query"], field
    if submitted:
        assert submitted not in json.dumps(error, ensure_ascii=False), "错误信息不得回显输入"
    request_id = body["request_id"]
    assert isinstance(request_id, str) and request_id
    assert str(uuid.UUID(request_id)) == request_id, request_id
    assert response.headers.get("X-Request-ID") == request_id
    return body


def test_cancelled_and_deleted_nested_summaries_are_redacted(app, admin_write):
    """PM04-R1-01：取消/删除后所有嵌套摘要（document/latest/active/列表）不得含处理内容。"""
    marker = "PM04_R1_SIMULATED_PRIVATE_CONTENT"
    workbook = openpyxl.load_workbook(D01)
    workbook.worksheets[0]["A1"] = '="' + marker + '"'
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    record = _upload(admin_write, content=stream.getvalue(), name="嵌套摘要样本.xlsx")
    document_id, version_id = record["document"]["id"], record["version"]["id"]
    assert _run_worker(app).state == "failed"
    before = _detail(admin_write, document_id)
    assert _marker_paths(before, marker), "真实解析报告必须先包含标记，避免空样本假通过"

    assert _cancel_http(admin_write, document_id, version_id).status_code == 204
    cancelled = _detail(admin_write, document_id)
    listing = admin_write.client.get("/api/v1/documents", params={"limit": 100}).json()
    assert _marker_paths(cancelled, marker) == [], "取消后详情任何嵌套位置都不得含处理内容"
    assert _marker_paths(listing, marker) == [], "取消后列表任何嵌套位置都不得含处理内容"
    assert all(item["processing_report"] is None for item in cancelled["versions"])
    assert cancelled["document"]["latest_version"]["processing_report"] is None
    assert _preview_http(admin_write, document_id, version_id).status_code == 410
    stored = _version_row(app, version_id).stored_path
    assert (app.state.store.root / stored).is_file(), "撤销访问不依赖物理删除"

    deleted = _delete_http(admin_write, document_id, cancelled["revision"])
    assert deleted.status_code == 200, deleted.text
    deleted_detail = _detail(admin_write, document_id)
    assert _marker_paths(deleted_detail, marker) == []
    assert deleted_detail["document"]["latest_version"]["processing_report"] is None
    assert deleted_detail["document"]["active_version"] is None
    assert _file_http(admin_write, document_id, version_id).status_code == 410
    assert (app.state.store.root / stored).is_file()

    # 对照：正常待确认资料仍可管理员检查报告
    normal = _upload(admin_write, path=D02, name="正常可检查.xlsx")
    assert _run_worker(app).state == "succeeded"
    normal_detail = _detail(admin_write, normal["document"]["id"])
    assert normal_detail["document"]["latest_version"]["processing_report"] is not None
    assert normal_detail["versions"][0]["processing_report"] is not None
    # 对照：失败但未取消的资料仍可检查失败报告
    failed = _upload(admin_write, content=_uncached_formula_xlsx(), name="失败可检查.xlsx")
    assert _run_worker(app).state == "failed"
    failed_detail = _detail(admin_write, failed["document"]["id"])
    assert failed_detail["document"]["latest_version"]["processing_report"] is not None
    # 对照：superseded 旧版报告保留供管理员核对
    normal_doc = normal["document"]["id"]
    first_publish = _publish_http(
        admin_write,
        normal_doc,
        normal["version"]["id"],
        expected_active_version_id=None,
        expected_revision=normal_detail["revision"],
    )
    assert first_publish.status_code == 200, first_publish.text
    newer = _upload(
        admin_write,
        path=V03,
        document_id=normal_doc,
        expected_active_version_id=normal["version"]["id"],
        name="替换版本.xlsx",
    )
    assert _run_worker(app).state == "succeeded"
    normal_detail = _detail(admin_write, normal_doc)
    second_publish = _publish_http(
        admin_write,
        normal_doc,
        newer["version"]["id"],
        expected_active_version_id=normal["version"]["id"],
        expected_revision=normal_detail["revision"],
    )
    assert second_publish.status_code == 200, second_publish.text
    superseded = next(
        item for item in _detail(admin_write, normal_doc)["versions"] if item["id"] == normal["version"]["id"]
    )
    assert superseded["state"] == "superseded" and superseded["processing_report"] is not None


def test_delete_query_requires_plain_nonnegative_integer(app, admin_write):
    """PM04-R1-02：DELETE query 只接受纯十进制非负整数字符串；非法输入 422 且无任何副作用。"""
    record = _upload(admin_write, path=D02, name="query-integer.xlsx")
    document_id = record["document"]["id"]
    revision = _detail(admin_write, document_id)["revision"]
    assert revision == 0
    baseline = _delete_state_snapshot(app, document_id)
    url = f"/api/v1/documents/{document_id}"
    bad_values = ["1.0", "0.5", "true", "-1", "", "abc", "1e2", " 1", "+1", "0x10", "1,0"]
    for value in bad_values:
        response = admin_write.client.delete(url, params={"expected_revision": value}, headers=admin_write.headers)
        _assert_validation_error_envelope(response, value)
        assert _delete_state_snapshot(app, document_id) == baseline, f"{value!r} 不得产生副作用"
    missing = admin_write.client.delete(url, headers=admin_write.headers)
    _assert_validation_error_envelope(missing)
    assert _delete_state_snapshot(app, document_id) == baseline
    duplicate = admin_write.client.delete(
        url,
        params=[("expected_revision", str(revision)), ("expected_revision", str(revision))],
        headers=admin_write.headers,
    )
    _assert_validation_error_envelope(duplicate)
    assert _delete_state_snapshot(app, document_id) == baseline

    # 确定性对照（PM04-R2-01）：request_id 本身含 "-1"/"abc" 时，旧的整响应子串断言必然误报；
    # 按 error 对象检查回显 + 独立 UUID/header 校验必须仍然通过，且非法请求无任何副作用。
    # patch 只覆盖这一次非法校验请求，退出上下文即恢复，不影响其他资料/会话 ID。
    for fixed_request_id, bad_value in (
        ("2b8decf9-1080-471f-9f01-82cf00c9d137", "-1"),
        ("abcdecf9-1080-471f-9f01-82cf00c9d137", "-1"),
        ("abcdecf9-1080-471f-9f01-82cf00c9d137", "abc"),
    ):
        with patch("mktkb.main.uuid.uuid4", return_value=uuid.UUID(fixed_request_id)):
            response = admin_write.client.delete(
                url, params={"expected_revision": bad_value}, headers=admin_write.headers
            )
        assert bad_value in response.text, "该对照必须让旧整响应断言失败，否则无法证明误报范围"
        body = _assert_validation_error_envelope(response, bad_value)
        assert body["request_id"] == fixed_request_id and response.headers["X-Request-ID"] == fixed_request_id
        assert _delete_state_snapshot(app, document_id) == baseline

    # 合法 0 与当前 revision 删除；重复删除返回原结果
    first = _delete_http(admin_write, document_id, revision)
    assert first.status_code == 200, first.text
    assert first.json() == {"document_id": document_id, "deleted": True, "revision": revision + 1}
    repeat = _delete_http(admin_write, document_id, revision + 1)
    assert repeat.status_code == 200 and repeat.json() == first.json()

    # 新资料：合法正整数删除，过时 revision 仍 409 且无副作用
    second = _upload(admin_write, path=D03, name="query-integer-2.docx")
    second_id = second["document"]["id"]
    current = _detail(admin_write, second_id)["revision"]
    assert current == revision + 1
    second_before = _delete_state_snapshot(app, second_id)
    stale = _delete_http(admin_write, second_id, current - 1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "DELETE_CONFLICT"
    assert _delete_state_snapshot(app, second_id) == second_before
    ok = _delete_http(admin_write, second_id, current)
    assert ok.status_code == 200 and ok.json()["revision"] == current + 1

    # JSON PublishRequest 的严格整数约束不被放宽
    third = _upload(admin_write, path=D01, name="query-integer-3.xlsx")
    assert _run_worker(app).state == "succeeded"
    publish_url = f"/api/v1/documents/{third['document']['id']}/versions/{third['version']['id']}/publish"
    for payload in (
        {"expected_active_version_id": None, "expected_revision": 1.0},
        {"expected_active_version_id": None, "expected_revision": True},
        {"expected_active_version_id": None, "expected_revision": -1},
    ):
        response = admin_write.client.post(publish_url, json=payload, headers=admin_write.headers)
        assert response.status_code == 422, payload
