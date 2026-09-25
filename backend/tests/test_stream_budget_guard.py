"""A turn is stopped when it outgrows what its budget can bear.

Budget is checked at admission, and the hold for a chat turn is an estimate:
``reservation_hold_usd`` sizes the completion side from ``max_tokens``, which
reaches ``completion_kwargs`` only on the agent path. An ordinary chat turn
therefore asks the provider for an unbounded completion.

There is no honest way to fix that with a better estimate - the catalog carries
``context_length`` and no ``max_output_tokens``, so there is no number to send -
and capping output would truncate answers that work today. The control that
matches the problem is to watch the running cost and stop when it passes what
the budget had left when the turn was admitted - not the hold, which only
guesses at the reply's length - which is also what makes Stop mean "stop
generating" rather than "stop showing me".
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import chat_turn_context, proxy_service, turn_settlement


def test_the_ceiling_reaches_the_stream():
    """The guard cannot exist without knowing what the turn may spend."""

    from app.services.chat_turn_context import TurnContext

    assert "budget_ceiling_usd" in proxy_service.ResolvedStreamContext.__dataclass_fields__
    assert "budget_ceiling_usd" in TurnContext.__dataclass_fields__


class _Model:
    """Priced at $1 per 1k completion tokens, nothing for the prompt."""

    id = 1
    external_id = "test/model"
    provider_type = "openai"


def _decide(
    monkeypatch, *, completion_tokens: int, cost: float, ceiling: float | None, prompt_tokens: int = 10
) -> bool:
    monkeypatch.setattr(proxy_service, "count_completion_tokens", lambda **_kwargs: completion_tokens)
    monkeypatch.setattr(proxy_service, "_compute_token_cost_usd", lambda *_a, **_k: cost)
    return proxy_service.turn_cost_exceeds_ceiling(
        ai_model=_Model(),
        provider_type="openai",
        model="test/model",
        messages=[{"role": "user", "content": "hello"}],
        prompt_tokens=prompt_tokens,
        completion_text="x" * 100,
        ceiling_usd=ceiling,
    )


def test_a_turn_inside_its_ceiling_keeps_going(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=100, cost=0.004, ceiling=0.01) is False


def test_a_turn_past_its_ceiling_is_stopped(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=5000, cost=0.02, ceiling=0.01) is True


def test_exactly_at_the_ceiling_is_not_over(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=100, cost=0.01, ceiling=0.01) is False


def test_an_unbudgeted_turn_is_never_stopped(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=5000, cost=99.0, ceiling=None) is False
    assert _decide(monkeypatch, completion_tokens=5000, cost=99.0, ceiling=0.0) is False


def test_a_tokenizer_that_cannot_count_does_not_stop_the_turn(monkeypatch):
    """Never kill a paid-for reply on a guess."""

    assert _decide(monkeypatch, completion_tokens=0, cost=99.0, ceiling=0.01) is False
    assert _decide(monkeypatch, completion_tokens=5000, cost=99.0, ceiling=0.01, prompt_tokens=0) is False


def test_an_unpriced_model_does_not_stop_the_turn(monkeypatch):
    monkeypatch.setattr(proxy_service, "count_completion_tokens", lambda **_k: 5000)
    assert (
        proxy_service.turn_cost_exceeds_ceiling(
            ai_model=None,
            provider_type="openai",
            model="test/model",
            messages=[],
            prompt_tokens=10,
            completion_text="x",
            ceiling_usd=0.01,
        )
        is False
    )


def test_the_guard_runs_inside_the_chunk_loop():
    source = inspect.getsource(proxy_service.stream_chat)
    assert "_over_budget(collected_content)" in source
    assert "BUDGET_RECHECK_CHARS" in source


def test_going_over_closes_the_upstream_stream():
    """Leaving it open means paying the provider for tokens nobody receives."""

    source = inspect.getsource(proxy_service.stream_chat)
    guard = source[source.index("if _over_budget(collected_content):") :]
    guard = guard[: guard.index("attempt.finish()")]
    assert "await attempt.close()" in guard
    assert "_sse_error_frame(BUDGET_EXCEEDED_MESSAGE)" in guard
    assert "break" in guard


def test_the_outcome_is_recorded_as_a_budget_stop():
    source = inspect.getsource(proxy_service.stream_chat)
    assert 'error_code = "budget_exceeded"' in source


def test_the_message_says_what_happened_and_what_to_do():
    message = proxy_service.BUDGET_EXCEEDED_MESSAGE
    assert "budget" in message.lower()
    assert "billed" in message.lower(), "the user is charged for what was generated; say so"
    assert "administrator" in message.lower(), "tell them who can change it"


def test_the_recheck_interval_is_not_per_chunk():
    """Re-pricing every chunk would run the tokenizer thousands of times a turn."""

    assert proxy_service.BUDGET_RECHECK_CHARS >= 100


# --- in a running turn -----------------------------------------------------------------


class _Chunk:
    def __init__(self, text: str) -> None:
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=text))]


async def _stream(monkeypatch, *, ceiling: float | None, chunks: int = 60) -> dict:
    """Stream ``chunks`` pieces of 100 characters against ``ceiling``, at $0.001 per completion character."""
    counted = {"prompt": 0}

    def count_prompt(**_kwargs) -> int:
        counted["prompt"] += 1
        return 10

    monkeypatch.setattr(proxy_service, "count_prompt_tokens", count_prompt)
    monkeypatch.setattr(proxy_service, "count_completion_tokens", lambda *, text, **_k: len(text))
    monkeypatch.setattr(
        proxy_service, "_compute_token_cost_usd", lambda *_a, completion_tokens=0, **_k: completion_tokens * 0.001
    )

    async def fake_acompletion(**_kwargs):
        async def gen():
            for _ in range(chunks):
                yield _Chunk("y" * 100)

        return gen()

    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(provider_type="openai", external_id="test/model", display_name="Test"),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openai",
        model_id="test/model",
        budget_ceiling_usd=ceiling,
    )
    logged: dict = {}

    async def capture_log(*_args, **kwargs):
        logged.update(kwargs)

    fake_db = AsyncMock()
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    passthrough = AsyncMock(side_effect=lambda db, m, *_a, **_k: m)
    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(chat_turn_context, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(turn_settlement, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(chat_turn_context, "augment_messages_with_tools", passthrough),
        patch.object(chat_turn_context, "augment_messages_with_profile", passthrough),
        patch.object(chat_turn_context, "augment_messages_with_memory", passthrough),
        patch.object(chat_turn_context, "augment_messages_with_project_context", passthrough),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(0, 0, 0)),
        patch.object(proxy_service, "_serialize_stream_chunk", return_value="{}"),
        patch.object(turn_settlement, "log_usage", side_effect=capture_log),
    ):
        body = {"model": "test/model", "messages": [{"role": "user", "content": "Write a long story"}]}
        frames = [
            frame
            async for frame in proxy_service.stream_chat(
                request, body, user_id=1, username="u", source="alpha_router_chat", skip_budget=False, resolved=resolved
            )
        ]
    return {"frames": b"".join(frames).decode(), "log": logged, "prompt_counts": counted["prompt"]}


async def test_a_reply_the_budget_cannot_bear_is_stopped(monkeypatch):
    run = await _stream(monkeypatch, ceiling=2.0)
    assert proxy_service.BUDGET_EXCEEDED_MESSAGE in run["frames"]
    assert run["log"]["error_code"] == "budget_exceeded"


async def test_a_reply_inside_the_budget_runs_to_the_end(monkeypatch):
    run = await _stream(monkeypatch, ceiling=100.0)
    assert proxy_service.BUDGET_EXCEEDED_MESSAGE not in run["frames"]
    assert run["log"]["success"] is True


async def test_nothing_stops_a_turn_without_a_ceiling(monkeypatch):
    run = await _stream(monkeypatch, ceiling=None)
    assert proxy_service.BUDGET_EXCEEDED_MESSAGE not in run["frames"]
    assert run["prompt_counts"] == 0


async def test_the_prompt_is_counted_once_a_turn(monkeypatch):
    """Counting a long conversation again at every check would stall the server."""

    run = await _stream(monkeypatch, ceiling=100.0)
    assert run["prompt_counts"] == 1
