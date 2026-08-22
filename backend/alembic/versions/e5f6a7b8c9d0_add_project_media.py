"""add project media assets and project_id on image/video generation

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-19 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _index_exists(inspector, table: str, index: str) -> bool:
    return index in {idx["name"] for idx in inspector.get_indexes(table)}


def _fk_exists(inspector, table: str, fk_name: str) -> bool:
    return fk_name in {
        fk["name"] for fk in inspector.get_foreign_keys(table) if fk.get("name")
    }


def _table_exists(inspector, table: str) -> bool:
    return table in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # ------------------------------------------------------------------
    # 1. Create project_media_assets table
    # ------------------------------------------------------------------
    if not _table_exists(inspector, "project_media_assets"):
        op.create_table(
            "project_media_assets",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer, nullable=True),
            sa.Column("kind", sa.String(length=32), nullable=False, server_default="image"),
            sa.Column(
                "mime_type",
                sa.String(length=128),
                nullable=False,
                server_default="application/octet-stream",
            ),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("storage_path", sa.Text, nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("source_model", sa.String(length=512), nullable=True),
            sa.Column("source_prompt", sa.Text, nullable=True),
            sa.Column("chat_session_id", sa.String(length=128), nullable=True),
            sa.Column("metadata_json", sa.Text, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("expires_at", sa.DateTime, nullable=True),
            sa.UniqueConstraint(
                "project_id",
                "content_hash",
                name="uq_project_media_assets_project_hash",
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["uploaded_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
        )

    project_media_indexes = {
        idx["name"] for idx in inspector.get_indexes("project_media_assets")
    }
    if "ix_project_media_assets_project_id" not in project_media_indexes:
        op.create_index(
            "ix_project_media_assets_project_id",
            "project_media_assets",
            ["project_id"],
        )
    if "ix_project_media_project_kind" not in project_media_indexes:
        op.create_index(
            "ix_project_media_project_kind",
            "project_media_assets",
            ["project_id", "kind"],
        )
    if "ix_project_media_uploaded_by" not in project_media_indexes:
        op.create_index(
            "ix_project_media_uploaded_by",
            "project_media_assets",
            ["uploaded_by_user_id"],
        )
    if (
        "ix_project_media_assets_content_hash" not in project_media_indexes
        and "content_hash" in {c["name"] for c in inspector.get_columns("project_media_assets")}
    ):
        op.create_index(
            "ix_project_media_assets_content_hash",
            "project_media_assets",
            ["content_hash"],
        )

    # ------------------------------------------------------------------
    # 2. Add project_id to image_generation_attempts
    # ------------------------------------------------------------------
    if not _column_exists(inspector, "image_generation_attempts", "project_id"):
        if dialect == "sqlite":
            with op.batch_alter_table("image_generation_attempts") as batch:
                batch.add_column(
                    sa.Column("project_id", sa.String(length=36), nullable=True)
                )
        else:
            op.add_column(
                "image_generation_attempts",
                sa.Column("project_id", sa.String(length=36), nullable=True),
            )

    if not _index_exists(inspector, "image_generation_attempts", "ix_image_generation_attempts_project_id"):
        op.create_index(
            "ix_image_generation_attempts_project_id",
            "image_generation_attempts",
            ["project_id"],
        )

    fk_img = "fk_image_generation_attempts_project_id"
    if not _fk_exists(inspector, "image_generation_attempts", fk_img):
        if dialect == "sqlite":
            with op.batch_alter_table("image_generation_attempts") as batch:
                batch.create_foreign_key(
                    fk_img,
                    "projects",
                    ["project_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                fk_img,
                "image_generation_attempts",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # ------------------------------------------------------------------
    # 3. Add project_id to video_generation_jobs
    # ------------------------------------------------------------------
    if not _column_exists(inspector, "video_generation_jobs", "project_id"):
        if dialect == "sqlite":
            with op.batch_alter_table("video_generation_jobs") as batch:
                batch.add_column(
                    sa.Column("project_id", sa.String(length=36), nullable=True)
                )
        else:
            op.add_column(
                "video_generation_jobs",
                sa.Column("project_id", sa.String(length=36), nullable=True),
            )

    if not _index_exists(inspector, "video_generation_jobs", "ix_video_generation_jobs_project_id"):
        op.create_index(
            "ix_video_generation_jobs_project_id",
            "video_generation_jobs",
            ["project_id"],
        )

    fk_vid = "fk_video_generation_jobs_project_id"
    if not _fk_exists(inspector, "video_generation_jobs", fk_vid):
        if dialect == "sqlite":
            with op.batch_alter_table("video_generation_jobs") as batch:
                batch.create_foreign_key(
                    fk_vid,
                    "projects",
                    ["project_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                fk_vid,
                "video_generation_jobs",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # video_generation_jobs
    fk_vid = "fk_video_generation_jobs_project_id"
    if _fk_exists(inspector, "video_generation_jobs", fk_vid):
        if dialect == "sqlite":
            with op.batch_alter_table("video_generation_jobs") as batch:
                batch.drop_constraint(fk_vid, type_="foreignkey")
        else:
            op.drop_constraint(fk_vid, "video_generation_jobs", type_="foreignkey")

    if _index_exists(inspector, "video_generation_jobs", "ix_video_generation_jobs_project_id"):
        op.drop_index("ix_video_generation_jobs_project_id", table_name="video_generation_jobs")

    if _column_exists(inspector, "video_generation_jobs", "project_id"):
        if dialect == "sqlite":
            with op.batch_alter_table("video_generation_jobs") as batch:
                batch.drop_column("project_id")
        else:
            op.drop_column("video_generation_jobs", "project_id")

    # image_generation_attempts
    fk_img = "fk_image_generation_attempts_project_id"
    if _fk_exists(inspector, "image_generation_attempts", fk_img):
        if dialect == "sqlite":
            with op.batch_alter_table("image_generation_attempts") as batch:
                batch.drop_constraint(fk_img, type_="foreignkey")
        else:
            op.drop_constraint(fk_img, "image_generation_attempts", type_="foreignkey")

    if _index_exists(inspector, "image_generation_attempts", "ix_image_generation_attempts_project_id"):
        op.drop_index("ix_image_generation_attempts_project_id", table_name="image_generation_attempts")

    if _column_exists(inspector, "image_generation_attempts", "project_id"):
        if dialect == "sqlite":
            with op.batch_alter_table("image_generation_attempts") as batch:
                batch.drop_column("project_id")
        else:
            op.drop_column("image_generation_attempts", "project_id")

    # project_media_assets
    if _table_exists(inspector, "project_media_assets"):
        op.drop_table("project_media_assets")
