"""Support tickets: the lifecycle rules in app.services.support_tickets, without the HTTP layer."""

from __future__ import annotations

import asyncio
import datetime
import json
import os

import pytest
from sqlalchemy import func, select

from app.models.support_ticket import SupportTicket, SupportTicketAttachment, SupportTicketMessage
from app.models.system import SystemSetting
from app.models.user import User
from app.services import support_tickets as st
from app.services.rbac import READ_ONLY_SUPER_ADMIN_SLUG, SUPPORT_SLUG
from app.services.user_role_service import set_user_roles

_ON_POSTGRES = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")

NOW = datetime.datetime(2026, 10, 22, 9, 0, 0)


async def _person(db, username, *, roles=None, active=True, email=None, display=None, department=None) -> User:
    person = User(
        username=username,
        email=email,
        display_name=display,
        department=department,
        is_active=active,
        auth_provider="local",
    )
    db.add(person)
    await db.flush()
    if roles:
        await set_user_roles(db, person, roles)
    await db.commit()
    return person


def _image(n: int = 1) -> st.StoredImage:
    return st.StoredImage(
        storage_key=f"tickets/2026/10/img{n}.png",
        mime="image/png",
        bytes=1000 * n,
        width=100,
        height=80,
        sha256="ab" * 32,
        display_name=f"screen{n}.png",
    )


async def _open(db, person, settings=None, **overrides) -> SupportTicket:
    values = {
        "title": "Export fails",
        "description": "The PDF export stops at 90%.",
        "category": "Bug",
        "priority": "normal",
        "context": None,
        "images": [],
    }
    values.update(overrides)
    ticket = await st.create_ticket(db, user=person, settings=settings or st.TicketSettings(), **values)
    await db.commit()
    return ticket


async def _kinds(db, ticket) -> list[str]:
    rows = await db.execute(
        select(SupportTicketMessage.kind)
        .where(SupportTicketMessage.ticket_id == ticket.id)
        .order_by(SupportTicketMessage.id)
    )
    return list(rows.scalars().all())


async def _events(db, ticket) -> list[dict]:
    rows = await db.execute(
        select(SupportTicketMessage.event_json)
        .where(SupportTicketMessage.ticket_id == ticket.id, SupportTicketMessage.kind == "event")
        .order_by(SupportTicketMessage.id)
    )
    return [json.loads(v) for v in rows.scalars().all()]


@pytest.fixture
async def support(db_session):
    return await _person(db_session, "majid", roles=[SUPPORT_SLUG], email="majid@corp.test", display="Majid Arasskhani")


@pytest.fixture
async def other_support(db_session):
    return await _person(db_session, "ali", roles=[SUPPORT_SLUG], email="ali@corp.test", display="Ali Mohammadi")


class TestCreating:
    async def test_a_new_ticket_is_open_numbered_and_answered_automatically(self, db_session, user):
        user.display_name = "Sara Karimi"
        user.department = "Finance"
        await db_session.commit()
        ticket = await _open(
            db_session,
            user,
            images=[_image(1), _image(2)],
            context={"browser": "Firefox 131", "page": "/app/chat", "secret": "dropped", "app_version": "x" * 500},
        )
        assert ticket.number == 1000 + ticket.id
        assert (ticket.status, ticket.needs_staff, ticket.user_unread) == ("open", True, False)
        assert (ticket.reporter_name, ticket.reporter_username) == ("Sara Karimi", "fixture_user")
        assert (ticket.reporter_email, ticket.reporter_department) == ("fixture_user@test", "Finance")
        context = json.loads(ticket.context_json)
        assert set(context) == {"browser", "page", "app_version"} and len(context["app_version"]) == 200
        assert await _kinds(db_session, ticket) == ["user", "auto"]
        auto = (
            await db_session.execute(
                select(SupportTicketMessage).where(
                    SupportTicketMessage.ticket_id == ticket.id, SupportTicketMessage.kind == "auto"
                )
            )
        ).scalar_one()
        assert auto.author_name == "Support team" and auto.author_id is None
        assert auto.body.startswith(f"Hello Sara Karimi, we have your ticket #{ticket.number} “Export fails”.")
        images = (await db_session.execute(select(SupportTicketAttachment))).scalars().all()
        assert [i.display_name for i in images] == ["screen1.png", "screen2.png"]
        assert ticket.first_staff_reply_at is None  # the automatic reply is not a first reply

    async def test_numbers_follow_the_ids(self, db_session, user):
        first = await _open(db_session, user)
        second = await _open(db_session, user)
        assert second.number == first.number + 1

    async def test_the_automatic_reply_can_be_off(self, db_session, user):
        ticket = await _open(db_session, user, settings=st.TicketSettings(auto_reply_enabled=False))
        assert await _kinds(db_session, ticket) == ["user"]

    @pytest.mark.parametrize(
        ("overrides", "code"),
        [
            ({"title": "  "}, "invalid_title"),
            ({"title": "x" * 151}, "invalid_title"),
            ({"description": ""}, "invalid_description"),
            ({"description": "x" * 5001}, "invalid_description"),
            ({"category": "Gossip"}, "invalid_category"),
            ({"priority": "critical"}, "invalid_priority"),
            ({"images": [_image(n) for n in range(6)]}, "too_many_images"),
        ],
    )
    async def test_it_refuses_what_the_form_does_not_allow(self, db_session, user, overrides, code):
        with pytest.raises(st.TicketError) as refused:
            await _open(db_session, user, **overrides)
        assert refused.value.code == code and refused.value.status_code == 422

    async def test_the_hourly_limit(self, db_session, user):
        settings = st.TicketSettings(per_hour=2)
        await _open(db_session, user, settings)
        old = await _open(db_session, user, settings)
        with pytest.raises(st.TicketError) as refused:
            await _open(db_session, user, settings)
        assert (refused.value.code, refused.value.status_code) == ("ticket_rate_limited", 429)
        old.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
        await db_session.commit()
        await _open(db_session, user, settings)

    async def test_the_open_ticket_limit(self, db_session, user):
        settings = st.TicketSettings(max_open=2, per_hour=100)
        first = await _open(db_session, user, settings)
        await _open(db_session, user, settings)
        with pytest.raises(st.TicketError) as refused:
            await _open(db_session, user, settings)
        assert (refused.value.code, refused.value.status_code) == ("too_many_open", 409)
        await st.user_resolve(db_session, ticket=first, user=user)
        await db_session.commit()
        await _open(db_session, user, settings)

    async def test_a_disabled_account_cannot_open_one(self, db_session):
        person = await _person(db_session, "gone", active=False)
        with pytest.raises(st.TicketError) as refused:
            await _open(db_session, person)
        assert refused.value.status_code == 403

    def test_placeholders_are_filled_once(self):
        ticket = SupportTicket(
            reporter_name="Sara", number=1042, title="{name} broke", priority="urgent", category="Bug"
        )
        text = st.render_auto_reply("{name}: {number} {title} {priority} {category} {unknown}", ticket)
        assert text == "Sara: #1042 {name} broke Urgent Bug {unknown}"


