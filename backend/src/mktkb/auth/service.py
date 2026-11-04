"""账号与会话服务：登录、会话解析、退出与账号初始化（幂等）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import AuthRequired, InvalidCredentials, SessionExpired
from .models import LoginSession, User
from .security import csrf_token_for, hash_password, new_session_token, token_hash, verify_password

DEFAULT_TTL_SECONDS = 8 * 3600


@dataclass
class UserContext:
    id: uuid.UUID
    username: str
    display_name: str
    role: str
    session_id: uuid.UUID


@dataclass
class LoginResult:
    user: User
    session_token: str
    csrf_token: str
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def login(
    db: Session,
    username: str,
    password: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    csrf_secret: str,
) -> LoginResult:
    """校验凭据并创建持久会话。未知用户与错误密码返回同一错误。"""
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    token = new_session_token()
    expires_at = _now() + timedelta(seconds=ttl_seconds)
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return LoginResult(
        user=user,
        session_token=token,
        csrf_token=csrf_token_for(csrf_secret, token),
        expires_at=expires_at,
    )


def require_user(db: Session, session_token: str | None, *, now: datetime | None = None) -> UserContext:
    """按会话令牌解析当前用户；缺失、过期或已撤销均返回 401。"""
    if not session_token:
        raise AuthRequired()
    row = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_token)))
    if row is None or row.revoked_at is not None:
        raise AuthRequired()
    moment = _as_utc(now or _now())
    if _as_utc(row.expires_at) <= moment:
        raise SessionExpired()
    user = db.get(User, row.user_id)
    if user is None:
        raise AuthRequired()
    return UserContext(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        session_id=row.id,
    )


def logout(db: Session, session_token: str | None) -> bool:
    """撤销当前会话；不存在或已撤销时返回 False（调用方按幂等处理）。"""
    if not session_token:
        return False
    row = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_token)))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    db.commit()
    return True


def create_account(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str,
    role: str,
    rounds: int = 12,
) -> User:
    """创建账号（供初始化与测试使用，不对外开放注册）。重名直接报错。"""
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise ValueError(f"account already exists: {username}")
    digest, algo = hash_password(password, rounds)
    user = User(
        username=username,
        display_name=display_name,
        role=role,
        password_hash=digest,
        password_algo=algo,
    )
    db.add(user)
    db.commit()
    return user


def bootstrap_accounts(
    db: Session,
    *,
    admin_username: str,
    admin_password: str,
    admin_display_name: str,
    employee_username: str,
    employee_password: str,
    employee_display_name: str,
    rounds: int = 12,
) -> list[str]:
    """幂等初始化预置账号：只补缺失账号，不重置已有密码、不复制账号、不清库。"""
    created: list[str] = []
    existing = set(db.scalars(select(User.username)).all())
    for username, password, display_name, role in (
        (admin_username, admin_password, admin_display_name, "admin"),
        (employee_username, employee_password, employee_display_name, "employee"),
    ):
        if username in existing:
            continue
        create_account(db, username=username, password=password, display_name=display_name, role=role, rounds=rounds)
        created.append(username)
    return created


def account_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User)) or 0)
