#!/usr/bin/env bash
# Every third-party image in docker-compose.yml must name a minor version. A floating major tag re-resolves silently on
# every pull: redis:7-alpine became a 7.4 that is no longer BSD-licensed
# without anybody changing a line in this repository. Reproducibility and the
# licence position both depend on the tag not moving under us; Renovate bumps
# the pins on a schedule, with a review.
#
# Our own images (alpha-router*, built from this tree) are exempt: their tag is
# the git version, stamped at build time. CI runner images are out of scope -
# they are not deployed - but the PostgreSQL the tests run against must be the
# PostgreSQL the product ships with, so that one is held equal to compose.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
pass=0; fail=0
check() { if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }

# image references: "image: repo:tag" in compose
refs() {
  grep -hoE '^\s*image:\s*\S+' "$REPO/docker-compose.yml" \
    | sed -E 's/^\s*image:\s*//' \
    | grep -v '^alpha-router' \
    | sort -u
}

pinned_to_minor() {
  # repo:tag where tag contains X.Y (digits.digits) or is a full version like v1.19.0
  local ref="$1" tag
  tag="${ref##*:}"
  [[ "$ref" == *:* ]] || return 1
  [[ "$tag" =~ ^v?[0-9]+\.[0-9]+ ]]
}

while read -r ref; do
  [ -n "$ref" ] || continue
  check "$ref names a minor version" 'pinned_to_minor "$ref"'
done < <(refs)

# The specific case that motivated this file.
redis_ref="$(grep -oE 'image:\s*redis:\S+' "$REPO/docker-compose.yml" | sed -E 's/image:\s*//')"
check "redis stays on the 7.2 line (last BSD release)" '[[ "$redis_ref" =~ ^redis:7\.2 ]]'

# Test against what you deploy: the CI service image for PostgreSQL must be the
# compose one.
compose_pg="$(grep -oE 'image:\s*postgres:\S+' "$REPO/docker-compose.yml" | sed -E 's/image:\s*//' | sort -u)"
ci_pg="$(grep -oE 'name:\s*postgres:\S+' "$REPO/.gitlab-ci.yml" | sed -E 's/name:\s*//' | sort -u)"
check "CI tests run against the PostgreSQL compose deploys ($compose_pg)" '[ -n "$ci_pg" ] && [ "$ci_pg" = "$compose_pg" ]'

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
