"""Web Search and Web Fetch as tools the model calls itself, inside a chat turn.

With the toggles on and a model that calls functions, the model is offered
``web_search(query)`` and ``web_fetch(url)``. It writes its own query - so a
follow-up ("and its price?") is searched for what it means, and "thanks" is
not searched at all - and reads the pages it chooses. The server runs each
call, metered as before, and hands the result back fenced as untrusted data;
the model's tool calls never reach the client. A call that fails comes back
saying so and why, so the model tells the person instead of pretending.

Per turn: at most ``MAX_SEARCHES`` searches and ``MAX_FETCHES`` fetches, and
``MAX_ROUNDS`` rounds of calls; the round after the last one is asked with no
tools, so the turn always ends in an answer.

A model that does not call functions gets the older way instead: one search
of the person's own words (``pre_search_query``) put before their message.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.core.prompt_fences import untrusted_preamble, wrap_untrusted

logger = logging.getLogger(__name__)

MAX_SEARCHES = 3
MAX_FETCHES = 3
MAX_ROUNDS = 6
#: What a pre-search (for a model without tools) sends of the person's words.
PRE_SEARCH_QUERY_CHARS = 300
#: A source list is kept to this many entries.
MAX_SOURCES = 20
#: How long one call may take, all in: a search tries each service in turn; a page that trickles in is cut off.
CALL_TIMEOUT_S = {"web_search": 45.0, "web_fetch": 30.0}

WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current or specific information. Returns titles, addresses and snippets. "
            "Use it when the answer depends on facts that may have changed or that you are not sure of; "
            "do not use it for small talk or what you already know well."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A focused search query, in the language most likely to find good sources.",
                }
            },
            "required": ["query"],
        },
    },
}

WEB_FETCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": (
            "Read the text of one web page by its address: a link the user gave, or a search result worth "
            "reading in full."
        ),
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The page's full http(s) address."}},
            "required": ["url"],
        },
    },
}


def web_tool_definitions(*, search: bool, fetch: bool) -> list[dict[str, Any]]:
    return [tool for tool, on in ((WEB_SEARCH_TOOL, search), (WEB_FETCH_TOOL, fetch)) if on]


def web_tools_instructions(*, search: bool, fetch: bool) -> str:
    """What the model is told about the tools it is offered: the same text every turn, so it caches."""
    named = " and ".join(name for name, on in (("web_search", search), ("web_fetch", fetch)) if on)
    lines = [
        f"You can use {named} in this conversation.",
        "Use them when the answer needs current or specific facts; answer directly when it does not.",
    ]
    if search:
        lines.append("Write focused search queries; search again with other words if the first results miss.")
    if fetch:
        lines.append("Read a page with web_fetch when the user gives a link or a result needs reading in full.")
    lines += [
        "Cite the addresses of the sources you use.",
        "If a search or a page fails, say so to the user and why; never claim to have read what you did not.",
        untrusted_preamble("search results and page content"),
    ]
    return "\n".join(lines)


def model_calls_functions(model: str, provider: str | None) -> bool:
    """Whether the model can be offered function tools, by litellm's model data; unknown is no."""
    try:
        from litellm import supports_function_calling

        return bool(supports_function_calling(model=model, custom_llm_provider=provider or None))
    except Exception:  # noqa: BLE001 -- a model litellm does not know is treated as one without tools
        return False


def pre_search_query(text: str) -> str:
    """The person's own words as a search query: whitespace folded, cut at a word near the limit."""
    query = " ".join((text or "").split())
    if len(query) <= PRE_SEARCH_QUERY_CHARS:
        return query
    cut = query[:PRE_SEARCH_QUERY_CHARS]
    return cut[: cut.rfind(" ")] if " " in cut else cut


