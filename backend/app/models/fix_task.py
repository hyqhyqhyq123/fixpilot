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

from sqlalchemy import DateTime, Enum, String, Text, func
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
    PENDING = "pending"                  # 任务刚创建，还没开始
    RUNNING = "running"                  # Agent 正在运行
    WAITING_APPROVAL = "waiting_approval"  # 等待用户审批修改计划
    SUCCESS = "success"                  # 全部完成
    FAILED = "failed"                    # 执行失败
    CANCELLED = "cancelled"              # 用户取消


class FixTask(Base):
    """
    fix_tasks 数据库表的模型定义。

    每个字段对应表中的一列。
    Mapped[xxx] 是 SQLAlchemy 2.0 的新写法，表示列的 Python 类型。
    mapped_column() 定义列的数据库属性（类型、是否必须、默认值等）。
    """
    __tablename__ = "fix_tasks"  # 数据库中的表名

    # ── 主键 ──────────────────────────────────────────────────
    # 使用自增整数作为主键，简单可靠
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 任务输入 ───────────────────────────────────────────────
    # repo_url: 用户提交的 GitHub 仓库地址
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # issue_text: 用户描述的问题，可能很长，用 Text 类型（无长度限制）
    issue_text: Mapped[str] = mapped_column(Text, nullable=False)

    # ── 任务状态 ───────────────────────────────────────────────
    # status: 当前任务阶段，用枚举限制合法值，防止乱填
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),  # name 是数据库中枚举类型的名字
        default=TaskStatus.PENDING,
        nullable=False,
    )

    # ── Agent 运行信息 ─────────────────────────────────────────
    # current_agent: 当前正在运行的 Agent 名称（如 "IssueAnalystAgent"）
    # 为什么要记录：方便前端显示"当前在做什么"，也方便调试
    current_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # current_node: LangGraph 中当前所在的节点名称（如 "analyze_issue"）
    # 为什么要记录：比 current_agent 更细粒度，可以精确知道 workflow 走到哪一步
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── 错误信息 ───────────────────────────────────────────────
    # 任务失败时，记录错误信息方便排查
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 时间戳 ────────────────────────────────────────────────
    # server_default=func.now() 表示插入时由数据库自动填入当前时间
    # 为什么用数据库时间而不是 Python 时间：多个服务器时时钟一致，数据库时间更可靠
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # onupdate=func.now() 表示每次更新记录时自动刷新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        """让 print(task) 输出有意义的内容，方便调试。"""
        return f"<FixTask id={self.id} status={self.status} repo={self.repo_url}>"
