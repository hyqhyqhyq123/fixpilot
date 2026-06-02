# backend/test_db.py
# 测试数据库建表是否正常：7 张表都能创建，基本 CRUD 能跑通

import asyncio
import sys
import os

# 把 backend 目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.db.session import engine, init_db


async def test_init_db():
    """测试 init_db() 能否正常创建所有表。"""
    print("=" * 50)
    print("测试：初始化数据库（建表）")
    print("=" * 50)

    await init_db()
    print("[OK] init_db() 执行成功")

    # 查询数据库里现有的表名，验证 7 张表都被创建了
    expected_tables = {
        "fix_tasks",
        "agent_steps",
        "tool_calls",
        "retrieved_contexts",
        "edit_history",
        "test_runs",
        "approvals",
    }

    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ))
        existing_tables = {row[0] for row in result.fetchall()}

    print(f"\n数据库中发现的表：{sorted(existing_tables)}")

    missing = expected_tables - existing_tables
    if missing:
        print(f"\n❌ 缺少以下表：{missing}")
        return False

    print(f"\n[OK] 所有 {len(expected_tables)} 张表已创建：")
    for t in sorted(expected_tables):
        print(f"   - {t}")
    return True


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
    ok = await test_init_db()
    if not ok:
        print("\n❌ 建表失败，中止测试")
        return

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
