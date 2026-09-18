"""Settle one chat turn after the provider stream has ended (Phase 4.1).

This is the body of the ``finally`` block that used to live inside
``proxy_service.stream_chat``: release the Code Interpreter capacity lease,
finalize the persisted assistant message, record memory usage, write the
RequestLog + ledger + budget settlement (in its own session, with retries),
finalize the Agent run and build the ``alpha_router`` metadata trailer.

It never yields. The caller wraps it in ``anyio.CancelScope(shield=True)``
so a client disconnect cannot interrupt settlement, and yields the trailer /
``[DONE]`` frames afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.services.client_ip import resolve_client_ip
from app.services.agent_run_service import finalize_agent_run
from app.services.budget_notice_service import budget_notice_after_settlement
from app.services.agent_chat_integration_service import PreparedAgentTurn
from app.services.agent_runtime_service import AgentCompletionReview
from app.services.code_interpreter_capacity_service import CapacityPermit, release_code_interpreter_turn
from app.services.observability import increment
from app.services.usage_accounting_service import PendingUsageEvent
from app.services.usage_logging_service import log_usage
from app.services.user_memory_service import record_memory_usage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnOutcome:
    """What the stream produced, as known when it ended (success or not)."""

    success: bool
    error_message: str | None
    was_cancelled: bool
    client_disconnected: bool
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_cost: float
    usage_events: list[PendingUsageEvent]
    elapsed_ms: float
    agent_review: AgentCompletionReview | None = None
    agent_output_displayed: bool = False
    #: Classification of the failure (see failure_details), for the API Logs filter.
    error_code: str | None = None
    #: Upstream HTTP status, when the provider answered with one.
    http_status: int | None = None


@dataclass(slots=True)
class TurnIdentity:
    """Who, what and where — constant for the whole turn."""

    request: Request
    body: dict
    user_id: int | None
    username: str
    model: str
    prompt_lang: str
    source: str
    alpha_router_api_key_id: int | None
    user_api_key_id: int | None
    client_app: str | None
    project_id_for_billing: str | None
    stream_reservation_id: str | None
    agent_turn: PreparedAgentTurn | None = None
    injected_memory_ids: list[str] = field(default_factory=list)
    project_memory_project_id: str | None = None
    injected_project_memory_ids: list[str] = field(default_factory=list)


def agent_identity_metadata(agent_turn: PreparedAgentTurn) -> dict[str, object]:
    plan = agent_turn.plan
    target = getattr(plan, "target", None)
    agent = getattr(target, "agent", None)
    version = getattr(target, "version", None)
    return {
        "agent_id": getattr(plan, "selected_agent_id", None) or getattr(agent, "id", None),
        "agent_version_id": getattr(plan, "selected_agent_version_id", None) or getattr(version, "id", None),
        "agent_name": getattr(agent, "name", None),
    }


def agent_citation_metadata(
    agent_turn: PreparedAgentTurn,
    review: AgentCompletionReview | None,
) -> list[dict[str, object]]:
    verification = review.citation_verification if review is not None else None
    if (
        not getattr(agent_turn.options, "include_citations", True)
        or verification is None
        or not verification.valid
        or agent_turn.plan.retrieval is None
    ):
        return []
    by_id = {citation.citation_id: citation for citation in agent_turn.plan.retrieval.context.citations}
    payloads: list[dict[str, object]] = []
    for citation_id in verification.cited_ids:
        citation = by_id.get(citation_id)
        if citation is None:
            continue
        payloads.append(
            {
                "citation_id": citation.citation_id,
                "marker": citation.marker,
                "title": citation.title,
                "file_name": citation.file_name,
                "mime_type": citation.mime_type,
                "page_number": citation.page_number,
                "section": citation.section,
                "authority": citation.authority,
                "effective_from": citation.effective_from,
                "effective_to": citation.effective_to,
                "document_version_id": citation.document_version_id,
            }
        )
    return payloads


async def release_capacity(
    permit: CapacityPermit | None,
    heartbeat_task: asyncio.Task | None,
) -> None:
    """Stop the heartbeat and give the Code Interpreter turn permit back."""
    if heartbeat_task is not None:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
    if permit is None:
        return
    try:
        await release_code_interpreter_turn(permit)
    except Exception:
        logger.exception("Failed to release Code Interpreter capacity permit")


async def _record_memory_usage(identity: TurnIdentity) -> None:
    if identity.user_id and identity.injected_memory_ids:
        try:
            async with AsyncSessionLocal() as mem_db:
                await record_memory_usage(mem_db, int(identity.user_id), identity.injected_memory_ids)
                await mem_db.commit()
        except Exception:
            logger.exception("Failed to record memory usage")
    if identity.project_memory_project_id and identity.injected_project_memory_ids:
        try:
            from app.services.project_memory_service import record_project_memory_usage

            async with AsyncSessionLocal() as mem_db:
                await record_project_memory_usage(
                    mem_db,
                    identity.project_memory_project_id,
                    identity.injected_project_memory_ids,
                )
                await mem_db.commit()
        except Exception:
            logger.exception("Failed to record project memory usage")


async def _persist_stream_usage(identity: TurnIdentity, outcome: TurnOutcome) -> int | None:
    # Usage/cost accounting is logged in an INDEPENDENT session so that a
    # persister rollback (which reverts the assistant message content)
    # cannot also drop the RequestLog / budget increment — otherwise a user
    # could be charged for a response whose stored message was lost, or
    # conversely get a response for free.
    accounting_key = (
        f"chat:{identity.stream_reservation_id}"
        if identity.stream_reservation_id
        else (f"chat:{outcome.usage_events[0].idempotency_key}" if outcome.usage_events else None)
    )
    for attempt in range(3):
        try:
            async with AsyncSessionLocal() as log_db:
                log_id = await log_usage(
                    log_db,
                    user_id=identity.user_id,
                    username=identity.username,
                    model_id=identity.model,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    cached_tokens=outcome.cached_tokens,
                    total_cost_usd=outcome.total_cost,
                    response_time_ms=outcome.elapsed_ms,
                    prompt_language=identity.prompt_lang,
                    source_ip=resolve_client_ip(identity.request),
                    source=identity.source,
                    success=outcome.success,
                    error_message=outcome.error_message,
                    alpha_router_api_key_id=identity.alpha_router_api_key_id,
                    user_api_key_id=identity.user_api_key_id,
                    client_app=identity.client_app,
                    budget_reservation_id=identity.stream_reservation_id,
                    usage_events=outcome.usage_events,
                    operation_type="chat",
                    operation_idempotency_key=accounting_key,
                    project_id=identity.project_id_for_billing,
                    error_code=outcome.error_code,
                    http_status=outcome.http_status,
                )
                chat_session_id = str(identity.body.get("chat_session_id") or "").strip()
                assistant_cid = str(identity.body.get("assistant_client_message_id") or "").strip()
                if (
                    log_id
                    and outcome.success
                    and identity.source == "alpha_router_chat"
                    and identity.user_id
                    and chat_session_id
                ):
                    from app.services.user_chat_storage_service import attach_request_log_id_to_chat_message

                    await attach_request_log_id_to_chat_message(
                        log_db,
                        int(identity.user_id),
                        chat_session_id,
                        int(log_id),
                        client_message_id=assistant_cid or None,
                    )
                await log_db.commit()
            return log_id
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            # The hold stays "held" until TTL: the one signal ops has that money is stuck.
            increment("budget_hold_leak")
            logger.exception("Chat usage settlement failed after retries; reservation remains held for recovery")
    return None


def _agent_terminal_status(outcome: TurnOutcome) -> str:
    if outcome.was_cancelled or outcome.client_disconnected:
        return "cancelled"
    if not outcome.success:
        return "failed"
    if outcome.agent_review is not None and outcome.agent_review.status == "blocked":
        return "blocked"
    return "succeeded"


async def _persist_agent_finalization(
    agent_turn: PreparedAgentTurn,
    outcome: TurnOutcome,
    *,
    terminal_status: str,
    request_log_id: int | None,
) -> None:
    review = outcome.agent_review
    if terminal_status == "blocked" and review is not None:
        error_code: str | None = review.reason_code
    elif terminal_status == "cancelled":
        error_code = "client_disconnected"
    elif terminal_status == "failed":
        error_code = "provider_error"
    else:
        error_code = None
    for attempt in range(3):
        try:
            async with AsyncSessionLocal() as agent_db:
                await finalize_agent_run(
                    agent_db,
                    run_id=agent_turn.run_id,
                    status=terminal_status or "failed",
                    review=review,
                    request_log_id=request_log_id,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    cached_tokens=outcome.cached_tokens,
                    total_cost_usd=outcome.total_cost,
                    provider_latency_ms=max(0, int(outcome.elapsed_ms)),
                    total_latency_ms=max(0, int(outcome.elapsed_ms + agent_turn.plan.total_planning_latency_ms)),
                    output_displayed=outcome.agent_output_displayed,
                    error_code=error_code,
                    error_message=(outcome.error_message if terminal_status in {"failed", "cancelled"} else None),
                )
                await agent_db.commit()
            return
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            logger.exception("Agent run finalization failed after retries run=%s", agent_turn.run_id)


async def settle_turn(
    identity: TurnIdentity,
    outcome: TurnOutcome,
    *,
    db: AsyncSession,
    persister: Any,
    capacity_permit: CapacityPermit | None,
    capacity_heartbeat_task: asyncio.Task | None,
) -> dict[str, object]:
    """Run every post-stream side effect and return the metadata trailer."""
    await release_capacity(capacity_permit, capacity_heartbeat_task)
    if persister:
        try:
            await persister.finalize(success=outcome.success, error_message=outcome.error_message)
        except Exception:  # noqa: BLE001 -- session is rolled back and the caller continues without the write
            await db.rollback()
    await _record_memory_usage(identity)
    request_log_id = await _persist_stream_usage(identity, outcome)

    response_metadata: dict[str, object] = {}
    if not outcome.was_cancelled and outcome.success and request_log_id and identity.source == "alpha_router_chat":
        response_metadata["request_log_id"] = int(request_log_id)

    # Budget warnings belong to the person sitting in front of the chat UI.
    # Gateway API-key callers bill against a different pool and would only be
    # handed an unexpected field in their response body, so the same gate as
    # request_log_id applies. Reading here does not consume the notice: it is
    # marked shown only when the browser acknowledges it, which is what makes a
    # dropped trailing frame harmless.
    if not outcome.was_cancelled and identity.source == "alpha_router_chat":
        budget_notice = await budget_notice_after_settlement(identity.user_id)
        if budget_notice:
            response_metadata["budget_notice"] = budget_notice

    agent_turn = identity.agent_turn
    if agent_turn is not None:
        terminal_status = _agent_terminal_status(outcome)
        await _persist_agent_finalization(
            agent_turn, outcome, terminal_status=terminal_status, request_log_id=request_log_id
        )
        if not outcome.was_cancelled:
            response_metadata.update(
                {
                    "agent_run_id": agent_turn.run_id,
                    **agent_identity_metadata(agent_turn),
                    "agent_status": terminal_status,
                    "routing_outcome": agent_turn.plan.routing_outcome,
                }
            )
            if outcome.agent_review is not None:
                response_metadata["completion_reason_code"] = outcome.agent_review.reason_code
                citations = agent_citation_metadata(agent_turn, outcome.agent_review)
                if citations:
                    response_metadata["citations"] = citations
    return response_metadata
