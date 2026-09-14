"""SAML config validation helpers (no live IdP required)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.auth import saml_metadata
from app.services.auth_urls import validate_frontend_url
from app.services.saml_sp import sp_metadata_xml, validate_saml_config


def test_validate_saml_requires_metadata_when_enabled():
    with pytest.raises(ValueError, match="IdP Metadata"):
        validate_saml_config(
            {
                "enabled": True,
                "idp_metadata_url": "",
                "idp_metadata_xml": "",
                "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
            }
        )


def test_validate_saml_accepts_metadata_url():
    with patch(
        "app.services.ssrf_guard.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
    ):
        data = validate_saml_config(
            {
                "enabled": True,
                "idp_metadata_url": "https://idp.example.com/metadata",
                "idp_metadata_xml": "",
                "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
                "strict": True,
                "want_assertions_signed": True,
            }
        )
    assert data["idp_metadata_url"] == "https://idp.example.com/metadata"
    assert data["entity_id"].endswith("/api/auth/saml/metadata")


def test_validate_frontend_url_rejects_credentials():
    with pytest.raises(ValueError):
        validate_frontend_url("https://user:pass@example.com")


def test_sp_metadata_xml_does_not_require_idp():
    xml = sp_metadata_xml(
        {
            "enabled": True,
            "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
            "strict": True,
            "want_assertions_signed": True,
        }
    )
    assert "EntityDescriptor" in xml
    assert "https://alpha-router.example/api/auth/saml/metadata" in xml
    assert "AssertionConsumerService" in xml


async def _metadata_404_when_disabled() -> None:
    db = AsyncMock()
    with patch("app.api.auth.get_provider_config", new=AsyncMock(return_value={"enabled": False})):
        with pytest.raises(HTTPException) as exc:
            await saml_metadata(db)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Not Found"


async def _metadata_xml_when_enabled() -> None:
    db = AsyncMock()
    cfg = {
        "enabled": True,
        "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
        "strict": True,
        "want_assertions_signed": True,
    }
    with patch("app.api.auth.get_provider_config", new=AsyncMock(return_value=cfg)):
        resp = await saml_metadata(db)
    assert resp.media_type == "application/samlmetadata+xml"
    body = resp.body.decode("utf-8") if isinstance(resp.body, (bytes, bytearray)) else str(resp.body)
    assert "EntityDescriptor" in body


async def test_saml_metadata_endpoint_404_when_disabled():
    await _metadata_404_when_disabled()


async def test_saml_metadata_endpoint_returns_xml_when_enabled():
    await _metadata_xml_when_enabled()
