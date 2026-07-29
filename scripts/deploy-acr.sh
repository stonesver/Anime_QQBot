#!/bin/sh
set -eu

log() {
  printf '[deploy-acr] %s\n' "$*"
}

fail() {
  printf '[deploy-acr] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  printf 'usage: %s [--no-backup] [--refresh-vendors]\n' "$0" >&2
  exit 64
}

skip_backup=0
refresh_vendors=0
for arg in "$@"; do
  case "$arg" in
    --no-backup) skip_backup=1 ;;
    --refresh-vendors) refresh_vendors=1 ;;
    *) usage ;;
  esac
done

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd -P)"
project_dir="$(CDPATH= cd "$script_dir/.." && pwd -P)"
cd "$project_dir"

[ -f compose.yaml ] || fail "compose.yaml not found in $project_dir"
[ -f compose.server-2g.yaml ] || fail "compose.server-2g.yaml not found in $project_dir"
[ -f .env ] || fail ".env not found in $project_dir"
[ -x scripts/backup-postgres.sh ] || fail "scripts/backup-postgres.sh is not executable"

read_env() {
  awk -F= -v key="$1" '
    $0 !~ /^[[:space:]]*#/ && $1 == key {
      value = substr($0, index($0, "=") + 1)
      sub(/\r$/, "", value)
      print value
      exit
    }
  ' .env
}

app_image="${APP_IMAGE:-$(read_env APP_IMAGE)}"
image_tag="${IMAGE_TAG:-$(read_env IMAGE_TAG)}"
postgres_image="${POSTGRES_IMAGE:-$(read_env POSTGRES_IMAGE)}"
napcat_image="${NAPCAT_IMAGE:-$(read_env NAPCAT_IMAGE)}"
compose_file="${COMPOSE_FILE:-$(read_env COMPOSE_FILE)}"
password="$(read_env POSTGRES_PASSWORD)"
token="$(read_env ONEBOT_TOKEN)"

[ -n "$app_image" ] || fail "APP_IMAGE is missing from .env"
[ -n "$image_tag" ] || fail "IMAGE_TAG is missing from .env"
postgres_image="${postgres_image:-${app_image}:vendor-postgres-17.4-alpine}"
napcat_image="${napcat_image:-${app_image}:vendor-napcat-v4.17.50}"
[ "$compose_file" = "compose.yaml:compose.server-2g.yaml" ] ||
  fail "COMPOSE_FILE must be compose.yaml:compose.server-2g.yaml"
[ -n "$password" ] || fail "POSTGRES_PASSWORD is missing from .env"
[ -n "$token" ] || fail "ONEBOT_TOKEN is missing from .env"
case "$app_image" in replace-*|change-me*) fail "APP_IMAGE is still a placeholder" ;; esac
case "$password" in replace-*|change-me*) fail "POSTGRES_PASSWORD is still a placeholder" ;; esac
case "$token" in replace-*|change-me*) fail "ONEBOT_TOKEN is still a placeholder" ;; esac
[ "${#token}" -ge 24 ] || fail "ONEBOT_TOKEN must contain at least 24 characters"
case "$token" in
  *[!A-Za-z0-9._~-]*) fail "ONEBOT_TOKEN may only contain URL-safe characters" ;;
esac

remote_ref="${app_image}:${image_tag}"
rollback_ref="anime-qqbot:rollback"
lock_dir="$project_dir/.deploy-acr.lock"

if ! mkdir "$lock_dir" 2>/dev/null; then
  fail "another deployment is already running; remove $lock_dir only after confirming no deployment process exists"
fi
cleanup_lock() {
  rmdir "$lock_dir" 2>/dev/null || true
}
trap cleanup_lock EXIT

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is not available"
docker compose config --quiet || fail "Compose configuration is invalid"

container_fingerprint() {
  container_id="$1"
  if [ -z "$container_id" ]; then
    printf 'absent\n'
    return
  fi
  docker inspect --format '{{.Id}}|{{.State.StartedAt}}' "$container_id" 2>/dev/null ||
    printf 'unavailable\n'
}

rollback_available=0
deployment_active=0

fail_before_runtime() {
  reason="$1"
  if [ "$rollback_available" = "1" ]; then
    log "restoring the previous application image reference"
    docker image tag "$rollback_ref" "$remote_ref" ||
      fail "$reason; previous image reference could not be restored"
  fi
  fail "$reason"
}

rollback_runtime() {
  if [ "$rollback_available" != "1" ]; then
    printf '[deploy-acr] ERROR: no previous application image is available for rollback\n' >&2
    return 2
  fi
  log "restoring $rollback_ref"
  if ! docker image tag "$rollback_ref" "$remote_ref"; then
    printf '[deploy-acr] ERROR: rollback image tag restore failed\n' >&2
    return 2
  fi
  if ! docker compose up -d --no-build --pull never --no-deps --force-recreate \
    worker astrbot; then
    printf '[deploy-acr] ERROR: rollback runtime recreation failed\n' >&2
    return 2
  fi
  printf '[deploy-acr] ERROR: rollback completed; previous application image is running\n' >&2
}

