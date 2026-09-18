"""What the hold quotes and what the provider is asked for are the same number.

``n`` was ``int = 1`` with no bound. The budget hold quoted ``min(4, n)`` in
three places, but the provider call passed ``body.n`` verbatim and the bill
counted ``len(out)``. Budget is only checked at admission, so a request for 50
images was admitted against a hold for 4, charged for 50, and only the *next*
request was refused.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.api import images
from app.api.images import IMAGE_MAX_BATCH, ImageRequest


def test_a_request_over_the_batch_limit_is_refused():
    with pytest.raises(ValidationError):
        ImageRequest(model="m", prompt="p", n=IMAGE_MAX_BATCH + 1)


def test_zero_and_negative_are_refused():
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            ImageRequest(model="m", prompt="p", n=bad)


def test_the_limit_itself_is_accepted():
    assert ImageRequest(model="m", prompt="p", n=IMAGE_MAX_BATCH).n == IMAGE_MAX_BATCH
    assert ImageRequest(model="m", prompt="p").n == 1


def test_no_site_hardcodes_a_different_batch_number():
    """The hold, the provider call and the reservation must agree."""

    code = [line for line in inspect.getsource(images).splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "min(4, " in line], "a hardcoded 4 is back; use IMAGE_MAX_BATCH"


def test_the_provider_is_not_sent_the_raw_field():
    source = inspect.getsource(images)
    assert '"n": body.n,' not in source, (
        "the unclamped field reached the provider again; the bill follows what comes back"
    )
