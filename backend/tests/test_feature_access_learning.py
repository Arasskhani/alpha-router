"""With Chat closed, nothing more is learned from the person's personal chats.

Memory extraction, the chat summary and the recall index each ask whether
the owner allows them; a Chat that Feature Access closed answers no for a
personal chat, and leaves project chats - which belong to the project - as
they were. Nothing already learned is deleted.
"""

from __future__ import annotations

import uuid

from app.models.chat import ChatSession, UserMemoryJob
from app.models.feature_access import FeatureAccessRule
from app.models.project import PROJECT_ROLE_PRIMARY_OWNER, Project, ProjectMember
from app.models.system import SystemSetting
from app.services import chat_recall_service
from app.services.chat_summary_service import owner_allows_summaries
from app.services.memory_job_service import schedule_extraction


async def _chat(db, user, project_id: str | None = None) -> ChatSession:
    chat = ChatSession(id=str(uuid.uuid4()), user_id=user.id, title="t", project_id=project_id)
    db.add(chat)
    await db.commit()
    return chat


async def _close_chat(db, user) -> None:
    db.add(FeatureAccessRule(feature="chat", effect="deny", user_id=user.id))
    await db.commit()


async def _project(db, user) -> str:
    project = Project(
        id=str(uuid.uuid4()),
        name="Team",
        status="active",
        visibility="private",
        created_by_user_id=user.id,
        revision=1,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    await db.commit()
    return str(project.id)


class TestMemory:
    async def test_no_extraction_is_queued_for_a_personal_chat(self, db_session, user):
        db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        await db_session.commit()
        chat = await _chat(db_session, user)
        assert await schedule_extraction(db_session, user_id=user.id, session_id=chat.id, watermark_sequence=2)
        await db_session.commit()

        later = await _chat(db_session, user)
        await _close_chat(db_session, user)
        assert await schedule_extraction(db_session, user_id=user.id, session_id=later.id, watermark_sequence=2) is None

    async def test_a_job_queued_before_the_section_closed_learns_nothing_now(self, db_session, user, monkeypatch):
        """The run re-reads it, and leaves the window for when Chat is open again: nothing is claimed."""
        from app.services import memory_extraction_service as extraction

        db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        await db_session.commit()
        chat = await _chat(db_session, user)
        job = await schedule_extraction(db_session, user_id=user.id, session_id=chat.id, watermark_sequence=4)
        assert isinstance(job, UserMemoryJob)
        await db_session.commit()
        await _close_chat(db_session, user)

        async def never(*_a, **_k):
            raise AssertionError("the model was asked to learn from a closed Chat")

        monkeypatch.setattr(extraction, "_mine_window", never, raising=False)
        assert await extraction._mine_next_part(db_session, job, completer=None, first=True) is False
        await db_session.refresh(job)
        assert int(job.extracted_sequence or 0) == 0


class TestSummaryAndRecall:
    async def test_a_personal_chat_is_neither_summarized_nor_indexed(self, db_session, user):
        chat = await _chat(db_session, user)
        assert await owner_allows_summaries(db_session, chat)
        assert await chat_recall_service._owner_allows(db_session, chat)
        await _close_chat(db_session, user)
        assert not await owner_allows_summaries(db_session, chat)
        assert not await chat_recall_service._owner_allows(db_session, chat)

    async def test_a_project_chat_is_the_project_s(self, db_session, user):
        chat = await _chat(db_session, user, await _project(db_session, user))
        await _close_chat(db_session, user)
        assert await owner_allows_summaries(db_session, chat)
        assert await chat_recall_service._owner_allows(db_session, chat)

    async def test_given_back_it_learns_again(self, db_session, user):
        chat = await _chat(db_session, user)
        await _close_chat(db_session, user)
        assert not await owner_allows_summaries(db_session, chat)
        rule = (await db_session.execute(FeatureAccessRule.__table__.select())).first()
        assert rule is not None
        await db_session.execute(FeatureAccessRule.__table__.delete())
        await db_session.commit()
        assert await owner_allows_summaries(db_session, chat)
