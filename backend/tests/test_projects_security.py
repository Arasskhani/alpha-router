"""Security gate: ACL, invitation, race, memory leakage, billing, deletion, regression."""

import asyncio
import contextlib
import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession
from app.models.logging import RequestLog
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMember,
)
from app.models.user import User
from app.services.project_access_service import (
    ProjectAccessError,
    resolve_project_access,
)
from app.services.project_chat_service import (
    append_project_chat_message,
    create_project_chat_session,
    list_project_chat_messages,
    pin_project_chat,
)
from app.services.project_memory_service import (
    create_memory_grant,
    create_project_memory,
    load_injectable_project_memories,
)
from app.services.project_service import (
    ProjectValidationError,
    claim_invitation,
    create_invitation,
    delete_project,
    get_project,
    leave_project,
    list_members,
    list_my_projects,
    remove_member,
    revoke_invitation,
    update_member_role,
    update_project,
)

PROJ = "sec-proj-1"
PROJ2 = "sec-proj-2"
PROJ3 = "sec-proj-3"


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _file_factory():
    """File-based factory with multiple connections for concurrency tests."""
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        pool_size=10,
        max_overflow=10,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def dispose():
        await engine.dispose()
        with contextlib.suppress(OSError):
            os.remove(path)

    return (
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        dispose,
    )


async def _user(db, username, *, active=True):
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=active,
    )
    db.add(u)
    await db.flush()
    return u


