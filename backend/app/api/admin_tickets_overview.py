"""Admin › Tickets › Overview: how tickets came in, ended and wait, for a period.

Aggregates only, never ticket text. Readable by everyone who can read tickets
(Support, Super Admin, Read Only Super Admin). Mounted before the queue router,
whose ``/{ticket_id}`` paths would otherwise see ``/overview``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_tickets
from app.database import get_db
from app.models.user import User
from app.services import support_tickets as st
from app.services.activity_service import ACTIVITY_PERIOD_PATTERN
from app.services.support_ticket_overview import OverviewFilters, build_overview, overview_csv

router = APIRouter(prefix="/api/admin/tickets", tags=["tickets"])

# An empty value is "any", as the frontend leaves a cleared filter out or empty.
_PRIORITY_PATTERN = f"^({'|'.join(st.PRIORITIES)})?$"
_STATUS_PATTERN = f"^({'|'.join(st.STATUSES)})?$"


def overview_filters(
    assignee: str | None = Query(None, pattern=r"^(none|[1-9]\d{0,9})?$"),
    department: str | None = Query(None, max_length=255),
    priority: str | None = Query(None, pattern=_PRIORITY_PATTERN),
    category: str | None = Query(None, max_length=st.CATEGORY_MAX),
    status: str | None = Query(None, pattern=_STATUS_PATTERN),
) -> OverviewFilters:
    return OverviewFilters(
        assignee=assignee or None,
        department=(department or "").strip() or None,
        priority=priority or None,
        category=(category or "").strip() or None,
        status=status or None,
    )


@router.get("/overview")
async def tickets_overview(
    period: str = Query("week", pattern=ACTIVITY_PERIOD_PATTERN),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    filters: OverviewFilters = Depends(overview_filters),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_tickets),
):
    return await build_overview(db, period=period, timezone=timezone, filters=filters)


@router.get("/overview.csv")
async def tickets_overview_csv(
    period: str = Query("week", pattern=ACTIVITY_PERIOD_PATTERN),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    filters: OverviewFilters = Depends(overview_filters),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_tickets),
):
    payload = await build_overview(db, period=period, timezone=timezone, filters=filters)
    return Response(
        content=overview_csv(payload, filters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tickets-overview-{payload["period"]}.csv"'},
    )
