"""Startup must not cost one round trip per user, per worker.

The lifespan loaded every row of ``users`` and then, for each of them, read
that user's role assignments and ensured a ``user_chat_prefs`` row. Four
uvicorn workers all run the lifespan, concurrently, so a directory of fifty
thousand accounts meant two hundred thousand of those pairs against a database
that is also serving the first requests. Startup got slower every time someone
was hired.

Neither piece of work needs every user:

* only the bootstrap account and accounts still carrying a legacy admin slug
  can change under ``ensure_super_admin_roles``;
* the chat-prefs row is created on demand at login and by every reader of the
  prefs, so the startup pass is a backfill and a backfill is one statement.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.security import hash_password
from app.models.chat import UserChatPrefs
from app.models.user import User, UserRoleAssignment
from app.services.rbac import LEGACY_ADMIN_SLUG, SUPER_ADMIN_SLUG
from app.services.user_chat_storage_service import backfill_user_chat_prefs
from app.services.user_role_service import (
    ensure_bootstrap_admin_roles,
    ensure_super_admin_roles,
    get_user_role_slugs,
)


class _CountingSession:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.executions = 0

    async def execute(self, *args, **kwargs):
        self.executions += 1
        return await self._inner.execute(*args, **kwargs)

    async def get(self, *args, **kwargs):
        self.executions += 1
        return await self._inner.get(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def _people(db_session, prefix: str, count: int) -> list[User]:
    rows = [
        User(
            username=f"{prefix}_{index}",
            hashed_password=hash_password("a-password"),
            auth_provider="local",
            is_active=True,
        )
        for index in range(count)
    ]
    db_session.add_all(rows)
    await db_session.flush()
    return rows


async def test_the_bootstrap_account_is_still_promoted(db_session):
    (person,) = await _people(db_session, "the_bootstrap_admin", 1)

    await ensure_bootstrap_admin_roles(db_session, admin_username=person.username)
    await db_session.flush()

    assert SUPER_ADMIN_SLUG in await get_user_role_slugs(db_session, person.id)


async def test_the_narrowed_pass_agrees_with_the_pass_over_everyone(db_session):
    """The proof for a narrowing: same outcome, fewer rows looked at.

    Every shape that reaches ``ensure_super_admin_roles`` at startup, run both
    ways. (A raw ``admin`` / ``full_administrator`` assignment resolves to the
    end-user role today - those slugs are no longer assignable - so that branch
    changes nothing; it is in the candidate set because when it does mean
    something, it must not be skipped.)
    """

    shapes: dict[str, list[str]] = {
        "shape_bootstrap": [],
        "shape_legacy_admin": [LEGACY_ADMIN_SLUG],
        "shape_super_admin": [SUPER_ADMIN_SLUG],
        "shape_ordinary": [],
    }
    for name, slugs in shapes.items():
        (person,) = await _people(db_session, name, 1)
        for slug in slugs:
            db_session.add(UserRoleAssignment(user_id=person.id, role_slug=slug))
    await db_session.flush()

    admin_username = "shape_bootstrap_0"
    everyone = (await db_session.execute(select(User))).scalars().all()
    for person in everyone:
        await ensure_super_admin_roles(db_session, person, admin_username=admin_username)
    await db_session.flush()
    from_the_loop = {person.username: await get_user_role_slugs(db_session, person.id) for person in everyone}

    await ensure_bootstrap_admin_roles(db_session, admin_username=admin_username)
    await db_session.flush()
    from_the_narrowed_pass = {person.username: await get_user_role_slugs(db_session, person.id) for person in everyone}

    assert from_the_narrowed_pass == from_the_loop
    assert SUPER_ADMIN_SLUG in from_the_loop[admin_username]


async def test_an_ordinary_user_is_left_alone(db_session):
    (person,) = await _people(db_session, "an_ordinary_person", 1)

    await ensure_bootstrap_admin_roles(db_session, admin_username="somebody-else")
    await db_session.flush()

    assert SUPER_ADMIN_SLUG not in await get_user_role_slugs(db_session, person.id)


async def test_the_cost_does_not_grow_with_the_directory(db_session):
    """The whole point: adding users must not add round trips."""

    await _people(db_session, "small_directory", 5)
    await db_session.commit()
    small = _CountingSession(db_session)
    await ensure_bootstrap_admin_roles(small, admin_username="nobody-here")

    await _people(db_session, "large_directory", 40)
    await db_session.commit()
    large = _CountingSession(db_session)
    await ensure_bootstrap_admin_roles(large, admin_username="nobody-here")

    assert large.executions == small.executions, f"{small.executions} statements for 5 users, {large.executions} for 45"


async def test_the_chat_prefs_backfill_covers_everyone(db_session):
    await _people(db_session, "needs_prefs", 6)
    await db_session.commit()

    created = await backfill_user_chat_prefs(db_session)
    await db_session.commit()

    users = int((await db_session.execute(select(func.count()).select_from(User))).scalar_one())
    prefs = int((await db_session.execute(select(func.count()).select_from(UserChatPrefs))).scalar_one())
    assert prefs == users
    assert created >= 6


async def test_the_chat_prefs_backfill_is_idempotent_and_bounded(db_session):
    await _people(db_session, "already_has_prefs", 20)
    await db_session.commit()
    await backfill_user_chat_prefs(db_session)
    await db_session.commit()

    counting = _CountingSession(db_session)
    created = await backfill_user_chat_prefs(counting)
    await db_session.commit()

    assert created == 0
    assert counting.executions <= 4, f"a no-op backfill took {counting.executions} statements"