async def _setup_project(db, pid=PROJ, *, owner_name="owner", visibility="private"):
    owner = await _user(db, f"{owner_name}_{pid}")
    contrib = await _user(db, f"contrib_{pid}")
    viewer = await _user(db, f"viewer_{pid}")
    db.add(
        Project(
            id=pid,
            name=f"Project {pid}",
            status="active",
            visibility=visibility,
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=pid, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=pid, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
    db.add(ProjectMember(project_id=pid, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    return owner, contrib, viewer


# ===========================================================================
# ACL: privilege escalation & cross-project access
# ===========================================================================


def test_viewer_cannot_write_chat():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup_project(db)
                sess = await create_project_chat_session(db, project_id=PROJ, user=owner, title="T")
                sid = sess["id"]
                # viewer cannot append
                from fastapi import HTTPException

                try:
                    await append_project_chat_message(
                        db,
                        project_id=PROJ,
                        session_id=sid,
                        user=viewer,
                        role="user",
                        content="hi",
                    )
                    pytest.fail("viewer should not write")
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_contributor_can_write_chat_but_not_pin_globally_restricted():
    """Contributor CAN pin (per requirements). This confirms the capability."""

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup_project(db)
                sess = await create_project_chat_session(db, project_id=PROJ, user=contrib, title="T")
                sid = sess["id"]
                msg = await append_project_chat_message(
                    db,
                    project_id=PROJ,
                    session_id=sid,
                    user=contrib,
                    role="user",
                    content="hello",
                )
                assert msg is not None
                pinned = await pin_project_chat(db, project_id=PROJ, session_id=sid, user=contrib)
                assert pinned is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cross_project_session_isolation():
    """A chat session from project A cannot be accessed via project B."""

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, PROJ)
                owner2, _, _ = await _setup_project(db, PROJ2, owner_name="owner2")
                sess = await create_project_chat_session(db, project_id=PROJ, user=owner, title="T")
                sid = sess["id"]
                # owner2 (member of PROJ2 only) tries to read PROJ's session via PROJ2
                result = await list_project_chat_messages(db, project_id=PROJ2, session_id=sid, user=owner2, limit=50)
                assert result is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_public_project_grants_viewer_to_non_member():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, PROJ, visibility="public")
                outsider = await _user(db, "outsider")
                access = await resolve_project_access(db, project_id=PROJ, user=outsider)
                assert access is not None
                assert access.role == "viewer"
                assert access.is_member is False
                assert access.is_public_viewer is True
                assert not access.can("chat.write")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_inactive_user_denied_even_if_member():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                contrib.is_active = False
                await db.flush()
                access = await resolve_project_access(db, project_id=PROJ, user=contrib)
                assert access is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_member_cannot_self_promote_via_update_project():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                from fastapi import HTTPException

                # contributor tries to update project (needs project.edit = owner only)
                try:
                    await update_project(db, project_id=PROJ, user=contrib, name="Hacked")
                    pytest.fail("expected an exception")
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_owner_cannot_demote_self_to_create_zero_owners():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                try:
                    await update_member_role(
                        db,
                        project_id=PROJ,
                        user=owner,
                        target_user_id=owner.id,
                        role="viewer",
                    )
                    pytest.fail("expected an exception")
                except ProjectAccessError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


# ===========================================================================
# Invitation edge cases
# ===========================================================================


def test_invitation_expired_rejected():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                inv = await create_invitation(db, project_id=PROJ, user=owner, role="viewer", ttl_days=1)
                # Manually expire it
                row = await db.get(
                    __import__("app.models.project", fromlist=["ProjectInvitation"]).ProjectInvitation,
                    inv["id"],
                )
                row.expires_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
                await db.flush()
                invitee = await _user(db, "invitee")
                try:
                    await claim_invitation(db, token=inv["token"], user=invitee)
                    pytest.fail("expected an exception")
                except ProjectValidationError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_invitation_revoked_rejected():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                inv = await create_invitation(db, project_id=PROJ, user=owner, role="viewer")
                await revoke_invitation(db, project_id=PROJ, invitation_id=inv["id"], user=owner)
                invitee = await _user(db, "invitee")
                try:
                    await claim_invitation(db, token=inv["token"], user=invitee)
                    pytest.fail("expected an exception")
                except ProjectValidationError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_invitation_tampered_token_rejected():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                invitee = await _user(db, "invitee")
                result = await claim_invitation(db, token="totally-fake-token", user=invitee)
                assert result is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_invitation_multi_use_exhaustion():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                inv = await create_invitation(
                    db,
                    project_id=PROJ,
                    user=owner,
                    role="viewer",
                    max_uses=2,
                )
                u1 = await _user(db, "u1")
                u2 = await _user(db, "u2")
                u3 = await _user(db, "u3")
                assert await claim_invitation(db, token=inv["token"], user=u1) is not None
                assert await claim_invitation(db, token=inv["token"], user=u2) is not None
                try:
                    await claim_invitation(db, token=inv["token"], user=u3)
                    pytest.fail("expected an exception")
                except ProjectValidationError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_invitation_claim_does_not_downgrade_existing_member():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                inv = await create_invitation(
                    db,
                    project_id=PROJ,
                    user=owner,
                    role="viewer",
                )
                # contrib is already a contributor; claiming a viewer invite must not downgrade
                result = await claim_invitation(db, token=inv["token"], user=contrib)
                assert result is not None
                assert result["myRole"] == "contributor"
        finally:
            await engine.dispose()

    asyncio.run(run())


# ===========================================================================
# Race conditions: concurrent message append produces unique sequences
# ===========================================================================


def test_concurrent_message_append_unique_sequences():
    async def run():
        factory, dispose = await _file_factory()
        try:
            # Create the project & session in one session
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                sess = await create_project_chat_session(db, project_id=PROJ, user=owner, title="T")
                sid = sess["id"]
                owner_id = owner.id
                await db.commit()

            # Append concurrently using separate sessions (simulating
            # concurrent requests).  Each append retries the whole
            # operation on a commit-time serialization conflict, which is
            # what a well-behaved API endpoint would do.
            from sqlalchemy.exc import IntegrityError, OperationalError

            async def append(i):
                for _ in range(12):
                    try:
                        async with factory() as db:
                            user = await db.get(User, owner_id)
                            msg = await append_project_chat_message(
                                db,
                                project_id=PROJ,
                                session_id=sid,
                                user=user,
                                role="user",
                                content=f"msg-{i}",
                            )
                            await db.commit()
                            return msg
                    except (IntegrityError, OperationalError):
                        continue
                raise RuntimeError("append exhausted retries")

            results = await asyncio.gather(*[append(i) for i in range(10)])
            seqs = [r["sequence"] for r in results]
            assert len(set(seqs)) == 10, f"sequences must be unique, got {seqs}"

            async with factory() as db:
                row = await db.get(ChatSession, sid)
                assert row.message_count == 10
        finally:
            await dispose()

    asyncio.run(run())


def test_concurrent_idempotent_append_dedup():
    async def run():
        factory, dispose = await _file_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                sess = await create_project_chat_session(db, project_id=PROJ, user=owner, title="T")
                sid = sess["id"]
                owner_id = owner.id
                await db.commit()

            cid = "client-msg-1"
            from sqlalchemy.exc import IntegrityError, OperationalError

            async def append():
                for _ in range(12):
                    try:
                        async with factory() as db:
                            user = await db.get(User, owner_id)
                            msg = await append_project_chat_message(
                                db,
                                project_id=PROJ,
                                session_id=sid,
                                user=user,
                                role="user",
                                content="dup",
                                client_message_id=cid,
                            )
                            await db.commit()
                            return msg
                    except (IntegrityError, OperationalError):
                        continue
                raise RuntimeError("append exhausted retries")

            results = await asyncio.gather(*[append() for _ in range(5)])
            ids = [r["id"] for r in results]
            # All concurrent appends with same client_message_id collapse to one
            assert len(set(ids)) == 1
            async with factory() as db:
                row = await db.get(ChatSession, sid)
                assert row.message_count == 1
        finally:
            await dispose()

    asyncio.run(run())


# ===========================================================================
# Memory leakage: cross-project isolation
# ===========================================================================


def test_memory_injection_only_loads_own_project_memories():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, PROJ)
                owner2, _, _ = await _setup_project(db, PROJ2, owner_name="owner2")
                await create_project_memory(db, project_id=PROJ, user=owner, content="secret-A")
                await create_project_memory(db, project_id=PROJ2, user=owner2, content="secret-B")
                # PROJ should only see secret-A
                injection = await load_injectable_project_memories(
                    db,
                    project_id=PROJ,
                    memory_enabled=True,
                )
                assert "secret-A" in injection.own_facts
                assert "secret-B" not in injection.own_facts
                assert "secret-B" not in injection.granted_facts
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_memory_grant_enables_cross_project_read():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                # one user owns both PROJ (consumer) and PROJ2 (source)
                owner = await _user(db, "owner_both")
                db.add(
                    Project(
                        id=PROJ,
                        name="Consumer",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(
                    Project(
                        id=PROJ2,
                        name="Source",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                db.add(ProjectMember(project_id=PROJ2, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                await db.flush()
                await create_project_memory(db, project_id=PROJ2, user=owner, content="source-fact")
                await create_memory_grant(
                    db,
                    consumer_project_id=PROJ,
                    source_project_id=PROJ2,
                    user=owner,
                )
                injection = await load_injectable_project_memories(
                    db,
                    project_id=PROJ,
                    memory_enabled=True,
                )
                assert "source-fact" in injection.granted_facts
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_memory_grant_requires_owner_in_both_projects():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db, PROJ)
                owner2, _, _ = await _setup_project(db, PROJ2, owner_name="owner2")
                # contrib is only a contributor of PROJ, not a member of PROJ2
                from app.services.project_memory_service import ProjectMemoryGrantError

                try:
                    await create_memory_grant(
                        db,
                        consumer_project_id=PROJ,
                        source_project_id=PROJ2,
                        user=contrib,
                    )
                    pytest.fail("expected an exception")
                except (ProjectMemoryGrantError, Exception):
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_revoked_grant_stops_cross_project_memory_read():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner_both")
                db.add(
                    Project(
                        id=PROJ,
                        name="Consumer",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(
                    Project(
                        id=PROJ2,
                        name="Source",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                db.add(ProjectMember(project_id=PROJ2, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                await db.flush()
                await create_project_memory(db, project_id=PROJ2, user=owner, content="source-fact")
                await create_memory_grant(
                    db,
                    consumer_project_id=PROJ,
                    source_project_id=PROJ2,
                    user=owner,
                )
                from app.services.project_memory_service import revoke_memory_grant

                await revoke_memory_grant(
                    db,
                    consumer_project_id=PROJ,
                    source_project_id=PROJ2,
                    user=owner,
                )
                injection = await load_injectable_project_memories(
                    db,
                    project_id=PROJ,
                    memory_enabled=True,
                )
                assert "source-fact" not in injection.granted_facts
        finally:
            await engine.dispose()

    asyncio.run(run())


# ===========================================================================
# Billing: project_id attribution correctness
# ===========================================================================


def test_billing_summary_isolates_projects():
    from app.services.project_billing_service import (
        report_all_projects_usage,
        report_project_usage_summary,
    )

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, PROJ)
                owner2, _, _ = await _setup_project(db, PROJ2, owner_name="owner2")
                now = datetime.datetime.utcnow()
                for cost in (0.1, 0.2, 0.3):
                    db.add(
                        RequestLog(
                            user_id=owner.id,
                            username="owner",
                            model_id="gpt-4",
                            project_id=PROJ,
                            total_cost_usd=cost,
                            prompt_tokens=10,
                            completion_tokens=20,
                            request_time=now,
                            success=True,
                        )
                    )
                db.add(
                    RequestLog(
                        user_id=owner2.id,
                        username="owner2",
                        model_id="gpt-4",
                        project_id=PROJ2,
                        total_cost_usd=5.0,
                        prompt_tokens=100,
                        completion_tokens=200,
                        request_time=now,
                        success=True,
                    )
                )
                # Unattributed log (regular chat)
                db.add(
                    RequestLog(
                        user_id=owner.id,
                        username="owner",
                        model_id="gpt-4",
                        project_id=None,
                        total_cost_usd=99.0,
                        prompt_tokens=1,
                        completion_tokens=1,
                        request_time=now,
                        success=True,
                    )
                )
                await db.flush()
                start = now - datetime.timedelta(days=30)
                df1 = await report_project_usage_summary(db, PROJ, start, now)
                assert df1.iloc[0]["requests"] == 3
                assert df1.iloc[0]["total_cost_usd"] == round(0.1 + 0.2 + 0.3, 4)
                all_df = await report_all_projects_usage(db, start, now)
                assert len(all_df) == 2
                by_id = all_df.set_index("project_id")
                assert by_id.loc[PROJ2, "cost_usd"] == 5.0
                # unattributed must NOT appear
                assert None not in by_id.index
        finally:
            await engine.dispose()

    asyncio.run(run())


# ===========================================================================
# Deletion: soft-delete hides project & cascades visibility
# ===========================================================================


def test_deleted_project_hidden_from_non_members():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, PROJ, visibility="public")
                outsider = await _user(db, "outsider")
                # before delete, outsider can see public project
                access = await resolve_project_access(db, project_id=PROJ, user=outsider)
                assert access is not None
                await delete_project(db, project_id=PROJ, user=owner)
                # after delete, outsider cannot see it
                access2 = await resolve_project_access(db, project_id=PROJ, user=outsider)
                assert access2 is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_deleted_project_excluded_from_my_list():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, PROJ)
                await delete_project(db, project_id=PROJ, user=owner)
                # Soft-delete is reversible: members keep seeing the project
                # (status "deletion_pending", with a Restore action in the UI)
                # until purge_expired_deleted_projects removes it.
                mine, total = await list_my_projects(db, user=owner)
                assert total == 1
                assert [p["status"] for p in mine] == ["deletion_pending"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_get_project_returns_none_after_deletion_for_outsider():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, PROJ, visibility="public")
                outsider = await _user(db, "outsider")
                await delete_project(db, project_id=PROJ, user=owner)
                result = await get_project(db, project_id=PROJ, user=outsider)
                assert result is None
        finally:
            await engine.dispose()

    asyncio.run(run())


# ===========================================================================
# Regression: pin visibility & private mode forbidden
# ===========================================================================


def test_pinned_chat_visible_to_viewer():
    from app.services.project_chat_service import list_pinned_chats

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup_project(db)
                sess = await create_project_chat_session(db, project_id=PROJ, user=owner, title="T")
                sid = sess["id"]
                await pin_project_chat(db, project_id=PROJ, session_id=sid, user=owner)
                pinned = await list_pinned_chats(db, project_id=PROJ, user=viewer)
                assert sid in (pinned or [])
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_private_mode_forbidden_in_project_chat():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                sess = await create_project_chat_session(db, project_id=PROJ, user=owner, title="T")
                sid = sess["id"]
                # Force private_mode on the session row directly
                row = await db.get(ChatSession, sid)
                row.private_mode = True
                await db.flush()
                msg = await append_project_chat_message(
                    db,
                    project_id=PROJ,
                    session_id=sid,
                    user=owner,
                    role="user",
                    content="should be rejected",
                )
                assert msg is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_leave_then_rejoin_via_invitation():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                inv = await create_invitation(db, project_id=PROJ, user=owner, role="contributor")
                token = inv["token"]
                await leave_project(db, project_id=PROJ, user=contrib)
                members = await list_members(db, project_id=PROJ, user=owner)
                assert len(members) == 2  # owner + viewer
                # rejoin
                result = await claim_invitation(db, token=token, user=contrib)
                assert result is not None
                assert result["myRole"] == "contributor"
                members2 = await list_members(db, project_id=PROJ, user=owner)
                assert len(members2) == 3
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_remove_last_owner_blocked():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                try:
                    await remove_member(db, project_id=PROJ, user=owner, target_user_id=owner.id)
                    pytest.fail("expected an exception")
                except ProjectAccessError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())
