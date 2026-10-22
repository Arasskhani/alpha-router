"""Support tickets: the rules a ticket lives by, from the moment a person opens it until it is deleted.

The APIs only call these functions; every lifecycle rule is here, so the user
API, the staff API and the scheduler cannot disagree about what a reply, a
status change or an assignment does.

- A new ticket is ``open`` and needs staff. The automatic reply, when it is
  on, is added at once; it changes nothing else and never counts as the
  first reply.
- A staff reply sets the first reply time once, hands the next move to the
  person, and turns an ``open`` ticket into ``in_progress``. A note changes
  nothing the person can see.
- The person's reply hands the move back to staff. On a resolved or closed
  ticket it reopens it while the reopen window lasts; after that they open a
  new ticket.
- ``waiting`` closes by itself after ``auto_close_days``; ``resolved`` closes
  after ``reopen_days``; ``closed`` is deleted after ``retention_days``.
- Assigning to someone else may email them; taking a ticket yourself never
  does. Whoever can no longer work tickets loses their open ones.

Functions that change a ticket flush and never commit (the API commits with
its audit row), except the scheduled jobs, which commit in batches. Times are
naive UTC, as everywhere else in the code base.

``updated_at`` is the activity the person can see (messages, replies, status
changes): staff-only changes (notes, priority, category, assignment) leave it,
so the person's list does not jump and the Needs-staff view keeps whoever
has waited longest first.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import case, delete, func, select
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_ticket import SupportTicket, SupportTicketAttachment, SupportTicketMessage
from app.models.system import SystemSetting
from app.models.user import User, UserRoleAssignment
from app.services.rbac import SUPER_ADMIN_SLUG, SUPPORT_SLUG, user_can_work_tickets, user_has_super_admin_access
from app.services.user_role_service import get_roles_map, get_user_role_slugs

logger = logging.getLogger(__name__)

Audience = Literal["user", "staff"]

PRIORITIES = ("low", "normal", "high", "urgent")
PRIORITY_RANK = {priority: rank for rank, priority in enumerate(PRIORITIES)}
PRIORITY_LABELS = {"low": "Low", "normal": "Normal", "high": "High", "urgent": "Urgent"}
STATUSES = ("open", "in_progress", "waiting", "resolved", "closed")
ACTIVE_STATUSES = ("open", "in_progress", "waiting")
DONE_STATUSES = ("resolved", "closed")
#: Staff wording; the person reads "Waiting for you" (``status_label``).
STATUS_LABELS = {
    "open": "Open",
    "in_progress": "In progress",
    "waiting": "Waiting for user",
    "resolved": "Resolved",
    "closed": "Closed",
}
MESSAGE_KINDS = ("user", "staff", "note", "auto", "event")
CLOSED_REASONS = ("manual", "auto", "resolved")
#: The image types an administrator may allow; never more.
IMAGE_TYPE_CEILING = ("png", "jpg", "webp", "gif")
SETTINGS_KEY = "tickets.settings"

TITLE_MAX = 150
BODY_MAX = 5000
CATEGORY_MAX = 40
CONTEXT_KEYS = ("app_version", "browser", "page")
CONTEXT_VALUE_MAX = 200
AUTO_REPLY_MAX = 2000
AUTO_REPLY_AUTHOR = "Support team"
DEFAULT_AUTO_REPLY_TEXT = (
    "Hello {name}, we have your ticket {number} “{title}”.\nWe answer within one working day; Urgent tickets sooner."
)
DEFAULT_CATEGORIES = ("Bug", "Problem", "Question", "Feature request")
_MAX_NOTIFY_EMAILS = 20
_MAX_CATEGORIES = 20
#: (minimum, maximum) for every whole-number setting.
SETTING_BOUNDS: dict[str, tuple[int, int]] = {
    "per_hour": (1, 100),
    "max_open": (1, 200),
    "reopen_days": (1, 90),
    "auto_close_days": (1, 60),
    "retention_days": (0, 3650),
    "max_image_mb": (1, 10),
    "max_images": (1, 10),
    "max_side_px": (512, 8192),
}
#: The hard ceiling on images per message: the settings may allow fewer, never more.
MAX_IMAGES_CEILING = SETTING_BOUNDS["max_images"][1]
_BOOL_SETTINGS = ("enabled", "notify_on_user_reply", "email_assignee", "email_user", "auto_reply_enabled")
#: Replies one person may send in an hour, over all their tickets.
REPLIES_PER_HOUR = 60
_JOB_BATCH = 200
_IN_CHUNK = 500


class TicketError(Exception):
    """A request the rules refuse. The APIs answer ``HTTPException(status_code, {"code", "message", **extra})``."""

    def __init__(self, code: str, message: str, status_code: int = 400, extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = dict(extra or {})


# --- settings -------------------------------------------------------------------------------------------------


@dataclass
class TicketSettings:
    enabled: bool = True
    per_hour: int = 5
    max_open: int = 20
    reopen_days: int = 14
    auto_close_days: int = 7
    retention_days: int = 365
    notify_emails: list[str] = field(default_factory=list)
    notify_on_user_reply: bool = True
    notify_min_priority: str = "normal"
    email_assignee: bool = True
    email_user: bool = False
    auto_reply_enabled: bool = True
    auto_reply_text: str = DEFAULT_AUTO_REPLY_TEXT
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    image_types: list[str] = field(default_factory=lambda: list(IMAGE_TYPE_CEILING))
    max_image_mb: int = 5
    max_images: int = 5
    max_side_px: int = 4096

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "per_hour": self.per_hour,
            "max_open": self.max_open,
            "reopen_days": self.reopen_days,
            "auto_close_days": self.auto_close_days,
            "retention_days": self.retention_days,
            "notify_emails": list(self.notify_emails),
            "notify_on_user_reply": self.notify_on_user_reply,
            "notify_min_priority": self.notify_min_priority,
            "email_assignee": self.email_assignee,
            "email_user": self.email_user,
            "auto_reply_enabled": self.auto_reply_enabled,
            "auto_reply_text": self.auto_reply_text,
            "categories": list(self.categories),
            "image_types": list(self.image_types),
            "max_image_mb": self.max_image_mb,
            "max_images": self.max_images,
            "max_side_px": self.max_side_px,
        }


def _valid_email(value: str) -> bool:
    from app.services.smtp_service import is_sendable_address

    return "@" in value and len(value) <= 254 and not any(c.isspace() for c in value) and is_sendable_address(value)


def _clean_categories(values: Iterable[Any]) -> list[str]:
    """Trimmed, de-duplicated (ignoring case) category names; refuses nothing, so the caller decides."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = " ".join(str(value).split())
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name)
    return out


def _clean_image_types(values: Iterable[Any]) -> list[str]:
    wanted = {"jpg" if str(v).strip().lower() == "jpeg" else str(v).strip().lower() for v in values}
    return [kind for kind in IMAGE_TYPE_CEILING if kind in wanted]


def _lenient_int(data: dict[str, Any], key: str, default: int) -> int:
    low, high = SETTING_BOUNDS[key]
    raw = data.get(key, default)
    if isinstance(raw, bool):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(value, low), high)


