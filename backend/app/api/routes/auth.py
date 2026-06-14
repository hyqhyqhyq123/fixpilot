# backend/app/api/routes/auth.py
# 作用：用户注册 / 登录 / 登出 / 当前用户（FR-001）

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_oauth_state,
    hash_password,
    validate_oauth_state,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    GitHubOAuthCallbackRequest,
    GitHubOAuthStartResponse,
    MessageResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def _github_oauth_settings():
    settings = get_settings()
    if (
        not settings.github_oauth_client_id
        or not settings.github_oauth_client_secret
        or not settings.github_oauth_redirect_uri
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub OAuth 未配置 client_id / client_secret / redirect_uri",
        )
    return settings


def _pick_github_email(profile: dict, emails: list[dict]) -> str:
    """从 GitHub profile/emails 中选择一个可用于 users.email 的地址。"""

    for item in emails:
        if item.get("primary") and item.get("verified") and item.get("email"):
            return str(item["email"]).lower()
    if profile.get("email"):
        return str(profile["email"]).lower()

    login = str(profile.get("login") or "github-user").lower()
    github_id = str(profile.get("id") or secrets.token_hex(4))
    return f"{login}-{github_id}@users.noreply.github.com"


async def _exchange_github_code(code: str, settings) -> str:
    """用 GitHub callback code 换取 GitHub access token。"""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_oauth_client_id,
                    "client_secret": settings.github_oauth_client_secret,
                    "code": code,
                    "redirect_uri": settings.github_oauth_redirect_uri,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="连接 GitHub OAuth 失败",
        ) from exc

    data = response.json()
    access_token = data.get("access_token")
    if response.status_code >= 400 or not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=data.get("error_description") or "GitHub OAuth code 无效",
        )
    return str(access_token)


async def _fetch_github_profile(access_token: str) -> tuple[dict, list[dict]]:
    """读取 GitHub 用户基础资料和邮箱列表。"""

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            profile_response = await client.get(GITHUB_USER_URL, headers=headers)
            emails_response = await client.get(GITHUB_EMAILS_URL, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="读取 GitHub 用户信息失败",
        ) from exc

    if profile_response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub access token 无法读取用户信息",
        )

    emails: list[dict] = []
    if emails_response.status_code < 400:
        raw_emails = emails_response.json()
        if isinstance(raw_emails, list):
            emails = raw_emails
    return profile_response.json(), emails


async def _upsert_github_user(
    db: AsyncSession,
    profile: dict,
    emails: list[dict],
) -> User:
    """按 github_user_id 或 email 创建/绑定本地用户。"""

    if not profile.get("id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub 用户信息缺少 id",
        )

    github_user_id = str(profile["id"])
    result = await db.execute(
        select(User).where(User.github_user_id == github_user_id)
    )
    user = result.scalar_one_or_none()
    if user:
        return user

    email = _pick_github_email(profile, emails)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        user.github_user_id = github_user_id
        await db.flush()
        await db.refresh(user)
        return user

    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        github_user_id=github_user_id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/github/authorize", response_model=GitHubOAuthStartResponse)
async def start_github_oauth() -> GitHubOAuthStartResponse:
    """生成 GitHub OAuth 授权地址。"""

    settings = _github_oauth_settings()
    state = create_oauth_state()
    query = urlencode(
        {
            "client_id": settings.github_oauth_client_id,
            "redirect_uri": settings.github_oauth_redirect_uri,
            "scope": "read:user user:email",
            "state": state,
            "allow_signup": "true",
        }
    )
    return GitHubOAuthStartResponse(
        auth_url=f"{GITHUB_AUTHORIZE_URL}?{query}",
        state=state,
    )


@router.post("/github/callback", response_model=TokenResponse)
async def complete_github_oauth(
    body: GitHubOAuthCallbackRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """完成 GitHub OAuth 回调并签发 FixPilot JWT。"""

    settings = _github_oauth_settings()
    if not validate_oauth_state(body.state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub OAuth state 无效或已过期",
        )

    github_token = await _exchange_github_code(body.code, settings)
    profile, emails = await _fetch_github_profile(github_token)
    user = await _upsert_github_user(db, profile, emails)
    token = create_access_token(str(user.id))
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    body: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    """注册新用户（邮箱唯一）。"""
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱已注册",
        )

    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    logger.info("用户注册成功 id=%s", user.id)
    return user


@router.post("/login", response_model=TokenResponse)
async def login_user(
    body: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """邮箱密码登录，返回 JWT。"""
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    token = create_access_token(str(user.id))
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", response_model=MessageResponse)
async def logout_user(
    _user: User = Depends(get_current_user),
) -> MessageResponse:
    """
    登出（JWT 无服务端黑名单时，客户端删除 token 即可）。

    仍要求带有效 token，便于前端统一调用。
    """
    return MessageResponse(message="已登出")


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)) -> User:
    """获取当前登录用户信息。"""
    return user
