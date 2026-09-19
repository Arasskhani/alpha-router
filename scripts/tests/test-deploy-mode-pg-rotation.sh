#!/usr/bin/env bash
# Unit harness for rotate_postgres_password (scripts/lib/deploy-mode.sh).
# docker/compose are replaced by shell functions; nothing touches a real host.
# Run: bash scripts/tests/test-deploy-mode-pg-rotation.sh
# shellcheck disable=SC2034 # values are read inside the check() eval strings
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export ENV_FILE="$TMP/.env"
export LOG_PREFIX=test

# shellcheck source=../lib/common.sh
source "$REPO/scripts/lib/common.sh"
# shellcheck source=../lib/env-bootstrap.sh
source "$REPO/scripts/lib/env-bootstrap.sh"
# shellcheck source=../lib/deploy-mode.sh
source "$REPO/scripts/lib/deploy-mode.sh"

# The header above promises this touches no real host. It did not hold:
# env-bootstrap.sh assigned ENV_FILE unconditionally, so sourcing it threw away
# the export on line 10 and every write below landed on $REPO/.env -- which on
# a machine with a live install meant the real file was truncated and its
# POSTGRES_PASSWORD replaced. Assert the promise instead of restating it.
[ "$ENV_FILE" = "$TMP/.env" ] || {
  echo "REFUSING TO RUN: ENV_FILE is $ENV_FILE, not $TMP/.env" >&2
  exit 1
}

CALLS="$TMP/calls"
: > "$CALLS"

docker() {
  echo "docker $*" >> "$CALLS"
  if [ "$1 $2" = "volume inspect" ]; then
    [ "${VOL_EXISTS:-0}" = 1 ]
    return
  fi
  return 0
}

compose() {
  echo "compose $*" >> "$CALLS"
  case "$1" in
    ps) [ "${PG_RUNNING:-0}" = 1 ] && echo postgres; return 0 ;;
    exec)
      if [[ "$*" == *pg_isready* ]]; then return 0; fi
      if [[ "$*" == *"ALTER ROLE"* ]]; then [ "${ALTER_OK:-1}" = 1 ]; return; fi
      ;;
    up|stop) return 0 ;;
  esac
}

pass=0
fail=0
check() {
  if eval "$2"; then
    echo "PASS $1"; pass=$((pass + 1))
  else
    echo "FAIL $1"; fail=$((fail + 1))
  fi
}

# 1. fresh install: no volume -> rotate .env only, never talk to compose
echo "POSTGRES_PASSWORD=changeme" > "$ENV_FILE"; VOL_EXISTS=0
out="$(rotate_postgres_password 2>/dev/null)"
check "fresh install rotates .env without compose" \
  '[ ${#out} -eq 48 ] && ! grep -q compose "$CALLS" && grep -q "POSTGRES_PASSWORD=$out" "$ENV_FILE"'

# 2. operator-chosen secret is never touched, even with a volume present
: > "$CALLS"; echo "POSTGRES_PASSWORD=s3cretlongvalue" > "$ENV_FILE"; VOL_EXISTS=1
out="$(rotate_postgres_password 2>/dev/null)"
check "operator secret untouched" '[ "$out" = s3cretlongvalue ] && ! grep -q docker "$CALLS"'

# 3. the reported bug: --dev install (changeme) + existing volume + --prod
: > "$CALLS"; echo "POSTGRES_PASSWORD=changeme" > "$ENV_FILE"; VOL_EXISTS=1; PG_RUNNING=1; ALTER_OK=1
out="$(rotate_postgres_password 2>/dev/null)"
check "existing volume: ALTER ROLE runs, then .env follows" \
  '[ ${#out} -eq 48 ] && grep -q "ALTER ROLE" "$CALLS" && ! grep -q "compose up" "$CALLS" && grep -q "POSTGRES_PASSWORD=$out" "$ENV_FILE"'

# 4. postgres not running: only the postgres service is started first
: > "$CALLS"; echo "POSTGRES_PASSWORD=alpha_router" > "$ENV_FILE"; VOL_EXISTS=1; PG_RUNNING=0; ALTER_OK=1
out="$(rotate_postgres_password 2>/dev/null)"
check "postgres down: started with --no-deps before ALTER" \
  '[ ${#out} -eq 48 ] && grep -q "compose up -d --no-deps postgres" "$CALLS" && grep -q "ALTER ROLE" "$CALLS"'

# 5. ALTER fails: abort loudly and leave .env exactly as it was
: > "$CALLS"; echo "POSTGRES_PASSWORD=changeme" > "$ENV_FILE"; VOL_EXISTS=1; PG_RUNNING=1; ALTER_OK=0
# die() exits; the subshell of $(...) contains that so the harness continues.
if out="$(rotate_postgres_password 2>/dev/null)"; then
  check "ALTER failure aborts (got: $out)" false
else
  check "ALTER failure aborts and leaves .env untouched" 'grep -q "POSTGRES_PASSWORD=changeme" "$ENV_FILE"'
fi

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
