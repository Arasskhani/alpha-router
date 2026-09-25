"""Tokens for the browser extension: connect, refresh, authenticate, revoke.

The connect flow is OAuth's authorization code with PKCE, run in a normal tab
(so the user's session, SSO and two-factor sign-in work as they always do):

1. The web app's consent page, for a signed-in user, asks for a code bound to
   that user, the extension's ``connected.html`` and the PKCE challenge
   (:func:`create_auth_code`). The code lives two minutes and is used once.
2. The extension redeems it with its verifier (:func:`redeem_auth_code`) and
   the API opens a session (:func:`create_session`): an access token (one
   hour) and a refresh token (30 days of disuse, 180 days at most).
3. Refreshing rotates the refresh token (:func:`refresh_session`). The token
   just replaced still works for two minutes for the refresh that replaced
   it, so a response lost on the way can be retried; presented by anyone
   else, or after that - or any older token of the same session - it can only
   be a stolen copy, and the session ends.

Each refresh carries an ``attempt``: a random name the extension gives it and
repeats on its own retries. A refresh token spent by the same attempt always
turns into the same new pair (:func:`next_pair`, keyed with the server's
secret). So a retry, or a retry racing the request it repeats, receives
exactly the tokens the first one did: whichever response the extension keeps,
it keeps a working pair, and a session never forks into two. Another attempt
would get another access token, so the session's current one tells which
refresh replaced the token. That is what gives a copy away: whoever else holds
the tokens sees their access token stop working when the extension refreshes,
and presenting the replaced refresh token then ends the session instead of
handing them the extension's new pair.

Tokens are opaque strings stored only as SHA-256 hashes - never JWTs, which
this product checks for their signature alone. Every request looks its token
up (:func:`authenticate`), which is also where a sign-out everywhere (a higher
``token_version``) and a deleted account end the session.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, cast

import redis.asyncio as redis_async
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import PRODUCT_SLUG
from app.config import get_settings
from app.core.redis_client import get_redis
from app.database import AsyncSessionLocal
from app.models.extension import DEVICE_NAME_MAX_CHARS, USER_AGENT_MAX_CHARS, ExtensionSession
from app.models.user import User
from app.services.observability import increment
from app.services.security_audit import log_security_event

logger = logging.getLogger(__name__)

ACCESS_TOKEN_PREFIX = f"{PRODUCT_SLUG}-ext-at-"
REFRESH_TOKEN_PREFIX = f"{PRODUCT_SLUG}-ext-rt-"

ACCESS_TOKEN_LIFETIME = datetime.timedelta(hours=1)
REFRESH_IDLE_LIFETIME = datetime.timedelta(days=30)
SESSION_MAX_LIFETIME = datetime.timedelta(days=180)
#: How long a replaced refresh token still works: longer than the extension's
#: refresh timeout plus a retry. Only for the refresh that replaced it (the
#: same attempt, see next_pair); anyone else presenting it ends the session.
REFRESH_GRACE = datetime.timedelta(minutes=2)
#: How many rotations back a returning refresh token is still recognised as
#: this session's - weeks of normal use - so that any old token, not only the
#: one just replaced, ends the session when it comes back.
REUSE_LOOKBACK = 256
#: How long an ended connection (revoked, or expired) is kept - its device
#: name, last address and browser - before the nightly cleanup deletes it.
ENDED_SESSION_RETENTION = datetime.timedelta(days=90)
_PURGE_BATCH = 500
#: last_used_at is written at most this often per session.
TOUCH_INTERVAL = datetime.timedelta(minutes=1)

CODE_TTL_SECONDS = 120
_CODE_KEY_PREFIX = "ext:code:"

_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")

REVOKED_BY_USER = "user"
REVOKED_REFRESH_REUSE = "refresh_reuse"
REVOKED_TOKEN_VERSION = "token_version"

#: The security audit trail's names for what happens to a connected browser.
AUDIT_RESOURCE = "extension_session"
AUDIT_CONNECTED = "extension_connected"
AUDIT_DISCONNECTED = "extension_disconnected"
AUDIT_SESSION_REVOKED = "extension_session_revoked"

_ROTATION_CONTEXT = b"alpharouter extension token rotation"


class ExtensionTokenError(Exception):
    """A token or code the server will not honour; ``code`` is what the API reports."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _invalid_grant(message: str) -> ExtensionTokenError:
    return ExtensionTokenError("invalid_grant", message)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


