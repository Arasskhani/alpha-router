"""One login's mailboxes on Exchange Server 2019 / SE, over EWS: the real ``MailClient``.

Everything else in Alpharouter sees only the plain values of
``exchange_ews_types``; this module is the one place that talks to Exchange
(through ``exchangelib``, synchronous, run in a thread by
``exchange_mail.run_ews``). The rules it keeps:

- **One attempt, never a retry.** The version is pinned to Exchange 2019 /
  SE (build 15.2), so nothing is guessed; autodiscover inside exchangelib is
  off; the retry policy fails fast, and a 401 is always "the password was
  refused" (``auth``) - even when the server also closes the connection,
  which exchangelib would otherwise read as "busy, try again". Alpharouter
  never tries a refused password twice, so it cannot lock an AD account.
- **Only ``EwsError`` leaves.** Every failure is mapped to one of its kinds
  with a short message a person can act on - never XML, a stack trace or the
  password (``_map_error``). exchangelib's own log lines that carry whole
  SOAP requests (email bodies, recipients, the Authorization header) are
  dropped, or cut down to the exception's name (``_QuietSoapLog``).
- **Nothing shared between logins.** exchangelib keeps a process-wide cache
  of protocols keyed by endpoint and credentials, and a class-wide HTTP
  adapter. Each client here has its own protocol (``_Protocol``, never
  cached) with its own adapter (``_TlsAdapter``) that verifies the server
  with this configuration's trust only: the system store (``certifi``) plus
  the administrator's extra CA certificates (written once per distinct PEM
  to a 0600 temp file), or no verification when ``verify_tls`` is off. The
  environment (``REQUESTS_CA_BUNDLE`` and friends) is ignored on purpose, so
  what the admin page says is what happens. Timeouts are ``timeout_s``.
- **NTLM**, with channel binding (``requests_ntlm``), as Extended
  Protection expects; Basic only when ``auth == "basic"`` (the test server).

How the less obvious parts work:

- ``whoami``: EWS opens the login's own mailbox when a request names none.
  ``GetFolder`` of ``msgfolderroot`` without a mailbox (and without the
  ``X-AnchorMailbox`` header) gives that mailbox's root folder id. EWS has no
  call that says whose mailbox that is, so ``ResolveNames`` is asked about
  the login (the user name of ``DOMAIN\\user``; the whole UPN and its user
  part otherwise), and each candidate's own ``msgfolderroot`` id is compared
  with the first one: the candidate with the same id is the login's mailbox
  (its primary SMTP address and display name). Exact matches (address,
  alias) are tried first, at most ``_IDENTITY_TRIES`` of them.
- ``same_mailbox``: the same comparison of root folder ids, with and without
  naming the mailbox.
- ``search``: ``FindItem`` (ids and received time only) then one ``GetItem``
  for the page, never bodies. ``preview`` is Exchange's ``item:Preview``
  (Exchange 2013+) and ``flagged`` is ``PidTagFlagStatus``; exchangelib has
  neither, so both are registered on its ``Message`` and ``MeetingRequest``
  classes at import (a schema addition that is the same for every login).
  A ``query`` is AQS (``QueryString``), and ``sender`` is added to it as
  ``from:"..."``. EWS cannot combine a query string with a restriction, so
  with a query the date range and ``unread_only`` are applied here, over at
  most ``_SCAN_MAX`` newest matches of each folder; without one they are a
  server-side restriction. ``folder="all"`` is the Inbox, its subfolders (at
  most ``_SUBFOLDERS_MAX``) and Sent Items in one ``FindItem``; EWS answers
  per folder, so the newest of each are merged here.
- ``availability``: ``GetUserAvailability`` in UTC (the UTC time zone element
  is built here exactly as exchangelib builds it from the server's UTC
  definition, which saves the ``GetServerTimeZones`` round trip). Working
  hours come with a time zone given as offsets and transition rules; it is
  matched to an IANA name with ``zoneinfo`` (the zone whose offsets agree
  every day of the year). When none matches, the hours are shifted into UTC
  by the standard offset, or left out when that window would cross midnight.
- ``discover_full_access``: the Autodiscover POX request Outlook sends, with
  the same TLS and auth, parsed with ``defusedxml`` (no DTDs, no entities).
  Anything that fails gives ``[]``; only a 401 whose server offered our auth
  scheme (the password itself was refused) raises ``auth``. Redirects are
  not followed.
- ``delete_draft`` uses ``DeleteItem`` with ``MoveToDeletedItems`` - what
  exchangelib's ``move_to_trash()`` sends - without its extra folder lookups.
"""

from __future__ import annotations

import atexit
import contextlib
import datetime
import functools
import hashlib
import logging
import os
import re
import ssl
import tempfile
import threading
import zoneinfo
from collections.abc import Iterable, Iterator, Sequence
from typing import Any
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError
from xml.sax.saxutils import escape as xml_escape

import certifi
import defusedxml
import defusedxml.ElementTree

# exchangelib is built on requests (sessions, adapters, auth); it has no stubs here.
import requests  # type: ignore[import-untyped]
import requests.adapters  # type: ignore[import-untyped]
import requests.auth  # type: ignore[import-untyped]
from exchangelib import (
    BASIC,
    DELEGATE,
    NTLM,
    UTC,
    Account,
    Body,
    Configuration,
    Credentials,
    EWSDateTime,
    ExtendedProperty,
    FailFast,
    Mailbox,
    Message,
    Q,
)
from exchangelib.errors import (
    CASError,
    ErrorAccessDenied,
    ErrorAccountDisabled,
    ErrorChangeKeyRequiredForWriteOperations,
    ErrorConnectionFailed,
    ErrorCreateItemAccessDenied,
    ErrorExceededConnectionCount,
    ErrorFolderNotFound,
    ErrorImpersonateUserDenied,
    ErrorInsufficientResources,
    ErrorInternalServerTransientError,
    ErrorInvalidChangeKey,
    ErrorInvalidIdMalformed,
    ErrorInvalidRecipients,
    ErrorInvalidRestriction,
    ErrorInvalidSmtpAddress,
    ErrorIrresolvableConflict,
    ErrorItemNotFound,
    ErrorMailboxMoveInProgress,
    ErrorMailboxStoreUnavailable,
    ErrorMailRecipientNotFound,
    ErrorMissingRecipients,
    ErrorNameResolutionNoResults,
    ErrorNoFreeBusyAccess,
    ErrorNonExistentMailbox,
    ErrorNotDelegate,
    ErrorPasswordChangeRequired,
    ErrorPasswordExpired,
    ErrorQuotaExceeded,
    ErrorSendAsDenied,
    ErrorServerBusy,
    ErrorStaleObject,
    ErrorTimeoutExpired,
    ErrorTooManyObjectsOpened,
    RateLimitError,
    RedirectError,
    ResponseMessageError,
    TransportError,
    UnauthorizedError,
)
from exchangelib.fields import FieldOrder, FieldPath, TextField
from exchangelib.folders import DeletedItems, Drafts, FolderCollection, Inbox, Root, SentItems
from exchangelib.items import (
    ALL_OCCURRENCES,
    ID_ONLY,
    MOVE_TO_DELETED_ITEMS,
    SEND_TO_NONE,
    ForwardItem,
    MeetingRequest,
    ReplyAllToItem,
    ReplyToItem,
)
from exchangelib.properties import (
    DaylightTime,
    DistinguishedFolderId,
    FreeBusyViewOptions,
    MailboxData,
    ReferenceItemId,
    StandardTime,
    TimeWindow,
    TimeZone,
)
from exchangelib.protocol import CachingProtocol, Protocol
from exchangelib.restriction import Restriction
from exchangelib.services import DeleteItem, FindItem, GetFolder, GetUserAvailability, SendItem
from exchangelib.version import EXCHANGE_2013, EXCHANGE_2019, Version
from requests_ntlm import HttpNtlmAuth

