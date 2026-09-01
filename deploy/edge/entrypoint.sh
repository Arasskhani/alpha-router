#!/bin/sh
# TLS edge for Alpharouter. Watches the shared volume written by the app and
# keeps nginx in sync with the desired HTTPS state chosen in Security Settings.
set -eu

TLS_DIR="${TLS_DIR:-/etc/alpha-router/tls}"
STATE="$TLS_DIR/desired-state.json"
STATUS="$TLS_DIR/apply-status.json"
SOURCE_CONF="$TLS_DIR/nginx.conf"
EFFECTIVE_CONF="/tmp/nginx.conf"
POLL_SECONDS="${TLS_POLL_SECONDS:-5}"

json_field() {
  key="$1"
  file="$2"
  grep -o "\"$key\":[[:space:]]*[^,}]*" "$file" 2>/dev/null | head -n 1 | awk -F: '{print $2}' | tr -d ' "'
}

# The healthcheck runs as a separate process, so it reads state from disk only.
if [ "${1:-}" = "--healthcheck" ]; then
  [ -f "$STATE" ] || exit 0
  [ "$(json_field enabled "$STATE" || true)" = "true" ] || exit 0
  [ -f /run/nginx.pid ] || exit 1
  kill -0 "$(cat /run/nginx.pid)" 2>/dev/null || exit 1
  [ "$(json_field ok "$STATUS" || true)" = "true" ] || exit 1
  exit 0
fi

NGINX_PID=""
LAST_GEN=""
FAILED_GEN=""
FAIL_COUNT=0

write_status() {
  gen="$1"
  ok="$2"
  msg="$3"
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  escaped="$(printf '%s' "$msg" | tr -d '"' | tr '\n' ' ')"
  printf '{"generation":%s,"ok":%s,"error":"%s","applied_at":"%s"}\n' \
    "${gen:-0}" "$ok" "$escaped" "$ts" > "$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}

nginx_alive() {
  [ -n "$NGINX_PID" ] && kill -0 "$NGINX_PID" 2>/dev/null
}

stop_nginx() {
  if nginx_alive; then
    kill -QUIT "$NGINX_PID" 2>/dev/null || true
    i=0
    while nginx_alive && [ "$i" -lt 20 ]; do
      sleep 1
      i=$((i + 1))
    done
    kill -KILL "$NGINX_PID" 2>/dev/null || true
  fi
  NGINX_PID=""
}

shutdown() {
  stop_nginx
  exit 0
}
trap shutdown TERM INT

# Hosts without IPv6 cannot bind [::]; nginx -t still passes but the listener
# fails at runtime, so those directives are dropped from the effective config.
render_effective_conf() {
  if [ -f /proc/net/if_inet6 ]; then
    cp "$SOURCE_CONF" "$EFFECTIVE_CONF"
  else
    sed '/listen[[:space:]]*\[::\]/d' "$SOURCE_CONF" > "$EFFECTIVE_CONF"
  fi
}

apply_enabled() {
  gen="$1"
  if [ ! -f "$SOURCE_CONF" ]; then
    return 1
  fi
  render_effective_conf
  if ! nginx -t -c "$EFFECTIVE_CONF" 2>/tmp/nginx-test.log; then
    LAST_ERROR="$(tail -n 3 /tmp/nginx-test.log 2>/dev/null || echo 'nginx -t failed')"
    return 1
  fi
  if nginx_alive; then
    kill -HUP "$NGINX_PID"
  else
    nginx -c "$EFFECTIVE_CONF" -g 'daemon off;' &
    NGINX_PID=$!
    sleep 2
    if ! nginx_alive; then
      NGINX_PID=""
      LAST_ERROR="nginx exited immediately after start"
      return 1
    fi
  fi
  write_status "$gen" true ""
  return 0
}

while true; do
  if [ -f "$STATE" ]; then
    enabled="$(json_field enabled "$STATE" || true)"
    gen="$(json_field generation "$STATE" || true)"
    if [ -n "$gen" ] && [ "$gen" != "$LAST_GEN" ]; then
      if [ "$enabled" = "true" ]; then
        LAST_ERROR="unknown error"
        if apply_enabled "$gen"; then
          LAST_GEN="$gen"
          FAILED_GEN=""
          FAIL_COUNT=0
        else
          # Report once per generation, then back off instead of rewriting the
          # status file on every poll.
          if [ "$FAILED_GEN" != "$gen" ]; then
            FAILED_GEN="$gen"
            FAIL_COUNT=0
            write_status "$gen" false "$LAST_ERROR"
          fi
          FAIL_COUNT=$((FAIL_COUNT + 1))
          if [ "$FAIL_COUNT" -ge 6 ]; then
            sleep 55
          fi
        fi
      else
        stop_nginx
        write_status "$gen" true ""
        LAST_GEN="$gen"
        FAILED_GEN=""
      fi
    fi
  fi

  # A crashed worker set must not leave the container silently idle; exiting
  # lets Docker restart the edge and reapply the current generation.
  if [ -n "$NGINX_PID" ] && ! nginx_alive; then
    write_status "$LAST_GEN" false "nginx exited unexpectedly"
    exit 1
  fi

  sleep "$POLL_SECONDS"
done
