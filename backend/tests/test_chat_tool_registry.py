"""The registry has to stay the truth about which tools exist.

Everything downstream - the access policy, the admin page, the endpoint that
tells a client what it may use - enumerates :data:`CHAT_TOOLS` and nothing
else. That is what lets a new tool arrive with governance already attached,
and it is also the failure mode: a toggle added to the request model but not
to the registry is a tool no administrator can restrict, silently.

Nothing at build time catches that, so it is caught here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.chat import ChatToolsIn
from app.services.chat_tool_registry import (
    CHAT_TOOLS,
    KNOWN_ICONS,
    REQUEST_TOOL_KEYS,
    TOOL_BY_KEY,
    is_valid_key,
    requested_tool_keys,
    spec_or_none,
)
from app.services.chat_tools_service import ChatToolsConfig


def _request_model_flags() -> set[str]:
    """The boolean toggles a client can send in ``tools``."""
    return {
        name
        for name, field in ChatToolsIn.model_fields.items()
        if field.annotation is bool  # type: ignore[misc]
    }


class TestEveryToggleIsGoverned:
    def test_the_request_model_and_the_registry_name_the_same_tools(self):
        assert _request_model_flags() == set(REQUEST_TOOL_KEYS)

    def test_every_request_key_is_a_registered_tool(self):
        assert set(TOOL_BY_KEY) >= REQUEST_TOOL_KEYS

    def test_the_execution_config_carries_no_tool_the_registry_omits(self):
        """``ChatToolsConfig`` is what the turn acts on. A field there with no
        registry entry is a tool that runs without a policy."""
        acted_on = {name for name in ChatToolsConfig.__dataclass_fields__ if not name.endswith("_depth")}
        assert set(TOOL_BY_KEY) >= acted_on


class TestTheRegistryIsWellFormed:
    def test_keys_are_unique(self):
        keys = [spec.key for spec in CHAT_TOOLS]
        assert len(keys) == len(set(keys))

    @pytest.mark.parametrize("spec", CHAT_TOOLS, ids=lambda s: s.key)
    def test_each_entry_is_usable(self, spec):
        assert is_valid_key(spec.key)
        assert spec.title.strip() and spec.description.strip()
        assert spec.icon in KNOWN_ICONS
        assert spec.default_access in ("public", "private")

    def test_the_extension_tools_are_registered_but_never_asked_for_by_a_chat_turn(self):
        """The browser extension is governed here, but the composer has no toggle for it."""
        assert TOOL_BY_KEY["browser_extension"].default_access == "public"
        assert TOOL_BY_KEY["browser_agent"].default_access == "private"
        assert {"browser_extension", "browser_agent"}.isdisjoint(REQUEST_TOOL_KEYS)
        body = {"tools": {"browser_extension": True, "browser_agent": True}, "browser_agent": True}
        assert requested_tool_keys(body) == frozenset()

    def test_the_client_draws_every_icon_the_registry_may_send(self):
        """An icon the client does not know renders as a generic glyph on the admin page."""
        source = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "ChatToolIcon.tsx"
        drawn = set(re.findall(r'case "([a-z]+)":', source.read_text(encoding="utf-8")))
        assert drawn == set(KNOWN_ICONS)

    def test_lookup_ignores_surrounding_space_and_unknown_keys(self):
        assert spec_or_none(" web_search ") is TOOL_BY_KEY["web_search"]
        assert spec_or_none("no_such_tool") is None

    @pytest.mark.parametrize("bad", ["", "Web_Search", "9lives", "a", "web-search", "x" * 65])
    def test_a_key_that_would_not_survive_a_url_is_rejected(self, bad):
        assert not is_valid_key(bad)


class TestReadingWhatATurnAsksFor:
    def test_both_shapes_of_the_request_are_understood(self):
        assert requested_tool_keys({"tools": {"web_fetch": True}}) == {"web_fetch"}
        # The top-level flag predates the tools object and is still accepted.
        assert requested_tool_keys({"web_search": True}) == {"web_search"}

    def test_private_mode_travels_on_its_own_field(self):
        assert requested_tool_keys({"private_mode": True}) == {"private_mode"}

    def test_tools_left_off_are_not_asked_for(self):
        body = {"tools": {"web_search": False, "code_interpreter": False}, "private_mode": False}
        assert requested_tool_keys(body) == frozenset()

    def test_settings_that_travel_beside_the_toggles_are_not_tools(self):
        """``web_search_depth`` is a knob, not something to grant."""
        assert requested_tool_keys({"tools": {"web_search_depth": "high"}}) == frozenset()

    def test_an_unknown_key_is_not_smuggled_through(self):
        assert requested_tool_keys({"tools": {"rm_rf": True}}) == frozenset()
