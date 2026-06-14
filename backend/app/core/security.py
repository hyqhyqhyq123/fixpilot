# backend/app/core/security.py
# 作用：密码哈希与 JWT 令牌（FR-001 认证基础）

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """把明文密码变成 bcrypt 哈希，存入数据库。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """登录时比对用户输入与数据库哈希是否一致。"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


def create_access_token(subject: str) -> str:
    """
    签发 JWT access token。

    subject 通常是用户 id（字符串），前端后续放在 Authorization 头里。
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_oauth_state() -> str:
    """
    生成 GitHub OAuth state。

    state 用来防止 CSRF：登录开始时签发，GitHub 回调时必须原样带回。
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=10)
    payload = {
        "purpose": "github_oauth_state",
        "nonce": secrets.token_urlsafe(24),
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def validate_oauth_state(state: str) -> bool:
    """校验 OAuth state 是否由本服务签发且未过期。"""
    settings = get_settings()
    try:
        payload = jwt.decode(
            state,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        return payload.get("purpose") == "github_oauth_state"
    except JWTError:
        return False


def decode_access_token(token: str) -> str | None:
    """解析 token，成功返回 sub（用户 id），失败返回 None。"""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        sub = payload.get("sub")
        return str(sub) if sub is not None else None
    except JWTError:
        return None
