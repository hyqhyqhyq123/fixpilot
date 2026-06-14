# backend/app/services/user_settings_service.py

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.user_settings import UserSettingsResponse, UserSettingsUpdate


def _token_hint(token: str | None) -> str | None:
    if not token or len(token) < 4:
        return None
    return f"****{token[-4:]}"


def _to_response(row: UserSettings | None) -> UserSettingsResponse:
    server = get_settings()
    user_model = row.model_name if row else None
    user_base = row.llm_base_url if row else None
    token = row.github_token if row else None

    return UserSettingsResponse(
        github_token_configured=bool(token),
        github_token_hint=_token_hint(token),
        model_name=user_model or server.model_name,
        llm_base_url=user_base or server.openai_base_url,
        user_model_name=user_model,
        user_llm_base_url=user_base,
        server_model_name=server.model_name,
        server_llm_base_url=server.openai_base_url,
    )


async def get_or_create_settings(
    db: AsyncSession,
    user: User,
) -> UserSettingsResponse:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    return _to_response(row)


async def update_settings(
    db: AsyncSession,
    user: User,
    body: UserSettingsUpdate,
) -> UserSettingsResponse:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)

    if body.github_token is not None:
        row.github_token = body.github_token.strip() or None

    if body.model_name is not None:
        cleaned = body.model_name.strip()
        row.model_name = cleaned or None

    if body.llm_base_url is not None:
        cleaned = body.llm_base_url.strip()
        row.llm_base_url = cleaned or None

    await db.flush()
    await db.refresh(row)
    return _to_response(row)
