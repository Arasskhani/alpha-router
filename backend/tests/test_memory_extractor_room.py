"""The extractor has room to answer, and an answer cut off is not a failure.

The extraction call allowed 600 tokens, fixed. A model that thinks before it
answers spent them thinking, the JSON never came, and the part failed for good
as "not JSON" (after a second paid call that ran out the same way). Now the
length is a setting (2,000 by default); a model that reasons is asked to
reason little; an answer cut off keeps the operations it finished; one cut
off before its first is asked again of half the part.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession, UserMemory, UserMemoryJob
from app.models.system import SystemSetting
from app.services.memory_extraction_service import (
    MAX_WINDOW_CHARS,
    REPAIR_NUDGE,
    ExtractionParseError,
    handle_memory_extraction,
    reasoning_hint,
    salvage_operations,
)
from app.services.memory_settings_service import parse_memory_settings

GOOD = json.dumps({"operations": [{"op": "add", "content": "User lives in Tehran", "category": "identity"}]})
CUT = '{"operations":[{"op":"add","content":"User lives in Tehran","category":"identity"},{"op":"add","content":"Use'


class _Choice:
    def __init__(self, content: str, finish_reason: str) -> None:
        self.message = type("M", (), {"content": content})()
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.choices = [_Choice(content, finish_reason)]
        self.usage = type("U", (), {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940})()


def _catalog_model(external_id: str, provider_type: str):
    return type(
        "CatalogModel",
        (),
        {"external_id": external_id, "provider_type": provider_type, "connection_id": None, "pricing_raw": None},
    )()


@pytest.fixture
async def job(db_session: AsyncSession, user) -> UserMemoryJob:
    session = ChatSession(id=str(uuid.uuid4()), user_id=user.id, title="Chat", model_id="m", private_mode=False)
    db_session.add(session)
    db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
    await db_session.flush()
    now = dt.datetime.utcnow()
    for sequence, (role, content) in enumerate([("user", "I live in Tehran."), ("assistant", "Noted.")], start=1):
        db_session.add(
            ChatMessage(id=str(uuid.uuid4()), session_id=session.id, role=role, content=content, sequence=sequence)
        )
    row = UserMemoryJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        session_id=session.id,
        status="running",
        watermark_sequence=2,
        extracted_sequence=0,
        run_after=now,
        attempt_count=1,
        max_attempts=5,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.fixture
def provider(monkeypatch, session_factory):
    """litellm and the model catalog stood in for; each call's arguments kept."""
    state: dict = {"model": _catalog_model("gpt-4o-mini", "openai"), "replies": [], "calls": []}

    async def _resolve(_db, _ref):
        return state["model"], "sk-test", None, state["model"].provider_type

    async def _acompletion(**kwargs):
        state["calls"].append(kwargs)
        reply = state["replies"].pop(0) if state["replies"] else (GOOD, "stop")
        return _Response(*reply)

    monkeypatch.setattr("app.services.model_resolution_service.resolve_model_and_key", _resolve)
    monkeypatch.setattr("litellm.acompletion", _acompletion)
    monkeypatch.setattr("app.services.usage_logging_service.AsyncSessionLocal", session_factory)
    return state


async def _memories(db: AsyncSession, user_id: int) -> list[str]:
    return [r.content for r in (await db.execute(select(UserMemory).where(UserMemory.user_id == user_id))).scalars()]


class TestTheAllowance:
    async def test_is_two_thousand_tokens_unless_the_administrator_says_otherwise(self, db_session, job, provider):
        await handle_memory_extraction(db_session, job)
        await db_session.commit()
        assert provider["calls"][0]["max_tokens"] == 2000

        db_session.add(SystemSetting(key="memory_extract_max_tokens", value="4096"))
        job.watermark_sequence = 4
        for sequence in (3, 4):
            db_session.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    session_id=job.session_id,
                    role="user" if sequence == 3 else "assistant",
                    content="I work as a nurse." if sequence == 3 else "Noted.",
                    sequence=sequence,
                )
            )
        await db_session.commit()
        await handle_memory_extraction(db_session, job)
        assert provider["calls"][1]["max_tokens"] == 4096

    def test_is_kept_within_bounds(self):
        assert parse_memory_settings({})["extract_max_tokens"] == 2000
        assert parse_memory_settings({"memory_extract_max_tokens": "10"})["extract_max_tokens"] == 256
        assert parse_memory_settings({"memory_extract_max_tokens": "99999"})["extract_max_tokens"] == 16_000


class TestAModelThatThinks:
    async def test_is_asked_to_think_little(self, db_session, job, provider):
        provider["model"] = _catalog_model("o3-mini", "openai")
        await handle_memory_extraction(db_session, job)
        call = provider["calls"][0]
        assert call["reasoning_effort"] == "low"
        # What such a model refuses (temperature 0) is dropped, not a failed call.
        assert call["drop_params"] is True

    async def test_any_other_model_is_sent_what_it_was(self, db_session, job, provider):
        await handle_memory_extraction(db_session, job)
        assert "reasoning_effort" not in provider["calls"][0]
        assert "drop_params" not in provider["calls"][0]

    def test_anthropic_models_are_not_asked_to_think(self):
        assert reasoning_hint("claude-sonnet-4-20250514", "anthropic") == {}
        assert reasoning_hint("some-local-model", None) == {}


class TestAnAnswerCutOff:
    def test_keeps_the_operations_it_finished(self):
        assert salvage_operations(CUT) == {
            "operations": [{"op": "add", "content": "User lives in Tehran", "category": "identity"}]
        }
        assert salvage_operations('{"operations":[{"op":"ad') is None
        assert salvage_operations("I think the user") is None

    async def test_writes_what_it_finished_without_a_second_call(self, db_session, user, job, provider):
        provider["replies"].append((CUT, "length"))
        await handle_memory_extraction(db_session, job)
        await db_session.commit()
        assert await _memories(db_session, user.id) == ["User lives in Tehran"]
        assert len(provider["calls"]) == 1
        assert job.extracted_sequence == 2

    async def test_before_its_first_operation_reads_the_part_again_in_less(self, db_session, user, job, provider):
        for sequence in range(3, 31):
            db_session.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    session_id=job.session_id,
                    role="user" if sequence % 2 else "assistant",
                    content=f"turn {sequence} " + "w" * 1_500,
                    sequence=sequence,
                )
            )
        job.watermark_sequence = 30
        await db_session.commit()
        provider["replies"].append(("", "length"))

        await handle_memory_extraction(db_session, job)
        await db_session.commit()

        first, second = provider["calls"][0], provider["calls"][1]
        first_text, second_text = first["messages"][1]["content"], second["messages"][1]["content"]
        assert "[user #1] I live in Tehran." in first_text and "[user #1] I live in Tehran." in second_text
        assert len(second_text) < len(first_text) and len(second_text) <= MAX_WINDOW_CHARS // 2 + 2_000
        # No "not JSON" nudge for an answer that simply ran out.
        assert all(REPAIR_NUDGE not in str(call["messages"]) for call in provider["calls"])
        assert job.extracted_sequence == 30
        assert "User lives in Tehran" in await _memories(db_session, user.id)

    async def test_that_cannot_be_made_smaller_is_a_failure_the_administrator_sees(self, db_session, job, provider):
        provider["replies"].extend([("", "length")] * 10)
        with pytest.raises(ExtractionParseError, match="Admin -> Memory"):
            await handle_memory_extraction(db_session, job)
        # The part is too small to be read in less, so it was asked once.
        assert len(provider["calls"]) == 1
        await db_session.rollback()
        await db_session.refresh(job)
        assert job.extracted_sequence == 0
