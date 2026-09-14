#!/usr/bin/env bash
# Apply --dev or --prod settings to .env (called after bootstrap_env_file base steps).

DEPLOY_MODE="${DEPLOY_MODE:-dev}"

INSECURE_PLACEHOLDERS=(
  change-me-in-production
  admin
  changeme
  change-me-seaweed-admin
  change-me-qdrant-api-key
  sk-alpha-router-master
  alpha_router
  rustfsadmin
)

# FRONTEND_URL / API_PUBLIC_URL are deployment-specific: every site has its own
# hostname. These are the first-install defaults shipped in .env.example, i.e.
# the only values this script may replace. Anything else was set by the
# operator and must survive every upgrade -- overwriting it collapses
# allowed_origins() (backend/app/services/csrf_protection.py) down to loopback
# and every browser request from the real hostname then fails with
# "CSRF validation failed".
PUBLIC_URL_PLACEHOLDERS=(
  http://localhost:8080
  http://localhost:8000
  http://127.0.0.1:8080
  http://127.0.0.1:8000
)

is_public_url_placeholder() {
  local value="${1%/}"
  local item
  for item in "${PUBLIC_URL_PLACEHOLDERS[@]}"; do
    if [ "$value" = "$item" ]; then
      return 0
    fi
  done
  return 1
}

is_loopback_public_url() {
  case "${1:-}" in
    http://localhost | http://localhost:* | \
      http://127.0.0.1 | http://127.0.0.1:* | \
      https://localhost | https://localhost:* | \
      https://127.0.0.1 | https://127.0.0.1:* | \
      http://\[::1\] | http://\[::1\]:* | https://\[::1\] | https://\[::1\]:*)
      return 0
      ;;
  esac
  return 1
}

# Keep whatever the operator configured; only fill in a missing or
# still-default value. Mirrors ensure_secret below. Echoes the effective value.
preserve_env_var() {
  local key="$1"
  local default_value="$2"
  local current
  current="$(env_value "$key" || true)"

  if [ -z "$current" ] || is_public_url_placeholder "$current"; then
    set_env_var "$key" "$default_value"
    printf '%s' "$default_value"
    return 0
  fi
  # stdout carries the value back to the caller's $( ), so the notice goes to stderr.
  log "Keeping configured $key=$current" >&2
  printf '%s' "$current"
}

is_truthy() {
  case "${1:-}" in
    true | True | TRUE | 1) return 0 ;;
  esac
  return 1
}

# HSTS is not a free-standing preference: the production guard
# (_collect_production_insecurities in backend/app/main.py) flags "HSTS"
# whenever either public URL is non-loopback and ENABLE_HSTS is not true. So it
# has to follow whatever surface the URLs above ended up describing, or simply
# preserving those URLs would start failing the guard on every upgrade.
apply_hsts_for_surface() {
  local frontend="$1"
  local api_public="$2"
  local current
  current="$(env_value ENABLE_HSTS || true)"

  if is_loopback_public_url "$frontend" && is_loopback_public_url "$api_public"; then
    if [ -z "$current" ]; then
      set_env_var ENABLE_HSTS false
    fi
    return 0
  fi

  local url insecure_scheme=0
  for url in "$frontend" "$api_public"; do
    [ -n "$url" ] || continue
    if ! is_loopback_public_url "$url" && [ "${url#https://}" = "$url" ]; then
      insecure_scheme=1
    fi
  done

  if [ "$insecure_scheme" -eq 1 ]; then
    warn "FRONTEND_URL/API_PUBLIC_URL are publicly reachable but not HTTPS."
    warn "The production guard refuses this unless PRODUCTION_GUARD_MODE=warning."
    warn "Terminate TLS in front of Alpharouter and use https:// URLs."
    if [ -z "$current" ]; then
      set_env_var ENABLE_HSTS false
    fi
    return 0
  fi

  if ! is_truthy "$current"; then
    set_env_var ENABLE_HSTS true
    log "Public HTTPS surface configured; set ENABLE_HSTS=true (production guard requires it)."
  fi
}

is_insecure_value() {
  local value="$1"
  local item
  for item in "${INSECURE_PLACEHOLDERS[@]}"; do
    if [ "$value" = "$item" ]; then
      return 0
    fi
  done
  return 1
}

apply_deploy_mode() {
  case "$DEPLOY_MODE" in
    dev)
      apply_dev_mode
      ;;
    prod)
      apply_prod_mode
      ;;
    *)
      die "Unknown deploy mode: $DEPLOY_MODE (use --dev or --prod)."
      ;;
  esac
}

apply_dev_mode() {
  set_env_var ENVIRONMENT development
  log "Deploy mode: development"
}

