"""登录/退出/当前用户路由与角色依赖。权限由服务端依赖执行，不依赖页面隐藏。"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from ..errors import CsrfInvalid, OriginRejected, RoleRequired
from .schemas import LoginRequest, SessionResponse, UserPublic
from .security import csrf_token_for
from .service import UserContext, login, logout, require_user

router = APIRouter(prefix="/auth", tags=["auth"])


def get_settings(request: Request):
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.db.session()
    try:
        yield session
    finally:
        session.close()


def require_trusted_origin(request: Request) -> None:
    """登录与写操作都校验 Origin；缺失或不受信任一律拒绝。"""
    settings = get_settings(request)
    origin = request.headers.get("origin")
    if not origin or origin not in settings.trusted_origins:
        raise OriginRejected()


def require_session_csrf(request: Request) -> None:
    """写操作校验会话绑定的 CSRF 令牌；供 T03 资料/任务接口复用，不改变登录/退出行为。"""
    settings = get_settings(request)
    token = _session_cookie(request)
    provided = request.headers.get("x-csrf-token")
    if not token or not provided:
        raise CsrfInvalid()
    expected = csrf_token_for(settings.csrf_secret, token)
    if not _constant_time_equal(provided, expected):
        raise CsrfInvalid()


def _session_cookie(request: Request) -> str | None:
    settings = get_settings(request)
    return request.cookies.get(settings.cookie_name)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserContext:
    settings = get_settings(request)
    return require_user(db, _session_cookie(request), now=None)


def require_role(role: str) -> Callable[..., UserContext]:
    """角色检查依赖：员工即使拿到管理员路由也会被服务端拒绝。"""

    def dependency(user: UserContext = Depends(get_current_user)) -> UserContext:
        if user.role != role:
            raise RoleRequired(role)
        return user

    return dependency


def _set_session_cookie(response: Response, request: Request, token: str, max_age: int) -> None:
    settings = get_settings(request)
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    settings = get_settings(request)
    response.delete_cookie(key=settings.cookie_name, path="/")


@router.post("/login", response_model=SessionResponse)
def login_endpoint(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _origin=Depends(require_trusted_origin),
) -> SessionResponse:
    settings = get_settings(request)
    result = login(
        db,
        payload.username,
        payload.password,
        ttl_seconds=settings.session_ttl_seconds,
        csrf_secret=settings.csrf_secret,
    )
    _set_session_cookie(response, request, result.session_token, settings.session_ttl_seconds)
    return SessionResponse(user=UserPublic.model_validate(result.user), csrf_token=result.csrf_token)


@router.get("/me", response_model=SessionResponse)
def me_endpoint(
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> SessionResponse:
    settings = get_settings(request)
    token = _session_cookie(request) or ""
    return SessionResponse(
        user=UserPublic(id=user.id, display_name=user.display_name, role=user.role),
        csrf_token=csrf_token_for(settings.csrf_secret, token),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _origin=Depends(require_trusted_origin),
) -> Response:
    """校验 Origin 与会话对应 CSRF 后撤销当前会话；重复退出保持 204。"""
    settings = get_settings(request)
    token = _session_cookie(request)
    if token:
        provided = request.headers.get("x-csrf-token")
        expected = csrf_token_for(settings.csrf_secret, token)
        if not provided or not _constant_time_equal(provided, expected):
            raise CsrfInvalid()
        logout(db, token)
    _clear_session_cookie(response, request)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
