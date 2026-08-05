"""Report generation: 30 predefined reports — CSV, XLS, PDF."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import AlphaRouterApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User, UserGroup, user_group_members
from app.services.plan_assignment_service import USER_PLAN_NONE, get_user_direct_assignment, user_plan_mode


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return float(ordered[idx])


async def _provider_map(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(select(AIModel.external_id, AIModel.provider_type))).all()
    out: dict[str, str] = {}
    for external_id, provider in rows:
        if external_id and external_id not in out:
            out[str(external_id)] = str(provider or "")
    return out


async def users_for_plan(db: AsyncSession, plan_id: int) -> list[int]:
    assigns = (
        await db.execute(select(PlanAssignment).where(PlanAssignment.plan_id == plan_id))
    ).scalars().all()
    user_ids: set[int] = set()
    group_ids: set[int] = set()
    departments: set[str] = set()
    for a in assigns:
        if a.user_id:
            user_ids.add(int(a.user_id))
        if a.group_id:
            group_ids.add(int(a.group_id))
        if a.department:
            departments.add(str(a.department))
    if group_ids:
        rows = (
            await db.execute(
                select(user_group_members.c.user_id).where(user_group_members.c.group_id.in_(group_ids))
            )
        ).all()
        user_ids.update(int(r[0]) for r in rows if r[0] is not None)
    if departments:
        rows = (
            await db.execute(
                select(User.id).where(
                    User.deleted_at.is_(None),
                    User.department.in_(departments),
                )
            )
        ).all()
        user_ids.update(int(r[0]) for r in rows if r[0] is not None)
    return list(user_ids)


def _apply_log_filters(q, *, start: datetime | None, end: datetime | None, user_ids: list[int] | None = None):
    if start is not None:
        q = q.where(RequestLog.request_time >= start)
    if end is not None:
        q = q.where(RequestLog.request_time <= end)
    if user_ids is not None:
        if not user_ids:
            q = q.where(RequestLog.user_id == -1)
        else:
            q = q.where(RequestLog.user_id.in_(user_ids))
    return q


async def report_user_budget_usage(
    db: AsyncSession, start: datetime, end: datetime, user_id: int | None = None
) -> pd.DataFrame:
    user_ids = [user_id] if user_id else None
    if user_id is None:
        rows = (
            await db.execute(
                select(RequestLog.user_id)
                .where(
                    RequestLog.request_time >= start,
                    RequestLog.request_time <= end,
                    RequestLog.user_id.isnot(None),
                )
                .distinct()
            )
        ).all()
        user_ids = [int(r[0]) for r in rows if r[0] is not None]
    q = (
        select(
            RequestLog.username,
            func.sum(RequestLog.total_cost_usd).label("cost_usd"),
            func.count().label("requests"),
            func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens).label("tokens"),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(RequestLog.username)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    if user_ids is not None:
        q = q.where(RequestLog.user_id.in_(user_ids))
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "username": r[0],
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
                "tokens": int(r[3] or 0),
            }
            for r in rows
        ]
    )


async def report_plan_usage(db: AsyncSession, plan_id: int, start: datetime, end: datetime) -> pd.DataFrame:
    plan = await db.get(BudgetPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    user_ids = await users_for_plan(db, plan_id)
    if not user_ids:
        return pd.DataFrame(columns=["username", "cost_usd", "requests", "tokens"])
    q = (
        select(
            RequestLog.username,
            func.sum(RequestLog.total_cost_usd).label("cost_usd"),
            func.count().label("requests"),
            func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens).label("tokens"),
        )
        .where(
            RequestLog.user_id.in_(user_ids),
            RequestLog.request_time >= start,
            RequestLog.request_time <= end,
        )
        .group_by(RequestLog.username)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "username": r[0],
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
                "tokens": int(r[3] or 0),
            }
            for r in rows
        ]
    )


async def report_org_cost_summary(db: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    row = (
        await db.execute(
            select(
                func.sum(RequestLog.total_cost_usd),
                func.count(),
                func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
                func.sum(RequestLog.prompt_tokens),
                func.sum(RequestLog.completion_tokens),
                func.sum(RequestLog.cached_tokens),
            ).where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        )
    ).one()
    return pd.DataFrame(
        [
            {
                "total_cost_usd": round(float(row[0] or 0), 4),
                "requests": int(row[1] or 0),
                "total_tokens": int(row[2] or 0),
                "prompt_tokens": int(row[3] or 0),
                "completion_tokens": int(row[4] or 0),
                "cached_tokens": int(row[5] or 0),
            }
        ]
    )


async def report_users_near_budget_limit(db: AsyncSession, threshold_pct: float) -> pd.DataFrame:
    users = (
        await db.execute(
            select(User).where(
                User.deleted_at.is_(None),
                User.monthly_budget_usd > 0,
            )
        )
    ).scalars().all()
    rows = []
    for u in users:
        budget = float(u.monthly_budget_usd or 0)
        used = float(u.budget_used_usd or 0)
        if budget <= 0:
            continue
        pct = (used / budget) * 100
        if pct >= threshold_pct:
            rows.append(
                {
                    "username": u.username,
                    "display_name": u.display_name or "",
                    "monthly_budget_usd": round(budget, 2),
                    "budget_used_usd": round(used, 4),
                    "usage_pct": round(pct, 1),
                }
            )
    rows.sort(key=lambda x: x["usage_pct"], reverse=True)
    return pd.DataFrame(rows)


async def report_users_without_budget(db: AsyncSession) -> pd.DataFrame:
    users = (
        await db.execute(select(User).where(User.deleted_at.is_(None)))
    ).scalars().all()
    rows = []
    for u in users:
        direct = await get_user_direct_assignment(db, u.id)
        mode = user_plan_mode(direct)
        budget = float(u.monthly_budget_usd or 0)
        if mode == USER_PLAN_NONE or budget <= 0:
            rows.append(
                {
                    "username": u.username,
                    "display_name": u.display_name or "",
                    "user_plan_mode": mode,
                    "monthly_budget_usd": budget,
                    "department": u.department or "",
                }
            )
    return pd.DataFrame(rows)


async def report_department_top_models(
    db: AsyncSession, department: str, start: datetime, end: datetime, top_n: int = 5
) -> pd.DataFrame:
    user_ids = [
        int(r[0])
        for r in (
            await db.execute(
                select(User.id).where(User.deleted_at.is_(None), User.department == department)
            )
        ).all()
        if r[0] is not None
    ]
    if not user_ids:
        return pd.DataFrame()
    q = (
        select(
            RequestLog.model_id,
            func.sum(RequestLog.total_cost_usd).label("cost_usd"),
            func.count().label("requests"),
        )
        .where(
            RequestLog.user_id.in_(user_ids),
            RequestLog.request_time >= start,
            RequestLog.request_time <= end,
        )
        .group_by(RequestLog.model_id)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
        .limit(top_n)
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "department": department,
                "model": r[0],
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
            }
            for r in rows
        ]
    )


async def report_office_usage(
    db: AsyncSession, start: datetime, end: datetime, office: str | None = None
) -> pd.DataFrame:
    q = (
        select(User.office, User.username, func.sum(RequestLog.total_cost_usd), func.count())
        .join(RequestLog, RequestLog.user_id == User.id)
        .where(
            RequestLog.request_time >= start,
            RequestLog.request_time <= end,
            User.deleted_at.is_(None),
        )
        .group_by(User.office, User.username)
    )
    if office:
        q = q.where(User.office == office)
    rows = (await db.execute(q)).all()
    data = [
        {
            "office": r[0] or "—",
            "username": r[1],
            "cost_usd": round(float(r[2] or 0), 4),
            "requests": int(r[3] or 0),
        }
        for r in rows
    ]
    df = pd.DataFrame(data)
    if df.empty:
        return df
    return df.sort_values("cost_usd", ascending=False).reset_index(drop=True)


async def report_top_users_by_spend(db: AsyncSession, start: datetime, end: datetime, top_n: int) -> pd.DataFrame:
    q = (
        select(
            RequestLog.username,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
            func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(RequestLog.username)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
        .limit(top_n)
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "username": r[0],
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
                "tokens": int(r[3] or 0),
            }
            for r in rows
        ]
    )


async def report_top_models_by_spend(db: AsyncSession, start: datetime, end: datetime, top_n: int) -> pd.DataFrame:
    q = (
        select(
            RequestLog.model_id,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
            func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(RequestLog.model_id)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
        .limit(top_n)
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "model": r[0],
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
                "tokens": int(r[3] or 0),
            }
            for r in rows
        ]
    )


async def report_user_model_usage(
    db: AsyncSession, start: datetime, end: datetime, user_id: int | None
) -> pd.DataFrame:
    user_ids = [user_id] if user_id else None
    if user_id is None:
        rows = (
            await db.execute(
                select(RequestLog.user_id)
                .where(
                    RequestLog.request_time >= start,
                    RequestLog.request_time <= end,
                    RequestLog.user_id.isnot(None),
                )
                .distinct()
            )
        ).all()
        user_ids = [int(r[0]) for r in rows if r[0] is not None]
    q = (
        select(
            RequestLog.username,
            RequestLog.model_id,
            func.sum(RequestLog.total_cost_usd),
            func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
            func.count(),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(RequestLog.username, RequestLog.model_id)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    if user_ids is not None:
        q = q.where(RequestLog.user_id.in_(user_ids))
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "username": r[0],
                "model": r[1],
                "cost_usd": round(float(r[2] or 0), 4),
                "tokens": int(r[3] or 0),
                "requests": int(r[4] or 0),
            }
            for r in rows
        ]
    )


async def report_usage_by_app(
    db: AsyncSession, start: datetime, end: datetime, app: str | None
) -> pd.DataFrame:
    q = (
        select(
            RequestLog.client_app,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(RequestLog.client_app)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    if app:
        q = q.where(RequestLog.client_app == app)
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "app": r[0] or "—",
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
            }
            for r in rows
        ]
    )


async def report_usage_by_api_source(db: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    q = (
        select(
            RequestLog.source,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(RequestLog.source)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "source": r[0] or "—",
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
            }
            for r in rows
        ]
    )


async def report_usage_by_provider(
    db: AsyncSession, start: datetime, end: datetime, provider: str | None
) -> pd.DataFrame:
    prov_map = await _provider_map(db)
    q = select(RequestLog.model_id, RequestLog.total_cost_usd).where(
        RequestLog.request_time >= start, RequestLog.request_time <= end
    )
    rows = (await db.execute(q)).all()
    agg: dict[str, dict[str, float]] = {}
    for model_id, cost in rows:
        p = prov_map.get((model_id or "").strip(), "unknown")
        if provider and p.lower() != provider.lower():
            continue
        bucket = agg.setdefault(p, {"cost_usd": 0.0, "requests": 0})
        bucket["cost_usd"] += float(cost or 0)
        bucket["requests"] += 1
    data = [
        {"provider": k, "cost_usd": round(v["cost_usd"], 4), "requests": int(v["requests"])}
        for k, v in sorted(agg.items(), key=lambda x: x[1]["cost_usd"], reverse=True)
    ]
    return pd.DataFrame(data)


async def report_token_breakdown(db: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    row = (
        await db.execute(
            select(
                func.sum(RequestLog.prompt_tokens),
                func.sum(RequestLog.completion_tokens),
                func.sum(RequestLog.cached_tokens),
                func.count(),
            ).where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        )
    ).one()
    return pd.DataFrame(
        [
            {
                "prompt_tokens": int(row[0] or 0),
                "completion_tokens": int(row[1] or 0),
                "cached_tokens": int(row[2] or 0),
                "total_tokens": int((row[0] or 0) + (row[1] or 0)),
                "requests": int(row[3] or 0),
            }
        ]
    )


async def report_usage_by_prompt_language(db: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    q = (
        select(
            RequestLog.prompt_language,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(RequestLog.prompt_language)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "language": r[0] or "—",
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
            }
            for r in rows
        ]
    )


async def report_model_error_rates(
    db: AsyncSession, start: datetime, end: datetime, model_id: str | None
) -> pd.DataFrame:
    q = select(RequestLog.model_id, RequestLog.success).where(
        RequestLog.request_time >= start, RequestLog.request_time <= end
    )
    if model_id:
        q = q.where(RequestLog.model_id == model_id)
    rows = (await db.execute(q)).all()
    stats: dict[str, dict[str, int]] = {}
    for mid, success in rows:
        key = mid or "—"
        bucket = stats.setdefault(key, {"total": 0, "errors": 0})
        bucket["total"] += 1
        if not success:
            bucket["errors"] += 1
    data = []
    for model, s in stats.items():
        total = s["total"]
        err = s["errors"]
        rate = (err / total * 100) if total else 0
        data.append(
            {
                "model": model,
                "total_requests": total,
                "errors": err,
                "error_rate_pct": round(rate, 2),
            }
        )
    df = pd.DataFrame(data)
    if df.empty:
        return df
    return df.sort_values("error_rate_pct", ascending=False).reset_index(drop=True)


async def report_failed_requests(
    db: AsyncSession,
    start: datetime,
    end: datetime,
    user_id: int | None,
    model_id: str | None,
    limit: int = 500,
) -> pd.DataFrame:
    q = (
        select(
            RequestLog.request_time,
            RequestLog.username,
            RequestLog.model_id,
            RequestLog.error_message,
            RequestLog.total_cost_usd,
        )
        .where(
            RequestLog.request_time >= start,
            RequestLog.request_time <= end,
            RequestLog.success == False,  # noqa: E712
        )
        .order_by(RequestLog.request_time.desc())
        .limit(limit)
    )
    if user_id:
        q = q.where(RequestLog.user_id == user_id)
    if model_id:
        q = q.where(RequestLog.model_id == model_id)
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "request_time": r[0].isoformat() if r[0] else "",
                "username": r[1] or "",
                "model": r[2],
                "error_message": (r[3] or "")[:500],
                "cost_usd": round(float(r[4] or 0), 4),
            }
            for r in rows
        ]
    )


async def report_slow_models_latency(
    db: AsyncSession, start: datetime, end: datetime, latency_ms: float, min_requests: int = 3
) -> pd.DataFrame:
    q = select(RequestLog.model_id, RequestLog.response_time_ms).where(
        RequestLog.request_time >= start,
        RequestLog.request_time <= end,
        RequestLog.response_time_ms.isnot(None),
    )
    rows = (await db.execute(q)).all()
    by_model: dict[str, list[float]] = {}
    for mid, ms in rows:
        if mid:
            by_model.setdefault(mid, []).append(float(ms or 0))
    data = []
    for model, times in by_model.items():
        if len(times) < min_requests:
            continue
        avg = sum(times) / len(times)
        data.append(
            {
                "model": model,
                "requests": len(times),
                "avg_ms": round(avg, 1),
                "p95_ms": round(_p95(times), 1),
                "max_ms": round(max(times), 1),
            }
        )
    df = pd.DataFrame(data)
    if df.empty:
        return df
    return df.sort_values("p95_ms", ascending=False).reset_index(drop=True)


async def report_slow_requests(
    db: AsyncSession, start: datetime, end: datetime, latency_ms: float, limit: int = 500
) -> pd.DataFrame:
    q = (
        select(
            RequestLog.request_time,
            RequestLog.username,
            RequestLog.model_id,
            RequestLog.response_time_ms,
            RequestLog.total_cost_usd,
        )
        .where(
            RequestLog.request_time >= start,
            RequestLog.request_time <= end,
            RequestLog.response_time_ms >= latency_ms,
        )
        .order_by(RequestLog.response_time_ms.desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "request_time": r[0].isoformat() if r[0] else "",
                "username": r[1] or "",
                "model": r[2],
                "response_time_ms": round(float(r[3] or 0), 1),
                "cost_usd": round(float(r[4] or 0), 4),
            }
            for r in rows
        ]
    )


async def report_activity_summary(
    db: AsyncSession, start: datetime, end: datetime, group_by: str
) -> pd.DataFrame:
    if group_by == "user":
        col = RequestLog.username
        label = "username"
    elif group_by == "app":
        col = RequestLog.client_app
        label = "app"
    else:
        col = RequestLog.model_id
        label = "model"
        group_by = "model"
    q = (
        select(
            col,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
            func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
        )
        .where(RequestLog.request_time >= start, RequestLog.request_time <= end)
        .group_by(col)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                label: r[0] or "—",
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
                "tokens": int(r[3] or 0),
            }
            for r in rows
        ]
    )


async def report_deactivated_users(db: AsyncSession) -> pd.DataFrame:
    users = (
        await db.execute(
            select(User).where(User.deleted_at.is_(None), User.is_active == False)  # noqa: E712
        )
    ).scalars().all()
    return pd.DataFrame(
        [
            {
                "username": u.username,
                "display_name": u.display_name or "",
                "email": u.email or "",
                "auth_provider": u.auth_provider,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else "",
            }
            for u in users
        ]
    )


async def report_users_no_recent_login(
    db: AsyncSession, end: datetime, inactive_days: int
) -> pd.DataFrame:
    cutoff = end - timedelta(days=inactive_days)
    users = (
        await db.execute(
            select(User).where(
                User.deleted_at.is_(None),
                User.is_active == True,  # noqa: E712
                or_(User.last_login_at.is_(None), User.last_login_at < cutoff),
            )
        )
    ).scalars().all()
    return pd.DataFrame(
        [
            {
                "username": u.username,
                "display_name": u.display_name or "",
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else "",
                "inactive_days_threshold": inactive_days,
            }
            for u in users
        ]
    )


async def report_new_users(db: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    users = (
        await db.execute(
            select(User).where(
                User.created_at >= start,
                User.created_at <= end,
            )
        )
    ).scalars().all()
    return pd.DataFrame(
        [
            {
                "username": u.username,
                "display_name": u.display_name or "",
                "email": u.email or "",
                "auth_provider": u.auth_provider,
                "created_at": u.created_at.isoformat() if u.created_at else "",
            }
            for u in users
        ]
    )


async def report_deleted_users(db: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    users = (
        await db.execute(
            select(User).where(
                User.deleted_at.isnot(None),
                User.deleted_at >= start,
                User.deleted_at <= end,
            )
        )
    ).scalars().all()
    return pd.DataFrame(
        [
            {
                "username": u.username,
                "display_name": u.display_name or "",
                "email": u.email or "",
                "deleted_at": u.deleted_at.isoformat() if u.deleted_at else "",
            }
            for u in users
        ]
    )


async def report_auth_provider_distribution(db: AsyncSession) -> pd.DataFrame:
    rows = (
        await db.execute(
            select(User.auth_provider, func.count())
            .where(User.deleted_at.is_(None))
            .group_by(User.auth_provider)
            .order_by(func.count().desc())
        )
    ).all()
    return pd.DataFrame(
        [{"auth_provider": r[0] or "—", "user_count": int(r[1] or 0)} for r in rows]
    )


async def report_users_without_group(db: AsyncSession, auth_provider: str | None) -> pd.DataFrame:
    member_exists = (
        select(user_group_members.c.user_id)
        .where(user_group_members.c.user_id == User.id)
        .correlate(User)
        .exists()
    )
    q = select(User).where(
        User.deleted_at.is_(None),
        User.is_active == True,  # noqa: E712
        ~member_exists,
    )
    if auth_provider:
        q = q.where(User.auth_provider == auth_provider)
    users = (await db.execute(q)).scalars().all()
    return pd.DataFrame(
        [
            {
                "username": u.username,
                "display_name": u.display_name or "",
                "auth_provider": u.auth_provider,
                "department": u.department or "",
            }
            for u in users
        ]
    )


async def report_group_members_usage(
    db: AsyncSession, group_id: int, start: datetime, end: datetime
) -> pd.DataFrame:
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    member_ids = [
        int(r[0])
        for r in (
            await db.execute(
                select(user_group_members.c.user_id).where(user_group_members.c.group_id == group_id)
            )
        ).all()
        if r[0] is not None
    ]
    if not member_ids:
        return pd.DataFrame(columns=["group", "username", "cost_usd", "requests"])
    q = (
        select(
            RequestLog.username,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
        )
        .where(
            RequestLog.user_id.in_(member_ids),
            RequestLog.request_time >= start,
            RequestLog.request_time <= end,
        )
        .group_by(RequestLog.username)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    rows = (await db.execute(q)).all()
    return pd.DataFrame(
        [
            {
                "group": group.name,
                "username": r[0],
                "cost_usd": round(float(r[1] or 0), 4),
                "requests": int(r[2] or 0),
            }
            for r in rows
        ]
    )


async def report_plan_assignments(db: AsyncSession, plan_id: int | None) -> pd.DataFrame:
    q = select(PlanAssignment)
    if plan_id:
        q = q.where(PlanAssignment.plan_id == plan_id)
    assigns = (await db.execute(q)).scalars().all()
    plan_names: dict[int, str] = {}
    if assigns:
        plan_ids = {a.plan_id for a in assigns if a.plan_id}
        if plan_ids:
            plans = (await db.execute(select(BudgetPlan).where(BudgetPlan.id.in_(plan_ids)))).scalars().all()
            plan_names = {p.id: p.name for p in plans}
    rows = []
    for a in assigns:
        if a.user_id:
            u = await db.get(User, a.user_id)
            rows.append(
                {
                    "kind": "user",
                    "target": u.display_name or u.username if u else f"user #{a.user_id}",
                    "plan": plan_names.get(a.plan_id, "No Plan") if a.plan_id else "No Plan",
                    "plan_id": a.plan_id,
                }
            )
        elif a.group_id:
            g = await db.get(UserGroup, a.group_id)
            rows.append(
                {
                    "kind": "group",
                    "target": g.name if g else f"group #{a.group_id}",
                    "plan": plan_names.get(a.plan_id, ""),
                    "plan_id": a.plan_id,
                }
            )
        elif a.department:
            rows.append(
                {
                    "kind": "department",
                    "target": a.department,
                    "plan": plan_names.get(a.plan_id, ""),
                    "plan_id": a.plan_id,
                }
            )
    return pd.DataFrame(rows)


async def report_alpha_router_api_key_usage(
    db: AsyncSession,
    start: datetime,
    end: datetime,
    alpha_router_api_key_id: int | None,
) -> pd.DataFrame:
    q = (
        select(
            RequestLog.alpha_router_api_key_id,
            func.sum(RequestLog.total_cost_usd),
            func.count(),
        )
        .where(
            RequestLog.request_time >= start,
            RequestLog.request_time <= end,
            RequestLog.alpha_router_api_key_id.isnot(None),
        )
        .group_by(RequestLog.alpha_router_api_key_id)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
    )
    if alpha_router_api_key_id:
        q = q.where(
            RequestLog.alpha_router_api_key_id == alpha_router_api_key_id
        )
    rows = (await db.execute(q)).all()
    data = []
    for key_id, cost, count in rows:
        key = await db.get(AlphaRouterApiKey, int(key_id)) if key_id else None
        data.append(
            {
                "api_key_name": key.name if key else f"#{key_id}",
                "api_key_id": int(key_id),
                "cost_usd": round(float(cost or 0), 4),
                "requests": int(count or 0),
            }
        )
    return pd.DataFrame(data)


async def report_alpha_router_api_keys_near_credit_limit(
    db: AsyncSession,
    threshold_pct: float,
) -> pd.DataFrame:
    keys = (
        await db.execute(
            select(AlphaRouterApiKey).where(AlphaRouterApiKey.is_active == True)  # noqa: E712
        )
    ).scalars().all()
    rows = []
    for k in keys:
        limit = float(k.credit_limit_usd or 0)
        if limit <= 0:
            continue
        used = float(k.period_used_usd or 0)
        pct = (used / limit) * 100
        if pct >= threshold_pct:
            rows.append(
                {
                    "name": k.name,
                    "credit_limit_usd": round(limit, 2),
                    "period_used_usd": round(used, 4),
                    "usage_pct": round(pct, 1),
                    "reset_period": k.reset_period,
                }
            )
    rows.sort(key=lambda x: x["usage_pct"], reverse=True)
    return pd.DataFrame(rows)


async def build_report(db: AsyncSession, report_type: str, params: dict[str, Any]) -> pd.DataFrame:
    from app.services.reports_catalog import REPORT_IDS

    if report_type not in REPORT_IDS:
        raise HTTPException(400, f"Unknown report_type: {report_type}")

    start = params.get("_start")
    end = params.get("_end")

    if report_type == "user_budget_usage":
        return await report_user_budget_usage(db, start, end, params.get("user_id"))
    if report_type == "plan_usage":
        if not params.get("plan_id"):
            raise HTTPException(400, "plan_id required")
        return await report_plan_usage(db, int(params["plan_id"]), start, end)
    if report_type == "org_cost_summary":
        return await report_org_cost_summary(db, start, end)
    if report_type == "users_near_budget_limit":
        return await report_users_near_budget_limit(db, float(params.get("threshold_pct") or 80))
    if report_type == "users_without_budget":
        return await report_users_without_budget(db)
    if report_type == "department_top_models":
        if not params.get("department"):
            raise HTTPException(400, "department required")
        return await report_department_top_models(db, params["department"], start, end)
    if report_type == "office_usage":
        return await report_office_usage(db, start, end, params.get("office"))
    if report_type == "top_users_by_spend":
        return await report_top_users_by_spend(db, start, end, int(params.get("top_n") or 10))
    if report_type == "top_models_by_spend":
        return await report_top_models_by_spend(db, start, end, int(params.get("top_n") or 10))
    if report_type == "user_model_usage":
        return await report_user_model_usage(db, start, end, params.get("user_id"))
    if report_type == "usage_by_app":
        return await report_usage_by_app(db, start, end, params.get("app"))
    if report_type == "usage_by_api_source":
        return await report_usage_by_api_source(db, start, end)
    if report_type == "usage_by_provider":
        return await report_usage_by_provider(db, start, end, params.get("provider"))
    if report_type == "token_breakdown":
        return await report_token_breakdown(db, start, end)
    if report_type == "usage_by_prompt_language":
        return await report_usage_by_prompt_language(db, start, end)
    if report_type == "model_error_rates":
        return await report_model_error_rates(db, start, end, params.get("model_id"))
    if report_type == "failed_requests":
        return await report_failed_requests(
            db, start, end, params.get("user_id"), params.get("model_id")
        )
    if report_type == "slow_models_latency":
        return await report_slow_models_latency(db, start, end, float(params.get("latency_ms") or 10000))
    if report_type == "slow_requests":
        return await report_slow_requests(db, start, end, float(params.get("latency_ms") or 10000))
    if report_type == "activity_summary":
        return await report_activity_summary(db, start, end, params.get("group_by") or "model")
    if report_type == "deactivated_users":
        return await report_deactivated_users(db)
    if report_type == "users_no_recent_login":
        return await report_users_no_recent_login(db, end, int(params.get("inactive_days") or 30))
    if report_type == "new_users":
        return await report_new_users(db, start, end)
    if report_type == "deleted_users_report":
        return await report_deleted_users(db, start, end)
    if report_type == "auth_provider_distribution":
        return await report_auth_provider_distribution(db)
    if report_type == "users_without_group":
        return await report_users_without_group(db, params.get("auth_provider"))
    if report_type == "group_members_usage":
        if not params.get("group_id"):
            raise HTTPException(400, "group_id required")
        return await report_group_members_usage(db, int(params["group_id"]), start, end)
    if report_type == "plan_assignments":
        return await report_plan_assignments(db, params.get("plan_id"))
    if report_type == "alpha_router_api_key_usage":
        return await report_alpha_router_api_key_usage(
            db,
            start,
            end,
            params.get("alpha_router_api_key_id"),
        )
    if report_type == "alpha_router_api_keys_near_credit_limit":
        return await report_alpha_router_api_keys_near_credit_limit(
            db,
            float(params.get("threshold_pct") or 80),
        )

    raise HTTPException(400, f"Unknown report_type: {report_type}")


# --- export helpers (unchanged surface) ---

def _table_style_header() -> list[tuple]:
    from reportlab.lib import colors

    return [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6366f1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]


def export_activity_logs_workbook(df: pd.DataFrame) -> tuple[bytes, str, str]:
    """Excel workbook with bold header row (API Logs columns)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Activity Logs"
    if df.empty:
        columns = ["message"]
        ws.append(columns)
        ws.append(["No data in selected range"])
    else:
        columns = list(df.columns)
        ws.append(columns)
        for _, row in df.iterrows():
            ws.append([row[c] for c in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return (
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "activity-logs.xlsx",
    )


def _fmt_num(n: float | int, *, decimals: int = 2) -> str:
    if isinstance(n, float):
        return f"{n:,.{decimals}f}"
    return f"{int(n):,}"


def _period_label(period: str) -> str:
    labels = {
        "15m": "Last 15 minutes",
        "30m": "Last 30 minutes",
        "1h": "Last hour",
        "3h": "Last 3 hours",
        "day": "Last 24 hours",
        "2d": "Last 2 days",
        "week": "Last 7 days",
        "month": "Last 30 days",
        "year": "Last 365 days",
    }
    return labels.get(period, period)


def _group_by_label(group_by: str) -> str:
    return {"model": "By model", "app": "By app", "user": "By user"}.get(group_by, group_by)


def _filter_lines(filters: dict | None) -> list[str]:
    filters = filters or {}
    lines: list[str] = []
    if filters.get("model_id"):
        lines.append(f"Model: {filters['model_id']}")
    if filters.get("username"):
        lines.append(f"User: {filters['username']}")
    if filters.get("app"):
        lines.append(f"App: {filters['app']}")
    if filters.get("response_status"):
        lines.append(f"Response status: {filters['response_status']}")
    return lines


def export_activity_dashboard_pdf(payload: dict, meta: dict) -> tuple[bytes, str, str]:
    """Render Activity dashboard content (matches on-screen summary)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ActivityTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=6)
    sub_style = ParagraphStyle("ActivitySub", parent=styles["Normal"], textColor=colors.grey, spaceAfter=10)
    h2 = ParagraphStyle("ActivityH2", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=6)
    story: list = []

    title = meta.get("title") or "Activity"
    story.append(Paragraph(title, title_style))
    subtitle_parts = [
        _period_label(payload.get("period") or "day"),
        _group_by_label(payload.get("group_by") or "model"),
        "UTC" if payload.get("timezone") == "utc" else "Local time",
    ]
    if meta.get("subtitle"):
        subtitle_parts.insert(0, str(meta["subtitle"]))
    story.append(Paragraph(" · ".join(subtitle_parts), sub_style))
    filter_lines = _filter_lines(meta.get("filters"))
    if filter_lines:
        story.append(Paragraph("Filters: " + "; ".join(filter_lines), sub_style))

    totals = payload.get("totals") or {}
    story.append(Paragraph("Summary", h2))
    summary_table = Table(
        [
            ["Metric", "Total"],
            ["Spend (USD)", _fmt_num(float(totals.get("spend") or 0), decimals=4)],
            ["Requests", _fmt_num(int(totals.get("requests") or 0), decimals=0)],
            ["Tokens", _fmt_num(int(totals.get("tokens") or 0), decimals=0)],
        ],
        colWidths=[2.5 * inch, 2.5 * inch],
    )
    summary_table.setStyle(TableStyle(_table_style_header()))
    story.append(summary_table)

    segments = payload.get("models") or []
    if segments:
        story.append(Paragraph("Breakdown", h2))
        seg_rows = [["Segment", "Spend (USD)", "Requests", "Tokens"]]
        for s in segments:
            seg_rows.append(
                [
                    str(s.get("label") or s.get("key") or ""),
                    _fmt_num(float(s.get("spend") or 0), decimals=4),
                    _fmt_num(int(s.get("requests") or 0), decimals=0),
                    _fmt_num(int(s.get("tokens") or 0), decimals=0),
                ]
            )
        seg_table = Table(seg_rows, repeatRows=1)
        seg_table.setStyle(TableStyle(_table_style_header()))
        story.append(seg_table)

    prompts = meta.get("prompts") or payload.get("prompts") or {}
    if prompts:
        story.append(Paragraph("Prompts", h2))
        prompts_rows = [
            ["Metric", "Value"],
            ["Total prompts", _fmt_num(int(prompts.get("total") or 0), decimals=0)],
            ["Longest streak (days)", str(prompts.get("streak_days") or 0)],
            [
                str(prompts.get("period_footer_label") or "Period"),
                _fmt_num(int(prompts.get("period_prompts") or 0), decimals=0) + " prompts",
            ],
        ]
        change = prompts.get("change_pct")
        if change is not None:
            prompts_rows.append(["Change vs previous period", f"{change}%"])
        prompts_table = Table(prompts_rows, colWidths=[2.5 * inch, 2.5 * inch])
        prompts_table.setStyle(TableStyle(_table_style_header()))
        story.append(prompts_table)

    top_models = payload.get("top_models") or []
    if top_models:
        story.append(Paragraph("Top models", h2))
        top_rows = [["Model", "Spend (USD)", "Requests", "Tokens"]]
        for m in top_models[:10]:
            top_rows.append(
                [
                    str(m.get("label") or m.get("key") or ""),
                    _fmt_num(float(m.get("spend") or 0), decimals=4),
                    _fmt_num(int(m.get("requests") or 0), decimals=0),
                    _fmt_num(int(m.get("tokens") or 0), decimals=0),
                ]
            )
        top_table = Table(top_rows, repeatRows=1)
        top_table.setStyle(TableStyle(_table_style_header()))
        story.append(top_table)

    insights = payload.get("insights") or {}
    usage_stats = insights.get("usage_stats") or {}
    if usage_stats:
        story.append(Paragraph("Usage insights (365-day window)", h2))
        ins_rows = [["Metric", "Streak (days)", "Avg/day", "Avg/week", "Total"]]
        for metric_key, label in (("spend", "Spend"), ("requests", "Requests"), ("tokens", "Tokens")):
            stats = usage_stats.get(metric_key) or {}
            avg_day = stats.get("avg_day", 0)
            avg_week = stats.get("avg_week", 0)
            total = stats.get("total", 0)
            if metric_key == "spend":
                ins_rows.append(
                    [
                        label,
                        str(stats.get("streak_days") or 0),
                        _fmt_num(float(avg_day), decimals=2),
                        _fmt_num(float(avg_week), decimals=2),
                        _fmt_num(float(total), decimals=2),
                    ]
                )
            else:
                ins_rows.append(
                    [
                        label,
                        str(stats.get("streak_days") or 0),
                        _fmt_num(int(avg_day), decimals=0),
                        _fmt_num(int(avg_week), decimals=0),
                        _fmt_num(int(total), decimals=0),
                    ]
                )
        ins_table = Table(ins_rows, repeatRows=1)
        ins_table.setStyle(TableStyle(_table_style_header()))
        story.append(ins_table)

    chart = payload.get("chart") or []
    if chart and segments:
        seg_keys = [s.get("key") for s in segments if s.get("key")]
        seg_labels = [str(s.get("label") or s.get("key")) for s in segments]

        def _chart_table(metric: str, title: str) -> None:
            header = ["Bucket", *seg_labels]
            rows = [header]
            for row in chart:
                line = [str(row.get("label") or row.get("bucket") or "")]
                for seg in seg_keys:
                    val = row.get(f"{metric}_{seg}")
                    if metric == "spend":
                        line.append(_fmt_num(float(val or 0), decimals=4))
                    else:
                        line.append(_fmt_num(int(val or 0), decimals=0))
                rows.append(line)
            if len(rows) <= 1:
                return
            story.append(Paragraph(title, h2))
            tbl = Table(rows, repeatRows=1)
            tbl.setStyle(TableStyle(_table_style_header()))
            story.append(tbl)

        _chart_table("spend", "Spend over time")
        _chart_table("requests", "Requests over time")
        _chart_table("tokens", "Tokens over time")

    doc.build(story)
    return buf.getvalue(), "application/pdf", "activity-dashboard.pdf"


def export_dataframe(df: pd.DataFrame, fmt: str, report_type: str = "report") -> tuple[bytes, str, str]:
    if df.empty:
        df = pd.DataFrame([{"message": "No data in selected range"}])
    safe_name = report_type.replace("/", "-")[:64]
    if fmt == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8"), "text/csv", f"{safe_name}.csv"
    if fmt == "xls" or fmt == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{safe_name}.xlsx"
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle(_table_style_header()))
    doc.build([table])
    return buf.getvalue(), "application/pdf", f"{safe_name}.pdf"
