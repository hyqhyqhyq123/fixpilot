# backend/test/test_auth.py
# FR-001 用户登录 API 冒烟测试
# 运行：cd backend && python test/test_auth.py

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

    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "testpass123"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 未登录访问 /me → 401
        r = await client.get("/api/auth/me")
        assert r.status_code == 401, r.text
        print("[OK] GET /me 未登录返回 401")

        # 注册
        r = await client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        assert r.status_code == 201, r.text
        user = r.json()
        assert user["email"] == email
        print(f"[OK] POST /register id={user['id']}")

        # 重复注册 → 400
        r = await client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        assert r.status_code == 400
        print("[OK] 重复注册返回 400")

        # 错误密码 → 401
        r = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert r.status_code == 401
        print("[OK] 错误密码返回 401")

        # 登录成功
        r = await client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        token = data["access_token"]
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == email
        print("[OK] POST /login 返回 token")

        headers = {"Authorization": f"Bearer {token}"}

        # /me
        r = await client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["email"] == email
        print("[OK] GET /me 返回当前用户")

        # logout
        r = await client.post("/api/auth/logout", headers=headers)
        assert r.status_code == 200, r.text
        print("[OK] POST /logout")

    print("\nFR-001 认证 API 测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())
