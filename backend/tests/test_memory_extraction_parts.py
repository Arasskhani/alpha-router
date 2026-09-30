"""A long stretch of chat is mined in parts, from its start.

The extraction window used to keep the newest 24,000 characters of a job's
stretch and drop the rest, while the job still marked the whole stretch as
mined. A chat with long answers lost its first turns for good: the facts the
person gave at the start were never learned. Now the stretch is read oldest
first, one part per extraction call, and the job's watermark moves only over
what a call has read.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession, UserMemory, UserMemoryJob
from app.models.project import (
    PROJECT_ROLE_PRIMARY_OWNER,
    Project,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryJob,
)
from app.models.system import SystemSetting
from app.services.memory_extraction_service import (
    CONTEXT_CHARS,
    MAX_PARTS_PER_RUN,
    MAX_WINDOW_CHARS,
    ExtractionBilling,
    fit_extraction_window,
    handle_memory_extraction,
)
from app.services.project_memory_extraction_service import handle_project_memory_extraction
from app.services.user_chat_storage_service import save_user_prefs

FIRST = "My workout plan: squats on Monday, running on Wednesday."
NEW_TURN = re.compile(r"^\[(?:user|assistant|member[^#\]]*) #(\d+)\]", re.MULTILINE)


@dataclass
class _Turn:
    sequence: int
    text: str


class TestFitting:
    def test_the_oldest_new_turns_come_first_and_the_part_stops_before_the_first_that_does_not_fit(self):
        turns = [_Turn(s, "x" * 5_000) for s in range(1, 11)]
        kept, covered = fit_extraction_window(turns, start=1, covered_to=10)
        assert [t.sequence for t in kept] == [1, 2, 3, 4]
        assert covered == 4

    def test_the_first_new_turn_is_read_however_long(self):
        kept, covered = fit_extraction_window([_Turn(7, "x" * (MAX_WINDOW_CHARS + 1))], start=7, covered_to=9)
        assert [t.sequence for t in kept] == [7]
        # Rows the model does not read (8, 9: skipped) are covered with it.
        assert covered == 9

    def test_context_is_the_newest_earlier_turns_within_its_share(self):
        turns = [_Turn(s, "c" * 2_500) for s in range(1, 5)] + [_Turn(5, "new")]
        kept, covered = fit_extraction_window(turns, start=5, covered_to=5)
        assert [t.sequence for t in kept] == [3, 4, 5]
        assert sum(len(t.text) for t in kept if t.sequence < 5) <= CONTEXT_CHARS
        assert covered == 5


@pytest.fixture
async def chat(db_session: AsyncSession, user) -> ChatSession:
    session = ChatSession(id=str(uuid.uuid4()), user_id=user.id, title="Coach", model_id="m", private_mode=False)
    db_session.add(session)
    db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
    await db_session.commit()
    return session


async def _messages(db: AsyncSession, session: ChatSession, count: int, *, reply_chars: int = 3_000) -> None:
    """``count`` messages: short questions, each answered at length."""
    for sequence in range(1, count + 1):
        user_turn = sequence % 2 == 1
        if sequence == 1:
            content = FIRST
        elif user_turn:
            content = f"Question {sequence}: what about day {sequence}?"
        else:
            content = f"Answer {sequence}. " + "r" * reply_chars
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=session.user_id,
                role="user" if user_turn else "assistant",
                content=content,
                sequence=sequence,
            )
        )
    await db.commit()


def _job(model, *, owner: dict, session_id: str, watermark: int, extracted: int = 0):
    now = dt.datetime.utcnow()
    return model(
        id=str(uuid.uuid4()),
        **owner,
        session_id=session_id,
        status="running",
        watermark_sequence=watermark,
        extracted_sequence=extracted,
        run_after=now,
        attempt_count=1,
        max_attempts=5,
        created_at=now,
        updated_at=now,
    )


class _Model:
    """Stands in for the extraction model: notes each prompt's new turns and adds one memory per part."""

    def __init__(self, *, fail_on: int | None = None, on_call=None, category: str = "other") -> None:
        self.parts: list[list[int]] = []
        self.category = category
        self.fail_on = fail_on
        self.on_call = on_call

    async def __call__(self, payload: dict) -> str:
        prompt = payload["messages"][0]["content"]
        seen = [int(n) for n in NEW_TURN.findall(prompt.split("BEGIN_UNTRUSTED_CONVERSATION", 1)[1])]
        if self.fail_on is not None and len(self.parts) + 1 == self.fail_on:
            raise RuntimeError("provider timed out")
        self.parts.append(seen)
        if self.on_call is not None:
            await self.on_call(len(self.parts))
        fact = f"Fact learned in part {len(self.parts)}"
        return json.dumps({"operations": [{"op": "add", "content": fact, "category": self.category}]})


