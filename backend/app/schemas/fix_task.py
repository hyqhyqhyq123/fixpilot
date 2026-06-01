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
# - 如果用同一个结构，要么请求体多字段（用户不该填 id），要么响应体少字段
#
# Pydantic 的作用：
# 1. 自动验证：如果 repo_url 没填，FastAPI 会返回 422 错误，不会乱跑
# 2. 自动转换：把 Python datetime 对象序列化成 JSON 字符串
# 3. 自动文档：FastAPI 会根据 Schema 自动生成 /docs 文档

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.fix_task import TaskStatus


class FixTaskCreate(BaseModel):
    """
    创建任务时的请求体结构。

    用户提交这两个字段，系统帮你填好 id、status、时间戳等其他字段。

    Field() 的作用：
    - description：出现在 /docs 文档里，告诉别人这个字段是干嘛的
    - min_length：自动校验，空字符串会被拒绝
    - example：文档里的示例值
    """
    repo_url: str = Field(
        ...,                          # ... 表示必填
        min_length=1,
        max_length=500,
        description="GitHub 仓库地址，例如 https://github.com/owner/repo",
        examples=["https://github.com/pallets/flask"],
    )
    issue_text: str = Field(
        ...,
        min_length=10,                # issue 至少 10 个字符，防止提交空内容
        description="Issue 描述：描述你发现的 bug 或想要的功能",
        examples=["当用户提交空表单时，应该显示错误提示，但现在直接崩溃了。"],
    )


class FixTaskUpdate(BaseModel):
    """
    更新任务状态时使用（Agent 内部调用，不对外暴露）。

    所有字段都是可选的，只传需要更新的字段。
    """
    status: TaskStatus | None = None
    current_agent: str | None = None
    current_node: str | None = None
    error_message: str | None = None


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
    issue_text: str
    status: TaskStatus
    current_agent: str | None = None
    current_node: str | None = None
    error_message: str | None = None
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
    total: int                        # 总任务数
    page: int                         # 当前页码（从 1 开始）
    page_size: int                    # 每页条数
    total_pages: int                  # 总页数
