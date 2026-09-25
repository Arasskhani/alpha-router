"""A running chat turn's hold grows out of the budget left, and turns running at once share it.

A chat hold guesses at the reply's length - 4,096 completion tokens unless the
request names max_tokens - so a reply can outgrow it, and the stream then asks
``extend_hold`` for more. It used to bound each turn by the balance its user or
key had left at admission instead, and every turn running at once counted that
same balance as its own: with $1.00 left, five of them could spend about $4.50.
A hold that grows claims its share under the subject's row lock, so free money
is spent once, and settling releases the hold as grown.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices
from sqlalchemy import select

from app.models.api_key import AlphaRouterApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.budget_reservation import BudgetReservation
from app.models.connection import Connection
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services import budget_reservation_service as reservations
from app.services import chat_turn_context, proxy_service, turn_settlement
from app.services.secret_crypto import encrypt_secret

_POSTGRES = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


@pytest.fixture(autouse=True)
def _own_sessions(monkeypatch, session_factory):
    """``extend_hold`` opens a session of its own, as do the stream and its settlement."""
    for module in (reservations, proxy_service, chat_turn_context, turn_settlement):
        monkeypatch.setattr(module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.budget_notice_service.AsyncSessionLocal", session_factory)


def _month_start() -> datetime.datetime:
    return datetime.datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _user(db, *, limit: float, used: float = 0.0) -> User:
    """A user whose plan gives ``limit`` a month, ``used`` of it already spent."""
    suffix = uuid.uuid4().hex[:8]
    plan = BudgetPlan(name=f"hold-growth-{suffix}", monthly_budget_usd=limit)
    user = User(
        username=f"hold-growth-{suffix}",
        email=f"hold-growth-{suffix}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
        monthly_budget_usd=limit,
        budget_used_usd=used,
        budget_reserved_usd=0.0,
        budget_period_start=_month_start(),
    )
    db.add_all([plan, user])
    await db.flush()
    db.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
    await db.commit()
    return user


async def _key(db, *, limit: float, used: float = 0.0, unlimited: bool = False) -> AlphaRouterApiKey:
    row = AlphaRouterApiKey(
        name="hold-growth-key",
        key_prefix="sk-",
        key_hash=f"hold-growth-{uuid.uuid4().hex}",
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


async def _chat_hold(db, *, amount: float, user_id: int | None = None, api_key_id: int | None = None):
    hold = await reservations.reserve(
        db,
        user_id=user_id,
        alpha_router_api_key_id=api_key_id,
        amount_usd=amount,
        operation="chat",
        model_id="gpt-a",
        idempotency_key=uuid.uuid4().hex,
        cost_is_estimated=True,
    )
    await db.commit()
    return hold


async def _books(session_factory, subject: User | AlphaRouterApiKey) -> SimpleNamespace:
    """The subject's reserved counter and used total, and its reservations, as the database has them now."""
    is_user = isinstance(subject, User)
    subject_type = reservations.SUBJECT_USER if is_user else reservations.SUBJECT_ALPHA_ROUTER_KEY
    async with session_factory() as fresh:
        row = await fresh.get(type(subject), subject.id)
        counter = float(row.budget_reserved_usd if is_user else row.period_reserved_usd)
        used = float(row.budget_used_usd if is_user else row.period_used_usd)
        rows = (
            await fresh.execute(
                select(BudgetReservation).where(
                    BudgetReservation.subject_type == subject_type,
                    BudgetReservation.subject_id == subject.id,
                )
            )
        ).scalars()
        holds = {
            h.id: SimpleNamespace(status=h.status, reserved_usd=float(h.reserved_usd), actual_usd=h.actual_usd)
            for h in rows
        }
        # How many counters sit above the holds behind them; the repair itself is rolled back.
        repaired = await reservations.reconcile_drifted_reserved_counters(fresh)
        await fresh.rollback()
    return SimpleNamespace(
        counter=counter,
        used=used,
        held=sum(h.reserved_usd for h in holds.values() if h.status == reservations.STATUS_HELD),
        holds=holds,
        repaired=repaired,
    )


