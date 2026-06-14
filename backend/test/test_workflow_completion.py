# backend/test/test_workflow_completion.py
# Workflow 补齐项：cancel / tool-calls / approve-diff 门禁
# 运行：cd backend && python test/test_workflow_completion.py

import asyncio
import shutil
import sys
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.graph import nodes
from app.graph.state import FixPilotState
from app.models.agent_step import AgentStep, StepStatus
from app.models.approval import Approval, ApprovalStatus, ApprovalType
from app.models.fix_task import FixTask, TaskStatus
from app.models.edit_history import EditHistory
from app.models.tool_call import PermissionLevel, ToolCall
from app.services import workflow_runner
from app.services.workflow_runner import NODE_TOOL_MAP, _persist_tool_call_for_step
from app.graph.workflow import get_workflow_app


ROLLBACK_TMP_ROOT = Path(__file__).parent / "_tmp_rollback_retry"


def _new_rollback_repo() -> Path:
    repo = ROLLBACK_TMP_ROOT / uuid4().hex
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    return repo


def _cleanup_rollback_repo(repo: Path) -> None:
    shutil.rmtree(repo, ignore_errors=True)
    try:
        ROLLBACK_TMP_ROOT.rmdir()
    except OSError:
        pass


def test_node_tool_map_coverage():
    expected = {
        "clone_repo_node",
        "retrieve_context_node",
        "edit_code_node",
        "run_tests_node",
    }
    assert expected <= set(NODE_TOOL_MAP.keys())
    print("[OK] NODE_TOOL_MAP 覆盖关键工具节点")


def test_review_sets_diff_review_pending():
    state = FixPilotState(
        issue_text="x",
        allowed_files=["a.py"],
        edit_history=[{"file_path": "b.py"}],
        current_diff="+x",
    )
    with patch("app.graph.nodes.review_diff") as mock:
        from app.schemas.review import ReviewResult

        mock.return_value = ReviewResult(
            risk_level="high",
            approval_required=True,
            summary="high",
        )
        updates = nodes.review_diff_node(state)
    assert updates["pending_approval_type"] == "diff_review"
    print("[OK] 高风险审查设置 diff_review")


async def _rollback_to_retry_step_restores_workspace():
    await init_db()
    repo = _new_rollback_repo()
    try:
        app_file = repo / "src" / "app.py"
        new_test_file = repo / "tests" / "test_app.py"
        app_file.write_text("v2\n", encoding="utf-8")
        new_test_file.write_text("test\n", encoding="utf-8")

        async with AsyncSessionLocal() as db:
            task = FixTask(
                repo_url="https://github.com/example/demo",
                issue_text="rollback retry step test",
                status=TaskStatus.SUCCESS,
                workspace_path=str(repo),
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)

            db.add_all(
                [
                    EditHistory(
                        task_id=task.id,
                        retry_index=0,
                        file_path="src/app.py",
                        before_content="v0\n",
                        after_content="v1\n",
                        diff="-v0\n+v1\n",
                    ),
                    EditHistory(
                        task_id=task.id,
                        retry_index=1,
                        file_path="src/app.py",
                        before_content="v1\n",
                        after_content="v2\n",
                        diff="-v1\n+v2\n",
                    ),
                    EditHistory(
                        task_id=task.id,
                        retry_index=1,
                        file_path="tests/test_app.py",
                        before_content=None,
                        after_content="test\n",
                        diff="+test\n",
                    ),
                ]
            )
            await db.commit()

            result = await workflow_runner.rollback_to_retry_step(db, task.id, 0)

            assert result.status == TaskStatus.FAILED
            assert result.current_node == "rollback_retry_step"
            assert app_file.read_text(encoding="utf-8") == "v1\n"
            assert not new_test_file.exists()

            tool_result = await db.execute(
                select(ToolCall).where(
                    ToolCall.task_id == task.id,
                    ToolCall.tool_name == "rollback_retry_tool",
                )
            )
            tool_call = tool_result.scalar_one()
            assert tool_call.permission_level == PermissionLevel.HIGH
    finally:
        _cleanup_rollback_repo(repo)

    print("[OK] rollback_to_retry_step 可恢复 workspace 并写入 high 权限审计")


def test_rollback_to_retry_step_restores_workspace():
    asyncio.run(_rollback_to_retry_step_restores_workspace())


async def _start_workflow_rejects_running_without_worker_flag():
    await init_db()
    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/pallets/click",
            issue_text="running 防重复启动测试任务描述足够长",
            status=TaskStatus.RUNNING,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        try:
            await workflow_runner.start_workflow(db, task.id)
        except ValueError as exc:
            assert "仅 pending / failed 可启动" in str(exc)
        else:
            raise AssertionError("running 任务不应被普通 start_workflow 重复启动")
    print("[OK] running 任务普通启动会被拒绝，避免重复步骤")


