"""TOTP must be enforced by account state, not by auth_provider.

The password login path used to challenge for a second factor only when
``auth_provider == "local"``. A directory sync that re-linked a local row to
``ldap`` therefore switched that user's 2FA off without anyone noticing.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import auth as auth_api


def _user(provider: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        username="admin",
        hashed_password="$2b$hash",
        auth_provider=provider,
        totp_enabled=True,
        is_active=True,
        deleted_at=None,
    )


@pytest.mark.parametrize("provider", ["local", "ldap"])
def test_password_login_challenges_totp_for_any_provider(provider: str) -> None:
    async def run() -> auth_api.TokenResponse:
        user = _user(provider)
        store_pending = AsyncMock()
        token_response = AsyncMock(side_effect=AssertionError("must not issue a session before 2FA"))
        request = MagicMock()
        request.headers = {}
        request.client = SimpleNamespace(host="127.0.0.1")

        with (
            patch("app.services.rate_limit.check_login_rate_limit", AsyncMock()),
            patch("app.services.client_ip.resolve_client_ip", return_value="127.0.0.1"),
            patch.object(auth_api, "find_user_by_username_ci", AsyncMock(return_value=user)),
            patch.object(auth_api, "verify_password", return_value=True),
            patch.object(auth_api, "ensure_user_chat_store", AsyncMock()),
            patch.object(auth_api, "_token_response", token_response),
            patch("app.services.twofa_pending.generate_pending_token", return_value="pending-123"),
            patch("app.services.twofa_pending.store_pending", store_pending),
        ):
            result = await auth_api.login_local(
                auth_api.LoginRequest(username="admin", password="pw"),
                request,
                MagicMock(),
                db=AsyncMock(),
            )
        store_pending.assert_awaited_once()
        return result

    result = asyncio.run(run())
    assert result.requires_2fa is True
    assert result.token_type == "2fa_pending"
    assert result.pending_token == "pending-123"
    assert result.access_token == ""
