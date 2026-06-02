# backend/app/models/tool_call.py
# 作用：记录每次工具调用的审计日志（对齐需求文档第 11.4 节）
#
# 为什么需要 tool_calls 表？
# 每个 Agent 可以调用多个工具（read_file、search_code、edit_file 等）。
# tool_calls 表是"工具审计日志"：
# - 记录了哪个任务的哪个步骤调用了什么工具
# - 记录了工具的权限级别（low/medium/high）
# - 高权限工具调用必须可追踪，出问题时能还原现场

import enum
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PermissionLevel(str, enum.Enum):
    """工具权限级别（见需求文档 9.2 节）。"""
    LOW = "low"        # 只读操作，无需审批（读文件、搜索代码）
    MEDIUM = "medium"  # 副作用有限，视情况（clone repo）
    HIGH = "high"      # 写操作，必须在审批或沙箱中（写文件、执行命令、创建 PR）


class ToolCallStatus(str, enum.Enum):
    """工具调用结果状态。"""
    SUCCESS = "success"
    FAILED = "failed"


class ToolCall(Base):
    """
    tool_calls 表：工具调用审计日志。

    每条记录对应一次工具调用。
    """
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 关联到具体哪个 Agent 步骤（可为空，允许直接关联 task）
    step_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("agent_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    tool_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="工具名称，如 read_file_tool、edit_file_tool",
    )

    permission_level: Mapped[PermissionLevel] = mapped_column(
        Enum(PermissionLevel, name="permission_level"),
        nullable=False,
        default=PermissionLevel.LOW,
    )

    input_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, comment="工具输入摘要"
    )
    output_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, comment="工具输出摘要"
    )

    status: Mapped[ToolCallStatus] = mapped_column(
        Enum(ToolCallStatus, name="tool_call_status"),
        nullable=False,
        default=ToolCallStatus.SUCCESS,
    )

    # 工具执行耗时（毫秒），用于性能分析
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ToolCall id={self.id} task={self.task_id} "
            f"tool={self.tool_name} status={self.status}>"
        )
