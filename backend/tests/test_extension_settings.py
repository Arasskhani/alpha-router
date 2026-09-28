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
    extra_package_permissions,
    host_matches,
    load_extension_settings,
    normalize_page_host,
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
            # Every host a page can come from can be named, so it can be blocked.
            ("My_Server.corp", "my_server.corp"),
            ("*.dev_lab.corp", "*.dev_lab.corp"),
            ("[FD00:0::1]", "[fd00::1]"),
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
            "[fd00::1]:8443",
            "*.[fd00::1]",
            "[not-an-address]",
            "fd00::1",
        ],
    )
    def test_anything_else_is_refused(self, raw):
        with pytest.raises(ValueError):
            normalize_site_pattern(raw)

    def test_a_wildcard_covers_the_domain_and_its_subdomains_as_in_chrome(self):
        assert host_matches("mail.example.com", "*.example.com")
        assert host_matches("a.b.example.com", "*.example.com")
        assert host_matches("example.com", "*.example.com")
        assert not host_matches("badexample.com", "*.example.com")
        assert not host_matches("example.com.evil", "*.example.com")
        assert host_matches("Example.com.", "example.com")
        assert not host_matches("mail.example.com", "example.com")

    def test_an_allow_list_never_shuts_out_alpharouter_itself(self):
        settings = ExtensionSettings(allowed_sites=("*.corp.example",))
        assert site_refusal("ai.example.com", settings) == SITE_NOT_ALLOWED
        assert site_refusal("AI.example.com", settings, server_host="ai.example.com") is None
        blocked = ExtensionSettings(blocked_sites=("ai.example.com",))
        assert site_refusal("ai.example.com", blocked, server_host="ai.example.com") == SITE_BLOCKED

    def test_an_ipv6_host_or_one_with_underscores_can_be_blocked(self):
        blocked = ExtensionSettings(
            blocked_sites=(normalize_site_pattern("[fd00::1]"), normalize_site_pattern("my_host.corp"))
        )
        assert site_refusal(normalize_page_host("[FD00:0:0::1]"), blocked) == SITE_BLOCKED
        assert site_refusal(normalize_page_host("My_Host.corp"), blocked) == SITE_BLOCKED

    def test_blocking_a_wildcard_blocks_the_site_itself(self):
        """An admin who blocks *.bank.example means the bank's own site too."""
        assert site_refusal("bank.example", ExtensionSettings(blocked_sites=("*.bank.example",))) == SITE_BLOCKED

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


class TestFullControl:
    def test_off_by_default(self):
        assert ExtensionSettings().full_control is False
        assert extra_package_permissions(ExtensionSettings()) == ()

    def test_on_adds_the_debugger_permission(self):
        assert extra_package_permissions(ExtensionSettings(full_control=True)) == ("debugger",)

    def test_it_reads_back(self):
        assert parse_settings(json.dumps({"full_control": True})).full_control is True
        assert parse_settings(json.dumps({"full_control": "yes"})).full_control is True
        assert parse_settings(json.dumps({})).full_control is False

    async def test_an_admin_can_turn_it_on(self, db_session):
        updated = await validated_update(db_session, ExtensionSettings(), **_update(full_control=True))
        assert updated.full_control is True
        off = await validated_update(db_session, updated, **_update(full_control=False))
        assert off.full_control is False


class TestOrganisationSwitch:
    def test_on_by_default_and_for_a_document_written_before_it_existed(self):
        assert ExtensionSettings().enabled is True
        assert parse_settings(json.dumps({"site_access": "per_site"})).enabled is True
        assert parse_settings(json.dumps({"enabled": False})).enabled is False

    async def test_an_admin_can_turn_the_whole_extension_off(self, db_session):
        off = await validated_update(db_session, ExtensionSettings(), **_update(enabled=False))
        assert off.enabled is False