class TestReplies:
    async def test_a_staff_reply_hands_the_move_to_the_person(self, db_session, user, support):
        ticket = await _open(db_session, user)
        await st.add_staff_message(
            db_session, ticket=ticket, staff=support, body="Looking", internal=False, images=[], status=None
        )
        await db_session.commit()
        assert ticket.status == "in_progress"
        assert ticket.first_staff_reply_at is not None
        assert (ticket.needs_staff, ticket.user_unread) == (False, True)
        first = ticket.first_staff_reply_at
        await st.add_staff_message(
            db_session, ticket=ticket, staff=support, body="Try again?", internal=False, images=[], status="waiting"
        )
        await db_session.commit()
        assert ticket.first_staff_reply_at == first
        assert ticket.status == "waiting" and ticket.waiting_since is not None
        assert [e["to"] for e in await _events(db_session, ticket)] == ["in_progress", "waiting"]

    async def test_a_note_changes_nothing_the_person_sees(self, db_session, user, support):
        ticket = await _open(db_session, user)
        await st.add_staff_message(
            db_session, ticket=ticket, staff=support, body="Secret", internal=True, images=[_image()], status=None
        )
        await db_session.commit()
        assert (ticket.status, ticket.needs_staff, ticket.user_unread) == ("open", True, False)
        assert ticket.first_staff_reply_at is None
        detail = await st.ticket_detail(db_session, ticket, audience="user", viewer=user)
        assert [m["kind"] for m in detail["messages"]] == ["user", "auto"]
        assert detail["message_count"] == 2 and detail["image_count"] == 0
        staff_view = await st.ticket_detail(db_session, ticket, audience="staff", viewer=support)
        note = staff_view["messages"][-1]
        assert note["internal"] is True and note["author_label"] == "Support" and len(note["attachments"]) == 1
        assert staff_view["message_count"] == 3 and staff_view["image_count"] == 1

    async def test_the_persons_reply_takes_a_waiting_ticket_back_to_open(self, db_session, user, support):
        ticket = await _open(db_session, user)
        await st.set_status(db_session, ticket=ticket, actor=support, status="waiting")
        await st.add_user_message(
            db_session, ticket=ticket, user=user, body="Still broken", images=[], settings=st.TicketSettings()
        )
        await db_session.commit()
        assert (ticket.status, ticket.needs_staff, ticket.waiting_since) == ("open", True, None)

    async def test_someone_elses_ticket_is_not_found(self, db_session, user, support):
        ticket = await _open(db_session, user)
        with pytest.raises(st.TicketError) as refused:
            await st.add_user_message(
                db_session, ticket=ticket, user=support, body="Hi", images=[], settings=st.TicketSettings()
            )
        assert refused.value.status_code == 404

    async def test_a_reply_in_the_window_reopens_and_after_it_is_refused(self, db_session, user, support):
        settings = st.TicketSettings(reopen_days=14)
        ticket = await _open(db_session, user)
        await st.set_status(db_session, ticket=ticket, actor=support, status="resolved")
        await db_session.commit()
        assert (ticket.resolved_by, ticket.needs_staff) == ("staff", False)
        await st.add_user_message(db_session, ticket=ticket, user=user, body="Again", images=[], settings=settings)
        await db_session.commit()
        assert (ticket.status, ticket.reopened_count, ticket.resolved_at) == ("open", 1, None)
        assert (await _events(db_session, ticket))[-1]["type"] == "reopened"

        await st.set_status(db_session, ticket=ticket, actor=support, status="closed")
        ticket.closed_at = datetime.datetime.utcnow() - datetime.timedelta(days=15)
        await db_session.commit()
        with pytest.raises(st.TicketError) as refused:
            await st.add_user_message(db_session, ticket=ticket, user=user, body="Again", images=[], settings=settings)
        assert (refused.value.code, refused.value.status_code) == ("reopen_window_passed", 409)
        detail = await st.ticket_detail(db_session, ticket, audience="user", viewer=user)
        assert detail["can_reply"] is False and detail["can_resolve"] is False

    async def test_the_hourly_reply_limit_counts_replies_on_all_tickets(self, db_session, user, monkeypatch):
        monkeypatch.setattr(st, "REPLIES_PER_HOUR", 3)
        settings = st.TicketSettings(per_hour=100)
        first = await _open(db_session, user, settings)
        second = await _open(db_session, user, settings)
        # The first message of each new ticket is not a reply.
        for ticket in (first, second, first):
            await st.add_user_message(db_session, ticket=ticket, user=user, body="More", images=[], settings=settings)
        await db_session.commit()
        with pytest.raises(st.TicketError) as refused:
            await st.precheck_user_reply(db_session, ticket=second, user=user, body="More", settings=settings)
        assert (refused.value.code, refused.value.status_code) == ("reply_rate_limited", 429)
        with pytest.raises(st.TicketError):
            await st.add_user_message(db_session, ticket=second, user=user, body="More", images=[], settings=settings)
        await db_session.rollback()
        old = (
            (
                await db_session.execute(
                    select(SupportTicketMessage)
                    .where(SupportTicketMessage.kind == "user")
                    .order_by(SupportTicketMessage.id)
                )
            )
            .scalars()
            .all()[-1]
        )
        old.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
        await db_session.commit()
        await db_session.refresh(second)
        await db_session.refresh(user)
        assert await st.precheck_user_reply(db_session, ticket=second, user=user, body=" More ", settings=settings) == (
            "More"
        )

    async def test_the_person_marks_it_resolved(self, db_session, user):
        ticket = await _open(db_session, user)
        await st.user_resolve(db_session, ticket=ticket, user=user)
        await db_session.commit()
        assert (ticket.status, ticket.resolved_by, ticket.needs_staff) == ("resolved", "user", False)
        with pytest.raises(st.TicketError):
            await st.user_resolve(db_session, ticket=ticket, user=user)

    async def test_status_priority_and_category_changes_leave_events(self, db_session, user, support):
        ticket = await _open(db_session, user)
        await st.set_priority(db_session, ticket=ticket, actor=support, priority="urgent")
        await st.set_priority(db_session, ticket=ticket, actor=support, priority="urgent")  # unchanged: no event
        await st.set_category(db_session, ticket=ticket, actor=support, category="Question")
        await st.set_status(db_session, ticket=ticket, actor=support, status="closed")
        await db_session.commit()
        assert [e["type"] for e in await _events(db_session, ticket)] == ["priority", "category", "status"]
        assert (ticket.closed_reason, ticket.user_unread) == ("manual", True)
        with pytest.raises(st.TicketError):
            await st.set_category(db_session, ticket=ticket, actor=support, category="Gossip")
        with pytest.raises(st.TicketError):
            await st.set_status(db_session, ticket=ticket, actor=support, status="pending")

    async def test_a_category_no_longer_offered_can_be_kept(self, db_session, user, support):
        ticket = await _open(db_session, user)
        await st.set_category(
            db_session, ticket=ticket, actor=support, category="Bug", settings=st.TicketSettings(categories=["Other"])
        )
        assert ticket.category == "Bug"


