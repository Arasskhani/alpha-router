"""What a connection is for: a model provider, or a web search provider.

A connection's ``kind`` is chosen when it is made and never changes. A model
connection's key goes to a model provider, and its models are synced and
offered; a web search connection's key goes only to that search service, for
the chat's Web Search tool. Every query that looks for model providers reads
``kind = 'models'`` (``model_connection``), so a search key is never sent to a
model provider, synced for models, or offered where models are chosen.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.models.connection import Connection

CONNECTION_KIND_MODELS = "models"
CONNECTION_KIND_WEB_SEARCH = "web_search"
CONNECTION_KINDS = (CONNECTION_KIND_MODELS, CONNECTION_KIND_WEB_SEARCH)

#: The search services a web search connection may be. Never a model provider's name, and no model connection
#: may take one of these.
WEB_SEARCH_PROVIDERS = ("brave", "tavily", "google", "searxng", "duckduckgo")


def model_connection() -> Any:
    """The condition every model-side query on ``connections`` carries."""
    return Connection.kind == CONNECTION_KIND_MODELS


def web_search_connection() -> Any:
    """The condition the chat's Web Search reads its connections by."""
    return Connection.kind == CONNECTION_KIND_WEB_SEARCH


def kind_mismatch(kind: str, provider_type: str) -> str | None:
    """Why ``provider_type`` cannot be a connection of ``kind``, or None when it can."""
    provider = (provider_type or "").strip().lower()
    if kind not in CONNECTION_KINDS:
        return "A connection is for models or for web search."
    if kind == CONNECTION_KIND_WEB_SEARCH and provider not in WEB_SEARCH_PROVIDERS:
        return f"A web search connection is one of: {', '.join(WEB_SEARCH_PROVIDERS)}."
    if kind == CONNECTION_KIND_MODELS and provider in WEB_SEARCH_PROVIDERS:
        return f"{provider} is a web search service: add it under Web search, not as a model provider."
    return None


#: Search services that take no API key: SearXNG (the organisation's own server) and DuckDuckGo.
NO_KEY_PROVIDERS = frozenset({"searxng", "duckduckgo"})
#: Search services that need the address of the server: SearXNG.
BASE_URL_PROVIDERS = frozenset({"searxng"})
#: What one search may be priced at, in US dollars, and the order connections may take.
MAX_PRICE_PER_REQUEST_USD = 10.0
MIN_PRIORITY = 1
MAX_PRIORITY = 1000
_GOOGLE_CX = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")


def search_config(provider_type: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """The options a search provider takes besides its key, checked; raises ValueError.

    Google Programmable Search needs its search engine id (``cx``); the others
    take none here. Anything else in ``config`` is dropped, never stored.
    """
    provider = (provider_type or "").strip().lower()
    raw = config if isinstance(config, dict) else {}
    if provider == "google":
        cx = str(raw.get("cx") or "").strip()
        if not _GOOGLE_CX.match(cx):
            raise ValueError("Google Programmable Search needs its search engine id (cx).")
        return {"cx": cx}
    return {}


def search_fields(
    provider_type: str,
    *,
    api_key: str | None,
    base_url: str | None,
    priority: int,
    price_per_request_usd: float,
    has_stored_key: bool = False,
) -> None:
    """Check what a web search connection is made of; raises ValueError saying which and why."""
    provider = (provider_type or "").strip().lower()
    if provider not in NO_KEY_PROVIDERS and not (api_key or "").strip() and not has_stored_key:
        raise ValueError("This search service needs its API key.")
    if provider in BASE_URL_PROVIDERS and not (base_url or "").strip():
        raise ValueError("SearXNG needs the address of your SearXNG server.")
    if not MIN_PRIORITY <= int(priority) <= MAX_PRIORITY:
        raise ValueError(f"Priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}.")
    price = float(price_per_request_usd)
    if not math.isfinite(price) or not 0 <= price <= MAX_PRICE_PER_REQUEST_USD:
        raise ValueError(f"The price of one search must be between 0 and {MAX_PRICE_PER_REQUEST_USD:g} USD.")
