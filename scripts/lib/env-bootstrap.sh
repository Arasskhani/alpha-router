#!/usr/bin/env bash
# Create or patch .env with secrets required by docker-compose.yml.

ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"

env_value() {
  local key="$1"
  if [ ! -f "$ENV_FILE" ]; then
    return 1
  fi
  local line
  line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  [ -n "$line" ] || return 1
  printf '%s' "${line#*=}"
}

set_env_var() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    awk -v k="$key" -v v="$value" '
      BEGIN { done = 0 }
      $0 ~ "^" k "=" {
        print k "=" v
        done = 1
        next
      }
      { print }
      END { if (!done) print k "=" v }
    ' "$ENV_FILE" >"$tmp"
  else
    cp "$ENV_FILE" "$tmp"
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
  fi
  mv "$tmp" "$ENV_FILE"
}

bootstrap_env_file() {
  if [ ! -f "$ENV_EXAMPLE" ]; then
    die ".env.example not found at $ENV_EXAMPLE"
  fi

  if [ ! -f "$ENV_FILE" ]; then
    log "Creating .env from .env.example..."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
  else
    log "Using existing .env (will only fill missing required secrets)."
  fi

  local sandbox_token
  sandbox_token="$(env_value SANDBOX_BROKER_TOKEN || true)"
  if [ -z "$sandbox_token" ]; then
    sandbox_token="$(rand_hex 32)"
    set_env_var SANDBOX_BROKER_TOKEN "$sandbox_token"
    log "Generated SANDBOX_BROKER_TOKEN."
  fi

  local code_token
  code_token="$(env_value CODE_SANDBOX_BROKER_TOKEN || true)"
  if [ -z "$code_token" ]; then
    set_env_var CODE_SANDBOX_BROKER_TOKEN "$sandbox_token"
    log "Set CODE_SANDBOX_BROKER_TOKEN to match SANDBOX_BROKER_TOKEN."
  fi

  # Compose requires non-empty values; example placeholders are fine for dev.
  local required_keys=(
    POSTGRES_PASSWORD
    QDRANT_API_KEY
    S3_ACCESS_KEY
    S3_SECRET_KEY
    SEAWEEDFS_ADMIN_PASSWORD
  )
  local key val
  for key in "${required_keys[@]}"; do
    val="$(env_value "$key" || true)"
    if [ -z "$val" ]; then
      die ".env is missing $key. Set it manually or remove .env and re-run install."
    fi
  done

  log ".env is ready for docker compose."
}
