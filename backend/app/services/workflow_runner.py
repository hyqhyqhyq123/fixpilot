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
from app.core.tool_permissions import get_tool_permission
from app.models.agent_step import AgentStep, StepStatus
from app.models.approval import Approval, ApprovalStatus, ApprovalType
from app.models.edit_history import EditHistory
from app.models.fix_task import FixTask, TaskStatus
from app.models.retrieved_context import RetrievedContext
from app.core.llm_trace import pop_token_usage
from app.core.observability import record_agent_step_metric
from app.models.test_run import TestRun
from app.models.tool_call import PermissionLevel, ToolCall, ToolCallStatus
from app.models.workflow_checkpoint import WorkflowCheckpoint
from app.services.task_state_machine import (
    validate_cancel_status,
    validate_retry_status,
    validate_start_status,
)
from app.services.task_status_audit import transition_task_status
from app.tools.path_utils import resolve_repo_file

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
    "diagnose_failure_node": "failure_diagnoser",
    "retry_decision_node": "coordinator",
    "review_diff_node": "reviewer",
    "pr_writer_node": "pr_writer",
    "rollback_retry_step": "coordinator",
    "final_report_node": "coordinator",
}

POST_APPROVAL_EDIT_TEST_NODES: list[tuple[str, Any]] = [
    ("edit_code_node", nodes.edit_code_node),
    ("run_tests_node", nodes.run_tests_node),
]
POST_APPROVAL_FAILURE_NODES: list[tuple[str, Any]] = [
    ("diagnose_failure_node", nodes.diagnose_failure_node),
    ("retry_decision_node", nodes.retry_decision_node),
]

# Node → 代表性工具名（用于 tool_calls 审计表）
NODE_TOOL_MAP: dict[str, tuple[str, PermissionLevel]] = {
    "clone_repo_node": ("repo_clone_tool", get_tool_permission("repo_clone_tool")),
    "retrieve_context_node": (
        "semantic_search_tool",
        get_tool_permission("semantic_search_tool"),
    ),
    "edit_code_node": ("edit_file_tool", get_tool_permission("edit_file_tool")),
    "run_tests_node": ("run_tests_tool", get_tool_permission("run_tests_tool")),
    "rollback_retry_step": (
        "rollback_retry_tool",
        get_tool_permission("rollback_retry_tool"),
    ),
}

PRE_APPROVAL_SEQUENCE: list[tuple[str, Any]] = [
    ("intake_node", nodes.intake_node),
    ("clone_repo_node", nodes.clone_repo_node),
    ("analyze_repo_node", nodes.analyze_repo_node),
    ("planning_node", nodes.planning_node),
]

PRE_APPROVAL_PARALLEL_AFTER_ANALYZE: list[tuple[str, Any]] = [
    ("classify_issue_node", nodes.classify_issue_node),
    ("retrieve_context_node", nodes.retrieve_context_node),
]


def _thread_config(task_id: int) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"task_{task_id}"}}


async def _save_workflow_checkpoint(
    db: AsyncSession,
    task_id: int,
    state: FixPilotState,
) -> WorkflowCheckpoint:
    """
    Persist the latest workflow State snapshot.

    为什么只保留每个任务最新一份：审批恢复只需要继续当前任务，
    历史过程已经在 agent_steps / tool_calls / test_runs 等表里保存。
    """
    thread_id = f"task_{task_id}"
    state_snapshot = dict(state)
    result = await db.execute(
        select(WorkflowCheckpoint).where(WorkflowCheckpoint.task_id == task_id)
    )
    checkpoint = result.scalar_one_or_none()
    if checkpoint is None:
        checkpoint = WorkflowCheckpoint(
            task_id=task_id,
            thread_id=thread_id,
            current_node=state_snapshot.get("current_node"),
            state=state_snapshot,
        )
        db.add(checkpoint)
    else:
        checkpoint.thread_id = thread_id
        checkpoint.current_node = state_snapshot.get("current_node")
        checkpoint.state = state_snapshot

    await db.flush()
    return checkpoint


