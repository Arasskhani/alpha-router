"""End-user Agent catalog, citation details, and handoff decisions."""

from __future__ import annotations

import asyncio
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user
from app.config import get_settings
from app.database import get_db
from app.models.agent import Agent, AgentHandoffEvent, AgentVersion
from app.models.agent_runtime import AgentCitation, AgentRun
from app.models.chat import ChatSession
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.models.user import User
from app.services.agent_handoff_service import (
    AgentHandoffConflict,
    AgentHandoffError,
    accept_agent_handoff,
    complete_agent_handoff,
    decline_agent_handoff,
)
from app.services.agent_policy_service import (
    AgentPolicyValidationError,
    resolve_agent_policies,
)
from app.services.knowledge_crypto_service import decrypt_bytes
from app.services.knowledge_object_store import default_knowledge_object_store
from app.services.list_bounds import ADMIN_LIST_HARD_CAP
from app.services.object_storage_service import ObjectNotFoundError
from app.services.resource_access_service import (
    filter_agents_for_subject,
    resolve_resource_access_subject,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _catalog_payload(agent: Agent, version: AgentVersion) -> dict:
    try:
        policies = resolve_agent_policies(version)
        disclaimer = version.disclaimer_policy or {}
        routing = version.routing_policy or {}
        locale = version.locale_policy or {}
        citations_required = bool(policies.retrieval.citations_required)
    except AgentPolicyValidationError:
        disclaimer = {}
        routing = {}
        locale = {}
        citations_required = True
    return {
        "id": agent.id,
        "slug": agent.slug,
        "name": agent.name,
        "description": agent.description,
        "icon": agent.icon,
        "category": agent.category,
        "sort_order": agent.sort_order,
        "version_id": version.id,
        "version_number": version.version_number,
        "disclaimer": disclaimer,
        "routing": {
            "enabled": bool(routing.get("enabled", True)),
            "explicit_only": bool(routing.get("explicit_only", False)),
            "description": routing.get("description"),
            "examples": routing.get("examples") or [],
        },
        "locale": locale,
        "citations_required": citations_required,
    }


async def _catalog_rows(db: AsyncSession, user: User) -> list[tuple[Agent, AgentVersion]]:
    rows = (
        await db.execute(
            select(Agent, AgentVersion)
            .join(
                AgentVersion,
                (
                    (AgentVersion.agent_id == Agent.id)
                    & (AgentVersion.active_scope_key == ("agent:" + Agent.id))
                    & (AgentVersion.status == "published")
                ),
            )
            .where(Agent.status == "active")
            .order_by(Agent.sort_order, Agent.name)
            .limit(ADMIN_LIST_HARD_CAP)
        )
    ).all()
    subject = await resolve_resource_access_subject(db, user_id=user.id)
    allowed = {agent.id for agent in await filter_agents_for_subject(db, [agent for agent, _version in rows], subject)}
    return [(agent, version) for agent, version in rows if agent.id in allowed]


@router.get("")
async def list_available_agents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
):
    rows = await _catalog_rows(db, user)
    items = [_catalog_payload(agent, version) for agent, version in rows]
    return {
        "items": items,
        "auto_route_available": any(not bool((item.get("routing") or {}).get("explicit_only")) for item in items),
    }


@router.get("/{agent_slug}")
async def get_available_agent(
    agent_slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
):
    for agent, version in await _catalog_rows(db, user):
        if agent.slug == agent_slug.strip().lower():
            return _catalog_payload(agent, version)
    raise HTTPException(404, "Agent not available")


