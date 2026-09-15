"""Consent-gated, ACL-rechecked Agent handoff state machine."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentAuditEvent, AgentHandoffEvent
from app.models.chat import ChatSession
from app.services.agent_policy_service import AgentRoutingPolicy, resolve_agent_policies
from app.services.agent_routing_service import (
    AgentExecutionTarget,
    AgentRoutingError,
    resolve_explicit_agent,
)
from app.services.resource_access_service import ResourceAccessSubject

_TURN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_FAILURE_CODE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_MAX_HANDOFF_CONTEXT_CHARACTERS = 16_000


class AgentHandoffError(ValueError):
    """Invalid handoff request or state transition."""


class AgentHandoffConflict(RuntimeError):
    """Concurrent or repeated state transition cannot be applied."""


@dataclass(frozen=True)
class HandoffContext:
    messages: tuple[dict[str, str], ...]
    digest: str
    truncated: bool


@dataclass(frozen=True)
class HandoffProposal:
    event: AgentHandoffEvent
    target: AgentExecutionTarget
    context: HandoffContext


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(block.get("text") or "").strip()
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part)
    return ""


def build_handoff_context(
    messages: list[dict[str, Any]],
    *,
    source_policy: AgentRoutingPolicy,
    target_policy: AgentRoutingPolicy,
) -> HandoffContext:
    """Transfer only bounded conversational text, never system/evidence/tool blocks."""

    maximum_messages = min(
        source_policy.transfer_history_messages,
        target_policy.transfer_history_messages,
    )
    if maximum_messages <= 0:
        canonical = "[]"
        return HandoffContext(
            messages=(),
            digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            truncated=False,
        )
    allow_assistant = source_policy.allow_assistant_context and target_policy.allow_assistant_context
    allowed_roles = {"user", "assistant"} if allow_assistant else {"user"}
    selected: list[dict[str, str]] = []
    for message in reversed(messages):
        role = str(message.get("role") or "").strip().lower()
        if role not in allowed_roles:
            continue
        text = _message_text(message)
        if not text:
            continue
        selected.append({"role": role, "content": text})
        if len(selected) >= maximum_messages:
            break
    selected.reverse()

    remaining = _MAX_HANDOFF_CONTEXT_CHARACTERS
    bounded: list[dict[str, str]] = []
    truncated = False
    for message in selected:
        text = message["content"]
        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        if text:
            bounded.append({"role": message["role"], "content": text})
            remaining -= len(text)
        if remaining <= 0:
            truncated = True
            break
    canonical = json.dumps(
        bounded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return HandoffContext(
        messages=tuple(bounded),
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        truncated=truncated,
    )


async def _audit(
    db: AsyncSession,
    event: AgentHandoffEvent,
    *,
    event_type: str,
    actor_user_id: int | None,
    payload: dict | None = None,
) -> None:
    db.add(
        AgentAuditEvent(
            id=str(uuid.uuid4()),
            agent_id=event.to_agent_id or event.from_agent_id,
            agent_version_id=event.to_agent_version_id or event.from_agent_version_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            reason=event.reason,
            payload={
                "handoff_event_id": event.id,
                "session_id": event.session_id,
                "turn_id": event.turn_id,
                "from_agent_id": event.from_agent_id,
                "to_agent_id": event.to_agent_id,
                **(payload or {}),
            },
        )
    )


async def _locked_session(
    db: AsyncSession,
    *,
    session_id: str,
    actor_user_id: int | None,
    subject: ResourceAccessSubject,
) -> ChatSession:
    session = (
        await db.execute(select(ChatSession).where(ChatSession.id == session_id).with_for_update())
    ).scalar_one_or_none()
    if session is None:
        raise AgentHandoffError("Chat session does not exist")
    principal_user_id = actor_user_id or subject.user_id
    if principal_user_id is None or int(session.user_id) != int(principal_user_id):
        raise AgentHandoffError("Chat session does not belong to this principal")
    return session


async def propose_agent_handoff(
    db: AsyncSession,
    *,
    session_id: str,
    turn_id: str,
    source: AgentExecutionTarget,
    subject: ResourceAccessSubject,
    reason: str,
    messages: list[dict[str, Any]],
    initiated_by_user_id: int | None,
    initiated_by: Literal["user", "runtime"],
    to_agent_id: str | None = None,
    to_agent_slug: str | None = None,
) -> HandoffProposal:
    clean_turn_id = (turn_id or "").strip()
    if not _TURN_ID_RE.fullmatch(clean_turn_id):
        raise AgentHandoffError("turn_id is invalid")
    clean_reason = " ".join((reason or "").split())
    if not clean_reason or len(clean_reason) > 2_000:
        raise AgentHandoffError("Handoff reason is required and limited to 2000 characters")
    await _locked_session(
        db,
        session_id=session_id,
        actor_user_id=initiated_by_user_id,
        subject=subject,
    )
    try:
        source = await resolve_explicit_agent(
            db,
            subject=subject,
            agent_id=source.agent.id,
            pinned_version_id=source.version.id,
        )
    except AgentRoutingError as exc:
        raise AgentHandoffError(str(exc)) from exc
    source_policies = resolve_agent_policies(source.version)
    maximum_handoffs = int(source_policies.routing.max_handoffs_per_turn or 0)
    existing_count = int(
        (
            await db.execute(
                select(func.count(AgentHandoffEvent.id)).where(
                    AgentHandoffEvent.session_id == session_id,
                    AgentHandoffEvent.turn_id == clean_turn_id,
                )
            )
        ).scalar_one()
        or 0
    )
    if existing_count >= maximum_handoffs:
        raise AgentHandoffError("Agent handoff limit exhausted for this turn")

    try:
        target = await resolve_explicit_agent(
            db,
            subject=subject,
            agent_id=to_agent_id,
            agent_slug=to_agent_slug,
        )
    except AgentRoutingError as exc:
        raise AgentHandoffError(str(exc)) from exc
    if target.agent.id == source.agent.id:
        raise AgentHandoffError("Source and target Agent must be different")
    if initiated_by == "runtime" and target.agent.slug not in set(source_policies.routing.allowed_handoff_targets):
        raise AgentHandoffError("Target Agent is not allowed by routing policy")

    target_policies = resolve_agent_policies(target.version)
    context = build_handoff_context(
        messages,
        source_policy=source_policies.routing,
        target_policy=target_policies.routing,
    )
    consent_required = bool(
        source_policies.routing.require_handoff_consent or target_policies.routing.require_handoff_consent
    )
    event = AgentHandoffEvent(
        id=str(uuid.uuid4()),
        session_id=session_id,
        turn_id=clean_turn_id,
        turn_ordinal=existing_count + 1,
        from_agent_id=source.agent.id,
        to_agent_id=target.agent.id,
        from_agent_version_id=source.version.id,
        to_agent_version_id=target.version.id,
        initiated_by_user_id=initiated_by_user_id,
        reason=clean_reason,
        status="proposed",
        consent_required=consent_required,
        context_digest=context.digest,
        context_payload={
            "schema_version": 1,
            "messages": list(context.messages),
            "truncated": context.truncated,
        },
    )
    db.add(event)
    await db.flush()
    await _audit(
        db,
        event,
        event_type="agent.handoff.proposed",
        actor_user_id=initiated_by_user_id,
        payload={
            "initiated_by": initiated_by,
            "turn_ordinal": existing_count + 1,
            "consent_required": consent_required,
            "context_truncated": context.truncated,
        },
    )
    return HandoffProposal(event=event, target=target, context=context)


async def _locked_event(
    db: AsyncSession,
    event_id: str,
) -> AgentHandoffEvent:
    event = (
        await db.execute(select(AgentHandoffEvent).where(AgentHandoffEvent.id == event_id).with_for_update())
    ).scalar_one_or_none()
    if event is None:
        raise AgentHandoffError("Handoff event does not exist")
    return event


async def accept_agent_handoff(
    db: AsyncSession,
    *,
    event_id: str,
    subject: ResourceAccessSubject,
    actor_user_id: int,
) -> AgentHandoffEvent:
    event = await _locked_event(db, event_id)
    if event.status != "proposed":
        raise AgentHandoffConflict("Only a proposed handoff can be accepted")
    await _locked_session(
        db,
        session_id=event.session_id,
        actor_user_id=actor_user_id,
        subject=subject,
    )
    target = await resolve_explicit_agent(
        db,
        subject=subject,
        agent_id=event.to_agent_id,
    )
    event.to_agent_version_id = target.version.id
    event.status = "accepted"
    event.decided_by_user_id = actor_user_id
    event.consented_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await _audit(
        db,
        event,
        event_type="agent.handoff.accepted",
        actor_user_id=actor_user_id,
    )
    return event


async def decline_agent_handoff(
    db: AsyncSession,
    *,
    event_id: str,
    subject: ResourceAccessSubject,
    actor_user_id: int,
) -> AgentHandoffEvent:
    event = await _locked_event(db, event_id)
    if event.status != "proposed":
        raise AgentHandoffConflict("Only a proposed handoff can be declined")
    await _locked_session(
        db,
        session_id=event.session_id,
        actor_user_id=actor_user_id,
        subject=subject,
    )
    event.status = "declined"
    event.decided_by_user_id = actor_user_id
    event.completed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await _audit(
        db,
        event,
        event_type="agent.handoff.declined",
        actor_user_id=actor_user_id,
    )
    return event


async def complete_agent_handoff(
    db: AsyncSession,
    *,
    event_id: str,
    subject: ResourceAccessSubject,
    actor_user_id: int,
) -> tuple[AgentHandoffEvent, AgentExecutionTarget]:
    event = await _locked_event(db, event_id)
    if event.status != "accepted":
        raise AgentHandoffConflict("Only an accepted handoff can be completed")
    await _locked_session(
        db,
        session_id=event.session_id,
        actor_user_id=actor_user_id,
        subject=subject,
    )
    if event.consent_required and event.consented_at is None:
        raise AgentHandoffConflict("Required handoff consent was not recorded")
    target = await resolve_explicit_agent(
        db,
        subject=subject,
        agent_id=event.to_agent_id,
    )
    event.to_agent_version_id = target.version.id
    event.status = "completed"
    event.completed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await _audit(
        db,
        event,
        event_type="agent.handoff.completed",
        actor_user_id=actor_user_id,
    )
    return event, target


async def fail_agent_handoff(
    db: AsyncSession,
    *,
    event_id: str,
    failure_code: str,
    actor_user_id: int | None,
) -> AgentHandoffEvent:
    clean_code = (failure_code or "").strip().lower()
    if not _FAILURE_CODE_RE.fullmatch(clean_code):
        raise AgentHandoffError("failure_code is invalid")
    event = await _locked_event(db, event_id)
    if event.status not in {"proposed", "accepted"}:
        raise AgentHandoffConflict("Only an open handoff can fail")
    event.status = "failed"
    event.failure_code = clean_code
    event.completed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await _audit(
        db,
        event,
        event_type="agent.handoff.failed",
        actor_user_id=actor_user_id,
        payload={"failure_code": clean_code},
    )
    return event
