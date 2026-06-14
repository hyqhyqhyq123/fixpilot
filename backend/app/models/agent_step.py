# backend/app/models/agent_step.py
# 作用：记录每个 Agent 的执行步骤（对齐需求文档第 11.3 节）
#
# 为什么需要 agent_steps 表？
# 每个任务由多个 Agent 依次执行，agent_steps 就像一份"执行日志"：
# - 每个 Agent 开始时写入一条 running 记录
# - 成功后更新为 success，记录输出摘要
# - 失败后更新为 failed，记录错误信息
# - 前端用这些记录展示"Agent 执行时间线"

import enum
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# PostgreSQL 生产环境使用 JSONB；SQLite 测试环境自动退回通用 JSON。
# 这样既保留线上查询能力，也让初学者可以不启动 PostgreSQL 先跑本地单测。
JSON_SUMMARY_TYPE = JSON().with_variant(JSONB, "postgresql")


class StepStatus(str, enum.Enum):
    """Agent 步骤的执行状态。"""
    RUNNING = "running"    # 正在执行
    SUCCESS = "success"    # 执行成功
    FAILED = "failed"      # 执行失败
    SKIPPED = "skipped"    # 被跳过（例如测试通过后跳过 Failure Diagnosis）


class AgentStep(Base):
    """
    agent_steps 表：记录每个 Agent 节点的执行情况。

    每个 FixTask 可以有多条 AgentStep 记录，通过 task_id 关联。
    """
    __tablename__ = "agent_steps"
    __table_args__ = (
        # Trace 页按 task_id 拉取步骤，并按 started_at 展示时间线。
        Index("ix_agent_steps_task_started", "task_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 关联到哪个任务
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # 经常用 task_id 查询，加索引提升速度
    )

    agent_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Agent 名称，如 issue_analyst、planner、coder",
    )
    node_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="LangGraph 节点名称，如 classify_issue_node",
    )

    status: Mapped[StepStatus] = mapped_column(
        Enum(StepStatus, name="step_status"),
        default=StepStatus.RUNNING,
        nullable=False,
    )

    # PostgreSQL 下实际是 JSONB，SQLite 测试下是普通 JSON。
    # input_summary：这个 Agent 收到的输入摘要（不是完整数据，是摘要，节省空间）
    input_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON_SUMMARY_TYPE, nullable=True
    )
    # output_summary：这个 Agent 输出的摘要
    output_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON_SUMMARY_TYPE, nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 用于计算每个 Agent 耗时（ended_at - started_at）
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<AgentStep id={self.id} task={self.task_id} "
            f"agent={self.agent_name} status={self.status}>"
        )
