"""What a report request may ask for, and turning it into build_report parameters.

Shared by the Reports page (preview, export) and the scheduled reports, which
run the same request later with the dates their period covers.
"""

from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.services.reports_catalog import REPORT_CATALOG


class ReportRequest(BaseModel):
    report_type: str
    start_date: str | None = None
    end_date: str | None = None
    format: str = "csv"
    user_id: int | None = None
    agent_id: str | None = None
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
    project_id: str | None = None


def parse_dates(start: str | None, end: str | None) -> tuple[datetime, datetime]:
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


def default_dates() -> tuple[str, str]:
    end = datetime.utcnow().date()
    start = end - timedelta(days=30)
    return start.isoformat(), end.isoformat()


def report_params(body: ReportRequest) -> dict:
    meta = next((r for r in REPORT_CATALOG if r["id"] == body.report_type), None)
    if not meta:
        raise HTTPException(400, f"Unknown report_type: {body.report_type}")

    params: dict = {
        "user_id": body.user_id,
        "agent_id": (body.agent_id or "").strip() or None,
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
        "project_id": (body.project_id or "").strip() or None,
    }

    if meta["needs_date"]:
        start, end = parse_dates(body.start_date, body.end_date)
        params["_start"] = start
        params["_end"] = end
    elif body.report_type == "users_no_recent_login":
        _, end = parse_dates(
            body.start_date or default_dates()[0],
            body.end_date or default_dates()[1],
        )
        params["_end"] = end

    if "plan" in meta["params"] and body.report_type == "plan_usage" and not body.plan_id:
        raise HTTPException(400, "plan_id required")
    if "department" in meta["params"] and body.report_type == "department_top_models" and not body.department:
        raise HTTPException(400, "department required")
    if "group" in meta["params"] and body.report_type == "group_members_usage" and not body.group_id:
        raise HTTPException(400, "group_id required")
    if (
        "project" in meta["params"]
        and body.report_type
        in {
            "project_usage_summary",
            "project_usage_by_model",
            "project_usage_by_member",
            "project_media_usage_summary",
        }
        and not body.project_id
    ):
        raise HTTPException(400, "project_id required")

    return params
