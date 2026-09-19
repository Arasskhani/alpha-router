#!/usr/bin/env bash
# New Ubuntu Server installer. Installs host prerequisites (git, Docker, Compose),
# clones GitHub if needed, then does a first-time Alpharouter deploy.
#
# Do NOT use this on a host that already has Alpharouter data. Use upgrade.sh.
#
# Examples (Ubuntu Server, amd64):
#   curl -fsSL https://raw.githubusercontent.com/Arasskhani/alpha-router/main/scripts/install.sh | sudo bash
#   sudo ./scripts/install.sh --prod
#   sudo ALPHAROUTER_HOME=/home/alpha/alpha-router ./scripts/install.sh --prod

set -euo pipefail

LOG_PREFIX="${LOG_PREFIX:-install}"
ALPHAROUTER_GIT_URL="${ALPHAROUTER_GIT_URL:-https://github.com/Arasskhani/alpha-router.git}"
# Empty = resolve the newest release tag (vX.Y.Z) at run time. Set to a branch
# or tag to override; `main` gives the old unpinned behaviour.
ALPHAROUTER_GIT_REF="${ALPHAROUTER_GIT_REF:-}"
ALPHAROUTER_HOME="${ALPHAROUTER_HOME:-/opt/alpha-router}"

bootstrap_die() {
  printf '[install] ERROR: %s\n' "$*" >&2
  exit 1
}

bootstrap_log() {
  printf '[install] %s\n' "$*"
}

script_in_repo() {
  local here
  if [ -z "${BASH_SOURCE[0]:-}" ] || [ ! -f "${BASH_SOURCE[0]}" ]; then
    return 1
  fi
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [ -f "$here/lib/common.sh" ] && [ -f "$here/../docker-compose.yml" ]
}

bootstrap_minimal_git() {
  if command -v git >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
    return 0
  fi
  [ "$(id -u)" -eq 0 ] || bootstrap_die "Need root to install git/curl. Re-run with sudo."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends ca-certificates curl git
}

bootstrap_refuse_existing() {
  local dest="$ALPHAROUTER_HOME"
  if [ -f "$dest/.alpharouter-installed" ] || [ -f "$dest/.env" ] || [ -f "$dest/docker-compose.override.yml" ]; then
    bootstrap_die "HARD LOCK: $dest already has an Alpharouter install. Use $dest/scripts/upgrade.sh"
  fi
  if [ -f /home/alpha/alpha-router/.alpharouter-installed ] || [ -f /home/alpha/alpha-router/.env ]; then
    bootstrap_die "HARD LOCK: /home/alpha/alpha-router already has an Alpharouter install. Use /home/alpha/alpha-router/scripts/upgrade.sh"
  fi
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker volume inspect alpha_router_pg >/dev/null 2>&1 \
      || docker ps -aq --filter name=alpha-router 2>/dev/null | grep -q .; then
      bootstrap_die "HARD LOCK: this host already has Alpharouter Docker data. Use ./scripts/upgrade.sh from the live tree."
    fi
  fi
}

# Newest semver release tag on the remote, or empty when there is none.
# `curl | bash` used to clone `main` unpinned: every push to main became root
# code on the next fresh host. Releases are what was actually tested.
bootstrap_latest_release_tag() {
  git ls-remote --tags --refs "$ALPHAROUTER_GIT_URL" 'v[0-9]*' 2>/dev/null \
    | awk -F/ '{print $NF}' \
    | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
    | sort -t. -k1,1V -k2,2n -k3,3n \
    | tail -n 1
}

bootstrap_resolve_git_ref() {
  if [ -n "$ALPHAROUTER_GIT_REF" ]; then
    return 0
  fi
  local tag
  tag="$(bootstrap_latest_release_tag || true)"
  if [ -n "$tag" ]; then
    ALPHAROUTER_GIT_REF="$tag"
    bootstrap_log "Installing latest release $tag (set ALPHAROUTER_GIT_REF to override)."
  else
    ALPHAROUTER_GIT_REF="main"
    bootstrap_log "WARNING: no release tag found on $ALPHAROUTER_GIT_URL; falling back to main."
  fi
}

