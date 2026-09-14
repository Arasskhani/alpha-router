"""Debounced extraction jobs for automatic project memory.

Mirrors ``memory_job_service`` but keys jobs on (project_id, session_id) instead
of the posting member, so several members chatting in one thread coalesce into a
single extraction run.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.chat import ChatMessage, ChatSession, is_member_channel
from app.models.project import ProjectMemoryJob
from app.services.memory_settings_service import get_memory_settings
from app.services.outbox_service import enqueue_outbox_event
from app.services.project_config_service import load_project_memory_flags

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("pending", "retry")
CLAIMABLE_STATUSES = ("pending", "retry", "running")
EVENT_TYPE = "project_memory.job.ready"
AGGREGATE_TYPE = "project_memory_job"


@dataclass(frozen=True)
class JobResult:
    status: str
    attempt_count: int
    next_attempt_at: dt.datetime | None


def _idempotency_key(job: ProjectMemoryJob, attempt: int, suffix: str) -> str:
    return f"project-memory:{job.id}:dispatch:{attempt}:{suffix}"


async def _latest_extracted_sequence(db: AsyncSession, project_id: str, session_id: str) -> int:
    row = (
        (
            await db.execute(
                select(ProjectMemoryJob.extracted_sequence)
                .where(
                    ProjectMemoryJob.project_id == project_id,
                    ProjectMemoryJob.session_id == session_id,
                )
                .order_by(ProjectMemoryJob.updated_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return int(row or 0)


def is_eligible_session(session: ChatSession | None) -> bool:
    """Only shared, non-private project AI threads are mined."""
    if session is None or not session.project_id:
        return False
    return not (bool(session.private_mode) or is_member_channel(session))


async def schedule_extraction(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    watermark_sequence: int,
) -> ProjectMemoryJob | None:
    settings = await get_memory_settings(db)
    if not settings.get("feature_enabled", True):
        return None
    if not settings.get("project_feature_enabled", True):
        return None
    if not settings.get("extraction_model_id"):
        return None
    if not get_settings().memory_extract_enabled:
        return None
    session = await db.get(ChatSession, session_id)
    if session is None or str(session.project_id or "") != str(project_id):
        return None
    if not is_eligible_session(session):
        return None
    memory_enabled, auto_capture = await load_project_memory_flags(db, project_id)
    if not memory_enabled or not auto_capture:
        return None

    now = dt.datetime.utcnow()
    debounce = int(settings.get("project_extract_debounce_seconds") or 45)
    max_wait = int(settings.get("project_extract_max_wait_seconds") or 900)
    existing = (
        (
            await db.execute(
                select(ProjectMemoryJob)
                .where(
                    ProjectMemoryJob.project_id == project_id,
                    ProjectMemoryJob.session_id == session_id,
                    ProjectMemoryJob.status.in_(OPEN_STATUSES),
                )
                .order_by(ProjectMemoryJob.created_at.asc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        existing.watermark_sequence = max(int(existing.watermark_sequence or 0), int(watermark_sequence))
        created = existing.created_at or now
        latest = now + dt.timedelta(seconds=debounce)
        deadline = created + dt.timedelta(seconds=max_wait)
        existing.run_after = min(latest, deadline)
        existing.updated_at = now
        await db.flush()
        return existing

    extracted = await _latest_extracted_sequence(db, project_id, session_id)
    job = ProjectMemoryJob(
        id=str(uuid.uuid4()),
        project_id=project_id,
        session_id=session_id,
        status="pending",
        watermark_sequence=int(watermark_sequence),
        extracted_sequence=extracted,
        run_after=now + dt.timedelta(seconds=debounce),
        attempt_count=0,
        max_attempts=get_settings().memory_job_max_attempts,
        created_at=now,
        updated_at=now,
    )
    try:
        # Savepoint: two members posting at once race for the open-job unique
        # index. That must not poison the caller's chat-persistence transaction.
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError:
        raced = (
            (
                await db.execute(
                    select(ProjectMemoryJob).where(
                        ProjectMemoryJob.project_id == project_id,
                        ProjectMemoryJob.session_id == session_id,
                        ProjectMemoryJob.status.in_(OPEN_STATUSES),
                    )
                )
            )
            .scalars()
            .first()
        )
        if raced is None:
            return None
        raced.watermark_sequence = max(int(raced.watermark_sequence or 0), int(watermark_sequence))
        raced.updated_at = now
        await db.flush()
        return raced
    await enqueue_outbox_event(
        db,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=job.id,
        event_type=EVENT_TYPE,
        payload={"job_id": job.id, "attempt": int(job.attempt_count or 0)},
        idempotency_key=_idempotency_key(job, int(job.attempt_count or 0), "created"),
        available_at=job.run_after,
    )
    return job


async def claim_job(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    now: dt.datetime | None = None,
) -> ProjectMemoryJob | None:
    current = now or dt.datetime.utcnow()
    statement = select(ProjectMemoryJob).where(ProjectMemoryJob.id == job_id)
    try:
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
    except Exception:
        pass
    job = (await db.execute(statement)).scalar_one_or_none()
    if job is None:
        return None
    if job.status in {"succeeded", "dead"}:
        return None
    if job.status == "running" and job.lease_expires_at is not None and job.lease_expires_at > current:
        return None
    if job.status not in CLAIMABLE_STATUSES:
        return None
    if job.run_after and job.run_after > current:
        await enqueue_outbox_event(
            db,
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=job.id,
            event_type=EVENT_TYPE,
            payload={"job_id": job.id, "attempt": int(job.attempt_count or 0)},
            idempotency_key=_idempotency_key(
                job,
                int(job.attempt_count or 0),
                f"deferred:{int(job.run_after.timestamp())}",
            ),
            available_at=job.run_after,
        )
        await db.flush()
        return None

    settings = get_settings()
    job.status = "running"
    job.attempt_count = int(job.attempt_count or 0) + 1
    job.worker_id = worker_id
    job.lease_expires_at = current + dt.timedelta(seconds=settings.memory_job_lease_seconds)
    job.updated_at = current
    job.last_error = None
    await db.flush()
    return job


async def heartbeat_job(
    db: AsyncSession,
    job: ProjectMemoryJob,
    *,
    worker_id: str,
    now: dt.datetime | None = None,
) -> bool:
    if job.status != "running" or job.worker_id != worker_id:
        return False
    current = now or dt.datetime.utcnow()
    job.lease_expires_at = current + dt.timedelta(seconds=get_settings().memory_job_lease_seconds)
    job.updated_at = current
    await db.flush()
    return True


async def complete_job(
    db: AsyncSession,
    job: ProjectMemoryJob,
    *,
    worker_id: str,
    extracted_sequence: int,
) -> bool:
    if job.status != "running" or job.worker_id != worker_id:
        return False
    now = dt.datetime.utcnow()
    job.status = "succeeded"
    job.extracted_sequence = int(extracted_sequence)
    job.worker_id = None
    job.lease_expires_at = None
    job.updated_at = now
    job.last_error = None
    await db.flush()
    return True


async def fail_job(
    db: AsyncSession,
    job: ProjectMemoryJob,
    *,
    worker_id: str,
    error: Exception | str,
    retryable: bool = True,
) -> JobResult:
    if job.status != "running" or job.worker_id != worker_id:
        return JobResult(
            status=job.status,
            attempt_count=int(job.attempt_count or 0),
            next_attempt_at=job.run_after,
        )
    settings = get_settings()
    attempts = int(job.attempt_count or 0)
    now = dt.datetime.utcnow()
    job.worker_id = None
    job.lease_expires_at = None
    job.last_error = str(error)[:8000]
    job.updated_at = now
    if not retryable or attempts >= int(job.max_attempts or settings.memory_job_max_attempts):
        job.status = "dead"
        next_at = None
    else:
        delay = settings.memory_retry_base_seconds * (2 ** max(0, attempts - 1))
        job.status = "retry"
        job.run_after = now + dt.timedelta(seconds=min(delay, 3600))
        next_at = job.run_after
        await enqueue_outbox_event(
            db,
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=job.id,
            event_type=EVENT_TYPE,
            payload={"job_id": job.id, "attempt": attempts},
            idempotency_key=_idempotency_key(job, attempts, "retry"),
            available_at=job.run_after,
        )
    await db.flush()
    return JobResult(status=job.status, attempt_count=attempts, next_attempt_at=next_at)


async def recover_stale_jobs(
    db: AsyncSession,
    *,
    now: dt.datetime | None = None,
    limit: int = 100,
) -> int:
    current = now or dt.datetime.utcnow()
    statement = (
        select(ProjectMemoryJob)
        .where(
            ProjectMemoryJob.status == "running",
            or_(
                ProjectMemoryJob.lease_expires_at.is_(None),
                ProjectMemoryJob.lease_expires_at <= current,
            ),
        )
        .order_by(ProjectMemoryJob.lease_expires_at, ProjectMemoryJob.created_at)
        .limit(limit)
    )
    try:
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
    except Exception:
        pass
    jobs = (await db.execute(statement)).scalars().all()
    recovered = 0
    for job in jobs:
        job.status = "retry"
        job.worker_id = None
        job.lease_expires_at = None
        job.run_after = current
        job.updated_at = current
        await enqueue_outbox_event(
            db,
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=job.id,
            event_type=EVENT_TYPE,
            payload={"job_id": job.id, "attempt": int(job.attempt_count or 0)},
            idempotency_key=_idempotency_key(job, int(job.attempt_count or 0), "lease-expired"),
            available_at=current,
        )
        recovered += 1
    if recovered:
        await db.flush()
    return recovered


async def reset_watermarks_for_project(db: AsyncSession, project_id: str) -> None:
    """Advance extracted_sequence so old threads are not re-mined after delete-all."""
    max_seq_rows = (
        await db.execute(
            select(ChatMessage.session_id, func.max(ChatMessage.sequence))
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatSession.project_id == project_id)
            .group_by(ChatMessage.session_id)
        )
    ).all()
    seq_by_session = {str(session_id): int(seq or 0) for session_id, seq in max_seq_rows}
    jobs = (await db.execute(select(ProjectMemoryJob).where(ProjectMemoryJob.project_id == project_id))).scalars().all()
    now = dt.datetime.utcnow()
    seen: set[str] = set()
    for job in jobs:
        seen.add(job.session_id)
        watermark = seq_by_session.get(job.session_id, int(job.watermark_sequence or 0))
        job.extracted_sequence = max(int(job.extracted_sequence or 0), watermark)
        job.watermark_sequence = max(int(job.watermark_sequence or 0), watermark)
        if job.status in OPEN_STATUSES:
            job.status = "succeeded"
        job.updated_at = now
    for session_id, seq in seq_by_session.items():
        if session_id in seen:
            continue
        db.add(
            ProjectMemoryJob(
                id=str(uuid.uuid4()),
                project_id=project_id,
                session_id=session_id,
                status="succeeded",
                watermark_sequence=seq,
                extracted_sequence=seq,
                run_after=now,
                attempt_count=0,
                max_attempts=get_settings().memory_job_max_attempts,
                created_at=now,
                updated_at=now,
            )
        )
    await db.flush()


async def maybe_schedule_from_append(
    db: AsyncSession,
    *,
    session: ChatSession,
    messages: list[dict],
    watermark_sequence: int,
) -> None:
    """Best-effort scheduling from the chat persistence path."""
    try:
        if not session.project_id:
            return
        if not any(str(msg.get("role") or "") == "assistant" for msg in messages):
            return
        await schedule_extraction(
            db,
            project_id=str(session.project_id),
            session_id=session.id,
            watermark_sequence=watermark_sequence,
        )
    except Exception:
        logger.exception(
            "Failed to schedule project memory extraction project_id=%s session_id=%s",
            session.project_id,
            session.id,
        )
