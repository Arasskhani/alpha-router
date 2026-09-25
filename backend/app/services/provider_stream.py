"""One streamed attempt against the model provider (Phase 4.1).

``stream_chat`` used to inline this: call ``acompletion``, iterate chunks,
merge usage from chunks / the LiteLLM wrapper, estimate tokens when the
provider sent none, and build the ``PendingUsageEvent`` for the ledger.
The same estimation code existed three times (stream, non-stream retry,
final cost). :class:`ProviderAttempt` owns that state for exactly one call
so the loop in ``stream_chat`` only decides *what to do* with each chunk.

The provider function is injected (``completion_fn``) so callers — and the
tests that patch ``proxy_service.acompletion`` — keep their seam.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

import litellm
from litellm.types.llms.openai import ChatCompletionToolParam

from app.models.model_catalog import AIModel
from app.services.llm_providers import litellm_model_for_provider, normalize_model_id
from app.services.provider_utils import (
    close_upstream_stream,
    extract_non_stream_content,
    merge_stream_usage,
    usage_from_chunk,
    usage_from_stream_wrapper,
)
from app.services.usage_accounting_service import PendingUsageEvent, capture_usage_event

logger = logging.getLogger(__name__)


def _tokenizer_model(provider_type: str | None, model: str) -> str:
    """The model name LiteLLM picks a tokenizer by.

    ``token_counter`` takes the model and nothing else: it has no
    ``custom_llm_provider`` argument, and passing one - as the completion
    kwargs carry it - raised TypeError, so every count for a mapped provider
    type came back 0.
    """
    return litellm_model_for_provider(normalize_model_id(model), provider_type)


def count_prompt_tokens(
    *,
    provider_type: str | None,
    model: str,
    messages: list[dict] | None,
    tools: list[dict] | None = None,
) -> int:
    """Prompt tokens by LiteLLM's tokenizer for this model; 0 when it cannot count. Never raises.

    ``tools`` are the function tools the request offers: the provider reads their schemas as prompt.
    """
    try:
        return int(
            litellm.token_counter(
                model=_tokenizer_model(provider_type, model),
                messages=messages or [],
                # OpenAI function tools: the shape LiteLLM's ChatCompletionToolParam describes.
                tools=cast("list[ChatCompletionToolParam] | None", tools or None),
            )
            or 0
        )
    except Exception:
        logger.debug("prompt token count failed for %s", model, exc_info=True)
        return 0


def count_completion_tokens(*, provider_type: str | None, model: str, text: str) -> int:
    """Tokens of generated text by LiteLLM's tokenizer for this model; 0 when it cannot count. Never raises."""
    try:
        return int(litellm.token_counter(model=_tokenizer_model(provider_type, model), text=text) or 0)
    except Exception:
        logger.debug("completion token count failed for %s", model, exc_info=True)
        return 0


def estimate_tokens(
    *,
    provider_type: str | None,
    model: str,
    messages: list[dict] | None,
    completion_text: str,
    tools: list[dict] | None = None,
) -> tuple[int, int]:
    """(prompt, completion) token estimate via LiteLLM's tokenizer; (0, 0) on any failure.

    Used only when the provider reported no usage. ``tools`` as for
    ``count_prompt_tokens``. Never raises: a tokenizer hiccup must not turn a
    billable turn into an error.
    """
    prompt_tokens = count_prompt_tokens(provider_type=provider_type, model=model, messages=messages, tools=tools)
    completion_tokens = count_completion_tokens(provider_type=provider_type, model=model, text=completion_text)
    if not prompt_tokens or (completion_text and not completion_tokens):
        return 0, 0
    return prompt_tokens, completion_tokens


