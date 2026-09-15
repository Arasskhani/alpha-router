"""Request logs: why a request failed, not just that it did.

Revision ID: 6d2e3f4a5b6c
Revises: 5c1d2e3f4a5b
Create Date: 2026-09-15

``request_logs`` recorded ``success`` and a free-text ``error_message`` that
was frequently empty (see ``app/services/failure_details``), so the API Logs
page could only ever say "Fail". These four columns make a failed request
answer the operator's actual questions: what kind of failure, what the
upstream answered, which container log lines belong to it, and — for async
media — which provider job it was.

All nullable: every existing row keeps its meaning, and paths that cannot
supply a value simply leave it empty.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6d2e3f4a5b6c"
down_revision: str | None = "5c1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS = (
    ("error_code", sa.String(length=64), True),
    ("http_status", sa.Integer(), False),
    ("correlation_id", sa.String(length=64), True),
    ("provider_job_id", sa.String(length=128), True),
)


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("request_logs")}
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("request_logs")}
    for name, type_, indexed in _COLUMNS:
        if name not in existing:
            op.add_column("request_logs", sa.Column(name, type_, nullable=True))
        index_name = f"ix_request_logs_{name}"
        if indexed and index_name not in indexes:
            op.create_index(index_name, "request_logs", [name])


def downgrade() -> None:
    for name, _type, indexed in _COLUMNS:
        if indexed:
            op.drop_index(f"ix_request_logs_{name}", table_name="request_logs")
        op.drop_column("request_logs", name)