def _settings_from_stored(data: dict[str, Any]) -> TicketSettings:
    """What was saved, with anything missing, garbled or out of bounds put back within the rules."""
    defaults = TicketSettings()
    values: dict[str, Any] = {}
    for key in _BOOL_SETTINGS:
        raw = data.get(key, getattr(defaults, key))
        values[key] = raw if isinstance(raw, bool) else getattr(defaults, key)
    for key in SETTING_BOUNDS:
        values[key] = _lenient_int(data, key, getattr(defaults, key))
    emails = data.get("notify_emails")
    emails = emails if isinstance(emails, list) else []
    values["notify_emails"] = [str(e).strip() for e in emails if _valid_email(str(e).strip())][:_MAX_NOTIFY_EMAILS]
    priority = data.get("notify_min_priority")
    values["notify_min_priority"] = priority if priority in PRIORITIES else defaults.notify_min_priority
    text = data.get("auto_reply_text")
    values["auto_reply_text"] = text[:AUTO_REPLY_MAX] if isinstance(text, str) else defaults.auto_reply_text
    raw_categories = data.get("categories")
    raw_categories = raw_categories if isinstance(raw_categories, list) else []
    categories = [c for c in _clean_categories(raw_categories) if len(c) <= CATEGORY_MAX][:_MAX_CATEGORIES]
    values["categories"] = categories or defaults.categories
    raw_types = data.get("image_types")
    types = _clean_image_types(raw_types) if isinstance(raw_types, list) else []
    values["image_types"] = types or defaults.image_types
    return TicketSettings(**values)


async def load_settings(db: AsyncSession) -> TicketSettings:
    """The administrator's settings; the defaults until they save some, or for whatever is unreadable."""
    row = await db.get(SystemSetting, SETTINGS_KEY)
    try:
        data = json.loads(str(row.value)) if row is not None and row.value else {}
    except ValueError:
        data = {}
    return _settings_from_stored(data if isinstance(data, dict) else {})


def _invalid(message: str) -> TicketError:
    return TicketError("invalid_settings", message, 422)


def _strict_int(data: dict[str, Any], key: str, default: int) -> int:
    low, high = SETTING_BOUNDS[key]
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _invalid(f"{key} must be a whole number from {low} to {high}.")
    return value


