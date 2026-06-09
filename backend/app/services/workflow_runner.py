# backend/app/services/workflow_runner.py
# 作用：编排 LangGraph 执行，并把 State / agent_steps 持久化到数据库

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph import nodes
from app.graph.state import FixPilotState
from app.graph.workflow import get_workflow_app
from app.models.agent_step import AgentStep, StepStatus
from app.models.approval import Approval, ApprovalStatus, ApprovalType
from app.models.edit_history import EditHistory
from app.models.fix_task import FixTask, TaskStatus
from app.models.retrieved_context import RetrievedContext
from app.models.test_run import TestRun

logger = logging.getLogger(__name__)

NODE_AGENT_MAP: dict[str, str] = {
    "intake_node": "coordinator",
    "clone_repo_node": "repository_analyst",
    "analyze_repo_node": "repository_analyst",
    "classify_issue_node": "issue_analyst",
    "retrieve_context_node": "code_retriever",
    "planning_node": "planner",
    "approval_node": "coordinator",
    "edit_code_node": "coder",
    "run_tests_node": "tester",
    "final_report_node": "coordinator",
}

POST_APPROVAL_SEQUENCE: list[tuple[str, Any]] = [
    ("edit_code_node", nodes.edit_code_node),
    ("run_tests_node", nodes.run_tests_node),
    ("final_report_node", nodes.final_report_node),
]

PRE_APPROVAL_SEQUENCE: list[tuple[str, Any]] = [
    ("intake_node", nodes.intake_node),
    ("clone_repo_node", nodes.clone_repo_node),
    ("analyze_repo_node", nodes.analyze_repo_node),
    ("classify_issue_node", nodes.classify_issue_node),
    ("retrieve_context_node", nodes.retrieve_context_node),
    ("planning_node", nodes.planning_node),
]


def _thread_config(task_id: int) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"task_{task_id}"}}


def _build_initial_state(task: FixTask) -> FixPilotState:
    return FixPilotState(
        task_id=str(task.id),
        user_id="anonymous",
        repo_url=task.repo_url,
        repo_path=task.workspace_path,
        base_branch=task.base_branch,
        issue_text=task.issue_text,
        issue_url=task.issue_url,
        current_agent="coordinator",
        current_node="intake_node",
        status=TaskStatus.RUNNING.value,
        approval_status="pending",
        retrieved_context=[],
        allowed_files=[],
        edit_history=[],
        test_results=[],
        retry_count=task.retry_count,
        max_retries=task.max_retries,
        test_command=task.test_command,
        lint_command=task.lint_command,
        final_status="running",
    )


def _summarize_node_io(
    node_name: str,
    state: FixPilotState,
    updates: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    input_summary = {
        "task_id": state.get("task_id"),
        "repo_url": state.get("repo_url"),
        "node": node_name,
    }
    output_summary: dict[str, Any] = {"updated_fields": list(updates.keys())}

    if node_name == "classify_issue_node" and updates.get("issue_analysis"):
        analysis = updates["issue_analysis"]
        output_summary.update(
            {
                "issue_type": analysis.get("issue_type"),
                "summary": analysis.get("summary"),
                "risk_level": analysis.get("risk_level"),
            }
        )

    if node_name == "retrieve_context_node":
        output_summary["retrieved_count"] = len(updates.get("retrieved_context") or [])

    if node_name == "planning_node" and updates.get("plan"):
        plan = updates["plan"]
        output_summary.update(
            {
                "problem_summary": plan.get("problem_summary"),
                "files_to_modify": len(plan.get("files_to_modify") or []),
                "files_to_add": len(plan.get("files_to_add") or []),
            }
        )

    if node_name == "edit_code_node":
        output_summary["edited_files"] = len(updates.get("edit_history") or [])

    if node_name == "run_tests_node" and updates.get("test_results"):
        last = updates["test_results"][-1]
        output_summary["test_passed"] = last.get("passed")
        output_summary["test_command"] = last.get("command")

    if updates.get("error_message"):
        output_summary["error_message"] = updates["error_message"]

    return input_summary, output_summary


async def _run_node(
    node_name: str,
    node_fn: Any,
    state: FixPilotState,
) -> tuple[FixPilotState, dict[str, Any]]:
    started_at = datetime.now(timezone.utc)
    updates = await asyncio.to_thread(node_fn, state)
    state = {**state, **updates}

    input_summary, output_summary = _summarize_node_io(node_name, state, updates)
    record = {
        "node_name": node_name,
        "agent_name": NODE_AGENT_MAP[node_name],
        "status": StepStatus.FAILED if updates.get("error_message") else StepStatus.SUCCESS,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "error_message": updates.get("error_message"),
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc),
    }
    return state, record


