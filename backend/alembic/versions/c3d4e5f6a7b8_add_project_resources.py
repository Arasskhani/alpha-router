"""add project resources table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-19 11:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_resources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('processing', 'active', 'revoked', 'failed')",
            name="chk_project_resources_status",
        ),
        sa.UniqueConstraint("project_id", "document_id", name="uq_project_resources_project_document"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_resources_project", "project_resources", ["project_id"])
    op.create_index("ix_project_resources_status", "project_resources", ["status"])
    op.create_index("ix_project_resources_project_status", "project_resources", ["project_id", "status"])
    op.create_index("ix_project_resources_uploaded_by", "project_resources", ["uploaded_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_project_resources_uploaded_by", table_name="project_resources")
    op.drop_index("ix_project_resources_project_status", table_name="project_resources")
    op.drop_index("ix_project_resources_status", table_name="project_resources")
    op.drop_index("ix_project_resources_project", table_name="project_resources")
    op.drop_table("project_resources")
