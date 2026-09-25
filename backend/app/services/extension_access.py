"""Who may use the browser extension and its agent: the two Chat Tools ACLs.

``browser_extension`` (public by default) is the extension itself - the
download, connecting a browser, and every call a connected browser makes.
``browser_agent`` (private by default) lets the extension act on pages; it
means nothing without the first.

A disabled account may use neither, whatever the ACLs say.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.chat_tool_access_service import permitted_tool_keys
from app.services.resource_access_service import resolve_resource_access_subject

EXTENSION_TOOL = "browser_extension"
AGENT_TOOL = "browser_agent"


async def permitted_extension_tools(db: AsyncSession, user: User) -> frozenset[str]:
    """Which of the extension's two tools this account may use."""
    if not user.is_active:
        return frozenset()
    subject = await resolve_resource_access_subject(db, user_id=int(user.id))
    return await permitted_tool_keys(db, subject, keys=[EXTENSION_TOOL, AGENT_TOOL])


async def extension_permitted(db: AsyncSession, user: User) -> bool:
    return EXTENSION_TOOL in await permitted_extension_tools(db, user)
