"""Admin reports: catalog, query, export + scheduled email (SMTP)."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user, require_reports, require_reports_write
from app.database import get_db
from app.models.api_key import AlphaRouterApiKey
from app.models.budget import BudgetPlan
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.system import ReportSchedule
from app.models.user import User
from app.services import reports_service
from app.services.reports_catalog import CATEGORY_LABELS, REPORT_CATALOG

router = APIRouter(prefix="/api/admin/reports", tags=["reports"])


class ReportRequest(BaseModel):
    report_type: str
    start_date: str | None = None
    end_date: str | None = None
    format: str = "csv"
    user_id: int | None = None
    plan_id: int | None = None
    department: str | None = None
    office: str | None = None
    group_id: int | None = None
    alpha_router_api_key_id: int | None = None
    app: str | None = None
    model_id: str | None = None
    provider: str | None = None
    top_n: int = Field(default=10, ge=1, le=100)
    threshold_pct: float = Field(default=80.0, ge=1, le=100)
    latency_ms: float = Field(default=10000.0, ge=1)
    inactive_days: int = Field(default=30, ge=1, le=365)
    auth_provider: str | None = None
    group_by: str = "model"


def _parse_dates(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    if not start or not end:
        raise HTTPException(400, "start_date and end_date are required for this report")
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        if e < s:
            raise HTTPException(400, "end_date must be on or after start_date")
        return s, e
    except ValueError as exc:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD") from exc


def _default_dates() -> tuple[str, str]:
    end = datetime.utcnow().date()
    start = end - timedelta(days=30)
    return start.isoformat(), end.isoformat()


def _report_params(body: ReportRequest) -> dict:
    meta = next((r for r in REPORT_CATALOG if r["id"] == body.report_type), None)
    if not meta:
        raise HTTPException(400, f"Unknown report_type: {body.report_type}")

    params: dict = {
        "user_id": body.user_id,
        "plan_id": body.plan_id,
        "department": body.department,
        "office": body.office or None,
        "group_id": body.group_id,
        "alpha_router_api_key_id": body.alpha_router_api_key_id,
        "app": body.app or None,
        "model_id": body.model_id or None,
        "provider": body.provider or None,
        "top_n": body.top_n,
        "threshold_pct": body.threshold_pct,
        "latency_ms": body.latency_ms,
        "inactive_days": body.inactive_days,
        "auth_provider": body.auth_provider or None,
        "group_by": body.group_by if body.group_by in ("model", "app", "user") else "model",
    }

    if meta["needs_date"]:
        start, end = _parse_dates(body.start_date, body.end_date)
        params["_start"] = start
        params["_end"] = end
    elif body.report_type == "users_no_recent_login":
        _, end = _parse_dates(
            body.start_date or _default_dates()[0],
            body.end_date or _default_dates()[1],
        )
        params["_end"] = end

    if "plan" in meta["params"] and body.report_type == "plan_usage" and not body.plan_id:
        raise HTTPException(400, "plan_id required")
    if "department" in meta["params"] and body.report_type == "department_top_models" and not body.department:
        raise HTTPException(400, "department required")
    if "group" in meta["params"] and body.report_type == "group_members_usage" and not body.group_id:
        raise HTTPException(400, "group_id required")

    return params


async def _build_report_df(body: ReportRequest, db: AsyncSession):
    params = _report_params(body)
    return await reports_service.build_report(db, body.report_type, params)


@router.get("/catalog")
async def report_catalog(_: User = Depends(require_reports)):
    return {
        "categories": CATEGORY_LABELS,
        "reports": REPORT_CATALOG,
        "default_dates": {"start_date": _default_dates()[0], "end_date": _default_dates()[1]},
    }


@router.get("/options")
async def report_options(db: AsyncSession = Depends(get_db), _: User = Depends(require_reports)):
    from app.models.user import UserGroup

    plans = (await db.execute(select(BudgetPlan.id, BudgetPlan.name).order_by(BudgetPlan.name))).all()
    groups = (await db.execute(select(UserGroup.id, UserGroup.name, UserGroup.source).order_by(UserGroup.name))).all()
    dept_rows = (
        await db.execute(
            select(User.department)
            .where(User.deleted_at.is_(None), User.department.isnot(None), User.department != "")
            .distinct()
            .order_by(User.department)
        )
    ).all()
    office_rows = (
        await db.execute(
            select(User.office)
            .where(User.deleted_at.is_(None), User.office.isnot(None), User.office != "")
            .distinct()
            .order_by(User.office)
        )
    ).all()
    app_rows = (
        await db.execute(
            select(RequestLog.client_app)
            .where(RequestLog.client_app.isnot(None), RequestLog.client_app != "")
            .distinct()
            .order_by(RequestLog.client_app)
        )
    ).all()
    provider_rows = (
        await db.execute(select(AIModel.provider_type).distinct().order_by(AIModel.provider_type))
    ).all()
    model_rows = (
        await db.execute(
            select(RequestLog.model_id).distinct().order_by(RequestLog.model_id).limit(500)
        )
    ).all()
    keys = (
        await db.execute(select(AlphaRouterApiKey.id, AlphaRouterApiKey.name).order_by(AlphaRouterApiKey.name))
    ).all()

    return {
        "plans": [{"id": p[0], "name": p[1]} for p in plans],
        "groups": [{"id": g[0], "name": g[1], "source": g[2]} for g in groups],
        "departments": [str(r[0]) for r in dept_rows if r[0]],
        "offices": [str(r[0]) for r in office_rows if r[0]],
        "apps": [str(r[0]) for r in app_rows if r[0]],
        "providers": [str(r[0]) for r in provider_rows if r[0]],
        "models": [str(r[0]) for r in model_rows if r[0]],
        "alpha_router_api_keys": [{"id": k[0], "name": k[1]} for k in keys],
        "auth_providers": ["local", "ldap", "saml", "openwebui"],
        "group_by_options": [
            {"value": "model", "label": "By model"},
            {"value": "app", "label": "By app"},
            {"value": "user", "label": "By user"},
        ],
    }


@router.post("/preview")
async def preview_report(body: ReportRequest, db: AsyncSession = Depends(get_db), _: User = Depends(require_reports_write)):
    df = await _build_report_df(body, db)
    rows = df.to_dict(orient="records") if not df.empty else []
    columns = list(df.columns) if not df.empty else []
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


@router.post("/export")
async def export_report(body: ReportRequest, db: AsyncSession = Depends(get_db), _: User = Depends(require_reports_write)):
    df = await _build_report_df(body, db)
    content, media, filename = reports_service.export_dataframe(df, body.format, body.report_type)
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class ScheduleIn(BaseModel):
    report_type: str
    cron_expression: str
    recipients: str
    parameters_json: str | None = None
    format: str = "pdf"


@router.get("/schedules")
async def list_schedules(db: AsyncSession = Depends(get_db), _: User = Depends(require_reports)):
    rows = (await db.execute(select(ReportSchedule))).scalars().all()
    return [
        {
            "id": r.id,
            "report_type": r.report_type,
            "cron_expression": r.cron_expression,
            "recipients": r.recipients,
            "format": r.format,
            "is_active": r.is_active,
        }
        for r in rows
    ]


@router.post("/schedules")
async def create_schedule(body: ScheduleIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_reports_write)):
    if body.report_type not in {r["id"] for r in REPORT_CATALOG}:
        raise HTTPException(400, "Unknown report_type")
    db.add(
        ReportSchedule(
            report_type=body.report_type,
            cron_expression=body.cron_expression,
            recipients=body.recipients,
            parameters_json=body.parameters_json,
            format=body.format,
            is_active=True,
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/schedules/user")
async def user_schedule_report(
    body: ScheduleIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Users may schedule their own reports; cannot configure SMTP."""
    db.add(
        ReportSchedule(
            owner_user_id=user.id,
            report_type=body.report_type,
            cron_expression=body.cron_expression,
            recipients=body.recipients,
            parameters_json=body.parameters_json,
            format=body.format,
            is_active=True,
        )
    )
    await db.commit()
    return {"ok": True}
