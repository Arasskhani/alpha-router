"""The two installable-app switches: on by default, and sent to the UI in the session."""

from pathlib import Path
from unittest.mock import patch

from app.config import Settings, get_settings


def test_both_switches_default_to_on():
    fields = Settings.model_fields
    assert fields["pwa_service_worker_enabled"].default is True
    assert fields["pwa_install_prompt_enabled"].default is True


def test_env_example_turns_both_on():
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert "\nPWA_SERVICE_WORKER_ENABLED=true\n" in example
    assert "\nPWA_INSTALL_PROMPT_ENABLED=true\n" in example


async def test_the_session_tells_the_ui_both_switches(client, user):
    from app.api import auth as auth_api
    from app.core.security import create_access_token

    client.cookies.set(get_settings().session_cookie_name, create_access_token(user.username, "user"))
    features = (await client.get("/api/auth/session")).json()["features"]
    assert features["pwa_service_worker"] is True
    assert features["pwa_install_prompt"] is True

    with (
        patch.object(auth_api.settings, "pwa_service_worker_enabled", False),
        patch.object(auth_api.settings, "pwa_install_prompt_enabled", False),
    ):
        features = (await client.get("/api/auth/session")).json()["features"]
    assert features["pwa_service_worker"] is False
    assert features["pwa_install_prompt"] is False
