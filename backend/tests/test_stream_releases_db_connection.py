"""The request session must not hold a transaction while awaiting the provider.

Gateway / API-key / Private Mode turns never committed before acompletion(),
so the transaction opened by the session lookups pinned one pooled connection
(and one PgBouncer server slot) for the entire stream.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.services import proxy_service, turn_settlement


def _chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))], usage=None)


async def test_request_session_transaction_is_closed_before_provider_call():
    async def run() -> dict:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        observed: dict = {}
        created: list[AsyncSession] = []

        def tracking_factory(*args, **kwargs):
            # stream_chat opens its own session via AsyncSessionLocal(); record
            # every session so the provider hook can inspect the stream's one.
            session = factory(*args, **kwargs)
            created.append(session)
            return session

        async def fake_acompletion(**kwargs):
            del kwargs
            observed["sessions_seen"] = len(created)
            observed["in_transaction_at_provider_call"] = any(s.in_transaction() for s in created)

            async def _gen():
                yield _chunk("hello")
                yield _chunk(" world")

            return _gen()

        request = MagicMock()
        request.client = SimpleNamespace(host="127.0.0.1")
        request.is_disconnected = AsyncMock(return_value=False)
        resolved = SimpleNamespace(
            ai_model=SimpleNamespace(
                provider_type="openrouter",
                input_cost_per_1k=0.001,
                output_cost_per_1k=0.002,
                external_id="vendor/good",
                display_name="Good model",
                connection_id=7,
            ),
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider_type="openrouter",
            model_id="vendor/good",
            code_interpreter_capacity_permit=None,
        )
        try:
            if True:
                with (
                    patch.object(proxy_service, "AsyncSessionLocal", tracking_factory),
                    patch.object(turn_settlement, "AsyncSessionLocal", tracking_factory),
                    patch.object(
                        proxy_service, "parse_tools_config", return_value=SimpleNamespace(code_interpreter=False)
                    ),
                    patch.object(
                        proxy_service,
                        "augment_messages_with_tools",
                        AsyncMock(side_effect=lambda db, m, t, **_kwargs: m),
                    ),
                    patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
                    patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
                    patch.object(proxy_service, "persister_from_body", return_value=None),
                    patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(3, 2, 0)),
                    patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
                    patch.object(proxy_service, "log_usage", AsyncMock(return_value=1)),
                    patch.object(turn_settlement, "log_usage", AsyncMock(return_value=1)),
                    patch.object(proxy_service, "record_compatibility_result", AsyncMock()),
                    patch.object(proxy_service, "openrouter_auto_plugin", AsyncMock(return_value=None)),
                ):
                    chunks = [
                        c
                        async for c in proxy_service.stream_chat(
                            request,
                            {
                                "model": "vendor/good",
                                "messages": [{"role": "user", "content": "hi"}],
                                # Triggers the ChatSession lookup on the stream's
                                # session, which autobegins a transaction.
                                "chat_session_id": "no-such-session",
                            },
                            user_id=None,
                            username="gateway-key",
                            source="gateway",
                            skip_budget=True,
                            resolved=resolved,
                        )
                    ]
                observed["done"] = b"[DONE]" in b"".join(chunks)
        finally:
            await engine.dispose()
        return observed

    observed = await run()
    assert observed["sessions_seen"] >= 1, "stream_chat must have opened its session"
    assert observed["in_transaction_at_provider_call"] is False
    assert observed["done"] is True
