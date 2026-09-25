"""Pages the extension shares in a chat turn: the site and model rules, and one Admin Logs row per site."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import chat as chat_api
from app.config import get_settings
from app.core.security import create_access_token
from app.models.connection import Connection
from app.models.extension import ExtensionEvent
from app.models.model_catalog import AIModel
from app.services import extension_tokens
from app.services.extension_page_context import page_shares
from app.services.extension_settings import ExtensionSettings, save_extension_settings
from app.services.extension_tokens import create_session
from app.services.model_resolution_service import resolve_model_row
from app.services.secret_crypto import encrypt_secret

SERVER = "https://ai.example.com"
CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr(extension_tokens, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr(get_settings(), "frontend_url", f"{SERVER}/")


class FakeTurn:
    """Stands in for the proxy: records what the endpoint hands it and resolves the model as preflight does."""

    def __init__(self) -> None:
        self.preflights: list[dict] = []
        self.streams: list[dict] = []
        self.refusal: HTTPException | None = None

    async def preflight(self, db, payload, **kwargs):
        if self.refusal is not None:
            raise self.refusal
        payload["_effective_private_mode"] = bool(payload.get("private_mode"))
        self.preflights.append({"payload": dict(payload), **kwargs})
        found = await resolve_model_row(db, str(payload.get("model") or ""))
        if found is None:
            raise HTTPException(status_code=404, detail="Model not enabled")
        return SimpleNamespace(ai_model=found[0], code_interpreter_capacity_permit=None)

    def stream(self, request, payload, **kwargs):
        self.streams.append({"payload": payload, **kwargs})

        async def frames():
            yield "data: [DONE]\n\n"

        return frames()


@pytest.fixture
def turn(monkeypatch) -> FakeTurn:
    fake = FakeTurn()
    monkeypatch.setattr(chat_api, "preflight_stream_chat", fake.preflight)
    monkeypatch.setattr(chat_api, "stream_chat", fake.stream)
    return fake


async def _model(db, external_id: str) -> AIModel:
    connection = Connection(
        name=f"c-{external_id}", provider_type="openai", api_key_encrypted=encrypt_secret("sk-x"), is_active=True
    )
    db.add(connection)
    await db.flush()
    row = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=f"Model {external_id}",
        provider_type="openai",
        is_enabled=True,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
async def models(db_session) -> SimpleNamespace:
    return SimpleNamespace(a=await _model(db_session, "gpt-a"), b=await _model(db_session, "gpt-b"))


async def _settings(db, **values) -> None:
    await save_extension_settings(db, ExtensionSettings(**values))
    await db.commit()


@pytest.fixture
async def browser(db_session, user) -> SimpleNamespace:
    pair = await create_session(db_session, user=user, device_name="Chrome", user_agent="UA", ip="10.0.0.5")
    await db_session.commit()
    return SimpleNamespace(session_id=pair.session_id, headers={"Authorization": f"Bearer {pair.access_token}"})


def _body(model: str, *sites: tuple[str, int], **extra) -> dict:
    body: dict = {"model": model, "messages": [{"role": "user", "content": "What is on this page?"}], **extra}
    if sites:
        body["extension_page_context"] = {"sites": [{"host": host, "chars": chars} for host, chars in sites]}
    return body


async def _events(session_factory) -> list[ExtensionEvent]:
    async with session_factory() as fresh:
        rows = await fresh.execute(select(ExtensionEvent).order_by(ExtensionEvent.id))
        return list(rows.scalars().all())


def _sign_in(client, user) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


class TestAccepted:
    async def test_each_site_is_recorded_once_the_turn_goes_ahead(
        self, client, browser, models, turn, user, session_factory
    ):
        resp = await client.post(
            "/api/chat/completions",
            json=_body(f"model::{models.a.id}", ("docs.example.com", 1200), ("intranet", 300)),
            headers=browser.headers,
        )
        assert resp.status_code == 200, resp.text
        events = await _events(session_factory)
        assert [(e.kind, e.site) for e in events] == [
            ("page_context", "docs.example.com"),
            ("page_context", "intranet"),
        ]
        first = events[0]
        assert first.actor_user_id == user.id
        assert first.actor_username == user.username
        assert first.session_id == browser.session_id
        assert first.actor_ip == "127.0.0.1"
        assert json.loads(first.detail_json) == {
            "chars": 1200,
            "model": f"model::{models.a.id}",
            "model_name": "Model gpt-a",
            "private": False,
        }
        # Never the text.
        assert "What is on this page" not in first.detail_json

    async def test_the_turn_is_named_as_the_extension_s(self, client, browser, models, turn):
        await client.post(
            "/api/chat/completions", json=_body(f"model::{models.a.id}", ("example.com", 5)), headers=browser.headers
        )
        assert turn.preflights[0]["client_app"] == "Alpharouter Extension"
        assert turn.streams[0]["client_app"] == "Alpharouter Extension"

    async def test_two_tabs_on_one_site_are_one_row(self, client, browser, models, turn, session_factory):
        resp = await client.post(
            "/api/chat/completions",
            json=_body(f"model::{models.a.id}", ("Example.COM.", 100), ("example.com", 50)),
            headers=browser.headers,
        )
        assert resp.status_code == 200, resp.text
        [event] = await _events(session_factory)
        assert event.site == "example.com"
        assert json.loads(event.detail_json)["chars"] == 150

    async def test_a_private_chat_is_recorded_as_one(self, client, browser, models, turn, session_factory):
        resp = await client.post(
            "/api/chat/completions",
            json=_body(f"model::{models.a.id}", ("example.com", 5), private_mode=True),
            headers=browser.headers,
        )
        assert resp.status_code == 200, resp.text
        [event] = await _events(session_factory)
        assert json.loads(event.detail_json)["private"] is True

    async def test_the_checked_model_is_the_one_the_turn_uses(self, client, browser, db_session, models, turn):
        await _settings(db_session, page_content_models=(f"model::{models.a.id}",))
        resp = await client.post(
            "/api/chat/completions", json=_body("gpt-a", ("example.com", 5)), headers=browser.headers
        )
        assert resp.status_code == 200, resp.text
        assert turn.preflights[0]["payload"]["model"] == f"model::{models.a.id}"

    async def test_an_allow_list_never_shuts_out_alpharouter_itself(self, client, browser, db_session, models, turn):
        await _settings(db_session, allowed_sites=("example.com",))
        resp = await client.post(
            "/api/chat/completions", json=_body(f"model::{models.a.id}", ("ai.example.com", 5)), headers=browser.headers
        )
        assert resp.status_code == 200, resp.text

    async def test_a_listed_subdomain_pattern_covers_the_site(self, client, browser, db_session, models, turn):
        await _settings(db_session, allowed_sites=("*.corp.example",))
        for host in ("corp.example", "wiki.corp.example"):
            resp = await client.post(
                "/api/chat/completions", json=_body(f"model::{models.a.id}", (host, 5)), headers=browser.headers
            )
            assert resp.status_code == 200, (host, resp.text)


class TestRefused:
    async def test_a_blocked_site(self, client, browser, db_session, models, turn, session_factory):
        await _settings(db_session, blocked_sites=("*.bank.example",))
        resp = await client.post(
            "/api/chat/completions",
            json=_body(f"model::{models.a.id}", ("example.com", 5), ("online.bank.example", 5)),
            headers=browser.headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "site_not_allowed"
        assert resp.json()["detail"]["site"] == "online.bank.example"
        assert turn.preflights == []
        assert await _events(session_factory) == []

    async def test_a_block_wins_over_the_server_itself(self, client, browser, db_session, models, turn):
        await _settings(db_session, blocked_sites=("ai.example.com",))
        resp = await client.post(
            "/api/chat/completions", json=_body(f"model::{models.a.id}", ("ai.example.com", 5)), headers=browser.headers
        )
        assert resp.status_code == 403

    async def test_a_site_outside_the_allow_list(self, client, browser, db_session, models, turn, session_factory):
        await _settings(db_session, allowed_sites=("wiki.example.com",))
        resp = await client.post(
            "/api/chat/completions",
            json=_body(f"model::{models.a.id}", ("mail.example.com", 5)),
            headers=browser.headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == {
            "code": "site_not_allowed",
            "message": "Your administrator does not allow sharing pages from mail.example.com.",
            "site": "mail.example.com",
        }
        assert turn.preflights == []
        assert await _events(session_factory) == []

    @pytest.mark.parametrize("ref", ["model::{b}", "gpt-b"])
    async def test_a_model_outside_the_list(self, client, browser, db_session, models, turn, session_factory, ref):
        await _settings(db_session, page_content_models=(f"model::{models.a.id}",))
        resp = await client.post(
            "/api/chat/completions",
            json=_body(ref.format(b=models.b.id), ("example.com", 5)),
            headers=browser.headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "model_not_allowed"
        assert turn.preflights == []
        assert await _events(session_factory) == []

    async def test_an_unknown_model_when_there_is_a_list(self, client, browser, db_session, models, turn):
        await _settings(db_session, page_content_models=(f"model::{models.a.id}",))
        for ref in ("gpt-unknown", "model::999999", ""):
            resp = await client.post(
                "/api/chat/completions", json=_body(ref, ("example.com", 5)), headers=browser.headers
            )
            assert resp.status_code == 403, ref
            assert resp.json()["detail"]["code"] == "model_not_allowed"

    async def test_an_unknown_model_without_a_list_is_the_turn_s_to_refuse(
        self, client, browser, models, turn, session_factory
    ):
        resp = await client.post(
            "/api/chat/completions", json=_body("gpt-unknown", ("example.com", 5)), headers=browser.headers
        )
        assert resp.status_code == 404
        assert turn.preflights[0]["payload"]["model"] == "gpt-unknown"
        assert await _events(session_factory) == []

    async def test_nothing_is_recorded_when_the_turn_is_refused(self, client, browser, models, turn, session_factory):
        turn.refusal = HTTPException(status_code=402, detail="Budget exceeded")
        resp = await client.post(
            "/api/chat/completions", json=_body(f"model::{models.a.id}", ("example.com", 5)), headers=browser.headers
        )
        assert resp.status_code == 402
        assert await _events(session_factory) == []

    async def test_only_the_extension_can_share_pages(self, client, models, turn, user, session_factory):
        resp = await client.post(
            "/api/chat/completions",
            json=_body(f"model::{models.a.id}", ("example.com", 5)),
            headers=_sign_in(client, user),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "extension_only"
        assert turn.preflights == []
        assert await _events(session_factory) == []

    @pytest.mark.parametrize(
        ("extra", "why"),
        [
            ({"agent_id": "agent-1"}, "agent"),
            ({"agent_auto_route": True}, "agent"),
            ({"alpharouter": {"agent": "helpdesk"}}, "agent"),
            ({"include_citations": True}, "agent"),
            ({"project_id": "project-1"}, "project"),
            ({"web_search": True}, "tools"),
            ({"tools": {"web_fetch": True}}, "tools"),
            ({"tools": {"code_interpreter": True}}, "tools"),
            ({"tools": {"image_generation": True}}, "tools"),
        ],
    )
    async def test_not_with_an_agent_a_project_or_tools(self, client, browser, models, turn, extra, why):
        resp = await client.post(
            "/api/chat/completions",
            json=_body(f"model::{models.a.id}", ("example.com", 5), **extra),
            headers=browser.headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "page_context_conflict"
        assert why in resp.json()["detail"]["message"]
        assert turn.preflights == []

    async def test_tools_left_off_are_fine(self, client, browser, models, turn):
        resp = await client.post(
            "/api/chat/completions",
            json=_body(
                f"model::{models.a.id}",
                ("example.com", 5),
                tools={"web_search": False, "web_search_depth": "deep", "code_interpreter": False},
            ),
            headers=browser.headers,
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "host",
        ["https://example.com", "example.com/path", "*.example.com", "exa mple.com", "user@example.com", "-x.com"],
    )
    async def test_a_declared_site_must_be_a_host_name(self, client, browser, models, turn, host):
        resp = await client.post(
            "/api/chat/completions", json=_body(f"model::{models.a.id}", (host, 5)), headers=browser.headers
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_request"

    @pytest.mark.parametrize(
        "context",
        [
            {"sites": []},
            {"sites": [{"host": f"site{i}.example", "chars": 1} for i in range(21)]},
            {"sites": [{"host": "example.com", "chars": -1}]},
            {"sites": [{"host": "", "chars": 1}]},
            {"sites": [{"host": "example.com"}]},
        ],
    )
    async def test_the_declaration_is_bounded(self, client, browser, models, turn, context):
        body = _body(f"model::{models.a.id}")
        body["extension_page_context"] = context
        resp = await client.post("/api/chat/completions", json=body, headers=browser.headers)
        assert resp.status_code == 422
        assert turn.preflights == []


class TestOtherTurns:
    async def test_an_extension_turn_without_a_page(self, client, browser, models, turn, session_factory):
        resp = await client.post("/api/chat/completions", json=_body(f"model::{models.a.id}"), headers=browser.headers)
        assert resp.status_code == 200, resp.text
        assert turn.preflights[0]["client_app"] == "Alpharouter Extension"
        assert await _events(session_factory) == []

    async def test_the_web_app_is_unchanged(self, client, models, turn, user, session_factory):
        resp = await client.post(
            "/api/chat/completions", json=_body(f"model::{models.a.id}"), headers=_sign_in(client, user)
        )
        assert resp.status_code == 200, resp.text
        assert turn.preflights[0]["client_app"] == "Alpharouter Chat"
        assert turn.streams[0]["client_app"] == "Alpharouter Chat"
        assert turn.preflights[0]["payload"]["model"] == f"model::{models.a.id}"


class TestTitles:
    async def test_the_extension_s_titles_are_named_as_its_own(self, client, browser, monkeypatch):
        title = AsyncMock(return_value="A title")
        monkeypatch.setattr(chat_api, "generate_chat_title", title)
        resp = await client.post(
            "/api/chat/session-title",
            json={"model": "model::1", "messages": [{"role": "user", "content": "hi"}]},
            headers=browser.headers,
        )
        assert resp.json() == {"title": "A title"}
        assert title.await_args.kwargs["client_app"] == "Alpharouter Extension"

    async def test_the_web_app_s_titles_are_unchanged(self, client, user, monkeypatch):
        title = AsyncMock(return_value="A title")
        monkeypatch.setattr(chat_api, "generate_chat_title", title)
        await client.post(
            "/api/chat/session-title",
            json={"model": "model::1", "messages": [{"role": "user", "content": "hi"}]},
            headers=_sign_in(client, user),
        )
        assert title.await_args.kwargs["client_app"] == "Alpharouter Chat"


class TestPageShares:
    def test_hosts_are_normalized_like_the_browser_reports_them(self):
        shares = page_shares([("Bücher.Example.", 3), ("[::1]", 4), ("10.0.0.5", 1), ("my_server.local", 2)])
        assert [(s.host, s.chars) for s in shares] == [
            ("xn--bcher-kva.example", 3),
            ("[::1]", 4),
            ("10.0.0.5", 1),
            ("my_server.local", 2),
        ]
