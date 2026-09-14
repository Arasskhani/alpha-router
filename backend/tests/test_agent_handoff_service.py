"""Controlled Agent handoff consent, ACL, context, and state-machine tests."""

from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.agent import Agent, AgentAuditEvent, AgentVersion
from app.models.chat import ChatSession
from app.models.user import User
from app.services.agent_handoff_service import (
    AgentHandoffConflict,
    AgentHandoffError,
    accept_agent_handoff,
    complete_agent_handoff,
    propose_agent_handoff,
)
from app.services.agent_routing_service import AgentAccessDenied, AgentExecutionTarget
from app.services.resource_access_service import ResourceAccessSubject


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    ), engine


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


async def _agent(
    db: AsyncSession,
    *,
    slug: str,
    target_slug: str,
) -> AgentExecutionTarget:
    agent = Agent(
        id=str(uuid.uuid4()),
        slug=slug,
        name=slug.replace("-", " ").title(),
        status="active",
        access_type="public",
    )
    version = AgentVersion(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version_number=1,
        status="published",
        active_scope_key=f"agent:{agent.id}",
        system_prompt=f"Approved behavior for {slug}.",
        model_policy={"primary_model_id": "model::1"},
        routing_policy={
            "allowed_handoff_targets": [target_slug],
            "require_handoff_consent": True,
            "max_handoffs_per_turn": 2,
            "transfer_history_messages": 3,
            "allow_assistant_context": False,
        },
        fingerprint=uuid.uuid4().hex,
        published_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    )
    db.add_all([agent, version])
    await db.flush()
    return AgentExecutionTarget(agent=agent, version=version, pinned_version=False)


async def _test_handoff_state_machine_and_acl_recheck() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            user = await _user(db, "handoff-user")
            source = await _agent(
                db,
                slug="hr-assistant",
                target_slug="legal-consultant",
            )
            target = await _agent(
                db,
                slug="legal-consultant",
                target_slug="hr-assistant",
            )
            session = ChatSession(
                id=str(uuid.uuid4()),
                user_id=user.id,
                title="Agent chat",
                model_id="",
            )
            db.add(session)
            await db.flush()
            subject = ResourceAccessSubject(user_id=user.id)
            messages = [
                {"role": "system", "content": "secret system policy"},
                {"role": "user", "content": "I need help with a contract."},
                {"role": "assistant", "content": "hidden retrieved evidence"},
                {"role": "tool", "content": "tool credential"},
                {"role": "user", "content": "Please transfer me."},
            ]

            proposal = await propose_agent_handoff(
                db,
                session_id=session.id,
                turn_id="turn-1",
                source=source,
                subject=subject,
                reason="Legal review is required",
                messages=messages,
                initiated_by_user_id=user.id,
                initiated_by="runtime",
                to_agent_slug=target.agent.slug,
            )
            assert proposal.event.status == "proposed"
            assert proposal.event.turn_ordinal == 1
            assert proposal.event.consent_required
            assert proposal.event.context_digest == proposal.context.digest
            assert proposal.event.context_payload["messages"] == list(proposal.context.messages)
            assert [message["role"] for message in proposal.context.messages] == [
                "user",
                "user",
            ]
            assert "secret system policy" not in str(proposal.context.messages)
            with pytest.raises(AgentHandoffConflict):
                await complete_agent_handoff(
                    db,
                    event_id=proposal.event.id,
                    subject=subject,
                    actor_user_id=user.id,
                )

            # Authorization is current state, never the proposal-time snapshot.
            target.agent.access_type = "private"
            await db.flush()
            with pytest.raises(AgentAccessDenied):
                await accept_agent_handoff(
                    db,
                    event_id=proposal.event.id,
                    subject=subject,
                    actor_user_id=user.id,
                )
            target.agent.access_type = "public"
            accepted = await accept_agent_handoff(
                db,
                event_id=proposal.event.id,
                subject=subject,
                actor_user_id=user.id,
            )
            assert accepted.status == "accepted"
            assert accepted.consented_at is not None
            completed, completed_target = await complete_agent_handoff(
                db,
                event_id=proposal.event.id,
                subject=subject,
                actor_user_id=user.id,
            )
            assert completed.status == "completed"
            assert completed_target.agent.id == target.agent.id

            second = await propose_agent_handoff(
                db,
                session_id=session.id,
                turn_id="turn-1",
                source=source,
                subject=subject,
                reason="Second bounded proposal",
                messages=messages,
                initiated_by_user_id=user.id,
                initiated_by="runtime",
                to_agent_slug=target.agent.slug,
            )
            assert second.event.status == "proposed"
            assert second.event.turn_ordinal == 2
            with pytest.raises(AgentHandoffError, match="limit exhausted"):
                await propose_agent_handoff(
                    db,
                    session_id=session.id,
                    turn_id="turn-1",
                    source=source,
                    subject=subject,
                    reason="Unbounded third proposal",
                    messages=messages,
                    initiated_by_user_id=user.id,
                    initiated_by="runtime",
                    to_agent_slug=target.agent.slug,
                )

            events = (
                (await db.execute(select(AgentAuditEvent.event_type).order_by(AgentAuditEvent.created_at)))
                .scalars()
                .all()
            )
            assert "agent.handoff.proposed" in events
            assert "agent.handoff.accepted" in events
            assert "agent.handoff.completed" in events
    finally:
        await engine.dispose()


def test_handoff_state_machine_and_acl_recheck():
    asyncio.run(_test_handoff_state_machine_and_acl_recheck())
