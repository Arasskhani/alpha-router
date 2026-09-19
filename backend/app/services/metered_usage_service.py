"""Budget and ledger helpers for non-LLM metered provider calls."""

from __future__ import annotations

import asyncio

import anyio
import datetime
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.observability import increment
from app.services.usage_logging_service import log_usage
from app.database import AsyncSessionLocal
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.budget_reservation_service import (
    reservation_hold_usd,
    reserve,
)
from app.services.usage_accounting_service import (
    SUBJECT_PLATFORM,
    capture_usage_event,
)

logger = logging.getLogger(__name__)

#: The ``username`` column of a platform-incurred row. Reports group by that
#: column, so the platform's own spend shows up under one name instead of
#: being scattered across "user-None".
PLATFORM_USERNAME = "platform"


@dataclass(slots=True)
class MeteredUsageCall:
    id: str
    user_id: int | None
    alpha_router_api_key_id: int | None
    connection_id: int | None
    username: str
    provider_type: str
    service_type: str
    operation_name: str
    model_id: str
    budget_reservation_id: str | None
    started_at: datetime.datetime
    source: str = "alpha_router_tool"
    client_app: str = "chat_tool"
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Set for platform-incurred calls (no user, no key, no budget hold).
    subject_type: str | None = None
    #: The catalog row whose pricing prices the call. Left ``None`` the quote
    #: falls back to the provider's or LiteLLM's own figure.
    pricing_model: AIModel | None = None


async def start_metered_usage(
    *,
    user_id: int | None,
    alpha_router_api_key_id: int | None = None,
    provider_type: str,
    service_type: str,
    operation_name: str,
    model_id: str,
    connection_id: int | None = None,
    quantity: float = 1,
    unit: str = "request",
    username: str | None = None,
    source: str = "alpha_router_tool",
    client_app: str = "chat_tool",
    metadata: dict[str, Any] | None = None,
    reserve_budget: bool = True,
    platform: bool = False,
    pricing_model: AIModel | None = None,
) -> MeteredUsageCall:
    """Reserve a conservative hold before one external metered call.

    ``platform=True`` names the platform itself as the subject: the call is
    recorded and priced so the spend is visible, but nobody's budget is held
    or charged, because nobody asked for it. A user or key and ``platform``
    together is a contradiction and is refused.
    """

    call_id = str(uuid.uuid4())
    reservation_id: str | None = None
    resolved_username = (username or "").strip()
    if platform:
        if user_id is not None or alpha_router_api_key_id is not None:
            raise ValueError("A platform-incurred call cannot also name a user or API key")
        return MeteredUsageCall(
            id=call_id,
            user_id=None,
            alpha_router_api_key_id=None,
            connection_id=connection_id,
            username=PLATFORM_USERNAME,
            provider_type=(provider_type or "unknown").strip().lower() or "unknown",
            service_type=(service_type or "tool").strip().lower() or "tool",
            operation_name=(operation_name or "tool_call").strip()[:64] or "tool_call",
            model_id=(model_id or operation_name or "unknown").strip()[:512] or "unknown",
            budget_reservation_id=None,
            started_at=datetime.datetime.utcnow(),
            source=source[:32],
            client_app=client_app[:128],
            metadata=dict(metadata or {}),
            subject_type=SUBJECT_PLATFORM,
            pricing_model=pricing_model,
        )
    if user_id is None and alpha_router_api_key_id is None:
        raise ValueError("A user or Alpharouter API-key subject is required")
    async with AsyncSessionLocal() as db:
        if not resolved_username and user_id is not None:
            user = await db.get(User, int(user_id))
            resolved_username = str(getattr(user, "username", "") or "").strip() if user is not None else ""
        if reserve_budget:
            hold_amount = await reservation_hold_usd(
                db,
                service_type=service_type,
                provider_type=provider_type,
                model_id=model_id,
                connection_id=connection_id,
                quantity=max(0.0, float(quantity)),
                unit=unit,
            )
            hold = await reserve(
                db,
                user_id=int(user_id) if user_id is not None else None,
                alpha_router_api_key_id=alpha_router_api_key_id,
                amount_usd=hold_amount,
                operation=operation_name[:32],
                model_id=model_id[:512],
                idempotency_key=f"metered:{call_id}",
            )
            reservation_id = hold.id if hold is not None else None
        await db.commit()

    return MeteredUsageCall(
        id=call_id,
        user_id=int(user_id) if user_id is not None else None,
        alpha_router_api_key_id=alpha_router_api_key_id,
        connection_id=connection_id,
        username=resolved_username
        or (f"user-{user_id}" if user_id is not None else f"api-key-{alpha_router_api_key_id}"),
        provider_type=(provider_type or "unknown").strip().lower() or "unknown",
        service_type=(service_type or "tool").strip().lower() or "tool",
        operation_name=(operation_name or "tool_call").strip()[:64] or "tool_call",
        model_id=(model_id or operation_name or "unknown").strip()[:512] or "unknown",
        budget_reservation_id=reservation_id,
        started_at=datetime.datetime.utcnow(),
        source=source[:32],
        client_app=client_app[:128],
        metadata=dict(metadata or {}),
        pricing_model=pricing_model,
    )


async def finish_metered_usage(
    call: MeteredUsageCall,
    *,
    response: Any = None,
    success: bool,
    quantity: float | None = 1,
    unit: str | None = "request",
    error_message: str | None = None,
) -> None:
    """Persist one metered call and settle its hold without masking tool output."""

    completed_at = datetime.datetime.utcnow()
    event = capture_usage_event(
        response,
        ai_model=call.pricing_model,
        provider_type=call.provider_type,
        service_type=call.service_type,
        operation_name=call.operation_name,
        model_id=call.model_id,
        status="succeeded" if success else "failed",
        started_at=call.started_at,
        completed_at=completed_at,
        quantity=quantity if success else None,
        unit=unit if success else None,
        error_message=error_message,
        idempotency_key=f"metered:{call.id}:event",
    )
    event.connection_id = call.connection_id or getattr(call.pricing_model, "connection_id", None)

    async def _persist() -> bool:
        for attempt in range(3):
            try:
                async with AsyncSessionLocal() as db:
                    await log_usage(
                        db,
                        user_id=call.user_id,
                        alpha_router_api_key_id=call.alpha_router_api_key_id,
                        username=call.username,
                        model_id=call.model_id,
                        prompt_tokens=event.usage.prompt_tokens,
                        completion_tokens=event.usage.completion_tokens,
                        cached_tokens=event.usage.cached_tokens,
                        total_cost_usd=float(event.quote.final_cost_usd or 0),
                        response_time_ms=max(
                            0.0,
                            (completed_at - call.started_at).total_seconds() * 1000,
                        ),
                        prompt_language="other",
                        source_ip=None,
                        source=call.source,
                        success=success,
                        error_message=error_message,
                        client_app=call.client_app,
                        budget_reservation_id=call.budget_reservation_id,
                        usage_events=[event],
                        operation_type=call.operation_name,
                        operation_idempotency_key=f"metered:{call.id}",
                        subject_type=call.subject_type,
                    )
                    await db.commit()
                return True
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                increment("budget_hold_leak")
                logger.exception(
                    "Metered usage settlement failed after retries provider=%s operation=%s; reservation remains held",
                    call.provider_type,
                    call.operation_name,
                )
        return False

    # Shield the frame, not just the coroutine: under Starlette's anyio cancel
    # scope a plain 'await task' in the except branch is re-cancelled before the
    # settlement finishes (see proxy_service.stream_chat finalizer).
    with anyio.CancelScope(shield=True):
        await _persist()
