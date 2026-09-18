"""An image tag cannot log a visitor out of every device.

``/api/auth/oidc/logout`` and ``/api/auth/saml/logout`` are GET - they end in a
redirect to the identity provider's single-logout URL, which only a top-level
navigation can follow - and they bump ``token_version``, which revokes every JWT
the account holds. ``CsrfProtectionMiddleware`` guards only unsafe methods, so
``<img src="https://host/api/auth/oidc/logout">`` on any page terminated every
session of any logged-in viewer.

They cannot become POST without breaking the redirect, so the discriminator is
``Sec-Fetch-Dest``: a navigation says ``document``, an image does not.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.auth import _require_top_level_navigation


class _Request:
    def __init__(self, dest: str | None) -> None:
        self.headers = {"sec-fetch-dest": dest} if dest is not None else {}


@pytest.mark.parametrize("dest", ["image", "iframe", "empty", "script", "style", "font"])
def test_a_subresource_request_is_refused(dest):
    with pytest.raises(HTTPException) as exc:
        _require_top_level_navigation(_Request(dest))
    assert exc.value.status_code == 400


def test_a_real_navigation_is_allowed():
    _require_top_level_navigation(_Request("document"))


def test_a_browser_that_sends_no_header_is_allowed():
    """Nothing better is available for it, and the worst case is a forced logout."""

    _require_top_level_navigation(_Request(None))
    _require_top_level_navigation(_Request(""))


def test_both_logout_endpoints_call_the_guard():
    import inspect

    from app.api import auth

    for name in ("oidc_logout", "saml_logout"):
        source = inspect.getsource(getattr(auth, name))
        assert "_require_top_level_navigation" in source, name