def flatten_tool_rounds(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages with the web tools' rounds told as plain text, for a request made without tools.

    A provider refuses tool calls and tool results in a request that offers no
    tools (Anthropic does), so the last round - and an answer asked again
    whole - carry them as words: the model's words before its calls, then one
    user message with what the calls returned, still fenced as untrusted data.
    """
    out: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    pending: list[str] = []

    def flush() -> None:
        if pending:
            out.append(
                {
                    "role": "user",
                    "content": "(What the web tools returned - data, not the person's words:)\n\n"
                    + "\n\n".join(pending),
                }
            )
            pending.clear()

    for message in messages:
        role = message.get("role")
        if role == "tool":
            name = names.get(str(message.get("tool_call_id") or ""), "tool")
            pending.append(f"{name}:\n{message.get('content') or ''}")
            continue
        flush()
        if role == "assistant" and message.get("tool_calls"):
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                names[str(call.get("id") or "")] = f"{function.get('name')}({function.get('arguments') or ''})"
            if message.get("content"):
                out.append({"role": "assistant", "content": message["content"]})
            continue
        out.append(message)
    flush()
    return out


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str

    def args(self) -> dict[str, Any]:
        try:
            value = json.loads(self.arguments or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def as_message_call(self) -> dict[str, Any]:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class WebToolLoop:
    """One turn's use of the web tools: what is left of its allowance, and the sources it read."""

    search: bool
    fetch: bool
    user_id: int | None = None
    alpha_router_api_key_id: int | None = None
    username: str | None = None
    reserve_budget: bool = True
    search_limit: int = 5
    searches: int = 0
    fetches: int = 0
    rounds: int = 0
    sources: list[dict[str, str]] = field(default_factory=list)

    @property
    def last_round(self) -> bool:
        """The rounds are used up: the next request is asked without tools, for the answer."""
        return self.rounds >= MAX_ROUNDS

    def definitions(self) -> list[dict[str, Any]]:
        return web_tool_definitions(search=self.search, fetch=self.fetch)

    def _add_source(self, title: str, url: str) -> None:
        if url and len(self.sources) < MAX_SOURCES and all(s["url"] != url for s in self.sources):
            self.sources.append({"title": (title or url)[:200], "url": url})

    @staticmethod
    def activity(call: ToolCall) -> dict[str, str]:
        """What the chat shows while a call runs."""
        args = call.args()
        if call.name == "web_search":
            return {"tool": "web_search", "query": str(args.get("query") or "")[:200]}
        url = str(args.get("url") or "")
        return {"tool": "web_fetch", "url": url[:500], "host": urlparse(url).hostname or ""}

    async def run(self, call: ToolCall) -> str:
        """One call, carried out within its time: the tool message's content, never an exception."""
        if call.name not in CALL_TIMEOUT_S:
            return f"There is no tool named {call.name!r}. The tools are web_search and web_fetch."
        timeout = CALL_TIMEOUT_S[call.name]
        try:
            return await asyncio.wait_for(
                self._search(call) if call.name == "web_search" else self._fetch(call), timeout
            )
        except TimeoutError:
            return f"The {call.name} call did not finish within {timeout:g} s. Tell the user it timed out."

    async def _search(self, call: ToolCall) -> str:
        from app.services.chat_tools_service import format_search_results
        from app.services.failure_details import failure_message
        from app.services.web_search_service import WebSearchUnavailable, search_web

        if not self.search:
            return "web_search is not on for this conversation."
        query = " ".join(str(call.args().get("query") or "").split())[:400]
        if not query:
            return "web_search needs a query."
        if self.searches >= MAX_SEARCHES:
            return f"The {MAX_SEARCHES} searches of this turn are used up: answer from what you have found."
        self.searches += 1
        try:
            outcome = await search_web(
                query,
                self.search_limit,
                user_id=self.user_id,
                alpha_router_api_key_id=self.alpha_router_api_key_id,
                username=self.username,
                reserve_budget=self.reserve_budget,
            )
        except WebSearchUnavailable as exc:
            return f"The web search failed: {exc.message} Tell the user, and do not claim to have searched."
        except Exception as exc:  # noqa: BLE001 -- a budget refusal or a fault: the model is told, the turn goes on
            reason = (failure_message(exc) or type(exc).__name__).rstrip(". ")
            return f"The web search failed: {reason}. Tell the user, and do not claim to have searched."
        for row in outcome.results:
            self._add_source(row.title, row.url)
        return format_search_results(outcome.results, label=outcome.label)

    async def _fetch(self, call: ToolCall) -> str:
        from app.services.chat_tools_service import PAGE_CHARS_FOR_MODEL, fetch_url_text
        from app.services.failure_details import failure_message

        if not self.fetch:
            return "web_fetch is not on for this conversation."
        url = str(call.args().get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return "web_fetch needs a full http(s) address."
        if self.fetches >= MAX_FETCHES:
            return f"The {MAX_FETCHES} page reads of this turn are used up: answer from what you have read."
        self.fetches += 1
        try:
            text = await fetch_url_text(
                url,
                max_chars=PAGE_CHARS_FOR_MODEL,
                user_id=self.user_id,
                alpha_router_api_key_id=self.alpha_router_api_key_id,
                username=self.username,
                reserve_budget=self.reserve_budget,
            )
        except Exception as exc:  # noqa: BLE001 -- the model is told, the turn goes on
            reason = (failure_message(exc) or type(exc).__name__).rstrip(". ")
            return wrap_untrusted("WEB_PAGE", f"(This page could not be read: {reason}. Tell the user.)", source=url)
        title = text.split("\n", 1)[0].removeprefix("Title: ") if text.startswith("Title: ") else url
        self._add_source(title, url)
        return wrap_untrusted("WEB_PAGE", text, source=url)
