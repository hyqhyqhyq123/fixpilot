import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal, init_db
from app.models.fix_task import FixTask, TaskStatus
from app.models.task_status_transition import TaskStatusTransition
from app.services.task_status_audit import transition_task_status


async def _transition_audit_records_valid_change():
    await init_db()
    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/example/demo",
            issue_text="状态流转审计测试任务描述足够长",
            status=TaskStatus.PENDING,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        await transition_task_status(
            db,
            task,
            TaskStatus.RUNNING,
            action="unit_test_start",
            reason="start from pending",
        )
        await db.commit()

        result = await db.execute(
            select(TaskStatusTransition).where(TaskStatusTransition.task_id == task.id)
        )
        record = result.scalar_one()

    assert record.from_status == "pending"
    assert record.to_status == "running"
    assert record.action == "unit_test_start"
    assert record.reason == "start from pending"
    print("[OK] 合法任务状态流转会写入 task_status_transitions")


def test_transition_audit_records_valid_change():
    asyncio.run(_transition_audit_records_valid_change())


async def _transition_audit_rejects_invalid_change():
    await init_db()
    async with AsyncSessionLocal() as db:
        task = FixTask(
            repo_url="https://github.com/example/demo",
            issue_text="非法状态流转审计测试任务描述足够长",
            status=TaskStatus.CANCELLED,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        try:
            await transition_task_status(
                db,
                task,
                TaskStatus.RUNNING,
                action="invalid_restart",
            )
        except ValueError as exc:
            assert "cancelled -> running" in str(exc)
        else:
            raise AssertionError("cancelled -> running 不应被允许")

        result = await db.execute(
            select(TaskStatusTransition).where(TaskStatusTransition.task_id == task.id)
        )
        records = result.scalars().all()

    assert records == []
    print("[OK] 非法任务状态流转会被拒绝且不写审计")


def test_transition_audit_rejects_invalid_change():
    asyncio.run(_transition_audit_rejects_invalid_change())
