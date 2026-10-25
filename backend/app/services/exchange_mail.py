"""Exchange EWS mailboxes: the administrator's settings, who may connect, and the rules a connection lives by.

Everything that touches a person's mailbox goes through here first - the
Connections API, the admin page, the chat's mail tools and the needs-action
check - so none of them can disagree about who may connect, which login is
used, or when a connection must stop.

- **Who.** Only accounts that sign in with Active Directory (``auth_provider
  == "ldap"``), with an email address, allowed by the ``exchange_mail`` entry
  of the chat tool registry (the Exchange EWS page edits it), and allowed the
  Chat by Feature Access. The feature itself is off until the administrator
  turns it on and gives the EWS address.
- **Login.** Derived from the account, never typed: ``DOMAIN\\username`` (the
  NetBIOS domain from the LDAP settings unless the administrator gives one),
  ``username@suffix``, or the account's email address as the UPN.
- **Password.** Encrypted with ``secret_crypto`` and never returned. The first
  time Exchange refuses it the connection turns to ``needs_password`` and is
  not used again until the person types it anew: Alpharouter never retries a
  refused password on its own, so it can never lock an AD account.
- **Mailboxes.** The connection's own mailbox, and those the person has Full
  Access to (from Autodiscover, or added by hand after a test read). The chat
  may name only these.
- **Item refs.** The model sees a short ref (``m7Q2xK9dPa``) for each email
  instead of the long EWS id; a ref is the same for the same email, belongs to
  one person, and is forgotten after ``REF_TTL_DAYS``.

Functions here flush and never commit; the API commits with its audit row.
The EWS calls themselves are in ``exchange_ews_client`` (synchronous, run in a
thread through ``call_ews``); this module never imports ``exchangelib``.
"""

from __future__ import annotations

import asyncio
import base64
import contextvars
import datetime
import functools
import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_provider import AuthProviderConfig
from app.models.mail_connection import (
    MailActionItem,
    MailConnection,
    MailConnectionMailbox,
    MailDraft,
    MailItemRef,
)
from app.models.system import SystemSetting
from app.models.user import User
from app.services.exchange_ews_types import EwsConfig, EwsError, MailboxInfo

if TYPE_CHECKING:
    from app.services.exchange_ews_types import MailClient

logger = logging.getLogger(__name__)

SETTINGS_KEY = "exchange_ews.settings"
#: The chat tool registry entry that decides who may connect (``chat_tool_registry``).
TOOL_KEY = "exchange_mail"
PROVIDER = "exchange_ews"

LoginFormat = Literal["netbios", "upn", "email"]
LOGIN_FORMATS: tuple[LoginFormat, ...] = ("netbios", "upn", "email")
DetectionMode = Literal["rules", "model"]
DETECTION_MODES: tuple[DetectionMode, ...] = ("rules", "model")

#: How long the model's short name for an email lasts.
REF_TTL_DAYS = 7
REF_LENGTH = 10
_REF_ALPHABET = re.compile(r"^m[A-Za-z0-9]{9}$")
#: EWS calls in flight at once, for the whole process (each holds a thread and an Exchange session).
EWS_CONCURRENCY = 8
CA_BUNDLE_MAX = 64 * 1024
URL_MAX = 500
DOMAIN_MAX = 255
MODEL_ID_MAX = 255

SETTING_BOUNDS: dict[str, tuple[int, int]] = {
    "poll_minutes": (2, 60),
    "search_limit": (5, 100),
    "body_chars": (1000, 30000),
    "timeout_s": (5, 120),
    "max_mailboxes": (1, 50),
    "action_retention_days": (1, 365),
}
_BOOL_SETTINGS = (
    "enabled",
    "verify_tls",
    "require_mailbox_match",
    "allow_full_access",
    "allow_manual_mailboxes",
    "allow_drafts",
    "allow_send",
    "allow_free_time",
    "notify_enabled",
)

