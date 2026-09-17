#!/usr/bin/env bash
# resolve_app_version derives the running version from the git tag (the same
# tag install.sh/upgrade.sh already use to decide which code to deploy), and
# Docker bakes it into the image as a build arg.
#
# This harness uses real local repositories -- no network, no Docker -- to check
# that it says the right thing in each state a real checkout can be in, and in
# particular that it never invents a version it does not have.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

fail() { echo "FAIL: $*" >&2; exit 1; }

# stack.sh expects these from the scripts that source it.
# shellcheck disable=SC2034  # read by resolve_app_version's default argument
ROOT_DIR="$REPO"
log() { :; }
warn() { :; }
die() { echo "die: $*" >&2; exit 1; }
# shellcheck source=/dev/null
. "$REPO/scripts/lib/stack.sh"

new_repo() {
  local dir="$1"
  mkdir -p "$dir"
  git -C "$dir" init -q -b main
  echo one > "$dir/file"
  git -C "$dir" add .
  git -C "$dir" commit -qm one
}

# --- on an exact release tag -------------------------------------------------
A="$TMP/tagged"; new_repo "$A"; git -C "$A" tag v1.0.1
got="$(resolve_app_version "$A")"
[ "$got" = "v1.0.1" ] || fail "exact tag: expected v1.0.1, got '$got'"
echo "ok: a checkout on a release tag reports that tag"

# --- past the tag on a branch ------------------------------------------------
echo two > "$A/file"; git -C "$A" commit -qam two
got="$(resolve_app_version "$A")"
case "$got" in
  v1.0.1-1-g*) echo "ok: commits past the tag report the distance ($got)" ;;
  *) fail "past tag: expected v1.0.1-1-g..., got '$got'" ;;
esac

# --- uncommitted changes -----------------------------------------------------
echo dirty >> "$A/file"
got="$(resolve_app_version "$A")"
case "$got" in
  *-dirty) echo "ok: an uncommitted change is marked dirty ($got)" ;;
  *) fail "dirty tree: expected a -dirty suffix, got '$got'" ;;
esac
git -C "$A" checkout -q -- file

# --- a repo with no tag at all -----------------------------------------------
B="$TMP/untagged"; new_repo "$B"
got="$(resolve_app_version "$B")"
case "$got" in
  g*) echo "ok: a tagless repo names the commit instead of inventing a version ($got)" ;;
  *) fail "untagged: expected g<sha>, got '$got'" ;;
esac

# --- a non-release tag must not be picked up ---------------------------------
C="$TMP/othertag"; new_repo "$C"; git -C "$C" tag nightly-2026-09-17
got="$(resolve_app_version "$C")"
case "$got" in
  g*) echo "ok: a non-release tag is ignored, as in latest_release_tag ($got)" ;;
  *) fail "non-release tag: expected g<sha>, got '$got'" ;;
esac

# --- not a git checkout at all -----------------------------------------------
D="$TMP/plain"; mkdir -p "$D"; echo x > "$D/file"
got="$(resolve_app_version "$D")"
[ -z "$got" ] || fail "no git: expected empty, got '$got'"
echo "ok: a source tree with no .git reports nothing, so the app says unknown"

# --- the revision is the full commit ----------------------------------------
got="$(resolve_app_revision "$A")"
[ "${#got}" -eq 40 ] || fail "revision: expected a 40-char sha, got '$got'"
[ "$got" = "$(git -C "$A" rev-parse HEAD)" ] || fail "revision: does not match HEAD"
echo "ok: the revision is the full commit the image was built from"

echo "PASS: test-app-version.sh"
