#!/usr/bin/env bash
# The commit-msg hook accepts our history and rejects the classic mistakes.
# shellcheck disable=SC2034 # values are read inside the check() eval strings
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
pass=0; fail=0
expect() { # expect <0|1> <message>
  printf '%s\n' "$2" > "$tmp"
  if python3 scripts/check-commit-message.py "$tmp" >/dev/null; then got=0; else got=1; fi
  if [ "$got" = "$1" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL (expected $1): $2"; fi
}
expect 0 "fix(budget): count budget_hold_leak when a settlement gives up"
expect 0 "style(backend): ruff format — no code change"
expect 0 "refactor!: drop the legacy bearer path"
expect 0 "perf(redis): one shared asyncio client per worker"
expect 0 "Merge branch 'main' into fix/x"
expect 0 "fixup! fix(chat): something"
expect 1 "Update3"
expect 1 "fixed the bug"
expect 1 "fix: Add a thing"
expect 1 "fix(chat): trailing period."
expect 1 "feat(scope): $(printf 'x%.0s' $(seq 1 120))"
expect 1 "$(printf 'fix: two lines\nbody without blank line')"
echo "commit-message: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
