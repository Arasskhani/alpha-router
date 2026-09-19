"""Admin logs: index the two columns the filter panel scans.

Revision ID: f4d5e6a7b8c9
Revises: e3c4d5f6a7b8
Create Date: 2026-09-19

``GET /admin-logs/filter-options`` runs SELECT DISTINCT over ``action``,
``resource_type`` and ``actor_username``. Only ``action`` had an index to read
(the composite with ``created_at``); the other two were sequential scans of the
whole audit table, on every open of the panel.

The endpoint also caches its answer now, but a cache miss should not be a table
scan.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4d5e6a7b8c9"
down_revision: str | None = "e3c4d5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "security_audit_events"
_INDEXES = (
    ("ix_security_audit_events_resource_type", "resource_type"),
    ("ix_security_audit_events_actor_username", "actor_username"),
)


def upgrade() -> None:
    present = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    for name, column in _INDEXES:
        if name not in present:
            op.create_index(name, _TABLE, [column])


def downgrade() -> None:
    present = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    for name, _column in _INDEXES:
        if name in present:
            op.drop_index(name, table_name=_TABLE)
