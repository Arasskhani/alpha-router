"""Tests for project config versioning, memory CRUD, and cross-project grants."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMemory,
    ProjectMemoryGrant,
    ProjectMember,
)
from app.models.user import User
from app.services.project_config_service import (
    get_active_config,
    list_config_versions,
    update_project_config,
)
from app.services.project_memory_service import (
    ProjectMemoryGrantError,
    ProjectMemoryNotFoundError,
    ProjectMemoryValidationError,
    create_memory_grant,
    create_project_memory,
    delete_project_memory,
    load_injectable_project_memories,
    revoke_memory_grant,
    update_project_memory,
)

PROJ_ID = "proj-ai-1"
PROJ_ID_2 = "proj-ai-2"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username, *, active=True):
    user = User(
        username=username, email=f"{username}@test", hashed_password="x",
        auth_provider="local", is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _setup_project(db, pid=PROJ_ID):
    owner = await _user(db, f"owner_{pid}")
    contrib = await _user(db, f"contrib_{pid}")
    viewer = await _user(db, f"viewer_{pid}")
    db.add(Project(
        id=pid, name=f"Test {pid}", status="active", visibility="private",
        created_by_user_id=owner.id, revision=1, acl_version=1,
    ))
    db.add(ProjectMember(project_id=pid, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=pid, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
    db.add(ProjectMember(project_id=pid, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    return owner, contrib, viewer


async def _setup_two_projects(db):
    owner = await _user(db, "owner_both")
    db.add(Project(
        id=PROJ_ID, name="Consumer", status="active", visibility="private",
        created_by_user_id=owner.id, revision=1, acl_version=1,
    ))
    db.add(Project(
        id=PROJ_ID_2, name="Source", status="active", visibility="private",
        created_by_user_id=owner.id, revision=1, acl_version=1,
    ))
    db.add(ProjectMember(project_id=PROJ_ID, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJ_ID_2, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    await db.flush()
    return owner


def test_get_active_config_defaults():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                config = await get_active_config(db, project_id=PROJ_ID, user=owner)
                assert config is not None
                assert config.revision == 0
                assert config.memory_enabled is True
                assert config.custom_prompt is None
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_update_config_owner():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                version = await update_project_config(
                    db, project_id=PROJ_ID, user=owner,
                    custom_prompt="Be helpful", memory_enabled=False,
                    grounding_policy={"restrict_to_internal": True},
                )
                await db.flush()
                assert version.revision == 1
                assert version.custom_prompt == "Be helpful"
                assert version.memory_enabled is False
                config = await get_active_config(db, project_id=PROJ_ID, user=owner)
                assert config.revision == 1
                assert config.memory_enabled is False
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_update_config_contributor_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, contrib, _ = await _setup_project(db)
                from fastapi import HTTPException
                try:
                    await update_project_config(db, project_id=PROJ_ID, user=contrib, custom_prompt="x")
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_update_config_new_version():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                v1 = await update_project_config(db, project_id=PROJ_ID, user=owner, custom_prompt="v1")
                await db.flush()
                v2 = await update_project_config(db, project_id=PROJ_ID, user=owner, custom_prompt="v2")
                await db.flush()
                assert v1.revision == 1
                assert v2.revision == 2
                assert v1.id != v2.id
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_memory_owner():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                memory, created = await create_project_memory(
                    db, project_id=PROJ_ID, user=owner, content="Important fact"
                )
                await db.flush()
                assert created is True
                assert memory["content"] == "Important fact"
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_memory_contributor_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, contrib, _ = await _setup_project(db)
                from fastapi import HTTPException
                try:
                    await create_project_memory(
                        db, project_id=PROJ_ID, user=contrib, content="Contrib fact"
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_memory_viewer_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, _, viewer = await _setup_project(db)
                from fastapi import HTTPException
                try:
                    await create_project_memory(db, project_id=PROJ_ID, user=viewer, content="x")
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_memory_dedup():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                m1, c1 = await create_project_memory(
                    db, project_id=PROJ_ID, user=owner, content="Same fact"
                )
                await db.flush()
                m2, c2 = await create_project_memory(
                    db, project_id=PROJ_ID, user=owner, content="  Same fact  "
                )
                await db.flush()
                assert c1 is True
                assert c2 is False
                assert m1["id"] == m2["id"]
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_memory_empty_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                try:
                    await create_project_memory(db, project_id=PROJ_ID, user=owner, content="   ")
                    assert False
                except ProjectMemoryValidationError:
                    pass
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_update_memory():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                memory, _ = await create_project_memory(
                    db, project_id=PROJ_ID, user=owner, content="Original"
                )
                await db.flush()
                updated = await update_project_memory(
                    db, project_id=PROJ_ID, user=owner,
                    memory_id=memory["id"], content="Updated", enabled=False,
                )
                await db.flush()
                assert updated["content"] == "Updated"
                assert updated["enabled"] is False
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_delete_memory():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                memory, _ = await create_project_memory(
                    db, project_id=PROJ_ID, user=owner, content="To delete"
                )
                await db.flush()
                await delete_project_memory(
                    db, project_id=PROJ_ID, user=owner, memory_id=memory["id"]
                )
                await db.flush()
                row = await db.get(ProjectMemory, memory["id"])
                assert row is None
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_delete_memory_not_found():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                try:
                    await delete_project_memory(
                        db, project_id=PROJ_ID, user=owner, memory_id="nonexistent"
                    )
                    assert False
                except ProjectMemoryNotFoundError:
                    pass
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_grant_owner_both():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                grant = await create_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                assert grant["consumerProjectId"] == PROJ_ID
                assert grant["sourceProjectId"] == PROJ_ID_2
                assert grant["status"] == "active"
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_grant_self_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                try:
                    await create_memory_grant(
                        db, consumer_project_id=PROJ_ID,
                        source_project_id=PROJ_ID, user=owner,
                    )
                    assert False
                except ValueError:
                    pass
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_grant_not_owner_of_source():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                await _setup_two_projects(db)
                non_owner = await _user(db, "non_owner")
                db.add(ProjectMember(project_id=PROJ_ID, user_id=non_owner.id, role=PROJECT_ROLE_OWNER))
                await db.flush()
                try:
                    await create_memory_grant(
                        db, consumer_project_id=PROJ_ID,
                        source_project_id=PROJ_ID_2, user=non_owner,
                    )
                    assert False
                except ValueError:
                    pass
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_create_grant_contributor_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                contrib = await _user(db, "contrib")
                db.add(ProjectMember(project_id=PROJ_ID, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
                await db.flush()
                from fastapi import HTTPException
                try:
                    await create_memory_grant(
                        db, consumer_project_id=PROJ_ID,
                        source_project_id=PROJ_ID_2, user=contrib,
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_revoke_grant():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                await create_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                revoked = await revoke_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                assert revoked is True
                grant = (
                    await db.execute(
                        select(ProjectMemoryGrant).where(
                            ProjectMemoryGrant.consumer_project_id == PROJ_ID,
                            ProjectMemoryGrant.source_project_id == PROJ_ID_2,
                        )
                    )
                ).scalar_one()
                assert grant.status == "revoked"
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_revoke_grant_not_found():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                revoked = await revoke_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                assert revoked is False
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_reactivate_revoked_grant():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                await create_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                await revoke_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                grant = await create_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                assert grant["status"] == "active"
                assert grant["revision"] == 3
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_load_injectable_disabled():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                await create_project_memory(db, project_id=PROJ_ID, user=owner, content="Fact 1")
                await db.flush()
                injection = await load_injectable_project_memories(
                    db, project_id=PROJ_ID, memory_enabled=False
                )
                assert injection.total_facts == 0
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_load_injectable_enabled():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                await create_project_memory(db, project_id=PROJ_ID, user=owner, content="Fact 1")
                await create_project_memory(db, project_id=PROJ_ID, user=owner, content="Fact 2")
                await db.flush()
                injection = await load_injectable_project_memories(
                    db, project_id=PROJ_ID, memory_enabled=True
                )
                assert injection.total_facts == 2
                assert "Fact 1" in injection.own_facts
                assert "Fact 2" in injection.own_facts
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_load_injectable_with_grant():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                await create_project_memory(db, project_id=PROJ_ID_2, user=owner, content="Source fact")
                await db.flush()
                await create_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                injection = await load_injectable_project_memories(
                    db, project_id=PROJ_ID, memory_enabled=True
                )
                assert injection.total_facts >= 1
                assert "Source fact" in injection.granted_facts
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_load_injectable_grant_revoked():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner = await _setup_two_projects(db)
                await create_project_memory(db, project_id=PROJ_ID_2, user=owner, content="Source fact")
                await create_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                await revoke_memory_grant(
                    db, consumer_project_id=PROJ_ID,
                    source_project_id=PROJ_ID_2, user=owner,
                )
                await db.flush()
                injection = await load_injectable_project_memories(
                    db, project_id=PROJ_ID, memory_enabled=True
                )
                assert len(injection.granted_facts) == 0
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_restore_config_creates_new_revision():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                first = await update_project_config(
                    db,
                    project_id=PROJ_ID,
                    user=owner,
                    custom_prompt="Version one.",
                    memory_enabled=True,
                    grounding_policy={"useProjectResources": True},
                )
                second = await update_project_config(
                    db,
                    project_id=PROJ_ID,
                    user=owner,
                    custom_prompt="Version two.",
                    memory_enabled=False,
                    grounding_policy={"useProjectResources": False},
                )
                assert second.revision == first.revision + 1
                restored = await update_project_config(
                    db,
                    project_id=PROJ_ID,
                    user=owner,
                    custom_prompt=first.custom_prompt,
                    memory_enabled=first.memory_enabled,
                    grounding_policy=dict(first.grounding_policy or {}),
                )
                assert restored.revision == second.revision + 1
                assert restored.id != first.id
                assert restored.custom_prompt == "Version one."
                assert restored.memory_enabled is True
                assert restored.grounding_policy.get("useProjectResources") is True
                versions, total = await list_config_versions(
                    db, project_id=PROJ_ID, user=owner
                )
                assert total == 3
                assert versions[0]["revision"] == restored.revision
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_grant_requires_owner_on_both():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner_a, contrib, _ = await _setup_project(db)
                owner_b = await _user(db, "owner_b")
                db.add(Project(
                    id=PROJ_ID_2, name="Other", status="active", visibility="private",
                    created_by_user_id=owner_b.id, revision=1, acl_version=1,
                ))
                db.add(ProjectMember(project_id=PROJ_ID_2, user_id=owner_b.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                await db.flush()
                from fastapi import HTTPException
                try:
                    await create_memory_grant(
                        db,
                        consumer_project_id=PROJ_ID,
                        source_project_id=PROJ_ID_2,
                        user=owner_a,
                    )
                    assert False
                except ProjectMemoryGrantError:
                    pass
                try:
                    await create_memory_grant(
                        db,
                        consumer_project_id=PROJ_ID,
                        source_project_id=PROJ_ID_2,
                        user=contrib,
                    )
                    assert False
                except HTTPException:
                    pass
        finally:
            await engine.dispose()
    asyncio.run(run())
