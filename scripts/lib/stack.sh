#!/usr/bin/env bash
# Shared compose start / health helpers for install.sh and upgrade.sh.

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
  # The app writes the first-boot admin password to a 0600 file inside the
  # container (never to its log). Print it once here, then remove the file.
  local marker="BOOTSTRAP_ADMIN_CREDENTIALS_ONCE" line creds
  line="$(compose logs alpha-router 2>&1 | grep "$marker" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    return 0
  fi
  creds="$(compose exec -T alpha-router sh -c 'cat /app/tls/bootstrap-admin.txt 2>/dev/null && rm -f /app/tls/bootstrap-admin.txt' 2>/dev/null || true)"
  if [ -z "$creds" ]; then
    printf '\n[%s] First-boot bootstrap administrator was created; the password is ADMIN_PASSWORD in .env.\n' "$LOG_PREFIX"
    return 0
  fi
  printf '\n[%s] First-boot bootstrap administrator (shown once; the file has been removed):\n' "$LOG_PREFIX"
  printf '%s\n' "$creds" | sed "s/^/[$LOG_PREFIX]   /"
  warn "Change this password after first login."
}

print_success() {
  local admin_user
  admin_user="$(env_value ADMIN_USERNAME 2>/dev/null || echo alpharouter)"

  write_install_lock_marker
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
  if [ "${UPGRADE:-0}" -eq 1 ]; then
    merge_env_from_example
  fi
  bootstrap_env_file
  apply_deploy_mode
  if [ -n "${IMAGE_TAG:-}" ]; then
    set_env_var ALPHAROUTER_IMAGE_TAG "$IMAGE_TAG"
  fi
  if [ "$DEPLOY_MODE" = "prod" ]; then
    run_python_production_check
  fi
}

# Keep the images that are running right now reachable as <image>:prev so
# scripts/restore.sh --previous-images can bring the pre-upgrade code back.
tag_previous_images() {
  local img
  for img in alpha-router alpha-router-sandbox alpha-router-sandbox-broker alpha-router-edge; do
    if docker image inspect "${img}:latest" >/dev/null 2>&1; then
      docker tag "${img}:latest" "${img}:prev"
    fi
  done
  log "Tagged current images as :prev (rollback: ./scripts/restore.sh <snapshot> --previous-images)."
}

# Snapshot before anything is rebuilt or migrated. Set SKIP_BACKUP=1 to opt out
# (e.g. on a fresh host or when a backup was just taken by hand).
backup_before_upgrade() {
  if [ "${SKIP_BACKUP:-0}" -eq 1 ]; then
    warn "SKIP_BACKUP=1: no pre-upgrade snapshot will be taken."
    return 0
  fi
  if ! docker volume inspect alpha_router_pg >/dev/null 2>&1; then
    log "No database volume yet; skipping pre-upgrade backup."
    return 0
  fi
  log "Taking a pre-upgrade snapshot (./scripts/backup.sh --consistent)..."
  LOG_PREFIX=backup "$ROOT_DIR/scripts/backup.sh" --consistent
}

start_stack() {
  if [ "${FROM_REGISTRY:-0}" -eq 1 ]; then
    require_registry_config
    registry_login_if_configured
    log "Pulling images from registry..."
    compose pull
    log "Starting stack (volumes are kept)..."
    compose up -d
    return 0
  fi

  if [ "${SKIP_BUILD:-0}" -eq 1 ]; then
    log "Starting stack (no rebuild; volumes are kept)..."
    compose up -d
  else
    log "Building and starting stack (this may take several minutes; volumes are kept)..."
    compose up --build -d
  fi
}

backup_env_file() {
  local stamp dest
  [ -f "$ROOT_DIR/.env" ] || return 0
  stamp="$(date +%Y%m%d%H%M%S)"
  dest="$ROOT_DIR/.env.bak.${stamp}"
  cp -a "$ROOT_DIR/.env" "$dest"
  chmod 600 "$dest" 2>/dev/null || true
  log "Backed up .env to $dest"
  # These copies hold every secret; keep only the five newest.
  find "$ROOT_DIR" -maxdepth 1 -name '.env.bak.*' -type f | sort | head -n -5 | while read -r old; do
    rm -f "$old"
  done
}

deploy_mode_from_env() {
  local env_mode
  env_mode="$(env_value ENVIRONMENT || true)"
  if [ "$env_mode" = "production" ]; then
    printf '%s' prod
  else
    printf '%s' dev
  fi
}

git_pull_ff_only() {
  if [ ! -d "$ROOT_DIR/.git" ]; then
    log "Not a git checkout; skipping git pull (source was copied)."
    return 0
  fi
  if ! command -v git >/dev/null 2>&1; then
    warn "git is not installed; skipping pull. Install git or copy an updated source tree."
    return 0
  fi
  local branch remote
  branch="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD)"
  remote="origin"
  log "Fetching and fast-forwarding $branch..."
  git -C "$ROOT_DIR" fetch --prune "$remote"
  if git -C "$ROOT_DIR" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    git -C "$ROOT_DIR" pull --ff-only
  else
    log "No upstream set for $branch; pulling $remote/$branch."
    git -C "$ROOT_DIR" pull --ff-only "$remote" "$branch"
    git -C "$ROOT_DIR" branch --set-upstream-to="$remote/$branch" "$branch" || true
  fi
}
