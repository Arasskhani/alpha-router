"""End-user panel API."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _activity_export_response, _activity_query_filters, _load_activity_context
from app.api.deps import get_bearer_token, get_current_user, require_active_user
from app.services import activity_service
from app.database import get_db
from app.models.api_key import UserApiKey
from app.models.user import User
from app.services.user_role_service import primary_role_for_user

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/api-keys/list")
async def list_user_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.config import get_settings

    rows = (await db.execute(select(UserApiKey).where(UserApiKey.user_id == user.id))).scalars().all()
    base = get_settings().api_public_url
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.key_prefix,
            "url": f"{base}/v1",
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in rows
    ]


@router.get("/budget")
async def user_budget(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.budget_service import ensure_budget_period, get_month_usage, resolve_monthly_budget

    await ensure_budget_period(db, user)
    budget = await resolve_monthly_budget(db, user)
    used = await get_month_usage(db, user.id)
    return {
        "monthly_budget_usd": budget,
        "used_usd": used,
        "remaining_usd": max(0, budget - used) if budget > 0 else None,
    }


class UserKeyIn(BaseModel):
    name: str


@router.post("/api-keys")
async def create_user_key(body: UserKeyIn, user: User = Depends(require_active_user), db: AsyncSession = Depends(get_db)):
    email_local = (user.email or user.username or "user").split("@")[0]
    from app.core.security import generate_api_key_for_user

    raw, prefix, key_hash = generate_api_key_for_user(email_local)
    db.add(UserApiKey(user_id=user.id, name=body.name, key_prefix=prefix, key_hash=key_hash))
    await db.commit()
    from app.config import get_settings

    s = get_settings()
    return {"name": body.name, "api_key": raw, "url": f"{s.api_public_url}/v1"}


@router.get("/activity")
async def my_activity(
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activity dashboard for the signed-in user only (never another account)."""
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
    (
        rows,
        prev_rows,
        heatmap_rows,
        options_rows,
        since,
        now,
        prompts_rows,
        prompts_prev_rows,
        since_prompts,
    ) = await _load_activity_context(
        db,
        period=period,
        prompts_period=pp,
        group_by="model",
        timezone=timezone,
        filters=filters,
        user_id=user.id,
    )
    options = activity_service.filter_options(options_rows, "model")
    payload = activity_service.build_activity_payload(
        rows,
        period=period,
        since=since,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prev_rows,
        heatmap_rows=heatmap_rows,
    )
    prompts_card = activity_service.build_prompts_card(
        prompts_rows,
        period=pp,
        since=since_prompts,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prompts_prev_rows,
        heatmap_rows=heatmap_rows,
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
    timezone: str = Query("local", pattern="^(local|utc)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    jwt_token: str = Depends(get_bearer_token),
):
    """Export activity for the signed-in user only."""
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
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