#: The code store's clock; a name of its own so tests can move it without
#: moving the event loop's.
_monotonic = time.monotonic


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_extension_access_token(token: str | None) -> bool:
    return bool(token) and str(token).startswith(ACCESS_TOKEN_PREFIX)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def _rotation_key() -> bytes:
    return hmac.new(get_settings().secret_key.encode("utf-8"), _ROTATION_CONTEXT, hashlib.sha256).digest()


def _derive(key: bytes, label: bytes, refresh_token: str) -> str:
    return _b64url(hmac.new(key, label + b"\0" + refresh_token.encode("utf-8"), hashlib.sha256).digest())


def next_pair(refresh_token: str, attempt: str | None = None) -> tuple[str, str]:
    """The access and refresh token that ``refresh_token`` turns into when refresh ``attempt`` spends it.

    Always the same two for the same token and attempt, and keyed with
    ``SECRET_KEY``, so nobody holding a token can work out its successor.

    The access token depends on the attempt as well: spent by another attempt,
    the token turns into another access token, so the session's current one
    says whether a refresh presenting the replaced token is the one that
    replaced it. The refresh token depends on the token alone, so that a
    session's refresh tokens stay one chain an old token can be followed along
    (:func:`_successor_hashes`), whichever attempts spent them. Without an
    attempt - an extension from before there were attempts - the access token
    comes from the token alone too.
    """
    key = _rotation_key()
    access = (
        _derive(key, b"access", refresh_token)
        if attempt is None
        else _derive(key, b"access for attempt", f"{refresh_token}\0{attempt}")
    )
    return ACCESS_TOKEN_PREFIX + access, REFRESH_TOKEN_PREFIX + _derive(key, b"refresh", refresh_token)


def _successor_hashes(refresh_token: str, steps: int) -> list[str]:
    """The hashes of the refresh tokens ``refresh_token`` turns into, one rotation after another."""
    key = _rotation_key()
    token, hashes = refresh_token, []
    for _ in range(steps):
        token = REFRESH_TOKEN_PREFIX + _derive(key, b"refresh", token)
        hashes.append(token_hash(token))
    return hashes


def pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256: base64url(SHA-256(verifier)) without padding."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def is_valid_challenge(challenge: str | None) -> bool:
    return bool(challenge) and bool(_CHALLENGE_RE.match(str(challenge)))


def verify_pkce(verifier: str | None, challenge: str) -> bool:
    if not verifier or not _VERIFIER_RE.match(verifier):
        return False
    return hmac.compare_digest(pkce_challenge(verifier), challenge)


def clean_device_name(raw: str | None) -> str:
    """Printable, one line, at most 64 characters: it is shown in lists."""
    text = "".join(
        " " if ch.isspace() else ch for ch in (raw or "") if ch.isspace() or unicodedata.category(ch)[0] != "C"
    )
    return " ".join(text.split())[:DEVICE_NAME_MAX_CHARS].rstrip()


# --- authorization codes -------------------------------------------------

_mem_lock = asyncio.Lock()
_mem_codes: dict[str, tuple[str, float]] = {}


def _code_key(code: str) -> str:
    # Keyed by the code's hash, so the store never holds a usable code.
    return _CODE_KEY_PREFIX + token_hash(code)


async def create_auth_code(*, user: User, redirect_uri: str, code_challenge: str) -> str:
    """A one-time code for the consent page to hand to the extension's page."""
    code = secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "user_id": int(user.id),
            "token_version": int(user.token_version or 0),
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
        }
    )
    client: redis_async.Redis = get_redis()
    try:
        await client.set(_code_key(code), payload, ex=CODE_TTL_SECONDS)
        return code
    except Exception:  # noqa: BLE001 -- a Redis outage degrades to the per-process store
        increment("redis_fallback")
    async with _mem_lock:
        now = _monotonic()
        for key in [k for k, (_, expires) in _mem_codes.items() if expires <= now]:
            _mem_codes.pop(key, None)
        _mem_codes[_code_key(code)] = (payload, now + CODE_TTL_SECONDS)
    return code


