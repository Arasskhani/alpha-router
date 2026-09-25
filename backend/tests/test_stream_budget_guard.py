"""A turn is stopped when it outgrows what its budget can bear.

Budget is checked at admission, and the hold for a chat turn is an estimate:
``reservation_hold_usd`` sizes the completion side from ``max_tokens``, which
reaches ``completion_kwargs`` only on the agent path. An ordinary chat turn
therefore asks the provider for an unbounded completion.

There is no honest way to fix that with a better estimate - the catalog carries
``context_length`` and no ``max_output_tokens``, so there is no number to send -
and capping output would truncate answers that work today. The control that
matches the problem is to watch the running cost. A reply that outgrows its
hold, which only guesses at the reply's length, grows the hold out of the
budget left, and is stopped only when the budget left cannot bear it - which is
also what makes Stop mean "stop generating" rather than "stop showing me".
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import chat_turn_context, proxy_service, turn_settlement


def test_the_hold_reaches_the_stream():
    """The guard cannot exist without knowing what the turn has claimed."""

    from app.services.chat_turn_context import TurnContext

    assert "budget_hold_usd" in proxy_service.ResolvedStreamContext.__dataclass_fields__
    assert "budget_hold_usd" in TurnContext.__dataclass_fields__


class _Model:
    """Priced at $1 per 1k completion tokens, nothing for the prompt."""

    id = 1
    external_id = "test/model"
    provider_type = "openai"


async def _grow(
    monkeypatch,
    *,
    completion_tokens: int,
    cost: float,
    hold: float,
    granted: float | None | Exception = None,
    prompt_tokens: int = 10,
    ai_model=None,
) -> tuple[float | None, AsyncMock]:
    """What ``grow_hold_to_turn_cost`` makes of a turn that has cost ``cost``; the budget answers ``granted``."""
    monkeypatch.setattr(proxy_service, "count_completion_tokens", lambda **_kwargs: completion_tokens)
    monkeypatch.setattr(proxy_service, "_compute_token_cost_usd", lambda *_a, **_k: cost)
    extend = AsyncMock(side_effect=granted) if isinstance(granted, Exception) else AsyncMock(return_value=granted)
    monkeypatch.setattr(proxy_service, "extend_hold", extend)
    result = await proxy_service.grow_hold_to_turn_cost(
        ai_model=ai_model or _Model(),
        provider_type="openai",
        model="test/model",
        messages=[{"role": "user", "content": "hello"}],
        prompt_tokens=prompt_tokens,
        completion_text="x" * 100,
        hold_usd=hold,
        reservation_id="hold-1",
    )
    return result, extend


async def test_a_turn_inside_its_hold_does_not_ask_the_budget(monkeypatch):
    result, extend = await _grow(monkeypatch, completion_tokens=100, cost=0.004, hold=0.01)
    assert result == 0.01
    extend.assert_not_awaited()


async def test_exactly_at_the_hold_is_not_over(monkeypatch):
    result, extend = await _grow(monkeypatch, completion_tokens=100, cost=0.01, hold=0.01)
    assert result == 0.01
    extend.assert_not_awaited()


async def test_a_turn_past_its_hold_grows_it(monkeypatch):
    """Outgrowing the hold is not being over budget: the hold only guessed at the reply's length."""

    result, extend = await _grow(monkeypatch, completion_tokens=5000, cost=0.02, hold=0.01, granted=0.04)
    assert result == 0.04
    extend.assert_awaited_once_with("hold-1", 0.02)


async def test_a_turn_the_budget_left_cannot_bear_is_stopped(monkeypatch):
    result, _extend = await _grow(monkeypatch, completion_tokens=5000, cost=0.02, hold=0.01, granted=None)
    assert result is None


async def test_a_tokenizer_that_cannot_count_does_not_stop_the_turn(monkeypatch):
    """Never kill a paid-for reply on a guess."""

    for completion_tokens, prompt_tokens in ((0, 10), (5000, 0)):
        result, extend = await _grow(
            monkeypatch, completion_tokens=completion_tokens, cost=99.0, hold=0.01, prompt_tokens=prompt_tokens
        )
        assert result == 0.01
        extend.assert_not_awaited()


