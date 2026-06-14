# backend/app/models/retrieved_context.py
# 作用：存储 Code Retriever 检索到的代码片段（对齐需求文档第 11.5 节）
#
# 为什么单独建表？
# - 一个任务可能检索到 10~20 个代码片段，放在 JSON 字段里不方便查询
# - 独立表可以按任务查询、按分数排序、在前端单独展示
# - 后续 LlamaIndex 接入后，可以在这里记录语义检索的结果

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RetrievedContext(Base):
    """
    retrieved_contexts 表：代码检索结果（对齐需求文档 11.5 节）。

    每条记录是一个检索到的代码片段。
    """
    __tablename__ = "retrieved_contexts"
    __table_args__ = (
        # 任务详情页按 task_id 查检索片段，并按 score 排序展示最相关结果。
        Index("ix_retrieved_contexts_task_score_id", "task_id", "score", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fix_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="相对于仓库根目录的文件路径"
    )
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False, comment="代码片段内容")

    # 相关度评分（0-100），越高越相关
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 检索方式：keyword（关键词）/ semantic（语义，V1）
    method: Mapped[str] = mapped_column(
        String(20), nullable=False, default="keyword"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<RetrievedContext id={self.id} task={self.task_id} "
            f"file={self.file_path} score={self.score}>"
        )
