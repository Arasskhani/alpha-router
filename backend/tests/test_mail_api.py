"""Connections (user API, /api/mail): connect, mailboxes, action items and drafts, against a fake Exchange.

The fake (``tests/fake_mail_client.py``) follows the client's promises: a
wrong password raises ``auth``, a mailbox without Full Access raises
``access_denied``, a draft sent with an old change key raises ``conflict``,
and ``calls`` records every call, so a test can tell nothing was retried.
"""

from __future__ import annotations

import datetime
import json
import re

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.mail_connection import (
    MailActionItem,
    MailConnection,
    MailConnectionMailbox,
    MailDraft,
    MailItemRef,
)
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services import exchange_mail as em
from app.services import exchange_mail_service as svc
from app.services import rate_limit
from app.services.exchange_ews_types import Address, EwsConfig, EwsError
from tests.fake_mail_client import FakeExchange, install

CSRF = "csrf-token"
BASE = "/api/mail"
PASSWORD = "Secret-1"
OWN = "s.karimi@corp.example"
LOGIN = "CORP\\s.karimi"
ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _no_redis():
    raise ConnectionError("no redis in tests")


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr(rate_limit, "get_redis", _no_redis)
    # The in-memory limiter is process-wide: no test may inherit another's counts.
    rate_limit._buckets.clear()
    yield
    rate_limit._buckets.clear()


@pytest.fixture
def exchange(monkeypatch) -> FakeExchange:
    fake = FakeExchange()
    fake.add_account(
        LOGIN,
        PASSWORD,
        OWN,
        "Sara Karimi",
        full_access=("finance@corp.example", "hr@corp.example"),
        automapped=("finance@corp.example",),
        send_as=("finance@corp.example",),
    )
    fake.add_mailbox("finance@corp.example", "Finance")
    fake.add_mailbox("hr@corp.example", "HR")
    fake.add_mailbox("ceo@corp.example", "CEO")
    fake.add_account("CORP\\a.rad", "Other-2", "a.rad@corp.example", "Ali Rad")
    return install(monkeypatch, fake)


