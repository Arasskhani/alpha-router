"""A tool the user has not been given is refused where the request arrives.

Two shapes of request, and both have to be covered or the policy is a
suggestion:

* Web search, web fetch, the sandbox and private mode travel inside a chat
  turn. ``preflight_stream_chat`` is the only way into one - the browser and
  the OpenAI-compatible Gateway both call it - so that is where they are
  checked, and checking there covers an API key without a second guard.
* Image, video and speech generation and voice dictation are endpoints of
  their own, reached without a chat turn at all. A policy enforced only in the
  chat path would leave each of them wide open to anybody who can call the
  endpoint directly.
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException

from app.services.secret_crypto import encrypt_secret
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services import proxy_service
from app.services.chat_tool_access_service import set_chat_tool_access
from app.services.resource_access_service import AccessGrant


async def _enabled_model(db, external_id: str = "vendor/good") -> AIModel:
    connection = Connection(
        name="c1",
        provider_type="openai",
        api_key_encrypted=encrypt_secret("sk-test"),
        is_active=True,
    )
    db.add(connection)
    await db.flush()
    model = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=external_id,
        provider_type="openai",
        is_enabled=True,
        access_type="public",
    )
    db.add(model)
    await db.commit()
    return model


async def _preflight(db, user_id, body, **kwargs):
    return await proxy_service.preflight_stream_chat(
        db,
        body,
        user_id=user_id,
        skip_budget=True,
        source="alpha_router_chat",
        **kwargs,
    )


def _turn(**tools) -> dict:
    return {
        "model": "vendor/good",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": tools,
    }


_CSRF_TOKEN = "test-csrf-token"
_CSRF_HEADER = {"X-CSRF-Token": _CSRF_TOKEN}


def _sign_in(client, user) -> None:
    """A browser session: the auth cookie plus the CSRF pair the middleware wants."""
    from app.config import get_settings
    from app.core.security import create_access_token

    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, _CSRF_TOKEN)


class TestToolsAskedForInsideAChatTurn:
    async def test_a_restricted_tool_is_refused(self, db_session, user):
        await _enabled_model(db_session)
        await set_chat_tool_access(db_session, "web_search", access_type="private", grants=[])
        await db_session.commit()

        with pytest.raises(HTTPException) as caught:
            await _preflight(db_session, user.id, _turn(web_search=True))
        assert caught.value.status_code == 403
        assert caught.value.detail["code"] == "tool_not_permitted"
        assert caught.value.detail["tool"] == "web_search"

    async def test_the_same_turn_without_that_tool_is_not_refused(self, db_session, user):
        """The refusal must be about the tool, not the turn: everything else
        the user was allowed to do a moment ago still works."""
        await _enabled_model(db_session)
        await set_chat_tool_access(db_session, "web_search", access_type="private", grants=[])
        await db_session.commit()

        # Reaching the budget/provider stage rather than a 403 is the assertion;
        # this database has no pricing rows, so it fails later and elsewhere.
        try:
            await _preflight(db_session, user.id, _turn())
        except HTTPException as exc:
            assert exc.status_code != 403, exc.detail

    async def test_a_granted_user_is_let_through(self, db_session, user):
        await _enabled_model(db_session)
        await set_chat_tool_access(
            db_session,
            "web_search",
            access_type="private",
            grants=[AccessGrant(target_type="user", target=user.id)],
        )
        await db_session.commit()

        try:
            await _preflight(db_session, user.id, _turn(web_search=True))
        except HTTPException as exc:
            assert exc.status_code != 403, exc.detail

    async def test_the_legacy_top_level_web_search_flag_is_governed_too(self, db_session, user):
        """Clients that predate the ``tools`` object send it this way, and a
        policy that only reads the new shape would not apply to them."""
        await _enabled_model(db_session)
        await set_chat_tool_access(db_session, "web_search", access_type="private", grants=[])
        await db_session.commit()

        body = {"model": "vendor/good", "messages": [{"role": "user", "content": "hi"}], "web_search": True}
        with pytest.raises(HTTPException) as caught:
            await _preflight(db_session, user.id, body)
        assert caught.value.status_code == 403

    async def test_private_mode_is_a_tool_like_any_other(self, db_session, user):
        await _enabled_model(db_session)
        await set_chat_tool_access(db_session, "private_mode", access_type="private", grants=[])
        await db_session.commit()

        body = {"model": "vendor/good", "messages": [{"role": "user", "content": "hi"}], "private_mode": True}
        with pytest.raises(HTTPException) as caught:
            await _preflight(db_session, user.id, body)
        assert caught.value.detail["tool"] == "private_mode"

    async def test_a_gateway_key_is_judged_by_its_owner(self, db_session, user):
        """The Gateway shares this preflight, so an API key must not be a way
        around a restriction placed on the person who owns it."""
        from app.models.api_key import AlphaRouterApiKey

        await _enabled_model(db_session)
        key = AlphaRouterApiKey(
            name="k",
            key_prefix="ar_test",
            key_hash="x" * 64,
            owner_user_id=user.id,
            is_active=True,
        )
        db_session.add(key)
        await set_chat_tool_access(db_session, "code_interpreter", access_type="private", grants=[])
        await db_session.commit()

        with pytest.raises(HTTPException) as caught:
            await _preflight(
                db_session,
                None,
                _turn(code_interpreter=True),
                alpha_router_api_key_id=key.id,
            )
        assert caught.value.status_code == 403
        assert caught.value.detail["tool"] == "code_interpreter"

    async def test_the_sandbox_seat_is_not_taken_before_the_tool_is_refused(self, db_session, user, monkeypatch):
        """Order matters: acquiring a capacity lease for a turn that is about
        to be refused would hold a seat nobody uses until it expires."""
        await _enabled_model(db_session)
        await set_chat_tool_access(db_session, "code_interpreter", access_type="private", grants=[])
        await db_session.commit()

        taken = False

        async def _acquire(*args, **kwargs):
            nonlocal taken
            taken = True
            raise AssertionError("capacity acquired for a refused turn")

        monkeypatch.setattr(proxy_service, "acquire_code_interpreter_turn", _acquire)
        with pytest.raises(HTTPException) as caught:
            await _preflight(db_session, user.id, _turn(code_interpreter=True))
        assert caught.value.status_code == 403
        assert taken is False


class TestToolsWithAnEndpointOfTheirOwn:
    """Each of these is reachable without a chat turn, so each is checked."""

    @pytest.mark.parametrize(
        ("key", "path", "payload"),
        [
            ("image_generation", "/api/images/generate", {"model": "m", "prompt": "a cat"}),
            ("video_generation", "/api/videos/generate", {"model": "m", "prompt": "a cat"}),
            ("speech_generation", "/api/speech/generate", {"model": "m", "text": "hello"}),
        ],
    )
    async def test_a_restricted_generator_answers_403(self, client, db_session, user, key, path, payload):
        await set_chat_tool_access(db_session, key, access_type="private", grants=[])
        await db_session.commit()

        _sign_in(client, user)
        resp = await client.post(path, json=payload, headers=_CSRF_HEADER)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "tool_not_permitted"
        assert detail["tool"] == key

    async def test_voice_dictation_is_refused_before_the_upload_is_read(self, client, db_session, user):
        await set_chat_tool_access(db_session, "speech_to_text", access_type="private", grants=[])
        await db_session.commit()

        _sign_in(client, user)
        resp = await client.post(
            "/api/chat/voice",
            files={"file": ("voice.webm", io.BytesIO(b"not really audio"), "audio/webm")},
            headers=_CSRF_HEADER,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["tool"] == "speech_to_text"

    async def test_an_unrestricted_generator_is_not_refused(self, client, db_session, user):
        """No policy saved means everybody, which is what every one of these
        endpoints did before this existed."""
        _sign_in(client, user)
        resp = await client.post("/api/images/generate", json={"model": "m", "prompt": "a cat"}, headers=_CSRF_HEADER)
        assert resp.status_code != 403
