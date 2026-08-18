#!/usr/bin/env bash
# Preflight checks before docker compose up.

REQUIRED_PATHS=(
  "docker-compose.yml"
  "Dockerfile"
  ".env.example"
  "backend/app/main.py"
  "frontend/package.json"
  "frontend/package-lock.json"
  "sandbox/Dockerfile"
  "sandbox/runner.py"
  "sandbox-broker/Dockerfile"
  "deploy/seaweedfs/entrypoint.sh"
)

run_preflight() {
  log "Running preflight checks..."
  check_docker
  check_compose
  check_architecture
  check_disk_space
  check_source_integrity
  check_docker_socket
  log "Preflight checks passed."
}

check_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed or not on PATH."
  docker info >/dev/null 2>&1 || die "Docker daemon is not running or not accessible."
}

check_compose() {
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  die "Docker Compose v2 is required (docker compose)."
}

check_architecture() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64 | amd64)
      log "Architecture: $arch (supported)"
      ;;
    aarch64 | arm64)
      warn "Architecture is $arch. Code Interpreter sandbox-broker bundles amd64 Docker CLI; ARM is not supported."
      ;;
    *)
      warn "Unknown architecture: $arch. Only amd64 is tested."
      ;;
  esac
}

check_disk_space() {
  local avail_kb avail_gb
  avail_kb="$(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $4}')"
  avail_gb=$((avail_kb / 1024 / 1024))
  if [ "$avail_gb" -lt "$MIN_DISK_GB" ]; then
    die "Need at least ${MIN_DISK_GB} GiB free disk on $(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $1}') (found ~${avail_gb} GiB)."
  fi
  log "Free disk: ~${avail_gb} GiB (minimum ${MIN_DISK_GB} GiB)."
}

check_source_integrity() {
  local missing=0 rel
  for rel in "${REQUIRED_PATHS[@]}"; do
    if [ ! -e "$ROOT_DIR/$rel" ]; then
      warn "Missing required path: $rel"
      missing=1
    fi
  done
  if [ "$missing" -ne 0 ]; then
    die "Source tree is incomplete. Copy the full project before installing."
  fi
  log "Source integrity check passed (${#REQUIRED_PATHS[@]} paths)."
}

check_docker_socket() {
  local sock="${DOCKER_SOCK:-/var/run/docker.sock}"
  [ -e "$sock" ] || die "Docker socket not found at $sock (Code Interpreter requires it)."
}

REGISTRY_REQUIRED_PATHS=(
  "docker-compose.yml"
  "deploy/docker-compose.registry.yml"
  ".env.example"
  "deploy/seaweedfs/entrypoint.sh"
)

run_preflight_registry() {
  log "Running registry preflight checks..."
  check_docker
  check_compose
  check_architecture
  check_disk_space
  check_registry_bundle_integrity
  check_docker_socket
  log "Registry preflight checks passed."
}

check_registry_bundle_integrity() {
  local missing=0 rel
  for rel in "${REGISTRY_REQUIRED_PATHS[@]}"; do
    if [ ! -e "$ROOT_DIR/$rel" ]; then
      warn "Missing required path: $rel"
      missing=1
    fi
  done
  if [ "$missing" -ne 0 ]; then
    die "Deploy bundle is incomplete for --from-registry."
  fi
  log "Registry bundle integrity check passed (${#REGISTRY_REQUIRED_PATHS[@]} paths)."
}