_SMTP = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")
_NETBIOS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,14}$")
_DNS = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9-]{2,63}$")
_PEM_CERT = re.compile(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


class MailError(Exception):
    """A request the rules refuse. The APIs answer ``HTTPException(status_code, {"code", "message"})``."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def normalize_smtp(value: Any) -> str:
    """A lower-case SMTP address, or ``""`` when ``value`` is not one."""
    text = str(value or "").strip().lower()
    if text.startswith("smtp:"):
        text = text[5:]
    return text if _SMTP.match(text) and len(text) <= 320 else ""


# --- settings -------------------------------------------------------------------------------------------------


@dataclass
class ExchangeSettings:
    #: Off until the administrator turns it on: nobody sees Connections before.
    enabled: bool = False
    #: ``https://mail.corp.example/EWS/Exchange.asmx`` (a bare ``https://host`` is completed).
    ews_url: str = ""
    #: Blank: ``https://<EWS host>/autodiscover/autodiscover.xml``.
    autodiscover_url: str = ""
    login_format: LoginFormat = "netbios"
    #: ``CORP``. Blank: from the LDAP settings.
    netbios_domain: str = ""
    #: ``corp.example`` for ``username@corp.example``. Blank: the LDAP domain.
    upn_suffix: str = ""
    verify_tls: bool = True
    #: Extra CA certificates (PEM) to trust for the Exchange server, besides the system store.
    ca_bundle_pem: str = ""
    #: The mailbox the login opens must be the account's own (its email address). Off only for odd setups.
    require_mailbox_match: bool = True
    allow_full_access: bool = True
    allow_manual_mailboxes: bool = True
    allow_drafts: bool = True
    allow_send: bool = True
    allow_free_time: bool = True
    #: The needs-action check and its toasts.
    notify_enabled: bool = True
    poll_minutes: int = 5
    detection: DetectionMode = "rules"
    #: The model (``ai_models.id`` as text) that classifies in ``model`` mode; blank: rules.
    detection_model: str = ""
    search_limit: int = 25
    body_chars: int = 8000
    timeout_s: int = 30
    max_mailboxes: int = 10
    action_retention_days: int = 30

    def as_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def ews_endpoint(self) -> str:
        return normalize_ews_url(self.ews_url)

    def autodiscover_endpoint(self) -> str:
        if self.autodiscover_url.strip():
            return self.autodiscover_url.strip()
        parts = urlsplit(self.ews_endpoint())
        if not parts.netloc:
            return ""
        return urlunsplit(("https", parts.netloc, "/autodiscover/autodiscover.xml", "", ""))

    @property
    def configured(self) -> bool:
        return bool(self.ews_endpoint())


def normalize_ews_url(value: str) -> str:
    """The EWS endpoint for an address an administrator typed, or ``""`` when it is not an https address.

    ``https://mail.corp.example`` becomes ``https://mail.corp.example/EWS/Exchange.asmx``; a full path is
    kept as typed (without query or fragment).
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        return ""
    path = parts.path if parts.path not in ("", "/") else "/EWS/Exchange.asmx"
    return urlunsplit(("https", parts.netloc, path, "", ""))


def _valid_https(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme.lower() == "https" and bool(parts.hostname) and not parts.username and not parts.password


def _lenient_int(data: dict[str, Any], key: str, default: int) -> int:
    low, high = SETTING_BOUNDS[key]
    raw = data.get(key, default)
    if isinstance(raw, bool):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(value, low), high)


def _settings_from_stored(data: dict[str, Any]) -> ExchangeSettings:
    """What was saved, with anything missing, garbled or out of bounds put back within the rules."""
    defaults = ExchangeSettings()
    values: dict[str, Any] = {}
    for key in _BOOL_SETTINGS:
        raw = data.get(key, getattr(defaults, key))
        values[key] = raw if isinstance(raw, bool) else getattr(defaults, key)
    for key in SETTING_BOUNDS:
        values[key] = _lenient_int(data, key, getattr(defaults, key))
    for key, limit in (
        ("ews_url", URL_MAX),
        ("autodiscover_url", URL_MAX),
        ("netbios_domain", DOMAIN_MAX),
        ("upn_suffix", DOMAIN_MAX),
        ("detection_model", MODEL_ID_MAX),
        ("ca_bundle_pem", CA_BUNDLE_MAX),
    ):
        raw = data.get(key, "")
        values[key] = raw.strip()[:limit] if isinstance(raw, str) else ""
    if values["autodiscover_url"] and not _valid_https(values["autodiscover_url"]):
        values["autodiscover_url"] = ""
    fmt = data.get("login_format")
    values["login_format"] = fmt if fmt in LOGIN_FORMATS else defaults.login_format
    mode = data.get("detection")
    values["detection"] = mode if mode in DETECTION_MODES else defaults.detection
    return ExchangeSettings(**values)


async def load_settings(db: AsyncSession) -> ExchangeSettings:
    """The administrator's settings; the defaults until they save some, or for whatever is unreadable."""
    row = await db.get(SystemSetting, SETTINGS_KEY)
    try:
        data = json.loads(str(row.value)) if row is not None and row.value else {}
    except ValueError:
        data = {}
    return _settings_from_stored(data if isinstance(data, dict) else {})


def _invalid(message: str) -> MailError:
    return MailError("invalid_settings", message, 422)


def _strict_int(data: dict[str, Any], key: str, default: int) -> int:
    low, high = SETTING_BOUNDS[key]
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _invalid(f"{key} must be a whole number from {low} to {high}.")
    return value


def _strict_text(data: dict[str, Any], key: str, limit: int) -> str:
    value = data.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise _invalid(f"{key} must be text of up to {limit} characters.")
    return value.strip()


def check_ca_bundle(pem: str) -> int:
    """How many certificates ``pem`` holds; refuses (422) text that is not PEM certificates."""
    if not pem.strip():
        return 0
    from cryptography import x509

    blocks = _PEM_CERT.findall(pem)
    if not blocks:
        raise _invalid("The CA certificates must be PEM text (-----BEGIN CERTIFICATE----- ...).")
    for block in blocks:
        try:
            x509.load_pem_x509_certificate(block.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise _invalid("One of the CA certificates could not be read.") from exc
    return len(blocks)


def validate_settings(data: dict[str, Any]) -> ExchangeSettings:
    """Check settings an administrator sends; refuse with ``invalid_settings`` (422) and say which value is wrong.

    A key that is left out takes its default, so a partial update has to be
    merged over the current ``as_dict()`` before it is checked.
    """
    if not isinstance(data, dict):
        raise _invalid("Send the settings as an object.")
    defaults = ExchangeSettings()
    values: dict[str, Any] = {}
    for key in _BOOL_SETTINGS:
        value = data.get(key, getattr(defaults, key))
        if not isinstance(value, bool):
            raise _invalid(f"{key} must be true or false.")
        values[key] = value
    for key in SETTING_BOUNDS:
        values[key] = _strict_int(data, key, getattr(defaults, key))

    ews_url = _strict_text(data, "ews_url", URL_MAX)
    if ews_url and not normalize_ews_url(ews_url):
        raise _invalid("The EWS address must be an https address, such as https://mail.corp.example/EWS/Exchange.asmx.")
    values["ews_url"] = normalize_ews_url(ews_url) if ews_url else ""
    if values["enabled"] and not values["ews_url"]:
        raise _invalid("Give the EWS address before turning Exchange EWS on.")
    autodiscover = _strict_text(data, "autodiscover_url", URL_MAX)
    if autodiscover and not _valid_https(autodiscover):
        raise _invalid("The Autodiscover address must be an https address, or blank.")
    values["autodiscover_url"] = autodiscover

    fmt = data.get("login_format", defaults.login_format)
    if fmt not in LOGIN_FORMATS:
        raise _invalid(f"login_format must be one of {', '.join(LOGIN_FORMATS)}.")
    values["login_format"] = fmt
    netbios = _strict_text(data, "netbios_domain", DOMAIN_MAX)
    if netbios and not _NETBIOS.match(netbios):
        raise _invalid("The NetBIOS domain is a short name such as CORP (up to 15 letters, digits, '-' or '.').")
    values["netbios_domain"] = netbios.upper()
    suffix = _strict_text(data, "upn_suffix", DOMAIN_MAX).lstrip("@")
    if suffix and not _DNS.match(suffix):
        raise _invalid("The UPN suffix is a domain such as corp.example.")
    values["upn_suffix"] = suffix.lower()

    ca = data.get("ca_bundle_pem", "")
    if ca is None:
        ca = ""
    if not isinstance(ca, str) or len(ca) > CA_BUNDLE_MAX:
        raise _invalid(f"The CA certificates can be up to {CA_BUNDLE_MAX // 1024} KB of PEM text.")
    check_ca_bundle(ca)
    values["ca_bundle_pem"] = ca.strip()

    mode = data.get("detection", defaults.detection)
    if mode not in DETECTION_MODES:
        raise _invalid(f"detection must be one of {', '.join(DETECTION_MODES)}.")
    values["detection"] = mode
    values["detection_model"] = _strict_text(data, "detection_model", MODEL_ID_MAX)
    if mode == "model" and not values["detection_model"]:
        raise _invalid("Choose the model that picks emails needing action, or use the rules.")
    return ExchangeSettings(**values)


async def save_settings(db: AsyncSession, settings: ExchangeSettings) -> None:
    """Store the settings; the caller commits (with its Admin Logs row)."""
    value = json.dumps(settings.as_dict(), ensure_ascii=False)
    row = await db.get(SystemSetting, SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value))
    else:
        row.value = value  # type: ignore[assignment]


def changed_keys(before: ExchangeSettings, after: ExchangeSettings) -> list[str]:
    """The settings that differ, for the Admin Logs row (names only, never the values of the CA text)."""
    old, new = before.as_dict(), after.as_dict()
    return [key for key in new if old.get(key) != new[key]]


# --- the domain, from the LDAP settings --------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectoryDefaults:
    """What the LDAP settings say about the domain; blanks when there are none."""

    netbios_domain: str = ""
    dns_domain: str = ""

    @property
    def available(self) -> bool:
        return bool(self.netbios_domain or self.dns_domain)


async def directory_defaults(db: AsyncSession) -> DirectoryDefaults:
    """The NetBIOS and DNS domain the LDAP settings imply. Reads the saved row only: never a network call."""
    from app.services.ldap_config import infer_domain, infer_netbios_domain

    row = await db.get(AuthProviderConfig, "ldap")
    try:
        raw = json.loads(str(row.config_json)) if row is not None and row.config_json else {}
    except ValueError:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    domain = str(raw.get("domain") or "").strip()
    base_dn = str(raw.get("base_dn") or "").strip() or None
    bind_username = str(raw.get("bind_username") or raw.get("bind_dn") or "").strip()
    if not domain:
        domain = infer_domain(bind_username, base_dn)
    if not domain and base_dn:
        parts = re.findall(r"DC=([^,]+)", base_dn, flags=re.I)
        domain = ".".join(parts)
    netbios = ""
    if "\\" in bind_username:
        candidate = bind_username.split("\\", 1)[0].strip()
        if candidate and "." not in candidate:
            netbios = candidate
    netbios = netbios or infer_netbios_domain(domain, base_dn)
    return DirectoryDefaults(netbios_domain=netbios.upper()[:15], dns_domain=domain.lower())


def login_for(user: User, settings: ExchangeSettings, defaults: DirectoryDefaults) -> str:
    """The login NTLM is given for this account, or ``""`` when one cannot be made from what is known."""
    username = str(user.username or "").strip()
    if "\\" in username:
        username = username.split("\\", 1)[1]
    if settings.login_format == "email":
        return normalize_smtp(user.email)
    if not username or any(c.isspace() for c in username):
        return ""
    if settings.login_format == "upn":
        if "@" in username:
            return username.lower()
        suffix = settings.upn_suffix or defaults.dns_domain
        return f"{username}@{suffix}" if suffix else ""
    domain = settings.netbios_domain or defaults.netbios_domain
    if "@" in username:
        username = username.split("@", 1)[0]
    return f"{domain}\\{username}" if domain and username else ""


# --- who may connect ------------------------------------------------------------------------------------------

EligibilityReason = Literal["", "feature_off", "not_configured", "not_ad", "no_email", "not_permitted", "chat_off"]

_REASON_MESSAGES: dict[str, str] = {
    "feature_off": "Exchange mail is not turned on for this organisation.",
    "not_configured": "Exchange mail is not set up yet. Ask your administrator.",
    "not_ad": "Only accounts that sign in with Active Directory can connect an Exchange mailbox.",
    "no_email": "Your account has no email address in the directory, so no mailbox can be matched to it.",
    "not_permitted": "Your administrator has not allowed you to connect a mailbox.",
    "chat_off": "Mail works inside the Chat, which your account cannot use.",
}


@dataclass(frozen=True)
class Eligibility:
    allowed: bool
    reason: EligibilityReason = ""

    @property
    def message(self) -> str:
        return _REASON_MESSAGES.get(self.reason, "")


async def eligibility(db: AsyncSession, user: User, settings: ExchangeSettings | None = None) -> Eligibility:
    """Whether this account may connect (and keep using) a mailbox, and if not, why - the first reason only."""
    settings = settings or await load_settings(db)
    if not settings.enabled:
        return Eligibility(False, "feature_off")
    if not settings.configured:
        return Eligibility(False, "not_configured")
    if (user.auth_provider or "local") != "ldap":
        return Eligibility(False, "not_ad")
    if not normalize_smtp(user.email):
        return Eligibility(False, "no_email")
    if user.deleted_at is not None or not bool(user.is_active):
        return Eligibility(False, "not_permitted")
    from app.services.chat_tool_access_service import permitted_tool_keys
    from app.services.resource_access_service import resolve_resource_access_subject

    subject = await resolve_resource_access_subject(db, user_id=int(user.id))
    if TOOL_KEY not in await permitted_tool_keys(db, subject, keys=[TOOL_KEY]):
        return Eligibility(False, "not_permitted")
    from app.services.feature_access_service import feature_enabled

    if not await feature_enabled(db, user, "chat"):
        return Eligibility(False, "chat_off")
    return Eligibility(True)


# --- connections ----------------------------------------------------------------------------------------------


async def get_connection(db: AsyncSession, user_id: int) -> MailConnection | None:
    return (await db.execute(select(MailConnection).where(MailConnection.user_id == user_id))).scalars().first()


async def list_mailboxes(db: AsyncSession, connection_id: int) -> list[MailConnectionMailbox]:
    """The connection's mailboxes, its own first, then by address."""
    rows = (
        (await db.execute(select(MailConnectionMailbox).where(MailConnectionMailbox.connection_id == connection_id)))
        .scalars()
        .all()
    )
    return sorted(rows, key=lambda row: (row.kind != "own", str(row.smtp)))


def encrypt_password(password: str) -> str:
    """The password as stored. Refuses text that is already one of this deployment's tokens (a copied row)."""
    from app.services.secret_crypto import encrypt_typed_secret, is_own_ciphertext

    if not password or len(password) > 256:
        raise MailError("invalid_password", "Type your password (up to 256 characters).", 422)
    if is_own_ciphertext(password.strip()):
        raise MailError("invalid_password", "That is not a password.", 422)
    return encrypt_typed_secret(password)


def connection_password(connection: MailConnection) -> str:
    """The stored password, decrypted; ``""`` when it cannot be (a changed encryption key)."""
    from app.services.secret_crypto import decrypt_secret

    try:
        return decrypt_secret(str(connection.secret_encrypted or "")) or ""
    except ValueError:
        return ""


def ews_config(settings: ExchangeSettings, login: str, password: str) -> EwsConfig:
    return EwsConfig(
        ews_url=settings.ews_endpoint(),
        login=login,
        password=password,
        autodiscover_url=settings.autodiscover_endpoint(),
        verify_tls=settings.verify_tls,
        ca_bundle_pem=settings.ca_bundle_pem,
        timeout_s=settings.timeout_s,
    )


@dataclass(frozen=True)
class MailAccess:
    """What one person's turn, request or check may use of their mailbox, right now."""

    user_id: int
    connection_id: int
    config: EwsConfig
    own_smtp: str
    #: The mailboxes the chat may name: enabled ones, the own mailbox first.
    mailboxes: tuple[MailboxInfo, ...]
    settings: ExchangeSettings
    #: The mailboxes whose Inbox the needs-action check reads.
    notify_mailboxes: tuple[str, ...] = field(default=())

    def allows(self, smtp: str) -> bool:
        wanted = normalize_smtp(smtp)
        return bool(wanted) and any(box.smtp == wanted for box in self.mailboxes)

    def mailbox(self, smtp: str | None) -> str:
        """The mailbox a call means: the one named when it is allowed, the own mailbox when none is named.

        Raises ``MailError("mailbox_not_allowed")`` for a mailbox that is not on the list.
        """
        if not smtp:
            return self.own_smtp
        wanted = normalize_smtp(smtp)
        if not self.allows(wanted):
            raise MailError(
                "mailbox_not_allowed",
                f"{smtp} is not one of the mailboxes connected for you. Use mail_list_mailboxes to see them.",
                403,
            )
        return wanted


async def usable_access(db: AsyncSession, user: User, settings: ExchangeSettings | None = None) -> MailAccess | None:
    """The person's mailbox access when they may use it now: eligible, connected, and the password readable.

    ``None`` otherwise - never an exception - so a chat turn or a scheduled
    check simply goes without mail.
    """
    settings = settings or await load_settings(db)
    if not (await eligibility(db, user, settings)).allowed:
        return None
    connection = await get_connection(db, int(user.id))
    if connection is None or connection.status != "connected":
        return None
    password = connection_password(connection)
    if not password:
        return None
    rows = await list_mailboxes(db, int(connection.id))
    boxes = tuple(
        MailboxInfo(smtp=str(row.smtp), display_name=str(row.display_name or ""))
        for row in rows
        if row.enabled and (row.kind == "own" or settings.allow_full_access)
    )
    own = normalize_smtp(connection.primary_smtp)
    if not own or not any(box.smtp == own for box in boxes):
        boxes = (MailboxInfo(smtp=own, display_name=str(connection.display_name or "")), *boxes) if own else boxes
    notify = tuple(
        str(row.smtp)
        for row in rows
        if row.enabled and row.notify and (row.kind == "own" or settings.allow_full_access)
    )
    return MailAccess(
        user_id=int(user.id),
        connection_id=int(connection.id),
        config=ews_config(settings, str(connection.login), password),
        own_smtp=own,
        mailboxes=boxes,
        settings=settings,
        notify_mailboxes=notify,
    )


def friendly_error(error: EwsError) -> str:
    """What the person reads about a failure: the client's message, cut to fit the column."""
    return (error.message or "Exchange did not answer as expected.")[:500]


async def record_success(db: AsyncSession, connection: MailConnection) -> None:
    connection.consecutive_failures = 0  # type: ignore[assignment]
    connection.last_error = None  # type: ignore[assignment]
    connection.last_ok_at = _now()  # type: ignore[assignment]
    if connection.status == "error":
        connection.status = "connected"  # type: ignore[assignment]
    await db.flush()


async def record_failure(db: AsyncSession, connection: MailConnection, error: EwsError) -> None:
    """Note a failed call. A refused password stops the connection at once; a wrong mailbox stops it too.

    Anything else (Exchange down, a timeout, throttling) is counted and kept
    as ``last_error``, but leaves the status alone: it will likely pass by
    itself, and a stopped connection would make the person type their
    password again after an outage they had nothing to do with.
    """
    connection.last_error = friendly_error(error)  # type: ignore[assignment]
    connection.consecutive_failures = int(connection.consecutive_failures or 0) + 1  # type: ignore[assignment]
    if error.kind == "auth":
        connection.status = "needs_password"  # type: ignore[assignment]
        connection.last_error = (  # type: ignore[assignment]
            "Exchange did not accept your password. If you changed it, type the new one on Connections."
        )
    elif error.kind == "mailbox_mismatch":
        connection.status = "error"  # type: ignore[assignment]
    await db.flush()


async def record_mailbox_failure(db: AsyncSession, connection_id: int, smtp: str, error: EwsError) -> bool:
    """A Full Access mailbox the login can no longer open drops out (turned off, with the reason).

    Returns whether it dropped out. The own mailbox never does: its failures
    are the connection's (``record_failure``).
    """
    if error.kind not in ("access_denied", "not_found"):
        return False
    row = (
        (
            await db.execute(
                select(MailConnectionMailbox).where(
                    MailConnectionMailbox.connection_id == connection_id,
                    MailConnectionMailbox.smtp == normalize_smtp(smtp),
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None or row.kind == "own":
        return False
    row.enabled = False  # type: ignore[assignment]
    row.notify = False  # type: ignore[assignment]
    row.last_error = friendly_error(error)  # type: ignore[assignment]
    await db.flush()
    return True


async def delete_connection(db: AsyncSession, user_id: int) -> bool:
    """Forget the person's connection and everything the chat made of it (drafts stay in Exchange)."""
    connection = await get_connection(db, user_id)
    await _delete_user_rows(db, user_id)
    if connection is None:
        return False
    await db.execute(delete(MailConnectionMailbox).where(MailConnectionMailbox.connection_id == connection.id))
    await db.execute(delete(MailConnection).where(MailConnection.id == connection.id))
    await db.flush()
    return True


async def _delete_user_rows(db: AsyncSession, user_id: int) -> None:
    await db.execute(delete(MailItemRef).where(MailItemRef.user_id == user_id))
    await db.execute(delete(MailActionItem).where(MailActionItem.user_id == user_id))
    await db.execute(delete(MailDraft).where(MailDraft.user_id == user_id))


async def delete_user_mail(db: AsyncSession, user_id: int) -> None:
    """Everything mail kept for a person, for the purge of their account."""
    await delete_connection(db, user_id)


# --- item refs ------------------------------------------------------------------------------------------------


def ref_value(mailbox: str, item_id: str) -> str:
    """The short name of one email: the same every time for the same email, ``m`` and nine letters or digits."""
    digest = hashlib.sha256(f"{normalize_smtp(mailbox)}|{item_id}".encode()).digest()
    letters = base64.b64encode(digest, altchars=b"Aa").decode("ascii").replace("=", "")
    return "m" + letters[: REF_LENGTH - 1]


def looks_like_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_REF_ALPHABET.match(value.strip()))


async def ref_for(db: AsyncSession, user_id: int, mailbox: str, item_id: str, change_key: str = "") -> str:
    """The ref the model is shown for an email, stored (or refreshed) for ``REF_TTL_DAYS``."""
    ref = ref_value(mailbox, item_id)
    row = (
        (await db.execute(select(MailItemRef).where(MailItemRef.user_id == user_id, MailItemRef.ref == ref)))
        .scalars()
        .first()
    )
    if row is None:
        db.add(
            MailItemRef(
                user_id=user_id,
                ref=ref,
                mailbox_smtp=normalize_smtp(mailbox),
                item_id=item_id,
                change_key=change_key or None,
                created_at=_now(),
            )
        )
    else:
        row.mailbox_smtp = normalize_smtp(mailbox)  # type: ignore[assignment]
        row.item_id = item_id  # type: ignore[assignment]
        row.change_key = change_key or row.change_key  # type: ignore[assignment]
        row.created_at = _now()  # type: ignore[assignment]
    await db.flush()
    return ref


async def resolve_ref(db: AsyncSession, user_id: int, ref: str) -> MailItemRef | None:
    """The email a ref names, when it is this person's and not older than ``REF_TTL_DAYS``."""
    if not looks_like_ref(ref):
        return None
    cutoff = _now() - datetime.timedelta(days=REF_TTL_DAYS)
    return (
        (
            await db.execute(
                select(MailItemRef).where(
                    MailItemRef.user_id == user_id,
                    MailItemRef.ref == ref.strip(),
                    MailItemRef.created_at >= cutoff,
                )
            )
        )
        .scalars()
        .first()
    )


async def prune_refs(db: AsyncSession, *, now: datetime.datetime | None = None) -> int:
    cutoff = (now or _now()) - datetime.timedelta(days=REF_TTL_DAYS)
    result = await db.execute(delete(MailItemRef).where(MailItemRef.created_at < cutoff))
    return int(getattr(result, "rowcount", 0) or 0)


# --- counts for the admin page ----------------------------------------------------------------------------------


async def connection_counts(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(select(MailConnection.status, func.count()).group_by(MailConnection.status))).all()
    counts = {"connected": 0, "needs_password": 0, "error": 0}
    for status, count in rows:
        counts[str(status)] = int(count)
    return counts


# --- running EWS calls ------------------------------------------------------------------------------------------

#: What a call's wait adds to the administrator's EWS timeout (the client's own HTTP timeout ends the thread).
CALL_WAIT_EXTRA_S = 5

_ews_slots: asyncio.Semaphore | None = None
_ews_slots_loop: asyncio.AbstractEventLoop | None = None


def _slots() -> asyncio.Semaphore:
    global _ews_slots, _ews_slots_loop
    loop = asyncio.get_running_loop()
    if _ews_slots is None or _ews_slots_loop is not loop:
        _ews_slots = asyncio.Semaphore(EWS_CONCURRENCY)
        _ews_slots_loop = loop
    return _ews_slots


def call_timeout(settings: ExchangeSettings, steps: int = 1) -> float:
    """How long to wait for a call of ``steps`` client methods: each within the EWS timeout and a little more."""
    return float(max(1, steps) * (settings.timeout_s + CALL_WAIT_EXTRA_S))


def _thread_ended(done: asyncio.Future[Any], slots: asyncio.Semaphore) -> None:
    """A thread whose wait was given up has ended: its slot is free now, and its outcome is dropped."""
    slots.release()
    if not done.cancelled():
        done.exception()


async def call_ews[T](config: EwsConfig, call: Callable[[MailClient], T], *, timeout_s: float) -> T:
    """Make a client for ``config``, run ``call(client)`` and close the client, all in one worker thread.

    At most ``EWS_CONCURRENCY`` of these threads run at once, and a slot is
    held until its thread has really ended. A wait that runs out
    (``timeout_s``: raised as ``EwsError("unreachable")``) or is cancelled
    leaves the thread to finish by itself - the client's own HTTP timeout ends
    it - and frees the slot only then, so a slow Exchange can never have more
    threads at work than the limit, and the client is never closed under a
    call still running in another thread.

    ``call`` gets the client and may call several of its methods (one
    Exchange session); it raises ``EwsError`` as the client does.
    """
    slots = _slots()
    await slots.acquire()

    def work() -> T:
        client = make_client(config)
        try:
            return call(client)
        finally:
            client.close()

    future = asyncio.get_running_loop().run_in_executor(None, contextvars.copy_context().run, work)
    try:
        # Shielded: a wait given up must not mark the thread's future done while the thread still runs.
        return await asyncio.wait_for(asyncio.shield(future), timeout_s)
    except TimeoutError as exc:
        raise EwsError("unreachable", f"Exchange did not answer within {timeout_s:g} seconds.") from exc
    finally:
        if future.done():
            slots.release()
        else:
            future.add_done_callback(functools.partial(_thread_ended, slots=slots))


def make_client(config: EwsConfig) -> MailClient:
    """A client for one login. Tests replace this function with one that gives a fake client."""
    from app.services.exchange_ews_client import EwsClient

    return EwsClient(config)


async def session_features(db: AsyncSession, user: User) -> dict[str, bool]:
    """The two switches the UI needs: Connections in the profile menu, and the mail sign by the chat box.

    ``connections``: the account may connect a mailbox. ``exchange_mail``: it
    has, and the connection works (a connection needing the password shows on
    Connections, not by the chat box).
    """
    try:
        settings = await load_settings(db)
        if not settings.enabled:
            return {"connections": False, "exchange_mail": False}
        allowed = (await eligibility(db, user, settings)).allowed
        connection = await get_connection(db, int(user.id)) if allowed else None
    except Exception:  # noqa: BLE001 -- the session must load even if this check cannot be made
        logger.exception("Could not decide the Exchange mail switches for user %s", getattr(user, "id", None))
        return {"connections": False, "exchange_mail": False}
    return {"connections": allowed, "exchange_mail": connection is not None and connection.status == "connected"}
