"""Revision d9f1b3c5e7a9: the Support tickets tables.

Run for real against a file-backed SQLite database through Alembic's own
operations. PostgreSQL gets the same revision through the schema drift gate,
which runs the whole chain and compares it with the ORM; the comparison here
covers the same ground for these three tables on SQLite, so a mismatch shows
up locally rather than only in CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.models as _orm_models  # noqa: F401 -- registers every ORM table on Base.metadata
from app.database import Base

_BACKEND = Path(__file__).resolve().parents[1]
_TABLES = ("support_tickets", "support_ticket_messages", "support_ticket_attachments")


def _revision():
    path = next((_BACKEND / "alembic" / "versions").glob("d9f1b3c5e7a9_*.py"))
    spec = importlib.util.spec_from_file_location("_rev_support_tickets", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'tickets.sqlite'}")

    @sa.event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
    yield engine
    engine.dispose()


def _run(engine, monkeypatch, step: str) -> None:
    module = _revision()
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        getattr(module, step)()


def _ticket_sql(**overrides: str) -> str:
    values = {
        "id": "1",
        "number": "1001",
        "user_id": "1",
        "reporter_name": "'Sara'",
        "reporter_username": "'sara'",
        "title": "'Export fails'",
        "category": "'Bug'",
        "priority": "'normal'",
        "status": "'open'",
        "user_unread": "0",
        "needs_staff": "1",
        "created_at": "'2026-10-22 08:00:00'",
        "updated_at": "'2026-10-22 08:00:00'",
        "reopened_count": "0",
        **overrides,
    }
    return f"INSERT INTO support_tickets ({', '.join(values)}) VALUES ({', '.join(values.values())})"


def test_upgrade_adds_empty_tables_whose_constraints_hold(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    assert set(_TABLES) <= set(sa.inspect(database).get_table_names())
    with database.connect() as conn:
        for table in _TABLES:
            assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    for bad in ({"priority": "'critical'"}, {"status": "'pending'"}, {"closed_reason": "'spam'"}):
        with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text(_ticket_sql(**bad)))
    with database.begin() as conn:
        conn.execute(sa.text(_ticket_sql()))
    with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(sa.text(_ticket_sql(id="2")))  # the same number twice
    with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO support_ticket_messages (ticket_id, kind, body, created_at) "
                "VALUES (1, 'shout', '', '2026-10-22 08:00:00')"
            )
        )
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO support_ticket_messages (id, ticket_id, kind, body, created_at) "
                "VALUES (1, 1, 'user', 'It fails', '2026-10-22 08:00:00')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO support_ticket_attachments (ticket_id, message_id, storage_key, mime, bytes, width, "
                "height, sha256, display_name, created_at) VALUES (1, 1, 'tickets/a.png', 'image/png', 10, 1, 1, "
                "'00', 'a.png', '2026-10-22 08:00:00')"
            )
        )
    # Deleting the person deletes their tickets, and with them the thread and its images.
    with database.begin() as conn:
        conn.execute(sa.text("DELETE FROM users WHERE id = 1"))
    with database.connect() as conn:
        for table in _TABLES:
            assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_the_revision_builds_what_the_orm_describes(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    tables = [Base.metadata.tables[name] for name in _TABLES]
    metadata = sa.MetaData()
    for table in [Base.metadata.tables["users"], *tables]:
        table.to_metadata(metadata)
    with database.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_object": lambda _obj, name, type_, _reflected, _other: type_ != "table" or name in _TABLES,
                "compare_type": True,
            },
        )
        diff = compare_metadata(context, metadata)
    assert diff == []


def test_downgrade_removes_them_again(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    _run(database, monkeypatch, "downgrade")
    assert not set(_TABLES) & set(sa.inspect(database).get_table_names())
