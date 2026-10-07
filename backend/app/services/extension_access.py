"""Who may use the browser extension and its agent: the two Chat Tools ACLs.

``browser_extension`` (public by default) is the extension itself - the
download, connecting a browser, and every call a connected browser makes.
``browser_agent`` (private by default) lets the extension act on pages; it
means nothing without the first.

A disabled account may use neither, whatever the ACLs say, and so does the
organisation switch: turned off, the extension is refused for everyone - no
browser connects, and a browser already connected is refused its calls.

Feature Access has a Browser extension section too, closed for some people
the same way as Chat or Projects. Closed, it refuses the extension like the
``browser_extension`` ACL does: no download, no connecting, no calls. The
browser stays connected and works again once the section reopens.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feature_access import FEATURE_EXTENSION
from app.models.user import User
from app.services.chat_tool_access_service import permitted_tool_keys
from app.services.feature_access_service import feature_enabled
from app.services.extension_settings import ExtensionSettings, load_extension_settings
from app.services.resource_access_service import resolve_resource_access_subject

EXTENSION_TOOL = "browser_extension"
AGENT_TOOL = "browser_agent"
#: Full control (a real mouse and keyboard, screenshots): needs the agent, and the admin's switch.
CONTROL_TOOL = "browser_control"
PRIVATE_MODE_TOOL = "private_mode"

#: What a refusal says when it is the organisation switch, not the account's own access.
SWITCHED_OFF = "Your administrator turned the browser extension off."
#: What it says when the account is the reason.
NOT_PERMITTED = "The browser extension is not enabled for your account."


async def permitted_extension_tools(db: AsyncSession, user: User) -> frozenset[str]:
    """Which of the extension's tools this account may use."""
    if not user.is_active:
        return frozenset()
    subject = await resolve_resource_access_subject(db, user_id=int(user.id))
    return await permitted_tool_keys(db, subject, keys=[EXTENSION_TOOL, AGENT_TOOL, CONTROL_TOOL])


async def extension_switched_off(db: AsyncSession) -> bool:
    """The organisation switch, for a refusal that needs to say which reason it is."""
    return not (await load_extension_settings(db)).enabled


async def refusal_message(db: AsyncSession) -> str:
    """Why the extension is refused: an administrator's switch reads differently from an account's access."""
    return SWITCHED_OFF if await extension_switched_off(db) else NOT_PERMITTED


async def extension_permitted(db: AsyncSession, user: User) -> bool:
    """May this account use the extension at all: the organisation switch, Feature Access, then its ACL."""
    if await extension_switched_off(db):
        return False
    if not await feature_enabled(db, user, FEATURE_EXTENSION):
        return False
    return EXTENSION_TOOL in await permitted_extension_tools(db, user)


async def extension_features(db: AsyncSession, user: User, settings: ExtensionSettings) -> dict[str, bool]:
    """What the side panel offers this account: the ACLs, and the admin's Auto mode switch.

    The organisation switch (``enabled``) is over all of it: turned off, the
    extension offers nothing to anyone, whatever the ACLs say.
    """
    if not user.is_active or not settings.enabled or not await feature_enabled(db, user, FEATURE_EXTENSION):
        allowed: frozenset[str] = frozenset()
    else:
        subject = await resolve_resource_access_subject(db, user_id=int(user.id))
        allowed = await permitted_tool_keys(
            db, subject, keys=[EXTENSION_TOOL, AGENT_TOOL, CONTROL_TOOL, PRIVATE_MODE_TOOL]
        )
    chat = EXTENSION_TOOL in allowed
    agent = chat and AGENT_TOOL in allowed
    return {
        "chat": chat,
        "page_context": chat,
        "agent": agent,
        "auto_mode": agent and settings.agent_auto_mode,
        "full_control": agent and settings.full_control and CONTROL_TOOL in allowed,
        "private_mode": chat and PRIVATE_MODE_TOOL in allowed,
    }
