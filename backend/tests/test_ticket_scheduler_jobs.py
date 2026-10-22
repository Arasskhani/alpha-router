"""Scheduled Support ticket jobs: the 15-minute lifecycle pass and the nightly retention purge."""

from __future__ import annotations

import datetime
import json
import logging

import pytest
from sqlalchemy import select

from app.models.governance import GovernanceAuditEvent
from app.models.support_ticket import SupportTicket, SupportTicketAttachment, SupportTicketMessage
from app.models.system import SystemSetting
from app.models.user import User
from app.services import scheduler
from app.services import support_tickets as st
from app.services.rbac import SUPPORT_SLUG
from app.services.user_role_service import set_user_roles


def _ago(days: float = 0, hours: float = 0) -> datetime.datetime:
    return datetime.datetime.utcnow() - datetime.timedelta(days=days, hours=hours)


@pytest.fixture
def jobs_on_test_engine(session_factory, monkeypatch):
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_factory)
    return session_factory


async def _person(db, username, roles=None) -> User:
    person = User(username=username, email=f"{username}@corp.test", is_active=True)
    person.auth_provider = "local"
    db.add(person)
    await db.flush()
    if roles:
        await set_user_roles(db, person, roles)
    await db.commit()
    return person


_SEQ = iter(range(1, 10_000))


async def _ticket(db, reporter, **fields) -> SupportTicket:
    created = fields.pop("created_at", _ago(days=30))
    values = {
        "number": 9000 + next(_SEQ),
        "user_id": reporter.id,
        "reporter_name": "Reporter",
        "reporter_username": reporter.username,
        "title": "Title",
        "category": "Bug",
        "priority": "normal",
        "status": "open",
        "needs_staff": True,
        "user_unread": False,
        "created_at": created,
        "updated_at": created,
        "reopened_count": 0,
    }
    values.update(fields)
    row = SupportTicket(**values)
    db.add(row)
    await db.flush()
    return row


async def _fresh(session_factory, ticket_id) -> SupportTicket | None:
    async with session_factory() as db:
        return await db.get(SupportTicket, ticket_id)


async def _event_types(session_factory, ticket_id) -> list[str]:
    async with session_factory() as db:
        rows = await db.execute(
            select(SupportTicketMessage.event_json).where(
                SupportTicketMessage.ticket_id == ticket_id, SupportTicketMessage.kind == "event"
            )
        )
        return [json.loads(v)["type"] for v in rows.scalars().all()]


class TestLifecycle:
    async def test_it_closes_releases_and_commits(self, jobs_on_test_engine, db_session, user):
        majid = await _person(db_session, "majid", roles=[SUPPORT_SLUG])
        gone = await _person(db_session, "gone", roles=[SUPPORT_SLUG])
        stale = await _ticket(db_session, user, status="waiting", waiting_since=_ago(days=8), needs_staff=False)
        fresh = await _ticket(db_session, user, status="waiting", waiting_since=_ago(days=2), needs_staff=False)
        old_resolved = await _ticket(
            db_session, user, status="resolved", resolved_at=_ago(days=15), resolved_by="staff", needs_staff=False
        )
        new_resolved = await _ticket(
            db_session, user, status="resolved", resolved_at=_ago(days=3), resolved_by="user", needs_staff=False
        )
        kept = await _ticket(db_session, user, assignee_id=majid.id)
        orphan = await _ticket(db_session, user, assignee_id=gone.id)
        await db_session.commit()
        await set_user_roles(db_session, gone, [])  # loses the Support role
        await db_session.commit()

        await scheduler.job_ticket_lifecycle()

        closed = await _fresh(jobs_on_test_engine, stale.id)
        assert (closed.status, closed.closed_reason, closed.user_unread) == ("closed", "auto", True)
        assert await _event_types(jobs_on_test_engine, stale.id) == ["auto_closed"]
        assert (await _fresh(jobs_on_test_engine, fresh.id)).status == "waiting"
        done = await _fresh(jobs_on_test_engine, old_resolved.id)
        assert (done.status, done.closed_reason) == ("closed", "resolved")
        assert await _event_types(jobs_on_test_engine, old_resolved.id) == ["closed_resolved"]
        assert (await _fresh(jobs_on_test_engine, new_resolved.id)).status == "resolved"
        assert (await _fresh(jobs_on_test_engine, kept.id)).assignee_id == majid.id
        assert (await _fresh(jobs_on_test_engine, orphan.id)).assignee_id is None
        assert await _event_types(jobs_on_test_engine, orphan.id) == ["assignee_removed"]

    async def test_the_settings_decide_the_windows(self, jobs_on_test_engine, db_session, user):
        await st.save_settings(db_session, st.TicketSettings(auto_close_days=1, reopen_days=2))
        waiting = await _ticket(db_session, user, status="waiting", waiting_since=_ago(days=1, hours=1))
        resolved = await _ticket(db_session, user, status="resolved", resolved_at=_ago(days=2, hours=1))
        await db_session.commit()

        await scheduler.job_ticket_lifecycle()

        assert (await _fresh(jobs_on_test_engine, waiting.id)).status == "closed"
        assert (await _fresh(jobs_on_test_engine, resolved.id)).status == "closed"

    async def test_a_failing_step_is_logged_and_the_others_still_run(
        self, jobs_on_test_engine, db_session, user, monkeypatch, caplog
    ):
        resolved = await _ticket(db_session, user, status="resolved", resolved_at=_ago(days=20))
        await db_session.commit()

        async def boom(*_a, **_k):
            raise RuntimeError("auto-close fell over")

        monkeypatch.setattr(st, "close_waiting_tickets", boom)
        with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
            await scheduler.job_ticket_lifecycle()  # must not raise

        assert any(r.exc_info and "auto-close fell over" in str(r.exc_info[1]) for r in caplog.records)
        assert (await _fresh(jobs_on_test_engine, resolved.id)).status == "closed"


