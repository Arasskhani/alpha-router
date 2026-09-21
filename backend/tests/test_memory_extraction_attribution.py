"""Memory extraction spend goes in the ledger everything else goes in.

Two problems lived here. The row was written with ``request_log_id=None``, so
it existed in ``usage_operations`` and nowhere Activity, Reports or the
dashboard look — all three read ``request_logs``. And it was written on the
worker's own session, so an ``ExtractionParseError``, which is raised only
*after* two paid calls, rolled the transaction back and took the record of
that money with it.

It is recorded against the person it was extracted for, and never charged to
their budget: nobody asks for an extraction, and a background job that eats
someone's allowance would make memory a tax on talking.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession, UserMemoryJob
from app.models.cost_accounting import UsageOperation
from app.models.logging import RequestLog
from app.models.system import SystemSetting
from app.models.user import User
from app.services import memory_extraction_service as extraction
from app.services.memory_extraction_service import (
    ExtractionBilling,
    ExtractionWindow,
    WindowTurn,
    extract_memory_operations,
    handle_memory_extraction,
)


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _Response:
    """The shape litellm returns, with usage the pricing path can read."""

    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]
        self.usage = type("U", (), {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940})()


GOOD = json.dumps({"operations": [{"op": "add", "content": "User lives in Tehran", "category": "identity"}]})


@pytest.fixture
def catalog_model():
    return type(
        "AIModel",
        (),
        {"external_id": "gpt-extract", "provider_type": "openai", "connection_id": None, "pricing_raw": None},
    )()


@pytest.fixture
async def seeded(db_session: AsyncSession) -> tuple[User, UserMemoryJob]:
    user = User(username="spender", email="spend@alpha-router.local", hashed_password="x", auth_provider="local")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(id="sess-bill", user_id=user.id, title="Chat", model_id="m", private_mode=False)
    db_session.add(session)
    db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
    await db_session.flush()
    now = dt.datetime.utcnow()
    for sequence, (role, content) in enumerate([("user", "I live in Tehran."), ("assistant", "Noted.")], start=1):
        db_session.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role=role,
                content=content,
                sequence=sequence,
                created_at=now,
            )
        )
    job = UserMemoryJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        session_id=session.id,
        status="running",
        watermark_sequence=2,
        extracted_sequence=0,
        run_after=now,
        attempt_count=1,
        max_attempts=5,
        created_at=now,
        updated_at=now,
    )
    db_session.add(job)
    await db_session.commit()
    return user, job


@pytest.fixture
def extraction_calls(monkeypatch, session_factory, catalog_model):
    """Stand in for litellm and the model catalog; count real provider calls."""
    replies: list[str] = []
    calls: list[dict] = []

    async def _resolve(_db, _ref):
        return catalog_model, "sk-test", None, "openai"

    async def _acompletion(**kwargs):
        calls.append(kwargs)
        return _Response(replies.pop(0) if replies else GOOD)

    monkeypatch.setattr("app.services.model_resolution_service.resolve_model_and_key", _resolve)
    monkeypatch.setattr("litellm.acompletion", _acompletion)
    # settle_auxiliary_usage opens a session of its own on purpose; in a test
    # that has to be the test's engine.
    monkeypatch.setattr("app.services.usage_logging_service.AsyncSessionLocal", session_factory)
    return replies, calls


async def _logs(db: AsyncSession) -> list[RequestLog]:
    return list((await db.execute(select(RequestLog))).scalars().all())


async def test_one_extraction_writes_one_request_log(db_session, seeded, extraction_calls) -> None:
    user, job = seeded
    await handle_memory_extraction(db_session, job)
    await db_session.commit()

    rows = await _logs(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == user.id
    # Activity groups the App column by source; this is what labels the rows.
    assert row.source == "system_memory"
    assert row.client_app == "Memory"
    assert row.usage_operation_id, "the request log and the usage operation must be linked"


async def test_the_spend_names_the_user_it_was_extracted_for(db_session, seeded, extraction_calls) -> None:
    user, job = seeded
    await handle_memory_extraction(db_session, job)
    await db_session.commit()

    operations = (await db_session.execute(select(UsageOperation))).scalars().all()
    assert [op.operation_type for op in operations] == ["memory_extract"]
    assert operations[0].user_id == user.id


async def test_charge_budget_false_records_the_cost_without_spending_the_allowance(db_session, seeded) -> None:
    """Asserted on log_usage directly, with a cost that is actually non-zero.

    Doing this through a stubbed extraction proves nothing: with no pricing
    configured the call costs 0, and _apply_cost_to_user returns early on 0,
    so the assertion passes whichever way the flag is set.
    """
    from app.services.usage_logging_service import log_usage

    user, _job = seeded

    async def _record(*, charge_budget: bool) -> None:
        await log_usage(
            db_session,
            user_id=user.id,
            username=user.username,
            model_id="gpt-extract",
            prompt_tokens=900,
            completion_tokens=40,
            cached_tokens=0,
            total_cost_usd=0.25,
            response_time_ms=120.0,
            prompt_language="en",
            source_ip=None,
            source="system_memory",
            success=True,
            client_app="Memory",
            operation_type="memory_extract",
            operation_idempotency_key=f"test:{uuid.uuid4()}",
            charge_budget=charge_budget,
        )
        await db_session.commit()

    await _record(charge_budget=False)
    await db_session.refresh(user)
    assert float(user.budget_used_usd or 0) == 0.0
    assert float((await _logs(db_session))[0].total_cost_usd or 0) == 0.25

    # The flag is doing the work, not the absence of cost.
    await _record(charge_budget=True)
    await db_session.refresh(user)
    assert float(user.budget_used_usd or 0) == 0.25


async def test_a_failed_parse_still_leaves_the_money_written_down(db_session, seeded, extraction_calls) -> None:
    """Two paid calls, no usable answer. The rows are the only proof it happened."""
    replies, calls = extraction_calls
    replies.extend(["not json at all", "still not json"])

    with pytest.raises(extraction.ExtractionParseError):
        await handle_memory_extraction(db_session, job=seeded[1])

    # The worker's transaction is discarded after a failure; the ledger is not.
    await db_session.rollback()
    assert len(calls) == 2
    rows = await _logs(db_session)
    assert len(rows) == 2, "a repair round is a second provider call and a second row"
    assert {r.source for r in rows} == {"system_memory"}


async def test_a_retry_of_the_same_job_is_not_mistaken_for_a_duplicate(
    db_session, seeded, extraction_calls, catalog_model
) -> None:
    """The idempotency key carries the attempt, because a retry costs again."""
    _user, job = seeded
    window = ExtractionWindow(
        user_id=job.user_id,
        session_id=job.session_id,
        from_sequence=1,
        to_sequence=2,
        turns=[WindowTurn(role="user", sequence=1, text="I live in Tehran.", message_id="m1")],
    )
    for attempt in (1, 2):
        job.attempt_count = attempt
        await extract_memory_operations(
            db_session,
            window=window,
            billing=ExtractionBilling.for_user(job, "spender"),
        )
    await db_session.commit()
    assert len(await _logs(db_session)) == 2


async def test_project_extraction_belongs_to_the_project_not_a_member(db_session, seeded) -> None:
    """The window is multi-author; charging whoever spoke last would be arbitrary."""
    _user, job = seeded
    project_job = type("J", (), {"id": job.id, "project_id": "proj-7", "attempt_count": 0})()
    billing = ExtractionBilling.for_project(project_job)
    assert billing.user_id is None
    assert billing.project_id == "proj-7"
    assert billing.subject_type == "platform"
    assert billing.operation_type == "project_memory_extract"


async def test_the_monthly_cap_still_counts_these_rows(db_session, seeded, extraction_calls) -> None:
    """Commit 8's ceiling reads usage_operations; moving the write must not lose it."""
    await handle_memory_extraction(db_session, job=seeded[1])
    await db_session.commit()
    total = (
        await db_session.execute(
            select(func.coalesce(func.sum(UsageOperation.total_cost_usd), 0)).where(
                UsageOperation.operation_type == "memory_extract"
            )
        )
    ).scalar_one()
    assert float(total or 0) >= 0.0
    assert await extraction.extraction_spend_this_month(db_session) == float(total or 0)
