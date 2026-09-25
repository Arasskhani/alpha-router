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
from app.services.extension_settings import ExtensionSettings
from app.services.resource_access_service import resolve_resource_access_subject

EXTENSION_TOOL = "browser_extension"
AGENT_TOOL = "browser_agent"
PRIVATE_MODE_TOOL = "private_mode"


async def permitted_extension_tools(db: AsyncSession, user: User) -> frozenset[str]:
    """Which of the extension's two tools this account may use."""
    if not user.is_active:
        return frozenset()
    subject = await resolve_resource_access_subject(db, user_id=int(user.id))
    return await permitted_tool_keys(db, subject, keys=[EXTENSION_TOOL, AGENT_TOOL])


async def extension_permitted(db: AsyncSession, user: User) -> bool:
    return EXTENSION_TOOL in await permitted_extension_tools(db, user)


async def extension_features(db: AsyncSession, user: User, settings: ExtensionSettings) -> dict[str, bool]:
    """What the side panel offers this account: the ACLs, and the admin's Auto mode switch."""
    if not user.is_active:
        allowed: frozenset[str] = frozenset()
    else:
        subject = await resolve_resource_access_subject(db, user_id=int(user.id))
        allowed = await permitted_tool_keys(db, subject, keys=[EXTENSION_TOOL, AGENT_TOOL, PRIVATE_MODE_TOOL])
    chat = EXTENSION_TOOL in allowed
    agent = chat and AGENT_TOOL in allowed
    return {
        "chat": chat,
        "page_context": chat,
        "agent": agent,
        "auto_mode": agent and settings.agent_auto_mode,
        "private_mode": chat and PRIVATE_MODE_TOOL in allowed,
    }
