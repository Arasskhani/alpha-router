"""Admin › Tickets: who may read and work the queue, assignment and its emails, bulk, export, settings and deleting."""

from __future__ import annotations

import asyncio
import csv
import datetime
import io
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import func, inspect, select

from app.api import admin_tickets
from app.config import get_settings
from app.core.security import create_access_token
from app.models.security import SecurityAuditEvent
from app.models.support_ticket import SupportTicket, SupportTicketAttachment, SupportTicketMessage
from app.models.user import User
from app.services import object_storage_service, smtp_service, support_ticket_images, upload_screening
from app.services import support_ticket_mail as mail
from app.services import support_tickets as st
from app.services.malware_scan_service import MalwareScanResult
from app.services.rbac import READ_ONLY_SUPER_ADMIN_SLUG, SUPPORT_SLUG
from app.services.user_role_service import set_user_roles

CSRF = "csrf-token"
BASE = "/api/admin/tickets"
SECRET_TEXT = "the-password-is-hunter2"
T0 = datetime.datetime(2026, 10, 1, 9, 0, 0)


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


@pytest.fixture
def mail_gate() -> asyncio.Event:
    """Emails wait for this to be set; a test clears it to look at the thread before the email goes."""
    gate = asyncio.Event()
    gate.set()
    return gate


@pytest.fixture(autouse=True)
def outbox(monkeypatch, session_factory, mail_gate):
    """Every email "sent"; the background mail sessions use the test database."""
    sent: list[dict] = []

    async def fake_send(db, *, to_address, subject, body_text, cc=None, attachments=()):
        await mail_gate.wait()
        sent.append({"to": to_address, "cc": list(cc or []), "subject": subject, "body": body_text})

    monkeypatch.setattr(smtp_service, "send_email", fake_send)
    monkeypatch.setattr(mail, "AsyncSessionLocal", session_factory)
    return sent


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    """Object storage in a dict: puts land in it, deletes take from it."""
    objects: dict[str, bytes] = {}
    monkeypatch.setattr(
        support_ticket_images.object_storage_service,
        "put_object",
        lambda key, body, ct: objects.__setitem__(key, body),
    )
    monkeypatch.setattr(object_storage_service, "delete_object", lambda key: objects.pop(key, None))
    monkeypatch.setattr(
        upload_screening,
        "scan_bytes",
        AsyncMock(return_value=MalwareScanResult(clean=True, signature=None, raw_response="stream: OK")),
    )
    return objects


def sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _person(db, username, *, roles=None, email=None, display=None, department=None) -> User:
    person = User(
        username=username,
        email=email,
        display_name=display,
        department=department,
        is_active=True,
        auth_provider="local",
    )
    db.add(person)
    await db.flush()
    if roles:
        await set_user_roles(db, person, roles)
    await db.commit()
    return person


@pytest.fixture
async def support(db_session):
    return await _person(db_session, "majid", roles=[SUPPORT_SLUG], email="majid@corp.test", display="Majid Arasskhani")


@pytest.fixture
async def other_support(db_session):
    return await _person(db_session, "ali", roles=[SUPPORT_SLUG], email="ali@corp.test", display="Ali Mohammadi")


@pytest.fixture
async def read_only(db_session):
    return await _person(db_session, "auditor", roles=[READ_ONLY_SUPER_ADMIN_SLUG], email="auditor@corp.test")


@pytest.fixture
async def reporter(db_session):
    return await _person(db_session, "sara", email="sara@corp.test", display="Sara Karimi", department="Finance")


_LOOSE = st.TicketSettings(per_hour=100, max_open=200)


async def _ticket(
    db,
    person,
    title="Export fails",
    *,
    description="The PDF export stops at 90%.",
    priority="normal",
    category="Bug",
    status=None,
    assignee=None,
    updated=None,
    needs_staff=None,
) -> SupportTicket:
    ticket = await st.create_ticket(
        db,
        user=person,
        title=title,
        description=description,
        category=category,
        priority=priority,
        context={"page": "/app/chat"},
        images=[],
        settings=_LOOSE,
    )
    if status is not None:
        ticket.status = status
        if status in st.DONE_STATUSES:
            ticket.needs_staff = False
            ticket.resolved_at = T0 if status == "resolved" else None
            ticket.closed_at = T0 if status == "closed" else None
    if assignee is not None:
        ticket.assignee_id = assignee.id
    if needs_staff is not None:
        ticket.needs_staff = needs_staff
    if updated is not None:
        ticket.updated_at = updated
    await db.commit()
    return ticket


