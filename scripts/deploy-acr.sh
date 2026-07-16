#!/bin/sh
set -eu

default_acr_image="crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot"
acr_image="${ACR_IMAGE:-$default_acr_image}"
acr_image_tag="${ACR_IMAGE_TAG:-latest}"
local_image="${LOCAL_IMAGE:-anime-qqbot}"
local_image_tag="${LOCAL_IMAGE_TAG:-latest}"
rollback_image_tag="${ROLLBACK_IMAGE_TAG:-rollback}"
deploy_timeout="${DEPLOY_TIMEOUT_SECONDS:-120}"
skip_backup="${SKIP_BACKUP:-0}"

remote_ref="${acr_image}:${acr_image_tag}"
local_ref="${local_image}:${local_image_tag}"
rollback_ref="${local_image}:${rollback_image_tag}"

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

wait_healthy() {
  service="$1"
  started_at="$(date +%s)"
  while :; do
    if ! container="$(docker compose ps -q "$service")"; then
      return 1
    fi
    [ -n "$container" ] || return 1
    if ! state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")"; then
      return 1
    fi
    case "$state" in
      healthy) return 0 ;;
      unhealthy|exited|dead) return 1 ;;
    esac
    now="$(date +%s)"
    [ $((now - started_at)) -lt "$deploy_timeout" ] || return 1
    sleep 2
  done
}

rollback() {
  printf '[deploy] ERROR: attempting application rollback\n' >&2
  if ! docker image tag "$rollback_ref" "$local_ref"; then
    printf '[deploy] ERROR: rollback failed while restoring image tag\n' >&2
    return 1
  fi
  if ! docker compose up -d --no-build --no-deps --force-recreate bot worker; then
    printf '[deploy] ERROR: rollback failed while recreating services\n' >&2
    return 1
  fi
  if ! wait_healthy bot || ! wait_healthy worker; then
    printf '[deploy] ERROR: rollback services did not become healthy\n' >&2
    return 1
  fi
  printf '[deploy] ERROR: rollback completed; previous application image is running\n' >&2
}

deployment_failed() {
  reason="$1"
  deployment_active=0
  printf '[deploy] ERROR: new version deployment failed: %s\n' "$reason" >&2
  if rollback; then
    exit 1
  fi
  exit 2
}

handle_signal() {
  trap - HUP INT TERM
  printf '[deploy] ERROR: deployment interrupted\n' >&2
  if [ "$deployment_active" = "1" ]; then
    deployment_active=0
    rollback || true
  fi
  exit 130
}

case "$deploy_timeout" in
  ''|*[!0-9]*) fail "DEPLOY_TIMEOUT_SECONDS must be a positive integer" ;;
esac
[ "$deploy_timeout" -gt 0 ] || fail "DEPLOY_TIMEOUT_SECONDS must be a positive integer"
[ "$skip_backup" = "0" ] || [ "$skip_backup" = "1" ] || fail "SKIP_BACKUP must be 0 or 1"

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd -P)"
project_dir="$(CDPATH= cd "$script_dir/.." && pwd -P)"
cd "$project_dir"

lock_dir="$project_dir/.deploy-acr.lock"
if ! mkdir "$lock_dir" 2>/dev/null; then
  fail "another deployment is already running; remove $lock_dir only if no deployment process exists"
fi
cleanup_lock() {
  rmdir "$lock_dir" 2>/dev/null || true
}
trap cleanup_lock EXIT

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is not available"
[ -f compose.yaml ] || fail "compose.yaml not found in $project_dir"
[ -f .env ] || fail ".env not found in $project_dir"
[ -x scripts/backup-postgres.sh ] || fail "scripts/backup-postgres.sh is not executable"

docker compose config --quiet || fail "docker compose configuration is invalid"
docker compose config --images | grep -F -x "$local_ref" >/dev/null 2>&1 ||
  fail "Compose does not use $local_ref; set IMAGE_TAG=$local_image_tag in .env"

if ! current_bot="$(docker compose ps -q bot)"; then
  fail "cannot inspect the current bot container"
fi
[ -n "$current_bot" ] || fail "bot container is not running; cannot prepare rollback image"
if ! previous_image="$(docker inspect --format '{{.Image}}' "$current_bot")"; then
  fail "cannot inspect the current bot image"
fi
[ -n "$previous_image" ] || fail "cannot determine the current bot image"

backup_path="skipped"
if [ "$skip_backup" = "0" ]; then
  log "creating PostgreSQL backup"
  if ! backup_path="$(scripts/backup-postgres.sh)"; then
    fail "database backup failed"
  fi
fi

log "saving current image as $rollback_ref"
docker image tag "$previous_image" "$rollback_ref" || fail "cannot save rollback image"

log "pulling $remote_ref"
if ! docker pull "$remote_ref"; then
  registry="${acr_image%%/*}"
  fail "cannot pull $remote_ref; run docker login $registry and retry"
fi

log "tagging new image as $local_ref"
docker image tag "$remote_ref" "$local_ref" || fail "cannot tag the new image"

deployment_active=1
trap handle_signal HUP INT TERM

log "recreating migrate, bot, and worker"
if ! docker compose up -d --no-build --force-recreate migrate bot worker; then
  deployment_failed "docker compose deployment command failed"
fi

if ! migrate_container="$(docker compose ps -a -q migrate)"; then
  deployment_failed "cannot inspect the migrate container"
fi
[ -n "$migrate_container" ] || deployment_failed "migrate container was not created"
if ! migrate_exit="$(docker inspect --format '{{.State.ExitCode}}' "$migrate_container")"; then
  deployment_failed "cannot inspect the migrate exit code"
fi
[ "$migrate_exit" = "0" ] || deployment_failed "migration failed with exit code $migrate_exit"

log "waiting for bot and worker health checks"
wait_healthy bot || deployment_failed "bot did not become healthy within ${deploy_timeout}s"
wait_healthy worker || deployment_failed "worker did not become healthy within ${deploy_timeout}s"

deployment_active=0
trap - HUP INT TERM

log "deployment completed"
log "previous image: $previous_image"
log "current image: $remote_ref"
log "database backup: $backup_path"
