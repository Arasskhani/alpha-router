"""Every tool a chat turn can be given, declared in one place.

Before this, a chat tool existed in five places that had to agree with each
other by hand: a boolean on :class:`~app.api.chat.ChatToolsIn`, a field on
``ChatToolsConfig``, a toggle in the chat menu, a branch wherever it is
executed, and nothing at all in the admin panel. Adding one meant touching
all five and remembering the fifth.

This module is the list. A tool is registered here once, next to where it is
defined, and everything that has to enumerate tools reads it: the access
policy, the admin page, the endpoint that tells a client what it may use, the
audit trail and the guide. None of those grow a branch per tool, so a new tool
arrives with governance already attached rather than as a follow-up commit
somebody has to remember.

``key`` is the wire name the client already sends and must not change once
shipped: it is what a policy row and its access grants are keyed by. Most keys
here name what the chat composer offers; the last two govern the browser
extension, which the composer never shows. The same registry (and the same two
tables behind it) can hold anything else a turn may be granted later - an
Agent tool by slug, a document export - without a migration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``access_type`` values, matching the other ACLs in this product.
ACCESS_PUBLIC = "public"
ACCESS_PRIVATE = "private"

#: Icon names the client knows how to draw. A key outside this set would
#: render as a blank square, so the registry test refuses one.
KNOWN_ICONS = frozenset(
    {
        "globe",
        "link",
        "image",
        "video",
        "speaker",
        "microphone",
        "terminal",
        "lock",
        "puzzle",
        "cursor",
    }
)

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class ChatToolSpec:
    """One governable chat tool.

    :param key: wire name; also the primary key of its access policy.
    :param title: what the operator and the user see.
    :param description: one line, shown under the title in both menus.
    :param icon: a name from :data:`KNOWN_ICONS`.
    :param default_access: the policy used until an administrator saves one.
        ``public`` means "everybody, until restricted" - the behaviour every
        one of these tools had before this registry existed, and the reason an
        upgrade changes nothing for anybody. ``private`` suits a tool that did
        not exist before and should reach nobody until an administrator grants
        it.
    """

    key: str
    title: str
    description: str
    icon: str
    default_access: str = ACCESS_PUBLIC


CHAT_TOOLS: tuple[ChatToolSpec, ...] = (
    ChatToolSpec(
        key="web_search",
        title="Web Search",
        description="Fresh web results",
        icon="globe",
    ),
    ChatToolSpec(
        key="web_fetch",
        title="Web Fetch",
        description="Read links in your message",
        icon="link",
    ),
    ChatToolSpec(
        key="image_generation",
        title="Image Generation",
        description="Create or edit images from text",
        icon="image",
    ),
    ChatToolSpec(
        key="video_generation",
        title="Video Generation",
        description="Create short videos from text",
        icon="video",
    ),
    ChatToolSpec(
        key="speech_generation",
        title="Text to Speech",
        description="Read the answer aloud",
        icon="speaker",
    ),
    ChatToolSpec(
        key="speech_to_text",
        title="Voice Messages",
        description="Dictate a message instead of typing",
        icon="microphone",
    ),
    ChatToolSpec(
        key="code_interpreter",
        title="Code Interpreter",
        description="Run Python in a sandbox",
        icon="terminal",
    ),
    ChatToolSpec(
        key="private_mode",
        title="Private Mode",
        description="Do not store this conversation",
        icon="lock",
    ),
    # The browser extension: connecting it, downloading it and every request
    # it makes. Public like the rest - restricting it is how an administrator
    # keeps the extension away from a role or a group.
    ChatToolSpec(
        key="browser_extension",
        title="Browser Extension",
        description="Use Alpharouter from the browser side panel",
        icon="puzzle",
    ),
    # The extension's agent clicks and types in the user's own signed-in tabs.
    # Nobody has it until an administrator grants it.
    ChatToolSpec(
        key="browser_agent",
        title="Browser Agent",
        description="Let the extension click and type in web pages",
        icon="cursor",
        default_access=ACCESS_PRIVATE,
    ),
)

TOOL_BY_KEY: dict[str, ChatToolSpec] = {spec.key: spec for spec in CHAT_TOOLS}

#: Keys whose toggle travels in the ``tools`` object of a chat request. The
#: rest are asked for another way - their own endpoint, or a field of their
#: own - and are enforced where that request arrives.
REQUEST_TOOL_KEYS: frozenset[str] = frozenset(
    {"web_search", "web_fetch", "image_generation", "video_generation", "speech_generation", "code_interpreter"}
)


def is_valid_key(key: str) -> bool:
    return bool(_KEY_RE.match(key or ""))


def spec_or_none(key: str) -> ChatToolSpec | None:
    return TOOL_BY_KEY.get((key or "").strip())


def requested_tool_keys(body: dict) -> frozenset[str]:
    """The registered tools this chat request is asking for.

    Reads both shapes the API accepts - the ``tools`` object and the legacy
    top-level ``web_search`` flag - so enforcement sees exactly what
    :func:`app.services.chat_tools_service.parse_tools_config` will act on.
    Unknown keys are ignored here; they are not tools this product runs.
    """
    raw = body.get("tools")
    tools: dict = raw if isinstance(raw, dict) else {}
    requested = {key for key in REQUEST_TOOL_KEYS if tools.get(key) or body.get(key)}
    if body.get("private_mode"):
        requested.add("private_mode")
    return frozenset(requested)