def test_start_workflow_rejects_running_without_worker_flag():
    asyncio.run(_start_workflow_rejects_running_without_worker_flag())


async def _approve_plan_recovers_missing_memory_state():
    await init_db()
    get_workflow_app.cache_clear()

    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/pallets/click",
            issue_text="审批恢复测试：数据库等待审批，但内存 workflow state 已丢失",
            status=TaskStatus.WAITING_APPROVAL,
            current_agent="planner",
            current_node="approval_node",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        recovered_state = FixPilotState(
            task_id=str(task.id),
            user_id="anonymous",
            repo_url=task.repo_url,
            repo_path="workspaces/task_test/click",
            base_branch="main",
            issue_text=task.issue_text,
            current_agent="planner",
            current_node="approval_node",
            status=TaskStatus.WAITING_APPROVAL.value,
            approval_status="pending",
            pending_approval_type="plan",
            plan={"files_to_modify": [{"path": "src/click/core.py"}]},
            allowed_files=["src/click/core.py"],
            retrieved_context=[],
            edit_history=[],
            test_results=[],
            retry_count=0,
            max_retries=2,
            final_status="running",
        )
        final_state = FixPilotState(
            **{
                **recovered_state,
                "approval_status": "approved",
                "status": TaskStatus.SUCCESS.value,
                "current_agent": "coordinator",
                "current_node": "final_report_node",
                "final_status": "success",
                "final_report": "ok",
            }
        )

        with (
            patch(
                "app.services.workflow_runner._run_until_approval",
                new_callable=AsyncMock,
                return_value=(recovered_state, []),
            ) as mock_recover,
            patch(
                "app.services.workflow_runner._resume_after_approval",
                new_callable=AsyncMock,
                return_value=(final_state, [], False),
            ) as mock_resume,
        ):
            result = await workflow_runner.approve_plan(db, task.id, "test approve")

        mock_recover.assert_awaited_once()
        mock_resume.assert_awaited_once()
        assert result.status == TaskStatus.SUCCESS
        assert result.final_report == "ok"

    get_workflow_app.cache_clear()
    print("[OK] 缺失内存 workflow state 时 approve_plan 可自动恢复后继续")


def test_approve_plan_recovers_missing_memory_state():
    asyncio.run(_approve_plan_recovers_missing_memory_state())


async def _reject_plan_records_feedback_and_replans():
    await init_db()
    get_workflow_app.cache_clear()

    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/pallets/click",
            issue_text="计划修订测试：用户拒绝初版计划并补充要求",
            status=TaskStatus.WAITING_APPROVAL,
            current_agent="planner",
            current_node="approval_node",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        feedback = "不要修改 API 行为，只补充错误处理"
        recovered_state = FixPilotState(
            task_id=str(task.id),
            user_id="anonymous",
            repo_url=task.repo_url,
            repo_path="workspaces/task_test/click",
            base_branch="main",
            issue_text=task.issue_text,
            current_agent="planner",
            current_node="approval_node",
            status=TaskStatus.WAITING_APPROVAL.value,
            approval_status="pending",
            pending_approval_type="plan",
            plan={"files_to_modify": [{"path": "src/click/core.py"}]},
            allowed_files=["src/click/core.py"],
            retrieved_context=[],
            edit_history=[],
            test_results=[],
            retry_count=0,
            max_retries=2,
            final_status="running",
        )
        replanned_state = FixPilotState(
            **{
                **recovered_state,
                "approval_status": "rejected",
                "user_feedback": feedback,
                "status": TaskStatus.WAITING_APPROVAL.value,
                "current_agent": "planner",
                "current_node": "approval_node",
                "plan": {
                    "problem_summary": "根据用户补充要求重新规划",
                    "files_to_modify": [{"path": "src/click/core.py"}],
                },
            }
        )
        replan_record = {
            "node_name": "planning_node",
            "agent_name": "planner",
            "status": StepStatus.SUCCESS,
            "input_summary": {"task_id": str(task.id)},
            "output_summary": {
                "problem_summary": "根据用户补充要求重新规划",
                "related_files": ["src/click/core.py"],
            },
        }

        with (
            patch(
                "app.services.workflow_runner._recover_missing_plan_state",
                new_callable=AsyncMock,
                return_value=recovered_state,
            ) as mock_recover,
            patch(
                "app.services.workflow_runner._resume_after_approval",
                new_callable=AsyncMock,
                return_value=(replanned_state, [replan_record], True),
            ) as mock_resume,
        ):
            result = await workflow_runner.reject_plan(db, task.id, feedback)

        mock_recover.assert_awaited_once()
        mock_resume.assert_awaited_once()
        resumed_state = mock_resume.await_args.args[1]
        assert resumed_state["approval_status"] == "rejected"
        assert resumed_state["user_feedback"] == feedback
        assert result.status == TaskStatus.WAITING_APPROVAL
        assert result.current_node == "approval_node"

        approval_result = await db.execute(
            select(Approval).where(
                Approval.task_id == task.id,
                Approval.approval_type == ApprovalType.PLAN,
                Approval.status == ApprovalStatus.REJECTED,
            )
        )
        approval = approval_result.scalar_one()
        assert approval.user_comment == feedback

        step_result = await db.execute(
            select(AgentStep).where(
                AgentStep.task_id == task.id,
                AgentStep.node_name == "planning_node",
            )
        )
        assert step_result.scalar_one().status == StepStatus.SUCCESS

    get_workflow_app.cache_clear()
    print("[OK] reject_plan 会记录用户反馈，并回到 Planner 重新规划")