class TestAssignment:
    async def test_taking_a_ticket_yourself_sends_no_email(self, db_session, user, support):
        ticket = await _open(db_session, user)
        outcome = await st.assign(db_session, ticket=ticket, actor=support, assignee=support)
        assert (outcome.changed, outcome.email_wanted) == (True, False)
        assert (await _events(db_session, ticket))[-1]["email"] == "none"
        assert ticket.assigned_by_id == support.id and ticket.assigned_at is not None

    async def test_assigning_someone_else_wants_an_email(self, db_session, user, support, other_support):
        ticket = await _open(db_session, user)
        outcome = await st.assign(db_session, ticket=ticket, actor=support, assignee=other_support)
        assert (outcome.changed, outcome.email_wanted) == (True, True)
        event = (await _events(db_session, ticket))[-1]
        assert event == {
            "type": "assigned",
            "by": "Majid Arasskhani",
            "by_id": support.id,
            "to": "Ali Mohammadi",
            "to_id": other_support.id,
            "email": "pending",
        }
        row = await db_session.get(SupportTicketMessage, outcome.event_id)
        assert row is not None and row.kind == "event"

    async def test_unchanged_is_a_no_op_and_reassigning_emails_only_the_new_one(
        self, db_session, user, support, other_support
    ):
        ticket = await _open(db_session, user)
        await st.assign(db_session, ticket=ticket, actor=support, assignee=support)
        again = await st.assign(db_session, ticket=ticket, actor=support, assignee=support)
        assert (again.changed, again.email_wanted, again.event_id) == (False, False, None)
        moved = await st.assign(db_session, ticket=ticket, actor=support, assignee=other_support)
        assert moved.email_wanted is True and ticket.assignee_id == other_support.id

    async def test_unassigning_sends_nothing(self, db_session, user, support):
        ticket = await _open(db_session, user)
        await st.assign(db_session, ticket=ticket, actor=support, assignee=support)
        outcome = await st.assign(db_session, ticket=ticket, actor=support, assignee=None)
        assert (outcome.changed, outcome.email_wanted) == (True, False)
        assert ticket.assignee_id is None
        assert (await _events(db_session, ticket))[-1]["type"] == "unassigned"
        nothing = await st.assign(db_session, ticket=ticket, actor=support, assignee=None)
        assert nothing.changed is False

    async def test_the_email_is_off_by_setting_or_without_an_address(self, db_session, user, support):
        nobody = await _person(db_session, "noaddress", roles=[SUPPORT_SLUG])
        ticket = await _open(db_session, user)
        outcome = await st.assign(db_session, ticket=ticket, actor=support, assignee=nobody)
        assert outcome.email_wanted is False and (await _events(db_session, ticket))[-1]["email"] == "off"
        other = await _open(db_session, user)
        colleague = await _person(db_session, "colleague", roles=[SUPPORT_SLUG], email="c@corp.test")
        outcome = await st.assign(
            db_session,
            ticket=other,
            actor=support,
            assignee=colleague,
            settings=st.TicketSettings(email_assignee=False),
        )
        assert outcome.email_wanted is False

    async def test_only_people_who_work_tickets_can_be_assigned(self, db_session, user, support, admin):
        viewer = await _person(db_session, "viewer", roles=[READ_ONLY_SUPER_ADMIN_SLUG])
        disabled = await _person(db_session, "disabled", roles=[SUPPORT_SLUG], active=False)
        ticket = await _open(db_session, user)
        for person in (user, viewer, disabled):
            with pytest.raises(st.TicketError) as refused:
                await st.assign(db_session, ticket=ticket, actor=support, assignee=person)
            assert (refused.value.code, refused.value.status_code) == ("not_assignable", 422)
        outcome = await st.assign(db_session, ticket=ticket, actor=support, assignee=admin)
        assert outcome.changed  # Super Admin works tickets

    async def test_the_assignable_staff_list(self, db_session, user, support, other_support, admin):
        await _person(db_session, "viewer", roles=[READ_ONLY_SUPER_ADMIN_SLUG])
        await _person(db_session, "disabled", roles=[SUPPORT_SLUG], active=False)
        await _person(db_session, "both", roles=[SUPPORT_SLUG, READ_ONLY_SUPER_ADMIN_SLUG])
        ticket = await _open(db_session, user)
        await st.assign(db_session, ticket=ticket, actor=support, assignee=support)
        await db_session.commit()
        staff = await st.assignable_staff(db_session)
        assert [(s.name, s.role_label, s.open_count) for s in staff] == [
            ("Ali Mohammadi", "Support", 0),
            ("fixture_admin", "Super Admin", 0),
            ("Majid Arasskhani", "Support", 1),
        ]
        assert await st.can_work_tickets(db_session, support)
        assert not await st.can_work_tickets(db_session, user)

    async def test_people_who_can_no_longer_work_tickets_lose_their_active_ones(
        self, db_session, user, support, other_support
    ):
        active = await _open(db_session, user)
        done = await _open(db_session, user)
        await st.assign(db_session, ticket=active, actor=support, assignee=other_support)
        await st.assign(db_session, ticket=done, actor=support, assignee=other_support)
        await st.set_status(db_session, ticket=done, actor=support, status="closed")
        await st.assign(db_session, ticket=await _open(db_session, user), actor=support, assignee=support)
        await db_session.commit()
        assert await st.release_orphaned_assignments(db_session) == 0
        await set_user_roles(db_session, other_support, [])
        await db_session.commit()
        assert await st.release_orphaned_assignments(db_session) == 1
        await db_session.commit()
        assert active.assignee_id is None
        assert done.assignee_id == other_support.id  # a closed ticket keeps who handled it
        assert (await _events(db_session, active))[-1] == {
            "type": "assignee_removed",
            "from": "Ali Mohammadi",
            "from_id": other_support.id,
        }