from app.services.exchange_ews_types import (
    Address,
    Attachment,
    Availability,
    BusyInterval,
    DraftKind,
    DraftResult,
    EwsConfig,
    ErrorKind,
    EwsError,
    FolderName,
    MailboxInfo,
    MessageDetail,
    MessageSummary,
    Person,
    WorkingHours,
)

logger = logging.getLogger(__name__)

#: Search results per call, at most (the chat asks for fewer).
SEARCH_MAX = 100
#: Messages ``list_received`` gives per call, at most.
LIST_MAX = 200
#: Subfolders of the Inbox that ``folder="all"`` reads, at most.
_SUBFOLDERS_MAX = 100
#: Newest matches per folder read when a query's date range or unread filter is applied here.
_SCAN_MAX = 500
#: Exchange's own cap on one FindItem page.
_PAGE_MAX = 1000
#: Candidates from the address book checked against the login's own root folder, at most.
_IDENTITY_TRIES = 5
PREVIEW_MAX = 255
#: Headers ``list_received`` returns as ``hints`` (lower-case), for the needs-action rules.
HINT_HEADERS = ("auto-submitted", "list-id", "list-unsubscribe", "precedence", "x-auto-response-suppress")
_HINT_VALUE_MAX = 300
#: Exchange answers free/busy for at most 42 days at a time.
_AVAILABILITY_MAX_DAYS = 42
_BUSY_TYPES = {"Busy", "Tentative", "OOF", "WorkingElsewhere"}
_AUTODISCOVER_MAX_BYTES = 1024 * 1024
_AUTODISCOVER_MAX_MAILBOXES = 200
_SUBJECT_MAX = 255

_POX_REQUEST = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Autodiscover xmlns="http://schemas.microsoft.com/exchange/autodiscover/outlook/requestschema/2006">'
    "<Request><EMailAddress>{email}</EMailAddress>"
    "<AcceptableResponseSchema>http://schemas.microsoft.com/exchange/autodiscover/outlook/responseschema/2006a"
    "</AcceptableResponseSchema></Request></Autodiscover>"
)

_SMTP = re.compile(r"^[^@\s<>\"]{1,64}@[^@\s<>\"]{1,255}$")
_HTTP_CODE = re.compile(r"Code: (\d{3})")

PREVIEW_FIELD = "preview"
FLAG_FIELD = "alpharouter_flag_status"
_FLAGGED = 2  # PidTagFlagStatus: 0 none, 1 completed, 2 flagged

_SUMMARY_FIELDS = (
    "subject",
    "author",
    "sender",
    "to_recipients",
    "cc_recipients",
    "datetime_received",
    "is_read",
    "has_attachments",
    "importance",
    "conversation_id",
    "item_class",
    "web_client_read_form_query_string",
    PREVIEW_FIELD,
    FLAG_FIELD,
)
_DRAFT_FIELDS = (
    "subject",
    "to_recipients",
    "cc_recipients",
    "text_body",
    "is_draft",
    "web_client_edit_form_query_string",
    "web_client_read_form_query_string",
)

_SOURCE_FIELDS = ("subject", "author", "sender", "to_recipients", "cc_recipients")

_FOLDER_CLASSES: dict[str, Any] = {"inbox": Inbox, "sent": SentItems, "drafts": Drafts, "deleted": DeletedItems}


# --- the schema additions and the log filter (the same for every login) -----------------------------------------


class _FlagStatus(ExtendedProperty):
    """``PidTagFlagStatus``: 2 when the message is flagged for follow-up."""

    property_tag = 0x1090
    property_type = "Integer"


def _register_fields() -> None:
    """Teach exchangelib ``item:Preview`` and the flag status, which it does not know (idempotent)."""
    for cls in (Message, MeetingRequest):
        names = {field.name for field in cls.FIELDS}
        if PREVIEW_FIELD not in names:
            cls.add_field(
                TextField(PREVIEW_FIELD, field_uri="item:Preview", is_read_only=True, supported_from=EXCHANGE_2013),
                insert_after="has_attachments",
            )
        if FLAG_FIELD not in names:
            cls.register(FLAG_FIELD, _FlagStatus)


