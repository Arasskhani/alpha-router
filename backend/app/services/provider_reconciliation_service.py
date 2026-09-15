"""Pluggable provider reconciliation adapters."""

from __future__ import annotations

import datetime
import logging
import math
from typing import Any, Protocol

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.cost_accounting import ReconciliationRun, UsageEvent
from app.models.model_catalog import AIModel
from app.services.secret_crypto import decrypt_secret
from app.services.usage_accounting_service import (
    create_reconciliation_run,
    extract_normalized_usage,
    finish_reconciliation_run,
    quote_usage,
    reconcile_usage_event,
)
from app.core.constants import normalize_openrouter_base_url
from app.config import get_settings
from app.services.provider_http import build_provider_client

logger = logging.getLogger("app.services.provider_reconciliation_service")


class ProviderReconciliationAdapter(Protocol):
    provider_type: str

    async def fetch_actual_cost(
        self,
        client: httpx.AsyncClient,
        *,
        connection: Connection,
        api_key: str,
        upstream_request_id: str,
        event: UsageEvent | None = None,
        db: AsyncSession | None = None,
    ) -> float | None: ...


def _finite_nonneg(value: Any) -> float | None:
    try:
        cost = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(cost) or cost < 0:
        return None
    return cost


def _extract_usd_cost(payload: Any) -> float | None:
    """Best-effort USD extraction from provider payloads."""

    if not isinstance(payload, dict):
        return None
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        data = payload
    for key in ("total_cost", "total_cost_usd", "provider_cost", "billed_cost", "cost"):
        cost = _finite_nonneg(data.get(key))
        if cost is not None:
            return cost
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in ("total_cost", "total_cost_usd", "provider_cost", "billed_cost", "cost"):
            cost = _finite_nonneg(usage.get(key))
            if cost is not None:
                return cost
    elif usage is not None and not isinstance(usage, dict):
        return _finite_nonneg(usage)
    return None


_openrouter_api_base = normalize_openrouter_base_url


def _openai_api_base(base_url: str | None) -> str:
    base = (base_url or "https://api.openai.com/v1").strip().rstrip("/")
    if base.endswith("/v1"):
        return base
    if base in {"https://api.openai.com", "http://api.openai.com"}:
        return f"{base}/v1"
    return base


