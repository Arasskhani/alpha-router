"""
OpenAI-compatible proxy with async streaming, cancellation, and prompt caching.
Costs are taken from provider usage objects — never adjusted by Alpharouter.
"""

import asyncio
import datetime
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx
import litellm
from fastapi import HTTPException, Request
from litellm import acompletion, aembedding
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import effective_redis_url, get_settings
from app.core.constants import normalize_openrouter_base_url
from app.core.language_detect import detect_prompt_language
from app.database import AsyncSessionLocal
from app.models.chat import ChatSession
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.agent_chat_integration_service import (
    AgentRequestError,
    PreparedAgentTurn,
    parse_agent_request,
    prepare_agent_turn,
)
from app.services.agent_policy_service import AgentPolicyValidationError
from app.services.agent_routing_service import (
    AgentAccessDenied,
    AgentNotFound,
    AgentRoutingError,
)
from app.services.agent_runtime_service import (
    AgentCompletionReview,
    AgentModelUnavailable,
    AgentRuntimeDenied,
    AgentRuntimeError,
    AgentRuntimeUnavailable,
    finalize_agent_completion,
)
from app.services.agent_tool_registry_service import (
    ToolPolicyDenied,
    ToolRegistryError,
)
from app.services.budget_reservation_service import (
    reservation_hold_usd,
    reservation_key,
    reserve,
)
from app.services.chat_tool_access_service import assert_tools_permitted
from app.services.chat_tool_registry import requested_tool_keys
from app.services.chat_tools_service import (
    parse_tools_config,
)
from app.services.chat_turn_context import (
    NonGeneratingReply,
    _adaptive_openrouter_extra_body,
    build_turn_context,
)
from app.services.code_interpreter_capacity_service import (
    CapacityPermit,
    acquire_code_interpreter_turn,
    release_code_interpreter_turn,
    subject_for_api_key,
    subject_for_system,
    subject_for_user,
)
from app.services.code_interpreter_service import (
    DEFAULT_MAX_WORKSPACE_FILES,
    DEFAULT_MAX_WORKSPACE_TOTAL_BYTES,
    MAX_CODE_ITERATIONS,
    SandboxArtifact,
    SandboxExecutionResult,
    WorkspaceFiles,
    WorkspaceLimitError,
    code_interpreter_nudge_message,
    extract_last_python_block,
    hydrate_binary_workspace_files,
    run_python_sandbox,
    workspace_files_from_messages,
)
from app.services.code_interpreter_turn import (
    CodeInterpreterLoop,
    describe_code_step,
    run_sandbox_until_stopped,
)
from app.services.failure_details import describe_failure, failure_message
from app.services.llm_providers import (
    litellm_model_for_provider,
    normalize_model_id,
    resolve_litellm_provider,
)
from app.services.model_resolution_service import (  # noqa: F401 -- re-exported for api.chat / api.gateway
    assert_model_supports_text_chat,
    resolve_model_and_key,
)
from app.services.model_tool_compatibility_service import (
    assert_code_interpreter_model_available,
    classify_failure_reason,
    is_auto_router_model_id,
    record_compatibility_result,
)
from app.services.private_mode_service import (
    PrivateModePersistenceError,
    resolve_private_mode,
)
from app.services.prompt_cache_service import apply_prompt_cache_breakpoints
from app.services.provider_http import build_provider_client
from app.services.provider_stream import NonStreamRetry, ProviderAttempt, estimate_tokens
from app.services.provider_utils import (  # noqa: F401 -- re-exported under the historical names
    _apply_litellm_provider_kwargs,
    _close_upstream_stream,
    _compute_token_cost_usd,
    _extract_non_stream_content,
    _extract_prompt_text,
    _format_provider_error,
    _merge_stream_usage,
    _sanitize_cost_usd,
    _serialize_stream_chunk,
    _should_retry_non_stream,
    _sse_delta_chunk,
    _sse_error_frame,
    _usable_cost_per_1k,
    _usage_event_model_id,
    _usage_from_chunk,
    _usage_from_response,
    _usage_from_stream_wrapper,
    _usage_from_usage_obj,
)
from app.services.rate_limit import check_generation_rate_limit, generation_subject
from app.services.storage_service import media_public_url, store_generated_blob
from app.services.turn_settlement import (
    TurnIdentity,
    TurnOutcome,
    settle_turn,
)
from app.services.turn_settlement import (
    agent_citation_metadata as _agent_citation_metadata,
)
from app.services.usage_accounting_service import (
    PendingUsageEvent,
    capture_usage_event,
)
from app.services.usage_logging_service import (  # noqa: F401 -- re-exported for api.chat / api.gateway
    log_usage,
    reserve_auxiliary_llm_usage,
    settle_auxiliary_usage,
)

logger = logging.getLogger("app.services.proxy_service")

# Backward-compatible aliases for internal modules that import from proxy_service.
_litellm_model_for_provider = litellm_model_for_provider
_resolve_litellm_provider = resolve_litellm_provider

settings = get_settings()

#: How much new text to accumulate before re-pricing the turn in flight.
#: Re-pricing every chunk would run the tokenizer thousands of times per turn;
#: a few hundred characters catches an overrun while it is still small.
BUDGET_RECHECK_CHARS = 400


def turn_cost_exceeds_hold(
    *,
    ai_model,
    provider_type: str | None,
    model: str,
    messages,
    completion_text: str,
    hold_usd: float | None,
) -> bool:
    """Has this turn already cost more than was reserved for it?

    The hold is an estimate. For chat it is sized from ``max_tokens``, which
    reaches ``completion_kwargs`` only on the agent path - so an ordinary turn
    asks the provider for an unbounded completion against a hold that assumed a
    bounded one. Budget is otherwise checked only at admission, so the overrun
    is charged in full and only the *next* request is refused.

    There is no honest way to fix that with a better estimate: the catalog
    carries ``context_length`` and no ``max_output_tokens``, so there is no
    number to send. Watching the running cost is the control that matches the
    problem.

    Returns False when anything is unknown - an unpriced model, a tokenizer
    that could not count, no hold at all. A turn is never stopped on a guess.
    """

    if hold_usd is None or hold_usd <= 0 or ai_model is None:
        return False
    est_prompt, est_completion = estimate_tokens(
        provider_type=provider_type,
        model=model,
        messages=messages,
        completion_text=completion_text,
    )
    if not est_completion:
        return False
    running = _compute_token_cost_usd(
        ai_model,
        prompt_tokens=est_prompt,
        completion_tokens=est_completion,
        model_id=model,
        messages=messages,
        completion_text=completion_text,
        provider_type=provider_type,
    )
    return running > hold_usd


