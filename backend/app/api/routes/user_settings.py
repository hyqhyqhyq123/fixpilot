# backend/app/api/routes/user_settings.py
# 设置页 API：GitHub Token + 模型配置（需登录）

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user_settings import UserSettingsResponse, UserSettingsUpdate
from app.services import user_settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSettingsResponse:
    """读取当前用户设置（Token 仅返回掩码）。"""
    return await user_settings_service.get_or_create_settings(db, user)


@router.put("", response_model=UserSettingsResponse)
async def put_settings(
    body: UserSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSettingsResponse:
    """更新 GitHub Token / 模型偏好。"""
    return await user_settings_service.update_settings(db, user, body)
