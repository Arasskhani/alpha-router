"""Support tickets: what a person asks the support team, the conversation that follows, and its images.

- A *ticket* keeps a snapshot of the reporter (name, username, email,
  department) taken when it was opened, so the record still says who asked
  after the account changes or is purged. ``number`` is what people quote
  (``#1042``); it is ``1000 + id``, set in the same transaction as the insert.
- A *message* is one entry in the thread: the person's text, a staff reply,
  an internal note (never shown to the person), the automatic first reply,
  or an event line (assigned, status changed, closed automatically ...) whose
  facts sit in ``event_json`` and whose wording is decided when it is read.
- An *attachment* is one image on a message. The bytes live in object storage
  under ``storage_key``; the row holds what the cleaned image turned out to be.

Lifecycle rules live in ``app.services.support_tickets``, not here.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("number", name="uq_support_tickets_number"),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="chk_support_tickets_priority"),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting', 'resolved', 'closed')", name="chk_support_tickets_status"
        ),
        # A NULL passes a CHECK, so both stay empty until the ticket is closed or resolved.
        CheckConstraint("closed_reason IN ('manual', 'auto', 'resolved')", name="chk_support_tickets_closed_reason"),
        CheckConstraint("resolved_by IN ('staff', 'user')", name="chk_support_tickets_resolved_by"),
        Index("ix_support_tickets_status_updated", "status", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    #: What people quote: ``1000 + id``.
    number = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # The reporter as they were when the ticket was opened.
    reporter_name = Column(String(255), nullable=False)
    reporter_username = Column(String(255), nullable=False)
    reporter_email = Column(String(255), nullable=True)
    reporter_department = Column(String(255), nullable=True, index=True)
    title = Column(String(150), nullable=False)
    category = Column(String(40), nullable=False)
    priority = Column(String(16), nullable=False, default="normal")
    status = Column(String(16), nullable=False, default="open")
    assignee_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True)
    assigned_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: JSON: ``{"app_version", "browser", "page"}`` as the person's browser sent it, when it did.
    context_json = Column(Text, nullable=True)
    #: Something changed that the person has not opened yet (a staff reply, a status change).
    user_unread = Column(Boolean, nullable=False, default=False)
    #: The next move is staff's: new, or the person wrote since staff last answered.
    needs_staff = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    #: Last activity on the ticket, not only an edit of this row.
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    waiting_since = Column(DateTime, nullable=True)
    first_staff_reply_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True, index=True)
    closed_reason = Column(String(16), nullable=True)
    resolved_by = Column(String(8), nullable=True)
    reopened_count = Column(Integer, nullable=False, default=0)


class SupportTicketMessage(Base):
    __tablename__ = "support_ticket_messages"
    __table_args__ = (
        CheckConstraint("kind IN ('user', 'staff', 'note', 'auto', 'event')", name="chk_support_ticket_messages_kind"),
    )

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: The author's name when they wrote it, so the thread reads the same after the account changes.
    author_name = Column(String(255), nullable=True)
    kind = Column(String(16), nullable=False)
    body = Column(Text, nullable=False, default="")
    #: Kind ``event`` only: the facts (``{"type": "assigned", "by": ..., "to": ..., "email": ...}``).
    event_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class SupportTicketAttachment(Base):
    __tablename__ = "support_ticket_attachments"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(
        Integer, ForeignKey("support_ticket_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key = Column(String(512), nullable=False)
    mime = Column(String(64), nullable=False)
    bytes = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    display_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
