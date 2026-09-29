"""Fit a chat turn into the model's context window, keeping what matters.

A chat longer than the model's window used to go to the provider whole and
come back as a "context length exceeded" error - or, on OpenRouter, be cut in
the middle without anyone saying so. Before the turn is sent, its prompt is
measured with LiteLLM's local tokenizer against the model's window (the
catalog's ``context_length``, else LiteLLM's own figure, else the
administrator's default), and a prompt over its share of the window is made
to fit:

- the system messages (instructions, memories, profile, tools) stay;
- the newest messages stay word for word, the new one always;
- the oldest go first. When the chat has a summary that covers them
  (``chat_summary_service``), the summary stands in for them; otherwise a
  short note tells the model that the start of the chat was left out.

Only plain chat histories are fitted (system, user and assistant messages). A
turn that carries tool calls and their results - the browser agent's steps -
is sent as it came: dropping half of a call and its result breaks the turn.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.memory_settings_service import get_memory_settings
from app.services.provider_stream import count_prompt_tokens

logger = logging.getLogger(__name__)

#: A rough mean for Persian and English text alike, for when the tokenizer cannot count.
CHARS_PER_TOKEN = 3
#: The fewest messages kept word for word, the new one included.
MIN_KEEP = 2

LEFT_OUT_NOTE = (
    "Note from the system: the {count} oldest messages of this conversation were left out to fit the "
    "model's context window. If the user refers to something from them, say that it is no longer in view "
    "and ask them to repeat it."
)


@dataclass
class ContextFit:
    """What fitting did to a turn's messages."""

    messages: list[dict[str, Any]]
    #: Older messages no longer sent word for word.
    dropped: int = 0
    #: How many of those a summary stands in for.
    summarized: int = 0
    window: int | None = None
    budget: int | None = None
    tokens_before: int = 0
    tokens_after: int = 0

    def metadata(self) -> dict[str, int] | None:
        """For the reply's metadata and the stored message: None when nothing was left out."""
        if not self.dropped:
            return None
        return {"dropped": self.dropped, "summarized": self.summarized}


def _text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return str(content or "")


def _chars(message: dict[str, Any]) -> int:
    """Characters as a stand-in for size; an image part counts as a thousand."""
    content = message.get("content")
    if isinstance(content, list):
        size = 0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                size += len(str(part.get("text") or ""))
            elif isinstance(part, dict):
                size += 1_000
        return size
    return len(_text(message))


def model_window(ai_model: Any, model: str, default_tokens: int) -> int | None:
    """The model's context window in tokens: the catalog's, else LiteLLM's, else the default; None when unknown."""
    catalog = getattr(ai_model, "context_length", None)
    if catalog:
        try:
            if int(catalog) > 0:
                return int(catalog)
        except (TypeError, ValueError):
            pass
    try:
        import litellm

        info = litellm.get_model_info(model)
        known = info.get("max_input_tokens") or info.get("max_tokens")
        if known:
            return int(known)
    except Exception:  # noqa: BLE001 -- a model LiteLLM does not know: fall through to the default
        pass
    return int(default_tokens) if default_tokens and int(default_tokens) > 0 else None


def fittable(messages: list[dict[str, Any]], tools: Any) -> bool:
    """A plain chat history: no tool calls, no tool results, no tools offered."""
    if tools:
        return False
    for message in messages:
        if message.get("role") not in ("system", "user", "assistant"):
            return False
        if message.get("tool_calls"):
            return False
    return True