class TestReadOnlyAndProtectedSites:
    async def test_they_are_normalized_like_the_other_site_lists(self, db_session):
        updated = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(read_only_sites=["Wiki.example.com", "wiki.example.com"], protected_sites=["*.shaparak.ir"]),
        )
        assert updated.read_only_sites == ("wiki.example.com",)
        assert updated.protected_sites == ("*.shaparak.ir",)

    async def test_a_bad_entry_says_which_list(self, db_session):
        with pytest.raises(ExtensionSettingsError, match="Read-only sites"):
            await validated_update(db_session, ExtensionSettings(), **_update(read_only_sites=["http://x/"]))
        with pytest.raises(ExtensionSettingsError, match="Protected sites"):
            await validated_update(db_session, ExtensionSettings(), **_update(protected_sites=["a b"]))

    def test_they_read_back(self):
        got = parse_settings(json.dumps({"read_only_sites": ["a.com"], "protected_sites": ["b.com"]}))
        assert got.read_only_sites == ("a.com",)
        assert got.protected_sites == ("b.com",)


class TestDataLocation:
    async def test_internal_sites_and_the_models_that_may_see_them(self, db_session):
        model = await _model(db_session, "gpt-internal")
        updated = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(
                internal_sites=["*.corp.example"],
                internal_models=[f"model::{model.id}"],
                screenshot_models=[f"model::{model.id}"],
            ),
        )
        assert updated.internal_sites == ("*.corp.example",)
        assert updated.internal_models == (f"model::{model.id}",)
        assert updated.screenshot_models == (f"model::{model.id}",)

    async def test_a_model_that_does_not_exist_is_refused(self, db_session):
        with pytest.raises(ExtensionSettingsError, match="internal sites"):
            await validated_update(db_session, ExtensionSettings(), **_update(internal_models=["model::999999"]))


class TestScreenshotAllowed:
    def test_any_model_when_no_lists(self):
        from app.services.extension_settings import screenshot_allowed

        s = ExtensionSettings()
        assert screenshot_allowed(s, "model::7", "shop.example.com") is True
        assert screenshot_allowed(s, None, None) is True

    def test_the_screenshot_list_gates_every_site(self):
        from app.services.extension_settings import screenshot_allowed

        s = ExtensionSettings(screenshot_models=("model::5",))
        assert screenshot_allowed(s, "model::5", "shop.example.com") is True
        assert screenshot_allowed(s, "model::9", "shop.example.com") is False
        assert screenshot_allowed(s, None, "shop.example.com") is False

    def test_an_internal_site_needs_a_model_on_the_internal_list(self):
        from app.services.extension_settings import screenshot_allowed

        s = ExtensionSettings(internal_sites=("*.corp.example",), internal_models=("model::5",))
        assert screenshot_allowed(s, "model::5", "app.corp.example") is True
        assert screenshot_allowed(s, "model::9", "app.corp.example") is False
        # A non-internal site is not gated by the internal list.
        assert screenshot_allowed(s, "model::9", "shop.example.com") is True

    def test_internal_with_no_internal_models_allows_any_screenshot_model(self):
        from app.services.extension_settings import screenshot_allowed

        s = ExtensionSettings(internal_sites=("*.corp.example",), screenshot_models=("model::5",))
        assert screenshot_allowed(s, "model::5", "app.corp.example") is True
        assert screenshot_allowed(s, "model::9", "app.corp.example") is False


