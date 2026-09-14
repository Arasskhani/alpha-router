"""Tests for directory profile context injection."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.user_profile_context_service import (
    augment_messages_with_profile,
    format_profile_system_block,
    profile_facts_from_user,
    profile_payload,
)


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def test_profile_facts_company_department_job_title_report_to() -> None:
    user = User(
        username="u",
        email="u@test.local",
        company="  Acme Corp ",
        department="  Engineering  ",
        job_title="  Senior Engineer ",
        office="Tehran",
        reporting_to="  CN=Boss ",
    )
    assert profile_facts_from_user(user) == [
        ("Company", "Acme Corp"),
        ("Department", "Engineering"),
        ("Job title", "Senior Engineer"),
        ("Report to", "CN=Boss"),
    ]
    payload = profile_payload(user)
    assert payload == {
        "company": "Acme Corp",
        "department": "Engineering",
        "job_title": "Senior Engineer",
        "reporting_to": "CN=Boss",
    }
    block = format_profile_system_block(profile_facts_from_user(user))
    assert "Company: Acme Corp" in block
    assert "Department: Engineering" in block
    assert "Job title: Senior Engineer" in block
    assert "Report to: CN=Boss" in block
    assert "Tehran" not in block


async def _inject_roundtrip() -> None:
    engine, factory = await _make_session()
    async with factory() as db:
        user = User(
            username="alice",
            email="a@test.local",
            auth_provider="local",
            company="Alpha",
            department="Platform",
            job_title="Engineer",
            reporting_to="Manager One",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        original = [dict(m) for m in messages]
        out = await augment_messages_with_profile(db, messages, user_id=user.id, private_mode=False)
        assert out[0]["role"] == "system"
        assert "Company: Alpha" in out[0]["content"]
        assert "Department: Platform" in out[0]["content"]
        assert "Job title: Engineer" in out[0]["content"]
        assert "Report to: Manager One" in out[0]["content"]
        assert out[1:] == original

        skipped = await augment_messages_with_profile(db, original, user_id=user.id, private_mode=True)
        assert skipped == original

        empty_user = User(
            username="bob",
            email="b@test.local",
            auth_provider="local",
            company="",
            department="",
            job_title=None,
            reporting_to=None,
        )
        db.add(empty_user)
        await db.commit()
        await db.refresh(empty_user)
        unchanged = await augment_messages_with_profile(db, original, user_id=empty_user.id, private_mode=False)
        assert unchanged == original
    await engine.dispose()


def test_augment_messages_with_profile() -> None:
    asyncio.run(_inject_roundtrip())
