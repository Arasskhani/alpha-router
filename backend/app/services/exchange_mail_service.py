"""Exchange EWS mailboxes: what the Connections and admin APIs do, apart from the HTTP.

``exchange_mail`` holds the rules (who may connect, the login, when a
connection stops); this module holds the work the two routers ask for, so they
stay thin and every rule about a refused password is kept in one place:

- **Connecting.** The password is tried once: ``whoami``, then (when the
  administrator wants it) ``same_mailbox`` with the account's email, then
  Autodiscover for Full Access mailboxes. A refused password stores nothing
  for a new connection and turns an existing one ``needs_password``; nothing
  here ever tries a password a second time. Failed attempts are counted
  (``CONNECT_ATTEMPTS`` in ``CONNECT_WINDOW_S``) so a person cannot lock their
  own AD account through the form either.
- **Mailboxes.** The own mailbox, those Autodiscover lists, and those added by
  hand after a test read of their Inbox. ``max_mailboxes`` bounds the Full
  Access mailboxes of one person; the own mailbox is not counted.
- **Drafts.** Read live from Exchange before the person sends (the change key
  they saw is the one sent), sent or discarded only by the person.
- **Action items.** Their state changes (notified, dismissed, done) and the
  composer text "Ask Alpharouter" opens a chat with.
- **Admin.** The Test connection steps, the People list and the overview.

Every failure an API answers is a ``MailError`` (code, message, HTTP status);
an ``EwsError`` becomes ``exchange_<kind>``. Functions flush and never commit:
the router commits, also before it answers a refusal, so a failure noted on
the connection is kept. Nothing here logs or returns a password, a body, a
subject or recipients' addresses beyond what the person's own screens show.
"""

from __future__ import annotations

import datetime
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail_connection import MailActionItem, MailConnection, MailConnectionMailbox, MailDraft
from app.models.user import User
from app.services import exchange_mail as em
from app.services import rate_limit
from app.services.exchange_ews_types import DraftResult, EwsError, MailboxInfo

if TYPE_CHECKING:
    from app.services.exchange_ews_types import MailClient

logger = logging.getLogger(__name__)

#: Failed connect attempts one person may make in ``CONNECT_WINDOW_S`` (AD lockout is usually 5-10 in 15-30 min).
CONNECT_ATTEMPTS = 5
CONNECT_WINDOW_S = 15 * 60
SENDS_PER_HOUR = 30
TESTS_PER_WINDOW = 10
TEST_WINDOW_S = 15 * 60
#: The opening of a draft kept for its card and the Review & send dialog's list view.
PREVIEW_CHARS = 300
ASK_SUBJECT_CHARS = 150
ACTION_LIST_MAX = 200
NOTIFIED_IDS_MAX = 200
#: Where the needs-action check starts on a new connection: the last day, not the whole Inbox.
FIRST_WATERMARK = datetime.timedelta(hours=24)
DRAFT_GONE = "The draft is no longer in Drafts: it was sent or deleted in Outlook."
CONNECTION_STATUSES = ("connected", "needs_password", "error")
OPEN_ACTION_STATUSES = ("new", "notified")

#: The HTTP status each kind of Exchange failure is answered with.
EWS_STATUS: dict[str, int] = {
    "auth": 400,
    "unreachable": 502,
    "tls": 502,
    "access_denied": 403,
    "not_found": 404,
    "throttled": 503,
    "mailbox_mismatch": 400,
    "invalid": 422,
    "conflict": 409,
    "server": 502,
}
#: Failures that will likely pass by themselves: a draft that met one is still in Drafts and can be sent again.
_PASSING_KINDS = ("auth", "unreachable", "tls", "throttled")
_PASSWORD_REFUSED = "Exchange did not accept your password. If you changed it, type the new one on Connections."
_MISMATCH = "This password opens another mailbox than yours."


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def iso_utc(value: datetime.datetime | None) -> str | None:
    """``2026-10-25T08:00:00Z``: stored times are naive UTC, so the zone is said out loud."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(datetime.UTC).replace(tzinfo=None)
    return f"{value.isoformat(timespec='seconds')}Z"


def ews_refusal(error: EwsError) -> em.MailError:
    """How an API answers a failure from Exchange: ``exchange_<kind>`` with the client's safe message."""
    return em.MailError(f"exchange_{error.kind}", em.friendly_error(error), EWS_STATUS.get(error.kind, 502))


def preview_of(text: str) -> str:
    return " ".join((text or "").split())[:PREVIEW_CHARS]


def _addresses_json(addresses: Sequence[Any]) -> str:
    return json.dumps([{"name": str(a.name or ""), "email": str(a.email or "")} for a in addresses], ensure_ascii=False)


def _addresses(raw: Any) -> list[dict[str, str]]:
    try:
        data = json.loads(str(raw or "[]"))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [
        {"name": str(item.get("name") or ""), "email": str(item.get("email") or "")}
        for item in data
        if isinstance(item, dict) and item.get("email")
    ]


async def _hit(key: str, *, limit: int, window_s: int, message: str) -> None:
    """Count one attempt against ``key``; refuse with ``too_many_attempts`` when the window is full."""
    try:
        await rate_limit.check_rate_limit(key, limit=limit, window_seconds=window_s)
    except HTTPException as exc:
        if exc.status_code == 429:
            raise em.MailError("too_many_attempts", message, 429) from exc
        raise


# --- shapes the APIs answer with ----------------------------------------------------------------------------------


def capabilities(settings: em.ExchangeSettings) -> dict[str, Any]:
    """What the Connections page and the chat may offer, from the administrator's switches."""
    return {
        "full_access": settings.allow_full_access,
        "manual_mailboxes": settings.allow_full_access and settings.allow_manual_mailboxes,
        "drafts": settings.allow_drafts,
        "send": settings.allow_send,
        "free_time": settings.allow_free_time,
        "notifications": settings.notify_enabled,
        "max_mailboxes": settings.max_mailboxes,
    }


