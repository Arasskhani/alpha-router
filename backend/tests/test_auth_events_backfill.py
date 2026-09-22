"""The one-off copy of legacy sign-in rows into auth_events.

A Sign-in Activity page that opened empty on the day it shipped would answer
the wrong question; the history from before is what an operator looks back
through. The copy must be idempotent, must carry rows whose reason has been
redacted rather than dropping them, and must leave administrative events in
the security trail where they belong.
"""

from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import select

from app.models.auth_event import AuthEvent
from app.models.security import SecurityAuditEvent
from app.services.auth_events_backfill import backfill_auth_events, record_backfill_run

NOW = dt.datetime(2026, 9, 1, 12, 0, 0)


def _legacy(action: str, *, user=None, ip="203.0.113.5", detail=None, redacted=False, at=NOW) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        actor_user_id=user.id if user else None,
        actor_username=user.username if user else None,
        actor_email=user.email if user else None,
        actor_ip=ip,
        action=action,
        resource_type="saml" if action == "saml_response_rejected" else "authentication",
        detail_json=None if redacted else json.dumps(detail or {}),
        detail_redacted_at=at if redacted else None,
        created_at=at,
    )


async def _new_rows(db) -> list[AuthEvent]:
    return list((await db.execute(select(AuthEvent).order_by(AuthEvent.occurred_at, AuthEvent.id))).scalars().all())


async def test_the_four_legacy_shapes_map_to_the_new_table(db_session, user):
    db_session.add_all(
        [
            _legacy("login_success", user=user, detail={"provider": "ldap"}, at=NOW),
            _legacy("login_failed", user=user, detail={"reason": "bad_password"}, at=NOW + dt.timedelta(minutes=1)),
            _legacy(
                "login_failed", detail={"reason": "unknown", "username": "ghost"}, at=NOW + dt.timedelta(minutes=2)
            ),
            _legacy("logout", user=user, at=NOW + dt.timedelta(minutes=3)),
            _legacy("saml_response_rejected", detail={"reason": "assertion_invalid"}, at=NOW + dt.timedelta(minutes=4)),
            # Not a sign-in; stays where it is.
            _legacy("security_setting_changed", user=user, at=NOW + dt.timedelta(minutes=5)),
        ]
    )
    await db_session.commit()

    report = await backfill_auth_events(db_session)

    rows = await _new_rows(db_session)
    assert [r.event_type for r in rows] == ["login_success", "login_failed", "login_failed", "logout", "login_failed"]
    assert report.written == 5
    assert report.scanned == 5, "the administrative event is not even a candidate"

    success, bad, ghost, out, saml = rows
    assert success.auth_method == "ldap"
    assert success.outcome == "success"
    assert bad.reason_code == "bad_password"
    assert bad.user_id == user.id
    assert ghost.user_id is None
    assert ghost.username == "ghost", "the typed name lived in detail_json"
    assert ghost.reason_code == "unknown"
    assert out.scope == "all_sessions"
    assert saml.reason_code == "saml_rejected"
    assert saml.auth_method == "saml"
    assert saml.reason_detail == "assertion_invalid"
    assert all(r.backfilled for r in rows)
    assert all(r.session_id is None for r in rows), "no jti existed for these"
    assert {r.ip for r in rows} == {"203.0.113.5"}


async def test_running_it_twice_writes_nothing_the_second_time(db_session, user):
    db_session.add(_legacy("login_success", user=user, detail={"provider": "local"}))
    await db_session.commit()

    first = await backfill_auth_events(db_session)
    second = await backfill_auth_events(db_session)

    assert first.written == 1
    assert second.written == 0
    assert second.skipped_existing == 1
    assert len(await _new_rows(db_session)) == 1


async def test_a_redacted_failure_is_carried_without_inventing_a_reason(db_session, user):
    db_session.add(_legacy("login_failed", user=user, redacted=True))
    await db_session.commit()

    report = await backfill_auth_events(db_session)

    row = (await _new_rows(db_session))[0]
    assert row.event_type == "login_failed"
    assert row.reason_code == "unknown"
    assert row.reason_detail is None
    assert row.backfilled is True
    assert report.redacted == 1


async def test_a_method_the_detail_never_recorded_comes_from_the_account(db_session, user):
    user.auth_provider = "saml"
    db_session.add(_legacy("login_success", user=user, detail={}))
    await db_session.commit()

    await backfill_auth_events(db_session)
    assert (await _new_rows(db_session))[0].auth_method == "saml"


async def test_the_run_itself_goes_in_the_security_trail(db_session, user):
    db_session.add(_legacy("login_success", user=user, detail={"provider": "local"}))
    await db_session.commit()
    report = await backfill_auth_events(db_session)
    await record_backfill_run(db_session, report)

    trail = (
        (
            await db_session.execute(
                select(SecurityAuditEvent).where(SecurityAuditEvent.action == "auth_events_backfilled")
            )
        )
        .scalars()
        .all()
    )
    assert len(trail) == 1
    detail = json.loads(trail[0].detail_json)
    assert detail["written"] == 1
    assert detail["by_type"] == {"login_success": 1}
