"""Token counts when the provider reports no usage: LiteLLM's tokenizer, for every provider type.

``litellm.token_counter`` takes a model and no provider argument. Handing it
``custom_llm_provider`` - as the completion kwargs carry it - made it raise,
so every count for a mapped provider type came back 0: turns from providers
that send no usage were logged with no tokens and no cost, and the running
budget check never fired. These tests use the real tokenizer.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import litellm
import pytest
from sqlalchemy import select

from app.models.logging import RequestLog
from app.models.user import User
from app.services import proxy_service
from app.services.llm_providers import LLM_PROVIDER_MAP
from app.services.provider_stream import (
    NonStreamRetry,
    ProviderAttempt,
    count_completion_tokens,
    count_prompt_tokens,
    estimate_tokens,
)

MESSAGES = [{"role": "user", "content": "Summarize the quarterly report in three bullet points."}]


@pytest.mark.parametrize("provider_type", [*sorted(LLM_PROVIDER_MAP), None, "something-else"])
def test_every_provider_type_is_counted(provider_type):
    prompt, completion = estimate_tokens(
        provider_type=provider_type,
        model="vendor/some-model",
        messages=MESSAGES,
        completion_text="Here are three bullet points.",
    )
    assert prompt > 0
    assert completion > 0


def test_more_text_is_more_tokens():
    short = count_completion_tokens(provider_type="openai", model="gpt-4o", text="one two")
    longer = count_completion_tokens(provider_type="openai", model="gpt-4o", text="one two " * 50)
    assert longer > short > 0
    assert count_prompt_tokens(provider_type="openrouter", model="openai/gpt-4o", messages=MESSAGES) > 0


def test_a_tokenizer_that_fails_counts_nothing(monkeypatch):
    def broken(**_kwargs):
        raise RuntimeError("no tokenizer")

    monkeypatch.setattr(litellm, "token_counter", broken)
    assert count_prompt_tokens(provider_type="openai", model="gpt-4o", messages=MESSAGES) == 0
    assert count_completion_tokens(provider_type="openai", model="gpt-4o", text="hi") == 0
    assert estimate_tokens(provider_type="openai", model="gpt-4o", messages=MESSAGES, completion_text="hi") == (0, 0)


class _Stream:
    def __init__(self, chunks: list) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _text_chunk(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=None)


@pytest.mark.parametrize("provider_type", ["openai", "custom", "openrouter"])
async def test_a_streamed_reply_without_usage_is_estimated(provider_type):
    attempt = ProviderAttempt(
        ai_model=SimpleNamespace(),
        provider_type=provider_type,
        model="vendor/some-model",
        completion_kwargs={"messages": MESSAGES},
        completion_fn=AsyncMock(),
    )
    attempt.response = _Stream([_text_chunk("Three "), _text_chunk("bullet points.")])
    async for chunk in attempt.chunks():
        attempt.record_text(ProviderAttempt.delta_text(chunk))
    attempt.finish()
    assert attempt.prompt_tokens > 0
    assert attempt.completion_tokens > 0


async def test_a_retried_reply_without_usage_is_estimated():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Three bullet points."))], usage=None
    )
    retry = NonStreamRetry(
        ai_model=SimpleNamespace(),
        provider_type="custom",
        model="vendor/some-model",
        completion_kwargs={"messages": MESSAGES, "stream": True},
        completion_fn=AsyncMock(return_value=response),
    )
    await retry.run()
    assert retry.prompt_tokens > 0
    assert retry.completion_tokens > 0


async def test_an_embedding_without_usage_is_counted(db_session, session_factory, monkeypatch):
    user = User(
        username="embed-user",
        email="embed@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
        budget_period_start=datetime.datetime.utcnow().replace(day=1),
    )
    db_session.add(user)
    await db_session.commit()
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(provider_type="openai", input_cost_per_1k=0.001, connection_id=None),
        api_key="test",
        base_url="https://example.invalid",
        provider_type="openai",
        model_id="text-embedding-3-small",
        budget_reservation_id=None,
    )
    response = SimpleNamespace(data=[{"embedding": [0.1, 0.2]}], usage=None, model_dump=lambda: {"data": []})
    monkeypatch.setattr(proxy_service, "AsyncSessionLocal", session_factory)
    with (
        patch.object(proxy_service, "preflight_stream_chat", AsyncMock(return_value=resolved)),
        patch.object(proxy_service, "aembedding", AsyncMock(return_value=response)),
    ):
        await proxy_service.create_embedding(
            db_session,
            {"model": "text-embedding-3-small", "input": "The quarterly report, summarized in a few words."},
            user_id=user.id,
            username=user.username,
            source="user_key",
            skip_budget=True,
            alpha_router_api_key_id=None,
            user_api_key_id=None,
            client_app="test",
            source_ip=None,
        )
    async with session_factory() as fresh:
        log = (await fresh.execute(select(RequestLog))).scalar_one()
    assert log.prompt_tokens > 0
