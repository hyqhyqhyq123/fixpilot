# backend/test/test_celery_tasks.py
# Celery 任务函数单元测试（mock workflow_runner）
# 运行：cd backend && python test/test_celery_tasks.py

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.fix_task import TaskStatus
from app.tasks import workflow_tasks


def test_run_async_without_loop():
    async def coro():
        return 42

    assert workflow_tasks._run(coro()) == 42
    print("[OK] _run 无 event loop")


def test_start_workflow_task_success():
    fake_task = MagicMock()
    fake_task.status = TaskStatus.WAITING_APPROVAL

    with patch(
        "app.tasks.workflow_tasks._run_with_session",
        new_callable=AsyncMock,
        return_value=fake_task,
    ):
        result = workflow_tasks.start_workflow_task.run(1)
    assert result["task_id"] == 1
    assert result["status"] == "waiting_approval"
    print("[OK] start_workflow_task mock 成功")


async def main() -> None:
    test_run_async_without_loop()
    test_start_workflow_task_success()
    print("\nCelery 任务单元测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
