"""Server-owned Private Mode resolution and persistence invariants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession


class PrivateModePersistenceError(ValueError):
    """Raised when a private conversation would be written to server storage."""


@dataclass(frozen=True)
class PrivateModeContext:
    requested: bool
    session_private: bool
    effective: bool
    session_id: str | None


def private_mode_requested(body: dict[str, Any]) -> bool:
    """Read either supported spelling without accepting truthy strings."""

    return body.get("private_mode") is True or body.get("privateMode") is True


async def resolve_private_mode(
    db: AsyncSession,
    body: dict[str, Any],
    *,
    user_id: int | None,
    source: str,
) -> PrivateModeContext:
    """Resolve Private Mode from the request and the owned server session.

    The resolved value is stamped into the internal request body so every
    downstream subsystem (persistence, memory, profile, and Agent RAG) consumes
    one server-owned decision.
    """

    requested = private_mode_requested(body)
    raw_session_id = body.get("chat_session_id")
    session_id = (
        str(raw_session_id).strip()
        if isinstance(raw_session_id, str) and raw_session_id.strip()
        else None
    )
    session_private = False
    if source == "alpha_router_chat" and user_id is not None and session_id:
        session_private = bool(
            (
                await db.execute(
                    select(ChatSession.private_mode).where(
                        ChatSession.id == session_id,
                        ChatSession.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
        )

    effective = requested or session_private
    body["_effective_private_mode"] = effective
    if effective and body.get("persist_chat") is True:
        raise PrivateModePersistenceError(
            "Private Mode conversations cannot be persisted on the server"
        )
    return PrivateModeContext(
        requested=requested,
        session_private=session_private,
        effective=effective,
        session_id=session_id,
    )


def effective_private_mode(body: dict[str, Any]) -> bool:
    """Return the preflight decision, falling back to a strict request flag."""

    resolved = body.get("_effective_private_mode")
    if isinstance(resolved, bool):
        return resolved
    return private_mode_requested(body)


def assert_session_persistence_allowed(session: ChatSession) -> None:
    """Fail closed before any message mutation on a private session."""

    if bool(session.private_mode):
        raise PrivateModePersistenceError(
            "Private Mode session messages cannot be stored on the server"
        )
