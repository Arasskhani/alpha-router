#!/usr/bin/env bash
# Control-flow harness for scripts/backup.sh with a fake docker binary:
# verifies snapshot layout, MANIFEST, consistent-mode stop/start and pruning.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WORK="$TMP/work"
mkdir -p "$WORK/scripts" "$TMP/bin"
cp -a "$REPO/scripts/lib" "$REPO/scripts/backup.sh" "$WORK/scripts/"
cp "$REPO/docker-compose.yml" "$WORK/"
printf 'POSTGRES_USER=alpha_router\nPOSTGRES_DB=alpha_router\n' > "$WORK/.env"
CALLS="$TMP/calls"; : > "$CALLS"

cat > "$TMP/bin/docker" <<'FAKE'
#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
case "$1" in
  volume) exit 0 ;;
  image) echo sha256:deadbeef; exit 0 ;;
  run)
    # find "<host>:/backup" mount and the tgz name, create an empty archive there
    dest=""; name=""
    for a in "$@"; do
      case "$a" in
        *:/backup) dest="${a%%:/backup}" ;;
        *tar\ czf*) name="$(echo "$a" | sed -E 's/.*\/backup\/([^"]+)".*/\1/')" ;;
      esac
    done
    [ -n "$dest" ] && [ -n "$name" ] && tar czf "$dest/$name" -T /dev/null
    exit 0 ;;
  compose)
    shift; while [ "${1:-}" = -f ]; do shift 2; done
    case "$1" in
      ps) printf 'postgres\nqdrant\nseaweedfs\n'; exit 0 ;;
      exec)
        if [[ "$*" == *pg_isready* ]]; then exit 0; fi
        if [[ "$*" == *pg_dump* ]]; then printf 'PGDMP-fake'; exit 0; fi
        exit 0 ;;
      *) exit 0 ;;
    esac ;;
esac
exit 0
FAKE
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH" CALLS

pass=0; fail=0
check() { if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }

( cd "$WORK" && BACKUP_KEEP=2 bash scripts/backup.sh --consistent >/dev/null 2>&1 )
# shellcheck disable=SC2034  # used inside the eval strings below
snap="$(ls -d "$WORK"/backups/20* | head -1)"
check "snapshot directory created" '[ -d "$snap" ]'
check "db.dump written" '[ -s "$snap/db.dump" ]'
check ".env copied" '[ -f "$snap/.env" ]'
check "MANIFEST has git+images" 'grep -q "^image_alpha-router=" "$snap/MANIFEST" && grep -q "^consistent=1" "$snap/MANIFEST"'
check "three volume archives" '[ -f "$snap/alpha_router_qdrant.tgz" ] && [ -f "$snap/alpha_router_seaweedfs.tgz" ] && [ -f "$snap/alpha_router_tls.tgz" ]'
check "consistent: qdrant/seaweedfs stopped then started" 'grep -q "stop qdrant" "$CALLS" && grep -q "start qdrant seaweedfs" "$CALLS"'
check "postgres never stopped (it was running)" '! grep -q "stop postgres" "$CALLS" && ! grep -q "up -d --no-deps postgres" "$CALLS"'

# pruning: create two older fake snapshots, keep=2 -> only newest two remain
mkdir -p "$WORK/backups/20200101000000" "$WORK/backups/20200102000000"
( cd "$WORK" && BACKUP_KEEP=2 bash scripts/backup.sh >/dev/null 2>&1 )
check "prune keeps newest 2" '[ "$(ls -d "$WORK"/backups/20* | wc -l)" -eq 2 ] && [ ! -d "$WORK/backups/20200101000000" ]'

echo "pass=$pass fail=$fail"; [ "$fail" -eq 0 ]
