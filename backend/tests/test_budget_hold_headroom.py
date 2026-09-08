"""Reservation holds must not overestimate media turns or block a live balance.

Regression cover for two defects that together refused chat turns from users who
still had budget:

* ``_prompt_tokens_from_messages`` stringified OpenAI-style multimodal content,
  counting an inlined base64 image as prompt text (~200x overestimate for a 1 MB
  image).
* ``reserve`` rejected a turn whenever the *estimate* exceeded the remaining
  balance, instead of reserving what was actually left.
"""

from __future__ import annotations

import asyncio
import datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.budget_reservation import BudgetReservation
from app.models.user import User
from app.services.budget_reservation_service import (
    IMAGE_PROMPT_TOKENS,
    _prompt_tokens_from_messages,
    reconcile_drifted_reserved_counters,
    reservation_hold_usd,
    reserve,
)


def _chat_model():
    """Sonnet-class rates: $3/M input, $15/M output."""
    return SimpleNamespace(
        external_id="provider/chat",
        provider_type="openrouter",
        connection_id=None,
        input_cost_per_1k=0.003,
        output_cost_per_1k=0.015,
        pricing_raw=json.dumps(
            {"pricing": {"prompt": "0.000003", "completion": "0.000015"}}
        ),
    )


async def _session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory, engine


def _image_message(size_kb: int) -> dict:
    """A user turn carrying an inlined base64 image, as the web client sends it."""
    payload = "A" * int(size_kb * 1024 * 4 / 3)
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": "سلام"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{payload}"}},
        ],
    }


# --------------------------------------------------------------------------- #
# 1. token estimation                                                          #
# --------------------------------------------------------------------------- #


def test_prompt_tokens_ignore_base64_image_payload() -> None:
    """A 1 MB image must not be billed as ~455k prompt tokens."""
    tokens = _prompt_tokens_from_messages([_image_message(1024)])
    text_tokens = _prompt_tokens_from_messages(
        [{"role": "user", "content": "سلام"}]
    )
    # Text bytes plus one flat image estimate — not the base64 length.
    assert tokens == text_tokens + IMAGE_PROMPT_TOKENS
    assert tokens < 2_000


def _image_only_message(size_kb: int) -> dict:
    payload = "A" * int(size_kb * 1024 * 4 / 3)
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{payload}"}},
        ],
    }


def test_prompt_tokens_scale_with_image_count_not_image_size() -> None:
    small = _prompt_tokens_from_messages([_image_message(50)])
    large = _prompt_tokens_from_messages([_image_message(4096)])
    assert small == large

    one = _prompt_tokens_from_messages([_image_only_message(50)])
    two = _prompt_tokens_from_messages([_image_only_message(50), _image_only_message(4096)])
    assert one == IMAGE_PROMPT_TOKENS
    assert two - one == IMAGE_PROMPT_TOKENS


def test_prompt_tokens_still_measure_plain_text_and_document_text() -> None:
    plain = _prompt_tokens_from_messages(
        [{"role": "user", "content": "x" * 3000}]
    )
    assert plain == 1000

    # Extracted document text arrives as a text part and must still be counted.
    parts = _prompt_tokens_from_messages(
        [{"role": "user", "content": [{"type": "text", "text": "x" * 3000}]}]
    )
    assert parts == 1000


async def _hold_for_image_turn() -> float:
    factory, engine = await _session()
    async with factory() as db:
        hold = await reservation_hold_usd(
            db,
            service_type="llm",
            ai_model=_chat_model(),
            provider_type="openrouter",
            body={"messages": [_image_message(1024)]},
        )
    await engine.dispose()
    return hold


def test_image_turn_hold_stays_small() -> None:
    """The reported failure: $1.05 left, a 1 MB image turn quoted at $1.57."""
    hold = asyncio.run(_hold_for_image_turn())
    assert hold < 0.20, f"hold {hold} would still block a user with $1.05 left"


