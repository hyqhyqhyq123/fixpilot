# backend/app/api/routes/workflow.py
# 作用：LangGraph Workflow 控制 API（对齐需求文档 12.3 节）

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.task_evaluation import TaskEvaluation
from app.models.user import User
from app.schemas.evaluation import EvaluationDetailResponse, EvaluationRunResponse
from app.schemas.fix_task import FixTaskResponse
from app.schemas.github import (
    CreatePrRequest,
    CreatePrResponse,
    PatchResponse,
    ReportResponse,
    TaskPrInfoResponse,
)
from app.schemas.plan import PlanApprovalRequest, PlanRejectionRequest
from app.schemas.task_artifacts import (
    ApprovalItemResponse,
    ApprovalListResponse,
    EditHistoryItemResponse,
    EditHistoryListResponse,
    RetrievedContextItemResponse,
    RetrievedContextListResponse,
    TestRunItemResponse,
    TestRunListResponse,
    ToolCallItemResponse,
    ToolCallListResponse,
)
from app.schemas.workflow import (
    AgentStepListResponse,
    AgentStepResponse,
    RollbackRetryRequest,
    WorkflowActionResponse,
)
from app.services import evaluation_service, github_pr_service, workflow_queue, workflow_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fix-tasks", tags=["workflow"])


