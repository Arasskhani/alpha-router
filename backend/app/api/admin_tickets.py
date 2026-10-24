"""Admin › Tickets: the queue, a ticket, assignment, settings and deleting.

Every rule a ticket lives by is in ``app.services.support_tickets``; this
module checks who may ask, turns the request into those calls, commits with an
Admin Logs row, and only then schedules the emails (which never hold up or
fail a change).

- Reading (the queue, a ticket, the counts, the settings): Support, Super
  Admin and Read Only Super Admin (``require_tickets``).
- Working tickets (reply, note, status, priority, category, assign, bulk):
  someone who can work tickets - active, Support or Super Admin.
- Changing the settings and every delete: Super Admin only.

Admin Logs rows carry ticket numbers, counts and the fields that changed, never
a title, a message or a note.
"""

from __future__ import annotations

import base64
import csv
import datetime
import hashlib
import hmac
import io
import json
import re
import time
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_super_admin, require_tickets, require_tickets_write
from app.config import get_settings
from app.database import get_db
from app.models.support_ticket import SupportTicket, SupportTicketAttachment, SupportTicketMessage
from app.models.user import User
from app.services import support_ticket_mail as mail
from app.services import support_tickets as st
from app.services.client_ip import resolve_client_ip
from app.services.rbac import user_has_super_admin_access
from app.services.security_audit import log_security_event
from app.services.support_ticket_images import forget_ticket_images, store_ticket_images
from app.services.user_role_service import get_user_role_slugs

router = APIRouter(prefix="/api/admin/tickets", tags=["tickets"])

VIEWS = ("needs_staff", "mine", "unassigned", "active", "closed", "all")
PAGE_SIZE_MAX = 100
#: Far past any real queue; keeps the offset a number every database takes.
PAGE_MAX = 100_000
EXPORT_ROWS = 50_000
BULK_MAX = 200
#: Ticket ids one delete may name (the queue selects at most a page).
DELETE_IDS_MAX = 1000
#: Ticket numbers written into an Admin Logs row; the count is always exact.
AUDIT_NUMBERS_MAX = 1000
DELETE_BATCH = 200
DELETE_ALL_PHRASE = "DELETE ALL TICKETS"
TOKEN_TTL_SECONDS = 600
_TOKEN_CONTEXT = b"alpharouter.tickets.delete.v1"
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
#: (tests/test_read_only_super_admin_surface.py walks it). Settings and deletes take Super Admin on top
#: (never Read Only Super Admin, never Support).
WORK = [Depends(require_tickets_write)]
SUPER_ADMIN = [Depends(require_tickets_write), Depends(require_super_admin)]


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


async def _ticket(db: AsyncSession, ticket_id: int, *, lock: bool = False) -> SupportTicket:
    """The ticket, or 404. ``lock`` reads it afresh and locks the row (PostgreSQL) for a change that depends on
    its status, so the scheduled close and a person's reply cannot cross it."""
    if st.parse_id(ticket_id) is None:
        raise _refuse("not_found", "Ticket not found.", 404)
    ticket = await db.get(SupportTicket, ticket_id, with_for_update=lock or None, populate_existing=lock)
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
    user_id = st.parse_id(value)
    if user_id is None:
        raise _bad_filter("assignee must be a user id or none.")
    return SupportTicket.assignee_id == user_id


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
    page: int = Query(1, ge=1, le=PAGE_MAX),
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


