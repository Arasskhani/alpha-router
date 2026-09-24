#!/usr/bin/env bash
# Unit harness for merge_env_from_example (scripts/lib/env-merge.sh) and the
# installable-app switches. Run: bash scripts/tests/test-env-merge-pwa.sh
#
# An upgrade must add PWA_SERVICE_WORKER_ENABLED and PWA_INSTALL_PROMPT_ENABLED
# as true to a .env that predates them, and must keep an operator's false.
# shellcheck disable=SC2034 # values are read inside the check() eval strings
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export LOG_PREFIX=test

# shellcheck source=../lib/common.sh
source "$REPO/scripts/lib/common.sh"
# shellcheck source=../lib/env-merge.sh
source "$REPO/scripts/lib/env-merge.sh"
ENV_EXAMPLE="$REPO/.env.example"
ENV_FILE="$TMP/.env"

pass=0
fail=0
check() {
  if eval "$2"; then
    echo "PASS $1"; pass=$((pass + 1))
  else
    echo "FAIL $1"; fail=$((fail + 1))
  fi
}
value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2-; }
count() { grep -cE "^$1=" "$ENV_FILE" || true; }

# A .env from before the switches: both are added, on.
printf 'SECRET_KEY=keep-me\n' > "$ENV_FILE"
merge_env_from_example >/dev/null 2>&1
check "the service worker switch is added as true" '[ "$(value PWA_SERVICE_WORKER_ENABLED)" = true ]'
check "the install prompt switch is added as true" '[ "$(value PWA_INSTALL_PROMPT_ENABLED)" = true ]'
check "an existing value is untouched" '[ "$(value SECRET_KEY)" = keep-me ]'

# A second upgrade adds nothing twice.
merge_env_from_example >/dev/null 2>&1
check "a second merge does not repeat the keys" \
  '[ "$(count PWA_SERVICE_WORKER_ENABLED)" -eq 1 ] && [ "$(count PWA_INSTALL_PROMPT_ENABLED)" -eq 1 ]'

# An operator who switched them off keeps them off.
printf 'PWA_SERVICE_WORKER_ENABLED=false\nPWA_INSTALL_PROMPT_ENABLED=false\n' > "$ENV_FILE"
merge_env_from_example >/dev/null 2>&1
merge_env_from_example >/dev/null 2>&1
check "an explicit false for the service worker survives upgrades" \
  '[ "$(value PWA_SERVICE_WORKER_ENABLED)" = false ] && [ "$(count PWA_SERVICE_WORKER_ENABLED)" -eq 1 ]'
check "an explicit false for the install prompt survives upgrades" \
  '[ "$(value PWA_INSTALL_PROMPT_ENABLED)" = false ] && [ "$(count PWA_INSTALL_PROMPT_ENABLED)" -eq 1 ]'

echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