def _png(size=(40, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (20, 120, 200)).save(out, format="PNG")
    return out.getvalue()


async def _audits(db, action=None) -> list[SecurityAuditEvent]:
    query = select(SecurityAuditEvent).where(SecurityAuditEvent.resource_type == "tickets")
    if action is not None:
        query = query.where(SecurityAuditEvent.action == action)
    return list((await db.execute(query.order_by(SecurityAuditEvent.id))).scalars().all())


def _id(ticket) -> int:
    """The id without touching attributes (the object may be expired)."""
    return int(inspect(ticket).identity[0])


async def _events(db, ticket) -> list[dict]:
    ticket_id = _id(ticket)
    rows = await db.execute(
        select(SupportTicketMessage.event_json)
        .where(SupportTicketMessage.ticket_id == ticket_id, SupportTicketMessage.kind == "event")
        .order_by(SupportTicketMessage.id)
    )
    return [json.loads(v) for v in rows.scalars().all()]


async def _ticket_count(db) -> int:
    return int((await db.execute(select(func.count()).select_from(SupportTicket))).scalar_one())


async def _fresh(db, ticket) -> SupportTicket:
    query = select(SupportTicket).where(SupportTicket.id == _id(ticket)).execution_options(populate_existing=True)
    return (await db.execute(query)).scalar_one()


# --- access -------------------------------------------------------------------------------------------------------

READ_PATHS = ("/meta", "/counts", "/assignees", "", "/export.csv", "/settings")


class TestAccess:
    async def test_a_plain_user_reaches_none_of_it(self, client, user, reporter, db_session):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, user)
        for path in (*READ_PATHS, f"/{ticket.id}"):
            assert (await client.get(BASE + path, headers=headers)).status_code == 403, path
        assert (
            await client.post(f"{BASE}/bulk", json={"ids": [ticket.id], "action": "close"}, headers=headers)
        ).status_code == 403
        assert (
            await client.patch(f"{BASE}/{ticket.id}", json={"priority": "high"}, headers=headers)
        ).status_code == 403

    async def test_support_reads_and_works_but_cannot_change_settings_or_delete(
        self, client, support, reporter, db_session
    ):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, support)
        for path in (*READ_PATHS, f"/{ticket.id}"):
            assert (await client.get(BASE + path, headers=headers)).status_code == 200, path
        meta = (await client.get(f"{BASE}/meta", headers=headers)).json()
        assert meta["me"] == {"id": support.id, "can_write": True, "is_super_admin": False}
        resp = await client.patch(f"{BASE}/{ticket.id}", json={"priority": "high"}, headers=headers)
        assert resp.status_code == 200 and resp.json()["priority"] == "high"
        assert resp.json()["can_write"] is True and resp.json()["can_delete"] is False
        assert (await client.put(f"{BASE}/settings", json={"per_hour": 9}, headers=headers)).status_code == 403
        assert (await client.delete(f"{BASE}/{ticket.id}", headers=headers)).status_code == 403
        preview = await client.post(f"{BASE}/delete-preview", json={"filter": {}}, headers=headers)
        assert preview.status_code == 403
        delete_all = await client.post(f"{BASE}/delete-all", json={"phrase": "DELETE ALL TICKETS"}, headers=headers)
        assert delete_all.status_code == 403
        assert await _ticket_count(db_session) == 1

    async def test_read_only_super_admin_reads_and_changes_nothing(self, client, read_only, reporter, db_session):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, read_only)
        for path in (*READ_PATHS, f"/{ticket.id}"):
            assert (await client.get(BASE + path, headers=headers)).status_code == 200, path
        meta = (await client.get(f"{BASE}/meta", headers=headers)).json()
        assert meta["me"]["can_write"] is False and meta["me"]["is_super_admin"] is False
        assert read_only.id not in [a["id"] for a in meta["assignees"]]
        detail = (await client.get(f"{BASE}/{ticket.id}", headers=headers)).json()
        assert detail["can_write"] is False and detail["can_delete"] is False
        refused = [
            await client.patch(f"{BASE}/{ticket.id}", json={"priority": "high"}, headers=headers),
            await client.post(f"{BASE}/{ticket.id}/messages", data={"body": "hi"}, headers=headers),
            await client.post(f"{BASE}/{ticket.id}/assign-to-me", headers=headers),
            await client.post(f"{BASE}/{ticket.id}/assign", json={"assignee_id": None}, headers=headers),
            await client.post(f"{BASE}/bulk", json={"ids": [ticket.id], "action": "close"}, headers=headers),
            await client.put(f"{BASE}/settings", json={"per_hour": 9}, headers=headers),
            await client.delete(f"{BASE}/{ticket.id}", headers=headers),
            await client.post(f"{BASE}/delete-preview", json={"filter": {}}, headers=headers),
            await client.post(f"{BASE}/delete-all", json={"phrase": "DELETE ALL TICKETS"}, headers=headers),
        ]
        assert [r.status_code for r in refused] == [403] * len(refused)
        assert (await _fresh(db_session, ticket)).priority == "normal"

    async def test_super_admin_does_everything(self, client, admin, reporter, db_session):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, admin)
        meta = (await client.get(f"{BASE}/meta", headers=headers)).json()
        assert meta["me"] == {"id": admin.id, "can_write": True, "is_super_admin": True}
        assert (await client.put(f"{BASE}/settings", json={"per_hour": 9}, headers=headers)).status_code == 200
        detail = (await client.get(f"{BASE}/{ticket.id}", headers=headers)).json()
        assert detail["can_delete"] is True
        assert (await client.delete(f"{BASE}/{ticket.id}", headers=headers)).json() == {"deleted": 1}

    async def test_fixed_paths_are_not_taken_for_a_ticket_id(self, client, support, reporter, db_session):
        await _ticket(db_session, reporter)
        headers = sign_in(client, support)
        assert set((await client.get(f"{BASE}/counts", headers=headers)).json()) == {
            "needs_staff",
            "needs_staff_urgent",
            "mine",
            "unassigned",
            "active",
            "closed",
        }
        assert "categories" in (await client.get(f"{BASE}/meta", headers=headers)).json()
        assert "auto_close_days" in (await client.get(f"{BASE}/settings", headers=headers)).json()
        assert isinstance((await client.get(f"{BASE}/assignees", headers=headers)).json(), list)
        assert (await client.get(f"{BASE}/export.csv", headers=headers)).headers["content-type"].startswith("text/csv")
        missing = await client.get(f"{BASE}/999999", headers=headers)
        assert missing.status_code == 404 and missing.json()["detail"]["code"] == "not_found"
        assert (await client.get(f"{BASE}/nonsense", headers=headers)).status_code in (404, 405)


# --- the queue ----------------------------------------------------------------------------------------------------


@pytest.fixture
async def queue(db_session, reporter, support, other_support):
    """Five tickets: two need staff (one Urgent), one is Majid's, one resolved, one closed."""
    other = await _person(db_session, "reza", display="Reza Ahmadi", department="IT")
    a = await _ticket(db_session, reporter, "Login loop", updated=T0)
    b = await _ticket(
        db_session, other, "VPN drops", priority="urgent", category="Problem", updated=T0 + datetime.timedelta(hours=2)
    )
    c = await _ticket(
        db_session,
        reporter,
        "Slow reports",
        description="Reports take 5 minutes with 100% CPU_load",
        priority="high",
        status="in_progress",
        assignee=support,
        needs_staff=False,
        updated=T0 + datetime.timedelta(hours=3),
    )
    d = await _ticket(
        db_session, reporter, "Old printer", priority="low", status="resolved", updated=T0 - datetime.timedelta(days=30)
    )
    e = await _ticket(
        db_session, other, "Typo", status="closed", category="Question", updated=T0 - datetime.timedelta(days=20)
    )
    return {"a": a, "b": b, "c": c, "d": d, "e": e}


