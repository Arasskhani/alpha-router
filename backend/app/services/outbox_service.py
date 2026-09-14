"""Transactional outbox creation, leasing, retry, and Redis relay."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.knowledge import OutboxEvent
from app.services.knowledge_queue import publish_outbox_message


@dataclass(frozen=True)
class RelayStats:
    claimed: int = 0
    published: int = 0
    retried: int = 0
    dead: int = 0


async def enqueue_outbox_event(
    db: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    available_at: datetime.datetime | None = None,
) -> OutboxEvent:
    """Insert an event in the caller's transaction; duplicate keys return the original."""

    event_id = str(uuid.uuid4())
    values = {
        "id": event_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "event_type": event_type,
        "payload_json": payload,
        "status": "pending",
        "attempt_count": 0,
        "idempotency_key": idempotency_key,
        "available_at": available_at or datetime.datetime.utcnow(),
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = (
            postgresql_insert(OutboxEvent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(OutboxEvent.id)
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(OutboxEvent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(OutboxEvent.id)
        )
    else:
        existing = (
            await db.execute(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        event = OutboxEvent(**values)
        db.add(event)
        await db.flush()
        return event

    inserted_id = (await db.execute(statement)).scalar_one_or_none()
    if inserted_id is None:
        return (
            await db.execute(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
        ).scalar_one()
    return (await db.execute(select(OutboxEvent).where(OutboxEvent.id == inserted_id))).scalar_one()


async def claim_outbox_events(
    db: AsyncSession,
    *,
    worker_id: str,
    now: datetime.datetime | None = None,
    batch_size: int | None = None,
) -> list[OutboxEvent]:
    settings = get_settings()
    current = now or datetime.datetime.utcnow()
    due = (
        select(OutboxEvent)
        .where(
            OutboxEvent.available_at <= current,
            or_(
                OutboxEvent.status.in_(("pending", "retry")),
                (
                    (OutboxEvent.status == "leased")
                    & (OutboxEvent.lease_until.is_not(None))
                    & (OutboxEvent.lease_until <= current)
                ),
            ),
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at, OutboxEvent.id)
        .limit(batch_size or settings.outbox_batch_size)
    )
    if db.get_bind().dialect.name == "postgresql":
        due = due.with_for_update(skip_locked=True)
    rows = (await db.execute(due)).scalars().all()
    lease_until = current + datetime.timedelta(seconds=settings.outbox_lease_seconds)
    for row in rows:
        row.status = "leased"
        row.lease_owner = worker_id
        row.lease_until = lease_until
    await db.flush()
    return list(rows)


async def mark_outbox_processed(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
) -> bool:
    if event.status != "leased" or event.lease_owner != worker_id:
        return False
    event.status = "processed"
    event.processed_at = datetime.datetime.utcnow()
    event.lease_owner = None
    event.lease_until = None
    event.last_error = None
    await db.flush()
    return True


async def mark_outbox_failed(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    error: Exception | str,
) -> str:
    if event.status != "leased" or event.lease_owner != worker_id:
        return event.status
    settings = get_settings()
    event.attempt_count = int(event.attempt_count or 0) + 1
    event.last_error = str(error)[:8000]
    event.lease_owner = None
    event.lease_until = None
    if event.attempt_count >= settings.knowledge_job_max_attempts:
        event.status = "dead"
    else:
        delay = settings.knowledge_retry_base_seconds * (2 ** (event.attempt_count - 1))
        event.status = "retry"
        event.available_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=min(delay, 3600))
    await db.flush()
    return event.status


async def relay_outbox_once(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    worker_id: str,
) -> RelayStats:
    """Lease a bounded batch, publish at least once, and persist outcomes."""

    async with session_factory() as db:
        claimed = await claim_outbox_events(db, worker_id=worker_id)
        event_ids = [event.id for event in claimed]
        await db.commit()

    published = retried = dead = 0
    for event_id in event_ids:
        async with session_factory() as db:
            event = await db.get(OutboxEvent, event_id)
            if event is None or event.status != "leased" or event.lease_owner != worker_id:
                continue
            try:
                await publish_outbox_message(
                    redis,
                    event_id=event.id,
                    event_type=event.event_type,
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    payload=dict(event.payload_json or {}),
                )
            except Exception as exc:  # noqa: BLE001 -- falls back to a safe default value
                status = await mark_outbox_failed(
                    db,
                    event,
                    worker_id=worker_id,
                    error=exc,
                )
                retried += int(status == "retry")
                dead += int(status == "dead")
            else:
                if await mark_outbox_processed(db, event, worker_id=worker_id):
                    published += 1
            await db.commit()

    return RelayStats(
        claimed=len(event_ids),
        published=published,
        retried=retried,
        dead=dead,
    )
