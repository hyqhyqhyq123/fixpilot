# backend/app/services/github_pr_service.py
# FR-903：创建 GitHub PR（需计划已审批 + 用户 Token）

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval, ApprovalStatus, ApprovalType
from app.models.edit_history import EditHistory
from app.models.fix_task import FixTask, TaskStatus
from app.models.task_github_pr import TaskGitHubPr
from app.models.user import User
from app.models.user_settings import UserSettings
from app.tools.github_pr_tool import (
    commit_and_push_branch,
    create_github_pull_request,
    extract_commit_message,
    extract_pr_content,
)

logger = logging.getLogger(__name__)


async def _get_task_or_raise(db: AsyncSession, task_id: int) -> FixTask:
    result = await db.execute(select(FixTask).where(FixTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise LookupError(f"任务 {task_id} 不存在")
    return task


async def ensure_task_exists(db: AsyncSession, task_id: int) -> FixTask:
    """公开接口：校验任务存在（供 API 层使用）。"""
    return await _get_task_or_raise(db, task_id)


async def _ensure_plan_approved(db: AsyncSession, task_id: int) -> None:
    result = await db.execute(
        select(Approval).where(
            Approval.task_id == task_id,
            Approval.approval_type == ApprovalType.PLAN,
            Approval.status == ApprovalStatus.APPROVED,
        )
    )
    if result.scalar_one_or_none() is None:
        raise ValueError("创建 PR 前必须先批准修改计划")


async def _get_user_github_token(db: AsyncSession, user: User) -> str:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    if not row or not row.github_token:
        raise ValueError("请先在设置页配置 GitHub Personal Access Token")
    return row.github_token


async def get_task_patch(db: AsyncSession, task_id: int) -> str:
    await _get_task_or_raise(db, task_id)
    result = await db.execute(
        select(EditHistory)
        .where(EditHistory.task_id == task_id)
        .order_by(EditHistory.created_at.asc())
    )
    items = list(result.scalars().all())
    return "\n".join(item.diff or "" for item in items if item.diff)


async def get_task_report(db: AsyncSession, task_id: int) -> str | None:
    task = await _get_task_or_raise(db, task_id)
    return task.final_report


async def get_task_pr_record(
    db: AsyncSession,
    task_id: int,
) -> TaskGitHubPr | None:
    result = await db.execute(
        select(TaskGitHubPr).where(TaskGitHubPr.task_id == task_id)
    )
    return result.scalar_one_or_none()


async def create_pull_request_for_task(
    db: AsyncSession,
    task_id: int,
    user: User,
) -> TaskGitHubPr:
    """完整流程：校验 → commit/push → GitHub API 创建 PR。"""
    task = await _get_task_or_raise(db, task_id)

    if task.status not in (TaskStatus.SUCCESS, TaskStatus.WAITING_APPROVAL):
        raise ValueError("仅 success 或 waiting_approval（diff 已批准）任务可创建 PR")

    existing = await get_task_pr_record(db, task_id)
    if existing:
        raise ValueError(f"该任务已创建 PR：{existing.pr_url}")

    await _ensure_plan_approved(db, task_id)

    if not task.workspace_path:
        raise ValueError("任务 workspace 不存在，无法 push")

    token = await _get_user_github_token(db, user)

    hist_result = await db.execute(
        select(EditHistory.file_path)
        .where(EditHistory.task_id == task_id)
        .order_by(EditHistory.created_at.asc())
    )
    file_paths = list({row[0] for row in hist_result.fetchall() if row[0]})
    if not file_paths:
        raise ValueError("没有 edit_history，无法创建 PR")

    title, body = extract_pr_content(task.final_report)
    commit_message = extract_commit_message(task.final_report)
    branch_name = f"fixpilot/task-{task_id}-{int(datetime.now(timezone.utc).timestamp())}"

    push_result = commit_and_push_branch(
        repo_path=task.workspace_path,
        branch_name=branch_name,
        commit_message=commit_message,
        file_paths=file_paths,
        github_token=token,
        repo_url=task.repo_url,
    )
    if not push_result.get("success"):
        raise ValueError(push_result.get("error") or "git push 失败")

    pr_result = await create_github_pull_request(
        owner=push_result["owner"],
        repo=push_result["repo"],
        github_token=token,
        title=title,
        body=body,
        head_branch=branch_name,
        base_branch=task.base_branch or "main",
    )
    if not pr_result.get("success"):
        raise ValueError(pr_result.get("error") or "GitHub 创建 PR 失败")

    record = TaskGitHubPr(
        task_id=task_id,
        pr_url=pr_result["pr_url"],
        branch_name=branch_name,
        pr_title=title,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.info("任务 %s 创建 PR 成功", task_id)
    return record
