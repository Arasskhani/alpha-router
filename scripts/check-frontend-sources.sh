#!/usr/bin/env bash
# Fail if compiled JavaScript twins are tracked under frontend/src.
#
# Why this exists: frontend/tsconfig.json sets "noEmit", so `tsc -b` only
# type-checks and never refreshes those .js files, while Vite's module
# resolution reaches a .js before the .ts/.tsx it shadows. A tracked twin
# therefore ships old code no matter how recently the TypeScript was edited --
# which is how a fix that exists in source can be missing from production.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tracked="$(git ls-files -- frontend/src | grep -E '\.js$' || true)"

if [ -z "$tracked" ]; then
  echo "OK: no compiled .js twins tracked under frontend/src."
  exit 0
fi

count="$(printf '%s\n' "$tracked" | grep -c . || true)"
{
  echo "ERROR: $count compiled .js file(s) are tracked under frontend/src."
  echo "They shadow their .ts/.tsx sources at build time and ship stale code."
  echo
  printf '  %s\n' $tracked
  echo
  echo "Remove them from the repository:"
  echo "  git rm -r --cached -- \$(git ls-files -- frontend/src | grep -E '\\.js\$')"
  echo "  find frontend/src -name '*.js' -delete"
  echo "(.gitignore already excludes frontend/src/**/*.js)"
} >&2
exit 1
