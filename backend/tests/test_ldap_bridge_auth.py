"""Fail-closed authentication tests for the Windows LDAP bridge."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import ldap_bridge_client
from app.services.ldap_bridge_security import authorize_bridge_request


def test_bridge_rejects_empty_token_configuration() -> None:
    with pytest.raises(HTTPException) as exc:
        authorize_bridge_request(None, "")
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic abc",
        "Bearer",
        "Bearer wrong-token",
    ],
)
def test_bridge_rejects_missing_or_wrong_authorization(authorization: str | None) -> None:
    with pytest.raises(HTTPException) as exc:
        authorize_bridge_request(authorization, "correct-token-value")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


def test_bridge_accepts_correct_bearer_token() -> None:
    authorize_bridge_request("Bearer correct-token-value", "correct-token-value")


def test_client_fails_closed_when_bridge_enabled_without_token() -> None:
    settings = SimpleNamespace(
        ldap_bridge_url="http://host.docker.internal:8765",
        ldap_bridge_token="",
    )
    with (
        patch.object(ldap_bridge_client, "get_settings", return_value=settings),
        pytest.raises(ldap_bridge_client.LdapBridgeError),
    ):
        ldap_bridge_client._headers()


def test_client_omits_header_when_bridge_is_disabled() -> None:
    settings = SimpleNamespace(ldap_bridge_url="", ldap_bridge_token="")
    with patch.object(ldap_bridge_client, "get_settings", return_value=settings):
        assert ldap_bridge_client._headers() == {}


def test_client_sends_configured_bearer_token() -> None:
    settings = SimpleNamespace(
        ldap_bridge_url="http://host.docker.internal:8765",
        ldap_bridge_token="correct-token-value",
    )
    with patch.object(ldap_bridge_client, "get_settings", return_value=settings):
        assert ldap_bridge_client._headers() == {
            "Authorization": "Bearer correct-token-value"
        }
