"""Phase 10: keep the public liveness response minimal and stable."""

from app.main import health_payload


def test_health_payload_does_not_expose_route_or_build_details():
    assert health_payload() == {"status": "ok", "service": "alpha-router"}