def mailbox_out(row: MailConnectionMailbox) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "smtp": str(row.smtp),
        "display_name": str(row.display_name or ""),
        "kind": str(row.kind),
        "source": str(row.source),
        "enabled": bool(row.enabled),
        "notify": bool(row.notify),
        "verified_at": iso_utc(row.verified_at),  # type: ignore[arg-type]
        "last_error": str(row.last_error) if row.last_error else None,
    }


async def connection_out(db: AsyncSession, connection: MailConnection) -> dict[str, Any]:
    """The connection as its owner sees it (never the password), its own mailbox first."""
    rows = await em.list_mailboxes(db, int(connection.id))
    return {
        "status": str(connection.status),
        "login": str(connection.login),
        "primary_smtp": str(connection.primary_smtp),
        "display_name": str(connection.display_name or ""),
        "last_error": str(connection.last_error) if connection.last_error else None,
        "last_ok_at": iso_utc(connection.last_ok_at),  # type: ignore[arg-type]
        "last_checked_at": iso_utc(connection.last_checked_at),  # type: ignore[arg-type]
        "connected_at": iso_utc(connection.connected_at),  # type: ignore[arg-type]
        "notify_enabled": bool(connection.notify_enabled),
        "mailboxes": [mailbox_out(row) for row in rows],
    }


def action_item_out(item: MailActionItem) -> dict[str, Any]:
    return {
        "id": int(item.id),
        "mailbox": str(item.mailbox_smtp),
        "subject": str(item.subject or ""),
        "sender_name": str(item.sender_name) if item.sender_name else None,
        "sender_email": str(item.sender_email) if item.sender_email else None,
        "received_at": iso_utc(item.received_at),  # type: ignore[arg-type]
        "reason": str(item.reason or ""),
        "action": str(item.action),
        "importance": str(item.importance) if item.importance else None,
        "status": str(item.status),
        "owa_url": str(item.owa_url) if item.owa_url else None,
        "created_at": iso_utc(item.created_at),  # type: ignore[arg-type]
    }


def draft_out(draft: MailDraft) -> dict[str, Any]:
    return {
        "id": int(draft.id),
        "mailbox": str(draft.mailbox_smtp),
        "kind": str(draft.kind),
        "status": str(draft.status),
        "subject": str(draft.subject or ""),
        "to": _addresses(draft.to_json),
        "cc": _addresses(draft.cc_json),
        "body_preview": str(draft.body_preview or ""),
        "created_at": iso_utc(draft.created_at),  # type: ignore[arg-type]
        "sent_at": iso_utc(draft.sent_at),  # type: ignore[arg-type]
        "error": str(draft.error) if draft.error else None,
        "chat_session_id": str(draft.chat_session_id) if draft.chat_session_id else None,
    }


async def open_action_count(db: AsyncSession, user_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(MailActionItem)
                .where(MailActionItem.user_id == user_id, MailActionItem.status.in_(OPEN_ACTION_STATUSES))
            )
        ).scalar_one()
        or 0
    )


async def status_out(db: AsyncSession, user: User, settings: em.ExchangeSettings) -> dict[str, Any]:
    """Everything the Connections card needs in one answer; says why when the person may not connect."""
    verdict = await em.eligibility(db, user, settings)
    defaults = await em.directory_defaults(db)
    connection = await em.get_connection(db, int(user.id))
    return {
        "eligible": verdict.allowed,
        "reason": verdict.reason,
        "message": verdict.message,
        "login": em.login_for(user, settings, defaults),
        "email": em.normalize_smtp(user.email) or str(user.email or ""),
        "connection": await connection_out(db, connection) if connection is not None else None,
        "capabilities": capabilities(settings),
        "pending_actions": await open_action_count(db, int(user.id)),
    }


# --- who may ask ----------------------------------------------------------------------------------------------------


async def require_eligible(db: AsyncSession, user: User, settings: em.ExchangeSettings) -> None:
    verdict = await em.eligibility(db, user, settings)
    if not verdict.allowed:
        raise em.MailError("not_eligible", verdict.message or "You may not connect a mailbox.", 403)


def _not_connected() -> em.MailError:
    return em.MailError("not_connected", "You have not connected your Exchange mailbox.", 404)


async def require_connection(db: AsyncSession, user: User, settings: em.ExchangeSettings) -> MailConnection:
    """The person's connection, whatever its status, for changes that do not reach Exchange."""
    await require_eligible(db, user, settings)
    connection = await em.get_connection(db, int(user.id))
    if connection is None:
        raise _not_connected()
    return connection


@dataclass(frozen=True)
class Usable:
    """A connection that may reach Exchange now, and what it may reach."""

    connection: MailConnection
    access: em.MailAccess


async def require_usable(db: AsyncSession, user: User, settings: em.ExchangeSettings) -> Usable:
    """``usable_access``, with the reason it is refused said as the API answers it.

    Not eligible: 403 ``not_eligible``. No connection: 404 ``not_connected``.
    A refused password, or one that can no longer be read: 409
    ``needs_password``. A connection stopped by repeated failures: 409
    ``connection_error`` (the person types the password again to restart it).
    """
    connection = await require_connection(db, user, settings)
    if connection.status == "needs_password":
        raise em.MailError(
            "needs_password",
            str(connection.last_error or "") or "Type your password again on Connections to use your mailbox.",
            409,
        )
    if connection.status == "error":
        raise em.MailError(
            "connection_error",
            f"{connection.last_error or 'The connection to your mailbox stopped.'} "
            "Type your password again on Connections to reconnect.",
            409,
        )
    access = await em.usable_access(db, user, settings)
    if access is None:
        raise em.MailError("needs_password", "Type your password again on Connections to use your mailbox.", 409)
    return Usable(connection=connection, access=access)


