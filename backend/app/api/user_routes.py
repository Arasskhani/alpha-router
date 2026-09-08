"""End-user panel API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import (
    _activity_export_response,
    _activity_query_filters,
    _build_scoped_activity,
    activity_explore_opts,
)
from app.api.deps import get_bearer_token, get_current_user, require_active_user
from app.services import activity_service
from app.database import get_db
from app.models.api_key import UserApiKey
from app.models.user import User
from app.services.user_api_key_service import (
    DEFAULT_PERSONAL_KEY_NAME,
    ensure_can_create_personal_key,
)
from app.services.user_role_service import primary_role_for_user

router = APIRouter(prefix="/api/user", tags=["user"])


def _serialize_user_key(key: UserApiKey, *, base_url: str) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.key_prefix,
        "url": f"{base_url}/v1",
        "is_active": key.is_active,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() + "Z" if key.last_used_at else None,
    }


@router.get("/api-keys/list")
async def list_user_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.config import get_settings

    rows = (
        await db.execute(
            select(UserApiKey)
            .where(UserApiKey.user_id == user.id)
            .order_by(UserApiKey.created_at.desc())
        )
    ).scalars().all()
    base = get_settings().api_public_url
    return [_serialize_user_key(k, base_url=base) for k in rows]


@router.get("/budget")
async def user_budget(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.budget_service import ensure_budget_period, resolve_monthly_budget

    await ensure_budget_period(db, user)
    budget = await resolve_monthly_budget(db, user)
    used = float(user.budget_used_usd or 0)
    reserved = float(user.budget_reserved_usd or 0)
    remaining = max(0.0, budget - used - reserved) if budget > 0 else None
    return {
        "monthly_budget_usd": budget,
        "used_usd": used,
        "reserved_usd": reserved,
        "remaining_usd": remaining,
    }


@router.post("/presence")
async def ping_presence(user: User = Depends(require_active_user)):
    """Refresh this user's online marker.

    The id comes from the session, never from the request body, so a caller can
    only ever report itself online. Disabled accounts are rejected by the
    dependency and therefore never appear online.
    """
    from app.services.presence_service import mark_online, presence_ttl_seconds

    recorded = await mark_online(user.id)
    return {"ok": recorded, "ttl_seconds": presence_ttl_seconds()}


class UserKeyIn(BaseModel):
    name: str = Field(default=DEFAULT_PERSONAL_KEY_NAME, min_length=1, max_length=128)


@router.post("/api-keys")
async def create_user_key(
    body: UserKeyIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    from app.config import get_settings
    from app.core.security import generate_api_key_for_user

    await ensure_can_create_personal_key(db, user)
    name = (body.name or DEFAULT_PERSONAL_KEY_NAME).strip() or DEFAULT_PERSONAL_KEY_NAME
    email_local = (user.email or user.username or "user").split("@")[0]
    raw, prefix, key_hash = generate_api_key_for_user(email_local)
    key = UserApiKey(
        user_id=user.id,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    s = get_settings()
    return {
        "id": key.id,
        "name": name,
        "api_key": raw,
        "prefix": prefix,
        "url": f"{s.api_public_url}/v1",
    }


@router.delete("/api-keys/{key_id}")
async def delete_user_key(
    key_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(UserApiKey, key_id)
    if not key or key.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(key)
    await db.commit()
    return {"ok": True}


@router.get("/activity")
async def my_activity(
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    personal_api_key_only: bool = Query(False),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    explore: dict = Depends(activity_explore_opts),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activity dashboard for the signed-in user only (never another account)."""
    user_api_key_id = None
    if personal_api_key_only:
        personal_key = (
            await db.execute(
                select(UserApiKey.id).where(UserApiKey.user_id == user.id).limit(1)
            )
        ).scalar_one_or_none()
        user_api_key_id = int(personal_key) if personal_key else -1
    filters = _activity_query_filters(
        model_id=model_id,
        username=None,
        app=app,
        response_status=response_status,
        user_api_key_id=user_api_key_id,
    )
    payload, options, prompts_card = await _build_scoped_activity(
        db,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        filters=filters,
        explore=explore,
        user_id=user.id,
    )
    return {
        **payload,
        **options,
        "prompts": prompts_card,
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
        "scope": "mine",
        "model_id": filters["model_id"],
        "filters": filters,
    }


@router.get("/activity/export")
async def my_activity_export(
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    personal_api_key_only: bool = Query(False),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    jwt_token: str = Depends(get_bearer_token),
):
    """Export activity for the signed-in user only."""
    user_api_key_id = None
    if personal_api_key_only:
        personal_key = (
            await db.execute(
                select(UserApiKey.id).where(UserApiKey.user_id == user.id).limit(1)
            )
        ).scalar_one_or_none()
        user_api_key_id = int(personal_key) if personal_key else -1
    filters = _activity_query_filters(
        model_id=model_id,
        username=None,
        app=app,
        response_status=response_status,
        user_api_key_id=user_api_key_id,
    )
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-my-activity-{user.id}-{period}",
        scope="mine",
        jwt_token=jwt_token,
        user_role=await primary_role_for_user(db, user.id),
        period=period,
        prompts_period=prompts_period,
        group_by="model",
        timezone=timezone,
        filters=filters,
        user_id=user.id,
    )
