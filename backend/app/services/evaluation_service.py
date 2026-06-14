# backend/app/services/evaluation_service.py
# 任务评测服务：汇总上下文 → LLM Judge → 写入 task_evaluations

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.task_judge import judge_task_result
from app.models.fix_task import FixTask, TaskStatus
from app.models.task_evaluation import TaskEvaluation
from app.models.test_run import TestRun
from app.services import workflow_runner

logger = logging.getLogger(__name__)


async def _build_judge_context(db: AsyncSession, task: FixTask) -> str:
    steps = await workflow_runner.list_task_steps(db, task.id)
    _, combined_diff = await workflow_runner.list_edit_history(db, task.id)
    test_runs = await workflow_runner.list_test_runs(db, task.id)

    plan_step = next((s for s in steps if s.node_name == "planning_node"), None)
    plan_summary = plan_step.output_summary if plan_step else None

    test_lines = [
        f"- command={run.command} passed={run.passed} exit={run.exit_code}"
        for run in test_runs
    ]

    parts = [
        f"Issue:\n{task.issue_text}",
        f"Repo: {task.repo_url}",
        f"Task status: {task.status.value}",
        f"Plan summary:\n{json.dumps(plan_summary, ensure_ascii=False) if plan_summary else 'N/A'}",
        f"Combined diff:\n{combined_diff[:12000] if combined_diff else '(empty)'}",
        f"Test runs:\n" + ("\n".join(test_lines) if test_lines else "(none)"),
        f"Final report:\n{(task.final_report or '')[:8000]}",
    ]
    return "\n\n".join(parts)


async def get_latest_evaluation(
    db: AsyncSession,
    task_id: int,
) -> TaskEvaluation | None:
    await workflow_runner.ensure_task_exists(db, task_id)
    result = await db.execute(
        select(TaskEvaluation)
        .where(TaskEvaluation.task_id == task_id)
        .order_by(TaskEvaluation.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def run_task_evaluation(db: AsyncSession, task_id: int) -> TaskEvaluation:
    task = await workflow_runner.ensure_task_exists(db, task_id)

    if task.status not in (TaskStatus.SUCCESS, TaskStatus.FAILED):
        raise ValueError("仅 success 或 failed 状态的任务可评测")

    context = await _build_judge_context(db, task)
    judge_result = judge_task_result(context)

    record = TaskEvaluation(
        task_id=task_id,
        overall_score=judge_result["overall_score"],
        patch_score=judge_result.get("patch_score"),
        plan_score=judge_result.get("plan_score"),
        test_score=judge_result.get("test_score"),
        judge_summary=judge_result["judge_summary"],
        details_json=json.dumps(judge_result.get("details") or {}, ensure_ascii=False),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.info("任务 %s 评测完成 overall=%s", task_id, record.overall_score)
    return record
