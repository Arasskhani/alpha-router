"""The page that grants chat tools, and the trail it leaves.

The property worth protecting here is that this endpoint enumerates the
registry and nothing else. A tool added to ``CHAT_TOOLS`` has to turn up on
the page with no work anywhere in this file, or the "register once" promise is
only true for the parts somebody remembered to generalise.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.api.admin_chat_tools import (
    ChatToolAccessBody,
    list_chat_tools,
    read_chat_tool_access,
    replace_chat_tool_access,
)
from app.models.security import SecurityAuditEvent
from app.services.chat_tool_registry import CHAT_TOOLS


class _Request:
    def __init__(self, host: str = "203.0.113.9") -> None:
        self.client = type("C", (), {"host": host})()
        self.headers: dict[str, str] = {}


def _body(access_type: str, grants: list[dict] | None = None) -> ChatToolAccessBody:
    return ChatToolAccessBody.model_validate({"access_type": access_type, "grants": grants or []})


class TestTheList:
    async def test_it_has_a_row_for_every_registered_tool(self, db_session):
        rows = await list_chat_tools(db=db_session, _=None)
        assert [row["key"] for row in rows] == [spec.key for spec in CHAT_TOOLS]

    async def test_a_row_carries_what_the_page_draws(self, db_session):
        row = (await list_chat_tools(db=db_session, _=None))[0]
        assert {"key", "title", "description", "icon", "access_type"} <= set(row)
        assert {"allow_count", "deny_count", "updated_at", "acl_version"} <= set(row)


class TestSavingFromThePage:
    async def test_it_saves_and_reads_back(self, db_session, admin, user):
        await replace_chat_tool_access(
            tool_key="code_interpreter",
            body=_body("private", [{"target_type": "user", "target": user.id, "effect": "allow"}]),
            request=_Request(),
            db=db_session,
            actor=admin,
        )
        saved = await read_chat_tool_access(tool_key="code_interpreter", db=db_session, _=None)
        assert saved["access_type"] == "private"
        assert saved["grants"] == [{"target_type": "user", "target": user.id, "effect": "allow"}]

    async def test_the_change_is_recorded_with_both_sides_of_it(self, db_session, admin, user):
        """ "Who took Code Interpreter away, and what was it before" is the
        question this trail exists to answer."""
        await replace_chat_tool_access(
            tool_key="code_interpreter",
            body=_body("private", [{"target_type": "user", "target": user.id, "effect": "allow"}]),
            request=_Request(),
            db=db_session,
            actor=admin,
        )
        event = (await db_session.execute(select(SecurityAuditEvent))).scalars().one()
        assert event.action == "chat_tool_access_changed"
        assert event.resource_type == "chat_tool"
        assert event.resource_id == "code_interpreter"
        assert event.actor_username == admin.username
        assert event.actor_ip == "203.0.113.9"
        detail = json.loads(event.detail_json)
        assert detail["before"] == {"access_type": "public", "grants": []}
        assert detail["after"]["access_type"] == "private"
        assert detail["after"]["grants"] == [[f"user:{user.id}", "allow"]]

    async def test_the_list_reflects_the_save(self, db_session, admin, user):
        await replace_chat_tool_access(
            tool_key="web_search",
            body=_body(
                "public",
                [{"target_type": "user", "target": user.id, "effect": "deny"}],
            ),
            request=_Request(),
            db=db_session,
            actor=admin,
        )
        row = next(r for r in await list_chat_tools(db=db_session, _=None) if r["key"] == "web_search")
        assert (row["access_type"], row["allow_count"], row["deny_count"]) == ("public", 0, 1)
        assert row["updated_at"] is not None

    async def test_a_grant_that_names_nobody_real_is_a_400(self, db_session, admin):
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as caught:
            await replace_chat_tool_access(
                tool_key="web_search",
                body=_body("private", [{"target_type": "user", "target": 999999}]),
                request=_Request(),
                db=db_session,
                actor=admin,
            )
        assert caught.value.status_code == 400

    async def test_a_tool_that_is_not_registered_is_a_404(self, db_session, admin):
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as caught:
            await replace_chat_tool_access(
                tool_key="rm_rf",
                body=_body("private"),
                request=_Request(),
                db=db_session,
                actor=admin,
            )
        assert caught.value.status_code == 404


class TestThePermissionThePageSitsBehind:
    def test_the_endpoints_require_the_chat_tools_menu(self):
        """The page is in the Chat experience section; its API has to agree,
        or the sidebar shows a page whose data nobody can load."""
        from app.api import admin_chat_tools
        from app.api.deps import require_chat_tools, require_chat_tools_write

        guards = {
            route.name: [dep.call for dep in route.dependant.dependencies] for route in admin_chat_tools.router.routes
        }
        assert require_chat_tools in guards["list_chat_tools"]
        assert require_chat_tools in guards["read_chat_tool_access"]
        assert require_chat_tools_write in guards["replace_chat_tool_access"]
