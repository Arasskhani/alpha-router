"""Explicit per-user durable memories for chat personalization."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from calendar import timegm
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession, UserMemory
from app.services.user_chat_storage_service import load_user_prefs

MAX_MEMORY_CHARS = 500
MAX_MEMORIES_PER_USER = 100
MAX_INJECT_ITEMS = 30
MAX_INJECT_CHARS = 4000

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class MemoryValidationError(ValueError):
    """Invalid memory content or source session."""


class MemoryLimitError(ValueError):
    """User has reached the max number of memories."""


class MemoryNotFoundError(LookupError):
    """Memory missing or not owned by the caller."""


def normalize_memory_content(text: str | None) -> str:
    raw = "" if text is None else str(text)
    cleaned = _CONTROL_RE.sub("", raw)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        raise MemoryValidationError("Memory content is required")
    if len(cleaned) > MAX_MEMORY_CHARS:
        raise MemoryValidationError(f"Memory content exceeds {MAX_MEMORY_CHARS} characters")
    return cleaned


def memory_content_hash(text: str) -> str:
    normalized = normalize_memory_content(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dt_to_ms(value: dt.datetime | None) -> int:
    if value is None:
        return 0
    return int(timegm(value.timetuple()) * 1000)


def memory_to_client(row: UserMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "content": row.content,
        "enabled": bool(row.enabled),
        "source_session_id": row.source_session_id,
        "created_at": _dt_to_ms(row.created_at),
        "updated_at": _dt_to_ms(row.updated_at),
    }


async def list_memories(
    db: AsyncSession,
    user_id: int,
    *,
    include_disabled: bool = True,
) -> list[dict[str, Any]]:
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    if not include_disabled:
        stmt = stmt.where(UserMemory.enabled.is_(True))
    stmt = stmt.order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [memory_to_client(row) for row in rows]


async def _count_memories(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(UserMemory).where(UserMemory.user_id == user_id)
    )
    return int(result.scalar_one() or 0)


async def _resolve_source_session_id(
    db: AsyncSession,
    user_id: int,
    source_session_id: str | None,
) -> str | None:
    if not source_session_id:
        return None
    session_id = str(source_session_id).strip()
    if not session_id:
        return None
    row = await db.get(ChatSession, session_id)
    if row is None or row.user_id != user_id:
        # Ignore unknown/foreign ids so Save Memory still works before first sync.
        return None
    if bool(row.private_mode):
        raise MemoryValidationError("Cannot attach memory to a private session")
    return session_id


async def create_memory(
    db: AsyncSession,
    user_id: int,
    content: str,
    *,
    source_session_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create a memory. Returns (payload, created) where created is False on dedupe hit."""
    normalized = normalize_memory_content(content)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    existing = (
        await db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.content_hash == digest,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return memory_to_client(existing), False

    if await _count_memories(db, user_id) >= MAX_MEMORIES_PER_USER:
        raise MemoryLimitError(f"Memory limit of {MAX_MEMORIES_PER_USER} reached")

    resolved_source = await _resolve_source_session_id(db, user_id, source_session_id)
    now = dt.datetime.utcnow()
    row = UserMemory(
        id=str(uuid.uuid4()),
        user_id=user_id,
        content=normalized,
        enabled=True,
        source_session_id=resolved_source,
        content_hash=digest,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raced = (
            await db.execute(
                select(UserMemory).where(
                    UserMemory.user_id == user_id,
                    UserMemory.content_hash == digest,
                )
            )
        ).scalar_one_or_none()
        if raced is None:
            raise
        return memory_to_client(raced), False
    return memory_to_client(row), True


async def _get_owned_memory(db: AsyncSession, user_id: int, memory_id: str) -> UserMemory:
    row = await db.get(UserMemory, memory_id)
    if row is None or row.user_id != user_id:
        raise MemoryNotFoundError("Memory not found")
    return row


async def update_memory(
    db: AsyncSession,
    user_id: int,
    memory_id: str,
    *,
    content: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    row = await _get_owned_memory(db, user_id, memory_id)
    changed = False
    if content is not None:
        normalized = normalize_memory_content(content)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if digest != row.content_hash:
            conflict = (
                await db.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user_id,
                        UserMemory.content_hash == digest,
                        UserMemory.id != row.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is not None:
                raise MemoryValidationError("Another memory with the same content already exists")
            row.content = normalized
            row.content_hash = digest
            changed = True
    if enabled is not None:
        next_enabled = bool(enabled)
        if next_enabled != bool(row.enabled):
            row.enabled = next_enabled
            changed = True
    if changed:
        row.updated_at = dt.datetime.utcnow()
        await db.flush()
    return memory_to_client(row)


async def delete_memory(db: AsyncSession, user_id: int, memory_id: str) -> None:
    row = await _get_owned_memory(db, user_id, memory_id)
    await db.delete(row)
    await db.flush()


async def delete_all_memories(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
    await db.flush()
    return int(result.rowcount or 0)


async def load_injectable_memories(
    db: AsyncSession,
    user_id: int,
    *,
    max_items: int | None = None,
) -> list[str]:
    prefs = await load_user_prefs(db, user_id)
    if not prefs.get("memory_enabled", True):
        return []
    item_limit = min(
        MAX_INJECT_ITEMS,
        max(0, int(max_items)) if max_items is not None else MAX_INJECT_ITEMS,
    )
    if item_limit == 0:
        return []
    rows = (
        await db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.enabled.is_(True))
            .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
            .limit(item_limit)
        )
    ).scalars().all()
    facts: list[str] = []
    total_chars = 0
    for row in rows:
        text = (row.content or "").strip()
        if not text:
            continue
        # Bullet prefix + newline overhead approximate.
        cost = len(text) + 2
        if total_chars + cost > MAX_INJECT_CHARS:
            break
        facts.append(text)
        total_chars += cost
    return facts


def format_memory_system_block(facts: list[str]) -> str:
    lines = [
        "## User memory",
        "The following are durable facts the user explicitly saved. Use them when relevant.",
        "Do not invent extra personal facts. Session messages remain the primary conversation context.",
    ]
    for fact in facts:
        lines.append(f"- {fact}")
    return "\n".join(lines)


async def augment_messages_with_memory(
    db: AsyncSession,
    messages: list[dict],
    *,
    user_id: int | None,
    private_mode: bool = False,
) -> list[dict]:
    """Prepend/merge memory system context. Never mutates non-system turns."""
    if user_id is None or private_mode:
        return messages
    facts = await load_injectable_memories(db, user_id)
    if not facts:
        return messages
    block = format_memory_system_block(facts)
    out = list(messages)
    if out and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        out[0] = {
            "role": "system",
            "content": f"{out[0]['content']}\n\n{block}",
        }
        return out
    return [{"role": "system", "content": block}, *out]
