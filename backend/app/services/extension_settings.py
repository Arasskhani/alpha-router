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

import ipaddress
import json
import logging
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, cast

import idna
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.services.extension_package import SITE_ACCESS_MODES, SITE_ACCESS_PER_SITE
from app.services.list_bounds import ADMIN_LIST_HARD_CAP
from app.services.system_default_models import model_supports_text_chat

logger = logging.getLogger(__name__)

SETTINGS_KEY = "extension.settings"

DEFAULT_MAX_STEPS = 25
MIN_MAX_STEPS = 5
MAX_MAX_STEPS = 100
MAX_SITE_PATTERNS = 200
MAX_MODEL_REFS = 500

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


@dataclass(frozen=True)
class ExtensionSettings:
    site_access: str = SITE_ACCESS_PER_SITE
    allowed_sites: tuple[str, ...] = field(default_factory=tuple)
    blocked_sites: tuple[str, ...] = field(default_factory=tuple)
    page_content_models: tuple[str, ...] = field(default_factory=tuple)
    agent_models: tuple[str, ...] = field(default_factory=tuple)
    agent_max_steps: int = DEFAULT_MAX_STEPS
    agent_auto_mode: bool = False
    agent_review_model: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("allowed_sites", "blocked_sites", "page_content_models", "agent_models"):
            data[key] = list(data[key])
        return data


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


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


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
    return ExtensionSettings(
        site_access=site_access if site_access in SITE_ACCESS_MODES else defaults.site_access,
        allowed_sites=_strings(data.get("allowed_sites")),
        blocked_sites=_strings(data.get("blocked_sites")),
        page_content_models=_strings(data.get("page_content_models")),
        agent_models=_strings(data.get("agent_models")),
        agent_max_steps=(
            max_steps
            if isinstance(max_steps, int) and MIN_MAX_STEPS <= max_steps <= MAX_MAX_STEPS
            else defaults.agent_max_steps
        ),
        agent_auto_mode=bool(data.get("agent_auto_mode")) and isinstance(review, str) and bool(review),
        agent_review_model=review if isinstance(review, str) and review else None,
    )


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


#: What the settings page says about a model it lists.
MODEL_OK = "ok"
MODEL_DISABLED = "disabled"
MODEL_NOT_CHAT = "not_chat"
MODEL_DELETED = "deleted"


def _named_model_ids(settings: ExtensionSettings) -> set[int]:
    refs = (*settings.page_content_models, *settings.agent_models, settings.agent_review_model or "")
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
            }
        )
    choices.extend(
        {"ref": f"model::{model_id}", "label": f"Model {model_id}", "provider": None, "state": MODEL_DELETED}
        for model_id in sorted(named - set(by_id))
    )
    choices.sort(key=lambda choice: (choice["label"].casefold(), choice["ref"]))
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
) -> ExtensionSettings:
    """The settings an administrator asked for, checked; raises ExtensionSettingsError."""
    if site_access not in SITE_ACCESS_MODES:
        raise ExtensionSettingsError("Site access must be per site or all sites.")
    if not MIN_MAX_STEPS <= int(agent_max_steps) <= MAX_MAX_STEPS:
        raise ExtensionSettingsError(f"Agent steps must be between {MIN_MAX_STEPS} and {MAX_MAX_STEPS}.")
    review = (agent_review_model or "").strip() or None
    # The review model has to answer for every action in Auto mode: it must work today.
    review_list = await _model_list(db, "Review model", [review] if review else [], enabled_only=True)
    if agent_auto_mode and not review_list:
        raise ExtensionSettingsError("Auto mode needs a review model to check each action.")
    updated = replace(
        current,
        site_access=site_access,
        allowed_sites=_site_list("Allowed sites", allowed_sites),
        blocked_sites=_site_list("Blocked sites", blocked_sites),
        page_content_models=await _model_list(db, "Models for page content", page_content_models),
        agent_models=await _model_list(db, "Agent models", agent_models),
        agent_max_steps=int(agent_max_steps),
        agent_auto_mode=bool(agent_auto_mode),
        agent_review_model=review_list[0] if review_list else None,
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
