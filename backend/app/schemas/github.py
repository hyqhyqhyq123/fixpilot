# backend/app/schemas/github.py

from datetime import datetime

from pydantic import BaseModel, Field


class PatchResponse(BaseModel):
    task_id: int
    patch: str


class ReportResponse(BaseModel):
    task_id: int
    report: str | None = None


class CreatePrRequest(BaseModel):
    confirm: bool = Field(
        default=True,
        description="用户确认创建 PR（不会自动 merge）",
    )


class CreatePrResponse(BaseModel):
    task_id: int
    pr_url: str
    branch_name: str
    pr_title: str
    message: str


class TaskPrInfoResponse(BaseModel):
    task_id: int
    pr_url: str | None = None
    branch_name: str | None = None
    pr_title: str | None = None
    created_at: datetime | None = None


class GitHubIssueResponse(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str
    issue_text: str = Field(description="title + body，可直接填入任务 issue_text")
    state: str | None = None
    html_url: str
    labels: list[str] = Field(default_factory=list)


class GitHubActionsRun(BaseModel):
    id: int | None = None
    name: str
    status: str | None = None
    conclusion: str | None = None
    html_url: str | None = None
    head_branch: str | None = None
    event: str | None = None
    run_number: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GitHubActionsRunsResponse(BaseModel):
    owner: str
    repo: str
    total_count: int
    runs: list[GitHubActionsRun] = Field(default_factory=list)
