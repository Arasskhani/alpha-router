"""A person's Exchange mailbox connection: the login, the mailboxes it reaches, and what the chat made of them.

- A *connection* is one per person: their own AD login (``DOMAIN\\sam`` or the
  UPN, never typed by them), the password encrypted with ``secret_crypto``,
  and the primary SMTP address of the mailbox that login opens. ``status``
  turns to ``needs_password`` on the first refusal from Exchange, and nothing
  uses the connection again until the person types the password anew - so a
  changed AD password can never lock the account through Alpharouter.
- A *mailbox* is one the connection may read: the person's own, and those the
  Exchange administrator gave them Full Access to (found through Autodiscover,
  or added by hand and checked with a read of their Inbox).
- An *item ref* is the short name the model uses for one email instead of the
  long EWS item id, kept for a week.
- A *draft* is one the model saved in a mailbox's Drafts folder. Only the
  person sends it, from the chat's Review & send, never the model.
- An *action item* is an email the needs-action check thinks the person should
  do something about; it is shown once as a toast and listed on Connections.

Every row belongs to one person and goes with their account.
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


class MailConnection(Base):
    __tablename__ = "mail_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_mail_connections_user"),
        CheckConstraint("provider IN ('exchange_ews')", name="chk_mail_connections_provider"),
        CheckConstraint("status IN ('connected', 'needs_password', 'error')", name="chk_mail_connections_status"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False, default="exchange_ews")
    #: What NTLM is given: ``CORP\\s.karimi`` or ``s.karimi@corp.example``. Derived from the account, never typed.
    login = Column(String(320), nullable=False)
    #: The password, encrypted (``secret_crypto.encrypt_secret``). Never returned by any API.
    secret_encrypted = Column(Text, nullable=False)
    #: The primary SMTP address of the mailbox the login opens.
    primary_smtp = Column(String(320), nullable=False)
    display_name = Column(String(255), nullable=True)
    status = Column(String(16), nullable=False, default="connected")
    #: The last failure, as the person should read it (never a password, never a stack trace).
    last_error = Column(String(500), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    #: The person wants toasts about emails that need their action.
    notify_enabled = Column(Boolean, nullable=False, default=True)
    #: The needs-action check has looked at everything received up to here.
    poll_watermark = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True, index=True)
    last_ok_at = Column(DateTime, nullable=True)
    connected_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class MailConnectionMailbox(Base):
    __tablename__ = "mail_connection_mailboxes"
    __table_args__ = (
        UniqueConstraint("connection_id", "smtp", name="uq_mail_connection_mailboxes_smtp"),
        CheckConstraint("kind IN ('own', 'full_access')", name="chk_mail_connection_mailboxes_kind"),
        CheckConstraint("source IN ('own', 'autodiscover', 'manual')", name="chk_mail_connection_mailboxes_source"),
    )

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("mail_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    #: Lower-case primary SMTP address.
    smtp = Column(String(320), nullable=False)
    display_name = Column(String(255), nullable=True)
    kind = Column(String(16), nullable=False)
    source = Column(String(16), nullable=False)
    #: The person lets the chat use it.
    enabled = Column(Boolean, nullable=False, default=True)
    #: The needs-action check looks at its Inbox.
    notify = Column(Boolean, nullable=False, default=False)
    verified_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class MailItemRef(Base):
    __tablename__ = "mail_item_refs"
    __table_args__ = (UniqueConstraint("user_id", "ref", name="uq_mail_item_refs_user_ref"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    #: What the model sees and gives back (``m7Q2xK9d``).
    ref = Column(String(16), nullable=False)
    mailbox_smtp = Column(String(320), nullable=False)
    item_id = Column(Text, nullable=False)
    change_key = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)


class MailDraft(Base):
    __tablename__ = "mail_drafts"
    __table_args__ = (
        CheckConstraint("kind IN ('new', 'reply', 'reply_all', 'forward')", name="chk_mail_drafts_kind"),
        CheckConstraint("status IN ('draft', 'sending', 'sent', 'discarded', 'failed')", name="chk_mail_drafts_status"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    mailbox_smtp = Column(String(320), nullable=False)
    item_id = Column(Text, nullable=False)
    change_key = Column(Text, nullable=True)
    kind = Column(String(16), nullable=False)
    subject = Column(String(500), nullable=False, default="")
    #: JSON lists of ``{"name", "email"}``.
    to_json = Column(Text, nullable=False, default="[]")
    cc_json = Column(Text, nullable=False, default="[]")
    #: The opening of the body as saved, for the chat's draft card.
    body_preview = Column(Text, nullable=False, default="")
    #: The email it answers or forwards (its ref), when it does.
    source_ref = Column(String(16), nullable=True)
    #: The chat it was written in (``chat_sessions.id``), when it was.
    chat_session_id = Column(String(64), nullable=True)
    #: ``sending`` while one request sends it (it claimed the row); a row left so for 10 minutes is a draft again.
    status = Column(String(16), nullable=False, default="draft")
    error = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)


class MailActionItem(Base):
    __tablename__ = "mail_action_items"
    __table_args__ = (
        UniqueConstraint("user_id", "item_key", name="uq_mail_action_items_user_item"),
        CheckConstraint(
            "action IN ('reply', 'schedule', 'review', 'approve', 'other')", name="chk_mail_action_items_action"
        ),
        CheckConstraint("source IN ('rules', 'model')", name="chk_mail_action_items_source"),
        CheckConstraint("status IN ('new', 'notified', 'dismissed', 'done')", name="chk_mail_action_items_status"),
        Index("ix_mail_action_items_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mailbox_smtp = Column(String(320), nullable=False)
    #: sha256 of ``mailbox|item_id``: one item per email, however often it is seen.
    item_key = Column(String(64), nullable=False)
    item_id = Column(Text, nullable=False)
    subject = Column(String(500), nullable=False, default="")
    sender_name = Column(String(255), nullable=True)
    sender_email = Column(String(320), nullable=True)
    received_at = Column(DateTime, nullable=True)
    #: Why it was picked, in a few words the person reads ("Asks you to approve the budget").
    reason = Column(String(200), nullable=False, default="")
    action = Column(String(16), nullable=False, default="other")
    importance = Column(String(8), nullable=True)
    source = Column(String(8), nullable=False, default="rules")
    status = Column(String(16), nullable=False, default="new")
    #: Opens the email in Outlook on the web, when Exchange gave the link.
    owa_url = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    notified_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
