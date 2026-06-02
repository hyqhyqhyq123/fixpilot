# backend/app/models/edit_history.py
# 作用：记录每次代码修改的快照和 diff（对齐需求文档第 11.6 节）
#
# 为什么要记录修改快照？
# - Coder Agent 修改文件前，必须保存修改前的内容（before_content）
# - 修改失败时可以回滚到 before_content
# - 每次重试都是新的一条记录（retry_index 区分）
# - 前端 Diff 页面用这里的 diff 字段展示改了什么

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EditHistory(Base):
    """
    edit_history 表：代码修改历史（对齐需求文档 11.6 节）。

    一次修改对应一条记录。重试时 retry_index 递增。
    """
    __tablename__ = "edit_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # retry_index：第 0 次尝试、第 1 次重试、第 2 次重试...
    # 同一个 task_id + retry_index 可以有多条记录（修改多个文件）
    retry_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    file_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="被修改的文件路径（相对仓库根目录）"
    )

    # 修改前的完整文件内容（用于回滚）
    before_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="修改前内容（快照）"
    )
    # 修改后的完整文件内容
    after_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="修改后内容"
    )
    # unified diff 格式的差异（用于前端展示）
    diff: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="git diff 格式的差异文本"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<EditHistory id={self.id} task={self.task_id} "
            f"retry={self.retry_index} file={self.file_path}>"
        )
