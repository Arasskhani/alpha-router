"""The shapes the Exchange EWS client takes and gives back, apart from the client itself.

The client (``exchange_ews_client``) talks to Exchange; everything else in
Alpharouter - the APIs, the chat's mail tools, the needs-action check - only
sees these plain values, so it can be tested without an Exchange server and
never handles an ``exchangelib`` object.

Datetimes here are timezone-aware (UTC unless said otherwise). Addresses are
lower-case SMTP addresses.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Literal, Protocol

AuthMode = Literal["ntlm", "basic"]
DraftKind = Literal["new", "reply", "reply_all", "forward"]
#: Where ``search`` looks; ``all`` is the Inbox with its subfolders and Sent Items.
FolderName = Literal["inbox", "sent", "drafts", "deleted", "all"]
ErrorKind = Literal[
    "auth",  # Exchange refused the login (401): stop, ask for the password again, never retry on its own
    "unreachable",  # DNS, connection refused, timeout
    "tls",  # the certificate could not be verified
    "access_denied",  # logged in, but that mailbox or item is not this login's to read
    "not_found",  # the item, folder or mailbox does not exist (any more)
    "throttled",  # Exchange asked to slow down
    "mailbox_mismatch",  # the login opens a mailbox other than the account's own
    "invalid",  # the request itself was wrong (bad address, bad date range)
    "conflict",  # the item changed since it was read (a draft edited in Outlook): read it again
    "server",  # anything else Exchange answered with
]


class EwsError(Exception):
    """A failure the person or the administrator can act on; ``message`` is safe to show (no secrets, no XML)."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message


@dataclass(frozen=True)
class EwsConfig:
    """How to reach Exchange as one login."""

    ews_url: str
    login: str
    password: str = field(repr=False)
    autodiscover_url: str = ""
    verify_tls: bool = True
    #: Extra CA certificates (PEM) to trust besides the system store; empty for none.
    ca_bundle_pem: str = ""
    timeout_s: int = 30
    #: NTLM in production; ``basic`` exists for the test server only.
    auth: AuthMode = "ntlm"


@dataclass(frozen=True)
class MailboxInfo:
    smtp: str
    display_name: str = ""


@dataclass(frozen=True)
class Address:
    email: str
    name: str = ""


@dataclass(frozen=True)
class MessageSummary:
    item_id: str
    change_key: str
    mailbox: str
    subject: str
    sender: Address | None
    to: tuple[Address, ...]
    cc: tuple[Address, ...]
    received: datetime.datetime | None
    is_read: bool
    has_attachments: bool
    #: ``Low``, ``Normal`` or ``High``.
    importance: str
    #: The first few hundred characters of the text, whitespace folded.
    preview: str
    folder: str = ""
    conversation_id: str = ""
    is_meeting_request: bool = False
    flagged: bool = False
    owa_url: str = ""
    #: Headers the needs-action rules read (lower-case names): auto-submitted, list-id, precedence, x-auto-response-suppress.
    hints: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Attachment:
    name: str
    size: int
    content_type: str = ""


@dataclass(frozen=True)
class MessageDetail:
    summary: MessageSummary
    #: The body as plain text, cut to the length asked for.
    body_text: str
    truncated: bool = False
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class DraftResult:
    item_id: str
    change_key: str
    mailbox: str
    subject: str
    to: tuple[Address, ...]
    cc: tuple[Address, ...]
    body_text: str
    owa_url: str = ""


@dataclass(frozen=True)
class Person:
    email: str
    name: str = ""
    department: str = ""
    title: str = ""
    office: str = ""


@dataclass(frozen=True)
class BusyInterval:
    start: datetime.datetime
    end: datetime.datetime
    #: ``Busy``, ``Tentative``, ``OOF`` or ``WorkingElsewhere``.
    status: str = "Busy"


@dataclass(frozen=True)
class WorkingHours:
    """Days are ISO weekdays (1 = Monday); minutes from midnight in ``timezone``."""

    timezone: str
    days: tuple[int, ...]
    start_minute: int
    end_minute: int


@dataclass(frozen=True)
class Availability:
    email: str
    busy: tuple[BusyInterval, ...]
    working_hours: WorkingHours | None = None
    #: Exchange could not tell (unknown address, no permission to see free/busy).
    error: str = ""


@dataclass(frozen=True)
class FreeSlot:
    start: datetime.datetime
    end: datetime.datetime


