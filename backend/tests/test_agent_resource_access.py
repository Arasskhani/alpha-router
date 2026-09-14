"""Deny-first Agent and Knowledge resource ACL tests."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.agent import Agent
from app.models.knowledge import KnowledgeBase, KnowledgeDocument
from app.models.user import User, UserGroup, UserRoleAssignment, user_group_members
from app.services.rbac import AGENT_DESIGNER_SLUG, SUPER_ADMIN_SLUG, USER_SLUG
from app.services.resource_access_service import (
    AccessGrant,
    compile_acl_payload,
    filter_agents_for_subject,
    resolve_resource_access_subject,
    set_agent_access,
    set_document_access,
    set_knowledge_base_access,
    user_can_access_agent,
    user_can_access_document,
    user_can_access_knowledge_base,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(
    db: AsyncSession,
    username: str,
    *,
    department: str | None = None,
    roles: tuple[str, ...] = (USER_SLUG,),
    active: bool = True,
) -> User:
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=active,
        department=department,
    )
    db.add(user)
    await db.flush()
    for role in roles:
        db.add(UserRoleAssignment(user_id=user.id, role_slug=role))
    await db.flush()
    return user


async def _agent(
    db: AsyncSession,
    slug: str,
    *,
    access_type: str = "private",
) -> Agent:
    agent = Agent(
        id=f"agent-{slug}",
        slug=slug,
        name=slug,
        status="active",
        access_type=access_type,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _knowledge(
    db: AsyncSession,
    slug: str,
    *,
    access_type: str = "private",
) -> tuple[KnowledgeBase, KnowledgeDocument]:
    knowledge_base = KnowledgeBase(
        id=f"kb-{slug}",
        slug=slug,
        name=slug,
        status="active",
        access_type=access_type,
        sensitivity="internal",
    )
    document = KnowledgeDocument(
        id=f"doc-{slug}",
        knowledge_base_id=knowledge_base.id,
        canonical_key=f"{slug}.md",
        title=slug,
        status="active",
    )
    db.add(knowledge_base)
    db.add(document)
    await db.flush()
    return knowledge_base, document


async def _test_public_access_and_inactive_denial() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        active = await _user(db, "active")
        inactive = await _user(db, "inactive", active=False)
        agent = await _agent(db, "public", access_type="public")
        assert await user_can_access_agent(
            db,
            agent,
            await resolve_resource_access_subject(db, user_id=active.id),
        )
        assert not await user_can_access_agent(
            db,
            agent,
            await resolve_resource_access_subject(db, user_id=inactive.id),
        )
    await engine.dispose()


async def _test_private_assignments_cover_all_principal_types() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        direct = await _user(db, "direct")
        group_member = await _user(db, "group-member")
        department_member = await _user(db, "department", department="Finance")
        role_member = await _user(db, "designer", roles=(USER_SLUG, AGENT_DESIGNER_SLUG))
        outsider = await _user(db, "outsider")
        group = UserGroup(name="legal", source="local")
        db.add(group)
        await db.flush()
        await db.execute(user_group_members.insert().values(user_id=group_member.id, group_id=group.id))
        agent = await _agent(db, "private")
        await set_agent_access(
            db,
            agent,
            access_type="private",
            grants=[
                AccessGrant("user", direct.id),
                AccessGrant("group", group.id),
                AccessGrant("department", " FINANCE "),
                AccessGrant("role", AGENT_DESIGNER_SLUG),
            ],
        )
        await db.flush()

        for user in (direct, group_member, department_member, role_member):
            assert await user_can_access_agent(
                db,
                agent,
                await resolve_resource_access_subject(db, user_id=user.id),
            )
        assert not await user_can_access_agent(
            db,
            agent,
            await resolve_resource_access_subject(db, user_id=outsider.id),
        )
    await engine.dispose()


async def _test_deny_overrides_public_and_allow() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = await _user(db, "blocked", department="Finance")
        agent = await _agent(db, "deny", access_type="public")
        await set_agent_access(
            db,
            agent,
            access_type="public",
            grants=[
                AccessGrant("user", user.id, "allow"),
                AccessGrant("department", "finance", "deny"),
            ],
        )
        await db.flush()
        assert not await user_can_access_agent(
            db,
            agent,
            await resolve_resource_access_subject(db, user_id=user.id),
        )
    await engine.dispose()


async def _test_super_admin_requires_explicit_break_glass() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        admin = await _user(db, "root", roles=(SUPER_ADMIN_SLUG,))
        agent = await _agent(db, "restricted")
        normal_subject = await resolve_resource_access_subject(db, user_id=admin.id)
        break_glass_subject = await resolve_resource_access_subject(
            db,
            user_id=admin.id,
            break_glass=True,
        )
        assert not await user_can_access_agent(db, agent, normal_subject)
        assert await user_can_access_agent(db, agent, break_glass_subject)
    await engine.dispose()


async def _test_document_acl_restricts_inherited_kb_access() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        allowed = await _user(db, "allowed")
        outsider = await _user(db, "outsider")
        knowledge_base, document = await _knowledge(db, "policies", access_type="public")
        await set_document_access(
            db,
            document,
            grants=[AccessGrant("user", allowed.id)],
        )
        await db.flush()
        allowed_subject = await resolve_resource_access_subject(db, user_id=allowed.id)
        outsider_subject = await resolve_resource_access_subject(db, user_id=outsider.id)
        assert await user_can_access_knowledge_base(db, knowledge_base, allowed_subject)
        assert await user_can_access_document(db, document, allowed_subject)
        assert not await user_can_access_document(db, document, outsider_subject)
    await engine.dispose()


async def _test_kb_acl_is_required_even_with_document_allow() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = await _user(db, "document-only")
        knowledge_base, document = await _knowledge(db, "legal")
        await set_knowledge_base_access(
            db,
            knowledge_base,
            access_type="private",
            grants=[],
        )
        await set_document_access(db, document, grants=[AccessGrant("user", user.id)])
        await db.flush()
        subject = await resolve_resource_access_subject(db, user_id=user.id)
        assert not await user_can_access_document(db, document, subject)
    await engine.dispose()


async def _test_filter_and_acl_version_increment() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = await _user(db, "alice")
        public = await _agent(db, "public-list", access_type="public")
        private = await _agent(db, "private-list")
        initial_version = int(private.acl_version)
        await set_agent_access(
            db,
            private,
            access_type="private",
            grants=[AccessGrant("user", user.id), AccessGrant("user", user.id)],
        )
        await db.flush()
        assert private.acl_version == initial_version + 1
        visible = await filter_agents_for_subject(
            db,
            [public, private],
            await resolve_resource_access_subject(db, user_id=user.id),
        )
        assert [item.id for item in visible] == [public.id, private.id]
    await engine.dispose()


async def test_public_access_and_inactive_denial():
    await _test_public_access_and_inactive_denial()


async def test_private_assignments_cover_all_principal_types():
    await _test_private_assignments_cover_all_principal_types()


async def test_deny_overrides_public_and_allow():
    await _test_deny_overrides_public_and_allow()


async def test_super_admin_requires_explicit_break_glass():
    await _test_super_admin_requires_explicit_break_glass()


async def test_document_acl_restricts_inherited_kb_access():
    await _test_document_acl_restricts_inherited_kb_access()


async def test_kb_acl_is_required_even_with_document_allow():
    await _test_kb_acl_is_required_even_with_document_allow()


async def test_filter_and_acl_version_increment():
    await _test_filter_and_acl_version_increment()


def test_compile_acl_payload_is_normalized_and_deny_aware():
    class Assignment:
        def __init__(
            self,
            *,
            user_id=None,
            group_id=None,
            department=None,
            role_slug=None,
            effect="allow",
        ):
            self.user_id = user_id
            self.group_id = group_id
            self.department = department
            self.role_slug = role_slug
            self.effect = effect

    payload = compile_acl_payload(
        [
            Assignment(user_id=1),
            Assignment(department=" Finance "),
            Assignment(group_id=4, effect="deny"),
        ]
    )
    assert payload == {
        "allow_principal_tokens": ["department:finance", "user:1"],
        "deny_principal_tokens": ["group:4"],
    }
