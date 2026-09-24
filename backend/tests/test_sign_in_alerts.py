"""Sign-in failure patterns raise a flag, once, and lock nobody out.

Thresholds are asserted exactly, because the difference between nine and
ten failures is the difference between a mistyped password and an attack,
and a threshold that drifts silently is worse than none.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import select

from app.models.auth_event import AuthEvent
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services import sign_in_alert_service as svc
from app.services.sign_in_alert_service import (
    ACTION,
    IP_DISTINCT_USERS_THRESHOLD,
    KIND_ACCOUNT,
    KIND_ADDRESS,
    USER_FAILURE_THRESHOLD,
    WINDOW_MINUTES,
    find_patterns,
    raise_alerts,
)
from app.services.smtp_service import SmtpNotConfiguredError

NOW = datetime.datetime(2026, 9, 22, 10, 0, 0)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """The dedup ledger is the trail; Redis is an accelerator. Tests run
    without it so the fallback is what is exercised — the one path that must
    work when nothing else does."""

    class _Down:
        async def set(self, *_a, **_k):
            raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.redis_client.get_redis", lambda: _Down())


@pytest.fixture
def outbox(monkeypatch):
    sent: list[tuple[str, str, str]] = []

    async def _send(_db, *, to_address, subject, body_text, **_kw):
        sent.append((to_address, subject, body_text))

    monkeypatch.setattr(svc, "send_email", _send)
    return sent


def _failure(*, username: str, ip: str, minutes_ago: int, user_id: int | None = None, **overrides) -> AuthEvent:
    fields = dict(
        occurred_at=NOW - datetime.timedelta(minutes=minutes_ago),
        user_id=user_id,
        username=username,
        event_type="login_failed",
        outcome="failure",
        reason_code="bad_password",
        auth_method="local",
        ip=ip,
    )
    fields.update(overrides)
    return AuthEvent(**fields)


async def _super_admin(db, username="root", email="root@test", active=True) -> User:
    from app.services.user_role_service import set_user_roles

    row = User(username=username, email=email, hashed_password="x", auth_provider="local", is_active=active)
    db.add(row)
    await db.flush()
    await set_user_roles(db, row, ["super_admin"])
    return row


async def _alerts(db) -> list[SecurityAuditEvent]:
    return list((await db.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == ACTION))).scalars())


class TestFinding:
    async def test_nine_failures_is_a_bad_day_ten_is_a_pattern(self, db_session):
        for i in range(USER_FAILURE_THRESHOLD - 1):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
        await db_session.commit()
        assert await find_patterns(db_session, now=NOW) == []

        db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=0))
        await db_session.commit()
        found = await find_patterns(db_session, now=NOW)
        assert [a.kind for a in found] == [KIND_ACCOUNT]
        assert found[0].subject == "name:alice"
        assert found[0].detail["failures"] == USER_FAILURE_THRESHOLD
        assert found[0].detail["distinct_addresses"] == 1

    async def test_the_name_is_the_subject_so_case_and_missing_accounts_still_count(self, db_session):
        """An attack on 'Alice' and 'alice' is one attack; an attack on an
        account that does not exist has no user id and still counts."""
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(
                _failure(
                    username="Alice" if i % 2 else "alice", ip="203.0.113.7", minutes_ago=i, reason_code="no_such_user"
                )
            )
        await db_session.commit()
        found = await find_patterns(db_session, now=NOW)
        assert len(found) == 1 and found[0].subject == "name:alice" and found[0].detail["user_id"] is None

    async def test_only_failures_inside_the_window_count(self, db_session):
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=WINDOW_MINUTES + 1 + i))
        db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=1))
        await db_session.commit()
        assert await find_patterns(db_session, now=NOW) == []

    async def test_successes_and_rate_limits(self, db_session):
        """A rate-limited attempt is a failure; a success and a sign-out are not."""
        for i in range(USER_FAILURE_THRESHOLD - 1):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
        db_session.add(
            _failure(
                username="alice",
                ip="203.0.113.7",
                minutes_ago=0,
                event_type="login_success",
                outcome="success",
                reason_code=None,
            )
        )
        db_session.add(
            _failure(
                username="alice", ip="203.0.113.7", minutes_ago=0, event_type="logout", outcome="n/a", reason_code=None
            )
        )
        await db_session.commit()
        assert await find_patterns(db_session, now=NOW) == []

        db_session.add(
            _failure(
                username="alice",
                ip="203.0.113.7",
                minutes_ago=0,
                event_type="login_rate_limited",
                reason_code="rate_limited",
            )
        )
        await db_session.commit()
        assert [a.kind for a in await find_patterns(db_session, now=NOW)] == [KIND_ACCOUNT]

    async def test_four_accounts_from_one_address_is_noise_five_is_a_pattern(self, db_session):
        for i in range(IP_DISTINCT_USERS_THRESHOLD - 1):
            db_session.add(_failure(username=f"user{i}", ip="198.51.100.9", minutes_ago=i))
        await db_session.commit()
        assert await find_patterns(db_session, now=NOW) == []

        db_session.add(_failure(username="user_last", ip="198.51.100.9", minutes_ago=0))
        await db_session.commit()
        found = await find_patterns(db_session, now=NOW)
        assert [a.kind for a in found] == [KIND_ADDRESS]
        assert found[0].subject == "ip:198.51.100.9"
        assert found[0].detail["distinct_accounts"] == IP_DISTINCT_USERS_THRESHOLD
        assert found[0].detail["sample_accounts"] == ["user0", "user1", "user2", "user3", "user_last"]

    async def test_the_sample_of_tried_names_is_bounded(self, db_session):
        for i in range(svc.SAMPLE_NAMES + 7):
            db_session.add(_failure(username=f"u{i:03d}", ip="198.51.100.9", minutes_ago=0))
        await db_session.commit()
        found = await find_patterns(db_session, now=NOW)
        assert found[0].detail["distinct_accounts"] == svc.SAMPLE_NAMES + 7
        assert len(found[0].detail["sample_accounts"]) == svc.SAMPLE_NAMES

    async def test_both_patterns_can_be_present_at_once(self, db_session):
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip=f"203.0.113.{i}", minutes_ago=i))
        for i in range(IP_DISTINCT_USERS_THRESHOLD):
            db_session.add(_failure(username=f"user{i}", ip="198.51.100.9", minutes_ago=i))
        await db_session.commit()
        kinds = sorted(a.kind for a in await find_patterns(db_session, now=NOW))
        assert kinds == [KIND_ACCOUNT, KIND_ADDRESS]


class TestRaising:
    async def test_an_alert_is_recorded_in_the_trail_and_mailed_to_active_super_admins(self, db_session, outbox):
        await _super_admin(db_session, "root", "root@test")
        await _super_admin(db_session, "gone", "gone@test", active=False)
        plain = User(username="alice", email="alice@test", hashed_password="x", auth_provider="local", is_active=True)
        db_session.add(plain)
        await db_session.flush()
        for i in range(USER_FAILURE_THRESHOLD + 2):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i, user_id=plain.id))
        await db_session.commit()

        result = await raise_alerts(db_session, now=NOW)
        assert result == {"found": 1, "raised": 1, "suppressed": 0, "emails_sent": 1}

        rows = await _alerts(db_session)
        assert len(rows) == 1
        assert rows[0].resource_type == "authentication"
        assert rows[0].resource_id == "name:alice"
        assert rows[0].actor_user_id is None, "the system raised it, not a person"
        detail = json.loads(rows[0].detail_json)
        assert detail["kind"] == KIND_ACCOUNT
        assert detail["failures"] == USER_FAILURE_THRESHOLD + 2
        assert detail["user_id"] == plain.id

        assert [to for to, _, _ in outbox] == ["root@test"], "inactive admins and the victim get nothing"
        _, subject, body = outbox[0]
        assert "alice" in subject and str(USER_FAILURE_THRESHOLD + 2) in subject
        assert "NOT been locked" in body
        assert "Sign-in Activity" in body

    async def test_nobody_is_locked_out(self, db_session, outbox):
        victim = User(username="alice", email="a@test", hashed_password="x", auth_provider="local", is_active=True)
        db_session.add(victim)
        await db_session.flush()
        before = int(victim.token_version or 0)
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i, user_id=victim.id))
        await db_session.commit()

        await raise_alerts(db_session, now=NOW)
        await db_session.refresh(victim)
        assert victim.is_active is True
        assert int(victim.token_version or 0) == before
        # And no session_revoked row was written for them.
        revoked = (
            (await db_session.execute(select(AuthEvent).where(AuthEvent.event_type == "session_revoked")))
            .scalars()
            .all()
        )
        assert revoked == []

    async def test_the_same_pattern_is_raised_once_an_hour_even_without_redis(self, db_session, outbox):
        await _super_admin(db_session)
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
        await db_session.commit()

        first = await raise_alerts(db_session, now=NOW)
        again = await raise_alerts(db_session, now=NOW + datetime.timedelta(minutes=5))
        assert first["raised"] == 1 and again == {"found": 1, "raised": 0, "suppressed": 1, "emails_sent": 0}
        assert len(outbox) == 1

        # An hour later, if it is still going, it is worth saying again.
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=-61 - i))  # in the future window
        await db_session.commit()
        later = await raise_alerts(db_session, now=NOW + datetime.timedelta(minutes=61))
        assert later["raised"] == 1
        assert len(await _alerts(db_session)) == 2

    async def test_redis_answers_first_when_it_is_there(self, db_session, outbox, monkeypatch):
        calls: list[tuple] = []

        class _Up:
            async def set(self, key, value, nx=False, ex=None):
                calls.append((key, nx, ex))
                return len(calls) == 1  # first caller wins, second is a repeat

        monkeypatch.setattr("app.core.redis_client.get_redis", lambda: _Up())
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
        await db_session.commit()

        assert (await raise_alerts(db_session, now=NOW))["raised"] == 1
        # Remove the trail row so only Redis can know it was raised.
        for row in await _alerts(db_session):
            await db_session.delete(row)
        await db_session.commit()
        assert (await raise_alerts(db_session, now=NOW))["suppressed"] == 1
        assert calls[0] == (f"sign_in_alert:{KIND_ACCOUNT}:name:alice", True, svc.DEDUP_SECONDS)

    async def test_the_record_survives_a_mail_failure(self, db_session, monkeypatch):
        await _super_admin(db_session)

        async def _broken(*_a, **_k):
            raise SmtpNotConfiguredError("SMTP is not configured")

        monkeypatch.setattr(svc, "send_email", _broken)
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
        await db_session.commit()

        result = await raise_alerts(db_session, now=NOW)
        assert result["raised"] == 1 and result["emails_sent"] == 0
        assert len(await _alerts(db_session)) == 1, "no SMTP must not mean no record"

    async def test_no_super_admin_email_is_a_warning_not_an_error(self, db_session, outbox):
        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
        await db_session.commit()
        result = await raise_alerts(db_session, now=NOW)
        assert result["raised"] == 1 and result["emails_sent"] == 0 and outbox == []

    async def test_the_address_alert_names_the_accounts_tried(self, db_session, outbox):
        await _super_admin(db_session)
        for i in range(IP_DISTINCT_USERS_THRESHOLD):
            db_session.add(_failure(username=f"user{i}", ip="198.51.100.9", minutes_ago=i))
        await db_session.commit()
        await raise_alerts(db_session, now=NOW)
        _, subject, body = outbox[0]
        assert "198.51.100.9" in subject
        assert "user0, user1, user2, user3, user4" in body
        assert "No account has been locked" in body

    async def test_the_alert_shows_up_in_admin_logs(self, db_session):
        """Written to security_audit_events with a resource type the Admin
        Logs filter panel already knows."""
        from app.api.admin_logs import list_admin_logs

        for i in range(USER_FAILURE_THRESHOLD):
            db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
        await db_session.commit()
        await raise_alerts(db_session, now=NOW)

        page = await list_admin_logs(
            db=db_session,
            _=None,
            limit=10,
            offset=0,
            actor=None,
            action=ACTION,
            resource_type=None,
            start_date=None,
            end_date=None,
            source="security",
        )
        assert len(page["items"]) == 1
        assert page["items"][0]["detail"]["kind"] == KIND_ACCOUNT


async def test_a_crafted_account_name_cannot_stop_the_alerts_after_it(db_session):
    """The subject names the account that was tried, and anyone can try any
    name. One with a line break used to make the mail library raise inside
    send_email, which stopped the run before the next alert was recorded."""

    from app.models.system import SmtpSettings
    from tests.smtp_test_server import MODE_PLAIN, SmtpTestServer

    await _super_admin(db_session, "root", "root@test")
    for i in range(USER_FAILURE_THRESHOLD):
        db_session.add(_failure(username="!x\ny", ip="198.51.100.1", minutes_ago=i))
        db_session.add(_failure(username="victim", ip="198.51.100.2", minutes_ago=i))
    async with SmtpTestServer(mode=MODE_PLAIN) as server:
        db_session.add(
            SmtpSettings(
                host="127.0.0.1",
                port=server.port,
                from_address="alerts@example.com",
                security="none",
                verify_certificate=True,
            )
        )
        await db_session.commit()
        result = await raise_alerts(db_session, now=NOW)

    assert result == {"found": 2, "raised": 2, "suppressed": 0, "emails_sent": 2}
    assert sorted(r.resource_id for r in await _alerts(db_session)) == ["name:!x\ny", "name:victim"]
    subjects = sorted(
        next(line for line in m.data.decode().splitlines() if line.startswith("Subject:")) for m in server.messages
    )
    assert subjects == [
        f"Subject: Alpharouter: {USER_FAILURE_THRESHOLD} failed sign-ins for '!x y' in {WINDOW_MINUTES} minutes",
        f"Subject: Alpharouter: {USER_FAILURE_THRESHOLD} failed sign-ins for 'victim' in {WINDOW_MINUTES} minutes",
    ]


def test_the_job_is_scheduled_every_five_minutes():
    import inspect

    from app.services import scheduler

    source = inspect.getsource(scheduler)
    assert 'id="sign_in_alerts"' in source and "job_sign_in_alerts," in source
    assert WINDOW_MINUTES > 5, "the window must be wider than the interval or attempts fall between runs"


async def test_the_job_runs_against_the_test_engine(db_session, session_factory, monkeypatch, outbox):
    from app.services import scheduler

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    for i in range(USER_FAILURE_THRESHOLD):
        db_session.add(_failure(username="alice", ip="203.0.113.7", minutes_ago=i))
    await db_session.commit()

    await scheduler.job_sign_in_alerts()
    assert len(await _alerts(db_session)) == 1


class TestOneFailureDoesNotStopTheRest:
    """The trail row is committed before any mail; what goes wrong with one
    alert's mail, or one recipient, must not stop the other alerts and the
    other Super Admins."""

    async def _two_alerts(self, db):
        for i in range(USER_FAILURE_THRESHOLD):
            db.add(_failure(username="alice", ip="198.51.100.1", minutes_ago=i))
            db.add(_failure(username="bob", ip="198.51.100.2", minutes_ago=i))
        await db.commit()

    async def test_a_refused_address_does_not_stop_mail_to_the_other_super_admins(self, db_session):
        from app.models.system import SmtpSettings
        from tests.smtp_test_server import MODE_PLAIN, SmtpTestServer

        await _super_admin(db_session, "root", "root@refused.example")
        await _super_admin(db_session, "second", "second@test")
        await self._two_alerts(db_session)
        async with SmtpTestServer(mode=MODE_PLAIN, refuse_recipients=frozenset({"root@refused.example"})) as server:
            db_session.add(
                SmtpSettings(
                    host="127.0.0.1",
                    port=server.port,
                    from_address="alerts@example.com",
                    security="none",
                    verify_certificate=True,
                )
            )
            await db_session.commit()
            result = await raise_alerts(db_session, now=NOW)

        assert result == {"found": 2, "raised": 2, "suppressed": 0, "emails_sent": 2}
        assert [m.recipients for m in server.messages] == [("second@test",), ("second@test",)]

    async def test_an_alert_whose_mail_cannot_be_prepared_does_not_stop_the_next(self, db_session, outbox, monkeypatch):
        await _super_admin(db_session)
        await self._two_alerts(db_session)
        real_message = svc._message

        def _message(alert):
            if alert.subject == "name:alice":
                raise RuntimeError("a bug in one alert's text")
            return real_message(alert)

        monkeypatch.setattr(svc, "_message", _message)
        result = await raise_alerts(db_session, now=NOW)

        assert result["raised"] == 2 and result["emails_sent"] == 1
        assert len(await _alerts(db_session)) == 2
        assert "'bob'" in outbox[0][1]

    async def test_an_unexpected_mail_error_keeps_every_record(self, db_session, monkeypatch):
        await _super_admin(db_session)
        await self._two_alerts(db_session)
        calls = []

        async def _crash(*_a, **_k):
            calls.append(1)
            raise RuntimeError("database went away")

        monkeypatch.setattr(svc, "send_email", _crash)
        result = await raise_alerts(db_session, now=NOW)

        assert result["raised"] == 2 and result["emails_sent"] == 0
        assert len(await _alerts(db_session)) == 2
        # Taken as the mail path being down for this run: tried once, not once per alert.
        assert calls == [1]