async def consume_auth_code(code: str | None) -> dict[str, Any] | None:
    """The code's payload, once; None for an unknown, used or expired code."""
    if not code:
        return None
    key = _code_key(code)
    raw: Any = None
    client: redis_async.Redis = get_redis()
    try:
        pipe = client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        raw, _deleted = await pipe.execute()
    except Exception:  # noqa: BLE001 -- a Redis outage degrades to the per-process store
        increment("redis_fallback")
    if not raw:
        async with _mem_lock:
            entry = _mem_codes.pop(key, None)
        if entry is None or entry[1] <= _monotonic():
            return None
        raw = entry[0]
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def redeem_auth_code(
    db: AsyncSession,
    *,
    code: str | None,
    code_verifier: str | None,
    redirect_uri: str | None,
) -> User:
    """The user a connect code was issued to; raises ExtensionTokenError(invalid_grant).

    The code is spent whatever happens next, so a wrong verifier cannot be
    retried against it.
    """
    payload = await consume_auth_code(code)
    if payload is None:
        raise _invalid_grant("The connect code is unknown, used or expired.")
    if not redirect_uri or payload.get("redirect_uri") != redirect_uri:
        raise _invalid_grant("The connect code was issued for another address.")
    if not verify_pkce(code_verifier, str(payload.get("code_challenge") or "")):
        raise _invalid_grant("The code verifier does not match.")
    try:
        user_id = int(payload["user_id"])
        issued_version = int(payload.get("token_version") or 0)
    except (KeyError, TypeError, ValueError):
        raise _invalid_grant("The connect code is unknown, used or expired.") from None
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise _invalid_grant("This account cannot connect a browser.")
    if int(user.token_version or 0) > issued_version:
        raise _invalid_grant("You signed out after allowing this browser; connect it again.")
    return user


# --- sessions ------------------------------------------------------------


@dataclass(frozen=True)
class TokenPair:
    session_id: str
    access_token: str
    refresh_token: str
    expires_in: int

    def as_response(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "refresh_token": self.refresh_token,
            "session_id": self.session_id,
        }


_ACCESS_SECONDS = int(ACCESS_TOKEN_LIFETIME.total_seconds())


async def create_session(
    db: AsyncSession,
    *,
    user: User,
    device_name: str | None,
    user_agent: str | None,
    ip: str | None,
) -> TokenPair:
    """A new connected browser; the caller commits."""
    now = _now()
    access = _new_token(ACCESS_TOKEN_PREFIX)
    refresh = _new_token(REFRESH_TOKEN_PREFIX)
    absolute = now + SESSION_MAX_LIFETIME
    session = ExtensionSession(
        id=str(uuid.uuid4()),
        user_id=int(user.id),
        device_name=clean_device_name(device_name),
        access_token_hash=token_hash(access),
        access_expires_at=now + ACCESS_TOKEN_LIFETIME,
        refresh_token_hash=token_hash(refresh),
        refresh_expires_at=min(now + REFRESH_IDLE_LIFETIME, absolute),
        absolute_expires_at=absolute,
        token_version=int(user.token_version or 0),
        created_at=now,
        last_used_at=now,
        last_ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:USER_AGENT_MAX_CHARS] or None,
    )
    db.add(session)
    await db.flush()
    return TokenPair(session_id=str(session.id), access_token=access, refresh_token=refresh, expires_in=_ACCESS_SECONDS)


def _session_is_open(session: ExtensionSession, now: datetime.datetime) -> bool:
    return (
        session.revoked_at is None
        and session.absolute_expires_at > now  # type: ignore[operator]
        and session.refresh_expires_at > now  # type: ignore[operator]
    )


async def _user_still_holds(db: AsyncSession, session: ExtensionSession) -> User | None:
    """The session's user, or None when the account is gone or signed out everywhere since."""
    user = await db.get(User, session.user_id)
    if user is None or user.deleted_at is not None:
        return None
    if int(user.token_version or 0) > int(session.token_version or 0):
        return None
    return user


