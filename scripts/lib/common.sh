#!/usr/bin/env bash
# Shared helpers for Alpharouter install scripts.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MIN_DISK_GB="${MIN_DISK_GB:-30}"
MIN_DISK_GB_REGISTRY="${MIN_DISK_GB_REGISTRY:-10}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-900}"
REGISTRY_COMPOSE_FILE="deploy/docker-compose.registry.yml"

log() {
  printf '[install] %s\n' "$*"
}

warn() {
  printf '[install] WARN: %s\n' "$*" >&2
}

die() {
  printf '[install] ERROR: %s\n' "$*" >&2
  exit 1
}

rand_hex() {
  local bytes="${1:-32}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
    return 0
  fi
  if [ -r /dev/urandom ]; then
    # shellcheck disable=SC2005
    echo "$(head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n')"
    return 0
  fi
  die "Cannot generate random secrets (need openssl or /dev/urandom)."
}

compose_args() {
  local args=(-f docker-compose.yml)
  if [ -f "$ROOT_DIR/docker-compose.override.yml" ]; then
    args+=(-f docker-compose.override.yml)
  fi
  if [ "${USE_REGISTRY_COMPOSE:-0}" -eq 1 ]; then
    args+=(-f "$REGISTRY_COMPOSE_FILE")
  fi
  printf '%s\n' "${args[@]}"
}

compose() {
  # shellcheck disable=SC2046
  docker compose $(compose_args) "$@"
}

registry_login_if_configured() {
  local user pass registry
  user="$(env_value REGISTRY_USER 2>/dev/null || true)"
  pass="$(env_value REGISTRY_PASSWORD 2>/dev/null || true)"
  registry="$(env_value ALPHAROUTER_REGISTRY 2>/dev/null || true)"
  if [ -n "$user" ] && [ -n "$pass" ] && [ -n "$registry" ]; then
    log "Logging in to container registry..."
    printf '%s' "$pass" | docker login "$registry" -u "$user" --password-stdin
  fi
}

require_registry_config() {
  local registry
  registry="$(env_value ALPHAROUTER_REGISTRY 2>/dev/null || true)"
  [ -n "$registry" ] || die "Set ALPHAROUTER_REGISTRY in .env (e.g. registry.gitlab.com/group/alpha-router)."
}

run_python_production_check() {
  if command -v python3 >/dev/null 2>&1; then
    if PYTHONPATH="$ROOT_DIR/backend" python3 -c "import pydantic_settings" 2>/dev/null; then
      log "Running production guard (Python)..."
      PYTHONPATH="$ROOT_DIR/backend" python3 "$ROOT_DIR/scripts/check_production_env.py"
      return 0
    fi
  fi
  log "Running production guard (shell preflight)..."
  bash "$ROOT_DIR/scripts/preflight-prod.sh" "$ROOT_DIR"
}
