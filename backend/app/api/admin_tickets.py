"""Admin › Tickets: the queue, a ticket, assignment, settings and deleting.

Every rule a ticket lives by is in ``app.services.support_tickets``; this
module checks who may ask, turns the request into those calls, commits with an
Admin Logs row, and only then schedules the emails (which never hold up or
fail a change).

- Reading (the queue, a ticket, the counts, the settings): Support, Super
  Admin and Read Only Super Admin (``require_tickets``).
- Working tickets (reply, note, status, priority, category, assign, bulk):
  someone who can work tickets - active, Support or Super Admin.

Admin Logs rows carry ticket numbers, counts and the fields that changed, never
a title, a message or a note.
"""

from __future__ import annotations

import csv
import datetime
import io
import re
from collections.abc import Sequence
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_tickets, require_tickets_write
from app.database import get_db
from app.models.support_ticket import SupportTicket, SupportTicketMessage
from app.models.user import User
from app.services import support_ticket_mail as mail
from app.services import support_tickets as st
from app.services.client_ip import resolve_client_ip
from app.services.rbac import user_has_super_admin_access
from app.services.security_audit import log_security_event
from app.services.support_ticket_images import store_ticket_images
from app.services.user_role_service import get_user_role_slugs

router = APIRouter(prefix="/api/admin/tickets", tags=["tickets"])

