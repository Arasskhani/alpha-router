"""The person's own Exchange mailbox (Connections): connect, mailboxes, action items and drafts.

The work is in ``app.services.exchange_mail_service`` and the rules in
``app.services.exchange_mail``; this module checks who is asking, turns the
request into those calls, commits with an Admin Logs row where one is due,
and answers each refusal as ``{"detail": {"code", "message"}}`` so the page
can say what went wrong.

A refusal is answered only after a commit: a failure the service noted on the
connection (a refused password turns it ``needs_password``, a Full Access
mailbox that can no longer be opened drops out) must outlive the request.

Admin Logs rows carry the login, mailbox addresses and counts, never a
password, a subject, a body or a recipient's address.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import exchange_mail as em
from app.services import exchange_mail_service as svc
from app.services.client_ip import resolve_client_ip
from app.services.security_audit import log_security_event

router = APIRouter(prefix="/api/mail", tags=["mail"])

ID_MAX = 2_147_483_647
#: A row id in a body or a path: 1..2147483647, so a larger number is a 422, never a database error.
RowId = Annotated[int, Field(ge=1, le=ID_MAX)]
PathId = Annotated[int, Path(ge=1, le=ID_MAX)]


class ConnectIn(BaseModel):
    # Checked by the service (``invalid_password``): a length limit here would echo the text back in a 422.
    password: str = ""


class ConnectionPatchIn(BaseModel):
    notify_enabled: bool


class MailboxIn(BaseModel):
    smtp: str = Field(default="", max_length=400)


class MailboxPatchIn(BaseModel):
    enabled: bool | None = None
    notify: bool | None = None


class NotifiedIn(BaseModel):
    ids: list[RowId] = Field(default_factory=list, max_length=svc.NOTIFIED_IDS_MAX)


class SendIn(BaseModel):
    change_key: str = Field(min_length=1, max_length=1024)


async def _answer(db: AsyncSession, error: em.MailError) -> NoReturn:
    """Keep what the service noted (a failure on the connection), then refuse."""
    await db.commit()
    raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message}) from error


async def _audit(db: AsyncSession, request: Request, user: User, action: str, detail: dict[str, Any]) -> None:
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action=action,
        resource_type="mail_connection",
        resource_id=str(user.id),
        detail=detail,
    )


async def _settings(db: AsyncSession = Depends(get_db)) -> em.ExchangeSettings:
    return await em.load_settings(db)


async def _connection_answer(db: AsyncSession, user: User) -> dict[str, Any]:
    connection = await em.get_connection(db, int(user.id))
    if connection is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_connected", "message": "You have not connected your mailbox."}
        )
    return await svc.connection_out(db, connection)


# --- the connection ---------------------------------------------------------------------------------------------


@router.get("/status")
async def mail_status(
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Whether the person may connect (and if not, why), their login, connection and open action items."""
    return await svc.status_out(db, user, settings)


