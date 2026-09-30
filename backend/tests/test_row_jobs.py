"""Jobs kept on their own rows (a chat's summary, its recall index): how a run takes its row.

A run took its row with a read, a check and a write, so two deliveries of
the same message could both run it; and a delivery that found the row held
by a worker that had died was dropped, leaving the row "running" until the
chat's next reply. Now the row is taken in one statement, a run left behind
is taken again once its lease has run out, and a delivery that finds a live
lease asks to be delivered again when it runs out.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.models.chat import ChatRecallIndex, ChatSession, ChatSummary
from app.models.knowledge import OutboxEvent
from app.services import chat_recall_service as recall
from app.services import chat_summary_service as summaries


async def _chat(db, user) -> str:
    session_id = str(uuid.uuid4())
    db.add(ChatSession(id=session_id, user_id=user.id, title="t", model_id="m", private_mode=False))
    await db.commit()
    return session_id


def _summary_row(session_id: str, user_id: int, *, status: str, lease_in: float | None, attempts: int = 1):
    now = dt.datetime.utcnow()
    return ChatSummary(
        session_id=session_id,
        user_id=user_id,
        content="",
        up_to_sequence=0,
        covered_count=0,
        status=status,
        attempt_count=attempts,
        worker_id="worker-gone" if status == "running" else None,
        lease_expires_at=(now + dt.timedelta(seconds=lease_in)) if lease_in is not None else None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize(
    ("status", "lease_in", "attempts", "taken"),
    [
        ("pending", None, 0, True),
        ("running", -30, 1, True),  # left behind by a worker that stopped
        ("running", 120, 1, False),  # a live lease
        ("failed", None, summaries.MAX_ATTEMPTS, False),
        ("idle", None, 0, False),
    ],
)
async def test_a_row_is_taken_only_when_it_is_free_to_take(db_session, user, status, lease_in, attempts, taken):
    session_id = await _chat(db_session, user)
    db_session.add(_summary_row(session_id, user.id, status=status, lease_in=lease_in, attempts=attempts))
    await db_session.commit()
    row = await summaries.claim_summary(db_session, session_id=session_id, worker_id="worker-1")
    assert (row is not None) is taken
    if taken:
        assert (row.status, row.worker_id, row.attempt_count) == ("running", "worker-1", attempts + 1)
        # Taken: a second delivery does not take it again.
        assert await summaries.claim_summary(db_session, session_id=session_id, worker_id="worker-2") is None


async def test_the_recall_index_rows_are_taken_the_same_way(db_session, user):
    session_id = await _chat(db_session, user)
    now = dt.datetime.utcnow()
    db_session.add(
        ChatRecallIndex(
            session_id=session_id,
            user_id=user.id,
            indexed_up_to=0,
            not_before=0,
            chunk_count=0,
            status="pending",
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()
    assert (await recall.claim_chat_index(db_session, session_id=session_id, worker_id="w1")).worker_id == "w1"
    assert await recall.claim_chat_index(db_session, session_id=session_id, worker_id="w2") is None


async def test_a_delivery_that_finds_a_live_lease_comes_back_when_it_runs_out(db_session, session_factory, user):
    from app.services.knowledge_job_handlers import KnowledgeJobContext
    from app.services.knowledge_queue import ensure_consumer_group, read_new_messages
    from app.services.knowledge_worker_service import KnowledgeWorker
    from app.services.outbox_service import relay_outbox_once
    from tests.test_memory_worker_dispatch import FakeRedis

    session_id = await _chat(db_session, user)
    db_session.add(_summary_row(session_id, user.id, status="running", lease_in=120))
    await summaries._enqueue(db_session, session_id, dt.datetime.utcnow() - dt.timedelta(seconds=1))
    await db_session.commit()
    redis = FakeRedis()
    await relay_outbox_once(session_factory, redis, worker_id="scheduler-1")
    await ensure_consumer_group(redis)
    messages = await read_new_messages(redis, consumer_name="worker-1")
    worker = KnowledgeWorker(
        session_factory=session_factory, redis=redis, consumer_name="worker-1", context=KnowledgeJobContext(qdrant=None)
    )

    result = await worker.process_message(messages[0])

    assert result.outcome == "duplicate"
    async with session_factory() as check:
        lease = (await check.get(ChatSummary, session_id)).lease_expires_at
        waiting = (
            (
                await check.execute(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == session_id, OutboxEvent.status == "pending")
                )
            )
            .scalars()
            .all()
        )
    assert len(waiting) == 1
    assert lease < waiting[0].available_at <= lease + dt.timedelta(seconds=10)


async def test_two_deliveries_at_once_never_both_take_the_row(db_session, session_factory, user):
    import asyncio

    if db_session.bind.dialect.name != "postgresql":
        pytest.skip("needs two real connections")
    session_id = await _chat(db_session, user)
    db_session.add(_summary_row(session_id, user.id, status="pending", lease_in=None, attempts=0))
    await db_session.commit()
    async with session_factory() as first, session_factory() as second:
        taken = await summaries.claim_summary(first, session_id=session_id, worker_id="worker-1")
        racing = asyncio.create_task(summaries.claim_summary(second, session_id=session_id, worker_id="worker-2"))
        await asyncio.sleep(0.3)
        await first.commit()
        also = await asyncio.wait_for(racing, timeout=10)
        await second.commit()
    assert taken is not None and also is None
