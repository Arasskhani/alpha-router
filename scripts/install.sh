#!/usr/bin/env bash
# Alpharouter installer — source copy or registry pull.
#
# Examples:
#   ./scripts/install.sh --from-source --dev
#   ./scripts/install.sh --from-source --prod
#   ./scripts/install.sh --from-registry --image-tag v1.0.0
#   ./scripts/install.sh --from-source --upgrade

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/preflight.sh
source "$SCRIPT_DIR/lib/preflight.sh"
# shellcheck source=lib/env-bootstrap.sh
source "$SCRIPT_DIR/lib/env-bootstrap.sh"
# shellcheck source=lib/env-merge.sh
source "$SCRIPT_DIR/lib/env-merge.sh"
# shellcheck source=lib/deploy-mode.sh
source "$SCRIPT_DIR/lib/deploy-mode.sh"
# shellcheck source=lib/docker-gid.sh
source "$SCRIPT_DIR/lib/docker-gid.sh"

FROM_SOURCE=0
FROM_REGISTRY=0
DEPLOY_MODE=dev
UPGRADE=0
PREFLIGHT_ONLY=0
SKIP_BUILD=0
IMAGE_TAG=""

usage() {
  cat <<'EOF'
Alpharouter install

  ./scripts/install.sh --from-source [--dev|--prod]
  ./scripts/install.sh --from-registry [--dev|--prod] [--image-tag TAG]
  ./scripts/install.sh --from-source --upgrade [--dev|--prod]
  ./scripts/install.sh --from-source --preflight-only
  ./scripts/install.sh --from-source --skip-build

Options:
  --dev                 Development mode (default)
  --prod                Production secrets + production preflight
  --upgrade             Merge new .env.example keys; rebuild or pull; run migrations
  --preflight-only      Checks + .env only; no docker compose up
  --skip-build          Start without image rebuild (source mode only)

Environment:
  MIN_DISK_GB=30              Minimum free disk for source build (GiB)
  MIN_DISK_GB_REGISTRY=10     Minimum free disk for registry pull (GiB)
  HEALTH_TIMEOUT_SEC=900      Health poll timeout (seconds)
  DOCKER_SOCK=/var/run/docker.sock

Registry (.env):
  ALPHAROUTER_REGISTRY        e.g. registry.gitlab.com/group/alpha-router
  ALPHAROUTER_IMAGE_TAG       Image tag (default: latest)
  REGISTRY_USER / REGISTRY_PASSWORD   Optional docker login
EOF
}

parse_args() {
  if [ "$#" -eq 0 ]; then
    usage
    die "Pass --from-source or --from-registry."
  fi

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --from-source)
        FROM_SOURCE=1
        ;;
      --from-registry)
        FROM_REGISTRY=1
        USE_REGISTRY_COMPOSE=1
        ;;
      --dev)
        DEPLOY_MODE=dev
        ;;
      --prod)
        DEPLOY_MODE=prod
        ;;
      --upgrade)
        UPGRADE=1
        ;;
      --preflight-only)
        PREFLIGHT_ONLY=1
        ;;
      --skip-build)
        SKIP_BUILD=1
        ;;
      --image-tag)
        shift
        IMAGE_TAG="${1:-}"
        [ -n "$IMAGE_TAG" ] || die "--image-tag requires a value."
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

  if [ "$FROM_SOURCE" -eq 1 ] && [ "$FROM_REGISTRY" -eq 1 ]; then
    die "Use only one of --from-source or --from-registry."
  fi
  if [ "$FROM_SOURCE" -ne 1 ] && [ "$FROM_REGISTRY" -ne 1 ]; then
    die "Pass --from-source or --from-registry."
  fi
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

show_bootstrap_admin_credentials() {
  local marker="BOOTSTRAP_ADMIN_CREDENTIALS_ONCE"
  local line
  line="$(compose logs alpha-router 2>&1 | grep "$marker" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    return 0
  fi
  printf '\n[install] First-boot bootstrap administrator (one-time; also in container logs):\n'
  printf '[install] %s\n' "$line"
  warn "Change this password after first login. Docker log retention may keep a copy."
}

print_success() {
  local admin_user
  admin_user="$(env_value ADMIN_USERNAME 2>/dev/null || echo alpharouter)"

  show_bootstrap_admin_credentials

  cat <<EOF

Alpharouter is running.

  UI:     http://127.0.0.1:8080
  Health: $HEALTH_URL
  Admin:  $admin_user
  Mode:   $DEPLOY_MODE

Logs:   docker compose logs -f alpha-router
Stop:   docker compose down

EOF
}

prepare_env() {
  if [ "$UPGRADE" -eq 1 ]; then
    merge_env_from_example
  fi
  bootstrap_env_file
  apply_deploy_mode
  if [ -n "$IMAGE_TAG" ]; then
    set_env_var ALPHAROUTER_IMAGE_TAG "$IMAGE_TAG"
  fi
  if [ "$DEPLOY_MODE" = "prod" ]; then
    run_python_production_check
  fi
}

start_stack() {
  if [ "$FROM_REGISTRY" -eq 1 ]; then
    require_registry_config
    registry_login_if_configured
    log "Pulling images from registry..."
    compose pull
    log "Starting stack..."
    compose up -d
    return 0
  fi

  if [ "$SKIP_BUILD" -eq 1 ]; then
    log "Starting stack (no rebuild)..."
    compose up -d
  else
    log "Building and starting stack (this may take several minutes)..."
    compose up --build -d
  fi
}

main() {
  parse_args "$@"
  cd "$ROOT_DIR"

  if [ "$FROM_REGISTRY" -eq 1 ]; then
    MIN_DISK_GB="$MIN_DISK_GB_REGISTRY"
    run_preflight_registry
  else
    run_preflight
  fi

  prepare_env
  write_docker_compose_override

  if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
    log "Preflight-only mode; skipping docker compose up."
    exit 0
  fi

  start_stack
  wait_for_health
  print_success
}

main "$@"
