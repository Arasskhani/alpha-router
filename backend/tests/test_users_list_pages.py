"""/admin/users pages in the database, exactly, under every filter.

Paging this list was deferred because two of its filters ran in Python after
the query - the effective-plan filter and the presence ("online") filter - so
a LIMIT placed before them yielded ragged pages that hid accounts without
saying so. The plan filter is now decided by the query. Presence cannot be:
it lives in Redis as one key per user and the keyspace is never scanned, so
the online page is built from the filtered *ids* (one indexed column, one
MGET) and only the page's rows are loaded in full.

Without ``limit`` the endpoint behaves exactly as before - the whole list
under the hard cap with X-List-Truncated - so no existing consumer changes.
"""

from __future__ import annotations

from fastapi import Response

from app.api import admin as admin_api
from app.core.security import hash_password
from app.models.user import User
from app.services import presence_service


def _args(response, db, **overrides) -> dict:
    base = {
        "q": None, "username": None, "email": None, "department": None, "job_title": None, "role": None,
        "is_active": None, "group_id": None, "plan_id": None, "no_plan": False, "user_id": None,
        "online": None, "picker": False, "limit": None, "offset": 0, "response": response, "db": db, "_": None,
    }
    base.update(overrides)
    return base


async def _people(db_session, count: int) -> list[User]:
    rows = [
        User(username=f"paged_{i:03d}", hashed_password=hash_password("x"), auth_provider="local", is_active=True)
        for i in range(count)
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return rows


async def test_a_page_is_exactly_the_requested_slice_in_list_order(db_session):
    await _people(db_session, 7)

    r1 = Response()
    page1 = await admin_api.list_users(**_args(r1, db_session, limit=3, offset=0))
    r2 = Response()
    page2 = await admin_api.list_users(**_args(r2, db_session, limit=3, offset=3))
    r3 = Response()
    page3 = await admin_api.list_users(**_args(r3, db_session, limit=3, offset=6))

    assert [u["username"] for u in page1] == ["paged_000", "paged_001", "paged_002"]
    assert [u["username"] for u in page2] == ["paged_003", "paged_004", "paged_005"]
    assert [u["username"] for u in page3] == ["paged_006"]
    assert r1.headers["X-Has-More"] == "true"
    assert r3.headers["X-Has-More"] == "false"
    assert r1.headers["X-List-Total"] == "7"


async def test_the_online_filter_pages_over_online_users_only(db_session, monkeypatch):
    """Presence decides membership before the page is cut, so a page of three
    online users is three online users - not three users of whom some are online."""

    people = await _people(db_session, 9)
    online = {people[i].id for i in (0, 2, 4, 6, 8)}

    async def fake_online(ids):
        return {i for i in ids if i in online}

    monkeypatch.setattr(presence_service, "presence_enabled", lambda: True)
    monkeypatch.setattr(presence_service, "online_user_ids", fake_online)

    r1 = Response()
    page1 = await admin_api.list_users(**_args(r1, db_session, online=True, limit=3, offset=0))
    r2 = Response()
    page2 = await admin_api.list_users(**_args(r2, db_session, online=True, limit=3, offset=3))

    assert [u["username"] for u in page1] == ["paged_000", "paged_002", "paged_004"]
    assert [u["username"] for u in page2] == ["paged_006", "paged_008"]
    assert r1.headers["X-List-Total"] == "5"
    assert r1.headers["X-Has-More"] == "true"
    assert r2.headers["X-Has-More"] == "false"
    assert all(u["online"] is True for u in page1)


async def test_when_presence_is_unavailable_the_online_filter_is_ignored_not_empty(db_session, monkeypatch):
    await _people(db_session, 4)

    async def unavailable(ids):
        return None

    monkeypatch.setattr(presence_service, "online_user_ids", unavailable)

    response = Response()
    page = await admin_api.list_users(**_args(response, db_session, online=True, limit=10, offset=0))

    assert len(page) == 4, "Redis being down must not read as 'nobody is online'"
    assert all(u["online"] is None for u in page)


async def test_without_a_limit_the_endpoint_is_unchanged(db_session):
    await _people(db_session, 5)

    response = Response()
    rows = await admin_api.list_users(**_args(response, db_session))

    assert len(rows) == 5
    assert response.headers["X-List-Truncated"] == "false"
    assert "X-Has-More" not in response.headers
