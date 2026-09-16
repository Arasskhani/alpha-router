#!/usr/bin/env bash
# Unit harness for show_bootstrap_admin_credentials (scripts/lib/stack.sh).
# compose is replaced by a shell function; nothing touches a real host.
# Run: bash scripts/tests/test-bootstrap-admin-display.sh
#
# The bug this covers: the installer printed the container's copy of the
# password rather than the ADMIN_PASSWORD it had just written to .env. On one
# install the printed value came out two characters longer than the real one,
# so the operator was locked out of a brand-new deployment and had to read
# .env by hand. .env is the source of truth and is what must be shown.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export LOG_PREFIX=test

# shellcheck source=../lib/common.sh
source "$REPO/scripts/lib/common.sh"
# shellcheck source=../lib/env-bootstrap.sh
source "$REPO/scripts/lib/env-bootstrap.sh"
ENV_FILE="$TMP/.env"
# shellcheck source=../lib/stack.sh
source "$REPO/scripts/lib/stack.sh"

REAL_PASSWORD=1ae3f6d502263084e7a3ef41c587fb7c

# compose logs -> the marker; compose exec -> whatever FILE_BODY says.
compose() {
  case "$1" in
    logs) [ "${MARKER:-1}" = 1 ] && echo "... BOOTSTRAP_ADMIN_CREDENTIALS_ONCE username=alpharouter"; return 0 ;;
    exec) printf '%s' "${FILE_BODY:-}"; return 0 ;;
  esac
  return 0
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

write_env() {
  {
    echo "ADMIN_USERNAME=${1:-alpharouter}"
    echo "ADMIN_PASSWORD=$REAL_PASSWORD"
  } > "$ENV_FILE"
}

# 1. Agreement: the .env password is printed, exactly once, unquoted.
write_env
FILE_BODY="username=alpharouter
password=$REAL_PASSWORD
"
out="$(show_bootstrap_admin_credentials 2>/dev/null)"
check "prints the password from .env" \
  'grep -qx "\[test\]   password=$REAL_PASSWORD" <<< "$out"'
check "prints the username from .env" \
  'grep -qx "\[test\]   username=alpharouter" <<< "$out"'
check "no mismatch warning when the two agree" \
  '! show_bootstrap_admin_credentials 2>&1 >/dev/null | grep -q "does not match"'

# 2. The reported failure: the container copy has two extra characters.
#    .env must still be what is shown, and the difference must be reported.
write_env
FILE_BODY="username=alpharouter
password=${REAL_PASSWORD}XY
"
out="$(show_bootstrap_admin_credentials 2>/dev/null)"
err="$(show_bootstrap_admin_credentials 2>&1 >/dev/null)"
check "a corrupted copy does not become the printed password" \
  'grep -qx "\[test\]   password=$REAL_PASSWORD" <<< "$out"'
check "the mismatch is reported with both lengths" \
  'grep -q "does not match" <<< "$err" && grep -q "34 vs 32" <<< "$err"'
check "the other value is offered rather than hidden" \
  'grep -q "${REAL_PASSWORD}XY" <<< "$err"'

# 3. A carriage return from `compose exec` is not a mismatch.
write_env
FILE_BODY="$(printf 'username=alpharouter\r\npassword=%s\r\n' "$REAL_PASSWORD")"
check "CRLF in the container copy is tolerated" \
  '! show_bootstrap_admin_credentials 2>&1 >/dev/null | grep -q "does not match"'

# 4. No marker in the logs: this is not a first boot, so say nothing at all.
write_env
MARKER=0
out="$(show_bootstrap_admin_credentials 2>/dev/null)"
check "silent when no bootstrap admin was created" '[ -z "$out" ]'
MARKER=1

# 5. Unreadable .env: point at .env rather than fall back to the copy we
#    just decided not to trust.
: > "$ENV_FILE"
FILE_BODY="username=alpharouter
password=${REAL_PASSWORD}XY
"
out="$(show_bootstrap_admin_credentials 2>/dev/null)"
check "never prints the copy when .env cannot be read" \
  '! grep -q "${REAL_PASSWORD}XY" <<< "$out" && grep -q "ADMIN_PASSWORD in .env" <<< "$out"'

echo "---- $pass passed, $fail failed"
[ "$fail" -eq 0 ]