async def _ids(client, headers, query="") -> list[int]:
    resp = await client.get(f"{BASE}?{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()["items"]]


class TestQueue:
    async def test_counts_and_views(self, client, support, queue):
        headers = sign_in(client, support)
        t = {k: v.id for k, v in queue.items()}
        assert (await client.get(f"{BASE}/counts", headers=headers)).json() == {
            "needs_staff": 2,
            "needs_staff_urgent": 1,
            "mine": 1,
            "unassigned": 2,
            "active": 3,
            "closed": 2,
        }
        # Urgent first, then whoever has waited longest; every other view newest activity first.
        assert await _ids(client, headers, "view=needs_staff") == [t["b"], t["a"]]
        assert await _ids(client, headers, "view=mine") == [t["c"]]
        assert await _ids(client, headers, "view=unassigned") == [t["b"], t["a"]]
        assert await _ids(client, headers) == [t["c"], t["b"], t["a"]]
        assert await _ids(client, headers, "view=closed") == [t["e"], t["d"]]
        assert await _ids(client, headers, "view=all") == [t["c"], t["b"], t["a"], t["e"], t["d"]]

    async def test_filters(self, client, support, queue):
        headers = sign_in(client, support)
        t = {k: v.id for k, v in queue.items()}
        assert await _ids(client, headers, "view=all&priority=urgent") == [t["b"]]
        assert await _ids(client, headers, "view=all&category=Question") == [t["e"]]
        assert await _ids(client, headers, "view=all&department=IT") == [t["b"], t["e"]]
        assert await _ids(client, headers, f"view=all&assignee={support.id}") == [t["c"]]
        assert await _ids(client, headers, "view=active&assignee=none") == [t["b"], t["a"]]
        assert await _ids(client, headers, "view=all&status=resolved") == [t["d"]]
        bad = await client.get(f"{BASE}?priority=extreme", headers=headers)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_filter"
        assert (await client.get(f"{BASE}?view=everything", headers=headers)).status_code == 422
        assert (await client.get(f"{BASE}?assignee=bob", headers=headers)).status_code == 422

    async def test_search_title_text_reporter_and_number(self, client, support, queue):
        headers = sign_in(client, support)
        t = {k: v.id for k, v in queue.items()}
        number = queue["d"].number
        assert await _ids(client, headers, "view=all&q=vpn") == [t["b"]]
        assert await _ids(client, headers, "view=all&q=PDF export") == [t["b"], t["a"], t["e"], t["d"]]
        assert await _ids(client, headers, "view=all&q=Reza Ahmadi") == [t["b"], t["e"]]
        assert await _ids(client, headers, "view=all&q=sara") == [t["c"], t["a"], t["d"]]
        assert await _ids(client, headers, f"view=all&q=%23{number}") == [t["d"]]
        assert await _ids(client, headers, f"view=all&q={number}") == [t["d"]]
        # A typed % or _ is a character, not a wildcard.
        assert await _ids(client, headers, "view=all&q=100%25") == [t["c"]]
        assert await _ids(client, headers, "view=all&q=CPU_load") == [t["c"]]
        assert await _ids(client, headers, "view=all&q=CPUxload") == []

    async def test_pagination_and_row_shape(self, client, support, queue):
        headers = sign_in(client, support)
        resp = (await client.get(f"{BASE}?view=all&page=2&page_size=2", headers=headers)).json()
        assert resp["total"] == 5 and resp["page"] == 2 and resp["page_size"] == 2
        assert [i["id"] for i in resp["items"]] == [queue["a"].id, queue["e"].id]
        assert (await client.get(f"{BASE}?page_size=101", headers=headers)).status_code == 422
        assert (await client.get(f"{BASE}?page=0", headers=headers)).status_code == 422
        [row] = (await client.get(f"{BASE}?view=mine", headers=headers)).json()["items"]
        assert row["assignee"] == {"id": support.id, "name": "Majid Arasskhani"}
        assert row["reporter"] == {"name": "Sara Karimi", "username": "sara", "department": "Finance"}
        assert row["message_count"] == 2 and row["needs_staff"] is False  # description + automatic reply

    async def test_meta_and_assignees(self, client, support, other_support, admin, queue):
        headers = sign_in(client, support)
        meta = (await client.get(f"{BASE}/meta", headers=headers)).json()
        assert meta["departments"] == ["Finance", "IT"]
        assert meta["categories"] == list(st.DEFAULT_CATEGORIES)
        assert meta["priorities"] == list(st.PRIORITIES) and meta["statuses"] == list(st.STATUSES)
        assert meta["settings"] == {"auto_close_days": 7, "reopen_days": 14, "enabled": True}
        people = {a["username"]: a for a in (await client.get(f"{BASE}/assignees", headers=headers)).json()}
        assert set(people) == {"majid", "ali", "fixture_admin"}
        assert people["majid"] == {
            "id": support.id,
            "name": "Majid Arasskhani",
            "username": "majid",
            "role_label": "Support",
            "open_count": 1,
            "is_me": True,
        }
        assert people["fixture_admin"]["role_label"] == "Super Admin" and people["ali"]["is_me"] is False


# --- one ticket ---------------------------------------------------------------------------------------------------


class TestTicket:
    async def test_detail_has_notes_events_and_context(self, client, support, reporter, db_session):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, support)
        await client.post(
            f"{BASE}/{ticket.id}/messages", data={"body": "Check logs", "internal": "true"}, headers=headers
        )
        await client.post(
            f"{BASE}/{ticket.id}/messages", data={"body": "Try again", "internal": "false"}, headers=headers
        )
        detail = (await client.get(f"{BASE}/{ticket.id}", headers=headers)).json()
        kinds = [m["kind"] for m in detail["messages"]]
        assert kinds == ["user", "auto", "note", "staff", "event"]
        note = detail["messages"][2]
        assert note["internal"] is True and note["author_label"] == "Support" and note["body"] == "Check logs"
        assert detail["messages"][-1]["body"] == "Status changed to In progress"
        assert detail["context"] == {"page": "/app/chat"}
        assert detail["reporter"]["email"] == "sara@corp.test"
        assert detail["first_staff_reply_at"] is not None and detail["needs_staff"] is False

    async def test_patch_changes_status_priority_and_category_with_audit(
        self, client, support, reporter, db_session, outbox
    ):
        ticket = await _ticket(db_session, reporter, SECRET_TEXT)
        headers = sign_in(client, support)
        resp = await client.patch(
            f"{BASE}/{ticket.id}",
            json={"status": "waiting", "priority": "high", "category": "Question"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["status"], body["priority"], body["category"]) == ("waiting", "high", "Question")
        assert body["auto_close_at"] is not None
        assert [e["type"] for e in await _events(db_session, ticket)] == ["status", "priority", "category"]
        [row] = await _audits(db_session, "ticket_updated")
        detail = json.loads(row.detail_json)
        assert detail["number"] == ticket.number
        assert detail["changes"]["status"] == {"from": "open", "to": "waiting"}
        # Nothing changes, nothing is logged.
        await client.patch(f"{BASE}/{ticket.id}", json={"priority": "high"}, headers=headers)
        assert len(await _audits(db_session, "ticket_updated")) == 1
        bad = await client.patch(f"{BASE}/{ticket.id}", json={"category": "Nope"}, headers=headers)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_category"
        bad = await client.patch(f"{BASE}/{ticket.id}", json={"status": "gone"}, headers=headers)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_status"
        await mail.drain()
        assert outbox == []  # email_user is off by default

    async def test_a_reply_hands_over_a_note_does_not(self, client, support, reporter, db_session):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, support)
        note = await client.post(
            f"{BASE}/{ticket.id}/messages", data={"body": "internal", "internal": "true"}, headers=headers
        )
        assert note.status_code == 200, note.text
        fresh = await _fresh(db_session, ticket)
        assert (fresh.status, fresh.needs_staff, fresh.user_unread, fresh.first_staff_reply_at) == (
            "open",
            True,
            False,
            None,
        )
        reply = await client.post(
            f"{BASE}/{ticket.id}/messages",
            data={"body": "Fixed", "internal": "false", "status": "resolved"},
            headers=headers,
        )
        assert reply.status_code == 200
        fresh = await _fresh(db_session, ticket)
        assert (fresh.status, fresh.needs_staff, fresh.user_unread) == ("resolved", False, True)
        assert fresh.resolved_by == "staff" and fresh.first_staff_reply_at is not None
        replied, noted = await _audits(db_session, "ticket_replied"), await _audits(db_session, "ticket_note_added")
        assert json.loads(replied[0].detail_json)["status"] == {"from": "open", "to": "resolved"}
        assert len(noted) == 1 and "internal" not in noted[0].detail_json

    async def test_a_reply_with_images_is_stored_under_the_reporter(
        self, client, support, reporter, db_session, storage
    ):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, support)
        resp = await client.post(
            f"{BASE}/{ticket.id}/messages",
            data={"body": "See the arrow", "internal": "false"},
            files=[("images", ("arrow.png", _png(), "image/png"))],
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        staff = [m for m in resp.json()["messages"] if m["kind"] == "staff"][0]
        assert len(staff["attachments"]) == 1 and staff["attachments"][0]["display_name"] == "arrow.png"
        [key] = list(storage)
        assert key.startswith(f"tickets/{reporter.id}/")

    async def test_a_message_the_rules_refuse_stores_no_image(self, client, support, reporter, db_session, storage):
        ticket = await _ticket(db_session, reporter)
        await st.save_settings(db_session, st.TicketSettings(max_images=1))
        await db_session.commit()
        headers = sign_in(client, support)
        empty = await client.post(
            f"{BASE}/{ticket.id}/messages",
            data={"body": "   "},
            files=[("images", ("a.png", _png(), "image/png"))],
            headers=headers,
        )
        assert empty.status_code == 422 and empty.json()["detail"]["code"] == "invalid_body"
        too_many = await client.post(
            f"{BASE}/{ticket.id}/messages",
            data={"body": "two"},
            files=[("images", ("a.png", _png(), "image/png")), ("images", ("b.png", _png(), "image/png"))],
            headers=headers,
        )
        assert too_many.status_code == 422 and too_many.json()["detail"]["code"] == "too_many_images"
        not_image = await client.post(
            f"{BASE}/{ticket.id}/messages",
            data={"body": "pdf"},
            files=[("images", ("a.pdf", b"%PDF-1.4", "application/pdf"))],
            headers=headers,
        )
        assert not_image.status_code == 422 and not_image.json()["detail"]["file"] == "a.pdf"
        assert storage == {}

    async def test_a_reply_that_fails_after_its_images_were_stored_leaves_none_behind(
        self, client, support, reporter, db_session, storage, monkeypatch
    ):
        ticket = await _ticket(db_session, reporter)

        async def broken(*_a, **_k):
            raise RuntimeError("database went away")

        monkeypatch.setattr(st, "add_staff_message", broken)
        headers = sign_in(client, support)
        with pytest.raises(RuntimeError):
            await client.post(
                f"{BASE}/{ticket.id}/messages",
                data={"body": "Here"},
                files=[("images", ("a.png", _png(), "image/png"))],
                headers=headers,
            )
        assert storage == {}

    async def test_text_and_status_are_refused_before_any_image_is_decoded(
        self, client, support, reporter, db_session, monkeypatch
    ):
        ticket = await _ticket(db_session, reporter)
        calls: list[int] = []

        async def counting_store(uploads, settings, *, owner_user_id):
            calls.append(len(uploads))
            return []

        monkeypatch.setattr(admin_tickets, "store_ticket_images", counting_store)
        headers = sign_in(client, support)
        shot = [("images", ("a.png", _png(), "image/png"))]
        for data, code in (({"body": " "}, "invalid_body"), ({"body": "ok", "status": "gone"}, "invalid_status")):
            resp = await client.post(f"{BASE}/{ticket.id}/messages", data=data, files=shot, headers=headers)
            assert resp.status_code == 422 and resp.json()["detail"]["code"] == code
        assert calls == []

    async def test_the_person_is_emailed_about_a_reply_when_that_is_on(
        self, client, support, reporter, db_session, outbox
    ):
        ticket = await _ticket(db_session, reporter)
        await st.save_settings(db_session, st.TicketSettings(email_user=True))
        await db_session.commit()
        headers = sign_in(client, support)
        await client.post(f"{BASE}/{ticket.id}/messages", data={"body": "A note", "internal": "true"}, headers=headers)
        await mail.drain()
        assert outbox == []
        await client.post(f"{BASE}/{ticket.id}/messages", data={"body": "We fixed it"}, headers=headers)
        await mail.drain()
        assert [m["to"] for m in outbox] == ["sara@corp.test"] and "We fixed it" in outbox[0]["body"]
        await client.patch(f"{BASE}/{ticket.id}", json={"status": "resolved"}, headers=headers)
        await mail.drain()
        assert "is resolved" in outbox[-1]["subject"]


# --- assignment ---------------------------------------------------------------------------------------------------


class TestAssignment:
    async def test_assigning_someone_else_emails_them_once(
        self, client, support, other_support, reporter, db_session, outbox, mail_gate
    ):
        ticket = await _ticket(db_session, reporter, SECRET_TEXT)
        headers = sign_in(client, support)
        mail_gate.clear()
        resp = await client.post(f"{BASE}/{ticket.id}/assign", json={"assignee_id": other_support.id}, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["assignee"] == {"id": other_support.id, "name": "Ali Mohammadi"}
        assert (await _events(db_session, ticket))[-1]["email"] == "pending"
        mail_gate.set()
        await mail.drain()
        assert (await _events(db_session, ticket))[-1]["email"] == "sent"
        assert [m["to"] for m in outbox] == ["ali@corp.test"]
        [row] = await _audits(db_session, "ticket_assigned")
        assert json.loads(row.detail_json) == {
            "number": ticket.number,
            "from_id": None,
            "to_id": other_support.id,
            "email": True,
        }
        detail = (await client.get(f"{BASE}/{ticket.id}", headers=headers)).json()
        assert "Majid Arasskhani assigned this to Ali Mohammadi · email sent" in [m["body"] for m in detail["messages"]]

    async def test_assign_to_me_and_picking_yourself_send_nothing(self, client, support, reporter, db_session, outbox):
        first = await _ticket(db_session, reporter)
        second = await _ticket(db_session, reporter, "Second")
        headers = sign_in(client, support)
        resp = await client.post(f"{BASE}/{first.id}/assign-to-me", headers=headers)
        assert resp.status_code == 200 and resp.json()["assignee"]["id"] == support.id
        resp = await client.post(f"{BASE}/{second.id}/assign", json={"assignee_id": support.id}, headers=headers)
        assert resp.json()["assignee"]["id"] == support.id
        await mail.drain()
        assert outbox == []
        assert (await _events(db_session, first))[-1]["email"] == "none"
        # Taking it again changes nothing and logs nothing.
        await client.post(f"{BASE}/{first.id}/assign-to-me", headers=headers)
        assert len(await _audits(db_session, "ticket_assigned")) == 2

    async def test_reassign_emails_only_the_new_person_and_unassign_nobody(
        self, client, admin, support, other_support, reporter, db_session, outbox
    ):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, admin)
        await client.post(f"{BASE}/{ticket.id}/assign", json={"assignee_id": support.id}, headers=headers)
        await client.post(f"{BASE}/{ticket.id}/assign", json={"assignee_id": other_support.id}, headers=headers)
        await mail.drain()
        assert [m["to"] for m in outbox] == ["majid@corp.test", "ali@corp.test"]
        resp = await client.post(f"{BASE}/{ticket.id}/assign", json={"assignee_id": None}, headers=headers)
        assert resp.json()["assignee"] is None
        await mail.drain()
        assert len(outbox) == 2
        [row] = await _audits(db_session, "ticket_unassigned")
        assert json.loads(row.detail_json) == {"number": ticket.number, "from_id": other_support.id}

    async def test_only_people_who_work_tickets_can_be_assigned(
        self, client, support, read_only, user, reporter, db_session
    ):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, support)
        for person_id in (user.id, read_only.id, 999999):
            resp = await client.post(f"{BASE}/{ticket.id}/assign", json={"assignee_id": person_id}, headers=headers)
            assert resp.status_code == 422 and resp.json()["detail"]["code"] == "not_assignable", person_id
        assert (await _fresh(db_session, ticket)).assignee_id is None


