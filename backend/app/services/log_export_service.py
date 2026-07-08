"""Detailed request-log exports (aligned with API Logs table)."""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import NitroApiKey
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services.activity_service import _display_dt
from app.utils.display import format_app_source

ACTIVITY_LOG_COLUMNS = [
    "Time",
    "User",
    "Model",
    "Provider",
    "App",
    "Input",
    "Output",
    "Cached Tokens",
    "Cost $",
    "Latency ms",
    "Response Status",
    "Source IP",
    "Language",
]


def _format_user(r: RequestLog, nitro_key: NitroApiKey | None) -> str:
    source_code = (r.source or "").strip().lower()
    if r.nitro_api_key_id:
        name = (nitro_key.name if nitro_key else None) or r.username or "API key"
        return f"{name} (API Key)"
    if source_code in ("nitro_chat", "billi_chat"):
        return f"{r.username or 'unknown'} (Chat)"
    return (r.username or "unknown").strip() or "unknown"


def _format_app(r: RequestLog) -> str:
    source_code = (r.source or "").strip().lower()
    if source_code in ("nitro_chat", "billi_chat"):
        return format_app_source(r.source)
    return (r.client_app or "").strip() or format_app_source(r.source)


def log_row_to_export(
    r: RequestLog,
    *,
    tz_mode: str,
    provider: str | None = None,
    nitro_key: NitroApiKey | None = None,
) -> dict[str, Any]:
    dt = r.request_time
    time_str = _display_dt(dt, tz_mode).strftime("%Y-%m-%dT%H:%M:%S") if dt else ""
    return {
        "Time": time_str,
        "User": _format_user(r, nitro_key),
        "Model": r.model_id or "",
        "Provider": provider or "",
        "App": _format_app(r),
        "Input": int(r.prompt_tokens or 0),
        "Output": int(r.completion_tokens or 0),
        "Cached Tokens": int(r.cached_tokens or 0),
        "Cost $": round(float(r.total_cost_usd or 0), 6),
        "Duration ms": round(float(r.response_time_ms or 0), 1),
        "Response Status": "Success" if r.success else "Fail",
        "Source IP": r.source_ip or "",
        "Language": r.prompt_language or "",
    }


async def resolve_log_export_maps(
    db: AsyncSession,
    rows: list[RequestLog],
) -> tuple[dict[str, str], dict[int, NitroApiKey]]:
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

    key_ids = {r.nitro_api_key_id for r in rows if r.nitro_api_key_id}
    key_map: dict[int, NitroApiKey] = {}
    if key_ids:
        keys = (await db.execute(select(NitroApiKey).where(NitroApiKey.id.in_(key_ids)))).scalars().all()
        key_map = {k.id: k for k in keys}
    return provider_map, key_map


def request_logs_to_export_dataframe(
    rows: list[RequestLog],
    *,
    tz_mode: str,
    provider_map: dict[str, str],
    key_map: dict[int, NitroApiKey],
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=ACTIVITY_LOG_COLUMNS)
    sorted_rows = sorted(rows, key=lambda r: r.request_time or r.id, reverse=True)
    data = [
        log_row_to_export(
            r,
            tz_mode=tz_mode,
            provider=provider_map.get((r.model_id or "").strip()),
            nitro_key=key_map.get(r.nitro_api_key_id) if r.nitro_api_key_id else None,
        )
        for r in sorted_rows
    ]
    return pd.DataFrame(data, columns=ACTIVITY_LOG_COLUMNS)
