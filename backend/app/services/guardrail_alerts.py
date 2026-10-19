"""Guardrails: telling the administrators' chosen addresses when a rule blocks something, and keeping
the events only as long as they said.

An alert is the administrator's choice (Settings: alert addresses); with none
set, nothing is sent. At most one email per rule every ``ALERT_INTERVAL``
per worker, so a burst of blocked messages is one alert, not a flood; the
events themselves keep the whole count. An alert says what the event says -
the rule, who, where, what kind and how many - never a value.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select

from app.models.guardrail import GuardrailEvent

logger = logging.getLogger(__name__)

ALERT_INTERVAL = datetime.timedelta(minutes=10)
_PURGE_BATCH_SIZE = 5000
_last_alert: dict[int | None, datetime.datetime] = {}
_pending: set[asyncio.Task[Any]] = set()


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def reset_alert_state() -> None:
    _last_alert.clear()


def alert_text(row: GuardrailEvent) -> tuple[str, str]:
    finds = []
    try:
        for finding in json.loads(str(row.findings_json or "[]")):
            finds.append(f"{finding.get('name')} ×{finding.get('count')}")
    except (TypeError, ValueError):
        pass
    subject = f"Guardrails blocked a request: {row.rule_name or 'a rule'}"
    body = "\n".join(
        [
            "A Guardrails rule blocked a request.",
            "",
            f"Rule: {row.rule_name or '-'} (version {row.rule_version or '-'})",
            f"Who: {row.username or ('API key #' + str(row.alpha_router_api_key_id) if row.alpha_router_api_key_id else '-')}",
            f"Channel: {row.channel}",
            f"Destination: {row.destination or '-'} ({row.destination_trust or '-'})",
            f"Found: {', '.join(finds) or '-'}",
            f"Time (UTC): {(row.created_at or _now()).isoformat(timespec='seconds')}",
            "",
            "The values found are never stored or sent. Admin › Guardrails › Events has the details.",
        ]
    )
    return subject, body


async def _send(rows: Sequence[GuardrailEvent], session_factory: Any) -> None:
    from app.services.guardrail_policy import load_settings
    from app.services.smtp_service import send_email

    async with session_factory() as db:
        settings = await load_settings(db)
        if not settings.alert_emails:
            return
        for row in rows:
            subject, body = alert_text(row)
            first, *others = settings.alert_emails
            try:
                await send_email(db, to_address=first, cc=others, subject=subject, body_text=body)
            except Exception:  # noqa: BLE001 -- an alert that cannot go out must not touch the request
                logger.warning("A Guardrails alert could not be sent", exc_info=True)


async def alert_blocked(rows: Sequence[GuardrailEvent], session_factory: Any = None) -> None:
    """Email the alert addresses about blocks, at most once per rule per interval; never waits on the mail."""
    now = _now()
    due: list[GuardrailEvent] = []
    for row in rows:
        if row.action != "block":
            continue
        rule_id = int(row.rule_id) if row.rule_id is not None else None
        last = _last_alert.get(rule_id)
        if last is not None and now - last < ALERT_INTERVAL:
            continue
        _last_alert[rule_id] = now
        due.append(row)
    if not due:
        return
    if session_factory is None:
        from app.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal
    task = asyncio.create_task(_send(due, session_factory))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def purge_expired_events(db: Any) -> dict[str, int]:
    """Delete events older than the administrator's retention window, in batches."""
    from app.services.guardrail_policy import load_settings

    days = (await load_settings(db)).event_retention_days
    cutoff = _now() - datetime.timedelta(days=days)
    deleted = 0
    while True:
        ids = (
            (
                await db.execute(
                    select(GuardrailEvent.id).where(GuardrailEvent.created_at < cutoff).limit(_PURGE_BATCH_SIZE)
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        await db.execute(delete(GuardrailEvent).where(GuardrailEvent.id.in_(ids)))
        await db.commit()
        deleted += len(ids)
    return {"events_deleted": deleted, "retention_days": days}