# --- calling Exchange on a stored connection ------------------------------------------------------------------------


async def _note_failure(
    db: AsyncSession, usable: Usable, error: EwsError, *, mailbox: str, item_kinds: Sequence[str]
) -> None:
    """Record a failure where it belongs: the item, a Full Access mailbox, or the connection itself.

    ``item_kinds`` are the kinds that, for this call, are about the item
    (a draft changed or gone, a recipient refused) and say nothing about the
    connection; they are not recorded, so a few conflicts never stop it.
    """
    if error.kind in item_kinds:
        return
    own = usable.access.own_smtp
    if mailbox and em.normalize_smtp(mailbox) != own and error.kind in ("access_denied", "not_found"):
        await em.record_mailbox_failure(db, int(usable.connection.id), mailbox, error)
        return
    await em.record_failure(db, usable.connection, error)


def _refusal_after(error: EwsError) -> em.MailError:
    if error.kind == "auth":
        return em.MailError("exchange_auth", _PASSWORD_REFUSED, EWS_STATUS["auth"])
    return ews_refusal(error)


async def _ews[T](
    db: AsyncSession,
    usable: Usable,
    call: Callable[[MailClient], T],
    *,
    mailbox: str = "",
    item_kinds: Sequence[str] = (),
) -> T:
    """Run one client call on the stored connection and record how it went.

    Raises the ``EwsError`` (already recorded); the caller decides how to
    answer it. A refused password is never tried again here or anywhere.
    """
    client = em.make_client(usable.access.config)
    try:
        result = await em.run_ews(call, client, timeout_s=usable.access.settings.timeout_s + 5)
    except EwsError as error:
        await _note_failure(db, usable, error, mailbox=mailbox, item_kinds=item_kinds)
        raise
    finally:
        client.close()
    await em.record_success(db, usable.connection)
    return result


# --- connecting -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectOutcome:
    connection: MailConnection
    created: bool
    full_access_count: int


def connect_attempts_key(user_id: int) -> str:
    return f"mail:connect-failures:{int(user_id)}"


async def _sign_in(
    settings: em.ExchangeSettings, login: str, password: str, email: str
) -> tuple[MailboxInfo, list[MailboxInfo]]:
    """Try the password once: the mailbox it opens, that it is the account's own, and its Full Access list.

    Raises ``EwsError`` as the client does, or ``MailError("mailbox_mismatch")``.
    """
    timeout = settings.timeout_s + 5
    client = em.make_client(em.ews_config(settings, login, password))
    try:
        found = await em.run_ews(client.whoami, timeout_s=timeout)
        if not em.normalize_smtp(found.smtp):
            raise EwsError("server", "Exchange did not say which mailbox this login opens.")
        if settings.require_mailbox_match and not await em.run_ews(client.same_mailbox, email, timeout_s=timeout):
            raise em.MailError("mailbox_mismatch", _MISMATCH, 400)
        delegates: list[MailboxInfo] = []
        if settings.allow_full_access:
            try:
                delegates = list(await em.run_ews(client.discover_full_access, timeout_s=timeout))
            except EwsError as error:
                if error.kind == "auth":
                    raise
                # Autodiscover is a convenience: the connection works without it.
                logger.info("Autodiscover failed for a new mail connection: %s", error.kind)
        return found, delegates
    finally:
        client.close()


async def connect(db: AsyncSession, user: User, password: str, settings: em.ExchangeSettings) -> ConnectOutcome:
    """Connect the person's mailbox, or replace the password (and login) of their connection.

    Refusals: ``not_eligible`` (403), ``no_login`` (422), ``too_many_attempts``
    (429), ``invalid_password`` (422), ``exchange_auth`` (400),
    ``mailbox_mismatch`` (400), or another ``exchange_<kind>``.
    """
    await require_eligible(db, user, settings)
    login = em.login_for(user, settings, await em.directory_defaults(db))
    if not login:
        raise em.MailError(
            "no_login",
            "Your Exchange login cannot be made from your account. Ask your administrator to set the domain "
            "on the Exchange EWS page.",
            422,
        )
    key = connect_attempts_key(int(user.id))
    if await rate_limit.failure_limit_reached(key, limit=CONNECT_ATTEMPTS, window_seconds=CONNECT_WINDOW_S):
        raise em.MailError(
            "too_many_attempts",
            "Too many failed attempts. Wait 15 minutes before trying again, so your account is not locked.",
            429,
        )
    secret = em.encrypt_password(password)
    try:
        found, delegates = await _sign_in(settings, login, password, em.normalize_smtp(user.email))
    except EwsError as error:
        await rate_limit.record_failure(key, window_seconds=CONNECT_WINDOW_S)
        existing = await em.get_connection(db, int(user.id))
        if existing is not None and error.kind == "auth":
            # The password the person typed is refused: the stored one is not used again either.
            await em.record_failure(db, existing, error)
        raise ews_refusal(error) from error
    except em.MailError:
        await rate_limit.record_failure(key, window_seconds=CONNECT_WINDOW_S)
        raise
    return await _store_connection(db, user, login, secret, found, delegates, settings)


