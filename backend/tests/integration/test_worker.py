"""T03 持久任务/worker 检查：领取租约、检查点、恢复、重试与状态边界。

任务由 HTTP 上传创建但处理不依赖请求连接；本文件直接以单次入口/子进程运行 worker，
不启动任何常驻后台服务。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from mktkb.db import Database
from mktkb.documents.models import Document, DocumentVersion, SourceUnit
from mktkb.ingestion.models import ImportJob
from mktkb.ingestion.parsers import ParseServices
from mktkb.ingestion.worker import _LeaseLost, _checkpoint, claim_job, retry_job, run_one_job

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
D03 = FIXTURES / "normal" / "D03_市场部工作指南.docx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
B06 = FIXTURES / "boundary" / "B06_超过5000行.xlsx"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session(app):
    return app.state.db.session()


def _run(app, **kwargs):
    db = _session(app)
    try:
        return run_one_job(db, app.state.store, **kwargs)
    finally:
        db.close()


def _claim(app, **kwargs):
    db = _session(app)
    try:
        return claim_job(db, **kwargs)
    finally:
        db.close()


def _job(app, job_id):
    import uuid

    db = _session(app)
    try:
        return db.get(ImportJob, uuid.UUID(str(job_id)))
    finally:
        db.close()


def _version(app, version_id):
    import uuid

    db = _session(app)
    try:
        return db.get(DocumentVersion, uuid.UUID(str(version_id)))
    finally:
        db.close()


def _document(app, document_id):
    import uuid

    db = _session(app)
    try:
        return db.get(Document, uuid.UUID(str(document_id)))
    finally:
        db.close()


def _unit_count(app, version_id=None) -> int:
    import uuid

    db = _session(app)
    try:
        query = select(SourceUnit.id)
        if version_id is not None:
            query = query.where(SourceUnit.version_id == uuid.UUID(str(version_id)))
        return len(db.scalars(query).all())
    finally:
        db.close()


# ---------------------------------------------------------------- 正常处理


def test_worker_processes_uploaded_xlsx_to_review_required(app, admin_write):
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    assert upload.status_code == 202
    payload = upload.json()

    result = _run(app)
    assert result.state == "succeeded", result
    assert result.units_written == 9
    assert result.error_code is None

    job = _job(app, payload["job"]["id"])
    version = _version(app, payload["version"]["id"])
    document = _document(app, payload["document"]["id"])
    assert job.state == "succeeded" and job.stage == "finished"
    assert job.completed_pages == job.total_pages == 9
    assert job.lease_token is None and job.lease_expires_at is None
    assert version.state == "review_required"
    assert version.processing_report["kind"] == "xlsx"
    assert version.processing_report["sheets"][2]["hidden"] is True
    assert document.active_version_id is None, "T03 处理成功只到 review_required，不切换有效版本"
    assert document.last_published_at is None
    assert _unit_count(app, payload["version"]["id"]) == 9

    again = _run(app)
    assert again.state == "idle"


def test_worker_processes_docx_and_keeps_body_order(app, admin_write):
    upload = admin_write.upload(path=D03, name="工作指南.docx")
    assert upload.status_code == 202
    result = _run(app)
    assert result.state == "succeeded" and result.units_written == 8

    db = _session(app)
    try:
        units = db.scalars(
            select(SourceUnit).where(SourceUnit.version_id == __import__("uuid").UUID(upload.json()["version"]["id"])).order_by(SourceUnit.ordinal)
        ).all()
    finally:
        db.close()
    assert [unit.unit_key for unit in units][:3] == ["paragraph:1", "paragraph:2", "paragraph:3"]
    assert units[0].kind == "paragraph"
    assert units[0].text == "市场部工作指南"
    assert units[2].text == "2.3 物料领用与登记"


def test_new_version_failure_does_not_touch_existing_active_version(app, admin_write):
    first = admin_write.upload(path=D01, name="物品位置表.xlsx")
    document_id = first.json()["document"]["id"]
    second = admin_write.upload(path=V03, name="物品位置表.xlsx", document_id=document_id)
    assert second.status_code == 202

    import uuid
    from datetime import datetime, timezone

    db = _session(app)
    try:
        document = db.get(Document, uuid.UUID(document_id))
        old_version = db.get(DocumentVersion, uuid.UUID(first.json()["version"]["id"]))
        old_version.state = "published"
        old_version.published_at = datetime.now(timezone.utc)
        document.active_version_id = old_version.id
        document.last_published_at = datetime.now(timezone.utc)
        # 模拟 T04 已发布完成后的任务终态（T03 不提供发布接口）
        old_job = db.get(ImportJob, uuid.UUID(first.json()["job"]["id"]))
        old_job.state = "succeeded"
        old_job.stage = "finished"
        old_job.total_pages = 9
        old_job.completed_pages = 9
        old_job.retryable = False
        old_job.lease_token = None
        old_job.lease_expires_at = None
        db.commit()
    finally:
        db.close()

    result = _run(app)
    assert result.state == "succeeded"

    document = _document(app, document_id)
    assert str(document.active_version_id) == first.json()["version"]["id"], "新版待确认不得切换有效版本"
    new_version = _version(app, second.json()["version"]["id"])
    assert new_version.state == "review_required"


# ---------------------------------------------------------------- 租约与恢复


def test_claim_lease_is_exclusive(app, admin_write):
    upload = admin_write.upload(path=D01)
    t0 = _now()

    first = _claim(app, now=t0)
    assert first is not None and str(first.job_id) == upload.json()["job"]["id"]
    second = _claim(app, now=t0)
    assert second is None, "同一有效租约不能被两个 worker 同时持有"

    job = _job(app, upload.json()["job"]["id"])
    assert job.state == "running" and job.attempts == 1


def test_expired_lease_reclaim_and_stale_commit_rejected(app, admin_write):
    upload = admin_write.upload(path=D01)
    t0 = _now()
    lease_a = _claim(app, now=t0, lease_seconds=5)
    assert lease_a is not None

    lease_b = _claim(app, now=t0 + timedelta(seconds=6))
    assert lease_b is not None and lease_b.token != lease_a.token

    stolen = _run(app, lease=lease_a, now=t0 + timedelta(seconds=6))
    assert stolen.state == "lease_lost"
    assert _unit_count(app, upload.json()["version"]["id"]) == 0, "过期租约不得写入任何检查点"

    finished = _run(app, lease=lease_b, now=t0 + timedelta(seconds=6))
    assert finished.state == "succeeded"
    job = _job(app, upload.json()["job"]["id"])
    assert job.state == "succeeded" and job.attempts == 2


def test_checkpoint_pause_and_resume_without_duplicate_units(app, admin_write):
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    t0 = _now()
    paused = _run(app, now=t0, max_units=2)
    assert paused.state == "paused", paused
    assert paused.units_written == 2
    job = _job(app, upload.json()["job"]["id"])
    assert job.state == "running" and job.completed_pages == 2 and job.total_pages == 9
    assert _unit_count(app, upload.json()["version"]["id"]) == 2

    lease = _claim(app, now=t0 + timedelta(seconds=600))
    assert lease is not None
    resumed = _run(app, lease=lease, now=t0 + timedelta(seconds=600))
    assert resumed.state == "succeeded"
    assert resumed.units_written == 7 and resumed.units_reused == 2
    assert _unit_count(app, upload.json()["version"]["id"]) == 9
    keys = _all_unit_keys(app, upload.json()["version"]["id"])
    assert len(keys) == len(set(keys)) == 9


def _all_unit_keys(app, version_id: str) -> list[str]:
    import uuid

    db = _session(app)
    try:
        units = db.scalars(select(SourceUnit).where(SourceUnit.version_id == uuid.UUID(version_id))).all()
        return [unit.unit_key for unit in units]
    finally:
        db.close()


def test_subprocess_worker_restart_resumes_after_checkpoint(app, admin_write, settings):
    """真实子进程：第一个 worker 保存检查点后退出，新进程恢复并完成。"""
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    assert upload.status_code == 202
    version_id = upload.json()["version"]["id"]
    job_id = upload.json()["job"]["id"]
    database_url = settings.resolved_database_url()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend" / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    command = [
        sys.executable,
        "-B",
        "-m",
        "mktkb.ingestion.worker",
        "--database-url",
        database_url,
        "--storage-dir",
        str(app.state.store.root),
        "--max-units",
        "2",
    ]
    child = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=str(settings.data_dir),
    )
    assert child.returncode == 0, child.stderr
    line = [item for item in child.stdout.strip().splitlines() if item.startswith("{")][-1]
    child_result = json.loads(line)
    assert child_result["state"] == "paused" and child_result["units_written"] == 2
    assert str(child_result["job_id"]) == job_id

    job = _job(app, job_id)
    assert job.state == "running" and job.completed_pages == 2
    assert job.lease_token is not None
    assert _unit_count(app, version_id) == 2

    # 模拟时间流逝（租约自然过期）后由新进程恢复
    t_later = _now() + timedelta(seconds=600)
    lease = _claim(app, now=t_later)
    assert lease is not None
    resumed = _run(app, lease=lease, now=t_later)
    assert resumed.state == "succeeded"
    assert resumed.units_reused == 2
    job = _job(app, job_id)
    assert job.state == "succeeded" and job.attempts == 2
    version = _version(app, version_id)
    assert version.state == "review_required"
    assert _unit_count(app, version_id) == 9
    keys = _all_unit_keys(app, version_id)
    assert len(keys) == len(set(keys)) == 9


def test_lease_renewal_extends_expiry_during_long_run(app, admin_write):
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    t0 = _now()
    lease = _claim(app, now=t0, lease_seconds=120)
    assert lease is not None

    ticks = {"index": 0}

    def clock() -> datetime:
        # T04 起 worker 在每推进一个单元前核对租约到期，假时钟按调用次数推进；
        # 这里用 10 秒步长让 5 个单元的核对仍落在 120 秒租约内，续期断言保持不变。
        value = t0 + timedelta(seconds=10 * ticks["index"])
        ticks["index"] += 1
        return value

    # 处理 5 个单元后暂停：停顿点保存检查点，运行超过 30 秒应已续期且租约仍在任务上
    paused = _run(app, lease=lease, now_fn=clock, lease_seconds=120, renew_seconds=30, max_units=5)
    assert paused.state == "paused"
    job = _job(app, upload.json()["job"]["id"])
    assert job.state == "running" and job.completed_pages == 5
    assert job.lease_expires_at is not None
    assert _as_utc(job.lease_expires_at) > t0 + timedelta(seconds=120), "运行超过 30 秒后应续期租约"
    assert _as_utc(job.lease_expires_at) == t0 + timedelta(seconds=190)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 失败与重试


def test_retry_failed_job_requeues_and_restores_checkpoint(app, admin_write):
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    job_id = upload.json()["job"]["id"]
    version_id = upload.json()["version"]["id"]

    def boom(path, kind, services):
        raise RuntimeError("simulated transient parser failure")

    failed = _run(app, parsers={"xlsx": boom, "docx": boom})
    assert failed.state == "failed" and failed.error_code == "PARSE_INTERNAL"
    job = _job(app, job_id)
    version = _version(app, version_id)
    assert job.state == "failed" and job.retryable is True
    assert version.state == "failed"

    db = _session(app)
    try:
        retry_job(db, __import__("uuid").UUID(str(job_id)))
    finally:
        db.close()
    job = _job(app, job_id)
    version = _version(app, version_id)
    assert job.state == "queued" and job.stage == "queued"
    assert version.state == "queued"

    result = _run(app)
    assert result.state == "succeeded" and result.units_written == 9
    assert _job(app, job_id).attempts == 2
    db = _session(app)
    try:
        jobs = db.scalars(select(ImportJob)).all()
        assert len(jobs) == 1, "重试不得产生重复任务"
    finally:
        db.close()


def test_retry_conflicts_for_running_and_succeeded_jobs(app, admin_write):
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    job_id = upload.json()["job"]["id"]

    lease = _claim(app, now=_now())
    assert lease is not None
    response = admin_write.client.post(f"/api/v1/jobs/{job_id}/retry", headers=admin_write.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_ALREADY_RUNNING"

    db = _session(app)
    try:
        job = db.get(ImportJob, __import__("uuid").UUID(str(job_id)))
        job.state = "queued"
        job.lease_token = None
        job.lease_expires_at = None
        db.commit()
    finally:
        db.close()
    assert _run(app).state == "succeeded"
    response = admin_write.client.post(f"/api/v1/jobs/{job_id}/retry", headers=admin_write.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_RETRYABLE"


def test_parse_limit_failure_is_not_partial_success(app, admin_write):
    upload = admin_write.upload(path=B06, name="B06_超过5000行.xlsx")
    assert upload.status_code == 202, upload.text
    result = _run(app)
    assert result.state == "failed"
    assert result.error_code == "EXCEL_ROW_LIMIT"
    job = _job(app, upload.json()["job"]["id"])
    version = _version(app, upload.json()["version"]["id"])
    assert job.state == "failed" and job.retryable is False
    assert version.state == "failed"
    assert version.processing_report["quality"]["complete"] is False
    assert version.processing_report["total_data_rows"] == 5001
    assert _unit_count(app, upload.json()["version"]["id"]) == 0, "超限不得截断成部分成功记录"


def test_worker_blocks_when_document_deleted_before_commit(app, admin_write):
    import uuid

    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    t0 = _now()
    lease = _claim(app, now=t0)
    assert lease is not None
    db = _session(app)
    try:
        document = db.get(Document, uuid.UUID(upload.json()["document"]["id"]))
        document.deleted = True  # 模拟 T04 删除；T03 不提供删除接口
        db.commit()
    finally:
        db.close()

    result = _run(app, lease=lease, now=t0)
    assert result.state == "blocked"
    job = _job(app, upload.json()["job"]["id"])
    version = _version(app, upload.json()["version"]["id"])
    assert job.state == "blocked" and job.error_code == "CONTENT_DELETED"
    assert version.state == "failed"
    assert version.state != "review_required"


def test_worker_fails_when_original_file_missing(app, admin_write):
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    version = _version(app, upload.json()["version"]["id"])
    original = app.state.store.root / version.stored_path
    original.unlink()

    result = _run(app)
    assert result.state == "failed" and result.error_code == "FILE_MISSING"
    job = _job(app, upload.json()["job"]["id"])
    assert job.state == "failed" and job.retryable is False
    assert _version(app, upload.json()["version"]["id"]).state == "failed"


# ---------------------------------------------------------------- 接口形态


def test_job_status_endpoint_matches_contract(app, admin_write):
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    job_id = upload.json()["job"]["id"]
    response = admin_write.client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id and body["state"] == "queued"
    assert set(body) >= {
        "id",
        "version_id",
        "state",
        "stage",
        "completed_pages",
        "total_pages",
        "error_code",
        "message",
        "retryable",
    }
    assert admin_write.client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


# ---------------------------------------------------------------- T03-R1：租约回收原子性


def test_reclaim_update_rechecks_renewal_committed_first(app, admin_write):
    """PM03-03：SELECT 后原持有者续期先提交，新领取者的条件 UPDATE 必须重新核对到期时间。"""
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    start = datetime.now(timezone.utc)
    lease = _claim(app, now=start, lease_seconds=2)
    assert lease is not None
    contender_time = start + timedelta(seconds=3)

    db = _session(app)
    try:
        original_scalar = db.scalar
        injected = {"done": False}

        def scalar_then_renew(statement, *args, **kwargs):
            result = original_scalar(statement, *args, **kwargs)
            if isinstance(result, ImportJob) and not injected["done"]:
                injected["done"] = True
                from sqlalchemy import update

                with _session(app) as owner:
                    owner.execute(
                        update(ImportJob)
                        .where(ImportJob.id == lease.job_id)
                        .values(lease_expires_at=contender_time + timedelta(seconds=120))
                    )
                    owner.commit()
            return result

        with patch.object(db, "scalar", side_effect=scalar_then_renew):
            stolen = claim_job(db, now=contender_time)
    finally:
        db.close()
    assert injected["done"] is True
    assert stolen is None, "续期已提交后不得被回收视角的旧到期值抢走"
    job = _job(app, upload.json()["job"]["id"])
    assert job.lease_token == lease.token


def test_stale_owner_rejected_after_reclaim_committed_first(app, admin_write):
    """PM03-03：回收先提交后，旧 token 的检查点、续期与最终提交都必须被拒绝。"""
    upload = admin_write.upload(path=D01, name="物品位置表.xlsx")
    start = datetime.now(timezone.utc)
    old_lease = _claim(app, now=start, lease_seconds=2)
    assert old_lease is not None
    later = start + timedelta(seconds=3)
    new_lease = _claim(app, now=later, lease_seconds=120)
    assert new_lease is not None and new_lease.token != old_lease.token

    db = _session(app)
    try:
        job = db.get(ImportJob, old_lease.job_id)
        with pytest.raises(_LeaseLost):
            _checkpoint(db, job, old_lease, ParseServices(), 0, lambda: later, 120, 1)
    finally:
        db.close()

    stale_run = _run(app, lease=old_lease, now=later)
    assert stale_run.state == "lease_lost"
    status = _job(app, upload.json()["job"]["id"])
    assert status.state == "running"
    assert status.lease_token == new_lease.token, "新持有者租约不得被旧 worker 覆盖"


def test_lease_expiry_boundary_is_claimable(app, admin_write):
    """PM03-03：有效期边界按“到期即不可提交”，回收在 expires_at == now 时可领取。"""
    admin_write.upload(path=D01, name="物品位置表.xlsx")
    start = datetime.now(timezone.utc)
    first = _claim(app, now=start, lease_seconds=2)
    assert first is not None
    second = _claim(app, now=start + timedelta(seconds=2))
    assert second is not None, "边界时刻应判为已过期，可被回收"
    assert second.token != first.token


def test_two_concurrent_claimers_get_single_lease(app, admin_write):
    """PM03-03：两个领取者竞争同一任务，条件 UPDATE 只能有一个成功。"""
    admin_write.upload(path=D01, name="物品位置表.xlsx")
    start = datetime.now(timezone.utc)
    barrier = threading.Barrier(2)
    results: list = []

    def contend(index: int) -> None:
        barrier.wait()
        for _attempt in range(5):
            session = _session(app)
            try:
                results.append((index, claim_job(session, now=start)))
                return
            except Exception:
                time.sleep(0.05)
            finally:
                session.close()

    threads = [threading.Thread(target=contend, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    granted = [lease for _index, lease in results if lease is not None]
    assert len(granted) == 1, results