async def _load_workflow_checkpoint(
    db: AsyncSession,
    task_id: int,
) -> FixPilotState | None:
    """Load the latest database-backed State snapshot for one task."""
    result = await db.execute(
        select(WorkflowCheckpoint).where(WorkflowCheckpoint.task_id == task_id)
    )
    checkpoint = result.scalar_one_or_none()
    if checkpoint is None:
        return None
    return FixPilotState(**(checkpoint.state or {}))


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

    if node_name == "planning_node" and updates.get("plan"):
        plan = updates["plan"]
        modify_paths = [f.get("path") for f in (plan.get("files_to_modify") or []) if f.get("path")]
        add_paths = [f.get("path") for f in (plan.get("files_to_add") or []) if f.get("path")]
        output_summary.update(
            {
                "problem_summary": plan.get("problem_summary"),
                "files_to_modify": len(plan.get("files_to_modify") or []),
                "files_to_add": len(plan.get("files_to_add") or []),
                "related_files": modify_paths + add_paths,
            }
        )

    if node_name == "retrieve_context_node":
        ctx = updates.get("retrieved_context") or state.get("retrieved_context") or []
        output_summary["retrieved_count"] = len(ctx)
        output_summary["related_files"] = [
            c.get("file_path") for c in ctx if c.get("file_path")
        ][:20]

    if node_name == "edit_code_node":
        histories = updates.get("edit_history") or state.get("edit_history") or []
        output_summary["edited_files"] = len(histories)
        output_summary["related_files"] = [
            h.get("file_path") for h in histories if h.get("file_path")
        ]
        if updates.get("test_note"):
            output_summary["test_note"] = updates["test_note"]

    if node_name == "run_tests_node" and updates.get("test_results"):
        results = updates["test_results"]
        output_summary["checks_run"] = len(results)
        output_summary["checks_passed"] = sum(1 for item in results if item.get("passed"))
        output_summary["check_types"] = [item.get("check_type", "test") for item in results]
        if results:
            last = results[-1]
            output_summary["test_passed"] = last.get("passed")
            output_summary["test_command"] = last.get("command")

    if node_name == "diagnose_failure_node" and updates.get("failure_analysis"):
        analysis = updates["failure_analysis"]
        output_summary["should_retry"] = analysis.get("should_retry")
        output_summary["is_caused_by_current_patch"] = analysis.get("is_caused_by_current_patch")
        output_summary["failure_summary"] = analysis.get("failure_summary")

    if node_name == "retry_decision_node":
        output_summary["retry_decision"] = updates.get("retry_decision")
        output_summary["retry_count"] = updates.get("retry_count", state.get("retry_count"))

    if node_name == "review_diff_node" and updates.get("review_result"):
        review = updates["review_result"]
        output_summary["risk_level"] = review.get("risk_level")
        output_summary["approval_required"] = review.get("approval_required")
        output_summary["review_decision"] = updates.get("review_decision")

    if node_name == "pr_writer_node" and updates.get("pr_draft"):
        output_summary["pr_draft_length"] = len(updates["pr_draft"])

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
    token_usage = pop_token_usage()
    if token_usage:
        output_summary["token_usage"] = token_usage
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
    record["_state_updates"] = updates
    return state, record


async def _run_parallel_nodes(
    parallel_nodes: list[tuple[str, Any]],
    state: FixPilotState,
) -> tuple[FixPilotState, list[dict[str, Any]]]:
    """
    Run independent nodes at the same time, then merge their State updates.

    为什么这里要集中合并：每个节点都只返回“自己负责的字段”，
    例如 Issue Analyst 写 issue_analysis，Code Retriever 写 retrieved_context。
    并行结束后再统一合并，可以让 Planner 同时拿到两边结果。
    """
    base_state = dict(state)
    tasks = [
        asyncio.create_task(_run_node(node_name, node_fn, dict(base_state)))
        for node_name, node_fn in parallel_nodes
    ]
    results = await asyncio.gather(*tasks)

    merged_state: FixPilotState = dict(base_state)
    records: list[dict[str, Any]] = []
    first_failed_node: str | None = None

    for _, record in results:
        updates = record.pop("_state_updates", {})
        records.append(record)
        merged_state = {**merged_state, **updates}
        if updates.get("error_message") and first_failed_node is None:
            first_failed_node = record["node_name"]

    if first_failed_node:
        merged_state["current_node"] = first_failed_node

    return merged_state, records