@router.get("/citations/{run_id}/{citation_id}")
async def get_citation_detail(
    run_id: str,
    citation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
):
    run = await db.get(AgentRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(404, "Citation not found")
    citation = (
        await db.execute(
            select(AgentCitation).where(
                AgentCitation.agent_run_id == run.id,
                AgentCitation.citation_id == citation_id,
            )
        )
    ).scalar_one_or_none()
    if citation is None:
        raise HTTPException(404, "Citation not found")
    # Run ownership already authorized this evidence during the agent turn.
    # Do not re-require direct Knowledge Base ACL for Open source / Download.
    knowledge_base = await db.get(KnowledgeBase, citation.knowledge_base_id) if citation.knowledge_base_id else None
    if knowledge_base is None:
        raise HTTPException(404, "Citation not found")
    return {
        "citation_id": citation.citation_id,
        "title": citation.title,
        "file_name": citation.file_name,
        "mime_type": citation.mime_type,
        "page_number": citation.page_number,
        "section": citation.section,
        "authority": citation.authority,
        "classification": citation.classification,
        "effective_from": citation.effective_from,
        "effective_to": citation.effective_to,
        "document_id": citation.document_id,
        "document_version_id": citation.document_version_id,
        "knowledge_base_id": citation.knowledge_base_id,
        "knowledge_base_name": knowledge_base.name,
        "download_url": (
            f"/api/agents/citations/{run.id}/{citation.citation_id}/content" if citation.document_version_id else None
        ),
    }


@router.get("/citations/{run_id}/{citation_id}/content")
async def download_citation_source(
    run_id: str,
    citation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
):
    detail = await get_citation_detail(run_id, citation_id, db, user)
    version_id = detail.get("document_version_id")
    version = await db.get(KnowledgeDocumentVersion, version_id) if version_id else None
    if version is None or not version.storage_key:
        raise HTTPException(404, "Citation source not found")
    # Retrieval only ever exposed excerpts; this hands over the entire original
    # file, and it did so on run ownership alone. A citation is therefore a
    # permanent grant: revoking a document version, or deleting the document,
    # left every past run's download working. Revocation has to mean something
    # at the moment of the download, not at the moment of the turn.
    document = await db.get(KnowledgeDocument, version.document_id) if version.document_id else None
    if (
        version.revoked_at is not None
        or document is None
        or document.revoked_at is not None
        or document.deleted_at is not None
    ):
        raise HTTPException(404, "Citation source is no longer available")
    settings = get_settings()
    store = default_knowledge_object_store()
    try:
        envelope = await store.get(
            version.storage_key,
            max_bytes=settings.knowledge_max_upload_bytes + 64 * 1024,
        )
        data = await asyncio.to_thread(
            decrypt_bytes,
            envelope,
            associated_data=f"document-version:{version.id}",
        )
    except (FileNotFoundError, ObjectNotFoundError, ValueError):
        raise HTTPException(404, "Citation source not found") from None
    safe_name = (version.file_name or "source").replace('"', "").replace("\r", "").replace("\n", "")
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in safe_name) or "source"
    return Response(
        content=data,
        media_type=version.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{ascii_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/handoffs/pending")
async def list_pending_handoffs(
    session_id: str = Query(min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
):
    session = await db.get(ChatSession, session_id)
    if session is None or int(session.user_id) != int(user.id):
        raise HTTPException(404, "Chat session not found")
    rows = (
        (
            await db.execute(
                select(AgentHandoffEvent)
                .where(
                    AgentHandoffEvent.session_id == session_id,
                    AgentHandoffEvent.status == "proposed",
                )
                .order_by(AgentHandoffEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"items": []}
    from_ids = {row.from_agent_id for row in rows if row.from_agent_id}
    to_ids = {row.to_agent_id for row in rows if row.to_agent_id}
    agents = (await db.execute(select(Agent).where(Agent.id.in_(from_ids | to_ids)))).scalars().all()
    names = {agent.id: agent.name for agent in agents}
    # The handoff service performs authoritative ownership and ACL checks on decision.
    return {
        "items": [
            {
                "id": row.id,
                "turn_id": row.turn_id,
                "from_agent_id": row.from_agent_id,
                "from_agent_name": names.get(row.from_agent_id),
                "to_agent_id": row.to_agent_id,
                "to_agent_name": names.get(row.to_agent_id),
                "reason": row.reason,
                "consent_required": bool(row.consent_required),
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.post("/handoffs/{event_id}/accept")
async def accept_handoff(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
):
    subject = await resolve_resource_access_subject(db, user_id=user.id)
    try:
        event = await accept_agent_handoff(
            db,
            event_id=event_id,
            actor_user_id=user.id,
            subject=subject,
        )
        event, resolved_target = await complete_agent_handoff(
            db,
            event_id=event.id,
            actor_user_id=user.id,
            subject=subject,
        )
        target = resolved_target.agent
        session = await db.get(ChatSession, event.session_id)
        if session is None or int(session.user_id) != int(user.id):
            raise AgentHandoffError("Chat session is unavailable")
        session.current_agent_id = target.id
        session.current_agent_version_id = resolved_target.version.id
        session.agent_selected_at = datetime.datetime.utcnow()
        await db.commit()
    except (AgentHandoffError, AgentHandoffConflict, PermissionError) as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {
        "id": event.id,
        "status": event.status,
        "agent_id": target.id,
        "agent_slug": target.slug,
        "agent_name": target.name,
    }


@router.post("/handoffs/{event_id}/decline")
async def decline_handoff(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
):
    subject = await resolve_resource_access_subject(db, user_id=user.id)
    try:
        event = await decline_agent_handoff(
            db,
            event_id=event_id,
            actor_user_id=user.id,
            subject=subject,
        )
        await db.commit()
    except (AgentHandoffError, AgentHandoffConflict, PermissionError) as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"id": event.id, "status": event.status}
