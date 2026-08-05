# Legacy-brand scan allowlist

Stage 9 uses a case-insensitive current-tree scan. Every remaining match that is
not part of the canonical `Alpha Router` naming matrix must be one of the
entries below.

## Explicit stale-configuration rejection

The following literals occur only in
`backend/app/legacy_brand_denylist.py` and in this allowlist. They are rejected
by the production startup guard; they are not accepted aliases, migration
inputs, generated identifiers, or current product names.

- `alpha_session` — stale session-cookie configuration.
- `alpha_csrf` — stale CSRF-cookie configuration.
- `sk-alpha-master` — stale gateway master-key default.
- `alpha` — stale database/object-storage development identity.
- `postgresql+asyncpg://alpha:changeme@postgres:5432/alpha` — stale direct
  database URL.
- `postgresql+asyncpg://alpha:changeme@pgbouncer:6432/alpha` — stale pooled
  database URL.

The denylist behavior is covered by
`backend/tests/test_legacy_brand_denylist.py` without copying these literals
into the test.

## External provider syntax

- `:nitro` in `backend/app/services/openrouter_image_service.py` and
  `backend/tests/test_image_generation_capabilities.py` is an OpenRouter routing
  suffix. It is provider-owned syntax and is not product branding.

## General terminology

- `alpha channel` in `docs/alpha-router-global-rename-plan.md` is the graphics
  concept used as the false-positive example.
- `alpha` in `frontend/dist/assets/index-*.js` is generated React DOM metadata
  for the standard SVG `alpha` attribute. Its source is third-party dependency
  code; it is not a product identifier.

No compatibility parser, data/storage migration, old export marker, old
filename stem, old fixture identity, or old project-owned filename is
allowlisted.
