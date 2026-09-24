"""Tell an administrator when sign-in failures stop looking like a typo.

Two patterns, read from ``auth_events`` every few minutes over a sliding
fifteen-minute window:

* **One account, many failures.** Ten or more failed or rate-limited attempts
  against a single account: a password-guessing attack on that account, or a
  person locked out of something they should know. Either way the
  administrator should hear about it before the account's owner asks.
* **One address, many accounts.** Five or more distinct account names tried
  from a single address: credential stuffing or a scan, which no single
  account's history would reveal.

What this does *not* do is lock anyone out. The login rate limiter already
slows the attacker down; locking the account on top of that hands an attacker
a way to lock out the legitimate owner with nothing but the username. This
raises the flag and leaves the decision to a person.

Every alert is written to the administrative trail as
``suspicious_sign_in_pattern`` — that row is the record, and also the
deduplication ledger. The e-mail to Super Admins is best effort: SMTP not
configured is a warning, not an error. Each pattern is raised at most once
per hour per subject; Redis carries that memory when it is there, and the
trail itself answers the question when it is not.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_event import OUTCOME_FAILURE, AuthEvent
from app.models.security import SecurityAuditEvent
from app.models.user import User, UserRoleAssignment
from app.services.observability import increment
from app.services.rbac import SUPER_ADMIN_SLUG
from app.services.smtp_service import SmtpNotConfiguredError, SmtpRecipientError, SmtpSendError, send_email

logger = logging.getLogger(__name__)

ACTION = "suspicious_sign_in_pattern"
WINDOW_MINUTES = 15
USER_FAILURE_THRESHOLD = 10
IP_DISTINCT_USERS_THRESHOLD = 5
#: One alert per subject per this many seconds, however long the attack runs.
DEDUP_SECONDS = 3600
#: How many of the tried names the alert quotes. Enough to recognise a
#: pattern, not the whole list an attacker fed in.
SAMPLE_NAMES = 10

KIND_ACCOUNT = "account_failures"
KIND_ADDRESS = "address_many_accounts"


@dataclass(frozen=True)
class Alert:
    kind: str
    subject: str  # "user:<id>" / "name:<username>" / "ip:<address>"
    count: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def subject_label(self) -> str:
        return self.detail.get("username") or self.detail.get("ip") or self.subject


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


async def find_patterns(db: AsyncSession, *, now: datetime.datetime | None = None) -> list[Alert]:
    """The patterns present in the window right now. Pure read."""

    moment = now or _now()
    since = moment - datetime.timedelta(minutes=WINDOW_MINUTES)
    failures = select(AuthEvent).where(AuthEvent.outcome == OUTCOME_FAILURE, AuthEvent.occurred_at >= since).subquery()

    alerts: list[Alert] = []

    # One account, many failures. Grouped by the *name* tried, not the user
    # id: an attack on an account that does not exist has no id, and an
    # attack that alternates "alice" and "Alice" is still one attack on alice.
    by_name = (
        await db.execute(
            select(
                func.lower(failures.c.username).label("name"),
                func.count().label("n"),
                func.count(func.distinct(failures.c.ip)).label("ips"),
                func.max(failures.c.user_id).label("user_id"),
                func.min(failures.c.occurred_at).label("first"),
                func.max(failures.c.occurred_at).label("last"),
            )
            .where(failures.c.username.isnot(None))
            .group_by(func.lower(failures.c.username))
            .having(func.count() >= USER_FAILURE_THRESHOLD)
        )
    ).all()
    for name, n, ips, user_id, first, last in by_name:
        alerts.append(
            Alert(
                kind=KIND_ACCOUNT,
                subject=f"name:{name}",
                count=int(n),
                detail={
                    "username": name,
                    "user_id": int(user_id) if user_id is not None else None,
                    "failures": int(n),
                    "distinct_addresses": int(ips or 0),
                    "window_minutes": WINDOW_MINUTES,
                    "first": first.isoformat() if first else None,
                    "last": last.isoformat() if last else None,
                },
            )
        )

    # One address, many accounts.
    by_ip = (
        await db.execute(
            select(
                failures.c.ip,
                func.count(func.distinct(func.lower(failures.c.username))).label("names"),
                func.count().label("n"),
                func.min(failures.c.occurred_at).label("first"),
                func.max(failures.c.occurred_at).label("last"),
            )
            .where(failures.c.ip.isnot(None), failures.c.username.isnot(None))
            .group_by(failures.c.ip)
            .having(func.count(func.distinct(func.lower(failures.c.username))) >= IP_DISTINCT_USERS_THRESHOLD)
        )
    ).all()
    for ip, names, n, first, last in by_ip:
        sample = (
            await db.execute(
                select(func.lower(failures.c.username))
                .where(failures.c.ip == ip)
                .group_by(func.lower(failures.c.username))
                .order_by(func.lower(failures.c.username))
                .limit(SAMPLE_NAMES)
            )
        ).scalars()
        alerts.append(
            Alert(
                kind=KIND_ADDRESS,
                subject=f"ip:{ip}",
                count=int(names),
                detail={
                    "ip": ip,
                    "distinct_accounts": int(names),
                    "failures": int(n),
                    "sample_accounts": list(sample),
                    "window_minutes": WINDOW_MINUTES,
                    "first": first.isoformat() if first else None,
                    "last": last.isoformat() if last else None,
                },
            )
        )
    return alerts


async def _already_raised(db: AsyncSession, alert: Alert, *, now: datetime.datetime) -> bool:
    """Once per hour per subject. Redis when it answers; the trail otherwise.

    Redis is the cheap path and shared across workers. It is not the record:
    if it is empty (restart, eviction, outage) the trail — which *is* the
    record — is asked, so an outage costs a query, never a duplicate e-mail.
    """
    try:
        from app.core.redis_client import get_redis

        key = f"sign_in_alert:{alert.kind}:{alert.subject}"
        # SET NX EX: first caller in the hour wins; the key expires on its own.
        if not await get_redis().set(key, now.isoformat(), nx=True, ex=DEDUP_SECONDS):
            return True
    except Exception:  # noqa: BLE001 -- Redis is an accelerator here, not the ledger
        logger.debug("sign-in alert dedup: Redis unavailable, asking the trail")

    recent = await db.execute(
        select(func.count())
        .select_from(SecurityAuditEvent)
        .where(
            SecurityAuditEvent.action == ACTION,
            SecurityAuditEvent.resource_id == alert.subject,
            SecurityAuditEvent.created_at >= now - datetime.timedelta(seconds=DEDUP_SECONDS),
        )
    )
    return int(recent.scalar_one() or 0) > 0


async def _recipients(db: AsyncSession) -> list[str]:
    rows = (
        (
            await db.execute(
                select(User.email)
                .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
                .where(
                    UserRoleAssignment.role_slug == SUPER_ADMIN_SLUG,
                    User.email.isnot(None),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return sorted({(email or "").strip() for email in rows if (email or "").strip()})


def _message(alert: Alert) -> tuple[str, str]:
    d = alert.detail
    if alert.kind == KIND_ACCOUNT:
        subject = f"Alpharouter: {d['failures']} failed sign-ins for '{d['username']}' in {WINDOW_MINUTES} minutes"
        body = (
            f"{d['failures']} failed sign-in attempts were recorded for the account '{d['username']}' "
            f"between {d['first']}Z and {d['last']}Z, from {d['distinct_addresses']} distinct address(es).\n\n"
            "The account has NOT been locked. The login rate limiter is slowing further attempts.\n\n"
            "Review: Admin -> Data & reports -> Sign-in Activity, filter by this username.\n"
        )
    else:
        names = ", ".join(d.get("sample_accounts") or [])
        subject = f"Alpharouter: {d['distinct_accounts']} accounts tried from {d['ip']} in {WINDOW_MINUTES} minutes"
        body = (
            f"{d['failures']} failed sign-in attempts against {d['distinct_accounts']} distinct account names "
            f"were recorded from {d['ip']} between {d['first']}Z and {d['last']}Z.\n"
            f"Accounts tried include: {names}\n\n"
            "No account has been locked. Consider blocking the address at your edge if it is not one you know.\n\n"
            "Review: Admin -> Data & reports -> Sign-in Activity, filter by this IP address.\n"
        )
    return subject, body


async def raise_alerts(db: AsyncSession, *, now: datetime.datetime | None = None) -> dict[str, int]:
    """Find, deduplicate, record, notify. Commits.

    The trail row is written and committed *before* the e-mail is attempted,
    so a mail failure never loses the record, and a duplicate mail can never
    be sent for a pattern the trail does not know about.
    """

    moment = now or _now()
    found = await find_patterns(db, now=moment)
    raised = 0
    sent = 0
    suppressed = 0
    recipients: list[str] | None = None
    smtp_down = False
    for alert in found:
        if await _already_raised(db, alert, now=moment):
            suppressed += 1
            continue
        db.add(
            SecurityAuditEvent(
                actor_user_id=None,
                actor_username=None,
                actor_email=None,
                actor_ip=None,
                action=ACTION,
                resource_type="authentication",
                resource_id=alert.subject,
                detail_json=_dumps({"kind": alert.kind, **alert.detail}),
                created_at=moment,
            )
        )
        await db.commit()
        raised += 1
        increment("sign_in_alert_raised")
        logger.warning("Suspicious sign-in pattern %s for %s: %s", alert.kind, alert.subject_label, alert.detail)

        if smtp_down:
            continue
        # The record is committed; whatever goes wrong with this alert's mail
        # below must not stop the alerts after it being recorded and mailed.
        try:
            if recipients is None:
                recipients = await _recipients(db)
                if not recipients:
                    logger.warning("Sign-in alert not e-mailed: no active Super Admin has an e-mail address.")
            subject, body = _message(alert)
        except Exception:  # noqa: BLE001 -- one alert's mail must not stop the next alert
            logger.exception("Sign-in alert %s for %s could not be prepared for e-mail", alert.kind, alert.subject)
            continue
        for address in recipients:
            try:
                await send_email(db, to_address=address, subject=subject, body_text=body)
                sent += 1
            except SmtpRecipientError as exc:
                # This address only (malformed, or refused by the server): the
                # other Super Admins, and the alerts after this one, still get it.
                logger.warning("Sign-in alert not e-mailed to %s: %s", address, exc)
            except (SmtpNotConfiguredError, SmtpSendError) as exc:
                # The server or the settings: every other address would fail the same way.
                logger.warning("Sign-in alert not e-mailed to %s: %s", address, exc)
                smtp_down = True
                break
            except Exception:  # noqa: BLE001 -- the records must survive whatever the mail path raises
                logger.exception("Sign-in alert not e-mailed to %s", address)
                smtp_down = True
                break
    return {"found": len(found), "raised": raised, "suppressed": suppressed, "emails_sent": sent}


def _dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, default=str)
