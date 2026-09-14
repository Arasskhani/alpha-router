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
from collections.abc import AsyncIterator
from dataclasses import dataclass

import anyio
import httpx
import litellm
from fastapi import HTTPException, Request
from litellm import acompletion, aembedding
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import effective_redis_url, get_settings
from app.core.language_detect import detect_prompt_language
from app.database import AsyncSessionLocal
from app.models.chat import ChatSession
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
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
from app.services.agent_run_service import (
    finalize_agent_run,
    mark_agent_run_started,
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
    release,
    reservation_hold_usd,
    reservation_key,
    reserve,
    settle,
)
from app.services.chat_completion_persistence import persister_from_body
from app.services.chat_tools_service import (
    augment_messages_with_tools,
    parse_tools_config,
)
from app.services.code_interpreter_capacity_service import (
    CapacityPermit,
    acquire_code_interpreter_turn,
    heartbeat_code_interpreter_turn,
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
    WorkspaceLimitError,
    code_interpreter_error_hint,
    code_interpreter_nudge_message,
    code_interpreter_workspace_message,
    extract_last_python_block,
    format_code_output_for_chat,
    run_python_sandbox,
    workspace_files_from_messages,
)
from app.services.llm_providers import (
    external_id_lookup_candidates,
    litellm_model_for_provider,
    normalize_model_id,
    resolve_litellm_provider,
)
from app.services.model_capabilities import model_kinds, model_media_flags
from app.services.model_tool_compatibility_service import (
    assert_code_interpreter_model_available,
    classify_failure_reason,
    is_auto_router_model_id,
    openrouter_auto_plugin,
    record_compatibility_result,
)
from app.services.observability import increment
from app.services.private_mode_service import (
    PrivateModePersistenceError,
    effective_private_mode,
    resolve_private_mode,
)
from app.services.prompt_cache_service import apply_prompt_cache_breakpoints
from app.services.resource_access_service import resolve_resource_access_subject
from app.services.secret_crypto import decrypt_secret
from app.services.storage_service import media_public_url, store_generated_blob
from app.services.usage_accounting_service import (
    NormalizedUsage,
    PendingUsageEvent,
    capture_usage_event,
    legacy_usage_event,
    persist_usage_operation,
    quote_usage,
)
from app.services.project_turn_planner import augment_messages_with_project_context
from app.services.user_memory_service import (
    augment_messages_with_memory,
    extract_query_text,
    record_memory_usage,
)
from app.services.user_profile_context_service import augment_messages_with_profile

logger = logging.getLogger("app.services.proxy_service")

# Backward-compatible aliases for internal modules that import from proxy_service.
_litellm_model_for_provider = litellm_model_for_provider
_resolve_litellm_provider = resolve_litellm_provider

settings = get_settings()

STREAM_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _apply_litellm_provider_kwargs(
    kwargs: dict, provider_type: str | None, model_id: str
) -> str:
    litellm_model = litellm_model_for_provider(
        normalize_model_id(model_id), provider_type
    )
    kwargs["model"] = litellm_model
    llm_provider = resolve_litellm_provider(provider_type)
    if llm_provider:
        kwargs["custom_llm_provider"] = llm_provider
    return litellm_model


@dataclass
class ResolvedStreamContext:
    ai_model: AIModel | None
    api_key: str | None
    base_url: str
    provider_type: str
    model_id: str
    budget_reservation_id: str | None = None
    code_interpreter_workspace_files: dict[str, str] | None = None
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
    except Exception:
        litellm.cache = litellm.Cache()


async def resolve_model_and_key(
    db: AsyncSession,
    model_id: str,
    *,
    allowed_connection_ids: set[int] | None = None,
    allowed_model_ids: set[int] | None = None,
) -> tuple[AIModel | None, str | None, str | None, str | None]:
    from sqlalchemy import select

    from app.models.connection import Connection

    if allowed_connection_ids is not None and not allowed_connection_ids:
        return None, None, None, None
    if allowed_model_ids is not None and not allowed_model_ids:
        return None, None, None, None

    connection_filter = ()
    if allowed_connection_ids is not None:
        connection_filter = (AIModel.connection_id.in_(allowed_connection_ids),)
    model_filter = ()
    if allowed_model_ids is not None:
        model_filter = (AIModel.id.in_(allowed_model_ids),)

    normalized_input = normalize_model_id(model_id)
    row: AIModel | None = None
    if isinstance(normalized_input, str) and normalized_input.startswith("model::"):
        try:
            model_pk = int(normalized_input.split("::", 1)[1])
        except Exception:
            model_pk = None
        if model_pk is not None:
            row = (
                (
                    await db.execute(
                        select(AIModel)
                        .join(Connection, Connection.id == AIModel.connection_id)
                        .where(
                            AIModel.id == model_pk,
                            AIModel.is_enabled == True,  # noqa: E712
                            Connection.is_active == True,  # noqa: E712
                            *connection_filter,
                            *model_filter,
                        )
                        .order_by(AIModel.id.asc())
                    )
                )
                .scalars()
                .first()
            )
    if not row:
        candidates = external_id_lookup_candidates(normalized_input)
        if candidates:
            row = (
                (
                    await db.execute(
                        select(AIModel)
                        # The same external id can exist on several connections;
                        # picking the lowest id and *then* checking its connection
                        # returned "no model" when that one was disabled even
                        # though an active twin existed. Filter first.
                        .join(Connection, Connection.id == AIModel.connection_id)
                        .where(
                            AIModel.external_id.in_(candidates),
                            AIModel.is_enabled == True,  # noqa: E712
                            Connection.is_active == True,  # noqa: E712
                            *connection_filter,
                            *model_filter,
                        )
                        .order_by(AIModel.id.asc())
                    )
                )
                .scalars()
                .first()
            )
    if not row:
        return None, None, None, None
    if (
        allowed_connection_ids is not None
        and int(row.connection_id) not in allowed_connection_ids
    ):
        return None, None, None, None
    if (
        allowed_model_ids is not None
        and int(row.id) not in allowed_model_ids
    ):
        return None, None, None, None
    conn = await db.get(Connection, row.connection_id)
    if not conn or not conn.is_active:
        return None, None, None, None
    return (
        row,
        decrypt_secret(conn.api_key_encrypted),
        conn.base_url,
        conn.provider_type,
    )


def assert_model_supports_text_chat(ai_model: AIModel) -> None:
    """Reject embeddings/rerank/media-only models from the chat-completions path."""
    if is_auto_router_model_id(ai_model.external_id):
        return
    media = model_media_flags(
        external_id=ai_model.external_id or "",
        is_image_model=bool(ai_model.is_image_model),
        is_video_model=bool(getattr(ai_model, "is_video_model", False)),
        pricing_raw=ai_model.pricing_raw,
        provider_type=ai_model.provider_type,
    )
    kinds = model_kinds(
        external_id=ai_model.external_id or "",
        is_image_model=media["is_image_model"],
        is_video_model=media["is_video_model"],
        pricing_raw=ai_model.pricing_raw,
        provider_type=ai_model.provider_type,
    )
    if "text" in kinds:
        return
    kind_label = ", ".join(kinds) if kinds else "unknown"
    raise HTTPException(
        status_code=400,
        detail={
            "message": (
                "This model is not available for text chat "
                f"(capabilities: {kind_label}). Choose a text model instead."
            ),
            "code": "model_not_for_chat",
            "kinds": kinds,
        },
    )


