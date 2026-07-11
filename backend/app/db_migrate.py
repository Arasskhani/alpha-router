"""Lightweight schema patches for existing databases (PostgreSQL production, SQLite tests)."""

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex

from app.config import get_settings
from app.database import Base, engine
from app.services.migration_flags import (
    BRANDING_MIGRATION_KEY,
    DELETED_USERS_SCHEMA_KEY,
    MEDIA_DEDUPE_MIGRATION_KEY,
    PRICING_SANITY_MIGRATION_KEY,
    RBAC_MIGRATION_KEY,
    SECRET_AT_REST_ENCRYPTION_KEY,
    USER_ROLES_MIGRATION_KEY,
    USER_BUDGET_PLAN_SYNC_KEY,
    is_migration_completed_sync,
    mark_migration_completed_sync,
)


def _sqlite_column_ddl(col, dialect) -> str:
    """Build ADD COLUMN fragment for SQLite (new columns must be nullable)."""
    compiled = col.type.compile(dialect=dialect)
    return f"{col.name} {compiled}"


def _ensure_missing_indexes(connection, table, insp) -> None:
    """Create ORM indexes absent from an existing table (e.g. after ADD COLUMN patch)."""
    existing = {idx["name"] for idx in insp.get_indexes(table.name) if idx.get("name")}
    for index in table.indexes:
        if not index.name or index.name in existing:
            continue
        connection.execute(CreateIndex(index))


async def apply_schema_column_patches() -> None:
    """Add ORM columns/indexes missing from existing tables (PostgreSQL, SQLite, etc.)."""
    async with engine.begin() as conn:

        def patch(connection) -> None:
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            for table in Base.metadata.sorted_tables:
                if table.name not in tables:
                    continue
                existing = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in existing:
                        continue
                    # Nullable-only ADD COLUMN: required for SQLite; safe on PostgreSQL upgrades.
                    ddl = col.type.compile(dialect=connection.dialect)
                    connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}"))
                _ensure_missing_indexes(connection, table, insp)

        await conn.run_sync(patch)


async def apply_sqlite_schema_patches() -> None:
    settings = get_settings()
    if "sqlite" not in settings.database_url:
        return

    await apply_schema_column_patches()


async def apply_deleted_users_schema_migrations() -> None:
    """Ensure users.deleted_at exists (legacy flag; column patch is idempotent)."""
    from app.models.user import User

    async with engine.begin() as conn:

        def migrate(connection) -> None:
            insp = inspect(connection)
            if "users" not in insp.get_table_names():
                return
            existing = {c["name"] for c in insp.get_columns("users")}
            if "deleted_at" not in existing:
                col = User.__table__.c.deleted_at
                ddl = col.type.compile(dialect=connection.dialect)
                connection.execute(text(f"ALTER TABLE users ADD COLUMN deleted_at {ddl}"))
            if not is_migration_completed_sync(connection, DELETED_USERS_SCHEMA_KEY):
                mark_migration_completed_sync(connection, DELETED_USERS_SCHEMA_KEY)

        await conn.run_sync(migrate)