async def _run_until_approval(task_id: int, initial_state: FixPilotState) -> tuple[FixPilotState, list[dict[str, Any]]]:
    """执行 intake → planning，在审批前暂停。"""
    app = get_workflow_app()
    config = _thread_config(task_id)
    app.update_state(config, initial_state)

    state = dict(initial_state)
    step_records: list[dict[str, Any]] = []

    for node_name, node_fn in PRE_APPROVAL_SEQUENCE:
        state, record = await _run_node(node_name, node_fn, state)
        record.pop("_state_updates", None)
        step_records.append(record)
        app.update_state(config, state)

        if state.get("error_message"):
            state, report_record = await _run_node(
                "final_report_node", nodes.final_report_node, state
            )
            report_record.pop("_state_updates", None)
            step_records.append(report_record)
            app.update_state(config, state)
            return state, step_records

        if node_name == "analyze_repo_node":
            state, parallel_records = await _run_parallel_nodes(
                PRE_APPROVAL_PARALLEL_AFTER_ANALYZE,
                state,
            )
            step_records.extend(parallel_records)
            app.update_state(config, state)

            if state.get("error_message"):
                state, report_record = await _run_node(
                    "final_report_node", nodes.final_report_node, state
                )
                report_record.pop("_state_updates", None)
                step_records.append(report_record)
                app.update_state(config, state)
                return state, step_records

    state["status"] = TaskStatus.WAITING_APPROVAL.value
    state["current_node"] = "approval_node"
    state["pending_approval_type"] = "plan"
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

    while True:
        for node_name, node_fn in POST_APPROVAL_EDIT_TEST_NODES:
            state, record = await _run_node(node_name, node_fn, state)
            step_records.append(record)
            app.update_state(config, state)

            if node_name == "edit_code_node" and state.get("error_message"):
                state, report_record = await _run_node(
                    "final_report_node", nodes.final_report_node, state
                )
                step_records.append(report_record)
                app.update_state(config, state)
                return state, step_records, False

        if _latest_checks_passed(state) and not state.get("error_message"):
            break

        for node_name, node_fn in POST_APPROVAL_FAILURE_NODES:
            state, record = await _run_node(node_name, node_fn, state)
            step_records.append(record)
            app.update_state(config, state)

        if state.get("retry_decision") != "retry":
            break

    if state.get("edit_history"):
        state, record = await _run_node("review_diff_node", nodes.review_diff_node, state)
        step_records.append(record)
        app.update_state(config, state)

        if (
            _latest_checks_passed(state)
            and state.get("review_decision") != "high_risk"
        ):
            state, record = await _run_node("pr_writer_node", nodes.pr_writer_node, state)
            step_records.append(record)
            app.update_state(config, state)

    state, report_record = await _run_node(
        "final_report_node", nodes.final_report_node, state
    )
    step_records.append(report_record)
    app.update_state(config, state)

    return state, step_records, False


def _latest_checks_passed(state: FixPilotState) -> bool:
    batch_size = len(_collect_docker_checks_from_state(state)) or 1
    results = state.get("test_results") or []
    latest = results[-batch_size:] if results else []
    return not latest or all(item.get("passed") for item in latest)


def _collect_docker_checks_from_state(state: FixPilotState) -> list[tuple[str, str]]:
    """与 nodes._collect_docker_checks 保持一致，用于判断本轮测试条数。"""
    checks: list[tuple[str, str]] = []
    if state.get("test_command"):
        checks.append(("test", state["test_command"]))
    if state.get("lint_command"):
        checks.append(("lint", state["lint_command"]))
    if state.get("typecheck_command"):
        checks.append(("typecheck", state["typecheck_command"]))
    return checks