class TestJobs:
    async def test_waiting_tickets_close_after_the_set_days(self, db_session, user, support):
        stale = await _open(db_session, user)
        fresh = await _open(db_session, user)
        for ticket in (stale, fresh):
            await st.set_status(db_session, ticket=ticket, actor=support, status="waiting")
        stale.waiting_since = NOW - datetime.timedelta(days=8)
        fresh.waiting_since = NOW - datetime.timedelta(days=6)
        await db_session.commit()
        assert await st.close_waiting_tickets(db_session, now=NOW) == [stale.id]
        assert (stale.status, stale.closed_reason, stale.closed_at) == ("closed", "auto", NOW)
        assert fresh.status == "waiting"
        assert (await _events(db_session, stale))[-1] == {"type": "auto_closed", "days": 7}

    def test_the_close_jobs_lock_what_they_close_and_skip_what_is_being_changed(self):
        from sqlalchemy.dialects import postgresql

        query = st._locked_batch_query(0, SupportTicket.status == "waiting")
        assert str(query.compile(dialect=postgresql.dialect())).endswith("FOR UPDATE SKIP LOCKED")

    @pytest.mark.skipif(not _ON_POSTGRES, reason="row locks need PostgreSQL (TEST_DATABASE_URL)")
    async def test_a_ticket_being_answered_is_skipped_not_overwritten(self, db_session, session_factory, user, support):
        ticket = await _open(db_session, user)
        await st.set_status(db_session, ticket=ticket, actor=support, status="waiting")
        ticket.waiting_since = NOW - datetime.timedelta(days=8)
        await db_session.commit()
        async with session_factory() as replying, session_factory() as job:
            # The person's reply holds the row (not committed yet) while the job runs.
            mine = (
                await replying.execute(select(SupportTicket).where(SupportTicket.id == ticket.id).with_for_update())
            ).scalar_one()
            assert await asyncio.wait_for(st.close_waiting_tickets(job, now=NOW), timeout=10) == []
            await st.add_user_message(
                replying,
                ticket=mine,
                user=await replying.get(User, user.id),
                body="Still here",
                images=[],
                settings=st.TicketSettings(),
            )
            await replying.commit()
            assert await asyncio.wait_for(st.close_waiting_tickets(job, now=NOW), timeout=10) == []
        fresh = await db_session.get(SupportTicket, ticket.id, populate_existing=True)
        assert (fresh.status, fresh.closed_at) == ("open", None)

    async def test_resolved_tickets_close_when_the_reopen_window_ends(self, db_session, user, support):
        old = await _open(db_session, user)
        recent = await _open(db_session, user)
        for ticket in (old, recent):
            await st.set_status(db_session, ticket=ticket, actor=support, status="resolved")
        old.resolved_at = NOW - datetime.timedelta(days=15)
        recent.resolved_at = NOW - datetime.timedelta(days=13)
        await db_session.commit()
        assert await st.close_resolved_tickets(db_session, now=NOW) == [old.id]
        assert (old.status, old.closed_reason) == ("closed", "resolved")
        assert recent.status == "resolved"
        detail = await st.ticket_detail(db_session, old, audience="user", viewer=user)
        assert detail["can_reply"] is False

    async def test_closed_tickets_are_deleted_after_the_retention_days(self, db_session, user, support, monkeypatch):
        removed: list[str] = []
        monkeypatch.setattr("app.services.object_storage_service.delete_object", removed.append)
        old = await _open(db_session, user, images=[_image(1)])
        kept = await _open(db_session, user)
        for ticket in (old, kept):
            await st.set_status(db_session, ticket=ticket, actor=support, status="closed")
        old.closed_at = NOW - datetime.timedelta(days=366)
        kept.closed_at = NOW - datetime.timedelta(days=300)
        old_id = old.id
        await db_session.commit()
        totals = await st.purge_closed_tickets(db_session, now=NOW)
        await st.drain_storage_deletions()
        assert totals == {"deleted": 1, "messages": 2, "images": 1, "image_bytes": 1000, "retention_days": 365}
        assert removed == ["tickets/2026/10/img1.png"]
        assert await db_session.get(SupportTicket, old_id) is None
        assert await db_session.get(SupportTicket, kept.id) is not None

    async def test_zero_retention_keeps_everything(self, db_session, user, support):
        db_session.add(SystemSetting(key=st.SETTINGS_KEY, value=json.dumps({"retention_days": 0})))
        ticket = await _open(db_session, user)
        await st.set_status(db_session, ticket=ticket, actor=support, status="closed")
        ticket.closed_at = NOW - datetime.timedelta(days=5000)
        await db_session.commit()
        assert (await st.purge_closed_tickets(db_session, now=NOW))["deleted"] == 0