# --- bulk ---------------------------------------------------------------------------------------------------------


class TestBulk:
    async def test_bulk_assign_sends_one_email_for_all_tickets(
        self, client, support, other_support, reporter, db_session, outbox
    ):
        tickets = [await _ticket(db_session, reporter, f"Ticket {n}") for n in range(3)]
        headers = sign_in(client, support)
        resp = await client.post(
            f"{BASE}/bulk",
            json={"ids": [t.id for t in tickets], "action": "assign", "assignee_id": other_support.id},
            headers=headers,
        )
        assert resp.json() == {"updated": 3}
        await mail.drain()
        assert len(outbox) == 1 and outbox[0]["subject"] == "3 tickets assigned to you"
        for ticket in tickets:
            assert (await _events(db_session, ticket))[-1]["email"] == "sent"
        [row] = await _audits(db_session, "tickets_bulk_assign")
        detail = json.loads(row.detail_json)
        assert detail["numbers"] == sorted(t.number for t in tickets) and detail["emails"] == 3

    async def test_bulk_assign_to_me_and_close(self, client, support, reporter, db_session, outbox):
        tickets = [await _ticket(db_session, reporter, f"Ticket {n}") for n in range(2)]
        done = await _ticket(db_session, reporter, "Done", status="closed")
        ids = [t.id for t in tickets] + [done.id, 999999]
        headers = sign_in(client, support)
        assert (
            await client.post(f"{BASE}/bulk", json={"ids": ids, "action": "assign_to_me"}, headers=headers)
        ).json() == {"updated": 3}
        assert (await client.post(f"{BASE}/bulk", json={"ids": ids, "action": "close"}, headers=headers)).json() == {
            "updated": 2
        }
        await mail.drain()
        assert outbox == []
        for ticket in tickets:
            fresh = await _fresh(db_session, ticket)
            assert (fresh.status, fresh.closed_reason, fresh.assignee_id) == ("closed", "manual", support.id)

    async def test_bulk_limits(self, client, support, reporter, db_session):
        ticket = await _ticket(db_session, reporter)
        headers = sign_in(client, support)
        too_many = await client.post(
            f"{BASE}/bulk", json={"ids": list(range(1, 202)), "action": "close"}, headers=headers
        )
        assert too_many.status_code == 422
        assert (
            await client.post(f"{BASE}/bulk", json={"ids": [], "action": "close"}, headers=headers)
        ).status_code == 422
        no_one = await client.post(f"{BASE}/bulk", json={"ids": [ticket.id], "action": "assign"}, headers=headers)
        assert no_one.status_code == 422 and no_one.json()["detail"]["code"] == "assignee_required"
        bad = await client.post(f"{BASE}/bulk", json={"ids": [ticket.id], "action": "delete"}, headers=headers)
        assert bad.status_code == 422