async def _turn_on(db, **overrides) -> em.ExchangeSettings:
    settings = em.ExchangeSettings(
        enabled=True, ews_url="https://mail.corp.example/EWS/Exchange.asmx", netbios_domain="CORP"
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    await em.save_settings(db, settings)
    await db.commit()
    return settings


@pytest.fixture
async def person(db_session) -> User:
    row = User(username="s.karimi", email=OWN, auth_provider="ldap", is_active=True, display_name="Sara Karimi")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def other(db_session) -> User:
    row = User(username="a.rad", email="a.rad@corp.example", auth_provider="ldap", is_active=True)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _fresh(db, model, *where):
    query = select(model).where(*where).execution_options(populate_existing=True)
    return list((await db.execute(query)).scalars().all())


async def _count(db, model, *where) -> int:
    return int((await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


async def _events(db, action: str | None = None) -> list[SecurityAuditEvent]:
    query = select(SecurityAuditEvent).order_by(SecurityAuditEvent.id)
    if action:
        query = query.where(SecurityAuditEvent.action == action)
    return list((await db.execute(query.execution_options(populate_existing=True))).scalars().all())


def _code(resp) -> str:
    return resp.json()["detail"]["code"]


async def _connected(client, db, headers, **settings) -> dict:
    await _turn_on(db, **settings)
    resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _calls(exchange: FakeExchange, method: str) -> int:
    return sum(1 for name, _ in exchange.calls if name == method)


# --- status and eligibility ---------------------------------------------------------------------------------------


class TestStatus:
    async def test_not_turned_on_says_why(self, client, db_session, person):
        headers = sign_in(client, person)
        resp = await client.get(f"{BASE}/status", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["eligible"] is False
        assert body["reason"] == "feature_off"
        assert body["message"]
        assert body["connection"] is None
        assert body["pending_actions"] == 0

    async def test_eligible_person_sees_login_and_capabilities(self, client, db_session, person):
        await _turn_on(db_session, allow_manual_mailboxes=False, max_mailboxes=4)
        headers = sign_in(client, person)
        body = (await client.get(f"{BASE}/status", headers=headers)).json()
        assert body["eligible"] is True and body["reason"] == "" and body["message"] == ""
        assert body["login"] == LOGIN
        assert body["email"] == OWN
        assert body["capabilities"] == {
            "full_access": True,
            "manual_mailboxes": False,
            "drafts": True,
            "send": True,
            "free_time": True,
            "notifications": True,
            "max_mailboxes": 4,
        }

    @pytest.mark.parametrize(
        ("changes", "reason"),
        [
            ({"auth_provider": "local"}, "not_ad"),
            ({"email": None}, "no_email"),
        ],
    )
    async def test_who_may_not_connect(self, client, db_session, exchange, person, changes, reason):
        for key, value in changes.items():
            setattr(person, key, value)
        await db_session.commit()
        await _turn_on(db_session)
        headers = sign_in(client, person)
        body = (await client.get(f"{BASE}/status", headers=headers)).json()
        assert (body["eligible"], body["reason"]) == (False, reason)
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        assert resp.status_code == 403 and _code(resp) == "not_eligible"
        assert resp.json()["detail"]["message"] == body["message"]
        assert exchange.calls == []

    async def test_the_access_list_can_refuse(self, client, db_session, exchange, person, other):
        from app.services.chat_tool_access_service import set_chat_tool_access
        from app.services.resource_access_service import AccessGrant

        await _turn_on(db_session)
        await set_chat_tool_access(
            db_session, em.TOOL_KEY, access_type="private", grants=[AccessGrant(target_type="user", target=other.id)]
        )
        await db_session.commit()
        headers = sign_in(client, person)
        assert (await client.get(f"{BASE}/status", headers=headers)).json()["reason"] == "not_permitted"
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        assert resp.status_code == 403 and _code(resp) == "not_eligible"

    async def test_feature_off_refuses_everything_but_status_and_disconnect(self, client, db_session, exchange, person):
        await _connected(client, db_session, sign_in(client, person))
        await _turn_on(db_session, enabled=False)
        headers = sign_in(client, person)
        assert (await client.get(f"{BASE}/status", headers=headers)).status_code == 200
        for method, path, body in (
            ("post", "/connect", {"password": PASSWORD}),
            ("patch", "/connection", {"notify_enabled": False}),
            ("post", "/mailboxes", {"smtp": "hr@corp.example"}),
            ("post", "/mailboxes/rediscover", None),
            ("get", "/action-items", None),
            ("get", "/drafts/1", None),
        ):
            kwargs = {"headers": headers} if body is None else {"headers": headers, "json": body}
            resp = await getattr(client, method)(f"{BASE}{path}", **kwargs)
            assert resp.status_code == 403, (path, resp.text)
            assert _code(resp) == "not_eligible"
        assert (await client.delete(f"{BASE}/connection", headers=headers)).json() == {"ok": True}
        assert await _count(db_session, MailConnection) == 0

    async def test_no_chat_no_mail(self, client, db_session, exchange, person, monkeypatch):
        from app.services import feature_access_service

        async def no_chat(db, user, feature):
            return feature != "chat"

        monkeypatch.setattr(feature_access_service, "feature_enabled", no_chat)
        await _turn_on(db_session)
        headers = sign_in(client, person)
        assert (await client.get(f"{BASE}/status", headers=headers)).json()["reason"] == "chat_off"
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        assert resp.status_code == 403

    async def test_status_shows_the_connection_and_pending_actions(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        db_session.add_all(
            [
                MailActionItem(user_id=person.id, mailbox_smtp=OWN, item_key=f"k{n}", item_id=f"i{n}", status=status)
                for n, status in enumerate(("new", "notified", "done", "dismissed"))
            ]
        )
        await db_session.commit()
        body = (await client.get(f"{BASE}/status", headers=headers)).json()
        assert body["pending_actions"] == 2
        assert body["connection"]["status"] == "connected"
        assert ZULU.match(body["connection"]["connected_at"])


# --- connecting ---------------------------------------------------------------------------------------------------


class TestConnect:
    async def test_connects_and_lists_the_mailboxes(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        body = await _connected(client, db_session, headers)
        assert body["status"] == "connected"
        assert body["login"] == LOGIN
        assert body["primary_smtp"] == OWN
        assert body["display_name"] == "Sara Karimi"
        assert body["notify_enabled"] is True
        assert body["last_error"] is None
        assert ZULU.match(body["last_ok_at"]) and ZULU.match(body["connected_at"])
        assert body["last_checked_at"] is None
        own, finance = body["mailboxes"]
        assert (own["smtp"], own["kind"], own["source"], own["enabled"], own["notify"]) == (
            OWN,
            "own",
            "own",
            True,
            True,
        )
        assert (finance["smtp"], finance["kind"], finance["source"], finance["enabled"], finance["notify"]) == (
            "finance@corp.example",
            "full_access",
            "autodiscover",
            True,
            False,
        )
        assert finance["display_name"] == "Finance"
        assert set(own) == {
            "id",
            "smtp",
            "display_name",
            "kind",
            "source",
            "enabled",
            "notify",
            "verified_at",
            "last_error",
        }
        assert [name for name, _ in exchange.calls] == ["whoami", "same_mailbox", "discover_full_access"]
        connection = (await _fresh(db_session, MailConnection))[0]
        # The password is stored encrypted, never as typed; the watermark starts a day back.
        assert PASSWORD not in str(connection.secret_encrypted)
        assert em.connection_password(connection) == PASSWORD
        assert connection.poll_watermark is not None
        assert datetime.timedelta(hours=23) < connection.connected_at - connection.poll_watermark
        assert "secret" not in json.dumps(body).lower()

    async def test_the_password_is_never_returned_or_logged(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        body = await _connected(client, db_session, headers)
        assert PASSWORD not in json.dumps(body)
        status = (await client.get(f"{BASE}/status", headers=headers)).text
        assert PASSWORD not in status
        (event,) = await _events(db_session, "mail_connected")
        assert json.loads(event.detail_json) == {"login": LOGIN, "mailbox": OWN, "full_access_count": 1}
        assert PASSWORD not in event.detail_json

    async def test_a_new_password_replaces_the_old(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        exchange.accounts[LOGIN.lower()].password = "Changed-2"
        resp = await client.post(f"{BASE}/connect", json={"password": "Changed-2"}, headers=headers)
        assert resp.status_code == 200
        (connection,) = await _fresh(db_session, MailConnection)
        assert em.connection_password(connection) == "Changed-2"
        assert await _count(db_session, MailConnection) == 1
        (event,) = await _events(db_session, "mail_password_updated")
        assert "Changed-2" not in event.detail_json

    async def test_a_refused_password_stores_nothing_and_is_tried_once(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        headers = sign_in(client, person)
        resp = await client.post(f"{BASE}/connect", json={"password": "wrong"}, headers=headers)
        assert resp.status_code == 400
        assert _code(resp) == "exchange_auth"
        assert await _count(db_session, MailConnection) == 0
        assert await _count(db_session, MailConnectionMailbox) == 0
        # One attempt reached Exchange, and nothing after it: never a retry.
        assert exchange.calls == [("whoami", "")]
        assert await _events(db_session) == []

    async def test_a_refused_password_stops_an_existing_connection(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        exchange.calls.clear()
        resp = await client.post(f"{BASE}/connect", json={"password": "wrong"}, headers=headers)
        assert resp.status_code == 400 and _code(resp) == "exchange_auth"
        (connection,) = await _fresh(db_session, MailConnection)
        assert connection.status == "needs_password"
        # The stored password is kept (it is not used again until replaced); the typed one is not stored.
        assert em.connection_password(connection) == PASSWORD
        assert exchange.calls == [("whoami", "")]
        # Nothing reaches Exchange any more until the person types a password that works.
        resp = await client.post(f"{BASE}/mailboxes/rediscover", headers=headers)
        assert resp.status_code == 409 and _code(resp) == "needs_password"
        assert exchange.calls == [("whoami", "")]
        status = (await client.get(f"{BASE}/status", headers=headers)).json()
        assert status["connection"]["status"] == "needs_password"
        assert status["connection"]["last_error"]
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        assert resp.json()["status"] == "connected"
        assert resp.json()["last_error"] is None

    async def test_another_persons_mailbox_is_refused(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        # The login opens a.rad's mailbox: the password is valid, but not for this account's own mailbox.
        exchange.accounts[LOGIN.lower()].smtp = "a.rad@corp.example"
        headers = sign_in(client, person)
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        assert resp.status_code == 400
        assert _code(resp) == "mailbox_mismatch"
        assert resp.json()["detail"]["message"] == "This password opens another mailbox than yours."
        assert await _count(db_session, MailConnection) == 0

    async def test_the_match_can_be_turned_off(self, client, db_session, exchange, person):
        exchange.accounts[LOGIN.lower()].smtp = "sara@corp.example"
        exchange.add_mailbox("sara@corp.example", "Sara")
        headers = sign_in(client, person)
        body = await _connected(client, db_session, headers, require_mailbox_match=False)
        assert body["primary_smtp"] == "sara@corp.example"
        assert ("same_mailbox", OWN) not in exchange.calls

    async def test_without_full_access_autodiscover_is_not_asked(self, client, db_session, exchange, person):
        body = await _connected(client, db_session, sign_in(client, person), allow_full_access=False)
        assert [m["kind"] for m in body["mailboxes"]] == ["own"]
        assert _calls(exchange, "discover_full_access") == 0

    async def test_autodiscover_is_capped(self, client, db_session, exchange, person):
        exchange.accounts[LOGIN.lower()].automapped = ("finance@corp.example", "hr@corp.example", OWN)
        body = await _connected(client, db_session, sign_in(client, person), max_mailboxes=1)
        assert [m["smtp"] for m in body["mailboxes"]] == [OWN, "finance@corp.example"]

    async def test_exchange_down_is_a_502_and_stores_nothing(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        exchange.fail_with = EwsError("unreachable", "Exchange did not answer.")
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=sign_in(client, person))
        assert resp.status_code == 502 and _code(resp) == "exchange_unreachable"
        assert await _count(db_session, MailConnection) == 0

    async def test_a_password_is_needed(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        resp = await client.post(f"{BASE}/connect", json={"password": ""}, headers=sign_in(client, person))
        assert resp.status_code == 422 and _code(resp) == "invalid_password"
        assert exchange.calls == []

    async def test_no_login_without_a_domain(self, client, db_session, exchange, person):
        await _turn_on(db_session, netbios_domain="")
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=sign_in(client, person))
        assert resp.status_code == 422 and _code(resp) == "no_login"
        assert exchange.calls == []

    async def test_failed_attempts_are_limited(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        headers = sign_in(client, person)
        for _ in range(svc.CONNECT_ATTEMPTS):
            resp = await client.post(f"{BASE}/connect", json={"password": "wrong"}, headers=headers)
            assert resp.status_code == 400
        tried = len(exchange.calls)
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        assert resp.status_code == 429 and _code(resp) == "too_many_attempts"
        # Refused before Exchange: the limit protects the AD account from lockout.
        assert len(exchange.calls) == tried

    async def test_successes_do_not_fill_the_limit(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        headers = sign_in(client, person)
        for _ in range(svc.CONNECT_ATTEMPTS + 2):
            resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
            assert resp.status_code == 200

    async def test_a_changed_login_format_replaces_the_login(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        exchange.add_account(OWN, PASSWORD, OWN, "Sara Karimi")
        await _turn_on(db_session, login_format="email")
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["login"] == OWN


# --- the connection and mailboxes ---------------------------------------------------------------------------------


class TestConnection:
    async def test_notifications_switch(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        resp = await client.patch(f"{BASE}/connection", json={"notify_enabled": False}, headers=headers)
        assert resp.status_code == 200 and resp.json()["notify_enabled"] is False

    async def test_patch_without_a_connection(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        resp = await client.patch(f"{BASE}/connection", json={"notify_enabled": False}, headers=sign_in(client, person))
        assert resp.status_code == 404 and _code(resp) == "not_connected"

    async def test_disconnect_forgets_everything(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        db_session.add(MailActionItem(user_id=person.id, mailbox_smtp=OWN, item_key="k", item_id="i"))
        db_session.add(MailDraft(user_id=person.id, mailbox_smtp=OWN, item_id="d", kind="new"))
        await db_session.commit()
        resp = await client.delete(f"{BASE}/connection", headers=headers)
        assert resp.json() == {"ok": True}
        for model in (MailConnection, MailConnectionMailbox, MailActionItem, MailDraft):
            assert await _count(db_session, model) == 0
        (event,) = await _events(db_session, "mail_disconnected")
        assert json.loads(event.detail_json) == {"by": "self", "mailbox": OWN}
        # Nothing to forget: still ok, and no second row.
        assert (await client.delete(f"{BASE}/connection", headers=headers)).json() == {"ok": True}
        assert len(await _events(db_session, "mail_disconnected")) == 1

    async def test_csrf_is_needed(self, client, db_session, exchange, person):
        sign_in(client, person)
        await _turn_on(db_session)
        resp = await client.post(f"{BASE}/connect", json={"password": PASSWORD})
        assert resp.status_code == 403
        assert exchange.calls == []


class TestMailboxes:
    async def test_add_a_mailbox_by_hand(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        resp = await client.post(f"{BASE}/mailboxes", json={"smtp": " HR@corp.example "}, headers=headers)
        assert resp.status_code == 200, resp.text
        hr = next(m for m in resp.json()["mailboxes"] if m["smtp"] == "hr@corp.example")
        assert (hr["kind"], hr["source"], hr["enabled"], hr["notify"]) == ("full_access", "manual", True, False)
        assert ZULU.match(hr["verified_at"])
        assert ("check_mailbox", "hr@corp.example") in exchange.calls
        (event,) = await _events(db_session, "mail_mailbox_added")
        assert json.loads(event.detail_json)["mailbox"] == "hr@corp.example"

    @pytest.mark.parametrize(
        ("smtp", "status", "code"),
        [
            ("not an address", 422, "invalid_address"),
            ("finance@corp.example", 409, "already_added"),
            (OWN, 409, "already_added"),
            ("ceo@corp.example", 403, "exchange_access_denied"),
            ("nobody@corp.example", 404, "exchange_not_found"),
        ],
    )
    async def test_add_refusals(self, client, db_session, exchange, person, smtp, status, code):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        resp = await client.post(f"{BASE}/mailboxes", json={"smtp": smtp}, headers=headers)
        assert resp.status_code == status and _code(resp) == code
        (connection,) = await _fresh(db_session, MailConnection)
        # A mailbox the login cannot open says nothing about the connection itself.
        assert connection.status == "connected" and connection.consecutive_failures == 0

    async def test_add_is_capped(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers, max_mailboxes=1)
        resp = await client.post(f"{BASE}/mailboxes", json={"smtp": "hr@corp.example"}, headers=headers)
        assert resp.status_code == 422 and _code(resp) == "too_many_mailboxes"

    async def test_add_needs_both_switches(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers, allow_manual_mailboxes=False)
        resp = await client.post(f"{BASE}/mailboxes", json={"smtp": "hr@corp.example"}, headers=headers)
        assert resp.status_code == 403 and _code(resp) == "manual_mailboxes_off"
        await _turn_on(db_session, allow_full_access=False)
        resp = await client.post(f"{BASE}/mailboxes", json={"smtp": "hr@corp.example"}, headers=headers)
        assert resp.status_code == 403 and _code(resp) == "manual_mailboxes_off"

    async def test_add_with_a_changed_password_stops_the_connection(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        exchange.accounts[LOGIN.lower()].password = "Changed-2"
        exchange.calls.clear()
        resp = await client.post(f"{BASE}/mailboxes", json={"smtp": "hr@corp.example"}, headers=headers)
        assert resp.status_code == 400 and _code(resp) == "exchange_auth"
        (connection,) = await _fresh(db_session, MailConnection)
        assert connection.status == "needs_password"
        assert exchange.calls == [("check_mailbox", "hr@corp.example")]

    async def test_add_without_a_connection(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        resp = await client.post(f"{BASE}/mailboxes", json={"smtp": "hr@corp.example"}, headers=sign_in(client, person))
        assert resp.status_code == 404 and _code(resp) == "not_connected"

    async def test_switch_a_mailbox(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        body = await _connected(client, db_session, headers)
        own, finance = body["mailboxes"]
        resp = await client.patch(
            f"{BASE}/mailboxes/{finance['id']}", json={"enabled": False, "notify": True}, headers=headers
        )
        changed = resp.json()["mailboxes"][1]
        assert (changed["enabled"], changed["notify"]) == (False, True)
        resp = await client.patch(f"{BASE}/mailboxes/{own['id']}", json={"notify": False}, headers=headers)
        assert resp.json()["mailboxes"][0]["notify"] is False
        resp = await client.patch(f"{BASE}/mailboxes/{own['id']}", json={"enabled": False}, headers=headers)
        assert resp.status_code == 422 and _code(resp) == "own_mailbox"
        # Turned off by the person and on again: no need to ask Exchange.
        exchange.calls.clear()
        resp = await client.patch(f"{BASE}/mailboxes/{finance['id']}", json={"enabled": True}, headers=headers)
        assert resp.json()["mailboxes"][1]["enabled"] is True
        assert exchange.calls == []

    async def test_a_dropped_mailbox_is_checked_again_when_turned_on(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        body = await _connected(client, db_session, headers)
        finance_id = body["mailboxes"][1]["id"]
        connection_id = (await _fresh(db_session, MailConnection))[0].id
        await em.record_mailbox_failure(
            db_session, connection_id, "finance@corp.example", EwsError("access_denied", "No access.")
        )
        await db_session.commit()
        exchange.accounts[LOGIN.lower()].full_access = ("hr@corp.example",)
        resp = await client.patch(f"{BASE}/mailboxes/{finance_id}", json={"enabled": True}, headers=headers)
        assert resp.status_code == 403 and _code(resp) == "exchange_access_denied"
        (row,) = await _fresh(db_session, MailConnectionMailbox, MailConnectionMailbox.id == finance_id)
        assert row.enabled is False and row.last_error
        exchange.accounts[LOGIN.lower()].full_access = ("finance@corp.example",)
        resp = await client.patch(f"{BASE}/mailboxes/{finance_id}", json={"enabled": True}, headers=headers)
        finance = resp.json()["mailboxes"][1]
        assert finance["enabled"] is True and finance["last_error"] is None
        assert ("check_mailbox", "finance@corp.example") in exchange.calls

    async def test_remove_a_mailbox(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        body = await _connected(client, db_session, headers)
        own, finance = body["mailboxes"]
        resp = await client.delete(f"{BASE}/mailboxes/{own['id']}", headers=headers)
        assert resp.status_code == 422 and _code(resp) == "own_mailbox"
        resp = await client.delete(f"{BASE}/mailboxes/{finance['id']}", headers=headers)
        assert [m["smtp"] for m in resp.json()["mailboxes"]] == [OWN]
        (event,) = await _events(db_session, "mail_mailbox_removed")
        assert json.loads(event.detail_json) == {"mailbox": "finance@corp.example"}
        resp = await client.delete(f"{BASE}/mailboxes/{finance['id']}", headers=headers)
        assert resp.status_code == 404

    async def test_someone_elses_mailbox_is_not_found(self, client, db_session, exchange, person, other):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        connection = MailConnection(
            user_id=other.id,
            login="CORP\\a.rad",
            secret_encrypted=em.encrypt_password("Other-2"),
            primary_smtp="a.rad@corp.example",
            status="connected",
        )
        db_session.add(connection)
        await db_session.flush()
        box = MailConnectionMailbox(
            connection_id=connection.id, smtp="shared@corp.example", kind="full_access", source="manual"
        )
        db_session.add(box)
        await db_session.commit()
        resp = await client.patch(f"{BASE}/mailboxes/{box.id}", json={"notify": True}, headers=headers)
        assert resp.status_code == 404 and _code(resp) == "not_found"
        resp = await client.delete(f"{BASE}/mailboxes/{box.id}", headers=headers)
        assert resp.status_code == 404
        assert await _count(db_session, MailConnectionMailbox, MailConnectionMailbox.id == box.id) == 1

    async def test_rediscover(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        await client.post(f"{BASE}/mailboxes", json={"smtp": "hr@corp.example"}, headers=headers)
        exchange.add_mailbox("legal@corp.example", "Legal")
        account = exchange.accounts[LOGIN.lower()]
        account.full_access = ("hr@corp.example", "legal@corp.example")
        account.automapped = ("legal@corp.example",)
        resp = await client.post(f"{BASE}/mailboxes/rediscover", headers=headers)
        assert resp.status_code == 200
        boxes = {m["smtp"]: m["source"] for m in resp.json()["mailboxes"]}
        # Finance is no longer listed and goes; Legal is new; HR was added by hand and stays.
        assert boxes == {OWN: "own", "hr@corp.example": "manual", "legal@corp.example": "autodiscover"}

    async def test_an_empty_autodiscover_answer_removes_nothing(self, client, db_session, exchange, person):
        """[] is also what a failed Autodiscover gives: it must not wipe the person's mailboxes and switches."""
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        before = {
            m["smtp"] for m in (await client.get(f"{BASE}/status", headers=headers)).json()["connection"]["mailboxes"]
        }
        assert "finance@corp.example" in before
        exchange.accounts[LOGIN.lower()].automapped = ()
        resp = await client.post(f"{BASE}/mailboxes/rediscover", headers=headers)
        assert resp.status_code == 200
        assert {m["smtp"] for m in resp.json()["mailboxes"]} == before

    async def test_rediscover_needs_full_access(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        await _turn_on(db_session, allow_full_access=False)
        resp = await client.post(f"{BASE}/mailboxes/rediscover", headers=headers)
        assert resp.status_code == 403 and _code(resp) == "full_access_off"

    async def test_a_connection_in_error_is_refused_until_reconnected(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        (connection,) = await _fresh(db_session, MailConnection)
        connection.status = "error"
        connection.last_error = "Exchange did not answer."
        await db_session.commit()
        resp = await client.post(f"{BASE}/mailboxes/rediscover", headers=headers)
        assert resp.status_code == 409 and _code(resp) == "connection_error"


# --- action items -------------------------------------------------------------------------------------------------


async def _item(db, owner, *, status="new", subject="Approve the budget", n=0, **kw) -> MailActionItem:
    item = MailActionItem(
        user_id=owner.id,
        mailbox_smtp=kw.pop("mailbox", OWN),
        item_key=f"key-{owner.id}-{n}",
        item_id=kw.pop("item_id", f"AAMk-{n}"),
        subject=subject,
        sender_name=kw.pop("sender_name", "Boss Person"),
        sender_email=kw.pop("sender_email", "boss@corp.example"),
        received_at=datetime.datetime(2026, 10, 24, 9, 0),
        reason="Asks you to approve",
        action="approve",
        importance="High",
        status=status,
        owa_url="https://mail.corp.example/owa/?ItemID=x",
        created_at=datetime.datetime(2026, 10, 24, 9, 1) + datetime.timedelta(minutes=n),
        **kw,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestActionItems:
    async def test_list_open_and_all(self, client, db_session, exchange, person, other):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        first = await _item(db_session, person, n=1)
        second = await _item(db_session, person, n=2, status="notified")
        await _item(db_session, person, n=3, status="done")
        await _item(db_session, other, n=4)
        resp = await client.get(f"{BASE}/action-items", headers=headers)
        body = resp.json()
        assert body["open_count"] == 2
        assert [i["id"] for i in body["items"]] == [second.id, first.id]
        item = body["items"][1]
        assert item == {
            "id": first.id,
            "mailbox": OWN,
            "subject": "Approve the budget",
            "sender_name": "Boss Person",
            "sender_email": "boss@corp.example",
            "received_at": "2026-10-24T09:00:00Z",
            "reason": "Asks you to approve",
            "action": "approve",
            "importance": "High",
            "status": "new",
            "owa_url": "https://mail.corp.example/owa/?ItemID=x",
            "created_at": "2026-10-24T09:02:00Z",
        }
        body = (await client.get(f"{BASE}/action-items?state=all&limit=2", headers=headers)).json()
        assert len(body["items"]) == 2 and body["open_count"] == 2
        assert (await client.get(f"{BASE}/action-items?state=bogus", headers=headers)).status_code == 422

    async def test_notified_touches_only_own_new_items(self, client, db_session, exchange, person, other):
        headers = sign_in(client, person)
        await _turn_on(db_session)
        mine = await _item(db_session, person, n=1)
        done = await _item(db_session, person, n=2, status="done")
        theirs = await _item(db_session, other, n=3)
        resp = await client.post(
            f"{BASE}/action-items/notified", json={"ids": [mine.id, done.id, theirs.id]}, headers=headers
        )
        assert resp.json() == {"ok": True}
        rows = {row.id: row for row in await _fresh(db_session, MailActionItem)}
        assert rows[mine.id].status == "notified" and rows[mine.id].notified_at is not None
        assert rows[done.id].status == "done"
        assert rows[theirs.id].status == "new"

    async def test_dismiss_and_done(self, client, db_session, exchange, person, other):
        headers = sign_in(client, person)
        await _turn_on(db_session)
        one = await _item(db_session, person, n=1)
        two = await _item(db_session, person, n=2)
        theirs = await _item(db_session, other, n=3)
        resp = await client.post(f"{BASE}/action-items/{one.id}/dismiss", headers=headers)
        assert resp.json()["status"] == "dismissed"
        resp = await client.post(f"{BASE}/action-items/{two.id}/done", headers=headers)
        assert resp.json()["status"] == "done"
        rows = {row.id: row for row in await _fresh(db_session, MailActionItem)}
        assert rows[one.id].closed_at is not None and rows[two.id].closed_at is not None
        for path in (f"{theirs.id}/dismiss", f"{theirs.id}/done", f"{theirs.id}/ask", "999/done"):
            resp = await client.post(f"{BASE}/action-items/{path}", headers=headers)
            assert resp.status_code == 404 and _code(resp) == "not_found"
        assert rows[theirs.id].status == "new"

    async def test_ask_makes_a_ref_and_the_composer_text(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        item = await _item(db_session, person, subject="Budget " + "x" * 300, item_id="AAMk-budget")
        resp = await client.post(f"{BASE}/action-items/{item.id}/ask", headers=headers)
        assert resp.status_code == 200
        prompt = resp.json()["prompt"]
        (ref,) = await _fresh(db_session, MailItemRef)
        assert ref.item_id == "AAMk-budget" and ref.mailbox_smtp == OWN and ref.user_id == person.id
        subject = ("Budget " + "x" * 300)[: svc.ASK_SUBJECT_CHARS]
        assert prompt == f'Help me with this email (ref {ref.ref}): "{subject}" from Boss Person <boss@corp.example>.'

    async def test_ask_needs_a_usable_connection(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _turn_on(db_session)
        item = await _item(db_session, person)
        resp = await client.post(f"{BASE}/action-items/{item.id}/ask", headers=headers)
        assert resp.status_code == 409 and _code(resp) == "not_connected"


# --- drafts -------------------------------------------------------------------------------------------------------


async def _draft(db, exchange, owner, *, mailbox=OWN, kind="new", login=LOGIN, password=PASSWORD, **kw) -> MailDraft:
    """A draft saved in the fake Exchange, and its row, as the chat's mail tools would leave them."""
    client = exchange.client(EwsConfig(ews_url="https://x", login=login, password=password))
    saved = client.create_draft(
        mailbox,
        kind="new",
        body_text=kw.pop("body", "Dear Ali,\n\nThe budget is approved.\n\nSara"),
        to=(Address("ali@corp.example", "Ali"), Address("b@corp.example", "B")),
        cc=(Address("c@corp.example", "C"),),
        subject=kw.pop("subject", "Budget approved"),
    )
    exchange.calls.clear()
    row = MailDraft(
        user_id=owner.id,
        mailbox_smtp=mailbox,
        item_id=saved.item_id,
        change_key=saved.change_key,
        kind=kind,
        subject=saved.subject,
        to_json=json.dumps([{"name": a.name, "email": a.email} for a in saved.to]),
        cc_json=json.dumps([{"name": a.name, "email": a.email} for a in saved.cc]),
        body_preview=svc.preview_of(saved.body_text),
        chat_session_id=kw.pop("chat_session_id", "chat-1"),
        status=kw.pop("status", "draft"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


DRAFT_OUT_KEYS = {
    "id",
    "mailbox",
    "kind",
    "status",
    "subject",
    "to",
    "cc",
    "body_preview",
    "created_at",
    "sent_at",
    "error",
    "chat_session_id",
}


class TestDrafts:
    async def test_read_live(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person)
        # Edited in Outlook since the chat saved it.
        exchange.messages[draft.item_id].subject = "Budget approved (final)"
        exchange.messages[draft.item_id].change_key = "ck2"
        resp = await client.get(f"{BASE}/drafts/{draft.id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == DRAFT_OUT_KEYS | {"body_text", "change_key", "owa_url", "can_send"}
        assert body["subject"] == "Budget approved (final)"
        assert body["change_key"] == "ck2"
        assert body["body_text"].startswith("Dear Ali")
        assert body["can_send"] is True
        assert body["to"] == [{"name": "Ali", "email": "ali@corp.example"}, {"name": "B", "email": "b@corp.example"}]
        assert body["chat_session_id"] == "chat-1"
        assert ZULU.match(body["created_at"]) and body["sent_at"] is None
        assert body["owa_url"].startswith("https://")
        (row,) = await _fresh(db_session, MailDraft)
        assert row.subject == "Budget approved (final)" and row.change_key == "ck2"

    async def test_a_draft_gone_from_outlook_is_discarded(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person)
        del exchange.messages[draft.item_id]
        body = (await client.get(f"{BASE}/drafts/{draft.id}", headers=headers)).json()
        assert set(body) == DRAFT_OUT_KEYS
        assert body["status"] == "discarded"
        assert body["error"] == svc.DRAFT_GONE
        (connection,) = await _fresh(db_session, MailConnection)
        assert connection.status == "connected" and connection.consecutive_failures == 0

    async def test_owner_only(self, client, db_session, exchange, person, other):
        await _turn_on(db_session)
        draft = await _draft(db_session, exchange, person)
        headers = sign_in(client, other)
        exchange.calls.clear()
        assert (await client.get(f"{BASE}/drafts/{draft.id}", headers=headers)).status_code == 404
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 404 and _code(resp) == "not_found"
        assert (await client.post(f"{BASE}/drafts/{draft.id}/discard", headers=headers)).status_code == 404
        assert exchange.calls == []
        assert exchange.sent == []

    async def test_send(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person, subject="Secret merger plans")
        live = (await client.get(f"{BASE}/drafts/{draft.id}", headers=headers)).json()
        resp = await client.post(
            f"{BASE}/drafts/{draft.id}/send", json={"change_key": live["change_key"]}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == DRAFT_OUT_KEYS
        assert body["status"] == "sent" and ZULU.match(body["sent_at"])
        assert [m.subject for m in exchange.sent] == ["Secret merger plans"]
        (event,) = await _events(db_session, "mail_draft_sent")
        assert json.loads(event.detail_json) == {
            "draft_id": draft.id,
            "mailbox": OWN,
            "kind": "new",
            "to_count": 2,
            "cc_count": 1,
        }
        # Sent once: a second press is refused, not sent again.
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 409 and _code(resp) == "not_a_draft"
        assert len(exchange.sent) == 1
        # And reading it now gives the row, without asking Exchange.
        exchange.calls.clear()
        body = (await client.get(f"{BASE}/drafts/{draft.id}", headers=headers)).json()
        assert body["status"] == "sent" and exchange.calls == []

    async def test_send_after_an_edit_in_outlook_is_a_conflict(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person)
        exchange.messages[draft.item_id].change_key = "ck2"
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 409 and _code(resp) == "exchange_conflict"
        (row,) = await _fresh(db_session, MailDraft)
        assert row.status == "draft"
        (connection,) = await _fresh(db_session, MailConnection)
        assert connection.consecutive_failures == 0
        assert exchange.sent == []

    async def test_send_as_refused_marks_the_draft_failed(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        exchange.accounts[LOGIN.lower()].send_as = ()
        draft = await _draft(db_session, exchange, person, mailbox="finance@corp.example")
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 403 and _code(resp) == "exchange_access_denied"
        (row,) = await _fresh(db_session, MailDraft)
        assert row.status == "failed" and row.error
        # Reading the mailbox still works: it does not drop out for a refused send.
        boxes = await _fresh(db_session, MailConnectionMailbox, MailConnectionMailbox.smtp == "finance@corp.example")
        assert boxes[0].enabled is True

    async def test_a_refused_password_on_send_keeps_the_draft(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person)
        exchange.accounts[LOGIN.lower()].password = "Changed-2"
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 400 and _code(resp) == "exchange_auth"
        (row,) = await _fresh(db_session, MailDraft)
        assert row.status == "draft" and row.error
        (connection,) = await _fresh(db_session, MailConnection)
        assert connection.status == "needs_password"
        assert _calls(exchange, "send_draft") == 1
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 409 and _code(resp) == "needs_password"
        assert _calls(exchange, "send_draft") == 1

    async def test_send_off(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers, allow_send=False)
        draft = await _draft(db_session, exchange, person)
        assert (await client.get(f"{BASE}/drafts/{draft.id}", headers=headers)).json()["can_send"] is False
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 403 and _code(resp) == "send_off"
        assert exchange.sent == []

    async def test_sends_are_limited(self, client, db_session, exchange, person, monkeypatch):
        monkeypatch.setattr(svc, "SENDS_PER_HOUR", 2)
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        drafts = [await _draft(db_session, exchange, person, subject=f"D{n}") for n in range(3)]
        for draft in drafts[:2]:
            resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
            assert resp.status_code == 200
        resp = await client.post(f"{BASE}/drafts/{drafts[2].id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 429 and _code(resp) == "too_many_attempts"
        assert len(exchange.sent) == 2

    async def test_a_draft_in_a_mailbox_turned_off_is_refused(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        body = await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person, mailbox="finance@corp.example")
        await client.patch(f"{BASE}/mailboxes/{body['mailboxes'][1]['id']}", json={"enabled": False}, headers=headers)
        resp = await client.get(f"{BASE}/drafts/{draft.id}", headers=headers)
        assert resp.status_code == 403 and _code(resp) == "mailbox_not_allowed"

    async def test_discard(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person)
        resp = await client.post(f"{BASE}/drafts/{draft.id}/discard", headers=headers)
        assert resp.status_code == 200 and resp.json()["status"] == "discarded"
        assert exchange.messages[draft.item_id].folder == "deleted"
        # Again: nothing to do, still discarded.
        resp = await client.post(f"{BASE}/drafts/{draft.id}/discard", headers=headers)
        assert resp.json()["status"] == "discarded"
        resp = await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        assert resp.status_code == 409 and _code(resp) == "not_a_draft"

    async def test_a_sent_draft_cannot_be_discarded(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        draft = await _draft(db_session, exchange, person, status="sent")
        resp = await client.post(f"{BASE}/drafts/{draft.id}/discard", headers=headers)
        assert resp.status_code == 409 and _code(resp) == "not_a_draft"

    async def test_drafts_need_a_connection(self, client, db_session, exchange, person):
        await _turn_on(db_session)
        draft = await _draft(db_session, exchange, person)
        resp = await client.get(f"{BASE}/drafts/{draft.id}", headers=sign_in(client, person))
        assert resp.status_code == 404 and _code(resp) == "not_connected"


# --- Admin Logs and the purge -------------------------------------------------------------------------------------


class TestAuditAndPurge:
    async def test_admin_logs_never_hold_a_secret_a_subject_or_a_recipient(self, client, db_session, exchange, person):
        headers = sign_in(client, person)
        await _connected(client, db_session, headers)
        await client.post(f"{BASE}/connect", json={"password": "wrong-Pass-9"}, headers=headers)
        await client.post(f"{BASE}/connect", json={"password": PASSWORD}, headers=headers)
        await client.post(f"{BASE}/mailboxes", json={"smtp": "hr@corp.example"}, headers=headers)
        draft = await _draft(db_session, exchange, person, subject="Quarterly layoffs list", body="Very private text")
        await client.post(f"{BASE}/drafts/{draft.id}/send", json={"change_key": "ck1"}, headers=headers)
        await client.delete(f"{BASE}/connection", headers=headers)
        events = await _events(db_session)
        assert {e.action for e in events} >= {
            "mail_connected",
            "mail_password_updated",
            "mail_mailbox_added",
            "mail_draft_sent",
            "mail_disconnected",
        }
        trail = " ".join(f"{e.detail_json} {e.resource_id}" for e in events)
        for secret in (PASSWORD, "wrong-Pass-9", "Quarterly layoffs", "Very private", "ali@corp.example", "c@corp"):
            assert secret not in trail

    async def test_the_purge_forgets_the_connection(self, db_session, person, monkeypatch):
        from app.services.user_account_cleanup_service import purge_user_account_data

        monkeypatch.setattr("app.services.object_storage_service.purge_user_cdn_objects", lambda *_a: 0)
        monkeypatch.setattr("app.services.object_storage_service.delete_object", lambda _key: None)
        connection = MailConnection(
            user_id=person.id,
            login=LOGIN,
            secret_encrypted=em.encrypt_password(PASSWORD),
            primary_smtp=OWN,
            status="connected",
        )
        db_session.add(connection)
        await db_session.flush()
        db_session.add(MailConnectionMailbox(connection_id=connection.id, smtp=OWN, kind="own", source="own"))
        db_session.add(MailActionItem(user_id=person.id, mailbox_smtp=OWN, item_key="k", item_id="i"))
        db_session.add(MailDraft(user_id=person.id, mailbox_smtp=OWN, item_id="d", kind="new"))
        await db_session.commit()
        await purge_user_account_data(db_session, user_id=person.id, username=person.username)
        await db_session.commit()
        for model in (MailConnection, MailConnectionMailbox, MailActionItem, MailDraft):
            assert await _count(db_session, model) == 0
