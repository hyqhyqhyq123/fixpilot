# backend/app/tools/github_pr_tool.py
# 作用：在 workspace 内 commit/push，并调用 GitHub API 创建 PR（FR-903）

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_GITHUB_REPO_RE = re.compile(
    r"^https://github\.com/(?P<owner>[\w\.\-]+)/(?P<repo>[\w\.\-]+)/?$"
)


def parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    """从 repo URL 解析 owner 与 repo 名。"""
    match = _GITHUB_REPO_RE.match(repo_url.strip())
    if not match:
        raise ValueError("仅支持 https://github.com/owner/repo 格式")
    return match.group("owner"), match.group("repo")


def extract_pr_content(final_report: str | None) -> tuple[str, str]:
    """从 final_report 提取 PR 标题与正文。"""
    if not final_report:
        return "fix: FixPilot automated patch", "Automated fix by FixPilot."

    title = "fix: FixPilot automated patch"
    body = final_report

    if "## PR 草稿" in final_report:
        section = final_report.split("## PR 草稿", 1)[1].strip()
        body = section
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()[:200]
                break
            if stripped.startswith("fix:") or stripped.startswith("feat:"):
                title = stripped[:200]
                break

    return title, body[:65000]


def _sanitize_commit_message(message: str | None) -> str:
    """把 commit message 限制成安全的一行文本。"""
    cleaned = " ".join((message or "").replace("\n", " ").split())
    return cleaned.strip()[:100] or "fix: FixPilot automated patch"


def extract_commit_message(final_report: str | None) -> str:
    """从 final_report 提取显式 commit message，缺失时回退到 PR 标题。"""
    if not final_report:
        return "fix: FixPilot automated patch"

    section = final_report.split("## PR 草稿", 1)[1] if "## PR 草稿" in final_report else final_report

    fenced = re.search(
        r"## Commit Message\s*```(?:text)?\s*(?P<message>.*?)\s*```",
        section,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        return _sanitize_commit_message(fenced.group("message"))

    plain = re.search(
        r"## Commit Message\s*(?P<message>.*?)(?:\n## |\Z)",
        section,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if plain:
        for line in plain.group("message").splitlines():
            stripped = line.strip()
            if stripped:
                return _sanitize_commit_message(stripped.strip("`"))

    title, _ = extract_pr_content(final_report)
    return _sanitize_commit_message(title)


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def commit_and_push_branch(
    repo_path: str,
    branch_name: str,
    commit_message: str,
    file_paths: list[str],
    github_token: str,
    repo_url: str,
) -> dict[str, Any]:
    """
    在 workspace 创建分支、提交指定文件并 push 到 GitHub。

    为什么只 add 计划内文件：避免误提交无关改动。
    """
    root = Path(repo_path).resolve()
    if not (root / ".git").exists():
        return {"success": False, "error": f"不是 git 仓库：{repo_path}"}

    owner, repo = parse_github_repo_url(repo_url)

    _run_git(root, "config", "user.email", "fixpilot@local.dev")
    _run_git(root, "config", "user.name", "FixPilot")

    checkout = _run_git(root, "checkout", "-b", branch_name)
    if checkout.returncode != 0 and "already exists" not in (checkout.stderr or ""):
        return {
            "success": False,
            "error": checkout.stderr.strip() or checkout.stdout.strip(),
        }

    for rel_path in file_paths:
        add = _run_git(root, "add", "--", rel_path)
        if add.returncode != 0:
            return {"success": False, "error": f"git add 失败：{rel_path}"}

    status = _run_git(root, "status", "--porcelain")
    if not status.stdout.strip():
        return {"success": False, "error": "没有可提交的改动"}

    commit = _run_git(root, "commit", "-m", commit_message)
    if commit.returncode != 0:
        return {
            "success": False,
            "error": commit.stderr.strip() or commit.stdout.strip(),
        }

    authed_url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo}.git"
    push = _run_git(root, "push", authed_url, branch_name)
    if push.returncode != 0:
        err = push.stderr.strip() or push.stdout.strip()
        # 避免 token 泄露到错误信息
        err = err.replace(github_token, "***")
        return {"success": False, "error": err or "git push 失败"}

    logger.info("已 push 分支 %s 到 %s/%s", branch_name, owner, repo)
    return {"success": True, "branch_name": branch_name, "owner": owner, "repo": repo}


async def create_github_pull_request(
    owner: str,
    repo: str,
    github_token: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str,
) -> dict[str, Any]:
    """调用 GitHub REST API 创建 Pull Request（不 merge）。"""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": title[:256],
        "body": body,
        "head": head_branch,
        "base": base_branch,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code >= 400:
        detail = response.text[:500]
        logger.error("GitHub create PR 失败 status=%s", response.status_code)
        return {
            "success": False,
            "error": f"GitHub API {response.status_code}: {detail}",
        }

    data = response.json()
    return {
        "success": True,
        "pr_url": data.get("html_url"),
        "pr_number": data.get("number"),
    }
