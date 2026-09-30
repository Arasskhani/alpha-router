"""Failed memory extraction jobs, as the administrator sees them, and running them again.

A job that failed for good ("dead") used to be a number on Admin -> Memory
and nothing more: no reason, and no way to run it again but to wait for the
person to say something new in that chat. The reasons are listed here, grouped
by what went wrong, and the administrator can send the jobs back to the queue
once the cause is fixed (a model chosen again, an allowance raised).

What is shown is the job's error, never a chat's words: a reason is the first
line of the error, shortened, with anything that looks like a key taken out.
Who the job was for is shown by username (or project name), not by chat title.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import UserMemoryJob
from app.models.project import Project, ProjectMemoryJob
from app.models.user import User
from app.services.outbox_service import enqueue_outbox_event

SCOPES = ("user", "project")
REASON_CHARS = 300
LIST_LIMIT = 50

_KEYISH = (
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\b(?:sk|rk|pk|api|key)[-_][A-Za-z0-9_\-*]{8,}", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
)


def failure_reason(error: str | None) -> str:
    """The first line of a job's error, shortened, with anything that looks like a key taken out."""
    line = next((part.strip() for part in str(error or "").splitlines() if part.strip()), "")
    for pattern in _KEYISH:
        line = pattern.sub("[redacted]", line)
    if len(line) > REASON_CHARS:
        line = line[: REASON_CHARS - 1].rstrip() + "…"
    return line or "No reason recorded"


