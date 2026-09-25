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
