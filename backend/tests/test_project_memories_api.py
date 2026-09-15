"""Project memory listing filters, pagination, export, and delete-all RBAC."""

from __future__ import annotations


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
from app.services.project_memory_service import (
    create_auto_project_memory,
    create_project_memory,
    delete_all_auto_project_memories,
    export_project_memories,
    list_project_memories,
)

PROJ_ID = "proj-memories-api"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db.add(user)
    await db.flush()
    return user


async def _seed(db: AsyncSession) -> tuple[User, User, User, ChatSession]:
    owner = await _user(db, "api_owner")
    contrib = await _user(db, "api_contrib")
    viewer = await _user(db, "api_viewer")
    db.add(
        Project(
            id=PROJ_ID,
            name="API",
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
    session = ChatSession(
        id="sess-memories-api",
        user_id=owner.id,
        title="Design review",
        model_id="m",
        private_mode=False,
        project_id=PROJ_ID,
        channel_kind="ai",
    )
    db.add(session)
    await db.flush()
    return owner, contrib, viewer, session


async def _seed_facts(db: AsyncSession, owner: User, session: ChatSession) -> None:
    await create_project_memory(db, project_id=PROJ_ID, user=owner, content="Invoices are issued monthly")
    await create_auto_project_memory(
        db,
        project_id=PROJ_ID,
        content="The ledger runs on Postgres",
        session_id=session.id,
        message_id=None,
        author_user_id=owner.id,
        category="stack",
    )
    await create_auto_project_memory(
        db,
        project_id=PROJ_ID,
        content="Scope freezes on Sept 1",
        session_id=session.id,
        message_id=None,
        author_user_id=owner.id,
        category="decision",
    )
    await db.flush()


async def _filters_and_source_links() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, contrib, _viewer, session = await _seed(db)
        await _seed_facts(db, owner, session)
        await db.commit()

        everything, total = await list_project_memories(db, project_id=PROJ_ID, user=contrib)
        assert total == 3
        assert len(everything) == 3

        manual, manual_total = await list_project_memories(db, project_id=PROJ_ID, user=contrib, origin="manual")
        assert manual_total == 1
        assert manual[0]["origin"] == "manual"
        assert manual[0]["content"] == "Invoices are issued monthly"
        assert manual[0]["sourceSessionId"] is None

        learned, learned_total = await list_project_memories(db, project_id=PROJ_ID, user=contrib, origin="auto")
        assert learned_total == 2
        assert {item["origin"] for item in learned} == {"auto_chat"}
        assert all(item["sourceSessionId"] == session.id for item in learned)
        assert all(item["sourceSessionTitle"] == "Design review" for item in learned)
        assert all(item["createdByUserId"] == owner.id for item in learned)

        by_category, category_total = await list_project_memories(
            db, project_id=PROJ_ID, user=contrib, category="stack"
        )
        assert category_total == 1
        assert by_category[0]["content"] == "The ledger runs on Postgres"

        first_page, page_total = await list_project_memories(db, project_id=PROJ_ID, user=contrib, limit=2, offset=0)
        second_page, _ = await list_project_memories(db, project_id=PROJ_ID, user=contrib, limit=2, offset=2)
        assert page_total == 3
        assert len(first_page) == 2
        assert len(second_page) == 1
        ids = {item["id"] for item in first_page} | {item["id"] for item in second_page}
        assert len(ids) == 3
    await engine.dispose()


async def _export_requires_owner() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, contrib, viewer, session = await _seed(db)
        await _seed_facts(db, owner, session)
        await db.commit()

        exported = await export_project_memories(db, project_id=PROJ_ID, user=owner)
        assert len(exported) == 3

        for actor in (contrib, viewer):
            try:
                await export_project_memories(db, project_id=PROJ_ID, user=actor)
                raise AssertionError("export must require memory.manage")
            except HTTPException as exc:
                assert exc.status_code == 403
    await engine.dispose()


async def _delete_all_requires_owner_and_keeps_manual() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, contrib, viewer, session = await _seed(db)
        await _seed_facts(db, owner, session)
        await db.commit()

        for actor in (contrib, viewer):
            try:
                await delete_all_auto_project_memories(db, project_id=PROJ_ID, user=actor)
                raise AssertionError("delete-all must require memory.manage")
            except HTTPException as exc:
                assert exc.status_code == 403

        deleted = await delete_all_auto_project_memories(db, project_id=PROJ_ID, user=owner)
        await db.commit()
        assert deleted == 2
        remaining, total = await list_project_memories(db, project_id=PROJ_ID, user=owner)
        assert total == 1
        assert remaining[0]["origin"] == "manual"
    await engine.dispose()


async def test_project_memory_filters_and_source_links() -> None:
    await _filters_and_source_links()


async def test_project_memory_export_requires_memory_manage() -> None:
    await _export_requires_owner()


async def test_delete_all_learned_requires_memory_manage() -> None:
    await _delete_all_requires_owner_and_keeps_manual()
