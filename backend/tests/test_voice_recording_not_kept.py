"""A dictation is transcribed and then gone.

The recording used to be written to the user's Media as an ``audio`` asset
after the transcript was returned, although nothing ever read it back. These
tests hold the new contract from both ends: the endpoint stores nothing and
starts nothing that would, and the transcription service leaves no copy of
the audio on disk — after success and after a provider failure alike.
"""

from __future__ import annotations

import io
import os
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.media import MediaAsset

#: Long enough to pass the service's "recording too short" floor.
AUDIO = b"RIFF" + bytes(range(256)) * 8


@pytest.fixture(autouse=True)
def _guards_on_the_test_engine(session_factory, monkeypatch):
    from app.services import admin_ip_allowlist_service

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


@pytest.fixture
async def funded_user(db_session, user):
    """The endpoint refuses an account without a budget plan before it reads
    the upload; these tests are about what happens after that gate."""
    plan = BudgetPlan(name="voice-tests", monthly_budget_usd=100.0)
    db_session.add(plan)
    await db_session.flush()
    db_session.add(PlanAssignment(plan_id=plan.id, user_id=user.id))
    await db_session.commit()
    return user


def _sign_in(client, user) -> dict[str, str]:
    from app.config import get_settings

    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf-token")
    return {settings.csrf_header_name: "csrf-token"}


async def _media_rows(db) -> int:
    return int((await db.execute(select(func.count()).select_from(MediaAsset))).scalar_one() or 0)


