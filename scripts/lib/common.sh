#!/usr/bin/env bash
# Shared helpers for Alpharouter install scripts.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MIN_DISK_GB="${MIN_DISK_GB:-30}"
MIN_DISK_GB_REGISTRY="${MIN_DISK_GB_REGISTRY:-10}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-900}"
REGISTRY_COMPOSE_FILE="deploy/docker-compose.registry.yml"
LOG_PREFIX="${LOG_PREFIX:-install}"
ALPHAROUTER_GIT_URL="${ALPHAROUTER_GIT_URL:-https://github.com/Arasskhani/alpha-router.git}"
ALPHAROUTER_GIT_REF="${ALPHAROUTER_GIT_REF:-main}"
ALPHAROUTER_HOME="${ALPHAROUTER_HOME:-/opt/alpha-router}"

NAMED_DATA_VOLUMES=(
  alpha_router_pg
  alpha_router_redis
  alpha_router_qdrant
  alpha_router_seaweedfs
  alpha_router_clamav
)

log() {
  printf '[%s] %s\n' "$LOG_PREFIX" "$*"
}

warn() {
  printf '[%s] WARN: %s\n' "$LOG_PREFIX" "$*" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "$LOG_PREFIX" "$*" >&2
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

is_repo_root() {
  local dir="${1:-}"
  [ -n "$dir" ] || return 1
  [ -f "$dir/docker-compose.yml" ] && [ -f "$dir/scripts/lib/common.sh" ]
}

named_data_volumes_exist() {
  local vol
  command -v docker >/dev/null 2>&1 || return 1
  docker info >/dev/null 2>&1 || return 1
  for vol in "${NAMED_DATA_VOLUMES[@]}"; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

require_existing_install() {
  [ -f "$ROOT_DIR/.env" ] || die ".env not found. This is an existing-server script. Run it from the installed tree (the directory that already has .env)."
  [ -f "$ROOT_DIR/docker-compose.yml" ] || die "docker-compose.yml not found in $ROOT_DIR."
}

refuse_if_existing_install() {
  if [ -f "$ROOT_DIR/.env" ]; then
    die "This directory already has .env. Use ./scripts/upgrade.sh so existing data and secrets stay intact."
  fi
  if named_data_volumes_exist; then
    die "Named data volumes already exist (alpha_router_pg / redis / qdrant / seaweedfs / clamav). This host already has Alpharouter data. Use ./scripts/upgrade.sh from the current install directory. Do not run install.sh here."
  fi
}
