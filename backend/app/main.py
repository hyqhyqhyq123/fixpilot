# backend/app/main.py
# 作用：FastAPI 应用入口，项目启动从这里开始
# FastAPI 是什么：Python 的现代 Web 框架，专门用来写 API 接口，
#                比 Flask 更快，内置数据校验和自动生成 API 文档

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import fix_tasks as fix_tasks_router
from app.api.routes import issue_analysis as issue_analysis_router
from app.api.routes import code_retrieval as code_retrieval_router
from app.api.routes import planner as planner_router
from app.api.routes import workflow as workflow_router
from app.core.config import get_settings
from app.db.session import init_db

# 配置日志格式：每条日志都带时间、级别和来源，方便排查问题
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。
    
    lifespan 是 FastAPI 推荐的启动/关闭钩子方式：
    - yield 之前的代码在应用启动时执行（比如连接数据库）
    - yield 之后的代码在应用关闭时执行（比如释放连接）
    """
    # 启动时执行
    logger.info(f"启动 {settings.app_name} v{settings.app_version}")
    logger.info(f"调试模式：{settings.debug}")
    logger.info(f"LLM 模型：{settings.model_name}")

    # 初始化数据库表（如果表不存在就自动创建）
    # 这样每次启动服务时，缺少的表会被自动补上，适合开发阶段
    await init_db()

    yield  # 应用正在运行

    # 关闭时执行
    logger.info(f"{settings.app_name} 已关闭")


# 创建 FastAPI 应用实例
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于 LangGraph 的多 Agent Coding 系统",
    # 只在 debug 模式下开放 API 文档（生产环境不需要暴露）
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# 配置跨域（CORS）
# 为什么需要：前端（Next.js，跑在 localhost:3000）要访问后端（localhost:8000），
#             浏览器默认会拦截不同端口的请求，CORS 配置告诉浏览器"这是允许的"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 健康检查接口 ──────────────────────────────────────────
# 作用：让你快速验证服务是否正常运行
# 访问 http://localhost:8000/health 看到 {"status": "ok"} 就说明服务跑起来了

# 注册任务路由
app.include_router(fix_tasks_router.router)
# 注册 Issue 分析路由
app.include_router(issue_analysis_router.router)
# 注册代码检索路由（阶段5）
app.include_router(code_retrieval_router.router)
# 注册 Planner 路由（阶段6）
app.include_router(planner_router.router)
# 注册 LangGraph Workflow 控制路由（Phase 2）
app.include_router(workflow_router.router)


@app.get("/health", tags=["system"])
async def health_check():
    """健康检查：返回服务状态和版本信息。"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "model": settings.model_name,
    }


@app.get("/", tags=["system"])
async def root():
    """根路径：提示用户访问 API 文档。"""
    return {
        "message": f"欢迎使用 {settings.app_name}",
        "docs": "/docs",
        "health": "/health",
    }
