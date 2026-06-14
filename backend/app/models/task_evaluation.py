# backend/app/models/task_evaluation.py
# LLM-as-Judge 任务评测结果（Phase 6 评测）

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskEvaluation(Base):
    __tablename__ = "task_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    patch_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    judge_summary: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
