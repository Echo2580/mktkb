"""T03/T04 资料路由：管理员上传/列表/详情/预览/受保护原件，以及发布/取消/删除。

所有资料接口要求管理员角色；写接口同时校验受信任 Origin 与当前会话 CSRF。
不公开静态挂载存储目录；生命周期写操作只在短事务内切换状态并递增 revision。
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth.routes import (
    get_db,
    require_role,
    require_session_csrf,
    require_trusted_origin,
)
from ..documents import lifecycle
from ..documents import service as document_service
from ..documents.schemas import (
    Deletion,
    DocumentDetail,
    DocumentList,
    PreviewResponse,
    Publication,
    PublishRequest,
    UploadResponse,
)
from ..documents.service import UploadInput, media_type_for, stage_upload

router = APIRouter(prefix="/documents", tags=["documents"])

# DELETE query 只接受非负十进制整数字符串：在 FastAPI 整数转换前核对原始写法，
# 避免 "1.0" 被静默转换为 1 后执行删除；缺失仍交给统一参数校验返回 422。
_EXPECTED_REVISION_QUERY = re.compile(r"^[0-9]+$")


def _validate_expected_revision_query(request: Request) -> None:
    values = request.query_params.getlist("expected_revision")
    if not values:
        return
    raw = values[0]
    if len(values) != 1 or _EXPECTED_REVISION_QUERY.fullmatch(raw) is None:
        raise RequestValidationError(
            [
                {
                    "loc": ("query", "expected_revision"),
                    "type": "int_parsing",
                    "msg": "Input should be a non-negative decimal integer",
                }
            ]
        )

admin_user = Depends(require_role("admin"))
trusted_origin = Depends(require_trusted_origin)
session_csrf = Depends(require_session_csrf)


def _store(request: Request):
    return request.app.state.store


def _qa(request: Request):
    return getattr(request.app.state, "qa", None)


def _sync_qa_index(request: Request) -> None:
    """发布/删除后同步 rag 索引；同步失败只记录状态，由问答入口返回明确的可重试错误。"""
    qa = _qa(request)
    if qa is not None:
        qa.notify_knowledge_changed()


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=UploadResponse, summary="上传资料")
def create_document(
    request: Request,
    file: UploadFile = File(...),
    allow_same_name: bool = Form(False),
    db: Session = Depends(get_db),
    _user=admin_user,
    _origin=trusted_origin,
    _csrf=session_csrf,
) -> UploadResponse:
    upload = UploadInput(filename=file.filename or "", stream=file.file, content_type=file.content_type)
    receipt = stage_upload(db, _store(request), upload, allow_same_name=allow_same_name)
    return document_service.upload_response(db, receipt)


@router.post(
    "/{document_id}/versions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadResponse,
    summary="上传资料新版（不切换有效版本）",
)
def create_version(
    request: Request,
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    expected_active_version_id: uuid.UUID | None = Form(None),
    db: Session = Depends(get_db),
    _user=admin_user,
    _origin=trusted_origin,
    _csrf=session_csrf,
) -> UploadResponse:
    upload = UploadInput(filename=file.filename or "", stream=file.file, content_type=file.content_type)
    receipt = stage_upload(
        db,
        _store(request),
        upload,
        document_id=document_id,
        expected_active_version_id=expected_active_version_id,
    )
    return document_service.upload_response(db, receipt)


@router.get("", response_model=DocumentList, summary="资料列表（分页）")
def list_documents(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    file_type: str | None = Query(default=None, pattern="^(xlsx|docx|pdf|png|jpg|jpeg)$"),
    state: str | None = Query(
        default=None,
        pattern="^(queued|processing|review_required|failed|published|superseded|cancelled|deleted)$",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user=admin_user,
) -> DocumentList:
    items, total = document_service.list_documents(
        db, q=q, file_type=file_type, state=state, offset=offset, limit=limit
    )
    return DocumentList(
        items=[document_service.document_summary(db, document) for document in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{document_id}", response_model=DocumentDetail, summary="资料元信息与版本摘要")
def document_detail(
    request: Request,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=admin_user,
) -> DocumentDetail:
    return document_service.document_detail(db, document_id)


@router.post(
    "/{document_id}/versions/{version_id}/publish",
    response_model=Publication,
    summary="发布待确认版本（原子切换有效版本并递增 revision）",
)
def publish_version_endpoint(
    request: Request,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: PublishRequest,
    db: Session = Depends(get_db),
    _user=admin_user,
    _origin=trusted_origin,
    _csrf=session_csrf,
) -> Publication:
    publication = lifecycle.publish_version(
        db,
        document_id,
        version_id,
        expected_active_version_id=payload.expected_active_version_id,
        expected_revision=payload.expected_revision,
    )
    _sync_qa_index(request)
    return publication


@router.post(
    "/{document_id}/versions/{version_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="取消未生效版本及其任务（保留旧有效版本）",
)
def cancel_version_endpoint(
    request: Request,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=admin_user,
    _origin=trusted_origin,
    _csrf=session_csrf,
) -> None:
    lifecycle.cancel_version(db, document_id, version_id)


@router.delete(
    "/{document_id}",
    response_model=Deletion,
    summary="逻辑删除资料（撤销内容访问，取消未完成任务）",
)
def delete_document_endpoint(
    request: Request,
    document_id: uuid.UUID,
    expected_revision: int = Query(ge=0),
    db: Session = Depends(get_db),
    _user=admin_user,
    _origin=trusted_origin,
    _csrf=session_csrf,
    _raw_revision=Depends(_validate_expected_revision_query),
) -> Deletion:
    deletion = lifecycle.delete_document(db, document_id, expected_revision=expected_revision)
    _sync_qa_index(request)
    return deletion


@router.get(
    "/{document_id}/versions/{version_id}/preview",
    response_model=PreviewResponse,
    summary="分页查看来源单元与处理摘要",
)
def preview_version(
    request: Request,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    sheet: str | None = Query(default=None, max_length=128),
    page: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    _user=admin_user,
) -> PreviewResponse:
    return document_service.preview(
        db, document_id, version_id, offset=offset, limit=limit, sheet=sheet, page=page
    )


@router.get(
    "/{document_id}/versions/{version_id}/file",
    summary="管理员受保护原件",
    response_class=FileResponse,
)
def version_file(
    request: Request,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=admin_user,
):
    document, version, path = document_service.resolve_version_file(
        _store(request), db, document_id, version_id
    )
    media_type = media_type_for(document.file_type)
    headers = {
        "Content-Disposition": "inline; filename*=UTF-8''" + quote(document.name),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    return FileResponse(path, media_type=media_type, headers=headers)
