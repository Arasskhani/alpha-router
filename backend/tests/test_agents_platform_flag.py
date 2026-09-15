"""AGENTS_PLATFORM_ENABLED (Phase 4.5): off by default, and off means off everywhere.

* The agent routers are not mounted (404, not 401/403), so nothing behind them
  is reachable at all.
* A chat request that carries agent fields is refused at preflight with 400.
* The session payload tells the UI, which hides the section.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.services import proxy_service


def test_flag_is_off_by_default():
    assert get_settings().agents_platform_enabled is False


async def test_agent_routes_are_not_mounted_when_disabled(client):
    assert get_settings().agents_platform_enabled is False
    resp = await client.get("/api/agents")
    assert resp.status_code == 404
    # Admin paths sit behind the IP-guard middleware (which needs the real
    # database), so check the route table itself for those.
    from app.main import app

    mounted = {getattr(route, "path", "") for route in app.routes}
    assert not any(path.startswith(("/api/admin/agents", "/api/admin/knowledge", "/api/agents")) for path in mounted)


async def test_session_payload_carries_the_flag(client, user):
    from app.core.security import create_access_token

    client.cookies.set(get_settings().session_cookie_name, create_access_token(user.username, "user"))
    resp = await client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json()["features"] == {"agents_platform": False}


async def test_agent_fields_in_chat_body_are_refused(db_session, user):
    body = {"model": "vendor/good", "messages": [{"role": "user", "content": "hi"}], "agent_id": "a1"}
    with (
        patch.object(proxy_service.settings, "agents_platform_enabled", False),
        pytest.raises(HTTPException) as exc,
    ):
        await proxy_service.preflight_stream_chat(
            db_session,
            body,
            user_id=user.id,
            skip_budget=True,
            alpha_router_api_key_id=None,
            source="alpha_router_chat",
        )
    assert exc.value.status_code == 400
    assert "Agent platform" in str(exc.value.detail)


async def test_ordinary_chat_body_is_not_refused_when_disabled(db_session, user):
    """The app sends ``agent_auto_route: false`` on every non-private turn.

    That is not a request for an Agent, so it must reach model resolution
    instead of the preview's 400 -- otherwise switching the preview off breaks
    chat outright.
    """
    body = {
        "model": "vendor/good",
        "messages": [{"role": "user", "content": "hi"}],
        "agent_auto_route": False,
    }
    with (
        patch.object(proxy_service.settings, "agents_platform_enabled", False),
        pytest.raises(HTTPException) as exc,
    ):
        await proxy_service.preflight_stream_chat(
            db_session,
            body,
            user_id=user.id,
            skip_budget=True,
            alpha_router_api_key_id=None,
            source="alpha_router_chat",
        )
    # No model named "vendor/good" exists in this test database: reaching the
    # 404 proves the Agent guard let the request through.
    assert exc.value.status_code == 404
    assert "Model not enabled" in str(exc.value.detail)
