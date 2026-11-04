"""T03 任务路由：查询任务状态、重试合法失败任务（管理员，写操作校验 Origin+CSRF）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from ..auth.routes import get_db, require_role, require_session_csrf, require_trusted_origin
from ..ingestion.schemas import JobStatus
from ..ingestion.worker import get_job, retry_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

admin_user = Depends(require_role("admin"))
trusted_origin = Depends(require_trusted_origin)
session_csrf = Depends(require_session_csrf)


@router.get("/{job_id}", response_model=JobStatus, summary="查询处理任务状态")
def get_job_status(
    request: Request,
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=admin_user,
) -> JobStatus:
    return JobStatus.from_job(get_job(db, job_id))


@router.post(
    "/{job_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobStatus,
    summary="重试失败任务（复用同字节与已保存检查点）",
)
def retry_job_endpoint(
    request: Request,
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=admin_user,
    _origin=trusted_origin,
    _csrf=session_csrf,
) -> JobStatus:
    return JobStatus.from_job(retry_job(db, job_id))
