"""Admin › Exchange EWS (/api/admin/exchange-ews): settings, Test connection, access, people and overview."""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.auth_provider import AuthProviderConfig
from app.models.mail_connection import MailActionItem, MailConnection, MailConnectionMailbox, MailDraft
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services import exchange_mail as em
from app.services import exchange_mail_service as svc
from app.services import rate_limit
from app.services.exchange_ews_types import EwsError
from app.services.rbac import READ_ONLY_SUPER_ADMIN_SLUG
from app.services.user_role_service import set_user_roles
from tests.fake_mail_client import FakeExchange, FakeMailClient, install

CSRF = "csrf-token"
BASE = "/api/admin/exchange-ews"
EWS = "https://mail.corp.example/EWS/Exchange.asmx"


def _no_redis():
    raise ConnectionError("no redis in tests")


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr(rate_limit, "get_redis", _no_redis)
    rate_limit._buckets.clear()
    yield
    rate_limit._buckets.clear()


@pytest.fixture
def exchange(monkeypatch) -> FakeExchange:
    fake = FakeExchange()
    fake.add_account(
        "CORP\\it.admin",
        "Admin-Pass-1",
        "it.admin@corp.example",
        "IT Admin",
        full_access=("finance@corp.example", "hr@corp.example"),
    )
    fake.add_mailbox("finance@corp.example", "Finance")
    fake.add_mailbox("hr@corp.example", "HR")
    return install(monkeypatch, fake)


def sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _person(db, username, *, roles=None, provider="ldap", email="", active=True, **kw) -> User:
    row = User(
        username=username,
        email=email if email != "" else f"{username}@corp.example",
        auth_provider=provider,
        is_active=active,
        **kw,
    )
    db.add(row)
    await db.flush()
    if roles:
        await set_user_roles(db, row, roles)
    await db.commit()
    await db.refresh(row)
    return row


async def _turn_on(db, **overrides) -> em.ExchangeSettings:
    settings = em.ExchangeSettings(enabled=True, ews_url=EWS, netbios_domain="CORP")
    for key, value in overrides.items():
        setattr(settings, key, value)
    await em.save_settings(db, settings)
    await db.commit()
    return settings


async def _events(db, action: str | None = None) -> list[SecurityAuditEvent]:
    query = select(SecurityAuditEvent).order_by(SecurityAuditEvent.id)
    if action:
        query = query.where(SecurityAuditEvent.action == action)
    return list((await db.execute(query.execution_options(populate_existing=True))).scalars().all())


