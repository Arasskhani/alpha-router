"""The browser extension: connected browsers and the extension's audit trail.

Revision ID: c7e1a2b3d4f5
Revises: b4d8e2f1a9c3
Create Date: 2026-09-25

``extension_sessions`` holds one row per browser a user connected the
extension from. Its access and refresh tokens are opaque random strings kept
only as SHA-256 hashes (unique indexes, since a request is authenticated by
looking the hash up). The previous refresh token is kept for a short grace, so
a retry after a lost response still works, and later use of it ends the session.

``extension_events`` is what Admin Logs shows about the extension: a page
shared with a model (site, size, model - never the text) and each step of the
browser agent. Like the security trail, its detail can be blanked by retention
before the row goes (``detail_redacted_at``).

Both tables are new; nothing existing is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e1a2b3d4f5"
down_revision: str | None = "b4d8e2f1a9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSIONS = "extension_sessions"
_EVENTS = "extension_events"


def _create_indexes(table: str, wanted: tuple[tuple[str, list[str], bool], ...]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    for name, columns, unique in wanted:
        if name not in existing:
            op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _SESSIONS not in tables:
        op.create_table(
            _SESSIONS,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("device_name", sa.String(length=64), nullable=False),
            sa.Column("access_token_hash", sa.String(length=64), nullable=False),
            sa.Column("access_expires_at", sa.DateTime(), nullable=False),
            sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
            sa.Column("prior_refresh_token_hash", sa.String(length=64), nullable=True),
            sa.Column("prior_refresh_valid_until", sa.DateTime(), nullable=True),
            sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
            sa.Column("absolute_expires_at", sa.DateTime(), nullable=False),
            sa.Column("token_version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("last_ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_reason", sa.String(length=32), nullable=True),
        )
    _create_indexes(
        _SESSIONS,
        (
            ("ux_extension_sessions_access_token", ["access_token_hash"], True),
            ("ux_extension_sessions_refresh_token", ["refresh_token_hash"], True),
            ("ix_extension_sessions_prior_refresh", ["prior_refresh_token_hash"], False),
            ("ix_extension_sessions_user", ["user_id"], False),
        ),
    )

    if _EVENTS not in tables:
        op.create_table(
            _EVENTS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column(
                "actor_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("actor_username", sa.String(length=255), nullable=True),
            sa.Column("actor_ip", sa.String(length=64), nullable=True),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("site", sa.String(length=255), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=True),
            sa.Column("outcome", sa.String(length=16), nullable=True),
            sa.Column("detail_json", sa.Text(), nullable=False),
            sa.Column("detail_redacted_at", sa.DateTime(), nullable=True),
        )
    _create_indexes(
        _EVENTS,
        (
            ("ix_extension_events_created_at", ["created_at"], False),
            ("ix_extension_events_actor_time", ["actor_user_id", "created_at"], False),
            ("ix_extension_events_session", ["session_id"], False),
        ),
    )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _EVENTS in tables:
        op.drop_table(_EVENTS)
    if _SESSIONS in tables:
        op.drop_table(_SESSIONS)