class TestPersonal:
    async def test_the_first_part_starts_at_the_chat_s_first_message(self, db_session, user, chat):
        await _messages(db_session, chat, 80)
        job = _job(UserMemoryJob, owner={"user_id": user.id}, session_id=chat.id, watermark=80)
        db_session.add(job)
        await db_session.commit()
        model = _Model()

        await handle_memory_extraction(db_session, job, completer=model)
        await db_session.commit()

        assert model.parts[0][0] == 1
        prompt_first = model.parts[0]
        assert prompt_first == sorted(prompt_first)
        assert len(model.parts) == MAX_PARTS_PER_RUN
        # The watermark moved over what was read, and only that.
        assert 1 < job.extracted_sequence < 80
        assert max(model.parts[-1]) == job.extracted_sequence

    async def test_the_rest_goes_on_in_a_follow_up_job_until_every_turn_is_read(self, db_session, user, chat):
        await _messages(db_session, chat, 80)
        job = _job(UserMemoryJob, owner={"user_id": user.id}, session_id=chat.id, watermark=80)
        db_session.add(job)
        await db_session.commit()
        model = _Model()

        current = job
        for _run in range(10):
            before = len(model.parts)
            await handle_memory_extraction(db_session, current, completer=model)
            await db_session.commit()
            follow = (
                (
                    await db_session.execute(
                        select(UserMemoryJob).where(
                            UserMemoryJob.session_id == chat.id, UserMemoryJob.status == "pending"
                        )
                    )
                )
                .scalars()
                .first()
            )
            current.status = "succeeded"
            assert len(model.parts) > before
            if follow is None:
                break
            assert follow.extracted_sequence == current.extracted_sequence
            assert follow.watermark_sequence == 80
            follow.status = "running"
            await db_session.commit()
            current = follow
        assert current.extracted_sequence == 80

        read_as_new: list[int] = []
        start = 1
        for seen in model.parts:
            new = [s for s in seen if s >= start]
            assert new and new[0] == start, "a part started somewhere other than where the last one stopped"
            read_as_new.extend(new)
            start = new[-1] + 1
        assert read_as_new == list(range(1, 81))
        memories = (await db_session.execute(select(UserMemory).where(UserMemory.user_id == user.id))).scalars().all()
        assert len(memories) == len(model.parts)

    async def test_a_part_that_fails_leaves_the_parts_before_it_done(self, db_session, session_factory, user, chat):
        user_id = user.id
        await _messages(db_session, chat, 40)
        job = _job(UserMemoryJob, owner={"user_id": user_id}, session_id=chat.id, watermark=40)
        db_session.add(job)
        await db_session.commit()
        failing = _Model(fail_on=2)

        with pytest.raises(RuntimeError):
            await handle_memory_extraction(db_session, job, completer=failing)
        await db_session.rollback()
        await db_session.refresh(job)

        first_end = max(failing.parts[0])
        async with session_factory() as other:
            live = await other.get(UserMemoryJob, job.id)
            assert live.extracted_sequence == first_end
            kept = (await other.execute(select(UserMemory.content).where(UserMemory.user_id == user_id))).all()
            assert [row.content for row in kept] == ["Fact learned in part 1"]

        # The retry starts where the part before it stopped, not at the start again.
        retry = _Model()
        await handle_memory_extraction(db_session, job, completer=retry)
        await db_session.commit()
        assert min(s for s in retry.parts[0] if s > first_end) == first_end + 1
        assert all(s > first_end - 4 for s in retry.parts[0])
        assert job.extracted_sequence == 40

    async def test_the_person_s_switch_is_read_before_every_part(self, db_session, session_factory, user, chat):
        # The person's settings row exists, as it does for everyone once the app has started.
        await save_user_prefs(db_session, user.id, {"memory_auto_capture": True})
        await _messages(db_session, chat, 80)
        job = _job(UserMemoryJob, owner={"user_id": user.id}, session_id=chat.id, watermark=80)
        db_session.add(job)
        await db_session.commit()

        async def opt_out(part: int) -> None:
            if part == 1:
                async with session_factory() as other:
                    await save_user_prefs(other, user.id, {"memory_auto_capture": False})
                    await other.commit()

        model = _Model(on_call=opt_out)
        await handle_memory_extraction(db_session, job, completer=model)
        await db_session.commit()

        assert len(model.parts) == 1
        # The rest is claimed, not left to be mined once the switch is back on.
        assert job.extracted_sequence == 80

    async def test_a_delete_all_while_a_part_is_written_stops_the_job_there(
        self, db_session, session_factory, user, chat, monkeypatch
    ):
        from app.services import memory_extraction_service as extraction
        from app.services.user_memory_service import delete_all_memories

        user_id = user.id
        await _messages(db_session, chat, 80)
        job = _job(UserMemoryJob, owner={"user_id": user_id}, session_id=chat.id, watermark=80)
        db_session.add(job)
        await db_session.commit()
        job_id = job.id
        real_apply = extraction.apply_memory_operations
        pressed: list[int] = []

        async def _apply_then_delete_all(db, **kwargs):
            result = await real_apply(db, **kwargs)
            if not pressed:
                # "Delete all my memories", while the first part's memories are being written.
                pressed.append(1)
                async with session_factory() as other:
                    await delete_all_memories(other, user_id)
                    await other.commit()
            return result

        monkeypatch.setattr(extraction, "apply_memory_operations", _apply_then_delete_all)
        model = _Model()
        await handle_memory_extraction(db_session, job, completer=model)
        await db_session.commit()

        assert len(model.parts) == 1
        async with session_factory() as check:
            live = await check.get(UserMemoryJob, job_id)
            assert live.extracted_sequence == 80  # where the delete-all put it, not back where the part ended
            kept = (
                await check.execute(
                    select(UserMemory.content).where(UserMemory.user_id == user_id, UserMemory.deleted_at.is_(None))
                )
            ).all()
            assert kept == []

    async def test_a_job_waits_for_another_job_of_its_chat_that_is_mining_it(self, db_session, user, chat):
        await _messages(db_session, chat, 40)
        mining = _job(UserMemoryJob, owner={"user_id": user.id}, session_id=chat.id, watermark=20)
        mining.lease_expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=5)
        job = _job(UserMemoryJob, owner={"user_id": user.id}, session_id=chat.id, watermark=40)
        db_session.add_all([mining, job])
        await db_session.commit()
        model = _Model()

        await handle_memory_extraction(db_session, job, completer=model)
        await db_session.commit()

        assert model.parts == []  # nothing read twice, nothing billed twice
        follow = (
            (
                await db_session.execute(
                    select(UserMemoryJob).where(UserMemoryJob.session_id == chat.id, UserMemoryJob.status == "pending")
                )
            )
            .scalars()
            .all()
        )
        assert [(row.extracted_sequence, row.watermark_sequence) for row in follow] == [(0, 40)]

    async def test_a_job_made_while_another_is_mining_starts_where_that_one_will_stop(self, db_session, user, chat):
        from app.services.memory_job_service import schedule_extraction

        await _messages(db_session, chat, 40)
        mining = _job(UserMemoryJob, owner={"user_id": user.id}, session_id=chat.id, watermark=20, extracted=6)
        mining.lease_expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=5)
        db_session.add(mining)
        await db_session.commit()

        made = await schedule_extraction(db_session, user_id=user.id, session_id=chat.id, watermark_sequence=40)
        assert made is not None and made.extracted_sequence == 20  # not 6: that job reads 7-20
        # A running job's own follow-up starts where it stopped.
        made.status = "succeeded"
        await db_session.commit()
        own = await schedule_extraction(
            db_session, user_id=user.id, session_id=chat.id, watermark_sequence=40, exclude_job_id=mining.id
        )
        assert own is not None and own.extracted_sequence <= 20

    async def test_relearning_reads_a_chat_mined_before_again(self, db_session, user, chat):
        from app.models.chat import UserChatPrefs
        from app.services.memory_relearn_service import start_relearn

        now = dt.datetime.utcnow()
        db_session.add(
            UserChatPrefs(user_id=user.id, prefs={"memory_auto_capture": True}, updated_at=now - dt.timedelta(days=60))
        )
        db_session.add(SystemSetting(key="memory_relearn_enabled", value="true"))
        await _messages(db_session, chat, 10)
        for message in (
            await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == chat.id))
        ).scalars():
            message.created_at = now - dt.timedelta(days=2)
        mined = _job(UserMemoryJob, owner={"user_id": user.id}, session_id=chat.id, watermark=10, extracted=10)
        mined.status = "succeeded"
        db_session.add(mined)
        await db_session.commit()
        assert (await start_relearn(db_session, days=30))["queued"] == 1
        await db_session.commit()
        job = (await db_session.execute(select(UserMemoryJob).where(UserMemoryJob.status == "pending"))).scalars().one()
        job.status, job.lease_expires_at = "running", now + dt.timedelta(minutes=5)
        await db_session.commit()
        model = _Model()

        await handle_memory_extraction(db_session, job, completer=model)
        await db_session.commit()

        assert model.parts and min(model.parts[0]) == 1  # read again from the chat's first message
        assert job.extracted_sequence == 10

    def test_each_call_is_billed_under_its_own_key(self):
        job = UserMemoryJob(id="j1", user_id=7, attempt_count=1)
        first = ExtractionBilling.for_user(job, "u", part="1-23").key_prefix
        second = ExtractionBilling.for_user(job, "u", part="24-51").key_prefix
        assert first.startswith("memory-extract:j1:1:part-1-23:") and second.startswith(
            "memory-extract:j1:1:part-24-51:"
        )
        # The same job, attempt and range again - an administrator's retry, a part read again in less - is
        # another paid call: never taken for the first one.
        assert ExtractionBilling.for_user(job, "u", part="1-23").key_prefix != first
        assert ExtractionBilling.for_user(job, "u").key_prefix.startswith("memory-extract:j1:1:")