@router.put("/settings", dependencies=SUPER_ADMIN)
async def put_ticket_settings(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    """Save the settings: what is sent is laid over what is saved, then checked as a whole."""
    current = (await st.load_settings(db)).as_dict()
    try:
        saved = st.validate_settings({**current, **body})
    except st.TicketError as exc:
        raise _answer(exc) from exc
    after = saved.as_dict()
    changed = [key for key in after if after[key] != current.get(key)]
    await st.save_settings(db, saved)
    detail: dict[str, Any] = {
        "changed": changed,
        "before": {k: current.get(k) for k in changed},
        "after": {k: after[k] for k in changed},
    }
    if saved.enabled and not current.get("enabled", True):
        # Back on: the auto-close was paused, and the people waited on could not answer meanwhile.
        detail["waiting_restarted"] = await st.restart_waiting_clocks(db)
    if changed:
        await _audit(db, request, actor, "tickets_settings_updated", st.SETTINGS_KEY, detail)
    await db.commit()
    return after


# --- bulk and deleting (fixed paths, before the ticket routes) ---------------------------------------------------


#: A row id in a request body: 1..2147483647, so a larger number is a 422, never a database error.
RowId = Annotated[int, Field(ge=1, le=st.MAX_ID)]


class BulkIn(BaseModel):
    ids: list[RowId] = Field(min_length=1, max_length=BULK_MAX)
    action: Literal["assign_to_me", "assign", "close"]
    assignee_id: RowId | None = None


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
        (
            await db.execute(
                select(SupportTicket)
                .where(SupportTicket.id.in_(set(body.ids)))
                .order_by(SupportTicket.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
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


class DeleteFilterIn(BaseModel):
    statuses: list[str] | None = None
    priority: str | None = None
    category: str | None = None
    department: str | None = None
    assignee: str | int | None = None
    before: str | None = None


class DeleteScopeIn(BaseModel):
    ids: list[RowId] | None = Field(None, max_length=DELETE_IDS_MAX)
    filter: DeleteFilterIn | None = None


class DeleteIn(DeleteScopeIn):
    token: str = ""
    phrase: str = ""


class DeleteAllIn(BaseModel):
    phrase: str = ""


def _normal_scope(body: DeleteScopeIn) -> dict[str, Any]:
    """The scope in one canonical form: what the token binds and what the recount uses."""
    if (body.ids is None) == (body.filter is None):
        raise _refuse("invalid_scope", "Send either the ticket ids or a filter.", 422)
    if body.ids is not None:
        ids = sorted({int(i) for i in body.ids})
        if not ids:
            raise _refuse("invalid_scope", "Name at least one ticket.", 422)
        return {"ids": ids}
    f = body.filter or DeleteFilterIn()
    out: dict[str, Any] = {"statuses": _statuses(f.statuses) or list(st.DONE_STATUSES)}
    if (p := _one_of(f.priority, st.PRIORITIES, "priority")) is not None:
        out["priority"] = p
    for key in ("category", "department"):
        value = (getattr(f, key) or "").strip()
        if value:
            out[key] = value
    assignee = str(f.assignee if f.assignee is not None else "").strip()
    if assignee:
        _assignee_condition(assignee)
        out["assignee"] = assignee
    if before := (f.before or "").strip():
        _before_condition(before)
        out["before"] = before
    return {"filter": out}


def _scope_conditions(scope: dict[str, Any]) -> list[Any]:
    if "ids" in scope:
        return [SupportTicket.id.in_(scope["ids"])]
    f = scope["filter"]
    conditions = [SupportTicket.status.in_(f["statuses"])]
    if "priority" in f:
        conditions.append(SupportTicket.priority == f["priority"])
    if "category" in f:
        conditions.append(SupportTicket.category == f["category"])
    if "department" in f:
        conditions.append(SupportTicket.reporter_department == f["department"])
    if "assignee" in f:
        conditions.append(_assignee_condition(f["assignee"]))
    if "before" in f:
        conditions.append(_before_condition(f["before"]))
    return conditions


async def _scope_count(db: AsyncSession, conditions: list[Any]) -> int:
    return int((await db.execute(select(func.count()).select_from(SupportTicket).where(*conditions))).scalar_one())


async def _scope_totals(db: AsyncSession, conditions: list[Any]) -> dict[str, Any]:
    ids = select(SupportTicket.id).where(*conditions).scalar_subquery()
    count = await _scope_count(db, conditions)
    active = await _scope_count(db, [*conditions, SupportTicket.status.in_(st.ACTIVE_STATUSES)])
    messages = (
        await db.execute(
            select(func.count())
            .select_from(SupportTicketMessage)
            .where(SupportTicketMessage.ticket_id.in_(ids), SupportTicketMessage.kind != "event")
        )
    ).scalar_one()
    images, image_bytes = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(SupportTicketAttachment.bytes), 0)).where(
                SupportTicketAttachment.ticket_id.in_(ids)
            )
        )
    ).one()
    return {
        "count": count,
        "messages": int(messages or 0),
        "images": int(images or 0),
        "image_bytes": int(image_bytes or 0),
        "includes_active": active > 0,
    }


