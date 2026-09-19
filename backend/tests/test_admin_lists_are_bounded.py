"""No administrative list returns an unbounded number of rows.

`/admin/users`, `/admin/deleted-users`, `/admin/user-api-keys`,
`/admin/models`, `/groups` and `/admin-knowledge/bases` had no LIMIT in the
query, no paging in the API and a frontend that rendered everything. On a
directory of any size the page is slow; on a large one the worker's memory is
the only limit. `deleted-users` is the sharpest: it only ever grows.

A cap alone would be a lie, so every one of these endpoints also says whether
it left anything out.
"""

from __future__ import annotations

import pytest
from fastapi import Response

from app.core.security import hash_password
from app.models.user import User
from app.services.list_bounds import (
    ADMIN_LIST_HARD_CAP,
    capped,
    mark_truncated,
    split_overflow,
)


def test_the_cap_is_a_real_ceiling():
    assert 100 <= ADMIN_LIST_HARD_CAP <= 20_000


def test_one_row_beyond_the_cap_is_fetched_so_more_can_be_detected():
    from sqlalchemy import select

    statement = capped(select(User), cap=5)
    assert statement._limit_clause is not None
    assert statement._limit_clause.value == 6


@pytest.mark.parametrize(
    ("fetched", "expected_len", "expected_truncated"),
    [(4, 4, False), (5, 5, False), (6, 5, True)],
)
def test_the_overflow_row_is_dropped_and_reported(fetched, expected_len, expected_truncated):
    page, truncated = split_overflow(list(range(fetched)), cap=5)
    assert len(page) == expected_len
    assert truncated is expected_truncated


@pytest.mark.parametrize("truncated", [True, False])
def test_the_header_is_always_set(truncated):
    """Absence of the header must not have to mean anything."""

    response = Response()
    mark_truncated(response, truncated, cap=5)
    assert response.headers["X-List-Truncated"] == ("true" if truncated else "false")
    assert response.headers["X-List-Cap"] == "5"


def _user_list_args(response, db_session) -> dict:
    """Calling the handler directly means supplying what Query() would."""

    return {
        "q": None,
        "username": None,
        "email": None,
        "department": None,
        "job_title": None,
        "role": None,
        "is_active": None,
        "group_id": None,
        "plan_id": None,
        "no_plan": False,
        "user_id": None,
        "online": None,
        "picker": False,
        "limit": None,
        "offset": 0,
        "response": response,
        "db": db_session,
        "_": None,
    }


async def _people(db_session, prefix: str, count: int, **overrides) -> None:
    import datetime

    for index in range(count):
        values = {
            "username": f"{prefix}_{index}",
            "hashed_password": hash_password("a-password"),
            "auth_provider": "local",
            "is_active": True,
        }
        values.update(overrides)
        db_session.add(User(**values))
    del datetime
    await db_session.flush()


async def test_the_user_list_stops_at_the_cap(db_session, monkeypatch):
    from app.api import admin as admin_api

    monkeypatch.setattr(admin_api, "ADMIN_LIST_HARD_CAP", 3)
    await _people(db_session, "listed", 5)
    await db_session.commit()

    response = Response()
    rows = await admin_api.list_users(**_user_list_args(response, db_session))

    assert len(rows) == 3
    assert response.headers["X-List-Truncated"] == "true"


async def test_the_deleted_user_list_stops_at_the_cap(db_session, monkeypatch):
    import datetime

    from app.api import admin as admin_api

    monkeypatch.setattr(admin_api, "ADMIN_LIST_HARD_CAP", 2)
    await _people(db_session, "gone", 4, deleted_at=datetime.datetime.utcnow(), is_active=False)
    await db_session.commit()

    response = Response()
    rows = await admin_api.list_deleted_users(
        q=None,
        username=None,
        email=None,
        department=None,
        job_title=None,
        role=None,
        is_active=None,
        response=response,
        db=db_session,
        _=None,
    )

    assert len(rows) == 2
    assert response.headers["X-List-Truncated"] == "true"


async def test_a_short_list_is_not_reported_as_truncated(db_session, monkeypatch):
    from app.api import admin as admin_api

    monkeypatch.setattr(admin_api, "ADMIN_LIST_HARD_CAP", 50)
    await _people(db_session, "few", 3)
    await db_session.commit()

    response = Response()
    rows = await admin_api.list_users(**_user_list_args(response, db_session))

    assert len(rows) == 3
    assert response.headers["X-List-Truncated"] == "false"