class TestRetention:
    async def test_old_closed_tickets_go_with_their_images_and_the_run_is_recorded(
        self, jobs_on_test_engine, db_session, user, monkeypatch
    ):
        removed: list[str] = []
        monkeypatch.setattr("app.services.object_storage_service.delete_object", removed.append)
        old = await _ticket(db_session, user, status="closed", closed_at=_ago(days=400), closed_reason="manual")
        message = SupportTicketMessage(ticket_id=old.id, kind="user", body="x", created_at=_ago(days=401))
        db_session.add(message)
        await db_session.flush()
        db_session.add(
            SupportTicketAttachment(
                ticket_id=old.id,
                message_id=message.id,
                storage_key="tickets/old.png",
                mime="image/png",
                bytes=10,
                width=1,
                height=1,
                sha256="ab" * 32,
                display_name="old.png",
            )
        )
        recent = await _ticket(db_session, user, status="closed", closed_at=_ago(days=30), closed_reason="auto")
        active = await _ticket(db_session, user, created_at=_ago(days=900))
        await db_session.commit()

        await scheduler.job_ticket_retention()
        await st.drain_storage_deletions()

        assert await _fresh(jobs_on_test_engine, old.id) is None
        assert await _fresh(jobs_on_test_engine, recent.id) is not None
        assert await _fresh(jobs_on_test_engine, active.id) is not None  # open tickets are never deleted by time
        assert removed == ["tickets/old.png"]
        async with jobs_on_test_engine() as db:
            events = (await db.execute(select(GovernanceAuditEvent))).scalars().all()
        assert [e.event_type for e in events] == ["governance.retention.support_tickets.purged"]
        assert events[0].resource_type == "support_tickets"

    async def test_zero_keeps_everything_and_records_nothing(self, jobs_on_test_engine, db_session, user):
        await st.save_settings(db_session, st.TicketSettings(retention_days=0))
        old = await _ticket(db_session, user, status="closed", closed_at=_ago(days=4000), closed_reason="manual")
        await db_session.commit()

        await scheduler.job_ticket_retention()

        assert await _fresh(jobs_on_test_engine, old.id) is not None
        async with jobs_on_test_engine() as db:
            assert (await db.execute(select(GovernanceAuditEvent))).scalars().all() == []

    async def test_a_failure_is_contained_and_logged(self, jobs_on_test_engine, monkeypatch, caplog):
        async def boom(*_a, **_k):
            raise RuntimeError("purge fell over")

        monkeypatch.setattr(st, "purge_closed_tickets", boom)
        with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
            await scheduler.job_ticket_retention()

        assert any(r.exc_info and "purge fell over" in str(r.exc_info[1]) for r in caplog.records)

    async def test_a_failure_to_record_does_not_undo_the_purge(
        self, jobs_on_test_engine, db_session, user, monkeypatch, caplog
    ):
        old = await _ticket(db_session, user, status="closed", closed_at=_ago(days=400), closed_reason="manual")
        await db_session.commit()

        async def boom(*_a, **_k):
            raise RuntimeError("chain unavailable")

        monkeypatch.setattr("app.services.agent_governance_service.append_governance_audit_event", boom)
        with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
            await scheduler.job_ticket_retention()

        assert await _fresh(jobs_on_test_engine, old.id) is None
        assert any("could not be recorded" in r.getMessage() for r in caplog.records)


async def test_both_jobs_are_scheduled(monkeypatch):
    added = []
    monkeypatch.setattr(scheduler.scheduler, "add_job", lambda *a, **k: added.append((a, k)))
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    scheduler.start_scheduler()
    jobs = {k.get("id"): (a, k) for a, k in added}
    lifecycle_args, lifecycle = jobs["ticket_lifecycle"]
    assert lifecycle_args == (scheduler.job_ticket_lifecycle, "interval") and lifecycle["minutes"] == 15
    retention_args, retention = jobs["ticket_retention"]
    assert retention_args == (scheduler.job_ticket_retention, "cron")
    assert (retention["hour"], retention["minute"]) == (4, 50)


async def test_the_settings_row_is_untouched_by_the_jobs(jobs_on_test_engine):
    await scheduler.job_ticket_lifecycle()
    await scheduler.job_ticket_retention()
    async with jobs_on_test_engine() as db:
        assert (await db.execute(select(SystemSetting).where(SystemSetting.key == st.SETTINGS_KEY))).first() is None
