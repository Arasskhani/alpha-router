"""Revision e1a3c5f7b9d2: the Exchange EWS mail connection tables.

Run for real against a file-backed SQLite database through Alembic's own
operations, and compared with the ORM so a mismatch shows up locally rather
than only in the PostgreSQL drift gate.
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
_TABLES = ("mail_connections", "mail_connection_mailboxes", "mail_item_refs", "mail_drafts", "mail_action_items")
_NOW = "'2026-10-25 08:00:00'"


def _revision():
    path = next((_BACKEND / "alembic" / "versions").glob("e1a3c5f7b9d2_*.py"))
    spec = importlib.util.spec_from_file_location("_rev_mail_connections", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mail.sqlite'}")

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


def _connection_sql(**overrides: str) -> str:
    values = {
        "id": "1",
        "user_id": "1",
        "provider": "'exchange_ews'",
        "login": "'CORP\\\\sara'",
        "secret_encrypted": "'x'",
        "primary_smtp": "'sara@corp.example'",
        "status": "'connected'",
        "consecutive_failures": "0",
        "notify_enabled": "1",
        "connected_at": _NOW,
        "updated_at": _NOW,
        **overrides,
    }
    return f"INSERT INTO mail_connections ({', '.join(values)}) VALUES ({', '.join(values.values())})"


def test_upgrade_adds_empty_tables_whose_constraints_hold(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    assert set(_TABLES) <= set(sa.inspect(database).get_table_names())
    with database.connect() as conn:
        for table in _TABLES:
            assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    for bad in ({"status": "'paused'"}, {"provider": "'imap'"}):
        with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text(_connection_sql(**bad)))
    with database.begin() as conn:
        conn.execute(sa.text(_connection_sql()))
    with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(sa.text(_connection_sql(id="2")))  # one connection per person
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO mail_connection_mailboxes (connection_id, smtp, kind, source, enabled, notify, created_at) "
                f"VALUES (1, 'sara@corp.example', 'own', 'own', 1, 1, {_NOW})"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO mail_item_refs (user_id, ref, mailbox_smtp, item_id, created_at) "
                f"VALUES (1, 'm1', 'sara@corp.example', 'AAMk', {_NOW})"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO mail_drafts (user_id, mailbox_smtp, item_id, kind, subject, to_json, cc_json, "
                f"body_preview, status, created_at, updated_at) VALUES (1, 'sara@corp.example', 'AAMk', 'reply', "
                f"'Re: budget', '[]', '[]', '', 'draft', {_NOW}, {_NOW})"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO mail_action_items (user_id, mailbox_smtp, item_key, item_id, subject, reason, action, "
                f"source, status, created_at) VALUES (1, 'sara@corp.example', 'k1', 'AAMk', 'Budget', 'Asks you', "
                f"'reply', 'rules', 'new', {_NOW})"
            )
        )
    with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO mail_connection_mailboxes (connection_id, smtp, kind, source, enabled, notify, created_at) "
                f"VALUES (1, 'sara@corp.example', 'own', 'own', 1, 1, {_NOW})"
            )
        )
    with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO mail_drafts (user_id, mailbox_smtp, item_id, kind, subject, to_json, cc_json, "
                f"body_preview, status, created_at, updated_at) VALUES (1, 'x', 'y', 'send_now', '', '[]', '[]', "
                f"'', 'draft', {_NOW}, {_NOW})"
            )
        )
    # A draft one request is sending is claimed with 'sending'; other states are refused.
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO mail_drafts (user_id, mailbox_smtp, item_id, kind, subject, to_json, cc_json, "
                f"body_preview, status, created_at, updated_at) VALUES (1, 'x', 'y2', 'new', '', '[]', '[]', "
                f"'', 'sending', {_NOW}, {_NOW})"
            )
        )
    with database.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO mail_drafts (user_id, mailbox_smtp, item_id, kind, subject, to_json, cc_json, "
                f"body_preview, status, created_at, updated_at) VALUES (1, 'x', 'y3', 'new', '', '[]', '[]', "
                f"'', 'queued', {_NOW}, {_NOW})"
            )
        )
    # Deleting the person deletes everything of theirs.
    with database.begin() as conn:
        conn.execute(sa.text("DELETE FROM users WHERE id = 1"))
    with database.connect() as conn:
        for table in _TABLES:
            assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_the_revision_builds_what_the_orm_describes(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    metadata = sa.MetaData()
    for table in [Base.metadata.tables["users"], *(Base.metadata.tables[name] for name in _TABLES)]:
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
