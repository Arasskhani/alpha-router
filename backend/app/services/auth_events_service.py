"""Record every way a session begins, fails to begin, or ends.

One function, called from every authentication path. Two rules it inherits
from the writer it replaces (``_record_auth_event`` in ``app.api.auth``), both
of which turned out to matter:

* **Its own session, committed at once.** A failed login raises, and ``get_db``
  rolls the request transaction back — which would take the record of the
  failure with it, exactly when it matters most.
* **It never raises.** A broken audit write must not turn a valid sign-in into
  a 500. It logs and returns.

Callers pass facts, not prose: a code from :data:`REASON_CODES`, and at most a
scrubbed provider message in ``reason_detail``. Nothing that arrived in the
request body is stored here — never a password, never a raw assertion.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_event import (
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_RATE_LIMITED,
    EVENT_LOGIN_SUCCESS,
    EVENT_LOGOUT,
    EVENT_SESSION_REVOKED,
    OUTCOME_FAILURE,
    OUTCOME_NONE,
    OUTCOME_SUCCESS,
    REASON_CODES,
    REASON_DETAIL_MAX_CHARS,
    SCOPE_ALL_SESSIONS,
    USER_AGENT_MAX_CHARS,
    AuthEvent,
)
from app.models.user import User

logger = logging.getLogger(__name__)

_OUTCOME_FOR_TYPE = {
    EVENT_LOGIN_SUCCESS: OUTCOME_SUCCESS,
    EVENT_LOGIN_FAILED: OUTCOME_FAILURE,
    EVENT_LOGIN_RATE_LIMITED: OUTCOME_FAILURE,
    EVENT_LOGOUT: OUTCOME_NONE,
    EVENT_SESSION_REVOKED: OUTCOME_NONE,
}


def _clip(value: Any, limit: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:limit] or None


def _request_facts(request: Request | None) -> tuple[str | None, str | None, str | None]:
    """(ip, user_agent, correlation_id) from the request, or Nones without one.

    ``session_revoked`` is sometimes raised by a scheduler or a directory sync
    with no request in hand; the row is still worth writing.
    """

    if request is None:
        return None, None, None
    from app.services.client_ip import resolve_client_ip
    from app.services.observability import correlation_id

    try:
        ip = resolve_client_ip(request)
    except Exception:  # noqa: BLE001 -- an address we cannot resolve is a NULL, not a failed login
        ip = None
    user_agent = _clip(request.headers.get("user-agent"), USER_AGENT_MAX_CHARS)
    return ip, user_agent, _clip(correlation_id(), 64)


def build_auth_event(
    *,
    event_type: str,
    user: User | None,
    username: str | None = None,
    reason_code: str | None = None,
    reason_detail: str | None = None,
    auth_method: str | None = None,
    session_id: str | None = None,
    scope: str | None = None,
    request: Request | None = None,
    occurred_at: dt.datetime | None = None,
) -> AuthEvent:
    """The row, not yet added to a session. Separate so tests and the backfill can use it."""

    if event_type not in _OUTCOME_FOR_TYPE:
        raise ValueError(f"unknown auth event type: {event_type}")
    if reason_code is not None and reason_code not in REASON_CODES:
        raise ValueError(f"unknown auth reason code: {reason_code}")
    if event_type in (EVENT_LOGOUT, EVENT_SESSION_REVOKED) and scope is None:
        # Both bump users.token_version, which ends every session everywhere.
        scope = SCOPE_ALL_SESSIONS

    ip, user_agent, correlation = _request_facts(request)
    return AuthEvent(
        occurred_at=occurred_at or dt.datetime.utcnow(),
        user_id=user.id if user is not None else None,
        # The name as the account has it; for a failed attempt at an account
        # that does not exist, the name as it was typed.
        username=_clip(user.username if user is not None else username, 255),
        event_type=event_type,
        outcome=_OUTCOME_FOR_TYPE[event_type],
        scope=scope,
        reason_code=reason_code,
        reason_detail=_clip(reason_detail, REASON_DETAIL_MAX_CHARS),
        auth_method=_clip(auth_method, 16),
        ip=_clip(ip, 64),
        user_agent=user_agent,
        session_id=_clip(session_id, 36),
        correlation_id=correlation,
    )


async def record_auth_event(
    *,
    event_type: str,
    user: User | None,
    username: str | None = None,
    reason_code: str | None = None,
    reason_detail: str | None = None,
    auth_method: str | None = None,
    session_id: str | None = None,
    scope: str | None = None,
    request: Request | None = None,
    db: AsyncSession | None = None,
) -> None:
    """Write one event in a session of its own. Never raises.

    ``db`` is accepted only so a caller already inside a transaction that it
    *wants* the row to share (the backfill, tests) can pass one; the
    authentication paths leave it None and get the independent session.
    """

    try:
        row = build_auth_event(
            event_type=event_type,
            user=user,
            username=username,
            reason_code=reason_code,
            reason_detail=reason_detail,
            auth_method=auth_method,
            session_id=session_id,
            scope=scope,
            request=request,
        )
        if db is not None:
            db.add(row)
            await db.flush()
            return
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as own:
            own.add(row)
            await own.commit()
    except Exception:  # noqa: BLE001 -- an audit write must never break a login
        logger.exception("Failed to record auth event type=%s user=%s", event_type, username)


def method_for(user: User | None, fallback: str = "local") -> str:
    """The provider the account authenticates with, as the row stores it."""

    provider = str(getattr(user, "auth_provider", "") or "").strip().lower()
    return provider if provider in ("local", "ldap", "saml", "oidc") else fallback
