"""Personal (user-owned) API keys — one per user, debits monthly budget."""

from __future__ import annotations

import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import UserApiKey
from app.models.user import User
from app.services.budget_service import ensure_budget_period, resolve_monthly_budget

MAX_PERSONAL_KEYS_PER_USER = 1
DEFAULT_PERSONAL_KEY_NAME = "Personal API Key"


async def count_active_user_keys(db: AsyncSession, user_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(UserApiKey)
                .where(UserApiKey.user_id == user_id)
            )
        ).scalar_one()
        or 0
    )


async def ensure_can_create_personal_key(db: AsyncSession, user: User) -> None:
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account disabled. You cannot create an API key.",
        )
    await ensure_budget_period(db, user)
    budget = await resolve_monthly_budget(db, user)
    if budget <= 0:
        raise HTTPException(
            status_code=402,
            detail="No monthly budget plan assigned. Contact an administrator.",
        )
    existing = await count_active_user_keys(db, user.id)
    if existing >= MAX_PERSONAL_KEYS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail="You already have a personal API key. Revoke it before creating a new one.",
        )


async def touch_user_key_last_used(
    db: AsyncSession,
    user_api_key_id: int | None,
) -> None:
    if not user_api_key_id:
        return
    key = await db.get(UserApiKey, user_api_key_id)
    if key:
        key.last_used_at = datetime.datetime.utcnow()
