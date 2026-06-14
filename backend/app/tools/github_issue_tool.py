# backend/app/tools/github_issue_tool.py
# 从 GitHub REST API 读取 public issue 内容（Phase 6 / §5.2 #3）

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ISSUE_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[\w\.\-]+)/(?P<repo>[\w\.\-]+)/issues/(?P<number>\d+)/?$"
)


def parse_github_issue_url(issue_url: str) -> tuple[str, str, int]:
    match = _ISSUE_URL_RE.match(issue_url.strip())
    if not match:
        raise ValueError("仅支持 https://github.com/owner/repo/issues/123 格式")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


async def fetch_github_issue(
    issue_url: str,
    github_token: str | None = None,
) -> dict[str, Any]:
    """
    调用 GitHub API 获取 issue 标题与正文。

    public repo 可无 Token；配置 Token 可提高 rate limit。
    """
    owner, repo, number = parse_github_issue_url(issue_url)
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)

    if response.status_code == 404:
        raise LookupError("GitHub Issue 不存在或无权访问")
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise ValueError(
            "GitHub API 已限流。请登录 FixPilot，并在设置页配置 GitHub Token 后重试；"
            "或者先手动填写 Issue 描述。"
        )
    if response.status_code >= 400:
        raise ValueError(f"GitHub API {response.status_code}: {response.text[:300]}")

    data = response.json()
    body = (data.get("body") or "").strip()
    title = (data.get("title") or "").strip()
    combined_text = f"{title}\n\n{body}".strip() if body else title

    return {
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": title,
        "body": body,
        "issue_text": combined_text,
        "state": data.get("state"),
        "html_url": data.get("html_url") or issue_url,
        "labels": [label.get("name") for label in data.get("labels", []) if label.get("name")],
    }
