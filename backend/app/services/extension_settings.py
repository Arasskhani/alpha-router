"""What an administrator decides about the browser extension.

Kept as one JSON document in ``system_settings`` (``extension.settings``):

- ``site_access``: ``per_site`` (Chrome asks the first time a site is used) or
  ``all_sites`` (granted at install, which a Group Policy install does
  silently). It changes the extension's permissions, so it changes the
  package, and policy-installed copies update to the new permissions.
- ``allowed_sites`` / ``blocked_sites``: host patterns (``example.com``, or
  ``*.example.com`` for the domain and all its subdomains, or an IPv6 literal
  such as ``[fd00::1]``). Blocked always
  wins; a non-empty allowed list means every other site is off limits. The extension checks them before it reads
  or does anything, and the server checks the sites it is told about.
- ``page_content_models`` / ``agent_models``: ``model::<id>`` lists (empty
  means any model the user may use) for turns that carry page content, and
  for the agent.
- ``agent_max_steps``, ``agent_auto_mode`` and ``agent_review_model``: the
  agent's limits. Auto mode (acting without asking on allowed sites) needs a
  review model, which checks every action against the user's request. It
  reads what the agent found on pages, so when page content is kept to some
  models, the review model has to be one of them.

Who may use the extension and its agent at all is the Chat Tools ACL
(``browser_extension``, ``browser_agent``), not this document.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import logging
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, cast

from urllib.parse import urlsplit

import idna
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.services.extension_package import SITE_ACCESS_MODES, SITE_ACCESS_PER_SITE
from app.services.list_bounds import ADMIN_LIST_HARD_CAP
from app.services.model_capabilities import model_media_flags, supports_vision
from app.services.model_tool_compatibility_service import is_auto_router_model_id
from app.services.system_default_models import model_supports_text_chat

logger = logging.getLogger(__name__)

SETTINGS_KEY = "extension.settings"

DEFAULT_MAX_STEPS = 25
MIN_MAX_STEPS = 5
MAX_MAX_STEPS = 100
MAX_SITE_PATTERNS = 200
MAX_MODEL_REFS = 500
#: A run's time limit, in minutes.
DEFAULT_MAX_MINUTES = 20
MIN_MAX_MINUTES = 1
MAX_MAX_MINUTES = 180
#: Tabs one run may open.
DEFAULT_MAX_TABS = 10
MIN_MAX_TABS = 1
MAX_MAX_TABS = 50
#: Runs one person may start in a day (None: no limit).
MAX_RUNS_PER_DAY = 1000
#: A screenshot's longest side, in pixels, and how many of the latest stay in the conversation.
DEFAULT_SCREENSHOT_SIDE = 1280
MIN_SCREENSHOT_SIDE = 800
MAX_SCREENSHOT_SIDE = 1600
DEFAULT_SCREENSHOTS_KEPT = 3
MIN_SCREENSHOTS_KEPT = 1
#: The images one agent step may carry (MAX_AGENT_IMAGES in app/api/chat.py): keeping more would refuse every step.
MAX_SCREENSHOTS_KEPT = 4
#: The manifest's minimum_chrome_version: the template's own, and how far an admin may raise it.
TEMPLATE_BROWSER_VERSION = 116
MAX_BROWSER_VERSION = 999
MAX_INTERNAL_CONNECTIONS = 500

#: The agent's modes: Ask (every action waits for the person), Plan (a plan is
#: approved once, then the agent works the plan's sites), Auto (a review model
#: checks each action).
AGENT_MODES = ("ask", "plan", "auto")
DEFAULT_AGENT_MODE = "plan"

#: A host label as browsers accept it: underscores included (intranet hosts have them).
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9_-]{1,63}(?<!-)$")
_MODEL_REF_RE = re.compile(r"^model::(\d{1,10})$")
#: Model ids are INTEGER columns; a larger number fails in PostgreSQL itself.
_MAX_MODEL_ID = 2**31 - 1

#: Why a site is off limits, as the API reports it.
SITE_BLOCKED = "site_blocked"
SITE_NOT_ALLOWED = "site_not_allowed"


class ExtensionSettingsError(ValueError):
    """A setting an administrator entered cannot be saved; the message says which and why."""


#: The sensitive cases an administrator may relax, so each counts as a plain
#: action instead of asking. Anything not here is fixed (authorizations,
#: personal data, the never list). ``relaxed_approvals`` holds the ones turned off.
APPROVAL_KEYS = ("send", "submit", "delete", "leave_sites", "downloads", "uploads", "dialogs")


@dataclass(frozen=True)
class ExtensionSettings:
    site_access: str = SITE_ACCESS_PER_SITE
    allowed_sites: tuple[str, ...] = field(default_factory=tuple)
    blocked_sites: tuple[str, ...] = field(default_factory=tuple)
    page_content_models: tuple[str, ...] = field(default_factory=tuple)
    agent_models: tuple[str, ...] = field(default_factory=tuple)
    #: The model the Agent tab starts with (``model::<id>``); None: the best that passed the probe.
    agent_recommended_model: str | None = None
    agent_max_steps: int = DEFAULT_MAX_STEPS
    agent_auto_mode: bool = False
    agent_review_model: str | None = None
    #: Full control: the agent drives the page with trusted input (a real mouse
    #: and keyboard) through chrome.debugger, and sees it in screenshots. It adds
    #: the ``debugger`` permission to the package, so a copy updates to get it.
    full_control: bool = False
    #: The extension for the whole organisation. Off refuses new connections and
    #: stops the extension offering anything; the Chat Tools ACL still gates who.
    enabled: bool = True
    #: Sites the agent may read but never act on.
    read_only_sites: tuple[str, ...] = field(default_factory=tuple)
    #: Sites where the agent never acts (payment gateways, banks - whatever the admin lists).
    protected_sites: tuple[str, ...] = field(default_factory=tuple)
    #: The organisation's own sites, whose content and screenshots are kept to internal models.
    internal_sites: tuple[str, ...] = field(default_factory=tuple)
    #: Models allowed to see internal sites' content and screenshots (empty: any model the user may use).
    internal_models: tuple[str, ...] = field(default_factory=tuple)
    #: Models allowed to see screenshots at all (empty: any). A model not here works from text and references.
    screenshot_models: tuple[str, ...] = field(default_factory=tuple)
    #: Which sensitive cases the admin relaxed to plain actions (a subset of APPROVAL_KEYS).
    relaxed_approvals: tuple[str, ...] = field(default_factory=tuple)
    #: An emergency stop: every agent run that began before this moment ends at its
    #: next step. ISO-8601 UTC, or None when no stop has been asked for.
    stop_runs_before: str | None = None
    #: The agent works only from a browser that runs the package this server hands out now.
    require_newest_package: bool = False
    #: The manifest's minimum_chrome_version, when raised above the template's.
    min_browser_version: int = TEMPLATE_BROWSER_VERSION
    #: Connections inside the organisation (their ids): their models may see internal sites.
    internal_connections: tuple[int, ...] = field(default_factory=tuple)
    #: Whether screenshots of sites that are not internal may go to models outside the organisation.
    external_screenshots: bool = True
    #: Plan mode offered to people (Ask is always offered; Auto is ``agent_auto_mode``).
    plan_mode: bool = True
    #: The mode a run starts in unless the person chose another.
    agent_default_mode: str = DEFAULT_AGENT_MODE
    #: A run's limits: minutes, tabs it may open, and runs per person per day (None: no limit).
    agent_max_minutes: int = DEFAULT_MAX_MINUTES
    agent_max_tabs: int = DEFAULT_MAX_TABS
    agent_runs_per_day: int | None = None
    #: Screenshots: the longest side, and how many of the latest stay in the conversation.
    screenshot_max_side: int = DEFAULT_SCREENSHOT_SIDE
    screenshots_kept: int = DEFAULT_SCREENSHOTS_KEPT
    #: Under full control, a fresh screenshot at the end of each step that changed the page.
    screenshot_after_action: bool = True
    #: Finished runs saved to the person's chat history; and whether a run may be private (not saved).
    save_runs: bool = True
    private_runs: bool = True

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "allowed_sites",
            "blocked_sites",
            "page_content_models",
            "agent_models",
            "read_only_sites",
            "protected_sites",
            "internal_sites",
            "internal_models",
            "screenshot_models",
            "relaxed_approvals",
            "internal_connections",
        ):
            data[key] = list(data[key])
        return data

    def modes_json(self) -> list[str]:
        """The modes people may choose, in the order the panel offers them."""
        return [
            mode
            for mode in AGENT_MODES
            if mode == "ask" or (mode == "plan" and self.plan_mode) or (mode == "auto" and self.agent_auto_mode)
        ]

    def approvals_json(self) -> dict[str, bool]:
        """Each relaxable case as the extension reads it: ``true`` when it still asks."""
        return {key: key not in self.relaxed_approvals for key in APPROVAL_KEYS}


def _to_ascii(host: str) -> str:
    """The host as a browser's URL.hostname has it: UTS #46, non-transitional (IDNA 2008)."""
    if host.isascii():
        return host
    return idna.encode(host, uts46=True, transitional=False).decode("ascii")


