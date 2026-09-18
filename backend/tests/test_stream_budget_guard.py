"""A turn is stopped when it outgrows the budget reserved for it.

Budget is checked at admission and nowhere else, and the hold for a chat turn is
an estimate: ``reservation_hold_usd`` sizes the completion side from
``max_tokens``, which reaches ``completion_kwargs`` only on the agent path. An
ordinary chat turn therefore asks the provider for an unbounded completion
against a hold that assumed a bounded one.

There is no honest way to fix that with a better estimate - the catalog carries
``context_length`` and no ``max_output_tokens``, so there is no number to send -
and capping output would truncate answers that work today. The control that
matches the problem is to watch the running cost and stop when it passes the
hold, which is also what makes Stop mean "stop generating" rather than "stop
showing me".
"""

from __future__ import annotations

import inspect

from app.services import proxy_service


def test_the_hold_amount_reaches_the_stream():
    """The guard cannot exist without knowing what was reserved."""

    from app.services.chat_turn_context import TurnContext

    assert "budget_hold_usd" in proxy_service.ResolvedStreamContext.__dataclass_fields__
    assert "budget_hold_usd" in TurnContext.__dataclass_fields__


class _Model:
    """Priced at $1 per 1k completion tokens, nothing for the prompt."""

    id = 1
    external_id = "test/model"
    provider_type = "openai"


def _decide(monkeypatch, *, completion_tokens: int, cost: float, hold: float | None) -> bool:
    monkeypatch.setattr(
        proxy_service,
        "estimate_tokens",
        lambda **_kwargs: (10, completion_tokens),
    )
    monkeypatch.setattr(proxy_service, "_compute_token_cost_usd", lambda *_a, **_k: cost)
    return proxy_service.turn_cost_exceeds_hold(
        ai_model=_Model(),
        provider_type="openai",
        model="test/model",
        messages=[{"role": "user", "content": "hello"}],
        completion_text="x" * 100,
        hold_usd=hold,
    )


def test_a_turn_inside_its_hold_keeps_going(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=100, cost=0.004, hold=0.01) is False


def test_a_turn_past_its_hold_is_stopped(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=5000, cost=0.02, hold=0.01) is True


def test_exactly_at_the_hold_is_not_over(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=100, cost=0.01, hold=0.01) is False


def test_an_unbudgeted_turn_is_never_stopped(monkeypatch):
    assert _decide(monkeypatch, completion_tokens=5000, cost=99.0, hold=None) is False
    assert _decide(monkeypatch, completion_tokens=5000, cost=99.0, hold=0.0) is False


def test_a_tokenizer_that_cannot_count_does_not_stop_the_turn(monkeypatch):
    """Never kill a paid-for reply on a guess."""

    assert _decide(monkeypatch, completion_tokens=0, cost=99.0, hold=0.01) is False


def test_an_unpriced_model_does_not_stop_the_turn(monkeypatch):
    monkeypatch.setattr(proxy_service, "estimate_tokens", lambda **_k: (10, 5000))
    assert (
        proxy_service.turn_cost_exceeds_hold(
            ai_model=None,
            provider_type="openai",
            model="test/model",
            messages=[],
            completion_text="x",
            hold_usd=0.01,
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
