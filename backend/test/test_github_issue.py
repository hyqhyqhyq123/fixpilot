# backend/test/test_github_issue.py
# GitHub Issue 读取 API 测试（mock httpx）
# 运行：cd backend && python test/test_github_issue.py

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.tools import github_issue_tool

pytestmark = pytest.mark.anyio


def test_parse_issue_url():
    owner, repo, num = github_issue_tool.parse_github_issue_url(
        "https://github.com/octocat/Hello-World/issues/42"
    )
    assert owner == "octocat"
    assert repo == "Hello-World"
    assert num == 42
    print("[OK] parse_github_issue_url")


async def test_api_fetch_issue():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    mock_response.json.return_value = {
        "title": "Bug: empty input",
        "body": "Steps to reproduce...",
        "state": "open",
        "html_url": "https://github.com/octocat/Hello-World/issues/42",
        "labels": [{"name": "bug"}],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.github_issue_tool.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(
                "/api/github/issues",
                params={"url": "https://github.com/octocat/Hello-World/issues/42"},
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["title"] == "Bug: empty input"
        assert "Steps to reproduce" in data["issue_text"]
        assert data["labels"] == ["bug"]
    print("[OK] GET /api/github/issues mock 成功")


async def test_fetch_issue_uses_token_header():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    mock_response.json.return_value = {
        "title": "Bug: token auth",
        "body": "Body",
        "state": "open",
        "html_url": "https://github.com/octocat/Hello-World/issues/42",
        "labels": [],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.github_issue_tool.httpx.AsyncClient", return_value=mock_client):
        await github_issue_tool.fetch_github_issue(
            "https://github.com/octocat/Hello-World/issues/42",
            github_token="ghp_example",
        )

    headers = mock_client.get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer ghp_example"
    print("[OK] fetch_github_issue 使用 GitHub Token")


async def test_fetch_issue_rate_limit_message():
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = '{"message":"API rate limit exceeded"}'

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.github_issue_tool.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError) as exc:
            await github_issue_tool.fetch_github_issue(
                "https://github.com/octocat/Hello-World/issues/42"
            )

    assert "GitHub API 已限流" in str(exc.value)
    assert "设置页配置 GitHub Token" in str(exc.value)
    print("[OK] rate limit 错误提示友好")


async def main() -> None:
    test_parse_issue_url()
    await test_api_fetch_issue()
    await test_fetch_issue_uses_token_header()
    await test_fetch_issue_rate_limit_message()
    print("\nGitHub Issue 读取测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
