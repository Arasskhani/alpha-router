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
  set_env_var ENABLE_HSTS false
  set_env_var FRONTEND_URL "http://127.0.0.1:8080"
  set_env_var API_PUBLIC_URL "http://127.0.0.1:8080"

  ensure_secret SECRET_KEY "$(rand_hex 32)" "change-me-in-production"
  ensure_secret DATA_ENCRYPTION_KEY "$(rand_hex 32)" "change-me-in-production"
  ensure_secret ADMIN_PASSWORD "$(rand_hex 16)" "admin"
  ensure_secret SERVICE_ADMIN_PASSWORD "$(rand_hex 16)" "changeme"
  ensure_secret GATEWAY_MASTER_KEY "sk-alpharouter-$(rand_hex 24)" "sk-alpha-router-master"

  local pg_pass
  pg_pass="$(ensure_secret POSTGRES_PASSWORD "$(rand_hex 24)" "changeme")"
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

sync_database_url_password() {
  local pg_pass="$1"
  local user db
  user="$(env_value POSTGRES_USER || echo alpha_router)"
  db="$(env_value POSTGRES_DB || echo alpha_router)"
  set_env_var DATABASE_URL "postgresql+asyncpg://${user}:${pg_pass}@pgbouncer:6432/${db}"
}
