"""The themes a person can save: the request model and the store agree, and ALPHA BLACK is one of them."""

from __future__ import annotations

from typing import get_args

from sqlalchemy import select

from app.api.user_chats import UserPrefsPatchIn
from app.models.user import User
from app.services.user_chat_storage_service import USER_THEMES, save_user_prefs


def test_the_request_accepts_exactly_the_stored_themes():
    literal = get_args(UserPrefsPatchIn.model_fields["theme"].annotation)[0]
    assert set(get_args(literal)) == set(USER_THEMES)


async def test_alpha_black_is_kept_and_an_unknown_theme_falls_back(db_session, user):
    me = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert (await save_user_prefs(db_session, me.id, {"theme": "alpha-black"}))["theme"] == "alpha-black"
    assert (await save_user_prefs(db_session, me.id, {"theme": "matrix"}))["theme"] == "light"
