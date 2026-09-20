"""Deny-first resource ACLs for Agents and organization Knowledge."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentAccessAssignment
from app.models.api_key import AlphaRouterApiKey
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseAccessAssignment,
    KnowledgeDocument,
    KnowledgeDocumentAccessAssignment,
)
from app.models.user import User, UserGroup, user_group_members
from app.services.rbac import is_valid_role_slug, user_has_super_admin_access
from app.services.user_role_service import get_user_role_slugs

ACCESS_PUBLIC = "public"
ACCESS_PRIVATE = "private"
VALID_ACCESS_TYPES = frozenset({ACCESS_PUBLIC, ACCESS_PRIVATE})
EFFECT_ALLOW = "allow"
EFFECT_DENY = "deny"
VALID_EFFECTS = frozenset({EFFECT_ALLOW, EFFECT_DENY})
VALID_TARGET_TYPES = frozenset({"user", "group", "department", "role"})


class AccessAssignment(Protocol):
    user_id: int | None
    group_id: int | None
    department: str | None
    role_slug: str | None
    effect: str


@dataclass(frozen=True)
class ResourceAccessSubject:
    """Resolved identity used consistently by SQL and vector ACL evaluation."""

    user_id: int | None = None
    group_ids: frozenset[int] = frozenset()
    department: str | None = None
    role_slugs: frozenset[str] = frozenset()
    active: bool = True
    public_only: bool = False
    break_glass: bool = False

    @property
    def principal_tokens(self) -> frozenset[str]:
        tokens: set[str] = set()
        if self.user_id is not None:
            tokens.add(f"user:{self.user_id}")
        tokens.update(f"group:{group_id}" for group_id in self.group_ids)
        if self.department:
            tokens.add(f"department:{self.department}")
        tokens.update(f"role:{slug}" for slug in self.role_slugs)
        return frozenset(tokens)


@dataclass(frozen=True)
class AccessGrant:
    """One normalized allow/deny assignment supplied by an admin service."""

    target_type: str
    target: int | str
    effect: str = EFFECT_ALLOW


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split()).casefold()
    return normalized or None


async def resolve_resource_access_subject(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    source: str | None = None,
    break_glass: bool = False,
) -> ResourceAccessSubject:
    """Resolve browser or Gateway identity without implicit Super Admin bypass."""

    if source == "master":
        return ResourceAccessSubject(public_only=True)

    if alpha_router_api_key_id is not None:
        key = await db.get(AlphaRouterApiKey, alpha_router_api_key_id)
        user_id = int(key.owner_user_id) if key and key.owner_user_id is not None else None
        if user_id is None:
            return ResourceAccessSubject(public_only=True)

    if user_id is None:
        return ResourceAccessSubject(public_only=True)

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None or not bool(user.is_active):
        return ResourceAccessSubject(user_id=user_id, active=False)

    group_ids = frozenset(
        int(value)
        for value in (
            await db.execute(select(user_group_members.c.group_id).where(user_group_members.c.user_id == user_id))
        )
        .scalars()
        .all()
    )
    role_slugs = frozenset(
        _normalize_text(slug) or "" for slug in await get_user_role_slugs(db, user_id) if _normalize_text(slug)
    )
    may_break_glass = break_glass and user_has_super_admin_access(list(role_slugs))
    return ResourceAccessSubject(
        user_id=user_id,
        group_ids=group_ids,
        department=_normalize_text(user.department),
        role_slugs=role_slugs,
        active=True,
        public_only=False,
        break_glass=may_break_glass,
    )


def _assignment_token(assignment: AccessAssignment) -> str | None:
    if assignment.user_id is not None:
        return f"user:{int(assignment.user_id)}"
    if assignment.group_id is not None:
        return f"group:{int(assignment.group_id)}"
    department = _normalize_text(assignment.department)
    if department:
        return f"department:{department}"
    role_slug = _normalize_text(assignment.role_slug)
    if role_slug:
        return f"role:{role_slug}"
    return None


def assignment_matches(
    assignment: AccessAssignment,
    subject: ResourceAccessSubject,
) -> bool:
    token = _assignment_token(assignment)
    return token is not None and token in subject.principal_tokens


def evaluate_access(
    *,
    access_type: str,
    assignments: Sequence[AccessAssignment],
    subject: ResourceAccessSubject,
) -> bool:
    """Deny wins; private resources require a matching explicit allow."""

    if not subject.active:
        return False
    if subject.break_glass:
        return True

    matched = [assignment for assignment in assignments if assignment_matches(assignment, subject)]
    if any((assignment.effect or EFFECT_ALLOW).lower() == EFFECT_DENY for assignment in matched):
        return False

    normalized_access = (access_type or ACCESS_PRIVATE).strip().lower()
    if normalized_access == ACCESS_PUBLIC:
        return True
    if subject.public_only or subject.user_id is None:
        return False
    return any((assignment.effect or EFFECT_ALLOW).lower() == EFFECT_ALLOW for assignment in matched)


def compile_acl_payload(
    assignments: Iterable[AccessAssignment],
) -> dict[str, list[str]]:
    """Compile database grants into Qdrant-ready principal token arrays."""

    allow: set[str] = set()
    deny: set[str] = set()
    for assignment in assignments:
        token = _assignment_token(assignment)
        if not token:
            continue
        if (assignment.effect or EFFECT_ALLOW).lower() == EFFECT_DENY:
            deny.add(token)
        else:
            allow.add(token)
    return {
        "allow_principal_tokens": sorted(allow),
        "deny_principal_tokens": sorted(deny),
    }


async def user_can_access_agent(
    db: AsyncSession,
    agent: Agent,
    subject: ResourceAccessSubject,
) -> bool:
    assignments = (
        (await db.execute(select(AgentAccessAssignment).where(AgentAccessAssignment.agent_id == agent.id)))
        .scalars()
        .all()
    )
    return evaluate_access(
        access_type=agent.access_type,
        assignments=assignments,
        subject=subject,
    )


async def filter_agents_for_subject(
    db: AsyncSession,
    agents: Sequence[Agent],
    subject: ResourceAccessSubject,
) -> list[Agent]:
    if not agents or not subject.active:
        return []
    agent_ids = [agent.id for agent in agents]
    assignments = (
        (await db.execute(select(AgentAccessAssignment).where(AgentAccessAssignment.agent_id.in_(agent_ids))))
        .scalars()
        .all()
    )
    by_agent: dict[str, list[AgentAccessAssignment]] = {agent_id: [] for agent_id in agent_ids}
    for assignment in assignments:
        by_agent.setdefault(str(assignment.agent_id), []).append(assignment)
    return [
        agent
        for agent in agents
        if evaluate_access(
            access_type=agent.access_type,
            assignments=by_agent.get(agent.id, []),
            subject=subject,
        )
    ]


async def user_can_access_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    subject: ResourceAccessSubject,
) -> bool:
    assignments = (
        (
            await db.execute(
                select(KnowledgeBaseAccessAssignment).where(
                    KnowledgeBaseAccessAssignment.knowledge_base_id == knowledge_base.id
                )
            )
        )
        .scalars()
        .all()
    )
    return evaluate_access(
        access_type=knowledge_base.access_type,
        assignments=assignments,
        subject=subject,
    )


async def filter_knowledge_bases_for_subject(
    db: AsyncSession,
    knowledge_bases: Sequence[KnowledgeBase],
    subject: ResourceAccessSubject,
) -> list[KnowledgeBase]:
    if not knowledge_bases or not subject.active:
        return []
    if subject.break_glass:
        return list(knowledge_bases)
    knowledge_base_ids = [knowledge_base.id for knowledge_base in knowledge_bases]
    assignments = (
        (
            await db.execute(
                select(KnowledgeBaseAccessAssignment).where(
                    KnowledgeBaseAccessAssignment.knowledge_base_id.in_(knowledge_base_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    by_knowledge_base: dict[str, list[KnowledgeBaseAccessAssignment]] = {
        knowledge_base_id: [] for knowledge_base_id in knowledge_base_ids
    }
    for assignment in assignments:
        by_knowledge_base.setdefault(
            str(assignment.knowledge_base_id),
            [],
        ).append(assignment)
    return [
        knowledge_base
        for knowledge_base in knowledge_bases
        if evaluate_access(
            access_type=knowledge_base.access_type,
            assignments=by_knowledge_base.get(knowledge_base.id, []),
            subject=subject,
        )
    ]


async def user_can_access_document(
    db: AsyncSession,
    document: KnowledgeDocument,
    subject: ResourceAccessSubject,
) -> bool:
    """Require KB access, then apply optional restrictive document ACLs."""

    knowledge_base = await db.get(KnowledgeBase, document.knowledge_base_id)
    if knowledge_base is None or not await user_can_access_knowledge_base(
        db,
        knowledge_base,
        subject,
    ):
        return False
    if subject.break_glass:
        return True

    assignments = (
        (
            await db.execute(
                select(KnowledgeDocumentAccessAssignment).where(
                    KnowledgeDocumentAccessAssignment.document_id == document.id
                )
            )
        )
        .scalars()
        .all()
    )
    if not assignments:
        return True

    matched = [assignment for assignment in assignments if assignment_matches(assignment, subject)]
    if any((assignment.effect or EFFECT_ALLOW).lower() == EFFECT_DENY for assignment in matched):
        return False
    allow_rules_exist = any((assignment.effect or EFFECT_ALLOW).lower() == EFFECT_ALLOW for assignment in assignments)
    if not allow_rules_exist:
        return True
    return any((assignment.effect or EFFECT_ALLOW).lower() == EFFECT_ALLOW for assignment in matched)


async def filter_documents_for_subject(
    db: AsyncSession,
    documents: Sequence[KnowledgeDocument],
    subject: ResourceAccessSubject,
) -> list[KnowledgeDocument]:
    """Bulk post-authorize candidates against current PostgreSQL ACL state."""

    if not documents or not subject.active:
        return []
    knowledge_base_ids = sorted({document.knowledge_base_id for document in documents})
    knowledge_bases = (
        (await db.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(knowledge_base_ids)))).scalars().all()
    )
    allowed_knowledge_base_ids = {
        knowledge_base.id
        for knowledge_base in await filter_knowledge_bases_for_subject(
            db,
            knowledge_bases,
            subject,
        )
    }
    if not allowed_knowledge_base_ids:
        return []
    if subject.break_glass:
        return [document for document in documents if document.knowledge_base_id in allowed_knowledge_base_ids]

    document_ids = [document.id for document in documents]
    assignments = (
        (
            await db.execute(
                select(KnowledgeDocumentAccessAssignment).where(
                    KnowledgeDocumentAccessAssignment.document_id.in_(document_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    by_document: dict[str, list[KnowledgeDocumentAccessAssignment]] = {document_id: [] for document_id in document_ids}
    for assignment in assignments:
        by_document.setdefault(str(assignment.document_id), []).append(assignment)

    allowed: list[KnowledgeDocument] = []
    for document in documents:
        if document.knowledge_base_id not in allowed_knowledge_base_ids:
            continue
        document_rules = by_document.get(document.id, [])
        if not document_rules:
            allowed.append(document)
            continue
        matched = [assignment for assignment in document_rules if assignment_matches(assignment, subject)]
        if any((assignment.effect or EFFECT_ALLOW).lower() == EFFECT_DENY for assignment in matched):
            continue
        allow_rules_exist = any(
            (assignment.effect or EFFECT_ALLOW).lower() == EFFECT_ALLOW for assignment in document_rules
        )
        if not allow_rules_exist or any(
            (assignment.effect or EFFECT_ALLOW).lower() == EFFECT_ALLOW for assignment in matched
        ):
            allowed.append(document)
    return allowed


async def validated_grants(
    db: AsyncSession,
    grants: Sequence[AccessGrant],
) -> list[dict[str, int | str | None]]:
    rows: list[dict[str, int | str | None]] = []
    seen: set[tuple[str, int | str, str]] = set()
    for grant in grants:
        target_type = (grant.target_type or "").strip().lower()
        effect = (grant.effect or "").strip().lower()
        if target_type not in VALID_TARGET_TYPES:
            raise ValueError(f"Unsupported ACL target_type: {target_type}")
        if effect not in VALID_EFFECTS:
            raise ValueError("ACL effect must be 'allow' or 'deny'")

        row: dict[str, int | str | None] = {
            "user_id": None,
            "group_id": None,
            "department": None,
            "role_slug": None,
            "effect": effect,
        }
        if target_type == "user":
            target = int(grant.target)
            user = await db.get(User, target)
            if user is None or user.deleted_at is not None or not bool(user.is_active):
                raise ValueError(f"Unknown or inactive ACL user: {target}")
            row["user_id"] = target
        elif target_type == "group":
            target = int(grant.target)
            if await db.get(UserGroup, target) is None:
                raise ValueError(f"Unknown ACL group: {target}")
            row["group_id"] = target
        elif target_type == "department":
            target = _normalize_text(str(grant.target))
            if not target:
                raise ValueError("ACL department cannot be empty")
            row["department"] = target
        else:
            target = _normalize_text(str(grant.target))
            if not target or not is_valid_role_slug(target):
                raise ValueError(f"Unknown ACL role: {target}")
            row["role_slug"] = target

        dedupe_key = (target_type, target, effect)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append(row)
    return rows


async def set_agent_access(
    db: AsyncSession,
    agent: Agent,
    *,
    access_type: str,
    grants: Sequence[AccessGrant],
    assigned_by_user_id: int | None = None,
) -> None:
    access = (access_type or "").strip().lower()
    if access not in VALID_ACCESS_TYPES:
        raise ValueError("access_type must be 'public' or 'private'")
    rows = await validated_grants(db, grants)
    await db.execute(delete(AgentAccessAssignment).where(AgentAccessAssignment.agent_id == agent.id))
    agent.access_type = access
    agent.acl_version = int(agent.acl_version or 0) + 1
    for row in rows:
        db.add(
            AgentAccessAssignment(
                agent_id=agent.id,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=datetime.utcnow(),
                **row,
            )
        )


async def set_knowledge_base_access(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    access_type: str,
    grants: Sequence[AccessGrant],
    assigned_by_user_id: int | None = None,
) -> None:
    access = (access_type or "").strip().lower()
    if access not in VALID_ACCESS_TYPES:
        raise ValueError("access_type must be 'public' or 'private'")
    rows = await validated_grants(db, grants)
    await db.execute(
        delete(KnowledgeBaseAccessAssignment).where(
            KnowledgeBaseAccessAssignment.knowledge_base_id == knowledge_base.id
        )
    )
    knowledge_base.access_type = access
    knowledge_base.acl_version = int(knowledge_base.acl_version or 0) + 1
    for row in rows:
        db.add(
            KnowledgeBaseAccessAssignment(
                knowledge_base_id=knowledge_base.id,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=datetime.utcnow(),
                **row,
            )
        )


async def set_document_access(
    db: AsyncSession,
    document: KnowledgeDocument,
    *,
    grants: Sequence[AccessGrant],
    assigned_by_user_id: int | None = None,
) -> None:
    rows = await validated_grants(db, grants)
    await db.execute(
        delete(KnowledgeDocumentAccessAssignment).where(KnowledgeDocumentAccessAssignment.document_id == document.id)
    )
    document.acl_version = int(document.acl_version or 0) + 1
    for row in rows:
        db.add(
            KnowledgeDocumentAccessAssignment(
                document_id=document.id,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=datetime.utcnow(),
                **row,
            )
        )
