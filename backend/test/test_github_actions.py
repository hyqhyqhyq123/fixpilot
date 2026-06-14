# backend/test/test_github_actions.py
# Purpose: verify GitHub Actions result reading without real GitHub network calls.

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.tools import github_actions_tool

pytestmark = pytest.mark.anyio


async def _test_fetch_actions_runs_shape_and_params():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    mock_response.json.return_value = {
        "total_count": 1,
        "workflow_runs": [
            {
                "id": 123,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/octocat/Hello-World/actions/runs/123",
                "head_branch": "main",
                "event": "push",
                "run_number": 7,
                "created_at": "2026-06-12T01:00:00Z",
                "updated_at": "2026-06-12T01:02:00Z",
            }
        ],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.github_actions_tool.httpx.AsyncClient", return_value=mock_client):
        data = await github_actions_tool.fetch_github_actions_runs(
            repo_url="https://github.com/octocat/Hello-World",
            github_token="ghp_example",
            branch="main",
            per_page=5,
        )

    assert data["owner"] == "octocat"
    assert data["repo"] == "Hello-World"
    assert data["total_count"] == 1
    assert data["runs"][0]["name"] == "CI"
    assert data["runs"][0]["conclusion"] == "success"

    kwargs = mock_client.get.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer ghp_example"
    assert kwargs["params"] == {"per_page": 5, "branch": "main"}


def test_fetch_actions_runs_shape_and_params():
    asyncio.run(_test_fetch_actions_runs_shape_and_params())


async def _test_api_fetch_actions_runs():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    mock_response.json.return_value = {
        "total_count": 1,
        "workflow_runs": [
            {
                "id": 456,
                "name": "Python tests",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/octocat/Hello-World/actions/runs/456",
                "head_branch": "fixpilot/patch",
                "event": "pull_request",
                "run_number": 8,
                "created_at": "2026-06-12T02:00:00Z",
                "updated_at": "2026-06-12T02:03:00Z",
            }
        ],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.github_actions_tool.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/github/actions/runs",
                params={
                    "repo_url": "https://github.com/octocat/Hello-World",
                    "branch": "fixpilot/patch",
                    "per_page": 3,
                },
            )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["owner"] == "octocat"
    assert data["repo"] == "Hello-World"
    assert data["runs"][0]["name"] == "Python tests"
    assert data["runs"][0]["conclusion"] == "failure"


def test_api_fetch_actions_runs():
    asyncio.run(_test_api_fetch_actions_runs())


async def _test_fetch_actions_rate_limit_message():
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = '{"message":"API rate limit exceeded"}'

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.github_actions_tool.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError) as exc:
            await github_actions_tool.fetch_github_actions_runs(
                "https://github.com/octocat/Hello-World"
            )

    assert "rate limit" in str(exc.value).lower()
    assert "GitHub Token" in str(exc.value)


def test_fetch_actions_rate_limit_message():
    asyncio.run(_test_fetch_actions_rate_limit_message())
