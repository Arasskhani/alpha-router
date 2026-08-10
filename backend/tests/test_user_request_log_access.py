"""Ownership checks for user-scoped request-log detail helpers."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.logs import _cost_details_payload, _owned_request_log
from app.database import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.logging import RequestLog
from app.models.user import User
from app.services.user_chat_storage_service import attach_request_log_id_to_chat_message


async def _run() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        owner = User(
            username="owner",
            email="owner@example.com",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        other = User(
            username="other",
            email="other@example.com",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add_all([owner, other])
        await db.flush()

        own_log = RequestLog(
            user_id=owner.id,
            username=owner.username,
            model_id="test/model",
            prompt_tokens=1,
            completion_tokens=2,
            cached_tokens=0,
            total_cost_usd=0.01,
            response_time_ms=12.0,
            prompt_language="en",
            source="alpha_router_chat",
            success=True,
        )
        foreign_log = RequestLog(
            user_id=other.id,
            username=other.username,
            model_id="test/model",
            prompt_tokens=3,
            completion_tokens=4,
            cached_tokens=0,
            total_cost_usd=0.02,
            response_time_ms=20.0,
            prompt_language="en",
            source="alpha_router_chat",
            success=True,
        )
        db.add_all([own_log, foreign_log])
        await db.flush()

        session = ChatSession(
            id="sess-1",
            user_id=owner.id,
            title="Chat",
            model_id="test/model",
        )
        db.add(session)
        await db.flush()
        msg = ChatMessage(
            id="msg-1",
            session_id=session.id,
            user_id=owner.id,
            role="assistant",
            content="hello",
            sequence=1,
            client_message_id="client-asst-1",
            meta={},
        )
        db.add(msg)
        await db.commit()

        loaded = await _owned_request_log(db, owner, own_log.id)
        assert loaded.id == own_log.id

        with pytest.raises(HTTPException) as denied:
            await _owned_request_log(db, owner, foreign_log.id)
        assert denied.value.status_code == 404

        details = await _cost_details_payload(db, own_log)
        assert details["legacy"] is True
        assert details["total_cost_usd"] == pytest.approx(0.01)

        attached = await attach_request_log_id_to_chat_message(
            db,
            owner.id,
            session.id,
            own_log.id,
            client_message_id="client-asst-1",
        )
        assert attached is True
        await db.refresh(msg)
        assert msg.meta.get("requestLogId") == own_log.id

    await engine.dispose()


def test_owned_request_log_and_message_link():
    asyncio.run(_run())