async def _persist_steps(
    db: AsyncSession,
    task_id: int,
    step_records: list[dict[str, Any]],
) -> None:
    for record in step_records:
        step = AgentStep(
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
        db.add(step)
        await db.flush()
        record_agent_step_metric(record)
        _persist_tool_call_for_step(db, task_id, step.id, record)


def _persist_tool_call_for_step(
    db: AsyncSession,
    task_id: int,
    step_id: int,
    record: dict[str, Any],
) -> None:
    """为关键 Node 写入 tool_calls 审计记录。"""
    node_name = record.get("node_name", "")
    mapping = NODE_TOOL_MAP.get(node_name)
    if not mapping:
        return

    tool_name, permission = mapping
    started = record.get("started_at") or datetime.now(timezone.utc)
    ended = record.get("ended_at") or started
    duration_ms = int((ended - started).total_seconds() * 1000)

    db.add(
        ToolCall(
            task_id=task_id,
            step_id=step_id,
            tool_name=tool_name,
            permission_level=permission,
            input_summary=record.get("input_summary"),
            output_summary=record.get("output_summary"),
            status=(
                ToolCallStatus.FAILED
                if record.get("error_message")
                else ToolCallStatus.SUCCESS
            ),
            duration_ms=duration_ms,
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
                retry_index=item.get("retry_index", retry_index),
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


async def ensure_task_exists(db: AsyncSession, task_id: int) -> FixTask:
    """公开接口：校验任务存在（供 API / Queue 层使用）。"""
    return await _get_task_or_raise(db, task_id)


async def _recover_missing_plan_state(
    db: AsyncSession,
    task: FixTask,
    task_id: int,
) -> FixPilotState:
    """
    Rebuild the in-memory workflow state after a local server restart.

    The current LangGraph checkpointer is MemorySaver, so it is intentionally
    lightweight but not durable. The database can still say "waiting_approval"
    while the in-memory plan state is gone. In that case we rerun the
    pre-approval nodes to recreate the plan state, then the approval action can
    continue normally.
    """
    logger.warning(
        "Workflow state missing for waiting approval task %s; rebuilding plan state",
        task_id,
    )
    task.status = TaskStatus.RUNNING
    task.current_agent = "coordinator"
    task.current_node = "recover_plan_state"
    await db.commit()
    await db.refresh(task)

    initial_state = _build_initial_state(task)
    state, step_records = await _run_until_approval(task_id, initial_state)
    await _save_workflow_checkpoint(db, task_id, state)

    existing_steps = await db.execute(
        select(AgentStep.id).where(AgentStep.task_id == task_id).limit(1)
    )
    if existing_steps.scalar_one_or_none() is None:
        await _persist_steps(db, task_id, step_records)
        if state.get("retrieved_context"):
            await _persist_retrieved_contexts(db, task_id, state["retrieved_context"])

    await _sync_task_from_state(db, task, state)
    if not state.get("error_message"):
        task.status = TaskStatus.WAITING_APPROVAL
    await db.flush()
    await db.refresh(task)
    return state


async def start_workflow(
    db: AsyncSession,
    task_id: int,
    *,
    allow_running: bool = False,
) -> FixTask:
    task = await _get_task_or_raise(db, task_id)
    # Celery 模式下 API 会先把任务标为 running 再入队。
    validate_start_status(task.status, allow_running=allow_running)

    if task.status != TaskStatus.RUNNING:
        await transition_task_status(db, task, TaskStatus.RUNNING, action="start_workflow")
        # 同步执行会花较长时间，先提交 running，避免用户连点时重复启动同一任务。
        await db.commit()
        await db.refresh(task)
    initial_state = _build_initial_state(task)
    state, step_records = await _run_until_approval(task_id, initial_state)
    await _save_workflow_checkpoint(db, task_id, state)

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

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state:
        state = await _load_workflow_checkpoint(db, task_id)
        if state:
            app.update_state(config, state)
        else:
            state = await _recover_missing_plan_state(db, task, task_id)

    if state.get("pending_approval_type") == "diff_review":
        raise ValueError("当前等待 diff 复核，请使用 POST /approve-diff")

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.PLAN,
            status=ApprovalStatus.APPROVED,
            user_comment=comment,
        )
    )
    await transition_task_status(db, task, TaskStatus.RUNNING, action="approve_plan")
    task.current_agent = "coordinator"
    task.current_node = "approval_node"
    await db.commit()
    await db.refresh(task)

    state = {**state, "approval_status": "approved", "status": TaskStatus.RUNNING.value}
    state, step_records, _ = await _resume_after_approval(task_id, state)
    await _save_workflow_checkpoint(db, task_id, state)

    await _persist_steps(db, task_id, step_records)
    if state.get("edit_history"):
        await _persist_edit_history(db, task_id, state["edit_history"])
    if state.get("test_results"):
        await _persist_test_runs(
            db, task_id, state["test_results"], state.get("retry_count", 0)
        )
    await _sync_task_from_state(db, task, state)

    # 高风险 diff：等待二次审批，不生成 PR
    if state.get("pending_approval_type") == "diff_review":
        task.status = TaskStatus.WAITING_APPROVAL
    await db.flush()
    await db.refresh(task)
    return task


async def reject_plan(db: AsyncSession, task_id: int, reason: str) -> FixTask:
    task = await _get_task_or_raise(db, task_id)
    if task.status != TaskStatus.WAITING_APPROVAL:
        raise ValueError("仅 waiting_approval 状态可拒绝计划")

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state:
        state = await _load_workflow_checkpoint(db, task_id)
        if state:
            app.update_state(config, state)
        else:
            state = await _recover_missing_plan_state(db, task, task_id)

    if state.get("pending_approval_type") == "diff_review":
        raise ValueError("当前等待 diff 复核，请使用 POST /reject-diff")

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.PLAN,
            status=ApprovalStatus.REJECTED,
            user_comment=reason,
        )
    )
    await transition_task_status(db, task, TaskStatus.RUNNING, action="reject_plan_replan")
    task.current_agent = "coordinator"
    task.current_node = "approval_node"
    await db.commit()
    await db.refresh(task)

    state = {
        **state,
        "approval_status": "rejected",
        "user_feedback": reason,
        "status": TaskStatus.RUNNING.value,
    }
    state, step_records, _ = await _resume_after_approval(task_id, state)
    await _save_workflow_checkpoint(db, task_id, state)

    await _persist_steps(db, task_id, step_records)
    await _sync_task_from_state(db, task, state)
    task.status = TaskStatus.WAITING_APPROVAL
    await db.flush()
    await db.refresh(task)
    return task


