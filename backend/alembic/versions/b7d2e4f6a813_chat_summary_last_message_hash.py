"""Where a chat's summary ends: the hash of the last message it covers.

Revision ID: b7d2e4f6a813
Revises: c9e48be1dd4f
Create Date: 2026-09-30

A turn used a chat's summary in place of the oldest messages of its history
by count alone: the summary covered the chat's first N messages, so the
turn's first N went. A history that holds one message more or fewer than the
stored chat before that point (a message the browser has and the server
does not, one the server skips) lost a message it still needed or kept one
the summary already told. The summary now also records the last message it
covers, and a turn finds where it ends by that message. Summaries made
before this have none and are used by count, as before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d2e4f6a813"
down_revision: str | None = "c9e48be1dd4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chat_summaries"
_COLUMN = "last_message_hash"


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COLUMN not in _columns():
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=64), nullable=True))


def downgrade() -> None:
    if _COLUMN in _columns():
        op.drop_column(_TABLE, _COLUMN)
