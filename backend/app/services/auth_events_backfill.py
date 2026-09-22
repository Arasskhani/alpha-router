"""Carry the sign-in history that predates ``auth_events`` into it.

Before the table existed, sign-ins were three ``action`` values in
``security_audit_events`` plus ``saml_response_rejected``. A Sign-in Activity
page that opened empty on the day it shipped would be answering the wrong
question — the history from before is exactly what an operator wants to look
back through — so this copies those rows over, once.

Idempotent by construction: every row written here carries the id of the
legacy event it came from, and that column has a unique index. Running it
again finds nothing to do. Running it while the application is live is safe;
new events go straight to the new table and are never candidates here.

Rows whose ``detail_json`` retention has already blanked cannot say why a
sign-in failed. They are carried with ``reason_code='unknown'`` and
``backfilled=true`` rather than dropped: the fact that an attempt failed, from
that address, at that time, is still the fact — only its reason has aged out.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_event import AuthEvent
from app.models.security import SecurityAuditEvent
from app.models.user import User

logger = logging.getLogger(__name__)

#: The legacy action values this understands. Anything else in the table is an
#: administrative event, not a sign-in, and stays where it is.
LEGACY_ACTIONS: tuple[str, ...] = ("login_success", "login_failed", "logout", "saml_response_rejected")

_LEGACY_REASONS = {
    "bad_password": "bad_password",
    "deleted": "account_deleted",
    "unknown": "unknown",
}


@dataclass
class BackfillReport:
    scanned: int = 0
    written: int = 0
    skipped_existing: int = 0
    redacted: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    first: dt.datetime | None = None
    last: dt.datetime | None = None


def _detail(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def translate(event: SecurityAuditEvent, *, provider_by_user: dict[int, str]) -> AuthEvent | None:
    """One legacy row to one new row, or None when it is not a sign-in event."""

    detail = _detail(event.detail_json)
    redacted = event.detail_redacted_at is not None
    action = str(event.action or "")
    user_id = event.actor_user_id
    method = (detail.get("provider") or provider_by_user.get(user_id or -1) or "").strip().lower() or None
    if method not in ("local", "ldap", "saml", "oidc"):
        method = None

    common: dict[str, Any] = dict(
        occurred_at=event.created_at or dt.datetime.utcnow(),
        user_id=user_id,
        # The account's name at the time, or the name that was typed at a
        # missing account — the legacy writer put the latter in detail.
        username=(event.actor_username or detail.get("username") or None),
        ip=event.actor_ip,
        auth_method=method,
        source_event_id=event.id,
        backfilled=True,
    )

    if action == "login_success":
        return AuthEvent(event_type="login_success", outcome="success", **common)
    if action == "login_failed":
        code = "unknown" if redacted else _LEGACY_REASONS.get(str(detail.get("reason") or ""), "unknown")
        return AuthEvent(event_type="login_failed", outcome="failure", reason_code=code, **common)
    if action == "logout":
        return AuthEvent(event_type="logout", outcome="n/a", scope="all_sessions", **common)
    if action == "saml_response_rejected":
        common["auth_method"] = "saml"
        return AuthEvent(
            event_type="login_failed",
            outcome="failure",
            reason_code="saml_rejected",
            reason_detail=None if redacted else (detail.get("reason") or None),
            **common,
        )
    return None


async def backfill_auth_events(db: AsyncSession, *, batch_size: int = 5000) -> BackfillReport:
    """Copy every legacy sign-in event not yet carried over. Commits per batch."""

    report = BackfillReport()
    already = set(
        (await db.execute(select(AuthEvent.source_event_id).where(AuthEvent.source_event_id.is_not(None)))).scalars()
    )
    # Method for rows whose detail never said: the account's provider today is
    # the best available answer, and honest enough for a backfilled row.
    provider_by_user = {
        int(uid): str(prov or "").lower() for uid, prov in (await db.execute(select(User.id, User.auth_provider))).all()
    }

    last_id = 0
    while True:
        batch = (
            (
                await db.execute(
                    select(SecurityAuditEvent)
                    .where(SecurityAuditEvent.action.in_(LEGACY_ACTIONS), SecurityAuditEvent.id > last_id)
                    .order_by(SecurityAuditEvent.id)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not batch:
            break
        for event in batch:
            last_id = int(event.id)
            report.scanned += 1
            if event.id in already:
                report.skipped_existing += 1
                continue
            row = translate(event, provider_by_user=provider_by_user)
            if row is None:
                continue
            db.add(row)
            report.written += 1
            report.by_type[row.event_type] = report.by_type.get(row.event_type, 0) + 1
            if event.detail_redacted_at is not None:
                report.redacted += 1
            when = event.created_at
            if when is not None:
                report.first = when if report.first is None or when < report.first else report.first
                report.last = when if report.last is None or when > report.last else report.last
        await db.commit()
    return report


async def record_backfill_run(db: AsyncSession, report: BackfillReport) -> None:
    """The backfill is itself an administrative act, and goes in the trail."""

    from app.services.security_audit import log_security_event

    await log_security_event(
        db,
        actor=None,
        actor_ip=None,
        action="auth_events_backfilled",
        resource_type="auth_events",
        detail={
            "scanned": report.scanned,
            "written": report.written,
            "skipped_existing": report.skipped_existing,
            "redacted": report.redacted,
            "by_type": report.by_type,
            "first": report.first.isoformat() if report.first else None,
            "last": report.last.isoformat() if report.last else None,
        },
    )
    await db.commit()


async def legacy_event_count(db: AsyncSession) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(SecurityAuditEvent)
                .where(SecurityAuditEvent.action.in_(LEGACY_ACTIONS))
            )
        ).scalar_one()
        or 0
    )