#: For every UPDATE here. By default SQLAlchemy applies an UPDATE's values to
#: matching objects already loaded, judged in Python - including a rotation
#: that lost its race and changed no row, which would leave the loaded session
#: holding a hash that was never issued. Reads use populate_existing instead.
_NO_SYNC = {"synchronize_session": False}


def _rowcount(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def revoke_session(
    db: AsyncSession,
    session_id: str,
    *,
    reason: str,
    user_id: int | None = None,
) -> bool:
    """End a session (only the user's own, when ``user_id`` is given); the caller commits."""
    query = update(ExtensionSession).where(ExtensionSession.id == session_id, ExtensionSession.revoked_at.is_(None))
    if user_id is not None:
        query = query.where(ExtensionSession.user_id == user_id)
    result = await db.execute(query.values(revoked_at=_now(), revoked_reason=reason[:32]), execution_options=_NO_SYNC)
    return _rowcount(result) > 0


async def _revoke_now(session_id: str, *, reason: str, ip: str | None = None) -> None:
    """End a session in a transaction of its own: the request that found out is refused, not committed.

    A replayed refresh token is a security event - someone else holds a copy -
    so that revocation is audited with the address it came from.
    """
    try:
        async with AsyncSessionLocal() as db:
            revoked = await revoke_session(db, session_id, reason=reason)
            if revoked and reason == REVOKED_REFRESH_REUSE:
                row = await db.get(ExtensionSession, session_id)
                owner = await db.get(User, row.user_id) if row is not None else None
                await log_security_event(
                    db,
                    actor=owner,
                    actor_ip=ip,
                    action=AUDIT_SESSION_REVOKED,
                    resource_type=AUDIT_RESOURCE,
                    resource_id=session_id,
                    detail={"reason": reason, "device_name": row.device_name if row is not None else None},
                )
            await db.commit()
    except Exception:  # noqa: BLE001 -- the request is refused either way; the next one tries again
        logger.warning("could not mark extension session %s revoked", session_id, exc_info=True)


async def _session_where(db: AsyncSession, condition: Any) -> ExtensionSession | None:
    query = select(ExtensionSession).where(condition).execution_options(populate_existing=True)
    return (await db.execute(query)).scalars().first()


async def _session_of_an_older_token(db: AsyncSession, refresh_token: str) -> ExtensionSession | None:
    """The live session a refresh token replaced several rotations ago, if any.

    Tokens form a chain (:func:`next_pair`), so walking forward from the one
    presented finds the session's current or last-replaced token when the
    presented one is an ancestor. A random string walks into nothing.
    """
    hashes = _successor_hashes(refresh_token, REUSE_LOOKBACK)
    query = (
        select(ExtensionSession)
        .where(
            ExtensionSession.revoked_at.is_(None),
            or_(
                ExtensionSession.refresh_token_hash.in_(hashes),
                ExtensionSession.prior_refresh_token_hash.in_(hashes),
            ),
        )
        .limit(1)
    )
    return (await db.execute(query)).scalars().first()


async def _require_usable(db: AsyncSession, session: ExtensionSession, now: datetime.datetime) -> None:
    """Refuse a refresh for a session that has ended.

    A disabled account still refreshes: its tokens reach nothing but the
    feature list and the disconnect call (app.api.deps), and re-enabling the
    account brings its browsers back - as re-enabling the extension does.
    Disabling from the admin pages signs the user out everywhere anyway.
    """
    if not _session_is_open(session, now):
        raise _invalid_grant("This browser's connection has ended.")
    if await _user_still_holds(db, session) is None:
        await _revoke_now(str(session.id), reason=REVOKED_TOKEN_VERSION)
        raise _invalid_grant("You signed out; connect this browser again.")


async def refresh_session(
    db: AsyncSession, refresh_token: str | None, *, attempt: str | None = None, ip: str | None = None
) -> TokenPair:
    """The next pair for a refresh token; raises ExtensionTokenError(invalid_grant). The caller commits.

    ``attempt`` is the extension's name for this refresh, the same on each of
    its retries; the pair depends on it (:func:`next_pair`).
    """
    if not refresh_token or not refresh_token.startswith(REFRESH_TOKEN_PREFIX):
        raise _invalid_grant("Unknown refresh token.")
    presented = token_hash(refresh_token)
    access, refresh = next_pair(refresh_token, attempt)
    for _ in range(3):
        current = await _session_where(db, ExtensionSession.refresh_token_hash == presented)
        if current is not None:
            await _require_usable(db, current, _now())
            # Read the clock for the write itself: the grace starts when the
            # token is replaced, not when a request that waited for a
            # database connection began.
            now = _now()
            result = await db.execute(
                update(ExtensionSession)
                .where(
                    ExtensionSession.id == current.id,
                    ExtensionSession.revoked_at.is_(None),
                    ExtensionSession.refresh_token_hash == presented,
                )
                .values(
                    access_token_hash=token_hash(access),
                    access_expires_at=now + ACCESS_TOKEN_LIFETIME,
                    refresh_token_hash=token_hash(refresh),
                    refresh_expires_at=min(now + REFRESH_IDLE_LIFETIME, current.absolute_expires_at),
                    prior_refresh_token_hash=presented,
                    prior_refresh_valid_until=now + REFRESH_GRACE,
                ),
                execution_options=_NO_SYNC,
            )
            if _rowcount(result) == 1:
                return TokenPair(str(current.id), access, refresh, _ACCESS_SECONDS)
            # Another request with this token changed the row first. The next
            # pass takes the grace path: this very pair when that request was
            # the same attempt (a retry racing its first try), and the end of
            # the session when it was anyone else.
            continue
        replaced = await _session_where(db, ExtensionSession.prior_refresh_token_hash == presented)
        if replaced is None:
            older = await _session_of_an_older_token(db, refresh_token)
            if older is not None:
                await _revoke_now(str(older.id), reason=REVOKED_REFRESH_REUSE, ip=ip)
                raise _invalid_grant("This browser's connection was ended for safety.")
            raise _invalid_grant("Unknown refresh token.")
        if replaced.revoked_at is not None:
            raise _invalid_grant("Unknown refresh token.")
        now = _now()
        if replaced.prior_refresh_valid_until is None or replaced.prior_refresh_valid_until < now:  # type: ignore[operator]
            # A replaced token, well after it was replaced: someone else holds a copy.
            await _revoke_now(str(replaced.id), reason=REVOKED_REFRESH_REUSE, ip=ip)
            raise _invalid_grant("This browser's connection was ended for safety.")
        await _require_usable(db, replaced, now)
        if (replaced.access_token_hash, replaced.refresh_token_hash) != (token_hash(access), token_hash(refresh)):
            # Not the pair this attempt turns the token into: another attempt
            # replaced it, so whoever presents it now holds a copy - likely
            # someone who saw their copy of the access token stop working when
            # the extension refreshed. (SECRET_KEY changing inside the grace
            # window lands here too, and ends the session as well.)
            await _revoke_now(str(replaced.id), reason=REVOKED_REFRESH_REUSE, ip=ip)
            raise _invalid_grant("This browser's connection was ended for safety.")
        remaining = int((replaced.access_expires_at - now).total_seconds())  # type: ignore[operator]
        # Nothing is written: the grace window never extends itself.
        return TokenPair(str(replaced.id), access, refresh, max(0, remaining))
    raise _invalid_grant("The connection changed while it was being refreshed; try again.")


@dataclass(frozen=True)
class Authenticated:
    session: ExtensionSession
    user: User


async def authenticate(db: AsyncSession, access_token: str) -> Authenticated:
    """The session and user an access token stands for; raises ExtensionTokenError.

    Codes: ``invalid_token`` (unknown, including one a refresh replaced),
    ``expired`` (refresh and try again) and ``revoked`` (connect again).
    """
    session = await _session_where(db, ExtensionSession.access_token_hash == token_hash(access_token))
    if session is None:
        raise ExtensionTokenError("invalid_token", "Unknown access token.")
    now = _now()
    if session.revoked_at is not None:
        raise ExtensionTokenError("revoked", "This browser was disconnected.")
    if session.absolute_expires_at <= now:  # type: ignore[operator]
        raise ExtensionTokenError("revoked", "This browser's connection has ended; connect it again.")
    if session.access_expires_at <= now:  # type: ignore[operator]
        raise ExtensionTokenError("expired", "The access token has expired.")
    user = await _user_still_holds(db, session)
    if user is None:
        await _revoke_now(str(session.id), reason=REVOKED_TOKEN_VERSION)
        raise ExtensionTokenError("revoked", "You signed out; connect this browser again.")
    return Authenticated(session=session, user=user)


def needs_touch(session: ExtensionSession, now: datetime.datetime | None = None) -> bool:
    last = cast("datetime.datetime | None", session.last_used_at)
    return last is None or last < (now or _now()) - TOUCH_INTERVAL


async def touch_session(session_id: str, *, ip: str | None) -> None:
    """Record use, at most once a minute, in a transaction of its own.

    Not the request's: that commits only when the request ends, and a chat
    stream lasts minutes - holding the row's lock that long would make a
    refresh of the same session wait for it. A failure costs a stale "last
    used", never the request.
    """
    now = _now()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ExtensionSession)
                .where(
                    ExtensionSession.id == session_id,
                    ExtensionSession.last_used_at.is_(None) | (ExtensionSession.last_used_at < now - TOUCH_INTERVAL),
                )
                .values(last_used_at=now, last_ip=(ip or "")[:64] or None),
                execution_options=_NO_SYNC,
            )
            await db.commit()
    except Exception:  # noqa: BLE001 -- bookkeeping only
        logger.debug("could not record extension session use", exc_info=True)


