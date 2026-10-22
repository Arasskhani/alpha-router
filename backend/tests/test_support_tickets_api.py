"""Support (user API): open, list, read, answer and resolve one's own tickets, and see their images."""

from __future__ import annotations

import datetime
import io
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.support_ticket import SupportTicket, SupportTicketAttachment, SupportTicketMessage
from app.models.user import User
from app.services import object_storage_service, smtp_service, upload_screening
from app.services import support_ticket_mail as mail
from app.services import support_tickets as st
from app.services.malware_scan_service import MalwareScanResult
from app.services.rbac import READ_ONLY_SUPER_ADMIN_SLUG, SUPPORT_SLUG
from app.services.user_role_service import set_user_roles

CSRF = "csrf-token"
BASE = "/api/support"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    """Object storage as a dict; the malware scan passes."""
    objects: dict[str, bytes] = {}
    monkeypatch.setattr(object_storage_service, "put_object", lambda key, body, ct: objects.__setitem__(key, body))
    monkeypatch.setattr(object_storage_service, "get_object_bytes", lambda key: objects[key])
    monkeypatch.setattr(object_storage_service, "delete_object", lambda key: objects.pop(key, None))
    monkeypatch.setattr(
        upload_screening,
        "scan_bytes",
        AsyncMock(return_value=MalwareScanResult(clean=True, signature=None, raw_response="stream: OK")),
    )
    return objects


@pytest.fixture(autouse=True)
def outbox(monkeypatch, session_factory):
    sent: list[dict] = []

    async def fake_send(db, *, to_address, subject, body_text, cc=None, attachments=()):
        sent.append({"to": to_address, "cc": list(cc or []), "subject": subject, "body": body_text})

    monkeypatch.setattr(smtp_service, "send_email", fake_send)
    monkeypatch.setattr(mail, "AsyncSessionLocal", session_factory)
    return sent


def sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


