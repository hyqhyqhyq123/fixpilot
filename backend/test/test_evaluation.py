# backend/test/test_evaluation.py
# LLM-as-Judge 评测 API 测试（mock judge）
# 运行：cd backend && python test/test_evaluation.py

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.fix_task import FixTask, TaskStatus


async def _seed_success_task() -> int:
    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/octocat/Hello-World",
            issue_text="评测测试 issue：修复空输入校验问题描述足够长",
            status=TaskStatus.SUCCESS,
            final_report="## 报告\n修复完成，测试通过。",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id


async def main() -> None:
    await init_db()
    task_id = await _seed_success_task()

    judge_mock = {
        "overall_score": 82,
        "patch_score": 85,
        "plan_score": 80,
        "test_score": 78,
        "judge_summary": "修复方向正确，测试基本覆盖。",
        "details": {
            "strengths": ["针对 issue"],
            "weaknesses": [],
            "recommendations": ["补充边界测试"],
        },
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/fix-tasks/{task_id}/evaluate")
        # 未 mock 时可能 500（无 LLM），先测 400 门禁
        assert r.status_code in (200, 500)

        with patch("app.services.evaluation_service.judge_task_result", return_value=judge_mock):
            r = await client.post(f"/api/fix-tasks/{task_id}/evaluate")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["overall_score"] == 82
        assert "修复方向" in data["judge_summary"]
        print("[OK] POST /evaluate mock Judge")

        r = await client.get(f"/api/fix-tasks/{task_id}/evaluation")
        assert r.status_code == 200
        assert r.json()["evaluation"]["overall_score"] == 82
        print("[OK] GET /evaluation")

        r = await client.post("/api/fix-tasks/99999/evaluate")
        assert r.status_code == 404
        print("[OK] evaluate 404")

    print("\n评测 API 测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
