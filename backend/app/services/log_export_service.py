"""Detailed request-log exports (aligned with API Logs table)."""

from __future__ import annotations

import csv
import io
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import AlphaRouterApiKey, UserApiKey
from app.models.cost_accounting import CostLineItem, UsageEvent, UsageOperation
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services.activity_service import _display_dt
from app.utils.display import format_app_source

ACTIVITY_LOG_COLUMNS = [
    "Id",
    "Time",
    "User",
    "Model",
    "Provider",
    "App",
    "Input",
    "Output",
    "Cached Tokens",
    "Cost $",
    "Provider Cost $",
    "Calculated Cost $",
    "Cost Source",
    "Cost Confidence",
    "Duration ms",
    "Response Status",
    "Source IP",
    "Language",
]

DETAIL_LOG_COLUMNS = [
    "Row Type",
    "Log Id",
    "Time",
    "User",
    "Model",
    "Provider",
    "App",
    "Input",
    "Output",
    "Cached Tokens",
    "Cost $",
    "Provider Cost $",
    "Calculated Cost $",
    "Cost Source",
    "Cost Confidence",
    "Duration ms",
    "Response Status",
    "Source IP",
    "Language",
    "Operation Id",
    "Operation Type",
    "Operation Status",
    "Attempt",
    "Event Id",
    "Event Provider",
    "Service Type",
    "Operation Name",
    "Event Model",
    "Event Status",
    "Upstream Request Id",
    "Event Prompt Tokens",
    "Event Completion Tokens",
    "Event Cached Tokens",
    "Event Reasoning Tokens",
    "Event Final Cost $",
    "Event Provider Cost $",
    "Event Calculated Cost $",
    "Event Cost Source",
    "Event Cost Confidence",
    "Line Category",
    "Line Quantity",
    "Line Unit",
    "Line Unit Price $",
    "Line Cost $",
    "Line Pricing Source",
]


def _format_user(
    r: RequestLog,
    router_key: AlphaRouterApiKey | None,
    user_key: UserApiKey | None = None,
) -> str:
    source_code = (r.source or "").strip().lower()
    if getattr(r, "alpha_router_api_key_id", None):
        name = (router_key.name if router_key else None) or r.username or "API key"
        return f"{name} (Gateway API Key)"
    if getattr(r, "user_api_key_id", None):
        username = (r.username or "unknown").strip() or "unknown"
        key_name = (user_key.name if user_key else None) or ""
        if key_name and key_name.strip().lower() != username.lower():
            return f"{username} · {key_name.strip()} (Personal API Key)"
        return f"{username} (Personal API Key)"
    if source_code == "alpha_router_chat":
        return f"{r.username or 'unknown'} (Chat)"
    return (r.username or "unknown").strip() or "unknown"


def _format_app(r: RequestLog) -> str:
    source_code = (r.source or "").strip().lower()
    if source_code == "alpha_router_chat":
        return format_app_source(r.source)
    return (r.client_app or "").strip() or format_app_source(r.source)


def _money(value: Any) -> float | str:
    if value is None:
        return ""
    try:
        return round(float(value), 8)
    except (TypeError, ValueError, OverflowError):
        return ""


def log_row_to_export(
    r: RequestLog,
    *,
    tz_mode: str,
    provider: str | None = None,
    router_key: AlphaRouterApiKey | None = None,
    user_key: UserApiKey | None = None,
) -> dict[str, Any]:
    dt = r.request_time
    time_str = _display_dt(dt, tz_mode).strftime("%Y-%m-%dT%H:%M:%S") if dt else ""
    return {
        "Id": int(r.id),
        "Time": time_str,
        "User": _format_user(r, router_key, user_key),
        "Model": r.model_id or "",
        "Provider": provider or "",
        "App": _format_app(r),
        "Input": int(r.prompt_tokens or 0),
        "Output": int(r.completion_tokens or 0),
        "Cached Tokens": int(r.cached_tokens or 0),
        "Cost $": round(float(r.total_cost_usd or 0), 6),
        "Provider Cost $": _money(r.provider_cost_usd),
        "Calculated Cost $": _money(r.calculated_cost_usd),
        "Cost Source": r.cost_source or "",
        "Cost Confidence": (
            "unpriced"
            if r.has_unpriced_usage
            else (r.cost_confidence or "")
        ),
        "Duration ms": round(float(r.response_time_ms or 0), 1),
        "Response Status": "Success" if r.success else "Fail",
        "Source IP": r.source_ip or "",
        "Language": r.prompt_language or "",
    }


async def resolve_log_export_maps(
    db: AsyncSession,
    rows: list[RequestLog],
) -> tuple[dict[str, str], dict[int, AlphaRouterApiKey], dict[int, UserApiKey]]:
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
                select(AlphaRouterApiKey).where(AlphaRouterApiKey.id.in_(key_ids))
            )
        ).scalars().all()
        key_map = {k.id: k for k in keys}
    user_key_ids = {r.user_api_key_id for r in rows if r.user_api_key_id}
    user_key_map: dict[int, UserApiKey] = {}
    if user_key_ids:
        user_keys = (
            await db.execute(
                select(UserApiKey).where(UserApiKey.id.in_(user_key_ids))
            )
        ).scalars().all()
        user_key_map = {k.id: k for k in user_keys}
    return provider_map, key_map, user_key_map


