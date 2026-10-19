"""Web search services the chat's Web Search tool can use, behind one interface.

Each takes a query and a result count and returns ``SearchResult`` rows, or
raises ``WebSearchError`` with a code that says what went wrong in terms an
administrator can act on (a key refused, a quota spent, the service rate
limiting, the network, an answer it could not read). The API key never
appears in an error: messages are written here, never taken from the HTTP
client, whose text would carry the address with the key in it (Google).

Brave, Tavily and Google Programmable Search are APIs with a key; SearXNG is
the organisation's own server (no key); DuckDuckGo goes through the ``ddgs``
package, which reads its pages and is the least reliable: kept as a fallback
an administrator may turn off.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from app.branding import OUTBOUND_USER_AGENT

logger = logging.getLogger(__name__)

#: How long one search may take, connecting included.
SEARCH_TIMEOUT_S = 15.0
#: The most results one search asks for.
MAX_RESULTS = 10
#: What a result's text is cut to.
MAX_SNIPPET_CHARS = 600
MAX_CONTENT_CHARS = 4000

#: The codes ``WebSearchError`` carries.
ERROR_AUTH = "auth"
ERROR_QUOTA = "quota"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_NETWORK = "network"
ERROR_BAD_RESPONSE = "bad_response"
ERROR_NOT_CONFIGURED = "not_configured"


class WebSearchError(Exception):
    """A search that did not come back with results, and why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    #: The page's text, when the service hands it over (Tavily).
    content: str | None = None


@dataclass(frozen=True)
class SearchTarget:
    """One service to ask: what it is, and what it needs (never logged, never returned)."""

    provider: str
    api_key: str = ""
    base_url: str | None = None
    config: dict[str, Any] | None = None