async def fit_turn_to_context(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    ai_model: Any,
    provider_type: str | None,
    model: str,
    tools: Any = None,
    reply_tokens: int | None = None,
    summary: Any = None,
    summary_loader: Callable[[], Awaitable[Any]] | None = None,
) -> ContextFit:
    """``messages`` made to fit the model's window, and what was done to them.

    ``summary`` is the chat's summary when it has a usable one
    (``chat_summary_service.summary_for_turn``): its ``covered`` oldest
    history messages are what it stands in for, and ``text`` is what is sent.
    ``summary_loader`` fetches it only when the turn does not fit. Fitting
    never stops a turn: when it fails, the turn goes as it came.
    """
    try:
        return await _fit(
            db,
            messages,
            ai_model=ai_model,
            provider_type=provider_type,
            model=model,
            tools=tools,
            reply_tokens=reply_tokens,
            summary=summary,
            summary_loader=summary_loader,
        )
    except Exception:
        logger.exception("fitting a chat turn into the model window failed; it is sent as it came")
        return ContextFit(messages=messages)


async def _fit(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    ai_model: Any,
    provider_type: str | None,
    model: str,
    tools: Any,
    reply_tokens: int | None,
    summary: Any,
    summary_loader: Callable[[], Awaitable[Any]] | None,
) -> ContextFit:
    settings = await get_memory_settings(db)
    fit = ContextFit(messages=messages)
    if not settings.get("context_fit_enabled", True) or not fittable(messages, tools):
        return fit
    window = model_window(ai_model, model, int(settings.get("context_default_tokens") or 0))
    if not window:
        return fit
    share = int(settings.get("context_share_percent") or 75)
    budget = window * share // 100
    if reply_tokens:
        budget = min(budget, max(1, window - int(reply_tokens)))
    fit.window, fit.budget = window, budget
    total_chars = sum(_chars(message) for message in messages) or 1
    if total_chars * 3 <= budget:
        # No tokenizer makes more than three tokens of a character: this fits, without counting.
        return fit
    measured = count_prompt_tokens(provider_type=provider_type, model=model, messages=messages)
    tokens = measured or total_chars // CHARS_PER_TOKEN
    fit.tokens_before = fit.tokens_after = tokens
    if tokens <= budget:
        return fit
    if summary is None and summary_loader is not None:
        summary = await summary_loader()

    # Tokens per character of this prompt, to size each message without counting it again.
    per_char = tokens / total_chars
    system = [message for message in messages if message.get("role") == "system"]
    conversation = [message for message in messages if message.get("role") != "system"]
    keep = max(MIN_KEEP, int(settings.get("summary_keep_recent") or 20))
    head, tail = conversation[:-keep], conversation[-keep:]
    if not head:
        head, tail = conversation[:-1], conversation[-1:]

    def size(items: list[dict[str, Any]]) -> float:
        return sum(_chars(message) for message in items) * per_char

    covered = min(int(getattr(summary, "covered", 0) or 0), len(head)) if summary is not None else 0
    note_room = len(LEFT_OUT_NOTE) * per_char + 20
    summary_room = len(str(getattr(summary, "text", "") or "")) * per_char + 20 if covered else 0.0
    fixed = size(system) + size(tail) + summary_room + note_room
    # The oldest go first: the ones a summary covers, then as many more as needed.
    dropped = covered
    rest = head[covered:]
    while rest and fixed + size(rest) > budget:
        rest = rest[1:]
        dropped += 1
    if not dropped and covered == 0:
        # Every older message fits once the newest are set apart: nothing to leave out.
        return fit
    bridge: list[dict[str, Any]] = []
    if covered:
        bridge.append({"role": "system", "content": str(summary.text)})
    if dropped > covered:
        bridge.append({"role": "system", "content": LEFT_OUT_NOTE.format(count=dropped - covered)})
    fitted = [*system, *bridge, *rest, *tail]
    fit.messages = fitted
    fit.dropped = dropped
    fit.summarized = covered
    fit.tokens_after = int(size(fitted))
    logger.info(
        "chat turn fitted to the model window model=%s window=%s budget=%s tokens=%s->%s dropped=%s summarized=%s",
        model,
        window,
        budget,
        tokens,
        fit.tokens_after,
        dropped,
        covered,
    )
    return fit
