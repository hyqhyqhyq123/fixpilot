# backend/test_db.py
# 测试数据库建表是否正常：12 张表都能创建，基本 CRUD 能跑通

import asyncio

import pytest
from sqlalchemy import inspect

from app.db.session import engine, init_db

pytestmark = pytest.mark.anyio


EXPECTED_TABLES = {
    "fix_tasks",
    "agent_steps",
    "tool_calls",
    "retrieved_contexts",
    "edit_history",
    "test_runs",
    "approvals",
    "users",
    "user_settings",
    "task_github_prs",
    "task_evaluations",
    "workflow_checkpoints",
}


async def _list_table_names() -> set[str]:
    """用 SQLAlchemy inspect 查询表名，兼容 PostgreSQL 和 SQLite。"""

    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )


async def test_init_db():
    """测试 init_db() 能否正常创建所有表。"""
    print("=" * 50)
    print("测试：初始化数据库（建表）")
    print("=" * 50)

    await init_db()
    print("[OK] init_db() 执行成功")

    # 这里不用 PostgreSQL 专属的 pg_tables，避免 SQLite 测试库无法运行。
    existing_tables = await _list_table_names()

    print(f"\n数据库中发现的表：{sorted(existing_tables)}")

    missing = EXPECTED_TABLES - existing_tables
    assert not missing, f"缺少以下表：{missing}"

    print(f"\n[OK] 所有 {len(EXPECTED_TABLES)} 张表已创建：")
    for t in sorted(EXPECTED_TABLES):
        print(f"   - {t}")


async def test_create_fix_task():
    """测试创建一条 fix_task 记录。"""
    print("\n" + "=" * 50)
    print("测试：创建 FixTask 记录")
    print("=" * 50)

    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db.session import AsyncSessionLocal
    from app.models.fix_task import FixTask, TaskStatus

    async with AsyncSessionLocal() as session:
        task = FixTask(
            repo_url="https://github.com/pallets/flask",
            issue_text="当用户提交空表单时应该返回 400 但现在直接崩溃了",
            base_branch="main",
            status=TaskStatus.PENDING,
        )
        session.add(task)
        await session.flush()
        await session.refresh(task)
        await session.commit()   # 必须 commit，后续测试才能引用这个 task_id

        print(f"[OK] FixTask 创建成功：id={task.id}, status={task.status}")
        task_id = task.id

    return task_id


@pytest.fixture
async def task_id() -> int:
    """为依赖 task_id 的表测试创建一条任务。

    pytest 的测试函数彼此独立，不能依赖上一个测试的 return 值。
    所以这里用 fixture 显式准备一条 FixTask。
    """

    await init_db()
    return await test_create_fix_task()


async def test_create_agent_step(task_id: int):
    """测试创建一条 agent_step 记录。"""
    print("\n" + "=" * 50)
    print("测试：创建 AgentStep 记录")
    print("=" * 50)

    from app.db.session import AsyncSessionLocal
    from app.models.agent_step import AgentStep, StepStatus

    async with AsyncSessionLocal() as session:
        step = AgentStep(
            task_id=task_id,
            agent_name="issue_analyst",
            node_name="classify_issue_node",
            status=StepStatus.SUCCESS,
            input_summary={"issue_text_length": 30},
            output_summary={"issue_type": "bug", "risk_level": "medium"},
        )
        session.add(step)
        await session.flush()
        await session.refresh(step)
        await session.commit()

        print(f"[OK] AgentStep 创建成功：id={step.id}, agent={step.agent_name}")
        return step.id


async def test_create_approval(task_id: int):
    """测试创建一条 approval 记录。"""
    print("\n" + "=" * 50)
    print("测试：创建 Approval 记录")
    print("=" * 50)

    from app.db.session import AsyncSessionLocal
    from app.models.approval import Approval, ApprovalType, ApprovalStatus

    async with AsyncSessionLocal() as session:
        approval = Approval(
            task_id=task_id,
            approval_type=ApprovalType.PLAN,
            status=ApprovalStatus.APPROVED,
            user_comment="计划合理，批准执行",
        )
        session.add(approval)
        await session.flush()
        await session.refresh(approval)
        await session.commit()

        print(
            f"[OK] Approval 创建成功：id={approval.id}, "
            f"type={approval.approval_type}, status={approval.status}"
        )


async def test_create_test_run(task_id: int):
    """测试创建一条 test_run 记录。"""
    print("\n" + "=" * 50)
    print("测试：创建 TestRun 记录")
    print("=" * 50)

    from app.db.session import AsyncSessionLocal
    from app.models.test_run import TestRun

    async with AsyncSessionLocal() as session:
        run = TestRun(
            task_id=task_id,
            retry_index=0,
            command="pytest tests/",
            exit_code=0,
            stdout="5 passed in 1.23s",
            stderr="",
            duration_ms=1230,
            passed=True,
        )
        session.add(run)
        await session.flush()
        await session.refresh(run)
        await session.commit()

        print(f"[OK] TestRun 创建成功：id={run.id}, passed={run.passed}")


async def main():
    print("\n[START] FixPilot 数据库测试开始\n")

    # 1. 建表
    await test_init_db()

    # 2. 测试各表的增删
    task_id = await test_create_fix_task()
    await test_create_agent_step(task_id)
    await test_create_approval(task_id)
    await test_create_test_run(task_id)

    print("\n" + "=" * 50)
    print("[PASS] 所有数据库测试通过！")
    print("=" * 50)

    # 关闭引擎连接
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