class _QuietSoapLog(logging.Filter):
    """Keep exchangelib's request log lines from carrying mail or credentials into the application log.

    ``exchangelib.util`` logs every request and response in full at DEBUG
    (bodies, recipients, the Authorization header), and the whole request
    again at ERROR when a POST fails in an unexpected way. DEBUG lines are
    dropped; an ERROR line keeps only the exception's class name.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno <= logging.DEBUG:
            return False
        if record.levelno >= logging.ERROR and isinstance(record.args, tuple) and record.args:
            record.msg = "EWS request failed: %s"
            record.args = (str(record.args[0])[:100],)
        return True


_register_fields()
for _name in ("exchangelib.util", "exchangelib.util.xml"):
    logging.getLogger(_name).addFilter(_QuietSoapLog())


# --- TLS ------------------------------------------------------------------------------------------------------

_bundle_lock = threading.Lock()
_bundles: dict[str, str] = {}


def _remove_bundles() -> None:
    for path in _bundles.values():
        with contextlib.suppress(OSError):
            os.unlink(path)


atexit.register(_remove_bundles)


def _combined_bundle(pem: str) -> str:
    """A file with the system CA store and ``pem``, written once per distinct PEM (mode 0600)."""
    key = hashlib.sha256(pem.encode("utf-8")).hexdigest()
    with _bundle_lock:
        path = _bundles.get(key)
        if path and os.path.exists(path):
            return path
        with open(certifi.where(), "rb") as source:
            system = source.read()
        fd, path = tempfile.mkstemp(prefix="alpharouter-ews-ca-", suffix=".pem")
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, system.rstrip(b"\n") + b"\n" + pem.strip().encode("utf-8") + b"\n")
        finally:
            os.close(fd)
        _bundles[key] = path
        return path


def _verify_setting(config: EwsConfig) -> bool | str:
    """What ``requests`` is told to verify with: ``False``, or a CA bundle file."""
    if not config.verify_tls:
        return False
    pem = (config.ca_bundle_pem or "").strip()
    return _combined_bundle(pem) if pem else certifi.where()


class _TlsAdapter(requests.adapters.HTTPAdapter):
    """Verifies the server with this client's trust only - whatever the session or the environment says."""

    def __init__(self, verify: bool | str, **kwargs: Any) -> None:
        self._verify = verify
        super().__init__(**kwargs)

    def send(
        self,
        request: Any,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> Any:
        return super().send(request, stream=stream, timeout=timeout, verify=self._verify, cert=cert, proxies=proxies)


def _adapter(verify: bool | str) -> _TlsAdapter:
    # One connection per session and no urllib3 retries, as exchangelib's own adapter.
    return _TlsAdapter(verify, pool_block=True, pool_connections=1, pool_maxsize=1, max_retries=0)


# --- exchangelib, per client ------------------------------------------------------------------------------------


class _HttpStatusError(TransportError):
    """An HTTP status EWS gives no SOAP answer for (403, 404), kept apart so the message can say what it means."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class _NoRetry(FailFast):
    """FailFast, and a 401 is always a refused login.

    exchangelib checks ``Connection: close`` before the status code and would
    turn a 401 that closes the connection into "server busy"; a refused
    password must never look like something worth trying again.
    """

    def raise_response_errors(self, response: Any) -> None:
        if response.status_code == 401:
            locked = b"currently locked out" in (response.content or b"")
            raise UnauthorizedError("locked out" if locked else "refused")
        if response.status_code in (403, 404):
            raise _HttpStatusError(response.status_code)
        super().raise_response_errors(response)


class _Credentials(Credentials):
    """Compared by identity, so exchangelib's process-wide protocol cache never matches another client's entry."""

    __eq__ = object.__eq__
    __hash__ = object.__hash__


class _UncachedProtocolMeta(CachingProtocol):
    """Build protocols directly: exchangelib's cache keeps them for the life of the process, for anyone."""

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        return type.__call__(cls, *args, **kwargs)


class _Protocol(Protocol, metaclass=_UncachedProtocolMeta):
    """This client's connection pool, TLS trust and timeout."""

    def __init__(self, *, config: Any, verify: bool | str, timeout_s: int) -> None:
        super().__init__(config=config)
        self._verify = verify
        # An instance attribute: the class-wide default (120 s) stays as it is for anyone else.
        self.TIMEOUT = timeout_s

    def create_session(self) -> Any:
        session = super().create_session()
        session.mount(self.service_endpoint, _adapter(self._verify))
        return session


class _OwnFolderId(DistinguishedFolderId):
    """A distinguished folder of the mailbox EWS opens when none is named (no ``Mailbox`` element)."""

    def clean(self, version: Any = None) -> None:
        self.mailbox = None
        super(DistinguishedFolderId, self).clean(version=version)


class _GetOwnFolder(GetFolder):
    """GetFolder without ``X-AnchorMailbox``: the request must not name any mailbox."""

    def _extra_headers(self) -> dict[str, str]:
        headers: dict[str, str] = super()._extra_headers()
        headers.pop("X-AnchorMailbox", None)
        return headers


class _FindItemPages(FindItem):
    """FindItem over one or more folders that returns the first page of each, per folder, in one request.

    exchangelib's paging would read on through every folder (or stop after a
    total count, all from the first folder); a newest-first page of each is
    what a merged search needs.
    """

    def pages(self, folders: list[Any], **kwargs: Any) -> list[list[Any]]:
        self.additional_fields = kwargs["additional_fields"]
        self.shape = kwargs["shape"]
        payload_kwargs = dict(kwargs, folders=folders, page_size=self.page_size)
        out: list[list[Any]] = []
        for page, _next_offset in self._get_pages(self.get_payload, payload_kwargs, len(folders)):
            if isinstance(page, Exception):
                out.append([page])
            elif page is None:
                out.append([])
            else:
                elems = self._get_elems_from_page(page, None, 0)
                out.append([e if isinstance(e, Exception) else self._elem_to_obj(e) for e in elems])
        return out


class _GetUserAvailability(GetUserAvailability):
    """Every per-address error comes back in that address's place instead of failing the whole call."""

    ERRORS_TO_CATCH_IN_RESPONSE = (ResponseMessageError,)


def _utc_timezone_element() -> Any:
    # Exactly what exchangelib derives from the server's UTC definition (one period, no daylight saving).
    return TimeZone(
        bias=0,
        standard_time=StandardTime(bias=0, time=datetime.time(0), occurrence=1, iso_month=1, weekday=1),
        daylight_time=DaylightTime(bias=0, time=datetime.time(0), occurrence=5, iso_month=12, weekday=7),
    )


def _first(results: Iterable[Any]) -> Any:
    """The one result of a call; an error exchangelib handed back in its place is raised."""
    for result in results:
        if isinstance(result, Exception):
            raise result
        return result
    raise ErrorItemNotFound("no result")


# --- mapping exchangelib values to ours ---------------------------------------------------------------------------


def _smtp(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("smtp:"):
        text = text[5:]
    return text if _SMTP.match(text) else ""


def _aware(value: datetime.datetime | None) -> datetime.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)


def _ews_time(value: datetime.datetime) -> Any:
    aware = _aware(value)
    assert aware is not None
    return EWSDateTime.from_datetime(aware)


def _utc(value: Any) -> datetime.datetime | None:
    """A plain, aware UTC datetime from what exchangelib gives (naive values are UTC)."""
    if not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.UTC)
    return datetime.datetime.fromtimestamp(value.timestamp(), tz=datetime.UTC)


def _address(mailbox: Any) -> Address | None:
    if mailbox is None:
        return None
    email = _smtp(getattr(mailbox, "email_address", ""))
    name = str(getattr(mailbox, "name", "") or "").strip()
    if not email and not name:
        return None
    return Address(email=email, name=name)


def _addresses(mailboxes: Any) -> tuple[Address, ...]:
    out = []
    for mailbox in mailboxes or ():
        address = _address(mailbox)
        if address is not None:
            out.append(address)
    return tuple(out)


def _fold_preview(text: Any) -> str:
    return " ".join(str(text or "").split())[:PREVIEW_MAX]


def _fold_body(text: Any) -> str:
    """The text body with line ends unified, trailing spaces gone and runs of blank lines folded to one."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    joined = "\n".join(line.rstrip() for line in lines)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _owa_url(value: Any, host: str) -> str:
    """An Outlook on the web link from Exchange's web client form string (a full URL from 2013 on)."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("?") and host:
        text = f"https://{host}/owa/{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("https", "http") or not parts.netloc:
        return ""
    return text[:2000]


