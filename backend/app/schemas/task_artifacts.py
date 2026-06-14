# backend/app/schemas/task_artifacts.py
# 作用：任务详情页所需的 diff / 测试 / 审批 数据结构（支撑 FR-004 前端）

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.approval import ApprovalStatus, ApprovalType


class EditHistoryItemResponse(BaseModel):
    id: int
    task_id: int
    retry_index: int
    file_path: str
    diff: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EditHistoryListResponse(BaseModel):
    task_id: int
    items: list[EditHistoryItemResponse]
    total: int
    combined_diff: str = Field(default="", description="所有 diff 合并文本")


class TestRunItemResponse(BaseModel):
    id: int
    task_id: int
    retry_index: int
    command: str
    exit_code: int
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: Optional[int] = None
    passed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TestRunListResponse(BaseModel):
    task_id: int
    items: list[TestRunItemResponse]
    total: int


class ApprovalItemResponse(BaseModel):
    id: int
    task_id: int
    approval_type: ApprovalType
    status: ApprovalStatus
    user_comment: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalListResponse(BaseModel):
    task_id: int
    items: list[ApprovalItemResponse]
    total: int


class ToolCallItemResponse(BaseModel):
    id: int
    task_id: int
    step_id: int | None
    tool_name: str
    permission_level: str
    input_summary: dict | None = None
    output_summary: dict | None = None
    status: str
    duration_ms: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ToolCallListResponse(BaseModel):
    task_id: int
    items: list[ToolCallItemResponse]
    total: int


class RetrievedContextItemResponse(BaseModel):
    id: int
    task_id: int
    file_path: str
    line_start: int
    line_end: int
    snippet: str
    score: float
    method: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RetrievedContextListResponse(BaseModel):
    task_id: int
    items: list[RetrievedContextItemResponse]
    total: int