def _evaluation_to_response(record: TaskEvaluation) -> EvaluationRunResponse:
    details = None
    if record.details_json:
        try:
            details = json.loads(record.details_json)
        except json.JSONDecodeError:
            details = None
    return EvaluationRunResponse(
        task_id=record.task_id,
        overall_score=record.overall_score,
        patch_score=record.patch_score,
        plan_score=record.plan_score,
        test_score=record.test_score,
        judge_summary=record.judge_summary,
        details=details,
        created_at=record.created_at,
    )


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

    启用 Celery 时在后台执行，API 立即返回。
    """
    try:
        if workflow_queue.celery_enabled():
            task = await workflow_queue.mark_task_running(db, task_id)
            workflow_queue.dispatch_start_workflow(task_id)
            message = "Workflow 已在后台启动，请刷新查看进度"
        else:
            task = await workflow_runner.start_workflow(db, task_id)
            message = "Workflow 已执行至审批节点，请查看计划并审批"
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
        message=message,
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
        if workflow_queue.celery_enabled():
            workflow_queue.dispatch_approve_plan(task_id, payload.comment)
            task = await workflow_runner.ensure_task_exists(db, task_id)
            message = "计划已批准，Coder/Tester 正在后台执行"
        else:
            task = await workflow_runner.approve_plan(db, task_id, payload.comment)
            message = "修改计划已批准，Coder 与 Tester 已执行完毕"
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
        message=message,
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
        if workflow_queue.celery_enabled():
            workflow_queue.dispatch_reject_plan(task_id, payload.reason)
            task = await workflow_runner.ensure_task_exists(db, task_id)
            message = "计划已拒绝，正在后台重新规划"
        else:
            task = await workflow_runner.reject_plan(db, task_id, payload.reason)
            message = "修改计划已拒绝，系统已根据反馈重新生成计划"
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
        message=message,
        task=FixTaskResponse.model_validate(task),
    )


@router.post(
    "/{task_id}/retry",
    response_model=WorkflowActionResponse,
    summary="重试失败任务",
)
async def retry_failed_task(
    task_id: int,
    payload: PlanApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    try:
        if workflow_queue.celery_enabled():
            task = await workflow_queue.mark_failed_task_retrying(db, task_id)
            workflow_queue.dispatch_retry_failed_workflow(task_id, payload.comment)
            message = "失败任务已进入后台重试"
        else:
            task = await workflow_runner.retry_failed_workflow(
                db,
                task_id,
                payload.comment,
            )
            message = "失败任务已重试"
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("重试任务 %s 失败", task_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"重试失败：{exc}",
        ) from exc

    return WorkflowActionResponse(
        message=message,
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


@router.get(
    "/{task_id}/edit-history",
    response_model=EditHistoryListResponse,
    summary="获取任务代码修改历史（diff）",
)
async def get_task_edit_history(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> EditHistoryListResponse:
    try:
        items, combined = await workflow_runner.list_edit_history(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return EditHistoryListResponse(
        task_id=task_id,
        items=[EditHistoryItemResponse.model_validate(i) for i in items],
        total=len(items),
        combined_diff=combined,
    )


@router.get(
    "/{task_id}/test-runs",
    response_model=TestRunListResponse,
    summary="获取任务测试运行记录",
)
async def get_task_test_runs(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> TestRunListResponse:
    try:
        items = await workflow_runner.list_test_runs(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return TestRunListResponse(
        task_id=task_id,
        items=[TestRunItemResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.get(
    "/{task_id}/approvals",
    response_model=ApprovalListResponse,
    summary="获取任务审批记录",
)
async def get_task_approvals(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApprovalListResponse:
    try:
        items = await workflow_runner.list_approvals(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ApprovalListResponse(
        task_id=task_id,
        items=[ApprovalItemResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.get(
    "/{task_id}/tool-calls",
    response_model=ToolCallListResponse,
    summary="获取任务工具调用审计记录",
)
async def get_task_tool_calls(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> ToolCallListResponse:
    try:
        items = await workflow_runner.list_tool_calls(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ToolCallListResponse(
        task_id=task_id,
        items=[ToolCallItemResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.get(
    "/{task_id}/retrieved-contexts",
    response_model=RetrievedContextListResponse,
    summary="获取任务代码检索结果",
)
async def get_task_retrieved_contexts(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> RetrievedContextListResponse:
    try:
        items = await workflow_runner.list_retrieved_contexts(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return RetrievedContextListResponse(
        task_id=task_id,
        items=[RetrievedContextItemResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.post(
    "/{task_id}/rollback-retry",
    response_model=WorkflowActionResponse,
    summary="回滚到指定 retry step",
)
async def rollback_task_retry_step(
    task_id: int,
    payload: RollbackRetryRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    try:
        task = await workflow_runner.rollback_to_retry_step(
            db,
            task_id,
            payload.retry_index,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return WorkflowActionResponse(
        message=f"任务已回滚到 retry_index={payload.retry_index}",
        task=FixTaskResponse.model_validate(task),
    )


@router.post(
    "/{task_id}/cancel",
    response_model=WorkflowActionResponse,
    summary="取消任务（Workflow 串联）",
)
async def cancel_task_workflow(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    try:
        task = await workflow_runner.cancel_workflow(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return WorkflowActionResponse(
        message="任务已取消",
        task=FixTaskResponse.model_validate(task),
    )


@router.post(
    "/{task_id}/approve-diff",
    response_model=WorkflowActionResponse,
    summary="批准高风险 diff（二次审批）",
)
async def approve_diff(
    task_id: int,
    payload: PlanApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    try:
        if workflow_queue.celery_enabled():
            workflow_queue.dispatch_approve_diff(task_id, payload.comment)
            task = await workflow_runner.ensure_task_exists(db, task_id)
            message = "diff 已批准，PR 草稿正在后台生成"
        else:
            task = await workflow_runner.approve_diff_review(db, task_id, payload.comment)
            message = "diff 已批准，PR 草稿已生成"
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return WorkflowActionResponse(
        message=message,
        task=FixTaskResponse.model_validate(task),
    )


@router.post(
    "/{task_id}/reject-diff",
    response_model=WorkflowActionResponse,
    summary="拒绝高风险 diff",
)
async def reject_diff(
    task_id: int,
    payload: PlanRejectionRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    try:
        if workflow_queue.celery_enabled():
            workflow_queue.dispatch_reject_diff(task_id, payload.reason)
            task = await workflow_runner.ensure_task_exists(db, task_id)
            message = "diff 已拒绝，正在后台更新任务状态"
        else:
            task = await workflow_runner.reject_diff_review(db, task_id, payload.reason)
            message = "diff 已拒绝"
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return WorkflowActionResponse(
        message=message,
        task=FixTaskResponse.model_validate(task),
    )


@router.get(
    "/{task_id}/patch",
    response_model=PatchResponse,
    summary="下载任务 patch（combined diff）",
)
async def get_task_patch(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> PatchResponse:
    try:
        patch = await github_pr_service.get_task_patch(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PatchResponse(task_id=task_id, patch=patch)


@router.get(
    "/{task_id}/report",
    response_model=ReportResponse,
    summary="获取任务最终报告",
)
async def get_task_report(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    try:
        report = await github_pr_service.get_task_report(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ReportResponse(task_id=task_id, report=report)


@router.get(
    "/{task_id}/github-pr",
    response_model=TaskPrInfoResponse,
    summary="查询任务是否已创建 GitHub PR",
)
async def get_task_github_pr(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> TaskPrInfoResponse:
    try:
        await github_pr_service.ensure_task_exists(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    record = await github_pr_service.get_task_pr_record(db, task_id)
    if not record:
        return TaskPrInfoResponse(task_id=task_id)
    return TaskPrInfoResponse(
        task_id=task_id,
        pr_url=record.pr_url,
        branch_name=record.branch_name,
        pr_title=record.pr_title,
        created_at=record.created_at,
    )


@router.post(
    "/{task_id}/create-pr",
    response_model=CreatePrResponse,
    summary="创建 GitHub Pull Request（需登录 + Token）",
)
async def create_task_github_pr(
    task_id: int,
    payload: CreatePrRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreatePrResponse:
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请确认 create_pr（confirm=true）",
        )
    try:
        record = await github_pr_service.create_pull_request_for_task(db, task_id, user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("创建 PR 失败 task_id=%s", task_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建 PR 失败：{exc}",
        ) from exc

    return CreatePrResponse(
        task_id=task_id,
        pr_url=record.pr_url,
        branch_name=record.branch_name,
        pr_title=record.pr_title,
        message="Pull Request 已创建（未自动 merge）",
    )


@router.post(
    "/{task_id}/evaluate",
    response_model=EvaluationRunResponse,
    summary="LLM-as-Judge 自动评测任务",
)
async def evaluate_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> EvaluationRunResponse:
    try:
        record = await evaluation_service.run_task_evaluation(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("评测任务 %s 失败", task_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"评测失败：{exc}",
        ) from exc
    return _evaluation_to_response(record)


@router.get(
    "/{task_id}/evaluation",
    response_model=EvaluationDetailResponse,
    summary="获取任务最新评测结果",
)
async def get_task_evaluation(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> EvaluationDetailResponse:
    try:
        record = await evaluation_service.get_latest_evaluation(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return EvaluationDetailResponse(
        task_id=task_id,
        evaluation=_evaluation_to_response(record) if record else None,
    )