def request_logs_to_export_dataframe(
    rows: list[RequestLog],
    *,
    tz_mode: str,
    provider_map: dict[str, str],
    key_map: dict[int, AlphaRouterApiKey],
    user_key_map: dict[int, UserApiKey] | None = None,
) -> pd.DataFrame:
    user_key_map = user_key_map or {}
    if not rows:
        return pd.DataFrame(columns=ACTIVITY_LOG_COLUMNS)
    sorted_rows = sorted(rows, key=lambda r: r.request_time or r.id, reverse=True)
    data = [
        log_row_to_export(
            r,
            tz_mode=tz_mode,
            provider=provider_map.get((r.model_id or "").strip()),
            router_key=(
                key_map.get(r.alpha_router_api_key_id)
                if r.alpha_router_api_key_id
                else None
            ),
            user_key=(
                user_key_map.get(r.user_api_key_id)
                if getattr(r, "user_api_key_id", None)
                else None
            ),
        )
        for r in sorted_rows
    ]
    return pd.DataFrame(data, columns=ACTIVITY_LOG_COLUMNS)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, lineterminator="\n")
    # UTF-8 BOM so Excel opens Persian/Unicode correctly.
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _empty_detail_row() -> dict[str, Any]:
    return {column: "" for column in DETAIL_LOG_COLUMNS}


def request_log_detail_to_export_rows(
    log_row: RequestLog,
    *,
    tz_mode: str,
    provider: str | None,
    router_key: AlphaRouterApiKey | None,
    operation: UsageOperation | None,
    events: list[UsageEvent],
    lines_by_event: dict[str, list[CostLineItem]],
) -> list[dict[str, Any]]:
    base = log_row_to_export(
        log_row,
        tz_mode=tz_mode,
        provider=provider,
        router_key=router_key,
    )
    rows: list[dict[str, Any]] = []

    request_row = _empty_detail_row()
    request_row.update(
        {
            "Row Type": "request",
            "Log Id": base["Id"],
            "Time": base["Time"],
            "User": base["User"],
            "Model": base["Model"],
            "Provider": base["Provider"],
            "App": base["App"],
            "Input": base["Input"],
            "Output": base["Output"],
            "Cached Tokens": base["Cached Tokens"],
            "Cost $": base["Cost $"],
            "Provider Cost $": base["Provider Cost $"],
            "Calculated Cost $": base["Calculated Cost $"],
            "Cost Source": base["Cost Source"],
            "Cost Confidence": base["Cost Confidence"],
            "Duration ms": base["Duration ms"],
            "Response Status": base["Response Status"],
            "Source IP": base["Source IP"],
            "Language": base["Language"],
        }
    )
    if operation is not None:
        request_row.update(
            {
                "Operation Id": operation.id,
                "Operation Type": operation.operation_type or "",
                "Operation Status": operation.status or "",
                "Cost $": round(float(operation.total_cost_usd or base["Cost $"] or 0), 8),
                "Provider Cost $": _money(operation.provider_cost_usd),
                "Calculated Cost $": _money(operation.calculated_cost_usd),
            }
        )
    rows.append(request_row)

    for event in events:
        event_row = _empty_detail_row()
        event_row.update(
            {
                "Row Type": "event",
                "Log Id": base["Id"],
                "Time": base["Time"],
                "User": base["User"],
                "Model": base["Model"],
                "Provider": base["Provider"],
                "App": base["App"],
                "Operation Id": event.operation_id or "",
                "Attempt": int(event.attempt_index or 0),
                "Event Id": event.id,
                "Event Provider": event.provider_type or "",
                "Service Type": event.service_type or "",
                "Operation Name": event.operation_name or "",
                "Event Model": event.model_id or "",
                "Event Status": event.status or "",
                "Upstream Request Id": event.upstream_request_id or "",
                "Event Prompt Tokens": int(event.prompt_tokens or 0),
                "Event Completion Tokens": int(event.completion_tokens or 0),
                "Event Cached Tokens": int(event.cached_tokens or 0),
                "Event Reasoning Tokens": int(event.reasoning_tokens or 0),
                "Event Final Cost $": _money(event.final_cost_usd),
                "Event Provider Cost $": _money(event.provider_cost_usd),
                "Event Calculated Cost $": _money(event.calculated_cost_usd),
                "Event Cost Source": event.cost_source or "",
                "Event Cost Confidence": event.cost_confidence or "",
            }
        )
        rows.append(event_row)

        for line in lines_by_event.get(event.id, []):
            line_row = dict(event_row)
            line_row.update(
                {
                    "Row Type": "line_item",
                    "Line Category": line.category or "",
                    "Line Quantity": float(line.quantity or 0),
                    "Line Unit": line.unit or "",
                    "Line Unit Price $": _money(line.unit_price_usd),
                    "Line Cost $": _money(line.cost_usd),
                    "Line Pricing Source": line.pricing_source or "",
                }
            )
            rows.append(line_row)

    return rows


def detail_rows_to_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=DETAIL_LOG_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in DETAIL_LOG_COLUMNS})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
