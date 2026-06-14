# backend/app/models/task_github_pr.py
# 记录任务在 GitHub 上创建的 PR（FR-903）

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskGitHubPr(Base):
    __tablename__ = "task_github_prs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    pr_url: Mapped[str] = mapped_column(Text, nullable=False)
    branch_name: Mapped[str] = mapped_column(String(200), nullable=False)
    pr_title: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
