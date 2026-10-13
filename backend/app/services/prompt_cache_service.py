"""Provider prompt-cache breakpoints for multi-turn chat."""

from __future__ import annotations

import copy


def apply_prompt_cache_breakpoints(messages: list[dict]) -> list[dict]:
    """
    Mark the stable conversation prefix so providers (OpenRouter/Anthropic/etc.)
    can reuse cached prompt tokens on later turns.

    The latest user turn stays uncached; everything before the breakpoint can hit
    prompt cache on the next request when the prefix is unchanged.
    """
    if len(messages) < 2:
        return [dict(m) for m in messages]
    if messages[-1].get("role") != "user":
        return [dict(m) for m in messages]

    out = [dict(m) for m in messages]
    idx = len(out) - 2
    while idx >= 0 and out[idx].get("role") == "system":
        idx -= 1
    if idx < 0:
        return out
    # A tool call or a tool's answer (the browser extension's agent) is left as
    # it is: providers read those in shapes of their own, where a message-level
    # marker has no agreed place.
    if out[idx].get("role") not in ("user", "assistant") or out[idx].get("tool_calls"):
        return out

    marked = copy.deepcopy(out[idx])
    marked["cache_control"] = {"type": "ephemeral"}
    out[idx] = marked
    return out


def apply_message_cache_breakpoint(messages: list[dict], index: object) -> list[dict]:
    """
    Mark message ``index`` as the end of a cached prefix: the browser agent's
    settled history, which reads the same at its next steps. Not the last
    message, nor a system message (already marked), nor anything out of range.
    For Anthropic's models through litellm, which carries a marker on a tool's
    answer or a tool call as it does on any other message.
    """
    if not isinstance(index, int) or isinstance(index, bool) or not 0 < index < len(messages) - 1:
        return messages
    if messages[index].get("role") == "system":
        return messages
    out = list(messages)
    marked = copy.deepcopy(out[index])
    marked["cache_control"] = {"type": "ephemeral"}
    out[index] = marked
    return out


def apply_system_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """
    Mark the first system message as the end of a cached prefix.

    A browser agent run sends the same tools and instructions with every
    step, while its last message is a tool's answer or a screenshot, where
    ``apply_prompt_cache_breakpoints`` sets no marker. Providers read the
    tools before the system message, so this one marker covers both.
    """
    out = [dict(m) for m in messages]
    for idx, message in enumerate(out):
        if message.get("role") == "system":
            marked = copy.deepcopy(message)
            marked["cache_control"] = {"type": "ephemeral"}
            out[idx] = marked
            break
    return out
