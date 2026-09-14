"""Phase 2.13 hardening batch: one focused test per fix."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


# --- B-19: loopback / RFC1918 origins are development-only -----------------


def test_private_and_loopback_origins_rejected_in_production(monkeypatch):
    from app.services import csrf_protection as csrf

    monkeypatch.setattr(csrf, "get_settings", lambda: SimpleNamespace(environment="production", frontend_url="https://app.example.com"))
    assert csrf.origin_allowed("https://app.example.com")
    assert not csrf.origin_allowed("http://localhost:8080")
    assert not csrf.origin_allowed("http://192.168.1.20:8080")
    assert csrf.development_origins() == set()

    monkeypatch.setattr(csrf, "get_settings", lambda: SimpleNamespace(environment="development", frontend_url="https://app.example.com"))
    assert csrf.origin_allowed("http://localhost:8080")
    assert csrf.origin_allowed("http://192.168.1.20:8080")


# --- B-29: constant-time master key ------------------------------------------


def test_master_key_comparison_is_constant_time_and_rejects_empty(monkeypatch):
    from app.api import gateway

    monkeypatch.setattr(gateway, "settings", SimpleNamespace(gateway_master_key="sk-master-123"))
    assert gateway._is_master_key("sk-master-123")
    assert not gateway._is_master_key("sk-master-12")
    monkeypatch.setattr(gateway, "settings", SimpleNamespace(gateway_master_key=""))
    assert not gateway._is_master_key("")


# --- #17: admin IP guard fails closed ----------------------------------------


def test_admin_ip_guard_answers_503_without_policy_and_db():
    from app.services import admin_ip_guard as guard

    sent = []

    async def app(scope, receive, send):
        sent.append("passed-through")

    async def send(message):
        sent.append(message)

    class _BrokenSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    mw = guard.AdminIpGuardMiddleware(app)
    scope = {"type": "http", "path": "/api/admin/users", "headers": [], "method": "GET", "client": ("10.0.0.1", 1)}

    async def run():
        with (
            patch.object(guard, "peek_restriction_state", lambda allow_stale=False: None),
            patch.object(guard, "AsyncSessionLocal", _BrokenSession),
            patch.object(guard, "path_is_admin_surface", lambda p: True),
            patch.object(guard, "resolve_client_ip", lambda r: "10.0.0.1"),
        ):
            await mw(scope, None, send)

    asyncio.run(run())
    assert "passed-through" not in sent
    start = next(m for m in sent if isinstance(m, dict) and m.get("type") == "http.response.start")
    assert start["status"] == 503


# --- #23: spreadsheet formula injection -------------------------------------


def test_xlsx_cells_starting_with_formula_characters_are_escaped():
    from app.services.chat_xlsx_service import _safe_cell

    assert _safe_cell("=HYPERLINK(\"http://evil\",\"click\")") == "'=HYPERLINK(\"http://evil\",\"click\")"
    assert _safe_cell("+1") == "'+1"
    assert _safe_cell("-1") == "'-1"
    assert _safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert _safe_cell("plain") == "plain"
    assert _safe_cell(42) == 42


# --- #24: streaming update strips NUL and bounds size -------------------------


def test_update_last_message_strips_nul_and_truncates():
    from app.models.chat import ChatMessage, ChatSession
    from app.models.user import User
    from app.services import user_chat_storage_service as ucs

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                u = User(username="n", email="n@t", hashed_password="x", auth_provider="local", is_active=True)
                db.add(u)
                await db.flush()
                s = ChatSession(id="s1", user_id=u.id, title="t")
                db.add(s)
                await db.flush()
                db.add(ChatMessage(id="m1", session_id="s1", role="assistant", content="", sequence=1))
                await db.commit()
                huge = "a" * (ucs._MAX_MESSAGE_BYTES + 100)
                await ucs.update_last_session_message(db, u.id, "s1", "he\x00llo" + huge)
                row = await db.get(ChatMessage, "m1")
                assert "\x00" not in row.content
                assert row.content.startswith("hello")
                assert len(row.content.encode("utf-8")) <= ucs._MAX_MESSAGE_BYTES
        finally:
            await engine.dispose()

    asyncio.run(run())


# --- B-27/B-28: STT suffix whitelist and WAV header sanity --------------------


def test_transcription_suffix_whitelist_and_wav_sanity():
    import struct

    from app.services import transcription_service as ts

    assert ts._suffix_for_file("voice.php", "audio/webm") == ".webm"
    assert ts._suffix_for_file("x.exe", "audio/wav") == ".wav"
    assert ts._suffix_for_file("note.mp3", "") == ".mp3"

    def wav(rate, channels, bits, data_len):
        fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits)
        body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", data_len) + b"\0" * data_len
        return b"RIFF" + struct.pack("<I", len(body)) + body

    assert abs(ts.wav_duration_seconds(wav(16000, 1, 16, 32000)) - 1.0) < 1e-6
    # 1 Hz mono 8-bit would turn 3 KB into "hours": refused.
    assert ts.wav_duration_seconds(wav(1, 1, 8, 3000)) is None
    assert ts.wav_duration_seconds(wav(16000, 1, 12, 32000)) is None


# --- B-15: LDAP prune refuses empty / mass-removal answers --------------------


def test_ldap_prune_refuses_empty_directory_and_mass_removal(monkeypatch):
    from app.models.user import User
    from app.services import ldap_sync

    async def run(users_data, expect_reason):
        factory, engine = await _factory()
        try:
            async with factory() as db:
                for i in range(4):
                    db.add(User(username=f"ldap{i}", email=f"l{i}@t", auth_provider="ldap", external_id=f"ext{i}", is_active=True))
                await db.commit()
                with (
                    patch.object(ldap_sync, "fetch_ldap_users", return_value=users_data),
                    patch.object(ldap_sync, "fetch_ldap_groups", return_value=[]),
                    patch.object(ldap_sync, "get_settings", lambda: SimpleNamespace(ldap_link_local_password_accounts=False, ldap_prune_max_ratio=0.5)),
                ):
                    result = await ldap_sync.sync_ldap_directory(
                        db,
                        {"enabled": True, "server": "ldaps://dc.example.com", "base_dn": "DC=example,DC=com", "sync_ous_prune": True},
                    )
                assert result["prune_skipped"] is True
                assert expect_reason in str(result["prune_reason"])
                assert result["users_pruned"] == 0
        finally:
            await engine.dispose()

    asyncio.run(run([], "empty_directory"))
    one = [{"username": "ldap0", "external_id": "ext0", "email": "l0@t", "display_name": "L0", "dn": "cn=l0"}]
    asyncio.run(run(one, "ratio_"))


# --- #14: report schedules are validated --------------------------------------


def test_report_schedule_validation():
    from app.api import reports

    good = reports.ScheduleIn(report_type=reports.REPORT_CATALOG[0]["id"], cron_expression="0 9 * * 1", recipients="a@b.co, c@d.io")
    clean = reports._validate_schedule(good)
    assert clean["recipients"] == "a@b.co,c@d.io"
    for bad in (
        dict(report_type="nope", cron_expression="0 9 * * 1", recipients="a@b.co"),
        dict(report_type=good.report_type, cron_expression="every monday", recipients="a@b.co"),
        dict(report_type=good.report_type, cron_expression="0 9 * * 1", recipients="not-an-email"),
        dict(report_type=good.report_type, cron_expression="0 9 * * 1", recipients="a@b.co", format="exe"),
        dict(report_type=good.report_type, cron_expression="0 9 * * 1", recipients="a@b.co", parameters_json="[1]"),
    ):
        with pytest.raises(HTTPException) as exc:
            reports._validate_schedule(reports.ScheduleIn(**bad))
        assert exc.value.status_code == 400


# --- B-26: chat_session_id ownership -----------------------------------------


def test_chat_session_must_belong_to_caller_or_writable_project():
    from app.models.chat import ChatSession
    from app.models.user import User
    from app.services.chat_session_access import resolve_owned_chat_session

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                me = User(username="me", email="me@t", hashed_password="x", auth_provider="local", is_active=True)
                other = User(username="ot", email="ot@t", hashed_password="x", auth_provider="local", is_active=True)
                db.add_all([me, other])
                await db.flush()
                db.add(ChatSession(id="mine", user_id=me.id, title="t"))
                db.add(ChatSession(id="theirs", user_id=other.id, title="t"))
                await db.commit()
                assert (await resolve_owned_chat_session(db, user=me, chat_session_id="mine")).id == "mine"
                assert await resolve_owned_chat_session(db, user=me, chat_session_id=None) is None
                # Unknown ids are the client's private / not-yet-synced sessions:
                # opaque, allowed (a 404 here broke attachments in Private Mode).
                assert await resolve_owned_chat_session(db, user=me, chat_session_id="not-synced-yet") is None
                with pytest.raises(HTTPException) as exc:
                    await resolve_owned_chat_session(db, user=me, chat_session_id="theirs")
                assert exc.value.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())


# --- B-30: connection base_url passes the SSRF guard --------------------------


def test_connection_base_url_rejects_internal_targets(monkeypatch):
    from app.api import admin

    monkeypatch.setattr("app.services.ssrf_guard.get_settings", lambda: SimpleNamespace(allow_ssrf_private_ranges=False))
    for bad in ("http://169.254.169.254/latest", "http://127.0.0.1:6333", "http://10.1.2.3/v1", "ftp://x.test"):
        with pytest.raises(HTTPException) as exc:
            admin._validated_connection_base_url(bad)
        assert exc.value.status_code == 400
    with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
        assert admin._validated_connection_base_url(" https://api.provider.test/v1 ") == "https://api.provider.test/v1"
    assert admin._validated_connection_base_url("") is None


# --- production guard: ALLOW_INSECURE_SAML -------------------------------------


def test_allow_insecure_saml_is_a_production_insecurity():
    from app.main import _collect_production_insecurities

    base = dict(
        environment="production", secret_key="s" * 40, admin_password="p" * 20, service_admin_password="q" * 20,
        gateway_master_key="g" * 40, code_sandbox_broker_url="http://sandbox-broker:8081",
        code_sandbox_broker_token="t" * 40, redis_url="redis://:pw@redis:6379/0", redis_password="pw",
        data_encryption_key="d" * 40, openapi_admin_only=True,
        database_url="postgresql+asyncpg://alpha_router:StrongPw123456@pgbouncer:6432/alpha_router",
    )
    assert "ALLOW_INSECURE_SAML" not in _collect_production_insecurities(**base)
    assert "ALLOW_INSECURE_SAML" in _collect_production_insecurities(**base, allow_insecure_saml=True)


# --- B-20: system default gate matches the transcription gate -------------------


def test_system_default_requires_connection_with_api_key():
    from app.models.connection import Connection
    from app.models.model_catalog import AIModel
    from app.services import system_default_models as sdm

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                no_key = Connection(name="nokey", provider_type="openai", api_key_encrypted="", is_active=True)
                db.add(no_key)
                await db.flush()
                orphan = AIModel(external_id="m1", provider_type="openai", is_enabled=True, access_type="public")
                keyless = AIModel(connection_id=no_key.id, external_id="m2", provider_type="openai", is_enabled=True, access_type="public")
                db.add_all([orphan, keyless])
                await db.commit()
                entry = SimpleNamespace(supports=lambda m: True, requirement="x")
                for model, msg in ((orphan, "no connection"), (keyless, "no API key")):
                    with pytest.raises(sdm.SystemDefaultModelError, match=msg):
                        await sdm._assert_usable(db, entry, model)
        finally:
            await engine.dispose()

    asyncio.run(run())
