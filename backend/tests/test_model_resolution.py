"""Which catalog row a requested model id names: the one lookup chat turns and policy checks share."""

from __future__ import annotations

import pytest

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.model_resolution_service import resolve_model_and_key, resolve_model_row
from app.services.secret_crypto import encrypt_secret


async def _connection(db, name: str, *, active: bool = True, secret: str | None = None) -> Connection:
    row = Connection(
        name=name,
        provider_type="openai",
        api_key_encrypted=secret if secret is not None else encrypt_secret(f"sk-{name}"),
        is_active=active,
    )
    db.add(row)
    await db.flush()
    return row


async def _model(db, connection: Connection, external_id: str, *, enabled: bool = True) -> AIModel:
    row = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=external_id,
        provider_type="openai",
        is_enabled=enabled,
    )
    db.add(row)
    await db.flush()
    return row


class TestResolveModelRow:
    async def test_by_catalog_id(self, db_session):
        conn = await _connection(db_session, "a")
        model = await _model(db_session, conn, "gpt-test")
        found = await resolve_model_row(db_session, f"model::{model.id}")
        assert found is not None
        assert found[0].id == model.id
        assert found[1].id == conn.id

    async def test_an_external_id_picks_the_lowest_usable_twin(self, db_session):
        off = await _connection(db_session, "off", active=False)
        on = await _connection(db_session, "on")
        await _model(db_session, off, "gpt-twin")
        await _model(db_session, on, "gpt-twin", enabled=False)
        usable = await _model(db_session, on, "gpt-twin")
        found = await resolve_model_row(db_session, "gpt-twin")
        assert found is not None
        assert found[0].id == usable.id

    @pytest.mark.parametrize("state", ["disabled", "inactive connection", "unknown"])
    async def test_nothing_unusable(self, db_session, state):
        conn = await _connection(db_session, "c", active=state != "inactive connection")
        model = await _model(db_session, conn, "gpt-test", enabled=state != "disabled")
        ref = "model::999999" if state == "unknown" else f"model::{model.id}"
        assert await resolve_model_row(db_session, ref) is None
        assert await resolve_model_and_key(db_session, ref) == (None, None, None, None)

    async def test_an_allow_list_narrows_it(self, db_session):
        conn = await _connection(db_session, "c")
        first = await _model(db_session, conn, "gpt-twin")
        second = await _model(db_session, conn, "gpt-twin")
        found = await resolve_model_row(db_session, "gpt-twin", allowed_model_ids={second.id})
        assert found is not None
        assert found[0].id == second.id
        assert await resolve_model_row(db_session, f"model::{first.id}", allowed_model_ids={second.id}) is None
        assert await resolve_model_row(db_session, "gpt-twin", allowed_connection_ids=set()) is None

    async def test_the_key_lookup_agrees_and_adds_the_secret(self, db_session):
        conn = await _connection(db_session, "c")
        model = await _model(db_session, conn, "gpt-test")
        row, key, _base_url, provider = await resolve_model_and_key(db_session, "gpt-test")
        assert row is not None
        assert row.id == model.id
        assert key == "sk-c"
        assert provider == "openai"

    async def test_the_row_is_found_without_reading_the_key(self, db_session):
        # A key that cannot be decrypted still names its model: only the
        # lookup that hands the key to a provider needs to read it.
        conn = await _connection(db_session, "c", secret="stored-in-plain-text")
        model = await _model(db_session, conn, "gpt-test")
        found = await resolve_model_row(db_session, f"model::{model.id}")
        assert found is not None
        assert found[0].id == model.id
        with pytest.raises(ValueError, match="not encrypted"):
            await resolve_model_and_key(db_session, f"model::{model.id}")
