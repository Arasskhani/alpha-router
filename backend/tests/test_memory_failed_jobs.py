"""Failed memory jobs: why they failed, and running them again.

A job that failed for good was a number on Admin -> Memory ("Dead letter")
with no reason and no way to run it again. The reasons are listed, grouped,
and the administrator sends the jobs back to the queue; a job goes on from
where its chat was mined to, so nothing is mined twice.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.chat import ChatSession, UserMemoryJob
from app.models.knowledge import OutboxEvent
from app.models.project import Project, ProjectMemoryJob
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services.memory_job_admin_service import failure_reason, list_failed_jobs, retry_failed_jobs
from app.services.user_role_service import set_user_roles


def _job(model, *, owner: dict, session_id: str, status: str, extracted: int, watermark: int, error=None, minutes=0):
    at = dt.datetime.utcnow() - dt.timedelta(minutes=minutes)
    return model(
        id=str(uuid.uuid4()),
        **owner,
        session_id=session_id,
        status=status,
        watermark_sequence=watermark,
        extracted_sequence=extracted,
        run_after=at,
        attempt_count=5 if status == "dead" else 0,
        max_attempts=5,
        last_error=error,
        created_at=at,
        updated_at=at,
    )


@pytest.fixture
async def chat(db_session, user) -> ChatSession:
    row = ChatSession(id=str(uuid.uuid4()), user_id=user.id, title="Private words", model_id="m", private_mode=False)
    db_session.add(row)
    await db_session.commit()
    return row


class TestReasons:
    def test_are_the_first_line_shortened_with_keys_taken_out(self):
        assert failure_reason("RateLimitError: slow down\nTraceback ...") == "RateLimitError: slow down"
        assert "sk-abcdef" not in failure_reason("AuthenticationError: bad key sk-abcdefghijklmnop1234")
        assert "[redacted]" in failure_reason("Bearer abc.def.ghi rejected")
        assert len(failure_reason("x " * 400)) <= 300
        assert failure_reason(None) == "No reason recorded"

    async def test_are_listed_grouped_with_who_the_job_was_for(self, db_session, user, chat):
        owner = {"user_id": user.id}
        db_session.add_all(
            [
                _job(
                    UserMemoryJob,
                    owner=owner,
                    session_id=chat.id,
                    status="dead",
                    extracted=0,
                    watermark=4,
                    error="Memory extraction model is unavailable",
                ),
                _job(
                    UserMemoryJob,
                    owner=owner,
                    session_id=chat.id,
                    status="dead",
                    extracted=4,
                    watermark=8,
                    error="Memory extraction model is unavailable",
                    minutes=5,
                ),
                _job(
                    UserMemoryJob,
                    owner=owner,
                    session_id=chat.id,
                    status="dead",
                    extracted=8,
                    watermark=9,
                    error="No JSON object in extractor output",
                    minutes=10,
                ),
                _job(UserMemoryJob, owner=owner, session_id=chat.id, status="succeeded", extracted=9, watermark=9),
            ]
        )
        await db_session.commit()
        listed = await list_failed_jobs(db_session, "user")
        assert listed["total"] == 3
        assert listed["reasons"] == [
            {"reason": "Memory extraction model is unavailable", "count": 2},
            {"reason": "No JSON object in extractor output", "count": 1},
        ]
        first = listed["jobs"][0]
        assert first["owner"] == user.username and first["mined_to"] == 0 and first["of"] == 4
        # The chat's title (the person's words) is not what identifies it.
        assert "Private words" not in str(listed)


class TestRetry:
    async def test_puts_a_job_back_in_the_queue_from_where_it_stopped(self, db_session, user, chat):
        dead = _job(
            UserMemoryJob,
            owner={"user_id": user.id},
            session_id=chat.id,
            status="dead",
            extracted=20,
            watermark=50,
            error="timeout",
        )
        db_session.add(dead)
        await db_session.commit()

        counts = await retry_failed_jobs(db_session, "user")
        await db_session.commit()

        assert counts == {"requeued": 1, "merged": 0, "covered": 0}
        await db_session.refresh(dead)
        assert (dead.status, dead.attempt_count, dead.extracted_sequence, dead.last_error) == ("retry", 0, 20, None)
        events = (await db_session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == dead.id))).scalars()
        assert [event.event_type for event in events] == ["memory.job.ready"]

    async def test_goes_on_from_where_a_later_job_got_to(self, db_session, user, chat):
        owner = {"user_id": user.id}
        dead = _job(
            UserMemoryJob, owner=owner, session_id=chat.id, status="dead", extracted=20, watermark=50, minutes=10
        )
        later = _job(UserMemoryJob, owner=owner, session_id=chat.id, status="succeeded", extracted=30, watermark=30)
        db_session.add_all([dead, later])
        await db_session.commit()
        assert (await retry_failed_jobs(db_session, "user"))["requeued"] == 1
        await db_session.refresh(dead)
        assert dead.extracted_sequence == 30

    async def test_drops_a_job_a_later_one_already_mined_past(self, db_session, user, chat):
        owner = {"user_id": user.id}
        dead = _job(UserMemoryJob, owner=owner, session_id=chat.id, status="dead", extracted=20, watermark=50)
        later = _job(UserMemoryJob, owner=owner, session_id=chat.id, status="succeeded", extracted=80, watermark=80)
        db_session.add_all([dead, later])
        await db_session.commit()
        assert await retry_failed_jobs(db_session, "user") == {"requeued": 0, "merged": 0, "covered": 1}
        await db_session.commit()
        assert await db_session.get(UserMemoryJob, dead.id) is None

    async def test_hands_its_stretch_to_the_chat_s_open_job(self, db_session, user, chat):
        owner = {"user_id": user.id}
        dead = _job(UserMemoryJob, owner=owner, session_id=chat.id, status="dead", extracted=20, watermark=70)
        open_job = _job(UserMemoryJob, owner=owner, session_id=chat.id, status="pending", extracted=20, watermark=60)
        db_session.add_all([dead, open_job])
        await db_session.commit()
        assert await retry_failed_jobs(db_session, "user") == {"requeued": 0, "merged": 1, "covered": 0}
        await db_session.commit()
        await db_session.refresh(open_job)
        assert (open_job.extracted_sequence, open_job.watermark_sequence) == (20, 70)
        assert await db_session.get(UserMemoryJob, dead.id) is None

    async def test_only_the_jobs_named_and_only_in_their_scope(self, db_session, user, chat):
        owner = {"user_id": user.id}
        one = _job(UserMemoryJob, owner=owner, session_id=chat.id, status="dead", extracted=0, watermark=4)
        db_session.add(one)
        db_session.add(
            Project(
                id="proj-dead",
                name="Billing",
                status="active",
                visibility="private",
                created_by_user_id=user.id,
                revision=1,
                acl_version=1,
            )
        )
        await db_session.flush()
        project_chat = ChatSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            title="Standup",
            model_id="m",
            project_id="proj-dead",
            channel_kind="ai",
        )
        db_session.add(project_chat)
        await db_session.flush()
        project_dead = _job(
            ProjectMemoryJob,
            owner={"project_id": "proj-dead"},
            session_id=project_chat.id,
            status="dead",
            extracted=0,
            watermark=6,
        )
        db_session.add(project_dead)
        await db_session.commit()

        assert (await retry_failed_jobs(db_session, "project", job_ids=[one.id]))["requeued"] == 0
        assert (await retry_failed_jobs(db_session, "project"))["requeued"] == 1
        await db_session.commit()
        await db_session.refresh(one)
        await db_session.refresh(project_dead)
        assert (one.status, project_dead.status) == ("dead", "retry")
        listed = await list_failed_jobs(db_session, "project")
        assert listed["total"] == 0


class TestTheEndpoints:
    @pytest.fixture(autouse=True)
    def _on_the_test_engine(self, session_factory, monkeypatch):
        """The admin IP guard and the read replica, both pointed at the test engine."""
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
        settings = get_settings()
        client.cookies.set(settings.session_cookie_name, create_access_token(person.username, "user"))
        client.cookies.set(settings.csrf_cookie_name, "csrf-token")
        return {settings.csrf_header_name: "csrf-token"}

    async def test_an_administrator_reads_and_retries_and_the_retry_is_audited(self, client, db_session, admin, chat):
        dead = _job(
            UserMemoryJob,
            owner={"user_id": chat.user_id},
            session_id=chat.id,
            status="dead",
            extracted=0,
            watermark=4,
            error="timeout",
        )
        db_session.add(dead)
        await db_session.commit()
        headers = self._sign_in(client, admin)

        listed = await client.get("/api/admin/memory/failed-jobs", params={"scope": "user"}, headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["reasons"] == [{"reason": "timeout", "count": 1}]

        done = await client.post("/api/admin/memory/failed-jobs/retry", json={"scope": "user"}, headers=headers)
        assert done.status_code == 200, done.text
        assert done.json()["requeued"] == 1
        audit = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "memory_jobs_retried")
                )
            )
            .scalars()
            .all()
        )
        assert len(audit) == 1 and audit[0].actor_user_id == admin.id

    async def test_someone_else_can_do_neither(self, client, db_session, user, chat):
        headers = self._sign_in(client, user)
        assert (await client.get("/api/admin/memory/failed-jobs", headers=headers)).status_code == 403
        denied = await client.post("/api/admin/memory/failed-jobs/retry", json={"scope": "user"}, headers=headers)
        assert denied.status_code == 403

    async def test_a_read_only_administrator_reads_but_does_not_retry(self, client, db_session):
        viewer = User(
            username="viewer", email="viewer@test", hashed_password="x", auth_provider="local", is_active=True
        )
        db_session.add(viewer)
        await db_session.flush()
        await set_user_roles(db_session, viewer, ["read_only_super_admin"])
        await db_session.commit()
        headers = self._sign_in(client, viewer)
        assert (await client.get("/api/admin/memory/failed-jobs", headers=headers)).status_code == 200
        denied = await client.post("/api/admin/memory/failed-jobs/retry", json={"scope": "user"}, headers=headers)
        assert denied.status_code == 403
