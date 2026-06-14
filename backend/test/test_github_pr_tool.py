# backend/test/test_github_pr_tool.py
# GitHub PR 工具单元测试（mock subprocess / httpx）
# 运行：cd backend && python test/test_github_pr_tool.py

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools import github_pr_tool

pytestmark = pytest.mark.anyio


def test_parse_github_repo_url():
    owner, repo = github_pr_tool.parse_github_repo_url(
        "https://github.com/octocat/Hello-World"
    )
    assert owner == "octocat"
    assert repo == "Hello-World"
    print("[OK] parse_github_repo_url")


def test_parse_github_repo_url_invalid():
    try:
        github_pr_tool.parse_github_repo_url("https://gitlab.com/a/b")
        assert False, "应抛出 ValueError"
    except ValueError:
        pass
    print("[OK] parse_github_repo_url 非法 URL")


def test_extract_pr_content_from_report():
    report = """## PR 草稿

# fix: handle empty input
Body line 1
Body line 2
"""
    title, body = github_pr_tool.extract_pr_content(report)
    assert title == "fix: handle empty input"
    assert "Body line 1" in body
    print("[OK] extract_pr_content 从 PR 草稿提取")


def test_extract_pr_content_empty():
    title, body = github_pr_tool.extract_pr_content(None)
    assert "FixPilot" in title
    assert body
    print("[OK] extract_pr_content 空报告默认值")


def test_extract_commit_message_from_report():
    report = """修复流程已完成

---
## PR 草稿

# fix: fallback title

## Commit Message
```text
fix: handle empty input in validator
```

## Summary
Body line
"""
    message = github_pr_tool.extract_commit_message(report)
    assert message == "fix: handle empty input in validator"
    print("[OK] extract_commit_message 提取显式 commit message")


def test_extract_commit_message_fallback_to_title():
    report = """## PR 草稿

# fix: fallback title

## Summary
Body line
"""
    message = github_pr_tool.extract_commit_message(report)
    assert message == "fix: fallback title"
    print("[OK] extract_commit_message 回退到 PR 标题")


def test_commit_and_push_branch_success(tmp_path: Path | None = None):
    root = Path(__file__).parent / "_gh_pr_tmp"
    root.mkdir(exist_ok=True)
    (root / ".git").mkdir(exist_ok=True)
    sample = root / "foo.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    def fake_run(cmd, cwd, capture_output, text, timeout, check):
        args = cmd[1:] if cmd[0] == "git" else cmd
        if args[:2] == ["checkout", "-b"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[:1] == ["add"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[:1] == ["status"]:
            return MagicMock(returncode=0, stdout="M foo.py\n", stderr="")
        if args[:1] == ["commit"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[:1] == ["push"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[:2] == ["config", "user.email"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[:2] == ["config", "user.name"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("app.tools.github_pr_tool.subprocess.run", side_effect=fake_run):
        result = github_pr_tool.commit_and_push_branch(
            repo_path=str(root),
            branch_name="fixpilot/test-branch",
            commit_message="fix: test",
            file_paths=["foo.py"],
            github_token="ghp_testtoken",
            repo_url="https://github.com/octocat/Hello-World",
        )
    assert result["success"] is True
    assert result["owner"] == "octocat"
    assert result["repo"] == "Hello-World"
    print("[OK] commit_and_push_branch mock 成功")


async def test_create_github_pull_request_success():
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.text = ""
    mock_response.json.return_value = {
        "html_url": "https://github.com/octocat/Hello-World/pull/1",
        "number": 1,
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.github_pr_tool.httpx.AsyncClient", return_value=mock_client):
        result = await github_pr_tool.create_github_pull_request(
            owner="octocat",
            repo="Hello-World",
            github_token="ghp_test",
            title="fix: test",
            body="body",
            head_branch="fixpilot/test",
            base_branch="main",
        )

    assert result["success"] is True
    assert "pull/1" in result["pr_url"]
    print("[OK] create_github_pull_request mock 成功")


async def main() -> None:
    test_parse_github_repo_url()
    test_parse_github_repo_url_invalid()
    test_extract_pr_content_from_report()
    test_extract_pr_content_empty()
    test_extract_commit_message_from_report()
    test_extract_commit_message_fallback_to_title()
    test_commit_and_push_branch_success()
    await test_create_github_pull_request_success()
    print("\nGitHub PR 工具测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
