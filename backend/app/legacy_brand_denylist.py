"""Legacy product literals retained solely to reject stale production config.

These values are not supported identities or migration aliases.  They remain
centralized here because silently accepting an old cookie, master key, database
URL, or infrastructure username can make a renamed deployment authenticate
against the wrong boundary.  Keep this module in sync with
``docs/legacy-brand-allowlist.md``.
"""

LEGACY_SESSION_COOKIE_NAMES = frozenset({"alpha_router_session"})
LEGACY_CSRF_COOKIE_NAMES = frozenset({"alpha_router_csrf"})
LEGACY_GATEWAY_MASTER_KEYS = frozenset({"sk-alpha-router-master"})
LEGACY_INFRASTRUCTURE_IDENTITIES = frozenset({"alpha"})
LEGACY_DATABASE_URLS = frozenset(
    {
        "postgresql+asyncpg://alpha_router:changeme@postgres:5432/alpha_router",
        "postgresql+asyncpg://alpha_router:changeme@pgbouncer:6432/alpha_router",
    }
)

LEGACY_INSECURE_DEFAULTS = (
    LEGACY_GATEWAY_MASTER_KEYS | LEGACY_INFRASTRUCTURE_IDENTITIES
)
