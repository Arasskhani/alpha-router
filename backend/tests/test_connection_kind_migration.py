"""Revision b7d9f1a3c5e7: connections get a kind.

Run for real against a file-backed SQLite database through Alembic's own
operations (batch mode included). PostgreSQL gets the same revision through
the schema drift gate, which runs the whole chain and compares it with the ORM.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_BACKEND = Path(__file__).resolve().parents[1]


def _revision(revision: str = "b7d9f1a3c5e7"):
    path = next((_BACKEND / "alembic" / "versions").glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_rev_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'connections.sqlite'}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE connections (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, "
                "provider_type VARCHAR(64) NOT NULL, adapter_key VARCHAR(64), api_key_encrypted TEXT NOT NULL, "
                "base_url VARCHAR(512), is_active BOOLEAN, sync_enabled BOOLEAN, sync_interval_hours INTEGER, "
                "last_sync_at DATETIME, created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO connections (id, name, provider_type, api_key_encrypted) VALUES (1, 'OR', 'openrouter', 'x')"
            )
        )
    yield engine
    engine.dispose()


def _run(engine, monkeypatch, step: str) -> None:
    module = _revision()
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        getattr(module, step)()


def _rows(engine) -> list[tuple]:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT id, kind, priority, price_per_request_usd FROM connections ORDER BY id")
        ).all()


def test_every_existing_connection_is_a_model_provider(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    assert _rows(database) == [(1, "models", 100, 0)]


def test_a_kind_outside_the_two_is_refused(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    with pytest.raises(sa.exc.IntegrityError), database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO connections (id, name, provider_type, api_key_encrypted, kind) "
                "VALUES (2, 'x', 'brave', 'x', 'search')"
            )
        )


def test_downgrade_drops_the_web_search_connections_and_the_columns(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO connections (id, name, provider_type, api_key_encrypted, kind) "
                "VALUES (2, 'Brave', 'brave', 'x', 'web_search')"
            )
        )
    _run(database, monkeypatch, "downgrade")
    columns = {c["name"] for c in sa.inspect(database).get_columns("connections")}
    assert not {"kind", "config_json", "priority", "price_per_request_usd"} & columns
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT id FROM connections")).scalars().all() == [1]