# --- growing ---------------------------------------------------------------------------


async def test_a_hold_that_covers_the_cost_is_left_alone(db_session, session_factory):
    user = await _user(db_session, limit=1.0)
    hold = await _chat_hold(db_session, amount=0.3, user_id=user.id)
    assert await reservations.extend_hold(hold.id, 0.2) == pytest.approx(0.3)
    books = await _books(session_factory, user)
    assert books.counter == pytest.approx(0.3)


async def test_a_hold_grows_to_twice_its_size(db_session, session_factory):
    """Ahead of the reply, so a long one does not come back at every check."""

    user = await _user(db_session, limit=1.0)
    hold = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    assert await reservations.extend_hold(hold.id, 0.15) == pytest.approx(0.2)
    books = await _books(session_factory, user)
    assert float(books.holds[hold.id].reserved_usd) == pytest.approx(0.2)
    assert books.counter == pytest.approx(0.2)


async def test_a_hold_grows_to_what_is_needed_when_that_is_more(db_session, session_factory):
    user = await _user(db_session, limit=1.0)
    hold = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    assert await reservations.extend_hold(hold.id, 0.35) == pytest.approx(0.35)
    assert (await _books(session_factory, user)).counter == pytest.approx(0.35)


async def test_a_hold_grows_no_further_than_what_is_free(db_session, session_factory):
    user = await _user(db_session, limit=1.0, used=0.85)
    hold = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    # $0.05 is free beside the hold: enough for the $0.12 needed, not for twice the hold.
    assert await reservations.extend_hold(hold.id, 0.12) == pytest.approx(0.15)
    books = await _books(session_factory, user)
    assert books.counter == pytest.approx(0.15)
    assert books.used + books.counter == pytest.approx(1.0)


async def test_a_hold_cannot_grow_past_the_budget_left(db_session, session_factory):
    user = await _user(db_session, limit=1.0, used=0.85)
    hold = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    assert await reservations.extend_hold(hold.id, 0.2) is None
    books = await _books(session_factory, user)
    assert float(books.holds[hold.id].reserved_usd) == pytest.approx(0.1)
    assert books.counter == pytest.approx(0.1)


async def test_two_turns_share_the_budget_left(db_session, session_factory):
    """Both replies keep growing, to $0.70 each; between them they get the $1.00 that is left, no more."""

    user = await _user(db_session, limit=1.0)
    first = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    second = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    holds = {first.id: 0.1, second.id: 0.1}
    refused: set[str] = set()
    for step in range(1, 13):
        needed = round(0.1 + 0.05 * step, 2)
        for hold_id in holds:
            if hold_id in refused:
                continue
            grown = await reservations.extend_hold(hold_id, needed)
            if grown is None:
                refused.add(hold_id)
                continue
            holds[hold_id] = grown
            assert sum(holds.values()) <= 1.0 + 1e-9
    assert refused, "$1.40 between them is more than the $1.00 left"
    books = await _books(session_factory, user)
    assert books.held == pytest.approx(sum(holds.values()))
    assert books.held <= 1.0 + 1e-9
    assert books.counter == pytest.approx(books.held)
    assert books.repaired == 0


@pytest.mark.skipif(not _POSTGRES, reason="needs real row locks; set TEST_DATABASE_URL")
async def test_turns_growing_at_once_never_claim_more_than_is_free(session_factory):
    async with session_factory() as db:
        user = await _user(db, limit=1.0)
        first = await _chat_hold(db, amount=0.1, user_id=user.id)
        second = await _chat_hold(db, amount=0.1, user_id=user.id)
    asks = [
        reservations.extend_hold(hold.id, round(0.15 + 0.05 * step, 2))
        for step in range(10)
        for hold in (first, second)
    ]
    results = await asyncio.gather(*asks)
    assert None in results, "$1.20 between them is more than the $1.00 left"
    books = await _books(session_factory, user)
    assert books.held <= 1.0 + 1e-9
    assert books.counter == pytest.approx(books.held), "no growth may be lost or counted twice"
    assert books.repaired == 0


