"""Agent draft, publish, immutability, and rollback lifecycle tests."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.agent import AgentAuditEvent, AgentKnowledgeBinding
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.services.agent_definition_service import (
    create_agent,
    create_agent_version,
    discard_agent_draft,
    get_active_agent_version,
    normalize_agent_slug,
    publish_agent_version,
    revoke_agent_knowledge_binding,
    rollback_agent_version,
    submit_agent_version,
    update_agent_draft,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db: AsyncSession, username: str) -> User:
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


async def _test_agent_version_lifecycle() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        author = await _user(db, "author")
        publisher = await _user(db, "publisher")
        agent = await create_agent(
            db,
            name="Legal Consultant",
            slug="Legal Consultant",
            created_by_user_id=author.id,
        )
        first = await create_agent_version(
            db,
            agent,
            system_prompt="Answer only from approved legal sources.",
            created_by_user_id=author.id,
            model_policy={"primary_model_id": "model-1"},
        )
        await submit_agent_version(db, first, actor_user_id=author.id)
        with pytest.raises(ValueError, match="Maker-checker"):
            await publish_agent_version(db, first, actor_user_id=author.id)
        await publish_agent_version(db, first, actor_user_id=publisher.id)
        await db.flush()

        assert agent.status == "active"
        assert first.status == "published"
        assert (await get_active_agent_version(db, agent.id)).id == first.id
        with pytest.raises(ValueError, match="Only draft"):
            await update_agent_draft(
                db,
                first,
                system_prompt="Mutated published prompt",
                actor_user_id=author.id,
            )

        second = await create_agent_version(
            db,
            agent,
            system_prompt="Answer from approved sources and cite each claim.",
            created_by_user_id=author.id,
            model_policy={"primary_model_id": "model-2"},
        )
        await submit_agent_version(db, second, actor_user_id=author.id)
        await publish_agent_version(db, second, actor_user_id=publisher.id)
        await db.flush()
        assert first.status == "archived"
        assert first.active_scope_key is None
        assert second.status == "published"

        await rollback_agent_version(
            db,
            first,
            actor_user_id=publisher.id,
            reason="Regression in citation quality",
        )
        await db.flush()
        assert first.status == "published"
        assert second.status == "archived"
        assert (await get_active_agent_version(db, agent.id)).id == first.id

        events = (
            (await db.execute(select(AgentAuditEvent.event_type).where(AgentAuditEvent.agent_id == agent.id)))
            .scalars()
            .all()
        )
        assert "agent.created" in events
        assert events.count("agent.version.published") == 2
        assert "agent.version.rolled_back" in events
    await engine.dispose()


async def _test_duplicate_slug_and_draft_fingerprint_change() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        author = await _user(db, "author")
        agent = await create_agent(
            db,
            name="IT Helpdesk",
            slug="IT Helpdesk",
            created_by_user_id=author.id,
        )
        with pytest.raises(ValueError, match="already exists"):
            await create_agent(
                db,
                name="Duplicate",
                slug="it-helpdesk",
                created_by_user_id=author.id,
            )
        version = await create_agent_version(
            db,
            agent,
            system_prompt="Initial prompt",
            created_by_user_id=author.id,
        )
        old_fingerprint = version.fingerprint
        await update_agent_draft(
            db,
            version,
            system_prompt="Updated prompt",
            policies={"retrieval_policy": {"top_k": 8}},
            actor_user_id=author.id,
        )
        assert version.fingerprint != old_fingerprint
        assert version.retrieval_policy == {"top_k": 8}
    await engine.dispose()


async def _test_discard_agent_draft() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        author = await _user(db, "author")
        publisher = await _user(db, "publisher")
        agent = await create_agent(
            db,
            name="Finance Consultant",
            slug="finance-consultant",
            created_by_user_id=author.id,
        )
        first = await create_agent_version(
            db,
            agent,
            system_prompt="Published baseline",
            created_by_user_id=author.id,
            model_policy={"primary_model_id": "model-1"},
        )
        await submit_agent_version(db, first, actor_user_id=author.id)
        await publish_agent_version(db, first, actor_user_id=publisher.id)
        draft = await create_agent_version(
            db,
            agent,
            system_prompt="Cloned draft",
            created_by_user_id=author.id,
            change_summary="Clone for binding",
            model_policy={"primary_model_id": "model-1"},
        )
        next_id = await discard_agent_draft(
            db,
            draft,
            actor_user_id=author.id,
            reason="Changed mind",
        )
        await db.flush()
        assert next_id == first.id
        assert draft.status == "archived"
        assert draft.published_at is None
        remaining = (
            (
                await db.execute(
                    select(AgentAuditEvent.event_type).where(
                        AgentAuditEvent.agent_id == agent.id,
                        AgentAuditEvent.event_type == "agent.version.discarded",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert remaining == ["agent.version.discarded"]
        alone = await create_agent(
            db,
            name="Solo Draft Agent",
            slug="solo-draft-agent",
            created_by_user_id=author.id,
        )
        only = await create_agent_version(
            db,
            alone,
            system_prompt="Only draft",
            created_by_user_id=author.id,
        )
        with pytest.raises(ValueError, match="only Agent version"):
            await discard_agent_draft(db, only, actor_user_id=author.id)
    await engine.dispose()


async def test_agent_version_lifecycle():
    await _test_agent_version_lifecycle()


async def test_duplicate_slug_and_draft_fingerprint_change():
    await _test_duplicate_slug_and_draft_fingerprint_change()


async def test_discard_agent_draft():
    await _test_discard_agent_draft()


async def _test_create_version_reuses_discarded_draft_number() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        author = await _user(db, "author")
        publisher = await _user(db, "publisher")
        agent = await create_agent(
            db,
            name="Ops Agent",
            slug="ops-agent",
            created_by_user_id=author.id,
        )
        first = await create_agent_version(
            db,
            agent,
            system_prompt="Published baseline",
            created_by_user_id=author.id,
            model_policy={"primary_model_id": "model-1"},
        )
        await submit_agent_version(db, first, actor_user_id=author.id)
        await publish_agent_version(db, first, actor_user_id=publisher.id)
        draft = await create_agent_version(
            db,
            agent,
            system_prompt="Temporary draft",
            created_by_user_id=author.id,
            model_policy={"primary_model_id": "model-1"},
        )
        assert draft.version_number == 2
        await discard_agent_draft(db, draft, actor_user_id=author.id)
        recycled = await create_agent_version(
            db,
            agent,
            system_prompt="Fresh draft after discard",
            created_by_user_id=author.id,
            change_summary="Clone again",
            model_policy={"primary_model_id": "model-1"},
        )
        assert recycled.id == draft.id
        assert recycled.version_number == 2
        assert recycled.status == "draft"
        assert recycled.system_prompt == "Fresh draft after discard"
    await engine.dispose()


async def test_create_version_reuses_discarded_draft_number():
    await _test_create_version_reuses_discarded_draft_number()


def test_agent_slug_normalization_and_validation():
    assert normalize_agent_slug(" Finance_Consultant ") == "finance-consultant"
    with pytest.raises(ValueError):
        normalize_agent_slug("invalid/slug")


async def _test_revoke_knowledge_binding_from_draft_only() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        author = await _user(db, "author")
        publisher = await _user(db, "publisher")
        agent = await create_agent(
            db,
            name="IT Helpdesk",
            slug="it-helpdesk-unbind",
            created_by_user_id=author.id,
        )
        draft = await create_agent_version(
            db,
            agent,
            system_prompt="Answer from approved IT sources.",
            created_by_user_id=author.id,
            model_policy={"primary_model_id": "model-1"},
        )
        knowledge_base = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug="kb-unbind",
            name="IT KB",
            status="active",
            access_type="private",
            sensitivity="internal",
            acl_version=1,
        )
        db.add(knowledge_base)
        await db.flush()
        binding = AgentKnowledgeBinding(
            id=str(uuid.uuid4()),
            agent_version_id=draft.id,
            knowledge_base_id=knowledge_base.id,
            release_mode="latest",
            status="approved",
            retrieval_policy={},
            requested_by_user_id=author.id,
        )
        db.add(binding)
        await db.flush()

        with pytest.raises(ValueError, match="Removal reason"):
            await revoke_agent_knowledge_binding(
                db,
                binding,
                version=draft,
                actor_user_id=author.id,
                reason="no",
            )

        await revoke_agent_knowledge_binding(
            db,
            binding,
            version=draft,
            actor_user_id=author.id,
            reason="Removed from draft",
        )
        assert binding.status == "revoked"
        events = (
            (await db.execute(select(AgentAuditEvent.event_type).where(AgentAuditEvent.agent_id == agent.id)))
            .scalars()
            .all()
        )
        assert "agent.knowledge_binding.revoked" in events

        with pytest.raises(ValueError, match="already removed"):
            await revoke_agent_knowledge_binding(
                db,
                binding,
                version=draft,
                actor_user_id=author.id,
                reason="Removed from draft",
            )

        published = await create_agent_version(
            db,
            agent,
            system_prompt="Published IT sources.",
            created_by_user_id=author.id,
            model_policy={"primary_model_id": "model-1"},
        )
        live_binding = AgentKnowledgeBinding(
            id=str(uuid.uuid4()),
            agent_version_id=published.id,
            knowledge_base_id=knowledge_base.id,
            release_mode="latest",
            status="approved",
            retrieval_policy={},
            requested_by_user_id=author.id,
        )
        db.add(live_binding)
        await db.flush()
        await submit_agent_version(db, published, actor_user_id=author.id)
        await publish_agent_version(db, published, actor_user_id=publisher.id)
        with pytest.raises(ValueError, match="draft"):
            await revoke_agent_knowledge_binding(
                db,
                live_binding,
                version=published,
                actor_user_id=author.id,
                reason="Removed from draft",
            )
        assert live_binding.status == "approved"
    await engine.dispose()


async def test_revoke_knowledge_binding_from_draft_only():
    await _test_revoke_knowledge_binding_from_draft_only()
