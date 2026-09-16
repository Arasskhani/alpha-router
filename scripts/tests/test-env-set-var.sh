#!/usr/bin/env bash
# Unit harness for set_env_var / env_value (scripts/lib/env-bootstrap.sh).
# Run: bash scripts/tests/test-env-set-var.sh
#
# The bug this covers: the value was handed to awk with -v, which processes
# escape sequences. Any secret or path containing a backslash was silently
# stored as something else, and a "\n" truncated the value and injected a bogus
# line into .env.
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

pass=0
fail=0
check() {
  if eval "$2"; then
    echo "PASS $1"; pass=$((pass + 1))
  else
    echo "FAIL $1"; fail=$((fail + 1))
  fi
}

roundtrip() {
  printf 'OTHER=keep\nADMIN_PASSWORD=admin\nTRAILING=keep\n' > "$ENV_FILE"
  set_env_var ADMIN_PASSWORD "$1"
  env_value ADMIN_PASSWORD
}

# A backslash must survive. Each of these used to come back as something else.
for v in 'abc\tdef' 'a\nb' 'p\\q' 'C:\Users\alpha' 'end\'; do
  got="$(roundtrip "$v")"
  check "stored verbatim: $(printf '%q' "$v")" '[ "$got" = "$v" ]'
done

# ... and must not disturb the rest of the file.
roundtrip 'a\nb' >/dev/null
check "a backslash-n value does not add lines to .env" '[ "$(wc -l < "$ENV_FILE")" -eq 3 ]'
check "neighbouring keys are untouched" \
  '[ "$(env_value OTHER)" = keep ] && [ "$(env_value TRAILING)" = keep ]'

# The ordinary cases still work.
hex=1ae3f6d502263084e7a3ef41c587fb7c
got="$(roundtrip "$hex")"
check "a generated hex secret round-trips" '[ "$got" = "$hex" ]'
check "the key is replaced in place, not appended" \
  '[ "$(grep -c "^ADMIN_PASSWORD=" "$ENV_FILE")" -eq 1 ]'

# A missing key is appended.
printf 'OTHER=keep\n' > "$ENV_FILE"
set_env_var NEW_KEY 'v\1'
check "a missing key is appended verbatim" '[ "$(env_value NEW_KEY)" = "v\1" ]'

# A key is matched literally, not as a regex, and only at the start of a line.
printf 'A.B=one\nAXB=two\nPREFIX_ADMIN_PASSWORD=three\nADMIN_PASSWORD=four\n' > "$ENV_FILE"
set_env_var ADMIN_PASSWORD five
check "a longer key ending in the same name is not overwritten" \
  '[ "$(env_value PREFIX_ADMIN_PASSWORD)" = three ]'
set_env_var "A.B" six
check "a dot in a key is literal, not any-character" \
  '[ "$(env_value AXB)" = two ]'

echo "---- $pass passed, $fail failed"
[ "$fail" -eq 0 ]
