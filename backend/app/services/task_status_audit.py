"""任务状态流转审计服务。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fix_task import FixTask, TaskStatus
from app.models.task_status_transition import TaskStatusTransition
from app.services.task_state_machine import normalize_status, require_transition


async def record_task_status_transition(
    db: AsyncSession,
    *,
    task_id: int,
    from_status: TaskStatus | str,
    to_status: TaskStatus | str,
    action: str,
    reason: str | None = None,
) -> TaskStatusTransition:
    record = TaskStatusTransition(
        task_id=task_id,
        from_status=normalize_status(from_status).value,
        to_status=normalize_status(to_status).value,
        action=action,
        reason=reason,
    )
    db.add(record)
    await db.flush()
    return record


async def transition_task_status(
    db: AsyncSession,
    task: FixTask,
    to_status: TaskStatus | str,
    *,
    action: str,
    reason: str | None = None,
    validate: bool = True,
) -> TaskStatusTransition | None:
    """修改 task.status，并记录审计。

    状态未变化时不写审计，避免重复 start worker resume 产生噪声。
    """
    target = normalize_status(to_status)
    current = normalize_status(task.status)
    if current == target:
        return None
    if validate:
        require_transition(current, target)
    task.status = target
    return await record_task_status_transition(
        db,
        task_id=task.id,
        from_status=current,
        to_status=target,
        action=action,
        reason=reason,
    )
