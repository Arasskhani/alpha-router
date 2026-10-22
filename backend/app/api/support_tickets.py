"""The person's own tickets (Support): list, open, answer, resolve, and their images.

Every rule lives in ``app.services.support_tickets``; this module checks who
is asking, turns the form into the service's arguments, and answers each
refusal as ``{"detail": {"code", "message", ...}}`` so the page can say what
went wrong. Images are checked and stored before any row is written (all or
nothing), and removed again when the change is refused after all. Emails go
out after the commit and never hold up the answer.

When the administrator turns Support off, everything here answers 403
``tickets_disabled`` except ``/status`` (which says so) and ``/unread`` (a
badge that reads 0). A disabled account still reads its tickets; it cannot
write.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import application_version
from app.database import get_db
from app.models.support_ticket import SupportTicket, SupportTicketAttachment, SupportTicketMessage
from app.models.user import User
from app.services import object_storage_service, support_ticket_mail
from app.services import support_tickets as st
from app.services.rbac import user_can_access_menu, user_is_admin_panel
from app.services.support_ticket_images import read_ticket_image, store_ticket_images
from app.services.user_role_service import get_user_role_slugs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/support", tags=["tickets"])

#: The newest this many tickets are listed; a person never gets near it within the retention period.
LIST_LIMIT = 500
SEARCH_MAX = 200
#: The ``context`` form field is a small JSON object (three values of up to 200 characters).
CONTEXT_FIELD_MAX = 4000
_NUMBER = re.compile(r"#?\s*(\d{1,9})")


def _refuse(code: str, message: str, status_code: int, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def _answer(error: st.TicketError) -> NoReturn:
    raise _refuse(error.code, error.message, error.status_code, **error.extra) from error


def _disabled() -> HTTPException:
    return _refuse("tickets_disabled", "Support is turned off by your administrator.", 403)


def _not_found() -> HTTPException:
    return _refuse("not_found", "Ticket not found.", 404)


async def enabled_settings(db: AsyncSession = Depends(get_db)) -> st.TicketSettings:
    """The settings, or 403 ``tickets_disabled`` while Support is off."""
    settings = await st.load_settings(db)
    if not settings.enabled:
        raise _disabled()
    return settings


def _require_active(user: User) -> None:
    if not user.is_active:
        raise _refuse("account_inactive", "A disabled account can read its tickets but cannot change them.", 403)


def _reporter(user: User) -> dict[str, Any]:
    return {
        "name": st.display_name(user),
        "username": str(user.username),
        "email": str(user.email) if user.email else None,
        "department": (str(user.department).strip() or None) if user.department else None,
    }


async def _own_ticket(db: AsyncSession, ticket_id: int, user: User) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id)
    # Someone else's ticket is "not found", never "forbidden": its existence is not theirs to learn.
    if ticket is None or int(ticket.user_id) != int(user.id):
        raise _not_found()
    return ticket


async def _detail(db: AsyncSession, ticket: SupportTicket, user: User) -> dict[str, Any]:
    return await st.ticket_detail(db, ticket, audience="user", viewer=user)


async def _forget_images(images: Sequence[st.StoredImage]) -> None:
    """Remove stored images whose message was refused after all; a leftover is logged, never raised."""
    for image in images:
        try:
            await asyncio.to_thread(object_storage_service.delete_object, image.storage_key)
        except Exception:  # noqa: BLE001 -- the refusal is the answer; a stray object is only logged
            logger.warning("A refused ticket image could not be removed: %s", image.storage_key, exc_info=True)


async def _store(uploads: list[UploadFile] | None, settings: st.TicketSettings, user: User) -> list[st.StoredImage]:
    if not uploads:
        return []
    try:
        return await store_ticket_images(uploads, settings, owner_user_id=int(user.id))
    except st.TicketError as error:
        _answer(error)


def _context(raw: str | None) -> dict[str, Any] | None:
    """The optional technical details, with the running version filled in when the browser could not know it."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text) if len(text) <= CONTEXT_FIELD_MAX else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise _refuse("invalid_context", "The technical details could not be read.", 422)
    if not str(data.get("app_version") or "").strip():
        data["app_version"] = application_version()
    return data


