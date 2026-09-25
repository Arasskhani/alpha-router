"""What a running chat turn may spend: the budget its subject had left when the turn was admitted.

The hold guesses at the reply's length; the ceiling is what the budget can
bear, so a reply is stopped only when it would take its user (or API key) past
the budget, never merely for being longer than the guess.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.api_key import AlphaRouterApiKey
from app.models.user import User
from app.services import budget_reservation_service as reservations


def _month_start() -> datetime.datetime:
    return datetime.datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _user(db, *, limit: float, used: float = 0.0) -> User:
    row = User(
        username="ceiling-user",
        email="ceiling@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
        monthly_budget_usd=limit,
        budget_used_usd=used,
        budget_reserved_usd=0.0,
        budget_period_start=_month_start(),
    )
    db.add(row)
    await db.commit()
    return row


async def _key(db, *, limit: float, used: float = 0.0, unlimited: bool = False) -> AlphaRouterApiKey:
    row = AlphaRouterApiKey(
        name="ceiling-key",
        key_prefix="sk-",
        key_hash=f"ceiling-{limit}-{unlimited}",
        is_active=True,
        credit_limit_usd=limit,
        unlimited_budget=unlimited,
        reset_period="monthly",
        period_used_usd=used,
        period_reserved_usd=0.0,
        total_used_usd=used,
        period_started_at=datetime.datetime.utcnow(),
    )
    db.add(row)
    await db.commit()
    return row


async def _chat_hold(db, *, amount: float, key: str, user_id: int | None = None, api_key_id: int | None = None):
    # The plan sync is not what these tests are about: keep the budget as set.
    with patch.object(reservations, "ensure_budget_period", AsyncMock(return_value=None)):
        return await reservations.reserve(
            db,
            user_id=user_id,
            alpha_router_api_key_id=api_key_id,
            amount_usd=amount,
            operation="chat",
            model_id="test/model",
            idempotency_key=key,
            cost_is_estimated=True,
        )


async def test_a_turn_may_spend_what_its_user_had_left(db_session):
    user = await _user(db_session, limit=1.0, used=0.1)
    await _chat_hold(db_session, amount=0.2, key="earlier", user_id=user.id)
    hold = await _chat_hold(db_session, amount=0.3, key="this", user_id=user.id)
    # $1.00 - $0.10 spent - $0.20 held by another turn; the $0.30 guess does not matter.
    assert await reservations.spend_ceiling_usd(db_session, hold) == pytest.approx(0.7)


async def test_a_hold_clamped_to_the_balance_is_the_ceiling(db_session):
    user = await _user(db_session, limit=1.0, used=0.8)
    hold = await _chat_hold(db_session, amount=0.5, key="clamped", user_id=user.id)
    assert float(hold.reserved_usd) == pytest.approx(0.2)
    assert await reservations.spend_ceiling_usd(db_session, hold) == pytest.approx(0.2)


async def test_an_api_key_s_turn_may_spend_its_credit_left(db_session):
    key = await _key(db_session, limit=1.0, used=0.5)
    hold = await _chat_hold(db_session, amount=0.1, key="key-turn", api_key_id=key.id)
    assert await reservations.spend_ceiling_usd(db_session, hold) == pytest.approx(0.5)


async def test_an_unlimited_api_key_is_never_stopped(db_session):
    key = await _key(db_session, limit=0.0, unlimited=True)
    hold = await _chat_hold(db_session, amount=0.1, key="unlimited", api_key_id=key.id)
    assert hold is not None
    assert await reservations.spend_ceiling_usd(db_session, hold) is None


async def test_no_hold_no_ceiling(db_session):
    assert await reservations.spend_ceiling_usd(db_session, None) is None
