"""Agents Overview 24h spend aggregation (chat turns only)."""

from __future__ import annotations

import asyncio
import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.admin_agents import _overview_spend_24h
from app.database import Base
from app.models.agent import Agent
from app.models.agent_runtime import AgentRun


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


async def _agent(db: AsyncSession, name: str, slug: str) -> Agent:
    row = Agent(
        id=str(uuid.uuid4()),
        slug=slug,
        name=name,
        status="active",
        access_type="private",
    )
    db.add(row)
    await db.flush()
    return row


async def _run(
    db: AsyncSession,
    *,
    agent_id: str | None,
    cost: float,
    tokens: int,
    created_at: datetime.datetime,
    status: str = "succeeded",
) -> AgentRun:
    run_id = str(uuid.uuid4())
    row = AgentRun(
        id=run_id,
        correlation_id=run_id,
        agent_id=agent_id,
        source="chat",
        status=status,
        routing_outcome="explicit",
        query_sha256="a" * 64,
        prompt_tokens=tokens,
        completion_tokens=0,
        total_cost_usd=cost,
        created_at=created_at,
    )
    db.add(row)
    await db.flush()
    return row


async def _aggregates_cost_and_ranks_agents() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        legal = await _agent(db, "Legal", "legal")
        hr = await _agent(db, "HR", "hr")
        finance = await _agent(db, "Finance", "finance")
        now = _now()
        await _run(db, agent_id=legal.id, cost=0.40, tokens=100, created_at=now)
        await _run(db, agent_id=legal.id, cost=0.10, tokens=50, created_at=now)
        await _run(db, agent_id=hr.id, cost=0.25, tokens=80, created_at=now)
        await _run(db, agent_id=finance.id, cost=0.05, tokens=20, created_at=now)
        await _run(db, agent_id=None, cost=9.99, tokens=999, created_at=now)
        await _run(
            db,
            agent_id=legal.id,
            cost=50.0,
            tokens=10_000,
            created_at=now - datetime.timedelta(hours=48),
        )
        await _run(
            db,
            agent_id=hr.id,
            cost=0,
            tokens=12,
            created_at=now,
            status="blocked",
        )
        payload = await _overview_spend_24h(db, now - datetime.timedelta(hours=24))
        assert payload["cost_usd"] == 10.79
        assert payload["tokens"] == 1261
        assert payload["turns"] == 6
        assert payload["billed_turns"] == 5
        names = [row["name"] for row in payload["top_agents"]]
        assert names == ["Legal", "HR", "Finance"]
        assert payload["top_agents"][0]["cost_usd"] == 0.5
        assert payload["top_agents"][0]["turns"] == 2
        assert payload["top_agents"][0]["id"] == legal.id
    await engine.dispose()


def test_overview_spend_24h_ranks_agents_and_ignores_old_runs() -> None:
    asyncio.run(_aggregates_cost_and_ranks_agents())
