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


def search_result_limit(depth: str) -> int:
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
    limit = search_result_limit(depth)
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


async def _guard_fetch(
    url: str, *, user_id: int | None, alpha_router_api_key_id: int | None, username: str | None
) -> None:
    """The administrator's Guardrails on an address about to be read: raises GuardrailBlocked to stop it.

    An address cannot be masked - a page asked for with another address is another page - so a rule that
    would mask or route it stops it instead.
    """
    from app.database import AsyncSessionLocal
    from app.services.guardrail_policy import (
        Destination,
        EventContext,
        GuardrailBlocked,
        GuardrailEngineError,
        Segment,
        inspect,
    )

    host = urlparse(url).hostname or url
    ctx = EventContext(
        user_id=user_id, username=username, alpha_router_api_key_id=alpha_router_api_key_id, source="web_fetch"
    )
    async with AsyncSessionLocal() as db:
        try:
            verdict = await inspect(
                db,
                [Segment("web_fetch", url)],
                destination=Destination(label=f"Web page · {host}", trust="public"),
                ctx=ctx,
            )
        except GuardrailEngineError as exc:
            raise GuardrailBlocked(str(exc)) from exc
    if verdict.action is not None:
        notices = verdict.notices()
        raise GuardrailBlocked(notices[0] if notices else "Your organisation does not allow this page to be read.")


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
    await _guard_fetch(url, user_id=user_id, alpha_router_api_key_id=alpha_router_api_key_id, username=username)
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
    model_driven: bool = False,
) -> list[dict]:
    """The turn's messages with what the tools add, rules first; a new list.

    When the model calls the web tools itself (``model_driven``, chat_web_tools) only
    their instructions are added - the results come later, as tool messages.
    Otherwise the person's own words are searched once and the links they
    typed are read, before the model is asked.

    The order is the runtime policy, then the chat's own system message (its
    instructions stay near the top, the same from turn to turn), then what
    the tools found - so untrusted text never comes before the rules.
    """
    if not messages:
        return messages
    static_blocks: list[str] = []
    found_blocks: list[str] = []
    user_text = latest_user_text(messages)

    if model_driven:
        from app.services.chat_web_tools import web_tools_instructions

        static_blocks.append(web_tools_instructions(search=tools.web_search, fetch=tools.web_fetch))
    else:
        from app.services.chat_web_tools import pre_search_query

        query = pre_search_query(user_text)
        if tools.web_search and query:
            ctx = await web_search_context(
                query,
                tools.web_search_depth,
                user_id=user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                username=username,
                reserve_budget=reserve_budget,
            )
            if ctx:
                found_blocks.append(ctx)
        if tools.web_fetch:
            ctx = await web_fetch_context(
                messages,
                user_id=user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                username=username,
                reserve_budget=reserve_budget,
            )
            if ctx:
                found_blocks.append(ctx)

    if tools.code_interpreter:
        from app.services.code_interpreter_service import code_interpreter_system_message

        static_blocks.insert(0, code_interpreter_system_message())

    if not static_blocks and not found_blocks:
        return list(messages)

    out = list(messages)
    head = [RUNTIME_POLICY]
    if out and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        head.append(str(out[0]["content"]))
        out = out[1:]
    first = {"role": "system", "content": "\n\n".join([*head, *static_blocks])}
    found = [{"role": "system", "content": "\n\n".join(found_blocks)}] if found_blocks else []
    return [first, *found, *out]
