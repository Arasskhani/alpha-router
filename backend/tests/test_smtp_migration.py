"""Revision 4ce0678f5e1c: the old "Use TLS" switch becomes an explicit mode.

Run for real against a file-backed SQLite database through Alembic's own
operations (the batch mode that SQLite needs for a column drop included).
PostgreSQL gets the same revision through the schema drift gate, which runs
the whole chain and compares it with the ORM.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.services.smtp_service import security_from_legacy

_BACKEND = Path(__file__).resolve().parents[1]

# (use_tls, port) -> what the row must say afterwards.
CASES = [
    (1, 587, "starttls"),  # the shipped default that never worked
    (1, 25, "starttls"),
    (1, 2525, "starttls"),
    (1, 465, "ssl"),  # worked before, works the same
    (1, 2465, "ssl"),
    (0, 587, "starttls"),  # "if offered" becomes required
    (0, 25, "starttls"),
    (None, 587, "starttls"),
]


def _revision(revision: str = "4ce0678f5e1c"):
    path = next((_BACKEND / "alembic" / "versions").glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_rev_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'smtp.sqlite'}")
    yield engine
    engine.dispose()


def _old_table(engine) -> None:
    """smtp_settings exactly as the legacy baseline created it."""

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE smtp_settings (id INTEGER PRIMARY KEY, host VARCHAR(255) NOT NULL, port INTEGER, "
                "username VARCHAR(255), password_encrypted TEXT, from_address VARCHAR(255) NOT NULL, "
                "use_tls BOOLEAN, updated_at DATETIME)"
            )
        )
        for index, (use_tls, port, _) in enumerate(CASES, start=1):
            conn.execute(
                sa.text(
                    "INSERT INTO smtp_settings (id, host, port, from_address, use_tls) "
                    "VALUES (:id, 'mail.example.com', :port, 'r@example.com', :use_tls)"
                ),
                {"id": index, "port": port, "use_tls": use_tls},
            )


def _run(engine, monkeypatch, step: str, revision: str = "4ce0678f5e1c") -> None:
    module = _revision(revision)
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        getattr(module, step)()


def _columns(engine) -> set[str]:
    return {c["name"] for c in sa.inspect(engine).get_columns("smtp_settings")}


def _security_by_id(engine) -> dict[int, str]:
    with engine.connect() as conn:
        return dict(conn.execute(sa.text("SELECT id, security FROM smtp_settings")).all())


def test_each_row_keeps_what_its_switch_meant(database, monkeypatch):
    _old_table(database)
    _run(database, monkeypatch, "upgrade")

    assert "use_tls" not in _columns(database)
    assert "security" in _columns(database)
    assert _security_by_id(database) == {index: expected for index, (_, _, expected) in enumerate(CASES, start=1)}


def test_the_page_compatibility_rule_is_the_same_rule():
    """A page loaded before the upgrade still sends use_tls; it must land where
    the migration would have put it."""

    for use_tls, port, expected in CASES:
        assert security_from_legacy(None if use_tls is None else bool(use_tls), port) == expected


def test_running_it_again_changes_nothing(database, monkeypatch):
    _old_table(database)
    _run(database, monkeypatch, "upgrade")
    before = _security_by_id(database)
    _run(database, monkeypatch, "upgrade")
    assert _security_by_id(database) == before


def test_a_new_row_defaults_to_starttls(database, monkeypatch):
    _old_table(database)
    _run(database, monkeypatch, "upgrade")
    with database.begin() as conn:
        conn.execute(sa.text("INSERT INTO smtp_settings (id, host, from_address) VALUES (99, 'h', 'a@b')"))
    assert _security_by_id(database)[99] == "starttls"


def test_downgrade_puts_the_switch_back(database, monkeypatch):
    _old_table(database)
    _run(database, monkeypatch, "upgrade")
    with database.begin() as conn:
        conn.execute(sa.text("UPDATE smtp_settings SET security = 'none' WHERE id = 1"))
    _run(database, monkeypatch, "downgrade")

    assert "security" not in _columns(database)
    with database.connect() as conn:
        switch = dict(conn.execute(sa.text("SELECT id, use_tls FROM smtp_settings")).all())
    # Only SSL/TLS was "on"; STARTTLS and none both go back to "off".
    assert switch[4] == 1 and switch[5] == 1
    assert switch[1] == 0 and switch[2] == 0 and switch[6] == 0


def test_a_database_without_the_table_is_left_alone(database, monkeypatch):
    _run(database, monkeypatch, "upgrade")
    _run(database, monkeypatch, "downgrade")
    assert "smtp_settings" not in sa.inspect(database).get_table_names()


def test_existing_rows_keep_verifying_certificates(database, monkeypatch):
    """Revision 3e27b36f9d8f: the self-signed exception starts switched off."""

    _old_table(database)
    _run(database, monkeypatch, "upgrade")
    _run(database, monkeypatch, "upgrade", "3e27b36f9d8f")
    with database.connect() as conn:
        values = {row[0] for row in conn.execute(sa.text("SELECT verify_certificate FROM smtp_settings"))}
    assert values == {1}

    _run(database, monkeypatch, "upgrade", "3e27b36f9d8f")  # again: nothing to do
    _run(database, monkeypatch, "downgrade", "3e27b36f9d8f")
    assert "verify_certificate" not in _columns(database)
    _run(database, monkeypatch, "downgrade", "3e27b36f9d8f")  # again: nothing to do


def test_the_certificate_revision_leaves_a_missing_table_alone(database, monkeypatch):
    _run(database, monkeypatch, "upgrade", "3e27b36f9d8f")
    _run(database, monkeypatch, "downgrade", "3e27b36f9d8f")
    assert "smtp_settings" not in sa.inspect(database).get_table_names()


_PG_URL = os.environ.get("DATABASE_URL", "")


@pytest.mark.skipif(not _PG_URL.startswith("postgresql"), reason="PostgreSQL only (set DATABASE_URL)")
async def test_postgres_reads_the_boolean_switch_the_same_way():
    """The same rows through the real chain on PostgreSQL, where use_tls is a
    true boolean rather than SQLite's 0/1."""

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.test_schema_baseline import _with_scratch_database

    async def check(url: str) -> None:
        from app import config as app_config

        config = Config(str(_BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(_BACKEND / "alembic"))
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        app_config.get_settings.cache_clear()
        engine = create_async_engine(url)
        try:
            await asyncio.to_thread(command.upgrade, config, "5dca7b7bddf9")
            async with engine.begin() as conn:
                for index, (use_tls, port, _) in enumerate(CASES, start=1):
                    await conn.execute(
                        sa.text(
                            "INSERT INTO smtp_settings (id, host, port, from_address, use_tls) "
                            "VALUES (:id, 'mail.example.com', :port, 'r@example.com', :use_tls)"
                        ),
                        {"id": index, "port": port, "use_tls": None if use_tls is None else bool(use_tls)},
                    )
            await asyncio.to_thread(command.upgrade, config, "4ce0678f5e1c")
            async with engine.connect() as conn:
                rows = dict((await conn.execute(sa.text("SELECT id, security FROM smtp_settings"))).all())
            assert rows == {index: expected for index, (_, _, expected) in enumerate(CASES, start=1)}

            await asyncio.to_thread(command.downgrade, config, "5dca7b7bddf9")
            async with engine.connect() as conn:
                switch = dict((await conn.execute(sa.text("SELECT id, use_tls FROM smtp_settings"))).all())
            assert switch[4] is True and switch[5] is True
            assert switch[1] is False and switch[6] is False
        finally:
            await engine.dispose()
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
            app_config.get_settings.cache_clear()

    await _with_scratch_database(check)
