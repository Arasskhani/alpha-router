"""Verifying the audit chain must not load the whole audit table.

``GET /admin/agent-governance/audit/verify`` read every governance event into
memory as ORM instances in a single query. The chain is append-only and never
trimmed by design, so that table only grows: the endpoint's cost and the
worker's memory grow with it, and on a mature installation the request is the
one that takes the process down.

The chain has to be walked in order - each hash covers its predecessor - but
in order does not mean all at once.
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select

from app.models.governance import GovernanceAuditEvent
from app.services import agent_governance_service as governance
from app.services.agent_governance_service import (
    append_governance_audit_event,
    verify_governance_audit_chain,
)


class _CountingSession:
    """The real session, counting the statements that reach the database."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.executions = 0

    async def execute(self, *args, **kwargs):
        self.executions += 1
        return await self._inner.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def _ordered_events(db_session):
    return (
        (
            await db_session.execute(
                select(GovernanceAuditEvent).order_by(
                    GovernanceAuditEvent.created_at,
                    GovernanceAuditEvent.id,
                )
            )
        )
        .scalars()
        .all()
    )


async def _chain_of(db_session, user, length: int) -> None:
    for index in range(length):
        await append_governance_audit_event(
            db_session,
            event_type="governance.test.link",
            resource_type="agent",
            resource_id=f"agent-{index}",
            actor_user_id=user.id,
            payload={"index": index},
        )
    await db_session.flush()


async def test_the_chain_is_read_in_batches(db_session, user, monkeypatch):
    monkeypatch.setattr(governance, "CHAIN_VERIFY_BATCH_SIZE", 2)
    await _chain_of(db_session, user, 7)

    counting = _CountingSession(db_session)
    verification = await verify_governance_audit_chain(counting)

    assert verification.valid
    assert verification.event_count == 7
    # One count, then a page per batch. A single statement means the whole
    # table was materialised at once.
    assert counting.executions >= 4, f"the chain was read in {counting.executions} statements"


async def test_a_batched_walk_still_verifies_the_whole_chain(db_session, user, monkeypatch):
    monkeypatch.setattr(governance, "CHAIN_VERIFY_BATCH_SIZE", 2)
    await _chain_of(db_session, user, 5)

    verification = await verify_governance_audit_chain(db_session)

    assert verification.valid
    assert verification.event_count == 5
    last = (
        (
            await db_session.execute(
                select(GovernanceAuditEvent).order_by(
                    GovernanceAuditEvent.created_at.desc(),
                    GovernanceAuditEvent.id.desc(),
                )
            )
        )
        .scalars()
        .first()
    )
    assert verification.head_hash == last.event_hash


@pytest.mark.parametrize("after_index", [0, 2, 4])
async def test_a_forged_link_is_caught_in_any_batch(db_session, user, monkeypatch, after_index):
    """A break in the last page is as detectable as one in the first.

    The rows themselves cannot be altered - the ORM refuses and PostgreSQL has
    a BEFORE UPDATE trigger - so the realistic tampering is an inserted link:
    a row written straight into the table with a predecessor hash that never
    belonged to the chain.
    """

    monkeypatch.setattr(governance, "CHAIN_VERIFY_BATCH_SIZE", 2)
    await _chain_of(db_session, user, 5)

    rows = await _ordered_events(db_session)
    forged_id = f"zzzzzzzz-forged-{after_index:04d}"
    await db_session.execute(
        insert(GovernanceAuditEvent).values(
            id=forged_id,
            event_type="governance.test.forged",
            resource_type="agent",
            resource_id="agent-forged",
            actor_user_id=user.id,
            outcome="success",
            payload_json={"forged": True},
            previous_event_hash="0" * 64,
            event_hash="1" * 64,
            # Same instant as the row it follows, an id that sorts after it:
            # the walk orders by (created_at, id), so this lands between them.
            created_at=rows[after_index].created_at,
        )
    )
    await db_session.flush()

    verification = await verify_governance_audit_chain(db_session)

    assert not verification.valid
    assert verification.first_invalid_event_id == forged_id
    assert verification.event_count == 6


async def test_an_empty_chain_verifies(db_session):
    verification = await verify_governance_audit_chain(db_session)

    assert verification.valid
    assert verification.event_count == 0
    assert verification.head_hash is None
