"""Pages a connected browser shares with a model: what the server checks, and what it records.

The extension reads a page only when the user asks, and only on sites the
administrator's rules allow; it checks the rules before it reads anything.
The server checks them again for every site a chat request declares, because
the extension's copy of the rules can be stale (a site blocked a minute ago,
a browser that kept an old copy), and it checks the model: an administrator
can name the models that may receive page content.

The declaration is the extension's word - the server cannot tell page text
from text the user typed. What it makes sure of is that a page the extension
declares goes nowhere the rules forbid, and that each one is recorded: the
site, how much text and which model, never the text itself.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.extension import ExtensionEvent
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.extension_package import normalize_origin
from app.services.extension_settings import ExtensionSettings, normalize_page_host, site_refusal
from app.services.model_resolution_service import resolve_model_row

#: Sites one request may declare; the panel sends one per tab it shares.
MAX_PAGE_SITES = 20
#: A sanity bound on the declared size of one site's text, far above what the extension sends.
MAX_PAGE_CHARS = 5_000_000

EVENT_PAGE_CONTEXT = "page_context"


class PageContextRefused(Exception):
    """A declared page may not go where the request would send it."""

    def __init__(self, status: int, code: str, message: str, **extra: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, **self.extra}


@dataclass(frozen=True)
class PageShare:
    """One site's pages in a request: the host, and how many characters of text."""

    host: str
    chars: int


def page_shares(declared: Iterable[tuple[str, int]]) -> list[PageShare]:
    """The declared sites, checked and merged: two tabs on one site are one share of both sizes."""
    totals: dict[str, int] = {}
    for raw_host, chars in declared:
        try:
            host = normalize_page_host(raw_host)
        except ValueError:
            raise PageContextRefused(400, "invalid_request", f"{raw_host!r} is not a host name.") from None
        totals[host] = totals.get(host, 0) + int(chars)
    return [PageShare(host=host, chars=chars) for host, chars in totals.items()]


def server_host() -> str | None:
    """This Alpharouter's own host, which an allow list never shuts out."""
    try:
        return urlsplit(normalize_origin(get_settings().frontend_url)).hostname
    except ValueError:
        return None


async def check_page_shares(
    db: AsyncSession,
    shares: list[PageShare],
    *,
    model_ref: str,
    settings: ExtensionSettings,
) -> AIModel | None:
    """Refuse a blocked or unlisted site, or a model outside the admin's list; otherwise the model.

    The model is the one a chat turn would resolve ``model_ref`` to, so naming
    it by its external id instead of ``model::<id>`` changes nothing. None
    when nothing usable is named and the admin set no list: the chat turn
    itself then refuses the model as it would any other request.
    """
    own_host = server_host()
    for share in shares:
        if site_refusal(share.host, settings, server_host=own_host) is not None:
            raise PageContextRefused(
                403,
                "site_not_allowed",
                f"Your administrator does not allow sharing pages from {share.host}.",
                site=share.host,
            )
    found = await resolve_model_row(db, model_ref)
    model = found[0] if found is not None else None
    if settings.page_content_models and (model is None or f"model::{model.id}" not in settings.page_content_models):
        raise PageContextRefused(
            403,
            "model_not_allowed",
            "Your administrator does not allow pages to be sent to this model. Choose another model.",
        )
    return model


def page_share_events(
    shares: list[PageShare],
    *,
    user: User,
    ip: str | None,
    session_id: str | None,
    model: AIModel | None,
    model_ref: str,
    private: bool,
) -> list[ExtensionEvent]:
    """One Admin Logs row per site: who, from which browser, how much text and to which model."""
    model_value = f"model::{model.id}" if model is not None else model_ref
    model_name = (model.display_name or model.external_id) if model is not None else None
    return [
        ExtensionEvent(
            actor_user_id=user.id,
            actor_username=user.username,
            actor_ip=ip,
            session_id=session_id,
            kind=EVENT_PAGE_CONTEXT,
            site=share.host,
            detail_json=json.dumps(
                {"chars": share.chars, "model": model_value, "model_name": model_name, "private": private},
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        for share in shares
    ]