def _phrase(count: int) -> str:
    return f"DELETE {count} TICKETS"


def _token_key() -> bytes:
    secret = (get_settings().secret_key or "").encode("utf-8")
    return hmac.new(secret, _TOKEN_CONTEXT, hashlib.sha256).digest()


def _scope_digest(scope: dict[str, Any]) -> str:
    canonical = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _epoch() -> int:
    return int(time.time())


def sign_delete_token(actor_id: int, scope: dict[str, Any], count: int, includes_active: bool = True) -> str:
    """A short-lived token binding who previewed, exactly what, how many tickets it was, and whether any was active."""
    payload = {
        "a": int(actor_id),
        "s": _scope_digest(scope),
        "c": int(count),
        "i": bool(includes_active),
        "e": _epoch() + TOKEN_TTL_SECONDS,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_token_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read_delete_token(token: str, actor_id: int, scope: dict[str, Any]) -> tuple[int, bool]:
    """The previewed count and whether it included active tickets, when the token is this actor's, for this
    scope, and not expired."""
    invalid = _refuse("token_invalid", "This confirmation has expired. Preview the delete again.", 400)
    try:
        body, signature = (token or "").strip().split(".", 1)
        expected = _b64(hmac.new(_token_key(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise ValueError("signature")
        payload = json.loads(_unb64(body))
        count = int(payload["c"])
        includes_active = bool(payload.get("i", True))
        if (
            int(payload["a"]) != int(actor_id)
            or not hmac.compare_digest(str(payload["s"]), _scope_digest(scope))
            or int(payload["e"]) < _epoch()
        ):
            raise ValueError("mismatch")
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise invalid from None
    return count, includes_active


async def _delete_in_batches(db: AsyncSession, ids: Sequence[int], where: Sequence[Any] = ()) -> dict[str, int]:
    """Delete these tickets in committed batches; each batch deletes only those still meeting ``where``."""
    totals = {"deleted": 0, "messages": 0, "images": 0, "image_bytes": 0}
    ordered = sorted(int(i) for i in ids)
    for start in range(0, len(ordered), DELETE_BATCH):
        counts = await st.delete_tickets(db, ordered[start : start + DELETE_BATCH], where=where)
        await db.commit()
        for key in totals:
            totals[key] += counts[key]
    return totals


async def _ids_and_numbers(db: AsyncSession, conditions: list[Any]) -> list[tuple[int, int]]:
    rows = await db.execute(select(SupportTicket.id, SupportTicket.number).where(*conditions))
    return [(int(i), int(n)) for i, n in rows.all()]


@router.post("/delete-preview", dependencies=SUPER_ADMIN)
async def delete_preview(
    body: DeleteScopeIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    """What a delete would remove, with the phrase to type and a token for ``/delete``."""
    scope = _normal_scope(body)
    totals = await _scope_totals(db, _scope_conditions(scope))
    return {
        **totals,
        "token": sign_delete_token(int(actor.id), scope, totals["count"], totals["includes_active"]),
        "phrase": _phrase(totals["count"]),
    }


@router.post("/delete", dependencies=SUPER_ADMIN)
async def delete_scope(
    body: DeleteIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    """Delete what was previewed: same actor, same scope, the typed phrase, and the same count now.

    The ids are taken once and counted against the confirmed number; each
    batch then deletes only the tickets still in the scope, so one that left
    it meanwhile (a reporter reopened it) stays, and the answer says how many
    really went.
    """
    scope = _normal_scope(body)
    previewed, previewed_active = read_delete_token(body.token, int(actor.id), scope)
    if body.phrase.strip() != _phrase(previewed):
        raise _refuse("phrase_mismatch", f'Type "{_phrase(previewed)}" to confirm.', 400)
    conditions = _scope_conditions(scope)
    if "ids" in scope and not previewed_active:
        # Selected tickets confirmed as all ended: one reopened since is no longer what was confirmed.
        conditions.append(SupportTicket.status.in_(st.DONE_STATUSES))
    rows = await _ids_and_numbers(db, conditions)
    if len(rows) != previewed:
        raise _refuse(
            "count_changed",
            f"The number of tickets changed from {previewed} to {len(rows)}. Check it again.",
            409,
            count=len(rows),
        )
    totals = await _scope_totals(db, conditions)
    # Written and committed before anything goes, so the trail outlives a delete that fails half way.
    await _audit(
        db,
        request,
        actor,
        "tickets_deleted",
        "selected" if "ids" in scope else "filter",
        {
            "scope": "ids" if "ids" in scope else "filter",
            **({"filter": scope["filter"]} if "filter" in scope else {}),
            "count": len(rows),
            "messages": totals["messages"],
            "images": totals["images"],
            "image_bytes": totals["image_bytes"],
            "includes_active": totals["includes_active"],
            **_numbers([n for _, n in rows]),
        },
    )
    await db.commit()
    done = await _delete_in_batches(db, [i for i, _ in rows], conditions)
    return {"deleted": done["deleted"], "messages": done["messages"], "images": done["images"]}


@router.post("/delete-all", dependencies=SUPER_ADMIN)
async def delete_all(
    body: DeleteAllIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    """Every ticket, after the typed phrase; recorded in Admin Logs before the delete."""
    if body.phrase.strip() != DELETE_ALL_PHRASE:
        raise _refuse("phrase_mismatch", f'Type "{DELETE_ALL_PHRASE}" to confirm.', 400)
    totals = await _scope_totals(db, [])
    rows = await _ids_and_numbers(db, [])
    await _audit(
        db,
        request,
        actor,
        "tickets_deleted_all",
        "all",
        {
            "count": totals["count"],
            "messages": totals["messages"],
            "images": totals["images"],
            "image_bytes": totals["image_bytes"],
            **_numbers([n for _, n in rows]),
        },
    )
    await db.commit()
    done = await _delete_in_batches(db, [i for i, _ in rows])
    return {"deleted": done["deleted"]}


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
    ticket = await _ticket(db, ticket_id, lock=True)
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
    try:
        # Refuse what the service would refuse before any image is decoded or stored.
        text = st.precheck_staff_message(body=body, status=new_status)
    except st.TicketError as exc:
        raise _answer(exc) from exc
    settings = await st.load_settings(db)
    try:
        # The person's images live under their own prefix, whoever attached them.
        stored = await store_ticket_images(images or [], settings, owner_user_id=int(ticket.user_id))
    except st.TicketError as exc:
        raise _answer(exc) from exc
    try:
        # Read again and locked: the ticket may have changed while the images were checked.
        await db.refresh(ticket, with_for_update=True)
        previous_status = str(ticket.status)
        await st.add_staff_message(
            db, ticket=ticket, staff=actor, body=text, internal=is_note, images=stored, status=new_status
        )
        detail: dict[str, Any] = {"number": ticket.number, "images": len(stored)}
        if ticket.status != previous_status:
            detail["status"] = {"from": previous_status, "to": ticket.status}
        await _audit(db, request, actor, "ticket_note_added" if is_note else "ticket_replied", ticket.id, detail)
        await db.commit()
    except st.TicketError as exc:
        await db.rollback()
        await forget_ticket_images(stored)
        raise _answer(exc) from exc
    except Exception:
        # Nothing kept the images: they leave storage again.
        await db.rollback()
        await forget_ticket_images(stored)
        raise
    if not is_note:
        mail.notify_user(int(ticket.id), "reply")
    elif ticket.status != previous_status:
        mail.notify_user(int(ticket.id), _user_mail_kind(str(ticket.status)))
    return await _detail(db, ticket, actor)


class AssignIn(BaseModel):
    assignee_id: RowId | None = None


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


@router.delete("/{ticket_id:int}", dependencies=SUPER_ADMIN)
async def delete_ticket(
    ticket_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    """One ticket with its messages and images; the Admin Logs row is written first, in the same commit."""
    ticket = await _ticket(db, ticket_id)
    totals = await _scope_totals(db, [SupportTicket.id == ticket.id])
    await _audit(
        db,
        request,
        actor,
        "ticket_deleted",
        ticket.id,
        {
            "number": ticket.number,
            "status": ticket.status,
            "messages": totals["messages"],
            "images": totals["images"],
            "image_bytes": totals["image_bytes"],
        },
    )
    await st.delete_tickets(db, [int(ticket.id)])
    await db.commit()
    return {"deleted": 1}
