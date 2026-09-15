#!/usr/bin/env bash
# install.sh pins a fresh host to the newest release tag (review B-24), which
# leaves a detached HEAD. This harness uses real local git repositories -- no
# network -- to check both halves of that:
#
#   * the tag picked is the newest by version, not by string order, and
#     pre-release tags are ignored;
#   * upgrading such a pinned checkout moves to the next release and never
#     fast-forwards onto the tip of main.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

fail() { echo "FAIL: $*" >&2; exit 1; }

# --- an "upstream" with three releases and extra commits on main -------------
UP="$TMP/upstream"
mkdir -p "$UP"
git -C "$UP" init -q -b main
echo v1 > "$UP/file"; git -C "$UP" add .; git -C "$UP" commit -qm v1
git -C "$UP" tag v1.2.0
echo v2 > "$UP/file"; git -C "$UP" commit -qam v2
git -C "$UP" tag v1.9.3
echo v3 > "$UP/file"; git -C "$UP" commit -qam v3
git -C "$UP" tag v1.10.0
git -C "$UP" tag v2.0.0-rc1          # pre-release: must be ignored
echo main-only > "$UP/file"; git -C "$UP" commit -qam "unreleased work on main"

# --- 1. install.sh resolves the newest release tag ---------------------------
resolved="$(
  ALPHAROUTER_GIT_URL="$UP" bash -c '
    source <(sed -n "/^bootstrap_latest_release_tag/,/^}/p" '"$REPO"'/scripts/install.sh)
    bootstrap_latest_release_tag
  '
)"
[ "$resolved" = "v1.10.0" ] || fail "install.sh picked '$resolved', expected v1.10.0"
echo "ok: newest release tag resolved (v1.10.0, not v1.9.3 or the rc)"

# --- 2. upgrading a pinned checkout stays on releases ------------------------
WORK="$TMP/work"
git -c advice.detachedHead=false clone -q --branch v1.9.3 --depth 1 "$UP" "$WORK"
[ "$(git -C "$WORK" rev-parse --abbrev-ref HEAD)" = "HEAD" ] || fail "clone of a tag should be detached"

OUT="$TMP/out"
(
  ROOT_DIR="$WORK"
  log() { echo "$*"; }
  warn() { echo "WARN: $*"; }
  # shellcheck source=../lib/stack.sh
  source "$REPO/scripts/lib/stack.sh"
  git_pull_ff_only
) > "$OUT" 2>&1 || { cat "$OUT"; fail "git_pull_ff_only errored on a pinned checkout"; }

now="$(git -C "$WORK" describe --tags --exact-match 2>/dev/null || echo none)"
[ "$now" = "v1.10.0" ] || { cat "$OUT"; fail "pinned checkout moved to '$now', expected v1.10.0"; }
[ "$(cat "$WORK/file")" = "v3" ] || fail "working tree is not the v1.10.0 content"
if grep -q "main-only" "$WORK/file"; then fail "pinned checkout followed main"; fi
echo "ok: pinned checkout upgraded v1.9.3 -> v1.10.0 and did not follow main"

# --- 3. already newest: no movement, no error --------------------------------
(
  ROOT_DIR="$WORK"
  log() { echo "$*"; }
  warn() { echo "WARN: $*"; }
  source "$REPO/scripts/lib/stack.sh"
  git_pull_ff_only
) > "$OUT" 2>&1 || { cat "$OUT"; fail "second upgrade errored"; }
grep -q "Already on the newest release (v1.10.0)" "$OUT" || { cat "$OUT"; fail "expected the no-op message"; }
echo "ok: a checkout already on the newest release is left alone"

# --- 4. a repository without release tags is left alone, loudly --------------
BARE="$TMP/untagged"
mkdir -p "$BARE"
git -C "$BARE" init -q -b main
echo x > "$BARE/file"; git -C "$BARE" add .; git -C "$BARE" commit -qm x
W2="$TMP/work2"
git clone -q --depth 1 "$BARE" "$W2"
git -C "$W2" checkout -q --detach HEAD
(
  ROOT_DIR="$W2"
  log() { echo "$*"; }
  warn() { echo "WARN: $*"; }
  source "$REPO/scripts/lib/stack.sh"
  git_pull_ff_only
) > "$OUT" 2>&1 || { cat "$OUT"; fail "untagged pinned checkout should not fail the upgrade"; }
grep -q "no release tag" "$OUT" || { cat "$OUT"; fail "expected a warning about the missing release tag"; }
echo "ok: untagged remote warns instead of pulling main"

echo "PASS: $(basename "$0")"
