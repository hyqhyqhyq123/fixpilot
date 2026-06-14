# 本地 Celery 联调冒烟：创建任务 → 后台 start → 轮询状态
# 运行：cd backend && python test/smoke_celery_local.py

import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

API = "http://127.0.0.1:8000"
POLL_TIMEOUT_SEC = 300
POLL_INTERVAL_SEC = 5


async def main() -> None:
    async with httpx.AsyncClient(base_url=API, timeout=30.0) as client:
        r = await client.get("/health")
        assert r.status_code == 200, r.text
        print("[OK] API health", r.json())

        r = await client.post(
            "/api/fix-tasks",
            json={
                "repo_url": "https://github.com/pallets/click",
                "issue_text": "Celery 本地联调：验证 Worker 能消费 start_workflow 任务",
            },
        )
        assert r.status_code == 201, r.text
        task_id = r.json()["id"]
        print(f"[OK] 创建任务 id={task_id}")

        r = await client.post(f"/api/fix-tasks/{task_id}/start")
        assert r.status_code == 200, r.text
        body = r.json()
        print("[OK] POST /start 响应:", body["message"])
        assert body["task"]["status"] == "running", body
        assert "后台" in body["message"], "请确认 backend/.env 中 USE_CELERY=true 且已重启 API"

        print(f"[..] 轮询任务状态（最多 {POLL_TIMEOUT_SEC}s，Worker 在跑完整 Workflow）...")
        deadline = time.time() + POLL_TIMEOUT_SEC
        last_status = "running"
        while time.time() < deadline:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            r = await client.get(f"/api/fix-tasks/{task_id}")
            assert r.status_code == 200
            status = r.json()["status"]
            node = r.json().get("current_node")
            if status != last_status:
                print(f"    状态变化: {last_status} -> {status} (node={node})")
                last_status = status
            if status in ("waiting_approval", "success", "failed"):
                print(f"[OK] Worker 完成预处理，最终 status={status}")
                return
        raise TimeoutError(f"超时：任务仍为 {last_status}，请查看 Celery Worker 终端日志")


if __name__ == "__main__":
    asyncio.run(main())
