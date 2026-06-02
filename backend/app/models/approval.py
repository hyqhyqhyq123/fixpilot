# backend/app/models/approval.py
# 作用：记录所有人工审批操作（对齐需求文档第 11.8 节）
#
# 为什么需要 approvals 表？
# - FixPilot 有多个地方需要人工审批：计划审批、高风险变更审批
# - 每条审批记录保存了谁批了什么、批了还是拒了、备注是什么
# - 这是审计日志的重要部分，出问题时可以追溯

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApprovalType(str, enum.Enum):
    """
    审批类型枚举（见需求文档 11.8 节）。

    - plan：修改计划审批（最常见）
    - file_write：写入计划外文件需要重新审批
    - test_execution：测试执行审批（可选）
    - pr_creation：创建 PR 前审批（V1）
    - high_risk：高风险变更（Reviewer 判定）
    """
    PLAN = "plan"
    FILE_WRITE = "file_write"
    TEST_EXECUTION = "test_execution"
    PR_CREATION = "pr_creation"
    HIGH_RISK = "high_risk"


class ApprovalStatus(str, enum.Enum):
    """审批结果。"""
    APPROVED = "approved"    # 批准，继续执行
    REJECTED = "rejected"    # 拒绝，重新规划
    CANCELLED = "cancelled"  # 取消整个任务


class Approval(Base):
    """
    approvals 表：人工审批记录（对齐需求文档 11.8 节）。

    每次审批操作（批准/拒绝/取消）对应一条记录。
    """
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    approval_type: Mapped[ApprovalType] = mapped_column(
        Enum(ApprovalType, name="approval_type"),
        nullable=False,
        default=ApprovalType.PLAN,
    )

    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"),
        nullable=False,
    )

    # 用户在审批时填写的备注，例如"注意不要改 utils.py 里的其他函数"
    user_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Approval id={self.id} task={self.task_id} "
            f"type={self.approval_type} status={self.status}>"
        )
