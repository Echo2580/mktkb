"""T03 任务接口响应模型：JobStatus 字段与契约一致（completed_pages/total_pages）。"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

JobState = Literal["queued", "running", "succeeded", "failed", "blocked", "cancelled"]


class JobStatus(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    state: JobState
    stage: str
    completed_pages: int
    total_pages: int
    error_code: str | None = None
    message: str | None = None
    retryable: bool

    @classmethod
    def from_job(cls, job) -> "JobStatus":
        return cls(
            id=job.id,
            version_id=job.version_id,
            state=job.state,
            stage=job.stage,
            completed_pages=job.completed_pages,
            total_pages=job.total_pages,
            error_code=job.error_code,
            message=job.message,
            retryable=job.retryable,
        )
