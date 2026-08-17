"""add agent evaluation platform

Revision ID: f2a8c5d91b34
Revises: d9e4f6a7b812
Create Date: 2026-08-12 17:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f2a8c5d91b34"
down_revision: str | None = "d9e4f6a7b812"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonDocument = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=Text()),
    "postgresql",
)


def upgrade() -> None:
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("minimum_case_count", sa.Integer(), nullable=False),
        sa.Column("is_publish_gate", sa.Boolean(), nullable=False),
        sa.Column("thresholds_json", JsonDocument, nullable=False),
        sa.Column("metadata_json", JsonDocument, nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("activated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="chk_evaluation_datasets_status",
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "slug",
            "version_number",
            name="uq_evaluation_dataset_agent_slug_version",
        ),
    )
    op.create_index(
        "ix_evaluation_datasets_agent_id",
        "evaluation_datasets",
        ["agent_id"],
    )
    op.create_index(
        "ix_evaluation_datasets_slug",
        "evaluation_datasets",
        ["slug"],
    )
    op.create_index(
        "ix_evaluation_datasets_status",
        "evaluation_datasets",
        ["status"],
    )
    op.create_index(
        "ix_evaluation_datasets_is_publish_gate",
        "evaluation_datasets",
        ["is_publish_gate"],
    )
    op.create_index(
        "ix_evaluation_datasets_created_by_user_id",
        "evaluation_datasets",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_evaluation_datasets_activated_at",
        "evaluation_datasets",
        ["activated_at"],
    )
    op.create_index(
        "ix_evaluation_datasets_agent_status",
        "evaluation_datasets",
        ["agent_id", "status", "version_number"],
    )

    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("case_key", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("expected_json", JsonDocument, nullable=False),
        sa.Column("tags_json", JsonDocument, nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "category IN ("
            "'routing', 'retrieval', 'citation', 'abstention', "
            "'acl', 'injection', 'escalation', 'quality'"
            ")",
            name="chk_evaluation_cases_category",
        ),
        sa.CheckConstraint(
            "language IN ('fa', 'en', 'multilingual')",
            name="chk_evaluation_cases_language",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["evaluation_datasets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id",
            "case_key",
            name="uq_evaluation_cases_dataset_key",
        ),
    )
    op.create_index(
        "ix_evaluation_cases_dataset_id",
        "evaluation_cases",
        ["dataset_id"],
    )
    op.create_index(
        "ix_evaluation_cases_category",
        "evaluation_cases",
        ["category"],
    )
    op.create_index(
        "ix_evaluation_cases_language",
        "evaluation_cases",
        ["language"],
    )
    op.create_index(
        "ix_evaluation_cases_enabled",
        "evaluation_cases",
        ["enabled"],
    )
    op.create_index(
        "ix_evaluation_cases_dataset_category",
        "evaluation_cases",
        ["dataset_id", "category", "enabled"],
    )

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("agent_version_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("trigger_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("passed_case_count", sa.Integer(), nullable=False),
        sa.Column("failed_case_count", sa.Integer(), nullable=False),
        sa.Column("skipped_case_count", sa.Integer(), nullable=False),
        sa.Column("metrics_json", JsonDocument, nullable=False),
        sa.Column("threshold_results_json", JsonDocument, nullable=False),
        sa.Column("deterministic_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ("
            "'running', 'awaiting_review', 'passed', 'failed', 'error', 'cancelled'"
            ")",
            name="chk_evaluation_runs_status",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('manual', 'publish_gate', 'ci', 'seed', 'scheduled')",
            name="chk_evaluation_runs_trigger",
        ),
        sa.CheckConstraint(
            "review_status IN ('not_required', 'pending', 'approved', 'rejected')",
            name="chk_evaluation_runs_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["evaluation_datasets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_evaluation_runs_idempotency_key",
        ),
    )
    for index_name, columns in (
        ("ix_evaluation_runs_dataset_id", ["dataset_id"]),
        ("ix_evaluation_runs_agent_version_id", ["agent_version_id"]),
        ("ix_evaluation_runs_dataset_snapshot_hash", ["dataset_snapshot_hash"]),
        ("ix_evaluation_runs_trigger_type", ["trigger_type"]),
        ("ix_evaluation_runs_status", ["status"]),
        ("ix_evaluation_runs_review_status", ["review_status"]),
        ("ix_evaluation_runs_created_by_user_id", ["created_by_user_id"]),
        ("ix_evaluation_runs_created_at", ["created_at"]),
        ("ix_evaluation_runs_completed_at", ["completed_at"]),
        (
            "ix_evaluation_runs_version_status",
            ["agent_version_id", "status", "completed_at"],
        ),
        (
            "ix_evaluation_runs_dataset_time",
            ["dataset_id", "created_at"],
        ),
    ):
        op.create_index(index_name, "evaluation_runs", columns)

    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("evaluator_type", sa.String(length=24), nullable=False),
        sa.Column("observation_json", JsonDocument, nullable=False),
        sa.Column("metrics_json", JsonDocument, nullable=False),
        sa.Column("failure_codes_json", JsonDocument, nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(20, 12), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("judge_metadata_json", JsonDocument, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'error', 'skipped')",
            name="chk_evaluation_results_status",
        ),
        sa.CheckConstraint(
            "evaluator_type IN ('deterministic', 'human', 'llm_assisted')",
            name="chk_evaluation_results_evaluator",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["evaluation_cases.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "case_id",
            name="uq_evaluation_results_run_case",
        ),
    )
    op.create_index(
        "ix_evaluation_results_run_id",
        "evaluation_results",
        ["run_id"],
    )
    op.create_index(
        "ix_evaluation_results_case_id",
        "evaluation_results",
        ["case_id"],
    )
    op.create_index(
        "ix_evaluation_results_status",
        "evaluation_results",
        ["status"],
    )
    op.create_index(
        "ix_evaluation_results_run_status",
        "evaluation_results",
        ["run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_results_run_status",
        table_name="evaluation_results",
    )
    op.drop_index("ix_evaluation_results_status", table_name="evaluation_results")
    op.drop_index("ix_evaluation_results_case_id", table_name="evaluation_results")
    op.drop_index("ix_evaluation_results_run_id", table_name="evaluation_results")
    op.drop_table("evaluation_results")

    for index_name in (
        "ix_evaluation_runs_dataset_time",
        "ix_evaluation_runs_version_status",
        "ix_evaluation_runs_completed_at",
        "ix_evaluation_runs_created_at",
        "ix_evaluation_runs_created_by_user_id",
        "ix_evaluation_runs_review_status",
        "ix_evaluation_runs_status",
        "ix_evaluation_runs_trigger_type",
        "ix_evaluation_runs_dataset_snapshot_hash",
        "ix_evaluation_runs_agent_version_id",
        "ix_evaluation_runs_dataset_id",
    ):
        op.drop_index(index_name, table_name="evaluation_runs")
    op.drop_table("evaluation_runs")

    op.drop_index(
        "ix_evaluation_cases_dataset_category",
        table_name="evaluation_cases",
    )
    op.drop_index("ix_evaluation_cases_enabled", table_name="evaluation_cases")
    op.drop_index("ix_evaluation_cases_language", table_name="evaluation_cases")
    op.drop_index("ix_evaluation_cases_category", table_name="evaluation_cases")
    op.drop_index("ix_evaluation_cases_dataset_id", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")

    op.drop_index(
        "ix_evaluation_datasets_agent_status",
        table_name="evaluation_datasets",
    )
    op.drop_index(
        "ix_evaluation_datasets_activated_at",
        table_name="evaluation_datasets",
    )
    op.drop_index(
        "ix_evaluation_datasets_created_by_user_id",
        table_name="evaluation_datasets",
    )
    op.drop_index(
        "ix_evaluation_datasets_is_publish_gate",
        table_name="evaluation_datasets",
    )
    op.drop_index("ix_evaluation_datasets_status", table_name="evaluation_datasets")
    op.drop_index("ix_evaluation_datasets_slug", table_name="evaluation_datasets")
    op.drop_index(
        "ix_evaluation_datasets_agent_id",
        table_name="evaluation_datasets",
    )
    op.drop_table("evaluation_datasets")
