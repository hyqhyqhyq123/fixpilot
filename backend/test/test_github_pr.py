# backend/test/test_github_pr.py
# FR-903 GitHub PR API 冒烟测试（mock git push + GitHub API）
# 运行：cd backend && python test/test_github_pr.py

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.approval import Approval, ApprovalStatus, ApprovalType
from app.models.edit_history import EditHistory
from app.models.fix_task import FixTask, TaskStatus
from app.models.user_settings import UserSettings

pytestmark = pytest.mark.anyio


async def _seed_pr_ready_task(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/octocat/Hello-World",
            issue_text="测试 GitHub PR 集成的 issue 描述足够长",
            base_branch="main",
            status=TaskStatus.SUCCESS,
            workspace_path=str(Path(__file__).parent / "_gh_pr_tmp"),
            final_report=(
                "## PR 草稿\n\n"
                "# fix: automated patch\n\n"
                "## Commit Message\n"
                "```text\n"
                "fix: use explicit commit message\n"
                "```\n\n"
                "Automated by FixPilot."
            ),
        )
        db.add(task)
        await db.flush()

        db.add(
            Approval(
                task_id=task.id,
                approval_type=ApprovalType.PLAN,
                status=ApprovalStatus.APPROVED,
                user_comment="approved",
            )
        )
        db.add(
            EditHistory(
                task_id=task.id,
                retry_index=0,
                file_path="foo.py",
                diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n",
            )
        )

        settings = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        row = settings.scalar_one_or_none()
        if row:
            row.github_token = "ghp_testtoken1234567890"
        else:
            db.add(UserSettings(user_id=user_id, github_token="ghp_testtoken1234567890"))

        await db.commit()
        return task.id


async def main() -> None:
    await init_db()
    email = f"ghpr_{uuid.uuid4().hex[:8]}@example.com"
    password = "testpass123"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/fix-tasks/99999/patch")
        assert r.status_code == 404
        print("[OK] GET /patch 404")

        r = await client.get("/api/fix-tasks/99999/report")
        assert r.status_code == 404
        print("[OK] GET /report 404")

        r = await client.post("/api/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201
        user_id = r.json()["id"]

        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        task_id = await _seed_pr_ready_task(user_id)

        r = await client.get(f"/api/fix-tasks/{task_id}/patch")
        assert r.status_code == 200, r.text
        assert "foo.py" in r.json()["patch"]
        print("[OK] GET /patch 返回 combined diff")

        r = await client.get(f"/api/fix-tasks/{task_id}/report")
        assert r.status_code == 200
        assert "PR 草稿" in (r.json()["report"] or "")
        print("[OK] GET /report")

        r = await client.get(f"/api/fix-tasks/{task_id}/github-pr")
        assert r.status_code == 200
        assert r.json()["pr_url"] is None
        print("[OK] GET /github-pr 未创建")

        r = await client.post(
            f"/api/fix-tasks/{task_id}/create-pr",
            headers=headers,
            json={"confirm": False},
        )
        assert r.status_code == 400
        print("[OK] create-pr confirm=false 400")

        push_mock = {
            "success": True,
            "owner": "octocat",
            "repo": "Hello-World",
            "branch_name": "fixpilot/task-x",
        }
        pr_mock = {
            "success": True,
            "pr_url": "https://github.com/octocat/Hello-World/pull/99",
            "pr_number": 99,
        }

        with (
            patch(
                "app.services.github_pr_service.commit_and_push_branch",
                return_value=push_mock,
            ) as commit_mock,
            patch(
                "app.services.github_pr_service.create_github_pull_request",
                new_callable=AsyncMock,
                return_value=pr_mock,
            ),
        ):
            r = await client.post(
                f"/api/fix-tasks/{task_id}/create-pr",
                headers=headers,
                json={"confirm": True},
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "pull/99" in data["pr_url"]
        assert data["branch_name"]
        assert (
            commit_mock.call_args.kwargs["commit_message"]
            == "fix: use explicit commit message"
        )
        print("[OK] POST /create-pr 成功")

        r = await client.get(f"/api/fix-tasks/{task_id}/github-pr")
        assert r.status_code == 200
        assert r.json()["pr_url"] == data["pr_url"]
        print("[OK] GET /github-pr 已创建")

        r = await client.post(
            f"/api/fix-tasks/{task_id}/create-pr",
            headers=headers,
            json={"confirm": True},
        )
        assert r.status_code == 400
        print("[OK] 重复 create-pr 400")

        r = await client.post(
            f"/api/fix-tasks/{task_id}/create-pr",
            json={"confirm": True},
        )
        assert r.status_code == 401
        print("[OK] create-pr 未登录 401")

    print("\nGitHub PR API 测试全部通过")


async def test_create_pr_api_flow_uses_commit_message() -> None:
    """pytest 入口：验证 create-pr API 使用显式 commit message。"""

    await main()


if __name__ == "__main__":
    asyncio.run(main())
