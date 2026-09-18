"""Memory extraction spend belongs to somebody.

``persist_usage_operation`` was called with ``user_id=None``, so every memory
extraction - a real completion call against a real model - landed in the ledger
attached to no subject. It therefore appeared in no report and against no
budget, while the Admin Guide says every provider attempt counts.

No reservation goes with the attribution. The point is that the cost is visible,
not that a background job can start refusing to run when someone is near their
ceiling.
"""

from __future__ import annotations

import inspect

from app.services import memory_extraction_service


def test_the_usage_row_names_the_user_it_was_extracted_for():
    source = inspect.getsource(memory_extraction_service.extract_memory_operations)
    assert "user_id=window.user_id," in source
    assert "user_id=None," not in source, "the usage row is still subjectless"


def test_no_budget_reservation_is_attached():
    """Attribution is for reporting; a memory job must not be blocked by a budget."""

    source = inspect.getsource(memory_extraction_service.extract_memory_operations)
    assert "budget_reservation_id=None," in source


def test_the_window_carries_the_user():
    """The id was available all along, one attribute away from the call."""

    assert "user_id" in memory_extraction_service.ExtractionWindow.__dataclass_fields__