class TestApprovals:
    def test_all_ask_by_default_and_map_to_true(self):
        assert ExtensionSettings().relaxed_approvals == ()
        assert ExtensionSettings().approvals_json() == {
            "send": True,
            "submit": True,
            "delete": True,
            "leave_sites": True,
            "downloads": True,
            "uploads": True,
            "dialogs": True,
        }

    async def test_an_admin_relaxes_a_subset_and_the_rest_still_ask(self, db_session):
        updated = await validated_update(
            db_session, ExtensionSettings(), **_update(relaxed_approvals=["send", "downloads"])
        )
        assert set(updated.relaxed_approvals) == {"send", "downloads"}
        assert updated.approvals_json()["send"] is False
        assert updated.approvals_json()["downloads"] is False
        assert updated.approvals_json()["delete"] is True

    async def test_an_unknown_case_is_refused(self, db_session):
        with pytest.raises(ExtensionSettingsError, match="can be relaxed"):
            await validated_update(db_session, ExtensionSettings(), **_update(relaxed_approvals=["purchases"]))

    def test_an_unknown_case_stored_by_hand_is_dropped_on_read(self):
        assert parse_settings(json.dumps({"relaxed_approvals": ["send", "nonsense"]})).relaxed_approvals == ("send",)


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

    @pytest.mark.parametrize(
        "ref", ["model::0", "model::2147483648", "model::99999999999", "model::123456789012345678"]
    )
    async def test_an_id_the_database_cannot_hold_is_not_a_model(self, db_session, ref):
        """Past INTEGER's range PostgreSQL itself would fail: a 500 instead of a message."""
        with pytest.raises(ExtensionSettingsError, match="not a model"):
            await validated_update(db_session, ExtensionSettings(), **_update(page_content_models=[ref]))

    async def test_the_review_model_must_be_enabled(self, db_session):
        model = await _model(db_session, "retired")
        model.is_enabled = False
        await db_session.commit()
        with pytest.raises(ExtensionSettingsError, match="not enabled"):
            await validated_update(
                db_session,
                ExtensionSettings(),
                **_update(agent_auto_mode=True, agent_review_model=f"model::{model.id}"),
            )
        # A disabled model may still sit in an allowlist, ready for when it comes back.
        kept = await validated_update(db_session, ExtensionSettings(), **_update(agent_models=[f"model::{model.id}"]))
        assert kept.agent_models == (f"model::{model.id}",)

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

    async def test_auto_mode_s_review_model_must_be_one_pages_may_reach(self, db_session):
        """The reviewer reads element names and the text the agent would type, both from pages."""
        listed = await _model(db_session, "listed")
        reviewer = await _model(db_session, "reviewer")
        with pytest.raises(ExtensionSettingsError, match="must be one of the models for page content"):
            await validated_update(
                db_session,
                ExtensionSettings(),
                **_update(
                    page_content_models=[f"model::{listed.id}"],
                    agent_auto_mode=True,
                    agent_review_model=f"model::{reviewer.id}",
                ),
            )
        both = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(
                page_content_models=[f"model::{listed.id}", f"model::{reviewer.id}"],
                agent_auto_mode=True,
                agent_review_model=f"model::{reviewer.id}",
            ),
        )
        assert both.agent_review_model == f"model::{reviewer.id}"
        # Pages may go to any model, or Auto mode is off and the reviewer is never asked.
        anyone = await validated_update(
            db_session, ExtensionSettings(), **_update(agent_auto_mode=True, agent_review_model=f"model::{reviewer.id}")
        )
        assert anyone.agent_auto_mode is True
        off = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(page_content_models=[f"model::{listed.id}"], agent_review_model=f"model::{reviewer.id}"),
        )
        assert (off.agent_auto_mode, off.agent_review_model) == (False, f"model::{reviewer.id}")

    @pytest.mark.parametrize("steps", [4, 101])
    async def test_agent_steps_stay_in_bounds(self, db_session, steps):
        with pytest.raises(ExtensionSettingsError, match="between 5 and 100"):
            await validated_update(db_session, ExtensionSettings(), **_update(agent_max_steps=steps))

    async def test_site_access_is_saved_as_asked(self, db_session):
        changed = await validated_update(db_session, ExtensionSettings(), **_update(site_access="all_sites"))
        assert changed.site_access == "all_sites"
        with pytest.raises(ExtensionSettingsError, match="per site or all sites"):
            await validated_update(db_session, ExtensionSettings(), **_update(site_access="some_sites"))


