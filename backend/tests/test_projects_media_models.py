"""Step 1 tests: project media models and migration correctness."""

import datetime
import sqlite3
import uuid
from pathlib import Path

import app.models  # noqa: F401
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.database import Base
from app.models.project import ProjectMediaAsset
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _alembic_head() -> str:
    """Current head, so adding a revision does not break this gate."""
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def test_project_media_asset_columns():
    cols = {c.name for c in ProjectMediaAsset.__table__.columns}
    assert cols == {
        "id",
        "project_id",
        "uploaded_by_user_id",
        "kind",
        "mime_type",
        "file_name",
        "storage_path",
        "content_hash",
        "size_bytes",
        "source_model",
        "source_prompt",
        "chat_session_id",
        "metadata_json",
        "created_at",
        "expires_at",
    }


def test_project_media_fk_cascade_on_project():
    fks = {fk.ondelete for fk in ProjectMediaAsset.__table__.foreign_keys}
    assert "CASCADE" in fks


def test_project_media_fk_set_null_on_user():
    fks = {fk.ondelete for fk in ProjectMediaAsset.__table__.foreign_keys}
    assert "SET NULL" in fks


def test_image_generation_attempt_has_project_id():
    from app.models.logging import ImageGenerationAttempt

    cols = {c.name for c in ImageGenerationAttempt.__table__.columns}
    assert "project_id" in cols


def test_video_generation_job_has_project_id():
    from app.models.video import VideoGenerationJob

    cols = {c.name for c in VideoGenerationJob.__table__.columns}
    assert "project_id" in cols


def test_project_media_registered_in_metadata():
    assert "project_media_assets" in {t.name for t in Base.metadata.sorted_tables}


def test_project_media_in_schema_registry():
    from app.schema_registry import AGENT_PLATFORM_TABLE_NAMES

    assert "project_media_assets" in AGENT_PLATFORM_TABLE_NAMES


def test_migration_idempotent_and_creates_table():
    import os
    import subprocess
    import sys

    database_path = Path(__file__).resolve().parent / f".step1-{uuid.uuid4().hex}.sqlite"
    try:
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.as_posix()}"
        env.pop("ALEMBIC_AGENT_PLATFORM_ONLY", None)
        backend_root = Path(__file__).resolve().parents[1]
        # Run twice to verify idempotency
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "app.migrate"],
                cwd=backend_root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )

        conn = sqlite3.connect(database_path)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()

            assert revision == (_alembic_head(),)
            assert "project_media_assets" in tables

            # Verify project_id columns exist on image/video tables
            img_cols = {row[1] for row in conn.execute("PRAGMA table_info(image_generation_attempts)")}
            assert "project_id" in img_cols

            vid_cols = {row[1] for row in conn.execute("PRAGMA table_info(video_generation_jobs)")}
            assert "project_id" in vid_cols

            # Verify project_media_assets has a unique constraint on (project_id, content_hash)
            # SQLite names inline UNIQUE constraints as sqlite_autoindex_<table>_<n>.
            index_rows = list(conn.execute("PRAGMA index_list(project_media_assets)"))
            has_unique = any(
                row[2] == 1  # unique flag
                and row[3] == "u"  # origin: u = created by UNIQUE constraint
                for row in index_rows
            )
            assert has_unique, f"expected a UNIQUE constraint, got {index_rows}"
        finally:
            conn.close()
    finally:
        database_path.unlink(missing_ok=True)


def test_project_media_asset_can_be_created():
    import asyncio

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as db:
                asset = ProjectMediaAsset(
                    project_id="proj-test-1",
                    uploaded_by_user_id=None,
                    kind="image",
                    mime_type="image/png",
                    file_name="test.png",
                    storage_path="cdn/p/proj-test-1/test.png",
                    content_hash="abc123",
                    size_bytes=1024,
                    created_at=datetime.datetime.utcnow(),
                )
                db.add(asset)
                await db.flush()
                assert asset.id is not None
                assert asset.project_id == "proj-test-1"
        finally:
            await engine.dispose()

    asyncio.run(run())