class TestTheEndpoint:
    @pytest.fixture
    def stubs(self, monkeypatch):
        """The two things this endpoint delegates to that need a network: the
        malware scan and the transcription provider. Everything about storage
        is left real and spied on, because storage is what must not happen."""
        monkeypatch.setattr("app.api.chat.screen_upload", AsyncMock(return_value=None))
        transcribe = AsyncMock(return_value="hello from the microphone")
        monkeypatch.setattr("app.api.chat.transcribe_audio_bytes", transcribe)
        put_object = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.storage_service._put_object_once", put_object)
        store_blob = AsyncMock()
        monkeypatch.setattr("app.services.storage_service.store_generated_blob", store_blob)
        return SimpleNamespace(transcribe=transcribe, put_object=put_object, store_blob=store_blob)

    async def test_the_transcript_comes_back_and_nothing_is_stored(self, client, db_session, funded_user, stubs):
        headers = _sign_in(client, funded_user)
        before = await _media_rows(db_session)

        resp = await client.post(
            "/api/chat/voice",
            headers=headers,
            files={"file": ("voice-1.webm", io.BytesIO(AUDIO), "audio/webm")},
            data={"language": "fa", "duration_seconds": "3.20"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "id": None,
            "url": None,
            "transcript": "hello from the microphone",
            "mime_type": "audio/webm",
            "media_pending": False,
            "media_error": None,
        }

        # The recording went to the provider once, and nowhere else.
        stubs.transcribe.assert_awaited_once()
        assert stubs.transcribe.await_args.args[1] == AUDIO
        stubs.store_blob.assert_not_called()
        stubs.put_object.assert_not_called()
        db_session.expire_all()
        assert await _media_rows(db_session) == before

    async def test_the_response_shape_is_the_old_one(self, client, db_session, funded_user, stubs):
        """A tab left open across the deploy still parses the reply: the keys
        that used to describe the stored asset are present and null."""
        headers = _sign_in(client, funded_user)
        body = (
            await client.post(
                "/api/chat/voice",
                headers=headers,
                files={"file": ("voice.webm", io.BytesIO(AUDIO), "audio/webm")},
            )
        ).json()
        assert set(body) == {"id", "url", "transcript", "mime_type", "media_pending", "media_error"}
        assert body["media_pending"] is False and body["media_error"] is None

    async def test_a_full_media_quota_no_longer_matters(self, client, db_session, funded_user, stubs, monkeypatch):
        """The quota guarded the copy that is no longer made. A person whose
        Media is full must still be able to dictate."""
        from app.services import user_media_service

        async def _full(*_a, **_k):
            raise user_media_service.MediaQuotaExceededError(used_bytes=10, incoming_bytes=1, quota_bytes=10)

        monkeypatch.setattr(user_media_service, "ensure_user_media_quota", _full)
        headers = _sign_in(client, funded_user)
        resp = await client.post(
            "/api/chat/voice", headers=headers, files={"file": ("v.webm", io.BytesIO(AUDIO), "audio/webm")}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["transcript"] == "hello from the microphone"

    async def test_a_provider_failure_stores_nothing_either(self, client, db_session, funded_user, stubs):
        stubs.transcribe.side_effect = RuntimeError("provider down")
        headers = _sign_in(client, funded_user)
        before = await _media_rows(db_session)
        resp = await client.post(
            "/api/chat/voice", headers=headers, files={"file": ("v.webm", io.BytesIO(AUDIO), "audio/webm")}
        )
        assert resp.status_code == 502
        stubs.store_blob.assert_not_called()
        db_session.expire_all()
        assert await _media_rows(db_session) == before

    def test_the_storage_path_is_gone_from_the_module(self):
        """Not disabled behind a flag: removed. A flag would be the first step
        back to keeping recordings nobody reads. The behavioural tests above
        prove nothing is stored; this one says the code that could is gone."""
        import inspect

        from app.api import chat as chat_api

        assert not hasattr(chat_api, "_store_voice_note")
        assert "background_tasks" not in inspect.signature(chat_api.voice_message).parameters


class TestTheServiceLeavesNoFile:
    """The LiteLLM path needs the audio as a file on disk for the length of
    one provider call. That file is the only other copy of the recording
    that ever exists, so it must be gone when the call returns — however
    it returns."""

    @pytest.fixture
    def provider(self, monkeypatch):
        from app.services import transcription_service as ts

        monkeypatch.setattr(
            ts,
            "resolve_transcription_target",
            AsyncMock(
                return_value=ts.ResolvedTranscription(
                    model_id="whisper-1",
                    api_key="sk-test",
                    base_url=None,
                    provider_type="openai",
                    connection_id=1,
                    ai_model=None,
                    source="admin",
                )
            ),
        )
        seen: dict[str, object] = {}

        async def fake_atranscription(**kwargs):
            audio_file = kwargs["file"]
            seen["path"] = audio_file.name
            seen["mode"] = stat.S_IMODE(os.stat(audio_file.name).st_mode)
            seen["bytes"] = audio_file.read()
            if seen.get("fail"):
                raise RuntimeError("provider exploded")
            return SimpleNamespace(text="transcribed", duration=1.5)

        monkeypatch.setattr(ts, "atranscription", fake_atranscription)
        return seen

    async def test_the_temp_file_holds_the_audio_privately_and_is_removed_on_success(self, db_session, provider):
        from app.services.transcription_service import transcribe_audio_bytes

        text = await transcribe_audio_bytes(db_session, AUDIO, filename="voice.webm", mime_type="audio/webm")
        assert text == "transcribed"
        assert provider["bytes"] == AUDIO
        # Readable by the process owner only; another account on the host
        # must not be able to read a person's voice off /tmp.
        assert provider["mode"] == 0o600
        assert not os.path.exists(str(provider["path"]))

    async def test_the_temp_file_is_removed_when_the_provider_fails(self, db_session, provider):
        from app.services.transcription_service import transcribe_audio_bytes

        provider["fail"] = True
        with pytest.raises(RuntimeError):
            await transcribe_audio_bytes(db_session, AUDIO, filename="voice.webm", mime_type="audio/webm")
        assert not os.path.exists(str(provider["path"]))

    async def test_the_openrouter_path_never_touches_the_disk(self, db_session, monkeypatch):
        """OpenRouter takes base64 in JSON, so there is no file at all."""
        from app.services import transcription_service as ts

        monkeypatch.setattr(
            ts,
            "resolve_transcription_target",
            AsyncMock(
                return_value=ts.ResolvedTranscription(
                    model_id="openai/whisper-1",
                    api_key="sk-or",
                    base_url="https://openrouter.ai/api/v1",
                    provider_type="openrouter",
                    connection_id=1,
                    ai_model=None,
                    source="admin",
                )
            ),
        )
        monkeypatch.setattr(
            ts, "transcribe_with_openrouter", AsyncMock(return_value=SimpleNamespace(text="ok", duration=None))
        )
        writes = AsyncMock()
        monkeypatch.setattr(ts, "_write_temp_audio", writes)
        assert await ts.transcribe_audio_bytes(db_session, AUDIO, filename="voice.webm") == "ok"
        writes.assert_not_called()
