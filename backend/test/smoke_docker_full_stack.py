# 全 Docker 栈冒烟：backend + celery_worker 容器均在运行

# 前置：docker compose up -d postgres redis backend celery_worker

#       宿主机勿占用 8000（停掉本地 uvicorn）

# 运行：cd backend && python test/smoke_docker_full_stack.py



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

        print("[OK] Docker backend health", r.json())



        r = await client.post(

            "/api/fix-tasks",

            json={

                "repo_url": "https://github.com/pallets/click",

                "issue_text": "全 Docker 栈联调：backend + celery_worker 容器",

            },

        )

        assert r.status_code == 201, r.text

        task_id = r.json()["id"]

        print(f"[OK] 创建任务 id={task_id}")



        r = await client.post(f"/api/fix-tasks/{task_id}/start")

        assert r.status_code == 200, r.text

        body = r.json()

        print("[OK] POST /start:", body["message"])

        assert body["task"]["status"] == "running"

        assert "后台" in body["message"]



        print(f"[..] 轮询（最多 {POLL_TIMEOUT_SEC}s）...")

        deadline = time.time() + POLL_TIMEOUT_SEC

        last_status = "running"

        while time.time() < deadline:

            await asyncio.sleep(POLL_INTERVAL_SEC)

            r = await client.get(f"/api/fix-tasks/{task_id}")

            assert r.status_code == 200

            status = r.json()["status"]

            node = r.json().get("current_node")

            if status != last_status:

                print(f"    {last_status} -> {status} (node={node})")

                last_status = status

            if status in ("waiting_approval", "success", "failed"):

                if status == "failed":

                    err = r.json().get("error_message", "")

                    raise AssertionError(f"任务失败: {err[:500]}")

                print(f"[OK] 全 Docker 栈联调成功，status={status}")

                return

        raise TimeoutError(f"超时：任务仍为 {last_status}")





if __name__ == "__main__":
    asyncio.run(main())
