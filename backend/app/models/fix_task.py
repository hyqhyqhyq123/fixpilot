# backend/app/models/fix_task.py
# 作用：定义 fix_tasks 数据库表（对齐需求文档第 11.2 节）
#
# ORM 是什么？
# ORM（Object-Relational Mapping）= 对象关系映射
# 让你用 Python 类操作数据库，不用手写 SQL。

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskStatus(str, enum.Enum):
    """
    任务状态枚举。

    状态流转图：
    pending → running → waiting_approval → running → success
                      ↘                            ↘ failed
                       → failed
                       → cancelled
    """
    PENDING = "pending"                    # 任务刚创建，还没开始
    RUNNING = "running"                    # Agent 正在运行
    WAITING_APPROVAL = "waiting_approval"  # 等待用户审批修改计划
    SUCCESS = "success"                    # 全部完成
    FAILED = "failed"                      # 执行失败
    CANCELLED = "cancelled"                # 用户取消


class FixTask(Base):
    """
    fix_tasks 数据库表（对齐需求文档 11.2 节）。

    字段说明见需求文档表格，每个字段都有对应的用途注释。
    """
    __tablename__ = "fix_tasks"

    # ── 主键 ──────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 任务输入 ───────────────────────────────────────────────
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    issue_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_text: Mapped[str] = mapped_column(Text, nullable=False)

    # base_branch：要修改的基础分支，默认 main
    base_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")

    # 用户可选手动指定，Agent 也会自动检测
    test_command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lint_command: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── 任务状态 ────────────────────────────────────────────
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        default=TaskStatus.PENDING,
        nullable=False,
    )

    # ── Agent 运行信息 ──────────────────────────────────────
    current_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── 重试配置 ────────────────────────────────────────────
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    # ── workspace 路径 ────────────────────────────────────
    # clone 下来的代码存在这里，Agent 在这里读写文件
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 最终输出 ───────────────────────────────────────────
    # PR Writer 生成的 Markdown 格式最终报告
    final_report: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 任务失败时的错误信息
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 时间戳 ──────────────────────────────────────────────
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

    def __repr__(self) -> str:
        return f"<FixTask id={self.id} status={self.status} repo={self.repo_url}>"