BUDGET_EXCEEDED_MESSAGE = (
    "This reply was stopped because it passed the budget reserved for it. "
    "The part already generated has been billed. Try a shorter request, or ask an administrator to raise your budget."
)

STREAM_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@dataclass
class ResolvedStreamContext:
    ai_model: AIModel | None
    api_key: str | None
    base_url: str
    provider_type: str
    model_id: str
    budget_reservation_id: str | None = None
    #: What the hold is worth. The stream watches its own running cost against
    #: this: the hold is an estimate, and a chat turn's completion length is not
    #: knowable in advance, so without a check the turn can outgrow what was
    #: reserved and the overspend is only noticed by the *next* request.
    budget_hold_usd: float | None = None
    code_interpreter_workspace_files: WorkspaceFiles | None = None
    #: Why an attachment is missing from the workspace (too large, not this
    #: user's); surfaced to the model with the inventory.
    code_interpreter_workspace_notes: list[str] = field(default_factory=list)
    code_interpreter_capacity_permit: CapacityPermit | None = None
    agent_turn: PreparedAgentTurn | None = None


@dataclass(frozen=True)
class StoredCodeArtifact:
    asset_id: int
    name: str
    url: str


async def _persist_code_interpreter_artifacts(
    artifacts: tuple[SandboxArtifact, ...],
    *,
    user_id: int,
    username: str,
    chat_session_id: str,
    model_id: str,
    source_prompt: str,
) -> list[StoredCodeArtifact]:
    """Store validated sandbox output in the owner's existing Media library."""
    async with AsyncSessionLocal() as media_db:
        session = (
            await media_db.execute(
                select(ChatSession).where(
                    ChatSession.id == chat_session_id,
                    ChatSession.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if session is None:
            raise ValueError("Chat session is unavailable for artifact storage")

        stored: list[StoredCodeArtifact] = []
        for artifact in artifacts:
            asset = await store_generated_blob(
                media_db,
                user_id=user_id,
                username=username,
                kind="document",
                blob=artifact.content,
                mime=artifact.mime_type,
                source_model=model_id,
                source_prompt=source_prompt[:4000] or "Code interpreter output",
                chat_session_id=chat_session_id,
                file_name_hint=artifact.name,
                metadata={
                    "source": "code_interpreter",
                    "sha256": artifact.sha256,
                },
            )
            stored.append(
                StoredCodeArtifact(
                    asset_id=asset.id,
                    name=asset.file_name,
                    url=media_public_url(asset.id),
                )
            )
        await media_db.commit()
        return stored


def _artifact_links_markdown(artifacts: list[StoredCodeArtifact]) -> str:
    if not artifacts:
        return ""
    links = "\n".join(f"- [{item.name}]({item.url})" for item in artifacts)
    return f"\n\n---\n**Generated files:**\n{links}\n\n"


# Backward-compatible alias — keeps OpenRouter ``~`` alias IDs intact.
_normalize_model_id = normalize_model_id


def configure_litellm_cache() -> None:
    litellm.suppress_debug_info = True
    redis_url = effective_redis_url()
    if not redis_url:
        litellm.cache = litellm.Cache()
        return
    try:
        import redis  # noqa: F401

        litellm.cache = litellm.Cache(type="redis", url=redis_url)
    except Exception:  # noqa: BLE001 -- falls back to a safe default value
        litellm.cache = litellm.Cache()


async def _openrouter_generation_outcome(
    *,
    base_url: str,
    api_key: str,
    upstream_request_id: str | None,
) -> dict | None:
    request_id = (upstream_request_id or "").strip()
    if not request_id:
        return None
    base = normalize_openrouter_base_url(base_url)
    # Its own client (short lookup budget, closed with the loop) but the same
    # connection policy as every other provider call: a scalar httpx timeout
    # would set the connect budget to the lookup budget as well, so a stalled
    # handshake blocked each of the four attempts below for the full 20s.
    async with build_provider_client(read_timeout=get_settings().provider_lookup_timeout_seconds) as client:
        # The generation record becomes queryable a moment after the stream ends,
        # so a single fast retry is not enough to resolve the routed model.
        for delay in (0.0, 0.6, 1.2, 2.4):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await client.get(
                    f"{base}/generation",
                    params={"id": request_id},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                return None
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                return None
            return {
                "model": data.get("model"),
                "provider_name": data.get("provider_name"),
                "finish_reason": data.get("finish_reason"),
                "native_finish_reason": data.get("native_finish_reason"),
            }
    return None


async def _record_runtime_compatibility(
    *,
    ai_model: AIModel,
    external_model_id: str,
    success: bool,
    reason_code: str | None = None,
    detail: str | None = None,
    upstream_request_id: str | None = None,
    evidence: dict | None = None,
) -> None:
    connection_id = getattr(ai_model, "connection_id", None)
    if connection_id is None:
        return
    target = (external_model_id or ai_model.external_id).strip()
    if target.startswith("openrouter/"):
        target = target.removeprefix("openrouter/")
    if not target or is_auto_router_model_id(target):
        # Evidence keyed on a router alias cannot constrain routing and would
        # score the alias itself, so it is dropped instead of stored.
        return
    async with AsyncSessionLocal() as compatibility_db:
        catalog_model = (
            await compatibility_db.execute(
                select(AIModel).where(
                    AIModel.connection_id == int(connection_id),
                    AIModel.external_id == target,
                )
            )
        ).scalar_one_or_none()
        await record_compatibility_result(
            compatibility_db,
            connection_id=int(connection_id),
            external_model_id=target,
            model_id=catalog_model.id if catalog_model is not None else None,
            success=success,
            source="runtime",
            reason_code=reason_code,
            detail=detail,
            requested_model_id=ai_model.external_id,
            upstream_request_id=upstream_request_id,
            evidence=evidence,
        )
        await compatibility_db.commit()


"""Strong refs for fire-and-forget bookkeeping so tasks are not GC'd early."""
_background_compatibility_tasks: set[asyncio.Task] = set()


def _spawn_compatibility_task(coro) -> None:
    task = asyncio.create_task(coro)
    _background_compatibility_tasks.add(task)
    task.add_done_callback(_background_compatibility_tasks.discard)


async def _log_compatibility_task_errors(coro) -> None:
    try:
        await coro
    except Exception:
        logger.exception("Failed to record Code Interpreter compatibility result")


async def _record_code_interpreter_success(
    *,
    ai_model: AIModel,
    provider: str,
    base_url: str,
    api_key: str,
    event: PendingUsageEvent | None,
    observed_model_ids: set[str],
) -> None:
    """Credit the concrete model that ran the flow, not the router alias."""
    targets = {m for m in observed_model_ids if m and not is_auto_router_model_id(m)}
    if not targets:
        # OpenRouter streams the requested alias back, so the real model has to
        # be resolved before a router success can be credited to anything.
        target = _usage_event_model_id(event)
        if provider == "openrouter" and (not target or is_auto_router_model_id(target)):
            outcome = await _openrouter_generation_outcome(
                base_url=base_url,
                api_key=api_key,
                upstream_request_id=(event.usage.upstream_request_id if event is not None else None),
            )
            selected = outcome.get("model") if outcome else None
            if selected:
                target = str(selected)
        if not target or is_auto_router_model_id(target):
            target = ai_model.external_id
        targets = {target}
    for observed in targets:
        await _record_runtime_compatibility(
            ai_model=ai_model,
            external_model_id=observed,
            success=True,
            upstream_request_id=(event.usage.upstream_request_id if event is not None else None),
            evidence={"source_request_model": ai_model.external_id},
        )


async def _record_code_interpreter_failure(
    *,
    ai_model: AIModel,
    provider: str,
    base_url: str,
    api_key: str,
    event: PendingUsageEvent | None,
    detail: str,
    reason_code_override: str | None = None,
) -> str:
    target = _usage_event_model_id(event)
    evidence: dict | None = None
    upstream_id = event.usage.upstream_request_id if event is not None else None
    if provider == "openrouter" and (not target or is_auto_router_model_id(target)):
        evidence = await _openrouter_generation_outcome(
            base_url=base_url,
            api_key=api_key,
            upstream_request_id=upstream_id,
        )
        selected = evidence.get("model") if evidence else None
        if selected:
            target = str(selected)
    native_reason = str(evidence.get("native_finish_reason") or evidence.get("finish_reason") or "") if evidence else ""
    reason_code = reason_code_override or classify_failure_reason(f"{detail} {native_reason}")
    await _record_runtime_compatibility(
        ai_model=ai_model,
        external_model_id=target or ai_model.external_id,
        success=False,
        reason_code=reason_code,
        detail=(native_reason or detail)[:1000],
        upstream_request_id=upstream_id,
        evidence=evidence,
    )
    return reason_code


async def _code_interpreter_capacity_subject(
    db: AsyncSession,
    *,
    user_id: int | None,
    alpha_router_api_key_id: int | None,
    source: str | None,
) -> str:
    """Per-subject capacity is per *person*: an owner with several gateway keys
    used to get one share per key and could crowd out everyone else."""
    if alpha_router_api_key_id is not None:
        from app.models.api_key import AlphaRouterApiKey

        key = await db.get(AlphaRouterApiKey, alpha_router_api_key_id)
        owner_id = getattr(key, "owner_user_id", None)
        if owner_id is not None:
            return subject_for_user(int(owner_id))
        return subject_for_api_key(alpha_router_api_key_id)
    if user_id is not None:
        return subject_for_user(user_id)
    return subject_for_system(source or "gateway")


def _code_interpreter_capacity_lease_id(body: dict, subject: str) -> str | None:
    request_key = body.get("_idempotency_key") or body.get("assistant_client_message_id")
    if not request_key:
        return None
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"alpharouter:code-interpreter:{subject}:{request_key}",
        )
    )


async def preflight_stream_chat(  # noqa: C901 -- Phase 4 split; complexity must not grow
    db: AsyncSession,
    body: dict,
    *,
    user_id: int | None,
    skip_budget: bool,
    alpha_router_api_key_id: int | None = None,
    operation: str = "chat",
    source: str | None = None,
    client_app: str | None = None,
) -> ResolvedStreamContext:
    """Validate budget/key/model while the request DB session is still open."""
    from app.services.api_key_connection_policy import allowed_connection_ids_for_key
    from app.services.api_key_model_policy import allowed_model_ids_for_key
    from app.services.chat_channel_guard import assert_session_allows_model_generation
    from app.services.model_access_service import (
        resolve_access_subject,
        user_can_access_model,
    )
    from app.services.resource_access_service import resolve_resource_access_subject

    await assert_session_allows_model_generation(db, str(body.get("chat_session_id") or "").strip() or None)

    # Before the model lookup and the budget hold, so a runaway client is turned
    # away cheaply. Chat completions and the OpenAI-compatible gateway both land
    # here, and neither had any limit: a leaked key was bounded only by the
    # monthly budget, which is discovered after the money is gone.
    if operation != "embedding":
        await check_generation_rate_limit(
            "chat",
            generation_subject(user_id=user_id, api_key_id=alpha_router_api_key_id),
            settings.generation_rate_limit_per_min,
        )

    agent_turn: PreparedAgentTurn | None = None
    try:
        private_mode = False
        if operation == "chat":
            private_mode = (
                await resolve_private_mode(
                    db,
                    body,
                    user_id=user_id,
                    source=source or "unknown",
                )
            ).effective
        agent_options = parse_agent_request(body) if operation == "chat" else None
        if agent_options is not None and not settings.agents_platform_enabled:
            raise HTTPException(status_code=400, detail="The Agent platform is not enabled on this installation")
        if agent_options is not None:
            agent_turn = await prepare_agent_turn(
                db,
                body=body,
                options=agent_options,
                user_id=user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                source=source or "unknown",
                client_app=client_app,
                private_mode=private_mode,
            )
    except PrivateModePersistenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AgentAccessDenied, AgentNotFound) as exc:
        raise HTTPException(status_code=404, detail="Agent not available") from exc
    except (AgentRoutingError, ToolRegistryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AgentRuntimeDenied, ToolPolicyDenied) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (AgentModelUnavailable, AgentRuntimeUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AgentPolicyValidationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Published Agent policy is invalid",
        ) from exc
    except AgentRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if agent_turn is not None and agent_turn.plan.status != "ready":
        return ResolvedStreamContext(
            ai_model=None,
            api_key=None,
            base_url="",
            provider_type="",
            model_id="",
            agent_turn=agent_turn,
        )

    selected_model = (
        f"model::{agent_turn.plan.model.id}"
        if agent_turn is not None and agent_turn.plan.model is not None
        else body.get("model")
    )
    if agent_turn is not None:
        body["model"] = selected_model
        if agent_turn.plan.policies is not None:
            body["max_tokens"] = agent_turn.plan.policies.model.max_output_tokens
    allowed_connection_ids = await allowed_connection_ids_for_key(db, alpha_router_api_key_id)
    allowed_model_ids = await allowed_model_ids_for_key(db, alpha_router_api_key_id)
    ai_model, api_key, base_url, provider_type = await resolve_model_and_key(
        db,
        selected_model,
        allowed_connection_ids=allowed_connection_ids,
        allowed_model_ids=allowed_model_ids,
    )
    if not ai_model or not api_key:
        raise HTTPException(status_code=404, detail=f"Model not enabled: {selected_model}")
    assert_model_supports_text_chat(ai_model)
    subject = await resolve_access_subject(
        db,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        source=source,
    )
    if not await user_can_access_model(db, ai_model, subject):
        raise HTTPException(status_code=404, detail=f"Model not enabled: {selected_model}")
    # Both ways into a chat turn - the browser and the Gateway - come through
    # here, so this is the one place a tool has to be checked. An agent turn
    # composes its own tool set below and is not the caller's to ask for.
    requested_tools = requested_tool_keys({} if agent_turn is not None else body)
    if requested_tools:
        # Only resolved when something was actually asked for: the ACL subject
        # costs two queries and most turns use no tool at all.
        await assert_tools_permitted(
            db,
            await resolve_resource_access_subject(
                db,
                user_id=user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                source=source,
            ),
            requested_tools,
        )
    tools = parse_tools_config({} if agent_turn is not None else body)
    workspace_files: WorkspaceFiles | None = None
    workspace_notes: list[str] = []
    capacity_permit: CapacityPermit | None = None
    if tools.code_interpreter:
        await assert_code_interpreter_model_available(db, ai_model)
        from app.services.transfer_limits_service import get_transfer_limits

        transfer_limits = await get_transfer_limits(db)
        max_workspace_files = int(
            transfer_limits.get(
                "max_code_interpreter_workspace_files",
                transfer_limits.get(
                    "max_chat_attachments_count",
                    DEFAULT_MAX_WORKSPACE_FILES,
                ),
            )
        )
        max_workspace_bytes = int(
            transfer_limits.get(
                "max_code_interpreter_workspace_total_bytes",
                DEFAULT_MAX_WORKSPACE_TOTAL_BYTES,
            )
        )
        try:
            workspace_files = workspace_files_from_messages(
                list(body.get("messages") or []),
                max_files=max_workspace_files,
                max_total_bytes=max_workspace_bytes,
            )
        except WorkspaceLimitError as exc:
            raise HTTPException(status_code=413, detail=exc.api_detail()) from exc
        # Attachments without extracted text (a PSD, a ZIP) reach the sandbox as
        # bytes; reading them needs the user, so the Gateway path without one
        # keeps a text-only workspace.
        if user_id is not None:
            user = await db.get(User, user_id)
            if user is not None:
                workspace_files, workspace_notes = await hydrate_binary_workspace_files(
                    db,
                    user=user,
                    messages=list(body.get("messages") or []),
                    files=workspace_files,
                    max_files=max_workspace_files,
                    max_total_bytes=max_workspace_bytes,
                )
        capacity_subject = await _code_interpreter_capacity_subject(
            db,
            user_id=user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            source=source,
        )
        capacity_permit = await acquire_code_interpreter_turn(
            capacity_subject,
            lease_id=_code_interpreter_capacity_lease_id(body, capacity_subject),
        )
    hold = None
    try:
        if alpha_router_api_key_id or (not skip_budget and user_id):
            estimate = await reservation_hold_usd(
                db,
                service_type="embedding" if operation == "embedding" else "llm",
                ai_model=ai_model,
                provider_type=provider_type or ai_model.provider_type,
                model_id=ai_model.external_id,
                body=body,
            )
            hold = await reserve(
                db,
                user_id=None if alpha_router_api_key_id else user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                amount_usd=estimate,
                operation=operation,
                model_id=ai_model.external_id,
                idempotency_key=reservation_key(body, operation=operation),
                # Chat only: the reply length is unknown, so the hold assumes the
                # whole max_tokens budget and over-states a short answer. Embedding
                # is priced from a known input size, so it stays strict.
                cost_is_estimated=operation != "embedding",
            )
    except BaseException:
        if capacity_permit is not None:
            await asyncio.shield(release_code_interpreter_turn(capacity_permit))
        raise
    return ResolvedStreamContext(
        ai_model=ai_model,
        api_key=api_key,
        base_url=base_url or "",
        provider_type=provider_type or ai_model.provider_type or "",
        model_id=litellm_model_for_provider(ai_model.external_id, provider_type or ai_model.provider_type),
        budget_reservation_id=hold.id if hold else None,
        budget_hold_usd=float(hold.reserved_usd) if hold is not None else None,
        code_interpreter_workspace_files=workspace_files,
        code_interpreter_workspace_notes=workspace_notes,
        code_interpreter_capacity_permit=capacity_permit,
        agent_turn=agent_turn,
    )


async def stream_chat(  # noqa: C901 -- Phase 4 split; complexity must not grow
    request: Request,
    body: dict,
    *,
    user_id: int | None,
    username: str,
    source: str,
    skip_budget: bool,
    client_app: str | None = None,
    alpha_router_api_key_id: int | None = None,
    user_api_key_id: int | None = None,
    resolved: ResolvedStreamContext | None = None,
) -> AsyncIterator[bytes]:
    prompt_lang = detect_prompt_language(_extract_prompt_text(list(body.get("messages", []))))
    success = True
    error_message = None

    async with AsyncSessionLocal() as db:
        if resolved is None:
            resolved = await preflight_stream_chat(
                db,
                body,
                user_id=user_id,
                skip_budget=skip_budget,
                alpha_router_api_key_id=alpha_router_api_key_id,
                source=source,
                client_app=client_app,
            )
            try:
                await db.commit()
            except BaseException:
                permit = getattr(resolved, "code_interpreter_capacity_permit", None)
                if permit is not None:
                    await release_code_interpreter_turn(permit)
                raise

        ctx = await build_turn_context(
            db,
            body,
            resolved,
            user_id=user_id,
            username=username,
            source=source,
            skip_budget=skip_budget,
            alpha_router_api_key_id=alpha_router_api_key_id,
        )
        if isinstance(ctx, NonGeneratingReply):
            for frame in ctx.frames:
                yield frame
            return
        # The streaming loop below still works on plain locals; they are the
        # context's fields under their historical names.
        messages = ctx.messages
        current_messages = ctx.current_messages
        completion_kwargs = ctx.completion_kwargs
        tools = ctx.tools
        ai_model = ctx.ai_model
        api_key = ctx.api_key
        base_url = ctx.base_url
        provider_type = ctx.provider_type
        provider = ctx.provider
        model = ctx.model
        workspace_files = ctx.workspace_files
        lease = ctx.lease
        capacity_lost = lease.lost
        capacity_permit = lease.permit
        capacity_heartbeat_task = lease.heartbeat_task
        stream_reservation_id = lease.stream_reservation_id
        persister = ctx.persister
        agent_turn = ctx.agent_turn
        agent_resource_subject = ctx.agent_resource_subject
        project_id_for_billing = ctx.project_id_for_billing
        project_memory_project_id = ctx.project_memory_project_id
        injected_memory_ids = ctx.injected_memory_ids
        injected_project_memory_ids = ctx.injected_project_memory_ids
        budget_hold_usd = ctx.budget_hold_usd

        prompt_tokens = completion_tokens = cached_tokens = 0
        total_cost = 0.0
        collected_content = ""
        usage_events: list[PendingUsageEvent] = []
        generation_start = time.perf_counter()
        stream_end_at: float | None = None
        attempt: ProviderAttempt | None = None

        def _absorb(
            done: ProviderAttempt,
            *,
            status: str,
            error_message: str | None,
            completion: str | None,
            track_model: bool = False,
        ) -> None:
            """Book one provider attempt into the turn totals and the ledger events."""
            nonlocal prompt_tokens, completion_tokens, cached_tokens
            usage_events.append(
                done.usage_event(
                    attempt_index=len(usage_events),
                    status=status,
                    error_message=error_message,
                    completion=completion,
                )
            )
            if track_model:
                observed = _usage_event_model_id(usage_events[-1])
                if observed and not is_auto_router_model_id(observed):
                    code_loop.observed_compatibility_models.add(observed)
            prompt_tokens += done.prompt_tokens
            completion_tokens += done.completion_tokens
            cached_tokens += done.cached_tokens

        def _compute_cost() -> None:
            nonlocal total_cost, prompt_tokens, completion_tokens
            if usage_events:
                total_cost = sum(
                    float(event.quote.final_cost_usd)
                    for event in usage_events
                    if event.quote.final_cost_usd is not None
                )
                return
            msgs_for_count = completion_kwargs.get("messages", messages)
            if prompt_tokens == 0 and collected_content:
                est_prompt, est_completion = estimate_tokens(
                    provider_type=provider_type, model=model, messages=msgs_for_count, completion_text=collected_content
                )
                if est_prompt:
                    prompt_tokens, completion_tokens = est_prompt, est_completion
            total_cost = _compute_token_cost_usd(
                ai_model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_id=model,
                messages=msgs_for_count,
                completion_text=collected_content,
                provider_type=provider_type,
            )

        was_cancelled = False
        error_code: str | None = None
        http_status: int | None = None
        agent_review: AgentCompletionReview | None = None
        agent_output_displayed = False
        # Sticky for the whole request: once the user presses Stop (or the client
        # goes away), later Code Interpreter iterations must not resume work.
        client_disconnected = False
        budget_exceeded = False
        # Re-pricing every chunk would run the tokenizer thousands of times per
        # turn. Every few hundred characters is often enough to catch an overrun
        # while it is still small, and costs almost nothing.
        budget_checked_at_len = 0

        def _over_budget(text: str) -> bool:
            return turn_cost_exceeds_hold(
                ai_model=ai_model,
                provider_type=provider_type,
                model=model,
                messages=messages,
                completion_text=text,
                hold_usd=budget_hold_usd,
            )

        async def _client_stopped() -> bool:
            """Checkpoint used outside the chunk loop (around sandbox execution)."""
            nonlocal client_disconnected
            if capacity_lost.is_set():
                client_disconnected = True
                return True
            if client_disconnected:
                return True
            try:
                if await request.is_disconnected():
                    client_disconnected = True
                    return True
            except Exception:  # noqa: BLE001 -- a broken transport counts as still connected until the next chunk
                pass
            if persister:
                try:
                    if await persister.is_cancel_requested(force=True):
                        client_disconnected = True
                        return True
                except Exception:  # noqa: BLE001 -- the cancel flag is advisory; the chunk loop re-checks it
                    pass
            return False

        async def _persist_content(text: str) -> None:
            if not persister:
                return
            try:
                await persister.on_content(text)
            except Exception:  # noqa: BLE001 -- session is rolled back and the caller continues without the write
                await db.rollback()
                persister.reset_persist_state()

        async def _review_agent_output() -> None:
            """Post-generation Agent review: rewrite collected_content, persist, mark displayed."""
            nonlocal agent_review, collected_content, agent_output_displayed
            if agent_turn is None:
                return
            if agent_resource_subject is None:
                raise AgentRuntimeUnavailable("Agent authorization context is unavailable")
            agent_review = await finalize_agent_completion(
                plan=agent_turn.plan,
                output_text=collected_content,
                resource_subject=agent_resource_subject,
            )
            reviewed = agent_review.display_text if agent_review.status == "ready" else agent_review.safe_response
            collected_content = reviewed or "This Agent response could not be displayed safely."
            if persister:
                persister.set_completion_metadata(
                    {
                        "agentStatus": ("succeeded" if agent_review.status == "ready" else "blocked"),
                        "completionReasonCode": agent_review.reason_code,
                        "citations": _agent_citation_metadata(agent_turn, agent_review),
                    }
                )
                await _persist_content(collected_content)
            agent_output_displayed = True

        async def _record_ci_failure(event, detail: str, **kwargs) -> None:
            try:
                await _record_code_interpreter_failure(
                    ai_model=ai_model,
                    provider=provider,
                    base_url=base_url,
                    api_key=api_key,
                    event=event,
                    detail=detail,
                    **kwargs,
                )
            except Exception:
                logger.exception("Failed to record Code Interpreter compatibility failure")

        code_loop = CodeInterpreterLoop(max_iterations=MAX_CODE_ITERATIONS)
        try:
            while not client_disconnected:
                attempt = ProviderAttempt(
                    ai_model=ai_model,
                    provider_type=provider_type,
                    model=model,
                    completion_kwargs=completion_kwargs,
                    completion_fn=acompletion,
                )
                # Release the request session's connection before waiting on
                # the provider. Only persisted chats commit via
                # persister.prepare(); gateway, API-key and Private Mode turns
                # otherwise keep the transaction opened by the session lookups
                # above -- and with it one pooled connection and one PgBouncer
                # server slot -- for the whole stream (minutes). ~32 concurrent
                # gateway streams per worker then exhaust the pool.
                await _end_request_transaction(db)
                await attempt.start()
                async for chunk in attempt.chunks():
                    stream_end_at = time.perf_counter()
                    if capacity_lost.is_set():
                        client_disconnected = True
                    if not client_disconnected and await request.is_disconnected():
                        client_disconnected = True
                    if not client_disconnected and persister:
                        if persister.peek_cancel_requested():
                            client_disconnected = True
                        else:
                            persister.schedule_cancel_poll()
                    if client_disconnected:
                        # Stop consuming the provider stream now: every further
                        # chunk is generated (and billed upstream) for nobody.
                        # The post-loop code estimates usage for what was
                        # received so the partial turn is still settled.
                        await attempt.close()
                        break
                    delta = ProviderAttempt.delta_text(chunk)
                    if delta:
                        attempt.record_text(delta)
                        collected_content += delta
                    if (
                        budget_hold_usd is not None
                        and len(collected_content) - budget_checked_at_len >= BUDGET_RECHECK_CHARS
                    ):
                        budget_checked_at_len = len(collected_content)
                        if _over_budget(collected_content):
                            budget_exceeded = True
                            client_disconnected = True
                            await attempt.close()
                            yield _sse_error_frame(BUDGET_EXCEEDED_MESSAGE)
                            break
                    if not client_disconnected and agent_turn is None:
                        yield f"data: {_serialize_stream_chunk(chunk)}\n\n".encode()
                    # Persist after yield and without awaiting DB: token printing
                    # must not wait on commit. A partial flush after Stop would
                    # re-mark the message as streaming, so skip once cancelled.
                    if delta and persister and agent_turn is None and not client_disconnected:
                        persister.schedule_content(collected_content)

                attempt.finish()
                iteration_content = attempt.content
                empty_completion = not iteration_content.strip()
                attempt_error = "Upstream model returned an empty completion." if empty_completion else None
                _absorb(
                    attempt,
                    status="failed" if empty_completion else "succeeded",
                    error_message=attempt_error,
                    completion=iteration_content,
                    track_model=True,
                )
                active_event = usage_events[-1]
                attempt = None

                if client_disconnected:
                    break

                if empty_completion and tools.code_interpreter:
                    await _record_ci_failure(active_event, attempt_error or "Empty Code Interpreter response")
                    if provider == "openrouter" and is_auto_router_model_id(ai_model.external_id):
                        retry_extra_body = await _adaptive_openrouter_extra_body(ai_model)
                        if retry_extra_body:
                            completion_kwargs["extra_body"] = retry_extra_body

                if empty_completion and (not tools.code_interpreter or code_loop.nudge_sent or code_loop.exhausted):
                    success = False
                    error_code = "empty_completion"
                    error_message = (
                        "The upstream model returned no usable content. Retry the request or select a different model."
                    )
                    yield _sse_error_frame(error_message)
                    break

                if not tools.code_interpreter or code_loop.exhausted:
                    break

                code = extract_last_python_block(iteration_content)
                if not code:
                    if code_loop.executed:
                        # Code already ran in this turn, so an answer without a new
                        # block is the normal end of the flow: never nudge again and
                        # never score it as a compatibility failure.
                        break
                    if code_loop.nudge_sent:
                        await _record_ci_failure(
                            active_event,
                            "The model did not emit a runnable Python block after an explicit nudge.",
                            reason_code_override="no_python_block",
                        )
                        break
                    code_loop.nudge_sent = True
                    current_messages = apply_prompt_cache_breakpoints(
                        current_messages
                        + [
                            {"role": "assistant", "content": iteration_content},
                            {"role": "user", "content": code_interpreter_nudge_message(workspace_files)},
                        ]
                    )
                    completion_kwargs["messages"] = current_messages
                    continue

                # Sandbox runs can take tens of seconds, so Stop must be honored
                # both before starting and while waiting for the result.
                if await _client_stopped():
                    break
                try:
                    exec_result = await run_sandbox_until_stopped(
                        code, workspace_files, sandbox_runner=run_python_sandbox, client_stopped=_client_stopped
                    )
                except ValueError as exc:
                    exec_result = SandboxExecutionResult(output=f"Code interpreter error: {exc}", exit_code=1)
                if exec_result is None or await _client_stopped():
                    break
                if isinstance(exec_result, str):
                    exec_result = SandboxExecutionResult(output=exec_result, exit_code=0)

                if exec_result.exit_code == 0:
                    code_loop.executed = True
                    # Resolving the routed model can take a second upstream, so it
                    # is never allowed to delay the user's stream.
                    _spawn_compatibility_task(
                        _log_compatibility_task_errors(
                            _record_code_interpreter_success(
                                ai_model=ai_model,
                                provider=provider,
                                base_url=base_url,
                                api_key=api_key,
                                event=active_event,
                                observed_model_ids=set(code_loop.observed_compatibility_models),
                            )
                        )
                    )

                can_persist_artifacts = bool(
                    source == "alpha_router_chat"
                    and body.get("persist_chat")
                    and user_id
                    and body.get("chat_session_id")
                )

                async def _persist_artifacts(artifacts: Sequence[Any]) -> Sequence[Any]:
                    return await _persist_code_interpreter_artifacts(
                        tuple(artifacts),
                        user_id=int(user_id),
                        username=username,
                        chat_session_id=str(body["chat_session_id"]),
                        model_id=model,
                        source_prompt=_extract_prompt_text(messages),
                    )

                step = await describe_code_step(
                    exec_result,
                    loop=code_loop,
                    can_persist_artifacts=can_persist_artifacts,
                    persist_artifacts=_persist_artifacts,
                    artifact_links_markdown=_artifact_links_markdown,
                )
                collected_content += step.formatted
                await _persist_content(collected_content)
                if not client_disconnected:
                    yield _sse_delta_chunk(step.formatted)

                current_messages = apply_prompt_cache_breakpoints(
                    current_messages
                    + [
                        {"role": "assistant", "content": iteration_content},
                        {"role": "user", "content": step.feedback},
                    ]
                )
                completion_kwargs["messages"] = current_messages
                code_loop.iterations += 1

            _compute_cost()
            if budget_exceeded:
                # Not a provider failure and not a user cancellation: the turn
                # was stopped by us, and the log should say which.
                success = False
                error_code = "budget_exceeded"
                error_message = BUDGET_EXCEEDED_MESSAGE
            if agent_turn is not None and not client_disconnected and success:
                await _review_agent_output()
                yield _sse_delta_chunk(collected_content)
        except GeneratorExit:
            # The ASGI server closed the generator (client gone). Nothing may be
            # yielded from here on; the finally block below still settles.
            was_cancelled = True
            client_disconnected = True
            success = False
            error_code = "client_disconnected"
            error_message = "Request cancelled"
            raise
        except asyncio.CancelledError as exc:
            was_cancelled = True
            success = False
            error_code = "cancelled"
            error_message = "Request cancelled"
            if attempt is not None:
                _absorb(attempt, status="cancelled", error_message=str(exc) or error_message, completion="")
                attempt = None
            raise
        except Exception as exc:  # noqa: BLE001 -- provider failures become an SSE error frame; settlement still runs
            failed_event = None
            if attempt is not None:
                _absorb(attempt, status="failed", error_message=failure_message(exc), completion="")
                failed_event = usage_events[-1]
                attempt = None
                if tools.code_interpreter:
                    await _record_ci_failure(failed_event, failure_message(exc))
            if _should_retry_non_stream(provider, exc):
                retry = NonStreamRetry(
                    ai_model=ai_model,
                    provider_type=provider_type,
                    model=model,
                    completion_kwargs=completion_kwargs,
                    completion_fn=acompletion,
                )
                try:
                    await retry.run()
                except Exception as retry_exc:  # noqa: BLE001 -- error text is surfaced to the caller
                    usage_events.append(
                        retry.usage_event(
                            attempt_index=len(usage_events), status="failed", error_message=failure_message(retry_exc)
                        )
                    )
                    success = False
                    retry_failure = describe_failure(retry_exc)
                    error_code, http_status = retry_failure.code, retry_failure.http_status
                    error_message = _format_provider_error(retry_exc, provider)[:500]
                    yield _sse_error_frame(error_message)
                else:
                    stream_end_at = time.perf_counter()
                    collected_content = retry.content
                    usage_events.append(retry.usage_event(attempt_index=len(usage_events), status="succeeded"))
                    prompt_tokens += retry.prompt_tokens
                    completion_tokens += retry.completion_tokens
                    cached_tokens += retry.cached_tokens
                    if retry.content and agent_turn is None:
                        yield _sse_delta_chunk(retry.content)
                        await _persist_content(collected_content)
                    _compute_cost()
                    if agent_turn is not None:
                        await _review_agent_output()
                        yield _sse_delta_chunk(collected_content)
            else:
                success = False
                failure = describe_failure(exc)
                error_code, http_status = failure.code, failure.http_status
                error_message = _format_provider_error(exc, provider)[:500]
                yield _sse_error_frame(error_message)
        finally:
            # Starlette cancels a streaming response through an anyio cancel
            # scope when the client disconnects. anyio delivers that
            # cancellation at *every* subsequent await until the scope exits, so
            # without a shield the first await below re-raises CancelledError and
            # settlement (release hold, RequestLog, persister.finalize, agent
            # finalization) is skipped: the hold leaks until TTL and consumed
            # tokens are never charged. asyncio.shield() alone protects the inner
            # coroutine but not this frame, so shield the whole finalizer.
            with anyio.CancelScope(shield=True):
                elapsed_ms = (
                    (stream_end_at if stream_end_at is not None else time.perf_counter()) - generation_start
                ) * 1000
                response_metadata = await settle_turn(
                    TurnIdentity(
                        request=request,
                        body=body,
                        user_id=user_id,
                        username=username,
                        model=model,
                        prompt_lang=prompt_lang,
                        source=source,
                        alpha_router_api_key_id=alpha_router_api_key_id,
                        user_api_key_id=user_api_key_id,
                        client_app=client_app,
                        project_id_for_billing=project_id_for_billing,
                        stream_reservation_id=stream_reservation_id,
                        agent_turn=agent_turn,
                        injected_memory_ids=injected_memory_ids,
                        project_memory_project_id=project_memory_project_id,
                        injected_project_memory_ids=injected_project_memory_ids,
                    ),
                    TurnOutcome(
                        success=success,
                        error_message=error_message,
                        was_cancelled=was_cancelled,
                        client_disconnected=client_disconnected,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cached_tokens=cached_tokens,
                        total_cost=total_cost,
                        usage_events=usage_events,
                        elapsed_ms=elapsed_ms,
                        agent_review=agent_review,
                        agent_output_displayed=agent_output_displayed,
                        error_code=error_code,
                        http_status=http_status,
                    ),
                    db=db,
                    persister=persister,
                    capacity_permit=capacity_permit,
                    capacity_heartbeat_task=capacity_heartbeat_task,
                )
            # Yields must stay outside the shielded scope and never run once the
            # consumer is gone: yielding from a cancelled/closed generator would
            # swallow the cancellation or raise "generator ignored GeneratorExit".
            if response_metadata and not was_cancelled and not client_disconnected:
                meta_payload = json.dumps(
                    {"alpha_router": response_metadata},
                    separators=(",", ":"),
                )
                yield f"data: {meta_payload}\n\n".encode()
            if not was_cancelled and not client_disconnected:
                yield b"data: [DONE]\n\n"


async def _end_request_transaction(db: AsyncSession) -> None:
    """Commit (or roll back) whatever the request session has open so its
    connection goes back to the pool while we await the provider."""
    try:
        if db.in_transaction():
            await db.commit()
    except Exception:
        logger.warning("Could not commit request session before provider call; rolling back", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            logger.debug("rollback after failed pre-provider commit failed", exc_info=True)


def _embedding_input_text(input_value) -> str:
    if isinstance(input_value, str):
        return input_value
    if isinstance(input_value, list):
        return "\n".join(str(x) for x in input_value if x is not None)
    return ""


def _embedding_cost_usd(ai_model: AIModel, prompt_tokens: int) -> float:
    if prompt_tokens <= 0:
        return 0.0
    in_rate = _usable_cost_per_1k(ai_model.input_cost_per_1k)
    if in_rate is None:
        return 0.0
    return _sanitize_cost_usd((prompt_tokens / 1000) * in_rate)


async def create_embedding(
    db: AsyncSession,
    body: dict,
    *,
    user_id: int | None,
    username: str,
    source: str,
    skip_budget: bool,
    alpha_router_api_key_id: int | None,
    user_api_key_id: int | None,
    client_app: str | None,
    source_ip: str | None,
) -> dict:
    """OpenAI-compatible embeddings proxy for gateway clients."""
    start = time.perf_counter()
    if not body.get("model"):
        raise HTTPException(status_code=400, detail="model is required")
    if body.get("input") is None:
        raise HTTPException(status_code=400, detail="input is required")

    resolved = await preflight_stream_chat(
        db,
        body,
        user_id=user_id,
        skip_budget=skip_budget,
        alpha_router_api_key_id=alpha_router_api_key_id,
        operation="embedding",
        source=source,
    )
    await db.commit()
    ai_model = resolved.ai_model
    model = resolved.model_id
    provider = (resolved.provider_type or ai_model.provider_type or "").lower()
    prompt_lang = detect_prompt_language(_embedding_input_text(body.get("input")))
    prompt_tokens = 0
    cached_tokens = 0
    total_cost = 0.0
    success = True
    error_message = None
    usage_events: list[PendingUsageEvent] = []
    attempt_started_at = datetime.datetime.utcnow()
    response = None

    embed_kwargs: dict = {
        "input": body.get("input"),
        "api_key": resolved.api_key,
        "base_url": resolved.base_url,
        "caching": True,
    }
    if body.get("dimensions") is not None:
        embed_kwargs["dimensions"] = body["dimensions"]
    if body.get("encoding_format"):
        embed_kwargs["encoding_format"] = body["encoding_format"]
    model = _apply_litellm_provider_kwargs(embed_kwargs, provider, resolved.model_id)

    try:
        response = await aembedding(**embed_kwargs)
        pt, _, cache = _usage_from_response(response)
        prompt_tokens = pt
        if prompt_tokens == 0 and getattr(response, "usage", None):
            prompt_tokens = int(getattr(response.usage, "total_tokens", 0) or 0)
        if prompt_tokens == 0:
            try:
                count_kwargs: dict = {
                    "model": model,
                    "text": _embedding_input_text(body.get("input")),
                }
                llm_provider = resolve_litellm_provider(provider)
                if llm_provider:
                    count_kwargs["custom_llm_provider"] = llm_provider
                prompt_tokens = int(litellm.token_counter(**count_kwargs) or 0)
            except Exception:  # noqa: BLE001 -- best-effort side effect, failure intentionally ignored (Phase 4: log at DEBUG)
                pass
        cached_tokens = cache
        usage_events.append(
            capture_usage_event(
                response,
                ai_model=ai_model,
                provider_type=provider,
                service_type="embedding",
                operation_name="embedding",
                model_id=model,
                status="succeeded",
                started_at=attempt_started_at,
                completed_at=datetime.datetime.utcnow(),
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                cached_tokens=cached_tokens,
                prompt=body.get("input"),
            )
        )
        total_cost = sum(
            float(event.quote.final_cost_usd) for event in usage_events if event.quote.final_cost_usd is not None
        )
        payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    except Exception as exc:
        success = False
        error_message = _format_provider_error(exc, provider)[:500]
        usage_events.append(
            capture_usage_event(
                response,
                ai_model=ai_model,
                provider_type=provider,
                service_type="embedding",
                operation_name="embedding",
                model_id=model,
                status="failed",
                started_at=attempt_started_at,
                completed_at=datetime.datetime.utcnow(),
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                cached_tokens=cached_tokens,
                prompt=body.get("input"),
                error_message=failure_message(exc),
            )
        )
        raise HTTPException(status_code=502, detail=error_message) from exc
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        try:
            async with AsyncSessionLocal() as log_db:
                await log_usage(
                    log_db,
                    user_id=user_id,
                    username=username,
                    model_id=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    cached_tokens=cached_tokens,
                    total_cost_usd=total_cost,
                    response_time_ms=elapsed_ms,
                    prompt_language=prompt_lang,
                    source_ip=source_ip,
                    source=source,
                    success=success,
                    error_message=error_message,
                    alpha_router_api_key_id=alpha_router_api_key_id,
                    user_api_key_id=user_api_key_id,
                    client_app=client_app,
                    budget_reservation_id=getattr(
                        resolved,
                        "budget_reservation_id",
                        None,
                    ),
                    usage_events=usage_events,
                    operation_type="embedding",
                )
                await log_db.commit()
        except Exception:
            import logging

            logging.getLogger("app.services.proxy_service").exception(
                "Embedding usage settlement failed; reservation will expire safely"
            )

    return payload
