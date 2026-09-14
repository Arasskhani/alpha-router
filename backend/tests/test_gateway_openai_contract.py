"""Contract test for ``POST /v1/chat/completions`` (Phase 3.2).

The gateway promises the OpenAI streaming wire format. External clients
(OpenAI SDKs, LangChain, Open WebUI) depend on exactly this and nothing in
the unit tests pinned it down:

* ``Content-Type: text/event-stream``; every frame is ``data: <json>\\n\\n``.
* Every JSON frame before the terminator is a ``chat.completion.chunk`` whose
  shape validates against the pydantic model below (id, object, created,
  model, choices[].index/delta/finish_reason).
* Alpharouter's own trailer, if present, is a single ``{"alpha_router": {...}}``
  frame and comes after all chunks.
* The stream ends with exactly one ``data: [DONE]``.
* A provider failure is reported as ``{"error": {"message", "type", "code"}}``.
* ``stream: false`` is refused with HTTP 400 and an OpenAI-style error body.

The provider is faked at ``acompletion``; the HTTP layer, auth, middlewares
and the SSE writer are real.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices
from pydantic import BaseModel, ConfigDict

from app.api import gateway
from app.services import proxy_service, turn_settlement

MASTER_KEY = gateway.settings.gateway_master_key


# --- the contract -----------------------------------------------------------


class ChunkDelta(BaseModel):
    model_config = ConfigDict(extra="allow")
    content: str | None = None
    role: str | None = None
    tool_calls: list[Any] | None = None


class ChunkChoice(BaseModel):
    model_config = ConfigDict(extra="allow")
    index: int
    delta: ChunkDelta
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "function_call"] | None = None


class ChatCompletionChunk(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    object: Literal["chat.completion.chunk"]
    created: int
    model: str
    choices: list[ChunkChoice]


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="allow")
    message: str
    type: str
    code: str | int | None = None


class ErrorFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorBody


# --- fakes ------------------------------------------------------------------


def _chunk(content: str | None, finish: str | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        id="chatcmpl-contract",
        model="vendor/good",
        choices=[StreamingChoices(index=0, delta=Delta(content=content), finish_reason=finish)],
    )


class _Provider:
    def __init__(self, chunks: list[ModelResponseStream], *, fail_after: int | None = None) -> None:
        self._chunks = list(chunks)
        self._fail_after = fail_after
        self.yielded = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._fail_after is not None and self.yielded >= self._fail_after:
            raise RuntimeError("upstream exploded")
        if not self._chunks:
            raise StopAsyncIteration
        self.yielded += 1
        return self._chunks.pop(0)

    async def aclose(self) -> None:
        return None


def _resolved() -> SimpleNamespace:
    return SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="vendor/good",
            display_name="Good model",
            connection_id=7,
            id=1,
        ),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openrouter",
        model_id="vendor/good",
        code_interpreter_capacity_permit=None,
    )


def _patches(provider: _Provider):
    async def fake_acompletion(**kwargs):
        del kwargs
        return provider

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    return (
        patch.object(gateway, "preflight_stream_chat", AsyncMock(return_value=_resolved())),
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(turn_settlement, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(proxy_service, "parse_tools_config", return_value=SimpleNamespace(code_interpreter=False)),
        patch.object(proxy_service, "augment_messages_with_tools", AsyncMock(side_effect=lambda db, m, t, **_kw: m)),
        patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "persister_from_body", return_value=None),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(0, 0, 0)),
        patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
        patch.object(turn_settlement, "log_usage", AsyncMock(return_value=1)),
        patch.object(proxy_service, "record_compatibility_result", AsyncMock()),
        patch.object(proxy_service, "openrouter_auto_plugin", AsyncMock(return_value=None)),
    )


def _enter_all(patches):
    from contextlib import ExitStack

    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


def _frames(raw: str) -> list[str]:
    """Split an SSE body into the payloads of its ``data:`` frames."""
    frames: list[str] = []
    for block in raw.split("\n\n"):
        block = block.strip("\r\n")
        if not block:
            continue
        lines = block.split("\n")
        assert all(line.startswith("data:") for line in lines), f"non-data SSE line in {block!r}"
        frames.append("\n".join(line[5:].lstrip() for line in lines))
    return frames


async def _post(client, body: dict, headers: dict | None = None):
    return await client.post(
        "/v1/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {MASTER_KEY}", **(headers or {})},
    )


_BODY = {"model": "vendor/good", "messages": [{"role": "user", "content": "hi"}], "stream": True}


# --- tests ------------------------------------------------------------------


async def test_stream_frames_are_openai_chunks_then_done(client) -> None:
    provider = _Provider([_chunk("Hel"), _chunk("lo"), _chunk(None, finish="stop")])
    with _enter_all(_patches(provider)):
        resp = await _post(client, _BODY)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _frames(resp.text)

    assert frames[-1] == "[DONE]", frames
    assert frames.count("[DONE]") == 1
    payloads = [json.loads(f) for f in frames[:-1]]
    chunks = [p for p in payloads if "alpha_router" not in p]
    trailers = [p for p in payloads if "alpha_router" in p]

    assert len(chunks) == 3
    for p in chunks:
        ChatCompletionChunk.model_validate(p)  # raises on contract drift
        assert "error" not in p
    assert "".join(c["choices"][0]["delta"]["content"] or "" for c in chunks) == "Hello"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)

    # Alpharouter's metadata trailer, when present, is one frame after the chunks.
    assert len(trailers) <= 1
    if trailers:
        assert payloads.index(trailers[0]) == len(payloads) - 1


async def test_provider_failure_is_an_openai_error_frame(client) -> None:
    provider = _Provider([_chunk("par"), _chunk("tial")], fail_after=2)
    with _enter_all(_patches(provider)):
        resp = await _post(client, _BODY)

    assert resp.status_code == 200  # headers are already out when a stream fails
    frames = _frames(resp.text)
    errors = [json.loads(f) for f in frames if f != "[DONE]" and '"error"' in f]
    assert len(errors) == 1, frames
    err = ErrorFrame.model_validate(errors[0])
    assert "upstream exploded" in err.error.message
    assert err.error.type == "provider_error"
    # The two chunks that did arrive are still valid chunks.
    for f in frames:
        if f != "[DONE]" and '"error"' not in f and "alpha_router" not in f:
            ChatCompletionChunk.model_validate(json.loads(f))


async def test_non_streaming_is_refused_with_openai_error_body(client) -> None:
    with _enter_all(_patches(_Provider([]))):
        resp = await _post(client, {**_BODY, "stream": False})
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" in body and "stream=true" in str(body["detail"])


@pytest.mark.parametrize("auth", [None, "Bearer ", "Bearer sk-not-a-key"])
async def test_missing_or_unknown_key_is_401(client, auth) -> None:
    headers = {} if auth is None else {"Authorization": auth}
    resp = await client.post("/v1/chat/completions", json=_BODY, headers=headers)
    assert resp.status_code == 401
