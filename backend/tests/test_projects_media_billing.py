"""Step 4: project attribution for image/video generation and media reports."""

import asyncio
import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession
from app.models.logging import ImageGenerationAttempt, RequestLog
from app.models.project import PROJECT_ROLE_PRIMARY_OWNER, Project, ProjectMember
from app.models.user import User
from app.models.video import VideoGenerationJob
from app.services.image_billing_service import ImageBillingCapture, log_image_usage
from app.services.project_billing_service import (
    report_all_projects_usage,
    report_project_media_usage_summary,
    report_project_usage_summary,
    resolve_project_id_for_request,
)
from app.services.video_billing_service import VideoBillingCapture, log_video_usage
from app.services.video_job_service import create_video_job

PROJ = "media-bill-1"


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username):
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
        monthly_budget_usd=100.0,
    )
    db.add(u)
    await db.flush()
    return u


async def _setup(db):
    owner = await _user(db, "owner")
    outsider = await _user(db, "outsider")
    db.add(
        Project(
            id=PROJ,
            name="Media Bill",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    await db.flush()
    return owner, outsider


async def _session(db, user, *, project_id=None, sid="sess-1"):
    now = datetime.datetime.utcnow()
    row = ChatSession(
        id=sid,
        user_id=user.id,
        title="T",
        model_id="",
        tools={},
        private_mode=False,
        project_id=project_id,
        created_by_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return row


def _window():
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=30)
    return start, end


def test_resolve_project_id_from_chat_session():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, outsider = await _setup(db)
                await _session(db, owner, project_id=PROJ, sid="proj-sess")
                resolved = await resolve_project_id_for_request(db, user=owner, chat_session_id="proj-sess")
                assert resolved == PROJ
                # personal chat → None
                await _session(db, owner, project_id=None, sid="personal")
                assert await resolve_project_id_for_request(db, user=owner, chat_session_id="personal") is None
                # session wins over a spoofed project_id
                spoofed = await resolve_project_id_for_request(
                    db,
                    user=outsider,
                    chat_session_id="proj-sess",
                    project_id="other-project",
                )
                assert spoofed == PROJ
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_resolve_explicit_project_id_requires_access():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, outsider = await _setup(db)
                assert await resolve_project_id_for_request(db, user=owner, project_id=PROJ) == PROJ
                assert await resolve_project_id_for_request(db, user=outsider, project_id=PROJ) is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_image_generation_attributed_to_project():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                capture = ImageBillingCapture(
                    model_id="google/gemini-flash-image",
                    ai_model=None,
                    provider_type="openrouter",
                    usage_source={
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                            "prompt_tokens_details": {},
                        }
                    },
                )
                await log_image_usage(
                    db,
                    user=owner,
                    capture=capture,
                    prompt="a cube",
                    response_time_ms=10,
                    success=True,
                    operation="generation",
                    project_id=PROJ,
                )
                row = (await db.execute(select(RequestLog))).scalar_one()
                assert row.project_id == PROJ
                assert "(image:" in (row.client_app or "")
                db.add(
                    ImageGenerationAttempt(
                        request_id="req-1",
                        user_id=owner.id,
                        project_id=PROJ,
                        requested_model="google/gemini-flash-image",
                        model_id="google/gemini-flash-image",
                        operation="generation",
                        attempt_index=0,
                        started_at=datetime.datetime.utcnow(),
                        response_time_ms=10,
                        success=True,
                        outcome="success",
                    )
                )
                await db.flush()
                attempt = (await db.execute(select(ImageGenerationAttempt))).scalar_one()
                assert attempt.project_id == PROJ
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_non_project_generation_has_null_project_id():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                capture = ImageBillingCapture(
                    model_id="google/gemini-flash-image",
                    usage_source={"usage": {"prompt_tokens": 1, "completion_tokens": 1}},
                )
                await log_image_usage(
                    db,
                    user=owner,
                    capture=capture,
                    prompt="hi",
                    response_time_ms=1,
                    success=True,
                    project_id=None,
                )
                row = (await db.execute(select(RequestLog))).scalar_one()
                assert row.project_id is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_video_generation_attributed_to_project():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                job = await create_video_job(
                    db,
                    user=owner,
                    model_id="google/veo-3",
                    prompt="waves",
                    operation="generation",
                    params={"duration": 4, "resolution": "720p", "aspect_ratio": "16:9"},
                    chat_session_id=None,
                    persist=True,
                    reference_image=None,
                    budget_reservation_id=None,
                    idempotency_key=None,
                    catalog_model_id=None,
                    source_ip="127.0.0.1",
                    provider_type="openrouter",
                    project_id=PROJ,
                )
                assert job.project_id == PROJ
                capture = VideoBillingCapture(model_id="google/veo-3", provider_type="openrouter")
                capture.add_usage(None, success=True, quantity=4, unit="second")
                await log_video_usage(
                    db,
                    user=owner,
                    capture=capture,
                    prompt="waves",
                    response_time_ms=100,
                    success=True,
                    operation="generation",
                    duration_seconds=4,
                    job_id=job.id,
                    project_id=job.project_id,
                )
                log = (await db.execute(select(RequestLog))).scalar_one()
                assert log.project_id == PROJ
                assert "(video:" in (log.client_app or "")
                stored = await db.get(VideoGenerationJob, job.id)
                assert stored is not None
                assert stored.project_id == PROJ
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_media_cost_in_project_usage_summary():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                now = datetime.datetime.utcnow()
                db.add(
                    RequestLog(
                        user_id=owner.id,
                        username=owner.username,
                        model_id="gpt-4",
                        project_id=PROJ,
                        total_cost_usd=1.0,
                        prompt_tokens=10,
                        completion_tokens=20,
                        request_time=now,
                        success=True,
                        client_app="Alpharouter Chat",
                    )
                )
                db.add(
                    RequestLog(
                        user_id=owner.id,
                        username=owner.username,
                        model_id="gemini-image",
                        project_id=PROJ,
                        total_cost_usd=0.4,
                        prompt_tokens=0,
                        completion_tokens=0,
                        request_time=now,
                        success=True,
                        client_app="Alpharouter Chat (image:generation)",
                    )
                )
                db.add(
                    RequestLog(
                        user_id=owner.id,
                        username=owner.username,
                        model_id="veo-3",
                        project_id=PROJ,
                        total_cost_usd=0.6,
                        prompt_tokens=0,
                        completion_tokens=0,
                        request_time=now,
                        success=True,
                        client_app="Alpharouter Chat (video:generation)",
                    )
                )
                # other project must not leak
                db.add(
                    RequestLog(
                        user_id=owner.id,
                        username=owner.username,
                        model_id="gemini-image",
                        project_id="other",
                        total_cost_usd=9.0,
                        request_time=now,
                        success=True,
                        client_app="Alpharouter Chat (image:generation)",
                    )
                )
                await db.flush()
                start, end = _window()
                summary = await report_project_usage_summary(db, PROJ, start, end)
                assert summary.iloc[0]["total_cost_usd"] == 2.0
                assert summary.iloc[0]["media_cost_usd"] == 1.0
                media = await report_project_media_usage_summary(db, PROJ, start, end)
                assert media.iloc[0]["media_cost_usd"] == 1.0
                assert media.iloc[0]["media_requests"] == 2
                all_df = await report_all_projects_usage(db, start, end)
                by_id = all_df.set_index("project_id")
                assert by_id.loc[PROJ, "media_cost_usd"] == 1.0
                assert by_id.loc[PROJ, "cost_usd"] == 2.0
        finally:
            await engine.dispose()

    asyncio.run(run())
