"""Admin gateway API keys: limits, period reset, expiration."""

from __future__ import annotations

import datetime
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import AlphaRouterApiKey

ResetPeriod = Literal["daily", "weekly", "monthly"]


def _utc_now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _period_delta(reset_period: str) -> datetime.timedelta:
    if reset_period == "daily":
        return datetime.timedelta(days=1)
    if reset_period == "weekly":
        return datetime.timedelta(days=7)
    return datetime.timedelta(days=30)


def compute_expires_at(
    created_at: datetime.datetime | None,
    expiration_days: int | None,
) -> datetime.datetime | None:
    if not expiration_days or expiration_days <= 0:
        return None
    base = created_at or _utc_now()
    return base + datetime.timedelta(days=int(expiration_days))


async def maybe_reset_key_period(db: AsyncSession, key: AlphaRouterApiKey) -> None:
    now = _utc_now()
    if not key.period_started_at:
        key.period_started_at = now
        key.period_used_usd = 0.0
        key.period_reserved_usd = 0.0
        await db.flush()
        return
    if (now - key.period_started_at) >= _period_delta(key.reset_period or "monthly"):
        # Lazy import avoids cycle with budget_reservation_service.
        from app.services.budget_reservation_service import (
            SUBJECT_ALPHA_ROUTER_KEY,
            release_open_holds_for_subject,
        )

        await release_open_holds_for_subject(db, SUBJECT_ALPHA_ROUTER_KEY, int(key.id))
        key.period_started_at = now
        key.period_used_usd = 0.0
        key.period_reserved_usd = 0.0
        await db.flush()


def apply_expiration(key: AlphaRouterApiKey) -> bool:
    """Deactivate if past expires_at. Returns False if key is unusable."""
    if key.expires_at and _utc_now() >= key.expires_at:
        key.is_active = False
        return False
    return bool(key.is_active)


async def ensure_key_usable(db: AsyncSession, key: AlphaRouterApiKey) -> None:
    if not apply_expiration(key):
        raise HTTPException(status_code=403, detail="API key has expired")
    if not key.is_active:
        raise HTTPException(status_code=403, detail="API key is disabled")
    await maybe_reset_key_period(db, key)
    limit = float(key.credit_limit_usd or 0)
    if limit <= 0 and not key_is_unlimited(key):
        # Formerly "0 means no cap": a forgotten field silently made the key a
        # blank cheque. Unlimited is now an explicit admin decision.
        raise HTTPException(
            status_code=402,
            detail="API key has no credit limit configured; ask an administrator to set one",
        )
    if limit > 0 and float(key.period_used_usd or 0) >= limit:
        raise HTTPException(status_code=402, detail="API key credit limit exceeded for this period")


def key_is_unlimited(key: AlphaRouterApiKey) -> bool:
    """True only when an admin explicitly marked the key as unlimited."""
    return bool(getattr(key, "unlimited_budget", False))


async def record_key_usage(db: AsyncSession, key: AlphaRouterApiKey, cost_usd: float) -> None:
    if cost_usd <= 0:
        return
    await maybe_reset_key_period(db, key)
    # Atomic increment via SQL UPDATE — concurrent gateway requests using the
    # same Alpharouter key would otherwise race on period_used_usd/total_used_usd
    # and lose updates (read-modify-write on the ORM object is not atomic).
    await db.execute(
        text(
            "UPDATE alpha_router_api_keys SET "
            "period_used_usd = COALESCE(period_used_usd, 0) + :cost, "
            "total_used_usd = COALESCE(total_used_usd, 0) + :cost, "
            "last_used_at = :now WHERE id = :kid"
        ),
        {"cost": float(cost_usd), "now": _utc_now(), "kid": key.id},
    )
    await db.refresh(
        key,
        attribute_names=["period_used_usd", "total_used_usd", "last_used_at"],
    )


def key_to_dict(
    key: AlphaRouterApiKey,
    owner: dict | None = None,
    *,
    allowed_connections: list[dict] | None = None,
    allowed_models: list[dict] | None = None,
) -> dict:
    expires = key.expires_at
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.key_prefix,
        "is_active": bool(key.is_active),
        "created_at": key.created_at.isoformat() + "Z" if key.created_at else None,
        "updated_at": (
            (key.updated_at or key.created_at).isoformat() + "Z" if (key.updated_at or key.created_at) else None
        ),
        "last_used_at": key.last_used_at.isoformat() + "Z" if key.last_used_at else None,
        "owner_user_id": key.owner_user_id,
        "owner_email": owner.get("email") if owner else None,
        "owner_username": owner.get("username") if owner else None,
        "owner_display_name": owner.get("display_name") if owner else None,
        "credit_limit_usd": float(key.credit_limit_usd or 0),
        "unlimited_budget": key_is_unlimited(key),
        "reset_period": key.reset_period or "monthly",
        "expires_at": expires.isoformat() if expires else None,
        "expiration_never": expires is None,
        "period_used_usd": float(key.period_used_usd or 0),
        "period_reserved_usd": float(key.period_reserved_usd or 0),
        "total_used_usd": float(key.total_used_usd or 0),
        "period_started_at": key.period_started_at.isoformat() if key.period_started_at else None,
        "restrict_connections": bool(key.restrict_connections),
        "allowed_connections": list(allowed_connections or []),
        "restrict_models": bool(key.restrict_models),
        "allowed_models": list(allowed_models or []),
    }
