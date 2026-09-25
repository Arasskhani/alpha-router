"""Canonical persisted chat/media wire markers."""

IMAGE_MESSAGE_PREFIX = "__ALPHA_ROUTER_IMAGE_JSON__:"
IMAGE_PENDING_MARKER = "__ALPHA_ROUTER_IMAGE_PENDING__"
VIDEO_MESSAGE_PREFIX = "__ALPHA_ROUTER_VIDEO_JSON__:"
VIDEO_PENDING_MARKER = "__ALPHA_ROUTER_VIDEO_PENDING__"
SPEECH_MESSAGE_PREFIX = "__ALPHA_ROUTER_SPEECH_JSON__:"
SPEECH_PENDING_MARKER = "__ALPHA_ROUTER_SPEECH_PENDING__"
ATTACHMENT_MESSAGE_PREFIX = "__ALPHA_ROUTER_ATTACH_JSON__:"
AUDIO_MESSAGE_PREFIX = "__ALPHA_ROUTER_AUDIO_JSON__:"

#: Server-owned body key: the hosts of the pages a chat turn carries from the
#: browser extension. Such a turn is answered without the user's memory or
#: profile, and its answer is marked with PAGE_CONTEXT_META_KEY.
PAGE_CONTEXT_BODY_KEY = "_page_context_sites"
#: Assistant message meta, ``{"sites": [host, ...]}``: an answer built from
#: pages shared from the browser. Page text is untrusted, so such an answer is
#: never learned from as memory, and the web app never loads its images.
PAGE_CONTEXT_META_KEY = "pageContext"
#: Server-owned body keys: the function tools the browser extension's agent
#: offers the model for one step, and the tool choice. The turn hands them to
#: the provider as ``tools`` / ``tool_choice`` and streams the model's tool
#: calls back; it is answered without the user's memory or profile.
BROWSER_TOOLS_BODY_KEY = "_browser_tools"
BROWSER_TOOL_CHOICE_BODY_KEY = "_browser_tool_choice"
