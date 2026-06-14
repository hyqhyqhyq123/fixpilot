# backend/app/api/routes/github.py
# GitHub 集成 API：读取 Issue 等（Phase 6）

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional
from app.db.session import get_db
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.github import GitHubActionsRunsResponse, GitHubIssueResponse
from app.tools.github_actions_tool import fetch_github_actions_runs
from app.tools.github_issue_tool import fetch_github_issue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github", tags=["github"])


async def _resolve_github_token(
    db: AsyncSession,
    user: User | None,
) -> str | None:
    if not user:
        return None
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    return row.github_token if row else None


@router.get(
    "/issues",
    response_model=GitHubIssueResponse,
    summary="从 GitHub Issue URL 读取标题与正文",
)
async def get_github_issue(
    url: str = Query(..., min_length=10, description="GitHub Issue URL"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> GitHubIssueResponse:
    try:
        token = await _resolve_github_token(db, user)
        data = await fetch_github_issue(url, github_token=token)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("读取 GitHub Issue 失败 url=%s", url)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取 Issue 失败：{exc}",
        ) from exc

    return GitHubIssueResponse.model_validate(data)


@router.get(
    "/actions/runs",
    response_model=GitHubActionsRunsResponse,
    summary="Read recent GitHub Actions workflow runs",
)
async def get_github_actions_runs(
    repo_url: str = Query(..., min_length=10, description="GitHub repository URL"),
    branch: str | None = Query(default=None, description="Optional branch filter"),
    per_page: int = Query(default=10, ge=1, le=30, description="Number of runs to read"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> GitHubActionsRunsResponse:
    try:
        token = await _resolve_github_token(db, user)
        data = await fetch_github_actions_runs(
            repo_url=repo_url,
            github_token=token,
            branch=branch,
            per_page=per_page,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Read GitHub Actions runs failed repo_url=%s", repo_url)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Read GitHub Actions runs failed: {exc}",
        ) from exc

    return GitHubActionsRunsResponse.model_validate(data)