def _ascii_host(host: str) -> str:
    text = (host or "").strip().lower().rstrip(".")
    try:
        return _to_ascii(text)
    except (idna.IDNAError, UnicodeError):
        return text


def _ipv6_literal(text: str) -> str:
    """``[fd00::1]`` as ``URL.hostname`` writes it: brackets, compressed, lower-case."""
    try:
        return f"[{ipaddress.IPv6Address(text[1:-1]).compressed}]"
    except ValueError as exc:
        raise ValueError("not a host name") from exc


def normalize_site_pattern(raw: str) -> str:
    """``example.com``, ``*.example.com`` or ``[fd00::1]``, normalized; raises ValueError otherwise."""
    text = (raw or "").strip().lower().rstrip(".")
    if not text:
        raise ValueError("empty")
    if text.startswith("[") and text.endswith("]"):
        return _ipv6_literal(text)
    if "://" in text or "/" in text or ":" in text or "@" in text or " " in text:
        raise ValueError("a host name only: no scheme, port or path")
    wildcard = text.startswith("*.")
    host = text[2:] if wildcard else text
    if "*" in host:
        raise ValueError("a wildcard is only allowed as the first label, as in *.example.com")
    try:
        ascii_host = _to_ascii(host)
    except (idna.IDNAError, UnicodeError) as exc:
        raise ValueError("not a valid host name") from exc
    # One label is fine: intranet hosts ("portal") are as real as any other.
    if not all(_LABEL_RE.match(label) for label in ascii_host.split(".")):
        raise ValueError("not a valid host name")
    return f"*.{ascii_host}" if wildcard else ascii_host


