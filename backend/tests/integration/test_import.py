"""T03 上传、持久化与检查接口检查（L 层，本地 ASGI + 隔离 SQLite）。

覆盖：管理员权限/Origin/CSRF 写保护、字节与格式边界、去重与同名规则、并发约束、
分页列表/详情/预览/受保护原件、迁移升级保留 T02 账号会话、失败无残留。
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from mktkb.auth.models import LoginSession, User
from mktkb.auth.service import bootstrap_accounts
from mktkb.db import MIGRATIONS_DIR, Database, current_revision, run_migrations, table_names
from mktkb.documents.models import Document, DocumentVersion, SourceUnit
from mktkb.documents.service import UploadInput, stage_upload
from mktkb.ingestion.models import ImportJob
from mktkb.ingestion.worker import run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
ORIGIN = "http://testserver"

D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
D03 = FIXTURES / "normal" / "D03_市场部工作指南.docx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
A01 = FIXTURES / "variants" / "A01_损坏的文档.docx"
A02 = FIXTURES / "variants" / "A02_损坏的表格.xlsx"
B05 = FIXTURES / "boundary" / "B05_恰好5000行.xlsx"
B06 = FIXTURES / "boundary" / "B06_超过5000行.xlsx"


# ---------------------------------------------------------------- 辅助


def _zip_members(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        return [(item.filename, archive.read(item.filename)) for item in archive.infolist()]


def _rebuild_zip(members: list[tuple[str, bytes]], *, extra: list[tuple[str, bytes, int]] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(name, data)
        for name, data, compress_type in extra or []:
            archive.writestr(name, data, compress_type=compress_type)
    return buffer.getvalue()


def _padded_xlsx(target_size: int) -> bytes:
    """构造恰好 target_size 字节的合法 xlsx（附加一个不参与解析的存储型成员）。"""
    members = _zip_members(D01)
    probe = len(_rebuild_zip(members, extra=[("xl/media/pad.bin", b"p", zipfile.ZIP_STORED)]))
    pad = 1 + (target_size - probe)
    assert pad > 0
    data = _rebuild_zip(members, extra=[("xl/media/pad.bin", b"p" * pad, zipfile.ZIP_STORED)])
    assert len(data) == target_size, (len(data), target_size)
    assert zipfile.is_zipfile(io.BytesIO(data))
    return data


def _db_counts(app) -> dict[str, int]:
    db = app.state.db.session()
    try:
        return {
            "documents": len(db.scalars(select(Document.id)).all()),
            "versions": len(db.scalars(select(DocumentVersion.id)).all()),
            "jobs": len(db.scalars(select(ImportJob.id)).all()),
            "units": len(db.scalars(select(SourceUnit.id)).all()),
        }
    finally:
        db.close()


def _run_worker(app, **kwargs):
    db = app.state.db.session()
    try:
        return run_one_job(db, app.state.store, **kwargs)
    finally:
        db.close()


def _job_row(app, job_id):
    import uuid

    db = app.state.db.session()
    try:
        return db.get(ImportJob, uuid.UUID(str(job_id)))
    finally:
        db.close()


def _version_row(app, version_id):
    import uuid

    db = app.state.db.session()
    try:
        return db.get(DocumentVersion, uuid.UUID(str(version_id)))
    finally:
        db.close()


def _storage_files(app) -> list[Path]:
    return [p for p in app.state.store.root.rglob("*") if p.is_file()]


def _var_relative_paths() -> list[str]:
    """正式 var 的路径清单（只列名，不打开文件/不读内容，可安全用于污染检查）。"""
    base = ROOT / "var"
    if not base.exists():
        return []
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*"))


# ---------------------------------------------------------------- 权限与写保护


def test_read_and_write_endpoints_require_admin_and_write_context(app, client, employee_client, admin_write):
    files = {"file": ("D01.xlsx", D01.read_bytes(), "application/octet-stream")}

    assert client.get("/api/v1/documents").status_code == 401
    assert client.post("/api/v1/documents", files=files).status_code == 401

    assert employee_client.get("/api/v1/documents").status_code == 403
    employee_csrf = employee_client.get("/api/v1/auth/me").json()["csrf_token"]
    denied = employee_client.post(
        "/api/v1/documents", files=files, headers={"Origin": ORIGIN, "X-CSRF-Token": employee_csrf}
    )
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "ROLE_REQUIRED"

    no_origin = admin_write.client.post("/api/v1/documents", files=files, headers={"X-CSRF-Token": admin_write.csrf})
    assert no_origin.status_code == 403 and no_origin.json()["error"]["code"] == "ORIGIN_REJECTED"

    no_csrf = admin_write.client.post("/api/v1/documents", files=files, headers={"Origin": ORIGIN})
    assert no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "CSRF_INVALID"

    wrong_csrf = admin_write.client.post(
        "/api/v1/documents", files=files, headers={"Origin": ORIGIN, "X-CSRF-Token": "0" * 64}
    )
    assert wrong_csrf.status_code == 403 and wrong_csrf.json()["error"]["code"] == "CSRF_INVALID"

    ok = admin_write.upload(path=D01)
    assert ok.status_code == 202, ok.text
    assert admin_write.client.get("/api/v1/documents").status_code == 200


def test_employee_cannot_read_admin_preview_or_file(app, admin_write, employee_client):
    response = admin_write.upload(path=D01)
    assert response.status_code == 202
    document_id = response.json()["document"]["id"]
    version_id = response.json()["version"]["id"]
    job_id = response.json()["job"]["id"]

    for url in (
        f"/api/v1/documents/{document_id}",
        f"/api/v1/documents/{document_id}/versions/{version_id}/preview",
        f"/api/v1/documents/{document_id}/versions/{version_id}/file",
        f"/api/v1/jobs/{job_id}",
    ):
        assert employee_client.get(url).status_code == 403, url
    retry = employee_client.post(f"/api/v1/jobs/{job_id}/retry", headers={"Origin": ORIGIN, "X-CSRF-Token": "x"})
    assert retry.status_code == 403


# ---------------------------------------------------------------- 上传成功与拒绝


def test_upload_creates_pending_document_version_and_job(app, admin_write):
    import hashlib
    import uuid

    response = admin_write.upload(path=D01)
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["version"]["state"] == "queued"
    assert payload["version"]["number"] == 1
    assert payload["job"]["state"] == "queued"
    assert payload["job"]["total_pages"] == 0 and payload["job"]["completed_pages"] == 0
    assert payload["document"]["active_version"] is None
    assert payload["document"]["latest_version"]["id"] == payload["version"]["id"]
    assert payload["version"]["sha256"] == hashlib.sha256(D01.read_bytes()).hexdigest()

    db = app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(payload["document"]["id"]))
        version = db.get(DocumentVersion, uuid.UUID(payload["version"]["id"]))
        assert document.active_version_id is None
        assert document.latest_version_number == 1
        assert version.stored_path and (app.state.store.root / version.stored_path).is_file()
        assert version.size_bytes == D01.stat().st_size
        assert db.scalars(select(SourceUnit)).all() == []
        job = db.get(ImportJob, uuid.UUID(payload["job"]["id"]))
        assert job.retryable is True and job.attempts == 0
    finally:
        db.close()


def test_upload_rejects_unsupported_spoofed_and_corrupt(app, admin_write):
    # T07：PDF/图片已成为受支持格式（由新增 test_ocr_jobs/ test_pdf_image 覆盖成功路径）；
    # 本函数继续验证真正的未知格式、伪装/损坏容器与加密 PDF 的拒绝。
    unsupported = admin_write.upload(content=b"plain text", name="说明.txt")
    assert unsupported.status_code == 415, unsupported.text
    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    encrypted = admin_write.upload(path=FIXTURES / "variants" / "A03_加密的规范.pdf", name="A03.pdf")
    assert encrypted.status_code == 415
    assert encrypted.json()["error"]["code"] == "FILE_ENCRYPTED"

    # 真实 PDF 字节伪装成 .xlsx：扩展名受支持但容器不是 OOXML
    spoofed_pdf = admin_write.upload(path=FIXTURES / "normal" / "D05_物料领用规范.pdf", name="伪装.xlsx")
    assert spoofed_pdf.status_code == 415
    assert spoofed_pdf.json()["error"]["code"] == "INVALID_FILE_TYPE"

    # docx 字节命名为 .xlsx：容器类型与扩展名不一致
    spoofed_docx = admin_write.upload(path=D03, name="伪装.xlsx")
    assert spoofed_docx.status_code == 415
    assert spoofed_docx.json()["error"]["code"] == "INVALID_FILE_TYPE"

    for path, name in ((A01, "A01.docx"), (A02, "A02.xlsx")):
        corrupt = admin_write.upload(path=path, name=name)
        assert corrupt.status_code == 422, (name, corrupt.text)
        assert corrupt.json()["error"]["code"] in {"INVALID_FILE", "FILE_CORRUPT"}
        assert corrupt.json()["request_id"]

    assert _db_counts(app) == {"documents": 0, "versions": 0, "jobs": 0, "units": 0}
    assert _storage_files(app) == []


def test_upload_rejects_empty_file(app, admin_write):
    response = admin_write.upload(content=b"", name="empty.xlsx")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILE"
    assert _db_counts(app)["jobs"] == 0


def test_upload_size_boundary_exact_limit_and_one_byte_over(app, admin_write):
    limit = 20 * 1024 * 1024
    exact = _padded_xlsx(limit)
    response = admin_write.upload(content=exact, name="B01_恰好20MB.xlsx", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert response.status_code == 202, response.text

    response = admin_write.upload(content=exact + b"\x00", name="B02_超过20MB一字节.xlsx")
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert _db_counts(app)["documents"] == 1, "超限请求不得残留文档/任务"
    stored = _storage_files(app)
    assert len(stored) == 1 and stored[0].stat().st_size == limit, "只保留恰好 20MB 的合格原件"
    assert all(path.stat().st_size <= limit for path in stored), "超限字节不得落盘为原件"


def test_upload_rejects_zip_resource_budgets(app, admin_write):
    # 压缩比/解压总量预算：30MB 全零成员压缩后极小，超出默认压缩比预算
    members = _zip_members(D01)
    bomb = _rebuild_zip(members, extra=[("xl/media/bomb.bin", b"\x00" * (30 * 1024 * 1024), zipfile.ZIP_DEFLATED)])
    response = admin_write.upload(content=bomb, name="bomb.xlsx")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "OOXML_RESOURCE_LIMIT"

    many = _rebuild_zip(members, extra=[(f"xl/media/m{i}.bin", b"x", zipfile.ZIP_STORED) for i in range(2100)])
    response = admin_write.upload(content=many, name="many.xlsx")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OOXML_RESOURCE_LIMIT"
    assert _db_counts(app) == {"documents": 0, "versions": 0, "jobs": 0, "units": 0}


# ---------------------------------------------------------------- 同名/替换/去重


def test_same_name_requires_explicit_action_and_allows_independent_document(app, admin_write):
    first = admin_write.upload(path=D01, name="物品位置表.xlsx")
    assert first.status_code == 202

    conflict = admin_write.upload(path=D02, name="物品位置表.xlsx")
    assert conflict.status_code == 409
    body = conflict.json()["error"]
    assert body["code"] == "SAME_NAME_REQUIRES_ACTION"
    assert body["details"]["candidates"][0]["name"] == "物品位置表.xlsx"

    independent = admin_write.upload(path=D02, name="物品位置表.xlsx", allow_same_name=True)
    assert independent.status_code == 202, independent.text
    assert independent.json()["document"]["id"] != first.json()["document"]["id"]
    assert _db_counts(app)["documents"] == 2


def test_replace_version_appends_without_touching_existing_bytes_or_active(app, admin_write):
    first = admin_write.upload(path=D01, name="物品位置表.xlsx")
    document_id = first.json()["document"]["id"]
    old_version_id = first.json()["version"]["id"]
    old_bytes = D01.read_bytes()

    second = admin_write.upload(path=V03, name="物品位置表.xlsx", document_id=document_id)
    assert second.status_code == 202, second.text
    assert second.json()["version"]["number"] == 2
    assert second.json()["document"]["active_version"] is None
    assert second.json()["document"]["latest_version"]["id"] == second.json()["version"]["id"]

    db = app.state.db.session()
    try:
        import uuid

        old = db.get(DocumentVersion, uuid.UUID(old_version_id))
        assert (app.state.store.root / old.stored_path).read_bytes() == old_bytes
        assert old.state == "queued"
        assert db.get(Document, uuid.UUID(document_id)).active_version_id is None
    finally:
        db.close()

    conflict = admin_write.upload(path=D02, name="x.xlsx", document_id=document_id, expected_active_version_id="00000000-0000-0000-0000-000000000001")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ACTIVE_VERSION_CONFLICT"


def test_duplicate_content_and_unchanged_replacement_conflicts(app, admin_write):
    first = admin_write.upload(path=D01, name="甲.xlsx")
    assert first.status_code == 202
    duplicate = admin_write.upload(path=D01, name="乙.xlsx")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_CONTENT"
    assert _db_counts(app)["versions"] == 1

    # 模拟 T04 已发布的有效版本（T03 不提供发布接口，只在隔离 fixture 中构造）
    import uuid
    from datetime import datetime, timezone

    document_id = first.json()["document"]["id"]
    version_id = first.json()["version"]["id"]
    db = app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(document_id))
        version = db.get(DocumentVersion, uuid.UUID(version_id))
        version.state = "published"
        version.published_at = datetime.now(timezone.utc)
        document.active_version_id = version.id
        document.last_published_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    unchanged = admin_write.upload(
        path=D01, name="甲.xlsx", document_id=document_id, expected_active_version_id=version_id
    )
    assert unchanged.status_code == 409
    assert unchanged.json()["error"]["code"] == "CONTENT_UNCHANGED"


def test_concurrent_same_fingerprint_creates_one_version(app, admin_write):
    content = D01.read_bytes()
    results: list = []

    def attempt(name: str) -> None:
        results.append(admin_write.upload(content=content, name=name))

    threads = [threading.Thread(target=attempt, args=(f"并发{index}.xlsx",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    statuses = sorted(response.status_code for response in results)
    assert statuses == [202, 409], [response.text for response in results]
    conflict = next(response for response in results if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "DUPLICATE_CONTENT"
    assert _db_counts(app)["versions"] == 1
    assert _db_counts(app)["documents"] == 1
    assert _db_counts(app)["jobs"] == 1


def test_concurrent_same_name_creates_one_document(app, admin_write):
    payloads = [(D01.read_bytes(), "同名.xlsx"), (D02.read_bytes(), "同名.xlsx")]
    results: list = []

    def attempt(index: int) -> None:
        content, name = payloads[index]
        results.append(admin_write.upload(content=content, name=name))

    threads = [threading.Thread(target=attempt, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    statuses = sorted(response.status_code for response in results)
    assert statuses == [202, 409], [response.text for response in results]
    conflict = next(response for response in results if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "SAME_NAME_REQUIRES_ACTION"
    db = app.state.db.session()
    try:
        names = db.scalars(select(Document.name)).all()
        assert names.count("同名.xlsx") == 1
    finally:
        db.close()


# ---------------------------------------------------------------- 列表/详情/预览/原件


def test_documents_list_filters_pagination_and_deleted_exclusion(app, admin_write):
    ids = []
    for path, name in ((D01, "位置表.xlsx"), (D02, "店家表.xlsx"), (D03, "工作指南.docx")):
        response = admin_write.upload(path=path, name=name)
        assert response.status_code == 202
        ids.append(response.json()["document"]["id"])

    client = admin_write.client
    listing = client.get("/api/v1/documents").json()
    assert listing["total"] == 3 and len(listing["items"]) == 3
    assert listing["offset"] == 0 and listing["limit"] == 20
    first_item = listing["items"][0]
    assert first_item["active_version"] is None and first_item["latest_version"]["state"] == "queued"

    assert client.get("/api/v1/documents", params={"q": "位置"}).json()["total"] == 1
    assert client.get("/api/v1/documents", params={"file_type": "xlsx"}).json()["total"] == 2
    assert client.get("/api/v1/documents", params={"state": "queued"}).json()["total"] == 3
    assert client.get("/api/v1/documents", params={"state": "published"}).json()["total"] == 0

    page = client.get("/api/v1/documents", params={"limit": 2, "offset": 0}).json()
    assert len(page["items"]) == 2 and page["total"] == 3
    page2 = client.get("/api/v1/documents", params={"limit": 2, "offset": 2}).json()
    assert len(page2["items"]) == 1
    assert client.get("/api/v1/documents", params={"limit": 101}).status_code == 422

    import uuid

    db = app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(ids[0]))
        document.deleted = True
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/documents").json()["total"] == 2


def test_document_detail_returns_versions_without_source_text(app, admin_write):
    first = admin_write.upload(path=D01, name="物品位置表.xlsx")
    document_id = first.json()["document"]["id"]
    second = admin_write.upload(path=V03, name="物品位置表.xlsx", document_id=document_id)
    assert second.status_code == 202

    response = admin_write.client.get(f"/api/v1/documents/{document_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["document"]["id"] == document_id
    assert [version["number"] for version in body["versions"]] == [1, 2]
    assert all("text" not in version for version in body["versions"])
    assert admin_write.client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000").status_code == 404


def test_preview_pagination_sheet_filter_and_report(app, admin_write):
    response = admin_write.upload(path=D01, name="物品位置表.xlsx")
    document_id = response.json()["document"]["id"]
    version_id = response.json()["version"]["id"]
    result = _run_worker(app)
    assert result.state == "succeeded", result

    preview = admin_write.client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/preview", params={"offset": 0, "limit": 5}
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total"] == 9 and len(body["items"]) == 5
    first_locator = body["items"][0]["locator"]
    assert {key: first_locator[key] for key in ("sheet", "row", "header_row")} == {
        "sheet": "物品位置",
        "row": 8,
        "header_row": 7,
    }
    assert first_locator["cell_types"]["标识"] == "s", "预览应持久暴露单元格原类型元数据"
    assert body["items"][0]["fields"]["标识"] == "P01"
    assert body["report"]["sheets"][2]["hidden"] is True

    page2 = admin_write.client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/preview", params={"offset": 5, "limit": 20}
    )
    assert len(page2.json()["items"]) == 4

    filtered = admin_write.client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/preview", params={"sheet": "物品位置"}
    )
    assert filtered.json()["total"] == 8

    other = admin_write.client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/preview", params={"sheet": "不存在"}
    )
    assert other.json()["total"] == 0 and other.json()["report"]["sheets"]


def test_protected_file_returns_original_bytes_only_to_admin(app, admin_write, employee_client, client):
    import hashlib

    response = admin_write.upload(path=D01, name="物品位置表.xlsx")
    document_id = response.json()["document"]["id"]
    version_id = response.json()["version"]["id"]

    file_response = admin_write.client.get(f"/api/v1/documents/{document_id}/versions/{version_id}/file")
    assert file_response.status_code == 200
    assert hashlib.sha256(file_response.content).hexdigest() == hashlib.sha256(D01.read_bytes()).hexdigest()
    assert "attachment" not in file_response.headers.get("content-disposition", "")
    assert file_response.headers.get("x-content-type-options") == "nosniff"

    assert employee_client.get(f"/api/v1/documents/{document_id}/versions/{version_id}/file").status_code == 403
    assert client.get(f"/api/v1/documents/{document_id}/versions/{version_id}/file").status_code == 401
    mismatch = admin_write.client.get(
        f"/api/v1/documents/{document_id}/versions/00000000-0000-0000-0000-000000000002/file"
    )
    assert mismatch.status_code == 404
    assert mismatch.json()["error"]["code"] == "VERSION_NOT_FOUND"


# ---------------------------------------------------------------- 迁移与隔离


def test_t02_database_upgrades_to_t03_preserving_accounts_and_sessions(tmp_path: Path):
    root = tmp_path / "upgrade"
    root.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{(root / 'mktkb.sqlite3').as_posix()}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0001_auth")

    database = Database(url)
    try:
        assert table_names(database.engine) >= {"users", "login_sessions"}
        with database.session_scope() as session:
            created = bootstrap_accounts(
                session,
                admin_username="admin",
                admin_password="AdminPass-1",
                admin_display_name="演示管理员",
                employee_username="employee",
                employee_password="EmployeePass-1",
                employee_display_name="演示员工",
                rounds=4,
            )
        assert sorted(created) == ["admin", "employee"]
        import uuid
        from datetime import datetime, timedelta, timezone

        token = "t02-session-token-preserved"
        import hashlib

        with database.session_scope() as session:
            admin_id = session.scalar(select(User.id).where(User.username == "admin"))
            session.add(
                LoginSession(
                    user_id=admin_id,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )

        run_migrations(url)
        tables = table_names(database.engine)
        assert {"documents", "document_versions", "import_jobs", "source_units"} <= tables
        assert current_revision(url) is not None
        with database.session_scope() as session:
            usernames = sorted(session.scalars(select(User.username)).all())
            assert usernames == ["admin", "employee"]
            session_rows = session.scalars(select(LoginSession)).all()
            assert len(session_rows) == 1
            version_rows = session.execute(
                __import__("sqlalchemy").text("SELECT count(*) FROM alembic_version")
            ).scalar()
        assert version_rows == 1

        run_migrations(url)  # 重复升级幂等
        with database.session_scope() as session:
            assert sorted(session.scalars(select(User.username)).all()) == ["admin", "employee"]
    finally:
        database.dispose()


def test_uploaded_data_lives_under_isolated_storage(app, settings, admin_write):
    # 正式 var 目录可能已存在（生产数据），本测试的安全意图是“隔离测试上传不得写入它”，
    # 因此比较上传前后的路径清单，而不是要求仓库根下没有 var。仅列名，不打开正式业务文件。
    var_before = _var_relative_paths()
    response = admin_write.upload(path=D01, name="物品位置表.xlsx")
    assert response.status_code == 202
    storage = app.state.store.root
    assert storage.is_relative_to(settings.data_dir)
    files = _storage_files(app)
    assert len(files) == 1
    assert files[0].is_relative_to(storage)
    assert _var_relative_paths() == var_before, "隔离测试上传不得在项目正式 var 下产生任何文件"


def test_client_filename_is_display_only_and_traversal_is_neutralised(app, admin_write):
    import uuid

    response = admin_write.upload(path=D01, name="../../evil.xlsx")
    assert response.status_code == 202, response.text
    assert response.json()["document"]["name"] == "evil.xlsx", "用户文件名只保留末段用于显示"

    db = app.state.db.session()
    try:
        version = db.get(DocumentVersion, uuid.UUID(response.json()["version"]["id"]))
        assert version.stored_path.startswith("originals/")
        assert "evil" not in version.stored_path, "内部存储路径不使用用户文件名"
        assert (app.state.store.root / version.stored_path).is_file()
    finally:
        db.close()
    assert not (app.state.settings.data_dir / "evil.xlsx").exists(), "不得在存储根外落盘"


def test_orphan_files_are_detectable_without_deleting(app, admin_write):
    from mktkb.documents.service import find_orphan_files, recorded_storage_paths

    response = admin_write.upload(path=D01, name="物品位置表.xlsx")
    assert response.status_code == 202
    stray = app.state.store.staging_dir / "crash-leftover.part"
    stray.write_bytes(b"orphan-bytes")

    db = app.state.db.session()
    try:
        recorded = recorded_storage_paths(db)
    finally:
        db.close()
    orphans = find_orphan_files(app.state.store, recorded)
    assert stray in orphans, "崩溃遗留文件应可被受控清理流程识别"
    assert recorded, "数据库引用的原件不应被列为孤立文件"
    assert all(path.is_relative_to(app.state.store.root) for path in orphans)
    assert stray.exists(), "识别流程不删除文件"


# ---------------------------------------------------------------- T03-R1：边界与契约回归


def _xlsx_bytes(rows_by_sheet: list[tuple[str, list[list]]]) -> bytes:
    workbook = openpyxl.Workbook()
    first = True
    for title, rows in rows_by_sheet:
        worksheet = workbook.active if first else workbook.create_sheet()
        first = False
        worksheet.title = title
        for row in rows:
            worksheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_unknown_structure_sheet_fails_whole_import(app, admin_write):
    """PM03-01：正常表 + 非空未知表不得整体成功；报告保留两张表状态。"""
    content = _xlsx_bytes(
        [
            ("正常表", [["编号", "位置"], ["P900", "A区"]]),
            ("未识别记录", [["唯一字段"], ["不能静默丢弃的内容"]]),
        ]
    )
    response = admin_write.upload(content=content, name="mixed.xlsx")
    assert response.status_code == 202, response.text
    result = _run_worker(app)
    assert result.state == "failed"
    job = _job_row(app, response.json()["job"]["id"])
    version = _version_row(app, response.json()["version"]["id"])
    assert job.state == "failed" and version.state == "failed"
    report = version.processing_report
    assert report["quality"]["complete"] is False
    assert [sheet["name"] for sheet in report["sheets"]] == ["正常表", "未识别记录"]
    assert report["units"] == 1, "已识别表仍可预览，但整体不完整"


def test_commit_failure_cleans_store_root_and_spares_cwd_sentinel(app):
    """PM03-02：原件移动后 commit 失败，按 Store 根清理；cwd 同名哨兵不得被误删。"""
    sentinel_paths: list[Path] = []
    original_commit = app.state.store.commit

    def commit_with_sentinel(staging, version_id, kind):
        target = original_commit(staging, version_id, kind)
        relative = target.relative_to(app.state.store.root).as_posix() if isinstance(target, Path) else str(target)
        sentinel = Path.cwd() / relative
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_bytes(b"cwd-sentinel-must-survive")
        sentinel_paths.append(sentinel)
        return target

    db = app.state.db.session()
    try:
        with patch.object(app.state.store, "commit", commit_with_sentinel), patch.object(
            db, "commit", side_effect=RuntimeError("R1 simulated commit failure")
        ):
            with pytest.raises(RuntimeError):
                stage_upload(db, app.state.store, UploadInput("commit.xlsx", io.BytesIO(D01.read_bytes())))
        originals = [path for path in app.state.store.originals_dir.rglob("*") if path.is_file()]
        staging = [path for path in app.state.store.staging_dir.rglob("*") if path.is_file()]
        assert originals == [] and staging == [], "失败后不得残留原件或暂存文件"
        assert _db_counts(app) == {"documents": 0, "versions": 0, "jobs": 0, "units": 0}
        assert sentinel_paths and all(path.exists() for path in sentinel_paths), "cwd 同名文件不受清理影响"
    finally:
        db.close()
        for path in sentinel_paths:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
                path.parent.parent.rmdir()
            except OSError:
                pass


def test_locked_commit_retry_keeps_staging_and_creates_single_version(app):
    """PM03-02：有界 OperationalError 重试不得消费已移动 staging 后伪成功或崩溃。"""
    db = app.state.db.session()
    real_commit = db.commit
    calls = {"count": 0}

    def flaky_commit():
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError("COMMIT", {}, Exception("database is locked"))
        return real_commit()

    try:
        with patch.object(db, "commit", side_effect=flaky_commit):
            receipt = stage_upload(db, app.state.store, UploadInput("locked.xlsx", io.BytesIO(D01.read_bytes())))
        assert calls["count"] >= 2
        assert _db_counts(app) == {"documents": 1, "versions": 1, "jobs": 1, "units": 0}
        originals = [path for path in app.state.store.originals_dir.rglob("*") if path.is_file()]
        staging = [path for path in app.state.store.staging_dir.rglob("*") if path.is_file()]
        assert len(originals) == 1 and staging == []
        assert originals[0].read_bytes() == D01.read_bytes()
        assert (app.state.store.root / receipt.version.stored_path).is_file()
    finally:
        db.close()


def test_cell_metadata_persisted_and_previewable(app, admin_write):
    """PM03-04：日期文本与日期单元格在预览定位元数据中可区分，fields 业务值兼容。"""
    content = _xlsx_bytes(
        [("日期类型", [["日期文本", "日期单元格"], ["2026-10-28T00:00:00", datetime(2026, 10, 28)]])]
    )
    response = admin_write.upload(content=content, name="cell-types.xlsx")
    assert response.status_code == 202
    assert _run_worker(app).state == "succeeded"

    document_id = response.json()["document"]["id"]
    version_id = response.json()["version"]["id"]
    preview_body = admin_write.client.get(
        f"/api/v1/documents/{document_id}/versions/{version_id}/preview", params={"limit": 10}
    ).json()
    locator = preview_body["items"][0]["locator"]
    cells = {cell["header"]: cell for cell in locator["cells"]}
    assert cells["日期文本"]["raw_type"] == "s"
    assert cells["日期单元格"]["raw_type"] in {"d", "n"}
    assert cells["日期文本"]["raw_type"] != cells["日期单元格"]["raw_type"]
    assert cells["日期单元格"]["number_format"]
    assert locator["cell_types"]["日期文本"] == "s"
    fields = preview_body["items"][0]["fields"]
    assert fields["日期文本"] == fields["日期单元格"] == "2026-10-28T00:00:00", "业务值语义保持兼容"


def test_word_heading_locator_contract_persisted(app, admin_write):
    """PM03-05：Word 预览定位使用契约 heading 键，顺序与段落定位保持。"""
    response = admin_write.upload(path=D03, name="工作指南.docx")
    assert response.status_code == 202
    assert _run_worker(app).state == "succeeded"
    preview_body = admin_write.client.get(
        f"/api/v1/documents/{response.json()['document']['id']}/versions/{response.json()['version']['id']}/preview",
        params={"limit": 20},
    ).json()
    target = next(item for item in preview_body["items"] if item["text"].startswith("门店领取宣传物料前"))
    assert target["locator"]["heading"] == "2.3 物料领用与登记"
    assert target["locator"]["paragraph"] == 4
    assert "headings" not in target["locator"]


# ---------------------------------------------------------------- T03-R2：可见无缓存公式表完整性


def _multi_sheet_xlsx_bytes(sheets: list[tuple]) -> bytes:
    workbook = openpyxl.Workbook()
    first = True
    for item in sheets:
        title, rows = item[0], item[1]
        state = item[2] if len(item) > 2 else "visible"
        worksheet = workbook.active if first else workbook.create_sheet()
        first = False
        worksheet.title = title
        worksheet.sheet_state = state
        for row in rows:
            worksheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _cached_formula_xlsx_bytes() -> bytes:
    source = _multi_sheet_xlsx_bytes([("缓存公式", [["标识", "结果"], ["R1", "=1+2"]])])
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as src, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                assert "<f>1+2</f>" in text
                data = text.replace("<f>1+2</f>", "<f>1+2</f><v>150</v>").encode("utf-8")
            dst.writestr(item, data)
    return buffer.getvalue()


def _formula_sheet_entry(report: dict, name: str) -> dict:
    return next(sheet for sheet in report["sheets"] if sheet["name"] == name)


def test_uncached_formula_sheet_fails_import_and_keeps_full_report(app, admin_write):
    """PM03-R2-01：持久化报告不得把无缓存公式表记为空表，整单必须失败。"""
    content = _multi_sheet_xlsx_bytes(
        [
            ("正常表", [["编号", "位置"], ["P900", "A区"]]),
            ("无缓存公式", [["=1+1", "=2+2"]]),
        ]
    )
    response = admin_write.upload(content=content, name="uncached-sheet.xlsx")
    assert response.status_code == 202, response.text
    result = _run_worker(app)
    assert result.state == "failed"
    assert result.error_code == "PARSE_INCOMPLETE"

    job = _job_row(app, response.json()["job"]["id"])
    version = _version_row(app, response.json()["version"]["id"])
    assert job.state == "failed" and version.state == "failed"
    report = version.processing_report
    assert report["formula_cells"] == 2
    assert report["quality"]["complete"] is False
    assert [sheet["name"] for sheet in report["sheets"]] == ["正常表", "无缓存公式"]
    formula_sheet = _formula_sheet_entry(report, "无缓存公式")
    assert formula_sheet.get("empty") is not True, "原始公式占用存在，不能伪报空表"
    assert formula_sheet["ingested"] is False and "公式" in formula_sheet["note"]
    cells = {
        (cell["row"], cell["column"], cell["formula"])
        for cell in formula_sheet.get("missing_formula_cells") or []
    }
    assert cells == {(1, "A", "=1+1"), (1, "B", "=2+2")}
    issue = next(issue for issue in report["quality"]["issues"] if issue.get("issue") == "formula_cache_missing")
    assert issue["sheet"] == "无缓存公式" and len(issue["cells"]) == 2


def test_only_uncached_formula_file_fails_without_empty_claim(app, admin_write):
    """PM03-R2-01：仅公式文件失败，不得标 succeeded/伪报真正空文件。"""
    content = _multi_sheet_xlsx_bytes([("仅公式", [["=1+1", "=2+2"]])])
    response = admin_write.upload(content=content, name="only-formula.xlsx")
    assert response.status_code == 202
    assert _run_worker(app).state == "failed"
    version = _version_row(app, response.json()["version"]["id"])
    assert version.state == "failed"
    report = version.processing_report
    entry = _formula_sheet_entry(report, "仅公式")
    assert entry.get("empty") is not True and "公式" in entry["note"]
    assert report["quality"]["complete"] is False
    assert report["units"] == 0


def test_uncached_formula_new_version_does_not_switch_active(app, admin_write):
    """PM03-R2-01：新版公式完整性失败时，既有有效版本不得被切换。"""
    import uuid
    from datetime import datetime

    first = admin_write.upload(path=D01, name="物品位置表.xlsx")
    assert first.status_code == 202
    assert _run_worker(app).state == "succeeded"

    db = app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(first.json()["document"]["id"]))
        old_version = db.get(DocumentVersion, uuid.UUID(first.json()["version"]["id"]))
        old_version.state = "published"
        old_version.published_at = datetime.now().astimezone()
        document.active_version_id = old_version.id
        document.last_published_at = old_version.published_at
        old_job = db.get(ImportJob, uuid.UUID(first.json()["job"]["id"]))
        old_job.state = "succeeded"
        old_job.stage = "finished"
        old_job.retryable = False
        db.commit()
        active_before = str(document.active_version_id)
    finally:
        db.close()

    content = _multi_sheet_xlsx_bytes(
        [
            ("正常表", [["编号", "位置"], ["P900", "A区"]]),
            ("无缓存公式", [["=1+1", "=2+2"]]),
        ]
    )
    second = admin_write.client.post(
        f"/api/v1/documents/{first.json()['document']['id']}/versions",
        files={"file": ("uncached-v2.xlsx", content, "application/octet-stream")},
        headers=admin_write.headers,
    )
    assert second.status_code == 202, second.text
    assert _run_worker(app).state == "failed"

    db = app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(first.json()["document"]["id"]))
        new_version = db.get(DocumentVersion, uuid.UUID(second.json()["version"]["id"]))
        assert str(document.active_version_id) == active_before, "失败新版不得切换有效版本"
        assert new_version.state == "failed"
    finally:
        db.close()


def test_normal_empty_hidden_control_still_succeeds(app, admin_write):
    """PM03-R2-01 对照：正常表 + 真正空表 + 隐藏表仍成功，空表/隐藏表如实报告。"""
    content = _multi_sheet_xlsx_bytes(
        [
            ("记录", [["编号", "位置"], ["P900", "A区"]]),
            ("空表", []),
            ("隐藏草稿", [["编号", "位置"], ["P999", "Z区"]], "hidden"),
        ]
    )
    response = admin_write.upload(content=content, name="control.xlsx")
    assert response.status_code == 202
    assert _run_worker(app).state == "succeeded"
    version = _version_row(app, response.json()["version"]["id"])
    report = version.processing_report
    assert report["quality"]["complete"] is True and report["units"] == 1
    assert _formula_sheet_entry(report, "空表")["empty"] is True
    hidden = _formula_sheet_entry(report, "隐藏草稿")
    assert hidden["hidden"] is True and hidden["ingested"] is False


def test_cached_formula_row_still_succeeds(app, admin_write):
    """PM03-R2-01 对照：有已保存缓存的公式行不回退，使用缓存值且不重算。"""
    response = admin_write.upload(content=_cached_formula_xlsx_bytes(), name="cached-formula.xlsx")
    assert response.status_code == 202
    assert _run_worker(app).state == "succeeded"
    version = _version_row(app, response.json()["version"]["id"])
    assert version.state == "review_required"
    assert version.processing_report["quality"]["complete"] is True
    preview_body = admin_write.client.get(
        f"/api/v1/documents/{response.json()['document']['id']}/versions/{response.json()['version']['id']}/preview",
        params={"limit": 10},
    ).json()
    item = preview_body["items"][0]
    assert item["fields"]["结果"] in {150, 150.0}, "只使用已保存缓存值，不执行/重算公式"
    assert item["locator"]["cells"][1]["cache_status"] == "cached"


# ---------------------------------------------------------------- T03-R3：整表公式完整性（表头前/表头内）


R3_POSITION_SAMPLES = {
    "before_header": [("可见记录", [["=1+1", "=2+2"], ["编号", "位置"], ["P900", "A区"]])],
    "in_header": [("可见记录", [["编号", "位置", "=1+1"], ["P900", "A区", "不能推断字段意义"]])],
    "data_row": [("数据行公式", [["标识", "结果"], ["R1", "=A2+1"]])],
    "formula_only": [("仅公式", [["=1+1", "=2+2"]])],
}


@pytest.mark.parametrize("position", ["before_header", "in_header", "data_row", "formula_only"])
def test_uncached_formula_any_position_fails_import(app, admin_write, position):
    """PM03-R3-01：表头前/表头内/数据行/仅公式表四种位置的缺缓存公式一致失败并保留定位。"""
    sheets = R3_POSITION_SAMPLES[position]
    sheet_name = sheets[0][0]
    response = admin_write.upload(content=_multi_sheet_xlsx_bytes(sheets), name=f"r3-{position}.xlsx")
    assert response.status_code == 202, response.text
    result = _run_worker(app)
    assert result.state == "failed" and result.error_code == "PARSE_INCOMPLETE"

    job = _job_row(app, response.json()["job"]["id"])
    version = _version_row(app, response.json()["version"]["id"])
    assert job.state == "failed" and version.state == "failed"
    report = version.processing_report
    assert report["quality"]["complete"] is False
    assert [sheet["name"] for sheet in report["sheets"]] == [sheet_name], "全部工作表摘要保留"
    entry = _formula_sheet_entry(report, sheet_name)
    cells = {
        (cell["row"], cell["column"], cell["formula"]) for cell in entry.get("missing_formula_cells") or []
    }
    issue = next(item for item in report["quality"]["issues"] if item.get("issue") == "formula_cache_missing")
    assert issue["sheet"] == sheet_name and len(issue["cells"]) == len(cells)

    preview_body = admin_write.client.get(
        f"/api/v1/documents/{response.json()['document']['id']}/versions/{response.json()['version']['id']}/preview",
        params={"limit": 10},
    ).json()
    if position == "before_header":
        assert cells == {(1, "A", "=1+1"), (1, "B", "=2+2")}
        assert entry["header_row"] == 2 and entry["data_rows"] == 1 and entry["ingested"] is True
        assert [item["fields"] for item in preview_body["items"]] == [{"编号": "P900", "位置": "A区"}]
    elif position == "in_header":
        assert cells == {(1, "C", "=1+1")}
        assert entry["ingested"] is False and preview_body["total"] == 0
        assert "列3" not in json.dumps(preview_body, ensure_ascii=False)
        assert "列3" not in json.dumps(report, ensure_ascii=False), "不得用自动列名掩盖未知表头"
    elif position == "data_row":
        assert cells == {(2, "B", "=A2+1")}
        assert [item["fields"] for item in preview_body["items"]] == [{"标识": "R1", "结果": None}]
    else:
        assert len(cells) == 2 and report["units"] == 0
        assert entry.get("empty") is not True, "原始公式占用存在，不能伪报空表"


def test_uncached_formula_before_header_new_version_keeps_active_and_bytes(app, admin_write):
    """PM03-R3-01：表头前公式的新版本失败时，既有有效版的状态/active/原件字节保持不变。"""
    import uuid

    first = admin_write.upload(path=D01, name="物品位置表.xlsx")
    assert first.status_code == 202
    assert _run_worker(app).state == "succeeded"

    db = app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(first.json()["document"]["id"]))
        old_version = db.get(DocumentVersion, uuid.UUID(first.json()["version"]["id"]))
        old_version.state = "published"
        old_version.published_at = datetime.now().astimezone()
        document.active_version_id = old_version.id
        document.last_published_at = old_version.published_at
        old_job = db.get(ImportJob, uuid.UUID(first.json()["job"]["id"]))
        old_job.state = "succeeded"
        old_job.stage = "finished"
        old_job.retryable = False
        db.commit()
        active_before = str(document.active_version_id)
        old_path = app.state.store.path_for(old_version.stored_path)
        old_sha_before = hashlib.sha256(old_path.read_bytes()).hexdigest()
    finally:
        db.close()

    content = _multi_sheet_xlsx_bytes(
        [("可见记录", [["=1+1", "=2+2"], ["编号", "位置"], ["P900", "A区"]])]
    )
    second = admin_write.client.post(
        f"/api/v1/documents/{first.json()['document']['id']}/versions",
        files={"file": ("prefix-formula-v2.xlsx", content, "application/octet-stream")},
        headers=admin_write.headers,
    )
    assert second.status_code == 202, second.text
    assert _run_worker(app).state == "failed"

    db = app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(first.json()["document"]["id"]))
        old_after = db.get(DocumentVersion, uuid.UUID(first.json()["version"]["id"]))
        new_version = db.get(DocumentVersion, uuid.UUID(second.json()["version"]["id"]))
        assert str(document.active_version_id) == active_before, "失败新版不得切换有效版本"
        assert new_version.state == "failed"
        assert old_after.state == "published"
        old_path = app.state.store.path_for(old_after.stored_path)
        assert hashlib.sha256(old_path.read_bytes()).hexdigest() == old_sha_before, "旧有效版原件字节不变"
    finally:
        db.close()