def _clip(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _row(title: Any, url: Any, snippet: Any, content: Any = None) -> SearchResult | None:
    link = str(url or "").strip()
    if not link.lower().startswith(("http://", "https://")):
        return None
    body = _clip(content, MAX_CONTENT_CHARS) if content else None
    return SearchResult(
        title=_clip(title, 200) or link, url=link, snippet=_clip(snippet, MAX_SNIPPET_CHARS), content=body or None
    )


def _status_error(provider: str, response: httpx.Response) -> WebSearchError:
    """What an unsuccessful answer means, by its status and, where the service says, its body."""
    status = response.status_code
    try:
        text = response.text[:2000].lower()
    except Exception:  # noqa: BLE001 -- a body that cannot be read says nothing more
        text = ""
    if status in (401, 403) and not any(word in text for word in ("quota", "limit exceeded", "dailylimit")):
        return WebSearchError(
            ERROR_AUTH, f"{provider} refused the API key (HTTP {status}). Check it under Connections."
        )
    if status == 429 and not any(word in text for word in ("quota", "plan", "usage limit")):
        return WebSearchError(
            ERROR_RATE_LIMITED, f"{provider} is rate limiting searches (HTTP 429). Try again shortly."
        )
    if status in (402, 429, 432, 433) or (status == 403 and "limit" in text):
        return WebSearchError(ERROR_QUOTA, f"{provider}'s search quota is used up (HTTP {status}).")
    if status >= 500:
        return WebSearchError(ERROR_NETWORK, f"{provider} had a server error (HTTP {status}).")
    return WebSearchError(ERROR_BAD_RESPONSE, f"{provider} refused the search (HTTP {status}).")


async def _get_json(
    provider: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    client_factory: Callable[..., httpx.AsyncClient] | None = None,
) -> Any:
    from app.services.ssrf_guard import SSRFBlockedError, assert_response_target_safe, assert_url_safe, safe_client

    factory = client_factory or safe_client
    try:
        await asyncio.to_thread(assert_url_safe, url)
        async with factory(
            headers={"User-Agent": OUTBOUND_USER_AGENT, "Accept": "application/json", **(headers or {})},
            timeout=httpx.Timeout(SEARCH_TIMEOUT_S, connect=min(5.0, SEARCH_TIMEOUT_S)),
        ) as client:
            response = await client.request(method, url, params=params, json=json_body)
            assert_response_target_safe(response)
    except SSRFBlockedError:
        raise WebSearchError(
            ERROR_NOT_CONFIGURED,
            f"{provider}'s address is a private or internal one, which this server may not reach "
            "(ALLOW_SSRF_PRIVATE_RANGES=true allows a trusted internal server).",
        ) from None
    except httpx.TimeoutException:
        raise WebSearchError(ERROR_NETWORK, f"{provider} did not answer within {SEARCH_TIMEOUT_S:g} s.") from None
    except httpx.HTTPError:
        raise WebSearchError(ERROR_NETWORK, f"{provider} could not be reached.") from None
    if response.status_code != 200:
        raise _status_error(provider, response)
    try:
        return response.json()
    except ValueError:
        raise WebSearchError(ERROR_BAD_RESPONSE, f"{provider} answered with something that is not JSON.") from None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


async def search_brave(target: SearchTarget, query: str, limit: int, **kwargs: Any) -> list[SearchResult]:
    data = await _get_json(
        "Brave Search",
        "GET",
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": target.api_key},
        params={"q": query, "count": min(limit, 20)},
        client_factory=kwargs.get("client_factory"),
    )
    web = data.get("web") if isinstance(data, dict) else None
    rows = _list(web.get("results") if isinstance(web, dict) else None)
    return [
        r for r in (_row(x.get("title"), x.get("url"), x.get("description")) for x in rows if isinstance(x, dict)) if r
    ]


async def search_tavily(target: SearchTarget, query: str, limit: int, **kwargs: Any) -> list[SearchResult]:
    data = await _get_json(
        "Tavily",
        "POST",
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {target.api_key}"},
        json_body={"query": query, "max_results": min(limit, 20), "search_depth": "basic"},
        client_factory=kwargs.get("client_factory"),
    )
    rows = _list(data.get("results") if isinstance(data, dict) else None)
    # Tavily's "content" is the relevant part of the page: the snippet, and the content too.
    return [
        r
        for r in (
            _row(x.get("title"), x.get("url"), x.get("content"), x.get("raw_content") or x.get("content"))
            for x in rows
            if isinstance(x, dict)
        )
        if r
    ]


async def search_google(target: SearchTarget, query: str, limit: int, **kwargs: Any) -> list[SearchResult]:
    cx = str((target.config or {}).get("cx") or "")
    if not cx:
        raise WebSearchError(ERROR_NOT_CONFIGURED, "Google Programmable Search needs its search engine id (cx).")
    data = await _get_json(
        "Google Programmable Search",
        "GET",
        "https://www.googleapis.com/customsearch/v1",
        params={"key": target.api_key, "cx": cx, "q": query, "num": min(limit, 10)},
        client_factory=kwargs.get("client_factory"),
    )
    rows = _list(data.get("items") if isinstance(data, dict) else None)
    return [
        r for r in (_row(x.get("title"), x.get("link"), x.get("snippet")) for x in rows if isinstance(x, dict)) if r
    ]


async def search_searxng(target: SearchTarget, query: str, limit: int, **kwargs: Any) -> list[SearchResult]:
    base = (target.base_url or "").strip()
    if not base:
        raise WebSearchError(ERROR_NOT_CONFIGURED, "SearXNG needs the address of your SearXNG server.")
    try:
        data = await _get_json(
            "SearXNG",
            "GET",
            urljoin(base.rstrip("/") + "/", "search"),
            params={"q": query, "format": "json"},
            client_factory=kwargs.get("client_factory"),
        )
    except WebSearchError as exc:
        if exc.code == ERROR_AUTH:
            # SearXNG answers 403 when its JSON format is off, not for a key.
            raise WebSearchError(
                ERROR_NOT_CONFIGURED, "SearXNG refused JSON results: add json to search.formats in its settings.yml."
            ) from None
        raise
    rows = _list(data.get("results") if isinstance(data, dict) else None)[:limit]
    return [r for r in (_row(x.get("title"), x.get("url"), x.get("content")) for x in rows if isinstance(x, dict)) if r]


def _ddgs_text(query: str, limit: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    return list(DDGS(timeout=int(SEARCH_TIMEOUT_S)).text(query, max_results=limit))


async def search_duckduckgo(target: SearchTarget, query: str, limit: int, **kwargs: Any) -> list[SearchResult]:
    runner = kwargs.get("ddgs_runner") or _ddgs_text
    try:
        rows = await asyncio.wait_for(asyncio.to_thread(runner, query, limit), timeout=SEARCH_TIMEOUT_S + 5)
    except TimeoutError:
        raise WebSearchError(ERROR_NETWORK, "DuckDuckGo did not answer in time.") from None
    except Exception as exc:  # noqa: BLE001 -- ddgs raises its own kinds; the name is enough to tell them apart
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        if "ratelimit" in name or "202" in text or "ratelimit" in text:
            raise WebSearchError(ERROR_RATE_LIMITED, "DuckDuckGo is rate limiting searches from this server.") from None
        if "timeout" in name:
            raise WebSearchError(ERROR_NETWORK, "DuckDuckGo did not answer in time.") from None
        if "noresults" in name or "no results" in text:
            return []
        logger.info("DuckDuckGo search failed: %s", type(exc).__name__)
        raise WebSearchError(ERROR_NETWORK, "DuckDuckGo could not be reached from this server.") from None
    return [
        r
        for r in (
            _row(x.get("title"), x.get("href") or x.get("link") or x.get("url"), x.get("body") or x.get("snippet"))
            for x in rows
            if isinstance(x, dict)
        )
        if r
    ]


_Search = Callable[..., Awaitable[list[SearchResult]]]

PROVIDERS: dict[str, _Search] = {
    "brave": search_brave,
    "tavily": search_tavily,
    "google_pse": search_google,
    "searxng": search_searxng,
    "duckduckgo": search_duckduckgo,
}

#: How each service is named to people.
PROVIDER_LABELS: dict[str, str] = {
    "brave": "Brave Search",
    "tavily": "Tavily",
    "google_pse": "Google Programmable Search",
    "searxng": "SearXNG",
    "duckduckgo": "DuckDuckGo",
}


async def run_search(target: SearchTarget, query: str, limit: int, **kwargs: Any) -> list[SearchResult]:
    """One search with one service; raises WebSearchError."""
    search = PROVIDERS.get(target.provider)
    if search is None:
        raise WebSearchError(ERROR_NOT_CONFIGURED, f"{target.provider} is not a web search service.")
    count = max(1, min(int(limit), MAX_RESULTS))
    results = await search(target, query, count, **kwargs)
    # One row per address, in the service's order.
    seen: set[str] = set()
    unique = []
    for row in results:
        if row.url not in seen:
            seen.add(row.url)
            unique.append(row)
    return unique[:count]
