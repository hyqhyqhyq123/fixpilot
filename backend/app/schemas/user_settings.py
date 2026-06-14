# backend/app/schemas/user_settings.py

from pydantic import BaseModel, Field


class UserSettingsResponse(BaseModel):
    """返回给前端的设置（不暴露完整 GitHub Token）。"""

    github_token_configured: bool
    github_token_hint: str | None = None
    model_name: str
    llm_base_url: str
    user_model_name: str | None = None
    user_llm_base_url: str | None = None
    server_model_name: str
    server_llm_base_url: str


class UserSettingsUpdate(BaseModel):
    """更新用户设置；空字符串表示清除 token。"""

    github_token: str | None = Field(
        default=None,
        max_length=500,
        description="GitHub Personal Access Token；传空字符串清除",
    )
    model_name: str | None = Field(default=None, max_length=200)
    llm_base_url: str | None = Field(default=None, max_length=500)