def test_reject_plan_records_feedback_and_replans():
    asyncio.run(_reject_plan_records_feedback_and_replans())


async def _retry_failed_task_recovers_and_resumes():
    await init_db()
    get_workflow_app.cache_clear()

    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/pallets/click",
            issue_text="失败后手动重试测试",
            status=TaskStatus.FAILED,
            current_agent="coordinator",
            current_node="final_report_node",
            error_message="Coder 生成失败：Connection error.",
            retry_count=0,
            max_retries=2,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        db.add(
            Approval(
                task_id=task.id,
                approval_type=ApprovalType.PLAN,
                status=ApprovalStatus.APPROVED,
                user_comment="approved",
            )
        )
        await db.commit()

        recovered_state = FixPilotState(
            task_id=str(task.id),
            user_id="anonymous",
            repo_url=task.repo_url,
            repo_path="workspaces/task_test/click",
            base_branch="main",
            issue_text=task.issue_text,
            current_agent="planner",
            current_node="approval_node",
            status=TaskStatus.WAITING_APPROVAL.value,
            approval_status="pending",
            pending_approval_type="plan",
            plan={"files_to_modify": [{"path": "src/click/core.py"}]},
            allowed_files=["src/click/core.py"],
            retrieved_context=[],
            edit_history=[],
            test_results=[],
            retry_count=0,
            max_retries=2,
            final_status="running",
        )
        final_state = FixPilotState(
            **{
                **recovered_state,
                "approval_status": "approved",
                "status": TaskStatus.SUCCESS.value,
                "current_agent": "coordinator",
                "current_node": "final_report_node",
                "final_status": "success",
                "final_report": "retry ok",
                "retry_count": 1,
            }
        )

        with (
            patch(
                "app.services.workflow_runner._run_until_approval",
                new_callable=AsyncMock,
                return_value=(recovered_state, []),
            ) as mock_recover,
            patch(
                "app.services.workflow_runner._resume_after_approval",
                new_callable=AsyncMock,
                return_value=(final_state, [], False),
            ) as mock_resume,
        ):
            result = await workflow_runner.retry_failed_workflow(
                db,
                task.id,
                "manual retry",
            )

        mock_recover.assert_awaited_once()
        mock_resume.assert_awaited_once()
        resumed_state = mock_resume.await_args.args[1]
        assert resumed_state["retry_count"] == 1
        assert result.status == TaskStatus.SUCCESS
        assert result.retry_count == 1
        assert result.final_report == "retry ok"

    get_workflow_app.cache_clear()
    print("[OK] failed 任务可手动 retry，并从已批准计划继续执行")


def test_retry_failed_task_recovers_and_resumes():
    asyncio.run(_retry_failed_task_recovers_and_resumes())