VIEWS = ("needs_staff", "mine", "unassigned", "active", "closed", "all")
PAGE_SIZE_MAX = 100
EXPORT_ROWS = 50_000
BULK_MAX = 200
#: Ticket numbers written into an Admin Logs row; the count is always exact.
AUDIT_NUMBERS_MAX = 1000
_SEARCH_MAX = 200
_NUMBER = re.compile(r"^#?\s*(\d{1,9})$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- answers and permissions ------------------------------------------------------------------------------------


def _refuse(code: str, message: str, status_code: int = 400, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def _answer(error: st.TicketError) -> HTTPException:
    return _refuse(error.code, error.message, error.status_code, **error.extra)


async def require_ticket_worker(
    user: User = Depends(require_tickets_write), db: AsyncSession = Depends(get_db)
) -> User:
    """May change tickets: writes the Tickets menu and can work tickets (active, not deleted)."""
    if not await st.can_work_tickets(db, user):
        raise HTTPException(status_code=403, detail="Only Support and Super Admins can work tickets.")
    return user


#: Guards written on the route itself, so the route table shows what protects each change
#: (tests/test_read_only_super_admin_surface.py walks it).
WORK = [Depends(require_tickets_write)]


async def _audit(db: AsyncSession, request: Request, actor: User, action: str, resource_id: Any, detail: dict) -> None:
    await log_security_event(
        db,
        actor=actor,
        actor_ip=resolve_client_ip(request),
        action=action,
        resource_type="tickets",
        resource_id=None if resource_id is None else str(resource_id),
        detail=detail,
    )


async def _ticket(db: AsyncSession, ticket_id: int) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise _refuse("not_found", "Ticket not found.", 404)
    return ticket


async def _detail(db: AsyncSession, ticket: SupportTicket, viewer: User) -> dict[str, Any]:
    return await st.ticket_detail(db, ticket, audience="staff", viewer=viewer)


def _numbers(values: Sequence[int]) -> dict[str, Any]:
    """Ticket numbers for an Admin Logs row: the first ``AUDIT_NUMBERS_MAX``, and how many were left out."""
    numbers = sorted(int(n) for n in values)
    out: dict[str, Any] = {"numbers": numbers[:AUDIT_NUMBERS_MAX]}
    if len(numbers) > AUDIT_NUMBERS_MAX:
        out["numbers_more"] = len(numbers) - AUDIT_NUMBERS_MAX
    return out


# --- filters ------------------------------------------------------------------------------------------------------


def _bad_filter(message: str) -> HTTPException:
    return _refuse("invalid_filter", message, 422)


def _one_of(value: str | None, allowed: Sequence[str], name: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if value not in allowed:
        raise _bad_filter(f"{name} must be one of {', '.join(allowed)}.")
    return value


def _assignee_condition(raw: str | int | None) -> Any | None:
    value = str(raw if raw is not None else "").strip()
    if not value:
        return None
    if value == "none":
        return SupportTicket.assignee_id.is_(None)
    if not value.isdigit():
        raise _bad_filter("assignee must be a user id or none.")
    return SupportTicket.assignee_id == int(value)


def _before_condition(raw: str | None) -> Any | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        if not _DAY.match(value):
            raise ValueError(value)
        day = datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise _bad_filter("before must be a date as YYYY-MM-DD.") from None
    return SupportTicket.updated_at < day


def _like(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _search_condition(raw: str | None) -> Any | None:
    text = " ".join((raw or "").split())[:_SEARCH_MAX]
    if not text:
        return None
    needle = _like(text)
    in_messages = exists().where(
        SupportTicketMessage.ticket_id == SupportTicket.id,
        SupportTicketMessage.kind != "event",
        func.lower(SupportTicketMessage.body).like(needle, escape="\\"),
    )
    options = [
        func.lower(SupportTicket.title).like(needle, escape="\\"),
        func.lower(SupportTicket.reporter_name).like(needle, escape="\\"),
        func.lower(SupportTicket.reporter_username).like(needle, escape="\\"),
        in_messages,
    ]
    number = _NUMBER.match(text)
    if number:
        options.append(SupportTicket.number == int(number.group(1)))
    return or_(*options)


def _view_condition(view: str, viewer_id: int) -> Any | None:
    active = SupportTicket.status.in_(st.ACTIVE_STATUSES)
    if view == "needs_staff":
        return and_(active, SupportTicket.needs_staff.is_(True))
    if view == "mine":
        return and_(active, SupportTicket.assignee_id == viewer_id)
    if view == "unassigned":
        return and_(active, SupportTicket.assignee_id.is_(None))
    if view == "active":
        return active
    if view == "closed":
        return SupportTicket.status.in_(st.DONE_STATUSES)
    return None


def _statuses(raw: str | Sequence[str] | None) -> list[str]:
    values = raw.split(",") if isinstance(raw, str) else list(raw or [])
    out: list[str] = []
    for value in values:
        status = str(value).strip()
        if not status:
            continue
        if status not in st.STATUSES:
            raise _bad_filter(f"status must be one of {', '.join(st.STATUSES)}.")
        if status not in out:
            out.append(status)
    return sorted(out, key=st.STATUSES.index)


def _queue_conditions(
    viewer: User,
    *,
    view: str,
    q: str | None,
    priority: str | None,
    category: str | None,
    department: str | None,
    assignee: str | None,
    status: str | None,
    statuses: str | None = None,
    before: str | None = None,
) -> tuple[str, list[Any]]:
    chosen = _one_of(view, VIEWS, "view") or "active"
    conditions = [
        _view_condition(chosen, int(viewer.id)),
        _search_condition(q),
        _assignee_condition(assignee),
        _before_condition(before),
    ]
    if (p := _one_of(priority, st.PRIORITIES, "priority")) is not None:
        conditions.append(SupportTicket.priority == p)
    if (s := _one_of(status, st.STATUSES, "status")) is not None:
        conditions.append(SupportTicket.status == s)
    if listed := _statuses(statuses):
        conditions.append(SupportTicket.status.in_(listed))
    if wanted_category := (category or "").strip():
        conditions.append(SupportTicket.category == wanted_category)
    if wanted_department := (department or "").strip():
        conditions.append(SupportTicket.reporter_department == wanted_department)
    return chosen, [c for c in conditions if c is not None]


def _ordered(query: Select, view: str) -> Select:
    if view == "needs_staff":
        # Urgent first, then whoever has waited longest.
        urgent_first = case((SupportTicket.priority == "urgent", 0), else_=1)
        return query.order_by(urgent_first, SupportTicket.updated_at.asc(), SupportTicket.id.asc())
    return query.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())


# --- reading ------------------------------------------------------------------------------------------------------


def _assignee_json(staff: st.Staff, viewer_id: int) -> dict[str, Any]:
    return {
        "id": staff.id,
        "name": staff.name,
        "username": staff.username,
        "role_label": staff.role_label,
        "open_count": staff.open_count,
        "is_me": staff.id == viewer_id,
    }


async def _assignees(db: AsyncSession, viewer: User) -> list[dict[str, Any]]:
    return [_assignee_json(s, int(viewer.id)) for s in await st.assignable_staff(db)]


@router.get("/meta")
async def meta(db: AsyncSession = Depends(get_db), viewer: User = Depends(require_tickets)):
    settings = await st.load_settings(db)
    departments = (
        (
            await db.execute(
                select(SupportTicket.reporter_department)
                .where(SupportTicket.reporter_department.is_not(None), SupportTicket.reporter_department != "")
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    slugs = await get_user_role_slugs(db, int(viewer.id))
    return {
        "categories": list(settings.categories),
        "priorities": list(st.PRIORITIES),
        "statuses": list(st.STATUSES),
        "departments": sorted({str(d) for d in departments}, key=str.casefold),
        "assignees": await _assignees(db, viewer),
        "me": {
            "id": int(viewer.id),
            "can_write": await st.can_work_tickets(db, viewer),
            "is_super_admin": user_has_super_admin_access(slugs),
        },
        "settings": {
            "auto_close_days": settings.auto_close_days,
            "reopen_days": settings.reopen_days,
            "enabled": settings.enabled,
        },
    }


@router.get("/counts")
async def counts(db: AsyncSession = Depends(get_db), viewer: User = Depends(require_tickets)):
    return await st.staff_counts(db, int(viewer.id))


@router.get("/assignees")
async def assignees(db: AsyncSession = Depends(get_db), viewer: User = Depends(require_tickets)):
    return await _assignees(db, viewer)


@router.get("")
async def list_tickets(
    view: str = "active",
    q: str | None = Query(None, max_length=500),
    priority: str | None = None,
    category: str | None = None,
    department: str | None = None,
    assignee: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=PAGE_SIZE_MAX),
    db: AsyncSession = Depends(get_db),
    viewer: User = Depends(require_tickets),
):
    chosen, conditions = _queue_conditions(
        viewer,
        view=view,
        q=q,
        priority=priority,
        category=category,
        department=department,
        assignee=assignee,
        status=status,
    )
    total = int(
        (await db.execute(select(func.count()).select_from(SupportTicket).where(*conditions))).scalar_one() or 0
    )
    rows = (
        (
            await db.execute(
                _ordered(select(SupportTicket).where(*conditions), chosen)
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        )
        .scalars()
        .all()
    )
    settings = await st.load_settings(db)
    message_counts = await st.message_counts(db, [int(t.id) for t in rows], audience="staff")
    names = await st.assignee_names(db, rows)
    items = [
        st.ticket_summary(
            t, audience="staff", counts=message_counts.get(int(t.id)), settings=settings, assignee_names=names
        )
        for t in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # A cell a spreadsheet would run as a formula is written as text.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


_CSV_HEADER = (
    "number",
    "title",
    "reporter",
    "username",
    "department",
    "category",
    "priority",
    "status",
    "assignee",
    "created",
    "updated",
    "first reply",
    "resolved",
    "closed",
    "closed reason",
)


@router.get("/export.csv")
async def export_csv(
    request: Request,
    view: str = "active",
    q: str | None = Query(None, max_length=500),
    priority: str | None = None,
    category: str | None = None,
    department: str | None = None,
    assignee: str | None = None,
    status: str | None = None,
    statuses: str | None = None,
    before: str | None = None,
    db: AsyncSession = Depends(get_db),
    viewer: User = Depends(require_tickets),
):
    """The tickets the list shows (no message text), up to ``EXPORT_ROWS``."""
    chosen, conditions = _queue_conditions(
        viewer,
        view=view,
        q=q,
        priority=priority,
        category=category,
        department=department,
        assignee=assignee,
        status=status,
        statuses=statuses,
        before=before,
    )
    rows = (
        (await db.execute(_ordered(select(SupportTicket).where(*conditions), chosen).limit(EXPORT_ROWS)))
        .scalars()
        .all()
    )
    names = await st.assignee_names(db, rows)
    filters = {
        "view": chosen,
        "q": bool((q or "").strip()),
        "priority": priority or None,
        "category": category or None,
        "department": department or None,
        "assignee": assignee or None,
        "status": status or None,
        "statuses": statuses or None,
        "before": before or None,
    }
    await _audit(
        db,
        request,
        viewer,
        "tickets_exported",
        "export",
        {"filter": {k: v for k, v in filters.items() if v}, "rows": len(rows)},
    )
    await db.commit()
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)
    for t in rows:
        assignee_name = names.get(int(t.assignee_id), "") if t.assignee_id is not None else ""
        writer.writerow(
            [
                _csv_cell(v)
                for v in (
                    t.number,
                    t.title,
                    t.reporter_name,
                    t.reporter_username,
                    t.reporter_department or "",
                    t.category,
                    st.PRIORITY_LABELS.get(str(t.priority), t.priority),
                    st.status_label(str(t.status), "staff"),
                    assignee_name,
                    st.iso_utc(t.created_at),
                    st.iso_utc(t.updated_at),
                    st.iso_utc(t.first_staff_reply_at),
                    st.iso_utc(t.resolved_at),
                    st.iso_utc(t.closed_at),
                    t.closed_reason or "",
                )
            ]
        )
    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tickets-{stamp}.csv"'},
    )


# --- settings -----------------------------------------------------------------------------------------------------


@router.get("/settings")
async def get_ticket_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_tickets)):
    return (await st.load_settings(db)).as_dict()


# --- bulk (a fixed path, before the ticket routes) --------------------------------------------------------------


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=BULK_MAX)
    action: Literal["assign_to_me", "assign", "close"]
    assignee_id: int | None = None


async def _assignee_user(db: AsyncSession, assignee_id: int) -> User:
    person = await db.get(User, assignee_id)
    if person is None:
        raise _refuse("not_assignable", "That person cannot work tickets.", 422)
    return person


@router.post("/bulk", dependencies=WORK)
async def bulk(
    body: BulkIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_ticket_worker),
):
    """Assign to me, assign to someone (one email for all of them), or close the selected tickets."""
    if body.action == "assign" and body.assignee_id is None:
        raise _refuse("assignee_required", "Choose who gets the tickets.", 422)
    assignee: User | None = None
    if body.action == "assign_to_me":
        assignee = actor
    elif body.action == "assign" and body.assignee_id is not None:
        assignee = await _assignee_user(db, body.assignee_id)
    tickets = (
        (await db.execute(select(SupportTicket).where(SupportTicket.id.in_(set(body.ids))).order_by(SupportTicket.id)))
        .scalars()
        .all()
    )
    settings = await st.load_settings(db)
    changed: list[SupportTicket] = []
    email_events: list[int] = []
    try:
        for ticket in tickets:
            if body.action == "close":
                if ticket.status == "closed":
                    continue
                await st.set_status(db, ticket=ticket, actor=actor, status="closed")
                changed.append(ticket)
                continue
            outcome = await st.assign(db, ticket=ticket, actor=actor, assignee=assignee, settings=settings)
            if outcome.changed:
                changed.append(ticket)
                if outcome.email_wanted and outcome.event_id is not None:
                    email_events.append(outcome.event_id)
    except st.TicketError as exc:
        await db.rollback()
        raise _answer(exc) from exc
    if changed:
        detail: dict[str, Any] = {
            "action": body.action,
            "updated": len(changed),
            **_numbers([t.number for t in changed]),
        }
        if assignee is not None:
            detail["assignee_id"] = int(assignee.id)
            detail["emails"] = len(email_events)
        await _audit(db, request, actor, f"tickets_bulk_{body.action}", None, detail)
    await db.commit()
    if email_events:
        mail.notify_assignees(email_events)
    if body.action == "close":
        for ticket in changed:
            mail.notify_user(int(ticket.id), "status")
    return {"updated": len(changed)}


# --- one ticket ---------------------------------------------------------------------------------------------------


@router.get("/{ticket_id:int}")
async def get_ticket(ticket_id: int, db: AsyncSession = Depends(get_db), viewer: User = Depends(require_tickets)):
    return await _detail(db, await _ticket(db, ticket_id), viewer)


class TicketPatch(BaseModel):
    status: str | None = None
    priority: str | None = None
    category: str | None = None


def _user_mail_kind(status: str) -> mail.UserMailKind:
    return "resolved" if status == "resolved" else "status"


@router.patch("/{ticket_id:int}", dependencies=WORK)
async def patch_ticket(
    ticket_id: int,
    body: TicketPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_ticket_worker),
):
    """Change the status, priority or category; each change is an event line and an Admin Logs entry."""
    ticket = await _ticket(db, ticket_id)
    before = {"status": ticket.status, "priority": ticket.priority, "category": ticket.category}
    try:
        if body.status is not None:
            await st.set_status(db, ticket=ticket, actor=actor, status=body.status)
        if body.priority is not None:
            await st.set_priority(db, ticket=ticket, actor=actor, priority=body.priority)
        if body.category is not None:
            await st.set_category(db, ticket=ticket, actor=actor, category=body.category)
    except st.TicketError as exc:
        await db.rollback()
        raise _answer(exc) from exc
    after = {"status": ticket.status, "priority": ticket.priority, "category": ticket.category}
    changes = {k: {"from": before[k], "to": after[k]} for k in after if after[k] != before[k]}
    if changes:
        await _audit(db, request, actor, "ticket_updated", ticket.id, {"number": ticket.number, "changes": changes})
    await db.commit()
    if "status" in changes:
        mail.notify_user(int(ticket.id), _user_mail_kind(str(ticket.status)))
    return await _detail(db, ticket, actor)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "1", "yes", "on")


