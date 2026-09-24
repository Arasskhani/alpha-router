"""Admin reports: catalog, query, export + scheduled email (SMTP)."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_reports, require_reports_write
from app.database import get_db
from app.models.agent import Agent
from app.models.api_key import AlphaRouterApiKey
from app.models.budget import BudgetPlan
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.system import ReportSchedule
from app.models.user import User
from app.services import reports_service
from app.services.report_request import ReportRequest, default_dates, report_params
from app.services.agent_definition_service import is_purged_agent
from app.services.reports_catalog import CATEGORY_LABELS, REPORT_CATALOG

router = APIRouter(prefix="/api/admin/reports", tags=["reports"])


async def _build_report_df(body: ReportRequest, db: AsyncSession):
    params = report_params(body)
    return await reports_service.build_report(db, body.report_type, params)


@router.get("/catalog")
async def report_catalog(_: User = Depends(require_reports)):
    return {
        "categories": CATEGORY_LABELS,
        "reports": REPORT_CATALOG,
        "default_dates": {"start_date": default_dates()[0], "end_date": default_dates()[1]},
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
    provider_rows = (await db.execute(select(AIModel.provider_type).distinct().order_by(AIModel.provider_type))).all()
    model_rows = (
        await db.execute(select(RequestLog.model_id).distinct().order_by(RequestLog.model_id).limit(500))
    ).all()
    keys = (
        await db.execute(select(AlphaRouterApiKey.id, AlphaRouterApiKey.name).order_by(AlphaRouterApiKey.name))
    ).all()
    agents = (await db.execute(select(Agent).order_by(Agent.name, Agent.sort_order))).scalars().all()

    from app.models.project import Project

    project_rows = (
        await db.execute(
            select(Project.id, Project.name).where(Project.status != "deletion_pending").order_by(Project.name)
        )
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
        "agents": [
            {"id": agent.id, "name": agent.name, "status": agent.status}
            for agent in agents
            if not is_purged_agent(agent)
        ],
        "auth_providers": ["local", "ldap", "saml", "oidc", "openwebui"],
        "group_by_options": [
            {"value": "model", "label": "By model"},
            {"value": "app", "label": "By app"},
            {"value": "user", "label": "By user"},
        ],
        "projects": [{"id": p[0], "name": p[1]} for p in project_rows],
    }


@router.post("/preview")
async def preview_report(
    body: ReportRequest, db: AsyncSession = Depends(get_db), _: User = Depends(require_reports_write)
):
    df = await _build_report_df(body, db)
    rows = df.to_dict(orient="records") if not df.empty else []
    columns = list(df.columns) if not df.empty else []
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


@router.post("/export")
async def export_report(
    body: ReportRequest, db: AsyncSession = Depends(get_db), _: User = Depends(require_reports_write)
):
    df = await _build_report_df(body, db)
    content, media, filename = reports_service.export_dataframe(df, body.format, body.report_type)
    return Response(
        content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


class ScheduleIn(BaseModel):
    report_type: str
    cron_expression: str
    recipients: str
    parameters_json: str | None = None
    format: str = "pdf"


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCHEDULE_FORMATS = frozenset({"pdf", "xlsx", "csv"})
_MAX_RECIPIENTS = 20


def _validate_schedule(body: ScheduleIn) -> dict:
    """Shared validation for admin and self-service schedules.

    Rows land in the admin schedule list and will one day drive an emailer,
    so every field is checked here: known report, a parseable 5-field cron,
    well-formed recipient addresses, a known format and JSON parameters.
    """
    from apscheduler.triggers.cron import CronTrigger

    if body.report_type not in {r["id"] for r in REPORT_CATALOG}:
        raise HTTPException(400, "Unknown report_type")
    cron = (body.cron_expression or "").strip()
    if not cron or len(cron.split()) != 5:
        raise HTTPException(400, "cron_expression must have 5 fields (minute hour day month weekday)")
    try:
        CronTrigger.from_crontab(cron)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, f"Invalid cron_expression: {exc}") from exc
    recipients = [r.strip() for r in re.split(r"[,;\s]+", body.recipients or "") if r.strip()]
    if not recipients:
        raise HTTPException(400, "At least one recipient is required")
    if len(recipients) > _MAX_RECIPIENTS:
        raise HTTPException(400, f"At most {_MAX_RECIPIENTS} recipients")
    bad = [r for r in recipients if not _EMAIL_RE.match(r) or len(r) > 254]
    if bad:
        raise HTTPException(400, f"Invalid recipient address: {bad[0]}")
    fmt = (body.format or "pdf").lower()
    if fmt not in _SCHEDULE_FORMATS:
        raise HTTPException(400, "format must be one of pdf, xlsx, csv")
    params = body.parameters_json
    if params:
        if len(params) > 8192:
            raise HTTPException(400, "parameters_json is too large")
        try:
            if not isinstance(json.loads(params), dict):
                raise ValueError("not an object")
        except ValueError as exc:
            raise HTTPException(400, "parameters_json must be a JSON object") from exc
    return {
        "report_type": body.report_type,
        "cron_expression": cron,
        "recipients": ",".join(recipients),
        "parameters_json": params,
        "format": fmt,
    }


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
async def create_schedule(
    body: ScheduleIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_reports_write)
):
    clean = _validate_schedule(body)
    db.add(ReportSchedule(**clean, is_active=True))
    await db.commit()
    return {"ok": True}


@router.post("/schedules/user")
async def user_schedule_report(
    body: ScheduleIn,
    user: User = Depends(require_reports_write),
    db: AsyncSession = Depends(get_db),
):
    """A schedule of one's own, sent only to the caller's own address.

    Reports hold the whole organisation's usage, so this takes what running
    them takes: write access to Reports. It used to take only an active
    account, which would have let anyone have any report mailed to them the
    moment the sender was wired up. The address rule stays: anything else
    would be an unauthenticated mailer.
    """
    clean = _validate_schedule(body)
    own = (user.email or "").strip().lower()
    others = [r for r in clean["recipients"].split(",") if r.lower() != own]
    if not own or others:
        raise HTTPException(400, "Self-service schedules can only be sent to your own account email")
    db.add(ReportSchedule(owner_user_id=user.id, **clean, is_active=True))
    await db.commit()
    return {"ok": True}
