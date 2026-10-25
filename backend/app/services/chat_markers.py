"""Canonical persisted chat/media wire markers."""

IMAGE_MESSAGE_PREFIX = "__ALPHA_ROUTER_IMAGE_JSON__:"
IMAGE_PENDING_MARKER = "__ALPHA_ROUTER_IMAGE_PENDING__"
VIDEO_MESSAGE_PREFIX = "__ALPHA_ROUTER_VIDEO_JSON__:"
VIDEO_PENDING_MARKER = "__ALPHA_ROUTER_VIDEO_PENDING__"
SPEECH_MESSAGE_PREFIX = "__ALPHA_ROUTER_SPEECH_JSON__:"
SPEECH_PENDING_MARKER = "__ALPHA_ROUTER_SPEECH_PENDING__"
ATTACHMENT_MESSAGE_PREFIX = "__ALPHA_ROUTER_ATTACH_JSON__:"
AUDIO_MESSAGE_PREFIX = "__ALPHA_ROUTER_AUDIO_JSON__:"
#: The answer of a media turn while its image, video or speech is being made.
PENDING_MARKERS = frozenset({IMAGE_PENDING_MARKER, VIDEO_PENDING_MARKER, SPEECH_PENDING_MARKER})


def is_answer_in_progress(content: object, streaming: object) -> bool:
    """An assistant message still being written: streaming, or a media turn's pending marker."""
    return streaming is True or (isinstance(content, str) and content.strip() in PENDING_MARKERS)


def is_whole_reply(message: dict) -> bool:
    """A message as the browser sends it (``role``, ``content``, ``streaming``) that is a finished answer."""
    return str(message.get("role") or "") == "assistant" and not is_answer_in_progress(
        message.get("content"), message.get("streaming")
    )


#: Server-owned body key: the hosts of the pages a chat turn carries from the
#: browser extension. Such a turn is answered without the user's memory or
#: profile, and its answer is marked with PAGE_CONTEXT_META_KEY.
PAGE_CONTEXT_BODY_KEY = "_page_context_sites"
#: Assistant message meta, ``{"sites": [host, ...]}``: an answer built from
#: pages shared from the browser. Page text is untrusted, so such an answer is
#: never learned from as memory, and the web app never loads its images.
PAGE_CONTEXT_META_KEY = "pageContext"
#: Assistant message meta, ``{"dropped": n, "summarized": m}``: the chat was
#: longer than the model's window, and its ``n`` oldest messages were not sent
#: word for word (``m`` of them stood in for by the chat's summary).
CONTEXT_FIT_META_KEY = "contextFit"
#: Assistant message meta, ``[{"id": session_id, "title": ...}]``: the person's
#: earlier chats this answer read from (recall).
RECALLED_CHATS_META_KEY = "recalledChats"
#: Assistant message meta, ``[{"title": ..., "url": ...}]``: the pages the model
#: searched up or read with the web tools while answering.
WEB_SOURCES_META_KEY = "webSources"
#: Assistant message meta, ``[{"id", "mailbox", "kind", "subject", "to", "cc", "preview"}]``: the drafts the
#: model saved in the person's Exchange mailbox while answering (``mail_drafts.id``), shown as draft cards.
MAIL_DRAFTS_META_KEY = "mailDrafts"
#: Assistant message meta, ``{"read": true}``: an answer for which the mail tools returned email content
#: (``mail_search``, ``mail_read``, ``mail_create_draft``). Email is untrusted - anyone can write to the person -
#: so, as with PAGE_CONTEXT_META_KEY, no memory is learned from such an answer and the web app never loads its
#: images (an email could ask for an image whose address carries other emails away).
MAIL_CONTEXT_META_KEY = "mailContext"
#: Assistant message meta, ``[str]``: what Guardrails told the person about their request (values masked
#: before sending, the request sent to another model), as the administrator worded it.
GUARDRAIL_META_KEY = "guardrailNotices"
#: Server-owned body keys: the function tools the browser extension's agent
#: offers the model for one step, and the tool choice. The turn hands them to
#: the provider as ``tools`` / ``tool_choice`` and streams the model's tool
#: calls back; it is answered without the user's memory or profile.
BROWSER_TOOLS_BODY_KEY = "_browser_tools"
BROWSER_TOOL_CHOICE_BODY_KEY = "_browser_tool_choice"
#: The reasoning effort the administrator holds the agent's model to (``low`` or ``medium``); absent: the provider's.
BROWSER_REASONING_BODY_KEY = "_browser_reasoning"
#: Where the agent's conversation settles (the index of the last message that reads the same at its next steps).
BROWSER_CACHE_POINT_BODY_KEY = "_browser_cache_point"
#: Assistant message meta: a Guardrails rule refused the turn; ``{"message": str}`` is shown in place of an answer.
GUARDRAIL_BLOCKED_META_KEY = "guardrailBlocked"
#: User message meta: the message a rule refused, kept with its values hidden and never sent to a model again.
GUARDRAIL_HELD_BACK_META_KEY = "guardrailHeldBack"


def refused_by_guardrails(meta: object) -> bool:
    """A message of a turn Guardrails refused (the held-back question, or the refusal in place of an answer).

    Never read back to a model: not in a turn's history, a summary or what memory learns from.
    """
    return isinstance(meta, dict) and bool(
        meta.get(GUARDRAIL_HELD_BACK_META_KEY) or meta.get(GUARDRAIL_BLOCKED_META_KEY)
    )
