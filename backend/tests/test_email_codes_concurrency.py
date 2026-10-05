"""Parallel guesses at one emailed code each take one of its tries.

The count of wrong tries used to be read into Python and written back, so
thirty guesses sent at once were all compared while the stored count rose by
one: a six-digit reset code could be guessed far beyond its five tries. The
count is now raised in the database before the code is compared.

Each guess has its own session (its own connection), as requests do. On
PostgreSQL (``TEST_DATABASE_URL``) the test uses the suite's database;
otherwise a SQLite file, since an in-memory database is one shared connection.
"""

from __future__ import annotations

import asyncio
import re

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.email_verification import PURPOSE_PASSWORD_RESET, EmailVerification
from app.services import email_signup_service as codes


@pytest.fixture
async def own_sessions(engine, tmp_path):
    from tests.conftest import _TEST_DATABASE_URL

    if _TEST_DATABASE_URL:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        return
    file_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'codes.db'}", connect_args={"timeout": 30})
    async with file_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(file_engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await file_engine.dispose()


async def _guess(sessions, token: str, code: str) -> str:
    async with sessions() as db:
        try:
            await codes.check_code(db, token=token, code=code, purpose=PURPOSE_PASSWORD_RESET)
            outcome = "accepted"
        except codes.CodeError as exc:
            outcome = str(exc)
        await db.commit()
        return outcome


async def test_thirty_guesses_at_once_take_five_tries(own_sessions):
    async with own_sessions() as db:
        row, code = await codes.issue_code(db, email="victim@example.com", purpose=PURPOSE_PASSWORD_RESET)
        await db.commit()
        token, row_id = str(row.token), int(row.id)
    wrong = [f"{i:06d}" for i in range(40) if f"{i:06d}" != code][:30]

    outcomes = await asyncio.gather(*(_guess(own_sessions, token, guess) for guess in wrong))

    told_left = sorted(int(m.group(1)) for o in outcomes if (m := re.search(r"(\d) tr(?:y|ies) left", o)))
    assert told_left == [1, 2, 3, 4], outcomes
    refused = {"Too many wrong codes. Ask for a new one.", "This code is no longer valid. Ask for a new one."}
    assert sum(o in refused for o in outcomes) == len(wrong) - 4, outcomes
    async with own_sessions() as db:
        stored = await db.get(EmailVerification, row_id)
        assert stored.attempts == codes.MAX_ATTEMPTS
        assert stored.consumed_at is not None
    # The right code no longer helps.
    assert await _guess(own_sessions, token, code) == "This code is no longer valid. Ask for a new one."


async def test_the_right_code_counts_as_a_try(own_sessions):
    async with own_sessions() as db:
        row, code = await codes.issue_code(db, email="person@example.com", purpose=PURPOSE_PASSWORD_RESET)
        await db.commit()
        token, row_id = str(row.token), int(row.id)
    for _ in range(codes.MAX_ATTEMPTS - 1):
        assert "left" in await _guess(own_sessions, token, "000000" if code != "000000" else "111111")
    assert await _guess(own_sessions, token, code) == "accepted"
    async with own_sessions() as db:
        stored = await db.get(EmailVerification, row_id)
        assert stored.verified_at is not None
        assert stored.attempts == codes.MAX_ATTEMPTS


async def test_one_token_finishes_once(own_sessions):
    async with own_sessions() as db:
        row, _code = await codes.issue_code(db, email="person@example.com", purpose=PURPOSE_PASSWORD_RESET)
        await db.commit()
        row_id = int(row.id)

    async def finish() -> str:
        async with own_sessions() as db:
            mine = await db.get(EmailVerification, row_id)
            try:
                await codes.consume(db, mine)
            except codes.CodeError:
                await db.rollback()
                return "refused"
            await db.commit()
            return "finished"

    assert sorted(await asyncio.gather(finish(), finish(), finish())) == ["finished", "refused", "refused"]
