"""db-init retries while the database is still coming up, then fails loudly."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from app import migrate


def test_retries_operational_errors_then_succeeds():
    calls = {"n": 0}

    def step():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OperationalError("connect", {}, Exception("connection refused"))

    with patch.object(migrate, "_CONNECT_BACKOFF_SECONDS", (0, 0, 0, 0, 0)), patch("time.sleep"):
        migrate._with_db_retry(step, "x")
    assert calls["n"] == 3


def test_gives_up_with_a_clear_exit_after_max_attempts():
    def step():
        raise OperationalError("connect", {}, Exception("still down"))

    with patch.object(migrate, "_CONNECT_BACKOFF_SECONDS", (0,)), patch("time.sleep"):
        with pytest.raises(SystemExit, match="failed after"):
            migrate._with_db_retry(step, "alembic upgrade")


def test_non_connection_errors_are_not_retried():
    calls = {"n": 0}

    def step():
        calls["n"] += 1
        raise ValueError("bad migration")

    with pytest.raises(ValueError):
        migrate._with_db_retry(step, "x")
    assert calls["n"] == 1
