# backend/app/schemas/fix_task.py
# 作用：定义 API 请求和响应的数据结构（Pydantic Schema）
#
# Model 和 Schema 的区别：
# - Model（SQLAlchemy）：对应数据库表，管理数据的"存储"
# - Schema（Pydantic）：对应 API 接口，管理数据的"传输"
#
# 举例说明：
# - 用户创建任务时，请求体只需要 repo_url + issue_text（用 FixTaskCreate）
# - 服务器返回任务时，要带上 id、status、时间戳等（用 FixTaskResponse）

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.fix_task import TaskStatus


class FixTaskCreate(BaseModel):
    """
    创建任务时的请求体结构。

    用户提交这些字段，系统帮你填好 id、status、时间戳等其他字段。

    Field() 的作用：
    - description：出现在 /docs 文档里，告诉别人这个字段是干嘛的
    - min_length：自动校验，空字符串会被拒绝
    - examples：文档里的示例值
    """
    repo_url: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="GitHub 仓库地址，例如 https://github.com/owner/repo",
        examples=["https://github.com/pallets/flask"],
    )
    issue_text: str = Field(
        ...,
        min_length=10,
        description="Issue 描述：描述你发现的 bug 或想要的功能",
        examples=["当用户提交空表单时，应该显示错误提示，但现在直接崩溃了。"],
    )
    # 以下字段均为可选，Agent 会自动检测，用户也可以手动指定
    issue_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="GitHub Issue URL（可选），如 https://github.com/owner/repo/issues/123",
        examples=["https://github.com/pallets/flask/issues/123"],
    )
    base_branch: str = Field(
        default="main",
        max_length=100,
        description="要修改的基础分支，默认 main",
        examples=["main", "master", "develop"],
    )
    test_command: Optional[str] = Field(
        default=None,
        max_length=200,
        description="测试命令（可选，Agent 会自动检测）",
        examples=["pytest", "npm test", "go test ./..."],
    )
    lint_command: Optional[str] = Field(
        default=None,
        max_length=200,
        description="lint 命令（可选，Agent 会自动检测）",
        examples=["ruff check .", "npm run lint"],
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=3,
        description="测试失败时最多自动重试次数，默认 2 次，最多 3 次",
    )


class FixTaskUpdate(BaseModel):
    """
    更新任务状态时使用（Agent 内部调用，不对外暴露）。

    所有字段都是可选的，只传需要更新的字段。
    """
    status: Optional[TaskStatus] = None
    current_agent: Optional[str] = None
    current_node: Optional[str] = None
    error_message: Optional[str] = None
    workspace_path: Optional[str] = None
    final_report: Optional[str] = None
    retry_count: Optional[int] = None


class FixTaskResponse(BaseModel):
    """
    返回给前端的任务数据结构。

    包含所有字段，比 FixTaskCreate 多出 id、status、时间戳等。

    model_config 的 from_attributes=True：
    - 默认情况下 Pydantic 只能从字典创建对象
    - 设置这个后，Pydantic 可以从 SQLAlchemy 模型对象创建（直接读取属性）
    - 这样就能 FixTaskResponse.model_validate(db_task) 把数据库对象转成响应体
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
    """
    任务列表响应，带分页信息。

    为什么要分页：
    - 任务可能越来越多，一次全返回会很慢
    - 分页让前端可以按需加载
    """
    items: list[FixTaskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
