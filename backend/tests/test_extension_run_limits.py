"""The run limits on their own: time, versions, and the sites a step's page content names."""

from __future__ import annotations

import datetime

import pytest

from app.services.extension_page_context import PageContextRefused
from app.services.extension_run_limits import check_run_time, older_version, page_sites, start_of_today
from app.services.extension_settings import ExtensionSettings


class TestTheClock:
    def test_a_run_within_its_time_and_the_grace_goes_on(self):
        now = datetime.datetime(2026, 9, 27, 12, 0, tzinfo=datetime.UTC)
        began = int((now - datetime.timedelta(minutes=21)).timestamp() * 1000)
        check_run_time(ExtensionSettings(agent_max_minutes=20), began, now=now)

    def test_a_run_past_its_time_and_the_grace_is_refused(self):
        now = datetime.datetime(2026, 9, 27, 12, 0, tzinfo=datetime.UTC)
        began = int((now - datetime.timedelta(minutes=23)).timestamp() * 1000)
        with pytest.raises(PageContextRefused) as caught:
            check_run_time(ExtensionSettings(agent_max_minutes=20), began, now=now)
        assert caught.value.code == "run_too_long"
        assert caught.value.status == 403

    def test_a_step_that_does_not_say_when_it_began_is_left_to_the_stop_check(self):
        check_run_time(ExtensionSettings(agent_max_minutes=1), None)

    def test_today_starts_at_utc_midnight_and_is_naive_like_the_rows(self):
        start = start_of_today()
        assert start.tzinfo is None
        assert (start.hour, start.minute, start.second) == (0, 0, 0)


class TestVersions:
    @pytest.mark.parametrize(
        ("reported", "latest", "older"),
        [
            ("1.0.0.8", "1.0.0.9", True),
            ("1.0.0.9", "1.0.0.9", False),
            ("1.0.1.0", "1.0.0.9", False),
            ("1.0", "1.0.0.0", False),
            ("1.0", "1.0.0.1", True),
            ("garbage", "1.0.0.9", False),
            ("1.0.0.9", "", False),
        ],
    )
    def test_older(self, reported, latest, older):
        assert older_version(reported, latest) is older


class TestPageSites:
    def test_the_sites_the_tags_name_in_text_and_parts(self):
        messages = [
            {"role": "system", "content": "You are the agent."},
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": '<untrusted_page_content_ab12 site="app.corp.example">\nhi\n</untrusted_page_content_ab12>',
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": '<untrusted_page_content_ab12 site="Shop.Example.com">\nx\n</untrusted_page_content_ab12>',
                    },
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}},
                ],
            },
            {"role": "assistant", "content": None},
        ]
        assert page_sites(messages) == {"app.corp.example", "shop.example.com"}

    def test_a_name_that_is_not_a_host_is_left_out(self):
        messages = [
            {
                "role": "tool",
                "tool_call_id": "c",
                "content": '<untrusted_page_content_ab12 site="browser tabs">\n</untrusted_page_content_ab12>',
            }
        ]
        assert page_sites(messages) == set()
        assert page_sites([{"role": "user", "content": "no tags here"}]) == set()
        assert page_sites(["not a message"]) == set()