class ProviderAttempt:
    """State of one ``acompletion(stream=True)`` call from start to settlement."""

    def __init__(
        self,
        *,
        ai_model: AIModel,
        provider_type: str,
        model: str,
        completion_kwargs: dict,
        completion_fn: Callable[..., Awaitable[Any]],
    ) -> None:
        self.ai_model = ai_model
        self.provider_type = provider_type
        self.model = model
        self.completion_kwargs = completion_kwargs
        self._completion_fn = completion_fn
        self.messages: list[dict] = list(completion_kwargs.get("messages", []))
        #: Function tools the request offers (the browser extension's agent); None otherwise.
        self.tools: list[dict] | None = completion_kwargs.get("tools") or None
        self.started_at: datetime.datetime = datetime.datetime.utcnow()
        self.response: Any = None
        self.last_usage_chunk: Any = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cached_tokens = 0
        self.content = ""
        self.last_chunk_at: float | None = None
        #: The model's tool calls as they stream in, by index: name and arguments so far.
        self._tool_calls: dict[int, dict[str, str]] = {}
        #: Characters of tool-call names and arguments received, for the running budget check.
        self.tool_call_chars = 0

    async def start(self) -> None:
        self.response = await self._completion_fn(**self.completion_kwargs)

    async def chunks(self) -> AsyncIterator[Any]:
        """Iterate provider chunks, recording usage and text as they arrive."""
        async for chunk in self.response:
            pt, ct, cache = usage_from_chunk(chunk)
            chunk_usage = chunk.get("usage") if isinstance(chunk, dict) else getattr(chunk, "usage", None)
            if pt or ct or cache or chunk_usage is not None:
                self.last_usage_chunk = chunk
            self.prompt_tokens, self.completion_tokens, self.cached_tokens = merge_stream_usage(
                self.prompt_tokens, self.completion_tokens, self.cached_tokens, pt, ct, cache
            )
            self._record_tool_calls(chunk)
            yield chunk

    @staticmethod
    def delta_text(chunk: Any) -> str:
        if chunk.choices and chunk.choices[0].delta.content:
            return chunk.choices[0].delta.content
        return ""

    def record_text(self, delta: str) -> None:
        self.content += delta

    def _record_tool_calls(self, chunk: Any) -> None:
        """Add a chunk's tool-call deltas: the first names a call, the rest carry its arguments in pieces."""
        try:
            deltas = chunk.choices[0].delta.tool_calls if chunk.choices else None
        except (AttributeError, IndexError, TypeError):
            return
        for position, delta in enumerate(deltas or ()):
            index = _field(delta, "index")
            call = self._tool_calls.setdefault(
                index if isinstance(index, int) else position, {"name": "", "arguments": ""}
            )
            function = _field(delta, "function")
            name = _field(function, "name")
            arguments = _field(function, "arguments")
            if isinstance(name, str) and name:
                call["name"] += name
                self.tool_call_chars += len(name)
            if isinstance(arguments, str) and arguments:
                call["arguments"] += arguments
                self.tool_call_chars += len(arguments)

    @property
    def has_tool_calls(self) -> bool:
        """Whether the model answered with tool calls (an answer without words, and not an empty one)."""
        return any(call["name"] or call["arguments"] for call in self._tool_calls.values())

    @property
    def tool_call_text(self) -> str:
        """The tool calls as text, for estimating what they cost: the provider bills them as output."""
        return "\n".join(f"{call['name']}({call['arguments']})" for _, call in sorted(self._tool_calls.items()))

    @property
    def billable_text(self) -> str:
        """Everything the model generated in this attempt: its words, then its tool calls."""
        calls = self.tool_call_text
        return f"{self.content}\n{calls}" if self.content and calls else (self.content or calls)

    async def close(self) -> None:
        """Stop consuming upstream (client gone): every further chunk is billed for nobody."""
        await close_upstream_stream(self.response)

    def finish(self) -> None:
        """Merge the wrapper's final usage; estimate when the provider sent none."""
        pt, ct, cache = usage_from_stream_wrapper(self.response)
        self.prompt_tokens, self.completion_tokens, self.cached_tokens = merge_stream_usage(
            self.prompt_tokens, self.completion_tokens, self.cached_tokens, pt, ct, cache
        )
        billable = self.billable_text
        if self.prompt_tokens == 0 and billable:
            est_prompt, est_completion = estimate_tokens(
                provider_type=self.provider_type,
                model=self.model,
                messages=self.messages,
                completion_text=billable,
                tools=self.tools,
            )
            self.prompt_tokens, self.completion_tokens = est_prompt, est_completion

    def usage_event(
        self,
        *,
        attempt_index: int,
        status: str,
        error_message: str | None = None,
        completion: str | None = None,
        operation_name: str = "chat_completion",
    ) -> PendingUsageEvent:
        return capture_usage_event(
            self.response,
            fallback_response=self.last_usage_chunk,
            ai_model=self.ai_model,
            provider_type=self.provider_type,
            service_type="llm",
            operation_name=operation_name,
            model_id=self.model,
            attempt_index=attempt_index,
            status=status,
            started_at=self.started_at,
            completed_at=datetime.datetime.utcnow(),
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cached_tokens=self.cached_tokens,
            prompt=self.messages,
            completion=self.billable_text if completion is None else completion,
            error_message=error_message,
        )


def _field(value: Any, name: str) -> Any:
    """``value.name`` or ``value[name]``: LiteLLM hands tool-call deltas over as objects, some providers as dicts."""
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


class NonStreamRetry:
    """The one-shot ``stream=False`` retry after a streaming read failure.

    Some providers (OpenRouter Auto Router in particular) drop a stream body
    but answer the same request fine without streaming. The retry re-sends the
    exact prompt once; its outcome is booked as a separate ``chat_completion_retry``
    usage event so the ledger shows both attempts.
    """

    def __init__(
        self,
        *,
        ai_model: AIModel,
        provider_type: str,
        model: str,
        completion_kwargs: dict,
        completion_fn: Callable[..., Awaitable[Any]],
    ) -> None:
        self.ai_model = ai_model
        self.provider_type = provider_type
        self.model = model
        self.kwargs = dict(completion_kwargs)
        self.kwargs["stream"] = False
        self.kwargs.pop("stream_options", None)
        self._completion_fn = completion_fn
        self.started_at = datetime.datetime.utcnow()
        self.content = ""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cached_tokens = 0
        self._response: Any = None

    async def run(self) -> None:
        """Perform the call; raises the provider error when it fails too."""
        response = await self._completion_fn(**self.kwargs)
        content, (pt, ct, cache) = extract_non_stream_content(response)
        if pt == 0 and content:
            est_prompt, est_completion = estimate_tokens(
                provider_type=self.provider_type,
                model=self.model,
                messages=self.kwargs.get("messages"),
                completion_text=content,
            )
            if est_prompt:
                pt, ct = est_prompt, est_completion
        self.content = content
        self.prompt_tokens, self.completion_tokens, self.cached_tokens = pt, ct, cache
        self._response = response

    def usage_event(self, *, attempt_index: int, status: str, error_message: str | None = None) -> PendingUsageEvent:
        return capture_usage_event(
            self._response,
            ai_model=self.ai_model,
            provider_type=self.provider_type,
            service_type="llm",
            operation_name="chat_completion_retry",
            model_id=self.model,
            attempt_index=attempt_index,
            status=status,
            started_at=self.started_at,
            completed_at=datetime.datetime.utcnow(),
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cached_tokens=self.cached_tokens,
            prompt=self.kwargs.get("messages"),
            completion=self.content if status == "succeeded" else "",
            error_message=error_message,
        )