async def _start_workflow_persists_retrieved_contexts():
    await init_db()
    get_workflow_app.cache_clear()

    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/pallets/click",
            issue_text="检索结果持久化测试任务描述足够长",
            status=TaskStatus.PENDING,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        retrieved_context = [
            {
                "file_path": "src/click/parser.py",
                "line_start": 10,
                "line_end": 20,
                "snippet": "def parse_args(args):\n    return args",
                "score": 0.72,
                "method": "semantic",
            },
            {
                "file_path": "src/click/core.py",
                "line_start": 30,
                "line_end": 40,
                "snippet": "class Command:\n    pass",
                "score": 0.91,
                "method": "semantic",
            },
        ]
        recovered_state = FixPilotState(
            task_id=str(task.id),
            user_id="anonymous",
            repo_url=task.repo_url,
            repo_path="workspaces/task_test/click",
            base_branch="main",
            issue_text=task.issue_text,
            current_agent="planner",
            current_node="approval_node",
            status=TaskStatus.WAITING_APPROVAL.value,
            approval_status="pending",
            pending_approval_type="plan",
            plan={"files_to_modify": [{"path": "src/click/core.py"}]},
            allowed_files=["src/click/core.py"],
            retrieved_context=retrieved_context,
            edit_history=[],
            test_results=[],
            retry_count=0,
            max_retries=2,
            final_status="running",
        )
        step_records = [
            {
                "node_name": "retrieve_context_node",
                "agent_name": "code_retriever",
                "status": StepStatus.SUCCESS,
                "input_summary": {"task_id": str(task.id)},
                "output_summary": {
                    "retrieved_count": 2,
                    "related_files": ["src/click/parser.py", "src/click/core.py"],
                },
            }
        ]

        with patch(
            "app.services.workflow_runner._run_until_approval",
            new_callable=AsyncMock,
            return_value=(recovered_state, step_records),
        ):
            result = await workflow_runner.start_workflow(db, task.id)

        assert result.status == TaskStatus.WAITING_APPROVAL
        contexts = await workflow_runner.list_retrieved_contexts(db, task.id)
        assert [item.file_path for item in contexts] == [
            "src/click/core.py",
            "src/click/parser.py",
        ]
        assert contexts[0].score == 0.91

    get_workflow_app.cache_clear()
    print("[OK] start_workflow 会把 retrieved_context 写入 retrieved_contexts 表")


def test_start_workflow_persists_retrieved_contexts():
    asyncio.run(_start_workflow_persists_retrieved_contexts())


async def _api_tests():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/fix-tasks",
            json={
                "repo_url": "https://github.com/pallets/click",
                "issue_text": "测试取消流程的任务描述足够长",
            },
        )
        assert r.status_code == 201, r.text
        task_id = r.json()["id"]
        print(f"[OK] 创建任务 id={task_id}")

        r = await client.post(f"/api/fix-tasks/{task_id}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["task"]["status"] == "cancelled"
        print("[OK] POST /cancel 取消 pending 任务")

        r = await client.get(f"/api/fix-tasks/{task_id}/tool-calls")
        assert r.status_code == 200
        assert r.json()["total"] == 0
        print("[OK] GET /tool-calls")

        r = await client.get(f"/api/fix-tasks/{task_id}/retrieved-contexts")
        assert r.status_code == 200
        assert r.json()["total"] == 0
        print("[OK] GET /retrieved-contexts")

        r = await client.post(
            f"/api/fix-tasks/{task_id}/approve-diff",
            json={"comment": "x"},
        )
        assert r.status_code == 400
        print("[OK] approve-diff 非 diff 阶段返回 400")

        r = await client.post(
            f"/api/fix-tasks/{task_id}/rollback-retry",
            json={"retry_index": 0},
        )
        assert r.status_code == 400
        print("[OK] rollback-retry 无 edit_history 返回 400")

        async with AsyncSessionLocal() as db:
            failed_task = FixTask(
                repo_url="https://github.com/pallets/click",
                issue_text="测试失败任务 retry API 的任务描述足够长",
                status=TaskStatus.FAILED,
                error_message="Coder 生成失败：Connection error.",
            )
            db.add(failed_task)
            await db.commit()
            await db.refresh(failed_task)
            failed_task_id = failed_task.id

        with patch(
            "app.api.routes.workflow.workflow_runner.retry_failed_workflow",
            new_callable=AsyncMock,
            return_value=failed_task,
        ) as mock_retry, patch(
            "app.api.routes.workflow.workflow_queue.celery_enabled",
            return_value=False,
        ):
            r = await client.post(
                f"/api/fix-tasks/{failed_task_id}/retry",
                json={"comment": "api retry"},
            )
        assert r.status_code == 200, r.text
        mock_retry.assert_awaited_once()
        assert r.json()["message"] == "失败任务已重试"
        print("[OK] POST /retry 调用失败任务重试")


def test_api_routes():
    asyncio.run(_api_tests())


async def main():
    test_node_tool_map_coverage()
    test_review_sets_diff_review_pending()
    await _start_workflow_rejects_running_without_worker_flag()
    await _approve_plan_recovers_missing_memory_state()
    await _reject_plan_records_feedback_and_replans()
    await _retry_failed_task_recovers_and_resumes()
    await _start_workflow_persists_retrieved_contexts()
    await _api_tests()
    print("\nWorkflow 补齐测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