async def test_a_drifted_counter_does_not_refuse_a_turn(db_session, session_factory):
    """As at admission: a counter above the holds behind it is repaired before anything is refused."""

    user = await _user(db_session, limit=1.0)
    hold = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    async with session_factory() as db:
        drifted = await db.get(User, user.id)
        drifted.budget_reserved_usd = 0.95
        await db.commit()
    assert await reservations.extend_hold(hold.id, 0.3) == pytest.approx(0.3)
    books = await _books(session_factory, user)
    assert books.counter == pytest.approx(0.3)
    assert books.repaired == 0


async def test_a_hold_that_no_longer_counts_cannot_grow(db_session, session_factory):
    user = await _user(db_session, limit=1.0)
    hold = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    assert await reservations.release(db_session, hold.id)
    await db_session.commit()
    assert await reservations.extend_hold(hold.id, 0.2) is None
    books = await _books(session_factory, user)
    assert float(books.holds[hold.id].reserved_usd) == pytest.approx(0.1)
    assert books.counter == pytest.approx(0.0)


async def test_an_api_key_s_hold_grows_within_its_credit(db_session, session_factory):
    key = await _key(db_session, limit=1.0, used=0.5)
    hold = await _chat_hold(db_session, amount=0.1, api_key_id=key.id)
    assert await reservations.extend_hold(hold.id, 0.3) == pytest.approx(0.3)
    assert await reservations.extend_hold(hold.id, 0.7) is None
    books = await _books(session_factory, key)
    assert books.counter == pytest.approx(0.3)


async def test_an_api_key_without_a_limit_is_never_stopped(db_session, session_factory):
    key = await _key(db_session, limit=0.0, unlimited=True)
    hold = await _chat_hold(db_session, amount=0.1, api_key_id=key.id)
    assert await reservations.bounded_hold_usd(db_session, hold) is None
    # Nothing watches such a turn; asked anyway, the hold grows without a cap.
    assert await reservations.extend_hold(hold.id, 50.0) == pytest.approx(50.0)
    assert (await _books(session_factory, key)).counter == pytest.approx(50.0)


# --- what the stream watches ------------------------------------------------------------


async def test_a_user_s_turn_watches_its_hold(db_session):
    user = await _user(db_session, limit=1.0, used=0.8)
    hold = await _chat_hold(db_session, amount=0.5, user_id=user.id)
    # Clamped to the $0.20 left at admission, and that is what the stream starts from.
    assert await reservations.bounded_hold_usd(db_session, hold) == pytest.approx(0.2)


async def test_an_api_key_s_turn_watches_its_hold(db_session):
    key = await _key(db_session, limit=1.0, used=0.5)
    hold = await _chat_hold(db_session, amount=0.1, api_key_id=key.id)
    assert await reservations.bounded_hold_usd(db_session, hold) == pytest.approx(0.1)


async def test_no_hold_nothing_to_watch(db_session):
    assert await reservations.bounded_hold_usd(db_session, None) is None


# --- giving it back ---------------------------------------------------------------------


async def test_settling_a_grown_hold_releases_all_of_it(db_session, session_factory):
    user = await _user(db_session, limit=1.0)
    grown = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    other = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    assert await reservations.extend_hold(grown.id, 0.3) == pytest.approx(0.3)
    async with session_factory() as db:
        assert await reservations.settle(db, grown.id, actual_usd=0.25)
        await db.commit()
    books = await _books(session_factory, user)
    assert books.holds[grown.id].status == reservations.STATUS_SETTLED
    assert float(books.holds[grown.id].actual_usd) == pytest.approx(0.25)
    assert books.used == pytest.approx(0.25)
    # Only the other turn's hold is still counted, and the counter says so.
    assert books.counter == pytest.approx(float(books.holds[other.id].reserved_usd))
    assert books.counter == pytest.approx(books.held)
    assert books.repaired == 0


