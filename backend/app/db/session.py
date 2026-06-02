# backend/app/db/session.py
# 作用：创建数据库连接引擎，并提供获取数据库会话（Session）的工具函数
#
# 核心概念：
# - Engine（引擎）：负责和数据库建立物理连接，一个应用只需要一个 engine
# - Session（会话）：每次数据库操作（查询、插入、更新）都需要一个 session
#                   类比：engine 是水管，session 是水龙头，每次用水开一次水龙头
# - 为什么用 async：FastAPI 是异步框架，数据库操作也要异步，否则会阻塞整个服务

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 创建异步数据库引擎
# echo=True 时会把每条 SQL 打印到日志，开发调试很有用，生产环境建议关闭
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,       # debug 模式打印 SQL，方便排查问题
    pool_pre_ping=True,        # 每次使用连接前先 ping 一下，自动重连断开的连接
    pool_size=10,              # 连接池大小：同时最多维持 10 个数据库连接
    max_overflow=20,           # 超出 pool_size 后最多再开 20 个临时连接
    # asyncpg 默认尝试 SSL 连接，本地 Docker 没有配置 SSL 会失败
    # ssl=False 直接告诉 asyncpg 不要用 SSL，避免多余的失败重试
    connect_args={"ssl": False},
)

# 创建 Session 工厂
# 每次调用 AsyncSessionLocal() 就能得到一个新的数据库 session
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,    # commit 后不让 SQLAlchemy 自动过期对象，方便继续读取
)


async def get_db() -> AsyncSession:
    """
    FastAPI 依赖注入函数：提供数据库 session。

    用法示例：
        @router.get("/tasks")
        async def list_tasks(db: AsyncSession = Depends(get_db)):
            ...

    为什么用 yield：
    - yield 前：创建 session，注入到路由函数
    - yield 后（finally 里）：无论请求成功还是报错，都关闭 session，释放连接
    这样能保证连接不会泄漏
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()    # 请求成功时提交事务
        except Exception:
            await session.rollback()  # 出错时回滚，保证数据一致性
            raise


async def init_db() -> None:
    """
    初始化数据库：创建所有表（如果不存在的话）。

    为什么在这里 import models：
    - 要让 SQLAlchemy 知道有哪些表，必须先 import 对应的 model 类
    - import 之后这些类就注册到了 Base.metadata 里
    - create_all 会扫描 Base.metadata 里的所有表定义并创建
    """
    # 延迟 import，避免循环导入
    # noqa: F401 — import 是为了注册模型到 Base.metadata，不是为了直接使用
    from app.db.base import Base
    import app.models.fix_task           # noqa: F401
    import app.models.agent_step         # noqa: F401
    import app.models.tool_call          # noqa: F401
    import app.models.retrieved_context  # noqa: F401
    import app.models.edit_history       # noqa: F401
    import app.models.test_run           # noqa: F401
    import app.models.approval           # noqa: F401

    async with engine.begin() as conn:
        # checkfirst=True 表示"表不存在才创建"，不会删除已有数据
        await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库表初始化完成（共 7 张表）")
