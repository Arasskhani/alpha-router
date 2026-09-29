"""Reading the last days of chats again for memory, by the administrator's hand.

Extraction used to drop the start of a long stretch of chat while marking it
mined; what it dropped is still in the chats. The administrator can have the
last days read again, and it must read only what the people (and projects)
agreed to be learned from.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.models.chat import ChatMessage, ChatSession, UserChatPrefs, UserMemoryEvent, UserMemoryJob
from app.models.knowledge import OutboxEvent
from app.models.model_catalog import AIModel
from app.models.project import Project, ProjectConfigVersion, ProjectMemoryEvent, ProjectMemoryJob
from app.models.system import SystemSetting
from app.models.user import User
from app.services.memory_relearn_service import (
    RelearnUnavailable,
    estimate_relearn,
    plan_relearn,
    start_relearn,
)

NOW = dt.datetime.utcnow()


def _ago(days: float) -> dt.datetime:
    return NOW - dt.timedelta(days=days)


async def _person(db, name: str, *, prefs_changed: float | None = None, learning: bool = True, active=True) -> User:
    row = User(username=name, email=f"{name}@test", hashed_password="x", auth_provider="local", is_active=active)
    db.add(row)
    await db.flush()
    if prefs_changed is not None:
        db.add(UserChatPrefs(user_id=row.id, prefs={"memory_auto_capture": learning}, updated_at=_ago(prefs_changed)))
    return row


async def _chat(db, owner: User, said: list[float], *, project_id=None, private=False, channel="ai") -> str:
    """A chat whose turns were said the given number of days ago, oldest first."""
    session_id = str(uuid.uuid4())
    db.add(
        ChatSession(
            id=session_id,
            user_id=owner.id,
            title="t",
            model_id="m",
            private_mode=private,
            project_id=project_id,
            channel_kind=channel,
        )
    )
    await db.flush()
    for sequence, days in enumerate(said, start=1):
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_id=owner.id,
                role="user" if sequence % 2 else "assistant",
                content=f"turn {sequence} " + "x" * 90,
                sequence=sequence,
                created_at=_ago(days),
            )
        )
    await db.flush()
    return session_id


def _ranges(plan) -> dict[str, tuple[int, int]]:
    return {chat.session_id: (chat.first, chat.last) for chat in plan.chats}


class TestWhatIsRead:
    async def test_the_last_days_of_people_who_learn(self, db_session):
        ana = await _person(db_session, "ana", prefs_changed=60)
        long_chat = await _chat(db_session, ana, [40, 40, 10, 10, 2, 2])
        await _chat(db_session, ana, [1, 1], private=True)
        await _chat(db_session, ana, [1, 1], channel="member")
        off = await _person(db_session, "off", prefs_changed=60, learning=False)
        await _chat(db_session, off, [1, 1])
        gone = await _person(db_session, "gone", active=False)
        await _chat(db_session, gone, [1, 1])
        await db_session.commit()

        plan = await plan_relearn(db_session, days=30, now=NOW)
        assert _ranges(plan) == {long_chat: (3, 6)}
        assert plan.summary()["messages"] == 4
        week = await plan_relearn(db_session, days=7, now=NOW)
        assert _ranges(week) == {long_chat: (5, 6)}

    async def test_nothing_before_a_delete_all_or_a_settings_change(self, db_session):
        wiped = await _person(db_session, "wiped", prefs_changed=60)
        wiped_chat = await _chat(db_session, wiped, [20, 20, 3, 3])
        db_session.add(
            UserMemoryEvent(
                id=str(uuid.uuid4()),
                user_id=wiped.id,
                event_type="purged",
                actor="user",
                detail={"deleted": 4, "scope": "all"},
                created_at=_ago(5),
            )
        )
        # A system "purged" (a suppressed fact) is not the person's delete-all.
        db_session.add(
            UserMemoryEvent(
                id=str(uuid.uuid4()),
                user_id=wiped.id,
                event_type="purged",
                actor="system",
                detail={"reason": "suppressed_hash"},
                created_at=_ago(1),
            )
        )
        changed = await _person(db_session, "changed", prefs_changed=4)
        changed_chat = await _chat(db_session, changed, [20, 20, 2, 2])
        never = await _person(db_session, "never")
        never_chat = await _chat(db_session, never, [20, 20])
        await db_session.commit()

        plan = await plan_relearn(db_session, days=30, now=NOW)
        assert _ranges(plan) == {wiped_chat: (3, 4), changed_chat: (3, 4), never_chat: (1, 2)}


async def _project(db, owner: User, project_id: str, versions: list[tuple[float, bool]]) -> None:
    db.add(
        Project(
            id=project_id,
            name=project_id,
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    await db.flush()
    last = None
    for revision, (days, on) in enumerate(versions, start=1):
        last = ProjectConfigVersion(
            id=str(uuid.uuid4()),
            project_id=project_id,
            revision=revision,
            memory_enabled=True,
            memory_auto_capture=on,
            created_at=_ago(days),
        )
        db.add(last)
    await db.flush()
    project = await db.get(Project, project_id)
    project.active_config_version_id = last.id if last else None
    await db.flush()


class TestProjects:
    async def test_from_when_learning_was_last_turned_back_on(self, db_session):
        owner = await _person(db_session, "owner", prefs_changed=90)
        await _project(db_session, owner, "p-back", [(40, True), (20, False), (10, True)])
        back = await _chat(db_session, owner, [15, 15, 5, 5], project_id="p-back")
        await _project(db_session, owner, "p-off", [(40, True), (20, False)])
        await _chat(db_session, owner, [5, 5], project_id="p-off")
        await _project(db_session, owner, "p-cleared", [(40, True)])
        cleared = await _chat(db_session, owner, [15, 15, 2, 2], project_id="p-cleared")
        db_session.add(
            ProjectMemoryEvent(
                id=str(uuid.uuid4()),
                project_id="p-cleared",
                event_type="deleted_all_auto",
                actor="user",
                detail={"count": 3},
                created_at=_ago(3),
            )
        )
        await db_session.commit()

        plan = await plan_relearn(db_session, days=30, now=NOW)
        assert _ranges(plan) == {back: (3, 4), cleared: (3, 4)}
        assert {chat.scope for chat in plan.chats} == {"project"}


class TestStarting:
    @pytest.fixture
    async def ready(self, db_session):
        db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        db_session.add(SystemSetting(key="memory_relearn_enabled", value="true"))
        await db_session.commit()

    async def test_queues_one_job_per_chat_from_its_first_message_in_those_days(self, db_session, ready):
        ana = await _person(db_session, "ana", prefs_changed=60)
        first = await _chat(db_session, ana, [40, 40, 10, 10, 2, 2])
        second = await _chat(db_session, ana, [3, 3])
        await db_session.commit()

        result = await start_relearn(db_session, days=30)
        await db_session.commit()

        assert (result["queued"], result["merged"]) == (2, 0)
        jobs = {job.session_id: job for job in (await db_session.execute(select(UserMemoryJob))).scalars()}
        assert (jobs[first].extracted_sequence, jobs[first].watermark_sequence, jobs[first].status) == (2, 6, "pending")
        assert (jobs[second].extracted_sequence, jobs[second].watermark_sequence) == (0, 2)
        assert jobs[first].run_after != jobs[second].run_after
        events = (await db_session.execute(select(OutboxEvent.aggregate_id))).scalars().all()
        assert set(events) == {jobs[first].id, jobs[second].id}

    async def test_a_chat_with_an_open_job_has_that_job_start_earlier(self, db_session, ready):
        ana = await _person(db_session, "ana", prefs_changed=60)
        chat = await _chat(db_session, ana, [10, 10, 1, 1, 0, 0])
        db_session.add(
            UserMemoryJob(
                id=str(uuid.uuid4()),
                user_id=ana.id,
                session_id=chat,
                status="pending",
                watermark_sequence=6,
                extracted_sequence=4,
                run_after=NOW,
                attempt_count=0,
                max_attempts=5,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await db_session.commit()
        result = await start_relearn(db_session, days=30)
        await db_session.commit()
        assert (result["queued"], result["merged"]) == (0, 1)
        job = (await db_session.execute(select(UserMemoryJob))).scalars().one()
        assert (job.extracted_sequence, job.watermark_sequence) == (0, 6)

    async def test_project_chats_get_project_jobs(self, db_session, ready):
        owner = await _person(db_session, "owner", prefs_changed=90)
        await _project(db_session, owner, "p-on", [(40, True)])
        chat = await _chat(db_session, owner, [5, 5], project_id="p-on")
        await db_session.commit()
        await start_relearn(db_session, days=30)
        await db_session.commit()
        job = (await db_session.execute(select(ProjectMemoryJob))).scalars().one()
        assert (job.project_id, job.session_id, job.extracted_sequence) == ("p-on", chat, 0)

    async def test_is_refused_while_switched_off_or_without_a_model(self, db_session):
        with pytest.raises(RelearnUnavailable, match="switched off"):
            await start_relearn(db_session, days=30)
        db_session.add(SystemSetting(key="memory_relearn_enabled", value="true"))
        await db_session.commit()
        with pytest.raises(RelearnUnavailable, match="extraction model"):
            await start_relearn(db_session, days=30)


class TestTheEstimate:
    async def test_counts_what_would_be_read_and_prices_it(self, db_session):
        db_session.add(
            AIModel(
                id=1,
                external_id="gpt-extract",
                provider_type="openai",
                input_cost_per_1k=0.001,
                output_cost_per_1k=0.002,
                pricing_unit="1k",
            )
        )
        db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        ana = await _person(db_session, "ana", prefs_changed=60)
        await _chat(db_session, ana, [2, 2, 2, 2])
        await db_session.commit()

        estimate = await estimate_relearn(db_session, days=30)
        assert estimate["enabled"] is False
        assert estimate["chats"] == {"user": 1, "project": 0}
        assert (estimate["messages"], estimate["parts"]) == (4, 1)
        assert estimate["characters"] == sum(len(f"turn {n} " + "x" * 90) for n in range(1, 5))
        assert estimate["estimated_cost_usd"] is not None and estimate["estimated_cost_usd"] > 0

    async def test_of_nothing_is_nothing(self, db_session):
        estimate = await estimate_relearn(db_session, days=30)
        assert (estimate["parts"], estimate["estimated_cost_usd"]) == (0, 0.0)


class TestTheEndpoints:
    @pytest.fixture(autouse=True)
    def _on_the_test_engine(self, session_factory, monkeypatch):
        from app.database import get_read_db
        from app.main import app as fastapi_app
        from app.services import admin_ip_allowlist_service

        async def _read_db():
            async with session_factory() as session:
                yield session

        monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
        monkeypatch.setitem(fastapi_app.dependency_overrides, get_read_db, _read_db)
        admin_ip_allowlist_service.invalidate_restriction_cache()
        yield
        admin_ip_allowlist_service.invalidate_restriction_cache()

    def _sign_in(self, client, person: User) -> dict[str, str]:
        from app.config import get_settings
        from app.core.security import create_access_token

        settings = get_settings()
        client.cookies.set(settings.session_cookie_name, create_access_token(person.username, "user"))
        client.cookies.set(settings.csrf_cookie_name, "csrf-token")
        return {settings.csrf_header_name: "csrf-token"}

    async def test_estimate_then_start_and_the_start_is_audited(self, client, db_session, admin):
        from app.models.security import SecurityAuditEvent

        db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        ana = await _person(db_session, "ana", prefs_changed=60)
        await _chat(db_session, ana, [2, 2])
        await db_session.commit()
        headers = self._sign_in(client, admin)

        estimate = await client.get("/api/admin/memory/relearn/estimate", params={"days": 30}, headers=headers)
        assert estimate.status_code == 200, estimate.text
        assert estimate.json()["chats"] == {"user": 1, "project": 0}
        refused = await client.post("/api/admin/memory/relearn", json={"days": 30}, headers=headers)
        assert refused.status_code == 409 and "switched off" in refused.text

        db_session.add(SystemSetting(key="memory_relearn_enabled", value="true"))
        await db_session.commit()
        started = await client.post("/api/admin/memory/relearn", json={"days": 30}, headers=headers)
        assert started.status_code == 200, started.text
        assert started.json()["queued"] == 1
        audit = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "memory_relearn_started")
                )
            )
            .scalars()
            .all()
        )
        assert len(audit) == 1

    async def test_someone_else_can_do_neither(self, client, db_session, user):
        headers = self._sign_in(client, user)
        assert (await client.get("/api/admin/memory/relearn/estimate", headers=headers)).status_code == 403
        assert (await client.post("/api/admin/memory/relearn", json={"days": 7}, headers=headers)).status_code == 403

    async def test_days_are_bounded(self, client, db_session, admin):
        headers = self._sign_in(client, admin)
        assert (await client.post("/api/admin/memory/relearn", json={"days": 400}, headers=headers)).status_code == 422
