# backend/app/tasks/workflow_tasks.py
# Celery 后台任务：在 Worker 进程中执行 LangGraph Workflow（避免阻塞 API）

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.models.fix_task import FixTask, TaskStatus
from app.services import workflow_runner

logger = logging.getLogger(__name__)

# Celery Worker 进程内复用同一 event loop。
# 若每次任务都 asyncio.run()，全局 AsyncEngine 连接池会绑在已关闭的 loop 上，第二次任务会报错。
_worker_loop: asyncio.AbstractEventLoop | None = None


def reset_worker_event_loop() -> None:
    """fork 后或测试 teardown 时重置 Worker loop（由 celery_app worker_process_init 调用）。"""
    global _worker_loop
    _worker_loop = None


async def _run_with_session(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    async with AsyncSessionLocal() as db:
        try:
            result = await fn(db, *args, **kwargs)
            await db.commit()
            return result
        except Exception:
            await db.rollback()
            raise


async def _mark_task_failed(task_id: int, message: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(FixTask).where(FixTask.id == task_id))
        task = result.scalar_one_or_none()
        if task is None:
            return
        task.status = TaskStatus.FAILED
        task.error_message = message[:2000]
        await db.commit()


def _run(coro: Awaitable[Any]) -> Any:
    """在 Celery Worker 或 eager 模式（可能已有 event loop）中执行 async 代码。"""
    global _worker_loop
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if _worker_loop is None or _worker_loop.is_closed():
            _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
        return _worker_loop.run_until_complete(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


@celery_app.task(name="fixpilot.start_workflow", bind=True)
def start_workflow_task(self, task_id: int) -> dict[str, Any]:
    try:
        task = _run(
            _run_with_session(
                workflow_runner.start_workflow,
                task_id,
                allow_running=True,
            )
        )
        return {"task_id": task_id, "status": task.status.value}
    except Exception as exc:
        logger.exception("Celery start_workflow 失败 task_id=%s", task_id)
        _run(_mark_task_failed(task_id, str(exc)))
        raise


@celery_app.task(name="fixpilot.approve_plan", bind=True)
def approve_plan_task(self, task_id: int, comment: str | None = None) -> dict[str, Any]:
    try:
        task = _run(_run_with_session(workflow_runner.approve_plan, task_id, comment))
        return {"task_id": task_id, "status": task.status.value}
    except Exception as exc:
        logger.exception("Celery approve_plan 失败 task_id=%s", task_id)
        _run(_mark_task_failed(task_id, str(exc)))
        raise


@celery_app.task(name="fixpilot.reject_plan", bind=True)
def reject_plan_task(self, task_id: int, reason: str) -> dict[str, Any]:
    try:
        task = _run(_run_with_session(workflow_runner.reject_plan, task_id, reason))
        return {"task_id": task_id, "status": task.status.value}
    except Exception as exc:
        logger.exception("Celery reject_plan 失败 task_id=%s", task_id)
        _run(_mark_task_failed(task_id, str(exc)))
        raise


@celery_app.task(name="fixpilot.retry_failed_workflow", bind=True)
def retry_failed_workflow_task(self, task_id: int, comment: str | None = None) -> dict[str, Any]:
    try:
        task = _run(
            _run_with_session(
                workflow_runner.retry_failed_workflow,
                task_id,
                comment,
                allow_running=True,
            )
        )
        return {"task_id": task_id, "status": task.status.value}
    except Exception as exc:
        logger.exception("Celery retry_failed_workflow 失败 task_id=%s", task_id)
        _run(_mark_task_failed(task_id, str(exc)))
        raise


@celery_app.task(name="fixpilot.approve_diff", bind=True)
def approve_diff_task(self, task_id: int, comment: str | None = None) -> dict[str, Any]:
    try:
        task = _run(
            _run_with_session(workflow_runner.approve_diff_review, task_id, comment)
        )
        return {"task_id": task_id, "status": task.status.value}
    except Exception as exc:
        logger.exception("Celery approve_diff 失败 task_id=%s", task_id)
        _run(_mark_task_failed(task_id, str(exc)))
        raise


@celery_app.task(name="fixpilot.reject_diff", bind=True)
def reject_diff_task(self, task_id: int, reason: str) -> dict[str, Any]:
    try:
        task = _run(
            _run_with_session(workflow_runner.reject_diff_review, task_id, reason)
        )
        return {"task_id": task_id, "status": task.status.value}
    except Exception as exc:
        logger.exception("Celery reject_diff 失败 task_id=%s", task_id)
        _run(_mark_task_failed(task_id, str(exc)))
        raise
