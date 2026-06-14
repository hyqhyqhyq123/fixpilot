# backend/app/models/workflow_checkpoint.py
# Purpose: persist the latest LangGraph State snapshot for each task.

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowCheckpoint(Base):
    """
    workflow_checkpoints stores one durable State snapshot per task.

    LangGraph's MemorySaver is useful while the process is alive, but it is
    intentionally in-memory. This table gives FixPilot a simple database-backed
    restore point when the API process restarts before the user approves a plan.
    """

    __tablename__ = "workflow_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
