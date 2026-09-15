"""Tamper-evident governance audit records."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapper
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")


class GovernanceAuditEvent(Base):
    """Append-only, hash-chained evidence for governance operations."""

    __tablename__ = "governance_audit_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success', 'denied', 'failed', 'scheduled')",
            name="chk_governance_audit_outcome",
        ),
        # Shape as the Alembic revision created it: a named unique constraint
        # plus a plain lookup index (not one unique index).
        UniqueConstraint("event_hash", name="uq_governance_audit_events_event_hash"),
        Index("ix_governance_audit_events_event_hash", "event_hash"),
        Index(
            "ix_governance_audit_resource_time",
            "resource_type",
            "resource_id",
            "created_at",
        ),
        Index("ix_governance_audit_actor_time", "actor_user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    event_type = Column(String(96), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(128), nullable=True, index=True)
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    outcome = Column(String(16), nullable=False, default="success", index=True)
    payload_json = Column(JsonDocument, nullable=False, default=dict)
    previous_event_hash = Column(String(64), nullable=True)
    event_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        index=True,
    )


def _reject_governance_audit_mutation(
    _mapper: Mapper,
    _connection: object,
    _target: GovernanceAuditEvent,
) -> None:
    raise ValueError("Governance audit events are append-only")


event.listen(
    GovernanceAuditEvent,
    "before_update",
    _reject_governance_audit_mutation,
)
event.listen(
    GovernanceAuditEvent,
    "before_delete",
    _reject_governance_audit_mutation,
)
