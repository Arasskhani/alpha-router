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
site, how much text, how many screenshots and which model, never the content.

A screenshot of a page is page content like its text: the same rules apply,
and it may only go to a model that reads images.

An answer about a page can restate it, so a chat that holds one carries page
content on: every later turn in it, in the extension or the web app, and the
chat's title, go only to a model the administrator's list allows.

The browser agent reads pages through its tools rather than declaring them;
the extension checks the site rules before each action, and the server checks
the agent's model against both model lists.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.extension import ExtensionEvent
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.extension_package import normalize_origin
from app.services.extension_settings import (
    ExtensionSettings,
    normalize_page_host,
    page_content_allowed,
    site_refusal,
)
from app.services.model_capabilities import model_media_flags, supports_vision
from app.services.model_resolution_service import resolve_model_row

#: Sites one request may declare; the panel sends one per tab it shares.
MAX_PAGE_SITES = 20
#: A sanity bound on the declared size of one site's text, far above what the extension sends.
MAX_PAGE_CHARS = 5_000_000
#: Screenshots of one site in one request (the panel sends one per question).
MAX_PAGE_IMAGES = 20

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
    """One site's pages in a request: the host, how many characters of text, how many screenshots."""

    host: str
    chars: int
    images: int = 0


def page_shares(declared: Iterable[tuple[str, int, int]]) -> list[PageShare]:
    """The declared sites, checked and merged: two tabs on one site are one share of both sizes."""
    totals: dict[str, tuple[int, int]] = {}
    for raw_host, chars, images in declared:
        try:
            host = normalize_page_host(raw_host)
        except ValueError:
            raise PageContextRefused(400, "invalid_request", f"{raw_host!r} is not a host name.") from None
        had_chars, had_images = totals.get(host, (0, 0))
        totals[host] = (had_chars + int(chars), had_images + int(images))
    return [PageShare(host=host, chars=chars, images=images) for host, (chars, images) in totals.items()]


def reads_images(model: AIModel) -> bool:
    """Whether a chat model takes an image as input, as /api/chat/models reports it."""
    external_id = str(model.external_id or "")
    pricing_raw = cast("str | None", model.pricing_raw)
    provider_type = cast("str | None", model.provider_type)
    media = model_media_flags(
        external_id=external_id,
        is_image_model=bool(model.is_image_model),
        is_video_model=bool(getattr(model, "is_video_model", False)),
        pricing_raw=pricing_raw,
        provider_type=provider_type,
    )
    return supports_vision(
        external_id=external_id,
        is_image_model=media["is_image_model"],
        pricing_raw=pricing_raw,
        provider_type=provider_type,
    )


def server_host() -> str | None:
    """This Alpharouter's own host, which an allow list never shuts out."""
    try:
        return urlsplit(normalize_origin(get_settings().frontend_url)).hostname
    except ValueError:
        return None


#: What a turn carrying page content is told when its model is not on the administrator's list.
PAGES_NOT_FOR_MODEL = "Your administrator does not allow pages to be sent to this model. Choose another model."


async def check_page_content_model(
    db: AsyncSession,
    *,
    model_ref: str,
    settings: ExtensionSettings,
    message: str = PAGES_NOT_FOR_MODEL,
) -> AIModel | None:
    """Refuse a model the administrator keeps page content from; otherwise the model.

    The model is the one a chat turn would resolve ``model_ref`` to, so naming
    it by its external id instead of ``model::<id>`` changes nothing. None
    when nothing usable is named and the admin set no list: the chat turn
    itself then refuses the model as it would any other request.
    """
    found = await resolve_model_row(db, model_ref)
    model = found[0] if found is not None else None
    if not page_content_allowed(settings, f"model::{model.id}" if model is not None else None):
        raise PageContextRefused(403, "model_not_allowed", message)
    return model


async def check_page_shares(
    db: AsyncSession,
    shares: list[PageShare],
    *,
    model_ref: str,
    settings: ExtensionSettings,
) -> AIModel | None:
    """Refuse a blocked or unlisted site, a model outside the admin's list, or
    screenshots for a model that reads no images; otherwise the model, as
    ``check_page_content_model`` resolves it.
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
    model = await check_page_content_model(db, model_ref=model_ref, settings=settings)
    if model is not None and any(share.images for share in shares) and not reads_images(model):
        raise PageContextRefused(400, "model_reads_no_images", "This model does not read images. Choose another model.")
    return model


async def check_agent_model(db: AsyncSession, *, model_ref: str, settings: ExtensionSettings) -> AIModel | None:
    """Refuse a model the administrator keeps from the browser agent; otherwise the model.

    The agent reads pages through its tools and sends what it reads to the
    model, so the page-content list binds it as well as its own list. Resolved
    as the chat turn will resolve ``model_ref``, like ``check_page_shares``.
    """
    found = await resolve_model_row(db, model_ref)
    model = found[0] if found is not None else None
    ref = f"model::{model.id}" if model is not None else None
    if settings.agent_models and ref not in settings.agent_models:
        raise PageContextRefused(
            403,
            "model_not_allowed",
            "Your administrator does not allow the browser agent to use this model. Choose another model.",
        )
    if not page_content_allowed(settings, ref):
        raise PageContextRefused(403, "model_not_allowed", PAGES_NOT_FOR_MODEL)
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
                {
                    "chars": share.chars,
                    "model": model_value,
                    "model_name": model_name,
                    "private": private,
                    # Only when there were any: a text-only share reads as it always did.
                    **({"images": share.images} if share.images else {}),
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        for share in shares
    ]
