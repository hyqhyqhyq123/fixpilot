# backend/app/models/test_run.py
# 作用：记录每次测试执行的完整结果（对齐需求文档第 11.7 节）
#
# 为什么单独建表？
# - 每次重试都会跑一次测试，需要保存每次的完整日志
# - Failure Diagnoser 需要读取 stdout/stderr 来分析失败原因
# - 前端测试页面展示所有历史测试记录

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TestRun(Base):
    """
    test_runs 表：测试执行记录（对齐需求文档 11.7 节）。

    每次运行测试命令对应一条记录。
    """
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    retry_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="第几次尝试（0=初次，1=第一次重试...）"
    )

    command: Mapped[str] = mapped_column(
        Text, nullable=False, comment="实际执行的测试命令，例如 pytest tests/"
    )

    # exit_code = 0 表示测试全部通过；非 0 表示有失败
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)

    stdout: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="标准输出（测试框架的输出）"
    )
    stderr: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="标准错误（崩溃、异常等）"
    )

    # 耗时（毫秒），用于性能分析和超时检测
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 方便快速查询是否通过（比 exit_code == 0 更直观）
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TestRun id={self.id} task={self.task_id} "
            f"retry={self.retry_index} passed={self.passed}>"
        )
