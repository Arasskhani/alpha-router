"""Web search services: requests they send, results they read, and what each failure means."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services import web_search_providers as wsp
from app.services.web_search_providers import SearchTarget, WebSearchError, run_search


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.services.ssrf_guard.assert_url_safe", lambda url: None)
    monkeypatch.setattr("app.services.ssrf_guard.assert_response_target_safe", lambda response: None)


class Recorder:
    """A transport that answers every request with one response, and keeps the requests."""

    def __init__(
        self, status: int = 200, body: object = None, *, text: str | None = None, error: Exception | None = None
    ):
        self.status = status
        self.body = body
        self.text = text
        self.error = error
        self.requests: list[httpx.Request] = []

    def factory(self, **kwargs):
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.error is not None:
                raise self.error
            if self.text is not None:
                return httpx.Response(self.status, text=self.text)
            return httpx.Response(self.status, json=self.body)

        kwargs.pop("transport", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)


async def _search(target: SearchTarget, recorder: Recorder, query: str = "python release", limit: int = 5):
    return await run_search(target, query, limit, client_factory=recorder.factory)


class TestBrave:
    async def test_sends_the_key_in_its_header_and_reads_the_results(self):
        rec = Recorder(
            body={"web": {"results": [{"title": "Python", "url": "https://python.org", "description": "Home"}]}}
        )
        rows = await _search(SearchTarget("brave", api_key="BSA-key"), rec)
        assert [(r.title, r.url, r.snippet) for r in rows] == [("Python", "https://python.org", "Home")]
        request = rec.requests[0]
        assert request.headers["X-Subscription-Token"] == "BSA-key"
        assert request.url.params["q"] == "python release"
        assert request.url.params["count"] == "5"

    @pytest.mark.parametrize(
        ("status", "body", "code"),
        [
            (401, {"error": "unauthorized"}, "auth"),
            (429, {"error": "too many requests"}, "rate_limited"),
            (429, {"error": "monthly quota exceeded"}, "quota"),
            (402, {"error": "payment"}, "quota"),
            (500, {}, "network"),
            (400, {}, "bad_response"),
        ],
    )
    async def test_each_refusal_says_what_it_is(self, status, body, code):
        with pytest.raises(WebSearchError) as raised:
            await _search(SearchTarget("brave", api_key="BSA-key"), Recorder(status, body))
        assert raised.value.code == code
        assert "BSA-key" not in raised.value.message


class TestTavily:
    async def test_sends_a_bearer_key_and_keeps_the_page_text(self):
        rec = Recorder(body={"results": [{"title": "T", "url": "https://t.example", "content": "the relevant part"}]})
        rows = await _search(SearchTarget("tavily", api_key="tvly-key"), rec, limit=3)
        assert rows[0].content == "the relevant part"
        request = rec.requests[0]
        assert request.headers["Authorization"] == "Bearer tvly-key"
        assert json.loads(request.content) == {"query": "python release", "max_results": 3, "search_depth": "basic"}

    async def test_a_plan_limit_is_a_spent_quota(self):
        with pytest.raises(WebSearchError) as raised:
            await _search(SearchTarget("tavily", api_key="k"), Recorder(432, {"detail": "plan limit"}))
        assert raised.value.code == "quota"


class TestGoogle:
    async def test_sends_key_and_engine_and_never_shows_the_key_in_an_error(self):
        rec = Recorder(body={"items": [{"title": "G", "link": "https://g.example", "snippet": "s"}]})
        rows = await _search(SearchTarget("google", api_key="AIza-secret", config={"cx": "abc"}), rec, limit=20)
        assert rows[0].url == "https://g.example"
        params = rec.requests[0].url.params
        assert (params["key"], params["cx"], params["num"]) == ("AIza-secret", "abc", "10")
        failing = Recorder(error=httpx.ConnectError("boom https://www.googleapis.com/customsearch/v1?key=AIza-secret"))
        with pytest.raises(WebSearchError) as raised:
            await _search(SearchTarget("google", api_key="AIza-secret", config={"cx": "abc"}), failing)
        assert raised.value.code == "network"
        assert "AIza-secret" not in raised.value.message

    async def test_a_daily_limit_is_a_quota_not_a_bad_key(self):
        body = {"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}
        with pytest.raises(WebSearchError) as raised:
            await _search(SearchTarget("google", api_key="k", config={"cx": "abc"}), Recorder(403, body))
        assert raised.value.code == "quota"

    async def test_without_its_engine_id_nothing_is_sent(self):
        rec = Recorder(body={})
        with pytest.raises(WebSearchError) as raised:
            await _search(SearchTarget("google", api_key="k"), rec)
        assert raised.value.code == "not_configured"
        assert rec.requests == []


class TestSearxng:
    async def test_asks_its_own_server_for_json(self):
        rec = Recorder(body={"results": [{"title": "S", "url": "https://s.example", "content": "c"}] * 3})
        rows = await _search(SearchTarget("searxng", base_url="https://search.corp.example/"), rec)
        assert len(rows) == 1  # one row per address
        request = rec.requests[0]
        assert str(request.url).startswith("https://search.corp.example/search?")
        assert request.url.params["format"] == "json"

    async def test_a_403_means_json_is_off_in_its_settings(self):
        with pytest.raises(WebSearchError) as raised:
            await _search(SearchTarget("searxng", base_url="https://s.example"), Recorder(403, text="Forbidden"))
        assert raised.value.code == "not_configured"
        assert "settings.yml" in raised.value.message


class TestDuckDuckGo:
    async def test_reads_the_rows_ddgs_returns(self):
        def runner(query, limit):
            return [{"title": "D", "href": "https://d.example", "body": "b"}, {"title": "bad", "href": "javascript:x"}]

        rows = await run_search(SearchTarget("duckduckgo"), "q", 5, ddgs_runner=runner)
        assert [r.url for r in rows] == ["https://d.example"]

    async def test_a_rate_limit_is_told_as_one(self):
        class RatelimitException(Exception):
            pass

        def runner(query, limit):
            raise RatelimitException("202 Ratelimit")

        with pytest.raises(WebSearchError) as raised:
            await run_search(SearchTarget("duckduckgo"), "q", 5, ddgs_runner=runner)
        assert raised.value.code == "rate_limited"


async def test_a_timeout_is_a_network_failure():
    with pytest.raises(WebSearchError) as raised:
        await _search(SearchTarget("brave", api_key="k"), Recorder(error=httpx.ReadTimeout("slow")))
    assert raised.value.code == "network"
    assert "did not answer" in raised.value.message


async def test_an_internal_address_is_refused_with_the_setting_that_allows_it(monkeypatch):
    from app.services.ssrf_guard import SSRFBlockedError

    def blocked(url):
        raise SSRFBlockedError("private")

    monkeypatch.setattr("app.services.ssrf_guard.assert_url_safe", blocked)
    with pytest.raises(WebSearchError) as raised:
        await _search(SearchTarget("searxng", base_url="http://10.0.0.5"), Recorder(body={}))
    assert raised.value.code == "not_configured"
    assert "ALLOW_SSRF_PRIVATE_RANGES" in raised.value.message


async def test_results_are_cut_to_size_and_an_unknown_provider_is_refused():
    long = "x" * 5000
    rec = Recorder(body={"web": {"results": [{"title": long, "url": "https://a.example", "description": long}]}})
    [row] = await _search(SearchTarget("brave", api_key="k"), rec)
    assert len(row.title) <= 200 and len(row.snippet) <= wsp.MAX_SNIPPET_CHARS
    with pytest.raises(WebSearchError):
        await run_search(SearchTarget("openai"), "q", 5)