class TestDeleting:
    async def test_delete_removes_rows_then_the_images_after_the_commit(self, db_session, user, monkeypatch):
        removed: list[str] = []
        monkeypatch.setattr("app.services.object_storage_service.delete_object", removed.append)
        first = await _open(db_session, user, images=[_image(1), _image(2)])
        second = await _open(db_session, user)
        ids = [first.id, second.id]
        assert sorted(await st.ticket_storage_keys(db_session, ids)) == [
            "tickets/2026/10/img1.png",
            "tickets/2026/10/img2.png",
        ]
        totals = await st.delete_tickets(db_session, ids)
        assert totals == {"deleted": 2, "messages": 4, "images": 2, "image_bytes": 3000}
        await st.drain_storage_deletions()
        assert removed == []  # nothing leaves storage before the commit
        await db_session.commit()
        await st.drain_storage_deletions()
        assert sorted(removed) == ["tickets/2026/10/img1.png", "tickets/2026/10/img2.png"]
        for model in (SupportTicket, SupportTicketMessage, SupportTicketAttachment):
            assert (await db_session.execute(select(func.count()).select_from(model))).scalar_one() == 0

    async def test_a_ticket_that_no_longer_meets_the_conditions_stays(self, db_session, user, monkeypatch):
        removed: list[str] = []
        monkeypatch.setattr("app.services.object_storage_service.delete_object", removed.append)
        closed = await _open(db_session, user, images=[_image(1)])
        reopened = await _open(db_session, user, images=[_image(2)])
        closed.status = "closed"
        await db_session.commit()
        totals = await st.delete_tickets(
            db_session, [closed.id, reopened.id], where=[SupportTicket.status.in_(st.DONE_STATUSES)]
        )
        assert totals == {"deleted": 1, "messages": 2, "images": 1, "image_bytes": 1000}
        await db_session.commit()
        await st.drain_storage_deletions()
        assert removed == ["tickets/2026/10/img1.png"]
        assert [t.id for t in (await db_session.execute(select(SupportTicket))).scalars()] == [reopened.id]

    async def test_a_rolled_back_delete_keeps_the_images(self, db_session, user, monkeypatch):
        removed: list[str] = []
        monkeypatch.setattr("app.services.object_storage_service.delete_object", removed.append)
        ticket = await _open(db_session, user, images=[_image(1)])
        await st.delete_tickets(db_session, [ticket.id])
        await db_session.rollback()
        await db_session.commit()
        await st.drain_storage_deletions()
        assert removed == []

    async def test_a_storage_failure_is_only_logged(self, db_session, user, monkeypatch):
        def boom(_key):
            raise RuntimeError("storage down")

        monkeypatch.setattr("app.services.object_storage_service.delete_object", boom)
        ticket = await _open(db_session, user, images=[_image(1)])
        await st.delete_tickets(db_session, [ticket.id])
        await db_session.commit()
        await st.drain_storage_deletions()

    async def test_a_purged_persons_tickets_go_with_them(self, db_session, user, support, monkeypatch):
        monkeypatch.setattr("app.services.object_storage_service.delete_object", lambda _key: None)
        await _open(db_session, user)
        await _open(db_session, support)
        assert (await st.delete_user_tickets(db_session, user.id))["deleted"] == 1
        await db_session.commit()
        owners = (await db_session.execute(select(SupportTicket.user_id))).scalars().all()
        assert owners == [support.id]

    async def test_account_purge_deletes_their_tickets(self, db_session, user, monkeypatch):
        from app.services.user_account_cleanup_service import purge_user_account_data

        monkeypatch.setattr("app.services.object_storage_service.purge_user_cdn_objects", lambda *_a: 0)
        monkeypatch.setattr("app.services.object_storage_service.delete_object", lambda _key: None)
        await _open(db_session, user)
        await purge_user_account_data(db_session, user_id=user.id, username=user.username)
        await db_session.commit()
        assert (await db_session.execute(select(func.count()).select_from(SupportTicket))).scalar_one() == 0


