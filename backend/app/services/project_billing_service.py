"""Project-scoped cost attribution and admin usage reporting.

Reuses the existing ``RequestLog`` cost pipeline. Project-scoped chat
completions tag their request logs with ``project_id``; this service
aggregates those rows into per-project summaries that the admin
"Data & Reports" section can render using the same patterns as the
rest of the reports catalog.
"""

from __future__ import annotations

import datetime
from typing import Any

import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logging import RequestLog
from app.models.project import PROJECT_STATUS_DELETION_PENDING, Project, ProjectMember
from app.services.project_access_service import resolve_project_access

PROJECT_REPORT_DEFAULT_DAYS = 30


def _media_client_app_filter():
    """Request logs written by image/video generation (see image/video billing services)."""
    return or_(
        RequestLog.client_app.contains("(image:"),
        RequestLog.client_app.contains("(video:"),
    )


async def resolve_project_id_for_request(
    db: AsyncSession,
    *,
    user: object,
    chat_session_id: str | None = None,
    project_id: str | None = None,
) -> str | None:
    """Resolve the project to attribute image/video (and similar) usage to.

    A project chat session is authoritative: its ``project_id`` cannot be
    overridden by a client-supplied value.  An explicit ``project_id`` is
    accepted only when the caller can view that project (Media-tab
    generation outside a chat).  Unknown or unauthorized IDs yield ``None``
    so the request is billed as personal usage rather than leaking cost
    onto another project.
    """
    sid = (chat_session_id or "").strip()
    if sid:
        from app.models.chat import ChatSession

        session = await db.get(ChatSession, sid)
        if session is not None and session.project_id:
            return session.project_id

    explicit = (project_id or "").strip()
    if not explicit:
        return None
    access = await resolve_project_access(db, project_id=explicit, user=user)
    if access is None:
        return None
    return explicit


async def _project_exists(db: AsyncSession, project_id: str) -> bool:
    row = (await db.execute(select(Project.id).where(Project.id == project_id))).first()
    return row is not None


async def report_project_usage_summary(
    db: AsyncSession, project_id: str, start: datetime.datetime, end: datetime.datetime
) -> pd.DataFrame:
    """Aggregate cost/tokens/requests for a single project over a window."""

    if not await _project_exists(db, project_id):
        raise ValueError("project not found")

    row = (
        await db.execute(
            select(
                func.sum(RequestLog.total_cost_usd),
                func.count(),
                func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
                func.sum(RequestLog.prompt_tokens),
                func.sum(RequestLog.completion_tokens),
                func.sum(RequestLog.cached_tokens),
            ).where(
                RequestLog.project_id == project_id,
                RequestLog.request_time >= start,
                RequestLog.request_time <= end,
            )
        )
    ).one()
    media_cost = (
        await db.execute(
            select(func.coalesce(func.sum(RequestLog.total_cost_usd), 0)).where(
                RequestLog.project_id == project_id,
                RequestLog.request_time >= start,
                RequestLog.request_time <= end,
                _media_client_app_filter(),
            )
        )
    ).scalar()
    return pd.DataFrame(
        [
            {
                "project_id": project_id,
                "total_cost_usd": round(float(row[0] or 0), 4),
                "media_cost_usd": round(float(media_cost or 0), 4),
                "requests": int(row[1] or 0),
                "total_tokens": int(row[2] or 0),
                "prompt_tokens": int(row[3] or 0),
                "completion_tokens": int(row[4] or 0),
                "cached_tokens": int(row[5] or 0),
            }
        ]
    )


async def report_project_usage_by_model(
    db: AsyncSession, project_id: str, start: datetime.datetime, end: datetime.datetime
) -> pd.DataFrame:
    """Per-model breakdown of cost/tokens/requests for a project."""

    if not await _project_exists(db, project_id):
        raise ValueError("project not found")

    rows = (
        await db.execute(
            select(
                RequestLog.model_id,
                func.sum(RequestLog.total_cost_usd),
                func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
                func.sum(RequestLog.prompt_tokens),
                func.sum(RequestLog.completion_tokens),
                func.sum(RequestLog.cached_tokens),
                func.count(),
            )
            .where(
                RequestLog.project_id == project_id,
                RequestLog.request_time >= start,
                RequestLog.request_time <= end,
            )
            .group_by(RequestLog.model_id)
            .order_by(func.sum(RequestLog.total_cost_usd).desc())
        )
    ).all()
    return pd.DataFrame(
        [
            {
                "model": r[0],
                "cost_usd": round(float(r[1] or 0), 4),
                "tokens": int(r[2] or 0),
                "prompt_tokens": int(r[3] or 0),
                "completion_tokens": int(r[4] or 0),
                "cached_tokens": int(r[5] or 0),
                "requests": int(r[6] or 0),
            }
            for r in rows
        ]
    )