async def _store_connection(
    db: AsyncSession,
    user: User,
    login: str,
    secret: str,
    found: MailboxInfo,
    delegates: list[MailboxInfo],
    settings: em.ExchangeSettings,
) -> ConnectOutcome:
    now = _now()
    own = em.normalize_smtp(found.smtp)
    connection = await em.get_connection(db, int(user.id))
    created = connection is None
    if connection is None:
        connection = MailConnection(
            user_id=int(user.id),
            provider=em.PROVIDER,
            login=login,
            secret_encrypted=secret,
            primary_smtp=own,
            display_name=found.display_name[:255] or None,
            status="connected",
            consecutive_failures=0,
            notify_enabled=True,
            poll_watermark=now - FIRST_WATERMARK,
            last_ok_at=now,
            connected_at=now,
        )
        db.add(connection)
        await db.flush()
    else:
        if em.normalize_smtp(connection.primary_smtp) != own:
            # Another mailbox than before (the login format changed): its list starts again.
            for row in await em.list_mailboxes(db, int(connection.id)):
                await db.delete(row)
            await db.flush()
        watermark = connection.poll_watermark
        floor = now - FIRST_WATERMARK
        connection.login = login  # type: ignore[assignment]
        connection.secret_encrypted = secret  # type: ignore[assignment]
        connection.primary_smtp = own  # type: ignore[assignment]
        connection.display_name = found.display_name[:255] or connection.display_name  # type: ignore[assignment]
        connection.status = "connected"  # type: ignore[assignment]
        connection.last_error = None  # type: ignore[assignment]
        connection.consecutive_failures = 0  # type: ignore[assignment]
        connection.last_ok_at = now  # type: ignore[assignment]
        # A connection that waited days for its password does not toast about the whole week it missed.
        connection.poll_watermark = max(watermark, floor) if watermark is not None else floor  # type: ignore[assignment]
    await _ensure_own_mailbox(db, connection, found, now)
    if settings.allow_full_access:
        await sync_discovered(db, connection, delegates, settings, now=now)
    count = await _full_access_count(db, int(connection.id))
    await db.flush()
    return ConnectOutcome(connection=connection, created=created, full_access_count=count)


async def _ensure_own_mailbox(
    db: AsyncSession, connection: MailConnection, found: MailboxInfo, now: datetime.datetime
) -> None:
    own = em.normalize_smtp(found.smtp)
    rows = await em.list_mailboxes(db, int(connection.id))
    row = next((r for r in rows if r.kind == "own" and r.smtp == own), None)
    stale = [r for r in rows if r is not row and (r.kind == "own" or r.smtp == own)]
    for other in stale:
        await db.delete(other)
    if stale:
        await db.flush()
    if row is None:
        db.add(
            MailConnectionMailbox(
                connection_id=int(connection.id),
                smtp=own,
                display_name=found.display_name[:255] or None,
                kind="own",
                source="own",
                enabled=True,
                notify=True,
                verified_at=now,
                created_at=now,
            )
        )
    else:
        row.display_name = found.display_name[:255] or row.display_name  # type: ignore[assignment]
        row.enabled = True  # type: ignore[assignment]
        row.verified_at = now  # type: ignore[assignment]
        row.last_error = None  # type: ignore[assignment]
    await db.flush()


async def _full_access_count(db: AsyncSession, connection_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(MailConnectionMailbox)
                .where(
                    MailConnectionMailbox.connection_id == connection_id, MailConnectionMailbox.kind == "full_access"
                )
            )
        ).scalar_one()
        or 0
    )


@dataclass(frozen=True)
class SyncResult:
    added: int
    removed: int
    skipped: int


async def sync_discovered(
    db: AsyncSession,
    connection: MailConnection,
    listed: Sequence[MailboxInfo],
    settings: em.ExchangeSettings,
    *,
    now: datetime.datetime | None = None,
) -> SyncResult:
    """Make the Autodiscover rows what Autodiscover lists now.

    New ones are added (enabled, not notifying) up to ``max_mailboxes``;
    ``source=autodiscover`` rows no longer listed go; those added by hand and
    the own mailbox stay, as do the person's switches on rows still listed.

    An empty list removes nothing: the client answers ``[]`` both when the
    login has no Full Access mailboxes and when Autodiscover failed, and one
    failed lookup must not throw away the person's mailboxes and switches. A
    mailbox whose access was really taken away drops out at its next failed
    read instead (``exchange_mail.record_mailbox_failure``).
    """
    now = now or _now()
    own = em.normalize_smtp(connection.primary_smtp)
    wanted: dict[str, MailboxInfo] = {}
    for box in listed:
        smtp = em.normalize_smtp(box.smtp)
        if smtp and smtp != own:
            wanted.setdefault(smtp, box)
    rows = await em.list_mailboxes(db, int(connection.id))
    removed = 0
    kept: dict[str, MailConnectionMailbox] = {}
    for row in rows:
        if wanted and row.source == "autodiscover" and row.smtp not in wanted:
            await db.delete(row)
            removed += 1
        else:
            kept[str(row.smtp)] = row
    if removed:
        await db.flush()
    count = sum(1 for row in kept.values() if row.kind == "full_access")
    added = skipped = 0
    for smtp, box in wanted.items():
        existing = kept.get(smtp)
        if existing is not None:
            if existing.source == "autodiscover" and box.display_name:
                existing.display_name = box.display_name[:255]  # type: ignore[assignment]
            continue
        if count >= settings.max_mailboxes:
            skipped += 1
            continue
        db.add(
            MailConnectionMailbox(
                connection_id=int(connection.id),
                smtp=smtp,
                display_name=box.display_name[:255] or None,
                kind="full_access",
                source="autodiscover",
                enabled=True,
                notify=False,
                verified_at=now,
                created_at=now,
            )
        )
        count += 1
        added += 1
    await db.flush()
    return SyncResult(added=added, removed=removed, skipped=skipped)


# --- the person's mailboxes ----------------------------------------------------------------------------------------


def _full_access_off() -> em.MailError:
    return em.MailError("full_access_off", "Full Access mailboxes are turned off by your administrator.", 403)