async def _run_until_approval(task_id: int, initial_state: FixPilotState) -> tuple[FixPilotState, list[dict[str, Any]]]:
    """执行 intake → planning，在审批前暂停。"""
    app = get_workflow_app()
    config = _thread_config(task_id)
    app.update_state(config, initial_state)

    state = dict(initial_state)
    step_records: list[dict[str, Any]] = []

    for node_name, node_fn in PRE_APPROVAL_SEQUENCE:
        state, record = await _run_node(node_name, node_fn, state)
        step_records.append(record)
        app.update_state(config, state)

        if state.get("error_message"):
            state, report_record = await _run_node(
                "final_report_node", nodes.final_report_node, state
            )
            step_records.append(report_record)
            app.update_state(config, state)
            return state, step_records

    state["status"] = TaskStatus.WAITING_APPROVAL.value
    state["current_node"] = "approval_node"
    app.update_state(config, state)
    return state, step_records


async def _resume_after_approval(
    task_id: int,
    state: FixPilotState,
) -> tuple[FixPilotState, list[dict[str, Any]], bool]:
    """审批后恢复：approval → (rejected 时 replan) → final_report。"""
    app = get_workflow_app()
    config = _thread_config(task_id)
    step_records: list[dict[str, Any]] = []

    state, record = await _run_node("approval_node", nodes.approval_node, state)
    step_records.append(record)
    app.update_state(config, state)

    if state.get("approval_status") == "rejected":
        state, replan_record = await _run_node("planning_node", nodes.planning_node, state)
        step_records.append(replan_record)
        app.update_state(config, state)
        state["status"] = TaskStatus.WAITING_APPROVAL.value
        state["current_node"] = "approval_node"
        app.update_state(config, state)
        return state, step_records, True

    for node_name, node_fn in POST_APPROVAL_SEQUENCE:
        state, record = await _run_node(node_name, node_fn, state)
        step_records.append(record)
        app.update_state(config, state)

        # Coder 失败则跳过测试，直接生成最终报告
        if node_name == "edit_code_node" and state.get("error_message"):
            state, report_record = await _run_node(
                "final_report_node", nodes.final_report_node, state
            )
            step_records.append(report_record)
            app.update_state(config, state)
            break

    return state, step_records, False


async def _persist_steps(db: AsyncSession, task_id: int, step_records: list[dict[str, Any]]) -> None:
    for record in step_records:
        db.add(
            AgentStep(
                task_id=task_id,
                agent_name=record["agent_name"],
                node_name=record["node_name"],
                status=record["status"],
                input_summary=record.get("input_summary"),
                output_summary=record.get("output_summary"),
                error_message=record.get("error_message"),
                started_at=record.get("started_at") or datetime.now(timezone.utc),
                ended_at=record.get("ended_at") or datetime.now(timezone.utc),
            )
        )


async def _persist_edit_history(
    db: AsyncSession,
    task_id: int,
    edit_records: list[dict[str, Any]],
) -> None:
    for item in edit_records:
        db.add(
            EditHistory(
                task_id=task_id,
                retry_index=item.get("retry_index", 0),
                file_path=item["file_path"],
                before_content=item.get("before_content"),
                after_content=item.get("after_content"),
                diff=item.get("diff"),
            )
        )


async def _persist_test_runs(
    db: AsyncSession,
    task_id: int,
    test_results: list[dict[str, Any]],
    retry_index: int,
) -> None:
    for item in test_results:
        db.add(
            TestRun(
                task_id=task_id,
                retry_index=retry_index,
                command=item["command"],
                exit_code=item["exit_code"],
                stdout=item.get("stdout"),
                stderr=item.get("stderr"),
                duration_ms=item.get("duration_ms"),
                passed=item.get("passed", False),
            )
        )


async def _persist_retrieved_contexts(
    db: AsyncSession,
    task_id: int,
    retrieved_context: list[dict[str, Any]],
) -> None:
    for item in retrieved_context:
        db.add(
            RetrievedContext(
                task_id=task_id,
                file_path=item["file_path"],
                line_start=item["line_start"],
                line_end=item["line_end"],
                snippet=item["snippet"],
                score=float(item.get("score") or 0.0),
                method=item.get("method") or "semantic",
            )
        )


