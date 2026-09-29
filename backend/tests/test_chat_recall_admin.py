"""The administrator's view of recall: how far the index has got, and indexing the chats from before it.

Chats are indexed as they go on; the ones from before recall was switched on
are indexed only when the administrator asks, after an estimate - and the
backfill reads only what indexing as they go would have read.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.chat import ChatRecallIndex
from app.models.knowledge import OutboxEvent
from app.models.security import SecurityAuditEvent
from app.models.system import SystemSetting
from app.services.chat_recall_service import estimate_backfill, recall_status, start_backfill
from app.services.user_chat_storage_service import save_user_prefs
from tests.test_chat_recall import WORKOUT, _chat, _indexed, _person, store  # noqa: F401 -- the store fixture


async def test_status_counts_what_is_indexed_and_the_jobs(db_session, user, store):  # noqa: F811
    chat = await _chat(db_session, user, "Workout", WORKOUT)
    await _indexed(db_session, chat)
    failed = await _chat(db_session, user, "Broken", WORKOUT)
    row = await _indexed(db_session, failed)
    row.status, row.chunk_count = "failed", 0
    await db_session.commit()
    status = await recall_status(db_session)
    assert status["enabled"] is True
    assert (status["indexed_chats"], status["chunks"], status["failed"]) == (1, 2, 1)


async def test_the_backfill_reads_only_what_indexing_as_they_go_would(db_session, user, store):  # noqa: F811
    waiting = await _chat(db_session, user, "Workout", WORKOUT)
    done = await _chat(db_session, user, "Done", WORKOUT)
    await _indexed(db_session, done)
    await _chat(db_session, user, "Private", WORKOUT, private=True)
    quiet = await _person(db_session, "quiet")
    await save_user_prefs(db_session, quiet.id, {"memory_recall_chats": False})
    await _chat(db_session, quiet, "Theirs", WORKOUT)
    await db_session.commit()

    estimate = await estimate_backfill(db_session)
    assert (estimate["chats"], estimate["messages"]) == (1, 4)
    assert estimate["characters"] == sum(len(text) for text in WORKOUT)

    assert await start_backfill(db_session) == {"queued": 1}
    await db_session.commit()
    events = (await db_session.execute(select(OutboxEvent.aggregate_id))).scalars().all()
    assert events == [waiting.id]
    row = await db_session.get(ChatRecallIndex, waiting.id)
    assert row.status == "pending"


async def test_the_backfill_never_reads_past_a_delete_all(db_session, user, store):  # noqa: F811
    from app.services.user_memory_service import delete_all_memories

    await _chat(db_session, user, "Workout", WORKOUT)
    await delete_all_memories(db_session, user.id)
    await db_session.commit()
    assert (await estimate_backfill(db_session))["chats"] == 0


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

    def _sign_in(self, client, person) -> dict[str, str]:
        settings = get_settings()
        client.cookies.set(settings.session_cookie_name, create_access_token(person.username, "user"))
        client.cookies.set(settings.csrf_cookie_name, "csrf-token")
        return {settings.csrf_header_name: "csrf-token"}

    async def test_an_administrator_estimates_then_starts_and_the_start_is_audited(
        self,
        client,
        db_session,
        admin,
        store,  # noqa: F811
    ):
        await _chat(db_session, admin, "Workout", WORKOUT)
        headers = self._sign_in(client, admin)
        assert (await client.get("/api/admin/memory/recall/status", headers=headers)).json()["enabled"] is True
        estimate = await client.get("/api/admin/memory/recall/backfill/estimate", headers=headers)
        assert estimate.status_code == 200 and estimate.json()["chats"] == 1
        started = await client.post("/api/admin/memory/recall/backfill", headers=headers)
        assert started.status_code == 200, started.text
        assert started.json()["queued"] == 1
        audit = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "memory_recall_backfill_started")
                )
            )
            .scalars()
            .all()
        )
        assert len(audit) == 1

    async def test_refused_while_recall_is_off_and_never_for_anyone_else(self, client, db_session, admin, user):
        db_session.add(SystemSetting(key="memory_recall_enabled", value="false"))
        await db_session.commit()
        refused = await client.post("/api/admin/memory/recall/backfill", headers=self._sign_in(client, admin))
        assert refused.status_code == 409
        headers = self._sign_in(client, user)
        assert (await client.get("/api/admin/memory/recall/status", headers=headers)).status_code == 403
        assert (await client.post("/api/admin/memory/recall/backfill", headers=headers)).status_code == 403