async def retry_failed_workflow(
    db: AsyncSession,
    task_id: int,
    comment: str | None = None,
    *,
    allow_running: bool = False,
) -> FixTask:
    task = await _get_task_or_raise(db, task_id)
    validate_retry_status(
        task.status,
        task.retry_count,
        task.max_retries,
        allow_running=allow_running,
    )

    approved_result = await db.execute(
        select(Approval)
        .where(
            Approval.task_id == task_id,
            Approval.approval_type == ApprovalType.PLAN,
            Approval.status == ApprovalStatus.APPROVED,
        )
        .limit(1)
    )
    if approved_result.scalar_one_or_none() is None:
        return await start_workflow(db, task_id)

    should_increment_retry = task.status == TaskStatus.FAILED
    await transition_task_status(db, task, TaskStatus.RUNNING, action="retry_failed_workflow")
    task.current_agent = "coordinator"
    task.current_node = "retry_failed_task"
    task.error_message = None
    if should_increment_retry:
        task.retry_count += 1
    await db.commit()
    await db.refresh(task)
    retry_count = task.retry_count

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state or not state.get("plan"):
        checkpoint_state = await _load_workflow_checkpoint(db, task_id)
        if checkpoint_state and checkpoint_state.get("plan"):
            state = checkpoint_state
            app.update_state(config, state)
        else:
            state = await _recover_missing_plan_state(db, task, task_id)
            await transition_task_status(
                db,
                task,
                TaskStatus.RUNNING,
                action="retry_recover_plan_state",
            )
            task.current_agent = "coordinator"
            task.current_node = "retry_failed_task"
            task.error_message = None
            task.retry_count = retry_count
            await db.commit()
            await db.refresh(task)

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.PLAN,
            status=ApprovalStatus.APPROVED,
            user_comment=comment or "重试失败任务",
        )
    )

    state = {
        **state,
        "approval_status": "approved",
        "pending_approval_type": None,
        "status": TaskStatus.RUNNING.value,
        "final_status": "running",
        "error_message": None,
        "retry_count": retry_count,
    }
    state, step_records, _ = await _resume_after_approval(task_id, state)
    await _save_workflow_checkpoint(db, task_id, state)

    await _persist_steps(db, task_id, step_records)
    if state.get("edit_history"):
        await _persist_edit_history(db, task_id, state["edit_history"])
    if state.get("test_results"):
        await _persist_test_runs(
            db, task_id, state["test_results"], state.get("retry_count", 0)
        )
    await _sync_task_from_state(db, task, state)

    if state.get("pending_approval_type") == "diff_review":
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


