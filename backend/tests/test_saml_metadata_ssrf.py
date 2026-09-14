"""H2: SAML IdP metadata URL must use SSRF guard; XML path preferred for internal IdPs."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services import saml_sp
from app.services.ssrf_guard import SSRFBlockedError


def _public_dns():
    """Force hostname resolution to a public IP so assert_url_safe can pass in tests."""
    return patch(
        "app.services.ssrf_guard.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
    )


def test_validate_rejects_loopback_metadata_url():
    with patch("app.services.ssrf_guard.get_settings") as gs:
        gs.return_value.allow_ssrf_private_ranges = False
        with pytest.raises(ValueError, match="not allowed|Metadata XML"):
            saml_sp.validate_saml_config(
                {
                    "enabled": True,
                    "idp_metadata_url": "http://127.0.0.1/metadata",
                    "idp_metadata_xml": "",
                    "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
                }
            )


def test_validate_rejects_cloud_metadata_url():
    with patch("app.services.ssrf_guard.get_settings") as gs:
        gs.return_value.allow_ssrf_private_ranges = False
        with pytest.raises(ValueError, match="not allowed|Metadata XML"):
            saml_sp.validate_saml_config(
                {
                    "enabled": True,
                    "idp_metadata_url": "http://169.254.169.254/latest/meta-data/",
                    "idp_metadata_xml": "",
                    "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
                }
            )


def test_validate_accepts_public_metadata_url_with_dns():
    with patch("app.services.ssrf_guard.get_settings") as gs:
        gs.return_value.allow_ssrf_private_ranges = False
        with _public_dns():
            data = saml_sp.validate_saml_config(
                {
                    "enabled": True,
                    "idp_metadata_url": "https://idp.example.com/metadata",
                    "idp_metadata_xml": "",
                    "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
                }
            )
    assert data["idp_metadata_url"] == "https://idp.example.com/metadata"


def test_validate_accepts_xml_only_without_url_fetch():
    xml = '<?xml version="1.0"?><EntityDescriptor entityID="https://idp.local"></EntityDescriptor>'
    data = saml_sp.validate_saml_config(
        {
            "enabled": True,
            "idp_metadata_url": "",
            "idp_metadata_xml": xml,
            "entity_id": "https://alpha-router.example/api/auth/saml/metadata",
        }
    )
    assert data["idp_metadata_xml"] == xml
    assert data["idp_metadata_url"] == ""


def test_load_idp_prefers_xml_over_url():
    xml = (
        '<?xml version="1.0"?>'
        '<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" '
        'entityID="https://idp.local/entity">'
        "<IDPSSODescriptor protocolSupportEnumeration="
        '"urn:oasis:names:tc:SAML:2.0:protocol">'
        '<SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
        'Location="https://idp.local/sso"/>'
        "</IDPSSODescriptor>"
        "</EntityDescriptor>"
    )
    with patch.object(saml_sp, "_fetch_idp_metadata_xml") as fetch:
        idp = saml_sp._load_idp_data(
            {
                "idp_metadata_url": "https://evil.example.com/metadata",
                "idp_metadata_xml": xml,
            }
        )
        fetch.assert_not_called()
    assert idp.get("entityId") == "https://idp.local/entity"


def test_fetch_idp_metadata_blocks_ssrf_before_http():
    with patch("app.services.ssrf_guard.get_settings") as gs:
        gs.return_value.allow_ssrf_private_ranges = False
        with pytest.raises((ValueError, SSRFBlockedError)):
            saml_sp._fetch_idp_metadata_xml("http://10.0.0.5/metadata")


def test_fetch_idp_metadata_revalidates_redirect_target():
    public = "https://idp.example.com/metadata"
    internal = "http://127.0.0.1/secret"

    class _Resp:
        def __init__(self, status_code, headers=None, body=b""):
            self.status_code = status_code
            self.headers = headers or {}
            self._body = body
            self.request = MagicMock()
            self.request.url = public if status_code in {301, 302} else internal

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Client:
        def __init__(self, *args, **kwargs):
            self._n = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            self._n += 1
            if self._n == 1:
                # First hop: public URL redirects to loopback
                resp = _Resp(302, {"location": internal})
                resp.request.url = url
                return resp
            resp = _Resp(200, body=b"<xml/>")
            resp.request.url = url
            return resp

    with patch("app.services.ssrf_guard.get_settings") as gs:
        gs.return_value.allow_ssrf_private_ranges = False
        with _public_dns():
            with patch.object(httpx, "Client", _Client):
                with pytest.raises((ValueError, SSRFBlockedError)):
                    saml_sp._fetch_idp_metadata_xml(public)
