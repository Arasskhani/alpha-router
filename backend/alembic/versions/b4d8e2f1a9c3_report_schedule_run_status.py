"""Scheduled reports: the period they cover, when they run next, how the last run went.

Revision ID: b4d8e2f1a9c3
Revises: 3e27b36f9d8f
Create Date: 2026-09-24

Report schedules were stored but nothing sent them. Now that a job emails
them, each row keeps the period a dated report covers, when it runs next,
and the outcome of its last run (sent, partial or failed) with what went
wrong, so the Reports page can say why a report did not arrive.

Existing rows get none of these: they have never run. The job gives such a
row its next run time the first time it sees it, so an old schedule starts
at its next time rather than all at once on upgrade.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d8e2f1a9c3"
down_revision: str | None = "3e27b36f9d8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "report_schedules"
_NEW_COLUMNS = (
    ("period", sa.String(length=32)),
    ("next_run_at", sa.DateTime()),
    ("last_status", sa.String(length=16)),
    ("last_error", sa.Text()),
)


def _columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    columns = _columns()
    if columns is None:
        return
    for name, column_type in _NEW_COLUMNS:
        if name not in columns:
            op.add_column(_TABLE, sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    columns = _columns()
    if columns is None:
        return
    present = [name for name, _ in _NEW_COLUMNS if name in columns]
    if not present:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name in present:
            batch.drop_column(name)
