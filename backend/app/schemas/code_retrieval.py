# backend/app/schemas/code_retrieval.py
# 作用：定义 Code Retriever Agent 的输入和输出结构
#
# 代码检索的核心思路（MVP 阶段）：
# 不把整个 repo 塞给 LLM（token 限制），而是先用关键词搜索，
# 找出最相关的代码片段，再交给 Planner Agent 生成修改计划。
# 这就像"搜索引擎"：先检索，再分析。

from typing import List, Optional
from pydantic import BaseModel, Field


class RetrievedFile(BaseModel):
    """
    一个检索到的代码文件信息。

    包含文件路径、相关代码片段、以及用什么方式找到的。
    """
    file_path: str = Field(description="文件路径（相对于仓库根目录）")
    line_start: int = Field(description="代码片段起始行号（从 1 开始）")
    line_end: int = Field(description="代码片段结束行号")
    snippet: str = Field(description="相关代码片段内容")
    matched_keywords: List[str] = Field(
        default=[],
        description="命中的关键词列表，帮助解释为什么检索到这个文件",
    )
    score: float = Field(
        default=0.0,
        description="相关度评分（0-100），用于排序",
    )


class CodeRetrievalRequest(BaseModel):
    """
    代码检索的输入。

    关键词从 issue 分析结果中提取，在仓库目录里搜索。
    """
    repo_path: str = Field(description="仓库的本地路径（workspace 下的目录）")
    keywords: List[str] = Field(description="要搜索的关键词列表")
    issue_summary: Optional[str] = Field(
        default=None,
        description="issue 摘要，用于评估文件相关度",
    )
    max_files: int = Field(
        default=10,
        ge=1,
        le=50,
        description="最多返回多少个文件，默认 10",
    )
    max_snippet_lines: int = Field(
        default=30,
        ge=5,
        le=100,
        description="每个文件最多返回多少行代码，默认 30",
    )


class CodeRetrievalResult(BaseModel):
    """
    代码检索的输出。

    retrieved_files 是按相关度排序的文件列表，越靠前越相关。
    """
    retrieved_files: List[RetrievedFile] = Field(
        default=[],
        description="检索到的相关文件列表，按相关度降序排列",
    )
    total_searched_files: int = Field(
        default=0,
        description="本次搜索扫描的文件总数",
    )
    keywords_used: List[str] = Field(
        default=[],
        description="实际使用的关键词列表",
    )
    search_method: str = Field(
        default="keyword",
        description="搜索方式：keyword（关键词）或 semantic（语义，未来版本）",
    )