# --- export -------------------------------------------------------------------------------------------------------


class TestExport:
    async def test_csv_has_no_message_text_and_is_safe_in_a_spreadsheet(self, client, support, reporter, db_session):
        await _ticket(db_session, reporter, '=HYPERLINK("http://evil")', description=SECRET_TEXT)
        await _ticket(db_session, reporter, "-2+3", status="closed", updated=T0)
        headers = sign_in(client, support)
        resp = await client.get(f"{BASE}/export.csv?view=all", headers=headers)
        assert resp.status_code == 200
        assert 'filename="tickets-' in resp.headers["content-disposition"]
        text = resp.text
        assert SECRET_TEXT not in text and "Hello" not in text  # neither the description nor the automatic reply
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
        assert rows[0][:4] == ["number", "title", "reporter", "username"]
        titles = {r[1] for r in rows[1:]}
        assert titles == {'\'=HYPERLINK("http://evil")', "'-2+3"}
        [row] = await _audits(db_session, "tickets_exported")
        assert json.loads(row.detail_json)["rows"] == 2

    async def test_export_takes_statuses_and_before(self, client, support, reporter, db_session):
        await _ticket(db_session, reporter, "Open one")
        await _ticket(db_session, reporter, "Old resolved", status="resolved", updated=T0)
        await _ticket(db_session, reporter, "New closed", status="closed", updated=T0 + datetime.timedelta(days=10))
        headers = sign_in(client, support)
        resp = await client.get(
            f"{BASE}/export.csv?view=all&statuses=resolved,closed&before=2026-10-05", headers=headers
        )
        rows = list(csv.reader(io.StringIO(resp.text.lstrip("﻿"))))
        assert [r[1] for r in rows[1:]] == ["Old resolved"]
        bad = await client.get(f"{BASE}/export.csv?statuses=resolved,gone", headers=headers)
        assert bad.status_code == 422
        bad = await client.get(f"{BASE}/export.csv?before=yesterday", headers=headers)
        assert bad.status_code == 422


