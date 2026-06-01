# backend/app/models/fix_task.py
# 作用：定义 fix_tasks 数据库表的结构（SQLAlchemy ORM 模型）
#
# ORM 是什么？
# ORM（Object-Relational Mapping）= 对象关系映射
# 它的作用是：让你用 Python 类和对象操作数据库，而不用手写 SQL
# 例如：task = FixTask(repo_url="...") 然后 db.add(task)
# ORM 会自动把它变成 INSERT INTO fix_tasks (...) VALUES (...)
#
# SQLAlchemy 是 Python 最流行的 ORM 框架

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskStatus(str, enum.Enum):
    """
    任务状态枚举。

    继承 str 的原因：
    - 让状态值既是字符串又是枚举，序列化到 JSON 时直接输出字符串（如 "pending"）
    - 不继承 str 的话，JSON 序列化会报错或输出 "TaskStatus.pending"

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
    fix_tasks 数据库表的模型定义。

    每个字段对应表中的一列。
    Mapped[xxx] 是 SQLAlchemy 2.0 的新写法，表示列的 Python 类型。
    mapped_column() 定义列的数据库属性（类型、是否必须、默认值等）。
    """
    __tablename__ = "fix_tasks"

    # ── 主键 ──────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 任务输入（用户提交的内容）─────────────────────────────
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # issue_url：用户可以直接粘贴 GitHub Issue 的 URL
    # 例如 https://github.com/pallets/flask/issues/123
    # MVP 中暂时只作记录，不自动拉取 issue 内容（V1 功能）
    issue_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    issue_text: Mapped[str] = mapped_column(Text, nullable=False)

    # base_branch：要在哪个分支上修改代码，默认 main
    # 后续 Coder Agent 会基于这个分支创建新分支并提交
    base_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")

    # ── 用户自定义命令（可选，Agent 会自动检测，也可以手动指定）──
    # 为什么让用户填？有些项目测试命令不标准，Agent 自动检测可能不准
    test_command: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lint_command: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── 重试配置 ────────────────────────────────────────────
    # retry_count：当前已重试次数，每次 Coder + Tester 失败后 +1
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # max_retries：允许最多重试几次，默认 2 次
    # 为什么有上限：防止 Agent 无限循环越修越错
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    # ── 任务状态 ────────────────────────────────────────────
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        default=TaskStatus.PENDING,
        nullable=False,
    )

    # ── Agent 运行信息 ──────────────────────────────────────
    current_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── 运行结果 ────────────────────────────────────────────
    # workspace_path：clone 下来的代码存放在哪个目录
    # 存进数据库的原因：任务中断后可以恢复，知道代码在哪
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # final_report：任务完成后由 PR Writer 生成的最终报告（Markdown 格式）
    final_report: Mapped[str | None] = mapped_column(Text, nullable=True)

    # error_message：任务失败时记录错误信息
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