def normalize_page_host(raw: str) -> str:
    """A page's host as the extension reports it (``URL.hostname``), checked; raises ValueError.

    The same hosts a site pattern can name, without the wildcard, so every
    host a page can come from can also be blocked.
    """
    text = (raw or "").strip().lower().rstrip(".")
    if text.startswith("[") and text.endswith("]"):
        return _ipv6_literal(text)
    if not text or len(text) > 253:
        raise ValueError("not a host name")
    try:
        ascii_host = _to_ascii(text)
    except (idna.IDNAError, UnicodeError) as exc:
        raise ValueError("not a host name") from exc
    if len(ascii_host) > 253 or not all(_LABEL_RE.match(label) for label in ascii_host.split(".")):
        raise ValueError("not a host name")
    return ascii_host


def host_matches(host: str, pattern: str) -> bool:
    """``*.example.com`` covers example.com and every subdomain, as in Chrome's match patterns.

    That is what an admin who blocks ``*.bank.example`` expects: the bank's own
    site blocked too, not only its subdomains.
    """
    host = _ascii_host(host)
    if pattern.startswith("*."):
        return host == pattern[2:] or host.endswith(pattern[1:])
    return host == pattern


def site_refusal(host: str, settings: ExtensionSettings, *, server_host: str | None = None) -> str | None:
    """None when the site may be read and acted on; otherwise why not.

    ``server_host`` is this Alpharouter's own host: an allow list never shuts
    the user out of asking about Alpharouter itself (the agent never acts on it,
    which the extension enforces). An explicit block still applies.
    """
    if any(host_matches(host, pattern) for pattern in settings.blocked_sites):
        return SITE_BLOCKED
    if server_host and _ascii_host(host) == _ascii_host(server_host):
        return None
    if settings.allowed_sites and not any(host_matches(host, pattern) for pattern in settings.allowed_sites):
        return SITE_NOT_ALLOWED
    return None


def page_content_allowed(settings: ExtensionSettings, model_ref: str | None) -> bool:
    """Whether page content may go to the model ``model_ref`` (``model::<id>``) names.

    Any model the user may use when the administrator lists none; otherwise
    only a listed one, so a model that cannot be named is never allowed.
    """
    return not settings.page_content_models or (model_ref is not None and model_ref in settings.page_content_models)


def internal_site(settings: ExtensionSettings, host: str | None) -> bool:
    """Whether ``host`` is one of the organisation's own sites."""
    return bool(host) and any(host_matches(host or "", pattern) for pattern in settings.internal_sites)


def inside_organisation(settings: ExtensionSettings, model_ref: str | None, connection_id: int | None) -> bool:
    """Whether the model may see the organisation's own data: on a connection inside
    the organisation, or on the internal-models list. With neither list set, any model.
    A model that cannot be named is never allowed once a list is set.
    """
    if not settings.internal_models and not settings.internal_connections:
        return True
    if connection_id is not None and int(connection_id) in settings.internal_connections:
        return True
    return model_ref is not None and model_ref in settings.internal_models


def screenshot_allowed(
    settings: ExtensionSettings, model_ref: str | None, host: str | None, *, connection_id: int | None = None
) -> bool:
    """Whether a screenshot of ``host`` may go to the model ``model_ref`` names.

    Three gates, all from the admin's data-location settings: a model must be
    on the screenshot list (empty: any); a screenshot of an internal site must
    go to a model inside the organisation (``inside_organisation``); and, when
    screenshots of other sites may not leave the organisation, so must any
    screenshot at all. ``host`` None (no web page) is treated as not internal.
    """
    if settings.screenshot_models and (model_ref is None or model_ref not in settings.screenshot_models):
        return False
    if internal_site(settings, host) or not settings.external_screenshots:
        return inside_organisation(settings, model_ref, connection_id)
    return True