# --- reading ------------------------------------------------------------------------------------------------------


@router.get("/status")
async def support_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Whether Support is on, and what the new-ticket form offers."""
    settings = await st.load_settings(db)
    return {
        "enabled": settings.enabled,
        "unread": await st.user_unread_count(db, int(user.id)) if settings.enabled else 0,
        "categories": list(settings.categories),
        "priorities": list(st.PRIORITIES),
        "limits": {
            "image_types": list(settings.image_types),
            "max_image_mb": settings.max_image_mb,
            "max_images": settings.max_images,
            "max_side_px": settings.max_side_px,
        },
        "reopen_days": settings.reopen_days,
        "auto_close_days": settings.auto_close_days,
        "reporter": _reporter(user),
    }


@router.get("/unread")
async def support_unread(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """The Support badge: tickets with something new the person has not opened (0 while Support is off)."""
    settings = await st.load_settings(db)
    return {"count": await st.user_unread_count(db, int(user.id)) if settings.enabled else 0}


def _search(q: str) -> Any | None:
    needle = " ".join(q.split())[:SEARCH_MAX]
    if not needle:
        return None
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    in_messages = exists().where(
        SupportTicketMessage.ticket_id == SupportTicket.id,
        SupportTicketMessage.kind == "user",
        SupportTicketMessage.body.ilike(pattern, escape="\\"),
    )
    conditions = [SupportTicket.title.ilike(pattern, escape="\\"), in_messages]
    number = _NUMBER.fullmatch(needle)
    if number:
        conditions.append(SupportTicket.number == int(number.group(1)))
    return or_(*conditions)


@router.get("/tickets")
async def list_tickets(
    state: Literal["open", "resolved", "all"] = Query("open"),
    q: str = Query("", max_length=1000),
    user: User = Depends(get_current_user),
    settings: st.TicketSettings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The person's tickets, newest activity first, with how many each filter holds (for the same search)."""
    scope: list[Any] = [SupportTicket.user_id == user.id]
    search = _search(q)
    if search is not None:
        scope.append(search)
    active = SupportTicket.status.in_(st.ACTIVE_STATUSES)
    done = SupportTicket.status.in_(st.DONE_STATUSES)
    open_count, resolved_count, all_count = (
        await db.execute(
            select(
                func.coalesce(func.sum(case((active, 1), else_=0)), 0),
                func.coalesce(func.sum(case((done, 1), else_=0)), 0),
                func.count(),
            )
            .select_from(SupportTicket)
            .where(*scope)
        )
    ).one()
    query = select(SupportTicket).where(*scope)
    if state == "open":
        query = query.where(active)
    elif state == "resolved":
        query = query.where(done)
    tickets = (
        (await db.execute(query.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).limit(LIST_LIMIT)))
        .scalars()
        .all()
    )
    counts = await st.message_counts(db, [int(t.id) for t in tickets], audience="user")
    return {
        "items": [
            st.ticket_summary(t, audience="user", counts=counts.get(int(t.id)), settings=settings) for t in tickets
        ],
        "counts": {"open": int(open_count or 0), "resolved": int(resolved_count or 0), "all": int(all_count or 0)},
    }


