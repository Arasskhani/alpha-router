#!/usr/bin/env bash
# restore.sh --previous-images can only roll back to images that were tagged
# :prev on the way up. upgrade.sh tagged them for a source build only, so a
# --from-registry or --skip-build upgrade left no :prev at all and the
# documented rollback silently kept the new code.
#
# Real bash, fake docker: assert every upgrade mode tags :prev before the stack
# is started.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0
check() { if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }

# upgrade.sh sources lib/stack.sh for tag_previous_images; drive that directly
# and assert the call site is reached for each mode, without running a real
# upgrade (which pulls, builds and migrates).
run_mode() {
  local from_source="$1" skip_build="$2" calls="$3"
  cat > "$TMP/probe.sh" <<PROBE
set -euo pipefail
FROM_SOURCE=$from_source
SKIP_BUILD=$skip_build
tag_previous_images() { echo "tagged" >> "$calls"; }
$(sed -n '/^  backup_before_upgrade$/,/^  export_app_version$/p' "$REPO/scripts/upgrade.sh" \
  | grep -v '^  backup_before_upgrade$' | grep -v '^  export_app_version$')
PROBE
  bash "$TMP/probe.sh"
}

for mode in "1 0 source-build" "0 0 from-registry" "1 1 skip-build" "0 1 registry-skip-build"; do
  set -- $mode
  calls="$TMP/calls-$3"; : > "$calls"
  run_mode "$1" "$2" "$calls"
  check "$3 tags :prev" '[ -s "$calls" ]'
done

# And the helper itself only tags images that exist.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'FAKE'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_CALLS"
if [ "$1" = image ] && [ "$2" = inspect ]; then
  case "$3" in
    alpha-router:latest|alpha-router-edge:latest) exit 0 ;;
    *) exit 1 ;;
  esac
fi
exit 0
FAKE
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH"
DOCKER_CALLS="$TMP/docker-calls"; : > "$DOCKER_CALLS"; export DOCKER_CALLS

(
  ROOT_DIR="$TMP"
  # shellcheck source=../lib/common.sh
  source "$REPO/scripts/lib/common.sh"
  # shellcheck source=../lib/stack.sh
  source "$REPO/scripts/lib/stack.sh"
  tag_previous_images >/dev/null 2>&1
)

check "tags the images that exist" 'grep -q "docker tag alpha-router:latest alpha-router:prev" "$DOCKER_CALLS" && grep -q "docker tag alpha-router-edge:latest alpha-router-edge:prev" "$DOCKER_CALLS"'
check "skips the images that do not" '! grep -q "docker tag alpha-router-sandbox:latest" "$DOCKER_CALLS"'

echo "pass=$pass fail=$fail"; [ "$fail" -eq 0 ]