async def report_project_usage_by_member(
    db: AsyncSession, project_id: str, start: datetime.datetime, end: datetime.datetime
) -> pd.DataFrame:
    """Per-member breakdown of cost/tokens/requests within a project.

    Only counts requests made by current project members. Non-member
    rows (e.g. revoked members' historical requests) are aggregated
    under ``"<revoked>"`` so the admin retains full visibility without
    leaking identity for users who are no longer members.
    """

    if not await _project_exists(db, project_id):
        raise ValueError("project not found")

    member_user_ids = {
        r[0]
        for r in (await db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id))).all()
        if r[0] is not None
    }

    rows = (
        await db.execute(
            select(
                RequestLog.user_id,
                RequestLog.username,
                func.sum(RequestLog.total_cost_usd),
                func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
                func.count(),
            )
            .where(
                RequestLog.project_id == project_id,
                RequestLog.request_time >= start,
                RequestLog.request_time <= end,
            )
            .group_by(RequestLog.user_id, RequestLog.username)
            .order_by(func.sum(RequestLog.total_cost_usd).desc())
        )
    ).all()

    out: list[dict[str, Any]] = []
    for r in rows:
        user_id = r[0]
        username = r[1] or ""
        is_member = user_id in member_user_ids
        out.append(
            {
                "user_id": user_id if is_member else None,
                "username": username if is_member else "<revoked>",
                "cost_usd": round(float(r[2] or 0), 4),
                "tokens": int(r[3] or 0),
                "requests": int(r[4] or 0),
                "is_member": is_member,
            }
        )
    return pd.DataFrame(out)


async def report_all_projects_usage(db: AsyncSession, start: datetime.datetime, end: datetime.datetime) -> pd.DataFrame:
    """Org-wide per-project cost summary for the admin overview."""

    rows = (
        await db.execute(
            select(
                RequestLog.project_id,
                func.sum(RequestLog.total_cost_usd),
                func.count(),
                func.sum(RequestLog.prompt_tokens + RequestLog.completion_tokens),
            )
            .where(
                RequestLog.project_id.isnot(None),
                RequestLog.request_time >= start,
                RequestLog.request_time <= end,
            )
            .group_by(RequestLog.project_id)
            .order_by(func.sum(RequestLog.total_cost_usd).desc())
        )
    ).all()

    project_ids = [r[0] for r in rows if r[0]]
    name_by_id: dict[str, str] = {}
    if project_ids:
        name_rows = (await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))).all()
        name_by_id = {r[0]: r[1] for r in name_rows}

    media_rows = (
        await db.execute(
            select(
                RequestLog.project_id,
                func.sum(RequestLog.total_cost_usd),
            )
            .where(
                RequestLog.project_id.isnot(None),
                RequestLog.request_time >= start,
                RequestLog.request_time <= end,
                _media_client_app_filter(),
            )
            .group_by(RequestLog.project_id)
        )
    ).all()
    media_by_id = {r[0]: round(float(r[1] or 0), 4) for r in media_rows if r[0]}

    return pd.DataFrame(
        [
            {
                "project_id": r[0],
                "project_name": name_by_id.get(r[0], "<deleted>"),
                "cost_usd": round(float(r[1] or 0), 4),
                "media_cost_usd": media_by_id.get(r[0], 0.0),
                "requests": int(r[2] or 0),
                "tokens": int(r[3] or 0),
            }
            for r in rows
        ]
    )


async def list_projects_usage_overview(
    db: AsyncSession, start: datetime.datetime, end: datetime.datetime
) -> list[dict[str, Any]]:
    """All non-purged projects with period spend, for the admin Project usage page."""
    usage = await report_all_projects_usage(db, start, end)
    usage_by_id = {row["project_id"]: row for row in usage.to_dict("records") if row.get("project_id")}
    projects = (
        (
            await db.execute(
                select(Project).where(Project.status != PROJECT_STATUS_DELETION_PENDING).order_by(Project.name)
            )
        )
        .scalars()
        .all()
    )
    out: list[dict[str, Any]] = []
    for project in projects:
        row = usage_by_id.get(project.id, {})
        out.append(
            {
                "id": project.id,
                "name": project.name,
                "status": project.status,
                "visibility": project.visibility,
                "costUsd": float(row.get("cost_usd") or 0),
                "mediaCostUsd": float(row.get("media_cost_usd") or 0),
                "requests": int(row.get("requests") or 0),
                "tokens": int(row.get("tokens") or 0),
            }
        )
    out.sort(key=lambda item: (-item["costUsd"], item["name"].lower()))
    return out


async def report_project_media_usage_summary(
    db: AsyncSession, project_id: str, start: datetime.datetime, end: datetime.datetime
) -> pd.DataFrame:
    """Image/video generation cost for a single project over a window."""

    if not await _project_exists(db, project_id):
        raise ValueError("project not found")

    row = (
        await db.execute(
            select(
                func.sum(RequestLog.total_cost_usd),
                func.count(),
            ).where(
                RequestLog.project_id == project_id,
                RequestLog.request_time >= start,
                RequestLog.request_time <= end,
                _media_client_app_filter(),
            )
        )
    ).one()
    return pd.DataFrame(
        [
            {
                "project_id": project_id,
                "media_cost_usd": round(float(row[0] or 0), 4),
                "media_requests": int(row[1] or 0),
            }
        ]
    )


def default_window() -> tuple[datetime.datetime, datetime.datetime]:
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=PROJECT_REPORT_DEFAULT_DAYS)
    return start, end