def _strict_emails(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise _invalid("notify_emails must be a list of email addresses.")
    emails: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            raise _invalid("notify_emails must be a list of email addresses.")
        email = value.strip()
        if not email:
            continue
        if not _valid_email(email):
            raise _invalid(f"Not an email address: {value}")
        if email.lower() not in {e.lower() for e in emails}:
            emails.append(email)
    if len(emails) > _MAX_NOTIFY_EMAILS:
        raise _invalid(f"Up to {_MAX_NOTIFY_EMAILS} addresses can be told about new tickets.")
    return emails


def _strict_categories(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise _invalid("categories must be a list of names.")
    names = [" ".join(v.split()) for v in raw if v.strip()]
    categories = _clean_categories(names)
    if len(categories) != len(names):
        raise _invalid("Each category can appear only once.")
    if not 1 <= len(categories) <= _MAX_CATEGORIES:
        raise _invalid(f"Keep from 1 to {_MAX_CATEGORIES} categories.")
    long = next((c for c in categories if len(c) > CATEGORY_MAX), None)
    if long is not None:
        raise _invalid(f"A category name can be up to {CATEGORY_MAX} characters: {long}")
    return categories


def _strict_image_types(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise _invalid("image_types must be a list.")
    unknown = [v for v in raw if v.strip().lower() not in (*IMAGE_TYPE_CEILING, "jpeg")]
    if unknown:
        raise _invalid(f"Only these image types can be allowed: {', '.join(IMAGE_TYPE_CEILING)}.")
    types = _clean_image_types(raw)
    if not types:
        raise _invalid("Allow at least one image type.")
    return types


def validate_settings(data: dict[str, Any]) -> TicketSettings:
    """Check settings an administrator sends; refuse with ``invalid_settings`` (422) and say which value is wrong.

    A key that is left out takes its default, so a partial update has to be
    merged over the current ``as_dict()`` before it is checked.
    """
    if not isinstance(data, dict):
        raise _invalid("Send the settings as an object.")
    defaults = TicketSettings()
    values: dict[str, Any] = {}
    for key in _BOOL_SETTINGS:
        value = data.get(key, getattr(defaults, key))
        if not isinstance(value, bool):
            raise _invalid(f"{key} must be true or false.")
        values[key] = value
    for key in SETTING_BOUNDS:
        values[key] = _strict_int(data, key, getattr(defaults, key))
    if values["retention_days"] and values["retention_days"] < values["reopen_days"]:
        raise _invalid(
            f"Keep closed tickets at least {values['reopen_days']} days (the reopen window), "
            "or set retention to 0 to keep them forever."
        )
    values["notify_emails"] = _strict_emails(data.get("notify_emails", []))
    priority = data.get("notify_min_priority", defaults.notify_min_priority)
    if priority not in PRIORITIES:
        raise _invalid(f"notify_min_priority must be one of {', '.join(PRIORITIES)}.")
    values["notify_min_priority"] = priority
    text = data.get("auto_reply_text", defaults.auto_reply_text)
    if not isinstance(text, str) or len(text) > AUTO_REPLY_MAX:
        raise _invalid(f"The automatic reply can be up to {AUTO_REPLY_MAX} characters.")
    if values["auto_reply_enabled"] and not text.strip():
        raise _invalid("Write the automatic reply, or turn it off.")
    values["auto_reply_text"] = text
    values["categories"] = _strict_categories(data.get("categories", list(defaults.categories)))
    values["image_types"] = _strict_image_types(data.get("image_types", list(defaults.image_types)))
    return TicketSettings(**values)


async def save_settings(db: AsyncSession, settings: TicketSettings) -> None:
    """Store the settings; the caller commits (with its Admin Logs row)."""
    value = json.dumps(settings.as_dict(), ensure_ascii=False)
    row = await db.get(SystemSetting, SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value))
    else:
        row.value = value  # type: ignore[assignment]


# --- who works tickets ----------------------------------------------------------------------------------------


@dataclass
class Staff:
    """Someone a ticket can be assigned to."""

    id: int
    name: str
    username: str
    role_label: str
    open_count: int


def display_name(user: User) -> str:
    return str(user.display_name or "").strip() or str(user.username)


def _usable(user: User | None) -> bool:
    return bool(user is not None and user.is_active and user.deleted_at is None and user.purged_at is None)


async def can_work_tickets(db: AsyncSession, user: User | None) -> bool:
    """Active, and holds a role that may write the Tickets menu (Support or Super Admin, never read-only)."""
    if user is None or not _usable(user):
        return False
    return user_can_work_tickets(await get_user_role_slugs(db, int(user.id)))


def staff_role_label(slugs: list[str]) -> str:
    return "Super Admin" if user_has_super_admin_access(slugs) else "Support"


async def _active_assigned_counts(db: AsyncSession) -> dict[int, int]:
    rows = (
        await db.execute(
            select(SupportTicket.assignee_id, func.count())
            .where(SupportTicket.assignee_id.is_not(None), SupportTicket.status.in_(ACTIVE_STATUSES))
            .group_by(SupportTicket.assignee_id)
        )
    ).all()
    return {int(assignee_id): int(count) for assignee_id, count in rows}


async def assignable_staff(db: AsyncSession) -> list[Staff]:
    """Everyone a ticket can be assigned to, with how many active tickets each holds, by name."""
    candidate_ids = (
        (
            await db.execute(
                select(UserRoleAssignment.user_id)
                .where(UserRoleAssignment.role_slug.in_((SUPPORT_SLUG, SUPER_ADMIN_SLUG)))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not candidate_ids:
        return []
    users = (await db.execute(select(User).where(User.id.in_(candidate_ids)))).scalars().all()
    roles = await get_roles_map(db, [int(u.id) for u in users])
    counts = await _active_assigned_counts(db)
    staff = [
        Staff(
            id=int(u.id),
            name=display_name(u),
            username=str(u.username),
            role_label=staff_role_label(roles.get(int(u.id), [])),
            open_count=counts.get(int(u.id), 0),
        )
        for u in users
        if _usable(u) and user_can_work_tickets(roles.get(int(u.id), []))
    ]
    return sorted(staff, key=lambda s: (s.name.casefold(), s.id))


# --- creating and changing --------------------------------------------------------------------------------------


@dataclass
class StoredImage:
    """An image the upload pipeline has checked, cleaned and stored; persisted here as an attachment row."""

    storage_key: str
    mime: str
    bytes: int
    width: int
    height: int
    sha256: str
    display_name: str


@dataclass
class AssignOutcome:
    changed: bool
    #: Send the assignee an email (``support_ticket_mail.notify_assignees([event_id])``) after the commit.
    email_wanted: bool
    event_id: int | None


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _text(value: str | None, *, name: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise TicketError(f"invalid_{name}", f"The {name} cannot be empty.", 422)
    if len(text) > limit:
        raise TicketError(f"invalid_{name}", f"The {name} can be up to {limit} characters.", 422)
    return text


def _check_image_count(images: Sequence[StoredImage], settings: TicketSettings) -> None:
    if len(images) > settings.max_images:
        raise TicketError("too_many_images", f"Up to {settings.max_images} images can go with one message.", 422)


def _clean_context(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    kept = {
        key: str(context[key]).strip()[:CONTEXT_VALUE_MAX]
        for key in CONTEXT_KEYS
        if isinstance(context.get(key), str | int | float) and str(context[key]).strip()
    }
    return json.dumps(kept, ensure_ascii=False) if kept else None


def _event(ticket: SupportTicket, now: datetime.datetime, **facts: Any) -> SupportTicketMessage:
    return SupportTicketMessage(
        ticket_id=ticket.id, kind="event", body="", event_json=json.dumps(facts, ensure_ascii=False), created_at=now
    )


def _attach(
    db: AsyncSession, ticket: SupportTicket, message: SupportTicketMessage, images: Sequence[StoredImage]
) -> None:
    for image in images:
        db.add(
            SupportTicketAttachment(
                ticket_id=ticket.id,
                message_id=message.id,
                storage_key=image.storage_key,
                mime=image.mime,
                bytes=image.bytes,
                width=image.width,
                height=image.height,
                sha256=image.sha256,
                display_name=(image.display_name or "image")[:255],
                created_at=message.created_at,
            )
        )


async def _add_message(
    db: AsyncSession,
    ticket: SupportTicket,
    *,
    kind: str,
    body: str,
    author: User | None,
    now: datetime.datetime,
    images: Sequence[StoredImage] = (),
    author_name: str | None = None,
) -> SupportTicketMessage:
    message = SupportTicketMessage(
        ticket_id=ticket.id,
        kind=kind,
        body=body,
        author_id=author.id if author is not None else None,
        author_name=(author_name or (display_name(author) if author is not None else None) or "")[:255] or None,
        created_at=now,
    )
    db.add(message)
    await db.flush()
    _attach(db, ticket, message, images)
    return message


_PLACEHOLDER = re.compile(r"\{(name|number|title|priority|category)\}")


def render_auto_reply(text: str, ticket: SupportTicket) -> str:
    """Fill the placeholders in one pass (a title that itself reads "{name}" stays as typed); any other
    braces are left as written."""
    values = {
        "name": str(ticket.reporter_name or ""),
        "number": f"#{ticket.number}",
        "title": str(ticket.title or ""),
        "priority": PRIORITY_LABELS.get(str(ticket.priority), str(ticket.priority)),
        "category": str(ticket.category or ""),
    }
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], text)


async def _count(db: AsyncSession, *conditions: Any) -> int:
    return int((await db.execute(select(func.count()).select_from(SupportTicket).where(*conditions))).scalar_one())


def auto_reply_wanted(settings: TicketSettings) -> bool:
    """Whether a new ticket gets the automatic reply (and, with ``email_user``, the person an email of it)."""
    return settings.auto_reply_enabled and bool(settings.auto_reply_text.strip())


async def precheck_create(
    db: AsyncSession,
    *,
    user: User,
    title: str,
    description: str,
    category: str,
    priority: str,
    settings: TicketSettings,
) -> tuple[str, str]:
    """Every refusal of a new ticket that needs no image: run before the images are checked and stored.

    ``create_ticket`` runs it again, so the rules live here once. Returns the
    trimmed title and description.
    """
    if not user.is_active:
        raise TicketError("account_inactive", "A disabled account cannot open tickets.", 403)
    title = _text(title, name="title", limit=TITLE_MAX)
    description = _text(description, name="description", limit=BODY_MAX)
    if category not in settings.categories:
        raise TicketError("invalid_category", "Pick one of the categories offered.", 422)
    if priority not in PRIORITIES:
        raise TicketError("invalid_priority", "Pick one of the priorities offered.", 422)
    since = _now() - datetime.timedelta(hours=1)
    recent = await _count(db, SupportTicket.user_id == user.id, SupportTicket.created_at >= since)
    if recent >= settings.per_hour:
        raise TicketError(
            "ticket_rate_limited",
            f"You can open up to {settings.per_hour} tickets an hour. Try again later.",
            429,
        )
    active = await _count(db, SupportTicket.user_id == user.id, SupportTicket.status.in_(ACTIVE_STATUSES))
    if active >= settings.max_open:
        raise TicketError(
            "too_many_open",
            f"You have {active} open tickets, the most allowed. Mark one resolved before you open another.",
            409,
        )
    return title, description


async def create_ticket(
    db: AsyncSession,
    *,
    user: User,
    title: str,
    description: str,
    category: str,
    priority: str,
    context: dict[str, Any] | None,
    images: Sequence[StoredImage],
    settings: TicketSettings,
) -> SupportTicket:
    """Open a ticket with the person's first message and, when it is on, the automatic reply."""
    title, description = await precheck_create(
        db, user=user, title=title, description=description, category=category, priority=priority, settings=settings
    )
    _check_image_count(images, settings)
    now = _now()
    ticket = SupportTicket(
        # The number is 1000 + id, known only after the insert; until then a
        # random negative stand-in keeps the column unique and not null.
        number=-(uuid.uuid4().int % 2_000_000_000) - 1,
        user_id=user.id,
        reporter_name=display_name(user)[:255],
        reporter_username=str(user.username)[:255],
        reporter_email=(str(user.email)[:255] if user.email else None),
        reporter_department=(str(user.department).strip()[:255] or None) if user.department else None,
        title=title,
        category=category,
        priority=priority,
        status="open",
        context_json=_clean_context(context),
        user_unread=False,
        needs_staff=True,
        created_at=now,
        updated_at=now,
        reopened_count=0,
    )
    db.add(ticket)
    await db.flush()
    ticket.number = 1000 + int(ticket.id)  # type: ignore[assignment]
    await _add_message(db, ticket, kind="user", body=description, author=user, now=now, images=images)
    if auto_reply_wanted(settings):
        await _add_message(
            db,
            ticket,
            kind="auto",
            body=render_auto_reply(settings.auto_reply_text, ticket),
            author=None,
            author_name=AUTO_REPLY_AUTHOR,
            now=now,
        )
    await db.flush()
    return ticket


def reopen_until(ticket: SupportTicket, settings: TicketSettings) -> datetime.datetime | None:
    """Until when the person can reopen a resolved or closed ticket by replying."""
    if ticket.status not in DONE_STATUSES:
        return None
    since = ticket.resolved_at or ticket.closed_at
    return since + datetime.timedelta(days=settings.reopen_days) if since is not None else None


def _clear_done(ticket: SupportTicket) -> None:
    ticket.resolved_at = None  # type: ignore[assignment]
    ticket.resolved_by = None  # type: ignore[assignment]
    ticket.closed_at = None  # type: ignore[assignment]
    ticket.closed_reason = None  # type: ignore[assignment]


def _own(ticket: SupportTicket, user: User) -> None:
    if int(ticket.user_id) != int(user.id):
        raise TicketError("not_found", "Ticket not found.", 404)


async def _recent_replies(db: AsyncSession, user: User, since: datetime.datetime) -> int:
    """The person's replies since then, on all their tickets (the first message of a new ticket is not a reply)."""
    messages = int(
        (
            await db.execute(
                select(func.count())
                .select_from(SupportTicketMessage)
                .join(SupportTicket, SupportTicket.id == SupportTicketMessage.ticket_id)
                .where(
                    SupportTicket.user_id == user.id,
                    SupportTicketMessage.kind == "user",
                    SupportTicketMessage.created_at >= since,
                )
            )
        ).scalar_one()
    )
    opened = await _count(db, SupportTicket.user_id == user.id, SupportTicket.created_at >= since)
    return max(0, messages - opened)


async def precheck_user_reply(
    db: AsyncSession, *, ticket: SupportTicket, user: User, body: str, settings: TicketSettings
) -> str:
    """Every refusal of the person's reply that needs no image: run before the images are checked and stored.

    ``add_user_message`` runs it again. Returns the trimmed body.
    """
    _own(ticket, user)
    if not user.is_active:
        raise TicketError("account_inactive", "A disabled account cannot reply.", 403)
    body = _text(body, name="body", limit=BODY_MAX)
    now = _now()
    if ticket.status in DONE_STATUSES:
        until = reopen_until(ticket, settings)
        if until is None or now > until:
            raise TicketError(
                "reopen_window_passed",
                f"This ticket ended more than {settings.reopen_days} days ago. Open a new ticket instead.",
                409,
            )
    if await _recent_replies(db, user, now - datetime.timedelta(hours=1)) >= REPLIES_PER_HOUR:
        raise TicketError(
            "reply_rate_limited",
            f"You can send up to {REPLIES_PER_HOUR} replies an hour. Try again later.",
            429,
        )
    return body


async def add_user_message(
    db: AsyncSession,
    *,
    ticket: SupportTicket,
    user: User,
    body: str,
    images: Sequence[StoredImage],
    settings: TicketSettings,
) -> SupportTicketMessage:
    """The person writes on their ticket: the move goes back to staff, and a done ticket reopens in time."""
    body = await precheck_user_reply(db, ticket=ticket, user=user, body=body, settings=settings)
    _check_image_count(images, settings)
    now = _now()
    reopening = ticket.status in DONE_STATUSES
    message = await _add_message(db, ticket, kind="user", body=body, author=user, now=now, images=images)
    if reopening:
        _clear_done(ticket)
        ticket.status = "open"  # type: ignore[assignment]
        ticket.reopened_count = int(ticket.reopened_count or 0) + 1  # type: ignore[assignment]
        db.add(_event(ticket, now, type="reopened", by=display_name(user), by_id=int(user.id)))
    elif ticket.status == "waiting":
        ticket.status = "open"  # type: ignore[assignment]
    ticket.waiting_since = None  # type: ignore[assignment]
    ticket.needs_staff = True  # type: ignore[assignment]
    ticket.updated_at = now  # type: ignore[assignment]
    await db.flush()
    return message


def _apply_status(ticket: SupportTicket, status: str, now: datetime.datetime) -> None:
    previous = str(ticket.status)
    if previous in DONE_STATUSES and status in ACTIVE_STATUSES:
        _clear_done(ticket)
        ticket.reopened_count = int(ticket.reopened_count or 0) + 1  # type: ignore[assignment]
    ticket.status = status  # type: ignore[assignment]
    ticket.waiting_since = now if status == "waiting" else None  # type: ignore[assignment]
    if status == "resolved":
        ticket.resolved_at = now  # type: ignore[assignment]
        ticket.resolved_by = "staff"  # type: ignore[assignment]
        ticket.closed_at = None  # type: ignore[assignment]
        ticket.closed_reason = None  # type: ignore[assignment]
    elif status == "closed":
        ticket.closed_at = now  # type: ignore[assignment]
        ticket.closed_reason = "manual"  # type: ignore[assignment]
    if status in DONE_STATUSES:
        ticket.needs_staff = False  # type: ignore[assignment]


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise TicketError("invalid_status", f"Status must be one of {', '.join(STATUSES)}.", 422)


async def _change_status(db: AsyncSession, ticket: SupportTicket, actor: User, status: str, now: datetime.datetime):
    if status == ticket.status:
        return
    previous = str(ticket.status)
    _apply_status(ticket, status, now)
    ticket.user_unread = True  # type: ignore[assignment]
    ticket.updated_at = now  # type: ignore[assignment]
    db.add(
        _event(ticket, now, type="status", by=display_name(actor), by_id=int(actor.id), to=status, **{"from": previous})
    )


def precheck_staff_message(*, body: str, status: str | None) -> str:
    """Every refusal of a staff reply or note that needs no image: run before the images are stored.

    ``add_staff_message`` runs it again. Returns the trimmed body.
    """
    body = _text(body, name="body", limit=BODY_MAX)
    if status is not None:
        _check_status(status)
    return body


async def add_staff_message(
    db: AsyncSession,
    *,
    ticket: SupportTicket,
    staff: User,
    body: str,
    internal: bool,
    images: Sequence[StoredImage],
    status: str | None,
) -> SupportTicketMessage:
    """A reply (the person sees it) or an internal note (only staff do), with an optional status change."""
    body = precheck_staff_message(body=body, status=status)
    if len(images) > MAX_IMAGES_CEILING:
        raise TicketError("too_many_images", f"Up to {MAX_IMAGES_CEILING} images can go with one message.", 422)
    now = _now()
    message = await _add_message(
        db, ticket, kind="note" if internal else "staff", body=body, author=staff, now=now, images=images
    )
    if not internal:
        if ticket.first_staff_reply_at is None:
            ticket.first_staff_reply_at = now  # type: ignore[assignment]
        ticket.needs_staff = False  # type: ignore[assignment]
        ticket.user_unread = True  # type: ignore[assignment]
        if status is None and ticket.status == "open":
            status = "in_progress"
    if status is not None:
        await _change_status(db, ticket, staff, status, now)
    if not internal:
        if ticket.status == "waiting":
            # Asked again: the person gets the full auto_close_days from this reply.
            ticket.waiting_since = now  # type: ignore[assignment]
        ticket.updated_at = now  # type: ignore[assignment]
    await db.flush()
    return message


async def set_status(db: AsyncSession, *, ticket: SupportTicket, actor: User, status: str) -> None:
    """Staff change the status; the person is told (``user_unread``) and the thread gets an event line."""
    _check_status(status)
    await _change_status(db, ticket, actor, status, _now())
    await db.flush()


async def set_priority(db: AsyncSession, *, ticket: SupportTicket, actor: User, priority: str) -> None:
    if priority not in PRIORITIES:
        raise TicketError("invalid_priority", f"Priority must be one of {', '.join(PRIORITIES)}.", 422)
    if priority == ticket.priority:
        return
    now = _now()
    previous = str(ticket.priority)
    ticket.priority = priority  # type: ignore[assignment]
    db.add(
        _event(
            ticket, now, type="priority", by=display_name(actor), by_id=int(actor.id), to=priority, **{"from": previous}
        )
    )
    await db.flush()


async def set_category(
    db: AsyncSession,
    *,
    ticket: SupportTicket,
    actor: User,
    category: str,
    settings: TicketSettings | None = None,
) -> None:
    """Move the ticket to another category; one the settings no longer offer can only be kept, not chosen."""
    if category == ticket.category:
        return
    settings = settings or await load_settings(db)
    if category not in settings.categories:
        raise TicketError("invalid_category", "Pick one of the categories offered.", 422)
    now = _now()
    previous = str(ticket.category)
    ticket.category = category  # type: ignore[assignment]
    db.add(
        _event(
            ticket, now, type="category", by=display_name(actor), by_id=int(actor.id), to=category, **{"from": previous}
        )
    )
    await db.flush()


async def user_resolve(db: AsyncSession, *, ticket: SupportTicket, user: User) -> None:
    """The person says it works now."""
    _own(ticket, user)
    if not user.is_active:
        raise TicketError("account_inactive", "A disabled account cannot change tickets.", 403)
    if ticket.status not in ACTIVE_STATUSES:
        raise TicketError("not_active", "This ticket has already ended.", 409)
    now = _now()
    ticket.status = "resolved"  # type: ignore[assignment]
    ticket.resolved_at = now  # type: ignore[assignment]
    ticket.resolved_by = "user"  # type: ignore[assignment]
    ticket.waiting_since = None  # type: ignore[assignment]
    ticket.needs_staff = False  # type: ignore[assignment]
    ticket.updated_at = now  # type: ignore[assignment]
    db.add(_event(ticket, now, type="resolved", by=display_name(user), by_id=int(user.id)))
    await db.flush()


async def assign(
    db: AsyncSession,
    *,
    ticket: SupportTicket,
    actor: User,
    assignee: User | None,
    settings: TicketSettings | None = None,
) -> AssignOutcome:
    """Give the ticket to someone who works tickets (or to nobody); say whether they should get an email.

    No email for taking a ticket yourself, none for unassigning, and none when
    the setting is off or the assignee has no address. The event records which
    (``pending``, ``none``, ``off``); the mail job turns ``pending`` into
    ``sent`` or ``failed``.
    """
    now = _now()
    if assignee is None:
        if ticket.assignee_id is None:
            return AssignOutcome(changed=False, email_wanted=False, event_id=None)
        previous = await db.get(User, ticket.assignee_id)
        ticket.assignee_id = None  # type: ignore[assignment]
        ticket.assigned_at = None  # type: ignore[assignment]
        ticket.assigned_by_id = None  # type: ignore[assignment]
        row = _event(
            ticket,
            now,
            type="unassigned",
            by=display_name(actor),
            by_id=int(actor.id),
            **{"from": display_name(previous) if previous else None, "from_id": previous.id if previous else None},
        )
        db.add(row)
        await db.flush()
        return AssignOutcome(changed=True, email_wanted=False, event_id=int(row.id))
    if not await can_work_tickets(db, assignee):
        raise TicketError("not_assignable", f"{display_name(assignee)} cannot work tickets.", 422)
    if ticket.assignee_id is not None and int(ticket.assignee_id) == int(assignee.id):
        return AssignOutcome(changed=False, email_wanted=False, event_id=None)
    settings = settings or await load_settings(db)
    if int(assignee.id) == int(actor.id):
        email = "none"
    elif settings.email_assignee and (assignee.email or "").strip():
        email = "pending"
    else:
        email = "off"
    ticket.assignee_id = assignee.id
    ticket.assigned_at = now  # type: ignore[assignment]
    ticket.assigned_by_id = actor.id
    row = _event(
        ticket,
        now,
        type="assigned",
        by=display_name(actor),
        by_id=int(actor.id),
        to=display_name(assignee),
        to_id=int(assignee.id),
        email=email,
    )
    db.add(row)
    await db.flush()
    return AssignOutcome(changed=True, email_wanted=email == "pending", event_id=int(row.id))


async def release_orphaned_assignments(db: AsyncSession) -> int:
    """Unassign active tickets whose assignee can no longer work tickets; returns how many. The caller commits.

    Someone loses the Support role, is disabled or purged: nothing should wait
    on a person who can no longer see it.
    """
    assignee_ids = (
        (
            await db.execute(
                select(SupportTicket.assignee_id)
                .where(SupportTicket.assignee_id.is_not(None), SupportTicket.status.in_(ACTIVE_STATUSES))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    released = 0
    now = _now()
    for assignee_id in assignee_ids:
        person = await db.get(User, assignee_id)
        if await can_work_tickets(db, person):
            continue
        name = display_name(person) if person is not None else "Someone"
        tickets = (
            (
                await db.execute(
                    select(SupportTicket).where(
                        SupportTicket.assignee_id == assignee_id, SupportTicket.status.in_(ACTIVE_STATUSES)
                    )
                )
            )
            .scalars()
            .all()
        )
        for ticket in tickets:
            ticket.assignee_id = None  # type: ignore[assignment]
            ticket.assigned_at = None  # type: ignore[assignment]
            ticket.assigned_by_id = None  # type: ignore[assignment]
            db.add(_event(ticket, now, type="assignee_removed", **{"from": name, "from_id": int(assignee_id)}))
            released += 1
    await db.flush()
    return released


# --- scheduled jobs ---------------------------------------------------------------------------------------------


def _locked_batch_query(after_id: int, *conditions: Any) -> Any:
    return (
        select(SupportTicket)
        .where(SupportTicket.id > after_id, *conditions)
        .order_by(SupportTicket.id)
        .limit(_JOB_BATCH)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


async def _locked_batch(db: AsyncSession, after_id: int, *conditions: Any) -> list[SupportTicket]:
    """The next tickets past ``after_id`` meeting the conditions, locked (``FOR UPDATE SKIP LOCKED`` on
    PostgreSQL; nothing on SQLite) and read afresh, so a change committed meanwhile is what the job sees and
    a ticket someone is changing right now waits for the next run."""
    return list((await db.execute(_locked_batch_query(after_id, *conditions))).scalars().all())


async def close_waiting_tickets(db: AsyncSession, *, now: datetime.datetime | None = None) -> list[int]:
    """Close tickets that waited for the person longer than ``auto_close_days``; commits in batches.

    Returns the ids closed, so the caller can tell each person after the commit.
    """
    now = now or _now()
    days = (await load_settings(db)).auto_close_days
    cutoff = now - datetime.timedelta(days=days)
    closed: list[int] = []
    after_id = 0
    while batch := await _locked_batch(
        db, after_id, SupportTicket.status == "waiting", SupportTicket.waiting_since < cutoff
    ):
        after_id = int(batch[-1].id)
        for ticket in batch:
            # Checked again on the locked row: a reply that got in first keeps the ticket open.
            if ticket.status != "waiting" or ticket.waiting_since is None or ticket.waiting_since >= cutoff:
                continue
            ticket.status = "closed"  # type: ignore[assignment]
            ticket.closed_at = now  # type: ignore[assignment]
            ticket.closed_reason = "auto"  # type: ignore[assignment]
            ticket.waiting_since = None  # type: ignore[assignment]
            ticket.needs_staff = False  # type: ignore[assignment]
            ticket.user_unread = True  # type: ignore[assignment]
            ticket.updated_at = now  # type: ignore[assignment]
            db.add(_event(ticket, now, type="auto_closed", days=days))
            closed.append(int(ticket.id))
        await db.commit()
    return closed


async def close_resolved_tickets(db: AsyncSession, *, now: datetime.datetime | None = None) -> list[int]:
    """Close resolved tickets once their reopen window has passed; commits in batches. Returns the ids closed."""
    now = now or _now()
    days = (await load_settings(db)).reopen_days
    cutoff = now - datetime.timedelta(days=days)
    closed: list[int] = []
    after_id = 0
    while batch := await _locked_batch(
        db, after_id, SupportTicket.status == "resolved", SupportTicket.resolved_at < cutoff
    ):
        after_id = int(batch[-1].id)
        for ticket in batch:
            if ticket.status != "resolved" or ticket.resolved_at is None or ticket.resolved_at >= cutoff:
                continue
            ticket.status = "closed"  # type: ignore[assignment]
            ticket.closed_at = now  # type: ignore[assignment]
            ticket.closed_reason = "resolved"  # type: ignore[assignment]
            ticket.updated_at = now  # type: ignore[assignment]
            db.add(_event(ticket, now, type="closed_resolved", days=days))
            closed.append(int(ticket.id))
        await db.commit()
    return closed


async def purge_closed_tickets(db: AsyncSession, *, now: datetime.datetime | None = None) -> dict[str, int]:
    """Delete closed tickets older than ``retention_days`` (0 keeps them), with their images; commits in batches.

    Never one the person may still reopen: the cutoff is the longer of the
    retention period and the reopen window.
    """
    now = now or _now()
    settings = await load_settings(db)
    days = settings.retention_days
    totals = {"deleted": 0, "messages": 0, "images": 0, "image_bytes": 0, "retention_days": days}
    if days <= 0:
        return totals
    cutoff = now - datetime.timedelta(days=max(days, settings.reopen_days))
    still_due = (SupportTicket.status == "closed", SupportTicket.closed_at < cutoff)
    while True:
        ids = (
            (await db.execute(select(SupportTicket.id).where(*still_due).order_by(SupportTicket.id).limit(_JOB_BATCH)))
            .scalars()
            .all()
        )
        if not ids:
            break
        # Re-checked on the locked rows: a ticket reopened since the select is not deleted.
        counts = await delete_tickets(db, [int(i) for i in ids], where=still_due)
        await db.commit()
        for key in ("deleted", "messages", "images", "image_bytes"):
            totals[key] += counts[key]
    return totals


# --- deleting ---------------------------------------------------------------------------------------------------


_STORAGE_KEYS_INFO = "support_tickets.storage_keys"
_LISTENING_INFO = "support_tickets.listening"
_storage_tasks: set[asyncio.Task[Any]] = set()


def _chunks(ids: Sequence[int]) -> Iterable[list[int]]:
    for start in range(0, len(ids), _IN_CHUNK):
        yield list(ids[start : start + _IN_CHUNK])


async def ticket_storage_keys(db: AsyncSession, ticket_ids: Sequence[int]) -> list[str]:
    keys: list[str] = []
    for chunk in _chunks(list(ticket_ids)):
        rows = await db.execute(
            select(SupportTicketAttachment.storage_key).where(SupportTicketAttachment.ticket_id.in_(chunk))
        )
        keys.extend(str(k) for k in rows.scalars().all())
    return keys


async def _remove_objects(keys: list[str]) -> None:
    from app.services import object_storage_service

    for key in keys:
        try:
            await asyncio.to_thread(object_storage_service.delete_object, key)
        except Exception:  # noqa: BLE001 -- the rows are gone; a stray object must not fail anything
            logger.warning("A support ticket image could not be removed from storage: %s", key, exc_info=True)


def _on_commit(session: Any) -> None:
    keys = session.info.pop(_STORAGE_KEYS_INFO, None)
    if not keys:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Support ticket images were left in storage: no event loop to remove them")
        return
    task = loop.create_task(_remove_objects(list(keys)))
    _storage_tasks.add(task)
    task.add_done_callback(_storage_tasks.discard)


def _on_rollback(session: Any, _previous_transaction: Any) -> None:
    session.info.pop(_STORAGE_KEYS_INFO, None)


def _remove_objects_after_commit(db: AsyncSession, keys: list[str]) -> None:
    """Remove the images from storage once the deleting transaction commits, off the request; never on rollback."""
    if not keys:
        return
    session = db.sync_session
    session.info.setdefault(_STORAGE_KEYS_INFO, []).extend(keys)
    if not session.info.get(_LISTENING_INFO):
        sa_event.listen(session, "after_commit", _on_commit)
        sa_event.listen(session, "after_soft_rollback", _on_rollback)
        session.info[_LISTENING_INFO] = True


async def drain_storage_deletions() -> None:
    """Wait for scheduled image removals (tests, and a clean shutdown)."""
    while _storage_tasks:
        await asyncio.gather(*list(_storage_tasks), return_exceptions=True)


async def delete_tickets(db: AsyncSession, ticket_ids: Sequence[int], *, where: Sequence[Any] = ()) -> dict[str, int]:
    """Delete tickets with their messages and images; the images leave storage after the commit.

    ``where`` are conditions each ticket must still meet when it is deleted
    (the scope a Super Admin confirmed, the retention rule): the matching rows
    are locked first (``FOR UPDATE`` on PostgreSQL), so a ticket that left the
    scope meanwhile, say reopened by its reporter, stays.

    Returns ``{"deleted", "messages", "images", "image_bytes"}`` for what was
    really deleted (messages without event lines, as everywhere else they are
    counted).
    """
    ids = sorted({int(i) for i in ticket_ids})
    totals = {"deleted": 0, "messages": 0, "images": 0, "image_bytes": 0}
    keys: list[str] = []
    for requested in _chunks(ids):
        chunk = requested
        if where:
            locked = await db.execute(
                select(SupportTicket.id)
                .where(SupportTicket.id.in_(requested), *where)
                .order_by(SupportTicket.id)
                .with_for_update()
            )
            chunk = [int(i) for i in locked.scalars().all()]
            if not chunk:
                continue
        image_rows = (
            await db.execute(
                select(SupportTicketAttachment.storage_key, SupportTicketAttachment.bytes).where(
                    SupportTicketAttachment.ticket_id.in_(chunk)
                )
            )
        ).all()
        keys.extend(str(key) for key, _ in image_rows)
        totals["images"] += len(image_rows)
        totals["image_bytes"] += sum(int(size or 0) for _, size in image_rows)
        totals["messages"] += int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(SupportTicketMessage)
                    .where(SupportTicketMessage.ticket_id.in_(chunk), SupportTicketMessage.kind != "event")
                )
            ).scalar_one()
        )
        await db.execute(delete(SupportTicketAttachment).where(SupportTicketAttachment.ticket_id.in_(chunk)))
        await db.execute(delete(SupportTicketMessage).where(SupportTicketMessage.ticket_id.in_(chunk)))
        result = await db.execute(delete(SupportTicket).where(SupportTicket.id.in_(chunk), *where))
        totals["deleted"] += int(getattr(result, "rowcount", 0) or 0)
    _remove_objects_after_commit(db, keys)
    return totals


async def delete_user_tickets(db: AsyncSession, user_id: int) -> dict[str, int]:
    """Delete every ticket a person opened, for when their account is purged."""
    ids = (await db.execute(select(SupportTicket.id).where(SupportTicket.user_id == user_id))).scalars().all()
    return await delete_tickets(db, [int(i) for i in ids])


# --- reading ----------------------------------------------------------------------------------------------------


def iso_utc(value: datetime.datetime | None) -> str | None:
    """``2026-10-22T09:40:00Z``: stored times are naive UTC, so the zone is said out loud."""
    return f"{value.replace(tzinfo=None).isoformat(timespec='seconds')}Z" if value else None


def status_label(status: str, audience: Audience) -> str:
    if status == "waiting" and audience == "user":
        return "Waiting for you"
    return STATUS_LABELS.get(status, status)


def _days(n: Any) -> str:
    try:
        count = int(n)
    except (TypeError, ValueError):
        return "some days"
    return "1 day" if count == 1 else f"{count} days"


_EMAIL_NOTES = {"pending": " · email queued", "sent": " · email sent", "failed": " · email not sent"}


def _staff_event_text(kind: str, facts: dict[str, Any]) -> str | None:
    by = facts.get("by") or "Someone"
    if kind == "assigned":
        if facts.get("by_id") is not None and facts.get("by_id") == facts.get("to_id"):
            return f"{facts.get('to') or by} took the ticket"
        return f"{by} assigned this to {facts.get('to') or 'someone'}{_EMAIL_NOTES.get(str(facts.get('email')), '')}"
    if kind == "unassigned":
        return f"Unassigned by {by}"
    if kind == "assignee_removed":
        return f"Unassigned: {facts.get('from') or 'the assignee'} can no longer work tickets"
    if kind == "priority":
        return f"Priority changed to {PRIORITY_LABELS.get(str(facts.get('to')), facts.get('to'))}"
    if kind == "category":
        return f"Category changed to {facts.get('to')}"
    return None


def event_text(event_json: dict[str, Any], audience: Audience) -> str | None:
    """The line an event shows in the thread, or None when this audience does not see it."""
    facts = event_json if isinstance(event_json, dict) else {}
    kind = str(facts.get("type") or "")
    by = facts.get("by") or "Someone"
    if kind == "status":
        return f"Status changed to {status_label(str(facts.get('to')), audience)}"
    if kind == "auto_closed":
        return f"Closed automatically: no reply in {_days(facts.get('days'))}"
    if kind == "closed_resolved":
        return f"Closed: resolved {_days(facts.get('days'))} ago"
    if kind == "reopened":
        return f"Reopened by {by}"
    if kind == "resolved":
        return f"{by} marked it resolved"
    if audience == "user":
        if kind == "assigned":
            return f"{facts.get('to') or 'Support'} is handling your ticket"
        return None
    return _staff_event_text(kind, facts)


def _load_json(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(value) if isinstance(value, str) and value else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def message_counts(
    db: AsyncSession, ticket_ids: Sequence[int], *, audience: Audience = "staff"
) -> dict[int, tuple[int, int]]:
    """``{ticket_id: (messages, images)}``; event lines never count, and notes only for staff."""
    counts: dict[int, tuple[int, int]] = {int(i): (0, 0) for i in ticket_ids}
    hidden = ("event", "note") if audience == "user" else ("event",)
    for chunk in _chunks(list(counts)):
        messages = await db.execute(
            select(SupportTicketMessage.ticket_id, func.count())
            .where(SupportTicketMessage.ticket_id.in_(chunk), SupportTicketMessage.kind.not_in(hidden))
            .group_by(SupportTicketMessage.ticket_id)
        )
        for ticket_id, count in messages.all():
            counts[int(ticket_id)] = (int(count), counts[int(ticket_id)][1])
        images = await db.execute(
            select(SupportTicketAttachment.ticket_id, func.count())
            .join(SupportTicketMessage, SupportTicketMessage.id == SupportTicketAttachment.message_id)
            .where(SupportTicketAttachment.ticket_id.in_(chunk), SupportTicketMessage.kind.not_in(hidden))
            .group_by(SupportTicketAttachment.ticket_id)
        )
        for ticket_id, count in images.all():
            counts[int(ticket_id)] = (counts[int(ticket_id)][0], int(count))
    return counts


async def assignee_names(db: AsyncSession, tickets: Iterable[SupportTicket]) -> dict[int, str]:
    """``{user_id: name}`` for the assignees of these tickets (for ``ticket_summary``)."""
    ids = {int(t.assignee_id) for t in tickets if t.assignee_id is not None}
    if not ids:
        return {}
    users = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {int(u.id): display_name(u) for u in users}


def _assignee_ref(ticket: SupportTicket, names: dict[int, str] | None) -> dict[str, Any] | None:
    if ticket.assignee_id is None:
        return None
    return {"id": int(ticket.assignee_id), "name": (names or {}).get(int(ticket.assignee_id), "Someone")}


def ticket_summary(
    ticket: SupportTicket,
    *,
    audience: Audience,
    counts: tuple[int, int] | None,
    settings: TicketSettings,
    assignee_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """One row of a list: ``UserTicketSummary`` or ``StaffTicketSummary`` (the frontend's ``src/lib/tickets.ts``)."""
    message_count, image_count = counts or (0, 0)
    row: dict[str, Any] = {
        "id": int(ticket.id),
        "number": int(ticket.number),
        "title": ticket.title,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": iso_utc(ticket.created_at),
        "updated_at": iso_utc(ticket.updated_at),
        "message_count": message_count,
        "image_count": image_count,
    }
    if audience == "user":
        row["user_unread"] = bool(ticket.user_unread)
        row["reopen_until"] = iso_utc(reopen_until(ticket, settings))
    else:
        row["needs_staff"] = bool(ticket.needs_staff)
        row["reporter"] = {
            "name": ticket.reporter_name,
            "username": ticket.reporter_username,
            "department": ticket.reporter_department,
        }
        row["assignee"] = _assignee_ref(ticket, assignee_names)
    return row


def _author_label(kind: str, audience: Audience, is_admin: bool) -> str:
    if kind == "user":
        return "You" if audience == "user" else "Reporter"
    if kind in ("staff", "note"):
        return "Administrator" if is_admin else "Support"
    if kind == "auto":
        return "Automatic reply"
    return ""


def _attachment_dict(row: SupportTicketAttachment) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "url": f"/api/support/attachments/{int(row.id)}",
        "mime": row.mime,
        "bytes": int(row.bytes),
        "width": int(row.width),
        "height": int(row.height),
        "display_name": row.display_name,
    }


async def _thread(db: AsyncSession, ticket: SupportTicket, audience: Audience) -> list[dict[str, Any]]:
    query = select(SupportTicketMessage).where(SupportTicketMessage.ticket_id == ticket.id)
    if audience == "user":
        query = query.where(SupportTicketMessage.kind != "note")
    messages = (
        (await db.execute(query.order_by(SupportTicketMessage.created_at, SupportTicketMessage.id))).scalars().all()
    )
    attachments: dict[int, list[dict[str, Any]]] = {}
    rows = await db.execute(
        select(SupportTicketAttachment)
        .where(SupportTicketAttachment.ticket_id == ticket.id)
        .order_by(SupportTicketAttachment.id)
    )
    for row in rows.scalars().all():
        attachments.setdefault(int(row.message_id), []).append(_attachment_dict(row))
    staff_ids = [int(m.author_id) for m in messages if m.kind in ("staff", "note") and m.author_id is not None]
    roles = await get_roles_map(db, sorted(set(staff_ids)))
    thread: list[dict[str, Any]] = []
    for message in messages:
        kind = str(message.kind)
        body = str(message.body or "")
        author: dict[str, Any] | None = None
        if kind == "event":
            text = event_text(_load_json(message.event_json), audience)
            if text is None:
                continue
            body = text
        elif kind == "auto":
            author = {"id": None, "name": message.author_name or AUTO_REPLY_AUTHOR}
        else:
            author_id = int(message.author_id) if message.author_id is not None else None
            author = {"id": author_id, "name": message.author_name or "Someone"}
        is_admin = message.author_id is not None and user_has_super_admin_access(roles.get(int(message.author_id), []))
        thread.append(
            {
                "id": int(message.id),
                "kind": kind,
                "author": author,
                "author_label": _author_label(kind, audience, is_admin),
                "body": body,
                "created_at": iso_utc(message.created_at),
                "internal": audience == "staff" and kind == "note",
                "attachments": attachments.get(int(message.id), []),
            }
        )
    return thread


async def ticket_detail(db: AsyncSession, ticket: SupportTicket, *, audience: Audience, viewer: User) -> dict[str, Any]:
    """One ticket with its thread: ``UserTicketDetail`` or ``StaffTicketDetail``. Reads only (clearing
    ``user_unread`` when the person opens it is the user API's change to make)."""
    settings = await load_settings(db)
    counts = (await message_counts(db, [int(ticket.id)], audience=audience))[int(ticket.id)]
    names = await assignee_names(db, [ticket])
    detail = ticket_summary(ticket, audience=audience, counts=counts, settings=settings, assignee_names=names)
    active = ticket.status in ACTIVE_STATUSES
    detail.update(
        {
            "user_unread": bool(ticket.user_unread),
            "reopen_until": iso_utc(reopen_until(ticket, settings)),
            "reporter": {
                "name": ticket.reporter_name,
                "username": ticket.reporter_username,
                "email": ticket.reporter_email,
                "department": ticket.reporter_department,
            },
            "assignee": _assignee_ref(ticket, names),
            "messages": await _thread(db, ticket, audience),
            "auto_close_at": iso_utc(
                ticket.waiting_since + datetime.timedelta(days=settings.auto_close_days)
                if ticket.status == "waiting" and ticket.waiting_since is not None
                else None
            ),
        }
    )
    if audience == "user":
        until = reopen_until(ticket, settings)
        reopenable = until is not None and _now() <= until
        detail["can_reply"] = bool(viewer.is_active) and (active or reopenable)
        detail["can_resolve"] = bool(viewer.is_active) and active
        return detail
    slugs = await get_user_role_slugs(db, int(viewer.id))
    can_write = _usable(viewer) and user_can_work_tickets(slugs)
    detail.update(
        {
            "context": _load_json(ticket.context_json) or None,
            "first_staff_reply_at": iso_utc(ticket.first_staff_reply_at),
            "resolved_at": iso_utc(ticket.resolved_at),
            "closed_at": iso_utc(ticket.closed_at),
            "closed_reason": ticket.closed_reason,
            "resolved_by": ticket.resolved_by,
            "reopened_count": int(ticket.reopened_count or 0),
            "can_write": can_write,
            "can_delete": _usable(viewer) and user_has_super_admin_access(slugs),
            "can_reply": can_write,
            "can_resolve": can_write and active,
        }
    )
    return detail


async def user_unread_count(db: AsyncSession, user_id: int) -> int:
    """The person's tickets with something new they have not opened (the Support badge)."""
    return await _count(db, SupportTicket.user_id == user_id, SupportTicket.user_unread.is_(True))


async def staff_counts(db: AsyncSession, viewer_id: int) -> dict[str, int]:
    """The quick-filter counts and the Tickets badge (``needs_staff``; red while ``needs_staff_urgent``)."""
    active = SupportTicket.status.in_(ACTIVE_STATUSES)
    needs = active & SupportTicket.needs_staff.is_(True)

    def _sum(condition: Any) -> Any:
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    row = (
        await db.execute(
            select(
                _sum(needs),
                _sum(needs & (SupportTicket.priority == "urgent")),
                _sum(active & (SupportTicket.assignee_id == viewer_id)),
                _sum(active & SupportTicket.assignee_id.is_(None)),
                _sum(active),
                _sum(SupportTicket.status.in_(DONE_STATUSES)),
            )
        )
    ).one()
    keys = ("needs_staff", "needs_staff_urgent", "mine", "unassigned", "active", "closed")
    return {key: int(value or 0) for key, value in zip(keys, row, strict=True)}
