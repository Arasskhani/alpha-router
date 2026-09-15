"""Video runner: a lost lease stops the runner; cancel yields to a finished provider job."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.user import User
from app.models.video import VideoGenerationJob
from app.services import video_job_service as vjs
from app.services.video_providers.contracts import ProviderJobRef, ProviderJobSnapshot


class _FakeAdapter:
    """Provider that stays 'running' until told otherwise."""

    provider_type = "openrouter"
    adapter_version = "test"

    def __init__(self) -> None:
        self.state = "running"
        self.polls = 0
        self.cancels = 0

    async def submit(self, *, api_key, base_url, request):
        return ProviderJobRef(provider_type="openrouter", provider_job_id="prov-1")

    async def poll(self, *, api_key, base_url, job):
        self.polls += 1
        return ProviderJobSnapshot(state=self.state, raw={"n": self.polls})

    async def cancel(self, *, api_key, base_url, job):
        self.cancels += 1
        return True


async def _factory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def dispose():
        await engine.dispose()
        with contextlib.suppress(OSError):
            os.remove(path)

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), dispose


async def _seed(db, *, status="submitted", lease_owner="worker-A", provider_job_id="prov-1"):
    user = User(username="v", email="v@t", hashed_password="x", auth_provider="local", is_active=True)
    db.add(user)
    await db.flush()
    job = VideoGenerationJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        model_id="video-model",
        provider_type="openrouter",
        adapter_key="openrouter",
        status=status,
        prompt="p",
        persist=1,
        params_json=json.dumps({"duration": 5}),
        lease_owner=lease_owner,
        provider_job_id=provider_job_id,
    )
    db.add(job)
    await db.commit()
    return user, job


async def test_runner_stops_without_billing_when_lease_is_taken_over():
    factory, dispose = await _factory()
    adapter = _FakeAdapter()
    billing = AsyncMock(return_value=None)
    try:
        async with factory() as db:
            user, job = await _seed(db)
            job_id = job.id

        async def takeover():
            # Wait for the runner's first poll, then another worker claims the job.
            for _ in range(200):
                if adapter.polls >= 1:
                    break
                await asyncio.sleep(0.01)
            async with factory() as db:
                row = await db.get(VideoGenerationJob, job_id)
                row.lease_owner = "worker-B"
                await db.commit()

        settings = SimpleNamespace(video_job_timeout_seconds=30, video_job_poll_interval_ms=50)
        with (
            patch.object(vjs, "AsyncSessionLocal", factory),
            patch.object(vjs, "get_video_adapter", lambda *a, **k: adapter),
            patch.object(vjs, "get_settings", lambda: settings),
            patch.object(vjs, "log_video_usage", billing),
        ):
            # Give the runner a connection to use.
            from app.models.connection import Connection
            from app.models.model_catalog import AIModel

            async with factory() as db:
                conn = Connection(name="c", provider_type="openrouter", api_key_encrypted="enc", is_active=True)
                db.add(conn)
                await db.flush()
                model = AIModel(
                    connection_id=conn.id,
                    external_id="video-model",
                    provider_type="openrouter",
                    display_name="v",
                    is_video_model=True,
                )
                db.add(model)
                await db.flush()
                row = await db.get(VideoGenerationJob, job_id)
                row.catalog_model_id = model.id
                row.connection_id = conn.id
                await db.commit()

            with patch("app.services.secret_crypto.decrypt_secret", lambda v: "k"):
                await asyncio.gather(vjs._run_video_job(job_id), takeover())

        async with factory() as db:
            row = await db.get(VideoGenerationJob, job_id)
        # The row belongs to worker-B now: status untouched by the old runner,
        # lease not cleared, and no usage row written by it.
        assert row.lease_owner == "worker-B"
        assert row.status not in ("failed", "cancelled", "completed")
        billing.assert_not_awaited()
    finally:
        await dispose()


async def test_cancel_yields_when_provider_already_completed():
    factory, dispose = await _factory()
    adapter = _FakeAdapter()
    adapter.state = "completed"
    try:
        from app.models.connection import Connection
        from app.models.model_catalog import AIModel

        async with factory() as db:
            user, job = await _seed(db, status="running")
            conn = Connection(name="c", provider_type="openrouter", api_key_encrypted="enc", is_active=True)
            db.add(conn)
            await db.flush()
            model = AIModel(
                connection_id=conn.id,
                external_id="video-model",
                provider_type="openrouter",
                display_name="v",
                is_video_model=True,
            )
            db.add(model)
            await db.flush()
            job.catalog_model_id = model.id
            job.connection_id = conn.id
            await db.commit()

            with (
                patch.object(vjs, "get_video_adapter", lambda *a, **k: adapter),
                patch("app.services.secret_crypto.decrypt_secret", lambda v: "k"),
            ):
                with pytest.raises(vjs.VideoJobAlreadyCompleted):
                    await vjs.cancel_video_job(db, job)
                assert adapter.cancels == 0
                assert job.status == "running" and job.cancel_requested_at is None

                # Still running at the provider: cancel proceeds as before.
                adapter.state = "running"
                out = await vjs.cancel_video_job(db, job)
                assert out.status == "cancelled" and adapter.cancels == 1
    finally:
        await dispose()
