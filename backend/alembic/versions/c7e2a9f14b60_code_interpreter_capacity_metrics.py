"""Operations: record Code Interpreter capacity in the hourly snapshot.

Revision ID: c7e2a9f14b60
Revises: f4d5e6a7b8c9
Create Date: 2026-09-19

The Operations page showed Code Interpreter utilisation as a single number read
at page load, which answers "is it busy right now" and nothing else. An
operator setting the concurrency ceiling needs the opposite: what the peak was,
and how often a turn was refused. Both belong in the series the page already
records hourly, beside CPU and memory.

``code_interpreter_active`` is a gauge. ``code_interpreter_rejected_total`` is
the running total from the shared Redis counter; the chart differences
consecutive rows, so a missed snapshot costs resolution rather than events.
Both are nullable: NULL means Redis could not be read, which the chart must not
draw as a zero.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e2a9f14b60"
down_revision: str | None = "f4d5e6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "system_metric_snapshots"
_COLUMNS = ("code_interpreter_active", "code_interpreter_rejected_total")


def upgrade() -> None:
    present = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    for name in _COLUMNS:
        if name not in present:
            op.add_column(_TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    present = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    for name in _COLUMNS:
        if name in present:
            op.drop_column(_TABLE, name)
