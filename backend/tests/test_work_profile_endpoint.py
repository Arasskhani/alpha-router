"""The Work profile screen has an endpoint of its own.

It used to read the directory fields out of ``GET /api/user/memories``. That
one request listed the account's memories, loaded its memory preferences and
read the deployment's memory settings - and threw all three away to keep four
strings. Two unrelated features shared a request, so either could take the
other's screen down, and a deployment with memory turned off had a Work
profile tab that could not open.
"""

from __future__ import annotations

import pytest

from app.api.user_memories import get_user_memories
from app.api.user_routes import user_work_profile


@pytest.fixture
async def person(db_session):
    from app.core.security import hash_password
    from app.models.user import User

    row = User(
        username="profile_person",
        email="profile_person@test",
        hashed_password=hash_password("x"),
        auth_provider="local",
        is_active=True,
        company="  BitPin ",
        department="IT",
        job_title="IT Manager",
        reporting_to="Yazdan Yazdizadeh",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


class TestTheWorkProfileEndpoint:
    async def test_it_answers_with_the_four_directory_fields(self, db_session, person):
        payload = await user_work_profile(user=person, db=db_session)
        assert payload == {
            "company": "BitPin",
            "department": "IT",
            "job_title": "IT Manager",
            "reporting_to": "Yazdan Yazdizadeh",
        }

    async def test_an_account_with_nothing_set_answers_with_nulls(self, db_session, user):
        payload = await user_work_profile(user=user, db=db_session)
        assert payload == {
            "company": None,
            "department": None,
            "job_title": None,
            "reporting_to": None,
        }

    async def test_it_reads_the_account_as_it_is_now(self, db_session, person):
        """A directory sync that runs while the tab is open should be visible
        on the next open, not on the next sign-in."""
        person.department = "Engineering"
        await db_session.commit()
        payload = await user_work_profile(user=person, db=db_session)
        assert payload["department"] == "Engineering"


class TestMemoryStandsOnItsOwn:
    async def test_the_memories_payload_no_longer_carries_the_profile(self, db_session, person):
        payload = await get_user_memories(limit=10, offset=0, user=person, db=db_session)
        assert "profile" not in payload
        assert set(payload) == {
            "memories",
            "total",
            "limit",
            "offset",
            "auto_capture",
            "memory_enabled",
            "feature_enabled",
            "extraction_configured",
        }

    async def test_the_work_profile_does_not_need_the_memory_feature(self, db_session, person, monkeypatch):
        """Turning memory off, or breaking it, must not take this screen with
        it - which is the whole reason the two were separated."""

        async def boom(*args, **kwargs):
            raise RuntimeError("memory is unavailable")

        monkeypatch.setattr("app.api.user_memories.list_memories", boom)
        payload = await user_work_profile(user=person, db=db_session)
        assert payload["company"] == "BitPin"