async def list_edit_history(db: AsyncSession, task_id: int) -> tuple[list[EditHistory], str]:
    await _get_task_or_raise(db, task_id)
    result = await db.execute(
        select(EditHistory)
        .where(EditHistory.task_id == task_id)
        .order_by(EditHistory.created_at.asc())
    )
    items = list(result.scalars().all())
    combined = "\n".join(item.diff or "" for item in items if item.diff)
    return items, combined


async def list_test_runs(db: AsyncSession, task_id: int) -> list[TestRun]:
    await _get_task_or_raise(db, task_id)
    result = await db.execute(
        select(TestRun)
        .where(TestRun.task_id == task_id)
        .order_by(TestRun.created_at.asc())
    )
    return list(result.scalars().all())


async def list_approvals(db: AsyncSession, task_id: int) -> list[Approval]:
    await _get_task_or_raise(db, task_id)
    result = await db.execute(
        select(Approval)
        .where(Approval.task_id == task_id)
        .order_by(Approval.created_at.asc())
    )
    return list(result.scalars().all())


async def list_tool_calls(db: AsyncSession, task_id: int) -> list[ToolCall]:
    await _get_task_or_raise(db, task_id)
    result = await db.execute(
        select(ToolCall)
        .where(ToolCall.task_id == task_id)
        .order_by(ToolCall.created_at.asc())
    )
    return list(result.scalars().all())


async def list_retrieved_contexts(
    db: AsyncSession,
    task_id: int,
) -> list[RetrievedContext]:
    """查询 Code Retriever 持久化到 DB 的代码片段。"""

    await _get_task_or_raise(db, task_id)
    result = await db.execute(
        select(RetrievedContext)
        .where(RetrievedContext.task_id == task_id)
        .order_by(RetrievedContext.score.desc(), RetrievedContext.id.asc())
    )
    return list(result.scalars().all())


def _restore_file_snapshot(
    repo_path: str,
    file_path: str,
    content: str | None,
) -> None:
    """Restore one file inside the task workspace."""

    resolved = resolve_repo_file(repo_path, file_path)
    if content is None:
        if resolved.exists():
            resolved.unlink()
        return

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")


async def rollback_to_retry_step(
    db: AsyncSession,
    task_id: int,
    retry_index: int,
) -> FixTask:
    """
    Restore workspace files to the state at the end of a retry attempt.

    retry_index=0 means "after the first Coder attempt". Files introduced only
    after that retry are deleted; files edited later are restored to the last
    snapshot at or before the target retry.
    """

    if retry_index < 0:
        raise ValueError("retry_index 不能小于 0")

    task = await _get_task_or_raise(db, task_id)
    if not task.workspace_path:
        raise ValueError("任务没有 workspace_path，无法回滚文件")

    result = await db.execute(
        select(EditHistory)
        .where(EditHistory.task_id == task_id)
        .order_by(EditHistory.retry_index.asc(), EditHistory.id.asc())
    )
    histories = list(result.scalars().all())
    if not histories:
        raise ValueError("任务没有 edit_history，无法回滚")

    max_retry = max(item.retry_index for item in histories)
    if retry_index > max_retry:
        raise ValueError(f"retry_index={retry_index} 超过最大记录 {max_retry}")

    by_file: dict[str, list[EditHistory]] = {}
    for item in histories:
        by_file.setdefault(item.file_path, []).append(item)

    restored_files: list[str] = []
    for file_path, records in by_file.items():
        before_or_at_target = [r for r in records if r.retry_index <= retry_index]
        if before_or_at_target:
            target_content = before_or_at_target[-1].after_content
        else:
            # The file was first touched after the target retry, so restore the
            # snapshot from just before that later edit.
            target_content = records[0].before_content

        _restore_file_snapshot(task.workspace_path, file_path, target_content)
        restored_files.append(file_path)

    task.status = TaskStatus.FAILED
    task.current_agent = "coordinator"
    task.current_node = "rollback_retry_step"
    task.error_message = f"已回滚到 retry_index={retry_index}，请重新检查后再继续。"

    await _persist_steps(
        db,
        task_id,
        [
            {
                "node_name": "rollback_retry_step",
                "agent_name": "coordinator",
                "status": StepStatus.SUCCESS,
                "input_summary": {"retry_index": retry_index},
                "output_summary": {
                    "restored_files": sorted(restored_files),
                    "related_files": sorted(restored_files),
                },
            }
        ],
    )
    await db.flush()
    await db.refresh(task)
    return task


