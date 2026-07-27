#!/bin/sh
set -eu

# deploy-multisource.sh: deploy the v0.2 AstrBot multi-source anime tracking stack.
#
# Prerequisites:
#   1. Docker + Docker Compose v2 installed.
#   2. .env file with POSTGRES_PASSWORD and ONEBOT_TOKEN set.
#   3. Docker logged into any private image registry (if used).
#
# Usage:
#   ./scripts/deploy-multisource.sh [--no-backup] [--no-build]
#
# The script does NOT touch scripts/deploy-acr.sh.

project_dir="$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)"
cd "$project_dir"

skip_backup=0
skip_build=0
for arg in "$@"; do
  case "$arg" in
    --no-backup) skip_backup=1 ;;
    --no-build) skip_build=1 ;;
  esac
done

log() { printf '[deploy-v02] %s\n' "$*"; }
fail() { printf '[deploy-v02] ERROR: %s\n' "$*" >&2; exit 1; }

[ -f compose.yaml ] || fail "compose.yaml not found"
[ -f .env ] || fail ".env not found"
docker compose config --quiet || fail "compose config invalid"

# 1. Pre-check migrate and worker in compose
if ! docker compose config --services | grep -qFx migrate; then
  fail "migrate service not found in compose"
fi

# 2. Backup
if [ "$skip_backup" = "0" ]; then
  if [ -x scripts/backup-postgres.sh ]; then
    log "creating database backup"
    scripts/backup-postgres.sh || fail "backup failed"
  else
    log "no backup script found; skipping"
  fi
fi

# 3. Build (optional)
if [ "$skip_build" = "0" ]; then
  log "building images"
  docker compose build --pull || fail "build failed"
fi

# 4. Deploy
log "starting postgres and migrate"
docker compose up -d --wait postgres || fail "postgres failed"
docker compose up -d migrate || fail "migrate failed"

# Wait for migration
migrate_cid="$(docker compose ps -q migrate)"
if [ -n "$migrate_cid" ]; then
  migrate_exit="$(docker inspect --format '{{.State.ExitCode}}' "$migrate_cid")"
  [ "$migrate_exit" = "0" ] || fail "migration failed with exit $migrate_exit"
fi

log "starting worker, astrbot, napcat"
docker compose up -d --wait postgres worker astrbot napcat || fail "services failed"

log "deployment completed"
log "check docker compose ps for health status"
log "log into QQ via NapCat at http://127.0.0.1:8082"
