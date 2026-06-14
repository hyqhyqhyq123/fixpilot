# backend/test/test_workflow_checkpoint.py
# Purpose: verify database-backed workflow checkpoints.

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal, init_db
from app.graph.state import FixPilotState
from app.graph.workflow import get_workflow_app
from app.models.fix_task import FixTask, TaskStatus
from app.services import workflow_runner


async def _save_and_load_checkpoint():
    await init_db()

    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/octocat/Hello-World",
            issue_text="checkpoint save/load test",
            status=TaskStatus.WAITING_APPROVAL,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        state = FixPilotState(
            task_id=str(task.id),
            repo_url=task.repo_url,
            issue_text=task.issue_text,
            current_node="approval_node",
            status=TaskStatus.WAITING_APPROVAL.value,
            approval_status="pending",
            pending_approval_type="plan",
            plan={"files_to_modify": [{"path": "app.py"}]},
            retrieved_context=[],
            edit_history=[],
            test_results=[],
        )

        checkpoint = await workflow_runner._save_workflow_checkpoint(db, task.id, state)
        await db.commit()

        loaded = await workflow_runner._load_workflow_checkpoint(db, task.id)

    assert checkpoint.current_node == "approval_node"
    assert loaded is not None
    assert loaded["task_id"] == str(task.id)
    assert loaded["plan"]["files_to_modify"][0]["path"] == "app.py"


def test_save_and_load_checkpoint():
    asyncio.run(_save_and_load_checkpoint())


async def _approve_plan_uses_db_checkpoint_when_memory_is_missing():
    await init_db()
    get_workflow_app.cache_clear()

    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/octocat/Hello-World",
            issue_text="approve from checkpoint test",
            status=TaskStatus.WAITING_APPROVAL,
            current_agent="planner",
            current_node="approval_node",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        checkpoint_state = FixPilotState(
            task_id=str(task.id),
            user_id="anonymous",
            repo_url=task.repo_url,
            repo_path="workspaces/task_test/hello",
            base_branch="main",
            issue_text=task.issue_text,
            current_agent="planner",
            current_node="approval_node",
            status=TaskStatus.WAITING_APPROVAL.value,
            approval_status="pending",
            pending_approval_type="plan",
            plan={"files_to_modify": [{"path": "app.py"}]},
            allowed_files=["app.py"],
            retrieved_context=[],
            edit_history=[],
            test_results=[],
            retry_count=0,
            max_retries=2,
            final_status="running",
        )
        await workflow_runner._save_workflow_checkpoint(db, task.id, checkpoint_state)
        await db.commit()

        final_state = FixPilotState(
            **{
                **checkpoint_state,
                "approval_status": "approved",
                "status": TaskStatus.SUCCESS.value,
                "current_agent": "coordinator",
                "current_node": "final_report_node",
                "final_status": "success",
                "final_report": "checkpoint ok",
            }
        )

        with (
            patch(
                "app.services.workflow_runner._recover_missing_plan_state",
                new_callable=AsyncMock,
            ) as mock_recover,
            patch(
                "app.services.workflow_runner._resume_after_approval",
                new_callable=AsyncMock,
                return_value=(final_state, [], False),
            ) as mock_resume,
        ):
            result = await workflow_runner.approve_plan(db, task.id, "approve")

        mock_recover.assert_not_awaited()
        mock_resume.assert_awaited_once()
        resumed_state = mock_resume.await_args.args[1]
        assert resumed_state["plan"]["files_to_modify"][0]["path"] == "app.py"
        assert result.status == TaskStatus.SUCCESS
        assert result.final_report == "checkpoint ok"

    get_workflow_app.cache_clear()


def test_approve_plan_uses_db_checkpoint_when_memory_is_missing():
    asyncio.run(_approve_plan_uses_db_checkpoint_when_memory_is_missing())
