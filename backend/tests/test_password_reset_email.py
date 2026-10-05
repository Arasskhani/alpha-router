"""Resetting a forgotten password by an emailed code.

Only for a local, active account, and only while an administrator allows it.
The new password meets the policy, every session ends, and the person then
signs in with it (a second factor still applies).
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.models.auth_event import AuthEvent
from app.models.security import SecurityAuditEvent
from app.models.system import SmtpSettings
from app.models.user import User
from app.services.email_signup_service import EmailSignupSettings, save_email_signup_settings

OLD = "Old-Pass-2025!"
NEW = "New-Pass-2026!"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    from app.services import rate_limit

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)
    rate_limit._buckets.clear()
    yield
    rate_limit._buckets.clear()


@pytest.fixture
def outbox(monkeypatch) -> list[dict]:
    sent: list[dict] = []

    async def capture(_db, *, to_address, subject, body_text, **_kw):
        sent.append({"to": to_address, "subject": subject, "body": body_text})

    monkeypatch.setattr("app.services.smtp_service.send_email", capture)
    return sent


def _code(outbox: list[dict]) -> str:
    match = re.search(r"\n\s{4}(\d{6})\n", outbox[-1]["body"])
    assert match
    return match.group(1)


def _detail(resp) -> dict:
    return resp.json()["detail"]


async def _turn_on(db, *, reset=True) -> None:
    db.add(SmtpSettings(host="smtp.example.com", port=587, from_address="noreply@example.com"))
    await db.flush()
    await save_email_signup_settings(db, EmailSignupSettings(enabled=False, reset_enabled=reset))
    await db.commit()


@pytest.fixture
async def person(db_session, user) -> User:
    user.email = "fixture_user@example.com"
    user.hashed_password = hash_password(OLD)
    await db_session.commit()
    return user


async def _events(session_factory, event_type: str) -> list[AuthEvent]:
    async with session_factory() as fresh:
        rows = await fresh.execute(select(AuthEvent).where(AuthEvent.event_type == event_type).order_by(AuthEvent.id))
        return list(rows.scalars().all())


async def _verified(client, outbox, email="fixture_user@example.com") -> str:
    started = await client.post("/api/auth/password-reset/start", json={"email": email})
    assert started.status_code == 200, started.text
    token = started.json()["token"]
    verified = await client.post("/api/auth/password-reset/verify", json={"token": token, "code": _code(outbox)})
    assert verified.status_code == 200, verified.text
    assert verified.json()["username"] == "fixture_user"
    return token


class TestTheWholeWay:
    async def test_the_password_changes_and_every_session_ends(
        self, client, db_session, person, outbox, session_factory
    ):
        await _turn_on(db_session)
        version = int(person.token_version or 0)
        token = await _verified(client, outbox)
        assert "password reset code" in outbox[-1]["subject"]
        assert _code(outbox) not in outbox[-1]["subject"]
        done = await client.post("/api/auth/password-reset/complete", json={"token": token, "password": NEW})
        assert done.status_code == 200, done.text
        assert done.json() == {"ok": True, "username": "fixture_user"}

        async with session_factory() as fresh:
            fresh_user = await fresh.get(User, person.id)
            assert verify_password(NEW, fresh_user.hashed_password)
            assert int(fresh_user.token_version) == version + 1
            audit = (
                await fresh.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "user_password_reset_by_email")
                )
            ).scalar_one()
            assert audit.resource_id == str(person.id)
        assert len(await _events(session_factory, "password_reset")) == 1
        revoked = await _events(session_factory, "session_revoked")
        assert [e.reason_code for e in revoked] == ["password_reset_by_email"]

        again = await client.post(
            "/api/auth/password-reset/complete", json={"token": token, "password": "Another-Pass-1!"}
        )
        assert again.status_code == 400

    async def test_the_new_password_meets_the_policy_and_is_new(self, client, db_session, person, outbox):
        await _turn_on(db_session)
        token = await _verified(client, outbox)
        weak = await client.post(
            "/api/auth/password-reset/complete", json={"token": token, "password": "simplepassword1"}
        )
        assert weak.status_code == 400
        assert _detail(weak)["code"] == "weak_password"
        same = await client.post("/api/auth/password-reset/complete", json={"token": token, "password": OLD})
        assert same.status_code == 400
        assert "different" in _detail(same)["message"]


class TestWhoCanReset:
    async def test_off_until_turned_on(self, client, db_session, person, outbox):
        await _turn_on(db_session, reset=False)
        resp = await client.post("/api/auth/password-reset/start", json={"email": "fixture_user@example.com"})
        assert resp.status_code == 403
        assert _detail(resp)["code"] == "reset_disabled"
        assert outbox == []

    async def test_an_unknown_address_is_told_so(self, client, db_session, person, outbox):
        await _turn_on(db_session)
        resp = await client.post("/api/auth/password-reset/start", json={"email": "nobody@example.com"})
        assert resp.status_code == 404
        assert _detail(resp)["code"] == "email_unknown"
        assert outbox == []

    async def test_a_directory_account_resets_in_the_directory(self, client, db_session, person, outbox):
        person.auth_provider = "ldap"
        await db_session.commit()
        await _turn_on(db_session)
        resp = await client.post("/api/auth/password-reset/start", json={"email": "fixture_user@example.com"})
        assert resp.status_code == 400
        assert _detail(resp)["code"] == "not_local_account"

    async def test_a_deactivated_account_asks_the_administrator(self, client, db_session, person, outbox):
        person.is_active = False
        await db_session.commit()
        await _turn_on(db_session)
        resp = await client.post("/api/auth/password-reset/start", json={"email": "fixture_user@example.com"})
        assert resp.status_code == 403
        assert _detail(resp)["code"] == "account_inactive"

    async def test_deactivated_after_the_code_still_stops_the_last_step(self, client, db_session, person, outbox):
        await _turn_on(db_session)
        token = await _verified(client, outbox)
        person.is_active = False
        await db_session.commit()
        resp = await client.post("/api/auth/password-reset/complete", json={"token": token, "password": NEW})
        assert resp.status_code == 403

    async def test_a_sign_up_code_does_not_reset_a_password(self, client, db_session, person, outbox):
        await _turn_on(db_session)
        token = await _verified(client, outbox)
        resp = await client.post(
            "/api/auth/signup/complete", json={"token": token, "username": "someone.else", "password": NEW}
        )
        assert resp.status_code in (400, 403)


class TestTheCodeSteps:
    async def test_wrong_codes_are_recorded_against_the_account(
        self, client, db_session, person, outbox, session_factory
    ):
        await _turn_on(db_session)
        started = await client.post("/api/auth/password-reset/start", json={"email": "fixture_user@example.com"})
        right = _code(outbox)
        wrong = "000000" if right != "000000" else "111111"
        resp = await client.post(
            "/api/auth/password-reset/verify", json={"token": started.json()["token"], "code": wrong}
        )
        assert resp.status_code == 400
        failed = await _events(session_factory, "password_reset_failed")
        assert [(e.reason_code, e.user_id) for e in failed] == [("code_invalid", person.id)]
