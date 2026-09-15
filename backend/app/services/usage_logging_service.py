"""RequestLog + ledger + hold settlement for one completed call (Phase 4.1).

``log_usage`` is the single write path every billed operation ends in: chat
streams (``turn_settlement``), helper LLM calls (``settle_auxiliary_usage``),
images, speech, video and metered tools. It lived in ``proxy_service`` and
was imported lazily from four services to dodge the import cycle; now it has
its own module with no dependency on the chat proxy.
"""

from __future__ import annotations

import asyncio
import datetime
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.language_detect import detect_prompt_language
from app.database import AsyncSessionLocal
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services.budget_reservation_service import (
    release,
    reservation_hold_usd,
    reservation_key,
    reserve,
    settle,
)
from app.services.observability import correlation_id as current_correlation_id, increment
from app.services.provider_utils import extract_prompt_text, sanitize_cost_usd
from app.services.usage_accounting_service import (
    PendingUsageEvent,
    capture_usage_event,
    legacy_usage_event,
    persist_usage_operation,
)

logger = logging.getLogger(__name__)


async def _apply_cost_to_user(db: AsyncSession, user_id: int, cost: float) -> None:
    if cost <= 0:
        return
    # Atomic increment via SQL UPDATE (col = col + :cost) instead of ORM
    # read-modify-write. Concurrent requests otherwise race on the same row:
    # both read the old value, both add their cost, both write — one update is
    # lost. The single UPDATE statement is atomic at the row level under both
    # PostgreSQL (row lock) and SQLite (database lock), so no lost updates.
    await db.execute(
        text("UPDATE users SET budget_used_usd = COALESCE(budget_used_usd, 0) + :cost WHERE id = :uid"),
        {"cost": float(cost), "uid": user_id},
    )


async def log_usage(
    db: AsyncSession,
    *,
    user_id: int | None,
    username: str,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    total_cost_usd: float,
    response_time_ms: float,
    prompt_language: str,
    source_ip: str | None,
    source: str,
    success: bool,
    error_message: str | None = None,
    alpha_router_api_key_id: int | None = None,
    user_api_key_id: int | None = None,
    client_app: str | None = None,
    budget_reservation_id: str | None = None,
    usage_events: list[PendingUsageEvent] | None = None,
    operation_type: str = "chat",
    operation_idempotency_key: str | None = None,
    project_id: str | None = None,
    error_code: str | None = None,
    http_status: int | None = None,
    correlation_id: str | None = None,
    provider_job_id: str | None = None,
) -> int | None:
    events = list(usage_events or [])
    if not events:
        events = [
            legacy_usage_event(
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                total_cost_usd=total_cost_usd,
                operation_name=operation_type,
            )
        ]
    log_row = RequestLog(
        user_id=user_id,
        username=username,
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        total_cost_usd=sanitize_cost_usd(total_cost_usd),
        response_time_ms=response_time_ms,
        prompt_language=prompt_language,
        source_ip=source_ip,
        source=source,
        client_app=client_app,
        success=success,
        error_message=error_message,
        error_code=(error_code or None),
        http_status=http_status,
        # Defaulted here rather than at every call site: inside a request this
        # is the id already stamped on that request's log lines.
        correlation_id=(correlation_id or current_correlation_id() or None),
        provider_job_id=(provider_job_id or None),
        alpha_router_api_key_id=alpha_router_api_key_id,
        user_api_key_id=user_api_key_id,
        budget_reservation_id=budget_reservation_id,
        project_id=project_id,
    )
    db.add(log_row)
    await db.flush()
    accounting = await persist_usage_operation(
        db,
        events=events,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        budget_reservation_id=budget_reservation_id,
        request_log_id=log_row.id,
        operation_type=operation_type,
        source=source,
        client_app=client_app,
        success=success,
        idempotency_key=operation_idempotency_key,
        metadata={"model_id": model_id},
    )
    if not accounting.created:
        await db.delete(log_row)
        if budget_reservation_id:
            await release(db, budget_reservation_id)
        await db.flush()
        return None
    total_cost_usd = sanitize_cost_usd(accounting.total_cost_usd)
    log_row.prompt_tokens = accounting.prompt_tokens
    log_row.completion_tokens = accounting.completion_tokens
    log_row.cached_tokens = accounting.cached_tokens
    log_row.total_cost_usd = total_cost_usd
    log_row.provider_cost_usd = accounting.provider_cost_usd
    log_row.calculated_cost_usd = accounting.calculated_cost_usd
    log_row.cost_source = accounting.cost_source
    log_row.cost_confidence = accounting.cost_confidence
    log_row.has_unpriced_usage = accounting.unpriced_event_count > 0
    log_row.usage_operation_id = accounting.operation_id
    settled = False
    if budget_reservation_id:
        settled = await settle(
            db,
            budget_reservation_id,
            actual_usd=total_cost_usd,
            request_log_id=log_row.id,
        )
    if not settled and alpha_router_api_key_id and total_cost_usd > 0:
        from app.models.api_key import AlphaRouterApiKey
        from app.services.alpha_router_api_key_service import record_key_usage

        key = await db.get(AlphaRouterApiKey, alpha_router_api_key_id)
        if key:
            await record_key_usage(db, key, total_cost_usd)
    elif not settled and user_id and total_cost_usd > 0:
        await _apply_cost_to_user(db, user_id, total_cost_usd)
    from app.services.user_api_key_service import touch_user_key_last_used

    await touch_user_key_last_used(db, user_api_key_id)
    await db.flush()
    return int(log_row.id) if log_row.id is not None else None


