from app.services.prompt_cache_service import apply_prompt_cache_breakpoints


def test_no_breakpoint_for_single_user_message():
    msgs = [{"role": "user", "content": "hi"}]
    assert apply_prompt_cache_breakpoints(msgs) == msgs


def test_breakpoint_before_latest_user_turn():
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "one"},
        {"role": "user", "content": "second"},
    ]
    out = apply_prompt_cache_breakpoints(msgs)
    assert out[0].get("cache_control") is None
    assert out[1]["cache_control"] == {"type": "ephemeral"}
    assert out[2].get("cache_control") is None


def test_skips_when_last_message_not_user():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert apply_prompt_cache_breakpoints(msgs) == msgs


def test_leaves_a_tool_answer_before_the_latest_user_turn_alone():
    # The browser extension's agent: the user writes again after a tool answered.
    msgs = [
        {"role": "user", "content": "Fill in the form"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "done", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "user", "content": "Now submit it"},
    ]
    out = apply_prompt_cache_breakpoints(msgs)
    assert out == msgs
    assert all("cache_control" not in message for message in out)


def test_leaves_an_assistant_tool_call_before_the_latest_user_turn_alone():
    msgs = [
        {"role": "user", "content": "Open the page"},
        {
            "role": "assistant",
            "content": "Opening it.",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "navigate", "arguments": "{}"}}],
        },
        {"role": "user", "content": "Stop"},
    ]
    assert apply_prompt_cache_breakpoints(msgs) == msgs
