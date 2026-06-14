# backend/app/schemas/workflow.py
# 作用：Workflow 控制 API 的响应结构

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def latency_ms(self) -> int | None:
        """节点耗时（毫秒），由 started_at / ended_at 计算。"""
        if not self.ended_at:
            return None
        delta = self.ended_at - self.started_at
        return int(delta.total_seconds() * 1000)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def token_usage(self) -> dict[str, int] | None:
        """LLM token 用量（仅 LLM 节点有值）。"""
        if not self.output_summary:
            return None
        usage = self.output_summary.get("token_usage")
        return usage if isinstance(usage, dict) else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def related_files(self) -> list[str]:
        """与本节点相关的文件路径列表。"""
        if not self.output_summary:
            return []
        files = self.output_summary.get("related_files")
        if not isinstance(files, list):
            return []
        return [str(f) for f in files if f]


class AgentStepListResponse(BaseModel):
    """任务步骤列表。"""
    task_id: int
    items: list[AgentStepResponse]
    total: int


class WorkflowActionResponse(BaseModel):
    """启动 / 审批 / 拒绝后的统一响应。"""
    message: str
    task: FixTaskResponse


class RollbackRetryRequest(BaseModel):
    """回滚到指定 retry_index 的请求体。"""

    retry_index: int = Field(
        ge=0,
        description="要回滚到的 retry_index；0 表示第一次 Coder 尝试结束后的文件状态",
    )


# 复用 Planner 模块里已经定义好的审批请求体
__all__ = [
    "AgentStepResponse",
    "AgentStepListResponse",
    "WorkflowActionResponse",
    "RollbackRetryRequest",
    "PlanApprovalRequest",
    "PlanRejectionRequest",
]
