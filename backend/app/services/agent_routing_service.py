"""ACL-aware explicit selection and deterministic specialist Agent routing."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent import Agent, AgentVersion
from app.services.agent_definition_service import get_active_agent_version
from app.services.agent_policy_service import (
    AgentPolicyValidationError,
    AgentRoutingPolicy,
    resolve_agent_policies,
)
from app.services.knowledge_sparse_service import (
    lexical_tokens,
    normalize_lexical_text,
)
from app.services.resource_access_service import (
    ResourceAccessSubject,
    filter_agents_for_subject,
    user_can_access_agent,
)


class AgentRoutingError(ValueError):
    """Base routing error."""


class AgentNotFound(AgentRoutingError):
    """Requested Agent does not exist or has no executable version."""


class AgentAccessDenied(PermissionError):
    """The current principal cannot use the selected Agent."""


@dataclass(frozen=True)
class AgentExecutionTarget:
    agent: Agent
    version: AgentVersion
    pinned_version: bool


@dataclass(frozen=True)
class AgentRouteAlternative:
    agent_id: str
    agent_slug: str
    agent_name: str
    agent_version_id: str
    confidence: float


@dataclass(frozen=True)
class AgentRoutingDecision:
    kind: str
    target: AgentExecutionTarget | None
    confidence: float
    alternatives: tuple[AgentRouteAlternative, ...]
    reason: str


async def resolve_explicit_agent(
    db: AsyncSession,
    *,
    subject: ResourceAccessSubject,
    agent_id: str | None = None,
    agent_slug: str | None = None,
    pinned_version_id: str | None = None,
) -> AgentExecutionTarget:
    """Resolve user-selected Agent while reevaluating current ACL every request."""

    if bool(agent_id) == bool(agent_slug):
        raise AgentRoutingError("Exactly one of agent_id or agent_slug is required")
    if agent_id:
        agent = await db.get(Agent, agent_id)
    else:
        normalized_slug = (agent_slug or "").strip().lower()
        agent = (await db.execute(select(Agent).where(Agent.slug == normalized_slug))).scalar_one_or_none()
    if agent is None or agent.status != "active":
        raise AgentNotFound("The selected Agent is unavailable")
    if not await user_can_access_agent(db, agent, subject):
        raise AgentAccessDenied("The current principal cannot access this Agent")

    if pinned_version_id:
        version = await db.get(AgentVersion, pinned_version_id)
        if (
            version is None
            or version.agent_id != agent.id
            or version.status not in {"published", "archived"}
            or version.published_at is None
        ):
            raise AgentNotFound("The pinned Agent version was never published or is unavailable")
        return AgentExecutionTarget(agent=agent, version=version, pinned_version=True)

    version = await get_active_agent_version(db, agent.id)
    if version is None:
        raise AgentNotFound("The selected Agent has no active published version")
    return AgentExecutionTarget(agent=agent, version=version, pinned_version=False)


def _phrase_score(query: str, query_tokens: set[str], phrase: str) -> float:
    normalized = normalize_lexical_text(phrase)
    if not normalized:
        return 0.0
    if normalized in query:
        return 1.0
    phrase_tokens = set(lexical_tokens(normalized))
    if not phrase_tokens:
        return 0.0
    overlap = len(query_tokens & phrase_tokens)
    return 0.5 * overlap / len(phrase_tokens)


def _route_score(
    *,
    query: str,
    agent: Agent,
    policy: AgentRoutingPolicy,
) -> float:
    query_normalized = normalize_lexical_text(query)
    query_tokens = set(lexical_tokens(query_normalized))
    if not query_tokens:
        return 0.0
    keyword_scores = [_phrase_score(query_normalized, query_tokens, value) for value in policy.keywords]
    example_scores = [_phrase_score(query_normalized, query_tokens, value) for value in policy.examples]
    identity = " ".join(
        value
        for value in (
            agent.name,
            agent.slug,
            agent.category or "",
            agent.description or "",
        )
        if value
    )
    identity_tokens = set(lexical_tokens(identity))
    identity_score = min(1.0, len(query_tokens & identity_tokens) / max(1, len(query_tokens))) * 0.15
    keyword_score = max(keyword_scores, default=0.0) * 0.75
    example_score = max(example_scores, default=0.0) * 0.35
    return min(1.0, keyword_score + example_score + identity_score)


async def _route_candidates(
    db: AsyncSession,
    subject: ResourceAccessSubject,
) -> list[tuple[Agent, AgentVersion, AgentRoutingPolicy]]:
    settings = get_settings()
    maximum = max(1, min(256, settings.agent_router_max_candidates))
    rows = (
        await db.execute(
            select(Agent, AgentVersion)
            .join(AgentVersion, AgentVersion.agent_id == Agent.id)
            .where(
                Agent.status == "active",
                AgentVersion.status == "published",
                AgentVersion.active_scope_key.is_not(None),
            )
            .order_by(Agent.sort_order, Agent.slug)
            .limit(maximum + 1)
        )
    ).all()
    if len(rows) > maximum:
        raise AgentRoutingError("Active Agent count exceeds the configured router limit")
    allowed = {
        agent.id
        for agent in await filter_agents_for_subject(
            db,
            [agent for agent, _ in rows],
            subject,
        )
    }
    candidates: list[tuple[Agent, AgentVersion, AgentRoutingPolicy]] = []
    for agent, version in rows:
        if agent.id not in allowed:
            continue
        if version.active_scope_key != f"agent:{agent.id}":
            continue
        try:
            policy = resolve_agent_policies(version).routing
        except AgentPolicyValidationError:
            # One malformed published draft must not route traffic to itself or
            # take all healthy specialists out of service.
            continue
        if policy.enabled and not policy.explicit_only:
            candidates.append((agent, version, policy))
    return candidates


async def route_agent(
    db: AsyncSession,
    *,
    subject: ResourceAccessSubject,
    query: str,
    agent_id: str | None = None,
    agent_slug: str | None = None,
    pinned_version_id: str | None = None,
) -> AgentRoutingDecision:
    """Prefer explicit selection; otherwise return a bounded routing decision."""

    clean_query = " ".join((query or "").split())
    if not clean_query:
        raise AgentRoutingError("Routing query cannot be empty")
    if agent_id or agent_slug:
        target = await resolve_explicit_agent(
            db,
            subject=subject,
            agent_id=agent_id,
            agent_slug=agent_slug,
            pinned_version_id=pinned_version_id,
        )
        return AgentRoutingDecision(
            kind="explicit",
            target=target,
            confidence=1.0,
            alternatives=(),
            reason="user_selected_agent",
        )
    if pinned_version_id:
        raise AgentRoutingError("A pinned version requires an explicit Agent")

    scored: list[tuple[float, int, str, Agent, AgentVersion, AgentRoutingPolicy]] = []
    for agent, version, policy in await _route_candidates(db, subject):
        confidence = _route_score(query=clean_query, agent=agent, policy=policy)
        scored.append((confidence, policy.priority, agent.slug, agent, version, policy))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    alternatives = tuple(
        AgentRouteAlternative(
            agent_id=agent.id,
            agent_slug=agent.slug,
            agent_name=agent.name,
            agent_version_id=version.id,
            confidence=round(confidence, 6),
        )
        for confidence, _, _, agent, version, _ in scored[:3]
        if confidence > 0.0
    )
    if not scored or scored[0][0] <= 0.0:
        return AgentRoutingDecision(
            kind="no_match",
            target=None,
            confidence=0.0,
            alternatives=alternatives,
            reason="no_specialist_signal",
        )

    top_confidence, _, _, top_agent, top_version, top_policy = scored[0]
    minimum_confidence = float(top_policy.minimum_confidence or 0.0)
    second_confidence = scored[1][0] if len(scored) > 1 else 0.0
    minimum_margin = float(top_policy.minimum_margin or 0.0)
    if top_confidence < minimum_confidence:
        return AgentRoutingDecision(
            kind="clarification",
            target=None,
            confidence=round(top_confidence, 6),
            alternatives=alternatives,
            reason="confidence_below_threshold",
        )
    if second_confidence > 0.0 and top_confidence - second_confidence < minimum_margin:
        return AgentRoutingDecision(
            kind="clarification",
            target=None,
            confidence=round(top_confidence, 6),
            alternatives=alternatives,
            reason="ambiguous_specialist_match",
        )
    return AgentRoutingDecision(
        kind="selected",
        target=AgentExecutionTarget(
            agent=top_agent,
            version=top_version,
            pinned_version=False,
        ),
        confidence=round(top_confidence, 6),
        alternatives=alternatives,
        reason="specialist_policy_match",
    )
