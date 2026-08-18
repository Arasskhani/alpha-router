#!/usr/bin/env bash
# Alpharouter installer — source copy / local tree deploy.
#
# Usage:
#   ./scripts/install.sh --from-source
#   ./scripts/install.sh --from-source --preflight-only
#
# Requires: Docker Engine, Docker Compose v2, bash, amd64 host (recommended).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/preflight.sh
source "$SCRIPT_DIR/lib/preflight.sh"
# shellcheck source=lib/env-bootstrap.sh
source "$SCRIPT_DIR/lib/env-bootstrap.sh"
# shellcheck source=lib/docker-gid.sh
source "$SCRIPT_DIR/lib/docker-gid.sh"

FROM_SOURCE=0
PREFLIGHT_ONLY=0
SKIP_BUILD=0

usage() {
  cat <<'EOF'
Alpharouter install

  ./scripts/install.sh --from-source              Build images and start the stack
  ./scripts/install.sh --from-source --preflight-only   Run checks only
  ./scripts/install.sh --from-source --skip-build       Start without rebuild

Environment:
  MIN_DISK_GB=30          Minimum free disk (GiB)
  HEALTH_TIMEOUT_SEC=900  Health poll timeout (seconds)
  DOCKER_SOCK=/var/run/docker.sock
EOF
}

parse_args() {
  if [ "$#" -eq 0 ]; then
    usage
    die "Pass --from-source to install."
  fi

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --from-source)
        FROM_SOURCE=1
        ;;
      --preflight-only)
        PREFLIGHT_ONLY=1
        ;;
      --skip-build)
        SKIP_BUILD=1
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
    shift
  done

  [ "$FROM_SOURCE" -eq 1 ] || die "Only --from-source is implemented in this release."
}

wait_for_health() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SEC))
  log "Waiting for $HEALTH_URL (timeout ${HEALTH_TIMEOUT_SEC}s)..."

  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      log "Health check passed."
      return 0
    fi
    sleep 5
  done

  die "Timed out waiting for health. Check: docker compose logs alpha-router"
}

print_success() {
  local admin_user admin_pass
  admin_user="$(env_value ADMIN_USERNAME 2>/dev/null || echo alpharouter)"
  admin_pass="$(env_value ADMIN_PASSWORD 2>/dev/null || echo admin)"

  cat <<EOF

Alpharouter is running.

  UI:     http://127.0.0.1:8080
  Health: $HEALTH_URL
  Admin:  $admin_user / (see ADMIN_PASSWORD in .env)

Logs:   docker compose logs -f alpha-router
Stop:   docker compose down

EOF
}

main() {
  parse_args "$@"
  cd "$ROOT_DIR"

  run_preflight
  bootstrap_env_file
  write_docker_compose_override

  if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
    log "Preflight-only mode; skipping docker compose up."
    exit 0
  fi

  if [ "$SKIP_BUILD" -eq 1 ]; then
    log "Starting stack (no rebuild)..."
    compose up -d
  else
    log "Building and starting stack (this may take several minutes)..."
    compose up --build -d
  fi

  wait_for_health
  print_success
}

main "$@"
