"""T06 个人会话路由：本人会话 CRUD、消息列表与异步问答。

- 公开前缀仍由 ``main`` 统一加 ``/api/v1``；
- 写操作复用既有 Origin/CSRF 依赖；本人会话对 admin/employee 都适用，管理员没有他人会话特权；
- 问答入口在读取用户后立刻关闭读 Session，模型 await 期间不持有数据库读事务。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ..auth.routes import get_db, require_session_csrf, require_trusted_origin
from ..auth.service import UserContext, require_user
from ..conversations import service
from ..conversations.schemas import (
    AskRequest,
    AskResult,
    ConversationCreate,
    ConversationList,
    ConversationSummary,
    MessageList,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])

trusted_origin = Depends(require_trusted_origin)
session_csrf = Depends(require_session_csrf)


def current_user_snapshot(request: Request) -> UserContext:
    """只读鉴权后立刻关闭 Session；不把读事务带过模型 await。"""
    settings = request.app.state.settings
    db = request.app.state.db.session()
    try:
        return require_user(db, request.cookies.get(settings.cookie_name), now=None)
    finally:
        db.close()


def _model(request: Request):
    return getattr(request.app.state, "model_gateway", None)


def _qa(request: Request):
    """S2：产品问答内核；未启用时为 None，走既有链路。"""
    return getattr(request.app.state, "qa", None)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConversationSummary, summary="新建本人会话")
def create_conversation(
    payload: ConversationCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: UserContext = Depends(current_user_snapshot),
    _origin=trusted_origin,
    _csrf=session_csrf,
) -> ConversationSummary:
    return service.create_conversation(db, user, payload.title)


@router.get("", response_model=ConversationList, summary="列出本人会话")
def list_conversations(
    db: Session = Depends(get_db),
    user: UserContext = Depends(current_user_snapshot),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> ConversationList:
    return service.list_conversations(db, user, offset=offset, limit=limit)


@router.get("/{conversation_id}/messages", response_model=MessageList, summary="列出本人会话消息")
def list_messages(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: UserContext = Depends(current_user_snapshot),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> MessageList:
    return service.list_messages(db, user, conversation_id, offset=offset, limit=limit)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除本人会话")
def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: UserContext = Depends(current_user_snapshot),
    _origin=trusted_origin,
    _csrf=session_csrf,
):
    service.delete_conversation(db, user, conversation_id, qa=_qa(request))
    return None


@router.post("/{conversation_id}/messages", response_model=AskResult, summary="提问（六类 AskResult）")
async def ask_question(
    conversation_id: uuid.UUID,
    payload: AskRequest,
    request: Request,
    user: UserContext = Depends(current_user_snapshot),
    _origin=trusted_origin,
    _csrf=session_csrf,
) -> AskResult:
    return await service.ask(
        request.app.state.db,
        user,
        conversation_id,
        payload,
        model=_model(request),
        qa=_qa(request),
    )
