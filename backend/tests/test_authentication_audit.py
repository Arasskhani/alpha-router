"""Sign-ins reach the audit trail.

``security_audit_events`` had no ``login_success``, no ``login_failed`` and no
``logout``. The only trace of a successful sign-in was ``users.last_login_at``,
overwritten every time and carrying no address - so the platform could not
answer "who signed in, from where, when" or "is someone grinding this account"
from its own audit surface. For a product sold as an organizational platform
that is a compliance gap as much as a security one.

A failed login raises, and ``get_db`` rolls the request transaction back, so
these rows are written in their own session and committed immediately - or the
record of the failure would be discarded exactly when it matters.
"""

from __future__ import annotations

import inspect
import json

import pytest
from sqlalchemy import select

from app.api import auth
from app.models.security import SecurityAuditEvent


class _Request:
    def __init__(self, ip: str = "203.0.113.7") -> None:
        self.client = type("C", (), {"host": ip})()
        self.headers: dict[str, str] = {}


@pytest.fixture
def audit_session(monkeypatch, session_factory):
    """Point the audit writer's own session at the test engine."""

    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)
    return session_factory


async def _events(db_session) -> list[SecurityAuditEvent]:
    return list((await db_session.execute(select(SecurityAuditEvent))).scalars().all())


async def test_a_successful_sign_in_is_recorded(db_session, user, audit_session):
    await auth._record_auth_event(_Request(), action="login_success", user=user, detail={"provider": "local"})

    rows = await _events(db_session)
    assert len(rows) == 1
    assert rows[0].action == "login_success"
    assert rows[0].actor_user_id == user.id
    assert rows[0].actor_username == user.username
    assert rows[0].actor_ip == "203.0.113.7"


async def test_a_failed_sign_in_names_the_username_that_was_tried(db_session, audit_session):
    await auth._record_auth_event(
        _Request(),
        action="login_failed",
        user=None,
        username="someone_who_does_not_exist",
        detail={"reason": "unknown"},
    )

    rows = await _events(db_session)
    assert len(rows) == 1
    assert rows[0].action == "login_failed"
    assert rows[0].actor_user_id is None
    # detail_json is Text, holding a JSON document.
    detail = json.loads(rows[0].detail_json)
    assert detail["username"] == "someone_who_does_not_exist"
    assert detail["reason"] == "unknown"


async def test_an_audit_failure_never_breaks_a_login(db_session, monkeypatch):
    """A broken audit write must not turn a valid sign-in into an error."""

    class _Broken:
        def __call__(self, *_a, **_k):
            raise RuntimeError("database is gone")

    monkeypatch.setattr("app.database.AsyncSessionLocal", _Broken())
    await auth._record_auth_event(_Request(), action="login_success", user=None, username="someone")


def test_every_login_outcome_is_covered():
    login = inspect.getsource(auth.login_local)
    assert login.count("_record_auth_event") >= 3, "a 401 exit from login is not recorded"
    assert "_record_auth_event" in inspect.getsource(auth._token_response), "success is not recorded"
    assert "_record_auth_event" in inspect.getsource(auth.logout_local), "logout is not recorded"