def _extract_prompt_text(messages: list) -> str:
    parts = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


_STREAM_BODY_READ_ERROR_MARKERS = (
    "Attempted to access streaming response content, without having called read()",
    "without having called read()",
)


def _message_has_stream_body_read_error(msg: str) -> bool:
    return any(marker in msg for marker in _STREAM_BODY_READ_ERROR_MARKERS)


def _is_stream_body_read_error(exc: Exception) -> bool:
    return _message_has_stream_body_read_error(str(exc))


def _should_retry_non_stream(_provider: str, exc: Exception) -> bool:
    return _is_stream_body_read_error(exc)


def _format_provider_error(exc: Exception, provider: str) -> str:
    msg = str(exc).strip()
    if provider != "openrouter":
        return msg
    for attr in ("message", "body", "text"):
        val = getattr(exc, attr, None)
        if (
            isinstance(val, str)
            and val.strip()
            and not _message_has_stream_body_read_error(val)
        ):
            return val.strip()
    if _is_stream_body_read_error(exc):
        return "OpenRouter request failed. Check model availability, context size, and API key."
    return msg


def _cached_tokens_from_usage(usage) -> int:
    if not usage:
        return 0
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cached = details.get("cached_tokens") or 0
        else:
            cached = getattr(details, "cached_tokens", None) or 0
        for key in (
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
            "cached_tokens",
        ):
            if usage.get(key):
                cached = cached or usage.get(key) or 0
        return int(cached or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = 0
    if details:
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens") or 0)
        else:
            cached = int(getattr(details, "cached_tokens", None) or 0)
    for key in ("cache_read_input_tokens", "prompt_cache_hit_tokens", "cached_tokens"):
        val = getattr(usage, key, None)
        if val:
            cached = int(val)
            break
    return cached


def _usage_from_usage_obj(usage) -> tuple[int, int, int]:
    if not usage:
        return 0, 0, 0
    if isinstance(usage, dict):
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        return pt, ct, _cached_tokens_from_usage(usage)
    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    return pt, ct, _cached_tokens_from_usage(usage)


def _usage_from_chunk(chunk) -> tuple[int, int, int]:
    pt, ct, cache = _usage_from_usage_obj(getattr(chunk, "usage", None))
    if pt or ct or cache:
        return pt, ct, cache
    if hasattr(chunk, "model_dump"):
        try:
            data = chunk.model_dump()
            if isinstance(data, dict):
                return _usage_from_usage_obj(data.get("usage"))
        except Exception:
            pass
    return 0, 0, 0


def _merge_stream_usage(
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    pt: int,
    ct: int,
    cache: int,
) -> tuple[int, int, int]:
    if pt:
        prompt_tokens = pt
    if ct:
        completion_tokens = ct
    if cache:
        cached_tokens = cache
    return prompt_tokens, completion_tokens, cached_tokens


def _usage_from_stream_wrapper(stream) -> tuple[int, int, int]:
    """Read final usage LiteLLM may attach after the stream completes."""
    for attr in ("_last_returned_hidden_params", "_hidden_params", "hidden_params"):
        params = getattr(stream, attr, None)
        if isinstance(params, dict) and params.get("usage"):
            return _usage_from_usage_obj(params["usage"])
    return 0, 0, 0


def _usage_from_response(response) -> tuple[int, int, int]:
    return _usage_from_usage_obj(getattr(response, "usage", None))


def _sse_delta_chunk(content: str) -> bytes:
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload)}\n\n".encode()


def _agent_citation_metadata(
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
    by_id = {
        citation.citation_id: citation
        for citation in agent_turn.plan.retrieval.context.citations
    }
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


def _agent_identity_metadata(agent_turn: PreparedAgentTurn) -> dict[str, object]:
    plan = agent_turn.plan
    target = getattr(plan, "target", None)
    agent = getattr(target, "agent", None)
    version = getattr(target, "version", None)
    return {
        "agent_id": getattr(plan, "selected_agent_id", None)
        or getattr(agent, "id", None),
        "agent_version_id": getattr(plan, "selected_agent_version_id", None)
        or getattr(version, "id", None),
        "agent_name": getattr(agent, "name", None),
    }


def _serialize_stream_chunk(chunk) -> str:
    try:
        return chunk.model_dump_json()
    except Exception:
        if hasattr(chunk, "model_dump"):
            return json.dumps(chunk.model_dump(), default=str)
        return json.dumps(chunk, default=str)


def _usage_event_model_id(event: PendingUsageEvent | None) -> str | None:
    if event is None:
        return None

    def _from_raw(value) -> str | None:
        if not isinstance(value, dict):
            return None
        model_value = value.get("model")
        if model_value:
            return str(model_value)
        for key in ("primary", "fallback"):
            nested = _from_raw(value.get(key))
            if nested:
                return nested
        return None

    value = _from_raw(event.usage.raw_usage)
    if value and value.startswith("openrouter/"):
        return value.removeprefix("openrouter/")
    return value


async def _openrouter_generation_outcome(
    *,
    base_url: str,
    api_key: str,
    upstream_request_id: str | None,
) -> dict | None:
    request_id = (upstream_request_id or "").strip()
    if not request_id:
        return None
    base = (base_url or "https://openrouter.ai/api/v1").strip().rstrip("/")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        trust_env=False,
    ) as client:
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


# How often the sandbox wait wakes up to notice that the user pressed Stop.
_SANDBOX_CANCEL_POLL_SECONDS = 0.4


def _abandon_task(task: asyncio.Task) -> None:
    """Cancel a task we no longer wait on and swallow its eventual result.

    Without draining it, asyncio logs "Task exception was never retrieved" once
    the abandoned sandbox call finishes or raises.
    """
    task.cancel()

    async def _drain() -> None:
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    _spawn_compatibility_task(_drain())


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
                upstream_request_id=(
                    event.usage.upstream_request_id if event is not None else None
                ),
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
            upstream_request_id=(
                event.usage.upstream_request_id if event is not None else None
            ),
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
    native_reason = (
        str(evidence.get("native_finish_reason") or evidence.get("finish_reason") or "")
        if evidence
        else ""
    )
    reason_code = reason_code_override or classify_failure_reason(
        f"{detail} {native_reason}"
    )
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


async def _adaptive_openrouter_extra_body(ai_model: AIModel) -> dict | None:
    """Constrain Auto Router with recorded evidence, never with vendor names."""
    connection_id = getattr(ai_model, "connection_id", None)
    if connection_id is None:
        return None
    try:
        async with AsyncSessionLocal() as compatibility_db:
            plugin = await openrouter_auto_plugin(
                compatibility_db,
                connection_id=int(connection_id),
                requested_model_id=ai_model.external_id,
            )
    except Exception:
        logger.exception("Failed to build adaptive Auto Router constraints")
        return None
    return {"plugins": [plugin]}


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
    request_key = body.get("_idempotency_key") or body.get(
        "assistant_client_message_id"
    )
    if not request_key:
        return None
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"alpharouter:code-interpreter:{subject}:{request_key}",
        )
    )