def _hints(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for header in headers or ():
        name = str(getattr(header, "name", "") or "").strip().lower()
        if name in HINT_HEADERS and name not in out:
            out[name] = " ".join(str(getattr(header, "value", "") or "").split())[:_HINT_VALUE_MAX]
    return out


def _summary(item: Any, *, mailbox: str, folder: str, host: str, with_hints: bool = False) -> MessageSummary:
    conversation = getattr(item, "conversation_id", None)
    item_class = str(getattr(item, "item_class", "") or "")
    importance = str(getattr(item, "importance", "") or "Normal")
    return MessageSummary(
        item_id=str(item.id),
        change_key=str(item.changekey or ""),
        mailbox=mailbox,
        subject=str(getattr(item, "subject", "") or ""),
        sender=_address(getattr(item, "author", None)) or _address(getattr(item, "sender", None)),
        to=_addresses(getattr(item, "to_recipients", None)),
        cc=_addresses(getattr(item, "cc_recipients", None)),
        received=_utc(getattr(item, "datetime_received", None)),
        is_read=bool(getattr(item, "is_read", False)),
        has_attachments=bool(getattr(item, "has_attachments", False)),
        importance=importance if importance in ("Low", "Normal", "High") else "Normal",
        preview=_fold_preview(getattr(item, PREVIEW_FIELD, "")),
        folder=folder,
        conversation_id=str(getattr(conversation, "id", "") or ""),
        is_meeting_request=isinstance(item, MeetingRequest) or item_class.startswith("IPM.Schedule.Meeting.Request"),
        flagged=getattr(item, FLAG_FIELD, None) == _FLAGGED,
        owa_url=_owa_url(getattr(item, "web_client_read_form_query_string", ""), host),
        hints=_hints(getattr(item, "headers", None)) if with_hints else {},
    )


def _draft_result(item: Any, *, mailbox: str, host: str) -> DraftResult:
    link = getattr(item, "web_client_edit_form_query_string", "") or getattr(
        item, "web_client_read_form_query_string", ""
    )
    return DraftResult(
        item_id=str(item.id),
        change_key=str(item.changekey or ""),
        mailbox=mailbox,
        subject=str(getattr(item, "subject", "") or ""),
        to=_addresses(getattr(item, "to_recipients", None)),
        cc=_addresses(getattr(item, "cc_recipients", None)),
        body_text=_fold_body(getattr(item, "text_body", "")),
        owa_url=_owa_url(link, host),
    )


def _attachments(item: Any) -> tuple[Attachment, ...]:
    """Names, sizes and types only: the contents are never fetched."""
    out = []
    for attachment in getattr(item, "attachments", None) or ():
        if getattr(attachment, "is_inline", False):
            continue
        out.append(
            Attachment(
                name=str(getattr(attachment, "name", "") or ""),
                size=int(getattr(attachment, "size", 0) or 0),
                content_type=str(getattr(attachment, "content_type", "") or ""),
            )
        )
    return tuple(out)


def _recipients(addresses: Iterable[Address]) -> list[Any]:
    """exchangelib mailboxes for the addresses given; ``invalid`` for one that is not an SMTP address."""
    out = []
    for address in addresses:
        email = _smtp(address.email)
        if not email:
            raise EwsError("invalid", "One of the recipients is not a valid email address.")
        out.append(Mailbox(email_address=email, name=(address.name or None)))
    return out


def _dedupe(mailboxes: Iterable[Any], *, drop: set[str] | frozenset[str] = frozenset()) -> list[Any]:
    out, seen = [], set(drop)
    for mailbox in mailboxes:
        email = _smtp(getattr(mailbox, "email_address", ""))
        if not email or email in seen:
            continue
        seen.add(email)
        out.append(mailbox)
    return out


def _aqs(query: str, sender: str) -> str:
    parts = [query.strip()] if query and query.strip() else []
    if sender and sender.strip():
        parts.append('from:"' + sender.strip().replace('"', "") + '"')
    return " ".join(parts)


# --- working hours and time zones ---------------------------------------------------------------------------------


def _nth_weekday(year: int, month: int, occurrence: int, weekday: int) -> datetime.date:
    """The ``occurrence``-th (5 = last) ``weekday`` (1 = Monday) of the month."""
    if occurrence >= 5:
        nxt = datetime.date(year + month // 12, month % 12 + 1, 1)
        day = nxt - datetime.timedelta(days=1)
        while day.isoweekday() != weekday:
            day -= datetime.timedelta(days=1)
        return day
    day = datetime.date(year, month, 1)
    while day.isoweekday() != weekday:
        day += datetime.timedelta(days=1)
    return day + datetime.timedelta(weeks=max(occurrence, 1) - 1)


#: A Windows time zone rule as a hashable tuple: (bias, time of day, occurrence, month, ISO weekday).
_Rule = tuple[int, datetime.time | None, int, int, int]
_TzKey = tuple[int, _Rule | None, _Rule | None]


def _tz_key(tz: Any) -> _TzKey:
    """exchangelib's ``TimeZone`` (Bias, StandardTime, DaylightTime) as a hashable tuple."""

    def rule(value: Any) -> _Rule | None:
        if value is None:
            return None
        return (
            int(value.bias or 0),
            value.time,
            int(value.occurrence or 1),
            int(value.iso_month or 1),
            int(value.weekday or 1),
        )

    return (int(tz.bias or 0), rule(tz.standard_time), rule(tz.daylight_time))


def _transition(year: int, rule: _Rule, offset: datetime.timedelta) -> datetime.datetime:
    """When a Windows time zone rule fires in ``year``, in UTC (``offset`` is the local offset before it)."""
    _bias, at, occurrence, month, weekday = rule
    day = _nth_weekday(year, month, occurrence, weekday)
    local = datetime.datetime.combine(day, at or datetime.time(0))
    return (local - offset).replace(tzinfo=datetime.UTC)


def _noons(year: int) -> list[datetime.datetime]:
    first = datetime.datetime(year, 1, 1, 12, tzinfo=datetime.UTC)
    days = (datetime.date(year + 1, 1, 1) - datetime.date(year, 1, 1)).days
    return [first + datetime.timedelta(days=n) for n in range(days)]


def _windows_offsets(key: _TzKey, year: int) -> list[datetime.timedelta]:
    """The UTC offset at noon UTC of every day of ``year`` under these Windows rules."""
    bias, std, dst = key
    standard = datetime.timedelta(minutes=-(bias + (std[0] if std else 0)))
    noons = _noons(year)
    if std is None or dst is None or dst[0] == std[0]:
        return [standard] * len(noons)
    daylight = datetime.timedelta(minutes=-(bias + dst[0]))
    starts, ends = _transition(year, dst, standard), _transition(year, std, daylight)
    out = []
    for moment in noons:
        in_dst = starts <= moment < ends if starts < ends else (moment >= starts or moment < ends)
        out.append(daylight if in_dst else standard)
    return out


@functools.cache
def _candidate_zones() -> tuple[str, ...]:
    """IANA zones to try: Windows' primary zone for each of its own zones first, then the rest."""
    from exchangelib.winzone import MS_TIMEZONE_TO_IANA_MAP

    available = zoneinfo.available_timezones()
    preferred = [name for name in dict.fromkeys(MS_TIMEZONE_TO_IANA_MAP.values()) if name in available]
    taken = set(preferred)
    rest = sorted(n for n in available if n not in taken and not n.startswith(("posix/", "right/")))
    return tuple(preferred + rest)


@functools.lru_cache(maxsize=256)
def _iana_zone(key: _TzKey, year: int) -> str | None:
    """The IANA zone whose UTC offset matches these Windows rules on every day of ``year``, if any."""
    expected = _windows_offsets(key, year)
    noons = _noons(year)
    middle = len(noons) // 2
    for name in _candidate_zones():
        try:
            zone = zoneinfo.ZoneInfo(name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
            continue
        # Two quick probes rule out almost every zone before the day-by-day check.
        if noons[0].astimezone(zone).utcoffset() != expected[0]:
            continue
        if noons[middle].astimezone(zone).utcoffset() != expected[middle]:
            continue
        if all(moment.astimezone(zone).utcoffset() == offset for moment, offset in zip(noons, expected, strict=True)):
            return name
    return None


def _working_hours(view: Any, year: int) -> WorkingHours | None:
    """The person's working hours in their own zone; several periods are joined (all days, earliest to latest)."""
    periods = [p for p in (getattr(view, "working_hours", None) or ()) if p.start is not None and p.end is not None]
    if not periods:
        return None
    days = sorted({int(day) for p in periods for day in (p.weekdays or ()) if 1 <= int(day) <= 7})
    start = min(p.start.hour * 60 + p.start.minute for p in periods)
    # 1440 minutes (midnight) comes back from exchangelib as 00:00.
    end = max((p.end.hour * 60 + p.end.minute) or 1440 for p in periods)
    if not days or end <= start:
        return None
    tz = getattr(view, "working_hours_timezone", None)
    if tz is None or tz.bias is None:
        return WorkingHours(timezone="UTC", days=tuple(days), start_minute=start, end_minute=end)
    try:
        name = _iana_zone(_tz_key(tz), year)
    except (TypeError, ValueError):
        name = None
    if name:
        return WorkingHours(timezone=name, days=tuple(days), start_minute=start, end_minute=end)
    # No IANA zone keeps these rules: shift the hours into UTC by the standard offset.
    east = -(int(tz.bias or 0) + int(getattr(tz.standard_time, "bias", 0) or 0))
    start, end, shift = start - east, end - east, 0
    if start < 0 and end <= 0:
        start, end, shift = start + 1440, end + 1440, -1
    elif start >= 1440:
        start, end, shift = start - 1440, end - 1440, 1
    if start < 0 or end > 1440:
        return None
    shifted = sorted({(day - 1 + shift) % 7 + 1 for day in days})
    return WorkingHours(timezone="UTC", days=tuple(shifted), start_minute=start, end_minute=end)


def _availability_error(error: Exception) -> str:
    if isinstance(error, ErrorMailRecipientNotFound | ErrorNonExistentMailbox | ErrorInvalidSmtpAddress):
        return "No mailbox has this address."
    if isinstance(error, ErrorNoFreeBusyAccess | ErrorAccessDenied):
        return "Free/busy is not visible for this person."
    return "Exchange could not tell this person's free/busy."


# --- errors -------------------------------------------------------------------------------------------------------

_KINDS: tuple[tuple[tuple[type[BaseException], ...], ErrorKind, str], ...] = (
    (
        (ErrorSendAsDenied,),
        "access_denied",
        "You may not send as this mailbox. Ask the Exchange administrator for Send As or Send on Behalf permission.",
    ),
    (
        (ErrorAccessDenied, ErrorCreateItemAccessDenied, ErrorImpersonateUserDenied, ErrorNotDelegate),
        "access_denied",
        "Exchange says this login may not open that mailbox or item.",
    ),
    ((ErrorNonExistentMailbox,), "not_found", "Exchange has no mailbox with this address."),
    (
        (ErrorItemNotFound, ErrorFolderNotFound, ErrorInvalidIdMalformed),
        "not_found",
        "That item is no longer in the mailbox.",
    ),
    (
        (
            ErrorServerBusy,
            ErrorTooManyObjectsOpened,
            ErrorExceededConnectionCount,
            ErrorInsufficientResources,
            ErrorInternalServerTransientError,
            RateLimitError,
        ),
        "throttled",
        "Exchange is busy and asked to slow down. Try again in a minute.",
    ),
    (
        (ErrorIrresolvableConflict, ErrorChangeKeyRequiredForWriteOperations, ErrorStaleObject, ErrorInvalidChangeKey),
        "conflict",
        "The item changed since it was read. Read it again.",
    ),
    (
        (ErrorInvalidRecipients, ErrorMailRecipientNotFound, ErrorMissingRecipients, ErrorInvalidSmtpAddress),
        "invalid",
        "Exchange did not accept one of the recipients' addresses.",
    ),
    ((ErrorInvalidRestriction,), "invalid", "Exchange could not run that search. Try simpler words."),
    (
        (ErrorPasswordExpired, ErrorPasswordChangeRequired),
        "auth",
        "The password has expired. Change it, then type the new one.",
    ),
    ((ErrorAccountDisabled,), "auth", "Exchange says this account is disabled."),
    ((ErrorQuotaExceeded,), "server", "The mailbox is full."),
    (
        (ErrorMailboxMoveInProgress, ErrorMailboxStoreUnavailable, ErrorConnectionFailed, CASError),
        "server",
        "Exchange could not open the mailbox right now. Try again later.",
    ),
)


def _caused_by(exc: BaseException, kinds: tuple[type[BaseException], ...]) -> bool:
    seen: BaseException | None = exc
    for _depth in range(5):
        if seen is None:
            return False
        if isinstance(seen, kinds):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _transport_error(exc: BaseException, where: str) -> EwsError | None:
    """A failure below EWS - TLS, the connection, a timeout - whatever exchangelib wrapped it in."""
    if _caused_by(exc, (requests.exceptions.SSLError, ssl.SSLError)) or (
        isinstance(exc, TransportError) and "CERTIFICATE_VERIFY_FAILED" in str(exc)
    ):
        return EwsError(
            "tls",
            f"The certificate of the Exchange server{where} could not be verified. "
            "Add the CA certificate on the Exchange EWS page, or check the server name.",
        )
    if _caused_by(exc, (requests.exceptions.Timeout, TimeoutError)):
        return EwsError("unreachable", f"Exchange{where} did not answer in time.")
    if _caused_by(exc, (requests.exceptions.ConnectionError, ConnectionError)):
        return EwsError("unreachable", f"Could not connect to Exchange{where}. Check the address and the network.")
    return None


def _http_error(exc: BaseException, where: str) -> EwsError:
    """What is left: an HTTP answer EWS did not wrap in SOAP, or something unexpected."""
    if isinstance(exc, _HttpStatusError):
        if exc.status == 403:
            return EwsError(
                "access_denied", "Exchange refused EWS for this login (HTTP 403). EWS may be turned off for it."
            )
        return EwsError("server", f"There is no EWS service{where} (HTTP 404). Check the EWS address.")
    if isinstance(exc, RedirectError):
        return EwsError("server", "Exchange redirected the request. Check the EWS address (.../EWS/Exchange.asmx).")
    if isinstance(exc, TransportError):
        match = _HTTP_CODE.search(str(exc))
        if match:
            return EwsError("server", f"Exchange answered with an error (HTTP {match.group(1)}).")
    elif isinstance(exc, OSError):
        return EwsError("unreachable", f"Could not connect to Exchange{where}.")
    return EwsError("server", "Exchange answered in a way Alpharouter did not expect.")


def _map_error(exc: BaseException, host: str) -> EwsError:
    """The ``EwsError`` for anything an EWS call raised. Messages are fixed text: nothing of the server's answer."""
    where = f" at {host}" if host else ""
    if isinstance(exc, EwsError):
        return exc
    if isinstance(exc, UnauthorizedError):
        if "locked out" in str(exc):
            return EwsError("auth", "Exchange says this account is locked out. Ask the IT help desk to unlock it.")
        return EwsError("auth", "Exchange did not accept the user name or password.")
    # Before the EWS codes: exchangelib reports a lost connection as "timeout" or "busy".
    below = _transport_error(exc, where)
    if below is not None:
        return below
    for kinds, kind, message in _KINDS:
        if isinstance(exc, kinds):
            return EwsError(kind, message)
    if isinstance(exc, ErrorTimeoutExpired):
        return EwsError("unreachable", f"Exchange{where} did not answer in time.")
    return _http_error(exc, where)


# --- the client ---------------------------------------------------------------------------------------------------


def _identity_names(login: str) -> list[str]:
    """What to ask the address book about a login: the user name of ``DOMAIN\\user``, else the UPN and its user part."""
    text = login.strip()
    if "\\" in text:
        user = text.split("\\", 1)[1].strip()
        return [user] if user else []
    if "@" in text:
        local = text.split("@", 1)[0].strip()
        return [text] + ([local] if local else [])
    return [text] if text else []


class EwsClient:
    """``MailClient`` over EWS for one login (see the module docstring). Not for use by two threads at once."""

    def __init__(self, config: EwsConfig) -> None:
        self.config = config
        parts = urlsplit(config.ews_url or "")
        self._host = (parts.hostname or "").lower()
        self._usable = parts.scheme.lower() == "https" and bool(parts.hostname)
        self._verify = _verify_setting(config)
        self._configuration = Configuration(
            service_endpoint=config.ews_url,
            credentials=_Credentials(username=config.login, password=config.password),
            auth_type=BASIC if config.auth == "basic" else NTLM,
            version=Version(build=EXCHANGE_2019),
            retry_policy=_NoRetry(),
            max_connections=2,
        )
        self._protocol = _Protocol(config=self._configuration, verify=self._verify, timeout_s=int(config.timeout_s))
        self._accounts: dict[str, Any] = {}
        self._roots: dict[str, Any] = {}
        self._own_root_id: str | None = None
        self._own: MailboxInfo | None = None

    # --- plumbing ---

    @contextlib.contextmanager
    def _errors(self, operation: str) -> Iterator[None]:
        if not self._usable:
            raise EwsError("invalid", "The EWS address is not set. Give it on the Exchange EWS page.")
        try:
            yield
        except EwsError:
            raise
        except Exception as exc:  # noqa: BLE001 -- callers are promised EwsError and nothing else
            error = _map_error(exc, self._host)
            logger.info("EWS %s failed: %s (%s)", operation, error.kind, type(exc).__name__)
            raise error from None

    def _account(self, smtp: str) -> Any:
        """The exchangelib account for a mailbox, opened as the login (delegate, never impersonation)."""
        key = smtp.strip().lower()
        account = self._accounts.get(key)
        if account is None:
            account = Account(
                primary_smtp_address=key,
                config=self._configuration,
                autodiscover=False,
                access_type=DELEGATE,
                locale="en_US",
                default_timezone=UTC,
            )
            # Account() took a protocol from exchangelib's process-wide cache; drop it and use this client's own.
            with CachingProtocol._protocol_cache_lock:
                CachingProtocol._protocol_cache.pop(CachingProtocol._cache_key(self._configuration), None)
            account.protocol = self._protocol
            self._accounts[key] = account
        return account

    def _root(self, account: Any) -> Any:
        """An unfetched root folder object: enough for folders named by id, without asking Exchange for it."""
        key = str(account.primary_smtp_address)
        root = self._roots.get(key)
        if root is None:
            root = Root(account=account)
            self._roots[key] = root
        return root

    def _folder(self, account: Any, which: str) -> Any:
        cls = _FOLDER_CLASSES[which]
        return cls(
            root=self._root(account),
            _distinguished_id=DistinguishedFolderId(
                id=cls.DISTINGUISHED_FOLDER_ID, mailbox=Mailbox(email_address=account.primary_smtp_address)
            ),
        )

    def _login_account(self) -> Any:
        # Used only for requests that name no mailbox; its address never leaves this process.
        login = _smtp(self.config.login)
        return self._account(login or "login@mailbox.invalid")

    def _own_root(self) -> str:
        if self._own_root_id is None:
            account = self._login_account()
            folder = Root(account=account)
            folder._distinguished_id = _OwnFolderId(id="msgfolderroot")
            result = _first(
                _GetOwnFolder(account=account).call(folders=[folder], additional_fields=None, shape=ID_ONLY)
            )
            self._own_root_id = str(result.id)
        return self._own_root_id

    def _mailbox_root(self, smtp: str) -> str:
        account = self._account(smtp)
        folder = Root(
            account=account,
            _distinguished_id=DistinguishedFolderId(id="msgfolderroot", mailbox=Mailbox(email_address=smtp)),
        )
        return str(_first(GetFolder(account=account).call(folders=[folder], additional_fields=None, shape=ID_ONLY)).id)

    def _resolve(self, name: str, *, scope: str, full: bool) -> list[Any]:
        results = self._protocol.resolve_names([name], return_full_contact_data=full, search_scope=scope)
        out = []
        for result in results:
            if isinstance(result, ErrorNameResolutionNoResults):
                continue
            if isinstance(result, Exception):
                raise result
            out.append(result if full else (result, None))
        return out

    def _fetch(self, account: Any, ids: Sequence[tuple[str, str | None]], fields: tuple[str, ...]) -> list[Any]:
        if not ids:
            return []
        folder = self._folder(account, "inbox")
        return list(account.fetch(ids=ids, folder=folder, only_fields=list(fields)))

    def _get_one(self, account: Any, item_id: str, fields: tuple[str, ...]) -> Any:
        return _first(self._fetch(account, [(item_id, None)], fields))

    def _find_pages(
        self, account: Any, folders: list[Any], q: Any, *, order: str, offset: int, page_size: int
    ) -> list[list[Any]]:
        restriction = query_string = None
        if q.query_string:
            query_string = Restriction(q, folders=folders, applies_to=Restriction.ITEMS)
        elif not q.is_empty():
            restriction = Restriction(q, folders=folders, applies_to=Restriction.ITEMS)
        additional = {
            FieldPath(field=Message.get_field_by_fieldname("datetime_received")),
            FieldPath(field=Message.get_field_by_fieldname("is_read")),
        }
        return _FindItemPages(account=account, page_size=max(1, min(page_size, _PAGE_MAX))).pages(
            folders,
            additional_fields=additional,
            restriction=restriction,
            order_fields=[FieldOrder.from_string(order, folder=folders[0])],
            query_string=query_string,
            shape=ID_ONLY,
            depth="Shallow",
            calendar_view=None,
            offset=offset,
        )

    def _search_folders(self, account: Any, folder: str) -> list[tuple[str, Any]]:
        if folder in _FOLDER_CLASSES:
            return [(folder, self._folder(account, folder))]
        if folder != "all":
            raise EwsError("invalid", "Search the inbox, sent, drafts, deleted or all folders.")
        inbox = self._folder(account, "inbox")
        out: list[tuple[str, Any]] = [("inbox", inbox)]
        found = FolderCollection(account=account, folders=[inbox]).find_folders(depth="Deep", max_items=_SUBFOLDERS_MAX)
        for sub in found:
            if isinstance(sub, Exception):
                raise sub
            folder_class = str(getattr(sub, "folder_class", "") or "")
            if folder_class and folder_class != "IPF.Note" and not folder_class.startswith("IPF.Note."):
                continue
            out.append((f"inbox/{getattr(sub, 'name', '') or ''}", sub))
        out.append(("sent", self._folder(account, "sent")))
        return out

    # --- MailClient ---

    def whoami(self) -> MailboxInfo:
        with self._errors("whoami"):
            return self._whoami()

    def _whoami(self) -> MailboxInfo:
        if self._own is not None:
            return self._own
        own_root = self._own_root()
        seen: set[str] = set()
        tries = 0
        for name in _identity_names(self.config.login):
            for email, display in self._identity_candidates(name, seen):
                if tries >= _IDENTITY_TRIES:
                    break
                tries += 1
                try:
                    if self._mailbox_root(email) == own_root:
                        self._own = MailboxInfo(smtp=email, display_name=display)
                        return self._own
                except (ErrorAccessDenied, ErrorNonExistentMailbox, ErrorFolderNotFound):
                    continue
        raise EwsError(
            "server",
            "Exchange accepted the login but its address book did not say which mailbox it opens.",
        )

    def _identity_candidates(self, name: str, seen: set[str]) -> list[tuple[str, str]]:
        """Mailboxes the address book finds for ``name`` (not in ``seen``), exact matches first: (smtp, name)."""
        login = self.config.login.strip().lower()
        wanted = name.lower()
        ranked: list[tuple[int, str, str]] = []
        for mailbox, contact in self._resolve(name, scope="ActiveDirectory", full=True):
            email = _smtp(getattr(mailbox, "email_address", ""))
            if not email or email in seen or getattr(mailbox, "mailbox_type", "Mailbox") not in (None, "Mailbox"):
                continue
            seen.add(email)
            alias = str(getattr(contact, "email_alias", "") or "").lower()
            exact = email == login or email.split("@", 1)[0] == wanted or alias == wanted
            display = str(getattr(mailbox, "name", "") or getattr(contact, "display_name", "") or "")
            ranked.append((0 if exact else 1, email, display))
        return [(email, display) for _rank, email, display in sorted(ranked, key=lambda entry: entry[0])]

    def same_mailbox(self, smtp: str) -> bool:
        with self._errors("same_mailbox"):
            address = _smtp(smtp)
            if not address:
                return False
            own_root = self._own_root()
            try:
                return self._mailbox_root(address) == own_root
            except (ErrorAccessDenied, ErrorNonExistentMailbox, ErrorFolderNotFound):
                return False

    def discover_full_access(self) -> list[MailboxInfo]:
        with self._errors("discover_full_access"):
            own = self._whoami()
            url = (self.config.autodiscover_url or "").strip()
            if not url.lower().startswith("https://"):
                return []
            data = self._autodiscover(url, own.smtp)
            return _alternative_mailboxes(data, own.smtp) if data else []

    def _autodiscover(self, url: str, email: str) -> bytes:
        """The POX answer for ``email``, or ``b""`` when there is none; ``auth`` when the password was refused."""
        ntlm = self.config.auth != "basic"
        session = requests.Session()
        session.mount("https://", _adapter(self._verify))
        if ntlm:
            session.auth = HttpNtlmAuth(self.config.login, self.config.password)
        else:
            session.auth = requests.auth.HTTPBasicAuth(self.config.login, self.config.password)
        body = _POX_REQUEST.format(email=xml_escape(email)).encode("utf-8")
        try:
            with session.post(
                url,
                data=body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                timeout=self.config.timeout_s,
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code == 401:
                    offered = response.headers.get("WWW-Authenticate", "").lower()
                    ours = ("ntlm" in offered or "negotiate" in offered) if ntlm else "basic" in offered
                    if ours:
                        raise EwsError("auth", "Exchange did not accept the user name or password.")
                    return b""
                if response.status_code != 200:
                    return b""
                data = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    data.extend(chunk)
                    if len(data) > _AUTODISCOVER_MAX_BYTES:
                        return b""
                return bytes(data)
        except requests.RequestException as exc:
            logger.info("Autodiscover failed: %s", type(exc).__name__)
            return b""
        finally:
            session.close()

    def check_mailbox(self, smtp: str) -> MailboxInfo:
        with self._errors("check_mailbox"):
            address = _smtp(smtp)
            if not address:
                raise EwsError("invalid", "That is not a valid email address.")
            account = self._account(address)
            inbox = self._folder(account, "inbox")
            _first(GetFolder(account=account).call(folders=[inbox], additional_fields=None, shape=ID_ONLY))
            try:
                found = self._resolve(address, scope="ActiveDirectory", full=False)
            except (ResponseMessageError, TransportError):
                found = []
            boxes = [box for box, _contact in found if _smtp(getattr(box, "email_address", ""))]
            match = [box for box in boxes if _smtp(box.email_address) == address] or (boxes if len(boxes) == 1 else [])
            if match:
                return MailboxInfo(smtp=_smtp(match[0].email_address), display_name=str(match[0].name or ""))
            return MailboxInfo(smtp=address, display_name="")

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
        with self._errors("search"):
            limit = max(1, min(int(limit), SEARCH_MAX))
            offset = max(0, int(offset))
            start, end = _aware(since), _aware(until)
            if start and end and start > end:
                raise EwsError("invalid", "The start of the date range is after its end.")
            account = self._account(mailbox)
            folders = self._search_folders(account, folder)
            aqs = _aqs(query, sender)
            here = bool(aqs) and bool(start or end or unread_only)
            if aqs:
                q = Q(aqs)
            else:
                conditions: dict[str, Any] = {}
                if start:
                    conditions["datetime_received__gte"] = _ews_time(start)
                if end:
                    conditions["datetime_received__lte"] = _ews_time(end)
                if unread_only:
                    conditions["is_read"] = False
                q = Q(**conditions)
            server_paging = len(folders) == 1 and not here
            page = limit if server_paging else (_SCAN_MAX if here else offset + limit)
            pages = self._find_pages(
                account,
                [f for _label, f in folders],
                q,
                order="-datetime_received",
                offset=offset if server_paging else 0,
                page_size=page,
            )
            found: list[tuple[datetime.datetime | None, str, str, str]] = []
            for (label, _folder), items in zip(folders, pages, strict=True):
                for item in items:
                    if isinstance(item, Exception):
                        raise item
                    received = _utc(getattr(item, "datetime_received", None))
                    if here and not _wanted(received, bool(getattr(item, "is_read", False)), start, end, unread_only):
                        continue
                    found.append((received, label, str(item.id), str(item.changekey or "")))
            if not server_paging:
                oldest = datetime.datetime.min.replace(tzinfo=datetime.UTC)
                found.sort(key=lambda entry: entry[0] or oldest, reverse=True)
                found = found[offset : offset + limit]
            items = self._fetch(account, [(item_id, ck) for _r, _l, item_id, ck in found], _SUMMARY_FIELDS)
            out = []
            for (_received, label, _id, _ck), item in zip(found, items, strict=True):
                if isinstance(item, Exception):
                    continue  # gone between FindItem and GetItem
                out.append(_summary(item, mailbox=mailbox, folder=label, host=self._host))
            return out

    def list_received(self, mailbox: str, *, since: datetime.datetime, limit: int = 50) -> list[MessageSummary]:
        with self._errors("list_received"):
            limit = max(1, min(int(limit), LIST_MAX))
            start = _aware(since)
            assert start is not None
            account = self._account(mailbox)
            inbox = self._folder(account, "inbox")
            q = Q(datetime_received__gt=_ews_time(start))
            (items,) = self._find_pages(account, [inbox], q, order="datetime_received", offset=0, page_size=limit)
            ids = []
            for item in items:
                if isinstance(item, Exception):
                    raise item
                ids.append((str(item.id), str(item.changekey or "")))
            fetched = self._fetch(account, ids, (*_SUMMARY_FIELDS, "headers"))
            return [
                _summary(item, mailbox=mailbox, folder="inbox", host=self._host, with_hints=True)
                for item in fetched
                if not isinstance(item, Exception)
            ]

    def read(self, mailbox: str, item_id: str, *, body_chars: int = 8000) -> MessageDetail:
        with self._errors("read"):
            account = self._account(mailbox)
            item = self._get_one(account, item_id, (*_SUMMARY_FIELDS, "text_body", "attachments"))
            body = _fold_body(getattr(item, "text_body", ""))
            limit = max(0, int(body_chars))
            return MessageDetail(
                summary=_summary(item, mailbox=mailbox, folder="", host=self._host),
                body_text=body[:limit],
                truncated=len(body) > limit,
                attachments=_attachments(item),
            )

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
        with self._errors("create_draft"):
            account = self._account(mailbox)
            drafts = self._folder(account, "drafts")
            to_boxes, cc_boxes = _recipients(to), _recipients(cc)
            body = Body(body_text or "")
            title = (subject or "").strip()[:_SUBJECT_MAX]
            if kind == "new":
                if not to_boxes:
                    raise EwsError("invalid", "A new email needs at least one recipient.")
                message = Message(
                    account=account,
                    folder=drafts,
                    subject=title,
                    body=body,
                    to_recipients=_dedupe(to_boxes),
                    cc_recipients=_dedupe(cc_boxes) or None,
                )
                message.save()
                return self._draft(account, str(message.id), mailbox)
            if kind not in ("reply", "reply_all", "forward"):
                raise EwsError("invalid", "A draft is new, reply, reply_all or forward.")
            if not source_item_id:
                raise EwsError("invalid", "A reply or forward needs the email it answers.")
            source = self._get_one(account, source_item_id, _SOURCE_FIELDS)
            reference = ReferenceItemId(id=source.id, changekey=source.changekey)
            if kind == "forward":
                if not to_boxes:
                    raise EwsError("invalid", "A forward needs at least one recipient.")
                response: Any = ForwardItem(
                    account=account,
                    reference_item_id=reference,
                    subject=title or None,
                    new_body=body,
                    to_recipients=_dedupe(to_boxes),
                    cc_recipients=_dedupe(cc_boxes) or None,
                )
            else:
                own = {mailbox.strip().lower()} | ({self._own.smtp} if self._own else set())
                origin = getattr(source, "author", None) or getattr(source, "sender", None)
                recipients = ([origin] if origin is not None else []) + to_boxes
                copies = list(cc_boxes)
                if kind == "reply_all":
                    recipients += [r for r in (source.to_recipients or ()) if _smtp(r.email_address) not in own]
                    copies = [r for r in (source.cc_recipients or ()) if _smtp(r.email_address) not in own] + copies
                recipients = _dedupe(recipients)
                if not recipients:
                    raise EwsError("invalid", "The email has no sender to reply to.")
                copies = _dedupe(copies, drop={_smtp(r.email_address) for r in recipients})
                cls = ReplyToItem if kind == "reply" else ReplyAllToItem
                response = cls(
                    account=account,
                    reference_item_id=reference,
                    subject=title or None,
                    new_body=body,
                    to_recipients=recipients,
                    cc_recipients=copies or None,
                )
            saved = response.save(drafts)
            return self._draft(account, str(saved.id), mailbox)

    def _draft(self, account: Any, item_id: str, mailbox: str) -> DraftResult:
        try:
            item = self._get_one(account, item_id, _DRAFT_FIELDS)
        except (ErrorItemNotFound, ErrorInvalidIdMalformed):
            raise EwsError("not_found", "The draft is no longer in Drafts.") from None
        if not getattr(item, "is_draft", False):
            raise EwsError("not_found", "The draft is no longer in Drafts.")
        return _draft_result(item, mailbox=mailbox, host=self._host)

    def get_draft(self, mailbox: str, item_id: str) -> DraftResult:
        with self._errors("get_draft"):
            return self._draft(self._account(mailbox), item_id, mailbox)

    def send_draft(self, mailbox: str, item_id: str, change_key: str) -> None:
        with self._errors("send_draft"):
            account = self._account(mailbox)
            current = self._draft(account, item_id, mailbox)
            if not change_key or current.change_key != change_key:
                raise EwsError("conflict", "The draft changed since it was read. Read it again before sending.")
            SendItem(account=account).get(
                items=[(item_id, change_key)], saved_item_folder=self._folder(account, "sent")
            )

    def delete_draft(self, mailbox: str, item_id: str) -> None:
        with self._errors("delete_draft"):
            account = self._account(mailbox)
            try:
                self._draft(account, item_id, mailbox)
            except EwsError as error:
                if error.kind == "not_found":
                    return  # already gone (or sent): nothing to discard
                raise
            try:
                DeleteItem(account=account).get(
                    items=[(item_id, None)],
                    delete_type=MOVE_TO_DELETED_ITEMS,
                    send_meeting_cancellations=SEND_TO_NONE,
                    affected_task_occurrences=ALL_OCCURRENCES,
                    suppress_read_receipts=True,
                )
            except (ErrorItemNotFound, ErrorInvalidIdMalformed):
                return

    def find_people(self, query: str, *, limit: int = 10) -> list[Person]:
        with self._errors("find_people"):
            needle = (query or "").strip()
            if not needle:
                raise EwsError("invalid", "Give a name or an address to look up.")
            limit = max(1, min(int(limit), 100))
            out: list[Person] = []
            seen: set[str] = set()
            for mailbox, contact in self._resolve(needle[:255], scope="ActiveDirectoryContacts", full=True):
                email = _smtp(getattr(mailbox, "email_address", ""))
                if not email or email in seen or getattr(mailbox, "mailbox_type", "Mailbox") != "Mailbox":
                    continue
                seen.add(email)
                out.append(
                    Person(
                        email=email,
                        name=str(getattr(mailbox, "name", "") or getattr(contact, "display_name", "") or ""),
                        department=str(getattr(contact, "department", "") or ""),
                        title=str(getattr(contact, "job_title", "") or ""),
                        office=str(getattr(contact, "office", "") or ""),
                    )
                )
                if len(out) >= limit:
                    break
            return out

    def availability(
        self, emails: list[str], *, start: datetime.datetime, end: datetime.datetime
    ) -> list[Availability]:
        with self._errors("availability"):
            begin, finish = _aware(start), _aware(end)
            assert begin is not None and finish is not None
            if finish <= begin:
                raise EwsError("invalid", "The end of the time range must be after its start.")
            if finish - begin > datetime.timedelta(days=_AVAILABILITY_MAX_DAYS):
                raise EwsError(
                    "invalid", f"Exchange gives free/busy for at most {_AVAILABILITY_MAX_DAYS} days at once."
                )
            wanted = [(email, _smtp(email)) for email in emails]
            valid = [address for _given, address in wanted if address]
            views: dict[str, Any] = {}
            if valid:
                results = _GetUserAvailability(self._protocol).call(
                    tzinfo=UTC,
                    mailbox_data=[
                        MailboxData(email=address, attendee_type="Required", exclude_conflicts=False)
                        for address in valid
                    ],
                    timezone=_utc_timezone_element(),
                    free_busy_view_options=FreeBusyViewOptions(
                        time_window=TimeWindow(start=_ews_time(begin), end=_ews_time(finish)),
                        merged_free_busy_interval=30,
                        requested_view="Detailed",
                    ),
                )
                views = dict(zip(valid, results, strict=True))
            out = []
            for given, address in wanted:
                if not address:
                    out.append(
                        Availability(email=str(given or "").strip().lower(), busy=(), error="Not an email address.")
                    )
                    continue
                view = views.get(address)
                if isinstance(view, Exception) or view is None:
                    error = _availability_error(view) if isinstance(view, Exception) else "No answer from Exchange."
                    out.append(Availability(email=address, busy=(), error=error))
                    continue
                if getattr(view, "view_type", None) == "None":
                    out.append(Availability(email=address, busy=(), error="Free/busy is not visible for this person."))
                    continue
                out.append(
                    Availability(
                        email=address,
                        busy=_busy(view),
                        working_hours=_working_hours(view, begin.year),
                    )
                )
            return out

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._protocol.close()
        self._accounts.clear()
        self._roots.clear()


def _wanted(
    received: datetime.datetime | None,
    is_read: bool,
    start: datetime.datetime | None,
    end: datetime.datetime | None,
    unread_only: bool,
) -> bool:
    if unread_only and is_read:
        return False
    if (start or end) and received is None:
        return False
    if start and received is not None and received < start:
        return False
    return not (end and received is not None and received > end)


def _busy(view: Any) -> tuple[BusyInterval, ...]:
    out = []
    for event in getattr(view, "calendar_events", None) or ():
        status = str(getattr(event, "busy_type", "") or "")
        begin, finish = _utc(getattr(event, "start", None)), _utc(getattr(event, "end", None))
        if status not in _BUSY_TYPES or begin is None or finish is None or finish <= begin:
            continue
        out.append(BusyInterval(start=begin, end=finish, status=status))
    return tuple(sorted(out, key=lambda interval: interval.start))


def _local_name(tag: Any) -> str:
    text = str(tag or "")
    return text.rsplit("}", 1)[-1]


def _alternative_mailboxes(data: bytes, own: str) -> list[MailboxInfo]:
    """The ``Delegate`` mailboxes in an Autodiscover POX answer; ``[]`` for anything unreadable."""
    try:
        root = defusedxml.ElementTree.fromstring(data, forbid_dtd=True)
    except (ParseError, defusedxml.DefusedXmlException, ValueError):
        return []
    out: list[MailboxInfo] = []
    seen = {own}
    for node in root.iter():
        if _local_name(node.tag) != "AlternativeMailbox":
            continue
        values = {_local_name(child.tag): (child.text or "").strip() for child in node}
        if values.get("Type", "").lower() != "delegate":
            continue
        smtp = _smtp(values.get("SmtpAddress"))
        if not smtp or smtp in seen:
            continue
        seen.add(smtp)
        out.append(MailboxInfo(smtp=smtp, display_name=values.get("DisplayName", "")[:255]))
        if len(out) >= _AUTODISCOVER_MAX_MAILBOXES:
            break
    return out
