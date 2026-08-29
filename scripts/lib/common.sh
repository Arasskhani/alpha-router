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

docker_is_ready() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

existing_alpha_router_containers() {
  docker_is_ready || return 1
  docker ps -aq --filter name=alpha-router 2>/dev/null | grep -q .
}

existing_alpha_router_network() {
  docker_is_ready || return 1
  docker network inspect alpha_router_app >/dev/null 2>&1
}

install_tree_lock_paths() {
  local path seen=""
  for path in "$ROOT_DIR" "${ALPHAROUTER_HOME:-}" /opt/alpha-router /home/alpha/alpha-router; do
    [ -n "$path" ] || continue
    case " $seen " in
      *" $path "*) continue ;;
    esac
    seen="$seen $path"
    printf '%s\n' "$path"
  done
}

collect_existing_install_reasons() {
  local path
  while IFS= read -r path; do
    [ -d "$path" ] || continue
    if [ -f "$path/.alpharouter-installed" ]; then
      printf 'lock file %s/.alpharouter-installed\n' "$path"
    fi
    if [ -f "$path/.env" ]; then
      printf 'existing .env at %s/.env\n' "$path"
    fi
    if [ -f "$path/docker-compose.override.yml" ]; then
      printf 'existing docker-compose.override.yml at %s\n' "$path"
    fi
  done < <(install_tree_lock_paths)

  if named_data_volumes_exist; then
    printf 'named data volumes (alpha_router_pg / redis / qdrant / seaweedfs / clamav)\n'
  fi
  if existing_alpha_router_containers; then
    printf 'Docker containers named alpha-router-*\n'
  fi
  if existing_alpha_router_network; then
    printf 'Docker network alpha_router_app\n'
  fi
}

require_existing_install() {
  [ -f "$ROOT_DIR/.env" ] || die ".env not found. This is an existing-server script. Run it from the installed tree (the directory that already has .env)."
  [ -f "$ROOT_DIR/docker-compose.yml" ] || die "docker-compose.yml not found in $ROOT_DIR."
}

write_install_lock_marker() {
  printf '%s\n' \
    "Alpharouter is installed in this directory." \
    "Do not run scripts/install.sh on this host." \
    "Use scripts/upgrade.sh to update." \
    >"$ROOT_DIR/.alpharouter-installed"
  log "Wrote $ROOT_DIR/.alpharouter-installed"
}

refuse_if_existing_install() {
  local reasons
  reasons="$(collect_existing_install_reasons || true)"
  if [ -z "$reasons" ]; then
    return 0
  fi
  printf '[%s] ERROR: HARD LOCK — install.sh is blocked on this host.\n' "$LOG_PREFIX" >&2
  printf '[%s] ERROR: This server already has Alpharouter data or an install. Use ./scripts/upgrade.sh from the live tree.\n' "$LOG_PREFIX" >&2
  printf '[%s] ERROR: There is no override and no confirmation prompt.\n' "$LOG_PREFIX" >&2
  printf '%s\n' "$reasons" | while IFS= read -r line; do
    [ -n "$line" ] || continue
    printf '[%s] ERROR:  - %s\n' "$LOG_PREFIX" "$line" >&2
  done
  exit 1
}
