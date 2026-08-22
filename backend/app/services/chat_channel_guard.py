"""Fail-closed checks so member rooms cannot spend on models."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession, is_member_channel

ROOM_SESSION_NOT_ALLOWED = "room_session_not_allowed"


async def assert_session_allows_model_generation(
    db: AsyncSession,
    session_id: str | None,
) -> None:
    """Reject completions and media jobs that target a human room session."""
    sid = (session_id or "").strip()
    if not sid:
        return
    session = await db.get(ChatSession, sid)
    if session is None:
        return
    if is_member_channel(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Human rooms cannot use models.",
                "code": ROOM_SESSION_NOT_ALLOWED,
            },
        )
