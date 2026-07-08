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
