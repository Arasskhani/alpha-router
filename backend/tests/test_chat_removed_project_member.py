"""A member removed from a project reads none of its chats through a turn - not even the one they started.

A project chat is stored under the member who started it. The turn's read
paths asked only "is this the person's session?", so a member removed from a
private project could keep sending turns in a chat they had started there:
recall searched the project's other chats (written after they left, too),
history completion put the whole chat in front of the turn, and the chat's
summary went with it. Project access now answers for every project chat,
whoever started it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.models.chat import ChatSummary
from app.models.project import PROJECT_ROLE_CONTRIBUTOR, PROJECT_ROLE_PRIMARY_OWNER, Project, ProjectMember
from app.services import chat_summary_service as summaries
from app.services.chat_history_service import complete_chat_history
from app.services.chat_recall_service import recall_for_turn
from app.services.chat_session_access import resolve_owned_chat_session
from app.services.chat_summary_service import summary_for_turn
from tests.test_chat_recall import WORKOUT, _chat, _indexed, _person, store  # noqa: F401 -- the store fixture

PROJECT = "proj-left"


async def _project_with(db, owner, member) -> None:
    db.add(
        Project(
            id=PROJECT,
            name="Gym app",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    await db.flush()
    db.add(ProjectMember(project_id=PROJECT, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJECT, user_id=member.id, role=PROJECT_ROLE_CONTRIBUTOR))
    await db.commit()


async def _remove(db, member) -> None:
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == member.id))
    await db.commit()


def _asking(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


async def _summary(db, chat) -> None:
    now = dt.datetime.utcnow()
    db.add(
        ChatSummary(
            session_id=chat.id,
            user_id=chat.user_id,
            project_id=chat.project_id,
            content="The team squats on Monday.",
            up_to_sequence=2,
            covered_count=2,
            first_message_hash=summaries._hash(WORKOUT[0]),
            status="idle",
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    await db.commit()


async def test_a_removed_member_s_turn_reads_nothing_of_the_project(db_session, user, store):  # noqa: F811
    owner = await _person(db_session, "owner")
    await _project_with(db_session, owner, user)
    theirs = await _chat(db_session, owner, "Team workout plan", WORKOUT, project_id=PROJECT)
    await _indexed(db_session, theirs)
    started = await _chat(db_session, user, "My project chat", WORKOUT, project_id=PROJECT)
    await _summary(db_session, started)

    # While a member: the turn may read the project.
    assert (await resolve_owned_chat_session(db_session, user=user, chat_session_id=started.id)).id == started.id
    member_recall = await recall_for_turn(
        db_session,
        user_id=user.id,
        chat_session_id=started.id,
        messages=_asking("the workout plan on Monday"),
        private_mode=False,
        via_api_key=False,
    )
    assert [chat["id"] for chat in member_recall.chats] == [theirs.id]

    await _remove(db_session, user)

    with pytest.raises(HTTPException) as refused:
        await resolve_owned_chat_session(db_session, user=user, chat_session_id=started.id)
    assert refused.value.status_code == 404
    recalled = await recall_for_turn(
        db_session,
        user_id=user.id,
        chat_session_id=started.id,
        messages=_asking("the workout plan on Monday"),
        private_mode=False,
        via_api_key=False,
    )
    assert recalled.block is None and recalled.chats == []
    turn = _asking("What next?")
    completed, added = await complete_chat_history(
        db_session, user=user, chat_session_id=started.id, messages=turn, history_from_sequence=3
    )
    assert (completed, added) == (turn, 0)
    found = await summary_for_turn(
        db_session,
        chat_session_id=started.id,
        user_id=user.id,
        messages=[{"role": "user", "content": WORKOUT[0]}],
    )
    assert found is None


async def test_a_personal_chat_is_still_its_owner_s_alone(db_session, user):
    other = await _person(db_session, "someone")
    mine = await _chat(db_session, user, "Mine", WORKOUT)
    assert (await resolve_owned_chat_session(db_session, user=user, chat_session_id=mine.id)).id == mine.id
    with pytest.raises(HTTPException):
        await resolve_owned_chat_session(db_session, user=other, chat_session_id=mine.id)
