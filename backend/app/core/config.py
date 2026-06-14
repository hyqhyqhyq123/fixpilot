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

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    use_celery: bool = False
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_task_always_eager: bool = False

    @property
    def resolved_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    # JWT 认证
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_uri: str = "http://localhost:3000/login"

    # LLM（DeepSeek 兼容 OpenAI 接口）
    openai_api_key: str
    openai_base_url: str = "https://api2.aigcbest.top/v1"
    model_name: str = "deepseek-v4-flash"

    # Workspace：每个任务 clone repo 的根目录
    workspace_base_path: str = "../workspaces"

    # 可观测性
    # Prometheus 是常见监控系统，/metrics 会暴露请求量、状态码和耗时指标。
    enable_prometheus: bool = True
    # OpenTelemetry 是标准化链路追踪协议；默认关闭，避免本地没部署 collector 时产生噪声。
    enable_opentelemetry: bool = False
    otel_service_name: str = "fixpilot-api"
    otel_exporter_otlp_endpoint: str = ""

    # 向量持久化
    # local 表示继续用当前本地检索；pgvector 表示把 embedding 存到 PostgreSQL。
    vector_store_provider: str = "local"
    pgvector_table_name: str = "code_embeddings"
    pgvector_embedding_dim: int = 1536

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