apply_prod_mode() {
  log "Deploy mode: production (generating strong secrets where needed)..."

  set_env_var ENVIRONMENT production
  set_env_var OPENAPI_ADMIN_ONLY true

  local frontend_url api_public_url
  frontend_url="$(preserve_env_var FRONTEND_URL "http://127.0.0.1:8080")"
  api_public_url="$(preserve_env_var API_PUBLIC_URL "http://127.0.0.1:8080")"
  apply_hsts_for_surface "$frontend_url" "$api_public_url"

  ensure_secret SECRET_KEY "$(rand_hex 32)" "change-me-in-production"
  ensure_secret DATA_ENCRYPTION_KEY "$(rand_hex 32)" "change-me-in-production"
  ensure_secret ADMIN_PASSWORD "$(rand_hex 16)" "admin"
  ensure_secret SERVICE_ADMIN_PASSWORD "$(rand_hex 16)" "changeme"
  ensure_secret GATEWAY_MASTER_KEY "sk-alpharouter-$(rand_hex 24)" "sk-alpha-router-master"

  local pg_pass
  pg_pass="$(rotate_postgres_password)"
  sync_database_url_password "$pg_pass"

  ensure_secret REDIS_PASSWORD "$(rand_hex 24)" ""
  ensure_secret QDRANT_API_KEY "$(rand_hex 32)" "change-me-qdrant-api-key"
  ensure_secret S3_ACCESS_KEY "ar$(rand_hex 12)" "alpha_router"
  ensure_secret S3_SECRET_KEY "$(rand_hex 32)" "changeme"
  ensure_secret SEAWEEDFS_ADMIN_PASSWORD "$(rand_hex 24)" "change-me-seaweed-admin"

  local sandbox_token
  sandbox_token="$(env_value SANDBOX_BROKER_TOKEN || true)"
  if [ -z "$sandbox_token" ] || [ "${#sandbox_token}" -lt 32 ] || is_insecure_value "$sandbox_token"; then
    sandbox_token="$(rand_hex 32)"
    set_env_var SANDBOX_BROKER_TOKEN "$sandbox_token"
  fi
  set_env_var CODE_SANDBOX_BROKER_TOKEN "$sandbox_token"

  if [ -z "$(env_value METRICS_BEARER_TOKEN || true)" ]; then
    set_env_var METRICS_BEARER_TOKEN "$(rand_hex 32)"
  fi

  log "Production .env values applied (loopback HTTP URLs; use HTTPS URLs for public hosts)."
}

ensure_secret() {
  local key="$1"
  local new_value="$2"
  local insecure_placeholder="${3:-}"
  local current
  current="$(env_value "$key" || true)"

  if [ -z "$current" ] || [ "$current" = "$insecure_placeholder" ] || is_insecure_value "$current"; then
    set_env_var "$key" "$new_value"
    printf '%s' "$new_value"
    return 0
  fi
  printf '%s' "$current"
}

# POSTGRES_PASSWORD is the one secret that also lives *inside* a data volume:
# the role password in alpha_router_pg. ensure_secret alone would rewrite .env
# on a host installed with --dev (password "changeme") and later switched to
# --prod, leaving pgbouncer/db-init unable to authenticate against the existing
# cluster -- a full outage with no automatic way back. So: rotate .env only
# together with an ALTER ROLE on the running cluster, or when no cluster exists
# yet. Echoes the effective password; all diagnostics go to stderr.
rotate_postgres_password() {
  local current new user db
  current="$(env_value POSTGRES_PASSWORD || true)"
  if [ -n "$current" ] && [ "$current" != "changeme" ] && ! is_insecure_value "$current"; then
    printf '%s' "$current"
    return 0
  fi
  new="$(rand_hex 24)"
  if ! postgres_volume_exists; then
    # Fresh install: initdb will create the role with whatever .env says.
    set_env_var POSTGRES_PASSWORD "$new"
    printf '%s' "$new"
    return 0
  fi
  user="$(env_value POSTGRES_USER || echo alpha_router)"
  db="$(env_value POSTGRES_DB || echo alpha_router)"
  warn "POSTGRES_PASSWORD is a known placeholder but a database volume already exists; rotating the role password in the cluster first."
  if ! postgres_alter_role_password "$user" "$db" "$new"; then
    die "Could not change the PostgreSQL role password inside the existing cluster. .env was left untouched so the stack still starts; fix the database, then re-run with --prod."
  fi
  set_env_var POSTGRES_PASSWORD "$new"
  printf '%s' "$new"
}

postgres_volume_exists() {
  docker volume inspect alpha_router_pg >/dev/null 2>&1
}

# ALTER ROLE on the cluster stored in alpha_router_pg. Starts only the postgres
# service (with the *current* .env, i.e. the old password) if it is not up;
# psql inside the container authenticates over the unix socket, so no password
# is needed. The later 'compose up' recreates the container with the new .env;
# POSTGRES_PASSWORD only matters at initdb, so the running cluster is unaffected.
postgres_alter_role_password() {
  local user="$1" db="$2" new="$3"
  local started=0 _attempt
  if ! compose ps --status running --services 2>/dev/null | grep -qx postgres; then
    compose up -d --no-deps postgres >&2 || return 1
    started=1
  fi
  for _attempt in $(seq 1 30); do
    if compose exec -T postgres pg_isready -U "$user" -d "$db" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  # rand_hex output is [0-9a-f], so no quoting hazards inside the literal.
  if ! compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$user" -d "$db" \
      -c "ALTER ROLE \"$user\" WITH PASSWORD '$new';" >&2; then
    if [ "$started" -eq 1 ]; then
      compose stop postgres >&2 || true
    fi
    return 1
  fi
  return 0
}

sync_database_url_password() {
  local pg_pass="$1"
  local user db
  user="$(env_value POSTGRES_USER || echo alpha_router)"
  db="$(env_value POSTGRES_DB || echo alpha_router)"
  set_env_var DATABASE_URL "postgresql+asyncpg://${user}:${pg_pass}@pgbouncer:6432/${db}"
}
