# backend/app/schemas/issue_analysis.py
# 作用：定义 Issue Analyst Agent 的输入和输出数据结构
#
# 为什么用 Pydantic 来约束 LLM 输出？
# LLM 的输出默认是自由文本，不稳定、难以解析。
# 用 Pydantic 定义结构后，LangChain 会把这个结构转换成 JSON Schema
# 发给 LLM，强制它按照固定格式输出，我们直接得到结构化对象，
# 不需要自己写正则或字符串解析。

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class IssueType(str, Enum):
    """
    Issue 类型枚举。
    
    使用 str 枚举的好处：序列化时直接得到字符串（"bug"），
    而不是 IssueType.BUG，方便 JSON 输出和数据库存储。
    """
    BUG = "bug"
    FEATURE = "feature"
    DOCUMENTATION = "documentation"
    REFACTOR = "refactor"
    TEST = "test"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    """
    风险等级枚举。
    
    risk_level 的作用：
    - low：小改动，改错了也容易回滚
    - medium：需要人工仔细看一下
    - high：改动影响范围广，必须人工审批
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IssueAnalysisResult(BaseModel):
    """
    Issue Analyst Agent 的输出结构。
    
    这个类定义了 Agent 分析完 issue 后必须返回的所有字段。
    Field(...) 里的 description 会被 LangChain 传给 LLM，
    告诉 LLM 每个字段的含义和要求，引导它正确填写。
    """

    issue_type: IssueType = Field(
        description=(
            "Issue 的类型。"
            "bug=缺陷修复, feature=新功能, documentation=文档, "
            "refactor=重构, test=测试, unknown=无法判断"
        )
    )

    summary: str = Field(
        description="用 1-2 句话总结 issue 的核心问题，要简洁清晰"
    )

    expected_behavior: str = Field(
        description=(
            "用户期望的正确行为是什么。"
            "如果 issue 没有明确描述，根据上下文合理推断，"
            "如果完全无法推断则填 '未明确描述'"
        )
    )

    actual_behavior: str = Field(
        description=(
            "当前实际发生的错误行为是什么。"
            "如果是 feature request 则填 '功能尚不存在'，"
            "如果无法判断则填 '未明确描述'"
        )
    )

    acceptance_criteria: List[str] = Field(
        description=(
            "验收条件列表：完成这个 issue 后，需要满足哪些条件才算成功。"
            "每条要具体可验证，比如 '调用 foo() 时不再抛出 KeyError'。"
            "至少提供 1 条，最多 5 条。"
        )
    )

    risk_level: RiskLevel = Field(
        description=(
            "修复这个 issue 的风险等级。"
            "low=改动范围小影响有限, "
            "medium=改动涉及多个模块或核心逻辑, "
            "high=改动影响全局、数据库结构或安全机制"
        )
    )

    needs_user_clarification: bool = Field(
        description=(
            "是否需要用户补充更多信息才能开始修复。"
            "如果 issue 描述过于模糊、缺少复现步骤、或者需求不明确，设为 true。"
            "如果信息足够开始分析和修复，设为 false。"
        )
    )

    clarification_questions: List[str] = Field(
        default=[],
        description=(
            "当 needs_user_clarification=true 时，列出需要用户回答的具体问题。"
            "问题要具体，不要问泛泛的问题。"
            "如果 needs_user_clarification=false，此字段留空列表。"
        )
    )


class IssueAnalysisRequest(BaseModel):
    """Issue 分析的请求体结构，用于 API 接口接收参数。"""

    issue_text: str = Field(
        description="需要分析的 GitHub Issue 原文",
        min_length=10,
    )

    repo_context: str = Field(
        default="",
        description="仓库背景信息（可选），比如项目类型、主要功能，帮助 Agent 更准确判断",
    )
