"""Admin › Integrations › Exchange EWS: settings, Test connection, who may connect, the people connected.

- Reading (settings, access, people, overview): the Exchange EWS menu
  (``require_exchange_ews``), so Read Only Super Admin sees everything.
- Changing anything, and Test connection (it signs in to Exchange with a
  typed password): the menu with write (``require_exchange_ews_write``).

The work is in ``app.services.exchange_mail_service``. Every change commits
with an Admin Logs row; the rows name the settings that changed (never the
CA text), the login tested and whether it worked (never the password), and
the person disconnected.
"""

from __future__ import annotations

from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_chat_tools import ChatToolAccessBody, save_tool_access
from app.api.deps import require_exchange_ews, require_exchange_ews_write
from app.database import get_db
from app.models.mail_connection import MailConnection
from app.models.user import User
from app.services import exchange_mail as em
from app.services import exchange_mail_service as svc
from app.services.chat_tool_access_service import get_chat_tool_access
from app.services.client_ip import resolve_client_ip
from app.services.security_audit import log_security_event

router = APIRouter(prefix="/api/admin/exchange-ews", tags=["exchange-ews"])

ID_MAX = 2_147_483_647
PathId = Annotated[int, Path(ge=1, le=ID_MAX)]
LOGIN_MAX = 320
PASSWORD_MAX = 256
PAGE_MAX = 200
OFFSET_MAX = 1_000_000


class ConnectionTestIn(BaseModel):
    # Lengths are checked below: a limit here would echo the password back in FastAPI's 422.
    login: str = ""
    password: str = ""
    email: str | None = None


def _refuse(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _answer(error: em.MailError) -> NoReturn:
    raise _refuse(error.code, error.message, error.status_code) from error


async def _audit(
    db: AsyncSession, request: Request, actor: User, action: str, resource_type: str, resource_id: Any, detail: dict
) -> None:
    await log_security_event(
        db,
        actor=actor,
        actor_ip=resolve_client_ip(request),
        action=action,
        resource_type=resource_type,
        resource_id=None if resource_id is None else str(resource_id),
        detail=detail,
    )


async def _settings_answer(db: AsyncSession, viewer: User, settings: em.ExchangeSettings) -> dict[str, Any]:
    defaults = await em.directory_defaults(db)
    return {
        "settings": settings.as_dict(),
        "directory": {
            "netbios_domain": defaults.netbios_domain,
            "dns_domain": defaults.dns_domain,
            "available": defaults.available,
        },
        "example_login": svc.example_login(viewer, settings, defaults),
        "ews_endpoint": settings.ews_endpoint(),
        "autodiscover_endpoint": settings.autodiscover_endpoint(),
    }


# --- settings -----------------------------------------------------------------------------------------------------


@router.get("/settings")
async def read_settings(
    db: AsyncSession = Depends(get_db), viewer: User = Depends(require_exchange_ews)
) -> dict[str, Any]:
    """The settings, the domain the LDAP settings imply, and what the login looks like with them."""
    return await _settings_answer(db, viewer, await em.load_settings(db))


@router.put("/settings")
async def put_settings(
    request: Request,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_exchange_ews_write),
) -> dict[str, Any]:
    """Save the settings: what is sent is laid over what is saved, then checked as a whole.

    Turning the feature off deletes nothing: connections wait, unused, until it is on again.
    """
    current = await em.load_settings(db)
    try:
        saved = em.validate_settings({**current.as_dict(), **body})
    except em.MailError as error:
        _answer(error)
    changed = em.changed_keys(current, saved)
    await em.save_settings(db, saved)
    if changed:
        await _audit(
            db, request, actor, "exchange_ews_settings_updated", "exchange_ews", em.SETTINGS_KEY, {"changed": changed}
        )
    await db.commit()
    return await _settings_answer(db, actor, saved)


@router.post("/test")
async def test_connection(
    body: ConnectionTestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_exchange_ews_write),
) -> dict[str, Any]:
    """Sign in with a typed login and password using the saved settings; step by step, nothing stored."""
    login = body.login.strip()
    if not login or len(login) > LOGIN_MAX:
        raise _refuse("invalid_test", f"Type the login to test (up to {LOGIN_MAX} characters).", 422)
    if not body.password or len(body.password) > PASSWORD_MAX:
        raise _refuse("invalid_test", f"Type the password (up to {PASSWORD_MAX} characters).", 422)
    email = (body.email or "").strip()[:LOGIN_MAX]
    try:
        await svc.check_test_rate(int(actor.id))
    except em.MailError as error:
        _answer(error)
    result = await svc.run_test(await em.load_settings(db), login=login, password=body.password, email=email)
    await _audit(db, request, actor, "exchange_ews_tested", "exchange_ews", None, {"login": login, "ok": result["ok"]})
    await db.commit()
    return result


# --- who may connect ----------------------------------------------------------------------------------------------


@router.get("/access")
async def get_access(db: AsyncSession = Depends(get_db), _: User = Depends(require_exchange_ews)) -> dict[str, Any]:
    """The ``exchange_mail`` entry of the chat tool registry: who may connect (AD accounts only, whatever it says)."""
    return await get_chat_tool_access(db, em.TOOL_KEY)


@router.put("/access")
async def put_access(
    body: ChatToolAccessBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_exchange_ews_write),
) -> dict[str, Any]:
    """Replace who may connect, exactly as the Chat Tools page does for this tool."""
    saved = await save_tool_access(db, request, actor, em.TOOL_KEY, body)
    await db.commit()
    return saved


# --- people -------------------------------------------------------------------------------------------------------


@router.get("/connections")
async def list_connections(
    q: str = Query("", max_length=400),
    status: str = Query(""),
    limit: int = Query(50, ge=1, le=PAGE_MAX),
    offset: int = Query(0, ge=0, le=OFFSET_MAX),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_exchange_ews),
) -> dict[str, Any]:
    """The people who connected a mailbox, newest first; search on name, username, email or mailbox."""
    status = status.strip()
    if status and status not in svc.CONNECTION_STATUSES:
        raise _refuse("invalid_filter", f"status must be one of {', '.join(svc.CONNECTION_STATUSES)}.", 422)
    return await svc.list_connections(db, q=q, status=status, limit=limit, offset=offset)


@router.delete("/connections/{connection_id}")
async def disconnect_person(
    connection_id: PathId,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_exchange_ews_write),
) -> dict[str, bool]:
    """Disconnect someone: their password, mailboxes, refs, drafts and action items are forgotten."""
    connection = await db.get(MailConnection, connection_id)
    if connection is None:
        raise _refuse("not_found", "Connection not found.", 404)
    user_id = int(connection.user_id)
    mailbox = str(connection.primary_smtp)
    await em.delete_connection(db, user_id)
    await _audit(
        db,
        request,
        actor,
        "mail_disconnected",
        "mail_connection",
        user_id,
        {"by": "admin", "user_id": user_id, "mailbox": mailbox},
    )
    await db.commit()
    return {"ok": True}


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db), _: User = Depends(require_exchange_ews)) -> dict[str, Any]:
    """Connections by status, AD accounts that could connect, and the last week's action items and drafts."""
    return await svc.overview(db, await em.load_settings(db))
