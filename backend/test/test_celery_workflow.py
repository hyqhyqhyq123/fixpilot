# backend/test/test_celery_workflow.py
# Celery Workflow 队列冒烟（task_always_eager 同步执行）
# 运行：cd backend && python test/test_celery_workflow.py

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["USE_CELERY"] = "true"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"

from app.core.config import get_settings

get_settings.cache_clear()

from httpx import ASGITransport, AsyncClient

from app.db.session import init_db
from app.main import app
from app.services.workflow_queue import celery_enabled


async def main() -> None:
    assert celery_enabled() is True
    print("[OK] USE_CELERY 已启用")

    await init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/fix-tasks",
            json={
                "repo_url": "https://github.com/pallets/click",
                "issue_text": "Celery 队列测试：验证后台启动 API 返回 running",
            },
        )
        assert r.status_code == 201, r.text
        task_id = r.json()["id"]

        with patch("app.services.workflow_queue.dispatch_start_workflow") as mock_dispatch:
            r = await client.post(f"/api/fix-tasks/{task_id}/start")
            assert r.status_code == 200, r.text
            data = r.json()
            assert "后台" in data["message"]
            assert data["task"]["status"] == "running"
            mock_dispatch.assert_called_once_with(task_id)

            r = await client.post(f"/api/fix-tasks/{task_id}/start")
            assert r.status_code == 400, r.text
            assert "pending / failed" in r.text
            mock_dispatch.assert_called_once_with(task_id)
        print("[OK] POST /start Celery 模式入队并返回 running")

    print("\nCelery Workflow 测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
