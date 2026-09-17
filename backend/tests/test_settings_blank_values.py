"""An empty value in .env means "leave the default", not "the value is ''".

This is what stopped a production upgrade. ``.env.example`` gained the line

    VIDEO_MAX_DURATION_SECONDS=

and ``merge_env_from_example`` copies any key the operator's ``.env`` does not
have yet - verbatim, empty value included. On the next start, pydantic read the
variable as present-and-empty, could not parse it as an int, and db-init died
at import time before a single migration ran. What the operator saw was a
pydantic traceback with no mention of which file to edit.

About 150 of the 216 settings are typed int, float or bool, so any one of them
left blank would have done the same. All 150 have defaults, which is why
falling back to the default is always safe.
"""

from __future__ import annotations

import os
import pathlib
from unittest.mock import patch

import pytest
from pydantic_settings import SettingsConfigDict

from app.config import Settings, _fields_rejecting_blank, get_settings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _settings(**env) -> Settings:
    with patch.dict(os.environ, env, clear=False):
        return Settings()


class TestBlankMeansUnset:
    def test_the_value_that_broke_the_upgrade(self):
        assert _settings(VIDEO_MAX_DURATION_SECONDS="").video_max_duration_seconds is None

    def test_a_blank_int_falls_back_to_its_default(self):
        default = Settings.model_fields["db_pool_size"].default
        assert _settings(DB_POOL_SIZE="").db_pool_size == default

    def test_a_blank_bool_falls_back_to_its_default(self):
        default = Settings.model_fields["enable_hsts"].default
        assert _settings(ENABLE_HSTS="").enable_hsts is default

    def test_a_blank_float_falls_back_to_its_default(self):
        default = Settings.model_fields["budget_hold_buffer"].default
        assert _settings(BUDGET_HOLD_BUFFER="").budget_hold_buffer == default

    def test_whitespace_counts_as_blank(self):
        assert _settings(DB_POOL_SIZE="   ").db_pool_size == Settings.model_fields["db_pool_size"].default

    def test_a_real_value_is_still_read(self):
        """The fix must not swallow values, only blanks."""
        assert _settings(DB_POOL_SIZE="7").db_pool_size == 7

    def test_a_malformed_value_still_fails(self):
        """A typo is an operator error worth reporting; a blank line is not."""
        with pytest.raises(Exception, match="db_pool_size|int_parsing"):
            _settings(DB_POOL_SIZE="twelve")

    def test_a_blank_string_setting_stays_blank(self):
        """REDIS_PASSWORD= means "no password", not "use the default". Text
        settings are deliberately untouched."""
        assert _settings(REDIS_PASSWORD="").redis_password == ""

    def test_every_field_that_rejects_a_blank_has_a_default(self):
        """The premise of the fix: dropping a blank can never turn into a
        "field required" error."""
        from pydantic_core import PydanticUndefined

        for name in _fields_rejecting_blank(Settings):
            field = Settings.model_fields[name]
            assert field.default is not PydanticUndefined or field.default_factory is not None, name


class TestTheShippedTemplate:
    """.env.example is copied to .env on a fresh install and merged into an
    existing .env on upgrade, so a value it cannot parse breaks deployments
    rather than tests."""

    def test_the_example_env_produces_valid_settings(self):
        example = REPO_ROOT / ".env.example"
        assert example.is_file(), example

        class FromExample(Settings):
            model_config = SettingsConfigDict(env_file=str(example), env_file_encoding="utf-8", extra="ignore")

        # The template alone, with no inherited process environment.
        with patch.dict(os.environ, {}, clear=True):
            FromExample()
