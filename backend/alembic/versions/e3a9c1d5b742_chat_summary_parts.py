"""A chat's summary kept in parts, so a retention purge takes only what it purged.

Revision ID: e3a9c1d5b742
Revises: b7d2e4f6a813
Create Date: 2026-09-30

A chat's running summary is one text folded from the whole of its older
messages, so a retention purge - which takes a few of the oldest messages of
every long chat, every night - had to drop the whole summary, and the next
reply made it again from the start: the whole chat read and paid for again.
Each stretch of a chat is now also summarized on its own; a purge takes the
parts that reach into what it purged and keeps the rest.

Each summary made before this becomes one part that covers all of it, so
nothing is summarized again until a purge reaches it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3a9c1d5b742"
down_revision: str | None = "b7d2e4f6a813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chat_summary_parts"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_sequence", sa.Integer(), nullable=False),
        sa.Column("to_sequence", sa.Integer(), nullable=False),
        sa.Column("counted", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("last_message_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "from_sequence", name="ux_chat_summary_parts_session_from"),
    )
    # One chat has one summary at most: its session id is a unique id for the one part it becomes.
    op.execute(
        sa.text(
            "INSERT INTO chat_summary_parts "
            "(id, session_id, from_sequence, to_sequence, counted, content, last_message_hash, created_at) "
            "SELECT session_id, session_id, 1, up_to_sequence, covered_count, content, last_message_hash, updated_at "
            "FROM chat_summaries WHERE content <> '' AND up_to_sequence > 0"
        )
    )


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
