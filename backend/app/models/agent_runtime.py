"""Durable Agent turn, retrieval, citation, tool, and escalation evidence."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")


class AgentRun(Base):
    """One bounded Agent turn, without storing raw prompt or provider output."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'running', 'route_required', 'abstained', "
            "'succeeded', 'blocked', 'failed', 'cancelled')",
            name="chk_agent_runs_status",
        ),
        Index("ix_agent_runs_session_time", "chat_session_id", "created_at"),
        Index("ix_agent_runs_agent_time", "agent_id", "created_at"),
        Index("ix_agent_runs_user_time", "user_id", "created_at"),
        Index("ix_agent_runs_status_time", "status", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    correlation_id = Column(String(64), nullable=False, unique=True, index=True)
    chat_session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_session_id = Column(String(128), nullable=True, index=True)
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
    request_log_id = Column(
        Integer,
        ForeignKey("request_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    usage_operation_id = Column(
        String(36),
        ForeignKey("usage_operations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_version_id = Column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    connection_id = Column(
        Integer,
        ForeignKey("connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_catalog_id = Column(
        Integer,
        ForeignKey("ai_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source = Column(String(32), nullable=False, index=True)
    client_app = Column(String(128), nullable=True)
    private_mode = Column(Boolean, nullable=False, default=False, index=True)
    status = Column(String(24), nullable=False, default="planned", index=True)
    routing_outcome = Column(String(32), nullable=False)
    routing_reason = Column(String(255), nullable=True)
    routing_confidence = Column(Float, nullable=False, default=0.0)
    provider_type = Column(String(64), nullable=True)
    model_external_id = Column(String(512), nullable=True)
    query_sha256 = Column(String(64), nullable=False)
    retrieval_outcome = Column(String(32), nullable=False, default="not_attempted")
    retrieval_result_count = Column(Integer, nullable=False, default=0)
    knowledge_release_ids = Column(JsonDocument, nullable=False, default=list)
    index_version_ids = Column(JsonDocument, nullable=False, default=list)
    retrieval_error_codes = Column(JsonDocument, nullable=False, default=list)
    tool_execution_ids = Column(JsonDocument, nullable=False, default=list)
    handoff_event_ids = Column(JsonDocument, nullable=False, default=list)
    guardrail_events = Column(JsonDocument, nullable=False, default=list)
    egress_manifest = Column(JsonDocument, nullable=False, default=dict)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    total_cost_usd = Column(Numeric(20, 12), nullable=False, default=0)
    planning_latency_ms = Column(Integer, nullable=False, default=0)
    retrieval_latency_ms = Column(Integer, nullable=True)
    provider_latency_ms = Column(Integer, nullable=True)
    total_latency_ms = Column(Integer, nullable=True)
    output_displayed = Column(Boolean, nullable=False, default=False)
    completion_reason_code = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(String(500), nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        index=True,
    )
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class AgentRetrievalTrace(Base):
    """Metadata-only retrieval evidence for one Agent turn."""

    __tablename__ = "agent_retrieval_traces"
    __table_args__ = (
        UniqueConstraint("agent_run_id", name="uq_agent_retrieval_trace_run"),
        Index("ix_agent_retrieval_trace_outcome_time", "outcome", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    agent_run_id = Column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_sha256 = Column(String(64), nullable=False, index=True)
    outcome = Column(String(32), nullable=False, index=True)
    answerable = Column(Boolean, nullable=True)
    abstention_reason = Column(String(64), nullable=True)
    candidate_count = Column(Integer, nullable=False, default=0)
    post_authorized_count = Column(Integer, nullable=False, default=0)
    result_count = Column(Integer, nullable=False, default=0)
    estimated_context_tokens = Column(Integer, nullable=False, default=0)
    context_truncated = Column(Boolean, nullable=False, default=False)
    knowledge_release_ids = Column(JsonDocument, nullable=False, default=list)
    index_version_ids = Column(JsonDocument, nullable=False, default=list)
    component_errors = Column(JsonDocument, nullable=False, default=list)
    results = Column(JsonDocument, nullable=False, default=list)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        index=True,
    )


class AgentCitation(Base):
    """A verified citation reference emitted for an Agent turn."""

    __tablename__ = "agent_citations"
    __table_args__ = (
        UniqueConstraint(
            "agent_run_id",
            "citation_id",
            name="uq_agent_citation_run_marker",
        ),
        Index("ix_agent_citations_document_version", "document_version_id"),
        Index("ix_agent_citations_knowledge_base", "knowledge_base_id"),
    )

    id = Column(String(36), primary_key=True)
    agent_run_id = Column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    citation_id = Column(String(128), nullable=False)
    chunk_id = Column(
        String(36),
        ForeignKey("knowledge_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_id = Column(
        String(36),
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_version_id = Column(
        String(36),
        ForeignKey("knowledge_document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    release_id = Column(
        String(36),
        ForeignKey("knowledge_releases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(512), nullable=False)
    file_name = Column(String(512), nullable=False)
    mime_type = Column(String(255), nullable=False)
    page_number = Column(Integer, nullable=True)
    section = Column(String(512), nullable=True)
    authority = Column(String(64), nullable=False)
    classification = Column(String(64), nullable=False)
    effective_from = Column(String(64), nullable=True)
    effective_to = Column(String(64), nullable=True)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        index=True,
    )


class AgentToolRun(Base):
    """Durable metadata for one governed Tool Registry execution."""

    __tablename__ = "agent_tool_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', "
            "'blocked', 'cancelled', 'cached')",
            name="chk_agent_tool_runs_status",
        ),
        Index("ix_agent_tool_runs_run_time", "agent_run_id", "created_at"),
        Index("ix_agent_tool_runs_tool_time", "tool_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    agent_run_id = Column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_id = Column(
        String(36),
        ForeignKey("agent_tools.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tool_version_id = Column(
        String(36),
        ForeignKey("agent_tool_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(24), nullable=False, default="pending", index=True)
    effect_type = Column(String(24), nullable=False)
    arguments_sha256 = Column(String(64), nullable=False)
    output_sha256 = Column(String(64), nullable=True)
    idempotency_key_sha256 = Column(String(64), nullable=True)
    approval_recorded = Column(Boolean, nullable=False, default=False)
    attempts = Column(Integer, nullable=False, default=0)
    elapsed_ms = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(20, 12), nullable=False, default=0)
    redacted_paths = Column(JsonDocument, nullable=False, default=list)
    guardrail_reason_codes = Column(JsonDocument, nullable=False, default=list)
    error_code = Column(String(64), nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        index=True,
    )
    completed_at = Column(DateTime, nullable=True)


class AgentEscalationCase(Base):
    """Human escalation record detached from any concrete delivery adapter."""

    __tablename__ = "agent_escalation_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'assigned', 'resolved', 'closed', 'failed')",
            name="chk_agent_escalation_cases_status",
        ),
        Index("ix_agent_escalation_status_time", "status", "created_at"),
        Index("ix_agent_escalation_user_time", "user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    agent_run_id = Column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chat_session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(24), nullable=False, default="open", index=True)
    reason_code = Column(String(64), nullable=False)
    summary = Column(Text, nullable=True)
    adapter_key = Column(String(128), nullable=True)
    external_reference = Column(String(255), nullable=True)
    metadata_payload = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        index=True,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    )
    resolved_at = Column(DateTime, nullable=True)
