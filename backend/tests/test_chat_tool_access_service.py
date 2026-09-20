"""Granting and refusing chat tools.

The rules are not new - ``evaluate_access`` has decided agent and knowledge
base access since Phase 5 - but the resource is. A chat tool has no row of its
own, so what is tested here is that a *key* behaves like a resource: that an
unsaved tool is open to everyone, that saving a policy restricts it, that deny
beats allow, and that none of it needs a code change when the registry grows.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.chat_tool import ChatToolAccessAssignment, ChatToolPolicy
from app.models.user import User, UserGroup, user_group_members
from app.services.chat_tool_access_service import (
    assert_tools_permitted,
    chat_tool_overview,
    get_chat_tool_access,
    permitted_tool_keys,
    set_chat_tool_access,
)
from app.services.chat_tool_registry import CHAT_TOOLS
from app.services.resource_access_service import (
    AccessGrant,
    ResourceAccessSubject,
    resolve_resource_access_subject,
)


async def _group(db, name: str, *user_ids: int) -> UserGroup:
    group = UserGroup(name=name)
    db.add(group)
    await db.flush()
    for user_id in user_ids:
        await db.execute(user_group_members.insert().values(group_id=group.id, user_id=user_id))
    await db.commit()
    return group


async def _second_user(db, username: str = "other", department: str | None = None) -> User:
    from app.core.security import hash_password

    row = User(
        username=username,
        email=f"{username}@test",
        hashed_password=hash_password("x"),
        auth_provider="local",
        is_active=True,
        department=department,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestAToolNobodyHasConfigured:
    async def test_is_available_to_everyone(self, db_session, user):
        """The upgrade that adds this must not take a tool away from anybody."""
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        assert await permitted_tool_keys(db_session, subject) == {spec.key for spec in CHAT_TOOLS}

    async def test_reads_as_public_with_no_grants(self, db_session):
        saved = await get_chat_tool_access(db_session, "code_interpreter")
        assert saved["access_type"] == "public"
        assert saved["grants"] == []
        assert saved["acl_version"] == 0

    async def test_appears_on_the_admin_page_before_anyone_saves_a_policy(self, db_session):
        rows = await chat_tool_overview(db_session)
        assert [row["key"] for row in rows] == [spec.key for spec in CHAT_TOOLS]
        assert all(row["access_type"] == "public" for row in rows)


class TestRestrictingATool:
    async def test_private_keeps_out_everyone_without_a_grant(self, db_session, user):
        await set_chat_tool_access(db_session, "code_interpreter", access_type="private", grants=[])
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        permitted = await permitted_tool_keys(db_session, subject)
        assert "code_interpreter" not in permitted
        assert "web_search" in permitted

    async def test_an_explicit_user_grant_lets_that_user_through(self, db_session, user):
        await set_chat_tool_access(
            db_session,
            "code_interpreter",
            access_type="private",
            grants=[AccessGrant(target_type="user", target=user.id)],
        )
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        assert "code_interpreter" in await permitted_tool_keys(db_session, subject)

    async def test_a_group_grant_covers_its_members_and_nobody_else(self, db_session, user):
        outsider = await _second_user(db_session)
        group = await _group(db_session, "data-team", user.id)
        await set_chat_tool_access(
            db_session,
            "code_interpreter",
            access_type="private",
            grants=[AccessGrant(target_type="group", target=group.id)],
        )
        await db_session.commit()

        member = await resolve_resource_access_subject(db_session, user_id=user.id)
        other = await resolve_resource_access_subject(db_session, user_id=outsider.id)
        assert "code_interpreter" in await permitted_tool_keys(db_session, member)
        assert "code_interpreter" not in await permitted_tool_keys(db_session, other)

    async def test_a_department_grant_is_matched_case_insensitively(self, db_session):
        person = await _second_user(db_session, "finance_person", department="  Finance  ")
        await set_chat_tool_access(
            db_session,
            "video_generation",
            access_type="private",
            grants=[AccessGrant(target_type="department", target="finance")],
        )
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=person.id)
        assert "video_generation" in await permitted_tool_keys(db_session, subject)

    async def test_deny_beats_a_group_allow(self, db_session, user):
        group = await _group(db_session, "everyone", user.id)
        await set_chat_tool_access(
            db_session,
            "web_search",
            access_type="private",
            grants=[
                AccessGrant(target_type="group", target=group.id, effect="allow"),
                AccessGrant(target_type="user", target=user.id, effect="deny"),
            ],
        )
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        assert "web_search" not in await permitted_tool_keys(db_session, subject)

    async def test_deny_works_on_a_public_tool_too(self, db_session, user):
        """The common case: leave it open, take it away from one person."""
        await set_chat_tool_access(
            db_session,
            "web_search",
            access_type="public",
            grants=[AccessGrant(target_type="user", target=user.id, effect="deny")],
        )
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        assert "web_search" not in await permitted_tool_keys(db_session, subject)

    async def test_a_super_admin_is_not_waved_through(self, db_session, admin):
        """Consistent with agents and knowledge bases: the role is a principal
        like any other, and an administrator who wants the tool grants it to
        the role."""
        await set_chat_tool_access(db_session, "code_interpreter", access_type="private", grants=[])
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=admin.id)
        assert "code_interpreter" not in await permitted_tool_keys(db_session, subject)

    async def test_granting_the_role_lets_every_holder_of_it_through(self, db_session, admin):
        await set_chat_tool_access(
            db_session,
            "code_interpreter",
            access_type="private",
            grants=[AccessGrant(target_type="role", target="super_admin")],
        )
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=admin.id)
        assert "code_interpreter" in await permitted_tool_keys(db_session, subject)


class TestSubjectsThatAreNotASignedInPerson:
    async def test_a_deactivated_account_gets_nothing(self, db_session, user):
        subject = ResourceAccessSubject(user_id=user.id, active=False)
        assert await permitted_tool_keys(db_session, subject) == frozenset()

    async def test_the_master_key_sees_only_public_tools(self, db_session):
        """``source="master"`` resolves to a public-only subject, so a private
        tool is refused rather than silently allowed to a keyholder with no
        user behind it."""
        await set_chat_tool_access(db_session, "code_interpreter", access_type="private", grants=[])
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, source="master")
        permitted = await permitted_tool_keys(db_session, subject)
        assert "code_interpreter" not in permitted
        assert "web_search" in permitted

    async def test_an_api_key_inherits_its_owner(self, db_session, user):
        from app.models.api_key import AlphaRouterApiKey

        key = AlphaRouterApiKey(
            name="k",
            key_prefix="ar_test",
            key_hash="x" * 64,
            owner_user_id=user.id,
            is_active=True,
        )
        db_session.add(key)
        await db_session.commit()
        await set_chat_tool_access(db_session, "web_fetch", access_type="private", grants=[])
        await db_session.commit()

        subject = await resolve_resource_access_subject(db_session, alpha_router_api_key_id=key.id)
        assert "web_fetch" not in await permitted_tool_keys(db_session, subject)

        await set_chat_tool_access(
            db_session,
            "web_fetch",
            access_type="private",
            grants=[AccessGrant(target_type="user", target=user.id)],
        )
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, alpha_router_api_key_id=key.id)
        assert "web_fetch" in await permitted_tool_keys(db_session, subject)


class TestTheGuardEndpointsCall:
    async def test_a_turn_that_asks_for_nothing_is_not_a_database_query(self, db_session, user):
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        await assert_tools_permitted(db_session, subject, [])

    async def test_an_unknown_key_is_ignored_rather_than_refused(self, db_session, user):
        """Enforcement governs the tools this product has. A key it does not
        know is not a tool, and refusing it would be refusing nothing."""
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        await assert_tools_permitted(db_session, subject, ["not_a_tool"])

    async def test_the_refusal_names_the_tool_so_the_client_can_switch_it_off(self, db_session, user):
        await set_chat_tool_access(db_session, "code_interpreter", access_type="private", grants=[])
        await db_session.commit()
        subject = await resolve_resource_access_subject(db_session, user_id=user.id)
        with pytest.raises(HTTPException) as caught:
            await assert_tools_permitted(db_session, subject, ["web_search", "code_interpreter"])
        assert caught.value.status_code == 403
        assert caught.value.detail["code"] == "tool_not_permitted"
        assert caught.value.detail["tool"] == "code_interpreter"
        assert "Code Interpreter" in caught.value.detail["message"]


class TestSavingAPolicy:
    async def test_saving_twice_replaces_rather_than_accumulates(self, db_session, user):
        for _ in range(2):
            await set_chat_tool_access(
                db_session,
                "web_search",
                access_type="private",
                grants=[AccessGrant(target_type="user", target=user.id)],
            )
        await db_session.commit()
        rows = (await db_session.execute(select(ChatToolAccessAssignment))).scalars().all()
        assert len(rows) == 1

    async def test_every_save_moves_the_acl_version(self, db_session):
        first = await set_chat_tool_access(db_session, "web_search", access_type="private", grants=[])
        second = await set_chat_tool_access(db_session, "web_search", access_type="public", grants=[])
        await db_session.commit()
        assert (first["acl_version"], second["acl_version"]) == (1, 2)

    async def test_the_saving_administrator_is_recorded(self, db_session, admin):
        await set_chat_tool_access(
            db_session, "web_search", access_type="private", grants=[], assigned_by_user_id=admin.id
        )
        await db_session.commit()
        policy = await db_session.get(ChatToolPolicy, "web_search")
        assert policy is not None and policy.updated_by_user_id == admin.id

    async def test_a_grant_for_somebody_who_does_not_exist_is_refused(self, db_session):
        with pytest.raises(ValueError):
            await set_chat_tool_access(
                db_session,
                "web_search",
                access_type="private",
                grants=[AccessGrant(target_type="user", target=999999)],
            )

    async def test_an_unknown_access_type_is_refused(self, db_session):
        with pytest.raises(ValueError):
            await set_chat_tool_access(db_session, "web_search", access_type="sometimes", grants=[])

    async def test_a_tool_the_registry_does_not_know_has_no_policy_to_save(self, db_session):
        with pytest.raises(HTTPException) as caught:
            await set_chat_tool_access(db_session, "rm_rf", access_type="private", grants=[])
        assert caught.value.status_code == 404

    async def test_the_overview_counts_allows_and_denies_separately(self, db_session, user):
        other = await _second_user(db_session)
        await set_chat_tool_access(
            db_session,
            "web_search",
            access_type="public",
            grants=[
                AccessGrant(target_type="user", target=user.id, effect="allow"),
                AccessGrant(target_type="user", target=other.id, effect="deny"),
            ],
        )
        await db_session.commit()
        row = next(r for r in await chat_tool_overview(db_session) if r["key"] == "web_search")
        assert (row["allow_count"], row["deny_count"]) == (1, 1)


class TestGrantsSurviveTheirTargets:
    async def test_deleting_a_group_takes_its_grant_with_it(self, db_session, user):
        group = await _group(db_session, "temp", user.id)
        await set_chat_tool_access(
            db_session,
            "web_search",
            access_type="private",
            grants=[AccessGrant(target_type="group", target=group.id)],
        )
        await db_session.commit()

        await db_session.delete(await db_session.get(UserGroup, group.id))
        await db_session.commit()

        rows = (await db_session.execute(select(ChatToolAccessAssignment))).scalars().all()
        assert rows == []
