"""Users: mark an account as permanently deleted instead of deleting the row.

Revision ID: c1a2b3d4e5f6
Revises: b8d5f1a24c77
Create Date: 2026-09-18

``permanently_delete_user`` ended in a plain ``DELETE FROM users``. On
PostgreSQL that statement cannot succeed for most of the accounts an operator
would want to remove.

``agent_audit_events``, ``agent_tool_audit_events``, ``knowledge_audit_events``
and ``governance_audit_events`` all reference ``users.id`` with
``ON DELETE SET NULL``, and revision ``d9e4f6a7b812`` put a
``BEFORE UPDATE OR DELETE`` trigger on each of them. PostgreSQL implements
``ON DELETE SET NULL`` as an internal UPDATE of the referencing row, so the
trigger fires and raises ``audit table ... is append-only``. The delete aborts.
Every administrator who has ever published an agent or touched a knowledge base
is therefore undeletable, and - because soft delete has no restore - stuck in
Deleted Users with no way out.

Letting the UPDATE through would be worse than the 500. The governance hash
chain is computed over ``actor_user_id`` (``_canonical_event_payload``), so
nulling it would make every event by that actor fail verification: the
tamper-evidence would report tampering that never happened.

So the row stays and everything identifying is cleared, which is the same
shape ``knowledge_hard_delete_service`` already uses for an audited knowledge
base. ``purged_at`` is what tells a purged row from a soft-deleted one, so the
Users and Deleted Users pages can both leave it out.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "b8d5f1a24c77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_COLUMN = "purged_at"
_INDEX = "ix_users_purged_at"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    # Guarded the same way the upgrade is: a downgrade that assumes the upgrade
    # ran to completion fails halfway and leaves the schema in a third state.
    inspector = sa.inspect(op.get_bind())
    if _INDEX in {index["name"] for index in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {column["name"] for column in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