async def inside_model_refs(db: AsyncSession, settings: ExtensionSettings) -> set[str] | None:
    """The models inside the organisation, as ``model::<id>`` refs: the internal list
    plus every model on a connection inside the organisation. None when neither list
    is set (any model).
    """
    if not settings.internal_models and not settings.internal_connections:
        return None
    refs = set(settings.internal_models)
    if settings.internal_connections:
        rows = await db.execute(select(AIModel.id).where(AIModel.connection_id.in_(settings.internal_connections)))
        refs.update(f"model::{int(model_id)}" for model_id in rows.scalars().all())
    return refs


async def data_policy(db: AsyncSession, settings: ExtensionSettings) -> dict[str, Any]:
    """The data-location rules as the extension applies them, with the lists made effective:
    which models may see internal sites, and which may see screenshots at all (null: any).
    """
    inside = await inside_model_refs(db, settings)
    screenshots: set[str] | None = set(settings.screenshot_models) or None
    # Screenshots that may not leave the organisation go only to the models inside it.
    if not settings.external_screenshots and inside is not None:
        screenshots = inside if screenshots is None else screenshots & inside
    return {
        "internal_sites": list(settings.internal_sites),
        "internal_models": sorted(inside) if inside is not None else None,
        "screenshot_models": sorted(screenshots) if screenshots is not None else None,
        "external_screenshots": settings.external_screenshots,
    }


def raised_browser_version(settings: ExtensionSettings, template: dict[str, Any] | None = None) -> int | None:
    """The minimum browser version to put in the manifest, or None to leave the template's."""
    base = TEMPLATE_BROWSER_VERSION
    raw = (template or {}).get("minimum_chrome_version")
    if isinstance(raw, str) and raw.split(".")[0].isdigit():
        base = int(raw.split(".")[0])
    return int(settings.min_browser_version) if int(settings.min_browser_version) > base else None


def _timestamp(value: Any) -> str | None:
    """An ISO-8601 UTC moment as stored, or None when it is not one."""
    return value if isinstance(value, str) and parse_timestamp(value) is not None else None


