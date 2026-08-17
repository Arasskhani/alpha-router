"""Legal holds, retention evidence, and tamper-evident governance audit."""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.agent_runtime import AgentRun
from app.models.chat import ChatSession
from app.models.governance import GovernanceAuditEvent
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    LegalHold,
)

SUPPORTED_HOLD_RESOURCE_TYPES = frozenset(
    {
        "agent",
        "agent_run",
        "chat_session",
        "knowledge_base",
        "knowledge_document",
        "knowledge_document_version",
    }
)
_AUDIT_LOCK_KEY = 4_156_085_146_008_932_117
_REDACTED_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
    "prompt",
    "content",
    "message",
    "output",
)


@dataclass(frozen=True)
class AuditChainVerification:
    valid: bool
    event_count: int
    first_invalid_event_id: str | None
    head_hash: str | None


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _sanitize_audit_value(
    value: Any,
    *,
    key: str = "",
    depth: int = 0,
) -> Any:
    normalized_key = key.strip().lower()
    if normalized_key and any(part in normalized_key for part in _REDACTED_KEY_PARTS):
        return "[REDACTED]"
    if depth >= 5:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2_000]
    if isinstance(value, dict):
        return {
            str(item_key)[:128]: _sanitize_audit_value(
                item_value,
                key=str(item_key),
                depth=depth + 1,
            )
            for item_key, item_value in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_audit_value(item, depth=depth + 1)
            for item in list(value)[:100]
        ]
    return str(value)[:2_000]


