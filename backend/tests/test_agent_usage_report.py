"""Agent usage report: chat-turn spend grouped by Agent."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.agent import Agent
from app.models.agent_runtime import AgentRun
from app.services.reports_service import report_agent_usage


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
) -> None:
    run_id = str(uuid.uuid4())
    db.add(
        AgentRun(
            id=run_id,
            correlation_id=run_id,
            agent_id=agent_id,
            source="chat",
            status="succeeded",
            routing_outcome="explicit",
            query_sha256="a" * 64,
            prompt_tokens=tokens,
            completion_tokens=0,
            total_cost_usd=cost,
            created_at=created_at,
        )
    )
    await db.flush()


async def _agent_usage_groups_and_filters() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        legal = await _agent(db, "Legal", "legal")
        hr = await _agent(db, "HR", "hr")
        now = _now()
        start = now - datetime.timedelta(days=7)
        end = now
        await _run(db, agent_id=legal.id, cost=0.40, tokens=100, created_at=now)
        await _run(db, agent_id=legal.id, cost=0.10, tokens=50, created_at=now)
        await _run(db, agent_id=hr.id, cost=0.25, tokens=80, created_at=now)
        await _run(db, agent_id=None, cost=1.00, tokens=10, created_at=now)
        await _run(
            db,
            agent_id=legal.id,
            cost=9.00,
            tokens=500,
            created_at=now - datetime.timedelta(days=30),
        )

        all_rows = await report_agent_usage(db, start, end)
        assert list(all_rows.columns) == ["agent", "cost_usd", "turns", "tokens"]
        by_name = {row["agent"]: row for row in all_rows.to_dict(orient="records")}
        assert by_name["Unassigned"]["cost_usd"] == 1.0
        assert by_name["Legal"]["cost_usd"] == 0.5
        assert by_name["Legal"]["turns"] == 2
        assert by_name["Legal"]["tokens"] == 150
        assert by_name["HR"]["turns"] == 1
        assert list(all_rows["agent"])[0] == "Unassigned"

        one = await report_agent_usage(db, start, end, agent_id=legal.id)
        assert list(one["agent"]) == ["Legal"]
        assert float(one.iloc[0]["cost_usd"]) == 0.5

        empty = await report_agent_usage(
            db,
            now - datetime.timedelta(days=60),
            now - datetime.timedelta(days=40),
        )
        assert empty.empty
        assert list(empty.columns) == ["agent", "cost_usd", "turns", "tokens"]
    await engine.dispose()


async def test_agent_usage_report_groups_and_filters() -> None:
    await _agent_usage_groups_and_filters()
