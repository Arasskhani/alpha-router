#!/usr/bin/env bash
# Type-check the backend against the committed baseline.
#   scripts/mypy-check.sh          -> fail on errors not in backend/mypy-baseline.txt
#   scripts/mypy-check.sh --sync   -> rewrite the baseline (after fixing errors; it may only shrink)
set -euo pipefail
cd "$(dirname "$0")/../backend"
mode="${1:-filter}"
case "$mode" in
  --sync) (mypy app || true) | mypy-baseline sync --baseline-path mypy-baseline.txt --sort-baseline ;;
  *)      (mypy app || true) | mypy-baseline filter --baseline-path mypy-baseline.txt --sort-baseline --no-colors ;;
esac
