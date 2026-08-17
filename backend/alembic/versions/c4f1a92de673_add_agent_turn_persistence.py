"""add agent turn persistence

Revision ID: c4f1a92de673
Revises: 8b7c2d41ef90
Create Date: 2026-08-12 15:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4f1a92de673"
down_revision: str | None = "8b7c2d41ef90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonDocument = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=Text()),
    "postgresql",
)


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("chat_session_id", sa.String(length=36), nullable=True),
        sa.Column("external_session_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("alpha_router_api_key_id", sa.Integer(), nullable=True),
        sa.Column("request_log_id", sa.Integer(), nullable=True),
        sa.Column("usage_operation_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("agent_version_id", sa.String(length=36), nullable=True),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("model_catalog_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("client_app", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("routing_outcome", sa.String(length=32), nullable=False),
        sa.Column("routing_reason", sa.String(length=255), nullable=True),
        sa.Column("routing_confidence", sa.Float(), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=True),
        sa.Column("model_external_id", sa.String(length=512), nullable=True),
        sa.Column("query_sha256", sa.String(length=64), nullable=False),
        sa.Column("retrieval_outcome", sa.String(length=32), nullable=False),
        sa.Column("retrieval_result_count", sa.Integer(), nullable=False),
        sa.Column("knowledge_release_ids", JsonDocument, nullable=False),
        sa.Column("index_version_ids", JsonDocument, nullable=False),
        sa.Column("retrieval_error_codes", JsonDocument, nullable=False),
        sa.Column("tool_execution_ids", JsonDocument, nullable=False),
        sa.Column("handoff_event_ids", JsonDocument, nullable=False),
        sa.Column("guardrail_events", JsonDocument, nullable=False),
        sa.Column("egress_manifest", JsonDocument, nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("total_cost_usd", sa.Numeric(20, 12), nullable=False),
        sa.Column("planning_latency_ms", sa.Integer(), nullable=False),
        sa.Column("retrieval_latency_ms", sa.Integer(), nullable=True),
        sa.Column("provider_latency_ms", sa.Integer(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("output_displayed", sa.Boolean(), nullable=False),
        sa.Column("completion_reason_code", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('planned', 'running', 'route_required', 'abstained', "
            "'succeeded', 'blocked', 'failed', 'cancelled')",
            name="chk_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["alpha_router_api_key_id"],
            ["alpha_router_api_keys.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["chat_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_catalog_id"],
            ["ai_models.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_log_id"],
            ["request_logs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["usage_operation_id"],
            ["usage_operations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "agent_id",
        "agent_version_id",
        "alpha_router_api_key_id",
        "chat_session_id",
        "connection_id",
        "created_at",
        "external_session_id",
        "model_catalog_id",
        "request_log_id",
        "source",
        "status",
        "usage_operation_id",
        "user_id",
    ):
        op.create_index(
            op.f(f"ix_agent_runs_{column}"),
            "agent_runs",
            [column],
            unique=False,
        )
    op.create_index(
        op.f("ix_agent_runs_correlation_id"),
        "agent_runs",
        ["correlation_id"],
        unique=True,
    )
    op.create_index(
        "ix_agent_runs_session_time",
        "agent_runs",
        ["chat_session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_agent_time",
        "agent_runs",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_user_time",
        "agent_runs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_status_time",
        "agent_runs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "agent_retrieval_traces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("query_sha256", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("answerable", sa.Boolean(), nullable=True),
        sa.Column("abstention_reason", sa.String(length=64), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("post_authorized_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("estimated_context_tokens", sa.Integer(), nullable=False),
        sa.Column("context_truncated", sa.Boolean(), nullable=False),
        sa.Column("knowledge_release_ids", JsonDocument, nullable=False),
        sa.Column("index_version_ids", JsonDocument, nullable=False),
        sa.Column("component_errors", JsonDocument, nullable=False),
        sa.Column("results", JsonDocument, nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_run_id",
            name="uq_agent_retrieval_trace_run",
        ),
    )
    for column in ("agent_run_id", "created_at", "outcome", "query_sha256"):
        op.create_index(
            op.f(f"ix_agent_retrieval_traces_{column}"),
            "agent_retrieval_traces",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_agent_retrieval_trace_outcome_time",
        "agent_retrieval_traces",
        ["outcome", "created_at"],
        unique=False,
    )

    op.create_table(
        "agent_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("citation_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("document_version_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=True),
        sa.Column("release_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=512), nullable=True),
        sa.Column("authority", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.String(length=64), nullable=True),
        sa.Column("effective_to", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge_chunks.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["knowledge_releases.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_run_id",
            "citation_id",
            name="uq_agent_citation_run_marker",
        ),
    )
    for column in (
        "agent_run_id",
        "chunk_id",
        "created_at",
        "document_id",
        "release_id",
    ):
        op.create_index(
            op.f(f"ix_agent_citations_{column}"),
            "agent_citations",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_agent_citations_document_version",
        "agent_citations",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_citations_knowledge_base",
        "agent_citations",
        ["knowledge_base_id"],
        unique=False,
    )

    op.create_table(
        "agent_tool_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("tool_id", sa.String(length=36), nullable=True),
        sa.Column("tool_version_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("effect_type", sa.String(length=24), nullable=False),
        sa.Column("arguments_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key_sha256", sa.String(length=64), nullable=True),
        sa.Column("approval_recorded", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(20, 12), nullable=False),
        sa.Column("redacted_paths", JsonDocument, nullable=False),
        sa.Column("guardrail_reason_codes", JsonDocument, nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', "
            "'blocked', 'cancelled', 'cached')",
            name="chk_agent_tool_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"],
            ["agent_tools.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tool_version_id"],
            ["agent_tool_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "agent_run_id",
        "created_at",
        "status",
        "tool_id",
        "tool_version_id",
        "user_id",
    ):
        op.create_index(
            op.f(f"ix_agent_tool_runs_{column}"),
            "agent_tool_runs",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_agent_tool_runs_run_time",
        "agent_tool_runs",
        ["agent_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_tool_runs_tool_time",
        "agent_tool_runs",
        ["tool_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "agent_escalation_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
        sa.Column("chat_session_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("adapter_key", sa.String(length=128), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("metadata_payload", JsonDocument, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'assigned', 'resolved', 'closed', 'failed')",
            name="chk_agent_escalation_cases_status",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["chat_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "agent_id",
        "agent_run_id",
        "chat_session_id",
        "created_at",
        "status",
        "user_id",
    ):
        op.create_index(
            op.f(f"ix_agent_escalation_cases_{column}"),
            "agent_escalation_cases",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_agent_escalation_status_time",
        "agent_escalation_cases",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_escalation_user_time",
        "agent_escalation_cases",
        ["user_id", "created_at"],
        unique=False,
    )

    inspector = sa.inspect(op.get_bind())
    chat_session_columns = {
        column["name"] for column in inspector.get_columns("chat_sessions")
    }
    if "current_agent_id" not in chat_session_columns:
        with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("current_agent_id", sa.String(length=36), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "current_agent_version_id",
                    sa.String(length=36),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column("agent_selected_at", sa.DateTime(), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_chat_sessions_current_agent",
                "agents",
                ["current_agent_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_chat_sessions_current_agent_version",
                "agent_versions",
                ["current_agent_version_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                batch_op.f("ix_chat_sessions_current_agent_id"),
                ["current_agent_id"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_chat_sessions_current_agent_version_id"),
                ["current_agent_version_id"],
                unique=False,
            )

    chat_message_columns = {
        column["name"] for column in inspector.get_columns("chat_messages")
    }
    if "agent_run_id" not in chat_message_columns:
        with op.batch_alter_table("chat_messages", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("agent_run_id", sa.String(length=36), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_chat_messages_agent_run",
                "agent_runs",
                ["agent_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                batch_op.f("ix_chat_messages_agent_run_id"),
                ["agent_run_id"],
                unique=False,
            )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.drop_column("agent_run_id")

    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_column("agent_selected_at")
        batch_op.drop_column("current_agent_version_id")
        batch_op.drop_column("current_agent_id")

    op.drop_table("agent_escalation_cases")
    op.drop_table("agent_tool_runs")
    op.drop_table("agent_citations")
    op.drop_table("agent_retrieval_traces")
    op.drop_table("agent_runs")
