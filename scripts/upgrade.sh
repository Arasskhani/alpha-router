#!/usr/bin/env bash
# Upgrade an existing Alpharouter host that already has .env and data volumes.
# Never removes volumes. Never runs docker compose down -v.
#
# Examples:
#   ./scripts/upgrade.sh
#   ./scripts/upgrade.sh --prod
#   ./scripts/upgrade.sh --skip-build
#   ./scripts/upgrade.sh --from-registry --image-tag v1.2.0

set -euo pipefail

LOG_PREFIX="${LOG_PREFIX:-upgrade}"

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
# shellcheck source=lib/stack.sh
source "$SCRIPT_DIR/lib/stack.sh"

FROM_SOURCE=1
FROM_REGISTRY=0
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
USE_REGISTRY_COMPOSE=0
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
DEPLOY_MODE=""
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
UPGRADE=1
PREFLIGHT_ONLY=0
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
SKIP_BUILD=0
SKIP_GIT=0
IMAGE_TAG=""

usage() {
  cat <<'EOF'
Alpharouter upgrade (existing server with data)

  ./scripts/upgrade.sh
  ./scripts/upgrade.sh --prod
  ./scripts/upgrade.sh --skip-build
  ./scripts/upgrade.sh --from-registry --image-tag TAG

Run this from the installed tree (the directory that already has .env).
Keeps named volumes and existing secrets. Writes docker-compose.override.yml
(docker.sock GID) so sandbox-broker can start.

Do not use install.sh on this host. Do not run docker compose down -v.

Options:
  --prod                Keep/apply production .env rules (default if ENVIRONMENT=production)
  --dev                 Development mode
  --from-source         Rebuild images from source (default)
  --from-registry       Pull published images
  --image-tag TAG       Registry image tag
  --skip-build          Recreate/start without rebuilding images
  --skip-git            Do not git pull
  --preflight-only      Checks + .env merge only; no compose up

Environment:
  # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
  MIN_DISK_GB=30
  HEALTH_TIMEOUT_SEC=900
  SKIP_BACKUP=1         Skip the pre-upgrade snapshot (scripts/backup.sh --consistent)
  BACKUP_DIR=...        Where snapshots go (default: ./backups, last 7 kept)

Rollback after a bad upgrade:
  ./scripts/restore.sh <snapshot> --previous-images
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --from-source)
        FROM_SOURCE=1
        FROM_REGISTRY=0
        # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
        USE_REGISTRY_COMPOSE=0
        ;;
      --from-registry)
        FROM_SOURCE=0
        FROM_REGISTRY=1
        # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
        USE_REGISTRY_COMPOSE=1
        ;;
      --dev)
        # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
        DEPLOY_MODE=dev
        ;;
      --prod)
        # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
        DEPLOY_MODE=prod
        ;;
      --preflight-only)
        PREFLIGHT_ONLY=1
        ;;
      --skip-build)
        # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
        SKIP_BUILD=1
        ;;
      --skip-git)
        SKIP_GIT=1
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
}

assert_no_volume_wipe() {
  log "Upgrade will not remove named volumes or run docker compose down -v."
}

main() {
  parse_args "$@"
  cd "$ROOT_DIR"
  require_existing_install
  write_install_lock_marker
  assert_no_volume_wipe

  if [ -z "$DEPLOY_MODE" ]; then
    # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
    DEPLOY_MODE="$(deploy_mode_from_env)"
    log "Deploy mode from .env: $DEPLOY_MODE"
  fi

  if [ "$FROM_REGISTRY" -eq 1 ]; then
    # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
    MIN_DISK_GB="$MIN_DISK_GB_REGISTRY"
  fi

  if [ "$SKIP_GIT" -ne 1 ]; then
    git_pull_ff_only
  else
    log "Skipping git pull."
  fi

  if [ "$FROM_REGISTRY" -eq 1 ]; then
    run_preflight_registry
  else
    run_preflight
  fi

  backup_env_file
  prepare_env
  write_docker_compose_override

  if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
    log "Preflight-only mode; skipping docker compose up."
    exit 0
  fi

  backup_before_upgrade
  # Every path here replaces :latest - a source build, a registry pull, and
  # --skip-build too, because the release checkout moved underneath it. The
  # guard used to run this only for a source build, so restore.sh
  # --previous-images silently kept the new code on the other two: the operator
  # restored old data and ran it under the build they were rolling back from.
  tag_previous_images
  export_app_version
  start_stack
  wait_for_health
  print_success
}

main "$@"
