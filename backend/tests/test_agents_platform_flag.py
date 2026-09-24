"""AGENTS_PLATFORM_ENABLED: on by default, and off still means off everywhere.

The Agent platform - Agents, Knowledge Bases, Tool Registry, Evaluations,
Approvals and Audit - shipped behind this switch while it was a preview, and
the switch defaulted to off. That default outlived the preview: an install
whose ``.env`` predated the key lost the whole section from the sidebar with
nothing on screen to say why, and a Super Admin had no way to tell a missing
permission from a missing feature.

The default is now on. The switch stays, because a deployment that does not
use the platform is better served by routers that were never mounted than by
routers that answer 403, and when it is off:

* the agent routers are not mounted (404, not 401/403), so nothing behind them
  is reachable at all;
* a chat request that carries agent fields is refused at preflight with 400;
* the session payload says so, and the UI hides the section.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.services import proxy_service


def test_the_platform_is_on_by_default():
    """An install that never set the key gets the feature, not a blank sidebar."""
    assert get_settings().agents_platform_enabled is True


async def test_the_routers_are_mounted_when_it_is_on(client):
    """Read through the OpenAPI schema, not ``app.routes``.

    FastAPI defers flattening included routers, so ``app.routes`` holds opaque
    ``_IncludedRouter`` placeholders whose ``path`` is ``None``. A test that
    scanned it for "/api/admin/agents" passed whether the routers were there or
    not - which is how a mounting check can watch a feature disappear and say
    nothing.
    """
    from app.main import app

    paths = list(app.openapi().get("paths", {}))
    assert any(path.startswith("/api/agents") for path in paths)
    assert any(path.startswith("/api/admin/agents") for path in paths)
    assert any(path.startswith("/api/admin/knowledge") for path in paths)
    # And reachable: answering as a guarded route rather than a missing one.
    assert (await client.get("/api/agents")).status_code != 404


async def test_the_session_tells_the_ui_the_platform_is_on(client, user):
    from app.core.security import create_access_token

    client.cookies.set(get_settings().session_cookie_name, create_access_token(user.username, "user"))
    resp = await client.get("/api/auth/session")
    assert resp.status_code == 200
    assert resp.json()["features"]["agents_platform"] is True


async def test_the_session_reports_it_off_when_a_deployment_turns_it_off(client, user):
    """The sidebar hides the section from this one field, so it has to follow
    the setting rather than a value baked in at import."""
    from app.api import auth as auth_api
    from app.core.security import create_access_token

    client.cookies.set(get_settings().session_cookie_name, create_access_token(user.username, "user"))
    with patch.object(auth_api.settings, "agents_platform_enabled", False):
        resp = await client.get("/api/auth/session")
    assert resp.json()["features"]["agents_platform"] is False


async def test_agent_fields_in_chat_body_are_refused_when_it_is_off(db_session, user):
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


async def test_ordinary_chat_body_is_not_refused_when_it_is_off(db_session, user):
    """The app sends ``agent_auto_route: false`` on every non-private turn.

    That is not a request for an Agent, so it must reach model resolution
    instead of the 400 -- otherwise turning the platform off breaks chat
    outright.
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
