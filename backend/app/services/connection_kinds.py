"""What a connection is for: a model provider, or a web search provider.

A connection's ``kind`` is chosen when it is made and never changes. A model
connection's key goes to a model provider, and its models are synced and
offered; a web search connection's key goes only to that search service, for
the chat's Web Search tool. Every query that looks for model providers reads
``kind = 'models'`` (``model_connection``), so a search key is never sent to a
model provider, synced for models, or offered where models are chosen.
"""

from __future__ import annotations

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