async def _count(db, model, *where) -> int:
    return int((await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


def _code(resp) -> str:
    return resp.json()["detail"]["code"]


async def _connection(db, owner, *, status="connected", boxes=(), **kw) -> MailConnection:
    connection = MailConnection(
        user_id=owner.id,
        login=f"CORP\\{owner.username}",
        secret_encrypted=em.encrypt_password("Pass-1"),
        primary_smtp=str(owner.email),
        display_name=owner.display_name,
        status=status,
        **kw,
    )
    db.add(connection)
    await db.flush()
    db.add(MailConnectionMailbox(connection_id=connection.id, smtp=str(owner.email), kind="own", source="own"))
    for smtp in boxes:
        db.add(MailConnectionMailbox(connection_id=connection.id, smtp=smtp, kind="full_access", source="manual"))
    await db.commit()
    await db.refresh(connection)
    return connection


@pytest.fixture
async def read_only(db_session) -> User:
    return await _person(db_session, "auditor", roles=[READ_ONLY_SUPER_ADMIN_SLUG], provider="local")


# --- who may ask ------------------------------------------------------------------------------------------------


class TestPermissions:
    async def test_a_plain_user_may_not_read(self, client, db_session, user):
        headers = sign_in(client, user)
        for path in ("/settings", "/access", "/connections", "/overview"):
            assert (await client.get(f"{BASE}{path}", headers=headers)).status_code == 403

    async def test_read_only_reads_but_changes_nothing(self, client, db_session, exchange, read_only):
        await _turn_on(db_session)
        someone = await _person(db_session, "s.karimi")
        connection = await _connection(db_session, someone)
        headers = sign_in(client, read_only)
        for path in ("/settings", "/access", "/connections", "/overview"):
            assert (await client.get(f"{BASE}{path}", headers=headers)).status_code == 200, path
        current = (await client.get(f"{BASE}/settings", headers=headers)).json()["settings"]
        assert (await client.put(f"{BASE}/settings", json=current, headers=headers)).status_code == 403
        resp = await client.post(f"{BASE}/test", json={"login": "CORP\\it.admin", "password": "x"}, headers=headers)
        assert resp.status_code == 403
        resp = await client.put(f"{BASE}/access", json={"access_type": "private", "grants": []}, headers=headers)
        assert resp.status_code == 403
        assert (await client.delete(f"{BASE}/connections/{connection.id}", headers=headers)).status_code == 403
        assert exchange.calls == []
        assert await _count(db_session, MailConnection) == 1


# --- settings ---------------------------------------------------------------------------------------------------


class TestSettings:
    async def test_defaults_and_the_example_login(self, client, db_session, admin):
        headers = sign_in(client, admin)
        body = (await client.get(f"{BASE}/settings", headers=headers)).json()
        assert body["settings"] == em.ExchangeSettings().as_dict()
        assert body["directory"] == {"netbios_domain": "", "dns_domain": "", "available": False}
        assert body["example_login"] == "DOMAIN\\fixture_admin"
        assert body["ews_endpoint"] == "" and body["autodiscover_endpoint"] == ""

    async def test_the_domain_comes_from_ldap(self, client, db_session, admin):
        db_session.add(
            AuthProviderConfig(
                provider="ldap", enabled=True, config_json=json.dumps({"domain": "corp.example", "base_dn": ""})
            )
        )
        await db_session.commit()
        headers = sign_in(client, admin)
        body = (await client.get(f"{BASE}/settings", headers=headers)).json()
        assert body["directory"]["dns_domain"] == "corp.example"
        assert body["directory"]["available"] is True
        assert body["example_login"] == f"{body['directory']['netbios_domain']}\\fixture_admin"

    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [("netbios", "CORP\\fixture_admin"), ("upn", "fixture_admin@corp.example"), ("email", "fixture_admin@test")],
    )
    async def test_example_login_follows_the_format(self, client, db_session, admin, fmt, expected):
        await _turn_on(db_session, login_format=fmt, upn_suffix="corp.example")
        body = (await client.get(f"{BASE}/settings", headers=sign_in(client, admin))).json()
        assert body["example_login"] == expected

    async def test_save(self, client, db_session, admin):
        headers = sign_in(client, admin)
        current = (await client.get(f"{BASE}/settings", headers=headers)).json()["settings"]
        wanted = {**current, "enabled": True, "ews_url": "https://mail.corp.example", "poll_minutes": 10}
        resp = await client.put(f"{BASE}/settings", json=wanted, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["settings"]["ews_url"] == EWS
        assert body["ews_endpoint"] == EWS
        assert body["autodiscover_endpoint"] == "https://mail.corp.example/autodiscover/autodiscover.xml"
        assert (await em.load_settings(db_session)).poll_minutes == 10
        (event,) = await _events(db_session, "exchange_ews_settings_updated")
        assert json.loads(event.detail_json) == {"changed": ["enabled", "ews_url", "poll_minutes"]}
        # The same again changes nothing and writes no row.
        await client.put(f"{BASE}/settings", json=body["settings"], headers=headers)
        assert len(await _events(db_session, "exchange_ews_settings_updated")) == 1

    async def test_the_ca_text_never_reaches_admin_logs(self, client, db_session, admin):
        from tests.test_exchange_mail_core import _make_ca_pem

        pem = _make_ca_pem()
        headers = sign_in(client, admin)
        current = (await client.get(f"{BASE}/settings", headers=headers)).json()["settings"]
        resp = await client.put(f"{BASE}/settings", json={**current, "ca_bundle_pem": pem}, headers=headers)
        assert resp.status_code == 200
        (event,) = await _events(db_session, "exchange_ews_settings_updated")
        assert json.loads(event.detail_json) == {"changed": ["ca_bundle_pem"]}
        assert "CERTIFICATE" not in event.detail_json

    async def test_invalid_settings(self, client, db_session, admin):
        headers = sign_in(client, admin)
        for change in ({"enabled": True}, {"ews_url": "http://plain.example"}, {"poll_minutes": 1}):
            resp = await client.put(f"{BASE}/settings", json=change, headers=headers)
            assert resp.status_code == 422, change
            assert _code(resp) == "invalid_settings"
            assert resp.json()["detail"]["message"]
        assert await _events(db_session) == []

    async def test_turning_off_deletes_nothing(self, client, db_session, admin):
        await _turn_on(db_session)
        someone = await _person(db_session, "s.karimi")
        await _connection(db_session, someone)
        headers = sign_in(client, admin)
        current = (await client.get(f"{BASE}/settings", headers=headers)).json()["settings"]
        resp = await client.put(f"{BASE}/settings", json={**current, "enabled": False}, headers=headers)
        assert resp.status_code == 200
        assert await _count(db_session, MailConnection) == 1


# --- Test connection --------------------------------------------------------------------------------------------


def _steps(body) -> list[tuple[str, bool]]:
    return [(step["key"], step["ok"]) for step in body["steps"]]


class TestConnectionTest:
    async def test_every_step_passes(self, client, db_session, exchange, admin):
        await _turn_on(db_session, enabled=False)
        headers = sign_in(client, admin)
        resp = await client.post(
            f"{BASE}/test",
            json={"login": "CORP\\it.admin", "password": "Admin-Pass-1", "email": "it.admin@corp.example"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert _steps(body) == [
            ("endpoint", True),
            ("login", True),
            ("mailbox", True),
            ("match", True),
            ("autodiscover", True),
        ]
        assert all(set(step) == {"key", "label", "ok", "detail"} and step["label"] for step in body["steps"])
        assert body["mailbox"] == {"smtp": "it.admin@corp.example", "display_name": "IT Admin"}
        assert body["full_access"] == [
            {"smtp": "finance@corp.example", "display_name": "Finance"},
            {"smtp": "hr@corp.example", "display_name": "HR"},
        ]
        # Nothing is stored, and the trail has the login and the outcome only.
        assert await _count(db_session, MailConnection) == 0
        (event,) = await _events(db_session, "exchange_ews_tested")
        assert json.loads(event.detail_json) == {"login": "CORP\\it.admin", "ok": True}
        assert "Admin-Pass-1" not in event.detail_json

    async def test_without_an_email_there_is_no_match_step(self, client, db_session, exchange, admin):
        await _turn_on(db_session)
        resp = await client.post(
            f"{BASE}/test", json={"login": "CORP\\it.admin", "password": "Admin-Pass-1"}, headers=sign_in(client, admin)
        )
        assert [key for key, _ in _steps(resp.json())] == ["endpoint", "login", "mailbox", "autodiscover"]

    async def test_a_wrong_password_stops_at_login(self, client, db_session, exchange, admin):
        await _turn_on(db_session)
        resp = await client.post(
            f"{BASE}/test",
            json={"login": "CORP\\it.admin", "password": "wrong", "email": "it.admin@corp.example"},
            headers=sign_in(client, admin),
        )
        body = resp.json()
        assert body["ok"] is False
        assert _steps(body) == [("endpoint", True), ("login", False)]
        assert body["steps"][1]["detail"] == "Exchange did not accept the user name or password."
        assert body["mailbox"] is None
        assert exchange.calls == [("whoami", "")]
        (event,) = await _events(db_session, "exchange_ews_tested")
        assert json.loads(event.detail_json) == {"login": "CORP\\it.admin", "ok": False}

    async def test_another_mailbox_fails_the_match(self, client, db_session, exchange, admin):
        await _turn_on(db_session)
        resp = await client.post(
            f"{BASE}/test",
            json={"login": "CORP\\it.admin", "password": "Admin-Pass-1", "email": "finance@corp.example"},
            headers=sign_in(client, admin),
        )
        body = resp.json()
        assert body["ok"] is False
        assert _steps(body)[-1] == ("match", False)
        assert "finance@corp.example" in body["steps"][-1]["detail"]

    async def test_no_address_saved(self, client, db_session, exchange, admin):
        resp = await client.post(
            f"{BASE}/test", json={"login": "CORP\\it.admin", "password": "Admin-Pass-1"}, headers=sign_in(client, admin)
        )
        assert _steps(resp.json()) == [("endpoint", False)]
        assert exchange.calls == []

    async def test_autodiscover_failing_is_only_a_warning(self, client, db_session, exchange, admin, monkeypatch):
        def broken(self):
            raise EwsError("server", "Autodiscover answered with an error.")

        monkeypatch.setattr(FakeMailClient, "discover_full_access", broken)
        await _turn_on(db_session)
        resp = await client.post(
            f"{BASE}/test", json={"login": "CORP\\it.admin", "password": "Admin-Pass-1"}, headers=sign_in(client, admin)
        )
        body = resp.json()
        assert body["ok"] is True
        assert _steps(body)[-1] == ("autodiscover", False)
        assert body["full_access"] == []

    async def test_unreachable(self, client, db_session, exchange, admin):
        await _turn_on(db_session)
        exchange.fail_with = EwsError("unreachable", "Exchange did not answer at mail.corp.example.")
        resp = await client.post(
            f"{BASE}/test", json={"login": "CORP\\it.admin", "password": "Admin-Pass-1"}, headers=sign_in(client, admin)
        )
        body = resp.json()
        assert _steps(body) == [("endpoint", True), ("login", False)]
        assert body["steps"][1]["detail"] == "Exchange did not answer at mail.corp.example."

    async def test_login_and_password_are_needed(self, client, db_session, exchange, admin):
        await _turn_on(db_session)
        headers = sign_in(client, admin)
        for body in ({"login": "", "password": "x"}, {"login": "CORP\\it.admin", "password": ""}):
            resp = await client.post(f"{BASE}/test", json=body, headers=headers)
            assert resp.status_code == 422 and _code(resp) == "invalid_test"
        assert exchange.calls == []

    async def test_tests_are_limited(self, client, db_session, exchange, admin):
        await _turn_on(db_session)
        headers = sign_in(client, admin)
        body = {"login": "CORP\\it.admin", "password": "Admin-Pass-1"}
        for _ in range(svc.TESTS_PER_WINDOW):
            assert (await client.post(f"{BASE}/test", json=body, headers=headers)).status_code == 200
        resp = await client.post(f"{BASE}/test", json=body, headers=headers)
        assert resp.status_code == 429 and _code(resp) == "too_many_attempts"


# --- access -----------------------------------------------------------------------------------------------------


class TestAccess:
    async def test_read_and_replace(self, client, db_session, exchange, admin):
        await _turn_on(db_session)
        allowed = await _person(db_session, "s.karimi")
        refused = await _person(db_session, "a.rad")
        headers = sign_in(client, admin)
        body = (await client.get(f"{BASE}/access", headers=headers)).json()
        assert body["tool_key"] == "exchange_mail" and body["access_type"] == "public" and body["grants"] == []
        resp = await client.put(
            f"{BASE}/access",
            json={"access_type": "private", "grants": [{"target_type": "user", "target": allowed.id}]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        saved = resp.json()
        assert saved["access_type"] == "private"
        assert saved["grants"] == [{"target_type": "user", "target": allowed.id, "effect": "allow"}]
        assert (await client.get(f"{BASE}/access", headers=headers)).json() == saved
        (event,) = await _events(db_session, "chat_tool_access_changed")
        assert (event.resource_type, event.resource_id) == ("chat_tool", "exchange_mail")
        assert json.loads(event.detail_json)["after"]["access_type"] == "private"
        assert (await em.eligibility(db_session, allowed)).allowed
        assert (await em.eligibility(db_session, refused)).reason == "not_permitted"

    async def test_bad_grants_are_refused(self, client, db_session, admin):
        headers = sign_in(client, admin)
        resp = await client.put(f"{BASE}/access", json={"access_type": "secret", "grants": []}, headers=headers)
        assert resp.status_code == 422
        resp = await client.put(
            f"{BASE}/access",
            json={"access_type": "private", "grants": [{"target_type": "user", "target": 999999}]},
            headers=headers,
        )
        assert resp.status_code == 400
        assert await _events(db_session) == []


# --- people and overview ----------------------------------------------------------------------------------------


class TestPeople:
    async def test_list_search_filter_and_page(self, client, db_session, admin):
        sara = await _person(db_session, "s.karimi", display_name="Sara Karimi")
        ali = await _person(db_session, "a.rad", display_name="Ali Rad")
        nima = await _person(db_session, "n.zand", display_name="Nima Zand")
        await _connection(
            db_session,
            sara,
            boxes=("finance@corp.example", "hr@corp.example"),
            connected_at=datetime.datetime(2026, 10, 20, 8, 0),
            last_ok_at=datetime.datetime(2026, 10, 25, 8, 0),
        )
        await _connection(db_session, ali, status="needs_password", connected_at=datetime.datetime(2026, 10, 21))
        await _connection(db_session, nima, status="error", connected_at=datetime.datetime(2026, 10, 22))
        headers = sign_in(client, admin)
        body = (await client.get(f"{BASE}/connections", headers=headers)).json()
        assert body["total"] == 3
        assert [item["username"] for item in body["items"]] == ["n.zand", "a.rad", "s.karimi"]
        row = body["items"][2]
        assert row == {
            "id": row["id"],
            "user_id": sara.id,
            "username": "s.karimi",
            "display_name": "Sara Karimi",
            "email": "s.karimi@corp.example",
            "login": "CORP\\s.karimi",
            "status": "connected",
            "primary_smtp": "s.karimi@corp.example",
            "mailbox_count": 3,
            "full_access_count": 2,
            "notify_enabled": True,
            "last_ok_at": "2026-10-25T08:00:00Z",
            "last_checked_at": None,
            "last_error": None,
            "connected_at": "2026-10-20T08:00:00Z",
        }
        assert "secret" not in json.dumps(body).lower()
        for query, names in (
            ("q=karimi", ["s.karimi"]),
            ("q=ALI", ["a.rad"]),
            ("q=n.zand@corp", ["n.zand"]),
            ("status=needs_password", ["a.rad"]),
            ("limit=1&offset=1", ["a.rad"]),
        ):
            body = (await client.get(f"{BASE}/connections?{query}", headers=headers)).json()
            assert [item["username"] for item in body["items"]] == names, query
        assert (await client.get(f"{BASE}/connections?limit=1", headers=headers)).json()["total"] == 3
        resp = await client.get(f"{BASE}/connections?status=bogus", headers=headers)
        assert resp.status_code == 422 and _code(resp) == "invalid_filter"

    async def test_disconnect_someone(self, client, db_session, admin):
        sara = await _person(db_session, "s.karimi")
        connection = await _connection(db_session, sara, boxes=("finance@corp.example",))
        db_session.add(MailDraft(user_id=sara.id, mailbox_smtp=str(sara.email), item_id="d", kind="new"))
        await db_session.commit()
        headers = sign_in(client, admin)
        resp = await client.delete(f"{BASE}/connections/{connection.id}", headers=headers)
        assert resp.json() == {"ok": True}
        for model in (MailConnection, MailConnectionMailbox, MailDraft):
            assert await _count(db_session, model) == 0
        (event,) = await _events(db_session, "mail_disconnected")
        assert json.loads(event.detail_json) == {"by": "admin", "user_id": sara.id, "mailbox": "s.karimi@corp.example"}
        resp = await client.delete(f"{BASE}/connections/{connection.id}", headers=headers)
        assert resp.status_code == 404 and _code(resp) == "not_found"


class TestOverview:
    async def test_counts(self, client, db_session, admin):
        await _turn_on(db_session)
        sara = await _person(db_session, "s.karimi")
        ali = await _person(db_session, "a.rad")
        nima = await _person(db_session, "n.zand")
        await _person(db_session, "no.mail", email=None)
        await _person(db_session, "gone", active=False)
        await _person(db_session, "local.one", provider="local")
        await _connection(db_session, sara, last_checked_at=datetime.datetime(2026, 10, 25, 7, 0))
        await _connection(
            db_session, ali, status="needs_password", last_checked_at=datetime.datetime(2026, 10, 25, 9, 0)
        )
        await _connection(db_session, nima, status="error")
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        old = now - datetime.timedelta(days=9)
        db_session.add_all(
            [
                MailActionItem(user_id=sara.id, mailbox_smtp="x", item_key="a", item_id="a", created_at=now),
                MailActionItem(user_id=sara.id, mailbox_smtp="x", item_key="b", item_id="b", created_at=old),
                MailDraft(user_id=sara.id, mailbox_smtp="x", item_id="1", kind="new", created_at=now),
                MailDraft(
                    user_id=sara.id,
                    mailbox_smtp="x",
                    item_id="2",
                    kind="new",
                    status="sent",
                    created_at=now,
                    sent_at=now,
                ),
                MailDraft(
                    user_id=sara.id,
                    mailbox_smtp="x",
                    item_id="3",
                    kind="new",
                    status="sent",
                    created_at=old,
                    sent_at=old,
                ),
            ]
        )
        await db_session.commit()
        body = (await client.get(f"{BASE}/overview", headers=sign_in(client, admin))).json()
        assert body == {
            "counts": {"connected": 1, "needs_password": 1, "error": 1},
            "eligible_accounts": 3,
            "action_items_7d": 1,
            "drafts_7d": 2,
            "sent_7d": 1,
            "last_check_at": "2026-10-25T09:00:00Z",
            "enabled": True,
            "configured": True,
        }
