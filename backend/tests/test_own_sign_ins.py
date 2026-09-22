"""A person can see their own recent sign-ins — and only their own.

The endpoint takes no parameters, so the only thing to prove about isolation
is that the rows come from the session's user id and nothing else. The rest
is what the list is for: failures show, the current session is marked, and
the provider's message stays with the administrator.
"""

from __future__ import annotations

import datetime

import pytest

from app.api import user_settings
from app.core.security import create_access_token
from app.models.auth_event import AuthEvent
from app.models.user import User


@pytest.fixture(autouse=True)
def _ip_guard_on_the_test_engine(session_factory, monkeypatch):
    from app.services import admin_ip_allowlist_service

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


def _cookie() -> str:
    from app.config import get_settings

    return get_settings().session_cookie_name


async def _other(db) -> User:
    row = User(username="bob", email="bob@test", hashed_password="x", auth_provider="saml", is_active=True)
    db.add(row)
    await db.flush()
    return row


def _event(user: User | None, minutes_ago: int, **overrides) -> AuthEvent:
    fields = dict(
        occurred_at=datetime.datetime(2026, 9, 21, 9, 0, 0) - datetime.timedelta(minutes=minutes_ago),
        user_id=user.id if user else None,
        username=user.username if user else "nobody",
        event_type="login_success",
        outcome="success",
        auth_method="local",
        ip="203.0.113.7",
        user_agent="Firefox",
    )
    fields.update(overrides)
    return AuthEvent(**fields)


async def test_only_the_callers_rows_and_never_a_sign_out(client, db_session, user):
    bob = await _other(db_session)
    db_session.add_all(
        [
            _event(user, 1),
            _event(
                user, 2, event_type="login_failed", outcome="failure", reason_code="bad_password", ip="198.51.100.9"
            ),
            _event(user, 3, event_type="login_rate_limited", outcome="failure", reason_code="rate_limited"),
            _event(
                user,
                4,
                event_type="session_revoked",
                outcome="n/a",
                scope="all_sessions",
                reason_code="password_changed",
            ),
            _event(user, 5, event_type="logout", outcome="n/a", scope="all_sessions"),
            _event(bob, 0),
            _event(bob, 0, event_type="login_failed", outcome="failure", reason_code="bad_password"),
            _event(None, 0, event_type="login_failed", outcome="failure", reason_code="no_such_user"),
        ]
    )
    await db_session.commit()

    client.cookies.set(_cookie(), create_access_token(user.username, "user"))
    resp = await client.get("/api/user/settings/sign-ins")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["auth_provider"] == "local"
    assert body["limit"] == user_settings.OWN_SIGN_IN_LIMIT
    assert [i["event_type"] for i in body["items"]] == [
        "login_success",
        "login_failed",
        "login_rate_limited",
        "session_revoked",
    ]
    failed = body["items"][1]
    assert failed["reason_code"] == "bad_password" and failed["ip"] == "198.51.100.9"
    assert "bob" not in resp.text and "nobody" not in resp.text


async def test_the_response_carries_no_administrative_detail(client, db_session, user):
    db_session.add(
        _event(
            user,
            1,
            event_type="login_failed",
            outcome="failure",
            reason_code="ldap_rejected",
            reason_detail="LDAP: invalidCredentials (49) data 52e",
            correlation_id="corr-77",
            session_id="sess-1",
        )
    )
    await db_session.commit()
    client.cookies.set(_cookie(), create_access_token(user.username, "user"))
    item = (await client.get("/api/user/settings/sign-ins")).json()["items"][0]
    assert set(item) == {
        "occurred_at",
        "event_type",
        "outcome",
        "reason_code",
        "auth_method",
        "ip",
        "user_agent",
        "current_session",
    }
    assert "invalidCredentials" not in str(item) and "corr-77" not in str(item) and "sess-1" not in str(item)


async def test_the_current_session_is_marked(client, db_session, user):
    from app.core.security import decode_access_token

    token = create_access_token(user.username, "user")
    jti = decode_access_token(token)["jti"]
    db_session.add_all([_event(user, 1, session_id=jti), _event(user, 2, session_id="another-device")])
    await db_session.commit()

    client.cookies.set(_cookie(), token)
    items = (await client.get("/api/user/settings/sign-ins")).json()["items"]
    assert [i["current_session"] for i in items] == [True, False]


async def test_the_list_is_bounded_and_newest_first(client, db_session, user):
    db_session.add_all([_event(user, m) for m in range(user_settings.OWN_SIGN_IN_LIMIT + 5)])
    await db_session.commit()
    client.cookies.set(_cookie(), create_access_token(user.username, "user"))
    items = (await client.get("/api/user/settings/sign-ins")).json()["items"]
    assert len(items) == user_settings.OWN_SIGN_IN_LIMIT
    assert items[0]["occurred_at"] > items[-1]["occurred_at"]


async def test_parameters_are_ignored_not_honoured(client, db_session, user):
    """Nothing in the request can point at another account."""
    bob = await _other(db_session)
    db_session.add(_event(bob, 0))
    await db_session.commit()
    client.cookies.set(_cookie(), create_access_token(user.username, "user"))
    for query in (f"user_id={bob.id}", f"user={bob.id}", "username=bob", "limit=1000"):
        body = (await client.get(f"/api/user/settings/sign-ins?{query}")).json()
        assert body["items"] == [], query


async def test_anonymous_is_refused(client):
    assert (await client.get("/api/user/settings/sign-ins")).status_code == 401
