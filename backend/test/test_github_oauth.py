# backend/test/test_github_oauth.py
# Purpose: GitHub OAuth login smoke tests without real GitHub network calls.

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

from app.db.session import init_db
from app.main import app


def _oauth_settings() -> SimpleNamespace:
    return SimpleNamespace(
        github_oauth_client_id="client-id",
        github_oauth_client_secret="client-secret",
        github_oauth_redirect_uri="http://localhost:3000/login",
    )


async def _authorize_requires_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "app.api.routes.auth.get_settings",
            return_value=SimpleNamespace(
                github_oauth_client_id="",
                github_oauth_client_secret="",
                github_oauth_redirect_uri="",
            ),
        ):
            response = await client.get("/api/auth/github/authorize")

    assert response.status_code == 400


def test_authorize_requires_config():
    asyncio.run(_authorize_requires_config())


async def _authorize_returns_github_url():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.api.routes.auth.get_settings", return_value=_oauth_settings()):
            response = await client.get("/api/auth/github/authorize")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["state"]
    assert "https://github.com/login/oauth/authorize" in data["auth_url"]
    assert "client_id=client-id" in data["auth_url"]
    assert "scope=read%3Auser+user%3Aemail" in data["auth_url"]


def test_authorize_returns_github_url():
    asyncio.run(_authorize_returns_github_url())


async def _callback_creates_user_and_returns_fixpilot_token():
    await init_db()
    email = f"oauth_{uuid.uuid4().hex[:8]}@example.com"
    github_id = int(uuid.uuid4().int % 1_000_000_000)
    profile = {"id": github_id, "login": "octocat", "email": None}
    emails = [{"email": email, "primary": True, "verified": True}]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch("app.api.routes.auth.get_settings", return_value=_oauth_settings()),
            patch("app.api.routes.auth.validate_oauth_state", return_value=True),
            patch(
                "app.api.routes.auth._exchange_github_code",
                new_callable=AsyncMock,
                return_value="github-token",
            ) as exchange_mock,
            patch(
                "app.api.routes.auth._fetch_github_profile",
                new_callable=AsyncMock,
                return_value=(profile, emails),
            ) as profile_mock,
        ):
            response = await client.post(
                "/api/auth/github/callback",
                json={"code": "callback-code", "state": "signed-state"},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["access_token"]
        assert data["user"]["email"] == email
        assert data["user"]["github_user_id"] == str(github_id)
        exchange_mock.assert_awaited_once()
        profile_mock.assert_awaited_once_with("github-token")

        me = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == email


def test_callback_creates_user_and_returns_fixpilot_token():
    asyncio.run(_callback_creates_user_and_returns_fixpilot_token())


async def _callback_rejects_invalid_state():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch("app.api.routes.auth.get_settings", return_value=_oauth_settings()),
            patch("app.api.routes.auth.validate_oauth_state", return_value=False),
        ):
            response = await client.post(
                "/api/auth/github/callback",
                json={"code": "callback-code", "state": "bad-state"},
            )

    assert response.status_code == 400


def test_callback_rejects_invalid_state():
    asyncio.run(_callback_rejects_invalid_state())
