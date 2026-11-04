"""密码摘要、会话令牌与 CSRF 派生。"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import bcrypt

PASSWORD_ALGO_PREFIX = "bcrypt"


def hash_password(password: str, rounds: int) -> tuple[str, str]:
    """返回 (摘要, 算法标识)。盐由 bcrypt 生成，算法与成本记录在标识里。"""
    salt = bcrypt.gensalt(rounds=rounds)
    digest = bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")
    return digest, f"{PASSWORD_ALGO_PREFIX}${rounds}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """服务端只保存令牌的 SHA-256 摘要。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for(secret: str, token: str) -> str:
    """CSRF 令牌由会话令牌派生，绑定该会话且可复算，不额外保存明文。"""
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
