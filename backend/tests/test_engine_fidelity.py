"""The test engine has to behave like the deployed one, or a green run means less.

Two properties are guarded here.

**Foreign keys are enforced.** SQLite defaults ``PRAGMA foreign_keys`` to OFF,
per connection, so every ``ON DELETE CASCADE`` and ``ON DELETE SET NULL`` in the
schema is inert unless something turns it on. PostgreSQL always enforces them,
and there a ``SET NULL`` runs as a real UPDATE that fires row triggers - which is
how a delete can be refused by an append-only audit table. With the pragma off
the two engines disagree about what a delete does and the suite cannot see it.

**Tests that build their own engine do not multiply.** 110 files predate the
shared ``engine`` fixture and construct ``create_async_engine`` themselves, so
they get none of the above. Converting them all at once is churn; letting the
number grow is how the fixture stays bypassed forever. Hence a ratchet: the
count may fall, never rise.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.models.video import VideoGenerationJob

#: Files under tests/ that build their own SQLite engine instead of using the
#: ``engine`` fixture. Lower this number when you convert one; never raise it.
MAX_SELF_BUILT_SQLITE_ENGINES = 130

_ENGINE_LITERAL = re.compile(r'create_async_engine\(\s*"sqlite\+aiosqlite:///:memory:"')

#: Assertions of the form ``"some string" in inspect.getsource(fn)``. They pass
#: whenever the string is present, so a refactor that keeps the string and
#: breaks the behaviour is green. Each one is replaced with a behavioural test
#: as its file is touched; the number may only shrink.
MAX_SOURCE_ASSERTIONS = 46
_SOURCE_ASSERTION = re.compile(r"inspect\.getsource\(")


async def test_the_test_engine_enforces_foreign_keys(db_session):
    """A dangling foreign key must be refused, on SQLite as it is on PostgreSQL."""

    db_session.add(
        VideoGenerationJob(
            id="job-with-no-owner",
            user_id=987654,  # no such user
            model_id="bytedance/seedance-1-pro",
            prompt="a cat",
            operation="generation",
            status="failed",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_referential_actions_actually_run(db_session):
    """``ON DELETE SET NULL`` has to fire, because on PostgreSQL it is an UPDATE."""

    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models.security import SecurityAuditEvent

    actor = User(
        username="fidelity_actor",
        hashed_password=hash_password("fidelity-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(actor)
    await db_session.flush()

    event = SecurityAuditEvent(actor_user_id=actor.id, action="fidelity_probe", resource_type="test")
    db_session.add(event)
    await db_session.flush()

    await db_session.delete(actor)
    await db_session.flush()
    db_session.expunge_all()

    rows = (await db_session.execute(select(SecurityAuditEvent))).scalars().all()
    assert len(rows) == 1, "the audit row must survive the actor"
    assert rows[0].actor_user_id is None, "ON DELETE SET NULL did not fire"


def test_self_built_sqlite_engines_do_not_multiply():
    tests_dir = pathlib.Path(__file__).resolve().parent
    here = pathlib.Path(__file__).resolve()
    total = 0
    for path in sorted(tests_dir.rglob("test_*.py")):
        if path.resolve() == here:
            continue
        total += len(_ENGINE_LITERAL.findall(path.read_text(encoding="utf-8")))
    assert total <= MAX_SELF_BUILT_SQLITE_ENGINES, (
        f"{total} self-built in-memory SQLite engines under tests/, was "
        f"{MAX_SELF_BUILT_SQLITE_ENGINES}. Use the shared `engine`/`db_session` "
        "fixture in new tests; it enforces foreign keys and honours "
        "TEST_DATABASE_URL."
    )


def test_source_string_assertions_do_not_multiply():
    """``"x" in inspect.getsource(fn)`` passes when the text is there, not when
    the behaviour is. Replace one with a real test whenever you touch its file."""

    tests_dir = pathlib.Path(__file__).resolve().parent
    here = pathlib.Path(__file__).resolve()
    total = 0
    for path in sorted(tests_dir.rglob("test_*.py")):
        if path.resolve() == here:
            continue
        total += len(_SOURCE_ASSERTION.findall(path.read_text(encoding="utf-8")))
    assert total <= MAX_SOURCE_ASSERTIONS, (
        f"{total} inspect.getsource assertions under tests/, was {MAX_SOURCE_ASSERTIONS}. "
        "Write a test that fails when the behaviour is reverted, not when a string is renamed."
    )
