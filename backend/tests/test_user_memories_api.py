"""User memory HTTP API: no manual create, enabled-only patch, export, delete-all."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.deps import get_current_user, require_active_user
from app.api.user_memories import router
from app.database import Base, get_db, get_read_db
from app.models.chat import ChatMessage, ChatSession, UserMemoryJob
from app.models.system import SystemSetting
from app.models.user import User
from app.services.memory_job_service import schedule_extraction
from app.services.user_memory_service import create_memory


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _api_flow() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = User(
            username="apiuser",
            email="apiuser@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        session = ChatSession(
            id="sess-api",
            user_id=user.id,
            title="API chat",
            model_id="m",
            private_mode=False,
        )
        db.add(session)
        db.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=user.id,
                role="user",
                content="hi",
                sequence=1,
            )
        )
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=user.id,
                role="assistant",
                content="hello",
                sequence=2,
            )
        )
        created, _ = await create_memory(db, user.id, "Prefers dark mode", source_session_id=session.id)
        job = await schedule_extraction(db, user_id=user.id, session_id=session.id, watermark_sequence=2)
        await db.commit()
        user_id = user.id
        memory_id = created["id"]
        job_id = job.id if job is not None else None

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_read_db] = override_db

    async def override_user():
        async with factory() as session:
            return await session.get(User, user_id)

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[require_active_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        posted = await client.post("/api/user/memories", json={"content": "manual"})
        assert posted.status_code in (404, 405)

        patched_content = await client.patch(f"/api/user/memories/{memory_id}", json={"content": "hacked"})
        assert patched_content.status_code == 400

        patched = await client.patch(f"/api/user/memories/{memory_id}", json={"enabled": False})
        assert patched.status_code == 200
        assert patched.json()["enabled"] is False

        listed = await client.get("/api/user/memories?limit=50&offset=0")
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] == 1
        assert body["memories"][0]["category"]
        assert "auto_capture" in body
        assert "feature_enabled" in body

        exported = await client.get("/api/user/memories/export")
        assert exported.status_code == 200
        assert exported.json()["total"] == 1
        assert "attachment" in (exported.headers.get("content-disposition") or "").lower()

        deleted = await client.delete("/api/user/memories")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] == 1

    async with factory() as db:
        leftover = await db.get(UserMemoryJob, job_id) if job_id else None
        if leftover is not None:
            assert leftover.extracted_sequence >= 2
        empty = await client_list_via_db(db, user_id)
        assert empty == 0
    await engine.dispose()


async def client_list_via_db(db, user_id: int) -> int:
    from app.services.user_memory_service import list_memories

    _items, total = await list_memories(db, user_id)
    return total


def test_user_memories_api_surface() -> None:
    asyncio.run(_api_flow())