class TestTheRunLimits:
    def test_defaults(self):
        s = ExtensionSettings()
        assert (s.agent_max_minutes, s.agent_max_tabs, s.agent_runs_per_day) == (20, 10, None)
        assert (s.screenshot_max_side, s.screenshots_kept) == (1280, 3)
        assert (s.plan_mode, s.agent_default_mode, s.agent_auto_mode) == (True, "plan", False)
        assert s.modes_json() == ["ask", "plan"]
        assert (s.require_newest_package, s.min_browser_version) == (False, 116)
        assert (s.internal_connections, s.external_screenshots) == ((), True)
        assert (s.save_runs, s.private_runs) == (True, True)
        assert s.screenshot_after_action is True

    def test_a_stored_value_out_of_range_falls_back_to_the_default(self):
        stored = {
            "agent_max_minutes": 0,
            "agent_max_tabs": 999,
            "agent_runs_per_day": 0,
            "screenshot_max_side": 100,
            "screenshots_kept": 9,
            "min_browser_version": 12,
            "agent_default_mode": "skip",
            "internal_connections": [3, "x", 0, -1, True, 3],
        }
        s = parse_settings(json.dumps(stored))
        assert (s.agent_max_minutes, s.agent_max_tabs, s.agent_runs_per_day) == (20, 10, None)
        # Screenshots kept past the most a step may carry is kept at that most, not dropped to the default.
        assert (s.screenshot_max_side, s.screenshots_kept, s.min_browser_version) == (1280, 4, 116)
        assert s.agent_default_mode == "plan"
        assert s.internal_connections == (3,)

    def test_screenshots_kept_above_what_a_step_may_carry_is_kept_at_the_most_it_may(self):
        from app.api.chat import MAX_AGENT_IMAGES
        from app.services.extension_settings import MAX_SCREENSHOTS_KEPT

        # An earlier version allowed 5, which made every step past the fifth screenshot fail.
        assert parse_settings(json.dumps({"screenshots_kept": 5})).screenshots_kept == 4
        assert MAX_SCREENSHOTS_KEPT <= MAX_AGENT_IMAGES

    def test_modes_on_offer_follow_the_switches(self):
        assert ExtensionSettings(plan_mode=False).modes_json() == ["ask"]
        assert ExtensionSettings(agent_auto_mode=True, agent_review_model="model::1").modes_json() == [
            "ask",
            "plan",
            "auto",
        ]

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"agent_max_minutes": 0}, "Run time"),
            ({"agent_max_minutes": 181}, "Run time"),
            ({"agent_max_tabs": 51}, "Tabs per run"),
            ({"agent_runs_per_day": 0}, "Runs per person"),
            ({"screenshot_max_side": 799}, "longest side"),
            ({"screenshots_kept": 5}, "Screenshots kept"),
            ({"min_browser_version": 115}, "minimum browser version"),
            ({"agent_default_mode": "skip"}, "default mode"),
            ({"agent_default_mode": "plan", "plan_mode": False}, "Plan cannot be the default"),
            ({"agent_default_mode": "auto"}, "Auto cannot be the default"),
            ({"internal_connections": [999999]}, "does not exist"),
        ],
    )
    async def test_a_value_past_its_limit_is_refused_by_name(self, db_session, overrides, message):
        with pytest.raises(ExtensionSettingsError, match=message):
            await validated_update(db_session, ExtensionSettings(), **_update(**overrides))

    async def test_the_limits_round_trip(self, db_session):
        model = await _model(db_session, "gpt-limits")
        updated = await validated_update(
            db_session,
            ExtensionSettings(),
            **_update(
                agent_max_minutes=5,
                agent_max_tabs=3,
                agent_runs_per_day=12,
                screenshot_max_side=800,
                screenshots_kept=1,
                screenshot_after_action=False,
                min_browser_version=142,
                require_newest_package=True,
                plan_mode=False,
                agent_default_mode="ask",
                internal_connections=[model.connection_id],
                external_screenshots=False,
                save_runs=False,
                private_runs=False,
            ),
        )
        await save_extension_settings(db_session, updated)
        await db_session.commit()
        again = await load_extension_settings(db_session)
        assert again == updated
        assert (again.agent_max_minutes, again.agent_max_tabs, again.agent_runs_per_day) == (5, 3, 12)
        assert again.internal_connections == (model.connection_id,)
        assert again.modes_json() == ["ask"]
        assert again.to_json()["internal_connections"] == [model.connection_id]


