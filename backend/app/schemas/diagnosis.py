# backend/app/schemas/diagnosis.py
# 作用：定义 Failure Diagnoser Agent 的输出结构
#
# 失败诊断 Agent 的核心作用：
# 不是简单的"测试失败了"，而是分析"为什么失败"、"是不是当前修改导致的"、"怎么修"。
# 这让系统能智能地决定是否重试，而不是无脑重试。

from typing import List
from pydantic import BaseModel, Field


class FailureDiagnosis(BaseModel):
    """
    Failure Diagnoser Agent 的分析结果。

    is_caused_by_current_patch 是关键字段：
    - True：失败是当前这次修改导致的，应该尝试修复
    - False：失败可能是环境问题或其他原因，不应该重试
    """
    failure_summary: str = Field(
        description="用 1-2 句话描述测试失败的表现"
    )

    likely_cause: str = Field(
        description="最可能的失败原因分析"
    )

    is_caused_by_current_patch: bool = Field(
        description=(
            "失败是否由当前这次代码修改导致。"
            "True=是当前修改引入的问题，应该继续修复；"
            "False=可能是环境、依赖或其他已有问题，不应该重试"
        )
    )

    next_fix_plan: List[str] = Field(
        default=[],
        description="下一步修复建议，每条是一个具体的修改方向",
    )

    should_retry: bool = Field(
        description=(
            "是否应该重试修复。"
            "True=应该，系统会再让 Coder 按新建议修改；"
            "False=不应该，失败超出当前能力范围"
        )
    )

    retry_hints: str = Field(
        default="",
        description="重试时给 Coder Agent 的额外提示",
    )
