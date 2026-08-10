"""API request logs (admin + user)."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user, require_api_logs, require_api_logs_write
from app.database import get_db
from app.models.api_key import AlphaRouterApiKey
from app.models.connection import Connection
from app.models.cost_accounting import (
    CostLineItem,
    LedgerEntry,
    PricingSnapshot,
    ReconciliationRun,
    UsageEvent,
    UsageOperation,
)
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.log_export_service import (
    dataframe_to_csv_bytes,
    detail_rows_to_csv_bytes,
    request_log_detail_to_export_rows,
    request_logs_to_export_dataframe,
    resolve_log_export_maps,
)
from app.utils.display import format_app_source
from app.services.usage_accounting_service import (
    create_configured_pricing_snapshot,
    create_reconciliation_run,
    finish_reconciliation_run,
    reconcile_usage_event,
)

router = APIRouter(prefix="/api", tags=["logs"])


class ReconciliationItemIn(BaseModel):
    event_id: str
    actual_cost_usd: float = Field(ge=0)


class ReconciliationIn(BaseModel):
    provider_type: str
    connection_id: int | None = None
    source: str = "manual"
    period_start: datetime | None = None
    period_end: datetime | None = None
    items: list[ReconciliationItemIn] = Field(min_length=1, max_length=500)


class ConfiguredPricingIn(BaseModel):
    provider_type: str
    service_type: str
    model_id: str | None = None
    connection_id: int | None = None
    unit: str
    unit_price_usd: float = Field(ge=0)
    source: str = Field(default="admin", pattern="^(admin|contract)$")
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class ProviderReconciliationIn(BaseModel):
    connection_id: int
    limit: int = Field(default=50, ge=1, le=500)


def _log_row(
    r: RequestLog,
    provider: str | None = None,
    *,
    router_key: AlphaRouterApiKey | None = None,
) -> dict:
    source_code = (r.source or "").strip().lower()
    if source_code == "alpha_router_chat":
        app = format_app_source(r.source)
    else:
        app = (r.client_app or "").strip() or format_app_source(r.source)
    if r.alpha_router_api_key_id:
        identity_type = "api_key"
    elif source_code == "alpha_router_chat":
        identity_type = "chat"
    else:
        identity_type = "user"
    row = {
        "id": r.id,
        "request_time": r.request_time.isoformat() if r.request_time else None,
        "username": r.username,
        "identity_type": identity_type,
        "model_id": r.model_id,
        "provider": provider or "",
        "app": app,
        "prompt_language": r.prompt_language,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "cached_tokens": r.cached_tokens,
        "total_tokens": (r.prompt_tokens or 0) + (r.completion_tokens or 0),
        "total_cost_usd": r.total_cost_usd,
        "provider_cost_usd": r.provider_cost_usd,
        "calculated_cost_usd": r.calculated_cost_usd,
        "cost_source": r.cost_source or "unknown",
        "cost_confidence": r.cost_confidence or "unknown",
        "has_unpriced_usage": bool(r.has_unpriced_usage),
        "usage_operation_id": r.usage_operation_id,
        "reconciled_at": r.reconciled_at.isoformat() if r.reconciled_at else None,
        "response_time_ms": r.response_time_ms,
        "source_ip": r.source_ip,
        "source": r.source,
        "client_app": r.client_app,
        "success": r.success,
        "error_message": r.error_message,
    }
    if router_key:
        row["api_key_name"] = router_key.name
        row["api_key_prefix"] = router_key.key_prefix
        row["alpha_router_api_key_id"] = router_key.id
    return row


def _apply_log_filters(
    q,
    *,
    username: str | None,
    model_id: str | None,
    response_status: str | None,
    prompt_cache: str | None,
    start_date: str | None,
    end_date: str | None,
):
    if username:
        term = username.strip()
        key_match = select(AlphaRouterApiKey.id).where(
            AlphaRouterApiKey.name.contains(term)
        )
        q = q.where(
            or_(
                RequestLog.username.contains(term),
                RequestLog.alpha_router_api_key_id.in_(key_match),
            )
        )
    if model_id:
        q = q.where(RequestLog.model_id.contains(model_id.strip()))
    if response_status == "success":
        q = q.where(RequestLog.success.is_(True))
    elif response_status == "fail":
        q = q.where(RequestLog.success.is_(False))
    if prompt_cache == "yes":
        q = q.where(RequestLog.cached_tokens > 0)
    elif prompt_cache == "no":
        q = q.where(or_(RequestLog.cached_tokens == 0, RequestLog.cached_tokens.is_(None)))
    if start_date:
        q = q.where(RequestLog.request_time >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        q = q.where(RequestLog.request_time <= datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59))
    return q


@router.get("/admin/logs/filter-options")
async def admin_logs_filter_options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
):
    """Distinct usernames, API key names, and models present in request logs (for filter comboboxes)."""
    usernames = (
        await db.execute(
            select(RequestLog.username)
            .where(RequestLog.username.isnot(None), RequestLog.username != "")
            .distinct()
            .order_by(RequestLog.username)
        )
    ).scalars().all()
    models = (
        await db.execute(
            select(RequestLog.model_id)
            .where(RequestLog.model_id.isnot(None), RequestLog.model_id != "")
            .distinct()
            .order_by(RequestLog.model_id)
        )
    ).scalars().all()
    api_keys = (
        await db.execute(
            select(AlphaRouterApiKey.name)
            .join(
                RequestLog,
                RequestLog.alpha_router_api_key_id == AlphaRouterApiKey.id,
            )
            .where(
                AlphaRouterApiKey.name.isnot(None),
                AlphaRouterApiKey.name != "",
            )
            .distinct()
            .order_by(AlphaRouterApiKey.name)
        )
    ).scalars().all()

    identity_options: list[str] = []
    seen: set[str] = set()
    for name in list(usernames) + list(api_keys):
        label = (name or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        identity_options.append(label)

    return {
        "usernames": identity_options,
        "models": [m for m in models if (m or "").strip()],
    }


@router.get("/admin/logs/export")
async def admin_logs_export(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
    limit: int = Query(5000, ge=1, le=20000),
    username: str | None = None,
    model_id: str | None = None,
    response_status: str | None = Query(default=None, pattern="^(success|fail)$"),
    prompt_cache: str | None = Query(default=None, pattern="^(yes|no)$"),
    start_date: str | None = None,
    end_date: str | None = None,
    timezone: str = Query("local", pattern="^(local|utc)$"),
):
    q = select(RequestLog).order_by(RequestLog.request_time.desc())
    q = _apply_log_filters(
        q,
        username=username,
        model_id=model_id,
        response_status=response_status,
        prompt_cache=prompt_cache,
        start_date=start_date,
        end_date=end_date,
    )
    rows = (await db.execute(q.limit(limit))).scalars().all()
    provider_map, key_map = await resolve_log_export_maps(db, rows)
    df = request_logs_to_export_dataframe(
        rows,
        tz_mode=timezone,
        provider_map=provider_map,
        key_map=key_map,
    )
    content = dataframe_to_csv_bytes(df)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"alpharouter-api-logs-{stamp}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/logs")
async def admin_logs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
    limit: int = Query(100, le=500),
    offset: int = 0,
    username: str | None = None,
    model_id: str | None = None,
    response_status: str | None = Query(default=None, pattern="^(success|fail)$"),
    prompt_cache: str | None = Query(default=None, pattern="^(yes|no)$"),
    start_date: str | None = None,
    end_date: str | None = None,
):
    q = select(RequestLog).order_by(RequestLog.request_time.desc())
    q = _apply_log_filters(
        q,
        username=username,
        model_id=model_id,
        response_status=response_status,
        prompt_cache=prompt_cache,
        start_date=start_date,
        end_date=end_date,
    )
    rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
    operation_ids = {
        r.usage_operation_id
        for r in rows
        if r.usage_operation_id
    }
    operation_providers: dict[str, set[str]] = {}
    if operation_ids:
        provider_rows = (
            await db.execute(
                select(UsageEvent.operation_id, UsageEvent.provider_type)
                .where(UsageEvent.operation_id.in_(operation_ids))
                .distinct()
            )
        ).all()
        for operation_id, provider in provider_rows:
            if provider:
                operation_providers.setdefault(str(operation_id), set()).add(
                    str(provider)
                )
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
                select(AlphaRouterApiKey).where(
                    AlphaRouterApiKey.id.in_(key_ids)
                )
            )
        ).scalars().all()
        key_map = {k.id: k for k in keys}

    return {
        "items": [
            _log_row(
                r,
                (
                    next(iter(operation_providers[r.usage_operation_id]))
                    if r.usage_operation_id
                    and len(operation_providers.get(r.usage_operation_id, set())) == 1
                    else (
                        "mixed"
                        if r.usage_operation_id
                        and operation_providers.get(r.usage_operation_id)
                        else provider_map.get((r.model_id or "").strip())
                    )
                ),
                router_key=key_map.get(r.alpha_router_api_key_id),
            )
            for r in rows
        ],
        "offset": offset,
        "limit": limit,
    }


@router.get("/admin/cost-accounting/pricing")
async def configured_cost_pricing(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
):
    rows = (
        await db.execute(
            select(PricingSnapshot)
            .where(PricingSnapshot.source.in_(("admin", "contract")))
            .order_by(PricingSnapshot.effective_at.desc(), PricingSnapshot.id.desc())
            .limit(500)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "connection_id": row.connection_id,
                "provider_type": row.provider_type,
                "service_type": row.service_type,
                "model_id": row.model_id,
                "currency": row.currency,
                "source": row.source,
                "pricing": json.loads(row.pricing_json),
                "effective_at": (
                    row.effective_at.isoformat() if row.effective_at else None
                ),
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in rows
        ]
    }


@router.post("/admin/cost-accounting/pricing")
async def create_cost_pricing(
    body: ConfiguredPricingIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs_write),
):
    if body.connection_id is not None:
        connection = await db.get(Connection, body.connection_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        if (
            (connection.provider_type or "").strip().lower()
            != body.provider_type.strip().lower()
        ):
            raise HTTPException(
                status_code=400,
                detail="connection_id does not belong to provider_type",
            )
    try:
        row = await create_configured_pricing_snapshot(
            db,
            provider_type=body.provider_type,
            service_type=body.service_type,
            model_id=body.model_id,
            connection_id=body.connection_id,
            unit=body.unit,
            unit_price_usd=body.unit_price_usd,
            source=body.source,
            effective_at=body.effective_at,
            expires_at=body.expires_at,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return {
        "id": row.id,
        "provider_type": row.provider_type,
        "service_type": row.service_type,
        "model_id": row.model_id,
        "source": row.source,
        "pricing": json.loads(row.pricing_json),
        "effective_at": row.effective_at.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.get("/admin/cost-accounting/summary")
async def cost_accounting_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
):
    grouped = (
        await db.execute(
            select(
                UsageEvent.cost_source,
                UsageEvent.cost_confidence,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.final_cost_usd), 0),
            )
            .group_by(UsageEvent.cost_source, UsageEvent.cost_confidence)
            .order_by(UsageEvent.cost_source, UsageEvent.cost_confidence)
        )
    ).all()
    unpriced = (
        await db.execute(
            select(func.count(UsageEvent.id)).where(
                UsageEvent.final_cost_usd.is_(None)
            )
        )
    ).scalar_one()
    ledger_total = (
        await db.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount_usd), 0))
        )
    ).scalar_one()
    legacy_total = (
        await db.execute(
            select(func.coalesce(func.sum(RequestLog.total_cost_usd), 0)).where(
                RequestLog.usage_operation_id.is_(None)
            )
        )
    ).scalar_one()
    ledger_started_at = (
        await db.execute(select(func.min(UsageOperation.started_at)))
    ).scalar_one()
    recent_runs = (
        await db.execute(
            select(ReconciliationRun)
            .order_by(ReconciliationRun.started_at.desc())
            .limit(10)
        )
    ).scalars().all()
    return {
        "ledger_total_usd": float(ledger_total or 0),
        "legacy_total_usd": float(legacy_total or 0),
        "combined_total_usd": float(ledger_total or 0)
        + float(legacy_total or 0),
        "ledger_started_at": (
            ledger_started_at.isoformat() if ledger_started_at else None
        ),
        "unpriced_event_count": int(unpriced or 0),
        "by_source": [
            {
                "cost_source": source or "unknown",
                "cost_confidence": confidence or "unknown",
                "event_count": int(count or 0),
                "total_cost_usd": float(total or 0),
            }
            for source, confidence, count, total in grouped
        ],
        "recent_reconciliation_runs": [
            {
                "id": run.id,
                "provider_type": run.provider_type,
                "source": run.source,
                "status": run.status,
                "expected_cost_usd": float(run.expected_cost_usd or 0),
                "reported_cost_usd": float(run.reported_cost_usd or 0),
                "adjustment_usd": float(run.adjustment_usd or 0),
                "matched_event_count": int(run.matched_event_count or 0),
                "unmatched_event_count": int(run.unmatched_event_count or 0),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
            for run in recent_runs
        ],
    }


@router.get("/admin/logs/{log_id}/export")
async def admin_log_export(
    log_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
    timezone: str = Query("local", pattern="^(local|utc)$"),
):
    log_row = await db.get(RequestLog, log_id)
    if log_row is None:
        raise HTTPException(status_code=404, detail="Request log not found")

    provider_map, key_map = await resolve_log_export_maps(db, [log_row])
    provider = provider_map.get((log_row.model_id or "").strip())
    router_key = (
        key_map.get(log_row.alpha_router_api_key_id)
        if log_row.alpha_router_api_key_id
        else None
    )

    operation = None
    events: list[UsageEvent] = []
    lines_by_event: dict[str, list[CostLineItem]] = {}
    if log_row.usage_operation_id:
        operation = await db.get(UsageOperation, log_row.usage_operation_id)
        events = (
            await db.execute(
                select(UsageEvent)
                .where(UsageEvent.operation_id == log_row.usage_operation_id)
                .order_by(UsageEvent.attempt_index, UsageEvent.started_at)
            )
        ).scalars().all()
        providers = {
            (event.provider_type or "").strip()
            for event in events
            if (event.provider_type or "").strip()
        }
        if len(providers) == 1:
            provider = next(iter(providers))
        elif len(providers) > 1:
            provider = "mixed"
        event_ids = [event.id for event in events]
        if event_ids:
            line_rows = (
                await db.execute(
                    select(CostLineItem)
                    .where(CostLineItem.usage_event_id.in_(event_ids))
                    .order_by(CostLineItem.id)
                )
            ).scalars().all()
            for line in line_rows:
                lines_by_event.setdefault(line.usage_event_id, []).append(line)

    detail_rows = request_log_detail_to_export_rows(
        log_row,
        tz_mode=timezone,
        provider=provider,
        router_key=router_key,
        operation=operation,
        events=events,
        lines_by_event=lines_by_event,
    )
    content = detail_rows_to_csv_bytes(detail_rows)
    filename = f"alpharouter-api-log-{log_id}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _cost_details_payload(db: AsyncSession, log_row: RequestLog) -> dict:
    if not log_row.usage_operation_id:
        return {
            "operation": None,
            "events": [],
            "legacy": True,
            "total_cost_usd": float(log_row.total_cost_usd or 0),
        }
    operation = await db.get(UsageOperation, log_row.usage_operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Usage operation not found")
    events = (
        await db.execute(
            select(UsageEvent)
            .where(UsageEvent.operation_id == operation.id)
            .order_by(UsageEvent.attempt_index, UsageEvent.started_at)
        )
    ).scalars().all()
    event_ids = [event.id for event in events]
    line_rows = (
        (
            await db.execute(
                select(CostLineItem)
                .where(CostLineItem.usage_event_id.in_(event_ids))
                .order_by(CostLineItem.id)
            )
        ).scalars().all()
        if event_ids
        else []
    )
    lines_by_event: dict[str, list[CostLineItem]] = {}
    for line in line_rows:
        lines_by_event.setdefault(line.usage_event_id, []).append(line)
    return {
        "operation": {
            "id": operation.id,
            "operation_type": operation.operation_type,
            "status": operation.status,
            "total_cost_usd": float(operation.total_cost_usd or 0),
            "provider_cost_usd": (
                float(operation.provider_cost_usd)
                if operation.provider_cost_usd is not None
                else None
            ),
            "calculated_cost_usd": (
                float(operation.calculated_cost_usd)
                if operation.calculated_cost_usd is not None
                else None
            ),
            "unpriced_event_count": int(operation.unpriced_event_count or 0),
            "reconciled_at": (
                operation.reconciled_at.isoformat()
                if operation.reconciled_at
                else None
            ),
        },
        "events": [
            {
                "id": event.id,
                "provider_type": event.provider_type,
                "service_type": event.service_type,
                "operation_name": event.operation_name,
                "model_id": event.model_id,
                "attempt_index": event.attempt_index,
                "upstream_request_id": event.upstream_request_id,
                "status": event.status,
                "prompt_tokens": event.prompt_tokens,
                "completion_tokens": event.completion_tokens,
                "cached_tokens": event.cached_tokens,
                "cache_write_tokens": event.cache_write_tokens,
                "reasoning_tokens": event.reasoning_tokens,
                "provider_cost_usd": (
                    float(event.provider_cost_usd)
                    if event.provider_cost_usd is not None
                    else None
                ),
                "calculated_cost_usd": (
                    float(event.calculated_cost_usd)
                    if event.calculated_cost_usd is not None
                    else None
                ),
                "final_cost_usd": (
                    float(event.final_cost_usd)
                    if event.final_cost_usd is not None
                    else None
                ),
                "cost_source": event.cost_source,
                "cost_confidence": event.cost_confidence,
                "reconciliation_attempts": int(
                    event.reconciliation_attempts or 0
                ),
                "last_reconciliation_attempt_at": (
                    event.last_reconciliation_attempt_at.isoformat()
                    if event.last_reconciliation_attempt_at
                    else None
                ),
                "error_message": event.error_message,
                "line_items": [
                    {
                        "category": line.category,
                        "quantity": line.quantity,
                        "unit": line.unit,
                        "unit_price_usd": (
                            float(line.unit_price_usd)
                            if line.unit_price_usd is not None
                            else None
                        ),
                        "cost_usd": (
                            float(line.cost_usd)
                            if line.cost_usd is not None
                            else None
                        ),
                        "pricing_source": line.pricing_source,
                    }
                    for line in lines_by_event.get(event.id, [])
                ],
            }
            for event in events
        ],
        "legacy": False,
    }


@router.get("/admin/logs/{log_id}/cost-details")
async def admin_log_cost_details(
    log_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
):
    log_row = await db.get(RequestLog, log_id)
    if log_row is None:
        raise HTTPException(status_code=404, detail="Request log not found")
    return await _cost_details_payload(db, log_row)


@router.post("/admin/cost-accounting/reconcile/provider")
async def reconcile_provider_costs(
    body: ProviderReconciliationIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs_write),
):
    from app.services.provider_reconciliation_service import (
        reconcile_connection_costs,
    )

    connection = await db.get(Connection, body.connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        run = await reconcile_connection_costs(
            db,
            connection,
            limit=body.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    if run is None:
        return {
            "run_id": None,
            "status": "no_candidates",
            "matched_event_count": 0,
            "unmatched_event_count": 0,
            "adjustment_usd": 0.0,
        }
    return {
        "run_id": run.id,
        "status": run.status,
        "matched_event_count": int(run.matched_event_count or 0),
        "unmatched_event_count": int(run.unmatched_event_count or 0),
        "adjustment_usd": float(run.adjustment_usd or 0),
    }


@router.post("/admin/cost-accounting/reconcile")
async def reconcile_costs(
    body: ReconciliationIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs_write),
):
    provider = body.provider_type.strip().lower()
    if not provider:
        raise HTTPException(status_code=400, detail="provider_type is required")
    run = await create_reconciliation_run(
        db,
        provider_type=provider,
        source=body.source,
        connection_id=body.connection_id,
        period_start=body.period_start,
        period_end=body.period_end,
        raw_summary={"submitted_items": len(body.items)},
    )
    matched = 0
    unmatched = 0
    adjustments = 0.0
    seen_event_ids: set[str] = set()
    for item in body.items:
        if item.event_id in seen_event_ids:
            continue
        seen_event_ids.add(item.event_id)
        event = await db.get(UsageEvent, item.event_id)
        if (
            event is None
            or (event.provider_type or "").lower() != provider
            or (
                body.connection_id is not None
                and event.connection_id != body.connection_id
            )
        ):
            unmatched += 1
            continue
        adjustments += await reconcile_usage_event(
            db,
            event_id=event.id,
            actual_cost_usd=item.actual_cost_usd,
            reconciliation_run_id=run.id,
        )
        matched += 1
    await finish_reconciliation_run(
        db,
        run,
        unmatched_event_count=unmatched,
    )
    await db.commit()
    return {
        "run_id": run.id,
        "status": run.status,
        "matched_event_count": matched,
        "unmatched_event_count": unmatched,
        "adjustment_usd": round(adjustments, 12),
    }


@router.delete("/admin/logs")
async def clear_admin_logs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs_write),
):
    """Permanently delete all API request log rows."""
    result = await db.execute(delete(RequestLog))
    await db.commit()
    return {"ok": True, "deleted": result.rowcount}


@router.get("/user/logs")
async def user_logs_route(
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(200, le=500),
):
    rows = (
        await db.execute(
            select(RequestLog)
            .where(RequestLog.user_id == user.id)
            .order_by(RequestLog.request_time.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_log_row(r) for r in rows]


async def _owned_request_log(db: AsyncSession, user: User, log_id: int) -> RequestLog:
    log_row = await db.get(RequestLog, log_id)
    if log_row is None or log_row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Request log not found")
    return log_row


@router.get("/user/request-logs/{log_id}")
async def user_request_log_summary(
    log_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Single owned request log summary for chat message cost details (no list/browse)."""
    log_row = await _owned_request_log(db, user, log_id)
    return _log_row(log_row)


@router.get("/user/request-logs/{log_id}/cost-details")
async def user_request_log_cost_details(
    log_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Cost ledger for one owned request log — same payload shape as admin cost-details."""
    log_row = await _owned_request_log(db, user, log_id)
    return await _cost_details_payload(db, log_row)
