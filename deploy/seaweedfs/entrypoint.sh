#!/bin/sh
# SeaweedFS single-node entrypoint for Alpha Router (weed mini).
# Requires AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (mapped from S3_* in Compose)
# so S3 auth is enabled (never "Allow All").
set -eu

: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID must be set}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY must be set}"
: "${SEAWEEDFS_ADMIN_PASSWORD:?SEAWEEDFS_ADMIN_PASSWORD must be set}"
S3_BUCKET="${S3_BUCKET:-alpha-router-media}"

exec weed mini \
  -dir=/data \
  -admin.dataDir=/data/admin \
  -admin.password="${SEAWEEDFS_ADMIN_PASSWORD}" \
  -bucket="${S3_BUCKET}"
