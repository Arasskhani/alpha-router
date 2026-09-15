"""Run versioned Alembic migrations without blocking the application event loop."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

logger = logging.getLogger(__name__)


def _alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    ini_path = backend_root / "alembic.ini"
    if not ini_path.is_file():
        raise RuntimeError(f"Alembic configuration is missing: {ini_path}")
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return config


def upgrade_schema_sync(revision: str = "head") -> None:
    command.upgrade(_alembic_config(), revision)
