"""Per-user chat history in normalized PostgreSQL/SQLite tables."""

from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text_safety import strip_nul
from app.config import get_settings
from app.models.chat import (
    ChatFolder,
    ChatMessage,
    ChatMessageFeedback,
    ChatSession,
    UserChatPrefs,
)
from app.services.chat_markers import (
    ATTACHMENT_MESSAGE_PREFIX,
    IMAGE_MESSAGE_PREFIX,
    IMAGE_PENDING_MARKER,
    SPEECH_MESSAGE_PREFIX,
    SPEECH_PENDING_MARKER,
    VIDEO_MESSAGE_PREFIX,
    VIDEO_PENDING_MARKER,
)
from app.services.private_mode_service import (
    PrivateModePersistenceError,
    assert_session_persistence_allowed,
)
import contextlib

logger = logging.getLogger(__name__)
settings = get_settings()

_MAX_PREFS_BYTES = 64 * 1024
_MAX_MESSAGE_BYTES = 512 * 1024
_MAX_SESSIONS_PAGE = 200
_MAX_MESSAGES_PAGE = 500
_MAX_SEARCH_RESULTS = 20
_PURGE_BATCH_SIZE = 5000


def _personal_session_filter():
    """Personal /app/chat threads only — project workspaces have their own list API."""
    return ChatSession.project_id.is_(None)


async def _owned_or_project_session(
    db: AsyncSession,
    session: ChatSession | None,
    user_id: int,
    *,
    write: bool,
) -> ChatSession | None:
    """Authorize a chat session as the owner or as a project member.

    Project threads are stored with ``user_id`` of the creator. Other members
    must pass ACL: any visible member may read; ``chat.write`` is required to
    mutate. Private Mode rows in a project are treated as inaccessible.
    """
    if session is None:
        return None
    if session.project_id:
        from app.models.user import User
        from app.services.project_access_service import resolve_project_access

        user = await db.get(User, user_id)
        if user is None:
            return None
        access = await resolve_project_access(db, project_id=session.project_id, user=user)
        if access is None:
            return None
        if write and not access.can("chat.write"):
            return None
        if session.private_mode:
            return None
        return session
    if session.user_id != user_id:
        return None
    return session


async def _project_author_display_name(db: AsyncSession, user_id: int) -> str | None:
    from app.models.user import User

    user = await db.get(User, user_id)
    if user is None:
        return None
    return user.display_name or user.username or None


# Orphan placeholders (container restart / dead stream) — reconcile on read after this age.
# Must exceed the OpenRouter read timeout (180s) plus the frontend client timeout (240s)
# margin, so a slow-but-alive generation is never finalized as "stopped" mid-flight.
_STALE_IMAGE_PENDING_SEC = 300
_STALE_VIDEO_PENDING_SEC = 900
_STALE_TEXT_STREAMING_SEC = 600


def _compact_attachment_content_for_storage(content: str) -> str:
    """Drop inline base64 from attachment JSON; persisted media remains via url."""
    if not content.startswith(ATTACHMENT_MESSAGE_PREFIX):
        return content
    try:
        payload = json.loads(content[len(ATTACHMENT_MESSAGE_PREFIX) :])
    except json.JSONDecodeError:
        return content
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return content
    compact: list[Any] = []
    for item in attachments:
        if isinstance(item, dict):
            compact.append({k: v for k, v in item.items() if k != "data_url"})
        else:
            compact.append(item)
    payload["attachments"] = compact
    return ATTACHMENT_MESSAGE_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _compact_message_content_for_storage(content: str, role: str) -> str:
    if role == "user":
        return _compact_attachment_content_for_storage(content)
    return content


class RevisionConflictError(Exception):
    """Raised when expectedRevision does not match the stored session revision."""

    def __init__(self, current_revision: int):
        self.current_revision = current_revision
        super().__init__(f"Session revision conflict (current={current_revision})")


def _empty_session_cutoff() -> dt.datetime:
    days = max(1, int(settings.chat_empty_session_hide_days))
    return dt.datetime.utcnow() - dt.timedelta(days=days)


def _default_prefs() -> dict[str, Any]:
    return {
        "default_model": None,
        "theme": "light",
        "timezone": "UTC",
        "language": "en",
        # "auto" = no language hint is sent to the speech-to-text provider, so it
        # detects the spoken language itself. Forcing "en" makes Whisper
        # transliterate or translate non-English audio.
        "voice_recording_language": "auto",
        # Catalog ref ("model::12") for speech-to-text; empty = use the
        # admin-selected system default.
        "transcription_model": "",
        # Catalog id from frontend build (public/fonts); empty = system UI font.
        "persian_font": "",
        # Opt-in: notify when a chat reply finishes while the user is away.
        "reply_notify_away": False,
        "reply_notify_sound": True,
        # When true, enabled user memories are injected into non-private completions.
        "memory_enabled": True,
        "memory_auto_capture": True,
    }


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ("1", "true", "yes", "on"):
            return True
        if token in ("0", "false", "no", "off", ""):
            return False
    return default


def _normalize_timezone(value: Any) -> str:
    """Validate IANA timezone; fall back to UTC when unknown."""
    raw = str(value or "UTC").strip()[:64] or "UTC"
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(raw)
            return raw
        except ZoneInfoNotFoundError:
            return "UTC"
        except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return "UTC")
            return "UTC"
    except Exception:  # noqa: BLE001 -- boundary with an external dependency; degraded result is returned
        # zoneinfo unavailable — accept common-looking tokens only
        if raw.replace("_", "").replace("/", "").replace("-", "").isalnum():
            return raw
        return "UTC"


