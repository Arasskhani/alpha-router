#!/usr/bin/env bash
# Point-in-time backup of an Alpharouter host: PostgreSQL dump, Qdrant and
# SeaweedFS data volumes, TLS state and .env. Never removes anything from the
# running stack. Keeps the newest BACKUP_KEEP (default 7) snapshots.
#
#   ./scripts/backup.sh                 # online: pg_dump + volume tars while running
#   ./scripts/backup.sh --consistent    # stops qdrant/seaweedfs for the tar step
#   BACKUP_DIR=/mnt/backups ./scripts/backup.sh
#
# Restore with ./scripts/restore.sh <timestamp>.
#
# upgrade.sh calls this with --consistent before 'compose up': the stack is
# about to restart anyway, so the short stop costs nothing extra.

set -euo pipefail

LOG_PREFIX="${LOG_PREFIX:-backup}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/env-bootstrap.sh
source "$SCRIPT_DIR/lib/env-bootstrap.sh"

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
CONSISTENT=0
# Volumes worth copying. redis holds only leases/rate-limit state and clamav
# only signature databases; both rebuild themselves.
DATA_VOLUMES=(alpha_router_qdrant alpha_router_seaweedfs alpha_router_tls)

usage() {
  sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --consistent) CONSISTENT=1 ;;
      -h | --help) usage; exit 0 ;;
      *) die "Unknown option: $1" ;;
    esac
    shift
  done
}

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

service_running() {
  # Capture first: with 'pipefail', grep -q closing the pipe early can turn a
  # successful 'compose ps' into SIGPIPE and a false "not running".
  local out
  out="$(compose ps --status running --services 2>/dev/null || true)"
  printf '%s\n' "$out" | grep -qx "$1"
}

dump_postgres() {
  local dest="$1" user db started=0 _attempt
  user="$(env_value POSTGRES_USER || echo alpha_router)"
  db="$(env_value POSTGRES_DB || echo alpha_router)"
  if ! service_running postgres; then
    log "postgres is not running; starting only that service for the dump."
    compose up -d --no-deps postgres >/dev/null
    started=1
  fi
  for _attempt in $(seq 1 30); do
    compose exec -T postgres pg_isready -U "$user" -d "$db" >/dev/null 2>&1 && break
    sleep 2
  done
  log "pg_dump ${db} -> db.dump"
  compose exec -T postgres pg_dump -U "$user" -d "$db" -Fc --no-owner > "$dest/db.dump"
  [ -s "$dest/db.dump" ] || die "pg_dump produced an empty file."
  if [ "$started" -eq 1 ]; then
    compose stop postgres >/dev/null
  fi
}

tar_volume() {
  local vol="$1" dest="$2"
  if ! volume_exists "$vol"; then
    log "volume $vol does not exist; skipping."
    return 0
  fi
  log "archiving volume $vol -> ${vol}.tgz"
  docker run --rm \
    -v "${vol}:/data:ro" \
    -v "${dest}:/backup" \
    alpine:3.20 sh -c 'cd /data && tar czf "/backup/'"$vol"'.tgz" .'
}

prune_old_backups() {
  local keep="$1" n
  n="$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' | wc -l)"
  if [ "$n" -le "$keep" ]; then
    return 0
  fi
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | head -n "$((n - keep))" | while read -r old; do
    log "removing old backup $(basename "$old")"
    rm -rf "$old"
  done
}

# Services this run stopped, and the one place that starts them again. Global
# rather than local because the EXIT trap has to see it.
STOPPED_SERVICES=()

restart_stopped_services() {
  local status=$?
  if [ "${#STOPPED_SERVICES[@]}" -gt 0 ]; then
    log "starting ${STOPPED_SERVICES[*]} again"
    compose start "${STOPPED_SERVICES[@]}" >/dev/null || warn "could not restart: ${STOPPED_SERVICES[*]}"
    STOPPED_SERVICES=()
  fi
  return "$status"
}

main() {
  parse_args "$@"
  cd "$ROOT_DIR"
  [ -f "$ROOT_DIR/.env" ] || die "No .env in $ROOT_DIR; nothing to back up."
  command -v docker >/dev/null 2>&1 || die "docker is required."

  local stamp dest
  stamp="$(date +%Y%m%d%H%M%S)"
  dest="$BACKUP_DIR/$stamp"
  mkdir -p "$dest"
  chmod 700 "$BACKUP_DIR" "$dest"

  cp -a "$ROOT_DIR/.env" "$dest/.env"
  [ -f "$ROOT_DIR/docker-compose.override.yml" ] && cp -a "$ROOT_DIR/docker-compose.override.yml" "$dest/"
  {
    echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "git_commit=$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "consistent=$CONSISTENT"
    for img in alpha-router alpha-router-sandbox alpha-router-sandbox-broker alpha-router-edge; do
      echo "image_${img}=$(docker image inspect --format '{{.Id}}' "${img}:latest" 2>/dev/null || echo none)"
    done
  } > "$dest/MANIFEST"

  dump_postgres "$dest"

  if [ "$CONSISTENT" -eq 1 ]; then
    for svc in qdrant seaweedfs; do
      if service_running "$svc"; then
        log "stopping $svc for a consistent volume copy"
        compose stop "$svc" >/dev/null
        STOPPED_SERVICES+=("$svc")
      fi
    done
  else
    warn "online mode: qdrant/seaweedfs volumes are copied while running; use --consistent for a crash-consistent copy."
  fi
  # From here until the services are back up, any failure must still restart
  # them. Under `set -e` a failing tar used to exit with qdrant and seaweedfs
  # stopped - and upgrade.sh runs this *before* bringing the stack up, so a
  # failed backup aborted the upgrade leaving the host worse than it started,
  # silently.
  trap restart_stopped_services EXIT INT TERM
  for vol in "${DATA_VOLUMES[@]}"; do
    tar_volume "$vol" "$dest"
  done
  restart_stopped_services
  trap - EXIT INT TERM

  prune_old_backups "$BACKUP_KEEP"
  log "Backup complete: $dest"
  du -sh "$dest" | awk '{print "[backup] size: "$1}'
}

main "$@"
