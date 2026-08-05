"""
OpenAI-compatible proxy with async streaming, cancellation, and prompt caching.
Costs are taken from provider usage objects — never adjusted by Alpha Router.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator

import litellm
from fastapi import HTTPException, Request
from litellm import acompletion, aembedding
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import effective_redis_url, get_settings
from app.database import AsyncSessionLocal
from app.core.language_detect import detect_prompt_language
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services.budget_reservation_service import (
    estimate_chat_hold,
    estimate_embedding_hold,
    reservation_key,
    reserve,
    settle,
)
from app.services.prompt_cache_service import apply_prompt_cache_breakpoints
from app.services.chat_tools_service import augment_messages_with_tools, parse_tools_config
from app.services.code_interpreter_service import (
    MAX_CODE_ITERATIONS,
    extract_last_python_block,
    format_code_output_for_chat,
    run_python_sandbox,
    workspace_files_from_messages,
)
from app.services.chat_completion_persistence import persister_from_body
from app.services.llm_providers import litellm_model_for_provider, resolve_litellm_provider
from app.services.secret_crypto import decrypt_secret

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

def _apply_litellm_provider_kwargs(kwargs: dict, provider_type: str | None, model_id: str) -> str:
    litellm_model = litellm_model_for_provider(_normalize_model_id(model_id), provider_type)
    kwargs["model"] = litellm_model
    llm_provider = resolve_litellm_provider(provider_type)
    if llm_provider:
        kwargs["custom_llm_provider"] = llm_provider
    return litellm_model


@dataclass
class ResolvedStreamContext:
    ai_model: AIModel
    api_key: str
    base_url: str
    provider_type: str
    model_id: str
    budget_reservation_id: str | None = None


def _normalize_model_id(model_id: str | None) -> str:
    raw = (model_id or "").strip()
    while raw.startswith("~"):
        raw = raw[1:]
    return raw


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
    db: AsyncSession, model_id: str
) -> tuple[AIModel | None, str | None, str | None, str | None]:
    from sqlalchemy import select
    from app.models.connection import Connection

    normalized_input = _normalize_model_id(model_id)
    row: AIModel | None = None
    if isinstance(normalized_input, str) and normalized_input.startswith("model::"):
        try:
            model_pk = int(normalized_input.split("::", 1)[1])
        except Exception:
            model_pk = None
        if model_pk is not None:
            row = (
                await db.execute(
                    select(AIModel).where(AIModel.id == model_pk, AIModel.is_enabled == True)  # noqa: E712
                )
            ).scalars().first()
    if not row:
        row = (
            await db.execute(
                select(AIModel).where(AIModel.external_id == normalized_input, AIModel.is_enabled == True)  # noqa: E712
            )
        ).scalars().first()
    if not row:
        return None, None, None, None
    conn = await db.get(Connection, row.connection_id)
    if not conn or not conn.is_active:
        return None, None, None, None
    return row, decrypt_secret(conn.api_key_encrypted), conn.base_url, conn.provider_type


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
        if isinstance(val, str) and val.strip() and not _message_has_stream_body_read_error(val):
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
        for key in ("cache_read_input_tokens", "prompt_cache_hit_tokens", "cached_tokens"):
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


def _serialize_stream_chunk(chunk) -> str:
    try:
        return chunk.model_dump_json()
    except Exception:
        if hasattr(chunk, "model_dump"):
            return json.dumps(chunk.model_dump(), default=str)
        return json.dumps(chunk, default=str)


async def preflight_stream_chat(
    db: AsyncSession,
    body: dict,
    *,
    user_id: int | None,
    skip_budget: bool,
    alpha_router_api_key_id: int | None = None,
    operation: str = "chat",
    source: str | None = None,
) -> ResolvedStreamContext:
    """Validate budget/key/model while the request DB session is still open."""
    from app.services.model_access_service import resolve_access_subject, user_can_access_model

    selected_model = body.get("model")
    ai_model, api_key, base_url, provider_type = await resolve_model_and_key(db, selected_model)
    if not ai_model or not api_key:
        raise HTTPException(status_code=404, detail=f"Model not enabled: {selected_model}")
    subject = await resolve_access_subject(
        db,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        source=source,
    )
    if not await user_can_access_model(db, ai_model, subject):
        raise HTTPException(status_code=404, detail=f"Model not enabled: {selected_model}")
    hold = None
    if alpha_router_api_key_id or (not skip_budget and user_id):
        estimate = (
            estimate_embedding_hold(ai_model, body)
            if operation == "embedding"
            else estimate_chat_hold(ai_model, body)
        )
        hold = await reserve(
            db,
            user_id=None if alpha_router_api_key_id else user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            amount_usd=estimate,
            operation=operation,
            model_id=ai_model.external_id,
            idempotency_key=reservation_key(body, operation=operation),
        )
    return ResolvedStreamContext(
        ai_model=ai_model,
        api_key=api_key,
        base_url=base_url or "",
        provider_type=provider_type or ai_model.provider_type or "",
        model_id=litellm_model_for_provider(ai_model.external_id, provider_type or ai_model.provider_type),
        budget_reservation_id=hold.id if hold else None,
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
        text("UPDATE users SET budget_used_usd = COALESCE(budget_used_usd, 0) + :cost WHERE id = :uid"),
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
    in_rate = _usable_cost_per_1k(ai_model.input_cost_per_1k)
    out_rate = _usable_cost_per_1k(ai_model.output_cost_per_1k)
    if in_rate is not None and out_rate is not None:
        return _sanitize_cost_usd(
            (prompt_tokens / 1000) * in_rate + (completion_tokens / 1000) * out_rate
        )
    try:
        litellm_model = litellm_model_for_provider(model_id, provider_type or ai_model.provider_type)
        cost_kwargs: dict = {
            "model": litellm_model,
            "prompt": str(messages),
            "completion": completion_text,
        }
        llm_provider = resolve_litellm_provider(provider_type or ai_model.provider_type)
        if llm_provider:
            cost_kwargs["custom_llm_provider"] = llm_provider
        return _sanitize_cost_usd(litellm.completion_cost(**cost_kwargs))
    except Exception:
        return 0.0


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
    client_app: str | None = None,
    budget_reservation_id: str | None = None,
) -> None:
    total_cost_usd = _sanitize_cost_usd(total_cost_usd)
    log_row = RequestLog(
            user_id=user_id,
            username=username,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            total_cost_usd=total_cost_usd,
            response_time_ms=response_time_ms,
            prompt_language=prompt_language,
            source_ip=source_ip,
            source=source,
            client_app=client_app,
            success=success,
            error_message=error_message,
            alpha_router_api_key_id=alpha_router_api_key_id,
            budget_reservation_id=budget_reservation_id,
        )
    db.add(log_row)
    await db.flush()
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
    await db.flush()


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
    resolved: ResolvedStreamContext | None = None,
) -> AsyncIterator[bytes]:
    messages = list(body.get("messages", []))
    tools = parse_tools_config(body)
    prompt_lang = detect_prompt_language(_extract_prompt_text(messages))
    success = True
    error_message = None
    model = body.get("model") or ""

    async with AsyncSessionLocal() as db:
        if resolved is None:
            resolved = await preflight_stream_chat(
                db,
                body,
                user_id=user_id,
                skip_budget=skip_budget,
                alpha_router_api_key_id=alpha_router_api_key_id,
            )
            await db.commit()

        ai_model = resolved.ai_model
        api_key = resolved.api_key
        base_url = resolved.base_url
        provider_type = resolved.provider_type
        model = resolved.model_id

        prompt_tokens = completion_tokens = cached_tokens = 0
        total_cost = 0.0
        collected_content = ""

        completion_kwargs: dict = {
            "messages": messages,
            "stream": True,
            "api_key": api_key,
            "base_url": base_url,
            "caching": True,
        }
        model = _apply_litellm_provider_kwargs(completion_kwargs, provider_type, model)
        provider = (provider_type or ai_model.provider_type or "").lower()
        if provider in ("openai", "azure", "openrouter", "anthropic", "xai"):
            completion_kwargs["stream_options"] = {"include_usage": True}

        messages = await augment_messages_with_tools(db, messages, tools)
        messages = apply_prompt_cache_breakpoints(messages)
        original_messages = list(body.get("messages", []))
        workspace_files = workspace_files_from_messages(original_messages) if tools.code_interpreter else {}
        current_messages = list(messages)
        completion_kwargs["messages"] = current_messages

        # Per-user MCP connectors: expose remote tools to the model and execute
        # any tool_calls it returns. Only when the user opted in via tools.connectors.
        mcp_tools: list[dict] = []
        mcp_provider_map: dict[str, tuple[str, str]] = {}
        if tools.connectors and user_id:
            try:
                from app.services.mcp_client_service import list_tools_for_user

                raw_tools = await list_tools_for_user(db, user_id)
                for t in raw_tools:
                    fn_name = t["function"]["name"]
                    mcp_provider_map[fn_name] = (
                        t["_alpha_router_provider"],
                        t["_alpha_router_tool"],
                    )
                    mcp_tools.append({"type": "function", "function": t["function"]})
                if mcp_tools:
                    completion_kwargs["tools"] = mcp_tools
                    completion_kwargs["tool_choice"] = "auto"
            except Exception:
                logger.exception("connector tool listing failed user=%s", user_id)
        mcp_iterations = 0
        MAX_MCP_ITERATIONS = 3
        generation_start = time.perf_counter()
        stream_end_at: float | None = None

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
                    await persister.prepare()
                except Exception:
                    await db.rollback()
                    persister = None

        async def _compute_cost() -> None:
            nonlocal total_cost, prompt_tokens, completion_tokens
            msgs_for_count = completion_kwargs.get("messages", messages)
            if prompt_tokens == 0 and collected_content:
                try:
                    tc_kwargs: dict = {"messages": msgs_for_count}
                    litellm_model = _apply_litellm_provider_kwargs(tc_kwargs, provider_type, model)
                    prompt_tokens = litellm.token_counter(**tc_kwargs)
                    ct_kwargs: dict = {"model": litellm_model, "text": collected_content}
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

        try:
            code_iterations = 0
            while True:
                response = await acompletion(**completion_kwargs)
                iteration_content = ""
                iteration_tool_calls: list[dict] = []
                client_disconnected = False
                async for chunk in response:
                    stream_end_at = time.perf_counter()
                    if not client_disconnected and await request.is_disconnected():
                        client_disconnected = True
                    if (
                        not client_disconnected
                        and persister
                        and await persister.is_cancel_requested()
                    ):
                        client_disconnected = True
                    pt, ct, cache = _usage_from_chunk(chunk)
                    prompt_tokens, completion_tokens, cached_tokens = _merge_stream_usage(
                        prompt_tokens, completion_tokens, cached_tokens, pt, ct, cache
                    )
                    if chunk.choices and chunk.choices[0].delta.content:
                        delta = chunk.choices[0].delta.content
                        iteration_content += delta
                        collected_content += delta
                        if persister:
                            try:
                                await persister.on_content(collected_content)
                            except Exception:
                                await db.rollback()
                                persister.reset_persist_state()
                    # Accumulate any tool_calls the model emitted (MCP connectors).
                    if chunk.choices and getattr(chunk.choices[0].delta, "tool_calls", None):
                        for tc in chunk.choices[0].delta.tool_calls:
                            idx = getattr(tc, "index", 0) or 0
                            while len(iteration_tool_calls) <= idx:
                                iteration_tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            slot = iteration_tool_calls[idx]
                            if getattr(tc, "id", None):
                                slot["id"] = tc.id
                            fn = tc.function
                            if getattr(fn, "name", None):
                                slot["function"]["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                slot["function"]["arguments"] = (slot["function"]["arguments"] or "") + fn.arguments
                    if not client_disconnected:
                        yield f"data: {_serialize_stream_chunk(chunk)}\n\n".encode()

                pt, ct, cache = _usage_from_stream_wrapper(response)
                prompt_tokens, completion_tokens, cached_tokens = _merge_stream_usage(
                    prompt_tokens, completion_tokens, cached_tokens, pt, ct, cache
                )

                if client_disconnected:
                    break

                # MCP connector tool calls: execute and re-prompt (before code interpreter).
                if (
                    mcp_tools
                    and iteration_tool_calls
                    and mcp_iterations < MAX_MCP_ITERATIONS
                ):
                    from app.services.mcp_client_service import call_tool as mcp_call_tool

                    tool_messages: list[dict] = [{"role": "assistant", "content": iteration_content or None, "tool_calls": iteration_tool_calls}]
                    for tc in iteration_tool_calls:
                        full_name = tc["function"]["name"]
                        provider_id, tool_name = mcp_provider_map.get(full_name, (full_name.split(".", 1)[0] if "." in full_name else full_name, ""))
                        try:
                            args = json.loads(tc["function"]["arguments"] or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        progress = f"\n\nCalling {provider_id}.{tool_name}…\n\n"
                        collected_content += progress
                        if persister:
                            try:
                                await persister.on_content(collected_content)
                            except Exception:
                                await db.rollback()
                                persister.reset_persist_state()
                        if not client_disconnected:
                            yield _sse_delta_chunk(progress)
                        try:
                            result = await mcp_call_tool(db, user_id, provider_id, tool_name, args)
                            tool_result_text = json.dumps(result, default=str)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("connector tool call failed user=%s tool=%s: %s", user_id, full_name, exc)
                            tool_result_text = f"Error calling {full_name}: {exc}"
                        tool_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result_text})
                    current_messages = apply_prompt_cache_breakpoints(current_messages + tool_messages)
                    completion_kwargs["messages"] = current_messages
                    mcp_iterations += 1
                    continue

                if not tools.code_interpreter or code_iterations >= MAX_CODE_ITERATIONS:
                    break;

                code = extract_last_python_block(iteration_content)
                if not code:
                    break

                try:
                    exec_result = await run_python_sandbox(code, workspace_files)
                except ValueError as exc:
                    exec_result = f"Code interpreter error: {exc}"

                formatted = format_code_output_for_chat(exec_result)
                collected_content += formatted
                if persister:
                    try:
                        await persister.on_content(collected_content)
                    except Exception:
                        await db.rollback()
                        persister.reset_persist_state()
                if not client_disconnected:
                    yield _sse_delta_chunk(formatted)

                current_messages = apply_prompt_cache_breakpoints(
                    current_messages
                    + [
                        {"role": "assistant", "content": iteration_content},
                        {
                            "role": "user",
                            "content": (
                                f"{exec_result}\n\n"
                                "Continue your reply to the user using these results. "
                                "Do not repeat the same code unless necessary."
                            ),
                        },
                    ]
                )
                completion_kwargs["messages"] = current_messages
                code_iterations += 1

            await _compute_cost()
        except Exception as exc:
            if _should_retry_non_stream(provider, exc):
                try:
                    retry_kwargs = dict(completion_kwargs)
                    retry_kwargs["stream"] = False
                    retry_kwargs.pop("stream_options", None)
                    retry_response = await acompletion(**retry_kwargs)
                    stream_end_at = time.perf_counter()
                    content, (pt, ct, cache) = _extract_non_stream_content(retry_response)
                    collected_content = content
                    prompt_tokens, completion_tokens, cached_tokens = _merge_stream_usage(
                        prompt_tokens, completion_tokens, cached_tokens, pt, ct, cache
                    )
                    if content:
                        yield _sse_delta_chunk(content)
                    if persister and content:
                        try:
                            await persister.on_content(collected_content)
                        except Exception:
                            await db.rollback()
                            persister.reset_persist_state()
                    await _compute_cost()
                except Exception as retry_exc:
                    success = False
                    error_message = _format_provider_error(retry_exc, provider)[:500]
                    yield f"data: {json.dumps({'error': error_message})}\n\n".encode()
            else:
                success = False
                error_message = _format_provider_error(exc, provider)[:500]
                yield f"data: {json.dumps({'error': error_message})}\n\n".encode()
        finally:
            if persister:
                try:
                    await persister.finalize(success=success, error_message=error_message)
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
            try:
                async with AsyncSessionLocal() as log_db:
                    await log_usage(
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
                        source_ip=request.client.host if request.client else None,
                        source=source,
                        success=success,
                        error_message=error_message,
                        alpha_router_api_key_id=alpha_router_api_key_id,
                        client_app=client_app,
                        budget_reservation_id=getattr(
                            resolved,
                            "budget_reservation_id",
                            None,
                        ),
                    )
                    await log_db.commit()
            except Exception:
                import logging

                logging.getLogger("app.services.proxy_service").exception(
                    "Chat usage settlement failed; reservation will expire safely"
                )
            yield b"data: [DONE]\n\n"


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
        cached_tokens = cache
        total_cost = _embedding_cost_usd(ai_model, prompt_tokens)
        if hasattr(response, "model_dump"):
            payload = response.model_dump()
        else:
            payload = dict(response)
    except Exception as exc:
        success = False
        error_message = _format_provider_error(exc, provider)[:500]
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
                    client_app=client_app,
                    budget_reservation_id=getattr(
                        resolved,
                        "budget_reservation_id",
                        None,
                    ),
                )
                await log_db.commit()
        except Exception:
            import logging

            logging.getLogger("app.services.proxy_service").exception(
                "Embedding usage settlement failed; reservation will expire safely"
            )

    return payload
