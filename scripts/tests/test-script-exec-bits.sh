#!/usr/bin/env bash
# Anything the documentation tells an operator to run as `./scripts/x.sh` has
# to be committed executable, or that command fails with "Permission denied" on
# every fresh checkout.
#
# It did. None of the scripts carried the bit, so operators chmod'd them by hand
# on each host -- an untracked local change that then blocked `git reset`, and
# that came back the moment the checkout was restored. The permission belongs in
# the repository, not in each administrator's shell history.
#
# Sourced libraries (scripts/lib/*.sh) and the harnesses CI runs as `bash <file>`
# are deliberately left non-executable: they are not entry points.
# shellcheck disable=SC2034 # values are read inside the check() eval strings
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

fail() { echo "FAIL: $*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 0; }
[ -d "$REPO/.git" ] || { echo "SKIP: not a git checkout"; exit 0; }

# Every ./scripts/<name>.sh the docs ask a human to execute.
mapfile -t documented < <(
  grep -rhoE '(^|[^[:alnum:]_/])\./scripts/[a-zA-Z0-9_/-]+\.sh' README.md CONTRIBUTING.md 2>/dev/null \
    | grep -oE '\./scripts/[a-zA-Z0-9_/-]+\.sh' \
    | sed 's|^\./||' \
    | sort -u
)

[ "${#documented[@]}" -gt 0 ] || fail "found no documented entry points; the scraper is broken"
echo "documented entry points: ${#documented[@]}"

missing=()
for f in "${documented[@]}"; do
  [ -f "$f" ] || fail "$f is documented but does not exist"
  mode="$(git ls-files -s -- "$f" | awk '{print $1}')"
  [ -n "$mode" ] || fail "$f is not tracked by git"
  if [ "$mode" != "100755" ]; then
    missing+=("$f (mode $mode)")
  fi
  head -1 "$f" | grep -q '^#!' || fail "$f is executable but has no shebang"
done

if [ "${#missing[@]}" -gt 0 ]; then
  printf 'FAIL: documented entry points are not committed executable:\n' >&2
  printf '  %s\n' "${missing[@]}" >&2
  printf 'Fix with: git update-index --chmod=+x <file>\n' >&2
  exit 1
fi
echo "ok: every documented entry point is committed executable, with a shebang"

# The other side: sourced libraries are not entry points and must stay plain.
while read -r mode _ _ path; do
  [ "$mode" = "100755" ] && fail "$path is a sourced library and should not be executable"
done < <(git ls-files -s -- 'scripts/lib/*.sh')
echo "ok: sourced libraries are left non-executable"

echo "PASS: test-script-exec-bits.sh"