async def preflight_stream_chat(
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
    from app.services.chat_channel_guard import assert_session_allows_model_generation
    from app.services.api_key_connection_policy import allowed_connection_ids_for_key
    from app.services.api_key_model_policy import allowed_model_ids_for_key
    from app.services.model_access_service import (
        resolve_access_subject,
        user_can_access_model,
    )

    await assert_session_allows_model_generation(
        db, str(body.get("chat_session_id") or "").strip() or None
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
    allowed_connection_ids = await allowed_connection_ids_for_key(
        db, alpha_router_api_key_id
    )
    allowed_model_ids = await allowed_model_ids_for_key(db, alpha_router_api_key_id)
    ai_model, api_key, base_url, provider_type = await resolve_model_and_key(
        db,
        selected_model,
        allowed_connection_ids=allowed_connection_ids,
        allowed_model_ids=allowed_model_ids,
    )
    if not ai_model or not api_key:
        raise HTTPException(
            status_code=404, detail=f"Model not enabled: {selected_model}"
        )
    assert_model_supports_text_chat(ai_model)
    subject = await resolve_access_subject(
        db,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        source=source,
    )
    if not await user_can_access_model(db, ai_model, subject):
        raise HTTPException(
            status_code=404, detail=f"Model not enabled: {selected_model}"
        )
    tools = parse_tools_config({} if agent_turn is not None else body)
    workspace_files: dict[str, str] | None = None
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
        model_id=litellm_model_for_provider(
            ai_model.external_id, provider_type or ai_model.provider_type
        ),
        budget_reservation_id=hold.id if hold else None,
        code_interpreter_workspace_files=workspace_files,
        code_interpreter_capacity_permit=capacity_permit,
        agent_turn=agent_turn,
    )


def _extract_non_stream_content(response) -> tuple[str, tuple[int, int, int]]:
    content = ""
    if response.choices:
        message = response.choices[0].message
        content = getattr(message, "content", None) or ""
    return content, _usage_from_response(response)


async def _apply_cost_to_user(db: AsyncSession, user_id: int, cost: float) -> None:
    if cost <= 0:
        return
    # Atomic increment via SQL UPDATE (col = col + :cost) instead of ORM
    # read-modify-write. Concurrent requests otherwise race on the same row:
    # both read the old value, both add their cost, both write — one update is
    # lost. The single UPDATE statement is atomic at the row level under both
    # PostgreSQL (row lock) and SQLite (database lock), so no lost updates.
    await db.execute(
        text(
            "UPDATE users SET budget_used_usd = COALESCE(budget_used_usd, 0) + :cost WHERE id = :uid"
        ),
        {"cost": float(cost), "uid": user_id},
    )


def _usable_cost_per_1k(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if rate >= 0 else None


def _sanitize_cost_usd(cost: float | None) -> float:
    try:
        value = float(cost or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if value >= 0 else 0.0


def _compute_token_cost_usd(
    ai_model: AIModel,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    model_id: str,
    messages,
    completion_text: str,
    provider_type: str | None = None,
) -> float:
    usage = NormalizedUsage(
        prompt_tokens=max(0, int(prompt_tokens or 0)),
        completion_tokens=max(0, int(completion_tokens or 0)),
    )
    quote = quote_usage(
        usage,
        ai_model=ai_model,
        provider_type=provider_type or getattr(ai_model, "provider_type", None),
        service_type="llm",
        model_id=model_id,
        prompt=messages,
        completion=completion_text,
    )
    return _sanitize_cost_usd(quote.final_cost_usd)


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
        total_cost_usd=_sanitize_cost_usd(total_cost_usd),
        response_time_ms=response_time_ms,
        prompt_language=prompt_language,
        source_ip=source_ip,
        source=source,
        client_app=client_app,
        success=success,
        error_message=error_message,
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
    total_cost_usd = _sanitize_cost_usd(accounting.total_cost_usd)
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
                        _extract_prompt_text(prompt)
                        if isinstance(prompt, list)
                        else str(prompt or "")
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
                        f"aux:{budget_reservation_id}"
                        if budget_reservation_id
                        else f"aux:{event.idempotency_key}"
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
                "Auxiliary usage settlement failed after retries operation=%s; "
                "reservation remains held for recovery",
                operation_name,
            )


async def _resolve_private_mode_for_memory(
    db: AsyncSession,
    body: dict,
    *,
    user_id: int | None,
) -> bool:
    """Return the server-owned preflight decision for legacy chat augmentation."""
    if isinstance(body.get("_effective_private_mode"), bool):
        return effective_private_mode(body)
    return (
        await resolve_private_mode(
            db,
            body,
            user_id=user_id,
            source="alpha_router_chat",
        )
    ).effective


async def _resolve_session_project_id(
    db: AsyncSession, chat_session_id: str | None
) -> str | None:
    """Server-side project of a chat session; the client value is never trusted."""
    sid = (chat_session_id or "").strip()
    if not sid:
        return None
    try:
        from app.models.chat import ChatSession

        session = await db.get(ChatSession, sid)
    except Exception:
        logger.exception("Failed to resolve session project session_id=%s", sid)
        return None
    if session is None:
        return None
    return str(session.project_id) if session.project_id else None


async def stream_chat(
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
    messages = list(body.get("messages", []))
    injected_memory_ids: list[str] = []
    injected_project_memory_ids: list[str] = []
    project_memory_project_id: str | None = None
    prompt_lang = detect_prompt_language(_extract_prompt_text(messages))
    success = True
    error_message = None
    model = body.get("model") or ""

    async with AsyncSessionLocal() as db:
        chat_session_id_for_billing = str(body.get("chat_session_id") or "").strip()
        project_id_for_billing: str | None = None
        if chat_session_id_for_billing:
            from app.models.chat import ChatSession

            sess_row = (
                await db.execute(
                    select(ChatSession.id, ChatSession.project_id).where(
                        ChatSession.id == chat_session_id_for_billing
                    )
                )
            ).first()
            if sess_row is not None:
                project_id_for_billing = sess_row[1]
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

        agent_turn = getattr(resolved, "agent_turn", None)
        if agent_turn is not None:
            body["_agent_run_id"] = agent_turn.run_id
            if agent_turn.plan.status != "ready":
                safe_response = (
                    agent_turn.plan.safe_response
                    or "This Agent turn could not be completed safely."
                )
                persister = None
                if source == "alpha_router_chat" and user_id:
                    persister = persister_from_body(
                        db,
                        user_id=user_id,
                        body=body,
                        model_id=(
                            str(agent_turn.plan.selected_model_id)
                            if agent_turn.plan.selected_model_id is not None
                            else None
                        ),
                        model_name=(
                            agent_turn.plan.target.agent.name
                            if agent_turn.plan.target is not None
                            else "Alpharouter"
                        ),
                    )
                if persister is not None:
                    try:
                        persister.set_completion_metadata(
                            {
                                "agentRunId": agent_turn.run_id,
                                "agentId": agent_turn.plan.selected_agent_id,
                                "agentVersionId": (
                                    agent_turn.plan.selected_agent_version_id
                                ),
                                "agentStatus": agent_turn.plan.status,
                                "routingOutcome": agent_turn.plan.routing_outcome,
                            }
                        )
                        await persister.prepare()
                        await persister.on_content(safe_response)
                        await persister.finalize(success=True)
                    except Exception:
                        await db.rollback()
                        logger.exception(
                            "Failed to persist non-generating Agent response run=%s",
                            agent_turn.run_id,
                        )
                await finalize_agent_run(
                    db,
                    run_id=agent_turn.run_id,
                    status=agent_turn.plan.status,
                    provider_latency_ms=0,
                    total_latency_ms=agent_turn.plan.total_planning_latency_ms,
                    output_displayed=True,
                )
                await db.commit()
                yield _sse_delta_chunk(safe_response)
                meta_payload = json.dumps(
                    {
                        "alpha_router": {
                            "agent_run_id": agent_turn.run_id,
                            **_agent_identity_metadata(agent_turn),
                            "agent_status": agent_turn.plan.status,
                            "routing_outcome": agent_turn.plan.routing_outcome,
                        }
                    },
                    separators=(",", ":"),
                )
                yield f"data: {meta_payload}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return

            if agent_turn.plan.prompt is None:
                raise HTTPException(
                    status_code=503,
                    detail="Agent prompt plan is unavailable",
                )
            messages = [dict(message) for message in agent_turn.plan.prompt.messages]
            await mark_agent_run_started(db, agent_turn.run_id)
            await db.commit()

        agent_resource_subject = (
            await resolve_resource_access_subject(
                db,
                user_id=user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                source=source,
            )
            if agent_turn is not None
            else None
        )
        tools = parse_tools_config({} if agent_turn is not None else body)
        ai_model = resolved.ai_model
        if ai_model is None:
            raise HTTPException(status_code=503, detail="Resolved model is unavailable")
        api_key = resolved.api_key
        base_url = resolved.base_url
        provider_type = resolved.provider_type
        model = resolved.model_id

        prompt_tokens = completion_tokens = cached_tokens = 0
        total_cost = 0.0
        collected_content = ""
        usage_events: list[PendingUsageEvent] = []
        stream_reservation_id = getattr(resolved, "budget_reservation_id", None)
        capacity_permit = getattr(
            resolved,
            "code_interpreter_capacity_permit",
            None,
        )
        capacity_lost = asyncio.Event()
        capacity_heartbeat_task: asyncio.Task | None = None

        async def _release_stream_reservation() -> None:
            if not stream_reservation_id:
                return
            async with AsyncSessionLocal() as release_db:
                await release(release_db, stream_reservation_id)
                await release_db.commit()

        async def _release_capacity_permit() -> None:
            if capacity_permit is None:
                return
            await release_code_interpreter_turn(capacity_permit)

        async def _capacity_heartbeat_loop() -> None:
            heartbeat_seconds = max(
                5,
                int(settings.code_interpreter_capacity_heartbeat_seconds or 30),
            )
            while True:
                await asyncio.sleep(heartbeat_seconds)
                try:
                    alive = await heartbeat_code_interpreter_turn(capacity_permit)
                except HTTPException:
                    logger.exception("Code Interpreter capacity heartbeat failed")
                    capacity_lost.set()
                    return
                if not alive:
                    logger.error("Code Interpreter capacity lease was lost")
                    capacity_lost.set()
                    return

        if capacity_permit is not None:
            capacity_heartbeat_task = asyncio.create_task(_capacity_heartbeat_loop())

        completion_kwargs: dict = {
            "messages": messages,
            "stream": True,
            "api_key": api_key,
            "base_url": base_url,
            "caching": True,
            "timeout": float(getattr(settings, "chat_provider_timeout_seconds", 600.0) or 600.0),
        }
        if agent_turn is not None and agent_turn.plan.policies is not None:
            completion_kwargs["max_tokens"] = (
                agent_turn.plan.policies.model.max_output_tokens
            )
            if agent_turn.plan.policies.model.temperature is not None:
                completion_kwargs["temperature"] = (
                    agent_turn.plan.policies.model.temperature
                )
        model = _apply_litellm_provider_kwargs(completion_kwargs, provider_type, model)
        provider = (provider_type or ai_model.provider_type or "").lower()
        if (
            tools.code_interpreter
            and provider == "openrouter"
            and is_auto_router_model_id(ai_model.external_id)
        ):
            auto_router_extra_body = await _adaptive_openrouter_extra_body(ai_model)
            if auto_router_extra_body:
                completion_kwargs["extra_body"] = auto_router_extra_body
        if provider in ("openai", "azure", "openrouter", "anthropic", "xai"):
            completion_kwargs["stream_options"] = {"include_usage": True}

        if agent_turn is None:
            try:
                messages = await augment_messages_with_tools(
                    db,
                    messages,
                    tools,
                    user_id=user_id,
                    alpha_router_api_key_id=alpha_router_api_key_id,
                    username=username,
                    reserve_budget=not skip_budget,
                )
            except BaseException:
                try:
                    await asyncio.shield(_release_stream_reservation())
                except Exception:
                    logger.exception(
                        "Failed to release chat reservation after tool setup error"
                    )
                if capacity_heartbeat_task is not None:
                    capacity_heartbeat_task.cancel()
                await asyncio.shield(_release_capacity_permit())
                raise
        private_mode = await _resolve_private_mode_for_memory(db, body, user_id=user_id)
        if agent_turn is None:
            try:
                chat_session_id = (
                    str(body.get("chat_session_id") or "").strip() or None
                )
                session_project_id = await _resolve_session_project_id(
                    db, chat_session_id
                )
                project_memory_project_id = session_project_id
                messages = await augment_messages_with_profile(
                    db,
                    messages,
                    user_id=user_id,
                    private_mode=private_mode,
                )
                if session_project_id is None:
                    # A project thread is shared with teammates, so it sees only
                    # project memory. Personal facts stay out of it entirely.
                    messages = await augment_messages_with_memory(
                        db,
                        messages,
                        user_id=user_id,
                        private_mode=private_mode,
                        query=extract_query_text(messages),
                        injected_ids=injected_memory_ids,
                    )
                messages = await augment_messages_with_project_context(
                    db,
                    messages,
                    user_id=user_id,
                    chat_session_id=chat_session_id,
                    client_project_id=str(
                        body.get("project_id") or body.get("projectId") or ""
                    ).strip()
                    or None,
                    query=extract_query_text(messages),
                    injected_memory_ids=injected_project_memory_ids,
                )
            except BaseException:
                try:
                    await asyncio.shield(_release_stream_reservation())
                except Exception:
                    logger.exception(
                        "Failed to release chat reservation after memory setup error"
                    )
                if capacity_heartbeat_task is not None:
                    capacity_heartbeat_task.cancel()
                await asyncio.shield(_release_capacity_permit())
                raise
        messages = apply_prompt_cache_breakpoints(messages)
        original_messages = list(body.get("messages", []))
        resolved_workspace_files = getattr(
            resolved,
            "code_interpreter_workspace_files",
            None,
        )
        workspace_files = (
            resolved_workspace_files
            if tools.code_interpreter and resolved_workspace_files is not None
            else (
                workspace_files_from_messages(original_messages)
                if tools.code_interpreter
                else {}
            )
        )
        if tools.code_interpreter and workspace_files:
            inventory = code_interpreter_workspace_message(workspace_files)
            if inventory:
                messages = list(messages)
                if (
                    messages
                    and messages[0].get("role") == "system"
                    and isinstance(messages[0].get("content"), str)
                ):
                    messages[0] = {
                        "role": "system",
                        "content": f"{messages[0]['content']}\n\n{inventory}",
                    }
                else:
                    messages = [
                        {"role": "system", "content": inventory},
                        *messages,
                    ]
        current_messages = list(messages)
        completion_kwargs["messages"] = current_messages
        generation_start = time.perf_counter()
        stream_end_at: float | None = None
        active_response = None
        active_last_chunk = None
        active_started_at: datetime.datetime | None = None
        active_messages = None
        active_prompt_tokens = 0
        active_completion_tokens = 0
        active_cached_tokens = 0

        persister = None
        if source == "alpha_router_chat" and user_id:
            persister = persister_from_body(
                db,
                user_id=user_id,
                body=body,
                model_id=model,
                model_name=ai_model.display_name or ai_model.external_id or model,
            )
            if persister:
                try:
                    if agent_turn is not None:
                        persister.set_completion_metadata(
                            {
                                "agentRunId": agent_turn.run_id,
                                "agentId": agent_turn.plan.selected_agent_id,
                                "agentVersionId": (
                                    agent_turn.plan.selected_agent_version_id
                                ),
                                "agentName": (
                                    agent_turn.plan.target.agent.name
                                    if agent_turn.plan.target is not None
                                    else None
                                ),
                                "routingOutcome": agent_turn.plan.routing_outcome,
                            }
                        )
                    await persister.prepare()
                except Exception:
                    await db.rollback()
                    persister = None

        async def _compute_cost() -> None:
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
                try:
                    tc_kwargs: dict = {"messages": msgs_for_count}
                    litellm_model = _apply_litellm_provider_kwargs(
                        tc_kwargs, provider_type, model
                    )
                    prompt_tokens = litellm.token_counter(**tc_kwargs)
                    ct_kwargs: dict = {
                        "model": litellm_model,
                        "text": collected_content,
                    }
                    llm_provider = resolve_litellm_provider(provider_type)
                    if llm_provider:
                        ct_kwargs["custom_llm_provider"] = llm_provider
                    completion_tokens = litellm.token_counter(**ct_kwargs)
                except Exception:
                    pass

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
        agent_review: AgentCompletionReview | None = None
        agent_output_displayed = False
        # Sticky for the whole request: once the user presses Stop (or the client
        # goes away), later Code Interpreter iterations must not resume work.
        client_disconnected = False

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
            except Exception:
                pass
            if persister:
                try:
                    if await persister.is_cancel_requested(force=True):
                        client_disconnected = True
                        return True
                except Exception:
                    pass
            return False

        async def _run_sandbox_until_stopped(
            code: str,
            files: dict[str, str],
        ) -> SandboxExecutionResult | None:
            """Run sandbox code, abandoning the wait as soon as the user stops.

            Returns ``None`` when the client stopped while the sandbox was still
            running. Cancelling the executor task invokes the broker Job DELETE
            path, which force-removes the active container.
            """
            task = asyncio.create_task(run_python_sandbox(code, files))
            while True:
                done, _pending = await asyncio.wait(
                    {task},
                    timeout=_SANDBOX_CANCEL_POLL_SECONDS,
                )
                if task in done:
                    return task.result()
                if await _client_stopped():
                    _abandon_task(task)
                    increment("code_interpreter_cancelled")
                    return None

        try:
            code_iterations = 0
            code_nudge_sent = False
            code_executed = False
            emitted_artifact_ids: set[int] = set()
            observed_compatibility_models: set[str] = set()
            while True:
                if client_disconnected:
                    break
                active_started_at = datetime.datetime.utcnow()
                active_messages = list(completion_kwargs.get("messages", messages))
                active_prompt_tokens = 0
                active_completion_tokens = 0
                active_cached_tokens = 0
                active_last_chunk = None
                # Release the request session's connection before waiting on
                # the provider. Only persisted chats commit via
                # persister.prepare(); gateway, API-key and Private Mode turns
                # otherwise keep the transaction opened by the session lookups
                # above -- and with it one pooled connection and one PgBouncer
                # server slot -- for the whole stream (minutes). ~32 concurrent
                # gateway streams per worker then exhaust the pool.
                await _end_request_transaction(db)
                response = await acompletion(**completion_kwargs)
                active_response = response
                iteration_content = ""
                async for chunk in response:
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
                        await _close_upstream_stream(response)
                        break
                    pt, ct, cache = _usage_from_chunk(chunk)
                    chunk_usage = (
                        chunk.get("usage")
                        if isinstance(chunk, dict)
                        else getattr(chunk, "usage", None)
                    )
                    if pt or ct or cache or chunk_usage is not None:
                        active_last_chunk = chunk
                    (
                        active_prompt_tokens,
                        active_completion_tokens,
                        active_cached_tokens,
                    ) = _merge_stream_usage(
                        active_prompt_tokens,
                        active_completion_tokens,
                        active_cached_tokens,
                        pt,
                        ct,
                        cache,
                    )
                    if chunk.choices and chunk.choices[0].delta.content:
                        delta = chunk.choices[0].delta.content
                        iteration_content += delta
                        collected_content += delta
                    if not client_disconnected and agent_turn is None:
                        yield f"data: {_serialize_stream_chunk(chunk)}\n\n".encode()
                    # Persist after yield and without awaiting DB: token printing
                    # must not wait on commit. A partial flush after Stop would
                    # re-mark the message as streaming, so skip once cancelled.
                    if (
                        chunk.choices
                        and chunk.choices[0].delta.content
                        and persister
                        and agent_turn is None
                        and not client_disconnected
                    ):
                        persister.schedule_content(collected_content)

                pt, ct, cache = _usage_from_stream_wrapper(response)
                active_prompt_tokens, active_completion_tokens, active_cached_tokens = (
                    _merge_stream_usage(
                        active_prompt_tokens,
                        active_completion_tokens,
                        active_cached_tokens,
                        pt,
                        ct,
                        cache,
                    )
                )
                if active_prompt_tokens == 0 and iteration_content:
                    try:
                        token_kwargs: dict = {"messages": active_messages}
                        _apply_litellm_provider_kwargs(
                            token_kwargs,
                            provider_type,
                            model,
                        )
                        active_prompt_tokens = int(
                            litellm.token_counter(**token_kwargs) or 0
                        )
                        completion_kwargs_for_count: dict = {
                            "model": model,
                            "text": iteration_content,
                        }
                        llm_provider = resolve_litellm_provider(provider_type)
                        if llm_provider:
                            completion_kwargs_for_count["custom_llm_provider"] = (
                                llm_provider
                            )
                        active_completion_tokens = int(
                            litellm.token_counter(**completion_kwargs_for_count) or 0
                        )
                    except Exception:
                        pass
                empty_completion = not iteration_content.strip()
                attempt_error = (
                    "Upstream model returned an empty completion."
                    if empty_completion
                    else None
                )
                active_event = capture_usage_event(
                    response,
                    fallback_response=active_last_chunk,
                    ai_model=ai_model,
                    provider_type=provider_type,
                    service_type="llm",
                    operation_name="chat_completion",
                    model_id=model,
                    attempt_index=len(usage_events),
                    status="failed" if empty_completion else "succeeded",
                    started_at=active_started_at,
                    completed_at=datetime.datetime.utcnow(),
                    prompt_tokens=active_prompt_tokens,
                    completion_tokens=active_completion_tokens,
                    cached_tokens=active_cached_tokens,
                    prompt=active_messages,
                    completion=iteration_content,
                    error_message=attempt_error,
                )
                usage_events.append(active_event)
                observed_model_id = _usage_event_model_id(active_event)
                if observed_model_id and not is_auto_router_model_id(observed_model_id):
                    observed_compatibility_models.add(observed_model_id)
                prompt_tokens += active_prompt_tokens
                completion_tokens += active_completion_tokens
                cached_tokens += active_cached_tokens
                active_response = None
                active_last_chunk = None
                active_started_at = None
                active_messages = None
                active_prompt_tokens = 0
                active_completion_tokens = 0
                active_cached_tokens = 0

                if client_disconnected:
                    break

                if empty_completion and tools.code_interpreter:
                    try:
                        await _record_code_interpreter_failure(
                            ai_model=ai_model,
                            provider=provider,
                            base_url=base_url,
                            api_key=api_key,
                            event=active_event,
                            detail=attempt_error or "Empty Code Interpreter response",
                        )
                    except Exception:
                        logger.exception(
                            "Failed to record Code Interpreter compatibility failure"
                        )
                    if provider == "openrouter" and is_auto_router_model_id(
                        ai_model.external_id
                    ):
                        retry_extra_body = await _adaptive_openrouter_extra_body(
                            ai_model
                        )
                        if retry_extra_body:
                            completion_kwargs["extra_body"] = retry_extra_body

                if empty_completion and (
                    not tools.code_interpreter
                    or code_nudge_sent
                    or code_iterations >= MAX_CODE_ITERATIONS
                ):
                    success = False
                    error_message = (
                        "The upstream model returned no usable content. "
                        "Retry the request or select a different model."
                    )
                    yield f"data: {json.dumps({'error': error_message})}\n\n".encode()
                    break

                if not tools.code_interpreter or code_iterations >= MAX_CODE_ITERATIONS:
                    break

                code = extract_last_python_block(iteration_content)
                if not code:
                    if code_executed:
                        # Code already ran in this turn, so an answer without a new
                        # block is the normal end of the flow: never nudge again and
                        # never score it as a compatibility failure.
                        break
                    if code_nudge_sent:
                        try:
                            await _record_code_interpreter_failure(
                                ai_model=ai_model,
                                provider=provider,
                                base_url=base_url,
                                api_key=api_key,
                                event=active_event,
                                detail=(
                                    "The model did not emit a runnable Python block "
                                    "after an explicit nudge."
                                ),
                                reason_code_override="no_python_block",
                            )
                        except Exception:
                            logger.exception(
                                "Failed to record Code Interpreter compatibility failure"
                            )
                        break
                    code_nudge_sent = True
                    current_messages = apply_prompt_cache_breakpoints(
                        current_messages
                        + [
                            {"role": "assistant", "content": iteration_content},
                            {
                                "role": "user",
                                "content": code_interpreter_nudge_message(
                                    workspace_files
                                ),
                            },
                        ]
                    )
                    completion_kwargs["messages"] = current_messages
                    continue

                # Sandbox runs can take tens of seconds, so Stop must be honored
                # both before starting and while waiting for the result.
                if await _client_stopped():
                    break

                try:
                    exec_result = await _run_sandbox_until_stopped(
                        code, workspace_files
                    )
                except ValueError as exc:
                    exec_result = SandboxExecutionResult(
                        output=f"Code interpreter error: {exc}",
                        exit_code=1,
                    )
                if exec_result is None or await _client_stopped():
                    break
                if isinstance(exec_result, str):
                    exec_result = SandboxExecutionResult(
                        output=exec_result,
                        exit_code=0,
                    )

                if exec_result.exit_code == 0:
                    code_executed = True
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
                                observed_model_ids=set(observed_compatibility_models),
                            )
                        )
                    )

                formatted = format_code_output_for_chat(exec_result)
                artifact_context = ""
                if exec_result.artifacts:
                    can_persist_artifacts = bool(
                        source == "alpha_router_chat"
                        and body.get("persist_chat")
                        and user_id
                        and body.get("chat_session_id")
                    )
                    if can_persist_artifacts:
                        try:
                            stored_artifacts = (
                                await _persist_code_interpreter_artifacts(
                                    exec_result.artifacts,
                                    user_id=int(user_id),
                                    username=username,
                                    chat_session_id=str(body["chat_session_id"]),
                                    model_id=model,
                                    source_prompt=_extract_prompt_text(messages),
                                )
                            )
                            new_artifacts = [
                                item
                                for item in stored_artifacts
                                if item.asset_id not in emitted_artifact_ids
                            ]
                            emitted_artifact_ids.update(
                                item.asset_id for item in new_artifacts
                            )
                            formatted += _artifact_links_markdown(new_artifacts)
                            artifact_context = (
                                "Platform-stored artifacts (use only these exact download links):\n"
                                + "\n".join(
                                    f"- {item.name}: {item.url}"
                                    for item in stored_artifacts
                                )
                            )
                        except Exception:
                            logger.exception(
                                "Failed to persist code interpreter artifacts"
                            )
                            artifact_context = (
                                "The generated files could not be stored in Media. "
                                "Do not invent download links."
                            )
                            formatted += (
                                "\n> Generated files could not be stored in Media. "
                                "No download link was created.\n\n"
                            )
                    else:
                        artifact_context = (
                            "This is not a persisted app chat, so generated files were not stored. "
                            "Do not invent download links."
                        )
                        formatted += (
                            "\n> Generated files are not persisted for Private Mode or "
                            "non-persisted API chats.\n\n"
                        )
                collected_content += formatted
                if persister:
                    try:
                        await persister.on_content(collected_content)
                    except Exception:
                        await db.rollback()
                        persister.reset_persist_state()
                if not client_disconnected:
                    yield _sse_delta_chunk(formatted)

                remediation = (
                    code_interpreter_error_hint(exec_result.output)
                    if exec_result.exit_code != 0
                    else ""
                )
                feedback_parts = [
                    part
                    for part in (
                        exec_result.output,
                        artifact_context,
                        remediation,
                        "Continue your reply to the user using these results. "
                        "Do not repeat the same code unless necessary.",
                    )
                    if part
                ]
                current_messages = apply_prompt_cache_breakpoints(
                    current_messages
                    + [
                        {"role": "assistant", "content": iteration_content},
                        {
                            "role": "user",
                            "content": "\n\n".join(feedback_parts),
                        },
                    ]
                )
                completion_kwargs["messages"] = current_messages
                code_iterations += 1

            await _compute_cost()
            if agent_turn is not None and not client_disconnected and success:
                if agent_resource_subject is None:
                    raise AgentRuntimeUnavailable(
                        "Agent authorization context is unavailable"
                    )
                agent_review = await finalize_agent_completion(
                    plan=agent_turn.plan,
                    output_text=collected_content,
                    resource_subject=agent_resource_subject,
                )
                reviewed_content = (
                    agent_review.display_text
                    if agent_review.status == "ready"
                    else agent_review.safe_response
                )
                collected_content = reviewed_content or (
                    "This Agent response could not be displayed safely."
                )
                if persister:
                    persister.set_completion_metadata(
                        {
                            "agentStatus": (
                                "succeeded"
                                if agent_review.status == "ready"
                                else "blocked"
                            ),
                            "completionReasonCode": agent_review.reason_code,
                            "citations": _agent_citation_metadata(
                                agent_turn,
                                agent_review,
                            ),
                        }
                    )
                    try:
                        await persister.on_content(collected_content)
                    except Exception:
                        await db.rollback()
                        persister.reset_persist_state()
                yield _sse_delta_chunk(collected_content)
                agent_output_displayed = True
        except GeneratorExit:
            # The ASGI server closed the generator (client gone). Nothing may be
            # yielded from here on; the finally block below still settles.
            was_cancelled = True
            client_disconnected = True
            success = False
            error_message = "Request cancelled"
            raise
        except asyncio.CancelledError as exc:
            was_cancelled = True
            success = False
            error_message = "Request cancelled"
            if active_started_at is not None:
                usage_events.append(
                    capture_usage_event(
                        active_response,
                        fallback_response=active_last_chunk,
                        ai_model=ai_model,
                        provider_type=provider_type,
                        service_type="llm",
                        operation_name="chat_completion",
                        model_id=model,
                        attempt_index=len(usage_events),
                        status="cancelled",
                        started_at=active_started_at,
                        completed_at=datetime.datetime.utcnow(),
                        prompt_tokens=active_prompt_tokens,
                        completion_tokens=active_completion_tokens,
                        cached_tokens=active_cached_tokens,
                        prompt=active_messages,
                        completion="",
                        error_message=str(exc) or error_message,
                    )
                )
                prompt_tokens += active_prompt_tokens
                completion_tokens += active_completion_tokens
                cached_tokens += active_cached_tokens
            raise
        except Exception as exc:
            if active_started_at is not None:
                failed_event = capture_usage_event(
                    active_response,
                    fallback_response=active_last_chunk,
                    ai_model=ai_model,
                    provider_type=provider_type,
                    service_type="llm",
                    operation_name="chat_completion",
                    model_id=model,
                    attempt_index=len(usage_events),
                    status="failed",
                    started_at=active_started_at,
                    completed_at=datetime.datetime.utcnow(),
                    prompt_tokens=active_prompt_tokens,
                    completion_tokens=active_completion_tokens,
                    cached_tokens=active_cached_tokens,
                    prompt=active_messages,
                    completion="",
                    error_message=str(exc),
                )
                usage_events.append(failed_event)
                prompt_tokens += active_prompt_tokens
                completion_tokens += active_completion_tokens
                cached_tokens += active_cached_tokens
                if tools.code_interpreter:
                    try:
                        await _record_code_interpreter_failure(
                            ai_model=ai_model,
                            provider=provider,
                            base_url=base_url,
                            api_key=api_key,
                            event=failed_event,
                            detail=str(exc),
                        )
                    except Exception:
                        logger.exception(
                            "Failed to record Code Interpreter compatibility failure"
                        )
            active_response = None
            active_last_chunk = None
            active_started_at = None
            active_messages = None
            active_prompt_tokens = 0
            active_completion_tokens = 0
            active_cached_tokens = 0
            if _should_retry_non_stream(provider, exc):
                retry_started_at = datetime.datetime.utcnow()
                try:
                    retry_kwargs = dict(completion_kwargs)
                    retry_kwargs["stream"] = False
                    retry_kwargs.pop("stream_options", None)
                    retry_response = await acompletion(**retry_kwargs)
                    stream_end_at = time.perf_counter()
                    content, (pt, ct, cache) = _extract_non_stream_content(
                        retry_response
                    )
                    collected_content = content
                    if pt == 0 and content:
                        try:
                            prompt_count_kwargs: dict = {
                                "messages": retry_kwargs.get("messages", messages)
                            }
                            _apply_litellm_provider_kwargs(
                                prompt_count_kwargs,
                                provider_type,
                                model,
                            )
                            pt = int(litellm.token_counter(**prompt_count_kwargs) or 0)
                            completion_count_kwargs: dict = {
                                "model": model,
                                "text": content,
                            }
                            llm_provider = resolve_litellm_provider(provider_type)
                            if llm_provider:
                                completion_count_kwargs["custom_llm_provider"] = (
                                    llm_provider
                                )
                            ct = int(
                                litellm.token_counter(**completion_count_kwargs) or 0
                            )
                        except Exception:
                            pass
                    usage_events.append(
                        capture_usage_event(
                            retry_response,
                            ai_model=ai_model,
                            provider_type=provider_type,
                            service_type="llm",
                            operation_name="chat_completion_retry",
                            model_id=model,
                            attempt_index=len(usage_events),
                            status="succeeded",
                            started_at=retry_started_at,
                            completed_at=datetime.datetime.utcnow(),
                            prompt_tokens=pt,
                            completion_tokens=ct,
                            cached_tokens=cache,
                            prompt=retry_kwargs.get("messages", messages),
                            completion=content,
                        )
                    )
                    prompt_tokens += pt
                    completion_tokens += ct
                    cached_tokens += cache
                    if content and agent_turn is None:
                        yield _sse_delta_chunk(content)
                    if persister and content and agent_turn is None:
                        try:
                            await persister.on_content(collected_content)
                        except Exception:
                            await db.rollback()
                            persister.reset_persist_state()
                    await _compute_cost()
                    if agent_turn is not None:
                        if agent_resource_subject is None:
                            raise AgentRuntimeUnavailable(
                                "Agent authorization context is unavailable"
                            )
                        agent_review = await finalize_agent_completion(
                            plan=agent_turn.plan,
                            output_text=collected_content,
                            resource_subject=agent_resource_subject,
                        )
                        reviewed_content = (
                            agent_review.display_text
                            if agent_review.status == "ready"
                            else agent_review.safe_response
                        )
                        collected_content = reviewed_content or (
                            "This Agent response could not be displayed safely."
                        )
                        if persister:
                            persister.set_completion_metadata(
                                {
                                    "agentStatus": (
                                        "succeeded"
                                        if agent_review.status == "ready"
                                        else "blocked"
                                    ),
                                    "completionReasonCode": agent_review.reason_code,
                                    "citations": _agent_citation_metadata(
                                        agent_turn,
                                        agent_review,
                                    ),
                                }
                            )
                            try:
                                await persister.on_content(collected_content)
                            except Exception:
                                await db.rollback()
                                persister.reset_persist_state()
                        yield _sse_delta_chunk(collected_content)
                        agent_output_displayed = True
                except Exception as retry_exc:
                    usage_events.append(
                        capture_usage_event(
                            None,
                            ai_model=ai_model,
                            provider_type=provider_type,
                            service_type="llm",
                            operation_name="chat_completion_retry",
                            model_id=model,
                            attempt_index=len(usage_events),
                            status="failed",
                            started_at=retry_started_at,
                            completed_at=datetime.datetime.utcnow(),
                            prompt=retry_kwargs.get("messages", messages),
                            completion="",
                            error_message=str(retry_exc),
                        )
                    )
                    success = False
                    error_message = _format_provider_error(retry_exc, provider)[:500]
                    yield f"data: {json.dumps({'error': error_message})}\n\n".encode()
            else:
                success = False
                error_message = _format_provider_error(exc, provider)[:500]
                yield f"data: {json.dumps({'error': error_message})}\n\n".encode()
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
            if capacity_heartbeat_task is not None:
                capacity_heartbeat_task.cancel()
                await asyncio.gather(
                    capacity_heartbeat_task,
                    return_exceptions=True,
                )
            try:
                await _release_capacity_permit()
            except Exception:
                logger.exception("Failed to release Code Interpreter capacity permit")
            if persister:
                try:
                    await persister.finalize(
                        success=success,
                        error_message=error_message,
                    )
                except Exception:
                    await db.rollback()
            if stream_end_at is not None:
                elapsed_ms = (stream_end_at - generation_start) * 1000
            else:
                elapsed_ms = (time.perf_counter() - generation_start) * 1000
            # Usage/cost accounting is logged in an INDEPENDENT session so that a
            # persister rollback (which reverts the assistant message content)
            # cannot also drop the RequestLog / budget increment — otherwise a
            # user could be charged for a response whose stored message was
            # lost, or conversely get a response for free. This decouples the
            # two concerns (message persistence vs cost accounting).
            accounting_key = (
                f"chat:{stream_reservation_id}"
                if stream_reservation_id
                else (
                    f"chat:{usage_events[0].idempotency_key}" if usage_events else None
                )
            )
            if user_id and injected_memory_ids:
                try:
                    async with AsyncSessionLocal() as mem_db:
                        await record_memory_usage(
                            mem_db, int(user_id), injected_memory_ids
                        )
                        await mem_db.commit()
                except Exception:
                    logger.exception("Failed to record memory usage")
            if project_memory_project_id and injected_project_memory_ids:
                try:
                    from app.services.project_memory_service import (
                        record_project_memory_usage,
                    )

                    async with AsyncSessionLocal() as mem_db:
                        await record_project_memory_usage(
                            mem_db,
                            project_memory_project_id,
                            injected_project_memory_ids,
                        )
                        await mem_db.commit()
                except Exception:
                    logger.exception("Failed to record project memory usage")

            stream_request_log_id: int | None = None

            async def _persist_stream_usage() -> int | None:
                for attempt in range(3):
                    try:
                        async with AsyncSessionLocal() as log_db:
                            log_id = await log_usage(
                                log_db,
                                user_id=user_id,
                                username=username,
                                model_id=model,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                cached_tokens=cached_tokens,
                                total_cost_usd=total_cost,
                                response_time_ms=elapsed_ms,
                                prompt_language=prompt_lang,
                                source_ip=request.client.host
                                if request.client
                                else None,
                                source=source,
                                success=success,
                                error_message=error_message,
                                alpha_router_api_key_id=alpha_router_api_key_id,
                                user_api_key_id=user_api_key_id,
                                client_app=client_app,
                                budget_reservation_id=stream_reservation_id,
                                usage_events=usage_events,
                                operation_type="chat",
                                operation_idempotency_key=accounting_key,
                                project_id=project_id_for_billing,
                            )
                            chat_session_id = str(
                                body.get("chat_session_id") or ""
                            ).strip()
                            assistant_cid = str(
                                body.get("assistant_client_message_id") or ""
                            ).strip()
                            if (
                                log_id
                                and success
                                and source == "alpha_router_chat"
                                and user_id
                                and chat_session_id
                            ):
                                from app.services.user_chat_storage_service import (
                                    attach_request_log_id_to_chat_message,
                                )

                                await attach_request_log_id_to_chat_message(
                                    log_db,
                                    int(user_id),
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
                        # The hold stays "held" until TTL: the one signal ops
                        # has that money is stuck.
                        increment("budget_hold_leak")
                        logger.exception(
                            "Chat usage settlement failed after retries; "
                            "reservation remains held for recovery"
                        )
                return None

            stream_request_log_id = await _persist_stream_usage()
            agent_terminal_status: str | None = None
            if agent_turn is not None:
                if was_cancelled or client_disconnected:
                    agent_terminal_status = "cancelled"
                elif not success:
                    agent_terminal_status = "failed"
                elif agent_review is not None and agent_review.status == "blocked":
                    agent_terminal_status = "blocked"
                else:
                    agent_terminal_status = "succeeded"

                async def _persist_agent_finalization() -> None:
                    for attempt in range(3):
                        try:
                            async with AsyncSessionLocal() as agent_db:
                                await finalize_agent_run(
                                    agent_db,
                                    run_id=agent_turn.run_id,
                                    status=agent_terminal_status or "failed",
                                    review=agent_review,
                                    request_log_id=stream_request_log_id,
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens,
                                    cached_tokens=cached_tokens,
                                    total_cost_usd=total_cost,
                                    provider_latency_ms=max(0, int(elapsed_ms)),
                                    total_latency_ms=max(
                                        0,
                                        int(
                                            elapsed_ms
                                            + agent_turn.plan.total_planning_latency_ms
                                        ),
                                    ),
                                    output_displayed=agent_output_displayed,
                                    error_code=(
                                        agent_review.reason_code
                                        if agent_terminal_status == "blocked"
                                        and agent_review is not None
                                        else (
                                            "client_disconnected"
                                            if agent_terminal_status == "cancelled"
                                            else (
                                                "provider_error"
                                                if agent_terminal_status == "failed"
                                                else None
                                            )
                                        )
                                    ),
                                    error_message=(
                                        error_message
                                        if agent_terminal_status
                                        in {"failed", "cancelled"}
                                        else None
                                    ),
                                )
                                await agent_db.commit()
                            return
                        except Exception:
                            if attempt < 2:
                                await asyncio.sleep(0.1 * (attempt + 1))
                                continue
                            logger.exception(
                                "Agent run finalization failed after retries run=%s",
                                agent_turn.run_id,
                            )

                await _persist_agent_finalization()

            response_metadata: dict[str, object] = {}
            if (
                not was_cancelled
                and success
                and stream_request_log_id
                and source == "alpha_router_chat"
            ):
                response_metadata["request_log_id"] = int(stream_request_log_id)
            if agent_turn is not None and not was_cancelled:
                response_metadata.update(
                    {
                        "agent_run_id": agent_turn.run_id,
                        **_agent_identity_metadata(agent_turn),
                        "agent_status": agent_terminal_status,
                        "routing_outcome": agent_turn.plan.routing_outcome,
                    }
                )
                if agent_review is not None:
                    response_metadata["completion_reason_code"] = (
                        agent_review.reason_code
                    )
                    citations = _agent_citation_metadata(agent_turn, agent_review)
                    if citations:
                        response_metadata["citations"] = citations
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


async def _close_upstream_stream(response) -> None:
    """Best-effort close of a LiteLLM stream wrapper and its underlying iterator."""
    seen: set[int] = set()
    for target in (response, getattr(response, "completion_stream", None)):
        if target is None or id(target) in seen:
            continue
        seen.add(id(target))
        aclose = getattr(target, "aclose", None)
        if aclose is None:
            continue
        try:
            result = aclose()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.debug("Ignoring error while closing upstream stream", exc_info=True)


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
            except Exception:
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
            float(event.quote.final_cost_usd)
            for event in usage_events
            if event.quote.final_cost_usd is not None
        )
        if hasattr(response, "model_dump"):
            payload = response.model_dump()
        else:
            payload = dict(response)
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
                error_message=str(exc),
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
