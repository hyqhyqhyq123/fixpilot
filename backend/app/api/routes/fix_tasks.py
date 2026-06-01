# backend/app/api/routes/fix_tasks.py
# 作用：定义任务相关的所有 API 接口（路由）
#
# 路由是什么？
# 路由就是"URL 路径" + "处理函数"的映射关系。
# 例如：POST /api/fix-tasks → create_task 函数
# 当客户端发请求到这个 URL，FastAPI 就调用对应函数处理。
#
# Depends(get_db) 是什么？
# 这是 FastAPI 的"依赖注入"机制。
# 意思是：在调用路由函数前，先调用 get_db() 获取数据库 session，
# 然后把 session 作为参数传给路由函数。
# 函数结束后，get_db() 里的 finally 代码会自动关闭 session。

import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.fix_task import FixTask, TaskStatus
from app.schemas.fix_task import (
    FixTaskCreate,
    FixTaskListResponse,
    FixTaskResponse,
)

logger = logging.getLogger(__name__)

# APIRouter 是 FastAPI 的路由分组工具
# prefix="/api/fix-tasks" 表示这个 router 下所有接口都以 /api/fix-tasks 开头
# tags 用于 /docs 文档分组
router = APIRouter(prefix="/api/fix-tasks", tags=["fix-tasks"])


@router.post(
    "",
    response_model=FixTaskResponse,
    status_code=status.HTTP_201_CREATED,  # 创建成功返回 201，比 200 更语义化
    summary="创建新的修复任务",
)
async def create_task(
    payload: FixTaskCreate,            # FastAPI 自动从请求体解析并验证
    db: AsyncSession = Depends(get_db),  # 依赖注入数据库 session
) -> FixTaskResponse:
    """
    创建一个新的 FixPilot 修复任务。

    用户提交 repo_url 和 issue_text，系统创建任务并返回任务详情。
    任务初始状态为 pending，等待 Agent 处理。
    """
    logger.info(f"创建新任务：repo={payload.repo_url}")

    # 创建 SQLAlchemy 模型对象（还没写入数据库）
    task = FixTask(
        repo_url=payload.repo_url,
        issue_url=payload.issue_url,
        issue_text=payload.issue_text,
        base_branch=payload.base_branch,
        test_command=payload.test_command,
        lint_command=payload.lint_command,
        max_retries=payload.max_retries,
        status=TaskStatus.PENDING,
    )

    # 写入数据库
    db.add(task)
    await db.flush()     # flush 把数据写到数据库但还没 commit，这样能拿到自增 id
    await db.refresh(task)  # 刷新对象，让时间戳等服务端生成的字段填充进来

    logger.info(f"任务创建成功：id={task.id}")

    # from_attributes=True 让 Pydantic 能从 SQLAlchemy 对象直接读取字段
    return FixTaskResponse.model_validate(task)


@router.get(
    "",
    response_model=FixTaskListResponse,
    summary="获取任务列表",
)
async def list_tasks(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页条数，最多 100"),
    status: TaskStatus | None = Query(default=None, description="按状态过滤"),
    db: AsyncSession = Depends(get_db),
) -> FixTaskListResponse:
    """
    获取所有任务列表，支持分页和状态过滤。

    Query 参数示例：
    - GET /api/fix-tasks?page=1&page_size=10
    - GET /api/fix-tasks?status=pending
    - GET /api/fix-tasks?status=running&page=2
    """
    # 构建基础查询（后面会根据过滤条件动态修改）
    query = select(FixTask)

    # 如果指定了状态过滤，加上 WHERE 条件
    if status is not None:
        query = query.where(FixTask.status == status)

    # 计算总记录数（用于分页信息）
    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    # 计算分页偏移量：第 2 页 page_size=10 → offset=10，跳过前 10 条
    offset = (page - 1) * page_size

    # 加上排序、分页，最新创建的任务排在前面
    query = query.order_by(FixTask.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    tasks = result.scalars().all()

    # math.ceil 向上取整：11 条记录每页 10 条 → 2 页
    total_pages = math.ceil(total / page_size) if total > 0 else 1

    return FixTaskListResponse(
        items=[FixTaskResponse.model_validate(t) for t in tasks],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{task_id}",
    response_model=FixTaskResponse,
    summary="获取任务详情",
)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> FixTaskResponse:
    """
    根据任务 ID 获取任务详情。

    如果任务不存在，返回 404 错误。
    """
    result = await db.execute(select(FixTask).where(FixTask.id == task_id))
    task = result.scalar_one_or_none()  # 找到一条返回对象，找不到返回 None

    if task is None:
        # 404 是标准 HTTP 状态码，表示"找不到资源"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 {task_id} 不存在",
        )

    return FixTaskResponse.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,  # 204 表示"操作成功但没有返回内容"
    summary="取消任务",
)
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    取消一个任务（只能取消 pending 或 waiting_approval 状态的任务）。

    注意：不是物理删除，而是把状态改为 cancelled。
    为什么不真正删除：保留记录方便审计和排查问题。
    """
    result = await db.execute(select(FixTask).where(FixTask.id == task_id))
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 {task_id} 不存在",
        )

    # 只有这两个状态可以取消，运行中的任务需要先停止 Agent（后续阶段再做）
    cancellable_statuses = {TaskStatus.PENDING, TaskStatus.WAITING_APPROVAL}
    if task.status not in cancellable_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"任务状态为 {task.status}，无法取消（只能取消 pending 或 waiting_approval 状态的任务）",
        )

    task.status = TaskStatus.CANCELLED
    logger.info(f"任务 {task_id} 已取消")
