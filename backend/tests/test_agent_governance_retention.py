"""Governance audit, legal-hold, and retention invariants."""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register complete ORM metadata
from app.database import Base
from app.models.agent import Agent
from app.models.chat import ChatMessage, ChatSession
from app.models.governance import GovernanceAuditEvent
from app.models.knowledge import (
    DeletionTombstone,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    LegalHold,
)
from app.models.user import User
from app.services.agent_governance_service import (
    append_governance_audit_event,
    place_legal_hold,
    release_legal_hold,
    verify_governance_audit_chain,
)
from app.services.knowledge_retention_service import (
    schedule_expired_knowledge_retention,
)
from app.services.retention_policy_service import (
    chat_retention_stats,
    purge_expired_chat_messages,
    set_chat_retention_settings,
)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def _create_user(db: AsyncSession) -> User:
    user = User(
        username="governance-user",
        email="governance@test",
        hashed_password="x",
        auth_provider="local",
    )
    db.add(user)
    await db.flush()
    return user


async def _exercise_audit_chain_and_legal_holds() -> None:
    engine, factory = await _factory()
    try:
        async with factory() as db:
            user = await _create_user(db)
            agent = Agent(
                id="agent-held",
                slug="agent-held",
                name="Held agent",
                status="active",
                access_type="private",
                created_by_user_id=user.id,
            )
            db.add(agent)
            await db.flush()

            hold = await place_legal_hold(
                db,
                resource_type="agent",
                resource_id=agent.id,
                reason="Active investigation",
                actor_user_id=user.id,
            )
            duplicate = await place_legal_hold(
                db,
                resource_type="agent",
                resource_id=agent.id,
                reason="Duplicate request",
                actor_user_id=user.id,
            )
            assert duplicate.id == hold.id

            await append_governance_audit_event(
                db,
                event_type="governance.test.redaction",
                resource_type="agent",
                resource_id=agent.id,
                actor_user_id=user.id,
                payload={
                    "authorization": "Bearer must-not-persist",
                    "nested": {"api_key": "must-not-persist"},
                    "safe": "retained",
                },
            )
            await release_legal_hold(
                db,
                hold_id=hold.id,
                actor_user_id=user.id,
                reason="Investigation complete",
            )

            verification = await verify_governance_audit_chain(db)
            assert verification.valid
            assert verification.event_count == 3
            assert verification.head_hash

            events = (
                (
                    await db.execute(
                        select(GovernanceAuditEvent).order_by(
                            GovernanceAuditEvent.created_at,
                            GovernanceAuditEvent.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            redaction = next(event for event in events if event.event_type == "governance.test.redaction")
            assert redaction.payload_json["authorization"] == "[REDACTED]"
            assert redaction.payload_json["nested"]["api_key"] == "[REDACTED]"
            assert redaction.payload_json["safe"] == "retained"

            redaction.outcome = "failed"
            with pytest.raises(ValueError, match="append-only"):
                await db.flush()
    finally:
        await engine.dispose()


async def _exercise_chat_retention_holds() -> None:
    engine, factory = await _factory()
    try:
        async with factory() as db:
            user = await _create_user(db)
            agent = Agent(
                id="retention-agent",
                slug="retention-agent",
                name="Retention agent",
                status="active",
                access_type="private",
                created_by_user_id=user.id,
            )
            db.add(agent)
            old = _now() - datetime.timedelta(days=90)
            sessions = [
                ChatSession(
                    id="held-by-agent",
                    user_id=user.id,
                    title="Held by agent",
                    current_agent_id=agent.id,
                    message_count=1,
                ),
                ChatSession(
                    id="held-directly",
                    user_id=user.id,
                    title="Held directly",
                    message_count=1,
                ),
                ChatSession(
                    id="not-held",
                    user_id=user.id,
                    title="Not held",
                    message_count=1,
                ),
            ]
            db.add_all(sessions)
            db.add_all(
                [
                    ChatMessage(
                        id=f"message-{index}",
                        session_id=session.id,
                        user_id=user.id,
                        role="user",
                        content="old",
                        sequence=1,
                        created_at=old,
                    )
                    for index, session in enumerate(sessions)
                ]
            )
            await db.flush()
            await place_legal_hold(
                db,
                resource_type="agent",
                resource_id=agent.id,
                reason="Preserve all agent conversations",
                actor_user_id=user.id,
            )
            await place_legal_hold(
                db,
                resource_type="chat_session",
                resource_id="held-directly",
                reason="Preserve this conversation",
                actor_user_id=user.id,
            )
            await set_chat_retention_settings(
                db,
                retention_enabled=True,
                retention_days=30,
            )

            stats = await chat_retention_stats(db)
            assert stats["expired_messages"] == 1
            assert stats["held_expired_messages"] == 2

            result = await purge_expired_chat_messages(db, retention_days=30)
            assert result["removed_messages"] == 1
            assert await db.get(ChatSession, "not-held") is None
            assert await db.get(ChatSession, "held-by-agent") is not None
            assert await db.get(ChatSession, "held-directly") is not None
            remaining = (await db.execute(select(func.count()).select_from(ChatMessage))).scalar_one()
            assert remaining == 2
    finally:
        await engine.dispose()


async def _exercise_knowledge_retention_holds() -> None:
    engine, factory = await _factory()
    try:
        async with factory() as db:
            user = await _create_user(db)
            knowledge_base = KnowledgeBase(
                id="kb-retention",
                slug="kb-retention",
                name="Retention KB",
                status="active",
                access_type="private",
                sensitivity="internal",
                retention_days=30,
                created_by_user_id=user.id,
            )
            old = _now() - datetime.timedelta(days=90)
            held_document = KnowledgeDocument(
                id="document-held",
                knowledge_base_id=knowledge_base.id,
                canonical_key="held",
                title="Held document",
                status="revoked",
                revoked_at=old,
                updated_at=old,
            )
            purge_document = KnowledgeDocument(
                id="document-purge",
                knowledge_base_id=knowledge_base.id,
                canonical_key="purge",
                title="Purge document",
                status="revoked",
                revoked_at=old,
                updated_at=old,
            )
            versions = [
                KnowledgeDocumentVersion(
                    id="version-held",
                    document_id=held_document.id,
                    version_number=1,
                    status="revoked",
                    storage_key="knowledge/held.pdf",
                    file_name="held.pdf",
                    mime_type="application/pdf",
                    size_bytes=10,
                    sha256="a" * 64,
                ),
                KnowledgeDocumentVersion(
                    id="version-purge",
                    document_id=purge_document.id,
                    version_number=1,
                    status="revoked",
                    storage_key="knowledge/purge.pdf",
                    file_name="purge.pdf",
                    mime_type="application/pdf",
                    size_bytes=10,
                    sha256="b" * 64,
                ),
            ]
            db.add_all([knowledge_base, held_document, purge_document, *versions])
            await db.flush()
            await place_legal_hold(
                db,
                resource_type="knowledge_document",
                resource_id=held_document.id,
                reason="Preserve for litigation",
                actor_user_id=user.id,
            )

            result = await schedule_expired_knowledge_retention(
                db,
                actor_user_id=user.id,
                now=_now(),
            )
            assert result["scheduled_versions"] == 1
            assert result["held_resources"] == 1

            tombstones = (await db.execute(select(DeletionTombstone))).scalars().all()
            assert len(tombstones) == 1
            assert tombstones[0].resource_id == "version-purge"
            assert tombstones[0].status == "pending"
            assert (
                await db.execute(select(func.count()).select_from(LegalHold).where(LegalHold.status == "active"))
            ).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_governance_audit_chain_and_legal_holds() -> None:
    await _exercise_audit_chain_and_legal_holds()


async def test_chat_retention_respects_session_and_agent_holds() -> None:
    await _exercise_chat_retention_holds()


async def test_knowledge_retention_respects_legal_holds() -> None:
    await _exercise_knowledge_retention_holds()
