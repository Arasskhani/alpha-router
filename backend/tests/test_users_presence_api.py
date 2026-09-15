"""HTTP surface for online presence: the `online` field, the Online filter, and
the browser ping.

Redis is faked, so this exercises the wiring (routes, dependencies, payload
shape) rather than Redis itself.
"""

from __future__ import annotations


from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.admin import router as admin_router
from app.api.deps import get_current_user, require_active_user, require_users
from app.api.user_routes import router as user_router
from app.database import Base, get_db, get_read_db
from app.models.user import User
from app.services import presence_service


class FakeSettings:
    presence_enabled = True
    presence_ttl_seconds = 90


class FakeRedis:
    """Minimal stand-in; ``fail`` simulates an unreachable Redis."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.fail = False

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.fail:
            raise RuntimeError("redis down")
        self.store[key] = value

    async def mget(self, keys: list[str]) -> list[str | None]:
        if self.fail:
            raise RuntimeError("redis down")
        return [self.store.get(key) for key in keys]

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def aclose(self) -> None:
        return None


def _row(payload: list[dict], username: str) -> dict:
    matches = [row for row in payload if row["username"] == username]
    assert matches, f"{username} missing from {[r['username'] for r in payload]}"
    return matches[0]


async def _flow(fake: FakeRedis) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        admin = User(
            username="admin-viewer",
            email="admin@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        online = User(
            username="at-their-desk",
            email="online@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        away = User(
            username="gone-home",
            email="away@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        disabled = User(
            username="disabled-but-pinged",
            email="disabled@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
            is_active=False,
        )
        db.add_all([admin, online, away, disabled])
        await db.commit()
        admin_id = admin.id
        online_id = online.id
        disabled_id = disabled.id

    # The disabled account still holds a key inside its TTL: it must never be
    # reported online.
    fake.store[presence_service.presence_key(online_id)] = "1"
    fake.store[presence_service.presence_key(disabled_id)] = "1"

    async def override_db():
        async with factory() as session:
            yield session

    async def override_user():
        async with factory() as session:
            return await session.get(User, admin_id)

    api = FastAPI()
    api.include_router(admin_router)
    api.include_router(user_router)
    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_read_db] = override_db
    api.dependency_overrides[require_users] = override_user
    api.dependency_overrides[get_current_user] = override_user
    api.dependency_overrides[require_active_user] = override_user

    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/admin/users")
        assert listed.status_code == 200
        rows = listed.json()
        assert _row(rows, "at-their-desk")["online"] is True
        assert _row(rows, "gone-home")["online"] is False
        assert _row(rows, "disabled-but-pinged")["online"] is False

        filtered = await client.get("/api/admin/users?online=true&is_active=true")
        assert filtered.status_code == 200
        assert [row["username"] for row in filtered.json()] == ["at-their-desk"]

        pinged = await client.post("/api/user/presence")
        assert pinged.status_code == 200
        assert pinged.json()["ok"] is True
        assert presence_service.presence_key(admin_id) in fake.store

        # Redis outage: presence becomes unknown, the filter is ignored, and the
        # table still renders instead of coming back empty.
        fake.fail = True
        degraded = await client.get("/api/admin/users?online=true&is_active=true")
        assert degraded.status_code == 200
        degraded_rows = degraded.json()
        assert len(degraded_rows) == 3
        assert all(row["online"] is None for row in degraded_rows)

    await engine.dispose()


async def test_presence_http_surface(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(presence_service, "_client", lambda: fake)
    monkeypatch.setattr(presence_service, "get_settings", lambda: FakeSettings())
    await _flow(fake)
