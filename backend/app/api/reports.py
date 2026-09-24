"""Admin reports: catalog, query, export + scheduled email (SMTP)."""

import datetime as dt
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.services import report_schedule_service as schedules
from app.services import reports_service
from app.services.agent_definition_service import is_purged_agent
from app.services.client_ip import resolve_client_ip
from app.services.report_request import ReportRequest, default_dates, report_params
from app.services.reports_catalog import CATEGORY_LABELS, REPORT_CATALOG
from app.services.schedule_timezone import get_server_timezone, server_timezone_label
from app.services.security_audit import log_security_event

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
        "schedule_periods": [{"value": value, "label": label} for value, label in schedules.PERIODS.items()],
        "schedule_timezone": server_timezone_label(),
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
    period: str = schedules.DEFAULT_PERIOD


class ScheduleChange(BaseModel):
    is_active: bool


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCHEDULE_FORMATS = frozenset({"pdf", "xlsx", "csv"})
_MAX_RECIPIENTS = 20


def _validate_schedule(body: ScheduleIn) -> dict:
    """Shared validation for admin and self-service schedules.

    Every field is checked the way a run will use it - a known report whose
    parameters it accepts, a standard 5-field cron expression that comes
    round, well-formed recipient addresses, a known format and period - so a
    mistake is refused here rather than turning into a failed email later.
    """
    if body.report_type not in {r["id"] for r in REPORT_CATALOG}:
        raise HTTPException(400, "Unknown report_type")
    cron = " ".join((body.cron_expression or "").split())
    if len(cron.split()) != 5:
        raise HTTPException(400, "cron_expression must have 5 fields (minute hour day month weekday)")
    try:
        schedules.first_run(cron, schedules.utcnow())
    except ValueError as exc:
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
    fmt = "xlsx" if fmt == "xls" else fmt
    if fmt not in _SCHEDULE_FORMATS:
        raise HTTPException(400, "format must be one of pdf, xlsx, csv")
    period = body.period or schedules.DEFAULT_PERIOD
    if period not in schedules.PERIODS:
        raise HTTPException(400, f"period must be one of {', '.join(schedules.PERIODS)}")
    params = body.parameters_json
    if params and len(params) > 8192:
        raise HTTPException(400, "parameters_json is too large")
    try:
        parameters = schedules.checked_parameters(body.report_type, params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "report_type": body.report_type,
        "cron_expression": cron,
        "recipients": ",".join(recipients),
        "parameters_json": json.dumps(parameters, sort_keys=True) if parameters else None,
        "format": fmt,
        "period": period,
    }


def _iso(value: dt.datetime | None) -> str | None:
    return value.replace(tzinfo=dt.UTC).isoformat().replace("+00:00", "Z") if value else None


def _local(value: dt.datetime | None, tz: dt.tzinfo) -> str | None:
    """A stored time as the server's clock shows it, the clock cron expressions use."""
    return value.replace(tzinfo=dt.UTC).astimezone(tz).strftime("%Y-%m-%d %H:%M") if value else None


def _schedule_row(row: ReportSchedule, owners: dict[int, str], now: dt.datetime, tz: dt.tzinfo) -> dict:
    next_run = None
    if row.is_active:
        next_run = row.next_run_at
        if next_run is None:
            # Saved before runs were kept: the job sets it within a minute.
            try:
                next_run = schedules.first_run(row.cron_expression, now, tz)
            except ValueError:
                next_run = None
    status, error = schedules.displayed_outcome(row, now)
    try:
        parameters = schedules.parse_parameters(row.parameters_json)
    except ValueError:
        parameters = {}
    report = next((r for r in REPORT_CATALOG if r["id"] == row.report_type), None)
    return {
        "id": row.id,
        "report_type": row.report_type,
        "report_title": report["title"] if report else row.report_type,
        "needs_date": bool(report["needs_date"]) if report else True,
        "cron_expression": row.cron_expression,
        "period": row.period or schedules.DEFAULT_PERIOD,
        "recipients": row.recipients,
        "parameters": parameters,
        "format": row.format,
        "is_active": bool(row.is_active),
        "owner": owners.get(row.owner_user_id) if row.owner_user_id is not None else None,
        "next_run_at": _iso(next_run),
        "next_run_local": _local(next_run, tz),
        "last_run_at": _iso(row.last_run_at),
        "last_run_local": _local(row.last_run_at, tz),
        "last_status": status,
        "last_error": error,
    }


async def _serialize(db: AsyncSession, rows: list[ReportSchedule]) -> list[dict]:
    owner_ids = {r.owner_user_id for r in rows if r.owner_user_id is not None}
    owners: dict[int, str] = {}
    if owner_ids:
        found = await db.execute(select(User.id, User.username).where(User.id.in_(owner_ids)))
        owners = {int(user_id): str(username) for user_id, username in found.all()}
    now = schedules.utcnow()
    tz = get_server_timezone()
    return [_schedule_row(r, owners, now, tz) for r in rows]