@router.post("/{ticket_id:int}/messages", dependencies=WORK)
async def add_message(
    ticket_id: int,
    request: Request,
    body: str = Form(""),
    internal: str = Form("false"),
    status: str | None = Form(None),
    images: list[UploadFile] | None = File(None),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_ticket_worker),
):
    """A reply the person sees, or an internal note, with images and an optional status change."""
    ticket = await _ticket(db, ticket_id)
    is_note = _truthy(internal)
    new_status = (status or "").strip() or None
    text = (body or "").strip()
    # Refuse what the service would refuse before any image is stored.
    if not text:
        raise _refuse("invalid_body", "The body cannot be empty.", 422)
    if len(text) > st.BODY_MAX:
        raise _refuse("invalid_body", f"The body can be up to {st.BODY_MAX} characters.", 422)
    if new_status is not None and new_status not in st.STATUSES:
        raise _refuse("invalid_status", f"Status must be one of {', '.join(st.STATUSES)}.", 422)
    previous_status = str(ticket.status)
    settings = await st.load_settings(db)
    try:
        # The person's images live under their own prefix, whoever attached them.
        stored = await store_ticket_images(images or [], settings, owner_user_id=int(ticket.user_id))
        await st.add_staff_message(
            db, ticket=ticket, staff=actor, body=text, internal=is_note, images=stored, status=new_status
        )
    except st.TicketError as exc:
        await db.rollback()
        raise _answer(exc) from exc
    detail: dict[str, Any] = {"number": ticket.number, "images": len(stored)}
    if ticket.status != previous_status:
        detail["status"] = {"from": previous_status, "to": ticket.status}
    await _audit(db, request, actor, "ticket_note_added" if is_note else "ticket_replied", ticket.id, detail)
    await db.commit()
    if not is_note:
        mail.notify_user(int(ticket.id), "reply")
    elif ticket.status != previous_status:
        mail.notify_user(int(ticket.id), _user_mail_kind(str(ticket.status)))
    return await _detail(db, ticket, actor)


