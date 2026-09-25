"""One shape over the product's ten administrative audit trails.

Each trail keeps its own table, with its own reasons: the governance chain is
hash-linked and append-only, the agent and knowledge trails are guarded by
triggers, the API-key and connection logs predate all of that. Nothing here
writes to any of them. This module only reads them through one normalised
projection - source, time, actor, action, resource, detail - so the Admin Logs
page can show an investigation everything that happened, in one order.

Adding a trail is one more entry in ``SOURCES``.

The tenth, ``browser_extension``, is what the browser extension did for each
person: a page shared with a model (the site, how much text, which model, never
the text), and later each step of the browser agent.

The ninth, ``authentication``, is the one that was here before under another
name: sign-ins used to be three ``action`` values in the security trail, and
when they moved to ``auth_events`` this page would have silently stopped
showing them. They are read back in here so "everything that happened" still
includes who signed in, and the Sign-in Activity page is where the typed
columns are filtered and exported.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, String, Text, and_, cast, literal, literal_column, null, or_, select, union_all
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import GenericFunction

from app.models.agent import AgentAuditEvent
from app.models.auth_event import AuthEvent
from app.models.agent_tool import AgentToolAuditEvent
from app.models.api_key import AlphaRouterApiKeyAuditLog
from app.models.connection import ConnectionAuditLog
from app.models.extension import ExtensionEvent
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


class json_detail(GenericFunction):  # noqa: N801 -- a SQL function, named like one
    """``{"k": v, ...}`` as JSON text, built by the database from typed columns.

    ``auth_events`` stores facts in columns rather than a detail blob, which is
    the point of that table; the union wants one text column. Every database
    this product runs on has a JSON constructor that escapes correctly - they
    just disagree on its name - so this compiles to each. Building the string
    with ``||`` would not escape a quote in a provider message.
    """

    type = Text()
    inherit_cache = True


@compiles(json_detail, "sqlite")
def _json_detail_sqlite(element, compiler, **kw):
    return f"json_object({compiler.process(element.clauses, **kw)})"


@compiles(json_detail, "postgresql")
def _json_detail_postgresql(element, compiler, **kw):
    return f"jsonb_build_object({compiler.process(element.clauses, **kw)})::text"


@compiles(json_detail)
def _json_detail_default(element, compiler, **kw):
    return f"json_object({compiler.process(element.clauses, **kw)})"


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
    #: Overrides for tables whose time and actor columns are not named
    #: ``created_at`` / ``actor_user_id``.
    created_at: Any = None
    actor_user_id: Any = None

    def select(self) -> Select:
        m = self.model
        return select(
            literal(self.key).label("source"),
            cast(m.id, String).label("id"),
            (self.created_at if self.created_at is not None else m.created_at).label("created_at"),
            (self.actor_user_id if self.actor_user_id is not None else m.actor_user_id).label("actor_user_id"),
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
        # The "actor" of a sign-in row is the account it concerns - the person
        # who signed in, or the name someone failed to sign in as. The same
        # ``resource_type`` the legacy security rows carried, so an operator's
        # saved filter for "authentication" keeps finding these.
        Source(
            key="authentication",
            label="Sign-in activity",
            model=AuthEvent,
            action=AuthEvent.event_type,
            resource_type=literal("authentication"),
            resource_id=AuthEvent.session_id,
            detail=json_detail(
                literal_column("'reason_code'"),
                AuthEvent.reason_code,
                literal_column("'reason_detail'"),
                AuthEvent.reason_detail,
                literal_column("'auth_method'"),
                AuthEvent.auth_method,
                literal_column("'scope'"),
                AuthEvent.scope,
                literal_column("'user_agent'"),
                AuthEvent.user_agent,
                literal_column("'backfilled'"),
                AuthEvent.backfilled,
            ),
            actor_username=AuthEvent.username,
            actor_ip=AuthEvent.ip,
            outcome=AuthEvent.outcome,
            created_at=AuthEvent.occurred_at,
            actor_user_id=AuthEvent.user_id,
        ),
        # Each row is about one site: the host, never a full URL.
        Source(
            key="browser_extension",
            label="Browser extension",
            model=ExtensionEvent,
            action=ExtensionEvent.kind,
            resource_type=literal("site"),
            resource_id=ExtensionEvent.site,
            detail=ExtensionEvent.detail_json,
            actor_username=ExtensionEvent.actor_username,
            actor_ip=ExtensionEvent.actor_ip,
            outcome=ExtensionEvent.outcome,
            detail_redacted_at=ExtensionEvent.detail_redacted_at,
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
