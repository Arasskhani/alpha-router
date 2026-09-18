"""Two different requests never collapse onto one reservation row.

The scoped key was a plain ``[:160]`` slice of
``{subject_type}:{subject_id}:{idempotency_key}``. ``alpha_router_key`` is 16
characters, the operation prefix adds up to 32 more, and nothing validates the
caller's key length - so a long key could be cut short, two requests differing
only in the dropped tail produced the same scoped key, and the second was
refused with "Duplicate request idempotency key". Silently, and looking like a
duplicate rather than a bug.
"""

from __future__ import annotations

from app.services.budget_reservation_service import _SCOPED_KEY_MAX, _scoped_idempotency_key


def test_a_key_that_fits_is_left_alone():
    """Existing keys and existing rows must be unaffected."""

    assert _scoped_idempotency_key("user", 7, "chat:abc123") == "user:7:chat:abc123"


def test_the_result_always_fits_the_column():
    for length in (1, 100, 128, 200, 5000):
        scoped = _scoped_idempotency_key("alpha_router_key", 999999, "chat:" + "x" * length)
        assert len(scoped) <= _SCOPED_KEY_MAX, length


def test_keys_differing_only_past_the_cut_stay_distinct():
    base = "chat:" + "x" * 200
    first = _scoped_idempotency_key("alpha_router_key", 12345, base + "a")
    second = _scoped_idempotency_key("alpha_router_key", 12345, base + "b")
    assert first != second, "two distinct requests would share one reservation row"


def test_the_same_key_is_stable():
    """Idempotency depends on it: the same request must scope to the same row."""

    key = "chat:" + "y" * 300
    assert _scoped_idempotency_key("user", 1, key) == _scoped_idempotency_key("user", 1, key)


def test_subjects_do_not_share_a_key():
    key = "chat:" + "z" * 300
    assert _scoped_idempotency_key("user", 1, key) != _scoped_idempotency_key("user", 2, key)
    assert _scoped_idempotency_key("user", 1, key) != _scoped_idempotency_key("alpha_router_key", 1, key)
