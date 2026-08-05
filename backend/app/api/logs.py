"""API request logs (admin + user)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user, require_api_logs, require_api_logs_write
from app.database import get_db
from app.models.api_key import AlphaRouterApiKey
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User
from app.utils.display import format_app_source

router = APIRouter(prefix="/api", tags=["logs"])


def _log_row(
    r: RequestLog,
    provider: str | None = None,
    *,
    router_key: AlphaRouterApiKey | None = None,
) -> dict:
    source_code = (r.source or "").strip().lower()
    if source_code == "alpha_router_chat":
        app = format_app_source(r.source)
    else:
        app = (r.client_app or "").strip() or format_app_source(r.source)
    if r.alpha_router_api_key_id:
        identity_type = "api_key"
    elif source_code == "alpha_router_chat":
        identity_type = "chat"
    else:
        identity_type = "user"
    row = {
        "id": r.id,
        "request_time": r.request_time.isoformat() if r.request_time else None,
        "username": r.username,
        "identity_type": identity_type,
        "model_id": r.model_id,
        "provider": provider or "",
        "app": app,
        "prompt_language": r.prompt_language,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "cached_tokens": r.cached_tokens,
        "total_tokens": (r.prompt_tokens or 0) + (r.completion_tokens or 0),
        "total_cost_usd": r.total_cost_usd,
        "response_time_ms": r.response_time_ms,
        "source_ip": r.source_ip,
        "source": r.source,
        "client_app": r.client_app,
        "success": r.success,
        "error_message": r.error_message,
    }
    if router_key:
        row["api_key_name"] = router_key.name
        row["api_key_prefix"] = router_key.key_prefix
        row["alpha_router_api_key_id"] = router_key.id
    return row


def _apply_log_filters(
    q,
    *,
    username: str | None,
    model_id: str | None,
    response_status: str | None,
    prompt_cache: str | None,
    start_date: str | None,
    end_date: str | None,
):
    if username:
        term = username.strip()
        key_match = select(AlphaRouterApiKey.id).where(
            AlphaRouterApiKey.name.contains(term)
        )
        q = q.where(
            or_(
                RequestLog.username.contains(term),
                RequestLog.alpha_router_api_key_id.in_(key_match),
            )
        )
    if model_id:
        q = q.where(RequestLog.model_id.contains(model_id.strip()))
    if response_status == "success":
        q = q.where(RequestLog.success.is_(True))
    elif response_status == "fail":
        q = q.where(RequestLog.success.is_(False))
    if prompt_cache == "yes":
        q = q.where(RequestLog.cached_tokens > 0)
    elif prompt_cache == "no":
        q = q.where(or_(RequestLog.cached_tokens == 0, RequestLog.cached_tokens.is_(None)))
    if start_date:
        q = q.where(RequestLog.request_time >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        q = q.where(RequestLog.request_time <= datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59))
    return q


@router.get("/admin/logs/filter-options")
async def admin_logs_filter_options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
):
    """Distinct usernames, API key names, and models present in request logs (for filter comboboxes)."""
    usernames = (
        await db.execute(
            select(RequestLog.username)
            .where(RequestLog.username.isnot(None), RequestLog.username != "")
            .distinct()
            .order_by(RequestLog.username)
        )
    ).scalars().all()
    models = (
        await db.execute(
            select(RequestLog.model_id)
            .where(RequestLog.model_id.isnot(None), RequestLog.model_id != "")
            .distinct()
            .order_by(RequestLog.model_id)
        )
    ).scalars().all()
    api_keys = (
        await db.execute(
            select(AlphaRouterApiKey.name)
            .join(
                RequestLog,
                RequestLog.alpha_router_api_key_id == AlphaRouterApiKey.id,
            )
            .where(
                AlphaRouterApiKey.name.isnot(None),
                AlphaRouterApiKey.name != "",
            )
            .distinct()
            .order_by(AlphaRouterApiKey.name)
        )
    ).scalars().all()

    identity_options: list[str] = []
    seen: set[str] = set()
    for name in list(usernames) + list(api_keys):
        label = (name or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        identity_options.append(label)

    return {
        "usernames": identity_options,
        "models": [m for m in models if (m or "").strip()],
    }


@router.get("/admin/logs")
async def admin_logs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
    limit: int = Query(100, le=500),
    offset: int = 0,
    username: str | None = None,
    model_id: str | None = None,
    response_status: str | None = Query(default=None, pattern="^(success|fail)$"),
    prompt_cache: str | None = Query(default=None, pattern="^(yes|no)$"),
    start_date: str | None = None,
    end_date: str | None = None,
):
    q = select(RequestLog).order_by(RequestLog.request_time.desc())
    q = _apply_log_filters(
        q,
        username=username,
        model_id=model_id,
        response_status=response_status,
        prompt_cache=prompt_cache,
        start_date=start_date,
        end_date=end_date,
    )
    rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
    model_ids = list({(r.model_id or "").strip() for r in rows if (r.model_id or "").strip()})
    provider_map: dict[str, str] = {}
    if model_ids:
        model_rows = (
            await db.execute(
                select(AIModel.external_id, AIModel.provider_type)
                .where(AIModel.external_id.in_(model_ids))
                .order_by(AIModel.id.desc())
            )
        ).all()
        for external_id, provider in model_rows:
            if external_id and external_id not in provider_map:
                provider_map[str(external_id)] = str(provider or "")

    key_ids = {
        r.alpha_router_api_key_id
        for r in rows
        if r.alpha_router_api_key_id
    }
    key_map: dict[int, AlphaRouterApiKey] = {}
    if key_ids:
        keys = (
            await db.execute(
                select(AlphaRouterApiKey).where(
                    AlphaRouterApiKey.id.in_(key_ids)
                )
            )
        ).scalars().all()
        key_map = {k.id: k for k in keys}

    return {
        "items": [
            _log_row(
                r,
                provider_map.get((r.model_id or "").strip()),
                router_key=key_map.get(r.alpha_router_api_key_id),
            )
            for r in rows
        ],
        "offset": offset,
        "limit": limit,
    }


@router.delete("/admin/logs")
async def clear_admin_logs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs_write),
):
    """Permanently delete all API request log rows."""
    result = await db.execute(delete(RequestLog))
    await db.commit()
    return {"ok": True, "deleted": result.rowcount}


@router.get("/user/logs")
async def user_logs_route(
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(200, le=500),
):
    rows = (
        await db.execute(
            select(RequestLog)
            .where(RequestLog.user_id == user.id)
            .order_by(RequestLog.request_time.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_log_row(r) for r in rows]
