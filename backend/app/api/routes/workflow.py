# backend/app/api/routes/workflow.py
# 作用：LangGraph Workflow 控制 API（对齐需求文档 12.3 节）

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.fix_task import FixTaskResponse
from app.schemas.plan import PlanApprovalRequest, PlanRejectionRequest
from app.schemas.workflow import (
    AgentStepListResponse,
    AgentStepResponse,
    WorkflowActionResponse,
)
from app.services import workflow_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fix-tasks", tags=["workflow"])


@router.post(
    "/{task_id}/start",
    response_model=WorkflowActionResponse,
    summary="启动任务 Workflow",
)
async def start_task_workflow(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    """
    启动 LangGraph Workflow，自动串联：
    clone → 分析仓库 → Issue 分析 → 代码检索 → 生成计划 → 等待审批。
    """
    try:
        task = await workflow_runner.start_workflow(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"启动任务 {task_id} Workflow 失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow 执行失败：{exc}",
        ) from exc

    return WorkflowActionResponse(
        message="Workflow 已执行至审批节点，请查看计划并审批",
        task=FixTaskResponse.model_validate(task),
    )


@router.post(
    "/{task_id}/approve",
    response_model=WorkflowActionResponse,
    summary="批准修改计划",
)
async def approve_task_plan(
    task_id: int,
    payload: PlanApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    try:
        task = await workflow_runner.approve_plan(db, task_id, payload.comment)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"审批任务 {task_id} 失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"审批失败：{exc}",
        ) from exc

    return WorkflowActionResponse(
        message="修改计划已批准",
        task=FixTaskResponse.model_validate(task),
    )


@router.post(
    "/{task_id}/reject",
    response_model=WorkflowActionResponse,
    summary="拒绝修改计划",
)
async def reject_task_plan(
    task_id: int,
    payload: PlanRejectionRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    try:
        task = await workflow_runner.reject_plan(db, task_id, payload.reason)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"拒绝任务 {task_id} 计划失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"拒绝计划失败：{exc}",
        ) from exc

    return WorkflowActionResponse(
        message="修改计划已拒绝，系统已根据反馈重新生成计划",
        task=FixTaskResponse.model_validate(task),
    )


@router.get(
    "/{task_id}/steps",
    response_model=AgentStepListResponse,
    summary="获取任务 Agent 执行步骤",
)
async def get_task_steps(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> AgentStepListResponse:
    try:
        steps = await workflow_runner.list_task_steps(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return AgentStepListResponse(
        task_id=task_id,
        items=[AgentStepResponse.model_validate(step) for step in steps],
        total=len(steps),
    )
