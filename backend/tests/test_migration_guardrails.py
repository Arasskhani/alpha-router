"""Two properties of the migration machinery that nothing else covers.

Both are failure modes that only appear on a real installation: a downgrade
against a database that predates a table, and a migration that waits forever
for a lock on a busy one. Neither shows up in a fresh-database gate.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


def _load_revision(prefix: str):
    matches = sorted((_BACKEND / "alembic" / "versions").glob(f"{prefix}*.py"))
    assert matches, f"no revision file for {prefix}"
    spec = importlib.util.spec_from_file_location(f"_rev_{prefix}", matches[0])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Recorder:
    """Stands in for ``op``: records the SQL a migration would run."""

    def __init__(self, *, dialect: str, tables: set[str]) -> None:
        self.statements: list[str] = []
        self._tables = tables
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))

    def get_bind(self):
        return self._bind

    def execute(self, statement) -> None:
        self.statements.append(str(statement))


@pytest.fixture
def money_revision(monkeypatch):
    module = _load_revision("5c1d2e3f4a5b")

    def install(*, tables: set[str], dialect: str = "postgresql") -> _Recorder:
        recorder = _Recorder(dialect=dialect, tables=tables)
        monkeypatch.setattr(module, "op", recorder)
        monkeypatch.setattr(
            module.sa,
            "inspect",
            lambda bind: SimpleNamespace(get_table_names=lambda: sorted(tables)),
        )
        return recorder

    return module, install


def test_the_money_downgrade_skips_a_table_that_is_not_there(money_revision):
    """``upgrade`` checks; ``downgrade`` did not, and raised on the first absent table.

    An installation that predates ``budget_plans`` upgrades fine and then cannot
    roll back - which is exactly when a rollback is being attempted.
    """

    module, install = money_revision
    present = {"users", "request_logs"}
    recorder = install(tables=present)

    module.downgrade()

    touched = {statement.split()[2] for statement in recorder.statements}
    assert touched <= present, f"downgrade touched a table that is not in the database: {touched - present}"
    assert touched, "the downgrade did nothing at all"


def test_the_money_downgrade_still_reverts_every_column_it_finds(money_revision):
    module, install = money_revision
    every = {table for table, _ in module._MONEY + module._PRICE}
    recorder = install(tables=every)

    module.downgrade()

    assert len(recorder.statements) == len(module._MONEY + module._PRICE)


def test_the_money_downgrade_is_a_no_op_off_postgres(money_revision):
    module, install = money_revision
    recorder = install(tables={"users"}, dialect="sqlite")

    module.downgrade()

    assert recorder.statements == []


def _sync_migrations_ast() -> ast.FunctionDef:
    tree = ast.parse((_BACKEND / "alembic" / "env.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_run_sync_migrations":
            return node
    raise AssertionError("_run_sync_migrations is gone")


def test_the_session_settings_are_issued_inside_alembic_s_own_transaction():
    """Not before it.

    ``_run_async_migrations`` uses ``connectable.connect()``, not ``.begin()``.
    A statement on that connection before ``context.begin_transaction()`` opens
    an implicit transaction; alembic's own then nests inside it and never
    commits, so the migrations report success and write nothing - not even the
    ``alembic_version`` row.
    """

    function = _sync_migrations_ast()
    inside = {
        node.lineno
        for statement in function.body
        if isinstance(statement, ast.With)
        for node in ast.walk(statement)
        if isinstance(node, ast.Attribute) and node.attr == "exec_driver_sql"
    }
    everywhere = {
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute) and node.attr == "exec_driver_sql"
    }
    assert everywhere, "no session settings are applied at all"
    assert everywhere == inside, "a statement runs before alembic opens its transaction"
