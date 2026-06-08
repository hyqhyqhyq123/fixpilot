# backend/app/schemas/code_retrieval.py
# 作用：定义 Code Retriever Agent 的输入和输出结构
#
# 为什么用 Pydantic schema？
# - 保证 API 接口的输入/输出格式固定，避免字段缺失或类型错误
# - FastAPI 用它自动生成文档和做参数校验
# - 同时也是 Agent 之间传递数据的"合同"

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class RetrievedFile(BaseModel):
    """
    一个检索到的代码文件信息。

    包含文件路径、相关代码片段、语义相关度评分，
    以及用什么方式找到的（keyword / semantic）。
    """
    file_path: str = Field(description="文件路径（相对于仓库根目录）")
    line_start: int = Field(description="代码片段起始行号（从 1 开始）")
    line_end: int = Field(description="代码片段结束行号")
    snippet: str = Field(description="相关代码片段内容")
    matched_keywords: List[str] = Field(
        default=[],
        description="命中的关键词列表（关键词搜索时使用，语义检索时为空）",
    )
    score: float = Field(
        default=0.0,
        description="相关度评分，语义检索时为余弦相似度（0~1），关键词检索时为自定义评分",
    )
    method: Literal["keyword", "semantic", "hybrid"] = Field(
        default="semantic",
        description="检索方式：keyword（关键词）/ semantic（语义）/ hybrid（混合）",
    )


class CodeRetrievalRequest(BaseModel):
    """
    代码检索的输入参数。

    语义检索模式（默认）：
    - 提供 repo_path + query_text（或 issue_summary）即可
    - 系统会自动构建/加载向量索引并进行语义搜索

    关键词检索模式：
    - 提供 repo_path + keywords
    - 系统直接在文件内容里搜索字符串

    混合模式：
    - 同时提供 query_text 和 keywords，结果合并去重
    """
    repo_path: str = Field(description="仓库的本地路径（workspace 下的目录）")

    # ── 语义检索参数 ──
    query_text: Optional[str] = Field(
        default=None,
        description="语义检索的查询文本，通常是完整的 issue_text 或 issue 摘要",
    )
    issue_summary: Optional[str] = Field(
        default=None,
        description="issue 摘要，query_text 为空时作为备选查询文本",
    )

    # ── 关键词检索参数（可选，向后兼容）──
    keywords: List[str] = Field(
        default=[],
        description="关键词列表（关键词检索模式使用）",
    )

    # ── 检索策略 ──
    search_method: Literal["keyword", "semantic", "hybrid"] = Field(
        default="semantic",
        description="检索策略：semantic（默认）/ keyword / hybrid（两者合并）",
    )

    # ── 结果控制 ──
    max_files: int = Field(
        default=10,
        ge=1,
        le=50,
        description="最多返回多少个代码片段，默认 10",
    )
    max_snippet_lines: int = Field(
        default=50,
        ge=5,
        le=200,
        description="每个片段最多返回多少行代码（仅关键词检索时生效），默认 50",
    )


class CodeRetrievalResult(BaseModel):
    """
    代码检索的输出。

    retrieved_files 按相关度降序排列，越靠前越相关。
    语义检索的 score 是余弦相似度（0~1），值越大越相关。
    """
    retrieved_files: List[RetrievedFile] = Field(
        default=[],
        description="检索到的相关代码片段列表，按相关度降序排列",
    )
    total_searched_files: int = Field(
        default=0,
        description="本次扫描的文件总数（关键词检索时有值，语义检索时为 0）",
    )
    keywords_used: List[str] = Field(
        default=[],
        description="实际使用的关键词列表（关键词检索时有值）",
    )
    search_method: str = Field(
        default="semantic",
        description="实际使用的检索方式：keyword / semantic / hybrid",
    )
