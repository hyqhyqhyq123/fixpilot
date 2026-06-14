# backend/test/test_task_artifacts_api.py
# 运行（需 PostgreSQL）：cd backend && python test/test_task_artifacts_api.py

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

from app.main import app


async def main() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200, r.text
        print("[OK] health", r.json())

        r = await client.get("/api/fix-tasks/99999/edit-history")
        assert r.status_code == 404
        print("[OK] edit-history 404 for missing task")

        r = await client.get("/api/fix-tasks/99999/test-runs")
        assert r.status_code == 404
        print("[OK] test-runs 404")

        r = await client.get("/api/fix-tasks/99999/approvals")
        assert r.status_code == 404
        print("[OK] approvals 404")

        r = await client.get("/api/fix-tasks/99999/tool-calls")
        assert r.status_code == 404
        print("[OK] tool-calls 404")

    print("\n任务 artifacts API 冒烟通过")


if __name__ == "__main__":
    asyncio.run(main())
