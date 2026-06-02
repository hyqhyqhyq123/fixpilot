# backend/app/schemas/plan.py
# 作用：定义 Planner Agent 的输出结构（修改计划）
#
# 为什么要先计划再执行？
# 直接让 LLM 改代码很危险：可能改错地方、改太多、改出 bug。
# 先让 Planner 生成"修改计划"，人工审批后再让 Coder 执行。
# 这就像装修前先出设计图，确认后再动工。

from typing import List, Optional
from pydantic import BaseModel, Field


class PlannedFileChange(BaseModel):
    """
    计划修改的单个文件信息。

    为什么要说明 reason？
    让 Coder Agent 和人工审批者都能理解为什么要改这个文件，
    不只是告诉它"改这个文件"，而是"为什么改、改什么部分"。
    """
    path: str = Field(description="文件路径（相对于仓库根目录）")
    reason: str = Field(description="为什么要修改这个文件，改动的理由")
    planned_changes: List[str] = Field(
        description="具体的修改点列表，每条说明一个修改操作",
    )
    is_new_file: bool = Field(
        default=False,
        description="是否是新建文件（True）还是修改已有文件（False）",
    )


class FixPlan(BaseModel):
    """
    Planner Agent 生成的完整修改计划。

    这是整个工作流的核心文档：
    - 人工审批时查看它，决定是否批准
    - Coder Agent 执行时按它操作
    - Reviewer Agent 审查时对照它验证

    requires_approval 永远是 True，MVP 中所有计划都必须人工审批。
    """
    problem_summary: str = Field(description="用 1-2 句话描述问题的本质")

    root_cause_hypothesis: str = Field(
        description="基于代码检索结果，对问题根本原因的分析和假设"
    )

    files_to_modify: List[PlannedFileChange] = Field(
        default=[],
        description="需要修改的现有文件列表",
    )

    files_to_add: List[PlannedFileChange] = Field(
        default=[],
        description="需要新建的文件列表",
    )

    test_plan: List[str] = Field(
        description="验证修改是否正确的测试步骤"
    )

    risk_analysis: str = Field(
        description="这个修改可能带来的风险说明"
    )

    requires_approval: bool = Field(
        default=True,
        description="是否需要人工审批（MVP 阶段永远是 True）",
    )

    estimated_complexity: str = Field(
        default="medium",
        description="预估修改复杂度：low / medium / high",
    )


class PlanApprovalRequest(BaseModel):
    """
    审批修改计划时的请求体。

    审批时可以添加备注，告诉 Coder Agent 注意什么。
    """
    comment: Optional[str] = Field(
        default=None,
        description="审批备注（可选），例如'注意不要改 utils.py 里的其他函数'",
    )


class PlanRejectionRequest(BaseModel):
    """
    拒绝修改计划时的请求体。

    reason 帮助系统记录为什么被拒绝，后续可用于改进 Planner。
    """
    reason: str = Field(
        description="拒绝原因，帮助了解为什么计划不可接受",
    )