async def test_an_unpriced_model_does_not_stop_the_turn(monkeypatch):
    monkeypatch.setattr(proxy_service, "count_completion_tokens", lambda **_k: 5000)
    extend = AsyncMock(return_value=None)
    monkeypatch.setattr(proxy_service, "extend_hold", extend)
    result = await proxy_service.grow_hold_to_turn_cost(
        ai_model=None,
        provider_type="openai",
        model="test/model",
        messages=[],
        prompt_tokens=10,
        completion_text="x",
        hold_usd=0.01,
        reservation_id="hold-1",
    )
    assert result == 0.01
    extend.assert_not_awaited()


async def test_a_budget_that_cannot_be_read_does_not_stop_the_turn(monkeypatch):
    """A database error is not an empty budget; the next check asks again."""

    result, extend = await _grow(
        monkeypatch, completion_tokens=5000, cost=0.02, hold=0.01, granted=RuntimeError("database unavailable")
    )
    assert result == 0.01
    extend.assert_awaited_once()


def test_the_guard_runs_inside_the_chunk_loop():
    source = inspect.getsource(proxy_service.stream_chat)
    assert "_hold_covering(collected_content, budget_hold_usd)" in source
    assert "BUDGET_RECHECK_CHARS" in source


def test_going_over_closes_the_upstream_stream():
    """Leaving it open means paying the provider for tokens nobody receives."""

    source = inspect.getsource(proxy_service.stream_chat)
    guard = source[source.index("if budget_hold_usd is None:") :]
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


async def _stream(monkeypatch, *, hold: float | None, budget: float = 0.0, chunks: int = 60) -> dict:
    """Stream ``chunks`` pieces of 100 characters, at $0.001 per completion character, against ``hold``.

    The hold may grow to ``budget``, what the turn's budget can bear; asking
    for more than that is refused.
    """
    counted = {"prompt": 0}
    asked: list[float] = []

    def count_prompt(**_kwargs) -> int:
        counted["prompt"] += 1
        return 10

    async def extend_hold(_reservation_id, needed_usd):
        asked.append(needed_usd)
        return None if needed_usd > budget else min(2 * needed_usd, budget)

    monkeypatch.setattr(proxy_service, "count_prompt_tokens", count_prompt)
    monkeypatch.setattr(proxy_service, "count_completion_tokens", lambda *, text, **_k: len(text))
    monkeypatch.setattr(
        proxy_service, "_compute_token_cost_usd", lambda *_a, completion_tokens=0, **_k: completion_tokens * 0.001
    )
    monkeypatch.setattr(proxy_service, "extend_hold", extend_hold)

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
        budget_reservation_id="hold-1",
        budget_hold_usd=hold,
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
    return {"frames": b"".join(frames).decode(), "log": logged, "prompt_counts": counted["prompt"], "asked": asked}


async def test_a_reply_the_budget_cannot_bear_is_stopped(monkeypatch):
    # The reply costs $6.00; its $0.50 hold may grow to the $2.00 the budget can bear.
    run = await _stream(monkeypatch, hold=0.5, budget=2.0)
    assert proxy_service.BUDGET_EXCEEDED_MESSAGE in run["frames"]
    assert run["log"]["error_code"] == "budget_exceeded"
    assert run["asked"][-1] > 2.0, "stopped only once the reply cost more than the budget can bear"


async def test_a_reply_that_outgrows_its_hold_runs_to_the_end(monkeypatch):
    run = await _stream(monkeypatch, hold=0.5, budget=100.0)
    assert proxy_service.BUDGET_EXCEEDED_MESSAGE not in run["frames"]
    assert run["log"]["success"] is True
    # Fifteen checks, but the hold grows ahead of the reply: only a few reach the database.
    assert 0 < len(run["asked"]) <= 4


async def test_a_reply_inside_its_hold_never_asks_the_budget(monkeypatch):
    run = await _stream(monkeypatch, hold=100.0)
    assert run["log"]["success"] is True
    assert run["asked"] == []


async def test_nothing_stops_a_turn_without_a_hold(monkeypatch):
    run = await _stream(monkeypatch, hold=None)
    assert proxy_service.BUDGET_EXCEEDED_MESSAGE not in run["frames"]
    assert run["prompt_counts"] == 0
    assert run["asked"] == []


async def test_the_prompt_is_counted_once_a_turn(monkeypatch):
    """Counting a long conversation again at every check would stall the server."""

    run = await _stream(monkeypatch, hold=0.5, budget=100.0)
    assert run["prompt_counts"] == 1
