# backend/app/schemas/workflow.py
# 作用：Workflow 控制 API 的响应结构

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.agent_step import StepStatus
from app.schemas.fix_task import FixTaskResponse
from app.schemas.plan import PlanApprovalRequest, PlanRejectionRequest


class AgentStepResponse(BaseModel):
    """单个 Agent 执行步骤。"""
    id: int
    task_id: int
    agent_name: str
    node_name: str
    status: StepStatus
    input_summary: Optional[dict[str, Any]] = None
    output_summary: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentStepListResponse(BaseModel):
    """任务步骤列表。"""
    task_id: int
    items: list[AgentStepResponse]
    total: int


class WorkflowActionResponse(BaseModel):
    """启动 / 审批 / 拒绝后的统一响应。"""
    message: str
    task: FixTaskResponse


# 复用 Planner 模块里已经定义好的审批请求体
__all__ = [
    "AgentStepResponse",
    "AgentStepListResponse",
    "WorkflowActionResponse",
    "PlanApprovalRequest",
    "PlanRejectionRequest",
]