def _canonical_event_payload(
    *,
    event_id: str,
    event_type: str,
    resource_type: str,
    resource_id: str | None,
    actor_user_id: int | None,
    outcome: str,
    payload: dict[str, Any],
    previous_event_hash: str | None,
    created_at: datetime.datetime,
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "event_type": event_type,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "actor_user_id": actor_user_id,
            "outcome": outcome,
            "payload": payload,
            "previous_event_hash": previous_event_hash,
            "created_at": created_at.isoformat(timespec="microseconds"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


async def append_governance_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    resource_type: str,
    resource_id: str | None = None,
    actor_user_id: int | None = None,
    outcome: str = "success",
    payload: dict[str, Any] | None = None,
) -> GovernanceAuditEvent:
    """Append one redacted event to the serialized hash chain."""

    clean_event_type = str(event_type or "").strip()[:96]
    clean_resource_type = str(resource_type or "").strip()[:64]
    clean_outcome = str(outcome or "").strip().lower()
    if not clean_event_type or not clean_resource_type:
        raise ValueError("Audit event_type and resource_type are required")
    if clean_outcome not in {"success", "denied", "failed", "scheduled"}:
        raise ValueError("Unsupported governance audit outcome")

    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _AUDIT_LOCK_KEY},
        )
    previous = (
        await db.execute(
            select(GovernanceAuditEvent)
            .order_by(
                GovernanceAuditEvent.created_at.desc(),
                GovernanceAuditEvent.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    previous_hash = previous.event_hash if previous is not None else None
    event_id = str(uuid.uuid4())
    created_at = _now()
    if previous is not None and created_at <= previous.created_at:
        created_at = previous.created_at + datetime.timedelta(microseconds=1)
    clean_payload = _sanitize_audit_value(dict(payload or {}))
    assert isinstance(clean_payload, dict)
    digest = hashlib.sha256(
        _canonical_event_payload(
            event_id=event_id,
            event_type=clean_event_type,
            resource_type=clean_resource_type,
            resource_id=(str(resource_id)[:128] if resource_id else None),
            actor_user_id=actor_user_id,
            outcome=clean_outcome,
            payload=clean_payload,
            previous_event_hash=previous_hash,
            created_at=created_at,
        )
    ).hexdigest()
    event = GovernanceAuditEvent(
        id=event_id,
        event_type=clean_event_type,
        resource_type=clean_resource_type,
        resource_id=str(resource_id)[:128] if resource_id else None,
        actor_user_id=actor_user_id,
        outcome=clean_outcome,
        payload_json=clean_payload,
        previous_event_hash=previous_hash,
        event_hash=digest,
        created_at=created_at,
    )
    db.add(event)
    await db.flush()
    return event


async def verify_governance_audit_chain(
    db: AsyncSession,
) -> AuditChainVerification:
    rows = (
        (
            await db.execute(
                select(GovernanceAuditEvent).order_by(
                    GovernanceAuditEvent.created_at,
                    GovernanceAuditEvent.id,
                )
            )
        )
        .scalars()
        .all()
    )
    previous_hash: str | None = None
    for row in rows:
        expected = hashlib.sha256(
            _canonical_event_payload(
                event_id=row.id,
                event_type=row.event_type,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                actor_user_id=row.actor_user_id,
                outcome=row.outcome,
                payload=dict(row.payload_json or {}),
                previous_event_hash=previous_hash,
                created_at=row.created_at,
            )
        ).hexdigest()
        if row.previous_event_hash != previous_hash or row.event_hash != expected:
            return AuditChainVerification(
                valid=False,
                event_count=len(rows),
                first_invalid_event_id=row.id,
                head_hash=previous_hash,
            )
        previous_hash = row.event_hash
    return AuditChainVerification(
        valid=True,
        event_count=len(rows),
        first_invalid_event_id=None,
        head_hash=previous_hash,
    )


async def _assert_hold_resource_exists(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: str,
) -> None:
    model_by_type = {
        "agent": Agent,
        "agent_run": AgentRun,
        "chat_session": ChatSession,
        "knowledge_base": KnowledgeBase,
        "knowledge_document": KnowledgeDocument,
        "knowledge_document_version": KnowledgeDocumentVersion,
    }
    model = model_by_type.get(resource_type)
    if model is None:
        raise ValueError("Unsupported legal-hold resource type")
    if await db.get(model, resource_id) is None:
        raise LookupError("Legal-hold resource not found")


async def has_active_legal_hold(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: str,
) -> bool:
    return (
        await db.execute(
            select(LegalHold.id)
            .where(
                LegalHold.resource_type == resource_type,
                LegalHold.resource_id == resource_id,
                LegalHold.status == "active",
            )
            .limit(1)
        )
    ).scalar_one_or_none() is not None


async def place_legal_hold(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: str,
    reason: str,
    actor_user_id: int,
) -> LegalHold:
    clean_type = str(resource_type or "").strip().lower()
    clean_id = str(resource_id or "").strip()
    clean_reason = " ".join(str(reason or "").split()).strip()
    if clean_type not in SUPPORTED_HOLD_RESOURCE_TYPES:
        raise ValueError("Unsupported legal-hold resource type")
    if not clean_id or len(clean_id) > 128:
        raise ValueError("Legal-hold resource id is invalid")
    if not clean_reason or len(clean_reason) > 8_000:
        raise ValueError("Legal-hold reason is required and limited to 8000 characters")
    await _assert_hold_resource_exists(
        db,
        resource_type=clean_type,
        resource_id=clean_id,
    )
    existing = (
        await db.execute(
            select(LegalHold).where(
                LegalHold.resource_type == clean_type,
                LegalHold.resource_id == clean_id,
                LegalHold.status == "active",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    hold = LegalHold(
        id=str(uuid.uuid4()),
        resource_type=clean_type,
        resource_id=clean_id,
        status="active",
        reason=clean_reason,
        placed_by_user_id=actor_user_id,
        placed_at=_now(),
    )
    db.add(hold)
    await db.flush()
    await append_governance_audit_event(
        db,
        event_type="governance.legal_hold.placed",
        resource_type=clean_type,
        resource_id=clean_id,
        actor_user_id=actor_user_id,
        payload={"legal_hold_id": hold.id, "reason": clean_reason},
    )
    return hold


async def release_legal_hold(
    db: AsyncSession,
    *,
    hold_id: str,
    actor_user_id: int,
    reason: str | None = None,
) -> LegalHold:
    hold = await db.get(LegalHold, hold_id)
    if hold is None:
        raise LookupError("Legal hold not found")
    if hold.status != "active":
        raise ValueError("Legal hold is already released")
    hold.status = "released"
    hold.released_by_user_id = actor_user_id
    hold.released_at = _now()
    await append_governance_audit_event(
        db,
        event_type="governance.legal_hold.released",
        resource_type=hold.resource_type,
        resource_id=hold.resource_id,
        actor_user_id=actor_user_id,
        payload={
            "legal_hold_id": hold.id,
            "release_reason": " ".join(str(reason or "").split())[:8_000] or None,
        },
    )
    return hold
