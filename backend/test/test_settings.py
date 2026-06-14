# backend/test/test_settings.py
# 设置页 API 冒烟测试
# 运行：cd backend && python test/test_settings.py

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

from app.db.session import init_db
from app.main import app


async def main() -> None:
    await init_db()
    email = f"settings_{uuid.uuid4().hex[:8]}@example.com"
    password = "testpass123"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings")
        assert r.status_code == 401
        print("[OK] GET /settings 未登录 401")

        r = await client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        assert r.status_code == 201

        r = await client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = await client.get("/api/settings", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["github_token_configured"] is False
        assert data["model_name"]
        print("[OK] GET /settings 默认服务器配置")

        r = await client.put(
            "/api/settings",
            headers=headers,
            json={
                "github_token": "ghp_testtoken1234567890",
                "model_name": "deepseek-v4-flash",
                "llm_base_url": "https://api.example.com/v1",
            },
        )
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["github_token_configured"] is True
        assert updated["github_token_hint"] == "****7890"
        assert updated["model_name"] == "deepseek-v4-flash"
        print("[OK] PUT /settings 保存 token 与模型")

        r = await client.put(
            "/api/settings",
            headers=headers,
            json={"github_token": ""},
        )
        cleared = r.json()
        assert cleared["github_token_configured"] is False
        print("[OK] 清除 GitHub Token")

    print("\n设置 API 测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
