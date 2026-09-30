"""Claiming a job whose state lives on the row it works on (a chat's summary, a chat's recall index).

The knowledge worker runs these jobs (``KnowledgeWorker._process_row_job``);
the services keep their own rows. What is shared is how a run takes a row:

- in one statement, so two deliveries of the same message never both run
  (a read, a check and a write let both through);
- a row left ``running`` by a worker that stopped is taken again once its
  lease has run out;
- a delivery that finds the row held by a live lease is not simply dropped:
  the worker that holds it may have died, and nothing else would run the row
  again until the chat's next reply. It asks to be delivered again once the
  lease has run out (``lease_end``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

#: How long after a lease runs out the row is looked at again.
REDELIVERY_GRACE_SECONDS = 5


async def claim_row(
    db: AsyncSession,
    model: Any,
    *,
    session_id: str,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
) -> Any | None:
    """Take the row for ``worker_id`` when it is queued, retrying, or left behind by a stopped worker; else None."""
    now = dt.datetime.utcnow()
    claimed = await db.execute(
        update(model)
        .where(
            model.session_id == session_id,
            or_(
                model.status == "pending",
                and_(model.status == "failed", model.attempt_count < int(max_attempts)),
                and_(
                    model.status == "running",
                    or_(model.lease_expires_at.is_(None), model.lease_expires_at <= now),
                ),
            ),
        )
        .values(
            status="running",
            worker_id=worker_id,
            attempt_count=model.attempt_count + 1,
            lease_expires_at=now + dt.timedelta(seconds=int(lease_seconds)),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(claimed, "rowcount", 0) or 0) != 1:
        return None
    return (
        await db.execute(select(model).where(model.session_id == session_id).execution_options(populate_existing=True))
    ).scalar_one()


async def lease_end(db: AsyncSession, model: Any, *, session_id: str) -> dt.datetime | None:
    """When the live lease holding the row runs out (plus a little); None when no live lease holds it."""
    now = dt.datetime.utcnow()
    row = (
        await db.execute(select(model.status, model.lease_expires_at).where(model.session_id == session_id))
    ).one_or_none()
    if row is None or row.status != "running" or row.lease_expires_at is None or row.lease_expires_at <= now:
        return None
    return row.lease_expires_at + dt.timedelta(seconds=REDELIVERY_GRACE_SECONDS)
