"""Pytest 公共配置。

这些默认值只在测试进程里生效，目的是让没有 `.env` 的新同学也能先跑单测。
真实开发和部署仍然应该通过 `.env` 或 Docker Compose 提供正式配置。
"""

import inspect
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./backend/test/test.db")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///./backend/test/test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")


@pytest.fixture
def anyio_backend() -> str:
    """让 async 单测只跑 asyncio，避免 anyio 同时尝试 trio。"""

    return "asyncio"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """自动给 async test 函数加 anyio 标记。

    项目里有不少初学阶段写的 `async def test_*`，没有显式加 marker。
    这里统一补上，让 pytest 能真正 await 它们。
    """

    for item in items:
        test_func = getattr(item, "obj", None)
        if test_func and inspect.iscoroutinefunction(test_func):
            item.add_marker(pytest.mark.anyio)
