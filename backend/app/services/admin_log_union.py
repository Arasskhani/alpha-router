"""One shape over the product's eight administrative audit trails.

Each trail keeps its own table, with its own reasons: the governance chain is
hash-linked and append-only, the agent and knowledge trails are guarded by
triggers, the API-key and connection logs predate all of that. Nothing here
writes to any of them. This module only reads them through one normalised
projection - source, time, actor, action, resource, detail - so the Admin Logs
page can show an investigation everything that happened, in one order.

Adding a trail is one more entry in ``SOURCES``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, String, Text, and_, cast, literal, null, or_, select, union_all

from app.models.agent import AgentAuditEvent
from app.models.agent_tool import AgentToolAuditEvent
from app.models.api_key import AlphaRouterApiKeyAuditLog
from app.models.connection import ConnectionAuditLog
from app.models.governance import GovernanceAuditEvent
from app.models.knowledge import KnowledgeAuditEvent
from app.models.project import ProjectAuditEvent
from app.models.security import SecurityAuditEvent
from app.models.user import User

#: The column names every source is projected onto, in this order.
COLUMNS = (
    "source",
    "id",
    "created_at",
    "actor_user_id",
    "actor_username",
    "actor_email",
    "actor_ip",
    "action",
    "resource_type",
    "resource_id",
    "detail",
    "outcome",
    "detail_redacted_at",
)


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    model: Any
    action: Any
    resource_type: Any
    resource_id: Any
    detail: Any
    actor_username: Any = None
    actor_email: Any = None
    actor_ip: Any = None
    outcome: Any = None
    detail_redacted_at: Any = None

    def select(self) -> Select:
        m = self.model
        return select(
            literal(self.key).label("source"),
            cast(m.id, String).label("id"),
            m.created_at.label("created_at"),
            m.actor_user_id.label("actor_user_id"),
            (self.actor_username if self.actor_username is not None else null()).label("actor_username"),
            (self.actor_email if self.actor_email is not None else null()).label("actor_email"),
            (self.actor_ip if self.actor_ip is not None else null()).label("actor_ip"),
            cast(self.action, String).label("action"),
            cast(self.resource_type, String).label("resource_type"),
            cast(self.resource_id, String).label("resource_id")
            if self.resource_id is not None
            else null().label("resource_id"),
            cast(self.detail, Text).label("detail") if self.detail is not None else null().label("detail"),
            (cast(self.outcome, String) if self.outcome is not None else null()).label("outcome"),
            (self.detail_redacted_at if self.detail_redacted_at is not None else null()).label("detail_redacted_at"),
        )


SOURCES: dict[str, Source] = {
    s.key: s
    for s in (
        Source(
            key="security",
            label="Security settings",
            model=SecurityAuditEvent,
            action=SecurityAuditEvent.action,
            resource_type=SecurityAuditEvent.resource_type,
            resource_id=SecurityAuditEvent.resource_id,
            detail=SecurityAuditEvent.detail_json,
            actor_username=SecurityAuditEvent.actor_username,
            actor_email=SecurityAuditEvent.actor_email,
            actor_ip=SecurityAuditEvent.actor_ip,
            detail_redacted_at=SecurityAuditEvent.detail_redacted_at,
        ),
        Source(
            key="agents",
            label="Agents",
            model=AgentAuditEvent,
            action=AgentAuditEvent.event_type,
            resource_type=literal("agent"),
            resource_id=AgentAuditEvent.agent_id,
            detail=AgentAuditEvent.payload,
        ),
        Source(
            key="tools",
            label="Agent tools",
            model=AgentToolAuditEvent,
            action=AgentToolAuditEvent.event_type,
            resource_type=literal("agent_tool"),
            resource_id=AgentToolAuditEvent.tool_id,
            detail=AgentToolAuditEvent.payload,
        ),
        Source(
            key="knowledge",
            label="Knowledge",
            model=KnowledgeAuditEvent,
            action=KnowledgeAuditEvent.event_type,
            resource_type=literal("knowledge_document"),
            resource_id=KnowledgeAuditEvent.document_id,
            detail=KnowledgeAuditEvent.payload_json,
        ),
        Source(
            key="governance",
            label="Governance",
            model=GovernanceAuditEvent,
            action=GovernanceAuditEvent.event_type,
            resource_type=GovernanceAuditEvent.resource_type,
            resource_id=GovernanceAuditEvent.resource_id,
            detail=GovernanceAuditEvent.payload_json,
            outcome=GovernanceAuditEvent.outcome,
        ),
        Source(
            key="projects",
            label="Projects",
            model=ProjectAuditEvent,
            action=ProjectAuditEvent.event_type,
            resource_type=literal("project"),
            resource_id=ProjectAuditEvent.project_id,
            detail=ProjectAuditEvent.payload_json,
            outcome=ProjectAuditEvent.outcome,
        ),
        Source(
            key="api_keys",
            label="API keys",
            model=AlphaRouterApiKeyAuditLog,
            action=AlphaRouterApiKeyAuditLog.action,
            resource_type=literal("api_key"),
            resource_id=AlphaRouterApiKeyAuditLog.alpha_router_api_key_id,
            detail=AlphaRouterApiKeyAuditLog.changes_json,
        ),
        Source(
            key="connections",
            label="Provider connections",
            model=ConnectionAuditLog,
            action=ConnectionAuditLog.action,
            resource_type=literal("connection"),
            resource_id=ConnectionAuditLog.connection_id,
            detail=ConnectionAuditLog.changes_json,
        ),
    )
}

ALL = "all"


def source_keys(source: str | None) -> list[str]:
    """Which trails a request names. ``None``/"security" keeps the old behaviour."""

    if not source or source == "security":
        return ["security"]
    if source == ALL:
        return list(SOURCES)
    if source not in SOURCES:
        raise ValueError(f"unknown audit source {source!r}")
    return [source]


def union_for(keys: list[str]):
    """A selectable with the normalised columns over the named trails."""

    selects = [SOURCES[key].select() for key in keys]
    if len(selects) == 1:
        return selects[0].subquery("audit")
    return union_all(*selects).subquery("audit")


def apply_filters(
    audit,
    *,
    actor: str | None,
    action: str | None,
    resource_type: str | None,
    start: datetime.datetime | None,
    end: datetime.datetime | None,
) -> Select:
    stmt = select(audit)
    if actor and actor.strip():
        term = f"%{actor.strip()}%"
        # The stored copy of the name when a trail keeps one; the account it
        # points at otherwise (and for security rows written before the copy
        # existed). Filtering has to find every row the list would *show* under
        # that name, or typing what the table shows makes rows disappear.
        by_account = select(User.id).where(User.username.ilike(term))
        stmt = stmt.where(
            or_(
                audit.c.actor_username.ilike(term),
                and_(audit.c.actor_username.is_(None), audit.c.actor_user_id.in_(by_account)),
            )
        )
    if action:
        stmt = stmt.where(audit.c.action == action.strip())
    if resource_type:
        stmt = stmt.where(audit.c.resource_type == resource_type.strip())
    if start:
        stmt = stmt.where(audit.c.created_at >= start)
    if end:
        stmt = stmt.where(audit.c.created_at <= end)
    return stmt