@router.post("/connect")
async def connect(
    body: ConnectIn,
    request: Request,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Connect the mailbox, or give the connection a new password. The password is tried once.

    One at a time for the person, until committed (``connect_lock``); a first
    connect that loses the race to another worker answers 409
    ``connect_in_progress`` rather than failing on the unique key.
    """
    async with svc.connect_lock(int(user.id)):
        try:
            outcome = await svc.connect(db, user, body.password, settings)
            connection = outcome.connection
            await _audit(
                db,
                request,
                user,
                "mail_connected" if outcome.created else "mail_password_updated",
                {
                    "login": str(connection.login),
                    "mailbox": str(connection.primary_smtp),
                    "full_access_count": outcome.full_access_count,
                },
            )
            await db.commit()
        except em.MailError as error:
            await _answer(db, error)
        except IntegrityError:
            # Another worker stored this person's connection meanwhile (uq_mail_connections_user).
            await db.rollback()
            await _answer(db, svc.connect_in_progress())
    return await svc.connection_out(db, connection)


@router.patch("/connection")
async def update_connection(
    body: ConnectionPatchIn,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Turn the toasts about emails that need the person's action on or off."""
    try:
        connection = await svc.require_connection(db, user, settings)
    except em.MailError as error:
        await _answer(db, error)
    connection.notify_enabled = body.notify_enabled  # type: ignore[assignment]
    await db.commit()
    return await svc.connection_out(db, connection)


@router.delete("/connection")
async def disconnect(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Forget the connection, its mailboxes, refs, drafts and action items. Works whatever the settings say."""
    connection = await em.get_connection(db, int(user.id))
    mailbox = str(connection.primary_smtp) if connection is not None else ""
    if await em.delete_connection(db, int(user.id)):
        await _audit(db, request, user, "mail_disconnected", {"by": "self", "mailbox": mailbox})
    await db.commit()
    return {"ok": True}


# --- mailboxes ----------------------------------------------------------------------------------------------------


@router.post("/mailboxes")
async def add_mailbox(
    body: MailboxIn,
    request: Request,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add a mailbox the person has Full Access to, after a test read of its Inbox."""
    try:
        row = await svc.add_mailbox(db, user, settings, body.smtp)
    except em.MailError as error:
        await _answer(db, error)
    await _audit(db, request, user, "mail_mailbox_added", {"mailbox": str(row.smtp), "source": "manual"})
    await db.commit()
    return await _connection_answer(db, user)


@router.post("/mailboxes/rediscover")
async def rediscover_mailboxes(
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ask Autodiscover again: new Full Access mailboxes are added, those no longer listed go."""
    try:
        await svc.rediscover(db, user, settings)
    except em.MailError as error:
        await _answer(db, error)
    await db.commit()
    return await _connection_answer(db, user)


@router.patch("/mailboxes/{mailbox_id}")
async def update_mailbox(
    mailbox_id: PathId,
    body: MailboxPatchIn,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Use a mailbox in the chat or not (``enabled``), and watch its Inbox for action or not (``notify``)."""
    try:
        await svc.update_mailbox(db, user, settings, mailbox_id, enabled=body.enabled, notify=body.notify)
    except em.MailError as error:
        await _answer(db, error)
    await db.commit()
    return await _connection_answer(db, user)


@router.delete("/mailboxes/{mailbox_id}")
async def remove_mailbox(
    mailbox_id: PathId,
    request: Request,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Take a Full Access mailbox off the list (the own mailbox stays)."""
    try:
        smtp = await svc.remove_mailbox(db, user, settings, mailbox_id)
    except em.MailError as error:
        await _answer(db, error)
    await _audit(db, request, user, "mail_mailbox_removed", {"mailbox": smtp})
    await db.commit()
    return await _connection_answer(db, user)


# --- action items -------------------------------------------------------------------------------------------------


@router.get("/action-items")
async def list_action_items(
    state: Literal["open", "all"] = Query("open"),
    limit: int = Query(50, ge=1, le=svc.ACTION_LIST_MAX),
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emails that need the person's action, newest first (``open``: not yet dismissed or done)."""
    try:
        await svc.require_eligible(db, user, settings)
    except em.MailError as error:
        await _answer(db, error)
    return await svc.list_action_items(db, int(user.id), state=state, limit=limit)


@router.post("/action-items/notified")
async def mark_notified(
    body: NotifiedIn,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """The toasts for these items were shown: they are not shown again."""
    try:
        await svc.require_eligible(db, user, settings)
    except em.MailError as error:
        await _answer(db, error)
    await svc.mark_notified(db, int(user.id), body.ids)
    await db.commit()
    return {"ok": True}


async def _close(
    db: AsyncSession, user: User, settings: em.ExchangeSettings, item_id: int, status: Literal["dismissed", "done"]
) -> dict[str, Any]:
    try:
        await svc.require_eligible(db, user, settings)
        item = await svc.close_action_item(db, int(user.id), item_id, status)
    except em.MailError as error:
        await _answer(db, error)
    await db.commit()
    return svc.action_item_out(item)


@router.post("/action-items/{item_id}/dismiss")
async def dismiss_action_item(
    item_id: PathId,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _close(db, user, settings, item_id, "dismissed")


@router.post("/action-items/{item_id}/done")
async def done_action_item(
    item_id: PathId,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _close(db, user, settings, item_id, "done")


@router.post("/action-items/{item_id}/ask")
async def ask_about_action_item(
    item_id: PathId,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """The text a new chat about this email starts with, naming it by a ref the chat's mail tools know."""
    try:
        prompt = await svc.ask_prompt(db, user, settings, item_id)
    except em.MailError as error:
        await _answer(db, error)
    await db.commit()
    return {"prompt": prompt}


# --- drafts -------------------------------------------------------------------------------------------------------


@router.get("/drafts/{draft_id}")
async def read_draft(
    draft_id: PathId,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The draft as it is now in Exchange, for Review & send (the row only, once it is not a draft)."""
    try:
        answer = await svc.read_draft(db, user, settings, draft_id)
    except em.MailError as error:
        await _answer(db, error)
    await db.commit()
    return answer


@router.post("/drafts/{draft_id}/send")
async def send_draft(
    draft_id: PathId,
    body: SendIn,
    request: Request,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Send the draft as the person read it; only the person ever sends, never the model."""
    try:
        outcome = await svc.send_draft(db, user, settings, draft_id, body.change_key)
    except em.MailError as error:
        await _answer(db, error)
    if outcome.error is not None:
        await _answer(db, outcome.error)
    await _audit(db, request, user, "mail_draft_sent", svc.sent_audit_detail(outcome.draft))
    await db.commit()
    return svc.draft_out(outcome.draft)


@router.post("/drafts/{draft_id}/discard")
async def discard_draft(
    draft_id: PathId,
    user: User = Depends(get_current_user),
    settings: em.ExchangeSettings = Depends(_settings),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Move the draft to Deleted Items."""
    try:
        draft = await svc.discard_draft(db, user, settings, draft_id)
    except em.MailError as error:
        await _answer(db, error)
    await db.commit()
    return svc.draft_out(draft)
