# backend/app/services/workflow_queue.py
# 将 Workflow 操作投递到 Celery；未启用时由 API 同步执行

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.fix_task import FixTask, TaskStatus
from app.services import workflow_runner
from app.services.task_status_audit import transition_task_status
from app.services.task_state_machine import (
    validate_retry_status,
    validate_start_status,
    validate_waiting_to_running,
)

logger = logging.getLogger(__name__)


def celery_enabled() -> bool:
    return get_settings().use_celery


async def mark_task_running(db: AsyncSession, task_id: int) -> FixTask:
    """启动 Workflow 前标记为 running（后台任务立即返回给前端）。"""
    task = await workflow_runner.ensure_task_exists(db, task_id)
    validate_start_status(task.status)
    await transition_task_status(db, task, TaskStatus.RUNNING, action="queue_start")
    # 这里要尽早提交状态，避免用户连点启动时第二个请求还读到 pending。
    await db.commit()
    await db.refresh(task)
    return task


async def mark_task_running_from_waiting(db: AsyncSession, task_id: int) -> FixTask:
    task = await workflow_runner.ensure_task_exists(db, task_id)
    validate_waiting_to_running(task.status)
    await transition_task_status(db, task, TaskStatus.RUNNING, action="queue_continue")
    await db.flush()
    await db.refresh(task)
    return task


async def mark_failed_task_retrying(db: AsyncSession, task_id: int) -> FixTask:
    task = await workflow_runner.ensure_task_exists(db, task_id)
    validate_retry_status(task.status, task.retry_count, task.max_retries)
    await transition_task_status(db, task, TaskStatus.RUNNING, action="queue_retry")
    task.current_agent = "coordinator"
    task.current_node = "retry_failed_task"
    task.error_message = None
    task.retry_count += 1
    await db.commit()
    await db.refresh(task)
    return task


def dispatch_start_workflow(task_id: int) -> None:
    from app.tasks.workflow_tasks import start_workflow_task

    start_workflow_task.delay(task_id)
    logger.info("已投递 Celery start_workflow task_id=%s", task_id)


def dispatch_retry_failed_workflow(task_id: int, comment: str | None) -> None:
    from app.tasks.workflow_tasks import retry_failed_workflow_task

    retry_failed_workflow_task.delay(task_id, comment)
    logger.info("已投递 Celery retry_failed_workflow task_id=%s", task_id)


def dispatch_approve_plan(task_id: int, comment: str | None) -> None:
    from app.tasks.workflow_tasks import approve_plan_task

    approve_plan_task.delay(task_id, comment)
    logger.info("已投递 Celery approve_plan task_id=%s", task_id)


def dispatch_reject_plan(task_id: int, reason: str) -> None:
    from app.tasks.workflow_tasks import reject_plan_task

    reject_plan_task.delay(task_id, reason)
    logger.info("已投递 Celery reject_plan task_id=%s", task_id)


def dispatch_approve_diff(task_id: int, comment: str | None) -> None:
    from app.tasks.workflow_tasks import approve_diff_task

    approve_diff_task.delay(task_id, comment)
    logger.info("已投递 Celery approve_diff task_id=%s", task_id)


def dispatch_reject_diff(task_id: int, reason: str) -> None:
    from app.tasks.workflow_tasks import reject_diff_task

    reject_diff_task.delay(task_id, reason)
    logger.info("已投递 Celery reject_diff task_id=%s", task_id)
