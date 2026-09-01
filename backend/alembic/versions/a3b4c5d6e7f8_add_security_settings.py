"""add security settings tables

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-31 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "admin_ip_allowlist_entries"):
        op.create_table(
            "admin_ip_allowlist_entries",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("cidr", sa.String(64), nullable=False),
            sa.Column("label", sa.String(128), nullable=True),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    if not _table_exists(inspector, "tls_certificates"):
        op.create_table(
            "tls_certificates",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("label", sa.String(128), nullable=False),
            sa.Column("cert_pem", sa.Text, nullable=False),
            sa.Column("key_pem_encrypted", sa.Text, nullable=False),
            sa.Column("chain_pem", sa.Text, nullable=True),
            sa.Column("subject", sa.String(512), nullable=True),
            sa.Column("sans_json", sa.Text, nullable=True),
            sa.Column("issuer", sa.String(512), nullable=True),
            sa.Column("serial", sa.String(128), nullable=True),
            sa.Column("not_before", sa.DateTime, nullable=True),
            sa.Column("not_after", sa.DateTime, nullable=True),
            sa.Column("sha256_fingerprint", sa.String(64), nullable=False),
            sa.Column("key_algorithm", sa.String(32), nullable=True),
            sa.Column("key_bits", sa.Integer, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("uploaded_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    if not _table_exists(inspector, "security_audit_events"):
        op.create_table(
            "security_audit_events",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_ip", sa.String(64), nullable=True),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("resource_id", sa.String(64), nullable=True),
            sa.Column("detail_json", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_security_audit_events_created_at", "security_audit_events", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "security_audit_events"):
        op.drop_index("ix_security_audit_events_created_at", table_name="security_audit_events")
        op.drop_table("security_audit_events")
    if _table_exists(inspector, "tls_certificates"):
        op.drop_table("tls_certificates")
    if _table_exists(inspector, "admin_ip_allowlist_entries"):
        op.drop_table("admin_ip_allowlist_entries")
