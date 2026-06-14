"""任务状态流转审计表。

这个表回答的是：任务从哪个状态变到哪个状态、由哪个动作触发。
面试里如果被问“状态机会不会被绕过”，这张表就是可查询证据。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskStatusTransition(Base):
    __tablename__ = "task_status_transitions"
    __table_args__ = (
        Index("ix_task_status_transitions_task_created", "task_id", "created_at"),
        Index("ix_task_status_transitions_from_to", "from_status", "to_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