class MailClient(Protocol):
    """What the rest of Alpharouter calls on one login's Exchange connection.

    ``exchange_ews_client.EwsClient`` is the real one; tests use
    ``tests/fake_mail_client.FakeMailClient``. Every method is synchronous and
    blocking (callers go through ``exchange_mail.call_ews``) and raises only
    ``EwsError``. ``mailbox`` is a lower-case SMTP address the caller already
    checked against the connection's list; the client opens it as the login
    (Full Access), never by impersonation.
    """

    def whoami(self, hint_smtp: str = "") -> MailboxInfo:
        """The mailbox the login opens without naming one: its primary SMTP address and display name.

        ``hint_smtp`` (callers give the account's email) is checked first, as
        ``same_mailbox`` checks it: when it is the login's own mailbox, that is
        the answer - with its display name from the address book, or a blank
        one when the address book does not list it (people hidden from the
        address book) - and the address book is never needed to find the login.
        Otherwise, or without a hint, the address book is asked about the
        login and each candidate's root folder compared.

        Raises ``auth`` for a refused password, ``unreachable`` / ``tls`` when
        Exchange cannot be reached.
        """
        ...

    def same_mailbox(self, smtp: str) -> bool:
        """Whether ``smtp`` (any of its addresses) is the login's own mailbox: the root folder ids compared."""
        ...

    #: Why the last ``discover_full_access`` gave nothing although it was asked (Autodiscover failed): a short
    #: text for the administrator's Test connection; ``""`` when it answered (or listed none).
    autodiscover_problem: str

    def discover_full_access(self) -> list[MailboxInfo]:
        """The other mailboxes Autodiscover lists for the login (``AlternativeMailbox`` of type Delegate).

        An Autodiscover that fails - not set up, unreachable, an answer that
        cannot be read, even a 401: it is asked after EWS accepted the login,
        so a refusal is Autodiscover's own trouble (another host, TLS ended by
        a load balancer, Extended Protection), never a wrong password - gives
        ``[]`` and says why in ``autodiscover_problem``. Raises only what
        finding the login's own mailbox raises (``whoami``).
        """
        ...

    def check_mailbox(self, smtp: str) -> MailboxInfo:
        """Open the Inbox of ``smtp`` as the login; ``access_denied`` / ``not_found`` when it cannot."""
        ...

    def search(
        self,
        mailbox: str,
        *,
        query: str = "",
        folder: FolderName = "inbox",
        sender: str = "",
        since: datetime.datetime | None = None,
        until: datetime.datetime | None = None,
        unread_only: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[MessageSummary]:
        """Messages newest first. ``query`` is AQS (Exchange's search syntax, as in Outlook's search box)."""
        ...

    def list_received(self, mailbox: str, *, since: datetime.datetime, limit: int = 50) -> list[MessageSummary]:
        """Inbox messages received after ``since``, oldest first, with ``hints`` filled (for needs-action)."""
        ...

    def read(self, mailbox: str, item_id: str, *, body_chars: int = 8000) -> MessageDetail:
        """One message with its text body (cut to ``body_chars``) and its attachments' names."""
        ...

    def create_draft(
        self,
        mailbox: str,
        *,
        kind: DraftKind,
        body_text: str,
        to: tuple[Address, ...] = (),
        cc: tuple[Address, ...] = (),
        subject: str = "",
        source_item_id: str = "",
    ) -> DraftResult:
        """Save a draft in ``mailbox``'s Drafts folder; never sends.

        ``reply`` / ``reply_all`` / ``forward`` need ``source_item_id`` and are
        made by Exchange from that message (its quote, its recipients); ``to``
        and ``cc`` are added to (forward: are) the recipients, ``subject``
        replaces Exchange's only when given. ``new`` needs ``to``.
        """
        ...

    def get_draft(self, mailbox: str, item_id: str) -> DraftResult:
        """The draft as it is now in Exchange (it may have been edited in Outlook); ``not_found`` when gone."""
        ...

    def send_draft(self, mailbox: str, item_id: str, change_key: str) -> None:
        """Send the draft exactly as it was read (``change_key``), keeping a copy in Sent Items.

        ``conflict`` when it changed since; ``access_denied`` when the login may
        not send as that mailbox (no Send As / Send on Behalf).
        """
        ...

    def delete_draft(self, mailbox: str, item_id: str) -> None:
        """Move the draft to Deleted Items; nothing when it is already gone."""
        ...

    def find_people(self, query: str, *, limit: int = 10) -> list[Person]:
        """People from the address book (and the login's contacts) whose name or address matches."""
        ...

    def availability(
        self, emails: list[str], *, start: datetime.datetime, end: datetime.datetime
    ) -> list[Availability]:
        """Free/busy and working hours of each address, in the order given; one that cannot be read has ``error``."""
        ...

    def close(self) -> None:
        """Let go of the HTTP session."""
        ...
