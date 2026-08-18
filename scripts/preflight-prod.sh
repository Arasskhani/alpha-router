#!/usr/bin/env bash
# Verify .env satisfies production guard rules before starting with ENVIRONMENT=production.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/env-bootstrap.sh
source "$SCRIPT_DIR/lib/env-bootstrap.sh"

if [ "${1:-}" != "" ]; then
  ROOT_DIR="$(cd "$1" && pwd)"
  ENV_FILE="$ROOT_DIR/.env"
fi
cd "$ROOT_DIR"

[ -f "$ENV_FILE" ] || die ".env not found. Run install.sh first."

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

is_insecure() {
  local value="$1"
  local item
  for item in "${INSECURE_PLACEHOLDERS[@]}"; do
    if [ "$value" = "$item" ]; then
      return 0
    fi
  done
  return 1
}

require_env() {
  local key="$1"
  local val
  val="$(env_value "$key" || true)"
  if [ -z "$val" ]; then
    die "Missing or empty: $key"
  fi
  printf '%s' "$val"
}

check_not_insecure() {
  local key="$1"
  local val="$2"
  if is_insecure "$val"; then
    die "$key uses insecure placeholder value."
  fi
}

is_loopback_url() {
  local url="$1"
  case "$url" in
    http://127.0.0.1:* | http://localhost:* | https://127.0.0.1:* | https://localhost:*)
      return 0
      ;;
  esac
  return 1
}

main() {
  local env_mode
  env_mode="$(require_env ENVIRONMENT)"
  if [ "$env_mode" != "production" ]; then
    log "ENVIRONMENT=$env_mode (not production) — production preflight skipped."
    exit 0
  fi

  log "Running production preflight on $ENV_FILE ..."

  check_not_insecure SECRET_KEY "$(require_env SECRET_KEY)"
  check_not_insecure ADMIN_PASSWORD "$(require_env ADMIN_PASSWORD)"
  check_not_insecure SERVICE_ADMIN_PASSWORD "$(require_env SERVICE_ADMIN_PASSWORD)"
  check_not_insecure GATEWAY_MASTER_KEY "$(require_env GATEWAY_MASTER_KEY)"
  check_not_insecure DATA_ENCRYPTION_KEY "$(require_env DATA_ENCRYPTION_KEY)"
  check_not_insecure S3_ACCESS_KEY "$(require_env S3_ACCESS_KEY)"
  check_not_insecure S3_SECRET_KEY "$(require_env S3_SECRET_KEY)"
  check_not_insecure SEAWEEDFS_ADMIN_PASSWORD "$(require_env SEAWEEDFS_ADMIN_PASSWORD)"

  local sandbox_token
  sandbox_token="$(require_env SANDBOX_BROKER_TOKEN)"
  if [ "${#sandbox_token}" -lt 32 ]; then
    die "SANDBOX_BROKER_TOKEN must be at least 32 characters."
  fi

  local redis_pw db_url openapi
  redis_pw="$(env_value REDIS_PASSWORD || true)"
  if [ -z "$redis_pw" ] || is_insecure "$redis_pw"; then
    die "REDIS_PASSWORD must be set to a strong value in production."
  fi

  db_url="$(require_env DATABASE_URL)"
  if echo "$db_url" | grep -q ':changeme@'; then
    die "DATABASE_URL must use a strong password in production."
  fi

  openapi="$(env_value OPENAPI_ADMIN_ONLY || echo false)"
  if [ "$openapi" != "true" ] && [ "$openapi" != "True" ] && [ "$openapi" != "1" ]; then
    die "OPENAPI_ADMIN_ONLY must be true in production."
  fi

  local frontend api_public
  frontend="$(require_env FRONTEND_URL)"
  api_public="$(require_env API_PUBLIC_URL)"
  if ! is_loopback_url "$frontend" && [[ "$frontend" != https://* ]]; then
    die "FRONTEND_URL must be HTTPS or loopback HTTP in production."
  fi
  if ! is_loopback_url "$api_public" && [[ "$api_public" != https://* ]]; then
    die "API_PUBLIC_URL must be HTTPS or loopback HTTP in production."
  fi

  if ! is_loopback_url "$frontend" && ! is_loopback_url "$api_public"; then
    local hsts
    hsts="$(env_value ENABLE_HSTS || echo false)"
    if [ "$hsts" != "true" ] && [ "$hsts" != "True" ] && [ "$hsts" != "1" ]; then
      warn "Public HTTPS URLs configured but ENABLE_HSTS is not true."
    fi
  fi

  log "Production preflight passed."
}

main "$@"
