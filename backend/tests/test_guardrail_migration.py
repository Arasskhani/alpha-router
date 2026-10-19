"""Revision c8e0a2b4d6f8: the Guardrails tables and connections' trust level.

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
_TABLES = ("guardrail_patterns", "guardrail_rules", "guardrail_rule_assignments", "guardrail_events")


def _revision():
    path = next((_BACKEND / "alembic" / "versions").glob("c8e0a2b4d6f8_*.py"))
    spec = importlib.util.spec_from_file_location("_rev_guardrails", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'guardrails.sqlite'}")
    with engine.begin() as conn:
        for table in ("users", "user_groups", "ai_models", "alpha_router_api_keys"):
            conn.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        conn.execute(
            sa.text(
                "CREATE TABLE connections (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, "
                "kind VARCHAR(16) NOT NULL DEFAULT 'models')"
            )
        )
        conn.execute(sa.text("INSERT INTO connections (id, name) VALUES (1, 'OpenRouter')"))
    yield engine
    engine.dispose()


def _run(engine, monkeypatch, step: str) -> None:
    module = _revision()
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        getattr(module, step)()


def test_upgrade_adds_empty_tables_and_makes_every_connection_public(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    names = set(sa.inspect(database).get_table_names())
    assert set(_TABLES) <= names
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT trust_level FROM connections")).scalar_one() == "public"
        for table in _TABLES:
            assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("UPDATE connections SET trust_level = 'friendly'"))


def test_downgrade_removes_them_again(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    _run(database, monkeypatch, "downgrade")
    inspector = sa.inspect(database)
    assert not set(_TABLES) & set(inspector.get_table_names())
    assert "trust_level" not in {c["name"] for c in inspector.get_columns("connections")}
