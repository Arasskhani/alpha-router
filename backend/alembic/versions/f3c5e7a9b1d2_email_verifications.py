"""Emailed codes for self sign-up and for resetting a forgotten password.

Revision ID: f3c5e7a9b1d2
Revises: e2b4d6f8a0c1
Create Date: 2026-10-05

Accounts were made only by an administrator or by a directory. An
administrator can now let people create their own (Admin -> Authentication ->
Email sign-up): the person proves their address with a 6-digit code sent by
email, then chooses a username and a password. The same codes let a person
with a local account reset a forgotten password. One row per code: an HMAC of
it (never the code), its expiry, the wrong tries so far, and when it was used.
Nothing changes until an administrator turns the feature on.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3c5e7a9b1d2"
down_revision: str | None = "e2b4d6f8a0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "email_verifications"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.CheckConstraint("purpose IN ('signup', 'password_reset')", name="chk_email_verifications_purpose"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_email_verifications_email_purpose", _TABLE, ["email", "purpose", "created_at"])
    op.create_index("ix_email_verifications_user_id", _TABLE, ["user_id"])
    op.create_index("ix_email_verifications_created_at", _TABLE, ["created_at"])


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
