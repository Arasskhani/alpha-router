"""Support tickets: the emails - to the administrators' addresses, to an assignee, and to the person.

Every email is sent in the background after the request has committed, in a
session of its own, so a slow or broken SMTP server never holds up or fails
a ticket change: it is logged and the change stands. Call these functions
after the commit (they schedule and return at once; nothing to await).

What leaves by email is deliberately small: the number, the title, the
priority and category, who asked, a 500-character excerpt of the text and a
link. Never an image, never an internal note.

- New tickets, and optionally the person's replies, go to ``notify_emails``
  (the first address in To, the others in Cc) when the ticket's priority is
  at least ``notify_min_priority``.
- An assignment by someone else goes to the assignee, one email per person
  however many tickets a bulk assign gave them; the thread's event then says
  whether it was sent.
- The person hears about replies and status changes only when ``email_user``
  is on (off by default).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Coroutine, Sequence
from typing import Any, Literal

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.support_ticket import SupportTicket, SupportTicketMessage
from app.models.user import User
from app.services import smtp_service
from app.services.security_audit import log_security_event
from app.services.support_tickets import (
    PRIORITY_LABELS,
    PRIORITY_RANK,
    TicketSettings,
    display_name,
    load_settings,
    status_label,
)

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 500
_pending: set[asyncio.Task[Any]] = set()


def _schedule(work: Coroutine[Any, Any, None]) -> None:
    task = asyncio.get_running_loop().create_task(work)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def drain() -> None:
    """Wait for every email still being sent (tests, and a clean shutdown)."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


def _session():
    # Looked up when the email is sent, not at import, so tests can point it at their database.
    return AsyncSessionLocal()


def _base_url() -> str:
    return (get_settings().frontend_url or "").strip().rstrip("/")


def staff_link(ticket_id: int) -> str:
    return f"{_base_url()}/admin/tickets/list?ticket={ticket_id}"


def user_link(ticket_id: int) -> str:
    return f"{_base_url()}/app/support/{ticket_id}"


def excerpt(text: str | None) -> str:
    """The first 500 characters, on one paragraph's worth of lines; an ellipsis says when there was more."""
    clean = "\n".join(line.rstrip() for line in (text or "").strip().splitlines())
    return clean if len(clean) <= EXCERPT_CHARS else clean[:EXCERPT_CHARS].rstrip() + "…"


def _reporter(ticket: SupportTicket) -> str:
    who = f"{ticket.reporter_name} ({ticket.reporter_username})"
    return f"{who}, {ticket.reporter_department}" if ticket.reporter_department else who


def _ticket_lines(ticket: SupportTicket, text: str | None, link: str) -> list[str]:
    return [
        f"Ticket: #{ticket.number} {ticket.title}",
        f"Priority: {PRIORITY_LABELS.get(str(ticket.priority), ticket.priority)}",
        f"Category: {ticket.category}",
        f"From: {_reporter(ticket)}",
        "",
        excerpt(text),
        "",
        f"Open it: {link}",
    ]


