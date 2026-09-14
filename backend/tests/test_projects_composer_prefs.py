"""Per-user project chat composer prefs stay isolated across members."""

import asyncio

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMember,
)
from app.models.user import User
from app.services.project_chat_service import create_project_chat_session
from app.services.project_composer_pref_service import (
    get_project_chat_composer_prefs,
    upsert_project_chat_composer_prefs,
)
from app.services.user_chat_storage_service import update_chat_session

PROJ_ID = "proj-composer-1"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username):
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _setup(db):
    owner = await _user(db, "owner")
    contrib = await _user(db, "contrib")
    viewer = await _user(db, "viewer")
    db.add(
        Project(
            id=PROJ_ID,
            name="Test",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ_ID, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJ_ID, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
    db.add(ProjectMember(project_id=PROJ_ID, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    return owner, contrib, viewer


def test_composer_prefs_are_isolated_per_user():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _viewer = await _setup(db)
                created = await create_project_chat_session(
                    db, project_id=PROJ_ID, user=owner, title="Shared", model_id="gpt-text"
                )
                session_id = created["id"]
                owner_saved = await upsert_project_chat_composer_prefs(
                    db,
                    project_id=PROJ_ID,
                    session_id=session_id,
                    user=owner,
                    payload={
                        "tools": {"web_search": True, "code_interpreter": True},
                        "toolsTouched": True,
                        "model": "image-specialist",
                        "selectedAgentSlug": "legal-consultant",
                    },
                )
                assert owner_saved["toolsTouched"] is True
                assert owner_saved["model"] == "image-specialist"
                assert owner_saved["selectedAgentSlug"] == "legal-consultant"
                assert owner_saved["tools"]["web_search"] is True

                contrib_prefs = await get_project_chat_composer_prefs(
                    db, project_id=PROJ_ID, session_id=session_id, user=contrib
                )
                assert contrib_prefs == {
                    "tools": {},
                    "toolsTouched": False,
                    "model": None,
                    "selectedAgentSlug": None,
                }

                owner_again = await get_project_chat_composer_prefs(
                    db, project_id=PROJ_ID, session_id=session_id, user=owner
                )
                assert owner_again["selectedAgentSlug"] == "legal-consultant"
                assert owner_again["model"] == "image-specialist"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_project_session_patch_ignores_shared_tools_and_model():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _viewer = await _setup(db)
                created = await create_project_chat_session(
                    db, project_id=PROJ_ID, user=owner, title="Shared", model_id="gpt-text"
                )
                session_id = created["id"]
                await update_chat_session(
                    db,
                    contrib.id,
                    session_id,
                    {
                        "tools": {"web_search": True},
                        "toolsTouched": True,
                        "model": "image-specialist",
                        "title": "Still shared title",
                    },
                )
                row = await db.get(ChatSession, session_id)
                assert row.tools == {}
                assert row.tools_touched is False
                assert row.model_id == "gpt-text"
                assert row.title == "Still shared title"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_viewer_cannot_write_composer_prefs():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _contrib, viewer = await _setup(db)
                created = await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="Shared")
                try:
                    await upsert_project_chat_composer_prefs(
                        db,
                        project_id=PROJ_ID,
                        session_id=created["id"],
                        user=viewer,
                        payload={"toolsTouched": True, "tools": {"web_search": True}},
                    )
                    raise AssertionError("expected HTTPException")
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())
