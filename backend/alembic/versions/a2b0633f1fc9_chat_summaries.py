"""A rolling summary per chat, for turns too long for the model.

Revision ID: a2b0633f1fc9
Revises: 9240933e581a
Create Date: 2026-09-29

A chat longer than the model's window is fitted before it is sent: the
newest messages stay word for word and the oldest give way. This table holds
what can stand in for them - a summary of the chat's older messages, kept by
a background job - with the job's own state beside it. One row per chat; it
goes with the chat.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b0633f1fc9"
down_revision: str | None = "9240933e581a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chat_summaries"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("up_to_sequence", sa.Integer(), nullable=False),
        sa.Column("covered_count", sa.Integer(), nullable=False),
        sa.Column("first_message_hash", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("run_after", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_summaries_user_id", _TABLE, ["user_id"])
    op.create_index("ix_chat_summaries_project_id", _TABLE, ["project_id"])
    op.create_index("ix_chat_summaries_status_run", _TABLE, ["status", "run_after"])


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_index("ix_chat_summaries_status_run", table_name=_TABLE)
        op.drop_index("ix_chat_summaries_project_id", table_name=_TABLE)
        op.drop_index("ix_chat_summaries_user_id", table_name=_TABLE)
        op.drop_table(_TABLE)
