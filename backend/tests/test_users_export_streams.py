"""The users CSV export is produced page by page, and is complete.

The export was deliberately left uncapped when the admin lists got a ceiling:
truncating an export silently is worse than a slow one. But "uncapped" meant
every user built as a dict, plus the whole CSV as one string, in memory at
once. Now it walks the directory in keyset pages on username - the list's own
sort order - and emits each page as it goes. Every row still arrives; the peak
is one page.
"""

from __future__ import annotations

import csv
import io

from app.api import admin as admin_api
from app.core.security import hash_password
from app.models.user import User


class _CountingSession:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.selects_of_users = 0

    async def execute(self, statement, *args, **kwargs):
        text = str(statement)
        if text.lstrip().upper().startswith("SELECT") and "FROM users" in text and "LIMIT" in text.upper():
            self.selects_of_users += 1
        return await self._inner.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def _people(db_session, count: int) -> None:
    for index in range(count):
        db_session.add(
            User(
                username=f"exported_{index:03d}",
                hashed_password=hash_password("a-password"),
                auth_provider="local",
                is_active=True,
            )
        )
    await db_session.commit()


async def _collect(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks).decode("utf-8-sig")


def _export_args(db):
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
        "online": None,
        "db": db,
        "_": None,
    }


async def test_every_user_is_exported_across_several_pages(db_session, monkeypatch):
    monkeypatch.setattr(admin_api, "USERS_EXPORT_PAGE_SIZE", 4)
    await _people(db_session, 10)

    counting = _CountingSession(db_session)
    response = await admin_api.export_users(**_export_args(counting))
    text = await _collect(response)

    rows = list(csv.DictReader(io.StringIO(text)))
    assert [row["Username"] for row in rows] == [f"exported_{i:03d}" for i in range(10)], (
        "every user, once, in the list's order"
    )
    assert counting.selects_of_users >= 3, "ten users at four a page is at least three windows"


async def test_the_header_comes_first_and_the_bom_once(db_session, monkeypatch):
    monkeypatch.setattr(admin_api, "USERS_EXPORT_PAGE_SIZE", 3)
    await _people(db_session, 5)

    response = await admin_api.export_users(**_export_args(db_session))
    raw = b"".join([c if isinstance(c, bytes) else c.encode() async for c in response.body_iterator])

    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\xef\xbb\xbf") == 1, "a BOM per page would corrupt the file"
    assert raw.decode("utf-8-sig").splitlines()[0].startswith("Username,")


async def test_a_page_that_the_python_filters_empty_does_not_end_the_export(db_session, monkeypatch):
    """The plan filter runs after the query. A window whose users all fail it
    must not be mistaken for the end of the table."""

    monkeypatch.setattr(admin_api, "USERS_EXPORT_PAGE_SIZE", 3)
    await _people(db_session, 7)
    # no user has a plan: `no_plan=True` keeps everyone; `plan_id=999` keeps nobody
    args = _export_args(db_session)
    args["no_plan"] = True

    response = await admin_api.export_users(**args)
    rows = list(csv.DictReader(io.StringIO(await _collect(response))))
    assert len(rows) == 7


async def test_an_empty_directory_is_a_header_only_file(db_session):
    response = await admin_api.export_users(**_export_args(db_session))
    text = await _collect(response)
    assert text.splitlines() == [admin_api._admin_users_csv_header().rstrip("\n")]