async def apply_branding_migrations() -> None:
    """Rename legacy tables/values to NITRO (once)."""
    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, BRANDING_MIGRATION_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            if "billi_api_keys" in tables and "nitro_api_keys" not in tables:
                connection.execute(text("ALTER TABLE billi_api_keys RENAME TO nitro_api_keys"))
            if "request_logs" in tables:
                connection.execute(
                    text("UPDATE request_logs SET source = 'nitro_key' WHERE source = 'billi_key'")
                )
                connection.execute(
                    text("UPDATE request_logs SET source = 'nitro_chat' WHERE source = 'billi_chat'")
                )
                connection.execute(
                    text(
                        "UPDATE request_logs SET user_id = NULL WHERE nitro_api_key_id IS NOT NULL"
                    )
                )
                if "nitro_api_keys" in tables:
                    connection.execute(
                        text(
                            """
                            UPDATE request_logs
                            SET username = (
                                SELECT name FROM nitro_api_keys
                                WHERE nitro_api_keys.id = request_logs.nitro_api_key_id
                            )
                            WHERE nitro_api_key_id IS NOT NULL
                            AND (
                                username IS NULL
                                OR username = ''
                                OR lower(username) = 'anonymous@local'
                            )
                            """
                        )
                    )
            if "users" in tables and "request_logs" in tables:
                connection.execute(
                    text(
                        """
                        UPDATE request_logs
                        SET user_id = NULL
                        WHERE user_id IN (
                            SELECT id FROM users
                            WHERE auth_provider = 'openwebui'
                            AND lower(username) = 'anonymous@local'
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        DELETE FROM users
                        WHERE auth_provider = 'openwebui'
                        AND lower(username) = 'anonymous@local'
                        AND id NOT IN (
                            SELECT user_id FROM user_api_keys WHERE user_id IS NOT NULL
                        )
                        AND id NOT IN (
                            SELECT owner_user_id FROM nitro_api_keys
                            WHERE owner_user_id IS NOT NULL
                        )
                        """
                    )
                )
            mark_migration_completed_sync(connection, BRANDING_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_media_dedupe_migrations() -> None:
    """Remove duplicate media rows and enforce one asset per user + content hash (once)."""
    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, MEDIA_DEDUPE_MIGRATION_KEY):
                return
            insp = inspect(connection)
            if "media_assets" not in insp.get_table_names():
                return

            connection.execute(
                text(
                    """
                    DELETE FROM media_assets
                    WHERE content_hash IS NOT NULL
                      AND content_hash != ''
                      AND id NOT IN (
                          SELECT MAX(id)
                          FROM media_assets
                          WHERE content_hash IS NOT NULL
                            AND content_hash != ''
                          GROUP BY user_id, content_hash
                      )
                    """
                )
            )

            indexes = {idx["name"] for idx in insp.get_indexes("media_assets")}
            if "ux_media_assets_user_content_hash" not in indexes:
                dialect = connection.dialect.name
                if dialect == "sqlite":
                    connection.execute(
                        text(
                            """
                            CREATE UNIQUE INDEX ux_media_assets_user_content_hash
                            ON media_assets (user_id, content_hash)
                            WHERE content_hash IS NOT NULL AND content_hash != ''
                            """
                        )
                    )
                elif dialect == "postgresql":
                    connection.execute(
                        text(
                            """
                            CREATE UNIQUE INDEX ux_media_assets_user_content_hash
                            ON media_assets (user_id, content_hash)
                            WHERE content_hash IS NOT NULL AND content_hash != ''
                            """
                        )
                    )
            mark_migration_completed_sync(connection, MEDIA_DEDUPE_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_pricing_sanity_migrations() -> None:
    """Fix negative OpenRouter sentinel pricing and corrupted request log costs (once)."""
    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, PRICING_SANITY_MIGRATION_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            if "ai_models" in tables:
                connection.execute(
                    text("UPDATE ai_models SET input_cost_per_1k = NULL WHERE input_cost_per_1k < 0")
                )
                connection.execute(
                    text("UPDATE ai_models SET output_cost_per_1k = NULL WHERE output_cost_per_1k < 0")
                )
            if "ai_models" in tables and "request_logs" in tables:
                dialect = connection.dialect.name
                if dialect == "postgresql":
                    recalc_sql = """
                        UPDATE request_logs
                        SET total_cost_usd =
                            (COALESCE(prompt_tokens, 0) / 1000.0) * ai_models.input_cost_per_1k
                            + (COALESCE(completion_tokens, 0) / 1000.0) * ai_models.output_cost_per_1k
                        FROM ai_models
                        WHERE request_logs.total_cost_usd < 0
                          AND ai_models.external_id = request_logs.model_id
                          AND ai_models.input_cost_per_1k >= 0
                          AND ai_models.output_cost_per_1k >= 0
                    """
                else:
                    recalc_sql = """
                        UPDATE request_logs
                        SET total_cost_usd = (
                            SELECT
                                (COALESCE(request_logs.prompt_tokens, 0) / 1000.0) * ai_models.input_cost_per_1k
                                + (COALESCE(request_logs.completion_tokens, 0) / 1000.0) * ai_models.output_cost_per_1k
                            FROM ai_models
                            WHERE ai_models.external_id = request_logs.model_id
                              AND ai_models.input_cost_per_1k >= 0
                              AND ai_models.output_cost_per_1k >= 0
                        )
                        WHERE request_logs.total_cost_usd < 0
                          AND EXISTS (
                            SELECT 1 FROM ai_models
                            WHERE ai_models.external_id = request_logs.model_id
                              AND ai_models.input_cost_per_1k >= 0
                              AND ai_models.output_cost_per_1k >= 0
                          )
                    """
                connection.execute(text(recalc_sql))
            if "request_logs" in tables:
                connection.execute(
                    text("UPDATE request_logs SET total_cost_usd = 0 WHERE total_cost_usd < 0")
                )
            mark_migration_completed_sync(connection, PRICING_SANITY_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_rbac_migrations() -> None:
    """Migrate legacy admin role to full_administrator (once)."""
    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, RBAC_MIGRATION_KEY):
                return
            insp = inspect(connection)
            if "users" not in insp.get_table_names():
                return
            connection.execute(
                text("UPDATE users SET role = 'full_administrator' WHERE lower(role) = 'admin'")
            )
            mark_migration_completed_sync(connection, RBAC_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_user_roles_migrations() -> None:
    """Backfill user_role_assignments from users.role (once)."""
    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, USER_ROLES_MIGRATION_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            if "users" not in tables:
                return
            if "user_role_assignments" not in tables:
                if connection.dialect.name == "postgresql":
                    connection.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS user_role_assignments (
                                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                                role_slug VARCHAR(64) NOT NULL,
                                PRIMARY KEY (user_id, role_slug)
                            )
                            """
                        )
                    )
                else:
                    connection.execute(
                        text(
                            """
                            CREATE TABLE user_role_assignments (
                                user_id INTEGER NOT NULL,
                                role_slug VARCHAR(64) NOT NULL,
                                PRIMARY KEY (user_id, role_slug),
                                FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
                            )
                            """
                        )
                    )
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text(
                        """
                        INSERT INTO user_role_assignments (user_id, role_slug)
                        SELECT id, role FROM users
                        WHERE role IS NOT NULL AND trim(role) != ''
                        ON CONFLICT DO NOTHING
                        """
                    )
                )
            else:
                connection.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO user_role_assignments (user_id, role_slug)
                        SELECT id, role FROM users
                        WHERE role IS NOT NULL AND trim(role) != ''
                        """
                    )
                )
            connection.execute(
                text(
                    """
                    UPDATE users SET role = 'full_administrator'
                    WHERE lower(role) = 'admin'
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE user_role_assignments SET role_slug = 'full_administrator'
                    WHERE lower(role_slug) = 'admin'
                    """
                )
            )
            mark_migration_completed_sync(connection, USER_ROLES_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_rbac_menu_migrations() -> None:
    """Remap legacy section-scoped roles to per-menu roles; rename global read-only role."""
    from app.services.rbac import (
        FULL_ADMIN_SLUG,
        READ_ONLY_FULL_ADMIN_SLUG,
        expand_legacy_role_slug,
        primary_role_slug,
    )
    from app.services.migration_flags import RBAC_MENU_MIGRATION_KEY

    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, RBAC_MENU_MIGRATION_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            if "users" not in tables:
                return

            if "user_role_assignments" in tables:
                rows = connection.execute(
                    text("SELECT user_id, role_slug FROM user_role_assignments")
                ).fetchall()
                by_user: dict[int, set[str]] = {}
                for uid, slug in rows:
                    if uid is None:
                        continue
                    for mapped in expand_legacy_role_slug(str(slug)):
                        by_user.setdefault(int(uid), set()).add(mapped)
                connection.execute(text("DELETE FROM user_role_assignments"))
                for uid, slugs in by_user.items():
                    for slug in sorted(slugs):
                        if connection.dialect.name == "postgresql":
                            connection.execute(
                                text(
                                    """
                                    INSERT INTO user_role_assignments (user_id, role_slug)
                                    VALUES (:uid, :slug)
                                    ON CONFLICT DO NOTHING
                                    """
                                ),
                                {"uid": uid, "slug": slug},
                            )
                        else:
                            connection.execute(
                                text(
                                    """
                                    INSERT OR IGNORE INTO user_role_assignments (user_id, role_slug)
                                    VALUES (:uid, :slug)
                                    """
                                ),
                                {"uid": uid, "slug": slug},
                            )

            connection.execute(
                text(
                    """
                    UPDATE users SET role = :full
                    WHERE lower(role) IN ('admin', 'full_administrator')
                    """
                ),
                {"full": FULL_ADMIN_SLUG},
            )
            connection.execute(
                text(
                    """
                    UPDATE users SET role = :read_full
                    WHERE lower(role) = 'read_only_administrator'
                    """
                ),
                {"read_full": READ_ONLY_FULL_ADMIN_SLUG},
            )
            connection.execute(
                text(
                    """
                    UPDATE user_role_assignments SET role_slug = :read_full
                    WHERE lower(role_slug) = 'read_only_administrator'
                    """
                ),
                {"read_full": READ_ONLY_FULL_ADMIN_SLUG},
            )

            if "user_role_assignments" in tables:
                user_rows = connection.execute(text("SELECT id, role FROM users")).fetchall()
                for uid, role in user_rows:
                    if uid is None:
                        continue
                    slugs = connection.execute(
                        text(
                            "SELECT role_slug FROM user_role_assignments WHERE user_id = :uid ORDER BY role_slug"
                        ),
                        {"uid": int(uid)},
                    ).fetchall()
                    if slugs:
                        primary = primary_role_slug([str(s[0]) for s in slugs])
                    else:
                        expanded = expand_legacy_role_slug(str(role or "user"))
                        primary = primary_role_slug(expanded or ["user"])
                    connection.execute(
                        text("UPDATE users SET role = :role WHERE id = :uid"),
                        {"role": primary, "uid": int(uid)},
                    )

            mark_migration_completed_sync(connection, RBAC_MENU_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_user_budget_plan_sync(db) -> None:
    """Recalculate cached user.monthly_budget_usd from plan assignments (not legacy defaults)."""
    from sqlalchemy import select

    from app.models.user import User
    from app.services.budget_service import resolve_monthly_budget
    from app.services.migration_flags import (
        is_migration_completed,
        mark_migration_completed,
    )

    if await is_migration_completed(db, USER_BUDGET_PLAN_SYNC_KEY):
        return

    users = (await db.execute(select(User))).scalars().all()
    for user in users:
        user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await mark_migration_completed(db, USER_BUDGET_PLAN_SYNC_KEY)
    await db.flush()


async def apply_rbac_removed_roles_migration() -> None:
    """Drop removed RBAC slugs; expand legacy global admins to per-menu full roles."""
    from app.services.migration_flags import RBAC_REMOVED_ROLES_MIGRATION_KEY
    from app.services.rbac import expand_legacy_role_slug, primary_role_slug

    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, RBAC_REMOVED_ROLES_MIGRATION_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            if "users" not in tables or "user_role_assignments" not in tables:
                return

            rows = connection.execute(
                text("SELECT user_id, role_slug FROM user_role_assignments")
            ).fetchall()
            by_user: dict[int, set[str]] = {}
            for uid, slug in rows:
                if uid is None:
                    continue
                for mapped in expand_legacy_role_slug(str(slug)):
                    by_user.setdefault(int(uid), set()).add(mapped)
            connection.execute(text("DELETE FROM user_role_assignments"))
            for uid, slugs in by_user.items():
                for slug in sorted(slugs):
                    if connection.dialect.name == "postgresql":
                        connection.execute(
                            text(
                                """
                                INSERT INTO user_role_assignments (user_id, role_slug)
                                VALUES (:uid, :slug)
                                ON CONFLICT DO NOTHING
                                """
                            ),
                            {"uid": uid, "slug": slug},
                        )
                    else:
                        connection.execute(
                            text(
                                """
                                INSERT OR IGNORE INTO user_role_assignments (user_id, role_slug)
                                VALUES (:uid, :slug)
                                """
                            ),
                            {"uid": uid, "slug": slug},
                        )

            user_rows = connection.execute(text("SELECT id, role FROM users")).fetchall()
            for uid, role in user_rows:
                if uid is None:
                    continue
                slugs = connection.execute(
                    text(
                        "SELECT role_slug FROM user_role_assignments WHERE user_id = :uid ORDER BY role_slug"
                    ),
                    {"uid": int(uid)},
                ).fetchall()
                if slugs:
                    primary = primary_role_slug([str(s[0]) for s in slugs])
                else:
                    expanded = expand_legacy_role_slug(str(role or "user"))
                    primary = primary_role_slug(expanded or ["user"])
                connection.execute(
                    text("UPDATE users SET role = :role WHERE id = :uid"),
                    {"role": primary, "uid": int(uid)},
                )

            mark_migration_completed_sync(connection, RBAC_REMOVED_ROLES_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_rbac_removed_roles_v2_migration() -> None:
    """Drop second batch of removed RBAC slugs; re-expand legacy assignments."""
    from app.services.migration_flags import RBAC_REMOVED_ROLES_V2_MIGRATION_KEY
    from app.services.rbac import expand_legacy_role_slug, primary_role_slug

    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, RBAC_REMOVED_ROLES_V2_MIGRATION_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            if "users" not in tables or "user_role_assignments" not in tables:
                return

            rows = connection.execute(
                text("SELECT user_id, role_slug FROM user_role_assignments")
            ).fetchall()
            by_user: dict[int, set[str]] = {}
            for uid, slug in rows:
                if uid is None:
                    continue
                for mapped in expand_legacy_role_slug(str(slug)):
                    by_user.setdefault(int(uid), set()).add(mapped)
            connection.execute(text("DELETE FROM user_role_assignments"))
            for uid, slugs in by_user.items():
                for slug in sorted(slugs):
                    if connection.dialect.name == "postgresql":
                        connection.execute(
                            text(
                                """
                                INSERT INTO user_role_assignments (user_id, role_slug)
                                VALUES (:uid, :slug)
                                ON CONFLICT DO NOTHING
                                """
                            ),
                            {"uid": uid, "slug": slug},
                        )
                    else:
                        connection.execute(
                            text(
                                """
                                INSERT OR IGNORE INTO user_role_assignments (user_id, role_slug)
                                VALUES (:uid, :slug)
                                """
                            ),
                            {"uid": uid, "slug": slug},
                        )

            user_rows = connection.execute(text("SELECT id, role FROM users")).fetchall()
            for uid, role in user_rows:
                if uid is None:
                    continue
                slugs = connection.execute(
                    text(
                        "SELECT role_slug FROM user_role_assignments WHERE user_id = :uid ORDER BY role_slug"
                    ),
                    {"uid": int(uid)},
                ).fetchall()
                if slugs:
                    primary = primary_role_slug([str(s[0]) for s in slugs])
                else:
                    expanded = expand_legacy_role_slug(str(role or "user"))
                    primary = primary_role_slug(expanded or ["user"])
                connection.execute(
                    text("UPDATE users SET role = :role WHERE id = :uid"),
                    {"role": primary, "uid": int(uid)},
                )

            mark_migration_completed_sync(connection, RBAC_REMOVED_ROLES_V2_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_rbac_removed_roles_v3_migration() -> None:
    """Drop Storage per-menu roles; remap user_role_assignments."""
    from app.services.migration_flags import RBAC_REMOVED_ROLES_V3_MIGRATION_KEY
    from app.services.rbac import expand_legacy_role_slug, primary_role_slug

    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, RBAC_REMOVED_ROLES_V3_MIGRATION_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            if "users" not in tables or "user_role_assignments" not in tables:
                return

            rows = connection.execute(
                text("SELECT user_id, role_slug FROM user_role_assignments")
            ).fetchall()
            by_user: dict[int, set[str]] = {}
            for uid, slug in rows:
                if uid is None:
                    continue
                for mapped in expand_legacy_role_slug(str(slug)):
                    by_user.setdefault(int(uid), set()).add(mapped)
            connection.execute(text("DELETE FROM user_role_assignments"))
            for uid, slugs in by_user.items():
                for slug in sorted(slugs):
                    if connection.dialect.name == "postgresql":
                        connection.execute(
                            text(
                                """
                                INSERT INTO user_role_assignments (user_id, role_slug)
                                VALUES (:uid, :slug)
                                ON CONFLICT DO NOTHING
                                """
                            ),
                            {"uid": uid, "slug": slug},
                        )
                    else:
                        connection.execute(
                            text(
                                """
                                INSERT OR IGNORE INTO user_role_assignments (user_id, role_slug)
                                VALUES (:uid, :slug)
                                """
                            ),
                            {"uid": uid, "slug": slug},
                        )

            user_rows = connection.execute(text("SELECT id, role FROM users")).fetchall()
            for uid, role in user_rows:
                if uid is None:
                    continue
                slugs = connection.execute(
                    text(
                        "SELECT role_slug FROM user_role_assignments WHERE user_id = :uid ORDER BY role_slug"
                    ),
                    {"uid": int(uid)},
                ).fetchall()
                if slugs:
                    primary = primary_role_slug([str(s[0]) for s in slugs])
                else:
                    expanded = expand_legacy_role_slug(str(role or "user"))
                    primary = primary_role_slug(expanded or ["user"])
                connection.execute(
                    text("UPDATE users SET role = :role WHERE id = :uid"),
                    {"role": primary, "uid": int(uid)},
                )

            mark_migration_completed_sync(connection, RBAC_REMOVED_ROLES_V3_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_chat_normalized_storage_migrations() -> None:
    """Wipe legacy JSONB chat blobs; create normalized tables; migrate prefs only."""
    from app.services.migration_flags import CHAT_NORMALIZED_STORAGE_KEY

    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, CHAT_NORMALIZED_STORAGE_KEY):
                return
            insp = inspect(connection)
            tables = set(insp.get_table_names())
            dialect = connection.dialect.name

            if "user_chat_stores" in tables:
                cols = {c["name"] for c in insp.get_columns("user_chat_stores")}
                if "user_chat_prefs" in tables and "prefs" in cols:
                    if dialect == "postgresql":
                        connection.execute(
                            text(
                                """
                                INSERT INTO user_chat_prefs (user_id, prefs, updated_at)
                                SELECT user_id, prefs, COALESCE(updated_at, NOW())
                                FROM user_chat_stores
                                WHERE prefs IS NOT NULL
                                ON CONFLICT (user_id) DO NOTHING
                                """
                            )
                        )
                    else:
                        connection.execute(
                            text(
                                """
                                INSERT OR IGNORE INTO user_chat_prefs (user_id, prefs, updated_at)
                                SELECT user_id, prefs, COALESCE(updated_at, CURRENT_TIMESTAMP)
                                FROM user_chat_stores
                                WHERE prefs IS NOT NULL
                                """
                            )
                        )
                connection.execute(text("DELETE FROM user_chat_stores"))
                for col in ("sessions", "folders", "prefs"):
                    if col in cols:
                        try:
                            connection.execute(text(f"ALTER TABLE user_chat_stores DROP COLUMN {col}"))
                        except Exception:
                            pass
                connection.execute(text("DROP TABLE IF EXISTS user_chat_stores"))

            mark_migration_completed_sync(connection, CHAT_NORMALIZED_STORAGE_KEY)

        await conn.run_sync(migrate)


        await conn.run_sync(migrate)


async def apply_chat_performance_migrations() -> None:
    """GIN/trgm title index and message full-text index (PostgreSQL); idempotent."""
    from app.services.migration_flags import CHAT_PERFORMANCE_MIGRATION_KEY

    async with engine.begin() as conn:

        def migrate(connection) -> None:
            if is_migration_completed_sync(connection, CHAT_PERFORMANCE_MIGRATION_KEY):
                return
            dialect = connection.dialect.name
            if dialect == "postgresql":
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                indexes = {
                    idx["name"]
                    for idx in inspect(connection).get_indexes("chat_sessions")
                    if idx.get("name")
                }
                if "ix_chat_sessions_title_trgm" not in indexes:
                    connection.execute(
                        text(
                            """
                            CREATE INDEX ix_chat_sessions_title_trgm
                            ON chat_sessions USING gin (title gin_trgm_ops)
                            """
                        )
                    )
                msg_indexes = {
                    idx["name"]
                    for idx in inspect(connection).get_indexes("chat_messages")
                    if idx.get("name")
                }
                if "ix_chat_messages_content_fts" not in msg_indexes:
                    connection.execute(
                        text(
                            """
                            CREATE INDEX ix_chat_messages_content_fts
                            ON chat_messages USING gin (
                                to_tsvector('simple', coalesce(content, ''))
                            )
                            """
                        )
                    )
            mark_migration_completed_sync(connection, CHAT_PERFORMANCE_MIGRATION_KEY)

        await conn.run_sync(migrate)


async def apply_secret_at_rest_encryption(db) -> None:
    """One-time: encrypt plaintext secrets already stored in the database.

    Phase 3 introduced Fernet encryption for connection API keys, SMTP
    passwords, and LDAP/Keycloak credentials in ``auth_providers.config_json``.
    Existing rows written before this phase hold plaintext in the ``*_encrypted``
    columns. This migration rewrites them as ciphertext in place.

    Idempotent: ``encrypt_secret`` skips values that already look like
    ciphertext, so a partial run that crashed mid-table can be re-run safely,
    and re-running after completion is a no-op. Guarded by a completion flag so
    the per-row scan only happens once.
    """
    from app.services.auth_config import _SENSITIVE_FIELDS
    from app.services.migration_flags import is_migration_completed, mark_migration_completed
    from app.services.secret_crypto import encrypt_secret, is_encrypted

    if await is_migration_completed(db, SECRET_AT_REST_ENCRYPTION_KEY):
        return

    # connections.api_key_encrypted
    from app.models.connection import Connection

    conns = (await db.execute(text("SELECT id, api_key_encrypted FROM connections"))).all()
    for row in conns:
        cid, val = row[0], row[1]
        if val and not is_encrypted(val):
            await db.execute(
                text("UPDATE connections SET api_key_encrypted = :v WHERE id = :id"),
                {"v": encrypt_secret(val), "id": cid},
            )

    # smtp_settings.password_encrypted
    try:
        smtp_rows = (await db.execute(text("SELECT id, password_encrypted FROM smtp_settings"))).all()
    except Exception:
        smtp_rows = []
    for row in smtp_rows:
        sid, val = row[0], row[1]
        if val and not is_encrypted(val):
            await db.execute(
                text("UPDATE smtp_settings SET password_encrypted = :v WHERE id = :id"),
                {"v": encrypt_secret(val), "id": sid},
            )

    # auth_providers.config_json — encrypt the sensitive fields inside the JSON blob
    try:
        ap_rows = (await db.execute(text("SELECT provider, config_json FROM auth_providers"))).all()
    except Exception:
        ap_rows = []
    import json as _json

    for row in ap_rows:
        provider, raw = row[0], row[1]
        sensitive = _SENSITIVE_FIELDS.get(provider, set())
        if not sensitive or not raw:
            continue
        try:
            payload = _json.loads(raw)
        except Exception:
            continue
        changed = False
        for k in sensitive:
            v = payload.get(k)
            if v and not is_encrypted(v):
                payload[k] = encrypt_secret(v)
                changed = True
        if changed:
            await db.execute(
                text("UPDATE auth_providers SET config_json = :v WHERE provider = :p"),
                {"v": _json.dumps(payload), "p": provider},
            )

    await db.commit()
    await mark_migration_completed(db, SECRET_AT_REST_ENCRYPTION_KEY)


async def run_one_time_migrations(db) -> None:
    """Run all pending one-time data/storage migrations; no-op when already completed."""
    from app.services.storage_migration_service import (
        migrate_legacy_storage_layout,
        reconcile_media_storage_v3,
    )
    from app.services.storage_service import migrate_legacy_blob_storage

    await apply_deleted_users_schema_migrations()
    await apply_branding_migrations()
    await apply_rbac_migrations()
    await apply_user_roles_migrations()
    await apply_rbac_menu_migrations()
    await apply_rbac_removed_roles_migration()
    await apply_rbac_removed_roles_v2_migration()
    await apply_rbac_removed_roles_v3_migration()
    await apply_media_dedupe_migrations()
    await apply_pricing_sanity_migrations()
    await apply_chat_normalized_storage_migrations()
    await apply_chat_performance_migrations()
    await apply_user_budget_plan_sync(db)
    await apply_secret_at_rest_encryption(db)
    await migrate_legacy_blob_storage(db)
    await migrate_legacy_storage_layout(db)
    await reconcile_media_storage_v3(db)
