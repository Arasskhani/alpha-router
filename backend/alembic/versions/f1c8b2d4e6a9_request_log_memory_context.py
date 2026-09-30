"""What a chat turn was given beside its messages, on its request log.

Revision ID: f1c8b2d4e6a9
Revises: e3a9c1d5b742
Create Date: 2026-09-30

A chat turn goes to the model with the person's memories, parts of their
earlier chats, the chat's summary in place of its oldest messages - and
nothing of that was on the request's log. An administrator looking into an
answer could not tell which earlier chats it read, which summary stood in
for what, or what was left out to fit the model's window. The log now keeps
it: ids and counts only, never words.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f1c8b2d4e6a9"
down_revision: str | None = "e3a9c1d5b742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "request_logs"
_COLUMN = "memory_context"


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COLUMN not in _columns():
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=True),
        )


def downgrade() -> None:
    if _COLUMN in _columns():
        op.drop_column(_TABLE, _COLUMN)
