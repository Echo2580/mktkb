"""T06 来源路由：本人消息引用详情与受保护原件。

两条路由都先校验"当前用户拥有 message 所属未删除会话 + source_id 确为该消息引用"，
再核对来源当前有效性；失效来源 410 且不带正文/字段/原图/内部路径。
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth.routes import get_db
from ..auth.service import UserContext
from ..conversations.routes import current_user_snapshot
from ..sources import service as source_service
from ..sources.schemas import SourceView

router = APIRouter(tags=["sources"])


def _store(request: Request):
    return request.app.state.store


@router.get(
    "/messages/{message_id}/sources/{source_id}",
    response_model=SourceView,
    summary="本人消息引用来源详情",
)
def get_message_source(
    message_id: uuid.UUID,
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: UserContext = Depends(current_user_snapshot),
) -> SourceView:
    return source_service.get_message_source(db, user, message_id, source_id)


@router.get(
    "/messages/{message_id}/sources/{source_id}/file",
    response_class=FileResponse,
    summary="本人消息引用的受保护原件",
)
def get_message_source_file(
    message_id: uuid.UUID,
    source_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: UserContext = Depends(current_user_snapshot),
):
    _message, _unit, _version, document, path = source_service.resolve_source_file(
        db, _store(request), user, message_id, source_id
    )
    headers = {
        "Content-Disposition": "inline; filename*=UTF-8''" + quote(document.name),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    return FileResponse(path, media_type=source_service.media_type_for(document), headers=headers)
