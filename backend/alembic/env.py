"""Alembic 运行环境。

Alembic 是数据库迁移工具：它让表结构变化有版本记录，避免线上靠
`create_all` 或手动 SQL 碰运气。
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# 导入模型是为了让 SQLAlchemy 把表注册到 Base.metadata。
import app.models.agent_step  # noqa: F401,E402
import app.models.approval  # noqa: F401,E402
import app.models.edit_history  # noqa: F401,E402
import app.models.fix_task  # noqa: F401,E402
import app.models.retrieved_context  # noqa: F401,E402
import app.models.task_evaluation  # noqa: F401,E402
import app.models.task_github_pr  # noqa: F401,E402
import app.models.task_status_transition  # noqa: F401,E402
import app.models.test_run  # noqa: F401,E402
import app.models.tool_call  # noqa: F401,E402
import app.models.user  # noqa: F401,E402
import app.models.user_settings  # noqa: F401,E402
import app.models.workflow_checkpoint  # noqa: F401,E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """优先使用测试/CI 覆盖值，否则读取项目配置里的同步数据库 URL。"""
    return os.getenv("FIXPILOT_ALEMBIC_DATABASE_URL") or get_settings().database_url_sync


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
