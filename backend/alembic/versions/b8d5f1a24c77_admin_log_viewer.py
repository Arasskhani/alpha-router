"""Security audit events: keep the actor's name, and make the table queryable.

Revision ID: b8d5f1a24c77
Revises: a7c4e9b21d38
Create Date: 2026-09-16

Three changes, all to ``security_audit_events``, all in service of the same
thing: this table has been written to since the security settings shipped and
never once read back, because there was no endpoint and no page. Exposing it
turns two latent problems into immediate ones.

``actor_username`` / ``actor_email`` -- ``actor_user_id`` is a foreign key with
``ON DELETE SET NULL``, and ``permanently_delete_user`` really does DELETE the
row. So deleting an administrator silently anonymised every action they had
ever taken: the trail survived and "who" did not. An audit record has to keep
its meaning after the account it names is gone, so the identity is copied onto
the row when the event is written. Existing rows keep NULL; nothing can
reconstruct a name that was never stored.

``detail_redacted_at`` -- retention blanks ``detail_json`` rather than deleting
the row, so the compliance-relevant fact (who, what, when) outlives the bulky
part. Without a marker the UI cannot tell "no detail was recorded" from "the
detail has aged out", which are very different answers to an auditor.

Two composite indexes -- the only index was on ``created_at``. A viewer filters
by actor and by action, so every filtered page would have been a sequential
scan of the whole table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8d5f1a24c77"
down_revision: str | None = "a7c4e9b21d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "security_audit_events"

_COLUMNS = (
    ("actor_username", sa.String(length=255)),
    ("actor_email", sa.String(length=255)),
    ("detail_redacted_at", sa.DateTime()),
)

_INDEXES = (
    ("ix_security_audit_events_actor_created", ["actor_user_id", "created_at"]),
    ("ix_security_audit_events_action_created", ["action", "created_at"]),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    for name, columns in _INDEXES:
        if name not in indexes:
            op.create_index(name, _TABLE, columns)


def downgrade() -> None:
    for name, _columns in _INDEXES:
        op.drop_index(name, table_name=_TABLE)
    for name, _type in _COLUMNS:
        op.drop_column(_TABLE, name)
