"""Sign-ins, failed attempts, sign-outs and revocations get a table of their own.

Revision ID: 5dca7b7bddf9
Revises: b8d3f0c71a25
Create Date: 2026-09-22

Authentication events were three ``action`` values in ``security_audit_events``
with the reason for a failure inside ``detail_json``. That table is shaped for
"an administrator changed something": the detail is text, so filtering by
outcome meant parsing JSON in Python, and retention blanks the detail on a
shorter window than the row — the reason a login failed aged out before the
fact that it failed. Nothing told "signed out" apart from "every session was
revoked because the password changed", and the paths that end a session
without a sign-out wrote nothing at all.

Typed columns for the things an operator filters on, indexed the way the page
will query them (by user, by address, by type, by outcome — each with time),
and no redaction: every column on this table is the essential fact.

``source_event_id`` and ``backfilled`` exist for one script: the one that
carries the existing rows over. The unique index makes it idempotent.
Existing rows in ``security_audit_events`` are not touched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5dca7b7bddf9"
down_revision: str | None = "b8d3f0c71a25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "auth_events"


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _TABLE not in tables:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("outcome", sa.String(length=16), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=True),
            sa.Column("reason_code", sa.String(length=48), nullable=True),
            sa.Column("reason_detail", sa.Text(), nullable=True),
            sa.Column("auth_method", sa.String(length=16), nullable=True),
            sa.Column("ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("source_event_id", sa.Integer(), nullable=True),
            sa.Column("backfilled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    existing = {index["name"] for index in sa.inspect(bind).get_indexes(_TABLE)}
    wanted = (
        ("ix_auth_events_occurred_at", ["occurred_at"], False),
        ("ix_auth_events_user_time", ["user_id", "occurred_at"], False),
        ("ix_auth_events_ip_time", ["ip", "occurred_at"], False),
        ("ix_auth_events_type_time", ["event_type", "occurred_at"], False),
        ("ix_auth_events_outcome_time", ["outcome", "occurred_at"], False),
        ("ux_auth_events_source_event", ["source_event_id"], True),
    )
    for name, columns, unique in wanted:
        if name not in existing:
            op.create_index(name, _TABLE, columns, unique=unique)


def downgrade() -> None:
    op.drop_table(_TABLE)