class TestSettings:
    async def test_defaults_until_saved(self, db_session):
        settings = await st.load_settings(db_session)
        assert settings == st.TicketSettings()
        assert settings.as_dict()["categories"] == ["Bug", "Problem", "Question", "Feature request"]
        assert settings.as_dict()["image_types"] == ["png", "jpg", "webp", "gif"]

    async def test_saved_settings_round_trip(self, db_session):
        chosen = st.validate_settings({**st.TicketSettings().as_dict(), "per_hour": 9, "notify_emails": ["a@b.test"]})
        await st.save_settings(db_session, chosen)
        await db_session.commit()
        assert (await st.load_settings(db_session)).as_dict() == chosen.as_dict()
        await st.save_settings(db_session, st.TicketSettings())
        await db_session.commit()
        assert (await st.load_settings(db_session)).per_hour == 5

    async def test_garbled_or_out_of_bounds_values_fall_back_or_are_clamped(self, db_session):
        stored = {
            "enabled": "yes",
            "per_hour": 1000,
            "max_open": "many",
            "retention_days": -5,
            "notify_emails": ["ok@corp.test", "not an address"],
            "notify_min_priority": "critical",
            "categories": "Bug",
            "image_types": ["bmp", "JPEG"],
            "auto_reply_text": "x" * 3000,
        }
        db_session.add(SystemSetting(key=st.SETTINGS_KEY, value=json.dumps(stored)))
        await db_session.commit()
        settings = await st.load_settings(db_session)
        assert settings.enabled is True
        assert (settings.per_hour, settings.max_open, settings.retention_days) == (100, 20, 0)
        assert settings.notify_emails == ["ok@corp.test"]
        assert settings.notify_min_priority == "normal"
        assert settings.categories == list(st.DEFAULT_CATEGORIES)
        assert settings.image_types == ["jpg"]
        assert len(settings.auto_reply_text) == 2000

    async def test_unreadable_json_gives_the_defaults(self, db_session):
        db_session.add(SystemSetting(key=st.SETTINGS_KEY, value="{not json"))
        await db_session.commit()
        assert await st.load_settings(db_session) == st.TicketSettings()

    @pytest.mark.parametrize(
        "change",
        [
            {"per_hour": 0},
            {"per_hour": 101},
            {"max_open": 201},
            {"reopen_days": 91},
            {"auto_close_days": 0},
            {"retention_days": 3651},
            {"max_image_mb": 11},
            {"max_images": 11},
            {"max_side_px": 511},
            {"per_hour": True},
            {"per_hour": "5"},
            {"enabled": "true"},
            {"notify_emails": ["nope"]},
            {"notify_emails": [f"p{n}@corp.test" for n in range(21)]},
            {"notify_min_priority": "critical"},
            {"categories": []},
            {"categories": ["Bug", "bug"]},
            {"categories": ["x" * 41]},
            {"categories": [f"c{n}" for n in range(21)]},
            {"image_types": []},
            {"image_types": ["png", "bmp"]},
            {"auto_reply_text": "x" * 2001},
            {"auto_reply_text": "  ", "auto_reply_enabled": True},
        ],
    )
    def test_validation_refuses_values_out_of_bounds(self, change):
        with pytest.raises(st.TicketError) as refused:
            st.validate_settings({**st.TicketSettings().as_dict(), **change})
        assert (refused.value.code, refused.value.status_code) == ("invalid_settings", 422)

    def test_validation_tidies_what_it_accepts(self):
        settings = st.validate_settings(
            {
                **st.TicketSettings().as_dict(),
                "notify_emails": [" a@corp.test ", "A@corp.test", ""],
                "categories": [" Bug ", "Access  request"],
                "image_types": ["gif", "jpeg", "png"],
                "auto_reply_enabled": False,
                "auto_reply_text": "",
                "retention_days": 0,
            }
        )
        assert settings.notify_emails == ["a@corp.test"]
        assert settings.categories == ["Bug", "Access request"]
        assert settings.image_types == ["png", "jpg", "gif"]
        assert settings.retention_days == 0