async def _sync_task_from_state(db: AsyncSession, task: FixTask, state: FixPilotState) -> None:
    status_value = state.get("status")
    if status_value:
        try:
            task.status = TaskStatus(status_value)
        except ValueError:
            logger.warning(f"未知任务状态：{status_value}")

    task.current_agent = state.get("current_agent")
    task.current_node = state.get("current_node")
    task.workspace_path = state.get("repo_path") or task.workspace_path
    task.final_report = state.get("final_report") or task.final_report
    task.error_message = state.get("error_message") or task.error_message
    task.retry_count = state.get("retry_count", task.retry_count)

    if state.get("test_command") and not task.test_command:
        task.test_command = state["test_command"]
    if state.get("lint_command") and not task.lint_command:
        task.lint_command = state["lint_command"]


async def start_workflow(db: AsyncSession, task_id: int) -> FixTask:
    task = await _get_task_or_raise(db, task_id)
    if task.status not in {TaskStatus.PENDING, TaskStatus.FAILED}:
        raise ValueError(f"任务状态为 {task.status.value}，仅 pending / failed 可启动")

    task.status = TaskStatus.RUNNING
    initial_state = _build_initial_state(task)
    state, step_records = await _run_until_approval(task_id, initial_state)

    await _persist_steps(db, task_id, step_records)
    if state.get("retrieved_context"):
        await _persist_retrieved_contexts(db, task_id, state["retrieved_context"])
    await _sync_task_from_state(db, task, state)

    if not state.get("error_message"):
        task.status = TaskStatus.WAITING_APPROVAL

    await db.flush()
    await db.refresh(task)
    logger.info(f"任务 {task_id} 启动完成，status={task.status.value}")
    return task


async def approve_plan(db: AsyncSession, task_id: int, comment: str | None = None) -> FixTask:
    task = await _get_task_or_raise(db, task_id)
    if task.status != TaskStatus.WAITING_APPROVAL:
        raise ValueError("仅 waiting_approval 状态可批准计划")

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.PLAN,
            status=ApprovalStatus.APPROVED,
            user_comment=comment,
        )
    )

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state:
        raise ValueError("找不到 Workflow 状态，请先 POST /start")

    state = {**state, "approval_status": "approved", "status": TaskStatus.RUNNING.value}
    state, step_records, _ = await _resume_after_approval(task_id, state)

    await _persist_steps(db, task_id, step_records)
    if state.get("edit_history"):
        await _persist_edit_history(db, task_id, state["edit_history"])
    if state.get("test_results"):
        await _persist_test_runs(
            db, task_id, state["test_results"], state.get("retry_count", 0)
        )
    await _sync_task_from_state(db, task, state)
    await db.flush()
    await db.refresh(task)
    return task


async def reject_plan(db: AsyncSession, task_id: int, reason: str) -> FixTask:
    task = await _get_task_or_raise(db, task_id)
    if task.status != TaskStatus.WAITING_APPROVAL:
        raise ValueError("仅 waiting_approval 状态可拒绝计划")

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.PLAN,
            status=ApprovalStatus.REJECTED,
            user_comment=reason,
        )
    )

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state:
        raise ValueError("找不到 Workflow 状态，请先 POST /start")

    state = {
        **state,
        "approval_status": "rejected",
        "user_feedback": reason,
        "status": TaskStatus.RUNNING.value,
    }
    state, step_records, _ = await _resume_after_approval(task_id, state)

    await _persist_steps(db, task_id, step_records)
    await _sync_task_from_state(db, task, state)
    task.status = TaskStatus.WAITING_APPROVAL
    await db.flush()
    await db.refresh(task)
    return task


async def list_task_steps(db: AsyncSession, task_id: int) -> list[AgentStep]:
    await _get_task_or_raise(db, task_id)
    result = await db.execute(
        select(AgentStep)
        .where(AgentStep.task_id == task_id)
        .order_by(AgentStep.started_at.asc())
    )
    return list(result.scalars().all())


async def _get_task_or_raise(db: AsyncSession, task_id: int) -> FixTask:
    result = await db.execute(select(FixTask).where(FixTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise LookupError(f"任务 {task_id} 不存在")
    return task
