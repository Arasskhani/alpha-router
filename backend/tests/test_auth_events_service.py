"""The sign-in recorder: what it writes, and the two rules it must never break.

Authentication events used to be three ``action`` values in the security
settings audit table, written by a private helper in ``app.api.auth``. This
service replaces that helper and keeps the two properties that turned out to
matter: the row is written in a session of its own, so a failed login that
rolls the request back does not roll the record back with it; and a broken
write logs and returns instead of turning a valid sign-in into a 500.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.auth_event import AuthEvent
from app.services import auth_events_service as svc


class _Request:
    def __init__(self, ip: str = "203.0.113.7", user_agent: str = "Mozilla/5.0 test", cookies=None) -> None:
        self.client = type("C", (), {"host": ip})()
        self.headers = {"user-agent": user_agent}
        self.cookies = cookies or {}


@pytest.fixture
def own_session(monkeypatch, session_factory):
    """Point the recorder's independent session at the test engine."""

    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)


async def _rows(db) -> list[AuthEvent]:
    return list((await db.execute(select(AuthEvent).order_by(AuthEvent.id))).scalars().all())


async def test_a_sign_in_is_written_with_the_facts_the_page_filters_on(db_session, user, own_session):
    await svc.record_auth_event(
        event_type="login_success",
        user=user,
        auth_method="local",
        session_id="jti-1",
        request=_Request(),
    )
    rows = await _rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == "login_success"
    assert row.outcome == "success"
    assert row.user_id == user.id
    assert row.username == user.username
    assert row.auth_method == "local"
    assert row.ip == "203.0.113.7"
    assert row.user_agent == "Mozilla/5.0 test"
    assert row.session_id == "jti-1"
    assert row.backfilled is False


async def test_a_failed_attempt_at_a_missing_account_keeps_the_name_that_was_typed(db_session, own_session):
    await svc.record_auth_event(
        event_type="login_failed",
        user=None,
        username="nobody_here",
        reason_code="no_such_user",
        auth_method="local",
        request=_Request(),
    )
    row = (await _rows(db_session))[0]
    assert row.user_id is None
    assert row.username == "nobody_here"
    assert row.outcome == "failure"
    assert row.reason_code == "no_such_user"


async def test_sign_outs_and_revocations_say_they_end_every_session(db_session, user, own_session):
    """token_version ends every session everywhere; the row must not imply one."""
    await svc.record_auth_event(event_type="logout", user=user, request=_Request())
    await svc.record_auth_event(event_type="session_revoked", user=user, reason_code="password_changed")
    rows = await _rows(db_session)
    assert [r.scope for r in rows] == ["all_sessions", "all_sessions"]
    assert [r.outcome for r in rows] == ["n/a", "n/a"]
    # The revocation came from a service with no request: no address, still a row.
    assert rows[1].ip is None


async def test_the_row_survives_the_request_transaction_being_rolled_back(db_session, session_factory, own_session):
    """The property the old helper existed for, kept."""
    async with session_factory() as request_db:
        await svc.record_auth_event(
            event_type="login_failed",
            user=None,
            username="x",
            reason_code="bad_password",
            request=_Request(),
        )
        await request_db.rollback()
    assert len(await _rows(db_session)) == 1


async def test_a_broken_write_never_raises(monkeypatch):
    class _Broken:
        def __call__(self, *_a, **_k):
            raise RuntimeError("database is gone")

    monkeypatch.setattr("app.database.AsyncSessionLocal", _Broken())
    await svc.record_auth_event(event_type="login_success", user=None, username="someone", request=_Request())


async def test_it_can_ride_a_callers_transaction_when_asked(db_session, user):
    """Revocations belong to the transaction that revoked; rolling one back rolls the other."""
    await svc.record_auth_event(event_type="session_revoked", user=user, reason_code="user_deleted", db=db_session)
    await db_session.rollback()
    assert await _rows(db_session) == []


def test_unknown_types_and_codes_are_refused_at_build_time():
    with pytest.raises(ValueError):
        svc.build_auth_event(event_type="signed_in", user=None)
    with pytest.raises(ValueError):
        svc.build_auth_event(event_type="login_failed", user=None, reason_code="typo")


def test_long_values_are_clipped_not_rejected():
    row = svc.build_auth_event(
        event_type="login_failed",
        user=None,
        username="u" * 400,
        reason_code="ldap_unavailable",
        reason_detail="e" * 5000,
        request=_Request(user_agent="a" * 900),
    )
    assert len(row.username) == 255
    assert len(row.reason_detail) == 2000
    assert len(row.user_agent) == 512


def test_method_for_reads_the_accounts_provider():
    class _U:
        auth_provider = "SAML"

    assert svc.method_for(_U()) == "saml"
    assert svc.method_for(None) == "local"
    assert svc.method_for(type("X", (), {"auth_provider": "keycloak"})(), fallback="oidc") == "oidc"