async def _latest(db: Any, ticket_id: int, kinds: Sequence[str], *, first: bool = False) -> SupportTicketMessage | None:
    order = SupportTicketMessage.id.asc() if first else SupportTicketMessage.id.desc()
    return (
        (
            await db.execute(
                select(SupportTicketMessage)
                .where(SupportTicketMessage.ticket_id == ticket_id, SupportTicketMessage.kind.in_(kinds))
                .order_by(order)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def _send(db: Any, recipients: Sequence[str], subject: str, body: str) -> str | None:
    """Send one email; return why it failed, or None. Never raises."""
    first, *others = recipients
    try:
        await smtp_service.send_email(db, to_address=first, cc=list(others), subject=subject, body_text=body)
    except Exception as exc:  # noqa: BLE001 -- an email that cannot go out must never touch the ticket change
        logger.warning("A support ticket email could not be sent: %s", subject, exc_info=True)
        return str(exc) or exc.__class__.__name__
    return None


def _wanted(ticket: SupportTicket, settings: TicketSettings) -> bool:
    rank = PRIORITY_RANK.get(str(ticket.priority), 0)
    return bool(settings.notify_emails) and rank >= PRIORITY_RANK.get(settings.notify_min_priority, 0)


async def _send_to_admins(ticket_id: int, reply: bool) -> None:
    async with _session() as db:
        settings = await load_settings(db)
        if reply and not settings.notify_on_user_reply:
            return
        ticket = await db.get(SupportTicket, ticket_id)
        if ticket is None or not _wanted(ticket, settings):
            return
        message = await _latest(db, ticket_id, ("user",), first=not reply)
        if reply:
            subject = f"Reply on ticket #{ticket.number}: {ticket.title}"
            intro = f"{ticket.reporter_name} replied on a support ticket."
        else:
            label = PRIORITY_LABELS.get(str(ticket.priority), ticket.priority)
            subject = f"New ticket #{ticket.number} ({label}): {ticket.title}"
            intro = f"{ticket.reporter_name} opened a support ticket."
        lines = [intro, "", *_ticket_lines(ticket, message.body if message else "", staff_link(ticket_id))]
        await _send(db, settings.notify_emails, subject, "\n".join(lines))


def notify_new_ticket(ticket_id: int) -> None:
    """Tell the administrators' addresses about a new ticket (when its priority is high enough)."""
    _schedule(_send_to_admins(ticket_id, reply=False))


def notify_user_reply(ticket_id: int) -> None:
    """Tell the administrators' addresses that the person replied (when that is switched on)."""
    _schedule(_send_to_admins(ticket_id, reply=True))


# --- assignments ----------------------------------------------------------------------------------------------


def _assignment_email(tickets: list[tuple[SupportTicket, str | None]], assigned_by: str) -> tuple[str, str]:
    if len(tickets) == 1:
        ticket, text = tickets[0]
        subject = f"Ticket #{ticket.number} assigned to you: {ticket.title}"
        lines = [
            f"{assigned_by} assigned a support ticket to you.",
            "",
            *_ticket_lines(ticket, text, staff_link(int(ticket.id))),
        ]
        return subject, "\n".join(lines)
    lines = [f"{assigned_by} assigned {len(tickets)} support tickets to you.", ""]
    for ticket, text in tickets:
        lines += [*_ticket_lines(ticket, text, staff_link(int(ticket.id))), "", "---", ""]
    return f"{len(tickets)} tickets assigned to you", "\n".join(lines[:-3])


async def _record(event_ids: list[int], state: str, failure: dict[str, Any] | None) -> None:
    """Write how the email went into each event, in a session and commit of its own."""
    async with _session() as db:
        rows = (await db.execute(select(SupportTicketMessage).where(SupportTicketMessage.id.in_(event_ids)))).scalars()
        for row in rows.all():
            facts = json.loads(str(row.event_json or "{}"))
            facts["email"] = state
            row.event_json = json.dumps(facts, ensure_ascii=False)  # type: ignore[assignment]
        if failure is not None:
            actor = await db.get(User, failure.pop("actor_id")) if failure.get("actor_id") else None
            await log_security_event(
                db,
                actor=actor,
                actor_ip=None,
                action="ticket_assignment_email_failed",
                resource_type="tickets",
                resource_id=str(failure.get("assignee_id")),
                detail=failure,
            )
        await db.commit()


async def _send_assignment(assignee_id: int, events: list[tuple[int, dict[str, Any], int]]) -> None:
    event_ids = [event_id for event_id, _, _ in events]
    tickets: list[tuple[SupportTicket, str | None]] = []
    error: str | None = None
    async with _session() as db:
        assignee = await db.get(User, assignee_id)
        address = str(assignee.email or "").strip() if assignee is not None else ""
        for _, _, ticket_id in events if address else []:
            ticket = await db.get(SupportTicket, ticket_id)
            if ticket is not None:
                first = await _latest(db, ticket_id, ("user",), first=True)
                tickets.append((ticket, first.body if first else ""))
        if tickets:
            subject, body = _assignment_email(tickets, str(events[0][1].get("by") or "Someone"))
            error = await _send(db, [address], subject, body)
    if not address:
        # The address went away after the assignment: nothing was sent, and the thread says no email.
        await _record(event_ids, "off", None)
        return
    if not tickets:
        return
    failure = None
    if error is not None:
        failure = {
            "actor_id": events[0][1].get("by_id"),
            "assignee_id": assignee_id,
            "assignee": display_name(assignee) if assignee is not None else None,
            "tickets": [int(t.number) for t, _ in tickets],
            "error": error[:500],
        }
    await _record(event_ids, "failed" if error else "sent", failure)


async def _send_assignments(event_ids: list[int]) -> None:
    async with _session() as db:
        rows = (
            await db.execute(
                select(SupportTicketMessage).where(
                    SupportTicketMessage.id.in_(event_ids), SupportTicketMessage.kind == "event"
                )
            )
        ).scalars()
        by_assignee: dict[int, list[tuple[int, dict[str, Any], int]]] = {}
        for row in rows.all():
            try:
                facts = json.loads(str(row.event_json or "{}"))
            except ValueError:
                continue
            if facts.get("type") != "assigned" or facts.get("email") != "pending" or facts.get("to_id") is None:
                continue
            by_assignee.setdefault(int(facts["to_id"]), []).append((int(row.id), facts, int(row.ticket_id)))
    for assignee_id, events in by_assignee.items():
        try:
            await _send_assignment(assignee_id, events)
        except Exception:  # noqa: BLE001 -- one assignee's failure must not stop the others' emails
            logger.warning("Assignment emails for user %s could not be handled", assignee_id, exc_info=True)


def notify_assignees(event_ids: list[int]) -> None:
    """Email each assignee once about the tickets in these ``assigned`` events still marked ``pending``.

    Pass every ``AssignOutcome.event_id`` whose ``email_wanted`` is true, after
    the commit; a bulk assign passes them all at once and each person gets one
    email listing their tickets. Each event then reads ``sent`` or ``failed``
    (a failure is also written to Admin Logs).
    """
    ids = [int(i) for i in event_ids if i is not None]
    if ids:
        _schedule(_send_assignments(ids))


# --- the person -------------------------------------------------------------------------------------------------

UserMailKind = Literal["reply", "resolved", "status"]


async def _send_to_user(ticket_id: int, kind: UserMailKind) -> None:
    async with _session() as db:
        settings = await load_settings(db)
        if not settings.email_user:
            return
        ticket = await db.get(SupportTicket, ticket_id)
        if ticket is None:
            return
        owner = await db.get(User, ticket.user_id)
        address = str((owner.email if owner is not None else None) or ticket.reporter_email or "").strip()
        if not address:
            return
        link = user_link(ticket_id)
        heading = f"Your ticket #{ticket.number}: {ticket.title}"
        if kind == "reply":
            message = await _latest(db, ticket_id, ("staff", "auto"))
            subject = f"Support replied on your ticket #{ticket.number}"
            lines = [heading, "", excerpt(message.body if message else ""), "", f"Read and reply: {link}"]
        elif kind == "resolved":
            subject = f"Your ticket #{ticket.number} is resolved"
            lines = [
                heading,
                "",
                "Support marked it resolved.",
                f"If it still does not work, reply within {settings.reopen_days} days to reopen it.",
                "",
                f"Open it: {link}",
            ]
        else:
            label = status_label(str(ticket.status), "user")
            subject = f"Your ticket #{ticket.number} is now {label}"
            lines = [heading, "", f"Status: {label}", "", f"Open it: {link}"]
        await _send(db, [address], subject, "\n".join(lines))


def notify_user(ticket_id: int, kind: UserMailKind) -> None:
    """Email the person about a reply, a resolve or a status change - only when ``email_user`` is on.

    ``reply`` quotes the latest staff reply or automatic reply, never a note.
    """
    _schedule(_send_to_user(ticket_id, kind))