def parse_timestamp(value: str | None) -> datetime.datetime | None:
    """``stop_runs_before`` as a timezone-aware datetime, or None when unset or unreadable."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=datetime.UTC)


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _ints(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        sorted({int(item) for item in value if isinstance(item, int) and not isinstance(item, bool) and item > 0})
    )


def _bounded(value: Any, low: int, high: int, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else default


def _at_most(value: Any, low: int, high: int, default: int) -> int:
    """Like _bounded, but a value above ``high`` - one an earlier version allowed - is kept at ``high``."""
    if isinstance(value, int) and not isinstance(value, bool) and value > high:
        return high
    return _bounded(value, low, high, default)


def parse_settings(raw: str | None) -> ExtensionSettings:
    """Settings as stored. A value this code did not write falls back to the default, field by field."""
    if not raw:
        return ExtensionSettings()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Ignoring unreadable %s; using defaults", SETTINGS_KEY)
        return ExtensionSettings()
    if not isinstance(data, dict):
        return ExtensionSettings()
    defaults = ExtensionSettings()
    site_access = data.get("site_access")
    max_steps = data.get("agent_max_steps")
    review = data.get("agent_review_model")
    recommended = data.get("agent_recommended_model")
    return ExtensionSettings(
        site_access=site_access if site_access in SITE_ACCESS_MODES else defaults.site_access,
        allowed_sites=_strings(data.get("allowed_sites")),
        blocked_sites=_strings(data.get("blocked_sites")),
        page_content_models=_strings(data.get("page_content_models")),
        agent_models=_strings(data.get("agent_models")),
        agent_recommended_model=(
            recommended if isinstance(recommended, str) and _MODEL_REF_RE.match(recommended) else None
        ),
        agent_max_steps=(
            max_steps
            if isinstance(max_steps, int) and MIN_MAX_STEPS <= max_steps <= MAX_MAX_STEPS
            else defaults.agent_max_steps
        ),
        agent_auto_mode=bool(data.get("agent_auto_mode")) and isinstance(review, str) and bool(review),
        agent_review_model=review if isinstance(review, str) and review else None,
        full_control=bool(data.get("full_control")),
        # A document written before this field existed has the extension on, as it was.
        enabled=bool(data.get("enabled", True)),
        read_only_sites=_strings(data.get("read_only_sites")),
        protected_sites=_strings(data.get("protected_sites")),
        internal_sites=_strings(data.get("internal_sites")),
        internal_models=_strings(data.get("internal_models")),
        screenshot_models=_strings(data.get("screenshot_models")),
        relaxed_approvals=tuple(key for key in _strings(data.get("relaxed_approvals")) if key in APPROVAL_KEYS),
        stop_runs_before=_timestamp(data.get("stop_runs_before")),
        require_newest_package=bool(data.get("require_newest_package")),
        min_browser_version=_bounded(
            data.get("min_browser_version"), TEMPLATE_BROWSER_VERSION, MAX_BROWSER_VERSION, defaults.min_browser_version
        ),
        internal_connections=_ints(data.get("internal_connections")),
        external_screenshots=bool(data.get("external_screenshots", True)),
        plan_mode=bool(data.get("plan_mode", True)),
        agent_default_mode=(
            data["agent_default_mode"] if data.get("agent_default_mode") in AGENT_MODES else defaults.agent_default_mode
        ),
        agent_max_minutes=_bounded(
            data.get("agent_max_minutes"), MIN_MAX_MINUTES, MAX_MAX_MINUTES, defaults.agent_max_minutes
        ),
        agent_max_tabs=_bounded(data.get("agent_max_tabs"), MIN_MAX_TABS, MAX_MAX_TABS, defaults.agent_max_tabs),
        agent_runs_per_day=(
            data["agent_runs_per_day"]
            if isinstance(data.get("agent_runs_per_day"), int) and 1 <= data["agent_runs_per_day"] <= MAX_RUNS_PER_DAY
            else None
        ),
        screenshot_max_side=_bounded(
            data.get("screenshot_max_side"), MIN_SCREENSHOT_SIDE, MAX_SCREENSHOT_SIDE, defaults.screenshot_max_side
        ),
        screenshots_kept=_at_most(
            data.get("screenshots_kept"), MIN_SCREENSHOTS_KEPT, MAX_SCREENSHOTS_KEPT, defaults.screenshots_kept
        ),
        screenshot_after_action=bool(data.get("screenshot_after_action", True)),
        save_runs=bool(data.get("save_runs", True)),
        private_runs=bool(data.get("private_runs", True)),
    )


#: A manifest permission an admin toggle adds to the package (see build_manifest).
PERMISSION_DEBUGGER = "debugger"


def extra_package_permissions(settings: ExtensionSettings) -> tuple[str, ...]:
    """The manifest permissions the current settings add beyond the template's.

    Full control needs ``debugger`` (trusted input and screenshots). Later
    releases add downloads, notifications and alarms here for their features.
    """
    extras: list[str] = []
    if settings.full_control:
        extras.append(PERMISSION_DEBUGGER)
    return tuple(extras)


async def load_extension_settings(db: AsyncSession) -> ExtensionSettings:
    row = await db.get(SystemSetting, SETTINGS_KEY)
    return parse_settings(cast("str | None", row.value) if row is not None else None)


def _site_list(label: str, values: list[str]) -> tuple[str, ...]:
    if len(values) > MAX_SITE_PATTERNS:
        raise ExtensionSettingsError(f"{label}: at most {MAX_SITE_PATTERNS} sites.")
    out: set[str] = set()
    for value in values:
        if not (value or "").strip():
            continue
        try:
            out.add(normalize_site_pattern(value))
        except ValueError as exc:
            raise ExtensionSettingsError(f"{label}: {value.strip()!r} is not usable ({exc}).") from exc
    return tuple(sorted(out))


async def _model_list(
    db: AsyncSession, label: str, values: list[str], *, enabled_only: bool = False
) -> tuple[str, ...]:
    if len(values) > MAX_MODEL_REFS:
        raise ExtensionSettingsError(f"{label}: at most {MAX_MODEL_REFS} models.")
    ids: set[int] = set()
    for value in values:
        match = _MODEL_REF_RE.match((value or "").strip())
        if match is None or not 1 <= int(match.group(1)) <= _MAX_MODEL_ID:
            raise ExtensionSettingsError(f"{label}: {value!r} is not a model.")
        ids.add(int(match.group(1)))
    if not ids:
        return ()
    query = select(AIModel.id).where(AIModel.id.in_(ids))
    if enabled_only:
        query = query.where(AIModel.is_enabled == True)  # noqa: E712
    found = set((await db.execute(query)).scalars().all())
    missing = sorted(ids - {int(i) for i in found})
    if missing:
        state = "is not enabled or does not exist" if enabled_only else "does not exist"
        raise ExtensionSettingsError(f"{label}: model {missing[0]} {state}.")
    return tuple(f"model::{i}" for i in sorted(ids))


async def _auto_router_ids(db: AsyncSession, refs: tuple[str, ...]) -> list[int]:
    """The ids, among model::<id> refs, of models that are Auto Router."""
    ids = {int(ref.split("::")[1]) for ref in refs}
    if not ids:
        return []
    rows = (await db.execute(select(AIModel.id, AIModel.external_id).where(AIModel.id.in_(ids)))).all()
    return sorted(int(row.id) for row in rows if is_auto_router_model_id(str(row.external_id or "")))


async def _connection_list(db: AsyncSession, values: list[int]) -> tuple[int, ...]:
    """Connection ids, each of which must exist; raises ExtensionSettingsError."""
    if len(values) > MAX_INTERNAL_CONNECTIONS:
        raise ExtensionSettingsError(f"Connections inside the organisation: at most {MAX_INTERNAL_CONNECTIONS}.")
    ids: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_MODEL_ID:
            raise ExtensionSettingsError(f"Connections inside the organisation: {value!r} is not a connection.")
        ids.add(value)
    if not ids:
        return ()
    found = set((await db.execute(select(Connection.id).where(Connection.id.in_(ids)))).scalars().all())
    missing = sorted(ids - {int(i) for i in found})
    if missing:
        raise ExtensionSettingsError(f"Connections inside the organisation: connection {missing[0]} does not exist.")
    return tuple(sorted(ids))


def _reads_images(row: AIModel) -> bool:
    external_id = str(row.external_id or "")
    pricing_raw = cast("str | None", row.pricing_raw)
    provider_type = cast("str | None", row.provider_type)
    media = model_media_flags(
        external_id=external_id,
        is_image_model=bool(row.is_image_model),
        is_video_model=bool(getattr(row, "is_video_model", False)),
        pricing_raw=pricing_raw,
        provider_type=provider_type,
    )
    return supports_vision(
        external_id=external_id,
        is_image_model=media["is_image_model"],
        pricing_raw=pricing_raw,
        provider_type=provider_type,
    )


#: What the settings page says about a model it lists.
MODEL_OK = "ok"
MODEL_DISABLED = "disabled"
MODEL_NOT_CHAT = "not_chat"
MODEL_DELETED = "deleted"


def _named_model_ids(settings: ExtensionSettings) -> set[int]:
    refs = (
        *settings.page_content_models,
        *settings.agent_models,
        settings.agent_recommended_model or "",
        *settings.internal_models,
        *settings.screenshot_models,
        settings.agent_review_model or "",
    )
    return {int(match.group(1)) for ref in refs if (match := _MODEL_REF_RE.match(ref))}


async def model_choices(db: AsyncSession, settings: ExtensionSettings) -> list[dict[str, Any]]:
    """The models the settings page offers, and what it shows for those the settings name.

    The choices are the enabled models that chat. A model the settings still
    name that is not one of them any more - turned off, no longer a chat model,
    deleted - is listed with its state, so the page can show it and let it be
    removed: a restriction to a model nobody can see still restricts. Read with
    the settings, under the Chat Tools permission, so the page needs no other
    admin menu.
    """
    named = _named_model_ids(settings)
    enabled = (
        (await db.execute(select(AIModel).where(AIModel.is_enabled == True).limit(ADMIN_LIST_HARD_CAP)))  # noqa: E712
        .scalars()
        .all()
    )
    by_id = {int(row.id): row for row in enabled}
    if named - set(by_id):
        rows = (await db.execute(select(AIModel).where(AIModel.id.in_(named - set(by_id))))).scalars().all()
        by_id.update({int(row.id): row for row in rows})
    choices: list[dict[str, Any]] = []
    for model_id, row in by_id.items():
        if not row.is_enabled:
            state = MODEL_DISABLED
        elif not model_supports_text_chat(row):
            state = MODEL_NOT_CHAT
        else:
            state = MODEL_OK
        if state != MODEL_OK and model_id not in named:
            continue
        choices.append(
            {
                "ref": f"model::{model_id}",
                "label": str(row.display_name or row.external_id or f"Model {model_id}"),
                "provider": row.provider_type,
                "state": state,
                "connection_id": int(row.connection_id) if row.connection_id is not None else None,
                # Whether it reads images: only such a model can see screenshots, or be probed.
                "vision": _reads_images(row),
                # Auto Router is never the browser agent's: the page does not offer it there.
                "auto_router": is_auto_router_model_id(str(row.external_id or "")),
            }
        )
    choices.extend(
        {
            "ref": f"model::{model_id}",
            "label": f"Model {model_id}",
            "provider": None,
            "state": MODEL_DELETED,
            "connection_id": None,
            "vision": False,
        }
        for model_id in sorted(named - set(by_id))
    )
    choices.sort(key=lambda choice: (choice["label"].casefold(), choice["ref"]))
    return choices


def looks_internal(base_url: str | None) -> bool:
    """Whether a connection's address looks like the organisation's own: a private
    or loopback address, localhost, or a single-label intranet name. A suggestion
    for the administrator to confirm, never a decision.
    """
    try:
        host = (urlsplit((base_url or "").strip()).hostname or "").strip("[]").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host
    return ip.is_private or ip.is_loopback or ip.is_link_local


async def connection_choices(db: AsyncSession, settings: ExtensionSettings) -> list[dict[str, Any]]:
    """The connections the settings page offers to tick as inside the organisation.

    Every connection, with what it is called, where it points, and whether its
    address looks internal; a ticked one that no longer exists is listed too,
    so it can be seen and removed.
    """
    rows = (
        (await db.execute(select(Connection).order_by(Connection.name, Connection.id).limit(ADMIN_LIST_HARD_CAP)))
        .scalars()
        .all()
    )
    choices: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        seen.add(int(row.id))
        host = ""
        try:
            host = urlsplit(str(row.base_url or "")).hostname or ""
        except ValueError:
            host = ""
        choices.append(
            {
                "id": int(row.id),
                "name": str(row.name),
                "provider": row.provider_type,
                "host": host,
                "active": bool(row.is_active),
                "looks_internal": looks_internal(cast("str | None", row.base_url)),
                "state": "ok",
            }
        )
    choices.extend(
        {
            "id": cid,
            "name": f"Connection {cid}",
            "provider": None,
            "host": "",
            "active": False,
            "looks_internal": False,
            "state": "deleted",
        }
        for cid in settings.internal_connections
        if cid not in seen
    )
    return choices


async def validated_update(
    db: AsyncSession,
    current: ExtensionSettings,
    *,
    site_access: str,
    allowed_sites: list[str],
    blocked_sites: list[str],
    page_content_models: list[str],
    agent_models: list[str],
    agent_max_steps: int,
    agent_auto_mode: bool,
    agent_review_model: str | None,
    agent_recommended_model: str | None = None,
    full_control: bool = False,
    enabled: bool = True,
    read_only_sites: list[str] | None = None,
    protected_sites: list[str] | None = None,
    internal_sites: list[str] | None = None,
    internal_models: list[str] | None = None,
    screenshot_models: list[str] | None = None,
    relaxed_approvals: list[str] | None = None,
    require_newest_package: bool = False,
    min_browser_version: int = TEMPLATE_BROWSER_VERSION,
    internal_connections: list[int] | None = None,
    external_screenshots: bool = True,
    plan_mode: bool = True,
    agent_default_mode: str = DEFAULT_AGENT_MODE,
    agent_max_minutes: int = DEFAULT_MAX_MINUTES,
    agent_max_tabs: int = DEFAULT_MAX_TABS,
    agent_runs_per_day: int | None = None,
    screenshot_max_side: int = DEFAULT_SCREENSHOT_SIDE,
    screenshots_kept: int = DEFAULT_SCREENSHOTS_KEPT,
    screenshot_after_action: bool = True,
    save_runs: bool = True,
    private_runs: bool = True,
) -> ExtensionSettings:
    """The settings an administrator asked for, checked; raises ExtensionSettingsError."""
    if site_access not in SITE_ACCESS_MODES:
        raise ExtensionSettingsError("Site access must be per site or all sites.")
    if not MIN_MAX_STEPS <= int(agent_max_steps) <= MAX_MAX_STEPS:
        raise ExtensionSettingsError(f"Agent steps must be between {MIN_MAX_STEPS} and {MAX_MAX_STEPS}.")
    if not MIN_MAX_MINUTES <= int(agent_max_minutes) <= MAX_MAX_MINUTES:
        raise ExtensionSettingsError(f"Run time must be between {MIN_MAX_MINUTES} and {MAX_MAX_MINUTES} minutes.")
    if not MIN_MAX_TABS <= int(agent_max_tabs) <= MAX_MAX_TABS:
        raise ExtensionSettingsError(f"Tabs per run must be between {MIN_MAX_TABS} and {MAX_MAX_TABS}.")
    if agent_runs_per_day is not None and not 1 <= int(agent_runs_per_day) <= MAX_RUNS_PER_DAY:
        raise ExtensionSettingsError(f"Runs per person per day must be between 1 and {MAX_RUNS_PER_DAY}, or empty.")
    if not MIN_SCREENSHOT_SIDE <= int(screenshot_max_side) <= MAX_SCREENSHOT_SIDE:
        raise ExtensionSettingsError(
            f"A screenshot's longest side must be between {MIN_SCREENSHOT_SIDE} and {MAX_SCREENSHOT_SIDE} pixels."
        )
    if not MIN_SCREENSHOTS_KEPT <= int(screenshots_kept) <= MAX_SCREENSHOTS_KEPT:
        raise ExtensionSettingsError(
            f"Screenshots kept must be between {MIN_SCREENSHOTS_KEPT} and {MAX_SCREENSHOTS_KEPT}."
        )
    if not TEMPLATE_BROWSER_VERSION <= int(min_browser_version) <= MAX_BROWSER_VERSION:
        raise ExtensionSettingsError(
            f"The minimum browser version must be between {TEMPLATE_BROWSER_VERSION} and {MAX_BROWSER_VERSION}."
        )
    if agent_default_mode not in AGENT_MODES:
        raise ExtensionSettingsError("The default mode must be ask, plan or auto.")
    if agent_default_mode == "plan" and not plan_mode:
        raise ExtensionSettingsError("Plan cannot be the default mode while Plan mode is turned off.")
    if agent_default_mode == "auto" and not agent_auto_mode:
        raise ExtensionSettingsError("Auto cannot be the default mode while Auto mode is turned off.")
    recommended = (agent_recommended_model or "").strip() or None
    recommended_list = await _model_list(
        db, "Recommended agent model", [recommended] if recommended else [], enabled_only=True
    )
    agent_list = await _model_list(db, "Agent models", agent_models)
    if recommended_list and agent_list and recommended_list[0] not in agent_list:
        raise ExtensionSettingsError("The recommended agent model must be one of the agent models.")
    content_list = await _model_list(db, "Models for page content", page_content_models)
    # Checked when these lists change: a row saved before the rule must not keep an administrator from saving
    # anything else - turning the extension off above all.
    models_changed = (
        agent_list != current.agent_models
        or (recommended_list[0] if recommended_list else None) != current.agent_recommended_model
        or content_list != current.page_content_models
    )
    # Every agent step on Auto Router is refused (it would change models between steps): it is not listed either.
    routed = await _auto_router_ids(db, (*agent_list, *recommended_list)) if models_changed else []
    if routed:
        raise ExtensionSettingsError(
            f"Agent models: model {routed[0]} is Auto Router, which picks another model at each step and is never "
            "the browser agent's. Choose a model that passed the browser control probe."
        )
    # The agent sends what it reads to its model: a recommendation the page-content list refuses would never run.
    if models_changed and recommended_list and content_list and recommended_list[0] not in content_list:
        raise ExtensionSettingsError("The recommended agent model must also be one of the models for page content.")
    review = (agent_review_model or "").strip() or None
    # The review model has to answer for every action in Auto mode: it must work today.
    review_list = await _model_list(db, "Review model", [review] if review else [], enabled_only=True)
    if agent_auto_mode and not review_list:
        raise ExtensionSettingsError("Auto mode needs a review model to check each action.")
    bad = sorted(set(relaxed_approvals or []) - set(APPROVAL_KEYS))
    if bad:
        raise ExtensionSettingsError(f"Approvals: {bad[0]!r} is not one that can be relaxed.")
    updated = replace(
        current,
        site_access=site_access,
        allowed_sites=_site_list("Allowed sites", allowed_sites),
        blocked_sites=_site_list("Blocked sites", blocked_sites),
        page_content_models=content_list,
        agent_models=agent_list,
        agent_recommended_model=recommended_list[0] if recommended_list else None,
        agent_max_steps=int(agent_max_steps),
        agent_auto_mode=bool(agent_auto_mode),
        agent_review_model=review_list[0] if review_list else None,
        full_control=bool(full_control),
        enabled=bool(enabled),
        read_only_sites=_site_list("Read-only sites", read_only_sites or []),
        protected_sites=_site_list("Protected sites", protected_sites or []),
        internal_sites=_site_list("Internal sites", internal_sites or []),
        internal_models=await _model_list(db, "Models for internal sites", internal_models or []),
        screenshot_models=await _model_list(db, "Models allowed screenshots", screenshot_models or []),
        relaxed_approvals=tuple(key for key in APPROVAL_KEYS if key in set(relaxed_approvals or [])),
        require_newest_package=bool(require_newest_package),
        min_browser_version=int(min_browser_version),
        internal_connections=await _connection_list(db, internal_connections or []),
        external_screenshots=bool(external_screenshots),
        plan_mode=bool(plan_mode),
        agent_default_mode=agent_default_mode,
        agent_max_minutes=int(agent_max_minutes),
        agent_max_tabs=int(agent_max_tabs),
        agent_runs_per_day=int(agent_runs_per_day) if agent_runs_per_day is not None else None,
        screenshot_max_side=int(screenshot_max_side),
        screenshots_kept=int(screenshots_kept),
        screenshot_after_action=bool(screenshot_after_action),
        save_runs=bool(save_runs),
        private_runs=bool(private_runs),
    )
    # The reviewer reads what the agent found on pages: element names, the text it would type.
    if updated.agent_auto_mode and not page_content_allowed(updated, updated.agent_review_model):
        raise ExtensionSettingsError(
            "Auto mode's review model reads element names and text from pages, so it must be one of "
            "the models for page content. Add it to that list or choose another review model."
        )
    return updated


async def save_extension_settings(db: AsyncSession, settings: ExtensionSettings) -> None:
    """Write the settings; the caller commits (and audits)."""
    value = json.dumps(settings.to_json(), separators=(",", ":"), sort_keys=True)
    if await db.get(SystemSetting, SETTINGS_KEY) is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value))
    else:
        await db.execute(update(SystemSetting).where(SystemSetting.key == SETTINGS_KEY).values(value=value))
