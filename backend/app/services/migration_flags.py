"""One-time migration completion flags in system_settings."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemSetting

COMPLETED_VALUES = frozenset({"1", "true", "yes", "done"})

BRANDING_MIGRATION_KEY = "branding_migration_completed"
MEDIA_DEDUPE_MIGRATION_KEY = "media_dedupe_migration_completed"
PRICING_SANITY_MIGRATION_KEY = "pricing_sanity_migration_completed"
LEGACY_BLOB_STORAGE_KEY = "legacy_blob_storage_completed"
RBAC_MIGRATION_KEY = "rbac_migration_completed"
USER_ROLES_MIGRATION_KEY = "user_roles_migration_completed"
RBAC_MENU_MIGRATION_KEY = "rbac_menu_migration_completed"
DELETED_USERS_SCHEMA_KEY = "deleted_users_schema_migration_completed"
RBAC_REMOVED_ROLES_MIGRATION_KEY = "rbac_removed_roles_migration_completed"
RBAC_REMOVED_ROLES_V2_MIGRATION_KEY = "rbac_removed_roles_v2_migration_completed"
RBAC_REMOVED_ROLES_V3_MIGRATION_KEY = "rbac_removed_roles_v3_storage_migration_completed"
USER_BUDGET_PLAN_SYNC_KEY = "user_budget_plan_sync_v1"
CHAT_NORMALIZED_STORAGE_KEY = "chat_normalized_storage_v1"
CHAT_PERFORMANCE_MIGRATION_KEY = "chat_performance_indexes_v1"
SECRET_AT_REST_ENCRYPTION_KEY = "secret_at_rest_encryption_v1"


def value_is_migration_completed(value: str | None) -> bool:
    return bool(value and value.strip().lower() in COMPLETED_VALUES)


async def is_migration_completed(db: AsyncSession, key: str) -> bool:
    row = await db.get(SystemSetting, key)
    return value_is_migration_completed(row.value if row else None)


async def mark_migration_completed(db: AsyncSession, key: str) -> None:
    row = await db.get(SystemSetting, key)
    if row:
        row.value = "true"
    else:
        db.add(SystemSetting(key=key, value="true"))
    await db.flush()


def is_migration_completed_sync(connection, key: str) -> bool:
    insp = inspect(connection)
    if "system_settings" not in insp.get_table_names():
        return False
    row = connection.execute(
        text("SELECT value FROM system_settings WHERE key = :key"),
        {"key": key},
    ).first()
    if not row:
        return False
    return value_is_migration_completed(row[0])


def mark_migration_completed_sync(connection, key: str) -> None:
    dialect = connection.dialect.name
    if dialect == "postgresql":
        connection.execute(
            text(
                """
                INSERT INTO system_settings (key, value) VALUES (:key, 'true')
                ON CONFLICT (key) DO UPDATE SET value = 'true'
                """
            ),
            {"key": key},
        )
    else:
        connection.execute(
            text("INSERT OR REPLACE INTO system_settings (key, value) VALUES (:key, 'true')"),
            {"key": key},
        )
