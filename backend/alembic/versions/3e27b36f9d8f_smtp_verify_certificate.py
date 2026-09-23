"""SMTP may accept a self-signed certificate, when an administrator says so.

Revision ID: 3e27b36f9d8f
Revises: 4ce0678f5e1c
Create Date: 2026-09-23

A mail server inside an organisation often has a certificate no public CA
signed. With verification always on, such a server could only be used with
``security = none``, which throws the encryption away along with the
identity check. ``verify_certificate = false`` keeps the encryption and gives
up only the check. Every existing row keeps verifying.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3e27b36f9d8f"
down_revision: str | None = "4ce0678f5e1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "smtp_settings"
_COLUMN = "verify_certificate"


def _columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    columns = _columns()
    if columns is None or _COLUMN in columns:
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    columns = _columns()
    if columns is None or _COLUMN not in columns:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