# --------------------------------------------------------------------------- #
# 2. reserve() clamps to the remaining balance                                 #
# --------------------------------------------------------------------------- #


async def _user_with_budget(
    db: AsyncSession,
    *,
    monthly: float,
    used: float,
    held: float = 0.0,
) -> User:
    plan = BudgetPlan(name="test-plan", monthly_budget_usd=monthly)
    db.add(plan)
    await db.flush()
    user = User(
        username="budget-user",
        email="budget-user@example.test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
        monthly_budget_usd=monthly,
        budget_used_usd=used,
        budget_reserved_usd=held,
        budget_period_start=datetime.datetime(
            datetime.datetime.utcnow().year, datetime.datetime.utcnow().month, 1
        ),
    )
    db.add(user)
    await db.flush()
    db.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
    await db.flush()
    return user


def test_reserve_refuses_an_estimate_larger_than_the_balance() -> None:
    """Admission is strict: the whole estimate must fit, or the request is refused.

    Clamping an over-sized estimate down to the remaining balance was tried and
    reverted — it let a 30-second video quoted at $7.64 start on a $1.68 hold and
    settle at its real $6.95, taking a $12.00 budget to $17.27.
    """
    detail = asyncio.run(_reserve_expecting_rejection(used=10.95, amount_usd=1.57))
    assert "1.5700" in detail, detail
    assert "1.0500" in detail, detail


def test_priced_hold_is_not_truncated_to_the_unpriced_ceiling() -> None:
    """A priced quote above ``budget_max_hold_usd`` ($5.00) must be held in full.

    The 30-second video quoted $7.64. Truncating it to $5.00 under-reserved the
    job, so it could overshoot the budget even under strict admission.
    """
    reserved = asyncio.run(_reserve_priced_video())
    assert reserved == pytest.approx(7.642, abs=1e-6)


async def _reserve_priced_video() -> float:
    factory, engine = await _session()
    async with factory() as db:
        # Enough budget for the job, so admission is not what is under test.
        user = await _user_with_budget(db, monthly=50.0, used=0.0)
        row = await reserve(
            db,
            user_id=user.id,
            alpha_router_api_key_id=None,
            amount_usd=7.642,  # 30s x $0.2316/s x 1.10 buffer
            operation="video",
            model_id="provider/video",
            idempotency_key="video-1",
        )
        reserved = float(row.reserved_usd)
    await engine.dispose()
    return reserved


async def _reserve_within_headroom() -> float:
    factory, engine = await _session()
    async with factory() as db:
        user = await _user_with_budget(db, monthly=12.0, used=1.0)
        row = await reserve(
            db,
            user_id=user.id,
            alpha_router_api_key_id=None,
            amount_usd=0.07,
            operation="chat",
            model_id="provider/chat",
            idempotency_key="turn-1",
        )
        reserved = float(row.reserved_usd)
    await engine.dispose()
    return reserved


def test_reserve_leaves_a_fitting_estimate_untouched() -> None:
    assert asyncio.run(_reserve_within_headroom()) == pytest.approx(0.07, abs=1e-9)


async def _reserve_expecting_rejection(
    *,
    used: float,
    amount_usd: float,
    cost_is_estimated: bool = False,
) -> str:
    factory, engine = await _session()
    detail: str | None = None
    try:
        async with factory() as db:
            user = await _user_with_budget(db, monthly=12.0, used=used)
            try:
                await reserve(
                    db,
                    user_id=user.id,
                    alpha_router_api_key_id=None,
                    amount_usd=amount_usd,
                    operation="chat",
                    model_id="provider/chat",
                    idempotency_key="turn-1",
                    cost_is_estimated=cost_is_estimated,
                )
            except HTTPException as exc:
                detail = str(exc.detail)
    finally:
        await engine.dispose()
    if detail is None:
        raise AssertionError("reserve() should have rejected this request")
    return detail


def test_reserve_rejects_a_spent_budget() -> None:
    detail = asyncio.run(_reserve_expecting_rejection(used=12.0, amount_usd=0.05))
    assert "budget exceeded" in detail.lower()


