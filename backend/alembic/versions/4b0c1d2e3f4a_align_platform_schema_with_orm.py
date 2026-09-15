"""Align the Agent-Platform tables with the ORM (indexes, JSONB detail).

Revision ID: 4b0c1d2e3f4a
Revises: a3b4c5d6e7f8
Create Date: 2026-09-14

Phase 4.3 introduced a CI gate that compares the ORM with a database built
purely from the migration chain. It found nine ORM indexes on
Alembic-owned tables that no revision ever created (the legacy
``_ensure_missing_indexes`` patch skipped Agent-Platform tables), and two
``detail`` columns created as ``JSON`` where the ORM says ``JSONB``.
Everything here is idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4b0c1d2e3f4a"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_project_audit_events_actor_user_id", "project_audit_events", ("actor_user_id",)),
    ("ix_project_audit_events_created_at", "project_audit_events", ("created_at",)),
    ("ix_project_audit_events_project_id", "project_audit_events", ("project_id",)),
    ("ix_project_chat_pins_project_id", "project_chat_pins", ("project_id",)),
    ("ix_project_chat_pins_session_id", "project_chat_pins", ("session_id",)),
    ("ix_project_media_assets_uploaded_by_user_id", "project_media_assets", ("uploaded_by_user_id",)),
    ("ix_project_memories_project_id", "project_memories", ("project_id",)),
    ("ix_projects_created_by_user_id", "projects", ("created_by_user_id",)),
    ("ix_projects_status", "projects", ("status",)),
)

_JSONB_COLUMNS: tuple[tuple[str, str], ...] = (
    ("project_memory_events", "detail"),
    ("user_memory_events", "detail"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name, table, columns in _INDEXES:
        if table not in tables:
            continue
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, list(columns))
    if bind.dialect.name == "postgresql":
        for table, column in _JSONB_COLUMNS:
            if table not in tables:
                continue
            current = {c["name"]: c for c in inspector.get_columns(table)}.get(column)
            if current is not None and str(current["type"]).upper() == "JSON":
                op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE JSONB USING {column}::jsonb")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name, table, _columns in _INDEXES:
        if table in tables and name in {idx["name"] for idx in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)
    if bind.dialect.name == "postgresql":
        for table, column in _JSONB_COLUMNS:
            if table in tables:
                op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE JSON USING {column}::json")
