"""Tests for server-local schedule timezone helpers."""

from app.services.schedule_timezone import get_server_timezone, server_timezone_label


def test_get_server_timezone_returns_tzinfo():
    tz = get_server_timezone()
    assert tz is not None
    assert server_timezone_label()