def _audit_detail(row: ReportSchedule) -> dict:
    return {
        "report_type": row.report_type,
        "cron_expression": row.cron_expression,
        "period": row.period,
        "format": row.format,
        "recipients": schedules.recipients_of(row),
        "owner_user_id": row.owner_user_id,
    }


async def _get_schedule(db: AsyncSession, schedule_id: int) -> ReportSchedule:
    row = await db.get(ReportSchedule, schedule_id)
    if row is None:
        raise HTTPException(404, "Schedule not found")
    return row


async def _create(db: AsyncSession, request: Request, actor: User, clean: dict, owner: User | None) -> dict:
    row = ReportSchedule(
        **clean,
        owner_user_id=owner.id if owner is not None else None,
        is_active=True,
        next_run_at=schedules.first_run(clean["cron_expression"], schedules.utcnow()),
    )
    db.add(row)
    await db.flush()
    await log_security_event(
        db,
        actor=actor,
        actor_ip=resolve_client_ip(request),
        action="report_schedule_created",
        resource_type="report_schedule",
        resource_id=str(row.id),
        detail=_audit_detail(row),
    )
    await db.commit()
    return {"ok": True, "schedule": (await _serialize(db, [row]))[0]}


@router.get("/schedules")
async def list_schedules(db: AsyncSession = Depends(get_db), _: User = Depends(require_reports)):
    rows = list((await db.execute(select(ReportSchedule).order_by(ReportSchedule.id))).scalars().all())
    return await _serialize(db, rows)


@router.post("/schedules")
async def create_schedule(
    body: ScheduleIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_reports_write),
):
    """A schedule of the whole service: it keeps running whoever set it up."""
    return await _create(db, request, admin, _validate_schedule(body), owner=None)


@router.post("/schedules/user")
async def user_schedule_report(
    body: ScheduleIn,
    request: Request,
    user: User = Depends(require_reports_write),
    db: AsyncSession = Depends(get_db),
):
    """A schedule of one's own: it goes only to the caller's own address.

    Reports hold the whole organisation's usage, so this takes what running
    them takes (write access to Reports). Each run checks again that the
    owner still has it and that the address is still theirs, and pauses the
    schedule when not (``report_schedule_service``).
    """
    clean = _validate_schedule(body)
    own = (user.email or "").strip().lower()
    others = [r for r in clean["recipients"].split(",") if r.lower() != own]
    if not own or others:
        raise HTTPException(400, "Self-service schedules can only be sent to your own account email")
    return await _create(db, request, user, clean, owner=user)


@router.patch("/schedules/{schedule_id}")
async def change_schedule(
    schedule_id: int,
    body: ScheduleChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_reports_write),
):
    """Pause or resume. A resumed schedule next runs at its next time from now:
    the runs it missed while paused are not sent late."""
    row = await _get_schedule(db, schedule_id)
    if bool(row.is_active) != body.is_active:
        if body.is_active:
            try:
                row.next_run_at = schedules.first_run(row.cron_expression, schedules.utcnow())
            except ValueError as exc:
                raise HTTPException(400, f"This schedule cannot run: {exc}") from exc
        row.is_active = body.is_active
        await log_security_event(
            db,
            actor=admin,
            actor_ip=resolve_client_ip(request),
            action="report_schedule_resumed" if body.is_active else "report_schedule_paused",
            resource_type="report_schedule",
            resource_id=str(row.id),
            detail=_audit_detail(row),
        )
        await db.commit()
    return {"ok": True, "schedule": (await _serialize(db, [row]))[0]}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_reports_write),
):
    row = await _get_schedule(db, schedule_id)
    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action="report_schedule_deleted",
        resource_type="report_schedule",
        resource_id=str(row.id),
        detail=_audit_detail(row),
    )
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/schedules/{schedule_id}/send")
async def send_schedule_now(
    schedule_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_reports_write),
):
    """Run the schedule now, as its next run would, without moving its next run."""
    row = await _get_schedule(db, schedule_id)
    result = await schedules.run_schedule(db, row)
    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action="report_schedule_sent_now",
        resource_type="report_schedule",
        resource_id=str(row.id),
        detail={**_audit_detail(row), "status": result.status, "sent": result.sent, "not_sent": list(result.not_sent)},
    )
    await db.commit()
    return {
        "status": result.status,
        "sent": result.sent,
        "not_sent": result.not_sent,
        "error": result.error,
        "schedule": (await _serialize(db, [row]))[0],
    }
