"""账号与会话的请求/响应模型。对外只暴露 id/display_name/role。"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["admin", "employee"]


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    role: Role


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)


class SessionResponse(BaseModel):
    user: UserPublic
    csrf_token: str