async def reserve_auxiliary_llm_usage(
    db: AsyncSession,
    *,
    user_id: int,
    ai_model: AIModel,
    operation_name: str,
    messages: list[dict],
    max_tokens: int,
) -> str | None:
    """Atomically reserve a helper LLM call and release its row lock."""

    body = {
        "model": ai_model.external_id,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    hold = await reserve(
        db,
        user_id=user_id,
        alpha_router_api_key_id=None,
        amount_usd=await reservation_hold_usd(
            db,
            service_type="llm",
            ai_model=ai_model,
            provider_type=ai_model.provider_type,
            model_id=ai_model.external_id,
            body=body,
        ),
        operation=operation_name[:32],
        model_id=ai_model.external_id,
        idempotency_key=reservation_key(body, operation=operation_name[:32]),
        # Auxiliary LLM calls (titles, prompt assist) are chat: reply length, and
        # therefore cost, is not knowable before the call.
        cost_is_estimated=True,
    )
    await db.commit()
    return hold.id if hold else None


async def settle_auxiliary_usage(
    *,
    user_id: int,
    username: str,
    ai_model: AIModel | None,
    provider_type: str | None,
    model_id: str,
    response,
    prompt,
    completion: str,
    operation_name: str,
    client_app: str,
    budget_reservation_id: str | None,
    success: bool,
    error_message: str | None = None,
    service_type: str = "llm",
    quantity: float | None = None,
    unit: str | None = None,
    started_at: datetime.datetime | None = None,
) -> None:
    """Persist one non-stream helper call without coupling it to route state."""

    event = capture_usage_event(
        response,
        ai_model=ai_model,
        provider_type=provider_type,
        service_type=service_type,
        operation_name=operation_name,
        model_id=model_id,
        status="succeeded" if success else "failed",
        started_at=started_at,
        completed_at=datetime.datetime.utcnow(),
        prompt=prompt,
        completion=completion,
        error_message=error_message,
        quantity=quantity,
        unit=unit,
    )
    for attempt in range(3):
        try:
            async with AsyncSessionLocal() as log_db:
                await log_usage(
                    log_db,
                    user_id=user_id,
                    username=username,
                    model_id=model_id,
                    prompt_tokens=event.usage.prompt_tokens,
                    completion_tokens=event.usage.completion_tokens,
                    cached_tokens=event.usage.cached_tokens,
                    total_cost_usd=float(event.quote.final_cost_usd or 0),
                    response_time_ms=max(
                        0.0,
                        (event.completed_at - event.started_at).total_seconds() * 1000,
                    ),
                    prompt_language=detect_prompt_language(
                        extract_prompt_text(prompt) if isinstance(prompt, list) else str(prompt or "")
                    ),
                    source_ip=None,
                    source="alpha_router_chat",
                    success=success,
                    error_message=error_message,
                    client_app=client_app,
                    budget_reservation_id=budget_reservation_id,
                    usage_events=[event],
                    operation_type=operation_name,
                    operation_idempotency_key=(
                        f"aux:{budget_reservation_id}" if budget_reservation_id else f"aux:{event.idempotency_key}"
                    ),
                )
                await log_db.commit()
            return
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            increment("budget_hold_leak")
            logger.exception(
                "Auxiliary usage settlement failed after retries operation=%s; reservation remains held for recovery",
                operation_name,
            )
