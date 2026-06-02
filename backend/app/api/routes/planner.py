# backend/app/api/routes/planner.py
# 作用：Planner Agent 相关的 API 接口
#
# 这个接口让你可以单独测试 Planner Agent，
# 不需要跑完整工作流，方便开发调试。

import logging

from fastapi import APIRouter, HTTPException, status

from app.agents.planner import generate_fix_plan
from app.schemas.plan import FixPlan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/planner", tags=["planner"])


class PlanRequest:
    """临时用 dataclass，避免循环导入。"""
    pass


from pydantic import BaseModel, Field
from typing import Optional


class GeneratePlanRequest(BaseModel):
    """调用 Planner Agent 的请求体。"""

    issue_text: str = Field(
        ...,
        min_length=10,
        description="原始 issue 文本",
        examples=["当用户调用 foo() 传入 None 时程序崩溃，应该抛出明确的 ValueError"],
    )
    issue_analysis: Optional[dict] = Field(
        default=None,
        description="Issue Analyst Agent 的分析结果（可选，有则更准确）",
    )
    retrieved_result: Optional[dict] = Field(
        default=None,
        description="Code Retriever 的检索结果（可选，有则更准确）",
    )
    repo_analysis: Optional[dict] = Field(
        default=None,
        description="仓库分析结果（可选）",
    )


@router.post(
    "/generate",
    response_model=FixPlan,
    summary="生成代码修改计划",
)
async def generate_plan(payload: GeneratePlanRequest) -> FixPlan:
    """
    调用 Planner Agent，根据 issue 和代码检索结果生成修改计划。

    返回结构化的 FixPlan：
    - 问题总结和根因假设
    - 需要修改的文件列表（含修改理由）
    - 测试计划
    - 风险分析

    注意：Planner 只生成计划，不执行任何代码修改。
    计划需要经过人工审批后才能执行（阶段7）。
    """
    try:
        plan = generate_fix_plan(
            issue_text=payload.issue_text,
            issue_analysis=payload.issue_analysis,
            retrieved_result=payload.retrieved_result,
            repo_analysis=payload.repo_analysis,
        )
        return plan
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Planner 输出解析失败：{e}",
        )
    except Exception as e:
        logger.error(f"Planner Agent 调用失败：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Planner Agent 调用失败：{e}",
        )
