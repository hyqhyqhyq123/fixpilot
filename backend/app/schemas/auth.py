# backend/app/schemas/auth.py
# 作用：认证 API 请求/响应结构（FR-001）

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="登录邮箱")
    password: str = Field(..., min_length=8, max_length=128, description="密码至少 8 位")


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    github_user_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class GitHubOAuthStartResponse(BaseModel):
    auth_url: str
    state: str


class GitHubOAuthCallbackRequest(BaseModel):
    code: str = Field(..., min_length=1, description="GitHub callback code")
    state: str = Field(..., min_length=1, description="OAuth state")


class MessageResponse(BaseModel):
    message: str
