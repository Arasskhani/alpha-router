#!/usr/bin/env bash
# Merge new keys from .env.example into .env without overwriting existing values.

merge_env_from_example() {
  if [ ! -f "$ENV_EXAMPLE" ]; then
    die ".env.example not found."
  fi
  if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    log "Created .env from .env.example."
    return 0
  fi

  local added=0 line key
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '' | \#*)
        continue
        ;;
      *=*)
        key="${line%%=*}"
        if ! grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
          printf '%s\n' "$line" >>"$ENV_FILE"
          added=$((added + 1))
        fi
        ;;
    esac
  done <"$ENV_EXAMPLE"

  if [ "$added" -gt 0 ]; then
    log "Merged $added new key(s) from .env.example into .env."
  else
    log "No new keys to merge from .env.example."
  fi
}
