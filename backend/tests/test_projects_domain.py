"""Tests for the Projects domain model, ACL service, and membership invariants."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_VISIBILITY_PRIVATE,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectInvitation,
    ProjectMember,
)
from app.models.user import User
from app.services.project_access_service import (
    ProjectAccessError,
    append_project_audit,
    bump_acl_version,
    count_owners,
    ensure_not_last_owner,
    require_capability,
    resolve_project_access,
    validate_invitation_role,
    validate_role,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db: AsyncSession, username: str, *, active: bool = True) -> User:
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db: AsyncSession, *, created_by: int, visibility: str = "private") -> Project:
    project = Project(
        id="proj-1",
        name="Test Project",
        description="desc",
        status="active",
        visibility=visibility,
        created_by_user_id=created_by,
        revision=1,
        acl_version=1,
    )
    db.add(project)
    await db.flush()
    return project


def test_validate_role_accepts_valid_roles():
    assert validate_role("owner") == "owner"
    assert validate_role("CONTRIBUTOR") == "contributor"
    assert validate_role("Viewer") == "viewer"


def test_validate_role_rejects_invalid():
    try:
        validate_role("admin")
        pytest.fail("expected ValueError")
    except ValueError:
        pass


def test_validate_invitation_role_rejects_owner():
    try:
        validate_invitation_role("owner")
        pytest.fail("expected ValueError")
    except ValueError:
        pass

    assert validate_invitation_role("contributor") == "contributor"
    assert validate_invitation_role("viewer") == "viewer"


async def test_resolve_project_access_owner_can_view_and_edit():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            await _project(db, created_by=owner.id)
            db.add(
                ProjectMember(
                    project_id="proj-1",
                    user_id=owner.id,
                    role=PROJECT_ROLE_OWNER,
                )
            )
            await db.flush()

            access = await resolve_project_access(db, project_id="proj-1", user=owner)
            assert access is not None
            assert access.is_member is True
            assert access.role == "owner"
            assert access.can("project.edit") is True
            # Only the Primary Owner may delete a project; a regular Owner
            # is a strict subset (see _CAPABILITIES in project_access_service).
            assert access.can("project.delete") is False
            assert access.can("member.manage_owners") is False
            assert access.can("chat.write") is True
    finally:
        await engine.dispose()


async def test_resolve_project_access_viewer_cannot_write():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            viewer = await _user(db, "viewer")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            db.add(ProjectMember(project_id="proj-1", user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
            await db.flush()

            access = await resolve_project_access(db, project_id="proj-1", user=viewer)
            assert access is not None
            assert access.can("project.view") is True
            assert access.can("chat.write") is False
            assert access.can("chat.pin") is False
            assert access.can("resource.upload") is False
    finally:
        await engine.dispose()


async def test_resolve_project_access_contributor_can_pin_and_upload():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            contrib = await _user(db, "contrib")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            db.add(ProjectMember(project_id="proj-1", user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
            await db.flush()

            access = await resolve_project_access(db, project_id="proj-1", user=contrib)
            assert access is not None
            assert access.can("chat.write") is True
            assert access.can("chat.pin") is True
            assert access.can("resource.upload") is True
            assert access.can("project.edit") is False
            assert access.can("member.manage") is False
            assert access.can("project.delete") is False
    finally:
        await engine.dispose()


async def test_resolve_project_access_private_project_hidden_from_non_member():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            stranger = await _user(db, "stranger")
            await _project(db, created_by=owner.id, visibility=PROJECT_VISIBILITY_PRIVATE)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()

            access = await resolve_project_access(db, project_id="proj-1", user=stranger)
            assert access is None  # hidden → 404
    finally:
        await engine.dispose()


async def test_resolve_project_access_public_project_grants_viewer_to_non_member():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            stranger = await _user(db, "stranger")
            await _project(db, created_by=owner.id, visibility=PROJECT_VISIBILITY_PUBLIC)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()

            access = await resolve_project_access(db, project_id="proj-1", user=stranger)
            assert access is not None
            assert access.is_member is False
            assert access.is_public_viewer is True
            assert access.role == "viewer"
            assert access.can("project.view") is True
            assert access.can("chat.write") is False
    finally:
        await engine.dispose()


async def test_resolve_project_access_inactive_user_denied():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            inactive = await _user(db, "inactive", active=False)
            await _project(db, created_by=owner.id, visibility=PROJECT_VISIBILITY_PUBLIC)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()

            access = await resolve_project_access(db, project_id="proj-1", user=inactive)
            assert access is None
    finally:
        await engine.dispose()


async def test_resolve_project_access_nonexistent_returns_none():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            user = await _user(db, "user")
            access = await resolve_project_access(db, project_id="missing", user=user)
            assert access is None
    finally:
        await engine.dispose()


async def test_require_capability_raises_404_for_hidden_project():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            stranger = await _user(db, "stranger")
            await _project(db, created_by=owner.id, visibility=PROJECT_VISIBILITY_PRIVATE)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()

            from fastapi import HTTPException

            try:
                await require_capability(db, project_id="proj-1", user=stranger, capability="project.view")
                pytest.fail("expected 404")
            except HTTPException as exc:
                assert exc.status_code == 404
    finally:
        await engine.dispose()


async def test_require_capability_raises_403_for_insufficient_role():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            viewer = await _user(db, "viewer")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            db.add(ProjectMember(project_id="proj-1", user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
            await db.flush()

            from fastapi import HTTPException

            try:
                await require_capability(db, project_id="proj-1", user=viewer, capability="project.edit")
                pytest.fail("expected 403")
            except HTTPException as exc:
                assert exc.status_code == 403
    finally:
        await engine.dispose()


async def test_count_owners_returns_correct_count():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            second = await _user(db, "second")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            db.add(ProjectMember(project_id="proj-1", user_id=second.id, role=PROJECT_ROLE_OWNER))
            await db.flush()

            assert await count_owners(db, "proj-1") == 2
    finally:
        await engine.dispose()


async def test_ensure_not_last_owner_blocks_demote_of_last_owner():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()

            try:
                await ensure_not_last_owner(db, project_id="proj-1", user_id=owner.id, new_role=PROJECT_ROLE_VIEWER)
                pytest.fail("expected ProjectAccessError")
            except ProjectAccessError:
                pass
    finally:
        await engine.dispose()


async def test_ensure_not_last_owner_allows_demote_when_multiple_owners():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            second = await _user(db, "second")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            db.add(ProjectMember(project_id="proj-1", user_id=second.id, role=PROJECT_ROLE_OWNER))
            await db.flush()

            # A regular Owner may be demoted while a Primary Owner remains.
            await ensure_not_last_owner(db, project_id="proj-1", user_id=second.id, new_role=PROJECT_ROLE_VIEWER)
            # The Primary Owner itself is always protected.
            with pytest.raises(ProjectAccessError):
                await ensure_not_last_owner(db, project_id="proj-1", user_id=owner.id, new_role=PROJECT_ROLE_VIEWER)
    finally:
        await engine.dispose()


async def test_ensure_not_last_owner_allows_removal_when_not_owner():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            viewer = await _user(db, "viewer")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            db.add(ProjectMember(project_id="proj-1", user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
            await db.flush()

            # Removing a viewer should not trigger the last-owner check
            await ensure_not_last_owner(db, project_id="proj-1", user_id=viewer.id, new_role=None)
    finally:
        await engine.dispose()


async def test_append_project_audit_creates_immutable_event():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            event = await append_project_audit(
                db,
                project_id="proj-1",
                event_type="project.created",
                actor_user_id=owner.id,
                payload={"name": "Test"},
            )
            assert event.id is not None
            assert event.event_type == "project.created"
            assert event.outcome == "success"
            assert event.payload_json == {"name": "Test"}
            await db.commit()

            # Mutation should be rejected
            event.event_type = "tampered"
            try:
                await db.commit()
                pytest.fail("expected append-only guard")
            except ValueError:
                await db.rollback()
    finally:
        await engine.dispose()


async def test_bump_acl_version_increments():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            project = await _project(db, created_by=owner.id)
            assert project.acl_version == 1

            v = await bump_acl_version(db, project)
            assert v == 2
            assert project.acl_version == 2

            v = await bump_acl_version(db, project)
            assert v == 3
    finally:
        await engine.dispose()


async def test_invitation_role_constraint_rejects_owner_at_model_level():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            await _project(db, created_by=owner.id)
            db.add(ProjectMember(project_id="proj-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()

            invite = ProjectInvitation(
                id="inv-1",
                project_id="proj-1",
                role=PROJECT_ROLE_OWNER,  # should violate CHECK
                token_hash="hash",
                max_uses=1,
                use_count=0,
                expires_at=__import__("datetime").datetime.utcnow(),
            )
            db.add(invite)
            try:
                await db.flush()
                pytest.fail("expected CHECK constraint violation")
            except Exception:
                await db.rollback()
    finally:
        await engine.dispose()
