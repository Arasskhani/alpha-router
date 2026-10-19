"""Server tools for in-app chat: web search and fetch."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.prompt_fences import RUNTIME_POLICY, untrusted_preamble, wrap_untrusted
from app.services.failure_details import failure_message
from app.services.metered_usage_service import (
    finish_metered_usage,
    start_metered_usage,
)
from app.services.web_fetch_service import extract_urls, fetch_all, fetch_page, latest_user_text
from app.services.web_search_providers import SearchResult
from app.services.web_search_service import WebSearchUnavailable, search_web


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


def _search_result_limit(depth: str) -> int:
    return {"low": 3, "medium": 5, "high": 8}.get(depth, 5)


async def web_search_context(
    query: str,
    depth: str,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
) -> str:
    """Search results for the model, or - when no service answered - a note saying so and why.

    The note matters: without it the model answers as if it had searched.
    """
    if not query.strip():
        return ""
    limit = _search_result_limit(depth)
    try:
        outcome = await search_web(
            query,
            limit,
            user_id=user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            username=username,
            reserve_budget=reserve_budget,
        )
    except WebSearchUnavailable as exc:
        return search_failed_note(exc.message)
    return format_search_results(outcome.results, label=outcome.label)


def search_failed_note(reason: str) -> str:
    """What the model is told when Web Search found nothing to read: say it to the user, never pretend."""
    return (
        "Web search was asked for, but it did not work this time: "
        f"{reason} Tell the user that the web search failed and why, and answer only from what you know, "
        "saying that it may be out of date. Do not claim to have searched."
    )


def format_search_results(rows: list[SearchResult], *, label: str) -> str:
    if not rows:
        return (
            f"Web search ({label}) found nothing for this. Tell the user so if it matters, and answer from what "
            "you know, saying that it may be out of date."
        )
    lines = []
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {row.title}\n   URL: {row.url}\n   {row.snippet}")
        if row.content and row.content != row.snippet:
            lines.append(f"   Page text: {row.content}")
    return (
        f"Web search results from {label} (use for up-to-date facts; cite the URLs you use). "
        + untrusted_preamble("search result text")
        + "\n"
        + wrap_untrusted("WEB_SEARCH_RESULTS", "\n".join(lines))
    )


#: What one page may give the model, in characters.
PAGE_CHARS_FOR_MODEL = 8000


async def fetch_url_text(
    url: str,
    max_chars: int = 14_000,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
) -> str:
    """One link read as text for the model (title first), metered as web_fetch; raises when it cannot be read.

    The fetch goes through the SSRF-guarded client: a link to an internal,
    private or metadata address is refused before anything is sent.
    """
    from app.config import get_settings
    from app.services.bounded_io import clamp_limit

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Invalid URL")
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
        byte_limit = clamp_limit(get_settings().max_web_fetch_bytes, minimum=256 * 1024, maximum=5 * 1024 * 1024)
        page = await fetch_page(url, max_bytes=byte_limit)
    except BaseException as exc:
        if metered is not None:
            await finish_metered_usage(
                metered, success=False, quantity=None, unit=None, error_message=failure_message(exc)
            )
        raise
    if metered is not None:
        await finish_metered_usage(metered, success=True, quantity=1, unit="request")
    text = f"Title: {page.title}\n\n{page.text}" if page.title else page.text
    if page.truncated or len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n(The page was longer; the rest was left out.)"
    return text


async def web_fetch_context(
    messages: list[dict],
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
) -> str:
    """The pages of the links the person typed in their latest message, read at the same time."""
    urls = extract_urls(latest_user_text(messages))
    if not urls:
        return ""

    async def read(url: str) -> str:
        return await fetch_url_text(
            url,
            max_chars=PAGE_CHARS_FOR_MODEL,
            user_id=user_id,
            alpha_router_api_key_id=alpha_router_api_key_id,
            username=username,
            reserve_budget=reserve_budget,
        )

    blocks: list[str] = ["Fetched page content for URLs in the user message. " + untrusted_preamble("page content")]
    for url, result in zip(urls, await fetch_all(urls, read), strict=True):
        if isinstance(result, BaseException):
            reason = (failure_message(result) or type(result).__name__).rstrip(". ")
            blocks.append(
                wrap_untrusted("WEB_PAGE", f"(This page could not be read: {reason}. Tell the user.)", source=url)
            )
        else:
            blocks.append(wrap_untrusted("WEB_PAGE", result, source=url))
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
    user_query = latest_user_text(messages)

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