class OpenRouterReconciliationAdapter:
    provider_type = "openrouter"

    async def fetch_actual_cost(
        self,
        client: httpx.AsyncClient,
        *,
        connection: Connection,
        api_key: str,
        upstream_request_id: str,
        event: UsageEvent | None = None,
        db: AsyncSession | None = None,
    ) -> float | None:
        del event, db
        response = await client.get(
            f"{_openrouter_api_base(connection.base_url)}/generation",
            params={"id": upstream_request_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _extract_usd_cost(response.json())


class OpenAIReconciliationAdapter:
    """Reconcile OpenAI Responses by provider USD when present, else catalog quote.

    OpenAI does not expose a per-generation invoice endpoint like OpenRouter.
    For ``resp_*`` IDs we retrieve the stored Responses object. If that payload
    includes a USD charge we use it; otherwise we re-quote the provider's
    authoritative token usage against the local model catalog.
    Chat Completions IDs (``chatcmpl-*``) cannot be retrieved and stay unmatched.
    """

    provider_type = "openai"

    async def fetch_actual_cost(
        self,
        client: httpx.AsyncClient,
        *,
        connection: Connection,
        api_key: str,
        upstream_request_id: str,
        event: UsageEvent | None = None,
        db: AsyncSession | None = None,
    ) -> float | None:
        request_id = (upstream_request_id or "").strip()
        if not request_id.startswith("resp_"):
            return None

        response = await client.get(
            f"{_openai_api_base(connection.base_url)}/responses/{request_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None

        direct_cost = _extract_usd_cost(payload)
        if direct_cost is not None:
            return direct_cost

        if event is None or db is None:
            return None

        usage = extract_normalized_usage(payload, provider_type="openai")
        if not (usage.prompt_tokens or usage.completion_tokens or usage.metered_quantity):
            return None

        model_id = (event.model_id or "").strip() or None
        ai_model = None
        if model_id:
            ai_model = (await db.execute(select(AIModel).where(AIModel.external_id == model_id))).scalar_one_or_none()
            if ai_model is None and "/" in model_id:
                bare = model_id.split("/", 1)[-1]
                ai_model = (await db.execute(select(AIModel).where(AIModel.external_id == bare))).scalar_one_or_none()

        quote = quote_usage(
            usage,
            ai_model=ai_model,
            provider_type="openai",
            service_type=(event.service_type or "chat"),
            model_id=model_id,
            quantity=event.quantity,
            unit=event.unit,
        )
        if quote.final_cost_usd is None:
            return None
        return float(quote.final_cost_usd)


_ADAPTERS: dict[str, ProviderReconciliationAdapter] = {
    "openrouter": OpenRouterReconciliationAdapter(),
    "openai": OpenAIReconciliationAdapter(),
}


def automatic_reconciliation_providers() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


async def reconcile_connection_costs(
    db: AsyncSession,
    connection: Connection,
    *,
    limit: int = 50,
) -> ReconciliationRun | None:
    """Reconcile pending events for one connection with its provider adapter."""

    provider = (connection.provider_type or "").strip().lower()
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise ValueError(f"No automatic reconciliation adapter is registered for {provider or 'unknown'}")
    now = datetime.datetime.utcnow()
    retry_before = now - datetime.timedelta(hours=1)
    events = (
        (
            await db.execute(
                select(UsageEvent)
                .where(
                    UsageEvent.connection_id == connection.id,
                    UsageEvent.provider_type == provider,
                    UsageEvent.upstream_request_id.isnot(None),
                    UsageEvent.status.in_(("succeeded", "failed")),
                    UsageEvent.cost_confidence.in_(("calculated", "estimated", "unknown")),
                    UsageEvent.reconciliation_attempts < 5,
                    or_(
                        UsageEvent.last_reconciliation_attempt_at.is_(None),
                        UsageEvent.last_reconciliation_attempt_at <= retry_before,
                    ),
                )
                .order_by(UsageEvent.completed_at, UsageEvent.started_at)
                .limit(max(1, min(500, int(limit))))
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if not events:
        return None

    run = await create_reconciliation_run(
        db,
        provider_type=provider,
        source="provider_usage_api",
        connection_id=connection.id,
        raw_summary={"candidate_events": len(events)},
    )
    claim_time = datetime.datetime.utcnow()
    claimed_event_ids: list[str] = []
    for event in events:
        event.reconciliation_attempts = int(event.reconciliation_attempts or 0) + 1
        event.last_reconciliation_attempt_at = claim_time
        claimed_event_ids.append(event.id)
    await db.commit()

    api_key = decrypt_secret(connection.api_key_encrypted)
    unmatched = 0
    error_message: str | None = None
    # Its own client, not the shared one: this keeps a short lookup budget and
    # is closed when the batch ends. A scalar httpx timeout would have set the
    # connect budget to the lookup budget too, so a stalled handshake held this
    # loop for the full 20s with no second attempt.
    async with build_provider_client(read_timeout=get_settings().provider_lookup_timeout_seconds) as client:
        for event_id in claimed_event_ids:
            event = await db.get(UsageEvent, event_id)
            if event is None:
                unmatched += 1
                continue
            try:
                actual_cost = await adapter.fetch_actual_cost(
                    client,
                    connection=connection,
                    api_key=api_key,
                    upstream_request_id=str(event.upstream_request_id),
                    event=event,
                    db=db,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403, 429}:
                    error_message = f"Provider reconciliation stopped with HTTP {exc.response.status_code}"
                    break
                logger.warning(
                    "Provider reconciliation HTTP error provider=%s event=%s status=%s",
                    provider,
                    event.id,
                    exc.response.status_code,
                )
                unmatched += 1
                continue
            except httpx.HTTPError as exc:
                error_message = f"Provider reconciliation transport error: {exc}"
                break
            except Exception:
                logger.exception(
                    "Provider reconciliation failed provider=%s event=%s",
                    provider,
                    event.id,
                )
                unmatched += 1
                continue

            if actual_cost is None:
                unmatched += 1
                continue
            await reconcile_usage_event(
                db,
                event_id=event.id,
                actual_cost_usd=actual_cost,
                reconciliation_run_id=run.id,
            )

    await finish_reconciliation_run(
        db,
        run,
        error_message=error_message,
        unmatched_event_count=unmatched,
    )
    return run
