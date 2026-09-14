"""Legacy product literals retained solely to reject stale production config.

These values are not supported identities or migration aliases.  They remain
centralized here because silently accepting an old cookie, master key, database
URL, or infrastructure username can make a renamed deployment authenticate
against the wrong boundary.
"""

LEGACY_SESSION_COOKIE_NAMES = frozenset({"alpha_session"})
LEGACY_CSRF_COOKIE_NAMES = frozenset({"alpha_csrf"})
LEGACY_GATEWAY_MASTER_KEYS = frozenset({"sk-alpha-master"})
LEGACY_INFRASTRUCTURE_IDENTITIES = frozenset({"alpha"})
LEGACY_DATABASE_URLS = frozenset(
    {
        "postgresql+asyncpg://alpha:changeme@postgres:5432/alpha",
        "postgresql+asyncpg://alpha:changeme@pgbouncer:6432/alpha",
    }
)

LEGACY_INSECURE_DEFAULTS = LEGACY_GATEWAY_MASTER_KEYS | LEGACY_INFRASTRUCTURE_IDENTITIES