def _model(scope: str) -> Any:
    """The scope's job model (the two share every column this module reads)."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope: {scope}")
    return UserMemoryJob if scope == "user" else ProjectMemoryJob


async def list_failed_jobs(db: AsyncSession, scope: str, *, limit: int = LIST_LIMIT) -> dict[str, Any]:
    """The scope's dead jobs: how many, grouped by reason, and the newest ``limit`` of them."""
    model = _model(scope)
    rows = (await db.execute(select(model).where(model.status == "dead").order_by(model.updated_at.desc()))).scalars()
    jobs = list(rows)
    reasons = Counter(failure_reason(job.last_error) for job in jobs)
    shown = jobs[: max(0, int(limit))]
    names: dict[Any, str] = {}
    if scope == "user":
        ids = {job.user_id for job in shown}
        if ids:
            rows_by_id = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
            names = {row_id: str(name) for row_id, name in rows_by_id}
    else:
        ids = {job.project_id for job in shown}
        if ids:
            projects = (await db.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()
            names = {row_id: str(name) for row_id, name in projects}
    owner = "user_id" if scope == "user" else "project_id"
    return {
        "scope": scope,
        "total": len(jobs),
        "reasons": [{"reason": reason, "count": count} for reason, count in reasons.most_common()],
        "jobs": [
            {
                "id": job.id,
                owner: getattr(job, owner),
                "owner": names.get(getattr(job, owner)) or str(getattr(job, owner)),
                "session_id": job.session_id,
                "reason": failure_reason(job.last_error),
                "attempts": int(job.attempt_count or 0),
                "failed_at": job.updated_at.isoformat() if job.updated_at else None,
                "mined_to": int(job.extracted_sequence or 0),
                "of": int(job.watermark_sequence or 0),
            }
            for job in shown
        ],
    }


def _same_chat(job: Any) -> list[Any]:
    model = type(job)
    if model is UserMemoryJob:
        return [model.user_id == job.user_id, model.session_id == job.session_id]
    return [model.project_id == job.project_id, model.session_id == job.session_id]


async def _open_job(db: AsyncSession, job: Any) -> Any | None:
    model = type(job)
    return (
        (
            await db.execute(
                select(model).where(*_same_chat(job), model.status.in_(("pending", "retry")), model.id != job.id)
            )
        )
        .scalars()
        .first()
    )


async def _progress(db: AsyncSession, job: Any) -> int:
    """How far the chat has been mined, by this job or by any job after it."""
    model = type(job)
    others = (
        await db.execute(select(func.max(model.extracted_sequence)).where(*_same_chat(job), model.id != job.id))
    ).scalar_one_or_none()
    return max(int(job.extracted_sequence or 0), int(others or 0))


async def _dispatch(db: AsyncSession, job: Any, now: dt.datetime, *, reason: str = "admin-retry") -> None:
    if isinstance(job, UserMemoryJob):
        aggregate, event, prefix = "user_memory_job", "memory.job.ready", "user-memory"
    else:
        from app.services.project_memory_job_service import AGGREGATE_TYPE, EVENT_TYPE

        aggregate, event, prefix = AGGREGATE_TYPE, EVENT_TYPE, "project-memory"
    await enqueue_outbox_event(
        db,
        aggregate_type=aggregate,
        aggregate_id=job.id,
        event_type=event,
        payload={"job_id": job.id, "attempt": 0},
        idempotency_key=f"{prefix}:{job.id}:dispatch:0:{reason}:{uuid.uuid4().hex[:12]}",
        available_at=now,
    )


async def hand_over(db: AsyncSession, job: Any, *, after_seconds: int) -> None:
    """Give a job's stretch - from where it starts, as it is - to a job of the same chat that runs later.

    For a job that finds another job of its chat mining it: rather than read
    the same parts at the same time, it goes on after that one. Its own
    starting point is kept (a relearn job starts earlier than the chat was
    mined, on purpose): the chat's open job starts no later than it, or a new
    job takes its stretch.
    """
    from app.config import get_settings

    model = type(job)
    now = dt.datetime.utcnow()
    run_after = now + dt.timedelta(seconds=after_seconds)
    open_job = await _open_job(db, job)
    if open_job is None:
        owner = {"user_id": job.user_id} if model is UserMemoryJob else {"project_id": job.project_id}
        follow = model(
            id=str(uuid.uuid4()),
            **owner,
            session_id=job.session_id,
            status="pending",
            watermark_sequence=int(job.watermark_sequence or 0),
            extracted_sequence=int(job.extracted_sequence or 0),
            run_after=run_after,
            attempt_count=0,
            max_attempts=get_settings().memory_job_max_attempts,
            created_at=now,
            updated_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(follow)
                await db.flush()
        except IntegrityError:
            open_job = await _open_job(db, job)
        else:
            await _dispatch(db, follow, run_after, reason="handed-over")
            return
    if open_job is not None:
        open_job.extracted_sequence = min(int(open_job.extracted_sequence or 0), int(job.extracted_sequence or 0))
        open_job.watermark_sequence = max(int(open_job.watermark_sequence or 0), int(job.watermark_sequence or 0))
        open_job.run_after = max(open_job.run_after or now, run_after)
        open_job.updated_at = now
        await db.flush()


async def retry_failed_jobs(db: AsyncSession, scope: str, *, job_ids: list[str] | None = None) -> dict[str, int]:
    """Send the scope's dead jobs (or the ones named) back to the queue, with their attempts reset.

    A job goes on from where its chat has been mined to, so nothing is mined
    twice: from where it stopped, or from further on when a later job of the
    same chat took its stretch over. What each failed job comes to:

    - ``covered``: a later job mined all of its stretch; it is removed.
    - ``merged``: the chat has an open job already (the person kept talking);
      that job takes the failed one's stretch, and the failed one is removed.
      Two open jobs for one chat are not allowed, and one is enough.
    - ``requeued``: back in the queue, to run now.
    """
    model = _model(scope)
    statement = select(model).where(model.status == "dead")
    if job_ids is not None:
        statement = statement.where(model.id.in_([str(item) for item in job_ids]))
    jobs = list((await db.execute(statement)).scalars())
    now = dt.datetime.utcnow()
    counts = {"requeued": 0, "merged": 0, "covered": 0}
    for job in jobs:
        progress = await _progress(db, job)
        if progress >= int(job.watermark_sequence or 0):
            await db.delete(job)
            counts["covered"] += 1
            continue
        open_job = await _open_job(db, job)
        if open_job is None:
            try:
                async with db.begin_nested():
                    job.status = "retry"
                    job.extracted_sequence = progress
                    job.attempt_count = 0
                    job.run_after = now
                    job.worker_id = None
                    job.lease_expires_at = None
                    job.last_error = None
                    job.updated_at = now
                    await db.flush()
            except IntegrityError:
                # An open job was made for this chat a moment ago.
                await db.refresh(job)
                open_job = await _open_job(db, job)
            else:
                await _dispatch(db, job, now)
                counts["requeued"] += 1
                continue
        if open_job is not None:
            open_job.extracted_sequence = min(int(open_job.extracted_sequence or 0), progress)
            open_job.watermark_sequence = max(int(open_job.watermark_sequence or 0), int(job.watermark_sequence or 0))
            open_job.updated_at = now
            await db.delete(job)
            counts["merged"] += 1
    await db.flush()
    return counts
