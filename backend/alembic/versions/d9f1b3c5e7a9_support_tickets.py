"""Support tickets: the tickets people open, the thread of each one, and its images.

Revision ID: d9f1b3c5e7a9
Revises: c8e0a2b4d6f8
Create Date: 2026-10-22

Every table starts empty. The settings (``tickets.settings`` in
``system_settings``) are not written here: until an administrator saves them,
the defaults in ``app.services.support_tickets`` apply.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9f1b3c5e7a9"
down_revision: str | None = "c8e0a2b4d6f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reporter_name", sa.String(length=255), nullable=False),
        sa.Column("reporter_username", sa.String(length=255), nullable=False),
        sa.Column("reporter_email", sa.String(length=255), nullable=True),
        sa.Column("reporter_department", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.Column("assigned_by_id", sa.Integer(), nullable=True),
        sa.Column("context_json", sa.Text(), nullable=True),
        sa.Column("user_unread", sa.Boolean(), nullable=False),
        sa.Column("needs_staff", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("waiting_since", sa.DateTime(), nullable=True),
        sa.Column("first_staff_reply_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_reason", sa.String(length=16), nullable=True),
        sa.Column("resolved_by", sa.String(length=8), nullable=True),
        sa.Column("reopened_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="chk_support_tickets_priority"),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting', 'resolved', 'closed')", name="chk_support_tickets_status"
        ),
        sa.CheckConstraint(
            "closed_reason IN ('manual', 'auto', 'resolved')", name="chk_support_tickets_closed_reason"
        ),
        sa.CheckConstraint("resolved_by IN ('staff', 'user')", name="chk_support_tickets_resolved_by"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", name="uq_support_tickets_number"),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"], unique=False)
    op.create_index("ix_support_tickets_reporter_department", "support_tickets", ["reporter_department"], unique=False)
    op.create_index("ix_support_tickets_assignee_id", "support_tickets", ["assignee_id"], unique=False)
    op.create_index("ix_support_tickets_updated_at", "support_tickets", ["updated_at"], unique=False)
    op.create_index("ix_support_tickets_closed_at", "support_tickets", ["closed_at"], unique=False)
    op.create_index("ix_support_tickets_status_updated", "support_tickets", ["status", "updated_at"], unique=False)

    op.create_table(
        "support_ticket_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("event_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('user', 'staff', 'note', 'auto', 'event')", name="chk_support_ticket_messages_kind"
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["support_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_ticket_messages_ticket_id", "support_ticket_messages", ["ticket_id"], unique=False)

    op.create_table(
        "support_ticket_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["support_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["support_ticket_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_ticket_attachments_ticket_id", "support_ticket_attachments", ["ticket_id"], unique=False
    )
    op.create_index(
        "ix_support_ticket_attachments_message_id", "support_ticket_attachments", ["message_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_support_ticket_attachments_message_id", table_name="support_ticket_attachments")
    op.drop_index("ix_support_ticket_attachments_ticket_id", table_name="support_ticket_attachments")
    op.drop_table("support_ticket_attachments")
    op.drop_index("ix_support_ticket_messages_ticket_id", table_name="support_ticket_messages")
    op.drop_table("support_ticket_messages")
    op.drop_index("ix_support_tickets_status_updated", table_name="support_tickets")
    op.drop_index("ix_support_tickets_closed_at", table_name="support_tickets")
    op.drop_index("ix_support_tickets_updated_at", table_name="support_tickets")
    op.drop_index("ix_support_tickets_assignee_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_reporter_department", table_name="support_tickets")
    op.drop_index("ix_support_tickets_user_id", table_name="support_tickets")
    op.drop_table("support_tickets")