@pytest.mark.parametrize("give_back", ["release", "expire"])
async def test_releasing_a_grown_hold_releases_all_of_it(db_session, session_factory, give_back):
    user = await _user(db_session, limit=1.0)
    hold = await _chat_hold(db_session, amount=0.1, user_id=user.id)
    assert await reservations.extend_hold(hold.id, 0.3) == pytest.approx(0.3)
    async with session_factory() as db:
        if give_back == "release":
            assert await reservations.release(db, hold.id)
        else:
            row = await db.get(BudgetReservation, hold.id)
            row.expires_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
            await db.flush()
            assert await reservations.expire_stale_reservations(db) == 1
        await db.commit()
    books = await _books(session_factory, user)
    assert books.counter == pytest.approx(0.0)
    assert books.used == pytest.approx(0.0)
    assert books.repaired == 0


# --- in a running turn -------------------------------------------------------------------


async def test_a_reply_the_budget_left_cannot_bear_is_stopped(monkeypatch, db_session, session_factory):
    """Real hold, real growth, real settlement: the reply outgrows its hold, then its budget."""

    async def passthrough(_db, messages, *_args, **_kwargs):
        return messages

    for name in (
        "augment_messages_with_tools",
        "augment_messages_with_profile",
        "augment_messages_with_memory",
        "augment_messages_with_project_context",
    ):
        monkeypatch.setattr(chat_turn_context, name, passthrough)

    user = await _user(db_session, limit=0.1)
    connection = Connection(
        name="c-growth", provider_type="openai", api_key_encrypted=encrypt_secret("sk-x"), is_active=True
    )
    db_session.add(connection)
    await db_session.flush()
    model = AIModel(
        connection_id=connection.id,
        external_id="gpt-a",
        display_name="Model A",
        provider_type="openai",
        is_enabled=True,
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.03,
    )
    db_session.add(model)
    await db_session.commit()
    hold = await _chat_hold(db_session, amount=0.02, user_id=user.id)

    twenty_words = Delta(content=" word" * 20)
    words = ModelResponseStream(id="c", model="gpt-a", choices=[StreamingChoices(index=0, delta=twenty_words)])

    async def stream():
        # About 6,000 output tokens, some $0.18: more than the whole $0.10 budget.
        for _ in range(300):
            yield words

    monkeypatch.setattr(proxy_service, "acompletion", AsyncMock(return_value=stream()))
    request = MagicMock()
    request.client = SimpleNamespace(host="203.0.113.7")
    request.headers = {}
    request.is_disconnected = AsyncMock(return_value=False)
    resolved = SimpleNamespace(
        ai_model=model,
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openai",
        model_id="gpt-a",
        budget_reservation_id=hold.id,
        budget_hold_usd=await reservations.bounded_hold_usd(db_session, hold),
        code_interpreter_capacity_permit=None,
        code_interpreter_workspace_files=None,
        agent_turn=None,
    )
    body = {"model": f"model::{model.id}", "messages": [{"role": "user", "content": "Write a long story."}]}
    frames = [
        frame
        async for frame in proxy_service.stream_chat(
            request,
            body,
            user_id=user.id,
            username=user.username,
            source="alpha_router_chat",
            skip_budget=False,
            resolved=resolved,
        )
    ]

    assert proxy_service.BUDGET_EXCEEDED_MESSAGE in b"".join(frames).decode()
    async with session_factory() as fresh:
        [log] = (await fresh.execute(select(RequestLog))).scalars().all()
    assert log.error_code == "budget_exceeded"
    cost = float(log.total_cost_usd)
    books = await _books(session_factory, user)
    assert books.holds[hold.id].status == reservations.STATUS_SETTLED
    assert float(books.holds[hold.id].actual_usd) == pytest.approx(cost)
    assert books.used == pytest.approx(cost)
    # It ran well past its $0.02 hold, and stopped within one check of the budget.
    assert cost > 0.05
    assert cost < 0.1 + 0.01
    assert books.counter == pytest.approx(0.0)
    assert books.repaired == 0
