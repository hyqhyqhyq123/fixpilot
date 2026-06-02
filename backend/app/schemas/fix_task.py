# backend/app/schemas/fix_task.py
# 作用：定义 fix-tasks API 请求和响应的数据结构（对齐需求文档精简后的字段）

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.fix_task import TaskStatus


class FixTaskCreate(BaseModel):
    """
    创建任务时的请求体。
    """
    repo_url: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="GitHub 仓库地址，例如 https://github.com/owner/repo",
        examples=["https://github.com/pallets/flask"],
    )
    issue_text: str = Field(
        ...,
        min_length=10,
        description="Issue 描述",
        examples=["当用户提交空表单时程序崩溃，应该显示错误提示。"],
    )
    issue_url: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="GitHub Issue URL（可选）",
        examples=["https://github.com/pallets/flask/issues/123"],
    )
    base_branch: str = Field(
        default="main",
        max_length=100,
        description="要修改的基础分支，默认 main",
    )
    test_command: Optional[str] = Field(
        default=None,
        max_length=500,
        description="测试命令（可选，Agent 会自动检测）",
        examples=["pytest", "npm test"],
    )
    lint_command: Optional[str] = Field(
        default=None,
        max_length=500,
        description="lint 命令（可选）",
        examples=["ruff check .", "npm run lint"],
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=3,
        description="测试失败时最多自动重试次数，默认 2",
    )


class FixTaskResponse(BaseModel):
    """
    返回给前端的任务数据结构。
    """
    id: int
    repo_url: str
    issue_url: Optional[str] = None
    issue_text: str
    base_branch: str
    test_command: Optional[str] = None
    lint_command: Optional[str] = None
    status: TaskStatus
    current_agent: Optional[str] = None
    current_node: Optional[str] = None
    retry_count: int
    max_retries: int
    workspace_path: Optional[str] = None
    final_report: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FixTaskListResponse(BaseModel):
    """任务列表响应（带分页）。"""
    items: list[FixTaskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
