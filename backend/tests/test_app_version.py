"""The running version comes from the git tag, stamped into the image.

The tag is already the source of truth for which code a host deploys
(``latest_release_tag`` in scripts/lib/stack.sh). These tests cover the other
half: what the application reports, and what it reports when nobody told it.

scripts/tests/test-app-version.sh covers the shell side - what
``resolve_app_version`` derives from a real repository in each of its states.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.config import UNKNOWN_VERSION, application_version, get_settings


def _with_env(**env):
    """A fresh Settings read from the given environment."""
    get_settings.cache_clear()
    return patch.dict(os.environ, env, clear=False)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_a_stamped_image_reports_its_tag():
    with _with_env(APP_VERSION="v1.0.1"):
        assert application_version() == "v1.0.1"


def test_a_development_build_reports_the_distance_from_the_tag():
    """git describe's own format, passed through unaltered: the operator can
    tell a release apart from three commits past one."""
    with _with_env(APP_VERSION="v1.0.1-3-gabc1234"):
        assert application_version() == "v1.0.1-3-gabc1234"


def test_an_unstamped_image_says_unknown_rather_than_claiming_a_version():
    """The whole point of removing the hardcoded 1.0.0. An image built outside
    install.sh / upgrade.sh does not know its version, and saying so is more
    useful than a number nobody set."""
    with _with_env(APP_VERSION=""):
        assert application_version() == UNKNOWN_VERSION
    assert UNKNOWN_VERSION != "1.0.0"


def test_whitespace_is_not_a_version():
    """An empty build arg can arrive as a blank string rather than unset."""
    with _with_env(APP_VERSION="   "):
        assert application_version() == UNKNOWN_VERSION


def test_the_openapi_document_carries_it():
    """/openapi.json is where the version was stale before this existed."""
    with _with_env(APP_VERSION="v9.9.9"):
        from fastapi import FastAPI

        app = FastAPI(title="t", version=application_version())
        assert app.openapi()["info"]["version"] == "v9.9.9"


async def test_the_admin_endpoint_returns_version_and_revision():
    from app.api.admin import get_application_version

    with _with_env(APP_VERSION="v1.0.1", APP_REVISION="a" * 40):
        payload = await get_application_version(_=None)
    assert payload == {"version": "v1.0.1", "revision": "a" * 40}


async def test_the_admin_endpoint_is_honest_about_an_unstamped_image():
    from app.api.admin import get_application_version

    with _with_env(APP_VERSION="", APP_REVISION=""):
        payload = await get_application_version(_=None)
    assert payload == {"version": UNKNOWN_VERSION, "revision": ""}


def test_the_version_is_not_on_an_unauthenticated_endpoint():
    """/health and /ready answer without a session. Handing an exact build
    number to anyone who can reach the port works against the hardening this
    product otherwise asks for, so the version is behind the admin guard."""
    import inspect

    from app.main import health_payload

    assert "version" not in inspect.getsource(health_payload)


def test_the_admin_endpoint_is_guarded():
    import inspect

    from app.api import admin

    source = inspect.getsource(admin.get_application_version)
    assert "require_admin" in source
