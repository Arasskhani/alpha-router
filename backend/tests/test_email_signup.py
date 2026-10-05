"""Self sign-up by an emailed code, end to end through the routes.

The email is captured instead of sent. What the administrator was promised:
the feature is off until turned on; only the allowed domains; an address that
has an account is told so (with a reset offer when that is possible); a code
works once, for ten minutes, for five tries; the username must be free and
well-formed; the password must meet the policy; the new account is active,
has the default plan, and is signed in.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.core.security import verify_password
from app.models.auth_event import AuthEvent
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.email_verification import EmailVerification
from app.models.security import SecurityAuditEvent
from app.models.system import SmtpSettings
from app.models.user import User
from app.services.email_signup_service import EmailSignupSettings, save_email_signup_settings

STRONG = "Strong-Pass-2026!"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    from app.services import rate_limit

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)
    # The in-memory limiter is process-wide: no test may inherit another's counts.
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
    import re

    match = re.search(r"\n\s{4}(\d{6})\n", outbox[-1]["body"])
    assert match, outbox[-1]["body"]
    return match.group(1)


async def _turn_on(db, *, domains=None, plan_id=None, reset=False, enabled=True) -> None:
    db.add(SmtpSettings(host="smtp.example.com", port=587, from_address="noreply@example.com"))
    await db.flush()
    await save_email_signup_settings(
        db,
        EmailSignupSettings(
            enabled=enabled, allowed_domains=domains or [], default_plan_id=plan_id, reset_enabled=reset
        ),
    )
    await db.commit()


async def _events(session_factory, event_type: str) -> list[AuthEvent]:
    async with session_factory() as fresh:
        rows = await fresh.execute(select(AuthEvent).where(AuthEvent.event_type == event_type).order_by(AuthEvent.id))
        return list(rows.scalars().all())


async def _start(client, email: str):
    return await client.post("/api/auth/signup/start", json={"email": email})


async def _verified_token(client, outbox, email: str = "new.person@example.com") -> str:
    started = await _start(client, email)
    assert started.status_code == 200, started.text
    token = started.json()["token"]
    verified = await client.post("/api/auth/signup/verify", json={"token": token, "code": _code(outbox)})
    assert verified.status_code == 200, verified.text
    return token


def _detail(resp) -> dict:
    return resp.json()["detail"]


class TestOffUntilTurnedOn:
    async def test_the_sign_in_page_does_not_offer_it(self, client, db_session):
        methods = (await client.get("/api/auth/methods")).json()
        assert methods["email_signup"] is False and methods["password_reset"] is False

    async def test_starting_is_refused(self, client, db_session, outbox, session_factory):
        resp = await _start(client, "someone@example.com")
        assert resp.status_code == 403
        assert _detail(resp)["code"] == "signup_disabled"
        assert outbox == []
        assert [e.reason_code for e in await _events(session_factory, "signup_failed")] == ["signup_disabled"]

    async def test_it_needs_smtp_to_be_turned_on(self, db_session):
        with pytest.raises(ValueError, match="SMTP"):
            await save_email_signup_settings(db_session, EmailSignupSettings(enabled=True))

    async def test_the_page_offers_it_once_on(self, client, db_session):
        await _turn_on(db_session, reset=True)
        methods = (await client.get("/api/auth/methods")).json()
        assert methods["email_signup"] is True and methods["password_reset"] is True


class TestTheWholeWay:
    async def test_an_account_is_made_active_with_the_default_plan_and_signed_in(
        self, client, db_session, outbox, session_factory
    ):
        plan = BudgetPlan(name="Starter", monthly_budget_usd=5)
        db_session.add(plan)
        await db_session.flush()
        await _turn_on(db_session, domains=["example.com"], plan_id=int(plan.id))

        started = await _start(client, "  New.Person@Example.com ")
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["email"] == "new.person@example.com"
        assert body["expires_in"] == 600 and body["resend_in"] == 60 and body["code_length"] == 6
        assert outbox[-1]["to"] == "new.person@example.com"
        assert "sign-up code" in outbox[-1]["subject"]
        assert _code(outbox) not in outbox[-1]["subject"]

        verified = await client.post("/api/auth/signup/verify", json={"token": body["token"], "code": _code(outbox)})
        assert verified.status_code == 200
        assert verified.json()["suggested_username"] == "new.person"

        done = await client.post(
            "/api/auth/signup/complete",
            json={
                "token": body["token"],
                "username": "New.Person",
                "password": STRONG,
                "display_name": " New  Person ",
            },
        )
        assert done.status_code == 200, done.text
        session = (await client.get("/api/auth/session")).json()
        assert session["username"] == "new.person"
        assert session["role"] == "user" and session["is_active"] is True

        async with session_factory() as fresh:
            user = (await fresh.execute(select(User).where(User.username == "new.person"))).scalar_one()
            assert user.email == "new.person@example.com"
            assert user.display_name == "New Person"
            assert user.auth_provider == "local" and user.is_active
            assert verify_password(STRONG, user.hashed_password)
            assignment = (
                await fresh.execute(select(PlanAssignment).where(PlanAssignment.user_id == user.id))
            ).scalar_one()
            assert assignment.plan_id == plan.id
            audit = (
                await fresh.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "user_self_registered")
                )
            ).scalar_one()
            assert audit.resource_id == str(user.id)
        assert len(await _events(session_factory, "signup_completed")) == 1
        assert len(await _events(session_factory, "login_success")) == 1

        # The code is spent: the same token makes nothing more.
        again = await client.post(
            "/api/auth/signup/complete", json={"token": body["token"], "username": "other.name", "password": STRONG}
        )
        assert again.status_code == 400
        assert _detail(again)["code"] == "code_invalid"


class TestWhoMaySignUp:
    async def test_only_the_allowed_domains(self, client, db_session, outbox):
        await _turn_on(db_session, domains=["example.com", "example.org"])
        resp = await _start(client, "person@gmail.com")
        assert resp.status_code == 400
        assert _detail(resp)["code"] == "domain_not_allowed"
        assert "example.com, example.org" in _detail(resp)["message"]
        assert outbox == []
        assert (await _start(client, "person@example.org")).status_code == 200

    async def test_no_domains_means_any_address(self, client, db_session, outbox):
        await _turn_on(db_session)
        assert (await _start(client, "person@anywhere.net")).status_code == 200

    async def test_an_invalid_address(self, client, db_session, outbox):
        await _turn_on(db_session)
        for bad in ("", "no-at-sign", "two@@example.com", "spaces in@example.com"):
            resp = await _start(client, bad)
            assert resp.status_code == 400, bad
            assert _detail(resp)["code"] == "email_invalid"


class TestAnAddressThatHasAnAccount:
    async def test_a_local_account_is_offered_a_reset_when_resets_are_on(self, client, db_session, user, outbox):
        user.email = "fixture_user@example.com"
        await db_session.commit()
        await _turn_on(db_session, reset=True)
        resp = await _start(client, "Fixture_User@example.com")
        assert resp.status_code == 409
        detail = _detail(resp)
        assert detail["code"] == "email_taken"
        assert detail["reset_available"] is True
        assert "reset its password" in detail["message"]
        assert outbox == []

    async def test_without_resets_it_is_told_to_sign_in(self, client, db_session, user, outbox):
        user.email = "fixture_user@example.com"
        await db_session.commit()
        await _turn_on(db_session, reset=False)
        detail = _detail(await _start(client, "fixture_user@example.com"))
        assert detail["reset_available"] is False

    async def test_an_administrator_is_not_offered_a_reset(self, client, db_session, admin, outbox):
        admin.email = "boss@example.com"
        await db_session.commit()
        await _turn_on(db_session, reset=True)
        detail = _detail(await _start(client, "boss@example.com"))
        assert detail["code"] == "email_taken"
        assert detail["reset_available"] is False
        assert "reset" not in detail["message"]

    async def test_a_directory_account_is_told_where_it_signs_in(self, client, db_session, user):
        user.email = "fixture_user@example.com"
        user.auth_provider = "ldap"
        await db_session.commit()
        await _turn_on(db_session, reset=True)
        detail = _detail(await _start(client, "fixture_user@example.com"))
        assert detail["reset_available"] is False
        assert "directory" in detail["message"]


class TestTheCode:
    async def test_a_wrong_code_counts_and_five_end_it(self, client, db_session, outbox, session_factory):
        await _turn_on(db_session)
        token = (await _start(client, "a@example.com")).json()["token"]
        right = _code(outbox)
        wrong = "000000" if right != "000000" else "111111"
        for left in (4, 3, 2, 1):
            resp = await client.post("/api/auth/signup/verify", json={"token": token, "code": wrong})
            assert resp.status_code == 400
            assert f"{left} {'try' if left == 1 else 'tries'} left" in _detail(resp)["message"]
        last = await client.post("/api/auth/signup/verify", json={"token": token, "code": wrong})
        assert "Too many wrong codes" in _detail(last)["message"]
        late = await client.post("/api/auth/signup/verify", json={"token": token, "code": right})
        assert late.status_code == 400
        assert _detail(late)["code"] == "code_invalid"
        assert len(await _events(session_factory, "signup_failed")) == 6

    async def test_an_expired_code(self, client, db_session, outbox, session_factory):
        await _turn_on(db_session)
        token = (await _start(client, "a@example.com")).json()["token"]
        async with session_factory() as fresh:
            row = (await fresh.execute(select(EmailVerification))).scalar_one()
            row.expires_at = dt.datetime.utcnow() - dt.timedelta(seconds=1)
            await fresh.commit()
        resp = await client.post("/api/auth/signup/verify", json={"token": token, "code": _code(outbox)})
        assert resp.status_code == 400
        assert _detail(resp)["code"] == "code_expired"

    async def test_wrong_codes_are_recorded_against_the_address(self, client, db_session, outbox, session_factory):
        await _turn_on(db_session)
        token = (await _start(client, "a@example.com")).json()["token"]
        wrong = "000000" if _code(outbox) != "000000" else "111111"
        await client.post("/api/auth/signup/verify", json={"token": token, "code": wrong})
        failed = await _events(session_factory, "signup_failed")
        assert [(e.reason_code, e.username) for e in failed] == [("code_invalid", "a@example.com")]

    async def test_only_the_hash_is_kept(self, client, db_session, outbox, session_factory):
        await _turn_on(db_session)
        await _start(client, "a@example.com")
        async with session_factory() as fresh:
            row = (await fresh.execute(select(EmailVerification))).scalar_one()
        assert _code(outbox) not in row.code_hash
        assert len(row.code_hash) == 64

    async def test_a_new_code_waits_a_minute_and_ends_the_last(self, client, db_session, outbox, session_factory):
        await _turn_on(db_session)
        first = (await _start(client, "a@example.com")).json()["token"]
        first_code = _code(outbox)
        soon = await _start(client, "a@example.com")
        assert soon.status_code == 429
        assert _detail(soon)["code"] == "resend_wait"
        assert 0 < _detail(soon)["retry_after"] <= 60
        async with session_factory() as fresh:
            row = (await fresh.execute(select(EmailVerification))).scalar_one()
            row.created_at = dt.datetime.utcnow() - dt.timedelta(seconds=61)
            await fresh.commit()
        second = await _start(client, "a@example.com")
        assert second.status_code == 200
        old = await client.post("/api/auth/signup/verify", json={"token": first, "code": first_code})
        assert old.status_code == 400

    async def test_completing_needs_the_code_first(self, client, db_session, outbox):
        await _turn_on(db_session)
        token = (await _start(client, "a@example.com")).json()["token"]
        resp = await client.post(
            "/api/auth/signup/complete", json={"token": token, "username": "aperson", "password": STRONG}
        )
        assert resp.status_code == 400
        assert "code from the email" in _detail(resp)["message"]

    async def test_the_email_failing_to_send_leaves_no_code_behind(
        self, client, db_session, monkeypatch, session_factory
    ):
        from app.services.smtp_service import SmtpSendError

        async def broken(*_a, **_k):
            raise SmtpSendError("connection refused")

        monkeypatch.setattr("app.services.smtp_service.send_email", broken)
        await _turn_on(db_session)
        resp = await _start(client, "a@example.com")
        assert resp.status_code == 503
        assert _detail(resp)["code"] == "email_send_failed"
        async with session_factory() as fresh:
            assert (await fresh.execute(select(EmailVerification))).scalars().all() == []


class TestTheUsernameAndPassword:
    async def test_the_username_must_be_free(self, client, db_session, user, outbox):
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        check = await client.post(
            "/api/auth/signup/username-available", json={"token": token, "username": "FIXTURE_USER"}
        )
        assert check.json() == {
            "username": "fixture_user",
            "available": False,
            "code": "username_taken",
            "message": "That username is taken. Choose another.",
        }
        free = await client.post("/api/auth/signup/username-available", json={"token": token, "username": "brand.new"})
        assert free.json()["available"] is True
        taken = await client.post(
            "/api/auth/signup/complete", json={"token": token, "username": "fixture_user", "password": STRONG}
        )
        assert taken.status_code == 409
        assert _detail(taken)["code"] == "username_taken"

    async def test_the_username_must_be_well_formed_and_not_reserved(self, client, db_session, outbox):
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        for bad in ("ab", "has space", "-starts-with-dash", "admin", "alpharouter"):
            resp = await client.post(
                "/api/auth/signup/complete", json={"token": token, "username": bad, "password": STRONG}
            )
            assert resp.status_code == 400, bad
            assert _detail(resp)["code"] == "username_invalid"

    async def test_checking_a_name_needs_a_verified_code(self, client, db_session, outbox):
        await _turn_on(db_session)
        token = (await _start(client, "a@example.com")).json()["token"]
        resp = await client.post("/api/auth/signup/username-available", json={"token": token, "username": "brand.new"})
        assert resp.status_code == 400

    async def test_the_password_must_meet_the_policy(self, client, db_session, outbox):
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        for weak, words in (
            ("short1!", "at least"),
            ("nouppercase1!", "uppercase"),
            ("Brand.New-2026!", "username"),
        ):
            resp = await client.post(
                "/api/auth/signup/complete", json={"token": token, "username": "brand.new", "password": weak}
            )
            assert resp.status_code == 400, weak
            assert _detail(resp)["code"] == "weak_password"
            assert words in _detail(resp)["message"]

    async def test_turning_it_off_midway_stops_the_last_step(self, client, db_session, outbox):
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        await save_email_signup_settings(db_session, EmailSignupSettings(enabled=False))
        await db_session.commit()
        resp = await client.post(
            "/api/auth/signup/complete", json={"token": token, "username": "brand.new", "password": STRONG}
        )
        assert resp.status_code == 403
        assert _detail(resp)["code"] == "signup_disabled"


class TestDirectoryNames:
    """While LDAP is on, a name the directory has is not free, even before that person ever signed in."""

    @pytest.fixture
    def directory(self, monkeypatch):
        state = {"enabled": True, "names": {"jdoe"}, "down": False, "asked": []}

        async def config(_db, provider):
            return {"enabled": state["enabled"]} if provider == "ldap" else {}

        def exists(username, _config):
            state["asked"].append(username)
            if state["down"]:
                raise RuntimeError("unreachable")
            return username in state["names"]

        monkeypatch.setattr("app.services.auth_config.get_provider_config", config)
        monkeypatch.setattr("app.services.ldap_auth.ldap_username_exists", exists)
        return state

    async def test_a_directory_name_is_taken(self, client, db_session, outbox, directory):
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        check = await client.post("/api/auth/signup/username-available", json={"token": token, "username": "jdoe"})
        assert check.json()["available"] is False
        assert check.json()["code"] == "username_taken"
        done = await client.post(
            "/api/auth/signup/complete", json={"token": token, "username": "jdoe", "password": STRONG}
        )
        assert done.status_code == 409
        free = await client.post("/api/auth/signup/username-available", json={"token": token, "username": "brand.new"})
        assert free.json()["available"] is True

    async def test_a_directory_that_cannot_be_asked_leaves_the_name_unchecked(
        self, client, db_session, outbox, directory
    ):
        directory["down"] = True
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        check = await client.post("/api/auth/signup/username-available", json={"token": token, "username": "brand.new"})
        assert check.json()["available"] is False
        assert check.json()["code"] == "ldap_unavailable"
        done = await client.post(
            "/api/auth/signup/complete", json={"token": token, "username": "brand.new", "password": STRONG}
        )
        assert done.status_code == 503
        assert _detail(done)["code"] == "ldap_unavailable"

    async def test_only_a_well_formed_name_reaches_the_directory(self, client, db_session, outbox, directory):
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        check = await client.post("/api/auth/signup/username-available", json={"token": token, "username": "j*(doe)"})
        assert check.json()["code"] == "username_invalid"
        assert directory["asked"] == []

    async def test_without_ldap_the_directory_is_not_asked(self, client, db_session, outbox, directory):
        directory["enabled"] = False
        await _turn_on(db_session)
        token = await _verified_token(client, outbox)
        check = await client.post("/api/auth/signup/username-available", json={"token": token, "username": "jdoe"})
        assert check.json()["available"] is True
        assert directory["asked"] == []


class TestLimits:
    async def test_one_address_cannot_send_codes_without_end(self, client, db_session, outbox, session_factory):
        await _turn_on(db_session)
        for i in range(10):
            assert (await _start(client, f"person{i}@example.com")).status_code == 200
        resp = await _start(client, "person10@example.com")
        assert resp.status_code == 429
        assert _detail(resp)["code"] == "rate_limited"
        assert len(outbox) == 10
        assert [e.reason_code for e in await _events(session_factory, "signup_failed")] == ["rate_limited"]