async def _own_mailbox_row(db: AsyncSession, connection: MailConnection, mailbox_id: int) -> MailConnectionMailbox:
    row = await db.get(MailConnectionMailbox, mailbox_id)
    if row is None or int(row.connection_id) != int(connection.id):
        raise em.MailError("not_found", "Mailbox not found.", 404)
    return row


async def add_mailbox(db: AsyncSession, user: User, settings: em.ExchangeSettings, smtp: str) -> MailConnectionMailbox:
    """Add a Full Access mailbox by hand, after reading its Inbox as the person's login."""
    if not (settings.allow_manual_mailboxes and settings.allow_full_access):
        raise em.MailError("manual_mailboxes_off", "Adding mailboxes by hand is turned off by your administrator.", 403)
    usable = await require_usable(db, user, settings)
    address = em.normalize_smtp(smtp)
    if not address:
        raise em.MailError("invalid_address", "Type the mailbox's email address, such as finance@corp.example.", 422)
    connection_id = int(usable.connection.id)
    rows = await em.list_mailboxes(db, connection_id)

    def present(value: str) -> bool:
        return any(row.smtp == value for row in rows)

    if present(address):
        raise em.MailError("already_added", "This mailbox is already on your list.", 409)
    if sum(1 for row in rows if row.kind == "full_access") >= settings.max_mailboxes:
        raise em.MailError(
            "too_many_mailboxes", f"You can have up to {settings.max_mailboxes} Full Access mailboxes.", 422
        )
    try:
        # Not a mailbox of the list yet: an access refusal is about the address typed, not a row to drop.
        found = await _ews(db, usable, lambda c: c.check_mailbox(address), item_kinds=("access_denied", "not_found"))
    except EwsError as error:
        raise _refusal_after(error) from error
    primary = em.normalize_smtp(found.smtp) or address
    if present(primary):
        raise em.MailError("already_added", "This mailbox is already on your list.", 409)
    row = MailConnectionMailbox(
        connection_id=connection_id,
        smtp=primary,
        display_name=found.display_name[:255] or None,
        kind="full_access",
        source="manual",
        enabled=True,
        notify=False,
        verified_at=_now(),
        created_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row


async def update_mailbox(
    db: AsyncSession,
    user: User,
    settings: em.ExchangeSettings,
    mailbox_id: int,
    *,
    enabled: bool | None,
    notify: bool | None,
) -> MailConnectionMailbox:
    """Switch a mailbox for the chat (``enabled``) or for the needs-action check (``notify``).

    The own mailbox cannot be turned off. Turning on a Full Access mailbox
    that dropped out (its access failed) reads its Inbox again first.
    """
    connection = await require_connection(db, user, settings)
    row = await _own_mailbox_row(db, connection, mailbox_id)
    if row.kind == "own" and enabled is False:
        raise em.MailError("own_mailbox", "Your own mailbox is always on.", 422)
    if enabled is True and row.kind == "full_access" and not row.enabled:
        if not settings.allow_full_access:
            raise _full_access_off()
        if row.last_error:
            await _recheck(db, user, settings, row)
        row.enabled = True  # type: ignore[assignment]
    elif enabled is False:
        row.enabled = False  # type: ignore[assignment]
    if notify is not None:
        row.notify = notify  # type: ignore[assignment]
    await db.flush()
    return row


async def _recheck(db: AsyncSession, user: User, settings: em.ExchangeSettings, row: MailConnectionMailbox) -> None:
    usable = await require_usable(db, user, settings)
    smtp = str(row.smtp)
    try:
        found = await _ews(db, usable, lambda c: c.check_mailbox(smtp), mailbox=smtp)
    except EwsError as error:
        raise _refusal_after(error) from error
    row.display_name = found.display_name[:255] or row.display_name  # type: ignore[assignment]
    row.verified_at = _now()  # type: ignore[assignment]
    row.last_error = None  # type: ignore[assignment]


async def remove_mailbox(db: AsyncSession, user: User, settings: em.ExchangeSettings, mailbox_id: int) -> str:
    """Take a Full Access mailbox off the list; returns its address. The own mailbox stays."""
    connection = await require_connection(db, user, settings)
    row = await _own_mailbox_row(db, connection, mailbox_id)
    if row.kind == "own":
        raise em.MailError("own_mailbox", "Your own mailbox cannot be removed. Disconnect instead.", 422)
    smtp = str(row.smtp)
    await db.delete(row)
    await db.flush()
    return smtp


async def rediscover(db: AsyncSession, user: User, settings: em.ExchangeSettings) -> SyncResult:
    """Ask Autodiscover again which mailboxes the login has Full Access to."""
    if not settings.allow_full_access:
        raise _full_access_off()
    usable = await require_usable(db, user, settings)
    try:
        listed = await _ews(db, usable, lambda c: c.discover_full_access())
    except EwsError as error:
        raise _refusal_after(error) from error
    return await sync_discovered(db, usable.connection, listed, settings)


# --- action items ---------------------------------------------------------------------------------------------------


async def list_action_items(
    db: AsyncSession, user_id: int, *, state: Literal["open", "all"], limit: int
) -> dict[str, Any]:
    query = select(MailActionItem).where(MailActionItem.user_id == user_id)
    if state == "open":
        query = query.where(MailActionItem.status.in_(OPEN_ACTION_STATUSES))
    limit = min(max(int(limit), 1), ACTION_LIST_MAX)
    rows = (
        (await db.execute(query.order_by(MailActionItem.created_at.desc(), MailActionItem.id.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return {"items": [action_item_out(row) for row in rows], "open_count": await open_action_count(db, user_id)}


async def mark_notified(db: AsyncSession, user_id: int, ids: Sequence[int]) -> int:
    """The toasts for these were shown: the person's own ``new`` items become ``notified``."""
    wanted = sorted({int(i) for i in ids})[:NOTIFIED_IDS_MAX]
    if not wanted:
        return 0
    result = await db.execute(
        update(MailActionItem)
        .where(MailActionItem.user_id == user_id, MailActionItem.id.in_(wanted), MailActionItem.status == "new")
        .values(status="notified", notified_at=_now())
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def own_action_item(db: AsyncSession, user_id: int, item_id: int) -> MailActionItem:
    item = await db.get(MailActionItem, item_id)
    # Someone else's item is "not found", never "forbidden".
    if item is None or int(item.user_id) != int(user_id):
        raise em.MailError("not_found", "That email is no longer in your list.", 404)
    return item


async def close_action_item(
    db: AsyncSession, user_id: int, item_id: int, status: Literal["dismissed", "done"]
) -> MailActionItem:
    item = await own_action_item(db, user_id, item_id)
    item.status = status  # type: ignore[assignment]
    item.closed_at = _now()  # type: ignore[assignment]
    await db.flush()
    return item


def _sender(item: MailActionItem) -> str:
    name = " ".join(str(item.sender_name or "").split())
    email = str(item.sender_email or "").strip()
    if name and email and name.lower() != email.lower():
        return f"{name} <{email}>"
    return name or email or "an unknown sender"


async def ask_prompt(db: AsyncSession, user: User, settings: em.ExchangeSettings, item_id: int) -> str:
    """The composer text that starts a chat about one email, with a ref the chat's mail tools resolve."""
    await require_eligible(db, user, settings)
    item = await own_action_item(db, int(user.id), item_id)
    if await em.usable_access(db, user, settings) is None:
        raise em.MailError("not_connected", "Connect your mailbox again on Connections to ask about this email.", 409)
    ref = await em.ref_for(db, int(user.id), str(item.mailbox_smtp), str(item.item_id))
    subject = " ".join(str(item.subject or "").split())[:ASK_SUBJECT_CHARS] or "(no subject)"
    return f'Help me with this email (ref {ref}): "{subject}" from {_sender(item)}.'


# --- drafts ---------------------------------------------------------------------------------------------------------


async def own_draft(db: AsyncSession, user_id: int, draft_id: int) -> MailDraft:
    draft = await db.get(MailDraft, draft_id)
    if draft is None or int(draft.user_id) != int(user_id):
        raise em.MailError("not_found", "Draft not found.", 404)
    return draft


def _draft_mailbox(usable: Usable, draft: MailDraft) -> str:
    """The draft's mailbox, when it is still one the person has connected and turned on."""
    smtp = em.normalize_smtp(draft.mailbox_smtp)
    if not usable.access.allows(smtp):
        raise em.MailError(
            "mailbox_not_allowed",
            f"This draft is in {smtp}, which is no longer one of your connected mailboxes. Open it in Outlook.",
            403,
        )
    return smtp


def _mark_gone(draft: MailDraft) -> None:
    draft.status = "discarded"  # type: ignore[assignment]
    draft.error = DRAFT_GONE  # type: ignore[assignment]


def _refresh_from(draft: MailDraft, live: DraftResult) -> None:
    draft.subject = (live.subject or "")[:500]  # type: ignore[assignment]
    draft.to_json = _addresses_json(live.to)  # type: ignore[assignment]
    draft.cc_json = _addresses_json(live.cc)  # type: ignore[assignment]
    draft.body_preview = preview_of(live.body_text)  # type: ignore[assignment]
    draft.change_key = live.change_key or None  # type: ignore[assignment]


async def read_draft(db: AsyncSession, user: User, settings: em.ExchangeSettings, draft_id: int) -> dict[str, Any]:
    """The draft as it is now in Exchange (``DraftLiveOut``), or the row (``DraftOut``) once it is not a draft.

    A draft gone from Drafts (sent or deleted in Outlook) is marked
    ``discarded`` and answered as a row.
    """
    await require_eligible(db, user, settings)
    draft = await own_draft(db, int(user.id), draft_id)
    if draft.status != "draft":
        return draft_out(draft)
    usable = await require_usable(db, user, settings)
    mailbox = _draft_mailbox(usable, draft)
    item_id = str(draft.item_id)
    try:
        live = await _ews(
            db, usable, lambda c: c.get_draft(mailbox, item_id), mailbox=mailbox, item_kinds=("not_found",)
        )
    except EwsError as error:
        if error.kind == "not_found":
            _mark_gone(draft)
            await db.flush()
            return draft_out(draft)
        raise _refusal_after(error) from error
    _refresh_from(draft, live)
    draft.error = None  # type: ignore[assignment]
    await db.flush()
    return {
        **draft_out(draft),
        "body_text": live.body_text,
        "change_key": live.change_key,
        "owa_url": live.owa_url or None,
        "can_send": settings.allow_send,
    }


@dataclass(frozen=True)
class SendOutcome:
    draft: MailDraft
    #: The refusal to answer with, when the send failed (the row already says so).
    error: em.MailError | None = None


async def send_draft(
    db: AsyncSession, user: User, settings: em.ExchangeSettings, draft_id: int, change_key: str
) -> SendOutcome:
    """Send the draft exactly as the person read it (``change_key``).

    ``conflict`` (it changed in Outlook since) is answered without touching
    the row: the dialog reads it again. A draft gone becomes ``discarded``.
    A failure that will likely pass by itself (password, network,
    throttling) leaves it a ``draft`` with the error, so it can be sent once
    that is fixed; any other failure marks it ``failed``.
    """
    await require_eligible(db, user, settings)
    draft = await own_draft(db, int(user.id), draft_id)
    if not settings.allow_send:
        raise em.MailError("send_off", "Sending from Alpharouter is turned off. Open the draft in Outlook.", 403)
    if draft.status != "draft":
        raise em.MailError("not_a_draft", "This draft was already sent or discarded.", 409)
    usable = await require_usable(db, user, settings)
    mailbox = _draft_mailbox(usable, draft)
    await _hit(
        f"mail:send:{int(user.id)}",
        limit=SENDS_PER_HOUR,
        window_s=3600,
        message=f"You can send up to {SENDS_PER_HOUR} emails an hour from Alpharouter. Try again later.",
    )
    item_id = str(draft.item_id)
    try:
        # A send refused for this mailbox (no Send As) says nothing about reading it: the mailbox stays.
        await _ews(
            db,
            usable,
            lambda c: c.send_draft(mailbox, item_id, change_key),
            mailbox=mailbox,
            item_kinds=("conflict", "not_found", "access_denied", "invalid"),
        )
    except EwsError as error:
        refusal = _refusal_after(error)
        if error.kind == "conflict":
            raise refusal from error
        if error.kind == "not_found":
            _mark_gone(draft)
        else:
            draft.error = refusal.message  # type: ignore[assignment]
            if error.kind not in _PASSING_KINDS:
                draft.status = "failed"  # type: ignore[assignment]
        await db.flush()
        return SendOutcome(draft=draft, error=refusal)
    draft.status = "sent"  # type: ignore[assignment]
    draft.sent_at = _now()  # type: ignore[assignment]
    draft.error = None  # type: ignore[assignment]
    draft.change_key = change_key  # type: ignore[assignment]
    await db.flush()
    return SendOutcome(draft=draft)


def sent_audit_detail(draft: MailDraft) -> dict[str, Any]:
    """Counts and the mailbox only: never the subject or the recipients' addresses."""
    return {
        "draft_id": int(draft.id),
        "mailbox": str(draft.mailbox_smtp),
        "kind": str(draft.kind),
        "to_count": len(_addresses(draft.to_json)),
        "cc_count": len(_addresses(draft.cc_json)),
    }


async def discard_draft(db: AsyncSession, user: User, settings: em.ExchangeSettings, draft_id: int) -> MailDraft:
    """Move the draft to Deleted Items and mark it ``discarded`` (a draft already gone is no error)."""
    await require_eligible(db, user, settings)
    draft = await own_draft(db, int(user.id), draft_id)
    if draft.status == "discarded":
        return draft
    if draft.status != "draft":
        raise em.MailError("not_a_draft", "This draft was already sent.", 409)
    usable = await require_usable(db, user, settings)
    mailbox = _draft_mailbox(usable, draft)
    item_id = str(draft.item_id)
    try:
        await _ews(db, usable, lambda c: c.delete_draft(mailbox, item_id), mailbox=mailbox, item_kinds=("not_found",))
    except EwsError as error:
        if error.kind != "not_found":
            raise _refusal_after(error) from error
    draft.status = "discarded"  # type: ignore[assignment]
    draft.error = None  # type: ignore[assignment]
    await db.flush()
    return draft


# --- admin: Test connection -----------------------------------------------------------------------------------------


def _step(key: str, label: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "ok": ok, "detail": detail}


def _test_failure(error: EwsError) -> str:
    if error.kind == "auth":
        return "Exchange did not accept the user name or password."
    return em.friendly_error(error)


async def run_test(settings: em.ExchangeSettings, *, login: str, password: str, email: str = "") -> dict[str, Any]:
    """Try the saved settings with a login typed on the admin page; nothing is stored.

    Steps in order - ``endpoint``, ``login``, ``mailbox``, ``match`` (only
    with ``email``), ``autodiscover`` - stopping at the first required one
    that fails. Autodiscover failing is a warning: ``ok`` stays true.
    """
    steps: list[dict[str, Any]] = []
    result: dict[str, Any] = {"ok": False, "steps": steps, "mailbox": None, "full_access": []}
    endpoint = settings.ews_endpoint()
    if not endpoint:
        steps.append(_step("endpoint", "EWS address", False, "Give the EWS address and save the settings first."))
        return result
    steps.append(_step("endpoint", "EWS address", True, endpoint))
    timeout = settings.timeout_s + 5
    client = em.make_client(em.ews_config(settings, login, password))
    try:
        try:
            found = await em.run_ews(client.whoami, timeout_s=timeout)
        except EwsError as error:
            steps.append(_step("login", "Sign in", False, _test_failure(error)))
            return result
        steps.append(_step("login", "Sign in", True, f"Exchange accepted {login}."))
        smtp = em.normalize_smtp(found.smtp)
        if not smtp:
            steps.append(_step("mailbox", "Mailbox", False, "Exchange did not say which mailbox this login opens."))
            return result
        result["mailbox"] = {"smtp": smtp, "display_name": found.display_name}
        name = f"{found.display_name} <{smtp}>" if found.display_name else smtp
        steps.append(_step("mailbox", "Mailbox", True, f"The login opens {name}."))
        if email and not await _match_step(client, steps, email, smtp, timeout):
            return result
        await _autodiscover_step(client, steps, result, timeout)
    finally:
        client.close()
    result["ok"] = True
    return result


async def _match_step(client: MailClient, steps: list[dict[str, Any]], email: str, smtp: str, timeout: int) -> bool:
    label = "Mailbox matches the email"
    wanted = em.normalize_smtp(email)
    if not wanted:
        steps.append(_step("match", label, False, "That is not an email address."))
        return False
    try:
        same = await em.run_ews(client.same_mailbox, wanted, timeout_s=timeout)
    except EwsError as error:
        steps.append(_step("match", label, False, _test_failure(error)))
        return False
    if not same:
        steps.append(_step("match", label, False, f"This login opens {smtp}, not the mailbox of {wanted}."))
        return False
    steps.append(_step("match", label, True, f"{wanted} is the login's own mailbox."))
    return True


async def _autodiscover_step(
    client: MailClient, steps: list[dict[str, Any]], result: dict[str, Any], timeout: int
) -> None:
    label = "Full Access mailboxes (Autodiscover)"
    try:
        listed = await em.run_ews(client.discover_full_access, timeout_s=timeout)
    except EwsError as error:
        steps.append(_step("autodiscover", label, False, f"{_test_failure(error)} (a warning: mail works without it)"))
        return
    boxes = [
        {"smtp": em.normalize_smtp(box.smtp), "display_name": box.display_name}
        for box in listed
        if em.normalize_smtp(box.smtp)
    ]
    result["full_access"] = boxes
    detail = (
        f"Autodiscover lists {len(boxes)} Full Access mailbox{'es' if len(boxes) != 1 else ''}."
        if boxes
        else "Autodiscover lists no Full Access mailboxes for this login (or is not reachable)."
    )
    steps.append(_step("autodiscover", label, True, detail))


async def check_test_rate(admin_id: int) -> None:
    await _hit(
        f"mail:admin-test:{int(admin_id)}",
        limit=TESTS_PER_WINDOW,
        window_s=TEST_WINDOW_S,
        message=f"Up to {TESTS_PER_WINDOW} tests in 15 minutes. Wait a little before testing again.",
    )


def example_login(user: User, settings: em.ExchangeSettings, defaults: em.DirectoryDefaults) -> str:
    """The login format applied to the reading admin's own account, with placeholders for what is not known.

    ``CORP\\s.karimi`` when the domain is known; ``DOMAIN\\s.karimi`` before
    it is; ``username`` stands in for a name that cannot be used.
    """
    own = em.login_for(user, settings, defaults)
    if own:
        return own
    name = str(user.username or "").strip().split("\\")[-1].split("@")[0]
    if not name or any(c.isspace() for c in name):
        name = "username"
    if settings.login_format == "netbios":
        return f"{settings.netbios_domain or defaults.netbios_domain or 'DOMAIN'}\\{name}"
    return f"{name}@{settings.upn_suffix or defaults.dns_domain or 'domain'}"


# --- admin: people and overview -------------------------------------------------------------------------------------


def _like(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def list_connections(
    db: AsyncSession, *, q: str = "", status: str = "", limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """The People tab: connections with their person, searched on name, username, email or mailbox."""
    mailboxes = (
        select(
            MailConnectionMailbox.connection_id.label("connection_id"),
            func.count().label("total"),
            func.sum(case((MailConnectionMailbox.kind == "full_access", 1), else_=0)).label("full_access"),
        )
        .group_by(MailConnectionMailbox.connection_id)
        .subquery()
    )
    conditions: list[Any] = []
    needle = " ".join((q or "").split())[:200]
    if needle:
        pattern = _like(needle)
        conditions.append(
            or_(
                func.lower(User.username).like(pattern, escape="\\"),
                func.lower(func.coalesce(User.display_name, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(User.email, "")).like(pattern, escape="\\"),
                func.lower(MailConnection.primary_smtp).like(pattern, escape="\\"),
            )
        )
    if status:
        conditions.append(MailConnection.status == status)
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(MailConnection)
                .join(User, User.id == MailConnection.user_id)
                .where(*conditions)
            )
        ).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            select(MailConnection, User, mailboxes.c.total, mailboxes.c.full_access)
            .join(User, User.id == MailConnection.user_id)
            .outerjoin(mailboxes, mailboxes.c.connection_id == MailConnection.id)
            .where(*conditions)
            .order_by(MailConnection.connected_at.desc(), MailConnection.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = []
    for connection, person, total_boxes, full_access in rows:
        items.append(
            {
                "id": int(connection.id),
                "user_id": int(person.id),
                "username": str(person.username),
                "display_name": str(person.display_name) if person.display_name else None,
                "email": str(person.email) if person.email else None,
                "login": str(connection.login),
                "status": str(connection.status),
                "primary_smtp": str(connection.primary_smtp),
                "mailbox_count": int(total_boxes or 0),
                "full_access_count": int(full_access or 0),
                "notify_enabled": bool(connection.notify_enabled),
                "last_ok_at": iso_utc(connection.last_ok_at),
                "last_checked_at": iso_utc(connection.last_checked_at),
                "last_error": str(connection.last_error) if connection.last_error else None,
                "connected_at": iso_utc(connection.connected_at),
            }
        )
    return {"items": items, "total": total}


async def overview(db: AsyncSession, settings: em.ExchangeSettings) -> dict[str, Any]:
    """The Overview tab's numbers. ``eligible_accounts`` ignores the access list (the page says so)."""
    since = _now() - datetime.timedelta(days=7)

    async def count(query: Any) -> int:
        return int((await db.execute(query)).scalar_one() or 0)

    eligible = await count(
        select(func.count())
        .select_from(User)
        .where(
            User.auth_provider == "ldap",
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            User.purged_at.is_(None),
            User.email.is_not(None),
            User.email != "",
        )
    )
    last_check = (await db.execute(select(func.max(MailConnection.last_checked_at)))).scalar_one_or_none()
    return {
        "counts": await em.connection_counts(db),
        "eligible_accounts": eligible,
        "action_items_7d": await count(
            select(func.count()).select_from(MailActionItem).where(MailActionItem.created_at >= since)
        ),
        "drafts_7d": await count(select(func.count()).select_from(MailDraft).where(MailDraft.created_at >= since)),
        "sent_7d": await count(
            select(func.count())
            .select_from(MailDraft)
            .where(and_(MailDraft.status == "sent", MailDraft.sent_at >= since))
        ),
        "last_check_at": iso_utc(last_check),
        "enabled": settings.enabled,
        "configured": settings.configured,
    }