def test_rejection_names_the_estimate_and_the_remaining_balance() -> None:
    """The refusal has to be diagnosable without reading the database."""
    detail = asyncio.run(_reserve_expecting_rejection(used=11.996, amount_usd=1.57))
    assert "1.5700" in detail, detail
    assert "0.0040" in detail, detail


def test_estimate_that_exactly_fits_is_admitted() -> None:
    """Boundary: estimate == remaining balance must be allowed, not refused."""
    assert asyncio.run(
        _reserve_amount(used=10.95, amount_usd=1.05)
    ) == pytest.approx(1.05, abs=1e-9)


async def _reserve_amount(
    *,
    used: float,
    amount_usd: float,
    cost_is_estimated: bool = False,
    monthly: float = 12.0,
) -> float:
    factory, engine = await _session()
    async with factory() as db:
        user = await _user_with_budget(db, monthly=monthly, used=used)
        row = await reserve(
            db,
            user_id=user.id,
            alpha_router_api_key_id=None,
            amount_usd=amount_usd,
            operation="chat",
            model_id="provider/chat",
            idempotency_key="turn-fit",
            cost_is_estimated=cost_is_estimated,
        )
        reserved = float(row.reserved_usd)
    await engine.dispose()
    return reserved


# --------------------------------------------------------------------------- #
# 4. chat may overshoot by a bounded, configured amount; nothing else may      #
# --------------------------------------------------------------------------- #


def test_chat_estimate_slightly_over_balance_is_clamped_and_admitted() -> None:
    """Chat's estimate is an upper bound, so a small miss must not refuse the turn.

    $12.00 limit, $11.70 used -> $0.30 left. A chat quoted at $0.55 misses by
    $0.25, inside the $0.50 tolerance, so it runs on a $0.30 hold.
    """
    reserved = asyncio.run(
        _reserve_amount(used=11.70, amount_usd=0.55, cost_is_estimated=True)
    )
    assert reserved == pytest.approx(0.30, abs=1e-6)


def test_chat_estimate_far_over_balance_is_still_refused() -> None:
    """Beyond the tolerance the overshoot stops being bounded, so refuse."""
    detail = asyncio.run(
        _reserve_expecting_rejection(
            used=11.70, amount_usd=2.50, cost_is_estimated=True
        )
    )
    assert "2.5000" in detail, detail
    assert "0.3000" in detail, detail


def test_strict_operations_get_no_tolerance() -> None:
    """The same shortfall that chat tolerates must refuse a video/image/speech job."""
    detail = asyncio.run(
        _reserve_expecting_rejection(
            used=11.70, amount_usd=0.55, cost_is_estimated=False
        )
    )
    assert "0.5500" in detail, detail
    assert "0.3000" in detail, detail


def test_video_overspend_scenario_stays_refused_under_the_soft_path() -> None:
    """The production regression must not come back through the chat tolerance.

    30s video quoted $7.6420 with $1.68 left. Even if it were ever mislabelled as
    an estimated cost, the shortfall dwarfs the tolerance, so it is refused.
    """
    detail = asyncio.run(
        _reserve_expecting_rejection(
            used=10.32, amount_usd=7.642, cost_is_estimated=True
        )
    )
    assert "7.6420" in detail, detail


