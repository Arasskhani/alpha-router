"""Server tools for in-app chat: web search and fetch."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse


from app.core.prompt_fences import RUNTIME_POLICY, untrusted_preamble, wrap_untrusted
from app.branding import OUTBOUND_USER_AGENT
from app.services.metered_usage_service import (
    finish_metered_usage,
    start_metered_usage,
)
from app.services.provider_utils import extract_prompt_text

URL_RE = re.compile(r"https?://[^\s<>\[\]()\"']+", re.IGNORECASE)


@dataclass
class ChatToolsConfig:
    web_search: bool = False
    web_search_depth: str = "medium"
    web_fetch: bool = False
    code_interpreter: bool = False


def parse_tools_config(body: dict) -> ChatToolsConfig:
    tools = body.get("tools") if isinstance(body.get("tools"), dict) else {}
    depth = str(tools.get("web_search_depth") or body.get("web_search_depth") or "medium").lower()
    if depth not in ("low", "medium", "high"):
        depth = "medium"
    return ChatToolsConfig(
        web_search=bool(body.get("web_search") or tools.get("web_search")),
        web_search_depth=depth,
        web_fetch=bool(tools.get("web_fetch") or body.get("web_fetch")),
        code_interpreter=bool(tools.get("code_interpreter") or body.get("code_interpreter")),
    )


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content.strip()
    return extract_prompt_text(messages).strip()


def _search_result_limit(depth: str) -> int:
    return {"low": 3, "medium": 5, "high": 8}.get(depth, 5)


def _run_duckduckgo_search(query: str, max_results: int) -> list[dict[str, str]]:
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def web_search_context(
    query: str,
    depth: str,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
) -> str:
    if not query.strip():
        return ""
    limit = _search_result_limit(depth)
    metered = (
        await start_metered_usage(
            user_id=user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            username=username,
            provider_type="duckduckgo",
            service_type="web_search",
            operation_name="web_search",
            model_id="duckduckgo-search",
            metadata={"depth": depth, "max_results": limit},
            reserve_budget=reserve_budget,
        )
        if user_id is not None or alpha_router_api_key_id is not None
        else None
    )
    try:
        rows = await asyncio.to_thread(_run_duckduckgo_search, query, limit)
    except asyncio.CancelledError as exc:
        if metered is not None:
            await finish_metered_usage(
                metered,
                success=False,
                quantity=None,
                unit=None,
                error_message=str(exc) or "Search cancelled",
            )
        raise
    except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
        if metered is not None:
            await finish_metered_usage(
                metered,
                success=False,
                quantity=None,
                unit=None,
                error_message=str(exc),
            )
        return ""
    if metered is not None:
        await finish_metered_usage(
            metered,
            success=True,
            quantity=1,
            unit="request",
        )
    if not rows:
        return ""
    lines = []
    for i, row in enumerate(rows, 1):
        title = (row.get("title") or "").strip()
        href = (row.get("href") or row.get("link") or "").strip()
        body = (row.get("body") or row.get("snippet") or "").strip()
        lines.append(f"{i}. {title}\n   URL: {href}\n   {body}")
    return (
        "Web search results (use for up-to-date facts; cite sources when relevant). "
        + untrusted_preamble("search result text")
        + "\n"
        + wrap_untrusted("WEB_SEARCH_RESULTS", "\n".join(lines))
    )


class _MLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._chunks.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self._chunks)


def _html_to_text(html: str) -> str:
    parser = _MLStripper()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return re.sub(r"<[^>]+>", " ", html))
        return re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", parser.get_text()).strip()


async def fetch_url_text(
    url: str,
    max_chars: int = 14_000,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Invalid URL")
    # SSRF guard: reject URLs that resolve to internal/private/metadata IPs.
    # This runs before the fetch so a malicious user cannot make the server
    # probe internal services or cloud metadata endpoints via the web-fetch
    # chat tool.
    from app.config import get_settings
    from app.services.bounded_io import bounded_get_bytes, clamp_limit
    from app.services.ssrf_guard import safe_client

    metered = (
        await start_metered_usage(
            user_id=user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            username=username,
            provider_type="direct_http",
            service_type="web_fetch",
            operation_name="web_fetch",
            model_id="direct-http-fetch",
            metadata={"host": parsed.hostname or ""},
            reserve_budget=reserve_budget,
        )
        if user_id is not None or alpha_router_api_key_id is not None
        else None
    )
    try:
        async with safe_client(
            headers={"User-Agent": OUTBOUND_USER_AGENT},
        ) as client:
            byte_limit = clamp_limit(
                get_settings().max_web_fetch_bytes,
                minimum=256 * 1024,
                maximum=5 * 1024 * 1024,
            )
            raw, ctype = await bounded_get_bytes(client, url, max_bytes=byte_limit)
            text = raw.decode("utf-8", errors="replace")
            if "html" in ctype.lower() or "<html" in text[:200].lower():
                text = _html_to_text(text)
    except BaseException as exc:
        if metered is not None:
            await finish_metered_usage(
                metered,
                success=False,
                quantity=None,
                unit=None,
                error_message=str(exc),
            )
        raise
    if metered is not None:
        await finish_metered_usage(
            metered,
            success=True,
            quantity=1,
            unit="request",
        )
    return text[:max_chars]


async def web_fetch_context(
    messages: list[dict],
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
) -> str:
    text = _last_user_text(messages)
    urls = list(dict.fromkeys(URL_RE.findall(text)))[:3]
    if not urls:
        return ""
    blocks: list[str] = ["Fetched page content for URLs in the user message. " + untrusted_preamble("page content")]
    for url in urls:
        try:
            content = await fetch_url_text(
                url,
                user_id=user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                username=username,
                reserve_budget=reserve_budget,
            )
            blocks.append(wrap_untrusted("WEB_PAGE", content[:8000], source=url))
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
            blocks.append(wrap_untrusted("WEB_PAGE", f"(fetch failed: {exc})", source=url))
    return "\n\n".join(blocks)


async def augment_messages_with_tools(
    db,
    messages: list[dict],
    tools: ChatToolsConfig,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
) -> list[dict]:
    """Prepend tool context as system messages; return new message list."""
    if not messages:
        return messages
    system_blocks: list[str] = []
    user_query = _last_user_text(messages)

    if tools.web_search and user_query:
        ctx = await web_search_context(
            user_query,
            tools.web_search_depth,
            user_id=user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            username=username,
            reserve_budget=reserve_budget,
        )
        if ctx:
            system_blocks.append(ctx)

    if tools.web_fetch:
        ctx = await web_fetch_context(
            messages,
            user_id=user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            username=username,
            reserve_budget=reserve_budget,
        )
        if ctx:
            system_blocks.append(ctx)

    if tools.code_interpreter:
        from app.services.code_interpreter_service import code_interpreter_system_message

        system_blocks.insert(0, code_interpreter_system_message())

    if not system_blocks:
        return list(messages)

    # Untrusted content is about to enter the prompt: state the rules first.
    system_blocks.insert(0, RUNTIME_POLICY)

    prefix = [{"role": "system", "content": "\n\n".join(system_blocks)}]
    out = list(messages)
    if out and out[0].get("role") == "system":
        merged = out[0].get("content", "")
        if isinstance(merged, str):
            out[0] = {"role": "system", "content": f"{merged}\n\n{system_blocks[0]}"}
            prefix = []
            if len(system_blocks) > 1:
                prefix = [{"role": "system", "content": "\n\n".join(system_blocks[1:])}]
    return prefix + out
