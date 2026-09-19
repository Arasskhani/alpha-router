"""Daily activity totals computed by the database, not by reading every row.

The Activity dashboard's heatmap is a 365-day grid of three numbers per day.
The only way the code knew to build it was to load every ``request_logs`` row
of the last year as an ORM object and count them in Python - which meant every
Activity view, including "last 15 minutes", widened its query to a year and
walked the result four or five times.

This module produces the same ``{day: {requests, tokens, spend}}`` mapping with
one ``GROUP BY``. It also owns the translation of the dashboard's scope and
filter arguments into SQL, so the aggregate and the row fetch cannot drift
apart.

One caveat, stated rather than hidden: in ``local`` mode the day boundary uses
the server's current UTC offset for the whole range, while the Python path
resolved each timestamp's own offset. The two disagree only for rows on the far
side of a daylight-saving transition, which moves a handful of requests between
two adjacent cells of a density grid.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import Select, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_runtime import AgentRun
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel

#: What an empty or missing value is called in the dashboard's filters.
UNKNOWN = "unknown"

#: Returned by the condition builders when the arguments can never match.
MATCHES_NOTHING = None


def _labelled(column) -> Any:
    """``(col or 'unknown').strip()`` as the Python filters spell it."""

    return func.coalesce(func.nullif(func.trim(column), ""), UNKNOWN)


async def scope_conditions(
    db: AsyncSession,
    since: datetime.datetime,
    *,
    user_id: int | None = None,
    user_ids: list[int] | None = None,
    alpha_router_api_key_id: int | None = None,
    user_api_key_id: int | None = None,
    connection_id: int | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
) -> list | None:
    """Which logs this dashboard scope covers. ``None`` means: none of them."""

    conditions = [RequestLog.request_time >= since]
    if user_id is not None:
        conditions.append(RequestLog.user_id == user_id)
    elif user_ids is not None:
        if not user_ids:
            return MATCHES_NOTHING
        conditions.append(RequestLog.user_id.in_(user_ids))
    if alpha_router_api_key_id is not None:
        conditions.append(RequestLog.alpha_router_api_key_id == alpha_router_api_key_id)
    if user_api_key_id is not None:
        if user_api_key_id < 0:
            return MATCHES_NOTHING
        conditions.append(RequestLog.user_api_key_id == user_api_key_id)
    if connection_id is not None:
        model_ids = (
            (await db.execute(select(AIModel.external_id).where(AIModel.connection_id == connection_id)))
            .scalars()
            .all()
        )
        if not model_ids:
            return MATCHES_NOTHING
        conditions.append(RequestLog.model_id.in_(list(model_ids)))
    if agent_id is not None:
        conditions.append(
            or_(
                RequestLog.id.in_(
                    select(AgentRun.request_log_id).where(
                        AgentRun.agent_id == agent_id,
                        AgentRun.request_log_id.is_not(None),
                    )
                ),
                RequestLog.usage_operation_id.in_(
                    select(AgentRun.usage_operation_id).where(
                        AgentRun.agent_id == agent_id,
                        AgentRun.usage_operation_id.is_not(None),
                    )
                ),
            )
        )
    if project_id is not None:
        conditions.append(RequestLog.project_id == project_id)
    return conditions


def filter_conditions(
    *,
    model_id: str | None = None,
    username: str | None = None,
    app: str | None = None,
    response_status: str | None = None,
    alpha_router_api_key_id: int | None = None,
    user_api_key_id: int | None = None,
) -> list | None:
    """The comboboxes above the dashboard, as SQL. Mirrors ``apply_activity_filters``."""

    conditions: list = []
    model_filter = (model_id or "").strip()
    if model_filter:
        conditions.append(_labelled(RequestLog.model_id) == model_filter)
    user_filter = (username or "").strip()
    if user_filter:
        conditions.append(func.trim(RequestLog.username) == user_filter)
    app_filter = (app or "").strip()
    if app_filter:
        conditions.append(_labelled(RequestLog.source) == app_filter)
    if alpha_router_api_key_id is not None:
        conditions.append(RequestLog.alpha_router_api_key_id == alpha_router_api_key_id)
    if user_api_key_id is not None:
        if user_api_key_id < 0:
            return MATCHES_NOTHING
        conditions.append(RequestLog.user_api_key_id == user_api_key_id)
    if response_status == "success":
        conditions.append(RequestLog.success.is_(True))
    elif response_status == "fail":
        conditions.append(RequestLog.success.is_(False))
    return conditions


def _local_offset_seconds(now: datetime.datetime | None = None) -> int:
    reference = now or datetime.datetime.now()
    offset = reference.astimezone().utcoffset() or datetime.timedelta(0)
    return int(offset.total_seconds())


def day_expression(dialect: str, tz_mode: str):
    """The calendar day a ``request_time`` falls on, as the dashboard displays it."""

    if tz_mode != "local":
        return func.date(RequestLog.request_time)
    seconds = _local_offset_seconds()
    if not seconds:
        return func.date(RequestLog.request_time)
    if dialect == "postgresql":
        # The literal is an int this module computed, never user input.
        return func.date(RequestLog.request_time + literal_column(f"interval '{seconds} seconds'"))
    return func.date(RequestLog.request_time, f"{seconds} seconds")


def _as_day_key(value: Any) -> str:
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)[:10]


async def daily_activity_metrics(
    db: AsyncSession,
    *,
    since: datetime.datetime,
    tz_mode: str,
    scope: dict[str, Any],
    filters: dict[str, Any],
) -> dict[str, dict[str, float]]:
    """``{"2026-09-19": {"requests": n, "tokens": n, "spend": n}}`` for the heatmap."""

    conditions = await scope_conditions(db, since, **scope)
    if conditions is None:
        return {}
    filtered = filter_conditions(**filters)
    if filtered is None:
        return {}

    day = day_expression(db.get_bind().dialect.name, tz_mode if tz_mode in ("local", "utc") else "local")
    statement: Select = (
        select(
            day.label("day"),
            func.count().label("requests"),
            func.coalesce(
                func.sum(func.coalesce(RequestLog.prompt_tokens, 0) + func.coalesce(RequestLog.completion_tokens, 0)),
                0,
            ).label("tokens"),
            func.coalesce(func.sum(func.coalesce(RequestLog.total_cost_usd, 0)), 0).label("spend"),
        )
        .where(*conditions, *filtered)
        .group_by(day)
    )
    rows = (await db.execute(statement)).all()
    return {
        _as_day_key(row.day): {
            "requests": float(row.requests or 0),
            "tokens": float(row.tokens or 0),
            "spend": float(row.spend or 0),
        }
        for row in rows
    }