class TestInsideTheOrganisation:
    def test_any_model_when_nothing_is_marked_internal(self):
        from app.services.extension_settings import inside_organisation

        assert inside_organisation(ExtensionSettings(), "model::7", 3) is True
        assert inside_organisation(ExtensionSettings(), None, None) is True

    def test_a_connection_inside_the_organisation_counts_like_the_internal_list(self):
        from app.services.extension_settings import inside_organisation

        s = ExtensionSettings(internal_connections=(3,), internal_models=("model::5",))
        assert inside_organisation(s, "model::9", 3) is True
        assert inside_organisation(s, "model::5", 8) is True
        assert inside_organisation(s, "model::9", 8) is False
        assert inside_organisation(s, None, None) is False

    def test_screenshots_kept_inside_the_organisation(self):
        from app.services.extension_settings import screenshot_allowed

        s = ExtensionSettings(internal_connections=(3,), external_screenshots=False)
        # Any site: a screenshot may not leave the organisation.
        assert screenshot_allowed(s, "model::9", "shop.example.com", connection_id=3) is True
        assert screenshot_allowed(s, "model::9", "shop.example.com", connection_id=8) is False
        # With nothing marked internal the switch cannot tell inside from outside, so it restricts nothing.
        assert screenshot_allowed(ExtensionSettings(external_screenshots=False), "model::9", "shop.example.com") is True

    def test_an_internal_site_takes_a_model_on_an_internal_connection(self):
        from app.services.extension_settings import screenshot_allowed

        s = ExtensionSettings(internal_sites=("*.corp.example",), internal_connections=(3,))
        assert screenshot_allowed(s, "model::9", "app.corp.example", connection_id=3) is True
        assert screenshot_allowed(s, "model::9", "app.corp.example", connection_id=8) is False
        assert screenshot_allowed(s, "model::9", "shop.example.com", connection_id=8) is True

    async def test_the_effective_lists_the_extension_gets(self, db_session):
        from app.services.extension_settings import data_policy, inside_model_refs

        inside = await _model(db_session, "gpt-inside")
        outside = await _model(db_session, "gpt-outside")
        listed = await _model(db_session, "gpt-listed")
        s = ExtensionSettings(
            internal_sites=("*.corp.example",),
            internal_connections=(inside.connection_id,),
            internal_models=(f"model::{listed.id}",),
            screenshot_models=(f"model::{outside.id}", f"model::{inside.id}"),
            external_screenshots=False,
        )
        assert await inside_model_refs(db_session, s) == {f"model::{inside.id}", f"model::{listed.id}"}
        policy = await data_policy(db_session, s)
        assert policy["internal_models"] == sorted([f"model::{inside.id}", f"model::{listed.id}"])
        # Screenshots may not leave: the screenshot list narrows to the models inside.
        assert policy["screenshot_models"] == [f"model::{inside.id}"]
        assert policy["external_screenshots"] is False
        assert (await data_policy(db_session, ExtensionSettings()))["internal_models"] is None

    @pytest.mark.parametrize(
        ("base_url", "internal"),
        [
            ("http://10.0.0.5:8000/v1", True),
            ("https://192.168.1.20/v1", True),
            ("http://172.16.4.4/v1", True),
            ("http://localhost:11434/v1", True),
            ("http://ollama.internal/v1", True),
            ("http://llm-box/v1", True),
            ("https://api.openai.com/v1", False),
            ("https://8.8.8.8/v1", False),
            ("", False),
            (None, False),
        ],
    )
    def test_an_address_that_looks_internal(self, base_url, internal):
        from app.services.extension_settings import looks_internal

        assert looks_internal(base_url) is internal


class TestTheBrowserVersion:
    def test_only_a_raised_version_changes_the_package(self):
        from app.services.extension_settings import raised_browser_version

        assert raised_browser_version(ExtensionSettings()) is None
        assert raised_browser_version(ExtensionSettings(min_browser_version=116)) is None
        assert raised_browser_version(ExtensionSettings(min_browser_version=142)) == 142
        # The template's own minimum is what counts as not raised.
        assert (
            raised_browser_version(ExtensionSettings(min_browser_version=120), {"minimum_chrome_version": "120"})
            is None
        )
        assert (
            raised_browser_version(ExtensionSettings(min_browser_version=142), {"minimum_chrome_version": "120"}) == 142
        )
