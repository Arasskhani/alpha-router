"""Request logs: an index for the query every log page runs.

Revision ID: e3c4d5f6a7b8
Revises: d2b3c4e5f6a7
Create Date: 2026-09-19

``request_logs`` is one row per API call and the only table in the product with
no retention job, so it is both the largest and the fastest-growing. Its indexes
were single-column: one on ``user_id``, one on ``request_time``. The query the
API Logs page actually runs is "this user's calls, newest first", which either
index answers badly - PostgreSQL picks one, filters the rest, and sorts.

This goes in before the retention job that follows it. A first purge against an
unindexed table of this size is an outage, so the order is not incidental.

**On a large installation, build it by hand first.** A plain CREATE INDEX takes
ACCESS EXCLUSIVE for the whole build, which stops every request that logs:

    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_request_logs_user_time
        ON request_logs (user_id, request_time DESC);

Then upgrade as usual - this migration checks first and skips an index that is
already there. Building it inside the migration is correct on a fresh or small
database and is what happens if you do nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3c4d5f6a7b8"
down_revision: str | None = "d2b3c4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "request_logs"
_INDEX = "ix_request_logs_user_time"


def upgrade() -> None:
    bind = op.get_bind()
    if _INDEX in {index["name"] for index in sa.inspect(bind).get_indexes(_TABLE)}:
        return
    if bind.dialect.name == "postgresql":
        op.create_index(_INDEX, _TABLE, ["user_id", sa.text("request_time DESC")])
    else:
        # SQLite has no DESC index syntax worth the trouble; the column order is
        # what matters for the planner there.
        op.create_index(_INDEX, _TABLE, ["user_id", "request_time"])


def downgrade() -> None:
    if _INDEX in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