deployment_failed() {
  reason="$1"
  deployment_active=0
  printf '[deploy-acr] ERROR: %s\n' "$reason" >&2
  if rollback_runtime; then
    exit 1
  fi
  exit 2
}

handle_signal() {
  trap - HUP INT TERM
  printf '[deploy-acr] ERROR: deployment interrupted\n' >&2
  if [ "$deployment_active" = "1" ]; then
    deployment_active=0
    rollback_runtime || true
  fi
  exit 130
}

postgres_container="$(docker compose ps -q postgres 2>/dev/null || true)"
napcat_container="$(docker compose ps -q napcat 2>/dev/null || true)"
napcat_any_container="$(docker compose ps -a -q napcat 2>/dev/null || true)"
napcat_before="$(container_fingerprint "$napcat_any_container")"
log "NapCat container before: $napcat_before"
app_container="$(docker compose ps -q worker 2>/dev/null || true)"
if [ -z "$app_container" ]; then
  app_container="$(docker compose ps -q astrbot 2>/dev/null || true)"
fi

backup_path="skipped"
if [ "$skip_backup" = "0" ] && [ -n "$postgres_container" ]; then
  log "creating PostgreSQL backup"
  backup_path="$(scripts/backup-postgres.sh)" || fail "database backup failed"
fi

if [ -n "$app_container" ]; then
  previous_image="$(docker inspect --format '{{.Image}}' "$app_container")" ||
    fail "cannot inspect the current application image"
  [ -n "$previous_image" ] || fail "cannot determine the current application image"
  log "saving current application image as $rollback_ref"
  docker image tag "$previous_image" "$rollback_ref" ||
    fail "cannot save the rollback image"
  rollback_available=1
else
  log "no previous application image was available"
fi

log "pulling $remote_ref"
if ! docker pull "$remote_ref"; then
  registry="${app_image%%/*}"
  fail "cannot pull $remote_ref; run docker login $registry and retry"
fi

if [ "$refresh_vendors" = "1" ] ||
  ! docker image inspect "$postgres_image" >/dev/null 2>&1; then
  log "pulling fixed PostgreSQL image"
  docker compose pull postgres ||
    fail_before_runtime "cannot pull PostgreSQL image"
else
  log "preserving fixed PostgreSQL image"
fi
if [ "$refresh_vendors" = "1" ] ||
  ! docker image inspect "$napcat_image" >/dev/null 2>&1; then
  log "pulling fixed NapCat image"
  docker compose pull napcat ||
    fail_before_runtime "cannot pull NapCat image"
else
  log "preserving fixed NapCat image"
fi

log "starting PostgreSQL"
docker compose up -d --wait postgres ||
  fail_before_runtime "PostgreSQL did not become healthy"

log "running migrations"
docker compose run --rm --no-deps migrate || fail_before_runtime "migration failed"

deployment_active=1
trap handle_signal HUP INT TERM

log "starting Worker and AstrBot"
if ! docker compose up -d --no-build --pull never --no-deps --wait worker astrbot; then
  deployment_failed "Worker or AstrBot did not become healthy"
fi

if [ -n "$napcat_container" ] && [ "$refresh_vendors" = "1" ]; then
  log "reconciling running NapCat after explicit vendor refresh"
  if ! docker compose up -d --no-build --pull never --no-deps --wait napcat; then
    deployment_failed "NapCat did not become healthy"
  fi
elif [ -n "$napcat_container" ]; then
  log "preserving running NapCat container"
elif [ -n "$napcat_any_container" ]; then
  log "NapCat was stopped before deployment; leaving it stopped"
else
  log "starting NapCat for first deployment"
  if ! docker compose up -d --no-build --pull never --no-deps --wait napcat; then
    deployment_failed "NapCat did not become healthy"
  fi
fi

deployment_active=0
trap - HUP INT TERM

image_id="$(docker image inspect --format '{{.Id}}' "$remote_ref")"
image_digests="$(docker image inspect --format '{{json .RepoDigests}}' "$remote_ref")"
napcat_after_container="$(docker compose ps -a -q napcat 2>/dev/null || true)"
napcat_after="$(container_fingerprint "$napcat_after_container")"
docker compose ps

log "deployment completed"
log "application image: $remote_ref"
log "image ID: $image_id"
log "image digests: $image_digests"
log "database backup: $backup_path"
log "NapCat container after: $napcat_after"
if [ "$napcat_before" = "$napcat_after" ]; then
  log "NapCat restart detected: no"
else
  log "NapCat restart detected: yes"
fi
log "NapCat WebUI tunnel: ssh -L 6099:127.0.0.1:6099 <server>"
log "AstrBot WebUI tunnel: ssh -L 6185:127.0.0.1:6185 <server>"