def _normalize_prefs(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = _default_prefs()
    if not raw:
        return base

    model = raw.get("default_model")
    if isinstance(model, str) and model.strip():
        base["default_model"] = model.strip()[:512]
    elif model is None:
        base["default_model"] = None

    theme = str(raw.get("theme") or "light").lower()
    if theme in ("dark", "system", "mint", "dark-mint", "mint-system"):
        base["theme"] = theme
    else:
        base["theme"] = "light"

    if "timezone" in raw or isinstance(raw.get("timezone"), str):
        base["timezone"] = _normalize_timezone(raw.get("timezone"))

    # Language: English only for now
    lang = str(raw.get("language") or "en").strip().lower()
    base["language"] = "en" if lang in ("en", "english", "") else "en"

    # Voice recording language: drives Web Speech API locale and Whisper `language`.
    # "auto" (the default, and anything unrecognized) sends no hint at all.
    vrl = str(raw.get("voice_recording_language") or "auto").strip().lower()
    if vrl in ("fa", "fas", "persian", "farsi"):
        base["voice_recording_language"] = "fa"
    elif vrl in ("en", "eng", "english"):
        base["voice_recording_language"] = "en"
    else:
        base["voice_recording_language"] = "auto"

    # Personal speech-to-text model. Stored as an opaque catalog ref and
    # re-validated server-side on every use, so a stale or forbidden pick simply
    # falls through to the system default instead of breaking dictation.
    if "transcription_model" in raw:
        tm = raw.get("transcription_model")
        base["transcription_model"] = "" if tm is None else str(tm).strip()[:64]

    # Persian chat font preference (frontend validates against build-time catalog).
    if "persian_font" in raw:
        pf = raw.get("persian_font")
        if pf is None:
            base["persian_font"] = ""
        else:
            token = str(pf).strip()[:64]
            if not token or token.lower() in ("system", "default", "none"):
                base["persian_font"] = ""
            else:
                # Allow only safe slug characters matching generated font ids.
                cleaned = "".join(ch for ch in token.lower().replace("_", "-") if ch.isalnum() or ch == "-")
                base["persian_font"] = cleaned[:64]

    if "reply_notify_away" in raw:
        base["reply_notify_away"] = _coerce_bool(raw.get("reply_notify_away"), default=False)
    if "reply_notify_sound" in raw:
        base["reply_notify_sound"] = _coerce_bool(raw.get("reply_notify_sound"), default=True)
    if "memory_enabled" in raw:
        base["memory_enabled"] = _coerce_bool(raw.get("memory_enabled"), default=True)
    if "memory_auto_capture" in raw:
        base["memory_auto_capture"] = _coerce_bool(raw.get("memory_auto_capture"), default=True)
    return base


def _check_json_size(payload: Any, max_bytes: int) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("Chat data exceeds storage limit")


def _ms_to_dt(ms: int | float | None) -> dt.datetime:
    if ms is None:
        return dt.datetime.utcnow()
    try:
        return dt.datetime.utcfromtimestamp(float(ms) / 1000.0)
    except (TypeError, ValueError, OSError):
        return dt.datetime.utcnow()


def _dt_to_ms(value: dt.datetime | None) -> int:
    if value is None:
        return 0
    return int(calendar.timegm(value.timetuple()) * 1000)


def _session_activity_dt(row: ChatSession) -> dt.datetime:
    return row.last_message_at or row.created_at


def _session_activity_expr():
    return func.coalesce(ChatSession.last_message_at, ChatSession.created_at)


def _message_meta_from_client(msg: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key, out in (
        ("modelId", "modelId"),
        ("modelName", "modelName"),
        ("sentAt", "sentAt"),
        ("receivedAt", "receivedAt"),
        ("streaming", "streaming"),
        ("requestLogId", "requestLogId"),
    ):
        if msg.get(key) is not None:
            meta[out] = msg[key]
    return meta


_SERVER_OWNED_AGENT_META_KEYS = frozenset(
    {
        "agentRunId",
        "agentId",
        "agentVersionId",
        "agentName",
        "agentStatus",
        "routingOutcome",
        "completionReasonCode",
        "citations",
    }
)


def _message_to_client(row: ChatMessage) -> dict[str, Any]:
    meta = row.meta if isinstance(row.meta, dict) else {}
    out: dict[str, Any] = {
        "id": row.id,
        "role": row.role,
        "content": row.content or "",
        "sequence": row.sequence,
    }
    if meta.get("modelId"):
        out["modelId"] = meta["modelId"]
    if meta.get("modelName"):
        out["modelName"] = meta["modelName"]
    if meta.get("sentAt") is not None:
        out["sentAt"] = meta["sentAt"]
    if meta.get("receivedAt") is not None:
        out["receivedAt"] = meta["receivedAt"]
    if meta.get("streaming") is not None:
        out["streaming"] = meta["streaming"]
    request_log_id = meta.get("requestLogId")
    if request_log_id is not None:
        with contextlib.suppress(TypeError, ValueError):
            out["requestLogId"] = int(request_log_id)
    for key in (
        "agentId",
        "agentVersionId",
        "agentName",
        "agentStatus",
        "routingOutcome",
        "completionReasonCode",
        "citations",
    ):
        if meta.get(key) is not None:
            out[key] = meta[key]
    if row.client_message_id:
        out["clientMessageId"] = row.client_message_id
    if row.author_display_name:
        out["authorDisplayName"] = row.author_display_name
    if row.agent_run_id:
        out["agentRunId"] = row.agent_run_id
    elif meta.get("agentRunId"):
        out["agentRunId"] = meta["agentRunId"]
    return out


async def attach_request_log_id_to_chat_message(
    db: AsyncSession,
    user_id: int,
    session_id: str | None,
    request_log_id: int,
    *,
    client_message_id: str | None = None,
) -> bool:
    """Persist requestLogId on an owned assistant message (by client id or trailing row)."""
    if not session_id or not request_log_id:
        return False
    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return False

    row: ChatMessage | None = None
    cid = (client_message_id or "").strip()
    if cid:
        row = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.client_message_id == cid,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        row = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.sequence.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None or row.role != "assistant":
        return False

    merged = dict(row.meta) if isinstance(row.meta, dict) else {}
    merged["requestLogId"] = int(request_log_id)
    row.meta = merged
    _bump_session_revision(session)
    await db.flush()
    return True


def _session_to_client(
    row: ChatSession,
    *,
    include_messages: bool = False,
    messages: list[dict] | None = None,
) -> dict[str, Any]:
    tools = row.tools if isinstance(row.tools, dict) else {}
    out: dict[str, Any] = {
        "id": row.id,
        "title": row.title or "New chat",
        "titleLocked": bool(row.title_locked),
        "titleGenerated": bool(row.title_generated),
        "folderId": row.folder_id,
        "model": row.model_id or "",
        "currentAgentId": row.current_agent_id,
        "currentAgentVersionId": row.current_agent_version_id,
        "agentSelectedAt": (_dt_to_ms(row.agent_selected_at) if row.agent_selected_at else None),
        "tools": tools,
        "toolsTouched": bool(row.tools_touched),
        "privateMode": bool(row.private_mode),
        "messageCount": row.message_count or 0,
        "revision": int(row.revision or 1),
        "createdAt": _dt_to_ms(row.created_at),
        "updatedAt": _dt_to_ms(row.updated_at),
        "lastMessageAt": _dt_to_ms(row.last_message_at) if row.last_message_at else None,
    }
    if include_messages:
        out["messages"] = messages or []
    return out


def _folder_to_client(row: ChatFolder) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "color": row.color,
        "createdAt": _dt_to_ms(row.created_at),
        "updatedAt": _dt_to_ms(row.updated_at),
    }


async def ensure_user_chat_prefs(db: AsyncSession, user_id: int) -> UserChatPrefs:
    row = await db.get(UserChatPrefs, user_id)
    if row is not None:
        return row
    # Race-safe insert: during startup multiple uvicorn workers run the lifespan
    # concurrently and all reach here for each user. A plain ORM get-then-add
    # would raise UniqueViolation on all but the first worker and crash startup
    # (same class of bug as mark_migration_completed). Use a dialect-aware upsert
    # that is idempotent, then re-fetch the row so callers always get the object.
    import json as _json

    prefs_json = _json.dumps(_default_prefs())
    now = dt.datetime.utcnow()
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    if dialect == "postgresql":
        await db.execute(
            text(
                """
                INSERT INTO user_chat_prefs (user_id, prefs, updated_at)
                VALUES (:uid, CAST(:prefs AS JSONB), :now)
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {"uid": user_id, "prefs": prefs_json, "now": now},
        )
    else:
        await db.execute(
            text("INSERT OR IGNORE INTO user_chat_prefs (user_id, prefs, updated_at) VALUES (:uid, :prefs, :now)"),
            {"uid": user_id, "prefs": prefs_json, "now": now},
        )
    await db.flush()
    # Re-fetch the committed row. A raw INSERT via text() does not put the row
    # into the ORM identity map, so db.get() will SELECT and load it fresh.
    row = await db.get(UserChatPrefs, user_id)
    if row is None:  # extremely unlikely fallback
        row = UserChatPrefs(user_id=user_id, prefs=_default_prefs(), updated_at=now)
        db.add(row)
        await db.flush()
    return row


#: Rows per statement in the startup backfill.
CHAT_PREFS_BACKFILL_BATCH_SIZE = 5000


async def backfill_user_chat_prefs(db: AsyncSession, *, batch_size: int | None = None) -> int:
    """Create the missing ``user_chat_prefs`` rows in bulk. Returns how many.

    Startup used to call :func:`ensure_user_chat_prefs` once per user, in every
    uvicorn worker. The row is created on demand anyway - at login, and by
    every reader of the prefs - so the startup pass is a backfill, and a
    backfill is a statement, not a loop.

    Committed per batch: this runs while the process is starting and the first
    requests are already arriving, so it must not hold a long write transaction.
    """

    import json as _json

    limit = int(batch_size or CHAT_PREFS_BACKFILL_BATCH_SIZE)
    prefs_json = _json.dumps(_default_prefs())
    now = dt.datetime.utcnow()
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    if dialect == "postgresql":
        statement = text(
            """
            INSERT INTO user_chat_prefs (user_id, prefs, updated_at)
            SELECT u.id, CAST(:prefs AS JSONB), :now
            FROM users u
            WHERE NOT EXISTS (SELECT 1 FROM user_chat_prefs p WHERE p.user_id = u.id)
            LIMIT :limit
            ON CONFLICT (user_id) DO NOTHING
            """
        )
    else:
        statement = text(
            """
            INSERT OR IGNORE INTO user_chat_prefs (user_id, prefs, updated_at)
            SELECT u.id, :prefs, :now
            FROM users u
            WHERE NOT EXISTS (SELECT 1 FROM user_chat_prefs p WHERE p.user_id = u.id)
            LIMIT :limit
            """
        )

    created = 0
    while True:
        result = await db.execute(statement, {"prefs": prefs_json, "now": now, "limit": limit})
        inserted = int(result.rowcount or 0)
        created += inserted
        if inserted:
            await db.commit()
        if inserted < limit:
            break
    return created


async def ensure_user_chat_store(db: AsyncSession, user_id: int) -> UserChatPrefs:
    """Backward-compatible alias for callers that ensured a chat store row."""
    return await ensure_user_chat_prefs(db, user_id)


async def load_user_prefs(db: AsyncSession, user_id: int) -> dict[str, Any]:
    row = await ensure_user_chat_prefs(db, user_id)
    return _normalize_prefs(row.prefs if isinstance(row.prefs, dict) else {})


async def save_user_prefs(db: AsyncSession, user_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    row = await ensure_user_chat_prefs(db, user_id)
    current = _normalize_prefs(row.prefs if isinstance(row.prefs, dict) else {})
    merged = _normalize_prefs({**current, **updates})
    _check_json_size(merged, _MAX_PREFS_BYTES)
    row.prefs = merged
    row.updated_at = dt.datetime.utcnow()
    await db.flush()
    return merged


async def list_chat_folders(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(ChatFolder)
                .where(ChatFolder.user_id == user_id)
                .order_by(ChatFolder.sort_order.asc(), ChatFolder.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_folder_to_client(r) for r in rows]


async def create_chat_folder(db: AsyncSession, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    folder_id = str(payload.get("id") or uuid.uuid4())
    now = dt.datetime.utcnow()
    row = ChatFolder(
        id=folder_id,
        user_id=user_id,
        name=str(payload.get("name") or "Folder")[:255],
        color=payload.get("color"),
        sort_order=int(payload.get("sort_order") or 0),
        created_at=_ms_to_dt(payload.get("createdAt")) if payload.get("createdAt") else now,
        updated_at=_ms_to_dt(payload.get("updatedAt")) if payload.get("updatedAt") else now,
    )
    db.add(row)
    await db.flush()
    return _folder_to_client(row)


async def update_chat_folder(
    db: AsyncSession, user_id: int, folder_id: str, updates: dict[str, Any]
) -> dict[str, Any] | None:
    row = await db.get(ChatFolder, folder_id)
    if row is None or row.user_id != user_id:
        return None
    if "name" in updates and updates["name"] is not None:
        row.name = str(updates["name"])[:255]
    if "color" in updates:
        row.color = updates["color"]
    if "sort_order" in updates and updates["sort_order"] is not None:
        row.sort_order = int(updates["sort_order"])
    row.updated_at = dt.datetime.utcnow()
    await db.flush()
    return _folder_to_client(row)


async def delete_chat_folder(db: AsyncSession, user_id: int, folder_id: str) -> bool:
    row = await db.get(ChatFolder, folder_id)
    if row is None or row.user_id != user_id:
        return False
    sessions = (
        (
            await db.execute(
                select(ChatSession).where(ChatSession.folder_id == folder_id, ChatSession.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    for s in sessions:
        s.folder_id = None
    await db.delete(row)
    await db.flush()
    return True


async def _dialect_name(db: AsyncSession) -> str:
    conn = await db.connection()
    return conn.dialect.name


def _check_expected_revision(session: ChatSession, expected: int | None) -> None:
    if expected is None:
        return
    current = int(session.revision or 1)
    if expected != current:
        raise RevisionConflictError(current)


def _bump_session_revision(session: ChatSession) -> int:
    session.revision = int(session.revision or 1) + 1
    session.updated_at = dt.datetime.utcnow()
    return session.revision


async def list_chat_sessions(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
    since_ms: int | None = None,
    min_activity_ms: int | None = None,
    max_activity_ms: int | None = None,
    exclude_empty_old: bool = True,
) -> tuple[list[dict[str, Any]], int, int | None]:
    limit = min(max(1, limit), _MAX_SESSIONS_PAGE)
    offset = max(0, offset)
    activity = _session_activity_expr()

    personal = _personal_session_filter()
    base = select(ChatSession).where(ChatSession.user_id == user_id, personal)
    count_q = select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id, personal)

    visible = None
    if exclude_empty_old:
        cutoff = _empty_session_cutoff()
        visible = or_(
            ChatSession.message_count > 0,
            ChatSession.created_at >= cutoff,
        )
        base = base.where(visible)
        count_q = count_q.where(visible)

    if since_ms is not None:
        since_dt = _ms_to_dt(since_ms)
        base = base.where(ChatSession.updated_at > since_dt)
        count_q = count_q.where(ChatSession.updated_at > since_dt)

    if min_activity_ms is not None:
        min_dt = _ms_to_dt(min_activity_ms)
        base = base.where(activity >= min_dt)
        count_q = count_q.where(activity >= min_dt)

    if max_activity_ms is not None:
        max_dt = _ms_to_dt(max_activity_ms)
        base = base.where(activity < max_dt)
        count_q = count_q.where(activity < max_dt)

    search = (q or "").strip()
    if search:
        dialect = await _dialect_name(db)
        if dialect == "postgresql" and len(search) >= 2:
            pattern = f"%{search}%"
            base = base.where(ChatSession.title.ilike(pattern))
            count_q = count_q.where(ChatSession.title.ilike(pattern))
        elif len(search) >= 2:
            pattern = f"%{search.lower()}%"
            base = base.where(func.lower(ChatSession.title).like(pattern))
            count_q = count_q.where(func.lower(ChatSession.title).like(pattern))

    older_total: int | None = None
    if min_activity_ms is not None and not search and since_ms is None:
        older_cutoff = _ms_to_dt(min_activity_ms)
        older_q = select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id, personal)
        if visible is not None:
            older_q = older_q.where(visible)
        older_total = int((await db.execute(older_q.where(activity < older_cutoff))).scalar_one())

    total = (await db.execute(count_q)).scalar_one()
    rows = (
        (await db.execute(base.order_by(activity.desc(), ChatSession.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return [_session_to_client(r) for r in rows], int(total), older_total


async def search_chat_messages(
    db: AsyncSession,
    user_id: int,
    *,
    q: str,
    limit: int = _MAX_SEARCH_RESULTS,
) -> list[dict[str, Any]]:
    """Full-text message search (PostgreSQL tsvector); LIKE fallback for SQLite tests."""
    term = (q or "").strip()
    if len(term) < 2:
        return []
    limit = min(max(1, limit), _MAX_SEARCH_RESULTS)
    dialect = await _dialect_name(db)

    if dialect == "postgresql":
        rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT m.id, m.session_id, m.role, m.content, m.sequence, m.created_at,
                           s.title AS session_title
                    FROM chat_messages m
                    JOIN chat_sessions s ON s.id = m.session_id
                    WHERE m.user_id = :uid
                      AND s.project_id IS NULL
                      AND to_tsvector('simple', coalesce(m.content, ''))
                          @@ plainto_tsquery('simple', :q)
                    ORDER BY m.created_at DESC
                    LIMIT :lim
                    """
                    ),
                    {"uid": user_id, "q": term, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
    else:
        pattern = f"%{term.lower()}%"
        rows = (
            await db.execute(
                select(ChatMessage, ChatSession.title)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(ChatMessage.user_id == user_id)
                .where(ChatSession.project_id.is_(None))
                .where(func.lower(ChatMessage.content).like(pattern))
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
            )
        ).all()

    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(
                {
                    "messageId": row["id"],
                    "sessionId": row["session_id"],
                    "sessionTitle": row["session_title"] or "New chat",
                    "role": row["role"],
                    "content": (row["content"] or "")[:500],
                    "sequence": row["sequence"],
                    "createdAt": _dt_to_ms(row["created_at"]),
                }
            )
        else:
            msg, title = row
            out.append(
                {
                    "messageId": msg.id,
                    "sessionId": msg.session_id,
                    "sessionTitle": title or "New chat",
                    "role": msg.role,
                    "content": (msg.content or "")[:500],
                    "sequence": msg.sequence,
                    "createdAt": _dt_to_ms(msg.created_at),
                }
            )
    return out


async def get_chat_session(db: AsyncSession, user_id: int, session_id: str) -> dict[str, Any] | None:
    row = await db.get(ChatSession, session_id)
    row = await _owned_or_project_session(db, row, user_id, write=False)
    if row is None:
        return None
    return _session_to_client(row)


async def create_chat_session(db: AsyncSession, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("id") or uuid.uuid4())
    project_id_raw = payload.get("projectId") or payload.get("project_id")
    project_id = str(project_id_raw).strip() if project_id_raw else ""
    existing = await db.get(ChatSession, session_id)
    if existing is not None:
        if existing.project_id:
            accessed = await _owned_or_project_session(db, existing, user_id, write=True)
            if accessed is None:
                raise ValueError("Session id already in use")
            if project_id and existing.project_id != project_id:
                raise ValueError("Session id already in use")
            return _session_to_client(existing)
        if existing.user_id != user_id or project_id:
            raise ValueError("Session id already in use")
        return _session_to_client(existing)

    if project_id:
        from app.models.user import User
        from app.services.project_access_service import resolve_project_access

        user = await db.get(User, user_id)
        if user is None:
            raise ValueError("User not found")
        access = await resolve_project_access(db, project_id=project_id, user=user)
        if access is None or not access.can("chat.write"):
            raise ValueError("Project chat is unavailable")
        now = dt.datetime.utcnow()
        row = ChatSession(
            id=session_id,
            user_id=user_id,
            project_id=project_id,
            created_by_user_id=user_id,
            channel_kind="ai",
            title=str(payload.get("title") or "New chat")[:512],
            model_id=str(payload.get("model") or payload.get("model_id") or "")[:512],
            tools={},
            private_mode=False,
            title_locked=bool(payload.get("titleLocked") or payload.get("title_locked")),
            title_generated=bool(payload.get("titleGenerated") or payload.get("title_generated")),
            tools_touched=False,
            message_count=0,
            revision=1,
            created_at=_ms_to_dt(payload.get("createdAt")) if payload.get("createdAt") else now,
            updated_at=_ms_to_dt(payload.get("updatedAt")) if payload.get("updatedAt") else now,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            raced = await db.get(ChatSession, session_id)
            accessed = await _owned_or_project_session(db, raced, user_id, write=True)
            if accessed is None:
                raise
            return _session_to_client(accessed)
        return _session_to_client(row)

    folder_id = payload.get("folderId") or payload.get("folder_id")
    if folder_id:
        folder_row = await db.get(ChatFolder, str(folder_id))
        if folder_row is None or folder_row.user_id != user_id:
            folder_id = None

    now = dt.datetime.utcnow()
    tools = payload.get("tools") if isinstance(payload.get("tools"), dict) else {}
    row = ChatSession(
        id=session_id,
        user_id=user_id,
        title=str(payload.get("title") or "New chat")[:512],
        folder_id=folder_id,
        model_id=str(payload.get("model") or payload.get("model_id") or "")[:512],
        tools=tools,
        private_mode=bool(payload.get("privateMode") or payload.get("private_mode")),
        title_locked=bool(payload.get("titleLocked") or payload.get("title_locked")),
        title_generated=bool(payload.get("titleGenerated") or payload.get("title_generated")),
        tools_touched=bool(payload.get("toolsTouched") or payload.get("tools_touched")),
        message_count=0,
        revision=1,
        created_at=_ms_to_dt(payload.get("createdAt")) if payload.get("createdAt") else now,
        updated_at=_ms_to_dt(payload.get("updatedAt")) if payload.get("updatedAt") else now,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raced = await db.get(ChatSession, session_id)
        if raced is None or raced.user_id != user_id:
            raise
        return _session_to_client(raced)
    return _session_to_client(row)


async def update_chat_session(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    updates: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any] | None:
    row = await db.get(ChatSession, session_id)
    row = await _owned_or_project_session(db, row, user_id, write=True)
    if row is None:
        return None
    _check_expected_revision(row, expected_revision)
    requested_private = updates.get(
        "privateMode",
        updates.get("private_mode"),
    )
    if row.project_id and requested_private is True:
        raise PrivateModePersistenceError("Private Mode is not allowed in project chats")
    if requested_private is not None:
        next_private = bool(requested_private)
        if row.private_mode and not next_private:
            raise PrivateModePersistenceError("Private Mode is permanent for a session; create a new chat instead")
        if not row.private_mode and next_private and int(row.message_count or 0) > 0:
            raise PrivateModePersistenceError("A persisted chat with messages cannot be converted to Private Mode")

    field_map = {
        "title": "title",
        "folderId": "folder_id",
        "folder_id": "folder_id",
        "model": "model_id",
        "model_id": "model_id",
        "tools": "tools",
        "privateMode": "private_mode",
        "private_mode": "private_mode",
        "titleLocked": "title_locked",
        "title_locked": "title_locked",
        "titleGenerated": "title_generated",
        "title_generated": "title_generated",
        "toolsTouched": "tools_touched",
        "tools_touched": "tools_touched",
    }
    for src, dest in field_map.items():
        if src in updates:
            if row.project_id and dest in (
                "folder_id",
                "private_mode",
                "tools",
                "tools_touched",
                "model_id",
            ):
                continue
            value = updates[src]
            if dest == "title" and value is not None:
                row.title = str(value)[:512]
            elif dest == "model_id" and value is not None:
                row.model_id = str(value)[:512]
            elif dest == "tools" and value is not None:
                if not isinstance(value, dict):
                    raise ValueError("tools must be an object")
                _check_json_size(value, 16 * 1024)
                row.tools = value
            else:
                setattr(row, dest, value)

    if "updatedAt" in updates and updates["updatedAt"]:
        row.updated_at = _ms_to_dt(updates["updatedAt"])
    _bump_session_revision(row)
    await db.flush()
    return _session_to_client(row)


async def delete_chat_session(db: AsyncSession, user_id: int, session_id: str) -> bool:
    row = await db.get(ChatSession, session_id)
    row = await _owned_or_project_session(db, row, user_id, write=True)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def _try_reconcile_inflight_assistant(
    db: AsyncSession,
    user_id: int,
    session_id: str,
) -> bool:
    """Finalize a trailing assistant placeholder left open by a killed stream or image job."""
    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return False

    last = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.role != "assistant":
        return False

    meta = dict(last.meta) if isinstance(last.meta, dict) else {}
    content = str(last.content or "")
    # Finalized assistant rows are done; a pending marker may still be open even
    # when meta incorrectly carries receivedAt (orphan image placeholder).
    if meta.get("receivedAt") is not None and content not in (
        IMAGE_PENDING_MARKER,
        SPEECH_PENDING_MARKER,
        VIDEO_PENDING_MARKER,
    ):
        return False

    age = (dt.datetime.utcnow() - last.created_at).total_seconds()
    force = bool(meta.get("cancelRequested"))
    if content == IMAGE_PENDING_MARKER and (meta.get("receivedAt") is not None or age >= _STALE_IMAGE_PENDING_SEC):
        force = True
    if content == SPEECH_PENDING_MARKER and (meta.get("receivedAt") is not None or age >= _STALE_IMAGE_PENDING_SEC):
        force = True
    if content == VIDEO_PENDING_MARKER and (meta.get("receivedAt") is not None or age >= _STALE_VIDEO_PENDING_SEC):
        force = True
    if not force and not content.strip() and meta.get("streaming") and age >= _STALE_TEXT_STREAMING_SEC:
        force = True
    # Imported / legacy rows: completed assistant text without receivedAt is treated
    # by the UI as an in-flight generation (STOP). Finalize when not actively streaming.
    if (
        not force
        and content.strip()
        and content not in (IMAGE_PENDING_MARKER, SPEECH_PENDING_MARKER, VIDEO_PENDING_MARKER)
        and meta.get("receivedAt") is None
        and meta.get("streaming") is not True
    ):
        force = True
    if not force:
        return False

    if content == IMAGE_PENDING_MARKER:
        new_content = "Image generation stopped."
    elif content == SPEECH_PENDING_MARKER:
        new_content = "Speech generation stopped."
    elif content == VIDEO_PENDING_MARKER:
        new_content = "Video generation stopped."
    elif content.strip():
        new_content = content
    else:
        new_content = "Generation stopped."

    meta["streaming"] = False
    meta["receivedAt"] = int(time.time() * 1000)
    meta.pop("cancelRequested", None)
    last.content = new_content
    last.meta = meta
    session.last_message_at = dt.datetime.utcnow()
    _bump_session_revision(session)
    await db.flush()
    return True


async def list_session_messages(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    *,
    limit: int = 100,
    before: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=False)
    if session is None:
        return [], False

    if before is None:
        await _try_reconcile_inflight_assistant(db, user_id, session_id)

    limit = min(max(1, limit), _MAX_MESSAGES_PAGE)
    q = select(ChatMessage).where(ChatMessage.session_id == session_id)
    if before is not None:
        q = q.where(ChatMessage.sequence < int(before))
    q = q.order_by(ChatMessage.sequence.desc()).limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    messages = [_message_to_client(r) for r in rows]
    if session.project_id:
        from app.services.project_media_service import rewrite_personal_media_urls_in_messages

        messages = await rewrite_personal_media_urls_in_messages(db, project_id=session.project_id, messages=messages)
    message_ids = [row.id for row in rows]
    if message_ids:
        feedback_rows = (
            (
                await db.execute(
                    select(ChatMessageFeedback).where(
                        ChatMessageFeedback.user_id == user_id,
                        ChatMessageFeedback.message_id.in_(message_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        feedback_by_message = {row.message_id: row for row in feedback_rows}
        for payload, row in zip(messages, rows, strict=False):
            feedback = feedback_by_message.get(row.id)
            if feedback is not None:
                payload["feedback"] = {
                    "rating": int(feedback.rating),
                    "reason": feedback.reason,
                }
    return messages, has_more


async def _next_sequence(db: AsyncSession, session_id: str) -> int:
    current = (
        await db.execute(select(func.max(ChatMessage.sequence)).where(ChatMessage.session_id == session_id))
    ).scalar_one()
    return int(current or 0) + 1


async def _touch_session_messages(
    db: AsyncSession,
    session: ChatSession,
    *,
    added: int = 0,
    last_at: dt.datetime | None = None,
) -> None:
    if added:
        session.message_count = int(session.message_count or 0) + added
    session.last_message_at = last_at or dt.datetime.utcnow()
    _bump_session_revision(session)


async def append_session_messages(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    expected_revision: int | None = None,
) -> list[dict[str, Any]] | None:
    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return None
    assert_session_persistence_allowed(session)
    _check_expected_revision(session, expected_revision)
    if not messages:
        return []

    inserted: list[ChatMessage] = []
    new_count = 0
    seq = await _next_sequence(db, session_id)
    last_created = dt.datetime.utcnow()
    author_name = await _project_author_display_name(db, user_id) if session.project_id else None
    for msg in messages:
        client_id = msg.get("clientMessageId") or msg.get("client_message_id")
        if client_id:
            existing = (
                await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.session_id == session_id,
                        ChatMessage.client_message_id == str(client_id),
                    )
                )
            ).scalar_one_or_none()
            if existing:
                inserted.append(existing)
                continue

        content = _compact_message_content_for_storage(str(msg.get("content") or ""), str(msg.get("role") or "user"))
        if len(content.encode("utf-8")) > _MAX_MESSAGE_BYTES:
            raise ValueError("Message content exceeds storage limit")

        last_created = dt.datetime.utcnow()
        row = ChatMessage(
            id=str(msg.get("id") or uuid.uuid4()),
            session_id=session_id,
            user_id=user_id,
            author_display_name=author_name,
            role=str(msg.get("role") or "user")[:16],
            content=content,
            sequence=seq,
            client_message_id=str(client_id) if client_id else None,
            meta=_message_meta_from_client(msg),
            created_at=last_created,
        )
        db.add(row)
        inserted.append(row)
        seq += 1
        new_count += 1

    await db.flush()
    if new_count:
        await _touch_session_messages(db, session, added=new_count, last_at=last_created)
        await db.flush()
        try:
            watermark = max((row.sequence for row in inserted), default=0)
            if session.project_id:
                # Project threads feed shared project memory; personal memory is
                # never learned from, or injected into, a project chat.
                from app.services.project_memory_job_service import (
                    maybe_schedule_from_append as schedule_project_extraction,
                )

                await schedule_project_extraction(
                    db,
                    session=session,
                    messages=messages,
                    watermark_sequence=watermark,
                )
            else:
                from app.services.memory_job_service import maybe_schedule_from_append

                await maybe_schedule_from_append(
                    db,
                    user_id=user_id,
                    session=session,
                    messages=messages,
                    watermark_sequence=watermark,
                )
        except Exception:
            logger.exception(
                "Memory extraction schedule failed user_id=%s session_id=%s",
                user_id,
                session_id,
            )
    return [_message_to_client(r) for r in inserted]


async def purge_session_messages_for_private_mode(
    db: AsyncSession,
    user_id: int,
    session_id: str,
) -> dict[str, Any] | None:
    """Delete this session's server copy and turn Private Mode on, in one step.

    Enabling Private Mode showed the user two dialogs - "messages and media will
    be stored only in this browser" and "this chat will be deleted when you log
    out" - and then set a flag in the browser. Nothing removed what the server
    already had, so every message written before the toggle stayed on the server
    permanently and the session stayed listable. The consent copy said otherwise.

    ``update_chat_session`` refuses to convert a session that still has messages,
    which is the right invariant and the reason this cannot be a plain PATCH:
    the removal and the flag have to happen together, in one transaction, so the
    session can never end up private with a readable server copy behind it.
    """

    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return None
    if session.project_id:
        raise PrivateModePersistenceError("Private Mode is not allowed in project chats")

    removed = len(
        (await db.execute(select(ChatMessage.id).where(ChatMessage.session_id == session_id))).scalars().all()
    )
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    session.message_count = 0
    session.last_message_at = None
    session.private_mode = True
    _bump_session_revision(session)
    await db.flush()
    return {"purgedMessages": removed, "session": _session_to_client(session)}


async def replace_session_messages(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    expected_revision: int | None = None,
) -> list[dict[str, Any]] | None:
    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return None
    assert_session_persistence_allowed(session)
    _check_expected_revision(session, expected_revision)

    existing_rows = (await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id))).scalars().all()
    existing_by_client_id = {row.client_message_id: row for row in existing_rows if row.client_message_id}
    existing_by_id = {row.id: row for row in existing_rows}
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    await db.flush()

    if not messages:
        session.message_count = 0
        session.last_message_at = None
        _bump_session_revision(session)
        await db.flush()
        return []

    rows: list[ChatMessage] = []
    last_created = dt.datetime.utcnow()
    for idx, msg in enumerate(messages, start=1):
        role = str(msg.get("role") or "user")
        content = _compact_message_content_for_storage(str(msg.get("content") or ""), role)
        if len(content.encode("utf-8")) > _MAX_MESSAGE_BYTES:
            raise ValueError("Message content exceeds storage limit")
        last_created = dt.datetime.utcnow()
        client_message_id = str(msg.get("clientMessageId") or msg.get("client_message_id") or "") or None
        previous = (
            existing_by_client_id.get(client_message_id)
            if client_message_id
            else existing_by_id.get(str(msg.get("id") or ""))
        )
        message_meta = _message_meta_from_client(msg)
        agent_run_id = None
        if previous is not None and role == "assistant":
            previous_meta = previous.meta if isinstance(previous.meta, dict) else {}
            for key in _SERVER_OWNED_AGENT_META_KEYS:
                if previous_meta.get(key) is not None:
                    message_meta[key] = previous_meta[key]
            agent_run_id = previous.agent_run_id
        row = ChatMessage(
            id=str(msg.get("id") or uuid.uuid4()),
            session_id=session_id,
            user_id=user_id,
            role=role[:16],
            content=content,
            sequence=idx,
            client_message_id=client_message_id,
            agent_run_id=agent_run_id,
            meta=message_meta,
            created_at=last_created,
        )
        db.add(row)
        rows.append(row)

    session.message_count = len(rows)
    session.last_message_at = last_created
    _bump_session_revision(session)
    await db.flush()
    return [_message_to_client(r) for r in rows]


def _build_image_message(
    url: str,
    prompt: str,
    model: str,
    routing: dict[str, Any] | None = None,
) -> str:
    payload = {"url": url, "prompt": prompt, "model": model}
    if routing:
        payload["routing"] = routing
    return f"{IMAGE_MESSAGE_PREFIX}{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"


async def finalize_chat_session_image(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    image_url: str,
    prompt: str,
    model: str,
    routing: dict[str, Any] | None = None,
) -> bool:
    """Replace trailing pending marker with the generated image message (idempotent)."""
    if not session_id or not image_url:
        return False

    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return False
    assert_session_persistence_allowed(session)

    last = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.role != "assistant":
        return False

    content = str(last.content or "")
    image_content = _build_image_message(image_url, prompt, model, routing)
    if content == IMAGE_PENDING_MARKER:
        last.content = image_content
        last.meta = {
            **(last.meta if isinstance(last.meta, dict) else {}),
            "modelId": model,
            **({"routing": routing} if routing else {}),
        }
        session.last_message_at = dt.datetime.utcnow()
        _bump_session_revision(session)
        await db.flush()
        return True
    return bool(content.startswith(IMAGE_MESSAGE_PREFIX))


def _build_video_message(
    url: str,
    prompt: str,
    model: str,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {"url": url, "prompt": prompt, "model": model}
    if params:
        payload.update({k: v for k, v in params.items() if v is not None})
    return f"{VIDEO_MESSAGE_PREFIX}{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"


async def finalize_chat_session_video(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    video_url: str,
    prompt: str,
    model: str,
    *,
    params: dict[str, Any] | None = None,
) -> bool:
    """Replace trailing video pending marker with the generated video message (idempotent)."""
    if not session_id or not video_url:
        return False

    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return False
    assert_session_persistence_allowed(session)

    last = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.role != "assistant":
        return False

    content = str(last.content or "")
    video_content = _build_video_message(video_url, prompt, model, params=params)
    if content == VIDEO_PENDING_MARKER:
        last.content = video_content
        last.meta = {
            **(last.meta if isinstance(last.meta, dict) else {}),
            "modelId": model,
        }
        session.last_message_at = dt.datetime.utcnow()
        _bump_session_revision(session)
        await db.flush()
        return True
    if content.startswith(VIDEO_MESSAGE_PREFIX):
        return True
    # The frontend normally persists the pending marker before starting the
    # durable job. If that request races with job completion (or is lost
    # during a refresh), preserve the prompt by appending the completed video
    # after its user turn instead of leaving the media orphaned.
    if last.role == "user":
        await append_session_messages(
            db,
            user_id,
            session_id,
            [
                {
                    "role": "assistant",
                    "content": video_content,
                    "clientMessageId": str(uuid.uuid4()),
                    "receivedAt": int(time.time() * 1000),
                    "modelId": model,
                }
            ],
        )
        return True
    return False


def _build_speech_message(
    url: str,
    prompt: str,
    model: str,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {"url": url, "prompt": prompt, "model": model}
    if params:
        payload.update({k: v for k, v in params.items() if v is not None})
    return f"{SPEECH_MESSAGE_PREFIX}{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"


async def finalize_chat_session_speech(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    audio_url: str,
    prompt: str,
    model: str,
    *,
    params: dict[str, Any] | None = None,
) -> bool:
    """Replace trailing speech pending marker with the generated audio message (idempotent)."""
    if not session_id or not audio_url:
        return False

    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return False
    assert_session_persistence_allowed(session)

    last = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.role != "assistant":
        return False

    content = str(last.content or "")
    speech_content = _build_speech_message(audio_url, prompt, model, params=params)
    if content == SPEECH_PENDING_MARKER:
        last.content = speech_content
        last.meta = {
            **(last.meta if isinstance(last.meta, dict) else {}),
            "modelId": model,
        }
        session.last_message_at = dt.datetime.utcnow()
        _bump_session_revision(session)
        await db.flush()
        return True
    if content.startswith(SPEECH_MESSAGE_PREFIX):
        return True
    # Fallback (mirrors video): if the pending marker was lost during a refresh,
    # append the completed speech after its user turn instead of orphaning it.
    if last.role == "user":
        await append_session_messages(
            db,
            user_id,
            session_id,
            [
                {
                    "role": "assistant",
                    "content": speech_content,
                    "clientMessageId": str(uuid.uuid4()),
                    "receivedAt": int(time.time() * 1000),
                    "modelId": model,
                }
            ],
        )
        return True
    return False


async def update_last_session_message(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    content: str,
    *,
    meta: dict[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any] | None:
    """Update the last message in a session (streaming / image finalize)."""
    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return None
    assert_session_persistence_allowed(session)
    _check_expected_revision(session, expected_revision)

    last = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None:
        return None

    # Same bounds as append: no NUL (PostgreSQL text rejects it -> 500 mid-
    # stream) and the storage ceiling, truncated rather than refused because
    # the message already exists and the stream must finish.
    content = strip_nul(content) or ""
    if len(content.encode("utf-8")) > _MAX_MESSAGE_BYTES:
        content = content.encode("utf-8")[:_MAX_MESSAGE_BYTES].decode("utf-8", errors="ignore")
    last.content = content
    if meta:
        merged = dict(last.meta) if isinstance(last.meta, dict) else {}
        merged.update(meta)
        last.meta = merged
    session.last_message_at = dt.datetime.utcnow()
    _bump_session_revision(session)
    await db.flush()
    return _session_to_client(session)


async def cancel_streaming_reply(
    db: AsyncSession,
    user_id: int,
    session_id: str,
) -> dict[str, Any] | None:
    """Stop and finalize the trailing assistant placeholder (live stream or orphan)."""
    session = await db.get(ChatSession, session_id)
    session = await _owned_or_project_session(db, session, user_id, write=True)
    if session is None:
        return None
    assert_session_persistence_allowed(session)

    last = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.role != "assistant":
        return None

    meta = dict(last.meta) if isinstance(last.meta, dict) else {}
    content = str(last.content or "")
    if meta.get("receivedAt") is not None and content not in (
        IMAGE_PENDING_MARKER,
        SPEECH_PENDING_MARKER,
        VIDEO_PENDING_MARKER,
    ):
        return _session_to_client(session)

    if content == IMAGE_PENDING_MARKER:
        new_content = "Image generation stopped."
    elif content == SPEECH_PENDING_MARKER:
        new_content = "Speech generation stopped."
    elif content == VIDEO_PENDING_MARKER:
        new_content = "Video generation stopped."
    elif content.strip():
        new_content = content
    else:
        new_content = "Generation stopped."

    meta["streaming"] = False
    meta["receivedAt"] = int(time.time() * 1000)
    meta.pop("cancelRequested", None)
    last.content = new_content
    last.meta = meta
    session.last_message_at = dt.datetime.utcnow()
    _bump_session_revision(session)
    await db.flush()
    return _session_to_client(session)


async def reconcile_session_message_stats(db: AsyncSession) -> int:
    """Nightly reconcile: recompute message_count/last_message_at from messages."""
    conn = await db.connection()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        await db.execute(
            text(
                """
                UPDATE chat_sessions AS cs SET
                    message_count = COALESCE(sub.cnt, 0),
                    last_message_at = sub.last_at
                FROM (
                    SELECT session_id, COUNT(*)::int AS cnt, MAX(created_at) AS last_at
                    FROM chat_messages
                    GROUP BY session_id
                ) AS sub
                WHERE cs.id = sub.session_id
                """
            )
        )
        await db.execute(
            text(
                """
                UPDATE chat_sessions SET message_count = 0, last_message_at = NULL
                WHERE id NOT IN (SELECT DISTINCT session_id FROM chat_messages)
                """
            )
        )
    else:
        sessions = (await db.execute(select(ChatSession.id))).scalars().all()
        for session_id in sessions:
            row = await db.get(ChatSession, session_id)
            if row is None:
                continue
            count = (
                await db.execute(
                    select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)
                )
            ).scalar() or 0
            last_at = (
                await db.execute(select(func.max(ChatMessage.created_at)).where(ChatMessage.session_id == session_id))
            ).scalar()
            row.message_count = int(count)
            row.last_message_at = last_at
    await db.flush()
    return 0