class TestProject:
    async def test_a_long_project_thread_is_mined_from_its_start(self, db_session, user):
        project_id = "proj-parts"
        db_session.add(
            Project(
                id=project_id,
                name="Billing",
                status="active",
                visibility="private",
                created_by_user_id=user.id,
                revision=1,
                acl_version=1,
            )
        )
        await db_session.flush()
        db_session.add(ProjectMember(project_id=project_id, user_id=user.id, role=PROJECT_ROLE_PRIMARY_OWNER))
        session = ChatSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            title="Standup",
            model_id="m",
            private_mode=False,
            project_id=project_id,
            channel_kind="ai",
        )
        db_session.add(session)
        db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        await db_session.commit()
        await _messages(db_session, session, 60)
        job = _job(ProjectMemoryJob, owner={"project_id": project_id}, session_id=session.id, watermark=60)
        db_session.add(job)
        await db_session.commit()
        model = _Model(category="decision")

        await handle_project_memory_extraction(db_session, job, completer=model)
        await db_session.commit()

        assert model.parts[0][0] == 1
        assert len(model.parts) == MAX_PARTS_PER_RUN
        assert max(model.parts[-1]) == job.extracted_sequence < 60
        follow = (
            (
                await db_session.execute(
                    select(ProjectMemoryJob).where(
                        ProjectMemoryJob.session_id == session.id, ProjectMemoryJob.status == "pending"
                    )
                )
            )
            .scalars()
            .one()
        )
        assert (follow.extracted_sequence, follow.watermark_sequence) == (job.extracted_sequence, 60)
        rows = (
            (await db_session.execute(select(ProjectMemory).where(ProjectMemory.project_id == project_id)))
            .scalars()
            .all()
        )
        assert len(rows) == MAX_PARTS_PER_RUN

    async def test_a_project_part_lands_only_where_its_watermark_still_is(
        self, db_session, session_factory, user, monkeypatch
    ):
        from app.services import project_memory_extraction_service as project_extraction

        project_id = "proj-cas"
        db_session.add(
            Project(
                id=project_id,
                name="Billing",
                status="active",
                visibility="private",
                created_by_user_id=user.id,
                revision=1,
                acl_version=1,
            )
        )
        await db_session.flush()
        db_session.add(ProjectMember(project_id=project_id, user_id=user.id, role=PROJECT_ROLE_PRIMARY_OWNER))
        session = ChatSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            title="Standup",
            model_id="m",
            private_mode=False,
            project_id=project_id,
            channel_kind="ai",
        )
        db_session.add(session)
        db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        await db_session.commit()
        await _messages(db_session, session, 60)
        job = _job(ProjectMemoryJob, owner={"project_id": project_id}, session_id=session.id, watermark=60)
        db_session.add(job)
        await db_session.commit()
        job_id = job.id

        real_apply = project_extraction.apply_project_memory_operations

        async def _apply_then_reset(db, **kwargs):
            result = await real_apply(db, **kwargs)
            # The project's memories are reset while the first part's are being written.
            async with session_factory() as other:
                live = await other.get(ProjectMemoryJob, job_id)
                live.extracted_sequence = 60
                await other.commit()
            return result

        monkeypatch.setattr(project_extraction, "apply_project_memory_operations", _apply_then_reset)
        model = _Model(category="decision")
        await handle_project_memory_extraction(db_session, job, completer=model)
        await db_session.commit()

        assert len(model.parts) == 1
        async with session_factory() as check:
            assert (await check.get(ProjectMemoryJob, job_id)).extracted_sequence == 60
            if check.bind.dialect.name == "postgresql":
                # (On the one shared SQLite connection the reset's commit takes the part's rows with it.)
                rows = (
                    (await check.execute(select(ProjectMemory).where(ProjectMemory.project_id == project_id)))
                    .scalars()
                    .all()
                )
                assert rows == []
