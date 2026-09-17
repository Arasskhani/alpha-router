#!/usr/bin/env bash
# Restore an Alpharouter host from a snapshot made by scripts/backup.sh.
#
#   ./scripts/restore.sh 20260914103000                 # database + volumes
#   ./scripts/restore.sh 20260914103000 --with-env      # also restore .env
#   ./scripts/restore.sh 20260914103000 --previous-images
#       # additionally re-tag <image>:prev -> :latest (set by upgrade.sh) so
#       # the code that ran before the failed upgrade starts again
#
# Stops the stack (never 'down -v'), replaces the database contents and the
# qdrant/seaweedfs/tls volumes with the snapshot, then starts the stack.
# Data written after the snapshot is lost -- this is the point of a restore.

set -euo pipefail

LOG_PREFIX="${LOG_PREFIX:-restore}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/env-bootstrap.sh
source "$SCRIPT_DIR/lib/env-bootstrap.sh"

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
WITH_ENV=0
PREVIOUS_IMAGES=0
STAMP=""
DATA_VOLUMES=(alpha_router_qdrant alpha_router_seaweedfs alpha_router_tls)
LOCAL_IMAGES=(alpha-router alpha-router-sandbox alpha-router-sandbox-broker alpha-router-edge)

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --with-env) WITH_ENV=1 ;;
      --previous-images) PREVIOUS_IMAGES=1 ;;
      -h | --help) usage; exit 0 ;;
      -*) die "Unknown option: $1" ;;
      *) [ -z "$STAMP" ] || die "Only one snapshot may be given."; STAMP="$1" ;;
    esac
    shift
  done
  [ -n "$STAMP" ] || { usage; die "Snapshot timestamp is required. Available: $(ls "$BACKUP_DIR" 2>/dev/null | tr '\n' ' ')"; }
}

confirm() {
  printf '[%s] %s\nType RESTORE to continue: ' "$LOG_PREFIX" "$1"
  local answer
  read -r answer
  [ "$answer" = "RESTORE" ] || die "Aborted."
}

restore_volume() {
  local vol="$1" src="$2"
  if [ ! -f "$src/${vol}.tgz" ]; then
    warn "no ${vol}.tgz in snapshot; leaving volume $vol as is."
    return 0
  fi
  log "restoring volume $vol"
  docker volume create "$vol" >/dev/null
  docker run --rm \
    -v "${vol}:/data" \
    -v "${src}:/backup:ro" \
    alpine:3.20 sh -c 'find /data -mindepth 1 -delete && tar xzf "/backup/'"$vol"'.tgz" -C /data'
}

restore_postgres() {
  local src="$1" user db _attempt
  user="$(env_value POSTGRES_USER || echo alpha_router)"
  db="$(env_value POSTGRES_DB || echo alpha_router)"
  log "starting only postgres"
  compose up -d --no-deps postgres >/dev/null
  for _attempt in $(seq 1 30); do
    compose exec -T postgres pg_isready -U "$user" -d "$db" >/dev/null 2>&1 && break
    sleep 2
  done
  log "pg_restore --clean into ${db}"
  # --clean --if-exists drops objects present in the dump before recreating
  # them; objects created *after* the snapshot (new Alembic tables) survive,
  # which is why --previous-images matters when rolling back a migration.
  compose exec -T postgres pg_restore -U "$user" -d "$db" --clean --if-exists --no-owner --exit-on-error < "$src/db.dump"
}

retag_previous_images() {
  local img
  for img in "${LOCAL_IMAGES[@]}"; do
    if docker image inspect "${img}:prev" >/dev/null 2>&1; then
      log "re-tagging ${img}:prev -> ${img}:latest"
      docker tag "${img}:prev" "${img}:latest"
    else
      warn "${img}:prev not found; keeping current ${img}:latest"
    fi
  done
}

main() {
  parse_args "$@"
  cd "$ROOT_DIR"
  local src="$BACKUP_DIR/$STAMP"
  [ -d "$src" ] || die "Snapshot not found: $src"
  [ -f "$src/db.dump" ] || die "Snapshot has no db.dump: $src"
  [ -f "$ROOT_DIR/.env" ] || [ "$WITH_ENV" -eq 1 ] || die "No .env present; re-run with --with-env."

  log "Snapshot: $src"
  cat "$src/MANIFEST" 2>/dev/null | sed 's/^/[restore]   /' || true
  confirm "This replaces the database and the qdrant/seaweedfs/tls volumes with the snapshot. Everything written since is lost."

  log "stopping the stack (volumes are kept)"
  compose down --remove-orphans >/dev/null

  if [ "$WITH_ENV" -eq 1 ]; then
    cp -a "$ROOT_DIR/.env" "$ROOT_DIR/.env.pre-restore.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
    cp -a "$src/.env" "$ROOT_DIR/.env"
    log ".env restored from snapshot"
  fi
  if [ "$PREVIOUS_IMAGES" -eq 1 ]; then
    retag_previous_images
  fi

  for vol in "${DATA_VOLUMES[@]}"; do
    restore_volume "$vol" "$src"
  done
  restore_postgres "$src"

  log "starting the stack"
  compose up -d
  log "Restore complete. Check: docker compose ps"
}

main "$@"
