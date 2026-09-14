"""Agent identity and immutable configuration-version lifecycle."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import (
    Agent,
    AgentAccessAssignment,
    AgentAuditEvent,
    AgentKnowledgeBinding,
    AgentVersion,
)
from app.services.agent_evaluation_service import (
    assert_agent_version_evaluation_gate,
)
from app.services.agent_policy_service import validate_agent_version_policies

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PURGED_AGENT_SLUG_PREFIX = "purged-"


def is_purged_agent(agent: Agent) -> bool:
    return (agent.slug or "").startswith(PURGED_AGENT_SLUG_PREFIX)


_POLICY_FIELDS = (
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
)


def normalize_agent_slug(value: str) -> str:
    slug = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug or len(slug) > 128 or not _SLUG_RE.fullmatch(slug):
        raise ValueError("Agent slug must contain lowercase letters, numbers, and single hyphens")
    return slug


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _version_fingerprint(
    *,
    agent_id: str,
    version_number: int,
    system_prompt: str,
    policies: dict[str, dict],
) -> str:
    payload = {
        "agent_id": agent_id,
        "version_number": version_number,
        "system_prompt": system_prompt,
        **{field: policies.get(field, {}) for field in _POLICY_FIELDS},
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


async def _audit(
    db: AsyncSession,
    *,
    event_type: str,
    agent_id: str | None,
    agent_version_id: str | None = None,
    actor_user_id: int | None = None,
    reason: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        AgentAuditEvent(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            reason=reason,
            payload=payload or {},
        )
    )


async def create_agent(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None = None,
    icon: str | None = None,
    category: str | None = None,
    access_type: str = "private",
    created_by_user_id: int | None = None,
    is_system: bool = False,
) -> Agent:
    clean_name = " ".join((name or "").split()).strip()
    if not clean_name or len(clean_name) > 255:
        raise ValueError("Agent name is required and must be at most 255 characters")
    clean_slug = normalize_agent_slug(slug)
    if access_type not in {"public", "private"}:
        raise ValueError("access_type must be 'public' or 'private'")
    existing = (await db.execute(select(Agent.id).where(Agent.slug == clean_slug))).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Agent slug already exists: {clean_slug}")

    agent = Agent(
        id=str(uuid.uuid4()),
        slug=clean_slug,
        name=clean_name,
        description=(description or "").strip() or None,
        icon=(icon or "").strip() or None,
        category=(category or "").strip() or None,
        status="draft",
        access_type=access_type,
        created_by_user_id=created_by_user_id,
        is_system=is_system,
    )
    db.add(agent)
    await db.flush()
    await _audit(
        db,
        event_type="agent.created",
        agent_id=agent.id,
        actor_user_id=created_by_user_id,
        payload={"slug": clean_slug, "name": clean_name},
    )
    return agent


async def create_agent_version(
    db: AsyncSession,
    agent: Agent,
    *,
    system_prompt: str,
    created_by_user_id: int | None,
    change_summary: str | None = None,
    **policies: dict,
) -> AgentVersion:
    prompt = (system_prompt or "").strip()
    if not prompt:
        raise ValueError("system_prompt is required")
    normalized_policies = {field: dict(policies.get(field) or {}) for field in _POLICY_FIELDS}
    # Discarded drafts stay archived (audit table is append-only), so reuse their
    # version numbers instead of forever incrementing past them.
    reusable = (
        await db.execute(
            select(AgentVersion)
            .where(
                AgentVersion.agent_id == agent.id,
                AgentVersion.status == "archived",
                AgentVersion.published_at.is_(None),
            )
            .order_by(AgentVersion.version_number.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if reusable is not None:
        await db.execute(delete(AgentKnowledgeBinding).where(AgentKnowledgeBinding.agent_version_id == reusable.id))
        reusable.status = "draft"
        reusable.archived_at = None
        reusable.submitted_at = None
        reusable.active_scope_key = None
        reusable.system_prompt = prompt
        reusable.change_summary = (change_summary or "").strip() or None
        reusable.created_by_user_id = created_by_user_id
        for field, value in normalized_policies.items():
            setattr(reusable, field, value)
        reusable.fingerprint = _version_fingerprint(
            agent_id=agent.id,
            version_number=reusable.version_number,
            system_prompt=prompt,
            policies=normalized_policies,
        )
        await db.flush()
        await _audit(
            db,
            event_type="agent.version.created",
            agent_id=agent.id,
            agent_version_id=reusable.id,
            actor_user_id=created_by_user_id,
            payload={
                "version_number": reusable.version_number,
                "recycled_discarded_draft": True,
            },
        )
        return reusable

    next_number = (
        int(
            (
                await db.execute(
                    select(func.max(AgentVersion.version_number)).where(
                        AgentVersion.agent_id == agent.id,
                        # Ignore never-published discarded drafts for numbering.
                        or_(
                            AgentVersion.status != "archived",
                            AgentVersion.published_at.is_not(None),
                        ),
                    )
                )
            ).scalar_one_or_none()
            or 0
        )
        + 1
    )
    version = AgentVersion(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version_number=next_number,
        status="draft",
        system_prompt=prompt,
        fingerprint=_version_fingerprint(
            agent_id=agent.id,
            version_number=next_number,
            system_prompt=prompt,
            policies=normalized_policies,
        ),
        change_summary=(change_summary or "").strip() or None,
        created_by_user_id=created_by_user_id,
        **normalized_policies,
    )
    db.add(version)
    await db.flush()
    await _audit(
        db,
        event_type="agent.version.created",
        agent_id=agent.id,
        agent_version_id=version.id,
        actor_user_id=created_by_user_id,
        payload={"version_number": next_number},
    )
    return version


async def update_agent_draft(
    db: AsyncSession,
    version: AgentVersion,
    *,
    system_prompt: str | None = None,
    change_summary: str | None = None,
    actor_user_id: int | None = None,
    policies: dict[str, dict] | None = None,
) -> AgentVersion:
    if version.status != "draft":
        raise ValueError("Only draft Agent versions can be edited")
    if system_prompt is not None:
        prompt = system_prompt.strip()
        if not prompt:
            raise ValueError("system_prompt cannot be empty")
        version.system_prompt = prompt
    if change_summary is not None:
        version.change_summary = change_summary.strip() or None
    for field, value in (policies or {}).items():
        if field not in _POLICY_FIELDS:
            raise ValueError(f"Unknown Agent policy field: {field}")
        setattr(version, field, dict(value or {}))
    version.fingerprint = _version_fingerprint(
        agent_id=version.agent_id,
        version_number=version.version_number,
        system_prompt=version.system_prompt,
        policies={field: getattr(version, field) or {} for field in _POLICY_FIELDS},
    )
    await _audit(
        db,
        event_type="agent.version.updated",
        agent_id=version.agent_id,
        agent_version_id=version.id,
        actor_user_id=actor_user_id,
    )
    return version


async def submit_agent_version(
    db: AsyncSession,
    version: AgentVersion,
    *,
    actor_user_id: int | None,
) -> AgentVersion:
    if version.status != "draft":
        raise ValueError("Only draft Agent versions can be submitted")
    validate_agent_version_policies(version, require_model=True)
    version.status = "review"
    version.submitted_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await _audit(
        db,
        event_type="agent.version.submitted",
        agent_id=version.agent_id,
        agent_version_id=version.id,
        actor_user_id=actor_user_id,
    )
    return version


async def discard_agent_draft(
    db: AsyncSession,
    version: AgentVersion,
    *,
    actor_user_id: int | None,
    reason: str | None = None,
) -> str:
    """Discard an unpublished draft without hard-deleting the row.

    PostgreSQL keeps ``agent_audit_events`` append-only, so deleting a version
    that already has audit rows fails when the FK tries to SET NULL. Drafts are
    therefore archived in place and hidden from the Studio version picker.
    """

    if version.status != "draft":
        raise ValueError("Only draft Agent versions can be discarded")
    sibling_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AgentVersion)
                .where(
                    AgentVersion.agent_id == version.agent_id,
                    AgentVersion.id != version.id,
                )
            )
        ).scalar_one()
        or 0
    )
    if sibling_count < 1:
        raise ValueError("Cannot discard the only Agent version; archive or delete the Agent instead")
    preferred = (
        await db.execute(
            select(AgentVersion.id)
            .where(
                AgentVersion.agent_id == version.agent_id,
                AgentVersion.id != version.id,
                AgentVersion.status == "published",
            )
            .order_by(AgentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if preferred is None:
        preferred = (
            await db.execute(
                select(AgentVersion.id)
                .where(
                    AgentVersion.agent_id == version.agent_id,
                    AgentVersion.id != version.id,
                    # Prefer selectable versions over other discarded drafts.
                    AgentVersion.status.in_(("published", "review", "draft")),
                )
                .order_by(AgentVersion.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if preferred is None:
        preferred = (
            await db.execute(
                select(AgentVersion.id)
                .where(
                    AgentVersion.agent_id == version.agent_id,
                    AgentVersion.id != version.id,
                )
                .order_by(AgentVersion.version_number.desc())
                .limit(1)
            )
        ).scalar_one()

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    version.status = "archived"
    version.archived_at = now
    version.active_scope_key = None
    if not (version.change_summary or "").strip():
        version.change_summary = "Discarded draft"
    await _audit(
        db,
        event_type="agent.version.discarded",
        agent_id=version.agent_id,
        agent_version_id=version.id,
        actor_user_id=actor_user_id,
        reason=(reason or "").strip() or None,
        payload={"version_number": version.version_number},
    )
    await db.flush()
    return str(preferred)


async def get_active_agent_version(
    db: AsyncSession,
    agent_id: str,
) -> AgentVersion | None:
    return (
        await db.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.active_scope_key == f"agent:{agent_id}",
                AgentVersion.status == "published",
            )
        )
    ).scalar_one_or_none()


async def publish_agent_version(
    db: AsyncSession,
    version: AgentVersion,
    *,
    actor_user_id: int,
    allow_same_actor: bool = False,
) -> AgentVersion:
    if version.status != "review":
        raise ValueError("Agent version must be in review before publish")
    validate_agent_version_policies(version, require_model=True)
    from app.services.agent_tool_registry_service import validate_agent_tool_bindings

    await validate_agent_tool_bindings(db, version)
    await assert_agent_version_evaluation_gate(db, version)
    if (
        not allow_same_actor
        and version.created_by_user_id is not None
        and int(version.created_by_user_id) == int(actor_user_id)
    ):
        raise ValueError("Maker-checker violation: creator cannot publish this Agent version")
    agent = await db.get(Agent, version.agent_id)
    if agent is None:
        raise ValueError("Agent no longer exists")

    current = await get_active_agent_version(db, agent.id)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if current is not None and current.id != version.id:
        current.active_scope_key = None
        current.status = "archived"
        current.archived_at = now
        # Release the unique active scope before assigning it to the new version.
        await db.flush()

    version.status = "published"
    version.active_scope_key = f"agent:{agent.id}"
    version.published_by_user_id = actor_user_id
    version.published_at = now
    version.archived_at = None
    agent.status = "active"
    await _audit(
        db,
        event_type="agent.version.published",
        agent_id=agent.id,
        agent_version_id=version.id,
        actor_user_id=actor_user_id,
        payload={"version_number": version.version_number},
    )
    return version


async def rollback_agent_version(
    db: AsyncSession,
    target: AgentVersion,
    *,
    actor_user_id: int,
    reason: str,
) -> AgentVersion:
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("Rollback reason is required")
    if target.status not in {"published", "archived"}:
        raise ValueError("Only a previously published Agent version can be restored")
    await assert_agent_version_evaluation_gate(db, target)
    current = await get_active_agent_version(db, target.agent_id)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if current is not None and current.id != target.id:
        current.active_scope_key = None
        current.status = "archived"
        current.archived_at = now
        # Keep update ordering deterministic for the unique active scope.
        await db.flush()
    target.status = "published"
    target.active_scope_key = f"agent:{target.agent_id}"
    target.published_by_user_id = actor_user_id
    target.published_at = now
    target.archived_at = None
    await _audit(
        db,
        event_type="agent.version.rolled_back",
        agent_id=target.agent_id,
        agent_version_id=target.id,
        actor_user_id=actor_user_id,
        reason=clean_reason,
        payload={
            "restored_version_number": target.version_number,
            "replaced_version_id": current.id if current and current.id != target.id else None,
        },
    )
    return target


async def revoke_agent_knowledge_binding(
    db: AsyncSession,
    binding: AgentKnowledgeBinding,
    *,
    version: AgentVersion,
    actor_user_id: int | None,
    reason: str,
) -> AgentKnowledgeBinding:
    """Remove a Knowledge binding from a draft Agent version without deleting audit."""

    if version.status != "draft":
        raise ValueError("Knowledge bindings can only be removed from a draft Agent version")
    if binding.agent_version_id != version.id:
        raise ValueError("Binding does not belong to this Agent version")
    if binding.status == "revoked":
        raise ValueError("Knowledge binding is already removed")
    clean_reason = (reason or "").strip()
    if len(clean_reason) < 3:
        raise ValueError("Removal reason is required")
    previous_status = binding.status
    binding.status = "revoked"
    await _audit(
        db,
        event_type="agent.knowledge_binding.revoked",
        agent_id=version.agent_id,
        agent_version_id=version.id,
        actor_user_id=actor_user_id,
        reason=clean_reason,
        payload={
            "binding_id": binding.id,
            "knowledge_base_id": binding.knowledge_base_id,
            "previous_status": previous_status,
        },
    )
    await db.flush()
    return binding


async def purge_agent(
    db: AsyncSession,
    agent: Agent,
    *,
    confirm_name: str,
    actor_user_id: int | None,
    reason: str,
) -> dict[str, object]:
    """Permanently remove an Agent from catalogs without deleting audit parents.

    ``agent_audit_events`` is append-only with ``ON DELETE SET NULL`` FKs, so the
    Agent and its versions are tombstoned in place and hidden from Studio lists.
    """

    if is_purged_agent(agent):
        raise ValueError("Agent is already permanently deleted")
    if (confirm_name or "").strip() != agent.name:
        raise ValueError("Confirmation name does not match the Agent name")

    clean_reason = (reason or "").strip()
    if len(clean_reason) < 3:
        raise ValueError("Deletion reason is required")

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    original_name = agent.name
    original_slug = agent.slug

    version_ids = (await db.execute(select(AgentVersion.id).where(AgentVersion.agent_id == agent.id))).scalars().all()
    if version_ids:
        await db.execute(delete(AgentKnowledgeBinding).where(AgentKnowledgeBinding.agent_version_id.in_(version_ids)))
    await db.execute(delete(AgentAccessAssignment).where(AgentAccessAssignment.agent_id == agent.id))

    versions = (await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id))).scalars().all()
    for version in versions:
        version.status = "archived"
        version.active_scope_key = None
        version.archived_at = now
        version.system_prompt = ""
        version.change_summary = "Permanently deleted with Agent"

    agent.status = "archived"
    agent.slug = f"{PURGED_AGENT_SLUG_PREFIX}{agent.id}"
    agent.name = f"[Deleted] {original_name}"
    agent.description = None
    agent.is_system = False
    agent.updated_at = now

    await _audit(
        db,
        event_type="agent.purged",
        agent_id=agent.id,
        actor_user_id=actor_user_id,
        reason=clean_reason,
        payload={
            "name": original_name,
            "slug": original_slug,
            "version_count": len(versions),
            "tombstone": True,
        },
    )
    await db.flush()
    return {
        "id": agent.id,
        "name": original_name,
        "slug": original_slug,
        "status": "purged",
        "deleted_at": now.isoformat(),
        "purge_scheduled": False,
        "tombstoned": True,
    }