class TestReading:
    def test_staff_event_texts(self):
        def text(**facts):
            return st.event_text(facts, "staff")

        assert (
            text(type="assigned", by="Ali Mohammadi", by_id=1, to="Majid Arasskhani", to_id=2, email="sent")
            == "Ali Mohammadi assigned this to Majid Arasskhani · email sent"
        )
        assert text(type="assigned", by="A", by_id=1, to="B", to_id=2, email="pending").endswith("· email queued")
        assert text(type="assigned", by="A", by_id=1, to="B", to_id=2, email="failed").endswith("· email not sent")
        assert text(type="assigned", by="A", by_id=1, to="B", to_id=2, email="off") == "A assigned this to B"
        assert (
            text(type="assigned", by="Majid Arasskhani", by_id=2, to="Majid Arasskhani", to_id=2, email="none")
            == "Majid Arasskhani took the ticket"
        )
        assert text(type="status", to="waiting") == "Status changed to Waiting for user"
        assert text(type="priority", to="high") == "Priority changed to High"
        assert text(type="category", to="Bug") == "Category changed to Bug"
        assert text(type="auto_closed", days=7) == "Closed automatically: no reply in 7 days"
        assert text(type="auto_closed", days=1) == "Closed automatically: no reply in 1 day"
        assert text(type="closed_resolved", days=14) == "Closed: resolved 14 days ago"
        assert text(type="reopened", by="Sara Karimi") == "Reopened by Sara Karimi"
        assert text(type="resolved", by="Sara Karimi") == "Sara Karimi marked it resolved"
        assert text(type="unassigned", by="Ali Mohammadi") == "Unassigned by Ali Mohammadi"
        assert (
            text(type="assignee_removed", **{"from": "Ali Mohammadi"})
            == "Unassigned: Ali Mohammadi can no longer work tickets"
        )

    def test_user_event_texts(self):
        def text(**facts):
            return st.event_text(facts, "user")

        assert (
            text(type="assigned", by="A", by_id=1, to="Majid Arasskhani", to_id=2, email="sent")
            == "Majid Arasskhani is handling your ticket"
        )
        assert text(type="status", to="waiting") == "Status changed to Waiting for you"
        assert text(type="status", to="in_progress") == "Status changed to In progress"
        assert text(type="auto_closed", days=7) == "Closed automatically: no reply in 7 days"
        assert text(type="reopened", by="Sara") == "Reopened by Sara"
        assert text(type="resolved", by="Sara") == "Sara marked it resolved"
        for hidden in ("priority", "category", "unassigned", "assignee_removed", "mystery"):
            assert text(type=hidden, by="A", to="x") is None

    async def test_the_two_details_have_the_contract_shapes(self, db_session, user, support, admin):
        ticket = await _open(db_session, user, images=[_image(1)], context={"browser": "Edge"})
        await st.assign(db_session, ticket=ticket, actor=support, assignee=support)
        await st.set_priority(db_session, ticket=ticket, actor=support, priority="high")
        await st.add_staff_message(
            db_session, ticket=ticket, staff=admin, body="On it", internal=False, images=[], status="waiting"
        )
        await db_session.commit()

        mine = await st.ticket_detail(db_session, ticket, audience="user", viewer=user)
        assert set(mine) == {
            "id", "number", "title", "category", "priority", "status", "user_unread", "created_at", "updated_at",
            "message_count", "image_count", "reopen_until", "reporter", "assignee", "messages", "auto_close_at",
            "can_reply", "can_resolve",
        }  # fmt: skip
        assert mine["reporter"] == {
            "name": "fixture_user",
            "username": "fixture_user",
            "email": "fixture_user@test",
            "department": None,
        }
        assert mine["assignee"] == {"id": support.id, "name": "Majid Arasskhani"}
        assert mine["created_at"].endswith("Z") and mine["auto_close_at"].endswith("Z")
        assert (mine["can_reply"], mine["can_resolve"], mine["reopen_until"]) == (True, True, None)
        labels = [(m["kind"], m["author_label"], m["body"]) for m in mine["messages"]]
        assert labels[:2] == [
            ("user", "You", "The PDF export stops at 90%."),
            ("auto", "Automatic reply", labels[1][2]),
        ]
        assert ("event", "", "Majid Arasskhani is handling your ticket") in labels
        assert ("staff", "Administrator", "On it") in labels
        assert ("event", "", "Status changed to Waiting for you") in labels
        assert not any("Priority" in body for _, _, body in labels)
        first = mine["messages"][0]
        assert first["author"] == {"id": user.id, "name": "fixture_user"} and first["internal"] is False
        assert first["attachments"][0]["url"] == f"/api/support/attachments/{first['attachments'][0]['id']}"
        assert set(first["attachments"][0]) == {"id", "url", "mime", "bytes", "width", "height", "display_name"}
        assert mine["messages"][1]["author"] == {"id": None, "name": "Support team"}

        staff = await st.ticket_detail(db_session, ticket, audience="staff", viewer=support)
        assert set(staff) - set(mine) == {
            "needs_staff", "context", "first_staff_reply_at", "resolved_at", "closed_at", "closed_reason",
            "resolved_by", "reopened_count", "can_write", "can_delete",
        }  # fmt: skip
        assert staff["context"] == {"browser": "Edge"}
        assert (staff["can_write"], staff["can_delete"], staff["can_reply"]) == (True, False, True)
        staff_lines = [(m["author_label"], m["body"]) for m in staff["messages"]]
        assert ("Reporter", "The PDF export stops at 90%.") in staff_lines
        assert ("", "Majid Arasskhani took the ticket") in staff_lines
        assert ("", "Priority changed to High") in staff_lines
        assert ("", "Status changed to Waiting for user") in staff_lines
        as_admin = await st.ticket_detail(db_session, ticket, audience="staff", viewer=admin)
        assert as_admin["can_delete"] is True
        viewer = await _person(db_session, "viewer", roles=[READ_ONLY_SUPER_ADMIN_SLUG])
        as_viewer = await st.ticket_detail(db_session, ticket, audience="staff", viewer=viewer)
        assert (as_viewer["can_write"], as_viewer["can_delete"], as_viewer["can_reply"]) == (False, False, False)

    async def test_summaries_and_counts(self, db_session, user, support):
        ticket = await _open(db_session, user, images=[_image(1)])
        await st.add_staff_message(
            db_session, ticket=ticket, staff=support, body="note", internal=True, images=[_image(2)], status=None
        )
        await st.assign(db_session, ticket=ticket, actor=support, assignee=support)
        await db_session.commit()
        settings = st.TicketSettings()
        user_counts = await st.message_counts(db_session, [ticket.id], audience="user")
        staff_counts = await st.message_counts(db_session, [ticket.id])
        assert user_counts[ticket.id] == (2, 1) and staff_counts[ticket.id] == (3, 2)
        mine = st.ticket_summary(ticket, audience="user", counts=user_counts[ticket.id], settings=settings)
        assert set(mine) == {
            "id", "number", "title", "category", "priority", "status", "user_unread", "created_at", "updated_at",
            "message_count", "image_count", "reopen_until",
        }  # fmt: skip
        names = await st.assignee_names(db_session, [ticket])
        row = st.ticket_summary(
            ticket, audience="staff", counts=staff_counts[ticket.id], settings=settings, assignee_names=names
        )
        assert row["assignee"] == {"id": support.id, "name": "Majid Arasskhani"}
        assert row["reporter"] == {"name": "fixture_user", "username": "fixture_user", "department": None}
        assert row["needs_staff"] is True

    async def test_reopen_until_counts_from_the_end(self, db_session, user, support):
        ticket = await _open(db_session, user)
        await st.set_status(db_session, ticket=ticket, actor=support, status="resolved")
        ticket.resolved_at = NOW
        until = st.reopen_until(ticket, st.TicketSettings(reopen_days=14))
        assert until == NOW + datetime.timedelta(days=14)
        assert st.iso_utc(until) == "2026-11-05T09:00:00Z"

    async def test_badge_and_quick_filter_counts(self, db_session, user, support, other_support):
        urgent = await _open(db_session, user, priority="urgent")
        answered = await _open(db_session, user)
        await _open(db_session, user)  # new, unassigned, needs staff
        done = await _open(db_session, user)
        await st.assign(db_session, ticket=urgent, actor=support, assignee=support)
        await st.add_staff_message(
            db_session, ticket=answered, staff=support, body="Hi", internal=False, images=[], status=None
        )
        await st.assign(db_session, ticket=answered, actor=support, assignee=other_support)
        await st.set_status(db_session, ticket=done, actor=support, status="resolved")
        await db_session.commit()
        assert await st.staff_counts(db_session, support.id) == {
            "needs_staff": 2,
            "needs_staff_urgent": 1,
            "mine": 1,
            "unassigned": 1,
            "active": 3,
            "closed": 1,
        }
        assert await st.user_unread_count(db_session, user.id) == 2  # the staff reply and the status change
        assert await st.user_unread_count(db_session, support.id) == 0


async def test_the_session_says_whether_support_is_on(client, db_session, user):
    from app.config import get_settings
    from app.core.security import create_access_token

    client.cookies.set(get_settings().session_cookie_name, create_access_token(user.username, "user"))
    assert (await client.get("/api/auth/session")).json()["features"]["support"] is True
    await st.save_settings(db_session, st.TicketSettings(enabled=False))
    await db_session.commit()
    assert (await client.get("/api/auth/session")).json()["features"]["support"] is False