_touches: set[asyncio.Task[None]] = set()


def schedule_touch(session_id: str, *, ip: str | None) -> None:
    """Record use beside the request instead of inside it.

    The request already holds a database connection; waiting for a second one
    would stall authentication whenever the pool is busy. Kept referenced until
    done, so the task is not collected half-way.
    """
    task = asyncio.get_running_loop().create_task(touch_session(session_id, ip=ip))
    _touches.add(task)
    task.add_done_callback(_touches.discard)


async def wait_for_touches() -> None:
    """Let every scheduled touch finish (tests, and an orderly shutdown)."""
    while _touches:
        await asyncio.gather(*list(_touches), return_exceptions=True)


async def list_sessions(db: AsyncSession, user: User) -> list[ExtensionSession]:
    """The user's connected browsers that can still be used, newest first."""
    now = _now()
    rows = (
        (
            await db.execute(
                select(ExtensionSession)
                .where(
                    ExtensionSession.user_id == int(user.id),
                    ExtensionSession.revoked_at.is_(None),
                    ExtensionSession.refresh_expires_at > now,
                    ExtensionSession.absolute_expires_at > now,
                    # A sign-out everywhere since connecting ended it, even if
                    # no request has come in to mark it revoked yet.
                    ExtensionSession.token_version >= int(user.token_version or 0),
                )
                .order_by(ExtensionSession.created_at.desc(), ExtensionSession.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def purge_ended_sessions(db: AsyncSession) -> int:
    """Delete connections that ended more than 90 days ago; how many went.

    Ended means revoked, idle past the refresh lifetime, or past the absolute
    limit - a session a sign-out everywhere made unusable ends by idling out
    too. In batches, committing each, so the first run on a busy installation
    never holds one long transaction.
    """
    cutoff = _now() - ENDED_SESSION_RETENTION
    ended = or_(
        ExtensionSession.revoked_at < cutoff,
        ExtensionSession.refresh_expires_at < cutoff,
        ExtensionSession.absolute_expires_at < cutoff,
    )
    deleted = 0
    while True:
        ids = list((await db.execute(select(ExtensionSession.id).where(ended).limit(_PURGE_BATCH))).scalars().all())
        if not ids:
            break
        result = await db.execute(
            delete(ExtensionSession).where(ExtensionSession.id.in_(ids)), execution_options=_NO_SYNC
        )
        deleted += _rowcount(result)
        await db.commit()
        if len(ids) < _PURGE_BATCH:
            break
    return deleted