reexec_from_clone() {
  local dest="$ALPHAROUTER_HOME"
  bootstrap_refuse_existing
  bootstrap_minimal_git
  bootstrap_resolve_git_ref
  if [ ! -f "$dest/scripts/install.sh" ]; then
    if [ -e "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null || true)" ]; then
      bootstrap_die "$dest exists and is not an Alpharouter checkout. Set ALPHAROUTER_HOME."
    fi
    [ "$(id -u)" -eq 0 ] || bootstrap_die "Need root to clone into $dest. Re-run with sudo."
    bootstrap_log "Cloning $ALPHAROUTER_GIT_URL ($ALPHAROUTER_GIT_REF) into $dest..."
    mkdir -p "$(dirname "$dest")"
    git clone --branch "$ALPHAROUTER_GIT_REF" --depth 1 "$ALPHAROUTER_GIT_URL" "$dest"
  fi
  chmod +x "$dest/scripts/install.sh"
  bootstrap_log "Re-running installer from $dest..."
  exec bash "$dest/scripts/install.sh" "$@"
}

if ! script_in_repo; then
  reexec_from_clone "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Kept for the re-run hint in require_root, which cannot see the script's own arguments.
SCRIPT_ARGS=("$@")
export SCRIPT_ARGS
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
# shellcheck source=lib/ubuntu-prereqs.sh
source "$SCRIPT_DIR/lib/ubuntu-prereqs.sh"

FROM_SOURCE=1
FROM_REGISTRY=0
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
USE_REGISTRY_COMPOSE=0
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
DEPLOY_MODE=prod
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
UPGRADE=0
PREFLIGHT_ONLY=0
# shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
SKIP_BUILD=0
IMAGE_TAG=""

usage() {
  cat <<'EOF'
Alpharouter new-server installer (Ubuntu Server amd64)

  sudo ./scripts/install.sh
  sudo ./scripts/install.sh --prod
  sudo ./scripts/install.sh --dev
  sudo ./scripts/install.sh --from-registry --image-tag TAG

On a host with no git checkout:

  curl -fsSL https://raw.githubusercontent.com/Arasskhani/alpha-router/main/scripts/install.sh | sudo bash

This script installs git, curl, Docker Engine, and Compose, clones GitHub if
needed, writes .env + docker-compose.override.yml, and starts the stack.

Hard lock: if .env, override, lock file, named volumes, or alpha-router
containers already exist, this script exits immediately. Use:

  ./scripts/upgrade.sh

Options:
  --prod                Production secrets + production preflight (default)
  --dev                 Development mode
  --from-source         Build images on the host (default)
  --from-registry       Pull published images instead of building
  --image-tag TAG       Registry image tag
  --preflight-only      Checks + .env only; no docker compose up
  --skip-build          Start without image rebuild (source mode only)

Environment:
  ALPHAROUTER_HOME=/opt/alpha-router
  ALPHAROUTER_GIT_URL=https://github.com/Arasskhani/alpha-router.git
  ALPHAROUTER_GIT_REF=main
  # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
  MIN_DISK_GB=30
  HEALTH_TIMEOUT_SEC=900
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
      --upgrade)
        die "install.sh is for empty hosts only. On a live server with data use: ./scripts/upgrade.sh"
        ;;
      --preflight-only)
        PREFLIGHT_ONLY=1
        ;;
      --skip-build)
        # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
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
}

main() {
  parse_args "$@"
  cd "$ROOT_DIR"

  if [ "$FROM_REGISTRY" -eq 1 ]; then
    # shellcheck disable=SC2034 # read by the sourced scripts/lib/*.sh
    MIN_DISK_GB="$MIN_DISK_GB_REGISTRY"
  fi

  refuse_if_existing_install
  install_ubuntu_prereqs
  refuse_if_existing_install

  if [ "$FROM_REGISTRY" -eq 1 ]; then
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

  export_app_version
  start_stack
  wait_for_health
  print_success
}

main "$@"
