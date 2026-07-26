"""Username normalization helpers (case-insensitive identity)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def normalize_username(value: str | None) -> str:
    """Canonical form for storage: strip + lowercase."""
    return (value or "").strip().lower()


async def find_user_by_username_ci(db: AsyncSession, username: str) -> User | None:
    """Look up a user by username without case sensitivity."""
    key = normalize_username(username)
    if not key:
        return None
    return (
        await db.execute(select(User).where(func.lower(User.username) == key))
    ).scalars().first()


async def username_taken_ci(
    db: AsyncSession,
    username: str,
    *,
    exclude_user_id: int | None = None,
) -> bool:
    key = normalize_username(username)
    if not key:
        return False
    stmt = select(User.id).where(func.lower(User.username) == key)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None
