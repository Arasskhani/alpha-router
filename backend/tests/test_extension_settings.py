"""Admin settings for the browser extension: site rules, models and the agent's limits."""

from __future__ import annotations

import json

import pytest

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.services.extension_settings import (
    SETTINGS_KEY,
    SITE_BLOCKED,
    SITE_NOT_ALLOWED,
    ExtensionSettings,
    ExtensionSettingsError,
    host_matches,
    load_extension_settings,
    normalize_site_pattern,
    parse_settings,
    save_extension_settings,
    site_refusal,
    validated_update,
)


def _update(**overrides):
    values = {
        "site_access": "per_site",
        "allowed_sites": [],
        "blocked_sites": [],
        "page_content_models": [],
        "agent_models": [],
        "agent_max_steps": 25,
        "agent_auto_mode": False,
        "agent_review_model": None,
    }
    values.update(overrides)
    return values


async def _model(db, external_id: str = "gpt-test") -> AIModel:
    connection = Connection(name=f"c-{external_id}", provider_type="openai", api_key_encrypted="x", is_active=True)
    db.add(connection)
    await db.flush()
    model = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=external_id,
        provider_type="openai",
        is_enabled=True,
    )
    db.add(model)
    await db.commit()
    return model


class TestSitePatterns:
    @pytest.mark.parametrize(
        ("raw", "normalized"),
        [
            ("Example.COM", "example.com"),
            (" *.corp.example ", "*.corp.example"),
            ("portal", "portal"),
            ("10.0.0.5", "10.0.0.5"),
            ("بانک.ایران", "xn--mgbb5gwr.xn--mgba3a4f16a"),
            # A zero-width non-joiner kept, as browsers do (non-transitional UTS #46).
            ("می\u200cخواهم.ir", "xn--mgbn2ecje63gr19l.ir"),
            ("example.com.", "example.com"),
        ],
    )
    def test_host_names_and_subdomain_wildcards_are_accepted(self, raw, normalized):
        assert normalize_site_pattern(raw) == normalized

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "https://example.com",
            "example.com/path",
            "example.com:8443",
            "*example.com",
            "a.*.example.com",
            "-bad.example",
            "user@example.com",
        ],
    )
    def test_anything_else_is_refused(self, raw):
        with pytest.raises(ValueError):
            normalize_site_pattern(raw)

    def test_a_wildcard_covers_subdomains_but_not_the_domain_itself(self):
        assert host_matches("mail.example.com", "*.example.com")
        assert host_matches("a.b.example.com", "*.example.com")
        assert not host_matches("example.com", "*.example.com")
        assert not host_matches("badexample.com", "*.example.com")
        assert host_matches("Example.com.", "example.com")

    def test_blocked_wins_and_an_allow_list_closes_everything_else(self):
        settings = ExtensionSettings(
            allowed_sites=("*.corp.example", "corp.example"), blocked_sites=("hr.corp.example",)
        )
        assert site_refusal("wiki.corp.example", settings) is None
        assert site_refusal("corp.example", settings) is None
        assert site_refusal("hr.corp.example", settings) == SITE_BLOCKED
        assert site_refusal("news.example", settings) == SITE_NOT_ALLOWED
        assert site_refusal("anything.example", ExtensionSettings()) is None


class TestStoredSettings:
    async def test_defaults_before_anything_is_saved(self, db_session):
        settings = await load_extension_settings(db_session)
        assert settings == ExtensionSettings()
        assert settings.site_access == "per_site"
        assert settings.agent_max_steps == 25
        assert settings.agent_auto_mode is False

    async def test_saved_settings_read_back(self, db_session):
        saved = ExtensionSettings(site_access="all_sites", blocked_sites=("bank.example",), agent_max_steps=40)
        await save_extension_settings(db_session, saved)
        await db_session.commit()
        assert await load_extension_settings(db_session) == saved
        await save_extension_settings(db_session, ExtensionSettings())
        await db_session.commit()
        assert await load_extension_settings(db_session) == ExtensionSettings()

    def test_a_value_this_code_did_not_write_falls_back_field_by_field(self):
        assert parse_settings("not json") == ExtensionSettings()
        assert parse_settings("[1, 2]") == ExtensionSettings()
        odd = parse_settings(
            json.dumps(
                {
                    "site_access": "some_sites",
                    "agent_max_steps": 1000,
                    "blocked_sites": ["ok.example", 7],
                    "agent_auto_mode": True,
                }
            )
        )
        assert odd.site_access == "per_site"
        assert odd.agent_max_steps == 25
        assert odd.blocked_sites == ("ok.example",)
        # Auto mode without a review model is never read back as on.
        assert odd.agent_auto_mode is False

    async def test_the_row_is_the_documented_key(self, db_session):
        await save_extension_settings(db_session, ExtensionSettings(agent_max_steps=30))
        await db_session.commit()
        row = await db_session.get(SystemSetting, SETTINGS_KEY)
        assert json.loads(row.value)["agent_max_steps"] == 30


class TestAnAdminsChange:
    async def test_sites_are_normalized_deduplicated_and_sorted(self, db_session):
        updated = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(blocked_sites=["B.example", "a.example", "b.example", "  "], allowed_sites=["*.corp.example"]),
        )
        assert updated.blocked_sites == ("a.example", "b.example")
        assert updated.allowed_sites == ("*.corp.example",)

    async def test_a_bad_site_says_which_list_and_which_entry(self, db_session):
        with pytest.raises(ExtensionSettingsError, match=r"Blocked sites: 'https://x.example'"):
            await validated_update(db_session, ExtensionSettings(), **_update(blocked_sites=["https://x.example"]))

    async def test_models_must_exist(self, db_session):
        model = await _model(db_session)
        updated = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(page_content_models=[f"model::{model.id}"], agent_models=[f"model::{model.id}"]),
        )
        assert updated.page_content_models == (f"model::{model.id}",)
        with pytest.raises(ExtensionSettingsError, match="does not exist"):
            await validated_update(db_session, ExtensionSettings(), **_update(agent_models=["model::999999"]))
        with pytest.raises(ExtensionSettingsError, match="not a model"):
            await validated_update(db_session, ExtensionSettings(), **_update(agent_models=["gpt-test"]))

    async def test_auto_mode_needs_a_review_model(self, db_session):
        with pytest.raises(ExtensionSettingsError, match="review model"):
            await validated_update(db_session, ExtensionSettings(), **_update(agent_auto_mode=True))
        model = await _model(db_session, "reviewer")
        updated = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(agent_auto_mode=True, agent_review_model=f"model::{model.id}"),
        )
        assert updated.agent_auto_mode is True
        assert updated.agent_review_model == f"model::{model.id}"

    @pytest.mark.parametrize("steps", [4, 101])
    async def test_agent_steps_stay_in_bounds(self, db_session, steps):
        with pytest.raises(ExtensionSettingsError, match="between 5 and 100"):
            await validated_update(db_session, ExtensionSettings(), **_update(agent_max_steps=steps))

    async def test_site_access_is_saved_as_asked(self, db_session):
        changed = await validated_update(db_session, ExtensionSettings(), **_update(site_access="all_sites"))
        assert changed.site_access == "all_sites"
        with pytest.raises(ExtensionSettingsError, match="per site or all sites"):
            await validated_update(db_session, ExtensionSettings(), **_update(site_access="some_sites"))
