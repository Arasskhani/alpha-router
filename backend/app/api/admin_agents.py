"""Administrative API for Agent Studio, tools, approvals, and operations."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import (
    _activity_export_response,
    _activity_query_filters,
    _build_scoped_activity,
    activity_explore_opts,
)
from app.api.deps import get_bearer_token, require_agent_permission, require_agents
from app.database import get_db
from app.models.agent import (
    Agent,
    AgentAccessAssignment,
    AgentAuditEvent,
    AgentKnowledgeBinding,
    AgentVersion,
)
from app.models.agent_runtime import AgentRun
from app.models.agent_tool import AgentTool, AgentToolAuditEvent, AgentToolVersion
from app.models.governance import GovernanceAuditEvent
from app.models.knowledge import (
    IngestionJob,
    KnowledgeAuditEvent,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeRelease,
)
from app.models.user import User
from app.services.agent_definition_service import (
    create_agent,
    create_agent_version,
    discard_agent_draft,
    is_purged_agent,
    publish_agent_version,
    purge_agent,
    revoke_agent_knowledge_binding,
    rollback_agent_version,
    submit_agent_version,
    update_agent_draft,
)
from app.services.agent_policy_service import validate_agent_version_policies
from app.services.agent_tool_registry_service import (
    ToolRegistryError,
    create_agent_tool,
    create_agent_tool_version,
    publish_agent_tool_version,
    rollback_agent_tool_version,
    submit_agent_tool_version,
    update_agent_tool_draft,
)
from app.services.resource_access_service import AccessGrant, set_agent_access
from app.services.knowledge_retention_service import LIVE_KNOWLEDGE_DOCUMENT_STATUSES
from app.services.user_role_service import primary_role_for_user, user_bypasses_maker_checker
from app.services import activity_service

router = APIRouter(prefix="/api/admin/agents", tags=["admin-agents"])

_POLICY_FIELDS = frozenset(
    {
        "model_policy",
        "tool_policy",
        "retrieval_policy",
        "memory_policy",
        "profile_policy",
        "routing_policy",
        "escalation_policy",
        "disclaimer_policy",
        "guardrail_policy",
        "locale_policy",
    }
)
_SENSITIVE_KB_LEVELS = frozenset(
    {"hr_confidential", "legal_privileged", "finance_restricted"}
)


class AgentCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=8000)
    icon: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    access_type: str = Field(default="private", pattern=r"^(public|private)$")
    system_prompt: str = Field(min_length=1, max_length=250_000)
    change_summary: str | None = Field(default=None, max_length=8000)
    policies: dict[str, dict] = Field(default_factory=dict)


class AgentIdentityUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    icon: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    sort_order: int | None = Field(default=None, ge=-100_000, le=100_000)
    status: str | None = Field(default=None, pattern=r"^(draft|active|archived)$")


class AgentVersionCreateBody(BaseModel):
    clone_version_id: str | None = Field(default=None, max_length=36)
    system_prompt: str | None = Field(default=None, max_length=250_000)
    change_summary: str | None = Field(default=None, max_length=8000)
    policies: dict[str, dict] = Field(default_factory=dict)


class AgentVersionUpdateBody(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=250_000)
    change_summary: str | None = Field(default=None, max_length=8000)
    policies: dict[str, dict] = Field(default_factory=dict)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class AccessGrantBody(BaseModel):
    target_type: str = Field(pattern=r"^(user|group|department|role)$")
    target: int | str
    effect: str = Field(default="allow", pattern=r"^(allow|deny)$")


class AgentAccessBody(BaseModel):
    access_type: str = Field(pattern=r"^(public|private)$")
    grants: list[AccessGrantBody] = Field(default_factory=list, max_length=5000)


class AgentDeleteBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    mode: str = Field(default="purge", pattern=r"^(archive|purge|purge_later)$")
    confirm_name: str | None = Field(default=None, max_length=255)


class KnowledgeBindingBody(BaseModel):
    knowledge_base_id: str = Field(min_length=1, max_length=36)
    release_mode: str = Field(default="latest", pattern=r"^(latest|pinned)$")
    pinned_release_id: str | None = Field(default=None, max_length=36)
    retrieval_policy: dict = Field(default_factory=dict)


class ToolCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=8000)
    handler_key: str = Field(min_length=1, max_length=128)
    input_schema: dict
    output_schema: dict
    effect_type: str = Field(default="read_only")
    required_permission: str | None = Field(default=None, max_length=128)
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_retries: int = Field(default=0, ge=0, le=3)
    idempotent: bool = True
    approval_mode: str = Field(default="never")
    secret_ref: str | None = Field(default=None, max_length=255)
    model_compatibility: dict = Field(default_factory=dict)
    rate_limit_policy: dict = Field(default_factory=dict)
    cost_policy: dict = Field(default_factory=dict)
    change_summary: str | None = Field(default=None, max_length=8000)


class ToolVersionBody(BaseModel):
    input_schema: dict
    output_schema: dict
    handler_key: str = Field(min_length=1, max_length=128)
    effect_type: str = Field(default="read_only")
    required_permission: str | None = Field(default=None, max_length=128)
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_retries: int = Field(default=0, ge=0, le=3)
    idempotent: bool = True
    approval_mode: str = Field(default="never")
    secret_ref: str | None = Field(default=None, max_length=255)
    model_compatibility: dict = Field(default_factory=dict)
    rate_limit_policy: dict = Field(default_factory=dict)
    cost_policy: dict = Field(default_factory=dict)
    change_summary: str | None = Field(default=None, max_length=8000)


def _clean_policies(value: dict[str, dict]) -> dict[str, dict]:
    unknown = set(value) - _POLICY_FIELDS
    if unknown:
        raise HTTPException(400, f"Unknown Agent policy fields: {sorted(unknown)}")
    if any(not isinstance(policy, dict) for policy in value.values()):
        raise HTTPException(400, "Every Agent policy must be a JSON object")
    return {key: dict(policy) for key, policy in value.items()}


def _version_payload(version: AgentVersion, *, include_prompt: bool = True) -> dict:
    payload: dict[str, Any] = {
        "id": version.id,
        "agent_id": version.agent_id,
        "version_number": version.version_number,
        "status": version.status,
        "fingerprint": version.fingerprint,
        "change_summary": version.change_summary,
        "created_by_user_id": version.created_by_user_id,
        "published_by_user_id": version.published_by_user_id,
        "created_at": version.created_at,
        "submitted_at": version.submitted_at,
        "published_at": version.published_at,
        "archived_at": version.archived_at,
        "policies": {
            field: getattr(version, field) or {} for field in sorted(_POLICY_FIELDS)
        },
    }
    if include_prompt:
        payload["system_prompt"] = version.system_prompt
    return payload


def _agent_payload(
    agent: Agent,
    *,
    versions: Iterable[AgentVersion] = (),
    include_prompt: bool = False,
) -> dict:
    version_rows = sorted(versions, key=lambda item: item.version_number, reverse=True)
    active = next(
        (
            version
            for version in version_rows
            if version.status == "published"
            and version.active_scope_key == f"agent:{agent.id}"
        ),
        None,
    )
    return {
        "id": agent.id,
        "slug": agent.slug,
        "name": agent.name,
        "description": agent.description,
        "icon": agent.icon,
        "category": agent.category,
        "status": agent.status,
        "access_type": agent.access_type,
        "acl_version": agent.acl_version,
        "sort_order": agent.sort_order,
        "is_system": bool(agent.is_system),
        "created_by_user_id": agent.created_by_user_id,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "active_version_id": active.id if active else None,
        "active_version_number": active.version_number if active else None,
        "versions": [
            _version_payload(version, include_prompt=include_prompt)
            for version in version_rows
        ],
    }


def _assignment_payload(row: AgentAccessAssignment) -> dict:
    if row.user_id is not None:
        target_type, target = "user", row.user_id
    elif row.group_id is not None:
        target_type, target = "group", row.group_id
    elif row.department is not None:
        target_type, target = "department", row.department
    else:
        target_type, target = "role", row.role_slug
    return {
        "id": row.id,
        "target_type": target_type,
        "target": target,
        "effect": row.effect,
        "assigned_by_user_id": row.assigned_by_user_id,
        "assigned_at": row.assigned_at,
    }


def _binding_payload(
    binding: AgentKnowledgeBinding,
    knowledge_base: KnowledgeBase | None = None,
) -> dict:
    return {
        "id": binding.id,
        "agent_version_id": binding.agent_version_id,
        "knowledge_base_id": binding.knowledge_base_id,
        "knowledge_base_name": knowledge_base.name if knowledge_base else None,
        "knowledge_base_sensitivity": (
            knowledge_base.sensitivity if knowledge_base else None
        ),
        "release_mode": binding.release_mode,
        "pinned_release_id": binding.pinned_release_id,
        "status": binding.status,
        "retrieval_policy": binding.retrieval_policy or {},
        "requested_by_user_id": binding.requested_by_user_id,
        "kb_approved_by_user_id": binding.kb_approved_by_user_id,
        "domain_approved_by_user_id": binding.domain_approved_by_user_id,
        "created_at": binding.created_at,
        "kb_approved_at": binding.kb_approved_at,
        "domain_approved_at": binding.domain_approved_at,
        "published_at": binding.published_at,
    }


def _tool_version_payload(version: AgentToolVersion) -> dict:
    return {
        "id": version.id,
        "tool_id": version.tool_id,
        "version_number": version.version_number,
        "status": version.status,
        "handler_key": version.handler_key,
        "effect_type": version.effect_type,
        "required_permission": version.required_permission,
        "timeout_seconds": version.timeout_seconds,
        "max_retries": version.max_retries,
        "idempotent": bool(version.idempotent),
        "approval_mode": version.approval_mode,
        "has_secret_ref": bool(version.secret_ref),
        "input_schema": version.input_schema or {},
        "output_schema": version.output_schema or {},
        "model_compatibility": version.model_compatibility or {},
        "rate_limit_policy": version.rate_limit_policy or {},
        "cost_policy": version.cost_policy or {},
        "fingerprint": version.fingerprint,
        "change_summary": version.change_summary,
        "created_by_user_id": version.created_by_user_id,
        "submitted_by_user_id": version.submitted_by_user_id,
        "published_by_user_id": version.published_by_user_id,
        "created_at": version.created_at,
        "submitted_at": version.submitted_at,
        "published_at": version.published_at,
    }


def _tool_payload(tool: AgentTool, versions: Iterable[AgentToolVersion]) -> dict:
    rows = sorted(versions, key=lambda item: item.version_number, reverse=True)
    active = next(
        (
            version
            for version in rows
            if version.status == "published"
            and version.active_scope_key == f"tool:{tool.id}"
        ),
        None,
    )
    return {
        "id": tool.id,
        "slug": tool.slug,
        "name": tool.name,
        "description": tool.description,
        "status": tool.status,
        "created_at": tool.created_at,
        "updated_at": tool.updated_at,
        "active_version_id": active.id if active else None,
        "active_version_number": active.version_number if active else None,
        "versions": [_tool_version_payload(version) for version in rows],
    }


async def _scalar_count(db: AsyncSession, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    return int((await db.execute(query)).scalar_one() or 0)


async def _overview_spend_24h(
    db: AsyncSession, since: datetime.datetime
) -> dict[str, Any]:
    """Chat-turn spend for Agent runs in the same 24h window as runtime health."""
    window = AgentRun.created_at >= since
    cost_usd, tokens, turns, billed_turns = (
        await db.execute(
            select(
                func.coalesce(func.sum(AgentRun.total_cost_usd), 0),
                func.coalesce(
                    func.sum(AgentRun.prompt_tokens + AgentRun.completion_tokens),
                    0,
                ),
                func.count(AgentRun.id),
                func.coalesce(
                    func.sum(case((AgentRun.total_cost_usd > 0, 1), else_=0)),
                    0,
                ),
            ).where(window)
        )
    ).one()
    top_rows = (
        await db.execute(
            select(
                AgentRun.agent_id,
                Agent.name,
                func.coalesce(func.sum(AgentRun.total_cost_usd), 0).label("cost_usd"),
                func.count(AgentRun.id).label("turns"),
            )
            .outerjoin(Agent, Agent.id == AgentRun.agent_id)
            .where(window, AgentRun.agent_id.is_not(None))
            .group_by(AgentRun.agent_id, Agent.name)
            .order_by(func.sum(AgentRun.total_cost_usd).desc())
            .limit(3)
        )
    ).all()
    return {
        "cost_usd": float(cost_usd or 0),
        "tokens": int(tokens or 0),
        "turns": int(turns or 0),
        "billed_turns": int(billed_turns or 0),
        "top_agents": [
            {
                "id": row.agent_id,
                "name": row.name or "Unknown Agent",
                "cost_usd": float(row.cost_usd or 0),
                "turns": int(row.turns or 0),
            }
            for row in top_rows
        ],
    }


async def _agent_or_404(db: AsyncSession, agent_id: str) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or is_purged_agent(agent):
        raise HTTPException(404, "Agent not found")
    return agent


async def _version_or_404(db: AsyncSession, version_id: str) -> AgentVersion:
    version = await db.get(AgentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Agent version not found")
    return version


async def _tool_or_404(db: AsyncSession, tool_id: str) -> AgentTool:
    tool = await db.get(AgentTool, tool_id)
    if tool is None:
        raise HTTPException(404, "Tool not found")
    return tool


async def _tool_version_or_404(db: AsyncSession, version_id: str) -> AgentToolVersion:
    version = await db.get(AgentToolVersion, version_id)
    if version is None:
        raise HTTPException(404, "Tool version not found")
    return version


@router.get("/overview")
async def get_agents_overview(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agents),
):
    since = datetime.datetime.now(datetime.UTC).replace(
        tzinfo=None
    ) - datetime.timedelta(hours=24)
    return {
        "agents": {
            "total": await _scalar_count(db, Agent),
            "active": await _scalar_count(db, Agent, Agent.status == "active"),
            "draft": await _scalar_count(db, Agent, Agent.status == "draft"),
            "in_review": await _scalar_count(
                db, AgentVersion, AgentVersion.status == "review"
            ),
        },
        "knowledge": {
            "bases": await _scalar_count(db, KnowledgeBase),
            "documents": await _scalar_count(
                db,
                KnowledgeDocument,
                KnowledgeDocument.status.in_(LIVE_KNOWLEDGE_DOCUMENT_STATUSES),
            ),
            "review": await _scalar_count(
                db,
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.status == "review",
            ),
            "failed_jobs": await _scalar_count(
                db, IngestionJob, IngestionJob.status == "dead"
            ),
        },
        "tools": {
            "total": await _scalar_count(db, AgentTool),
            "active": await _scalar_count(db, AgentTool, AgentTool.status == "active"),
            "in_review": await _scalar_count(
                db, AgentToolVersion, AgentToolVersion.status == "review"
            ),
        },
        "runs_24h": {
            "total": await _scalar_count(db, AgentRun, AgentRun.created_at >= since),
            "succeeded": await _scalar_count(
                db,
                AgentRun,
                AgentRun.created_at >= since,
                AgentRun.status == "succeeded",
            ),
            "blocked": await _scalar_count(
                db,
                AgentRun,
                AgentRun.created_at >= since,
                AgentRun.status == "blocked",
            ),
            "failed": await _scalar_count(
                db,
                AgentRun,
                AgentRun.created_at >= since,
                AgentRun.status == "failed",
            ),
        },
        "spend_24h": await _overview_spend_24h(db, since),
        "pending_approvals": (
            await _scalar_count(db, AgentVersion, AgentVersion.status == "review")
            + await _scalar_count(
                db, AgentToolVersion, AgentToolVersion.status == "review"
            )
            + await _scalar_count(
                db,
                AgentKnowledgeBinding,
                AgentKnowledgeBinding.status.in_(
                    {"pending_kb_approval", "pending_domain_approval"}
                ),
            )
            + await _scalar_count(
                db,
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.status == "review",
            )
        ),
    }


@router.get("")
async def list_agents(
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("agent.read")),
):
    query = select(Agent).order_by(Agent.sort_order, Agent.name)
    if status:
        query = query.where(Agent.status == status)
    agents = [
        agent
        for agent in (await db.execute(query)).scalars().all()
        if not is_purged_agent(agent)
    ]
    if not agents:
        return []
    versions = (
        (
            await db.execute(
                select(AgentVersion)
                .where(AgentVersion.agent_id.in_([agent.id for agent in agents]))
                .order_by(AgentVersion.agent_id, AgentVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    by_agent: dict[str, list[AgentVersion]] = {}
    for version in versions:
        by_agent.setdefault(version.agent_id, []).append(version)
    return [
        _agent_payload(agent, versions=by_agent.get(agent.id, ())) for agent in agents
    ]


@router.post("", status_code=201)
async def create_agent_endpoint(
    body: AgentCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.create")),
):
    try:
        policies = _clean_policies(body.policies)
        agent = await create_agent(
            db,
            name=body.name,
            slug=body.slug,
            description=body.description,
            icon=body.icon,
            category=body.category,
            access_type=body.access_type,
            created_by_user_id=user.id,
        )
        version = await create_agent_version(
            db,
            agent,
            system_prompt=body.system_prompt,
            change_summary=body.change_summary,
            created_by_user_id=user.id,
            **policies,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _agent_payload(agent, versions=(version,), include_prompt=True)


@router.get("/tools")
async def list_tools(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("tool.read")),
):
    tools = (
        (await db.execute(select(AgentTool).order_by(AgentTool.name))).scalars().all()
    )
    if not tools:
        return []
    versions = (
        (
            await db.execute(
                select(AgentToolVersion)
                .where(AgentToolVersion.tool_id.in_([tool.id for tool in tools]))
                .order_by(
                    AgentToolVersion.tool_id,
                    AgentToolVersion.version_number.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    by_tool: dict[str, list[AgentToolVersion]] = {}
    for version in versions:
        by_tool.setdefault(version.tool_id, []).append(version)
    return [_tool_payload(tool, by_tool.get(tool.id, ())) for tool in tools]


def _tool_kwargs(body: ToolCreateBody | ToolVersionBody) -> dict[str, Any]:
    return {
        "input_schema": body.input_schema,
        "output_schema": body.output_schema,
        "handler_key": body.handler_key,
        "effect_type": body.effect_type,
        "required_permission": body.required_permission,
        "timeout_seconds": body.timeout_seconds,
        "max_retries": body.max_retries,
        "idempotent": body.idempotent,
        "approval_mode": body.approval_mode,
        "secret_ref": body.secret_ref,
        "model_compatibility": body.model_compatibility,
        "rate_limit_policy": body.rate_limit_policy,
        "cost_policy": body.cost_policy,
        "change_summary": body.change_summary,
    }


@router.post("/tools", status_code=201)
async def create_tool_endpoint(
    body: ToolCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("tool.manage")),
):
    try:
        tool = await create_agent_tool(
            db,
            name=body.name,
            slug=body.slug,
            description=body.description,
            created_by_user_id=user.id,
        )
        version = await create_agent_tool_version(
            db,
            tool,
            created_by_user_id=user.id,
            **_tool_kwargs(body),
        )
        await db.commit()
    except ToolRegistryError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _tool_payload(tool, (version,))


@router.post("/tools/{tool_id}/versions", status_code=201)
async def create_tool_version_endpoint(
    tool_id: str,
    body: ToolVersionBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("tool.manage")),
):
    tool = await _tool_or_404(db, tool_id)
    try:
        version = await create_agent_tool_version(
            db,
            tool,
            created_by_user_id=user.id,
            **_tool_kwargs(body),
        )
        await db.commit()
    except ToolRegistryError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _tool_version_payload(version)


@router.patch("/tool-versions/{version_id}")
async def update_tool_version_endpoint(
    version_id: str,
    body: ToolVersionBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("tool.manage")),
):
    version = await _tool_version_or_404(db, version_id)
    changes = _tool_kwargs(body)
    change_summary = changes.pop("change_summary")
    try:
        version = await update_agent_tool_draft(
            db,
            version,
            actor_user_id=user.id,
            change_summary=change_summary,
            **changes,
        )
        await db.commit()
    except ToolRegistryError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _tool_version_payload(version)


@router.post("/tool-versions/{version_id}/submit")
async def submit_tool_version_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("tool.manage")),
):
    version = await _tool_version_or_404(db, version_id)
    try:
        version = await submit_agent_tool_version(db, version, actor_user_id=user.id)
        await db.commit()
    except ToolRegistryError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _tool_version_payload(version)


@router.post("/tool-versions/{version_id}/publish")
async def publish_tool_version_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("tool.manage")),
):
    version = await _tool_version_or_404(db, version_id)
    try:
        version = await publish_agent_tool_version(
            db,
            version,
            actor_user_id=user.id,
            allow_same_actor=await user_bypasses_maker_checker(db, user.id),
        )
        await db.commit()
    except ToolRegistryError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _tool_version_payload(version)


@router.post("/tool-versions/{version_id}/rollback")
async def rollback_tool_version_endpoint(
    version_id: str,
    body: ReasonBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("tool.manage")),
):
    version = await _tool_version_or_404(db, version_id)
    try:
        version = await rollback_agent_tool_version(
            db,
            version,
            actor_user_id=user.id,
            reason=body.reason,
        )
        await db.commit()
    except ToolRegistryError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _tool_version_payload(version)


async def _submitter_labels(
    db: AsyncSession,
    user_ids: Iterable[int | None],
) -> dict[int, dict[str, str | None]]:
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.username, User.display_name).where(User.id.in_(ids))
        )
    ).all()
    return {
        int(row.id): {
            "submitted_by_username": row.username,
            "submitted_by_display_name": row.display_name,
        }
        for row in rows
    }


@router.get("/approvals")
async def list_approvals(
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("approval.read")),
):
    items: list[dict[str, Any]] = []
    agent_versions = (
        await db.execute(
            select(AgentVersion, Agent)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(AgentVersion.status == "review")
            .order_by(AgentVersion.submitted_at.desc())
            .limit(limit)
        )
    ).all()
    for version, agent in agent_versions:
        items.append(
            {
                "id": version.id,
                "kind": "agent_version",
                "title": f"{agent.name} v{version.version_number}",
                "status": version.status,
                "submitted_by_user_id": version.created_by_user_id,
                "created_at": version.submitted_at or version.created_at,
                "agent_id": agent.id,
            }
        )

    tool_versions = (
        await db.execute(
            select(AgentToolVersion, AgentTool)
            .join(AgentTool, AgentTool.id == AgentToolVersion.tool_id)
            .where(AgentToolVersion.status == "review")
            .order_by(AgentToolVersion.submitted_at.desc())
            .limit(limit)
        )
    ).all()
    for version, tool in tool_versions:
        items.append(
            {
                "id": version.id,
                "kind": "tool_version",
                "title": f"{tool.name} v{version.version_number}",
                "status": version.status,
                "submitted_by_user_id": version.submitted_by_user_id,
                "created_at": version.submitted_at or version.created_at,
                "tool_id": tool.id,
            }
        )

    bindings = (
        await db.execute(
            select(AgentKnowledgeBinding, KnowledgeBase)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == AgentKnowledgeBinding.knowledge_base_id,
            )
            .where(
                AgentKnowledgeBinding.status.in_(
                    {"pending_kb_approval", "pending_domain_approval"}
                )
            )
            .order_by(AgentKnowledgeBinding.created_at.desc())
            .limit(limit)
        )
    ).all()
    for binding, knowledge_base in bindings:
        items.append(
            {
                "id": binding.id,
                "kind": "knowledge_binding",
                "title": f"Knowledge binding: {knowledge_base.name}",
                "status": binding.status,
                "submitted_by_user_id": binding.requested_by_user_id,
                "created_at": binding.created_at,
                "agent_version_id": binding.agent_version_id,
                "knowledge_base_id": knowledge_base.id,
            }
        )

    documents = (
        await db.execute(
            select(KnowledgeDocumentVersion, KnowledgeDocument)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
            )
            .where(
                KnowledgeDocumentVersion.status == "review",
                KnowledgeDocumentVersion.reviewed_by_user_id.is_(None),
            )
            .order_by(KnowledgeDocumentVersion.created_at.desc())
            .limit(limit)
        )
    ).all()
    for version, document in documents:
        items.append(
            {
                "id": version.id,
                "kind": "document_version",
                "title": f"{document.title} v{version.version_number}",
                "status": version.status,
                "submitted_by_user_id": version.uploaded_by_user_id,
                "created_at": version.created_at,
                "knowledge_base_id": document.knowledge_base_id,
            }
        )
    items.sort(
        key=lambda item: item["created_at"] or datetime.datetime.min, reverse=True
    )
    labels = await _submitter_labels(
        db, (item.get("submitted_by_user_id") for item in items)
    )
    for item in items:
        uid = item.get("submitted_by_user_id")
        extra = labels.get(int(uid)) if uid is not None else None
        if extra:
            item.update(extra)
    return {"items": items[:limit], "total": len(items)}


_ACTIVITY_SOURCES = frozenset(
    {"agent", "tool", "knowledge", "governance", "runtime"}
)


def _activity_since(since_hours: int | None) -> datetime.datetime | None:
    if not since_hours:
        return None
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(
        hours=since_hours
    )


@router.get("/activity")
async def list_activity(
    limit: int = Query(default=100, ge=1, le=500),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    since_hours: int | None = Query(default=None, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("activity.read")),
):
    wanted = (source or "").strip().lower()
    run_status = (status or "").strip().lower()
    if wanted and wanted not in _ACTIVITY_SOURCES:
        raise HTTPException(400, "Unknown activity source")
    if run_status:
        wanted = "runtime"
    since = _activity_since(since_hours)
    events: list[dict[str, Any]] = []
    if not wanted or wanted == "agent":
        query = select(AgentAuditEvent).order_by(AgentAuditEvent.created_at.desc())
        if since is not None:
            query = query.where(AgentAuditEvent.created_at >= since)
        agent_events = ((await db.execute(query.limit(limit)))).scalars().all()
        events.extend(
            {
                "id": event.id,
                "source": "agent",
                "event_type": event.event_type,
                "resource_id": event.agent_id,
                "version_id": event.agent_version_id,
                "actor_user_id": event.actor_user_id,
                "reason": event.reason,
                "payload": event.payload or {},
                "created_at": event.created_at,
            }
            for event in agent_events
        )
    if not wanted or wanted == "tool":
        query = select(AgentToolAuditEvent).order_by(
            AgentToolAuditEvent.created_at.desc()
        )
        if since is not None:
            query = query.where(AgentToolAuditEvent.created_at >= since)
        tool_events = ((await db.execute(query.limit(limit)))).scalars().all()
        events.extend(
            {
                "id": event.id,
                "source": "tool",
                "event_type": event.event_type,
                "resource_id": event.tool_id,
                "version_id": event.tool_version_id,
                "actor_user_id": event.actor_user_id,
                "reason": event.reason,
                "payload": event.payload or {},
                "created_at": event.created_at,
            }
            for event in tool_events
        )
    if not wanted or wanted == "knowledge":
        query = select(KnowledgeAuditEvent).order_by(
            KnowledgeAuditEvent.created_at.desc()
        )
        if since is not None:
            query = query.where(KnowledgeAuditEvent.created_at >= since)
        knowledge_events = ((await db.execute(query.limit(limit)))).scalars().all()
        events.extend(
            {
                "id": event.id,
                "source": "knowledge",
                "event_type": event.event_type,
                "resource_id": event.document_id or event.knowledge_base_id,
                "version_id": event.release_id,
                "actor_user_id": event.actor_user_id,
                "reason": event.reason,
                "payload": event.payload_json or {},
                "created_at": event.created_at,
            }
            for event in knowledge_events
        )
    if not wanted or wanted == "governance":
        query = select(GovernanceAuditEvent).order_by(
            GovernanceAuditEvent.created_at.desc()
        )
        if since is not None:
            query = query.where(GovernanceAuditEvent.created_at >= since)
        governance_events = ((await db.execute(query.limit(limit)))).scalars().all()
        events.extend(
            {
                "id": event.id,
                "source": "governance",
                "event_type": event.event_type,
                "resource_id": event.resource_id,
                "version_id": None,
                "actor_user_id": event.actor_user_id,
                "reason": event.outcome,
                "payload": {
                    **dict(event.payload_json or {}),
                    "resource_type": event.resource_type,
                    "event_hash": event.event_hash,
                    "previous_event_hash": event.previous_event_hash,
                },
                "created_at": event.created_at,
            }
            for event in governance_events
        )
    if not wanted or wanted == "runtime":
        query = (
            select(AgentRun, Agent.name)
            .outerjoin(Agent, Agent.id == AgentRun.agent_id)
            .order_by(AgentRun.created_at.desc())
        )
        if since is not None:
            query = query.where(AgentRun.created_at >= since)
        if run_status:
            query = query.where(AgentRun.status == run_status)
        runs = (await db.execute(query.limit(limit))).all()
        events.extend(
            {
                "id": run.id,
                "source": "runtime",
                "event_type": f"agent.run.{run.status}",
                "resource_id": run.agent_id,
                "version_id": run.agent_version_id,
                "actor_user_id": run.user_id,
                "reason": run.completion_reason_code or run.error_code,
                "payload": {
                    "agent_name": agent_name,
                    "routing_outcome": run.routing_outcome,
                    "retrieval_outcome": run.retrieval_outcome,
                    "latency_ms": run.total_latency_ms,
                    "cost_usd": float(run.total_cost_usd or 0),
                    "output_displayed": bool(run.output_displayed),
                    "private_mode": bool(run.private_mode),
                    "provider_type": run.provider_type,
                    "model_id": run.model_external_id,
                    "egress_manifest": run.egress_manifest or {},
                    "guardrail_events": run.guardrail_events or [],
                },
                "created_at": run.created_at,
            }
            for run, agent_name in runs
        )
    events.sort(
        key=lambda item: item["created_at"] or datetime.datetime.min, reverse=True
    )
    return {"items": events[:limit]}


@router.get("/evaluations")
async def list_evaluation_readiness(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("evaluation.read")),
):
    versions = (
        await db.execute(
            select(AgentVersion, Agent)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(AgentVersion.status.in_({"draft", "review", "published"}))
            .order_by(Agent.name, AgentVersion.version_number.desc())
        )
    ).all()
    run_rows = (
        await db.execute(
            select(
                AgentRun.agent_version_id,
                func.count(AgentRun.id),
                func.sum(
                    func.coalesce(
                        (AgentRun.status == "succeeded").cast(
                            type_=AgentRun.prompt_tokens.type
                        ),
                        0,
                    )
                ),
            )
            .where(AgentRun.agent_version_id.is_not(None))
            .group_by(AgentRun.agent_version_id)
        )
    ).all()
    metrics = {
        version_id: {"run_count": int(total or 0), "succeeded": int(succeeded or 0)}
        for version_id, total, succeeded in run_rows
    }
    items: list[dict[str, Any]] = []
    for version, agent in versions:
        errors: list[str] = []
        try:
            validate_agent_version_policies(version, require_model=True)
        except ValueError as exc:
            errors.append(str(exc))
        stat = metrics.get(version.id, {"run_count": 0, "succeeded": 0})
        run_count = stat["run_count"]
        items.append(
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "agent_version_id": version.id,
                "version_number": version.version_number,
                "status": version.status,
                "ready": not errors,
                "validation_errors": errors,
                "run_count": run_count,
                "success_rate": (
                    round((stat["succeeded"] / run_count) * 100, 2)
                    if run_count
                    else None
                ),
            }
        )
    return {"items": items}


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("agent.read")),
):
    agent = await _agent_or_404(db, agent_id)
    versions = (
        (
            await db.execute(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent.id)
                .order_by(AgentVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    bindings = (
        await db.execute(
            select(AgentKnowledgeBinding, KnowledgeBase)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == AgentKnowledgeBinding.knowledge_base_id,
            )
            .join(
                AgentVersion,
                AgentVersion.id == AgentKnowledgeBinding.agent_version_id,
            )
            .where(AgentVersion.agent_id == agent.id)
            .order_by(
                AgentVersion.version_number.desc(),
                KnowledgeBase.name,
            )
        )
    ).all()
    payload = _agent_payload(agent, versions=versions, include_prompt=True)
    payload["bindings"] = [
        _binding_payload(binding, knowledge_base)
        for binding, knowledge_base in bindings
        if binding.status not in {"revoked", "suspended"}
    ]
    return payload


@router.get("/{agent_id}/activity")
async def agent_usage_activity(
    agent_id: str,
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    api_key_id: int | None = Query(None, ge=1),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    explore: dict = Depends(activity_explore_opts),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_agent_permission("agent.read")),
):
    agent = await _agent_or_404(db, agent_id)
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
        api_key_id=api_key_id,
    )
    payload, options, prompts_card = await _build_scoped_activity(
        db,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        filters=filters,
        explore=explore,
        agent_id=agent.id,
    )
    return {
        **payload,
        **options,
        "prompts": prompts_card,
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "status": agent.status,
        },
        "scope": "agent",
        "model_id": filters["model_id"],
        "filters": filters,
    }


@router.get("/{agent_id}/activity/export")
async def agent_usage_activity_export(
    agent_id: str,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    api_key_id: int | None = Query(None, ge=1),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_agent_permission("agent.read")),
    jwt_token: str = Depends(get_bearer_token),
):
    agent = await _agent_or_404(db, agent_id)
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
        api_key_id=api_key_id,
    )
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-agent-{agent.slug}-activity-{period}",
        scope="agent",
        jwt_token=jwt_token,
        user_role=await primary_role_for_user(db, admin.id),
        period=period,
        prompts_period=prompts_period,
        group_by="model",
        timezone=timezone,
        filters=filters,
        agent_id=agent.id,
    )


@router.patch("/{agent_id}")
async def update_agent_identity(
    agent_id: str,
    body: AgentIdentityUpdateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.edit")),
):
    agent = await _agent_or_404(db, agent_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = " ".join((changes["name"] or "").split())
    for field in ("description", "icon", "category"):
        if field in changes:
            changes[field] = (changes[field] or "").strip() or None
    for key, value in changes.items():
        setattr(agent, key, value)
    agent.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    db.add(
        AgentAuditEvent(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            actor_user_id=user.id,
            event_type="agent.identity.updated",
            payload={"fields": sorted(changes)},
        )
    )
    await db.commit()
    return _agent_payload(agent)


@router.post("/{agent_id}/delete")
async def delete_agent(
    agent_id: str,
    body: AgentDeleteBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.archive")),
):
    agent = await _agent_or_404(db, agent_id)
    if body.mode == "purge":
        if not (body.confirm_name or "").strip():
            raise HTTPException(409, "Confirmation name is required for permanent delete")
        try:
            result = await purge_agent(
                db,
                agent,
                confirm_name=body.confirm_name or "",
                actor_user_id=user.id,
                reason=body.reason,
            )
            await db.commit()
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(409, str(exc)) from exc
        return result
    if (body.confirm_name or "").strip() and body.confirm_name.strip() != agent.name:
        raise HTTPException(409, "Confirmation name does not match the Agent name")
    agent.status = "archived"
    agent.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    db.add(
        AgentAuditEvent(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            actor_user_id=user.id,
            event_type="agent.deleted",
            reason=body.reason,
            payload={
                "mode": body.mode,
                "status": agent.status,
                "is_system": bool(agent.is_system),
            },
        )
    )
    await db.commit()
    return {
        "id": agent.id,
        "status": agent.status,
        "deleted_at": None,
        "purge_scheduled": body.mode == "purge_later",
    }


@router.post("/{agent_id}/versions", status_code=201)
async def create_agent_version_endpoint(
    agent_id: str,
    body: AgentVersionCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.edit")),
):
    agent = await _agent_or_404(db, agent_id)
    source: AgentVersion | None = None
    if body.clone_version_id:
        source = await _version_or_404(db, body.clone_version_id)
        if source.agent_id != agent.id:
            raise HTTPException(400, "Clone source belongs to another Agent")
    policies = (
        {field: getattr(source, field) or {} for field in _POLICY_FIELDS}
        if source
        else {}
    )
    policies.update(_clean_policies(body.policies))
    prompt = (
        body.system_prompt
        if body.system_prompt is not None
        else (source.system_prompt if source else None)
    )
    if not prompt:
        raise HTTPException(400, "system_prompt is required")
    try:
        version = await create_agent_version(
            db,
            agent,
            system_prompt=prompt,
            change_summary=body.change_summary,
            created_by_user_id=user.id,
            **policies,
        )
        if source:
            source_bindings = (
                (
                    await db.execute(
                        select(AgentKnowledgeBinding).where(
                            AgentKnowledgeBinding.agent_version_id == source.id,
                            AgentKnowledgeBinding.status.not_in(
                                {"revoked", "suspended"}
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            bypass = await user_bypasses_maker_checker(db, user.id)
            now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            for binding in source_bindings:
                cloned = AgentKnowledgeBinding(
                    id=str(uuid.uuid4()),
                    agent_version_id=version.id,
                    knowledge_base_id=binding.knowledge_base_id,
                    release_mode=binding.release_mode,
                    pinned_release_id=binding.pinned_release_id,
                    status="pending_kb_approval",
                    retrieval_policy=binding.retrieval_policy or {},
                    requested_by_user_id=user.id,
                )
                if bypass:
                    cloned.kb_approved_by_user_id = user.id
                    cloned.kb_approved_at = now
                    cloned.domain_approved_by_user_id = user.id
                    cloned.domain_approved_at = now
                    cloned.status = "approved"
                db.add(cloned)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _version_payload(version)


@router.patch("/versions/{version_id}")
async def update_agent_version_endpoint(
    version_id: str,
    body: AgentVersionUpdateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.edit")),
):
    version = await _version_or_404(db, version_id)
    try:
        version = await update_agent_draft(
            db,
            version,
            system_prompt=body.system_prompt,
            change_summary=body.change_summary,
            actor_user_id=user.id,
            policies=_clean_policies(body.policies),
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _version_payload(version)


@router.post("/versions/{version_id}/submit")
async def submit_agent_version_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.submit")),
):
    version = await _version_or_404(db, version_id)
    try:
        version = await submit_agent_version(db, version, actor_user_id=user.id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _version_payload(version)


@router.post("/versions/{version_id}/discard")
async def discard_agent_version_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.edit")),
):
    version = await _version_or_404(db, version_id)
    try:
        next_version_id = await discard_agent_draft(
            db,
            version,
            actor_user_id=user.id,
            reason="Discarded from Agent Studio",
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"discarded_version_id": version_id, "next_version_id": next_version_id}


@router.post("/versions/{version_id}/publish")
async def publish_agent_version_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.publish")),
):
    version = await _version_or_404(db, version_id)
    bindings = (
        (
            await db.execute(
                select(AgentKnowledgeBinding).where(
                    AgentKnowledgeBinding.agent_version_id == version.id
                )
            )
        )
        .scalars()
        .all()
    )
    pending = [
        binding
        for binding in bindings
        if binding.status not in {"approved", "published", "revoked"}
    ]
    if pending:
        raise HTTPException(
            409,
            "All Knowledge bindings must complete required approvals before publish",
        )
    try:
        version = await publish_agent_version(
            db,
            version,
            actor_user_id=user.id,
            allow_same_actor=await user_bypasses_maker_checker(db, user.id),
        )
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        for binding in bindings:
            if binding.status == "approved":
                binding.status = "published"
                binding.published_at = now
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _version_payload(version)


@router.post("/versions/{version_id}/rollback")
async def rollback_agent_version_endpoint(
    version_id: str,
    body: ReasonBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.rollback")),
):
    version = await _version_or_404(db, version_id)
    try:
        version = await rollback_agent_version(
            db,
            version,
            actor_user_id=user.id,
            reason=body.reason,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _version_payload(version)


@router.get("/{agent_id}/access")
async def get_agent_access(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("agent.read")),
):
    agent = await _agent_or_404(db, agent_id)
    assignments = (
        (
            await db.execute(
                select(AgentAccessAssignment)
                .where(AgentAccessAssignment.agent_id == agent.id)
                .order_by(AgentAccessAssignment.id)
            )
        )
        .scalars()
        .all()
    )
    return {
        "access_type": agent.access_type,
        "acl_version": agent.acl_version,
        "grants": [_assignment_payload(row) for row in assignments],
    }


@router.put("/{agent_id}/access")
async def replace_agent_access(
    agent_id: str,
    body: AgentAccessBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.access.manage")),
):
    agent = await _agent_or_404(db, agent_id)
    try:
        await set_agent_access(
            db,
            agent,
            access_type=body.access_type,
            grants=[
                AccessGrant(
                    target_type=grant.target_type,
                    target=grant.target,
                    effect=grant.effect,
                )
                for grant in body.grants
            ],
            assigned_by_user_id=user.id,
        )
        db.add(
            AgentAuditEvent(
                id=str(uuid.uuid4()),
                agent_id=agent.id,
                actor_user_id=user.id,
                event_type="agent.access.updated",
                payload={
                    "access_type": body.access_type,
                    "grant_count": len(body.grants),
                    "acl_version": agent.acl_version,
                },
            )
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return await get_agent_access(agent_id, db, user)


@router.post("/versions/{version_id}/bindings", status_code=201)
async def create_knowledge_binding(
    version_id: str,
    body: KnowledgeBindingBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.knowledge.bind")),
):
    version = await _version_or_404(db, version_id)
    if version.status != "draft":
        raise HTTPException(409, "Knowledge can only be bound to a draft Agent version")
    knowledge_base = await db.get(KnowledgeBase, body.knowledge_base_id)
    if knowledge_base is None or knowledge_base.status != "active":
        raise HTTPException(404, "Active Knowledge Base not found")
    existing = (
        await db.execute(
            select(AgentKnowledgeBinding).where(
                AgentKnowledgeBinding.agent_version_id == version.id,
                AgentKnowledgeBinding.knowledge_base_id == knowledge_base.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status != "revoked":
        raise HTTPException(409, "Knowledge Base is already bound to this version")
    if body.release_mode == "pinned":
        release = (
            await db.get(KnowledgeRelease, body.pinned_release_id)
            if body.pinned_release_id
            else None
        )
        if (
            release is None
            or release.knowledge_base_id != knowledge_base.id
            or release.status != "published"
        ):
            raise HTTPException(400, "Pinned mode requires a published release")
    elif body.pinned_release_id is not None:
        raise HTTPException(400, "pinned_release_id requires release_mode=pinned")
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    bypass = await user_bypasses_maker_checker(db, user.id)
    reactivated = existing is not None
    binding = existing or AgentKnowledgeBinding(
        id=str(uuid.uuid4()),
        agent_version_id=version.id,
        knowledge_base_id=knowledge_base.id,
    )
    binding.release_mode = body.release_mode
    binding.pinned_release_id = body.pinned_release_id
    binding.retrieval_policy = body.retrieval_policy
    binding.requested_by_user_id = user.id
    binding.kb_approved_by_user_id = None
    binding.kb_approved_at = None
    binding.domain_approved_by_user_id = None
    binding.domain_approved_at = None
    binding.published_at = None
    binding.status = "pending_kb_approval"
    if bypass:
        # Super Admin break-glass: complete the binding without a second actor.
        binding.kb_approved_by_user_id = user.id
        binding.kb_approved_at = now
        if knowledge_base.sensitivity in _SENSITIVE_KB_LEVELS:
            binding.domain_approved_by_user_id = user.id
            binding.domain_approved_at = now
        if version.status == "published":
            binding.status = "published"
            binding.published_at = now
        else:
            binding.status = "approved"
    if not reactivated:
        db.add(binding)
    db.add(
        AgentAuditEvent(
            id=str(uuid.uuid4()),
            agent_id=version.agent_id,
            agent_version_id=version.id,
            actor_user_id=user.id,
            event_type=(
                "agent.knowledge_binding.auto_approved"
                if bypass
                else "agent.knowledge_binding.requested"
            ),
            payload={
                "binding_id": binding.id,
                "knowledge_base_id": knowledge_base.id,
                "status": binding.status,
                "super_admin_bypass": bypass,
                "reactivated": reactivated,
            },
        )
    )
    await db.commit()
    return _binding_payload(binding, knowledge_base)


@router.post("/bindings/{binding_id}/approve-knowledge")
async def approve_knowledge_binding(
    binding_id: str,
    body: ReasonBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.review")),
):
    binding = await db.get(AgentKnowledgeBinding, binding_id)
    if binding is None:
        raise HTTPException(404, "Knowledge binding not found")
    if binding.status != "pending_kb_approval":
        raise HTTPException(409, "Binding is not awaiting Knowledge approval")
    if (
        binding.requested_by_user_id == user.id
        and not await user_bypasses_maker_checker(db, user.id)
    ):
        raise HTTPException(
            409,
            "Maker-checker policy requires a different Knowledge approver",
        )
    knowledge_base = await db.get(KnowledgeBase, binding.knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge Base not found")
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    binding.kb_approved_by_user_id = user.id
    binding.kb_approved_at = now
    version = await _version_or_404(db, binding.agent_version_id)
    if knowledge_base.sensitivity in _SENSITIVE_KB_LEVELS:
        binding.status = "pending_domain_approval"
    elif version.status == "published":
        binding.status = "published"
        binding.published_at = now
    else:
        binding.status = "approved"
    db.add(
        AgentAuditEvent(
            id=str(uuid.uuid4()),
            agent_id=version.agent_id,
            agent_version_id=version.id,
            actor_user_id=user.id,
            event_type="agent.knowledge_binding.knowledge_approved",
            reason=body.reason,
            payload={"binding_id": binding.id, "status": binding.status},
        )
    )
    await db.commit()
    return _binding_payload(binding, knowledge_base)


@router.post("/bindings/{binding_id}/approve-domain")
async def approve_domain_binding(
    binding_id: str,
    body: ReasonBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("approval.approve")),
):
    binding = await db.get(AgentKnowledgeBinding, binding_id)
    if binding is None:
        raise HTTPException(404, "Knowledge binding not found")
    if binding.status != "pending_domain_approval":
        raise HTTPException(409, "Binding is not awaiting domain approval")
    if (
        user.id
        in {
            binding.requested_by_user_id,
            binding.kb_approved_by_user_id,
        }
        and not await user_bypasses_maker_checker(db, user.id)
    ):
        raise HTTPException(
            409,
            "Maker-checker policy requires an independent domain approver",
        )
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    binding.domain_approved_by_user_id = user.id
    binding.domain_approved_at = now
    version = await _version_or_404(db, binding.agent_version_id)
    if version.status == "published":
        binding.status = "published"
        binding.published_at = now
    else:
        binding.status = "approved"
    db.add(
        AgentAuditEvent(
            id=str(uuid.uuid4()),
            agent_id=version.agent_id,
            agent_version_id=version.id,
            actor_user_id=user.id,
            event_type="agent.knowledge_binding.domain_approved",
            reason=body.reason,
            payload={"binding_id": binding.id, "status": binding.status},
        )
    )
    await db.commit()
    knowledge_base = await db.get(KnowledgeBase, binding.knowledge_base_id)
    return _binding_payload(binding, knowledge_base)


@router.post("/bindings/{binding_id}/revoke")
async def revoke_knowledge_binding(
    binding_id: str,
    body: ReasonBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("agent.knowledge.bind")),
):
    binding = await db.get(AgentKnowledgeBinding, binding_id)
    if binding is None:
        raise HTTPException(404, "Knowledge binding not found")
    version = await _version_or_404(db, binding.agent_version_id)
    try:
        await revoke_agent_knowledge_binding(
            db,
            binding,
            version=version,
            actor_user_id=user.id,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    knowledge_base = await db.get(KnowledgeBase, binding.knowledge_base_id)
    return _binding_payload(binding, knowledge_base)
