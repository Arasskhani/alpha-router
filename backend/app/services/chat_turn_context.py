"""Build everything a chat turn needs before the first provider call (Phase 4.1).

This is the preparation half of the former ``proxy_service.stream_chat``:
project scope for billing, the Agent plan (including the non-generating
"safe response" short-circuit), the Code Interpreter capacity lease and its
heartbeat, LiteLLM kwargs, tool / profile / memory / project-context prompt
augmentation, cache breakpoints, the workspace inventory and the message
persister. It returns a :class:`TurnContext`; the streaming loop in
``proxy_service.stream_chat`` and ``turn_settlement.settle_turn`` consume it.

If preparation fails after a budget hold or a capacity permit was taken,
:class:`CapacityLease.abandon` gives both back before the error propagates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.model_catalog import AIModel
from app.services.agent_chat_integration_service import PreparedAgentTurn
from app.services.agent_run_service import finalize_agent_run, mark_agent_run_started
from app.services.budget_reservation_service import release
from app.services.chat_completion_persistence import persister_from_body
from app.services.chat_tools_service import ChatToolsConfig, augment_messages_with_tools, parse_tools_config
from app.services.code_interpreter_capacity_service import (
    CapacityPermit,
    heartbeat_code_interpreter_turn,
    release_code_interpreter_turn,
)
from app.services.code_interpreter_service import (
    code_interpreter_workspace_message,
    workspace_files_from_messages,
)
from app.services.model_tool_compatibility_service import is_auto_router_model_id, openrouter_auto_plugin
from app.services.private_mode_service import effective_private_mode, resolve_private_mode
from app.services.project_turn_planner import augment_messages_with_project_context
from app.services.prompt_cache_service import apply_prompt_cache_breakpoints
from app.services.provider_utils import apply_litellm_provider_kwargs, sse_delta_chunk
from app.services.resource_access_service import resolve_resource_access_subject
from app.services.turn_settlement import agent_identity_metadata
from app.services.user_memory_service import augment_messages_with_memory, extract_query_text
from app.services.user_profile_context_service import augment_messages_with_profile

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(slots=True)
class CapacityLease:
    """The Code Interpreter turn permit plus the budget hold taken at preflight.

    ``lost`` is set when the permit heartbeat fails; the stream loop treats it
    like a client disconnect. ``abandon`` returns both resources when
    preparation fails before the stream starts; after the stream the
    settlement releases the permit and ``log_usage`` settles the hold.
    """

    permit: CapacityPermit | None
    stream_reservation_id: str | None
    lost: asyncio.Event = field(default_factory=asyncio.Event)
    heartbeat_task: asyncio.Task | None = None
    abandoned: bool = False

    def start_heartbeat(self) -> None:
        if self.permit is not None and self.heartbeat_task is None:
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        permit = self.permit
        if permit is None:
            return
        heartbeat_seconds = max(5, int(settings.code_interpreter_capacity_heartbeat_seconds or 30))
        while True:
            await asyncio.sleep(heartbeat_seconds)
            try:
                alive = await heartbeat_code_interpreter_turn(permit)
            except HTTPException:
                logger.exception("Code Interpreter capacity heartbeat failed")
                self.lost.set()
                return
            if not alive:
                logger.error("Code Interpreter capacity lease was lost")
                self.lost.set()
                return

    async def release_reservation(self) -> None:
        if not self.stream_reservation_id:
            return
        async with AsyncSessionLocal() as release_db:
            await release(release_db, self.stream_reservation_id)
            await release_db.commit()

    async def release_permit(self) -> None:
        if self.permit is None:
            return
        await release_code_interpreter_turn(self.permit)

    async def abandon(self, reason: str) -> None:
        """Preparation failed: give the hold and the permit back (shielded).

        Idempotent, so an inner handler and the outer guard around the whole
        preparation cannot release the same permit twice — which would free a
        Code Interpreter slot another turn is already holding.
        """
        if self.abandoned:
            return
        self.abandoned = True
        try:
            await asyncio.shield(self.release_reservation())
        except Exception:
            logger.exception("Failed to release chat reservation after %s", reason)
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
        await asyncio.shield(self.release_permit())


@dataclass(slots=True)
class NonGeneratingReply:
    """An Agent plan that is not ``ready``: the safe response is the whole turn."""

    frames: list[bytes]


@dataclass(slots=True)
class TurnContext:
    messages: list[dict]
    current_messages: list[dict]
    completion_kwargs: dict
    tools: ChatToolsConfig
    ai_model: AIModel
    api_key: str | None
    base_url: str
    provider_type: str
    provider: str
    model: str
    workspace_files: dict[str, str]
    lease: CapacityLease
    persister: Any
    agent_turn: PreparedAgentTurn | None
    agent_resource_subject: Any
    project_id_for_billing: str | None
    project_memory_project_id: str | None
    injected_memory_ids: list[str]
    injected_project_memory_ids: list[str]


async def adaptive_openrouter_extra_body(ai_model: AIModel) -> dict | None:
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


async def resolve_private_mode_for_memory(
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


async def resolve_session_project_id(db: AsyncSession, chat_session_id: str | None) -> str | None:
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


async def build_turn_context(  # noqa: C901 -- straight-line preparation moved out of stream_chat; Phase 4 shrinks it further
    db: AsyncSession,
    body: dict,
    resolved,
    *,
    user_id: int | None,
    username: str,
    source: str,
    skip_budget: bool,
    alpha_router_api_key_id: int | None,
) -> TurnContext | NonGeneratingReply:
    messages = list(body.get("messages", []))
    injected_memory_ids: list[str] = []
    injected_project_memory_ids: list[str] = []
    project_memory_project_id: str | None = None
    chat_session_id_for_billing = str(body.get("chat_session_id") or "").strip()
    project_id_for_billing: str | None = None
    if chat_session_id_for_billing:
        from app.models.chat import ChatSession

        sess_row = (
            await db.execute(
                select(ChatSession.id, ChatSession.project_id).where(ChatSession.id == chat_session_id_for_billing)
            )
        ).first()
        if sess_row is not None:
            project_id_for_billing = sess_row[1]
    agent_turn = getattr(resolved, "agent_turn", None)
    if agent_turn is not None:
        body["_agent_run_id"] = agent_turn.run_id
        if agent_turn.plan.status != "ready":
            safe_response = agent_turn.plan.safe_response or "This Agent turn could not be completed safely."
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
                        agent_turn.plan.target.agent.name if agent_turn.plan.target is not None else "Alpharouter"
                    ),
                )
            if persister is not None:
                try:
                    persister.set_completion_metadata(
                        {
                            "agentRunId": agent_turn.run_id,
                            "agentId": agent_turn.plan.selected_agent_id,
                            "agentVersionId": (agent_turn.plan.selected_agent_version_id),
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
            meta_payload = json.dumps(
                {
                    "alpha_router": {
                        "agent_run_id": agent_turn.run_id,
                        **agent_identity_metadata(agent_turn),
                        "agent_status": agent_turn.plan.status,
                        "routing_outcome": agent_turn.plan.routing_outcome,
                    }
                },
                separators=(",", ":"),
            )
            return NonGeneratingReply(
                frames=[sse_delta_chunk(safe_response), f"data: {meta_payload}\n\n".encode(), b"data: [DONE]\n\n"]
            )

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

    stream_reservation_id = getattr(resolved, "budget_reservation_id", None)
    lease = CapacityLease(
        permit=getattr(resolved, "code_interpreter_capacity_permit", None),
        stream_reservation_id=stream_reservation_id,
    )
    lease.start_heartbeat()

    # Everything from here on can raise (provider kwargs, augmentation, the
    # workspace inventory, the persister). The lease is live by now, so any
    # escape has to hand the permit and the budget hold back; abandon() is
    # idempotent, so the handlers inside still report their own reason first.
    try:
        completion_kwargs: dict = {
            "messages": messages,
            "stream": True,
            "api_key": api_key,
            "base_url": base_url,
            "caching": True,
            "timeout": float(getattr(settings, "chat_provider_timeout_seconds", 600.0) or 600.0),
        }
        if agent_turn is not None and agent_turn.plan.policies is not None:
            completion_kwargs["max_tokens"] = agent_turn.plan.policies.model.max_output_tokens
            if agent_turn.plan.policies.model.temperature is not None:
                completion_kwargs["temperature"] = agent_turn.plan.policies.model.temperature
        model = apply_litellm_provider_kwargs(completion_kwargs, provider_type, model)
        provider = (provider_type or ai_model.provider_type or "").lower()
        if tools.code_interpreter and provider == "openrouter" and is_auto_router_model_id(ai_model.external_id):
            auto_router_extra_body = await adaptive_openrouter_extra_body(ai_model)
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
                await lease.abandon("tool setup error")
                raise
        private_mode = await resolve_private_mode_for_memory(db, body, user_id=user_id)
        if agent_turn is None:
            try:
                chat_session_id = str(body.get("chat_session_id") or "").strip() or None
                session_project_id = await resolve_session_project_id(db, chat_session_id)
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
                    client_project_id=str(body.get("project_id") or body.get("projectId") or "").strip() or None,
                    query=extract_query_text(messages),
                    injected_memory_ids=injected_project_memory_ids,
                )
            except BaseException:
                await lease.abandon("memory setup error")
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
            else (workspace_files_from_messages(original_messages) if tools.code_interpreter else {})
        )
        if tools.code_interpreter and workspace_files:
            inventory = code_interpreter_workspace_message(workspace_files)
            if inventory:
                messages = list(messages)
                if messages and messages[0].get("role") == "system" and isinstance(messages[0].get("content"), str):
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
                                "agentVersionId": (agent_turn.plan.selected_agent_version_id),
                                "agentName": (
                                    agent_turn.plan.target.agent.name if agent_turn.plan.target is not None else None
                                ),
                                "routingOutcome": agent_turn.plan.routing_outcome,
                            }
                        )
                    await persister.prepare()
                except Exception:  # noqa: BLE001 -- session is rolled back and the caller continues without the write
                    await db.rollback()
                    persister = None

        return TurnContext(
            messages=messages,
            current_messages=current_messages,
            completion_kwargs=completion_kwargs,
            tools=tools,
            ai_model=ai_model,
            api_key=api_key,
            base_url=base_url,
            provider_type=provider_type,
            provider=provider,
            model=model,
            workspace_files=workspace_files,
            lease=lease,
            persister=persister,
            agent_turn=agent_turn,
            agent_resource_subject=agent_resource_subject,
            project_id_for_billing=project_id_for_billing,
            project_memory_project_id=project_memory_project_id,
            injected_memory_ids=injected_memory_ids,
            injected_project_memory_ids=injected_project_memory_ids,
        )
    except BaseException:
        await lease.abandon("turn preparation error")
        raise


# Historical names, still imported by proxy_service and patched by tests.
_adaptive_openrouter_extra_body = adaptive_openrouter_extra_body
_resolve_private_mode_for_memory = resolve_private_mode_for_memory
_resolve_session_project_id = resolve_session_project_id
