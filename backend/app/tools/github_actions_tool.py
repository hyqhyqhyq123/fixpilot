# backend/app/tools/github_actions_tool.py
# Purpose: read GitHub Actions workflow run results for a public repository.

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.tools.github_pr_tool import parse_github_repo_url

logger = logging.getLogger(__name__)


async def fetch_github_actions_runs(
    repo_url: str,
    github_token: str | None = None,
    branch: str | None = None,
    per_page: int = 10,
) -> dict[str, Any]:
    """
    Read recent GitHub Actions workflow runs.

    GitHub Actions tells us whether CI passed, failed, or is still running.
    We only read status here because FixPilot should not trigger or mutate
    workflow runs without a separate, explicit approval step.
    """
    owner, repo = parse_github_repo_url(repo_url)
    safe_per_page = max(1, min(per_page, 30))
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    params: dict[str, Any] = {"per_page": safe_per_page}
    if branch:
        params["branch"] = branch

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers, params=params)

    if response.status_code == 404:
        raise LookupError("GitHub repository not found or Actions is unavailable")
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise ValueError(
            "GitHub API rate limit exceeded. Please sign in and configure a GitHub Token in Settings."
        )
    if response.status_code >= 400:
        raise ValueError(f"GitHub API {response.status_code}: {response.text[:300]}")

    data = response.json()
    runs = []
    for item in data.get("workflow_runs", []):
        runs.append(
            {
                "id": item.get("id"),
                "name": item.get("name") or item.get("display_title") or "workflow",
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "html_url": item.get("html_url"),
                "head_branch": item.get("head_branch"),
                "event": item.get("event"),
                "run_number": item.get("run_number"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )

    logger.info("Read %s GitHub Actions runs for %s/%s", len(runs), owner, repo)
    return {
        "owner": owner,
        "repo": repo,
        "total_count": data.get("total_count", len(runs)),
        "runs": runs,
    }
