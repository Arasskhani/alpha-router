"""A ceiling on how much an administrative list endpoint will ever return.

Several admin lists were unbounded end to end: no LIMIT in the query, no paging
in the API, and a frontend that rendered every row. On a directory of any size
the page is slow; on a large one the worker's memory is the limit, and
``deleted-users`` is the sharpest case because it only ever grows and nothing
trims it.

These endpoints are not feeds - an operator looking for someone filters rather
than scrolls - so the answer here is a cap with a signal, not silent paging.
The query asks for one row more than the cap, the extra row is dropped, and
``X-List-Truncated`` tells the page to say so. An operator who sees "showing the
first 2000 of more" narrows the filter; an operator who is silently shown 2000
of 50000 concludes the other 48000 are gone.

Paging proper is the better answer for ``/admin/users`` specifically, and it is
blocked on something real: the online filter needs Redis and the effective-plan
filter is resolved in Python, both after the query, so a LIMIT placed before
them yields ragged pages. Those two belong in SQL first.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

#: Rows any one administrative list will return. Chosen to be far above what an
#: operator reads and far below what costs a worker its memory.
ADMIN_LIST_HARD_CAP = 2000

#: PEP 695 type parameters, which ruff would prefer below, are newer than the
#: mypy this repository pins - it cannot parse them, and the parse error stops
#: it checking anything at all.
T = TypeVar("T")


def capped(statement: Any, *, cap: int = ADMIN_LIST_HARD_CAP) -> Any:
    """One more row than the cap, so the caller can tell there were more."""

    return statement.limit(cap + 1)


# noqa on the signature: see the note on T above.
def split_overflow(rows: Sequence[T], *, cap: int = ADMIN_LIST_HARD_CAP) -> tuple[list[T], bool]:  # noqa: UP047
    """``(the page, whether anything was left out)``."""

    listed = list(rows)
    if len(listed) > cap:
        return listed[:cap], True
    return listed, False


def mark_truncated(response: Any, truncated: bool, *, cap: int = ADMIN_LIST_HARD_CAP) -> None:
    """Say so in the response, always - absence of the header must not mean "fine"."""

    if response is None:
        return
    response.headers["X-List-Cap"] = str(cap)
    response.headers["X-List-Truncated"] = "true" if truncated else "false"
