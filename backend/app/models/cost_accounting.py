"""Provider-agnostic usage, pricing, ledger, and reconciliation records."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base


class PricingSnapshot(Base):
    """Immutable provider/catalog pricing used to calculate one or more events."""

    __tablename__ = "pricing_snapshots"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_pricing_snapshots_fingerprint"),
        Index(
            "ix_pricing_snapshots_provider_model_effective",
            "provider_type",
            "model_id",
            "effective_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    connection_id = Column(
        Integer,
        ForeignKey("connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_type = Column(String(64), nullable=False, index=True)
    model_id = Column(String(512), nullable=True, index=True)
    service_type = Column(String(32), nullable=False, index=True)
    currency = Column(String(8), nullable=False, default="USD")
    source = Column(String(32), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    active_scope_key = Column(String(64), nullable=True, unique=True, index=True)
    pricing_json = Column(Text, nullable=False)
    effective_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
    )


class UsageOperation(Base):
    """One user-visible operation that may contain several billable calls."""

    __tablename__ = "usage_operations"
    __table_args__ = (
        Index("ix_usage_operations_subject_time", "subject_type", "subject_id", "started_at"),
        Index("ix_usage_operations_status_time", "status", "started_at"),
    )

    id = Column(String(36), primary_key=True)
    subject_type = Column(String(24), nullable=True, index=True)
    subject_id = Column(Integer, nullable=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    alpha_router_api_key_id = Column(
        Integer,
        ForeignKey("alpha_router_api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    budget_reservation_id = Column(String(36), nullable=True, index=True)
    operation_type = Column(String(32), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    client_app = Column(String(128), nullable=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    accounting_status = Column(
        String(24),
        nullable=False,
        default="unpriced",
        index=True,
    )
    idempotency_key = Column(String(200), nullable=False, unique=True, index=True)
    total_cost_usd = Column(Numeric(20, 12), nullable=False, default=0)
    provider_cost_usd = Column(Numeric(20, 12), nullable=True)
    calculated_cost_usd = Column(Numeric(20, 12), nullable=True)
    unpriced_event_count = Column(Integer, nullable=False, default=0)
    metadata_json = Column(Text, nullable=True)
    started_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )
    completed_at = Column(DateTime, nullable=True)
    reconciled_at = Column(DateTime, nullable=True)


class ReconciliationRun(Base):
    """One provider usage/invoice reconciliation batch."""

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        Index(
            "ix_reconciliation_runs_provider_time",
            "provider_type",
            "started_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    connection_id = Column(
        Integer,
        ForeignKey("connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_type = Column(String(64), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="running", index=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    expected_cost_usd = Column(Numeric(20, 12), nullable=False, default=0)
    reported_cost_usd = Column(Numeric(20, 12), nullable=False, default=0)
    adjustment_usd = Column(Numeric(20, 12), nullable=False, default=0)
    matched_event_count = Column(Integer, nullable=False, default=0)
    unmatched_event_count = Column(Integer, nullable=False, default=0)
    raw_summary_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )
    completed_at = Column(DateTime, nullable=True)


class UsageEvent(Base):
    """A concrete upstream attempt, including retries and helper/tool calls."""

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_usage_events_idempotency_key"),
        Index("ix_usage_events_operation_attempt", "operation_id", "attempt_index"),
        Index(
            "ix_usage_events_upstream_request",
            "connection_id",
            "upstream_request_id",
        ),
        Index("ix_usage_events_cost_state_time", "cost_confidence", "completed_at"),
    )

    id = Column(String(36), primary_key=True)
    operation_id = Column(
        String(36),
        ForeignKey("usage_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id = Column(
        Integer,
        ForeignKey("connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pricing_snapshot_id = Column(
        Integer,
        ForeignKey("pricing_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reconciliation_run_id = Column(
        String(36),
        ForeignKey("reconciliation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_type = Column(String(64), nullable=False, index=True)
    service_type = Column(String(32), nullable=False, index=True)
    operation_name = Column(String(64), nullable=False)
    model_id = Column(String(512), nullable=True, index=True)
    attempt_index = Column(Integer, nullable=False, default=0)
    upstream_request_id = Column(String(255), nullable=True, index=True)
    idempotency_key = Column(String(220), nullable=False)
    status = Column(String(24), nullable=False, default="success", index=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    cache_write_tokens = Column(Integer, nullable=False, default=0)
    reasoning_tokens = Column(Integer, nullable=False, default=0)
    quantity = Column(Float, nullable=True)
    unit = Column(String(32), nullable=True)
    provider_cost_usd = Column(Numeric(20, 12), nullable=True)
    calculated_cost_usd = Column(Numeric(20, 12), nullable=True)
    final_cost_usd = Column(Numeric(20, 12), nullable=True)
    cost_source = Column(String(32), nullable=False, default="unknown", index=True)
    cost_confidence = Column(
        String(24),
        nullable=False,
        default="unknown",
        index=True,
    )
    raw_usage_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    reconciliation_attempts = Column(Integer, nullable=False, default=0)
    last_reconciliation_attempt_at = Column(DateTime, nullable=True, index=True)
    started_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )
    completed_at = Column(DateTime, nullable=True, index=True)
    reconciled_at = Column(DateTime, nullable=True)


class CostLineItem(Base):
    """A normalized quantity × unit-price component of a usage event."""

    __tablename__ = "cost_line_items"
    __table_args__ = (Index("ix_cost_line_items_event_category", "usage_event_id", "category"),)

    id = Column(Integer, primary_key=True)
    usage_event_id = Column(
        String(36),
        ForeignKey("usage_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = Column(String(64), nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    unit = Column(String(32), nullable=False)
    unit_price_usd = Column(Numeric(24, 14), nullable=True)
    cost_usd = Column(Numeric(20, 12), nullable=True)
    pricing_source = Column(String(32), nullable=False)
    metadata_json = Column(Text, nullable=True)


class LedgerEntry(Base):
    """Immutable signed budget entry; positive amounts consume budget."""

    __tablename__ = "cost_ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_cost_ledger_entries_idempotency_key"),
        Index("ix_cost_ledger_subject_time", "subject_type", "subject_id", "created_at"),
        Index("ix_cost_ledger_operation_time", "operation_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    operation_id = Column(
        String(36),
        ForeignKey("usage_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    usage_event_id = Column(
        String(36),
        ForeignKey("usage_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_log_id = Column(
        Integer,
        ForeignKey("request_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reconciliation_run_id = Column(
        String(36),
        ForeignKey("reconciliation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_type = Column(String(24), nullable=True, index=True)
    subject_id = Column(Integer, nullable=True, index=True)
    entry_type = Column(String(24), nullable=False, index=True)
    amount_usd = Column(Numeric(20, 12), nullable=False)
    cost_source = Column(String(32), nullable=False)
    cost_confidence = Column(String(24), nullable=False)
    idempotency_key = Column(String(240), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )
    effective_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )
    is_reversed = Column(Boolean, nullable=False, default=False)
