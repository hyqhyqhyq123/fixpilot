# backend/app/schemas/review.py
# 作用：定义 Reviewer Agent 的输出结构
#
# Reviewer Agent 的价值：
# 最终修改完成后，让另一个"角色"来审查 diff，
# 检查是否有越权修改、危险代码、安全问题，作为最后一道质量把关。

from typing import List, Optional
from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    """单条审查问题（对齐 FR-802 issues 数组）。"""
    type: str = Field(description="问题类型，如 scope_creep / dangerous_code")
    message: str = Field(description="问题描述")
    file: Optional[str] = Field(default=None, description="相关文件路径")


class ReviewResult(BaseModel):
    """
    Reviewer Agent 的审查结果。

    risk_level 决定了是否需要再次人工介入：
    - low：直接进入 PR Writer 环节
    - medium：显示警告，但可以继续
    - high：建议停下来人工检查
    """
    risk_level: str = Field(description="整体风险评级：low / medium / high")

    review_comments: List[str] = Field(
        default=[],
        description="审查意见列表，每条是一个具体的发现或建议",
    )

    issues: List[ReviewIssue] = Field(
        default_factory=list,
        description="结构化问题列表（FR-802）",
    )

    has_unauthorized_changes: bool = Field(
        default=False,
        description="是否修改了计划外的文件（scope creep）",
    )

    has_dangerous_code: bool = Field(
        default=False,
        description="是否包含明显危险的代码（eval、exec、os.system 等）",
    )

    has_sensitive_info: bool = Field(
        default=False,
        description="是否意外包含了敏感信息（密码、token、密钥等）",
    )

    matches_issue_goal: bool = Field(
        default=True,
        description="修改内容是否符合原始 issue 的目标",
    )

    approval_required: bool = Field(
        default=False,
        description="是否需要额外的人工审批（高风险时为 True）",
    )

    summary: str = Field(
        default="",
        description="审查结论摘要，1-2 句话总结整体评价",
    )