def png(size=(40, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (30, 120, 200)).save(out, format="PNG")
    return out.getvalue()


async def person(db, username, *, roles=None, active=True, email=None, department=None) -> User:
    row = User(
        username=username,
        email=email,
        department=department,
        is_active=active,
        auth_provider="local",
    )
    db.add(row)
    await db.flush()
    if roles:
        await set_user_roles(db, row, roles)
    await db.commit()
    return row


async def configure(db, **changes) -> st.TicketSettings:
    settings = st.TicketSettings(**changes)
    await st.save_settings(db, settings)
    await db.commit()
    return settings


async def open_ticket(client, headers, *, images=(), **fields):
    data = {"title": "Export fails", "description": "It stops halfway.", "category": "Bug"}
    data.update(fields)
    files = [("images", (name, body, "image/png")) for name, body in images]
    return await client.post(f"{BASE}/tickets", data=data, files=files or None, headers=headers)


async def fresh(db, ticket_id: int) -> SupportTicket:
    ticket = await db.get(SupportTicket, ticket_id, populate_existing=True)
    assert ticket is not None
    return ticket


async def staff_reply(db, ticket_id, staff, body="Try again now.", **kw):
    ticket = await fresh(db, ticket_id)
    await st.add_staff_message(
        db,
        ticket=ticket,
        staff=staff,
        body=body,
        internal=kw.get("internal", False),
        images=kw.get("images", []),
        status=kw.get("status"),
    )
    await db.commit()


class TestStatus:
    async def test_the_form_and_the_reporter(self, client, db_session):
        sara = await person(db_session, "sara", email="sara@corp.test", department="Finance")
        headers = sign_in(client, sara)
        body = (await client.get(f"{BASE}/status", headers=headers)).json()
        assert body["enabled"] is True and body["unread"] == 0
        assert body["categories"] == list(st.DEFAULT_CATEGORIES)
        assert body["priorities"] == ["low", "normal", "high", "urgent"]
        assert body["limits"] == {
            "image_types": ["png", "jpg", "webp", "gif"],
            "max_image_mb": 5,
            "max_images": 5,
            "max_side_px": 4096,
        }
        assert (body["reopen_days"], body["auto_close_days"]) == (14, 7)
        assert body["reporter"] == {
            "name": "sara",
            "username": "sara",
            "email": "sara@corp.test",
            "department": "Finance",
        }

    async def test_signed_out_is_refused(self, client):
        assert (await client.get(f"{BASE}/status")).status_code == 401


class TestCreate:
    async def test_a_ticket_with_images_and_the_automatic_reply(self, client, db_session, user, storage):
        headers = sign_in(client, user)
        context = json.dumps({"browser": "Firefox", "page": "/app/chat"})
        resp = await open_ticket(
            client,
            headers,
            images=[("one.png", png()), ("two.png", png((20, 10)))],
            priority="high",
            context=context,
        )
        assert resp.status_code == 201, resp.text
        detail = resp.json()
        assert detail["status"] == "open" and detail["priority"] == "high" and detail["number"] == 1000 + detail["id"]
        assert [m["kind"] for m in detail["messages"]] == ["user", "auto"]
        first, auto = detail["messages"]
        assert first["author_label"] == "You" and auto["author_label"] == "Automatic reply"
        assert f"#{detail['number']}" in auto["body"]
        assert [a["display_name"] for a in first["attachments"]] == ["one.png", "two.png"]
        assert first["attachments"][0]["url"] == f"{BASE}/attachments/{first['attachments'][0]['id']}"
        assert detail["image_count"] == 2 and detail["message_count"] == 2
        assert detail["can_reply"] and detail["can_resolve"] and detail["reporter"]["username"] == user.username
        rows = (await db_session.execute(select(SupportTicketAttachment))).scalars().all()
        assert len(rows) == 2 and all(r.storage_key in storage for r in rows)
        assert all(r.storage_key.startswith(f"tickets/{user.id}/") for r in rows)
        ticket = await fresh(db_session, detail["id"])
        saved = json.loads(ticket.context_json)
        assert saved["browser"] == "Firefox" and saved["page"] == "/app/chat"
        assert saved["app_version"]  # the running version, or "unknown"

    async def test_context_is_optional_and_a_sent_version_is_kept(self, client, db_session, user):
        headers = sign_in(client, user)
        plain = (await open_ticket(client, headers)).json()
        assert (await fresh(db_session, plain["id"])).context_json is None
        sent = (await open_ticket(client, headers, context=json.dumps({"app_version": "9.9"}))).json()
        assert json.loads((await fresh(db_session, sent["id"])).context_json)["app_version"] == "9.9"

    @pytest.mark.parametrize(
        ("fields", "code"),
        [
            ({"title": "  "}, "invalid_title"),
            ({"title": "x" * 151}, "invalid_title"),
            ({"description": ""}, "invalid_description"),
            ({"description": "x" * 5001}, "invalid_description"),
            ({"category": "Billing"}, "invalid_category"),
            ({"priority": "critical"}, "invalid_priority"),
            ({"context": "{not json"}, "invalid_context"),
            ({"context": "[1, 2]"}, "invalid_context"),
        ],
    )
    async def test_the_form_is_checked(self, client, db_session, user, fields, code):
        headers = sign_in(client, user)
        resp = await open_ticket(client, headers, **fields)
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == code, resp.text
        assert resp.json()["detail"]["message"]
        assert (await db_session.execute(select(func.count()).select_from(SupportTicket))).scalar_one() == 0

    async def test_a_refused_image_names_the_file_and_stores_nothing(self, client, db_session, user, storage):
        headers = sign_in(client, user)
        resp = await client.post(
            f"{BASE}/tickets",
            data={"title": "T", "description": "D", "category": "Bug"},
            files=[("images", ("ok.png", png(), "image/png")), ("images", ("evil.svg", b"<svg/>", "image/svg+xml"))],
            headers=headers,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "image_rejected" and resp.json()["detail"]["file"] == "evil.svg"
        assert storage == {}
        assert (await db_session.execute(select(func.count()).select_from(SupportTicket))).scalar_one() == 0

    async def test_too_large_and_too_many_images(self, client, db_session, user):
        await configure(db_session, max_image_mb=1, max_images=2)
        headers = sign_in(client, user)
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (1024 * 1024 + 10)
        resp = await open_ticket(client, headers, images=[("big.png", big)])
        assert resp.status_code == 413 and resp.json()["detail"]["file"] == "big.png"
        resp = await open_ticket(client, headers, images=[(f"{n}.png", png()) for n in range(3)])
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "too_many_images"

    async def test_a_ticket_refused_after_its_images_were_stored_leaves_none_behind(
        self, client, db_session, user, storage
    ):
        headers = sign_in(client, user)
        resp = await open_ticket(client, headers, images=[("a.png", png())], category="Nope")
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_category"
        assert storage == {}

    async def test_rate_limit_and_most_open(self, client, db_session, user):
        await configure(db_session, per_hour=2, max_open=5)
        headers = sign_in(client, user)
        for _ in range(2):
            assert (await open_ticket(client, headers)).status_code == 201
        resp = await open_ticket(client, headers)
        assert resp.status_code == 429 and resp.json()["detail"]["code"] == "ticket_rate_limited"

        await configure(db_session, per_hour=100, max_open=2)
        resp = await open_ticket(client, headers)
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "too_many_open"

    async def test_new_ticket_email_goes_out_after_the_commit(self, client, db_session, user, outbox):
        await configure(db_session, notify_emails=["ops@corp.test"])
        headers = sign_in(client, user)
        detail = (await open_ticket(client, headers, priority="high")).json()
        await mail.drain()
        assert [m["subject"] for m in outbox] == [f"New ticket #{detail['number']} (High): Export fails"]

    @pytest.mark.parametrize(
        ("changes", "emailed"),
        [
            ({"email_user": True}, True),
            ({"email_user": True, "auto_reply_enabled": False}, False),
            ({"email_user": False}, False),
        ],
    )
    async def test_the_automatic_reply_is_emailed_to_the_person_when_that_is_on(
        self, client, db_session, outbox, changes, emailed
    ):
        sara = await person(db_session, "sara", email="sara@corp.test")
        await configure(db_session, **changes)
        detail = (await open_ticket(client, sign_in(client, sara))).json()
        await mail.drain()
        mine = [m for m in outbox if m["to"] == "sara@corp.test"]
        if emailed:
            assert [m["subject"] for m in mine] == [f"We have your ticket #{detail['number']}"]
            assert "We answer within one working day" in mine[0]["body"]
        else:
            assert mine == []

    async def test_without_csrf_a_multipart_post_is_refused(self, client, db_session, user):
        sign_in(client, user)
        resp = await client.post(
            f"{BASE}/tickets",
            data={"title": "T", "description": "D", "category": "Bug"},
            files=[("images", ("a.png", png(), "image/png"))],
        )
        assert resp.status_code == 403 and resp.json()["detail"] == "CSRF validation failed"


class TestList:
    async def test_filters_counts_search_and_order(self, client, db_session, user, admin):
        headers = sign_in(client, user)
        first = (await open_ticket(client, headers, title="Export fails")).json()
        second = (await open_ticket(client, headers, title="Login loop", description="Keeps asking for 50%_off")).json()
        third = (await open_ticket(client, headers, title="Slow page")).json()
        ticket = await fresh(db_session, third["id"])
        await st.user_resolve(db_session, ticket=ticket, user=await db_session.get(User, user.id))
        await db_session.commit()
        # Someone else's ticket never shows.
        other = await person(db_session, "other")
        await st.create_ticket(
            db_session,
            user=other,
            title="Export fails too",
            description="x",
            category="Bug",
            priority="normal",
            context=None,
            images=[],
            settings=st.TicketSettings(),
        )
        await db_session.commit()

        listing = (await client.get(f"{BASE}/tickets", headers=headers)).json()
        assert [t["id"] for t in listing["items"]] == [second["id"], first["id"]]
        assert listing["counts"] == {"open": 2, "resolved": 1, "all": 3}
        item = listing["items"][0]
        assert set(item) == {
            "id",
            "number",
            "title",
            "category",
            "priority",
            "status",
            "user_unread",
            "created_at",
            "updated_at",
            "message_count",
            "image_count",
            "reopen_until",
        }
        assert item["message_count"] == 2 and item["created_at"].endswith("Z")

        resolved = (await client.get(f"{BASE}/tickets?state=resolved", headers=headers)).json()
        assert [t["id"] for t in resolved["items"]] == [third["id"]] and resolved["items"][0]["reopen_until"]
        everything = (await client.get(f"{BASE}/tickets?state=all", headers=headers)).json()
        assert len(everything["items"]) == 3

        search = (await client.get(f"{BASE}/tickets", params={"state": "all", "q": "export"}, headers=headers)).json()
        assert [t["id"] for t in search["items"]] == [first["id"]]
        assert search["counts"] == {"open": 1, "resolved": 0, "all": 1}
        by_text = (await client.get(f"{BASE}/tickets", params={"state": "all", "q": "50%_"}, headers=headers)).json()
        assert [t["id"] for t in by_text["items"]] == [second["id"]]
        wildcard = (await client.get(f"{BASE}/tickets", params={"state": "all", "q": "%"}, headers=headers)).json()
        assert [t["id"] for t in wildcard["items"]] == [second["id"]]
        for q in (f"#{third['number']}", str(third["number"])):
            found = (await client.get(f"{BASE}/tickets", params={"state": "all", "q": q}, headers=headers)).json()
            assert [t["id"] for t in found["items"]] == [third["id"]], q

    async def test_staff_text_and_notes_are_not_searched_or_counted(self, client, db_session, user, admin):
        headers = sign_in(client, user)
        detail = (await open_ticket(client, headers)).json()
        await staff_reply(db_session, detail["id"], admin, body="secret-note-word", internal=True)
        found = (await client.get(f"{BASE}/tickets", params={"q": "secret-note-word"}, headers=headers)).json()
        assert found["items"] == []
        listing = (await client.get(f"{BASE}/tickets", headers=headers)).json()
        assert listing["items"][0]["message_count"] == 2

    async def test_a_bad_state_is_refused(self, client, user):
        headers = sign_in(client, user)
        assert (await client.get(f"{BASE}/tickets?state=closed", headers=headers)).status_code == 422


class TestDetail:
    async def test_opening_clears_unread_and_hides_notes(self, client, db_session, user, admin, storage):
        headers = sign_in(client, user)
        detail = (await open_ticket(client, headers)).json()
        note_image = st.StoredImage("tickets/x/note.png", "image/png", 3, 1, 1, "00" * 32, "note.png")
        storage["tickets/x/note.png"] = b"png"
        await staff_reply(db_session, detail["id"], admin, body="internal only", internal=True, images=[note_image])
        await staff_reply(db_session, detail["id"], admin, body="Fixed, try now.", status="waiting")
        assert (await client.get(f"{BASE}/unread", headers=headers)).json() == {"count": 1}
        assert (await client.get(f"{BASE}/status", headers=headers)).json()["unread"] == 1

        body = (await client.get(f"{BASE}/tickets/{detail['id']}", headers=headers)).json()
        assert body["user_unread"] is False and body["status"] == "waiting" and body["auto_close_at"]
        kinds = [m["kind"] for m in body["messages"]]
        assert "note" not in kinds and all(not m["internal"] for m in body["messages"])
        assert "internal only" not in json.dumps(body)
        staff = next(m for m in body["messages"] if m["kind"] == "staff")
        assert staff["author_label"] == "Administrator"
        assert body["image_count"] == 0
        assert (await client.get(f"{BASE}/unread", headers=headers)).json() == {"count": 0}
        assert (await fresh(db_session, detail["id"])).user_unread is False

    async def test_someone_elses_ticket_is_not_found(self, client, db_session, user):
        owner = await person(db_session, "owner")
        detail = (await open_ticket(client, sign_in(client, owner))).json()
        headers = sign_in(client, user)
        tid = detail["id"]
        assert (await client.get(f"{BASE}/tickets/{tid}", headers=headers)).status_code == 404
        resp = await client.post(f"{BASE}/tickets/{tid}/messages", data={"body": "hi"}, headers=headers)
        assert resp.status_code == 404 and resp.json()["detail"]["code"] == "not_found"
        assert (await client.post(f"{BASE}/tickets/{tid}/resolve", headers=headers)).status_code == 404
        assert (await client.get(f"{BASE}/tickets/999999", headers=headers)).status_code == 404


class TestReplyAndResolve:
    async def test_reply_hands_it_back_and_emails_staff(self, client, db_session, user, admin, outbox):
        await configure(db_session, notify_emails=["ops@corp.test"])
        headers = sign_in(client, user)
        detail = (await open_ticket(client, headers)).json()
        await staff_reply(db_session, detail["id"], admin, status="waiting")
        await mail.drain()
        outbox.clear()
        resp = await client.post(
            f"{BASE}/tickets/{detail['id']}/messages",
            data={"body": "Still broken."},
            files=[("images", ("again.png", png(), "image/png"))],
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "open" and body["messages"][-1]["body"] == "Still broken."
        assert body["messages"][-1]["attachments"][0]["display_name"] == "again.png"
        assert (await fresh(db_session, detail["id"])).needs_staff is True
        await mail.drain()
        assert [m["subject"] for m in outbox] == [f"Reply on ticket #{detail['number']}: Export fails"]

    async def test_an_empty_reply_is_refused(self, client, user):
        headers = sign_in(client, user)
        detail = (await open_ticket(client, headers)).json()
        resp = await client.post(f"{BASE}/tickets/{detail['id']}/messages", data={"body": " "}, headers=headers)
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_body"

    async def test_resolve_then_reopen_within_the_window_then_409_after(self, client, db_session, user, storage):
        headers = sign_in(client, user)
        detail = (await open_ticket(client, headers)).json()
        tid = detail["id"]
        resolved = (await client.post(f"{BASE}/tickets/{tid}/resolve", headers=headers)).json()
        assert resolved["status"] == "resolved" and resolved["can_resolve"] is False and resolved["can_reply"]
        assert resolved["reopen_until"] and "marked it resolved" in resolved["messages"][-1]["body"]
        again = await client.post(f"{BASE}/tickets/{tid}/resolve", headers=headers)
        assert again.status_code == 409 and again.json()["detail"]["code"] == "not_active"

        reopened = (await client.post(f"{BASE}/tickets/{tid}/messages", data={"body": "Back."}, headers=headers)).json()
        assert reopened["status"] == "open" and reopened["messages"][-1]["body"].startswith("Reopened by")
        assert (await fresh(db_session, tid)).reopened_count == 1

        await client.post(f"{BASE}/tickets/{tid}/resolve", headers=headers)
        ticket = await fresh(db_session, tid)
        ticket.resolved_at = datetime.datetime.utcnow() - datetime.timedelta(days=15)
        await db_session.commit()
        late = await client.post(
            f"{BASE}/tickets/{tid}/messages",
            data={"body": "Late."},
            files=[("images", ("late.png", png(), "image/png"))],
            headers=headers,
        )
        assert late.status_code == 409 and late.json()["detail"]["code"] == "reopen_window_passed"
        assert len(storage) == 0  # the refused reply's image did not stay behind
        detail = (await client.get(f"{BASE}/tickets/{tid}", headers=headers)).json()
        assert detail["can_reply"] is False and detail["can_resolve"] is False


class TestAttachments:
    async def _ticket_with_image(self, client, owner):
        headers = sign_in(client, owner)
        detail = (await open_ticket(client, headers, images=[("shot.png", png())])).json()
        return detail, detail["messages"][0]["attachments"][0]

    async def test_owner_sees_it_with_safe_headers(self, client, user):
        _detail, attachment = await self._ticket_with_image(client, user)
        resp = await client.get(attachment["url"], headers=sign_in(client, user))
        assert resp.status_code == 200 and resp.content.startswith(b"\x89PNG")
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["cache-control"] == "private, max-age=3600"
        assert resp.headers["content-disposition"] == "inline"

    async def test_another_person_gets_404_and_staff_get_it(self, client, db_session, user, admin):
        _detail, attachment = await self._ticket_with_image(client, user)
        stranger = await person(db_session, "stranger")
        resp = await client.get(attachment["url"], headers=sign_in(client, stranger))
        assert resp.status_code == 404
        assert (await client.get(f"{BASE}/attachments/999999", headers=sign_in(client, stranger))).status_code == 404
        for account in (
            admin,
            await person(db_session, "agent", roles=[SUPPORT_SLUG]),
            await person(db_session, "auditor", roles=[READ_ONLY_SUPER_ADMIN_SLUG]),
        ):
            assert (await client.get(attachment["url"], headers=sign_in(client, account))).status_code == 200
        inactive_agent = await person(db_session, "gone_agent", roles=[SUPPORT_SLUG], active=False)
        assert (await client.get(attachment["url"], headers=sign_in(client, inactive_agent))).status_code == 404

    async def test_a_note_image_is_hidden_from_the_owner(self, client, db_session, user, admin, storage):
        detail, _attachment = await self._ticket_with_image(client, user)
        storage["tickets/x/note.png"] = png()
        note_image = st.StoredImage("tickets/x/note.png", "image/png", 3, 1, 1, "00" * 32, "note.png")
        await staff_reply(db_session, detail["id"], admin, body="note", internal=True, images=[note_image])
        row = (
            await db_session.execute(
                select(SupportTicketAttachment).where(SupportTicketAttachment.storage_key == "tickets/x/note.png")
            )
        ).scalar_one()
        assert (await client.get(f"{BASE}/attachments/{row.id}", headers=sign_in(client, user))).status_code == 404
        assert (await client.get(f"{BASE}/attachments/{row.id}", headers=sign_in(client, admin))).status_code == 200


class TestDisabled:
    async def test_everything_but_status_is_refused(self, client, db_session, user, admin):
        headers = sign_in(client, user)
        detail, attachment = await TestAttachments()._ticket_with_image(client, user)
        await configure(db_session, enabled=False)
        status = (await client.get(f"{BASE}/status", headers=headers)).json()
        assert status["enabled"] is False and status["unread"] == 0
        assert (await client.get(f"{BASE}/unread", headers=headers)).json() == {"count": 0}
        tid = detail["id"]
        for method, path, kwargs in (
            ("GET", "/tickets", {}),
            ("GET", f"/tickets/{tid}", {}),
            ("POST", "/tickets", {"data": {"title": "T", "description": "D", "category": "Bug"}}),
            ("POST", f"/tickets/{tid}/messages", {"data": {"body": "hi"}}),
            ("POST", f"/tickets/{tid}/resolve", {}),
            ("GET", f"/attachments/{attachment['id']}", {}),
        ):
            resp = await client.request(method, BASE + path, headers=headers, **kwargs)
            assert resp.status_code == 403 and resp.json()["detail"]["code"] == "tickets_disabled", path
        # Staff keep seeing the images of the queue.
        assert (await client.get(attachment["url"], headers=sign_in(client, admin))).status_code == 200


class TestInactiveAccount:
    async def test_reads_but_cannot_write(self, client, db_session, user, storage):
        headers = sign_in(client, user)
        detail = (await open_ticket(client, headers)).json()
        row = await db_session.get(User, user.id, populate_existing=True)
        row.is_active = False
        await db_session.commit()
        assert (await client.get(f"{BASE}/tickets", headers=headers)).status_code == 200
        body = (await client.get(f"{BASE}/tickets/{detail['id']}", headers=headers)).json()
        assert body["can_reply"] is False and body["can_resolve"] is False
        for resp in (
            await open_ticket(client, headers, images=[("a.png", png())]),
            await client.post(f"{BASE}/tickets/{detail['id']}/messages", data={"body": "hi"}, headers=headers),
            await client.post(f"{BASE}/tickets/{detail['id']}/resolve", headers=headers),
        ):
            assert resp.status_code == 403 and resp.json()["detail"]["code"] == "account_inactive"
        assert storage == {}
        count = (await db_session.execute(select(func.count()).select_from(SupportTicketMessage))).scalar_one()
        assert count == 2


class TestCheapRefusalsComeFirst:
    """What needs no image is refused before any upload is decoded, scanned or stored."""

    @pytest.fixture
    def image_work(self, monkeypatch):
        calls: list[int] = []

        async def counting_store(uploads, settings, *, owner_user_id):
            calls.append(len(uploads))
            return []

        monkeypatch.setattr("app.api.support_tickets.store_ticket_images", counting_store)
        return calls

    async def test_a_new_ticket(self, client, db_session, user, image_work):
        await configure(db_session, per_hour=1, max_open=5)
        headers = sign_in(client, user)
        shot = [("a.png", png())]
        resp = await open_ticket(client, headers, images=shot, category="Nope")
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_category"
        resp = await open_ticket(client, headers, images=shot, title=" ")
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_title"
        assert image_work == []
        assert (await open_ticket(client, headers, images=shot)).status_code == 201
        assert image_work == [1]
        resp = await open_ticket(client, headers, images=shot)
        assert resp.status_code == 429 and resp.json()["detail"]["code"] == "ticket_rate_limited"
        await configure(db_session, per_hour=100, max_open=1)
        resp = await open_ticket(client, headers, images=shot)
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "too_many_open"
        assert image_work == [1]

    async def test_a_reply(self, client, db_session, user, image_work, monkeypatch):
        headers = sign_in(client, user)
        tid = (await open_ticket(client, headers)).json()["id"]
        shot = [("images", ("a.png", png(), "image/png"))]
        resp = await client.post(f"{BASE}/tickets/{tid}/messages", data={"body": " "}, files=shot, headers=headers)
        assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_body"
        other = await person(db_session, "other")
        theirs = await client.post(
            f"{BASE}/tickets/{tid}/messages", data={"body": "x"}, files=shot, headers=sign_in(client, other)
        )
        assert theirs.status_code == 404
        headers = sign_in(client, user)
        ticket = await fresh(db_session, tid)
        ticket.status, ticket.closed_at = "closed", datetime.datetime.utcnow() - datetime.timedelta(days=30)
        await db_session.commit()
        late = await client.post(f"{BASE}/tickets/{tid}/messages", data={"body": "x"}, files=shot, headers=headers)
        assert late.status_code == 409 and late.json()["detail"]["code"] == "reopen_window_passed"
        assert image_work == []

        ticket = await fresh(db_session, tid)
        ticket.status, ticket.closed_at = "open", None
        await db_session.commit()
        monkeypatch.setattr(st, "REPLIES_PER_HOUR", 1)
        ok = await client.post(f"{BASE}/tickets/{tid}/messages", data={"body": "x"}, files=shot, headers=headers)
        assert ok.status_code == 200 and image_work == [1]
        limited = await client.post(f"{BASE}/tickets/{tid}/messages", data={"body": "x"}, files=shot, headers=headers)
        assert limited.status_code == 429 and limited.json()["detail"]["code"] == "reply_rate_limited"
        assert image_work == [1]


async def test_a_ticket_closed_while_the_images_were_checked_is_reopened_cleanly(
    client, db_session, session_factory, user, monkeypatch
):
    """The reply reads the ticket again (locked) after the image work, so it sees the scheduled close."""
    headers = sign_in(client, user)
    tid = (await open_ticket(client, headers)).json()["id"]
    ticket = await fresh(db_session, tid)
    ticket.status, ticket.waiting_since = "waiting", datetime.datetime.utcnow() - datetime.timedelta(days=8)
    await db_session.commit()

    async def close_meanwhile(uploads, settings, *, owner_user_id):
        async with session_factory() as job:
            assert await st.close_waiting_tickets(job) == [tid]
        return []

    monkeypatch.setattr("app.api.support_tickets.store_ticket_images", close_meanwhile)
    resp = await client.post(
        f"{BASE}/tickets/{tid}/messages",
        data={"body": "Still broken"},
        files=[("images", ("a.png", png(), "image/png"))],
        headers=headers,
    )
    assert resp.status_code == 200
    ticket = await fresh(db_session, tid)
    assert (ticket.status, ticket.closed_at, ticket.closed_reason, ticket.reopened_count) == ("open", None, None, 1)
    assert resp.json()["messages"][-1]["body"].startswith("Reopened by")
