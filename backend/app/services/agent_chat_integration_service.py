"""Backward-compatible Agent request parsing and chat turn preparation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession
from app.services.agent_run_service import persist_agent_plan
from app.services.agent_runtime_service import (
    AgentTurnPlan,
    QdrantAgentKnowledgeRetriever,
    plan_agent_turn,
)
from app.services.knowledge_embedding_service import (
    CatalogKnowledgeEmbeddingBackend,
)
from app.services.knowledge_rerank_service import DeterministicKnowledgeReranker
from app.services.model_access_service import resolve_access_subject
from app.services.qdrant_service import QdrantVectorService
from app.services.resource_access_service import resolve_resource_access_subject
from app.services.project_turn_planner import augment_messages_with_project_context
from app.services.user_chat_storage_service import (
    _owned_or_project_session,
    create_chat_session,
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AgentRequestError(ValueError):
    """Agent request extension is malformed or internally inconsistent."""


@dataclass(frozen=True)
class AgentRequestOptions:
    agent_id: str | None
    agent_slug: str | None
    pinned_version_id: str | None
    auto_route: bool
    include_citations: bool
    external_session_id: str | None


@dataclass(frozen=True)
class PreparedAgentTurn:
    plan: AgentTurnPlan
    options: AgentRequestOptions
    run_id: str
    chat_session_id: str | None


def _optional_identifier(value: Any, *, label: str, maximum: int = 128) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    if len(clean) > maximum or not _IDENTIFIER_RE.fullmatch(clean):
        raise AgentRequestError(f"{label} is invalid")
    return clean


def _strict_bool(value: Any, *, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise AgentRequestError(f"{label} must be a JSON boolean")
    return value


def parse_agent_request(body: dict[str, Any]) -> AgentRequestOptions | None:
    """Parse app fields or the additive OpenAI-compatible ``alpharouter`` block."""

    extension = body.get("alpharouter")
    if extension is not None and not isinstance(extension, dict):
        raise AgentRequestError("alpharouter must be a JSON object")
    extension = dict(extension or {})
    top_level_enabled = any(
        key in body
        for key in (
            "agent_id",
            "agent_slug",
            "agent_version_id",
            "agent_auto_route",
            "include_citations",
        )
    )
    if not extension and not top_level_enabled:
        return None

    agent_value = extension.get("agent")
    nested: dict[str, Any] = {}
    if isinstance(agent_value, str):
        nested["slug"] = agent_value
    elif isinstance(agent_value, dict):
        nested = dict(agent_value)
    elif agent_value is not None:
        raise AgentRequestError("alpharouter.agent must be a slug or JSON object")

    agent_id = _optional_identifier(
        body.get("agent_id", nested.get("id")),
        label="agent_id",
        maximum=36,
    )
    raw_slug = body.get("agent_slug", nested.get("slug"))
    agent_slug = str(raw_slug or "").strip().lower() or None
    if agent_slug is not None and (len(agent_slug) > 128 or not _SLUG_RE.fullmatch(agent_slug)):
        raise AgentRequestError("agent_slug is invalid")
    if agent_id and agent_slug:
        raise AgentRequestError("Only one of agent_id or agent_slug may be supplied")

    pinned_version_id = _optional_identifier(
        body.get(
            "agent_version_id",
            nested.get("version_id", extension.get("agent_version_id")),
        ),
        label="agent_version_id",
        maximum=36,
    )
    if pinned_version_id and not (agent_id or agent_slug):
        raise AgentRequestError("agent_version_id requires an explicit Agent selection")
    auto_route = _strict_bool(
        body.get("agent_auto_route", extension.get("auto_route")),
        label="agent_auto_route",
        default=not bool(agent_id or agent_slug),
    )
    if auto_route and (agent_id or agent_slug):
        raise AgentRequestError("agent_auto_route cannot be combined with an explicit Agent")
    if not agent_id and not agent_slug and not auto_route:
        return None
    include_citations = _strict_bool(
        body.get("include_citations", extension.get("include_citations")),
        label="include_citations",
        default=True,
    )
    external_session_id = _optional_identifier(
        extension.get("session_id"),
        label="alpharouter.session_id",
    )
    return AgentRequestOptions(
        agent_id=agent_id,
        agent_slug=agent_slug,
        pinned_version_id=pinned_version_id,
        auto_route=auto_route,
        include_citations=include_citations,
        external_session_id=external_session_id,
    )


async def _owned_or_new_chat_session(
    db: AsyncSession,
    *,
    body: dict[str, Any],
    user_id: int | None,
    source: str,
) -> ChatSession | None:
    if source != "alpha_router_chat" or user_id is None:
        return None
    session_id = _optional_identifier(
        body.get("chat_session_id"),
        label="chat_session_id",
        maximum=36,
    )
    if session_id is None:
        return None
    session = (await db.execute(select(ChatSession).where(ChatSession.id == session_id))).scalar_one_or_none()
    if session is not None:
        authorized = await _owned_or_project_session(db, session, user_id, write=True)
        if authorized is None:
            raise AgentRequestError("Chat session is unavailable")
        return authorized
    if not bool(body.get("persist_chat")):
        return None
    try:
        created = await create_chat_session(
            db,
            user_id,
            {
                "id": session_id,
                "title": "New chat",
                "model": str(body.get("model") or ""),
                "project_id": body.get("project_id") or body.get("projectId"),
            },
        )
    except ValueError as exc:
        raise AgentRequestError("Chat session is unavailable") from exc
    if created is None:
        raise AgentRequestError("Chat session could not be created")
    await db.flush()
    return await db.get(ChatSession, session_id)


async def prepare_agent_turn(
    db: AsyncSession,
    *,
    body: dict[str, Any],
    options: AgentRequestOptions,
    user_id: int | None,
    alpha_router_api_key_id: int | None,
    source: str,
    client_app: str | None,
    private_mode: bool = False,
) -> PreparedAgentTurn:
    """Plan and persist one Agent turn before any generation call or budget charge."""

    session = await _owned_or_new_chat_session(
        db,
        body=body,
        user_id=user_id,
        source=source,
    )
    messages = list(body.get("messages") or [])
    if session is not None and session.project_id:
        from app.services.user_memory_service import extract_query_text

        messages = await augment_messages_with_project_context(
            db,
            messages,
            user_id=user_id,
            chat_session_id=session.id,
            client_project_id=str(body.get("project_id") or body.get("projectId") or "").strip() or None,
            query=extract_query_text(messages),
        )
    agent_id = options.agent_id
    agent_slug = options.agent_slug
    pinned_version_id = options.pinned_version_id
    if (
        options.auto_route
        and session is not None
        and not session.project_id
        and session.current_agent_id
        and session.current_agent_version_id
    ):
        agent_id = session.current_agent_id
        pinned_version_id = session.current_agent_version_id

    resource_subject = await resolve_resource_access_subject(
        db,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        source=source,
    )
    model_subject = await resolve_access_subject(
        db,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        source=source,
    )
    qdrant = QdrantVectorService()
    try:
        plan = await plan_agent_turn(
            db,
            messages=messages,
            resource_subject=resource_subject,
            model_subject=model_subject,
            agent_id=agent_id,
            agent_slug=agent_slug,
            pinned_version_id=pinned_version_id,
            private_mode=private_mode,
            # Project threads are shared with teammates: they get project memory
            # only, never the requesting member's personal facts.
            personal_memory_allowed=not (session is not None and session.project_id),
            knowledge_retriever=QdrantAgentKnowledgeRetriever(
                qdrant=qdrant,
                embedding_backend=CatalogKnowledgeEmbeddingBackend(),
                reranker=DeterministicKnowledgeReranker(),
            ),
        )
    finally:
        await qdrant.close()

    run = await persist_agent_plan(
        db,
        plan=plan,
        source=source,
        client_app=client_app,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        chat_session_id=(session.id if session is not None and not private_mode else None),
        external_session_id=options.external_session_id,
        private_mode=private_mode,
    )
    body["_agent_run_id"] = run.id
    return PreparedAgentTurn(
        plan=plan,
        options=options,
        run_id=run.id,
        chat_session_id=(session.id if session is not None and not private_mode else None),
    )