class AssignIn(BaseModel):
    assignee_id: int | None = None


async def _assign(
    db: AsyncSession, request: Request, actor: User, ticket: SupportTicket, assignee: User | None
) -> dict[str, Any]:
    previous = int(ticket.assignee_id) if ticket.assignee_id is not None else None
    try:
        outcome = await st.assign(db, ticket=ticket, actor=actor, assignee=assignee)
    except st.TicketError as exc:
        await db.rollback()
        raise _answer(exc) from exc
    if outcome.changed:
        action = "ticket_unassigned" if assignee is None else "ticket_assigned"
        detail: dict[str, Any] = {"number": ticket.number, "from_id": previous}
        if assignee is not None:
            detail["to_id"] = int(assignee.id)
            detail["email"] = outcome.email_wanted
        await _audit(db, request, actor, action, ticket.id, detail)
    await db.commit()
    if outcome.email_wanted and outcome.event_id is not None:
        mail.notify_assignees([outcome.event_id])
    return await _detail(db, ticket, actor)


@router.post("/{ticket_id:int}/assign", dependencies=WORK)
async def assign_ticket(
    ticket_id: int,
    body: AssignIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_ticket_worker),
):
    """Give the ticket to someone who works tickets (they get an email unless it is you), or to nobody."""
    ticket = await _ticket(db, ticket_id)
    assignee = await _assignee_user(db, body.assignee_id) if body.assignee_id is not None else None
    return await _assign(db, request, actor, ticket, assignee)


@router.post("/{ticket_id:int}/assign-to-me", dependencies=WORK)
async def assign_to_me(
    ticket_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_ticket_worker),
):
    """Take the ticket; never an email."""
    return await _assign(db, request, actor, await _ticket(db, ticket_id), actor)
