#!/usr/bin/env bash
# The sandbox broker downloads a static Docker CLI tarball and installs it.
# TLS proves who served it, not what it is, so the Dockerfile must pin the
# tarball's sha256 and check it before extracting - and the pin must be a real
# digest, not the placeholder the patch shipped with.
# shellcheck disable=SC2034 # values are read inside the check() eval strings
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOCKERFILE="$REPO/sandbox-broker/Dockerfile"
pass=0; fail=0
check() { if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }

sha="$(sed -nE 's/^ARG DOCKER_CLI_SHA256=(.*)$/\1/p' "$DOCKERFILE" | head -1)"

check "the Dockerfile declares DOCKER_CLI_SHA256" '[ -n "$sha" ]'
check "the pin is a 64-digit hex digest, not a placeholder" '[[ "$sha" =~ ^[0-9a-f]{64}$ ]]'
check "the download is checked before it is extracted" \
  'grep -qE "sha256sum -c" "$DOCKERFILE" && [ "$(grep -nE "sha256sum -c" "$DOCKERFILE" | cut -d: -f1)" -lt "$(grep -nE "tar -xzf /tmp/docker.tgz" "$DOCKERFILE" | cut -d: -f1)" ]'

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
