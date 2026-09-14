"""Versioned golden datasets, deterministic runs, and review evidence."""

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
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class EvaluationDataset(Base):
    """Immutable-on-activation golden set for one specialist Agent."""

    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "slug",
            "version_number",
            name="uq_evaluation_dataset_agent_slug_version",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="chk_evaluation_datasets_status",
        ),
        Index(
            "ix_evaluation_datasets_agent_status",
            "agent_id",
            "status",
            "version_number",
        ),
    )

    id = Column(String(36), primary_key=True)
    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug = Column(String(128), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    version_number = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="draft", index=True)
    minimum_case_count = Column(Integer, nullable=False, default=100)
    is_publish_gate = Column(Boolean, nullable=False, default=True, index=True)
    thresholds_json = Column(JsonDocument, nullable=False, default=dict)
    metadata_json = Column(JsonDocument, nullable=False, default=dict)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    activated_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)
    activated_at = Column(DateTime, nullable=True, index=True)
    archived_at = Column(DateTime, nullable=True)

    cases = relationship(
        "EvaluationCase",
        back_populates="dataset",
        cascade="all, delete-orphan",
    )
    runs = relationship(
        "EvaluationRun",
        back_populates="dataset",
        cascade="all, delete-orphan",
    )


class EvaluationCase(Base):
    """One prompt-free-of-secrets expectation in a versioned golden dataset."""

    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "case_key",
            name="uq_evaluation_cases_dataset_key",
        ),
        CheckConstraint(
            "category IN ("
            "'routing', 'retrieval', 'citation', 'abstention', "
            "'acl', 'injection', 'escalation', 'quality'"
            ")",
            name="chk_evaluation_cases_category",
        ),
        CheckConstraint(
            "language IN ('fa', 'en', 'multilingual')",
            name="chk_evaluation_cases_language",
        ),
        Index(
            "ix_evaluation_cases_dataset_category",
            "dataset_id",
            "category",
            "enabled",
        ),
    )

    id = Column(String(36), primary_key=True)
    dataset_id = Column(
        String(36),
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_key = Column(String(160), nullable=False)
    category = Column(String(24), nullable=False, index=True)
    language = Column(String(16), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    expected_json = Column(JsonDocument, nullable=False, default=dict)
    tags_json = Column(JsonDocument, nullable=False, default=list)
    weight = Column(Float, nullable=False, default=1.0)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    dataset = relationship("EvaluationDataset", back_populates="cases")
    results = relationship(
        "EvaluationResult",
        back_populates="case",
        passive_deletes=True,
    )


class EvaluationRun(Base):
    """One reproducible scorecard for a dataset and immutable Agent version."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_evaluation_runs_idempotency_key",
        ),
        CheckConstraint(
            "status IN ('running', 'awaiting_review', 'passed', 'failed', 'error', 'cancelled')",
            name="chk_evaluation_runs_status",
        ),
        CheckConstraint(
            "trigger_type IN ('manual', 'publish_gate', 'ci', 'seed', 'scheduled')",
            name="chk_evaluation_runs_trigger",
        ),
        CheckConstraint(
            "review_status IN ('not_required', 'pending', 'approved', 'rejected')",
            name="chk_evaluation_runs_review_status",
        ),
        Index(
            "ix_evaluation_runs_version_status",
            "agent_version_id",
            "status",
            "completed_at",
        ),
        Index(
            "ix_evaluation_runs_dataset_time",
            "dataset_id",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    idempotency_key = Column(String(128), nullable=False)
    dataset_id = Column(
        String(36),
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_version_id = Column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_snapshot_hash = Column(String(64), nullable=False, index=True)
    trigger_type = Column(String(24), nullable=False, default="manual", index=True)
    status = Column(String(24), nullable=False, default="running", index=True)
    review_status = Column(
        String(24),
        nullable=False,
        default="not_required",
        index=True,
    )
    case_count = Column(Integer, nullable=False, default=0)
    passed_case_count = Column(Integer, nullable=False, default=0)
    failed_case_count = Column(Integer, nullable=False, default=0)
    skipped_case_count = Column(Integer, nullable=False, default=0)
    metrics_json = Column(JsonDocument, nullable=False, default=dict)
    threshold_results_json = Column(JsonDocument, nullable=False, default=dict)
    deterministic_gate_passed = Column(Boolean, nullable=False, default=False)
    error_code = Column(String(64), nullable=True)
    error_message = Column(String(500), nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    started_at = Column(DateTime, nullable=False, default=_now)
    completed_at = Column(DateTime, nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)

    dataset = relationship("EvaluationDataset", back_populates="runs")
    results = relationship(
        "EvaluationResult",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EvaluationResult(Base):
    """Metadata-only deterministic result for one golden case."""

    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "case_id",
            name="uq_evaluation_results_run_case",
        ),
        CheckConstraint(
            "status IN ('passed', 'failed', 'error', 'skipped')",
            name="chk_evaluation_results_status",
        ),
        CheckConstraint(
            "evaluator_type IN ('deterministic', 'human', 'llm_assisted')",
            name="chk_evaluation_results_evaluator",
        ),
        Index("ix_evaluation_results_run_status", "run_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    run_id = Column(
        String(36),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id = Column(
        String(36),
        ForeignKey("evaluation_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(16), nullable=False, index=True)
    evaluator_type = Column(
        String(24),
        nullable=False,
        default="deterministic",
    )
    observation_json = Column(JsonDocument, nullable=False, default=dict)
    metrics_json = Column(JsonDocument, nullable=False, default=dict)
    failure_codes_json = Column(JsonDocument, nullable=False, default=list)
    latency_ms = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(20, 12), nullable=False, default=0)
    output_sha256 = Column(String(64), nullable=True)
    judge_metadata_json = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=_now)

    run = relationship("EvaluationRun", back_populates="results")
    case = relationship("EvaluationCase", back_populates="results")
