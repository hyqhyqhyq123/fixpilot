# backend/app/core/config.py
# 作用：集中管理所有配置项，从 .env 文件中读取
# 为什么这样做：所有配置放一处，修改方便，也避免在代码各处硬编码

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """
    项目全局配置类。
    
    pydantic-settings 会自动从 .env 文件读取同名变量，
    比如 .env 里有 APP_NAME=FixPilot，这里的 app_name 就自动等于 "FixPilot"。
    """

    # 基础配置
    app_name: str = "FixPilot"
    app_version: str = "0.1.0"
    debug: bool = False

    # 数据库
    database_url: str
    database_url_sync: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT 认证
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # LLM（DeepSeek 兼容 OpenAI 接口）
    openai_api_key: str
    openai_base_url: str = "https://api2.aigcbest.top/v1"
    model_name: str = "deepseek-v4-flash"

    # Workspace：每个任务 clone repo 的根目录
    workspace_base_path: str = "../workspaces"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        # 避免 pydantic 把 model_ 开头的字段误认为内部字段
        "protected_namespaces": ("settings_",),
    }


@lru_cache()
def get_settings() -> Settings:
    """
    获取全局配置单例。
    
    使用 @lru_cache 是因为：配置只需要从文件读一次，
    之后每次调用直接返回缓存，不重复读文件，性能更好。
    
    使用方式：
        from app.core.config import get_settings
        settings = get_settings()
        print(settings.app_name)
    """
    return Settings()
