"""Support ticket emails: who gets one, what it says, and that a broken SMTP server changes nothing."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models.security import SecurityAuditEvent
from app.models.support_ticket import SupportTicketMessage
from app.models.user import User
from app.services import smtp_service
from app.services import support_ticket_mail as mail
from app.services import support_tickets as st
from app.services.rbac import SUPPORT_SLUG
from app.services.user_role_service import set_user_roles


@pytest.fixture
def sent(monkeypatch, session_factory):
    """Every email "sent", as a dict; the background sessions use the test database."""
    outbox: list[dict] = []

    async def fake_send(db, *, to_address, subject, body_text, cc=None, attachments=()):
        outbox.append({"to": to_address, "cc": list(cc or []), "subject": subject, "body": body_text})

    monkeypatch.setattr(smtp_service, "send_email", fake_send)
    monkeypatch.setattr(mail, "AsyncSessionLocal", session_factory)
    return outbox


async def _settings(db, **changes) -> st.TicketSettings:
    settings = st.TicketSettings(**changes)
    await st.save_settings(db, settings)
    await db.commit()
    return settings


async def _person(db, username, *, roles=None, email=None, display=None) -> User:
    person = User(username=username, email=email, display_name=display, is_active=True, auth_provider="local")
    db.add(person)
    await db.flush()
    if roles:
        await set_user_roles(db, person, roles)
    await db.commit()
    return person


async def _open(db, person, settings, **overrides):
    values = {
        "title": "Export fails",
        "description": "The PDF export stops at 90%.",
        "category": "Bug",
        "priority": "high",
        "context": None,
        "images": [],
    }
    values.update(overrides)
    ticket = await st.create_ticket(db, user=person, settings=settings, **values)
    await db.commit()
    return ticket


async def _events(db, outcomes) -> list[tuple[int, str]]:
    """``(ticket_id, event_json)`` read from the database, as the background sessions left them."""
    rows = await db.execute(
        select(SupportTicketMessage.ticket_id, SupportTicketMessage.event_json).where(
            SupportTicketMessage.id.in_([o.event_id for o in outcomes])
        )
    )
    return [(int(ticket_id), str(facts)) for ticket_id, facts in rows.all()]


@pytest.fixture
async def support(db_session):
    return await _person(db_session, "majid", roles=[SUPPORT_SLUG], email="majid@corp.test", display="Majid Arasskhani")


@pytest.fixture
async def colleague(db_session):
    return await _person(db_session, "ali", roles=[SUPPORT_SLUG], email="ali@corp.test", display="Ali Mohammadi")


class TestAdministrators:
    async def test_a_new_ticket_is_announced_with_an_excerpt_and_a_link(self, db_session, user, sent):
        user.display_name = "Sara Karimi"
        user.department = "Finance"
        await db_session.commit()
        settings = await _settings(db_session, notify_emails=["help@corp.test", "lead@corp.test"])
        image = st.StoredImage("tickets/x.png", "image/png", 10, 1, 1, "00", "secret-screen.png")
        ticket = await _open(db_session, user, settings, description="x" * 600, images=[image])
        mail.notify_new_ticket(ticket.id)
        await mail.drain()
        assert len(sent) == 1
        email = sent[0]
        assert (email["to"], email["cc"]) == ("help@corp.test", ["lead@corp.test"])
        assert email["subject"] == f"New ticket #{ticket.number} (High): Export fails"
        body = email["body"]
        assert f"Ticket: #{ticket.number} Export fails" in body
        assert "Priority: High" in body and "Category: Bug" in body
        assert "From: Sara Karimi (fixture_user), Finance" in body
        assert "x" * 500 + "…" in body and "x" * 501 not in body
        assert body.rstrip().endswith(f"/admin/tickets/list?ticket={ticket.id}")
        assert "secret-screen" not in body

    async def test_nothing_goes_below_the_minimum_priority_or_without_addresses(self, db_session, user, sent):
        settings = await _settings(db_session, notify_emails=["help@corp.test"], notify_min_priority="high")
        low = await _open(db_session, user, settings, priority="normal")
        mail.notify_new_ticket(low.id)
        settings = await _settings(db_session, notify_emails=[])
        urgent = await _open(db_session, user, settings, priority="urgent")
        mail.notify_new_ticket(urgent.id)
        await mail.drain()
        assert sent == []

    async def test_replies_are_announced_only_when_switched_on(self, db_session, user, support, sent):
        settings = await _settings(db_session, notify_emails=["help@corp.test"])
        ticket = await _open(db_session, user, settings)
        await st.add_staff_message(
            db_session, ticket=ticket, staff=support, body="Internal guess", internal=True, images=[], status=None
        )
        await st.add_user_message(
            db_session, ticket=ticket, user=user, body="Still broken today", images=[], settings=settings
        )
        await db_session.commit()
        mail.notify_user_reply(ticket.id)
        await mail.drain()
        assert [e["subject"] for e in sent] == [f"Reply on ticket #{ticket.number}: Export fails"]
        assert "Still broken today" in sent[0]["body"] and "Internal guess" not in sent[0]["body"]
        await _settings(db_session, notify_emails=["help@corp.test"], notify_on_user_reply=False)
        mail.notify_user_reply(ticket.id)
        await mail.drain()
        assert len(sent) == 1


class TestAssignees:
    async def test_one_email_per_assignee_listing_their_tickets(self, db_session, user, support, colleague, sent):
        settings = await _settings(db_session, per_hour=10)
        third = await _person(db_session, "nima", roles=[SUPPORT_SLUG], email="nima@corp.test", display="Nima")
        first = await _open(db_session, user, settings, title="First")
        second = await _open(db_session, user, settings, title="Second")
        other = await _open(db_session, user, settings, title="Other")
        mine = await _open(db_session, user, settings, title="Mine")
        outcomes = [
            await st.assign(db_session, ticket=first, actor=support, assignee=colleague),
            await st.assign(db_session, ticket=second, actor=support, assignee=colleague),
            await st.assign(db_session, ticket=other, actor=support, assignee=third),
            await st.assign(db_session, ticket=mine, actor=support, assignee=support),
        ]
        await db_session.commit()
        mail.notify_assignees([o.event_id for o in outcomes])  # the self-assign is not pending: skipped
        await mail.drain()
        by_to = {e["to"]: e for e in sent}
        assert set(by_to) == {"ali@corp.test", "nima@corp.test"}
        bulk = by_to["ali@corp.test"]
        assert bulk["subject"] == "2 tickets assigned to you"
        assert "Majid Arasskhani assigned 2 support tickets to you." in bulk["body"]
        assert f"#{first.number} First" in bulk["body"] and f"#{second.number} Second" in bulk["body"]
        assert by_to["nima@corp.test"]["subject"] == f"Ticket #{other.number} assigned to you: Other"
        states = {ticket_id: json.loads(facts)["email"] for ticket_id, facts in await _events(db_session, outcomes)}
        assert states == {first.id: "sent", second.id: "sent", other.id: "sent", mine.id: "none"}
        db_session.expire_all()  # the background sessions changed the events
        for row in (first, support):
            await db_session.refresh(row)
        detail = await st.ticket_detail(db_session, first, audience="staff", viewer=support)
        assert any(m["body"].endswith("· email sent") for m in detail["messages"])

    async def test_a_failed_email_is_recorded_and_the_assignment_stands(
        self, db_session, user, support, colleague, monkeypatch, session_factory
    ):
        async def refuse(db, **_kwargs):
            raise smtp_service.SmtpNotConfiguredError("SMTP is not configured.")

        monkeypatch.setattr(smtp_service, "send_email", refuse)
        monkeypatch.setattr(mail, "AsyncSessionLocal", session_factory)
        settings = await _settings(db_session)
        ticket = await _open(db_session, user, settings)
        outcome = await st.assign(db_session, ticket=ticket, actor=support, assignee=colleague)
        await db_session.commit()
        mail.notify_assignees([outcome.event_id])
        await mail.drain()
        [(_, facts)] = await _events(db_session, [outcome])
        assert json.loads(facts)["email"] == "failed"
        assert ticket.assignee_id == colleague.id
        audit = (
            await db_session.execute(
                select(SecurityAuditEvent).where(SecurityAuditEvent.action == "ticket_assignment_email_failed")
            )
        ).scalar_one()
        assert audit.resource_type == "tickets" and audit.actor_user_id == support.id
        detail = json.loads(audit.detail_json)
        assert detail["tickets"] == [ticket.number] and "SMTP is not configured" in detail["error"]
        assert "Export fails" not in audit.detail_json  # numbers, never ticket text
        text = st.event_text(json.loads(facts), "staff")
        assert text == "Majid Arasskhani assigned this to Ali Mohammadi · email not sent"

    async def test_an_address_removed_since_means_no_email(self, db_session, user, support, colleague, sent):
        settings = await _settings(db_session)
        ticket = await _open(db_session, user, settings)
        outcome = await st.assign(db_session, ticket=ticket, actor=support, assignee=colleague)
        colleague.email = None
        await db_session.commit()
        mail.notify_assignees([outcome.event_id])
        await mail.drain()
        assert sent == []
        [(_, facts)] = await _events(db_session, [outcome])
        assert json.loads(facts)["email"] == "off"


class TestThePerson:
    async def test_nothing_while_the_setting_is_off(self, db_session, user, support, sent):
        settings = await _settings(db_session)
        ticket = await _open(db_session, user, settings)
        mail.notify_user(ticket.id, "reply")
        await mail.drain()
        assert sent == []

    async def test_replies_resolves_and_status_changes_when_on(self, db_session, user, support, sent):
        settings = await _settings(db_session, email_user=True)
        ticket = await _open(db_session, user, settings)
        await st.add_staff_message(
            db_session, ticket=ticket, staff=support, body="Please retry now", internal=False, images=[], status=None
        )
        await st.add_staff_message(
            db_session, ticket=ticket, staff=support, body="Never tell them", internal=True, images=[], status=None
        )
        await db_session.commit()
        mail.notify_user(ticket.id, "reply")
        await mail.drain()
        await st.set_status(db_session, ticket=ticket, actor=support, status="waiting")
        await db_session.commit()
        mail.notify_user(ticket.id, "status")
        await mail.drain()
        await st.set_status(db_session, ticket=ticket, actor=support, status="resolved")
        await db_session.commit()
        mail.notify_user(ticket.id, "resolved")
        await mail.drain()
        assert [e["to"] for e in sent] == ["fixture_user@test"] * 3
        reply, status, resolved = sent
        assert reply["subject"] == f"Support replied on your ticket #{ticket.number}"
        assert "Please retry now" in reply["body"] and "Never tell them" not in reply["body"]
        assert reply["body"].rstrip().endswith(f"/app/support/{ticket.id}")
        assert status["subject"] == f"Your ticket #{ticket.number} is now Waiting for you"
        assert resolved["subject"] == f"Your ticket #{ticket.number} is resolved"
        assert "reply within 14 days to reopen it" in resolved["body"]

    async def test_the_automatic_reply_can_be_emailed(self, db_session, user, sent):
        settings = await _settings(db_session, email_user=True)
        ticket = await _open(db_session, user, settings)
        mail.notify_user(ticket.id, "reply")
        await mail.drain()
        assert sent and f"we have your ticket #{ticket.number}" in sent[0]["body"]


def test_the_excerpt_keeps_500_characters():
    assert mail.excerpt("  short  ") == "short"
    assert mail.excerpt("a" * 501) == "a" * 500 + "…"
    assert mail.excerpt(None) == ""
