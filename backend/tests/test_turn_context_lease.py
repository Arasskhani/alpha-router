"""The Code Interpreter permit and the budget hold survive a failed preparation.

``build_turn_context`` takes both at preflight and hands them to the streaming
loop, which settles them in its ``finally``. Between the two, preparation can
still fail — and then nothing downstream exists to give them back. Each escape
has to release them exactly once: leaking the permit blocks a concurrency slot
until its TTL, and releasing it twice frees a slot another turn is holding.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import chat_turn_context
from app.services.chat_turn_context import CapacityLease, build_turn_context


def _resolved() -> SimpleNamespace:
    return SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="vendor/good",
            display_name="Good model",
            connection_id=7,
        ),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openrouter",
        model_id="vendor/good",
        budget_reservation_id="hold-1",
        code_interpreter_capacity_permit=SimpleNamespace(lease_id="lease-1", subject="user:1"),
        code_interpreter_workspace_files=None,
        agent_turn=None,
    )


async def test_abandon_is_idempotent() -> None:
    lease = CapacityLease(permit=SimpleNamespace(lease_id="l"), stream_reservation_id=None)
    with patch.object(chat_turn_context, "release_code_interpreter_turn", AsyncMock()) as release:
        await lease.abandon("first")
        await lease.abandon("second")
    assert release.await_count == 1


async def test_preparation_failure_outside_the_augment_blocks_still_releases(db_session) -> None:
    """A raise between the lease and the augmentation used to leak both resources."""
    body = {"model": "vendor/good", "messages": [{"role": "user", "content": "hi"}]}
    release_permit = AsyncMock()
    release_hold = AsyncMock()
    fake_db = AsyncMock()
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(chat_turn_context, "release_code_interpreter_turn", release_permit),
        patch.object(chat_turn_context, "release", release_hold),
        patch.object(chat_turn_context, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(
            chat_turn_context,
            "apply_litellm_provider_kwargs",
            side_effect=RuntimeError("provider kwargs blew up"),
        ),
        pytest.raises(RuntimeError, match="provider kwargs"),
    ):
        await build_turn_context(
            db_session,
            body,
            _resolved(),
            user_id=1,
            username="u",
            source="alpha_router_chat",
            skip_budget=True,
            alpha_router_api_key_id=None,
        )

    assert release_permit.await_count == 1
    assert release_hold.await_count == 1
