"""Durable Knowledge job state machine and stale-lease recovery."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.knowledge import IngestionJob
from app.services.outbox_service import enqueue_outbox_event

TERMINAL_JOB_STATUSES = frozenset({"succeeded", "dead", "cancelled"})


@dataclass(frozen=True)
class JobFailure:
    status: str
    attempt_count: int
    next_attempt_at: datetime.datetime | None


async def enqueue_knowledge_job(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
    job_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    document_version_id: str | None = None,
    index_version_id: str | None = None,
    max_attempts: int | None = None,
) -> IngestionJob:
    existing = (
        await db.execute(select(IngestionJob).where(IngestionJob.idempotency_key == idempotency_key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    settings = get_settings()
    job_id = str(uuid.uuid4())
    values = {
        "id": job_id,
        "knowledge_base_id": knowledge_base_id,
        "document_version_id": document_version_id,
        "index_version_id": index_version_id,
        "job_type": job_type,
        "status": "pending",
        "attempt_count": 0,
        "max_attempts": max_attempts or settings.knowledge_job_max_attempts,
        "idempotency_key": idempotency_key,
        "payload_json": payload,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = (
            postgresql_insert(IngestionJob)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(IngestionJob.id)
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(IngestionJob)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(IngestionJob.id)
        )
    else:
        job = IngestionJob(**values)
        db.add(job)
        await db.flush()
        statement = None

    if statement is not None:
        inserted_id = (await db.execute(statement)).scalar_one_or_none()
        if inserted_id is None:
            return (
                await db.execute(select(IngestionJob).where(IngestionJob.idempotency_key == idempotency_key))
            ).scalar_one()
        job = (await db.execute(select(IngestionJob).where(IngestionJob.id == inserted_id))).scalar_one()

    await schedule_job_dispatch(
        db,
        job,
        reason="created",
        available_at=datetime.datetime.utcnow(),
    )
    return job


async def schedule_job_dispatch(
    db: AsyncSession,
    job: IngestionJob,
    *,
    reason: str,
    available_at: datetime.datetime,
) -> None:
    dispatch_number = int(job.attempt_count or 0)
    await enqueue_outbox_event(
        db,
        aggregate_type="knowledge_job",
        aggregate_id=job.id,
        event_type="knowledge.job.ready",
        payload={
            "job_id": job.id,
            "job_type": job.job_type,
            "attempt": dispatch_number,
            "reason": reason,
        },
        idempotency_key=f"knowledge-job:{job.id}:dispatch:{dispatch_number}:{reason}",
        available_at=available_at,
    )


async def claim_knowledge_job(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    now: datetime.datetime | None = None,
) -> IngestionJob | None:
    current = now or datetime.datetime.utcnow()
    statement = select(IngestionJob).where(IngestionJob.id == job_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    job = (await db.execute(statement)).scalar_one_or_none()
    if job is None or job.status in TERMINAL_JOB_STATUSES:
        return None
    if job.status in {"leased", "processing"} and job.lease_until is not None and job.lease_until > current:
        return None
    if job.status not in {"pending", "retry", "leased", "processing"}:
        return None
    if job.next_attempt_at is not None and job.next_attempt_at > current:
        return None

    settings = get_settings()
    job.status = "processing"
    job.attempt_count = int(job.attempt_count or 0) + 1
    job.lease_owner = worker_id
    job.lease_until = current + datetime.timedelta(seconds=settings.knowledge_job_lease_seconds)
    job.started_at = job.started_at or current
    job.updated_at = current
    job.error_code = None
    job.error_message = None
    await db.flush()
    return job


async def heartbeat_knowledge_job(
    db: AsyncSession,
    job: IngestionJob,
    *,
    worker_id: str,
    now: datetime.datetime | None = None,
) -> bool:
    if job.status != "processing" or job.lease_owner != worker_id:
        return False
    settings = get_settings()
    current = now or datetime.datetime.utcnow()
    job.lease_until = current + datetime.timedelta(seconds=settings.knowledge_job_lease_seconds)
    job.updated_at = current
    await db.flush()
    return True


async def complete_knowledge_job(
    db: AsyncSession,
    job: IngestionJob,
    *,
    worker_id: str,
) -> bool:
    if job.status != "processing" or job.lease_owner != worker_id:
        return False
    now = datetime.datetime.utcnow()
    job.status = "succeeded"
    job.lease_owner = None
    job.lease_until = None
    job.next_attempt_at = None
    job.completed_at = now
    job.updated_at = now
    job.error_code = None
    job.error_message = None
    await db.flush()
    return True


async def fail_knowledge_job(
    db: AsyncSession,
    job: IngestionJob,
    *,
    worker_id: str,
    error: Exception | str,
    error_code: str = "handler_failed",
    retryable: bool = True,
) -> JobFailure:
    if job.status != "processing" or job.lease_owner != worker_id:
        return JobFailure(
            status=job.status,
            attempt_count=int(job.attempt_count or 0),
            next_attempt_at=job.next_attempt_at,
        )
    settings = get_settings()
    attempts = int(job.attempt_count or 0)
    now = datetime.datetime.utcnow()
    job.lease_owner = None
    job.lease_until = None
    job.error_code = error_code[:64]
    job.error_message = str(error)[:8000]
    job.updated_at = now
    if not retryable or attempts >= int(job.max_attempts or 1):
        job.status = "dead"
        job.completed_at = now
        job.next_attempt_at = None
    else:
        delay = settings.knowledge_retry_base_seconds * (2 ** max(0, attempts - 1))
        job.status = "retry"
        job.next_attempt_at = now + datetime.timedelta(seconds=min(delay, 3600))
        await schedule_job_dispatch(
            db,
            job,
            reason="retry",
            available_at=job.next_attempt_at,
        )
    await db.flush()
    return JobFailure(
        status=job.status,
        attempt_count=attempts,
        next_attempt_at=job.next_attempt_at,
    )


async def recover_stale_knowledge_jobs(
    db: AsyncSession,
    *,
    now: datetime.datetime | None = None,
    limit: int = 100,
) -> int:
    current = now or datetime.datetime.utcnow()
    statement = (
        select(IngestionJob)
        .where(
            IngestionJob.status.in_(("leased", "processing")),
            or_(
                IngestionJob.lease_until.is_(None),
                IngestionJob.lease_until <= current,
            ),
        )
        .order_by(IngestionJob.lease_until, IngestionJob.created_at)
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    jobs = (await db.execute(statement)).scalars().all()
    recovered = 0
    for job in jobs:
        job.lease_owner = None
        job.lease_until = None
        job.error_code = "lease_expired"
        job.error_message = "Worker lease expired before completion"
        job.updated_at = current
        if int(job.attempt_count or 0) >= int(job.max_attempts or 1):
            job.status = "dead"
            job.completed_at = current
            job.next_attempt_at = None
        else:
            job.status = "retry"
            job.next_attempt_at = current
            await schedule_job_dispatch(
                db,
                job,
                reason="lease-expired",
                available_at=current,
            )
        recovered += 1
    await db.flush()
    return recovered


async def retry_dead_knowledge_job(
    db: AsyncSession,
    *,
    job_id: str,
) -> IngestionJob:
    statement = select(IngestionJob).where(IngestionJob.id == job_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = (await db.execute(statement)).scalar_one_or_none()
    if job is None:
        raise ValueError("Knowledge job not found")
    if job.status != "dead":
        raise ValueError("Only a dead Knowledge job can be retried manually")
    payload = dict(job.payload_json or {})
    manual_retry_count = int(payload.get("manual_retry_count") or 0) + 1
    if manual_retry_count > 10:
        raise ValueError("Knowledge job exceeded the manual retry limit")
    payload["manual_retry_count"] = manual_retry_count
    job.payload_json = payload
    job.status = "pending"
    job.attempt_count = 0
    job.lease_owner = None
    job.lease_until = None
    job.next_attempt_at = None
    job.started_at = None
    job.completed_at = None
    job.error_code = None
    job.error_message = None
    job.updated_at = datetime.datetime.utcnow()
    await schedule_job_dispatch(
        db,
        job,
        reason=f"manual-retry-{manual_retry_count}",
        available_at=datetime.datetime.utcnow(),
    )
    await db.flush()
    return job