async def cancel_workflow(db: AsyncSession, task_id: int, comment: str | None = None) -> FixTask:
    """取消任务并同步 LangGraph State（cancel → final_report）。"""
    task = await _get_task_or_raise(db, task_id)
    validate_cancel_status(task.status)

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.PLAN,
            status=ApprovalStatus.CANCELLED,
            user_comment=comment,
        )
    )
    await transition_task_status(
        db,
        task,
        TaskStatus.CANCELLED,
        action="cancel_workflow",
        reason=comment,
    )

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state:
        state = await _load_workflow_checkpoint(db, task_id)
        if state:
            app.update_state(config, state)
    if state:
        state = {
            **state,
            "approval_status": "cancelled",
            "status": TaskStatus.CANCELLED.value,
        }
        state, record = await _run_node(
            "final_report_node", nodes.final_report_node, state
        )
        app.update_state(config, state)
        await _save_workflow_checkpoint(db, task_id, state)
        await _persist_steps(db, task_id, [record])
        await _sync_task_from_state(db, task, state)
    else:
        task.final_report = task.final_report or "任务已被用户取消。"

    await db.flush()
    await db.refresh(task)
    logger.info(f"任务 {task_id} 已取消")
    return task


async def approve_diff_review(
    db: AsyncSession,
    task_id: int,
    comment: str | None = None,
) -> FixTask:
    """高风险 diff 二次审批通过后生成 PR 并完成报告。"""
    task = await _get_task_or_raise(db, task_id)
    if task.status != TaskStatus.WAITING_APPROVAL:
        raise ValueError("仅 waiting_approval 状态可批准 diff")

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state:
        state = await _load_workflow_checkpoint(db, task_id)
        if state:
            app.update_state(config, state)
        else:
            raise ValueError("找不到 Workflow 状态")

    if state.get("pending_approval_type") != "diff_review":
        raise ValueError("当前不在 diff 复核阶段")

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.HIGH_RISK,
            status=ApprovalStatus.APPROVED,
            user_comment=comment,
        )
    )

    step_records: list[dict[str, Any]] = []
    state, record = await _run_node("pr_writer_node", nodes.pr_writer_node, state)
    step_records.append(record)

    state = {
        **state,
        "pending_approval_type": None,
        "status": TaskStatus.RUNNING.value,
    }
    state, report_record = await _run_node(
        "final_report_node", nodes.final_report_node, state
    )
    step_records.append(report_record)
    app.update_state(config, state)
    await _save_workflow_checkpoint(db, task_id, state)

    await _persist_steps(db, task_id, step_records)
    await _sync_task_from_state(db, task, state)
    await db.flush()
    await db.refresh(task)
    return task


async def reject_diff_review(
    db: AsyncSession,
    task_id: int,
    reason: str,
) -> FixTask:
    """拒绝高风险 diff，任务标记失败。"""
    task = await _get_task_or_raise(db, task_id)
    if task.status != TaskStatus.WAITING_APPROVAL:
        raise ValueError("仅 waiting_approval 状态可拒绝 diff")

    app = get_workflow_app()
    config = _thread_config(task_id)
    state = app.get_state(config).values
    if not state:
        state = await _load_workflow_checkpoint(db, task_id)
        if state:
            app.update_state(config, state)
    if not state or state.get("pending_approval_type") != "diff_review":
        raise ValueError("当前不在 diff 复核阶段")

    db.add(
        Approval(
            task_id=task_id,
            approval_type=ApprovalType.HIGH_RISK,
            status=ApprovalStatus.REJECTED,
            user_comment=reason,
        )
    )

    state = {
        **state,
        "error_message": f"diff 复核被拒绝：{reason}",
        "status": TaskStatus.FAILED.value,
        "pending_approval_type": None,
    }
    state, record = await _run_node(
        "final_report_node", nodes.final_report_node, state
    )
    app.update_state(config, state)
    await _save_workflow_checkpoint(db, task_id, state)
    await _persist_steps(db, task_id, [record])
    await _sync_task_from_state(db, task, state)
    task.status = TaskStatus.FAILED
    await db.flush()
    await db.refresh(task)
    return task


async def _get_task_or_raise(db: AsyncSession, task_id: int) -> FixTask:
    result = await db.execute(select(FixTask).where(FixTask.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise LookupError(f"任务 {task_id} 不存在")
    return task