@router.get("/tickets/{ticket_id:int}")
async def get_ticket(
    ticket_id: int,
    user: User = Depends(get_current_user),
    _settings: st.TicketSettings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """One ticket and its conversation; opening it clears its badge."""
    ticket = await _own_ticket(db, ticket_id, user)
    if ticket.user_unread:
        ticket.user_unread = False  # type: ignore[assignment]
        await db.commit()
    return await _detail(db, ticket, user)


# --- writing ------------------------------------------------------------------------------------------------------


@router.post("/tickets", status_code=201)
async def create_ticket(
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form(""),
    priority: str = Form("normal"),
    context: str | None = Form(None),
    images: list[UploadFile] | None = File(None),
    user: User = Depends(get_current_user),
    settings: st.TicketSettings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Open a ticket: the first message, its screenshots and, when it is on, the automatic reply."""
    _require_active(user)
    details = _context(context)
    stored = await _store(images, settings, user)
    try:
        ticket = await st.create_ticket(
            db,
            user=user,
            title=title,
            description=description,
            category=category.strip(),
            priority=priority.strip(),
            context=details,
            images=stored,
            settings=settings,
        )
        await db.commit()
    except st.TicketError as error:
        await db.rollback()
        await _forget_images(stored)
        _answer(error)
    except Exception:
        await db.rollback()
        await _forget_images(stored)
        raise
    support_ticket_mail.notify_new_ticket(int(ticket.id))
    return await _detail(db, ticket, user)


@router.post("/tickets/{ticket_id:int}/messages")
async def reply(
    ticket_id: int,
    body: str = Form(""),
    images: list[UploadFile] | None = File(None),
    user: User = Depends(get_current_user),
    settings: st.TicketSettings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The person answers; a resolved or closed ticket reopens while the reopen window lasts."""
    ticket = await _own_ticket(db, ticket_id, user)
    _require_active(user)
    stored = await _store(images, settings, user)
    try:
        await st.add_user_message(db, ticket=ticket, user=user, body=body, images=stored, settings=settings)
        await db.commit()
    except st.TicketError as error:
        await db.rollback()
        await _forget_images(stored)
        _answer(error)
    except Exception:
        await db.rollback()
        await _forget_images(stored)
        raise
    support_ticket_mail.notify_user_reply(int(ticket.id))
    return await _detail(db, ticket, user)


@router.post("/tickets/{ticket_id:int}/resolve")
async def resolve(
    ticket_id: int,
    user: User = Depends(get_current_user),
    _settings: st.TicketSettings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The person says it works now and marks their ticket resolved."""
    ticket = await _own_ticket(db, ticket_id, user)
    _require_active(user)
    try:
        await st.user_resolve(db, ticket=ticket, user=user)
        await db.commit()
    except st.TicketError as error:
        await db.rollback()
        _answer(error)
    return await _detail(db, ticket, user)


# --- images -------------------------------------------------------------------------------------------------------


async def _reads_tickets(db: AsyncSession, user: User) -> bool:
    """The same test as ``require_tickets`` (Support, Super Admin, Read Only Super Admin), without raising."""
    if not user.is_active:
        return False
    slugs = await get_user_role_slugs(db, int(user.id))
    return user_is_admin_panel(slugs) and user_can_access_menu(slugs, "tickets")


@router.get("/attachments/{attachment_id:int}")
async def get_attachment(
    attachment_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    """An image of a ticket, for its owner (never one of an internal note) or the support staff.

    Anyone else gets 404, as if it did not exist. Staff still see images while
    Support is switched off: their queue keeps working.
    """
    row = (
        await db.execute(
            select(SupportTicketAttachment, SupportTicketMessage.kind, SupportTicket.user_id)
            .join(SupportTicketMessage, SupportTicketMessage.id == SupportTicketAttachment.message_id)
            .join(SupportTicket, SupportTicket.id == SupportTicketAttachment.ticket_id)
            .where(SupportTicketAttachment.id == attachment_id)
        )
    ).first()
    staff = await _reads_tickets(db, user)
    if not staff:
        settings = await st.load_settings(db)
        if not settings.enabled:
            raise _disabled()
    if row is None:
        raise _refuse("not_found", "Image not found.", 404)
    attachment, kind, owner_id = row
    owner_may = int(owner_id) == int(user.id) and kind != "note"
    if not (owner_may or staff):
        raise _refuse("not_found", "Image not found.", 404)
    try:
        content = await read_ticket_image(str(attachment.storage_key))
    except Exception as exc:  # noqa: BLE001 -- a missing object reads like a missing image
        logger.warning("A ticket image could not be read: %s", attachment.storage_key, exc_info=True)
        raise _refuse("not_found", "Image not found.", 404) from exc
    return Response(
        content=content,
        media_type=str(attachment.mime),
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": "inline",
        },
    )
