"""/ready readiness probe: required vs degraded dependencies and bounded timeouts."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.services import readiness_service as rs


async def _ok() -> None:
    return None


async def _boom() -> None:
    raise ConnectionError("x")


async def _slow() -> None:
    await asyncio.sleep(5)


def test_degraded_dependency_does_not_fail_probe():
    with (
        patch.object(rs, "_check_database", _ok),
        patch.object(rs, "_check_redis", _ok),
        patch.object(rs, "_check_qdrant", _boom),
        patch.object(rs, "_check_object_storage", _ok),
    ):
        report = asyncio.run(rs.readiness_report())
    assert report.ready is True
    payload = report.payload()
    assert payload["status"] == "ready"
    assert payload["checks"]["qdrant"]["ok"] is False
    assert payload["checks"]["qdrant"]["required"] is False
    assert payload["checks"]["qdrant"]["detail"] == "ConnectionError"


def test_required_dependency_failure_makes_probe_unavailable():
    with (
        patch.object(rs, "_check_database", _boom),
        patch.object(rs, "_check_redis", _ok),
        patch.object(rs, "_check_qdrant", _ok),
        patch.object(rs, "_check_object_storage", _ok),
    ):
        report = asyncio.run(rs.readiness_report())
    assert report.ready is False
    assert report.payload()["status"] == "unavailable"
    assert report.payload()["checks"]["database"]["detail"] == "ConnectionError"


def test_hung_dependency_is_bounded_by_timeout(monkeypatch):
    monkeypatch.setattr(rs, "CHECK_TIMEOUT_SECONDS", 0.2)
    with (
        patch.object(rs, "_check_database", _ok),
        patch.object(rs, "_check_redis", _slow),
        patch.object(rs, "_check_qdrant", _ok),
        patch.object(rs, "_check_object_storage", _ok),
    ):
        report = asyncio.run(rs.readiness_report())
    assert report.ready is False
    assert report.payload()["checks"]["redis"]["detail"] == "timeout"


def test_ready_endpoint_status_codes():
    from fastapi.testclient import TestClient

    from app.main import app

    good = rs.ReadinessReport(ready=True)
    bad = rs.ReadinessReport(ready=False)
    # No context manager: that would run the lifespan (real DB connections).
    client = TestClient(app)

    async def _good():
        return good

    async def _bad():
        return bad

    with patch("app.services.readiness_service.readiness_report", _good):
        assert client.get("/ready").status_code == 200
    with patch("app.services.readiness_service.readiness_report", _bad):
        assert client.get("/ready").status_code == 503