# --- settings -----------------------------------------------------------------------------------------------------


class TestSettings:
    async def test_a_partial_update_is_merged_checked_and_logged(self, client, admin, db_session):
        headers = sign_in(client, admin)
        assert (await client.get(f"{BASE}/settings", headers=headers)).json() == st.TicketSettings().as_dict()
        resp = await client.put(
            f"{BASE}/settings", json={"auto_close_days": 10, "categories": ["Bug", "Access"]}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {**st.TicketSettings().as_dict(), "auto_close_days": 10, "categories": ["Bug", "Access"]}
        resp = await client.put(f"{BASE}/settings", json={"email_assignee": False}, headers=headers)
        assert resp.json()["auto_close_days"] == 10 and resp.json()["email_assignee"] is False
        first, second = await _audits(db_session, "tickets_settings_updated")
        assert json.loads(first.detail_json) == {
            "changed": ["auto_close_days", "categories"],
            "before": {"auto_close_days": 7, "categories": list(st.DEFAULT_CATEGORIES)},
            "after": {"auto_close_days": 10, "categories": ["Bug", "Access"]},
        }
        assert json.loads(second.detail_json)["changed"] == ["email_assignee"]

    @pytest.mark.parametrize(
        "change",
        [
            {"auto_close_days": 0},
            {"per_hour": "5"},
            {"categories": ["Bug", "bug"]},
            {"image_types": ["png", "svg"]},
            {"notify_emails": ["not an address"]},
            {"auto_reply_enabled": True, "auto_reply_text": "  "},
            {"retention_days": 7},  # shorter than the 14-day reopen window
        ],
    )
    async def test_settings_outside_the_rules_are_refused(self, client, admin, db_session, change):
        headers = sign_in(client, admin)
        resp = await client.put(f"{BASE}/settings", json=change, headers=headers)
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_settings"
        assert await _audits(db_session, "tickets_settings_updated") == []


# --- deleting -----------------------------------------------------------------------------------------------------


async def _attach(db, ticket, n=1, size=1000) -> None:
    message = (
        await db.execute(select(SupportTicketMessage).where(SupportTicketMessage.ticket_id == ticket.id).limit(1))
    ).scalar_one()
    for i in range(n):
        db.add(
            SupportTicketAttachment(
                ticket_id=ticket.id,
                message_id=message.id,
                storage_key=f"tickets/{ticket.user_id}/{ticket.id}-{i}.png",
                mime="image/png",
                bytes=size,
                width=10,
                height=10,
                sha256="ab" * 32,
                display_name="a.png",
            )
        )
    await db.commit()


class TestDelete:
    async def test_delete_one_ticket_with_its_images(self, client, admin, reporter, db_session, storage):
        ticket = await _ticket(db_session, reporter, SECRET_TEXT)
        await _attach(db_session, ticket, 2)
        storage.update({f"tickets/{reporter.id}/{ticket.id}-{i}.png": b"x" for i in range(2)})
        headers = sign_in(client, admin)
        assert (await client.delete(f"{BASE}/{ticket.id}", headers=headers)).json() == {"deleted": 1}
        await st.drain_storage_deletions()
        assert storage == {} and await _ticket_count(db_session) == 0
        [row] = await _audits(db_session, "ticket_deleted")
        assert json.loads(row.detail_json) == {
            "number": ticket.number,
            "status": "open",
            "messages": 2,
            "images": 2,
            "image_bytes": 2000,
        }
        assert (await client.delete(f"{BASE}/{ticket.id}", headers=headers)).status_code == 404

    async def test_preview_and_delete_by_filter(self, client, admin, reporter, db_session):
        await _ticket(db_session, reporter, "Active")
        old = await _ticket(db_session, reporter, "Old", status="closed", updated=T0)
        await _attach(db_session, old, 1, 500)
        done = await _ticket(db_session, reporter, "Done", status="resolved", updated=T0)
        headers = sign_in(client, admin)
        preview = (await client.post(f"{BASE}/delete-preview", json={"filter": {}}, headers=headers)).json()
        assert {k: preview[k] for k in ("count", "messages", "images", "image_bytes", "includes_active", "phrase")} == {
            "count": 2,
            "messages": 4,
            "images": 1,
            "image_bytes": 500,
            "includes_active": False,
            "phrase": "DELETE 2 TICKETS",
        }
        wrong = await client.post(
            f"{BASE}/delete",
            json={"filter": {}, "token": preview["token"], "phrase": "DELETE 3 TICKETS"},
            headers=headers,
        )
        assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "phrase_mismatch"
        resp = await client.post(
            f"{BASE}/delete",
            json={
                "filter": {"statuses": ["closed", "resolved"]},
                "token": preview["token"],
                "phrase": "DELETE 2 TICKETS",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"deleted": 2, "messages": 4, "images": 1}
        assert await _ticket_count(db_session) == 1
        [row] = await _audits(db_session, "tickets_deleted")
        detail = json.loads(row.detail_json)
        assert detail["count"] == 2 and detail["numbers"] == sorted([old.number, done.number])
        assert detail["filter"] == {"statuses": ["resolved", "closed"]}

    async def test_the_token_binds_the_actor_the_scope_and_time(self, client, admin, reporter, db_session, monkeypatch):
        await _ticket(db_session, reporter, "Done", status="resolved")
        other_admin = await _person(db_session, "boss", roles=["super_admin"], email="boss@corp.test")
        headers = sign_in(client, admin)
        preview = (await client.post(f"{BASE}/delete-preview", json={"filter": {}}, headers=headers)).json()

        async def attempt(body, who=None):
            hdrs = sign_in(client, who) if who else sign_in(client, admin)
            return await client.post(f"{BASE}/delete", json=body, headers=hdrs)

        base = {"filter": {}, "token": preview["token"], "phrase": "DELETE 1 TICKETS"}
        cases = [
            {**base, "token": preview["token"][:-2] + "xx"},
            {**base, "token": "garbage"},
            {**base, "filter": {"priority": "low"}},
            {"ids": [1], "token": preview["token"], "phrase": "DELETE 1 TICKETS"},
        ]
        for body in cases:
            resp = await attempt(body)
            assert resp.status_code == 400 and resp.json()["detail"]["code"] == "token_invalid", body
        resp = await attempt(base, other_admin)
        assert resp.status_code == 400 and resp.json()["detail"]["code"] == "token_invalid"
        later = admin_tickets._epoch() + admin_tickets.TOKEN_TTL_SECONDS + 1
        monkeypatch.setattr(admin_tickets, "_epoch", lambda: later)
        resp = await attempt(base)
        assert resp.status_code == 400 and resp.json()["detail"]["code"] == "token_invalid"
        assert await _ticket_count(db_session) == 1

    async def test_a_changed_count_deletes_nothing(self, client, admin, reporter, db_session):
        await _ticket(db_session, reporter, "Done", status="resolved")
        headers = sign_in(client, admin)
        preview = (await client.post(f"{BASE}/delete-preview", json={"filter": {}}, headers=headers)).json()
        await _ticket(db_session, reporter, "Closed meanwhile", status="closed")
        resp = await client.post(
            f"{BASE}/delete",
            json={"filter": {}, "token": preview["token"], "phrase": preview["phrase"]},
            headers=headers,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "count_changed" and resp.json()["detail"]["count"] == 2
        assert await _ticket_count(db_session) == 2 and await _audits(db_session, "tickets_deleted") == []

    @pytest.mark.parametrize("by", ["filter", "ids"])
    async def test_a_ticket_that_leaves_the_scope_after_the_recount_is_not_deleted(
        self, client, admin, reporter, db_session, monkeypatch, by
    ):
        first = await _ticket(db_session, reporter, "Done", status="resolved")
        second = await _ticket(db_session, reporter, "Done too", status="closed")
        scope = {"filter": {}} if by == "filter" else {"ids": [_id(first), _id(second)]}
        headers = sign_in(client, admin)
        preview = (await client.post(f"{BASE}/delete-preview", json=scope, headers=headers)).json()
        assert preview["count"] == 2 and preview["includes_active"] is False
        audit = admin_tickets._audit

        async def reopen_meanwhile(db, *args, **kwargs):
            # The reporter replies between the recount and the delete.
            await audit(db, *args, **kwargs)
            ticket = await db.get(SupportTicket, _id(second))
            ticket.status, ticket.closed_at, ticket.needs_staff = "open", None, True

        monkeypatch.setattr(admin_tickets, "_audit", reopen_meanwhile)
        resp = await client.post(
            f"{BASE}/delete", json={**scope, "token": preview["token"], "phrase": preview["phrase"]}, headers=headers
        )
        assert resp.status_code == 200 and resp.json()["deleted"] == 1
        remaining = (await db_session.execute(select(SupportTicket.id))).scalars().all()
        assert remaining == [_id(second)]

    async def test_a_selected_ticket_reopened_after_the_preview_changes_the_count(
        self, client, admin, reporter, db_session
    ):
        done = await _ticket(db_session, reporter, "Done", status="closed")
        headers = sign_in(client, admin)
        preview = (await client.post(f"{BASE}/delete-preview", json={"ids": [_id(done)]}, headers=headers)).json()
        assert preview["includes_active"] is False
        row = await _fresh(db_session, done)
        row.status, row.closed_at = "open", None
        await db_session.commit()
        resp = await client.post(
            f"{BASE}/delete",
            json={"ids": [_id(done)], "token": preview["token"], "phrase": preview["phrase"]},
            headers=headers,
        )
        assert resp.status_code == 409 and resp.json()["detail"] == {
            "code": "count_changed",
            "message": "The number of tickets changed from 1 to 0. Check it again.",
            "count": 0,
        }
        assert await _ticket_count(db_session) == 1

    async def test_active_tickets_only_when_named(self, client, admin, reporter, db_session):
        active = await _ticket(db_session, reporter, "Active")
        done = await _ticket(db_session, reporter, "Done", status="closed")
        headers = sign_in(client, admin)
        default = (await client.post(f"{BASE}/delete-preview", json={"filter": {}}, headers=headers)).json()
        assert default["count"] == 1 and default["includes_active"] is False
        named = (
            await client.post(f"{BASE}/delete-preview", json={"filter": {"statuses": ["open"]}}, headers=headers)
        ).json()
        assert named["count"] == 1 and named["includes_active"] is True
        by_id = (
            await client.post(f"{BASE}/delete-preview", json={"ids": [active.id, done.id, 999999]}, headers=headers)
        ).json()
        assert by_id["count"] == 2 and by_id["includes_active"] is True and by_id["phrase"] == "DELETE 2 TICKETS"
        resp = await client.post(
            f"{BASE}/delete",
            json={"ids": [done.id, active.id, 999999], "token": by_id["token"], "phrase": "DELETE 2 TICKETS"},
            headers=headers,
        )
        assert resp.json()["deleted"] == 2 and await _ticket_count(db_session) == 0

    async def test_scope_is_checked(self, client, admin, db_session):
        headers = sign_in(client, admin)
        for body in (
            {},
            {"ids": [1], "filter": {}},
            {"ids": []},
            {"filter": {"statuses": ["gone"]}},
            {"filter": {"before": "10/05/2026"}},
        ):
            assert (await client.post(f"{BASE}/delete-preview", json=body, headers=headers)).status_code == 422, body

    async def test_delete_all(self, client, admin, reporter, db_session):
        tickets = [await _ticket(db_session, reporter, f"T{n}", status="closed" if n else None) for n in range(3)]
        headers = sign_in(client, admin)
        wrong = await client.post(f"{BASE}/delete-all", json={"phrase": "delete all tickets"}, headers=headers)
        assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "phrase_mismatch"
        assert await _ticket_count(db_session) == 3
        resp = await client.post(f"{BASE}/delete-all", json={"phrase": "DELETE ALL TICKETS"}, headers=headers)
        assert resp.json() == {"deleted": 3} and await _ticket_count(db_session) == 0
        [row] = await _audits(db_session, "tickets_deleted_all")
        detail = json.loads(row.detail_json)
        assert detail["count"] == 3 and detail["numbers"] == sorted(t.number for t in tickets)


async def test_admin_logs_never_hold_ticket_text(client, admin, support, other_support, reporter, db_session):
    ticket = await _ticket(db_session, reporter, SECRET_TEXT, description=SECRET_TEXT)
    second = await _ticket(db_session, reporter, SECRET_TEXT, status="closed")
    headers = sign_in(client, support)
    await client.post(f"{BASE}/{ticket.id}/messages", data={"body": SECRET_TEXT, "internal": "true"}, headers=headers)
    await client.post(f"{BASE}/{ticket.id}/messages", data={"body": SECRET_TEXT}, headers=headers)
    await client.patch(f"{BASE}/{ticket.id}", json={"priority": "urgent"}, headers=headers)
    await client.post(f"{BASE}/{ticket.id}/assign", json={"assignee_id": other_support.id}, headers=headers)
    await client.post(f"{BASE}/bulk", json={"ids": [ticket.id], "action": "close"}, headers=headers)
    await client.get(f"{BASE}/export.csv?view=all&q={SECRET_TEXT}", headers=headers)
    headers = sign_in(client, admin)
    preview = (await client.post(f"{BASE}/delete-preview", json={"ids": [second.id]}, headers=headers)).json()
    await client.post(
        f"{BASE}/delete",
        json={"ids": [second.id], "token": preview["token"], "phrase": preview["phrase"]},
        headers=headers,
    )
    await client.delete(f"{BASE}/{ticket.id}", headers=headers)
    await mail.drain()
    rows = await _audits(db_session)
    assert {r.action for r in rows} >= {
        "ticket_note_added",
        "ticket_replied",
        "ticket_updated",
        "ticket_assigned",
        "tickets_bulk_close",
        "tickets_exported",
        "tickets_deleted",
        "ticket_deleted",
    }
    assert all(SECRET_TEXT not in str(r.detail_json) for r in rows)
