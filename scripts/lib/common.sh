#!/usr/bin/env bash
# Shared helpers for Alpharouter install scripts.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MIN_DISK_GB="${MIN_DISK_GB:-30}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-900}"

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

compose() {
  docker compose "$@"
}
