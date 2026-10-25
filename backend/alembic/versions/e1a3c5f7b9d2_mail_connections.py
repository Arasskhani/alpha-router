"""Exchange EWS: each person's mailbox connection, the mailboxes it reaches, and what the chat made of them.

Revision ID: e1a3c5f7b9d2
Revises: d9f1b3c5e7a9
Create Date: 2026-10-25

Every table starts empty, and the feature is off until an administrator turns
it on (``exchange_ews.settings`` in ``system_settings``, not written here).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1a3c5f7b9d2"
down_revision: str | None = "d9f1b3c5e7a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mail_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("login", sa.String(length=320), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("primary_smtp", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("notify_enabled", sa.Boolean(), nullable=False),
        sa.Column("poll_watermark", sa.DateTime(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("provider IN ('exchange_ews')", name="chk_mail_connections_provider"),
        sa.CheckConstraint("status IN ('connected', 'needs_password', 'error')", name="chk_mail_connections_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_mail_connections_user"),
    )
    op.create_index("ix_mail_connections_last_checked_at", "mail_connections", ["last_checked_at"], unique=False)

    op.create_table(
        "mail_connection_mailboxes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("smtp", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notify", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('own', 'full_access')", name="chk_mail_connection_mailboxes_kind"),
        sa.CheckConstraint(
            "source IN ('own', 'autodiscover', 'manual')", name="chk_mail_connection_mailboxes_source"
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["mail_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "smtp", name="uq_mail_connection_mailboxes_smtp"),
    )
    op.create_index(
        "ix_mail_connection_mailboxes_connection_id", "mail_connection_mailboxes", ["connection_id"], unique=False
    )

    op.create_table(
        "mail_item_refs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ref", sa.String(length=16), nullable=False),
        sa.Column("mailbox_smtp", sa.String(length=320), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("change_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "ref", name="uq_mail_item_refs_user_ref"),
    )
    op.create_index("ix_mail_item_refs_user_id", "mail_item_refs", ["user_id"], unique=False)
    op.create_index("ix_mail_item_refs_created_at", "mail_item_refs", ["created_at"], unique=False)

    op.create_table(
        "mail_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mailbox_smtp", sa.String(length=320), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("change_key", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("to_json", sa.Text(), nullable=False),
        sa.Column("cc_json", sa.Text(), nullable=False),
        sa.Column("body_preview", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(length=16), nullable=True),
        sa.Column("chat_session_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("kind IN ('new', 'reply', 'reply_all', 'forward')", name="chk_mail_drafts_kind"),
        sa.CheckConstraint(
            "status IN ('draft', 'sending', 'sent', 'discarded', 'failed')", name="chk_mail_drafts_status"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mail_drafts_user_id", "mail_drafts", ["user_id"], unique=False)
    op.create_index("ix_mail_drafts_created_at", "mail_drafts", ["created_at"], unique=False)

    op.create_table(
        "mail_action_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mailbox_smtp", sa.String(length=320), nullable=False),
        sa.Column("item_key", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("sender_email", sa.String(length=320), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("importance", sa.String(length=8), nullable=True),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("owa_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "action IN ('reply', 'schedule', 'review', 'approve', 'other')", name="chk_mail_action_items_action"
        ),
        sa.CheckConstraint("source IN ('rules', 'model')", name="chk_mail_action_items_source"),
        sa.CheckConstraint(
            "status IN ('new', 'notified', 'dismissed', 'done')", name="chk_mail_action_items_status"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "item_key", name="uq_mail_action_items_user_item"),
    )
    op.create_index("ix_mail_action_items_user_status", "mail_action_items", ["user_id", "status"], unique=False)
    op.create_index("ix_mail_action_items_created_at", "mail_action_items", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mail_action_items_created_at", table_name="mail_action_items")
    op.drop_index("ix_mail_action_items_user_status", table_name="mail_action_items")
    op.drop_table("mail_action_items")
    op.drop_index("ix_mail_drafts_created_at", table_name="mail_drafts")
    op.drop_index("ix_mail_drafts_user_id", table_name="mail_drafts")
    op.drop_table("mail_drafts")
    op.drop_index("ix_mail_item_refs_created_at", table_name="mail_item_refs")
    op.drop_index("ix_mail_item_refs_user_id", table_name="mail_item_refs")
    op.drop_table("mail_item_refs")
    op.drop_index("ix_mail_connection_mailboxes_connection_id", table_name="mail_connection_mailboxes")
    op.drop_table("mail_connection_mailboxes")
    op.drop_index("ix_mail_connections_last_checked_at", table_name="mail_connections")
    op.drop_table("mail_connections")