def test_soft_path_never_reserves_past_the_limit() -> None:
    """Whatever the tolerance allows, the hold itself still cannot exceed the limit."""
    factory_reserved = asyncio.run(
        _reserve_amount(used=11.70, amount_usd=0.55, cost_is_estimated=True)
    )
    assert 11.70 + factory_reserved == pytest.approx(12.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# 3. a drifted reserved counter must self-repair, not lock the account out     #
# --------------------------------------------------------------------------- #


async def _reserve_with_orphaned_counter() -> tuple[float, float]:
    """Reproduce the production lockout: counter pinned, zero ``held`` rows.

    majid: $15.00 budget, $10.29 settled, $5.05 stuck in ``budget_reserved_usd``
    with no open reservations behind it -> headroom -$0.34 -> every message
    refused for the rest of the month.
    """
    factory, engine = await _session()
    async with factory() as db:
        user = await _user_with_budget(db, monthly=15.0, used=10.28669274, held=5.05)
        # No BudgetReservation rows at all: the counter is orphaned.
        row = await reserve(
            db,
            user_id=user.id,
            alpha_router_api_key_id=None,
            amount_usd=0.07,
            operation="chat",
            model_id="provider/chat",
            idempotency_key="turn-after-drift",
        )
        reserved = float(row.reserved_usd)
        counter = float(user.budget_reserved_usd)
    await engine.dispose()
    return reserved, counter


def test_orphaned_reserved_counter_is_repaired_instead_of_blocking() -> None:
    reserved, counter = asyncio.run(_reserve_with_orphaned_counter())
    # The $5.05 phantom is dropped and the real estimate is held instead.
    assert reserved == pytest.approx(0.07, abs=1e-9)
    assert counter == pytest.approx(0.07, abs=1e-9)


async def _reserve_with_genuine_holds() -> str:
    """A counter backed by real ``held`` rows must NOT be repaired away."""
    factory, engine = await _session()
    detail: str | None = None
    try:
        async with factory() as db:
            user = await _user_with_budget(db, monthly=15.0, used=10.0, held=5.0)
            db.add(
                BudgetReservation(
                    id="real-hold-1",
                    subject_type="user",
                    subject_id=user.id,
                    idempotency_key="user:%d:real-hold-1" % user.id,
                    operation="chat",
                    model_id="provider/chat",
                    reserved_usd=5.0,
                    status="held",
                    created_at=datetime.datetime.utcnow(),
                    expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=2),
                )
            )
            await db.flush()
            try:
                await reserve(
                    db,
                    user_id=user.id,
                    alpha_router_api_key_id=None,
                    amount_usd=0.07,
                    operation="chat",
                    model_id="provider/chat",
                    idempotency_key="turn-blocked",
                )
            except HTTPException as exc:
                detail = str(exc.detail)
    finally:
        await engine.dispose()
    if detail is None:
        raise AssertionError("a genuinely held balance must still be refused")
    return detail


def test_real_open_holds_are_not_repaired_away() -> None:
    detail = asyncio.run(_reserve_with_genuine_holds())
    assert "budget exceeded" in detail.lower()


async def _drift_sweep() -> tuple[int, float, float]:
    """The scheduler sweep repairs drift without touching a healthy counter."""
    factory, engine = await _session()
    async with factory() as db:
        drifted = await _user_with_budget(db, monthly=15.0, used=1.0, held=5.05)
        healthy = User(
            username="healthy-user",
            email="healthy@example.test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
            monthly_budget_usd=15.0,
            budget_used_usd=1.0,
            budget_reserved_usd=2.0,
            budget_period_start=datetime.datetime.utcnow(),
        )
        db.add(healthy)
        await db.flush()
        db.add(
            BudgetReservation(
                id="healthy-hold",
                subject_type="user",
                subject_id=healthy.id,
                idempotency_key="user:%d:healthy-hold" % healthy.id,
                operation="chat",
                model_id="provider/chat",
                reserved_usd=2.0,
                status="held",
                created_at=datetime.datetime.utcnow(),
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=2),
            )
        )
        await db.flush()
        repaired = await reconcile_drifted_reserved_counters(db)
        drifted_counter = float(drifted.budget_reserved_usd)
        healthy_counter = float(healthy.budget_reserved_usd)
    await engine.dispose()
    return repaired, drifted_counter, healthy_counter


def test_scheduler_sweep_repairs_only_drifted_counters() -> None:
    repaired, drifted_counter, healthy_counter = asyncio.run(_drift_sweep())
    assert repaired == 1
    assert drifted_counter == pytest.approx(0.0, abs=1e-9)
    assert healthy_counter == pytest.approx(2.0, abs=1e-9)
